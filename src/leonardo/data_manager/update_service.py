"""Read-only reconciliation and explicit Data Manager update execution."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from leonardo.artifacts import (
    ArtifactError,
    ArtifactLineageError,
    ArtifactMetadataV1,
    ArtifactRecipeV1,
    ArtifactService,
    ArtifactSourceRefV1,
    ManagedArtifactVersionKey,
    OHLCVSourceFingerprintV1,
)
from leonardo.data import MarketId
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    UpdateStrategy,
    get_financial_tool_spec,
    resolve_output_signals,
)
from leonardo.financial_tools.construct_input_eligibility import (
    FinancialToolInputCompatibilityError,
    FinancialToolInputSource,
    validate_financial_tool_inputs,
)
from leonardo.research.catalog import AcceptedDatasetCatalog, AcceptedDatasetSummary
from leonardo.research.dataset import HistoricalDatasetLoader

from .artifact_materialization import (
    ArtifactMaterializationValidationError,
    _calculate_artifact_recipe,
    _dataset_frame,
)
from .creation_models import (
    ArtifactCollectionDependencyV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    DatabaseCollectionReferenceV2,
    DatabaseDefinitionV1,
    DatabaseRevisionManifest,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DataManagerCreationError,
    deterministic_hash,
)
from .creation_service import DataManagerCreationWorkflow
from .models import (
    DataManagerArtifactMaterializationResult,
    DataManagerManagedArtifactEntry,
    DataManagerOperationError,
)
from .update_models import (
    ArtifactCollectionUpdatePlan,
    ArtifactCollectionUpdateResult,
    ArtifactUpdateNodePlan,
    DataManagerArtifactCurrentness,
    DataManagerCollectionCurrentness,
    DataManagerDatabaseCurrentness,
    DataManagerReconciliationSnapshot,
    DataManagerSourceChange,
    DatabaseUpdatePlan,
    DatabaseUpdateResult,
)


_NUMERIC_ATOL = 0.00005


def _market_key(market: MarketId) -> tuple[str, str, str, str]:
    return (market.exchange, market.market_type, market.symbol, market.timeframe)


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _hash_payload(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _source_payload(source: OHLCVSourceFingerprintV1 | None) -> object:
    return None if source is None else source.to_dict()


class DataManagerUpdateWorkflow:
    """Coordinate canonical update planning and explicit immutable publication."""

    def __init__(
        self,
        catalog: AcceptedDatasetCatalog,
        loader: HistoricalDatasetLoader,
        artifacts: ArtifactService,
        creation: DataManagerCreationWorkflow,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._loader = loader
        self._artifacts = artifacts
        self._creation = creation
        self._clock = clock or (lambda: datetime.now(UTC))
        self._snapshot: DataManagerReconciliationSnapshot | None = None
        self._invalidated = True

    def invalidate(self) -> None:
        self._invalidated = True

    def cached_snapshot(self) -> DataManagerReconciliationSnapshot | None:
        return self._snapshot

    def latest_snapshot(self) -> DataManagerReconciliationSnapshot:
        return self.reconcile_all(force=False)

    def reconcile_all(
        self,
        *,
        force: bool = False,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> DataManagerReconciliationSnapshot:
        cancelled = cancellation_requested or (lambda: False)
        self._check_reconciliation_cancelled(cancelled, "before catalog scanning")
        report = self._catalog.scan()
        accepted_summaries = {
            item.market_id: item for item in report.accepted
        }
        failures = [
            f"{item.market_id.as_key() if item.market_id else item.dataset_dir}: {item.reason}"
            for item in report.rejected
        ]

        self._check_reconciliation_cancelled(cancelled, "before managed-market discovery")
        known_markets = set(accepted_summaries)
        known_markets.update(self._artifacts.list_managed_markets())

        collections_by_id: dict[str, ArtifactCollectionRevisionV1] = {}
        collection_evidence: list[tuple[str, str]] = []
        for collection_id in self._creation.store.list_collection_ids():
            try:
                collection = self._creation.load_artifact_collection(collection_id)
                collections_by_id[collection_id] = collection
                collection_evidence.append((collection_id, collection.revision_id))
                known_markets.add(collection.market_id)
            except (DataManagerCreationError, OSError, ValueError) as exc:
                failures.append(f"Collection {collection_id}: {exc}")
                collection_evidence.append((collection_id, str(exc)))

        database_revisions = {}
        database_evidence: list[tuple[str, str]] = []
        for database_id in self._creation.store.list_database_ids():
            try:
                loaded = self._creation.load_database_revision(database_id)
                database_revisions[database_id] = loaded
                database_evidence.append((database_id, loaded.manifest.revision_id))
                known_markets.add(loaded.manifest.market_id)
            except (DataManagerCreationError, OSError, ValueError) as exc:
                failures.append(f"Database {database_id}: {exc}")
                database_evidence.append((database_id, str(exc)))

        sources: dict[MarketId, OHLCVSourceFingerprintV1] = {}
        source_errors: dict[MarketId, str] = {}
        for market in sorted(accepted_summaries, key=_market_key):
            self._check_reconciliation_cancelled(cancelled, "before source capture")
            try:
                sources[market] = self._artifacts.capture_accepted_source(market)
            except (ArtifactError, OSError, ValueError) as exc:
                source_errors[market] = str(exc)
                failures.append(f"{market.as_key()}: {exc}")

        managed_by_market = {}
        for market in sorted(known_markets, key=_market_key):
            self._check_reconciliation_cancelled(cancelled, "before managed-market scan")
            managed_by_market[market] = self._artifacts.list_managed_artifacts(market)

        previous_by_market: dict[MarketId, OHLCVSourceFingerprintV1] = {}
        for market in sorted(managed_by_market, key=_market_key):
            for item in managed_by_market[market]:
                self._check_reconciliation_cancelled(cancelled, "before Artifact")
                if not item.valid:
                    continue
                try:
                    previous_by_market.setdefault(
                        market,
                        self._artifacts.load_artifact_by_id(
                            market, item.artifact_id
                        ).metadata.source_ohlcv,
                    )
                except (ArtifactError, OSError, ValueError):
                    pass
        for collection in collections_by_id.values():
            previous_by_market.setdefault(collection.market_id, collection.source_ohlcv)
        for loaded in database_revisions.values():
            previous_by_market.setdefault(
                loaded.manifest.market_id, loaded.manifest.source_ohlcv
            )

        source_changes = tuple(
            self._classify_captured_source(
                previous_by_market.get(market, sources.get(market)),
                market,
                sources.get(market),
                accepted_summaries.get(market),
                cancelled,
                source_error=source_errors.get(market),
            )
            for market in sorted(known_markets, key=_market_key)
        )
        changes_by_market = {item.market_id: item for item in source_changes}
        signature = self._evidence_signature(
            accepted_summaries,
            sources,
            source_errors,
            managed_by_market,
            collection_evidence,
            database_evidence,
        )
        if (
            not force
            and not self._invalidated
            and self._snapshot is not None
            and self._snapshot.evidence_signature == signature
        ):
            return self._snapshot
        artifacts = self._reconcile_artifacts(
            sources,
            accepted_summaries,
            managed_by_market,
            failures,
            cancelled,
        )
        artifact_by_logical = {
            item.logical_artifact_id: item for item in artifacts
        }
        collections = self._reconcile_collections(
            sources,
            artifact_by_logical,
            collections_by_id,
            failures,
            cancelled,
        )
        collection_by_id = {item.collection_id: item for item in collections}
        databases = self._reconcile_databases(
            collection_by_id,
            collections_by_id,
            database_revisions,
            changes_by_market,
            accepted_summaries,
            managed_by_market,
            failures,
            cancelled,
        )
        self._check_reconciliation_cancelled(cancelled, "before publishing snapshot")
        snapshot = DataManagerReconciliationSnapshot(
            created_at_utc=self._clock(),
            source_changes=source_changes,
            artifacts=artifacts,
            collections=collections,
            databases=databases,
            failures=tuple(failures),
            evidence_signature=signature,
        )
        self._snapshot = snapshot
        self._invalidated = False
        return snapshot

    def classify_source_change(
        self,
        previous_source: OHLCVSourceFingerprintV1,
        market_id: MarketId | None = None,
    ) -> DataManagerSourceChange:
        if not isinstance(previous_source, OHLCVSourceFingerprintV1):
            raise TypeError("previous_source must be an OHLCVSourceFingerprintV1")
        market = previous_source.market_id if market_id is None else market_id
        if not isinstance(market, MarketId):
            raise TypeError("market_id must be a MarketId")
        summary = self._accepted_summary(market)
        current = None
        source_error = None
        try:
            if summary is not None:
                current = self._artifacts.capture_accepted_source(market)
        except (ArtifactError, OSError, ValueError) as exc:
            source_error = str(exc)
        return self._classify_captured_source(
            previous_source,
            market,
            current,
            summary,
            lambda: False,
            source_error=source_error,
        )

    def _classify_captured_source(
        self,
        previous_source: OHLCVSourceFingerprintV1 | None,
        market: MarketId,
        current: OHLCVSourceFingerprintV1 | None,
        summary: AcceptedDatasetSummary | None,
        cancellation_requested: Callable[[], bool],
        *,
        source_error: str | None = None,
    ) -> DataManagerSourceChange:
        if previous_source is not None and previous_source.market_id != market:
            return DataManagerSourceChange(
                market,
                "IDENTITY_MISMATCH",
                previous_source,
                current,
                previous_source.last_timestamp_ms,
                None if current is None else current.last_timestamp_ms,
                0 if current is None else max(0, current.row_count - previous_source.row_count),
                "previous source MarketId differs from requested MarketId",
            )
        if current is None or summary is None:
            reason = "current accepted OHLCV source is unavailable or rejected"
            if source_error is not None:
                reason = f"current accepted OHLCV source is invalid: {source_error}"
            return DataManagerSourceChange(
                market,
                "INVALID_SOURCE",
                previous_source,
                None,
                None if previous_source is None else previous_source.last_timestamp_ms,
                None,
                0,
                reason,
            )
        if previous_source is None:
            previous_source = current
        missing = max(0, current.row_count - previous_source.row_count)
        if current.market_id != previous_source.market_id:
            status, reason = "IDENTITY_MISMATCH", "current source MarketId differs"
        elif (
            current.row_count < previous_source.row_count
            or current.last_timestamp_ms < previous_source.last_timestamp_ms
            or current.first_timestamp_ms > previous_source.first_timestamp_ms
        ):
            status, reason = "TRUNCATED", "current source coverage is shorter"
        elif current == previous_source:
            status, reason = "UNCHANGED", "complete source fingerprint is unchanged"
        elif current.row_count > previous_source.row_count and self._prefix_matches(
            summary.csv_path, previous_source, cancellation_requested
        ):
            status, reason = "APPEND_ONLY", "exact accepted CSV prefix is unchanged"
        else:
            status, reason = (
                "HISTORICAL_MUTATION",
                "accepted source evidence differs without an exact append-only prefix",
            )
        return DataManagerSourceChange(
            market,
            status,
            previous_source,
            current,
            previous_source.last_timestamp_ms,
            current.last_timestamp_ms,
            missing,
            reason,
        )

    @staticmethod
    def _incoming_collection_edges(
        collection: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2,
    ) -> dict[str, tuple[ArtifactCollectionDependencyV1, ...]]:
        incoming: dict[str, list[ArtifactCollectionDependencyV1]] = {
            member.version_key.logical_artifact_id: []
            for member in collection.members
        }
        seen: set[tuple[str, str, str, str]] = set()
        for edge in collection.dependency_edges:
            signature = (
                edge.dependency_logical_artifact_id,
                edge.dependent_logical_artifact_id,
                edge.role,
                edge.output_name,
            )
            if signature in seen:
                raise DataManagerOperationError(
                    "Artifact Collection dependency edges must be unique"
                )
            seen.add(signature)
            incoming[edge.dependent_logical_artifact_id].append(edge)
        return {key: tuple(value) for key, value in incoming.items()}

    @classmethod
    def _artifact_execution_stages(
        cls, collection: ArtifactCollectionRevisionV1
    ) -> tuple[tuple[str, ...], ...]:
        incoming = cls._incoming_collection_edges(collection)
        member_order = {
            member.version_key.logical_artifact_id: index
            for index, member in enumerate(collection.members)
        }
        indegree = {logical_id: len(edges) for logical_id, edges in incoming.items()}
        dependents: dict[str, list[str]] = {logical_id: [] for logical_id in indegree}
        for edge in collection.dependency_edges:
            dependents[edge.dependency_logical_artifact_id].append(
                edge.dependent_logical_artifact_id
            )
        ready = tuple(
            sorted(
                (logical_id for logical_id, count in indegree.items() if count == 0),
                key=member_order.__getitem__,
            )
        )
        stages: list[tuple[str, ...]] = []
        consumed: set[str] = set()
        while ready:
            stages.append(ready)
            next_ready: set[str] = set()
            for logical_id in ready:
                consumed.add(logical_id)
                for dependent_id in dependents[logical_id]:
                    indegree[dependent_id] -= 1
                    if indegree[dependent_id] == 0:
                        next_ready.add(dependent_id)
            ready = tuple(sorted(next_ready, key=member_order.__getitem__))
        if consumed != set(member_order):
            raise DataManagerOperationError(
                "Artifact Collection dependency graph cannot be completely ordered"
            )
        return tuple(stages)

    def _load_and_prove_member_artifact(
        self,
        collection: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2,
        member,
        summary,
        members: Mapping[str, object],
        incoming_edges: Sequence[ArtifactCollectionDependencyV1],
    ):
        logical_id = member.version_key.logical_artifact_id
        if summary.logical_artifact_id != logical_id:
            raise DataManagerOperationError(
                "managed Artifact logical identity disagrees with Collection member"
            )
        if summary.portable_recipe_id != member.portable_recipe_id:
            raise DataManagerOperationError(
                "managed Artifact semantic signature disagrees with Collection member"
            )
        if (
            summary.tool_key != member.tool_key
            or summary.kind != member.kind
            or summary.output_names != member.output_names
        ):
            raise DataManagerOperationError(
                "managed Artifact specification disagrees with Collection member"
            )
        version = self._artifacts.load_artifact_version(
            collection.market_id, logical_id, summary.artifact_id
        )
        if version.portable_recipe_id != member.portable_recipe_id:
            raise DataManagerOperationError(
                "managed Artifact version semantic signature disagrees"
            )
        loaded = self._artifacts.load_artifact_by_id(
            collection.market_id, summary.artifact_id
        )
        recipe = loaded.metadata.recipe
        if (
            loaded.metadata.artifact_id != summary.artifact_id
            or recipe.market_id != collection.market_id
            or recipe.tool_key != member.tool_key
            or recipe.kind != member.kind
            or recipe.output_names != member.output_names
        ):
            raise DataManagerOperationError(
                "Artifact-owned calculation metadata disagrees with Collection member"
            )
        refs_by_role = {ref.role: ref for ref in recipe.source_artifacts}
        edges_by_role = {edge.role: edge for edge in incoming_edges}
        if len(edges_by_role) != len(incoming_edges):
            raise DataManagerOperationError(
                "Artifact Collection dependency roles must be unique per dependent"
            )
        if set(refs_by_role) != set(edges_by_role):
            raise DataManagerOperationError(
                "Artifact source references do not match Collection dependency roles"
            )
        dependency_sources: list[FinancialToolInputSource] = []
        for role, edge in edges_by_role.items():
            ref = refs_by_role[role]
            if ref.output_name != edge.output_name:
                raise DataManagerOperationError(
                    "Artifact source output disagrees with Collection dependency edge"
                )
            dependency_member = members[edge.dependency_logical_artifact_id]
            source_version = self._artifacts.load_artifact_version(
                collection.market_id,
                edge.dependency_logical_artifact_id,
                ref.artifact_id,
            )
            if source_version.portable_recipe_id != dependency_member.portable_recipe_id:
                raise DataManagerOperationError(
                    "Artifact source version belongs to another semantic lineage"
                )
            source = self._artifacts.load_artifact_by_id(
                collection.market_id, ref.artifact_id
            )
            if (
                source.metadata.recipe.market_id != collection.market_id
                or source.metadata.recipe.tool_key != dependency_member.tool_key
                or source.metadata.recipe.kind != dependency_member.kind
                or source.metadata.recipe.output_names != dependency_member.output_names
                or ref.output_name not in source.metadata.recipe.output_names
            ):
                raise DataManagerOperationError(
                    "Artifact source metadata disagrees with dependency lineage"
                )
            source_recipe = source.metadata.recipe
            naming = dict(source_recipe.parameters)
            naming.update(source_recipe.bindings)
            signal = next(
                (
                    item
                    for item in resolve_output_signals(source_recipe.tool_key, naming)
                    if item.name == ref.output_name
                ),
                None,
            )
            if signal is None:
                raise DataManagerOperationError(
                    "Artifact source output metadata is unavailable"
                )
            dependency_sources.append(
                FinancialToolInputSource(
                    role,
                    source_recipe.kind,
                    ref.output_name,
                    True,
                    source_recipe.tool_key,
                    edge.dependency_logical_artifact_id,
                    signal.analysis_usable,
                    signal.value_type,
                )
            )
        try:
            validate_financial_tool_inputs(
                get_financial_tool_spec(recipe.tool_key),
                dependency_sources,
                parameters=recipe.parameters,
                allow_partial_roles=True,
                family_scope="dependencies",
            )
        except FinancialToolInputCompatibilityError as exc:
            raise DataManagerOperationError(str(exc)) from exc
        return loaded

    def _resolve_database_members(
        self,
        content: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2,
        current_source: OHLCVSourceFingerprintV1,
        managed_summaries: Sequence[object],
    ) -> tuple[tuple[ArtifactCollectionMemberV1, ...], dict[str, str]]:
        if not content.members:
            return (), {}
        summaries: dict[str, list[object]] = {}
        for summary in managed_summaries:
            summaries.setdefault(summary.logical_artifact_id, []).append(summary)
        members = {
            item.version_key.logical_artifact_id: item for item in content.members
        }
        incoming = self._incoming_collection_edges(content)
        resolved: list[ArtifactCollectionMemberV1] = []
        heads: dict[str, str] = {}
        for member in content.members:
            logical_id = member.version_key.logical_artifact_id
            candidates = tuple(summaries.get(logical_id, ()))
            if len(candidates) != 1 or not candidates[0].valid:
                raise DataManagerOperationError(
                    "required managed Artifact head is unavailable"
                )
            summary = candidates[0]
            loaded = self._load_and_prove_member_artifact(
                content, member, summary, members, incoming[logical_id]
            )
            if loaded.metadata.source_ohlcv != current_source:
                raise DataManagerOperationError(
                    "required managed Artifact is stale for current OHLCV"
                )
            heads[logical_id] = summary.artifact_id
            resolved.append(replace(
                member,
                version_key=ManagedArtifactVersionKey(logical_id, summary.artifact_id),
                values_sha256=loaded.metadata.values_sha256,
            ))
        return tuple(resolved), heads

    def plan_artifact_collection_update(
        self, collection_id: str
    ) -> ArtifactCollectionUpdatePlan:
        try:
            collection = self._creation.load_artifact_collection(collection_id)
            source_change = self.classify_source_change(
                collection.source_ohlcv, collection.market_id
            )
            members = {
                member.version_key.logical_artifact_id: member
                for member in collection.members
            }
            logical_stages = self._artifact_execution_stages(collection)
            member_order = tuple(
                logical_id for stage in logical_stages for logical_id in stage
            )
            roots = tuple(
                members[logical_id].portable_recipe_id
                for logical_id in collection.root_logical_artifact_ids
            )
            member_recipe_ids = tuple(
                members[logical_id].portable_recipe_id for logical_id in member_order
            )
            execution_stages = tuple(
                tuple(members[logical_id].portable_recipe_id for logical_id in stage)
                for stage in logical_stages
            )
            managed_by_logical: dict[str, list[object]] = {}
            for item in self._artifacts.list_managed_artifacts(collection.market_id):
                managed_by_logical.setdefault(item.logical_artifact_id, []).append(item)
            incoming = self._incoming_collection_edges(collection)
            root_set = set(collection.root_logical_artifact_ids)
            node_by_logical: dict[str, ArtifactUpdateNodePlan] = {}
            nodes: list[ArtifactUpdateNodePlan] = []
            plan_blockers: list[str] = []
            current_source = source_change.current_source
            for logical_id in member_order:
                member = members[logical_id]
                summaries = tuple(managed_by_logical.get(logical_id, ()))
                summary = summaries[0] if len(summaries) == 1 else None
                blockers: list[str] = []
                edges = incoming[logical_id]
                dependency_ids = tuple(dict.fromkeys(
                    edge.dependency_logical_artifact_id for edge in edges
                ))
                if len(summaries) > 1:
                    blockers.append("managed Artifact head is not unique")
                for dependency_id in dependency_ids:
                    dependency_node = node_by_logical.get(dependency_id)
                    if dependency_node is None or dependency_node.action == "BLOCKED":
                        blockers.append("dependency update is blocked")
                current_artifact_id = None
                loaded = None
                if summary is None or not summary.valid:
                    if len(summaries) <= 1:
                        blockers.append(
                            "managed Artifact is unavailable"
                            if summary is None
                            else summary.rejection_reason
                        )
                else:
                    current_artifact_id = summary.artifact_id
                    try:
                        loaded = self._load_and_prove_member_artifact(
                            collection, member, summary, members, edges
                        )
                    except (ArtifactError, DataManagerOperationError, KeyError, ValueError) as exc:
                        blockers.append(str(exc))
                recipe = None if loaded is None else loaded.metadata.recipe
                if recipe is not None and recipe.tool_key == "dynamic_binning":
                    blockers.append("dynamic_binning cannot be materialized")
                action = "UPDATE"
                if blockers or current_source is None:
                    if current_source is None:
                        blockers.append("accepted OHLCV source is unavailable")
                    action = "BLOCKED"
                elif loaded is not None:
                    current_refs = {ref.role: ref for ref in loaded.metadata.recipe.source_artifacts}
                    dependencies_reused = all(
                        node_by_logical[dependency_id].action == "REUSE_CURRENT"
                        for dependency_id in dependency_ids
                    )
                    refs_are_current = all(
                        current_refs[edge.role].artifact_id
                        == node_by_logical[
                            edge.dependency_logical_artifact_id
                        ].current_artifact_id
                        for edge in edges
                    )
                    if (
                        loaded.metadata.source_ohlcv == current_source
                        and dependencies_reused
                        and refs_are_current
                    ):
                        action = "REUSE_CURRENT"
                policy = get_financial_tool_spec(member.tool_key).update_policy
                try:
                    context = policy.effective_context_rows(
                        {} if recipe is None else recipe.parameters
                    )
                except (TypeError, ValueError) as exc:
                    blockers.append(str(exc))
                    context = 0
                    action = "BLOCKED"
                node = ArtifactUpdateNodePlan(
                    portable_recipe_id=member.portable_recipe_id,
                    logical_artifact_id=logical_id,
                    tool_key=member.tool_key,
                    role="ROOT" if logical_id in root_set else "SUPPORT",
                    action=action,
                    current_artifact_id=current_artifact_id,
                    dependency_logical_artifact_ids=dependency_ids,
                    update_strategy=policy.strategy,
                    context_rows=context,
                    revisable_tail_rows=policy.revisable_tail_rows,
                    blockers=tuple(blockers),
                )
                nodes.append(node)
                node_by_logical[logical_id] = node
                plan_blockers.extend(
                    f"{member.portable_recipe_id}: {value}" for value in blockers
                )
            starting_heads = tuple(
                (node.logical_artifact_id, node.current_artifact_id)
                for node in nodes
                if node.current_artifact_id is not None
            )
            payload = {
                "schema": "data_manager_artifact_collection_update_plan_v1",
                "collection_id": collection.collection_id,
                "collection_revision_id": collection.revision_id,
                "source": _source_payload(current_source),
                "source_status": source_change.status,
                "roots": list(roots),
                "members": list(member_recipe_ids),
                "heads": [list(value) for value in sorted(starting_heads)],
                "stages": [list(value) for value in execution_stages],
                "nodes": [
                    {
                        "recipe_id": node.portable_recipe_id,
                        "logical_id": node.logical_artifact_id,
                        "action": node.action,
                        "strategy": node.update_strategy.value,
                        "context": node.context_rows,
                        "tail": node.revisable_tail_rows,
                        "blockers": list(node.blockers),
                    }
                    for node in nodes
                ],
            }
            return ArtifactCollectionUpdatePlan(
                plan_id=_hash_payload(payload),
                collection_id=collection.collection_id,
                collection_revision_id=collection.revision_id,
                market_id=collection.market_id,
                source_change=source_change,
                source_ohlcv=current_source,
                root_recipe_ids=roots,
                member_recipe_ids=member_recipe_ids,
                root_logical_artifact_ids=collection.root_logical_artifact_ids,
                support_logical_artifact_ids=collection.support_logical_artifact_ids,
                starting_artifact_heads=starting_heads,
                execution_stages=execution_stages,
                nodes=tuple(nodes),
                blockers=tuple(plan_blockers),
            )
        except (
            ArtifactError,
            DataManagerCreationError,
            ArtifactMaterializationValidationError,
            FileNotFoundError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, DataManagerOperationError):
                raise
            raise DataManagerOperationError(str(exc)) from exc

    def execute_artifact_collection_update(
        self,
        plan: ArtifactCollectionUpdatePlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionUpdateResult:
        if not isinstance(plan, ArtifactCollectionUpdatePlan):
            raise TypeError("plan must be an ArtifactCollectionUpdatePlan")
        if plan.blocked:
            raise DataManagerOperationError("blocked Artifact Collection update plan cannot execute")
        cancelled = cancellation_requested or (lambda: False)
        fresh = self.plan_artifact_collection_update(plan.collection_id)
        if fresh != plan:
            raise DataManagerOperationError("Artifact Collection update plan is stale")
        if cancelled():
            raise DataManagerOperationError("Artifact Collection update cancelled")
        if plan.source_ohlcv is None:
            raise DataManagerOperationError("accepted OHLCV source is unavailable")
        try:
            dataset = self._loader.load(
                plan.market_id, cancellation_requested=cancelled
            )
            target_frame = _dataset_frame(dataset)
            collection = self._creation.load_artifact_collection(plan.collection_id)
            incoming = self._incoming_collection_edges(collection)
            nodes = {node.logical_artifact_id: node for node in plan.nodes}
            logical_by_recipe = {
                node.portable_recipe_id: node.logical_artifact_id for node in plan.nodes
            }
            recipes: dict[str, ArtifactRecipeV1] = {}
            frames: dict[str, pd.DataFrame] = {}
            metadata: dict[str, ArtifactMetadataV1] = {}
            artifact_ids: dict[str, str] = {}
            calculations: dict[str, FinancialToolCalculationResult] = {}
            operation_time = self._clock()
            for stage in plan.execution_stages:
                for recipe_id in stage:
                    if cancelled():
                        raise DataManagerOperationError(
                            "Artifact Collection update cancelled"
                        )
                    logical_id = logical_by_recipe[recipe_id]
                    node = nodes[logical_id]
                    loaded = self._artifacts.load_artifact_by_id(
                        plan.market_id, node.current_artifact_id
                    )
                    recipes[logical_id] = loaded.metadata.recipe
                    if node.action == "REUSE_CURRENT":
                        if node.current_artifact_id is None:
                            raise DataManagerOperationError("reused node has no Artifact")
                        frames[logical_id] = loaded.frame
                        metadata[logical_id] = loaded.metadata
                        artifact_ids[logical_id] = node.current_artifact_id
                        continue
                    recipe = recipes[logical_id]
                    result = self._calculate_updated_node(
                        recipe,
                        node,
                        plan.source_change,
                        target_frame,
                        frames,
                        incoming[logical_id],
                    )
                    calculations[logical_id] = result
                    frames[logical_id] = result.to_frame()
            prepared = []
            for recipe_id in plan.member_recipe_ids:
                logical_id = logical_by_recipe[recipe_id]
                node = nodes[logical_id]
                if node.action == "REUSE_CURRENT":
                    continue
                refs = tuple(
                    ArtifactSourceRefV1(
                        edge.role,
                        artifact_ids[edge.dependency_logical_artifact_id],
                        edge.output_name,
                    )
                    for edge in incoming[logical_id]
                )
                source_metadata = tuple({
                    metadata[edge.dependency_logical_artifact_id].artifact_id:
                    metadata[edge.dependency_logical_artifact_id]
                    for edge in incoming[logical_id]
                }.values())
                candidate = self._artifacts.prepare_managed_calculation(
                    plan.market_id,
                    recipe_id,
                    calculations[logical_id],
                    expected_source=plan.source_ohlcv,
                    source_artifacts=refs,
                    source_metadata=source_metadata,
                    previous_artifact_id=node.current_artifact_id,
                    created_at_utc=operation_time,
                )
                prepared.append(candidate)
                artifact_ids[logical_id] = candidate.metadata.artifact_id
                metadata[logical_id] = candidate.metadata
            if cancelled():
                raise DataManagerOperationError("Artifact Collection update cancelled")
            if prepared:
                publication = self._artifacts.publish_managed_artifact_graph(
                    tuple(prepared),
                    expected_source=plan.source_ohlcv,
                    before_publish=before_publish,
                )
                created_ids = publication.created_artifact_ids
                reused_ids = publication.reused_artifact_ids
                created_keys = publication.created_version_keys
                reused_keys = publication.reused_version_keys
                advanced_ids = publication.advanced_logical_artifact_ids
            else:
                created_ids = ()
                reused_ids = tuple(artifact_ids.values())
                created_keys = ()
                reused_keys = tuple(
                    ManagedArtifactVersionKey(key, value)
                    for key, value in artifact_ids.items()
                )
                advanced_ids = ()
            current = {
                item.logical_artifact_id: item
                for item in self._artifacts.list_managed_artifacts(plan.market_id)
            }
            entries = tuple(
                self._managed_entry(current[logical_by_recipe[recipe_id]])
                for recipe_id in plan.member_recipe_ids
            )
            materialization = DataManagerArtifactMaterializationResult(
                plan_id=plan.plan_id,
                target_market_id=plan.market_id,
                source_ohlcv=plan.source_ohlcv,
                root_logical_artifact_ids=plan.root_logical_artifact_ids,
                support_logical_artifact_ids=plan.support_logical_artifact_ids,
                created_artifact_ids=tuple(created_ids),
                reused_artifact_ids=tuple(
                    dict.fromkeys(
                        (*reused_ids, *(
                            artifact_ids[logical_by_recipe[key]]
                            for key in plan.member_recipe_ids
                            if nodes[logical_by_recipe[key]].action == "REUSE_CURRENT"
                        ))
                    )
                ),
                created_version_keys=tuple(created_keys),
                reused_version_keys=tuple(
                    dict.fromkeys(
                        (*reused_keys, *(
                            ManagedArtifactVersionKey(
                                logical_by_recipe[key], artifact_ids[logical_by_recipe[key]]
                            )
                            for key in plan.member_recipe_ids
                            if nodes[logical_by_recipe[key]].action == "REUSE_CURRENT"
                        ))
                    )
                ),
                advanced_logical_artifact_ids=tuple(advanced_ids),
                managed_artifacts=entries,
            )
            if prepared:
                collection = self._creation.advance_artifact_collection(
                    plan.collection_id, materialization
                )
            else:
                collection = self._creation.load_artifact_collection(plan.collection_id)
            self.invalidate()
            snapshot = self.reconcile_all(force=True)
            return ArtifactCollectionUpdateResult(
                plan.plan_id, materialization, collection, snapshot
            )
        except DataManagerOperationError:
            raise
        except (
            ArtifactError,
            DataManagerCreationError,
            ArtifactMaterializationValidationError,
            FileNotFoundError,
            KeyError,
            ValueError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def plan_database_update(self, database_id: str) -> DatabaseUpdatePlan:
        try:
            loaded = self._creation.load_database_revision(database_id)
            manifest = loaded.manifest
            content: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2
            if isinstance(manifest, DatabaseRevisionManifestV1):
                content = self._creation.load_artifact_collection(
                    manifest.collection_id
                )
            else:
                content = manifest
            source_change = self.classify_source_change(
                manifest.source_ohlcv, manifest.market_id
            )
            managed = self._artifacts.list_managed_artifacts(manifest.market_id)
            return self._plan_database_update_from_evidence(
                database_id,
                loaded,
                content,
                source_change,
                managed,
            )
        except (DataManagerCreationError, ArtifactError, OSError, ValueError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def _plan_database_update_from_evidence(
        self,
        database_id,
        loaded,
        collection,
        source_change,
        managed_summaries,
    ) -> DatabaseUpdatePlan:
        manifest = loaded.manifest
        try:
            blockers: list[str] = []
            status = "CURRENT"
            mode = "CURRENT"
            current_source = source_change.current_source
            resolved_members: tuple[ArtifactCollectionMemberV1, ...] = ()
            heads: dict[str, str] = {}
            if isinstance(manifest, DatabaseRevisionManifestV1):
                heads = self._current_collection_heads(
                    collection, managed_summaries=managed_summaries
                )
                resolved_members = collection.members
            elif current_source is not None:
                try:
                    resolved_members, heads = self._resolve_database_members(
                        collection, current_source, managed_summaries
                    )
                except DataManagerOperationError as exc:
                    status, mode = "WAITING_FOR_ARTIFACT_UPDATE", "BLOCKED"
                    blockers.append(str(exc))
            member_ids = tuple(
                item.version_key.logical_artifact_id for item in collection.members
            )
            old_member_ids = tuple(
                item.logical_artifact_id for item in manifest.artifact_version_keys
            )
            if current_source is None:
                status, mode = "SOURCE_INVALID", "BLOCKED"
                blockers.append("accepted OHLCV source is unavailable")
            elif isinstance(manifest, DatabaseRevisionManifestV1) and (any(
                heads.get(item.version_key.logical_artifact_id)
                != item.version_key.artifact_id
                for item in collection.members
            ) or any(
                self._artifacts.load_artifact_by_id(
                    collection.market_id, item.version_key.artifact_id
                ).metadata.source_ohlcv != current_source
                for item in collection.members
            )):
                status, mode = "WAITING_FOR_ARTIFACT_UPDATE", "BLOCKED"
                blockers.append("Artifact Collection members are not current")
            candidate = None
            if mode != "BLOCKED":
                candidate = self._database_frame(
                    self._creation.load_database_seed(manifest.seed_id),
                    collection,
                    members=resolved_members,
                )
                old = pd.read_csv(io.BytesIO(loaded.values_csv))
                if set(member_ids) != set(old_member_ids):
                    status, mode = "COLLECTION_CHANGED", "REBUILD_REQUIRED"
                elif tuple(candidate.columns) != tuple(old.columns):
                    status, mode = "SCHEMA_CHANGED", "REBUILD_REQUIRED"
                elif not self._frame_prefix_equal(old, candidate):
                    status, mode = "PREFIX_MISMATCH", "REBUILD_REQUIRED"
                elif source_change.status in {
                    "HISTORICAL_MUTATION", "TRUNCATED", "IDENTITY_MISMATCH"
                }:
                    status, mode = "REBUILD_REQUIRED", "REBUILD_REQUIRED"
                elif len(candidate) > len(old):
                    status, mode = "UPDATE_AVAILABLE", "APPEND"
                elif (
                    source_change.status in {"UNCHANGED", "APPEND_ONLY"}
                    and (
                        not isinstance(manifest, DatabaseRevisionManifestV1)
                        or collection.revision_id == manifest.collection_revision_id
                    )
                    and tuple(item.version_key for item in resolved_members)
                    == manifest.artifact_version_keys
                ):
                    status, mode = "CURRENT", "CURRENT"
                else:
                    status, mode = "REBUILD_REQUIRED", "REBUILD_REQUIRED"
            columns = () if candidate is None else tuple(candidate.columns)
            payload = {
                "schema": "data_manager_database_update_plan_v1",
                "database_id": database_id,
                "revision_id": manifest.revision_id,
                "source": _source_payload(current_source),
                "source_status": source_change.status,
                "collection_id": (
                    collection.collection_id
                    if isinstance(manifest, DatabaseRevisionManifestV1)
                    else None
                ),
                "collection_revision_id": (
                    collection.revision_id
                    if isinstance(manifest, DatabaseRevisionManifestV1)
                    else None
                ),
                "heads": [list(value) for value in sorted(heads.items())],
                "columns": list(columns),
                "mode": mode,
                "status": status,
                "blockers": sorted(blockers),
            }
            return DatabaseUpdatePlan(
                plan_id=_hash_payload(payload),
                database_id=database_id,
                database_revision_id=manifest.revision_id,
                market_id=manifest.market_id,
                mode=mode,
                status=status,
                source_change=source_change,
                source_ohlcv=current_source,
                collection_id=(
                    collection.collection_id
                    if isinstance(manifest, DatabaseRevisionManifestV1)
                    else None
                ),
                collection_revision_id=(
                    collection.revision_id
                    if isinstance(manifest, DatabaseRevisionManifestV1)
                    else None
                ),
                starting_artifact_heads=tuple(heads.items()),
                column_names=columns,
                execution_stages=(("database",),),
                blockers=tuple(blockers),
            )
        except (DataManagerCreationError, ArtifactError, OSError, ValueError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def execute_database_append(
        self,
        plan: DatabaseUpdatePlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseUpdateResult:
        return self._execute_database_update(
            plan,
            required_mode="APPEND",
            cancellation_requested=cancellation_requested,
            before_publish=before_publish,
        )

    def execute_database_rebuild(
        self,
        plan: DatabaseUpdatePlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseUpdateResult:
        return self._execute_database_update(
            plan,
            required_mode="REBUILD_REQUIRED",
            cancellation_requested=cancellation_requested,
            before_publish=before_publish,
        )

    def _execute_database_update(
        self,
        plan: DatabaseUpdatePlan,
        *,
        required_mode: str,
        cancellation_requested: Callable[[], bool] | None,
        before_publish: Callable[[], None] | None,
    ) -> DatabaseUpdateResult:
        if not isinstance(plan, DatabaseUpdatePlan):
            raise TypeError("plan must be a DatabaseUpdatePlan")
        fresh = self.plan_database_update(plan.database_id)
        if fresh != plan:
            raise DataManagerOperationError("Database update plan is stale")
        if plan.mode != required_mode:
            raise DataManagerOperationError(
                f"Database update requires mode {required_mode}"
            )
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerOperationError("Database update cancelled")
        if plan.source_ohlcv is None:
            raise DataManagerOperationError("accepted OHLCV source is unavailable")
        try:
            current = self._creation.load_database_revision(plan.database_id)
            manifest = current.manifest
            definition = self._creation.load_database_definition(plan.database_id)
            if isinstance(manifest, DatabaseRevisionManifestV1):
                if plan.collection_id is None:
                    raise DataManagerOperationError(
                        "V1 Database update requires an Artifact Collection"
                    )
                content: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2 = (
                    self._creation.load_artifact_collection(plan.collection_id)
                )
                members = content.members
            else:
                content = manifest
                members, heads = self._resolve_database_members(
                    content,
                    plan.source_ohlcv,
                    self._artifacts.list_managed_artifacts(plan.market_id),
                )
                if tuple(sorted(heads.items())) != plan.starting_artifact_heads:
                    raise DataManagerOperationError(
                        "Database Artifact heads changed before execution"
                    )
            seed = self._creation.load_database_seed(manifest.seed_id)
            candidate = self._database_frame(seed, content, members=members)
            if required_mode == "APPEND":
                existing = pd.read_csv(io.BytesIO(current.values_csv))
                additions = candidate.loc[
                    candidate["ts_ms"] > manifest.last_timestamp_ms
                ]
                if additions.empty:
                    raise DataManagerOperationError("Database append has no new aligned rows")
                frame = pd.concat([existing, additions], ignore_index=True)
            else:
                frame = candidate
            values = frame.to_csv(
                index=False, lineterminator="\n", float_format="%.17g"
            ).encode("utf-8")
            revision = self._database_manifest(
                definition,
                manifest,
                content,
                plan.source_ohlcv,
                frame,
                values,
                members=members,
            )
            if cancelled():
                raise DataManagerOperationError("Database update cancelled")

            def publication_gate() -> None:
                if cancelled():
                    raise DataManagerOperationError("Database update cancelled")
                if self._artifacts.capture_accepted_source(plan.market_id) != plan.source_ohlcv:
                    raise DataManagerOperationError(
                        "accepted OHLCV source changed before Database publication"
                    )
                if isinstance(manifest, DatabaseRevisionManifestV2):
                    _members, current_heads = self._resolve_database_members(
                        manifest,
                        plan.source_ohlcv,
                        self._artifacts.list_managed_artifacts(plan.market_id),
                    )
                    if tuple(sorted(current_heads.items())) != plan.starting_artifact_heads:
                        raise DataManagerOperationError(
                            "Database Artifact heads changed before publication"
                        )
                if before_publish is not None:
                    before_publish()

            published = self._creation.store.publish_database_revision(
                definition,
                revision,
                values,
                expected_head_revision_id=manifest.revision_id,
                before_publish=publication_gate,
            )
            self.invalidate()
            snapshot = self.reconcile_all(force=True)
            return DatabaseUpdateResult(
                plan.plan_id, required_mode, published, snapshot
            )
        except DataManagerOperationError:
            raise
        except (DataManagerCreationError, ArtifactError, OSError, ValueError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def _reconcile_artifacts(
        self,
        sources,
        accepted_summaries,
        managed_by_market,
        failures,
        cancellation_requested,
    ):
        summaries = tuple(
            item
            for market in sorted(managed_by_market, key=_market_key)
            for item in managed_by_market[market]
        )
        artifact_to_logical: dict[str, str] = {}
        for summary in summaries:
            self._check_reconciliation_cancelled(
                cancellation_requested, "before Artifact"
            )
            if summary.valid:
                for record in self._artifacts.list_artifact_versions(
                    summary.market_id, summary.logical_artifact_id
                ):
                    artifact_to_logical[record.artifact_id] = summary.logical_artifact_id
        pending = list(summaries)
        resolved: dict[str, DataManagerArtifactCurrentness] = {}
        while pending:
            progressed = False
            for summary in tuple(pending):
                self._check_reconciliation_cancelled(
                    cancellation_requested, "before Artifact"
                )
                try:
                    if not summary.valid:
                        item = DataManagerArtifactCurrentness(
                            summary.logical_artifact_id, "", "", summary.market_id,
                            "INVALID", True, None,
                            sources.get(summary.market_id).last_timestamp_ms if summary.market_id in sources else None,
                            0, (), (summary.rejection_reason,),
                        )
                    else:
                        loaded = self._artifacts.load_artifact_by_id(
                            summary.market_id, summary.artifact_id
                        )
                        dependency_ids = tuple(
                            artifact_to_logical.get(ref.artifact_id, "")
                            for ref in loaded.metadata.recipe.source_artifacts
                        )
                        if any(not value for value in dependency_ids):
                            raise ArtifactLineageError(
                                "Artifact dependency has no managed logical identity"
                            )
                        if any(value not in resolved for value in dependency_ids):
                            continue
                        change = self._classify_captured_source(
                            loaded.metadata.source_ohlcv,
                            summary.market_id,
                            sources.get(summary.market_id),
                            accepted_summaries.get(summary.market_id),
                            cancellation_requested,
                        )
                        dependency_blocked = any(
                            resolved[value].status != "CURRENT" for value in dependency_ids
                        ) or any(
                            next(
                                candidate.artifact_id
                                for candidate in summaries
                                if candidate.logical_artifact_id == value
                            )
                            != next(
                                ref.artifact_id
                                for ref in loaded.metadata.recipe.source_artifacts
                                if artifact_to_logical.get(ref.artifact_id) == value
                            )
                            for value in dependency_ids
                        )
                        if dependency_blocked:
                            status = "BLOCKED_BY_DEPENDENCY"
                        elif change.status == "UNCHANGED":
                            status = "CURRENT"
                        elif change.status == "APPEND_ONLY":
                            status = "APPEND_AVAILABLE"
                        elif change.status == "HISTORICAL_MUTATION":
                            status = "HISTORICAL_SOURCE_CHANGED"
                        elif change.status == "INVALID_SOURCE":
                            status = "INVALID"
                        else:
                            status = "REBUILD_REQUIRED"
                        item = DataManagerArtifactCurrentness(
                            summary.logical_artifact_id,
                            summary.artifact_id,
                            summary.portable_recipe_id,
                            summary.market_id,
                            status,
                            change.status != "UNCHANGED",
                            summary.last_timestamp_ms,
                            change.current_through_ms,
                            change.missing_row_count,
                            dependency_ids,
                            (() if status == "CURRENT" else (change.reason,)),
                        )
                    resolved[summary.logical_artifact_id] = item
                except (ArtifactError, OSError, ValueError) as exc:
                    failures.append(f"Artifact {summary.logical_artifact_id}: {exc}")
                    resolved[summary.logical_artifact_id] = DataManagerArtifactCurrentness(
                        summary.logical_artifact_id,
                        summary.artifact_id if summary.valid else "",
                        summary.portable_recipe_id if summary.valid else "",
                        summary.market_id,
                        "INVALID",
                        True,
                        summary.last_timestamp_ms if summary.valid else None,
                        sources.get(summary.market_id).last_timestamp_ms if summary.market_id in sources else None,
                        0,
                        (),
                        (str(exc),),
                    )
                pending.remove(summary)
                progressed = True
            if not progressed:
                for summary in pending:
                    resolved[summary.logical_artifact_id] = DataManagerArtifactCurrentness(
                        summary.logical_artifact_id,
                        summary.artifact_id if summary.valid else "",
                        summary.portable_recipe_id if summary.valid else "",
                        summary.market_id,
                        "INVALID",
                        True,
                        summary.last_timestamp_ms if summary.valid else None,
                        sources.get(summary.market_id).last_timestamp_ms if summary.market_id in sources else None,
                        0,
                        (),
                        ("managed Artifact dependency cycle",),
                    )
                break
        return tuple(
            resolved[key]
            for key in sorted(resolved)
        )

    def _reconcile_collections(
        self,
        sources,
        artifacts,
        collections_by_id,
        failures,
        cancellation_requested,
    ):
        values = []
        for collection_id in sorted(collections_by_id):
            self._check_reconciliation_cancelled(
                cancellation_requested, "before Collection"
            )
            try:
                collection = collections_by_id[collection_id]
                current = sources.get(collection.market_id)
                statuses = [
                    artifacts.get(member.version_key.logical_artifact_id)
                    for member in collection.members
                ]
                blocked = sum(
                    item is None or item.status in {"INVALID", "BLOCKED_BY_DEPENDENCY"}
                    for item in statuses
                )
                stale = sum(item is None or item.status != "CURRENT" for item in statuses)
                exact_heads = all(
                    item is not None and item.artifact_id == member.version_key.artifact_id
                    for item, member in zip(statuses, collection.members, strict=True)
                )
                if current is None:
                    status, reasons = "SOURCE_INVALID", ("accepted source unavailable",)
                elif blocked:
                    status, reasons = "BLOCKED_BY_DEPENDENCY", ("Collection has blocked members",)
                elif stale or not exact_heads:
                    status, reasons = "MEMBERS_REQUIRE_UPDATE", ("Collection members require update",)
                elif collection.last_timestamp_ms != current.last_timestamp_ms:
                    status, reasons = "PARTIALLY_ALIGNED", ("Collection coverage is not current",)
                else:
                    status, reasons = "CURRENT", ()
                values.append(DataManagerCollectionCurrentness(
                    collection.collection_id,
                    collection.revision_id,
                    collection.market_id,
                    status,
                    collection.last_timestamp_ms,
                    None if current is None else current.last_timestamp_ms,
                    stale,
                    blocked,
                    collection.database_ready and status == "CURRENT",
                    reasons,
                ))
            except (DataManagerCreationError, OSError, ValueError) as exc:
                failures.append(f"Collection {collection_id}: {exc}")
        return tuple(values)

    def _reconcile_databases(
        self,
        collections,
        collections_by_id,
        database_revisions,
        source_changes,
        accepted_summaries,
        managed_by_market,
        failures,
        cancellation_requested,
    ):
        values = []
        for database_id in sorted(database_revisions):
            self._check_reconciliation_cancelled(
                cancellation_requested, "before Database"
            )
            try:
                loaded_revision = database_revisions[database_id]
                loaded = loaded_revision.manifest
                if isinstance(loaded, DatabaseRevisionManifestV1):
                    collection_revision = collections_by_id.get(loaded.collection_id)
                    if collection_revision is None:
                        raise DataManagerOperationError(
                            "Database Artifact Collection is unavailable"
                        )
                else:
                    collection_revision = loaded
                source_change = self._classify_captured_source(
                    loaded.source_ohlcv,
                    loaded.market_id,
                    source_changes[loaded.market_id].current_source,
                    accepted_summaries.get(loaded.market_id),
                    cancellation_requested,
                )
                plan = self._plan_database_update_from_evidence(
                    database_id,
                    loaded_revision,
                    collection_revision,
                    source_change,
                    managed_by_market.get(loaded.market_id, ()),
                )
                collection = (
                    None
                    if plan.collection_id is None
                    else collections.get(plan.collection_id)
                )
                values.append(DataManagerDatabaseCurrentness(
                    database_id,
                    loaded.revision_id,
                    loaded.market_id,
                    plan.status,
                    loaded.last_timestamp_ms,
                    plan.source_change.current_through_ms,
                    None if collection is None else collection.aligned_through_ms,
                    plan.source_change.missing_row_count,
                    plan.status != "PREFIX_MISMATCH",
                    plan.blockers,
                ))
            except (DataManagerOperationError, DataManagerCreationError, OSError) as exc:
                failures.append(f"Database {database_id}: {exc}")
        return tuple(values)

    def _evidence_signature(
        self,
        accepted_summaries,
        sources,
        source_errors,
        managed_by_market,
        collections,
        databases,
    ) -> str:
        accepted = [
            sources[market].to_dict()
            if market in sources
            else {"market": market.as_key(), "error": source_errors.get(market, "unavailable")}
            for market in sorted(accepted_summaries, key=_market_key)
        ]
        managed = [
            {
                "market": summary.market_id.as_key(),
                "logical": summary.logical_artifact_id,
                "artifact": summary.artifact_id,
                "valid": summary.valid,
            }
            for market in sorted(managed_by_market, key=_market_key)
            for summary in managed_by_market[market]
        ]
        return _hash_payload({
            "accepted": accepted,
            "managed": sorted(managed, key=lambda value: (value["market"], value["logical"])),
            "collections": sorted(collections),
            "databases": sorted(databases),
        })

    def _accepted_summary(self, market: MarketId) -> AcceptedDatasetSummary | None:
        result = self._catalog.inspect_market(market)
        return result if isinstance(result, AcceptedDatasetSummary) else None

    def _prefix_matches(
        self,
        path: Path,
        previous: OHLCVSourceFingerprintV1,
        cancellation_requested: Callable[[], bool],
    ) -> bool:
        self._check_reconciliation_cancelled(
            cancellation_requested, "before prefix hashing"
        )
        digest = hashlib.sha256()
        header = b""
        terminal_line = b""
        with path.open("rb") as handle:
            for line_number in range(previous.row_count + 1):
                if line_number % 1024 == 0:
                    self._check_reconciliation_cancelled(
                        cancellation_requested, "during prefix hashing"
                    )
                line = handle.readline()
                if not line:
                    return False
                digest.update(line)
                if line_number == 0:
                    header = line
                else:
                    terminal_line = line
        if digest.hexdigest() != previous.csv_sha256:
            return False
        reader = csv.DictReader(
            io.StringIO((header + terminal_line).decode("utf-8"))
        )
        row = next(reader, None)
        if row is None:
            return False
        try:
            terminal = int(row["ts_ms"])
        except (KeyError, TypeError, ValueError):
            return False
        return terminal == previous.last_timestamp_ms

    def _calculate_updated_node(
        self,
        recipe,
        node,
        source_change,
        target_frame,
        dependency_frames,
        incoming_edges,
    ) -> FinancialToolCalculationResult:
        refs_by_role = {ref.role: ref for ref in recipe.source_artifacts}

        def calculate(frame, frames):
            dependencies = tuple(
                (
                    refs_by_role[edge.role],
                    frames.get(edge.dependency_logical_artifact_id),
                )
                for edge in incoming_edges
            )
            if any(frame is None for _ref, frame in dependencies):
                missing = next(
                    edge.dependency_logical_artifact_id
                    for edge in incoming_edges
                    if frames.get(edge.dependency_logical_artifact_id) is None
                )
                raise ArtifactMaterializationValidationError(
                    f"dependency result is unavailable: {missing}"
                )
            return _calculate_artifact_recipe(
                recipe,
                frame,
                tuple((ref, value) for ref, value in dependencies if value is not None),
            )

        if (
            source_change.status != "APPEND_ONLY"
            or node.current_artifact_id is None
            or node.update_strategy is not UpdateStrategy.OVERLAP_RECALCULATION
        ):
            return calculate(target_frame, dependency_frames)
        previous = self._artifacts.load_artifact_by_id(
            source_change.market_id, node.current_artifact_id
        ).frame
        preserve_count = max(0, len(previous) - node.revisable_tail_rows)
        start = max(0, preserve_count - node.context_rows)
        comparison_start = start + max(0, node.context_rows - 1)
        if comparison_start >= preserve_count:
            return calculate(target_frame, dependency_frames)
        target_slice = target_frame.iloc[start:].reset_index(drop=True)
        dependency_slices = {
            key: value.iloc[start:].reset_index(drop=True)
            for key, value in dependency_frames.items()
        }
        recalculated = calculate(target_slice, dependency_slices)
        replacement = recalculated.to_frame()
        old_overlap = previous.iloc[comparison_start:preserve_count].reset_index(drop=True)
        new_overlap = replacement.loc[
            replacement["ts_ms"].isin(old_overlap["ts_ms"])
        ].reset_index(drop=True)
        self._require_frames_equal(old_overlap, new_overlap, "overlap")
        if preserve_count >= len(previous):
            preserved = previous
            terminal = int(previous["ts_ms"].iloc[-1])
            replacement = replacement.loc[replacement["ts_ms"] > terminal]
        else:
            preserved = previous.iloc[:preserve_count]
            boundary = int(previous["ts_ms"].iloc[preserve_count])
            replacement = replacement.loc[replacement["ts_ms"] >= boundary]
        merged = pd.concat([preserved, replacement], ignore_index=True)
        if tuple(int(value) for value in merged["ts_ms"]) != tuple(
            int(value) for value in target_frame["ts_ms"]
        ):
            raise DataManagerOperationError(
                "overlap result does not cover the current OHLCV timestamp spine"
            )
        result = recalculated
        return FinancialToolCalculationResult(
            tool_key=result.tool_key,
            kind=result.kind,
            parameters=result.parameters,
            bindings=result.bindings,
            output_names=result.output_names,
            frame=merged,
            analysis=result.analysis,
        )

    @staticmethod
    def _check_reconciliation_cancelled(
        cancellation_requested: Callable[[], bool], context: str
    ) -> None:
        if cancellation_requested():
            raise DataManagerOperationError(
                f"Data Manager reconciliation cancelled {context}"
            )

    @staticmethod
    def _require_frames_equal(left: pd.DataFrame, right: pd.DataFrame, context: str) -> None:
        if tuple(left.columns) != tuple(right.columns) or len(left) != len(right):
            raise DataManagerOperationError(f"{context} structure mismatch")
        if not left["ts_ms"].reset_index(drop=True).equals(
            right["ts_ms"].reset_index(drop=True)
        ):
            raise DataManagerOperationError(f"{context} timestamp mismatch")
        for column in left.columns[1:]:
            old = left[column].reset_index(drop=True)
            new = right[column].reset_index(drop=True)
            if not old.isna().equals(new.isna()):
                raise DataManagerOperationError(f"{context} NaN-mask mismatch")
            mask = ~old.isna()
            if pd.api.types.is_numeric_dtype(old.dtype) and not pd.api.types.is_bool_dtype(old.dtype):
                if not np.allclose(
                    old.loc[mask].to_numpy(dtype="float64"),
                    new.loc[mask].to_numpy(dtype="float64"),
                    atol=_NUMERIC_ATOL,
                    rtol=0,
                ):
                    raise DataManagerOperationError(f"{context} numeric mismatch")
            elif not old.loc[mask].astype(object).equals(new.loc[mask].astype(object)):
                raise DataManagerOperationError(f"{context} value mismatch")

    @staticmethod
    def _managed_entry(summary) -> DataManagerManagedArtifactEntry:
        return DataManagerManagedArtifactEntry(
            summary.logical_artifact_id,
            summary.portable_recipe_id,
            summary.market_id,
            summary.artifact_id,
            summary.previous_artifact_id,
            summary.tool_key,
            summary.kind,
            summary.output_names,
            summary.row_count,
            summary.first_timestamp_ms,
            summary.last_timestamp_ms,
            summary.created_at_utc,
            summary.valid,
            summary.rejection_reason,
        )

    def _current_collection_heads(
        self,
        collection: ArtifactCollectionRevisionV1,
        *,
        managed_summaries=None,
    ) -> dict[str, str]:
        summaries = (
            self._artifacts.list_managed_artifacts(collection.market_id)
            if managed_summaries is None
            else managed_summaries
        )
        managed = {
            item.logical_artifact_id: item.artifact_id
            for item in summaries
            if item.valid
        }
        return {
            member.version_key.logical_artifact_id: managed.get(
                member.version_key.logical_artifact_id, ""
            )
            for member in collection.members
        }

    def _database_frame(
        self,
        seed,
        collection: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2,
        *,
        members: Sequence[ArtifactCollectionMemberV1] | None = None,
    ) -> pd.DataFrame:
        dataset = self._loader.load(seed.market_id)
        frame = pd.DataFrame({
            "ts_ms": dataset.ts_ms,
            "open": dataset.open,
            "high": dataset.high,
            "low": dataset.low,
            "close": dataset.close,
            "volume": dataset.volume,
        })
        end = (
            int(dataset.ts_ms[-1])
            if seed.selected_range_end_ms == seed.last_timestamp_ms
            else seed.selected_range_end_ms
        )
        frame = frame.loc[
            frame["ts_ms"].between(seed.selected_range_start_ms, end),
            ["ts_ms", *seed.selected_ohlcv_columns],
        ].copy()
        exact_members = tuple(collection.members if members is None else members)
        output_columns = tuple(
            item.column_name for item in collection.selected_outputs
        )
        base_columns = {"ts_ms", *seed.selected_ohlcv_columns}
        if base_columns.intersection(output_columns):
            raise DataManagerOperationError(
                "Database output columns collide with selected base columns"
            )
        members_by_id = {
            item.version_key.logical_artifact_id: item for item in exact_members
        }
        for output in collection.selected_outputs:
            member = members_by_id[output.logical_artifact_id]
            loaded = self._artifacts.load_artifact_by_id(
                seed.market_id, member.version_key.artifact_id
            )
            values = loaded.frame[["ts_ms", output.output_name]].rename(
                columns={output.output_name: output.column_name}
            )
            frame = frame.merge(values, on="ts_ms", how="inner", validate="one_to_one")
        presentation_order = (
            collection.presentation_order
            if isinstance(collection, ArtifactCollectionRevisionV1)
            else tuple(item.column_name for item in collection.selected_outputs)
        )
        mask = (
            frame[list(presentation_order)].notna().all(axis=1)
            if presentation_order
            else pd.Series(True, index=frame.index)
        )
        return frame.loc[
            mask,
            ["ts_ms", *seed.selected_ohlcv_columns, *presentation_order],
        ].reset_index(drop=True)

    @classmethod
    def _frame_prefix_equal(cls, old: pd.DataFrame, candidate: pd.DataFrame) -> bool:
        if tuple(old.columns) != tuple(candidate.columns) or len(candidate) < len(old):
            return False
        try:
            cls._require_frames_equal(
                old.reset_index(drop=True),
                candidate.iloc[: len(old)].reset_index(drop=True),
                "Database prefix",
            )
        except DataManagerOperationError:
            return False
        return True

    def _database_manifest(
        self,
        definition: DatabaseDefinitionV1,
        previous: DatabaseRevisionManifest,
        collection: ArtifactCollectionRevisionV1 | DatabaseRevisionManifestV2,
        source: OHLCVSourceFingerprintV1,
        frame: pd.DataFrame,
        values: bytes,
        *,
        members: Sequence[ArtifactCollectionMemberV1] | None = None,
    ) -> DatabaseRevisionManifest:
        now = self._clock()
        if isinstance(previous, DatabaseRevisionManifestV2):
            exact_members = tuple(collection.members if members is None else members)
            payload = {
                "schema_version": "2.0",
                "object_type": "database_revision",
                "database_id": definition.database_id,
                "display_name": definition.display_name,
                "description": definition.description,
                "seed_id": definition.seed_id,
                "market_id": {
                    "exchange": definition.market_id.exchange,
                    "market_type": definition.market_id.market_type,
                    "symbol": definition.market_id.symbol,
                    "timeframe": definition.market_id.timeframe,
                },
                "source_ohlcv": source.to_dict(),
                "members": [item.to_dict() for item in exact_members],
                "dependency_edges": [
                    item.to_dict() for item in previous.dependency_edges
                ],
                "selected_outputs": [
                    item.to_dict() for item in previous.selected_outputs
                ],
                "collection_sources": [
                    item.to_dict() for item in previous.collection_sources
                ],
                "column_mapping": {value: value for value in frame.columns},
                "first_timestamp_ms": int(frame["ts_ms"].iloc[0]),
                "last_timestamp_ms": int(frame["ts_ms"].iloc[-1]),
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "values_sha256": hashlib.sha256(values).hexdigest(),
                "previous_revision_id": previous.revision_id,
                "created_at_utc": now.isoformat().replace("+00:00", "Z"),
            }
            return DatabaseRevisionManifestV2(
                database_id=definition.database_id,
                revision_id=deterministic_hash(payload),
                display_name=definition.display_name,
                description=definition.description,
                seed_id=definition.seed_id,
                market_id=definition.market_id,
                source_ohlcv=source,
                members=exact_members,
                dependency_edges=previous.dependency_edges,
                selected_outputs=previous.selected_outputs,
                collection_sources=previous.collection_sources,
                column_mapping={value: value for value in frame.columns},
                first_timestamp_ms=int(frame["ts_ms"].iloc[0]),
                last_timestamp_ms=int(frame["ts_ms"].iloc[-1]),
                row_count=len(frame),
                column_count=len(frame.columns),
                values_sha256=hashlib.sha256(values).hexdigest(),
                previous_revision_id=previous.revision_id,
                created_at_utc=now,
            )
        payload = {
            "schema_version": "1.0",
            "object_type": "database_revision",
            "database_id": definition.database_id,
            "display_name": definition.display_name,
            "description": definition.description,
            "seed_id": definition.seed_id,
            "market_id": {
                "exchange": definition.market_id.exchange,
                "market_type": definition.market_id.market_type,
                "symbol": definition.market_id.symbol,
                "timeframe": definition.market_id.timeframe,
            },
            "source_ohlcv": source.to_dict(),
            "collection_id": collection.collection_id,
            "collection_revision_id": collection.revision_id,
            "collection_manifest_hash": collection.revision_id,
            "artifact_version_keys": [
                {
                    "logical_artifact_id": item.version_key.logical_artifact_id,
                    "artifact_id": item.version_key.artifact_id,
                }
                for item in collection.members
            ],
            "artifact_payload_hashes": [item.values_sha256 for item in collection.members],
            "portable_recipe_ids": list(collection.source_portable_recipe_ids),
            "column_mapping": {value: value for value in frame.columns},
            "first_timestamp_ms": int(frame["ts_ms"].iloc[0]),
            "last_timestamp_ms": int(frame["ts_ms"].iloc[-1]),
            "row_count": len(frame),
            "column_count": len(frame.columns),
            "values_sha256": hashlib.sha256(values).hexdigest(),
            "previous_revision_id": previous.revision_id,
            "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        }
        return DatabaseRevisionManifestV1(
            database_id=definition.database_id,
            revision_id=deterministic_hash(payload),
            display_name=definition.display_name,
            description=definition.description,
            seed_id=definition.seed_id,
            market_id=definition.market_id,
            source_ohlcv=source,
            collection_id=collection.collection_id,
            collection_revision_id=collection.revision_id,
            collection_manifest_hash=collection.revision_id,
            artifact_version_keys=tuple(item.version_key for item in collection.members),
            artifact_payload_hashes=tuple(item.values_sha256 for item in collection.members),
            portable_recipe_ids=collection.source_portable_recipe_ids,
            column_mapping={value: value for value in frame.columns},
            first_timestamp_ms=int(frame["ts_ms"].iloc[0]),
            last_timestamp_ms=int(frame["ts_ms"].iloc[-1]),
            row_count=len(frame),
            column_count=len(frame.columns),
            values_sha256=hashlib.sha256(values).hexdigest(),
            previous_revision_id=previous.revision_id,
            created_at_utc=now,
        )


__all__ = ("DataManagerUpdateWorkflow",)
