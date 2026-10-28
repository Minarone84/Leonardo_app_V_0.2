"""Read-only reconciliation and explicit Data Manager update execution."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from leonardo.artifacts import (
    ArtifactError,
    ArtifactLineageError,
    ArtifactNotFoundError,
    ArtifactMetadataV1,
    ArtifactRecipeV1,
    ArtifactService,
    ArtifactSourceRefV1,
    ManagedArtifactVersionKey,
    ManagedArtifactSummary,
    OHLCVSourceFingerprintV1,
)
from leonardo.data import MarketId, timeframe_duration_ms
from leonardo.ohlcv.validation import _add_calendar_months
from .creation_store import _database_nullable_columns, _snapshot_rows
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
    DatabaseRevisionManifestV3,
    database_revision_from_dict,
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
    ArtifactUpdatePlan,
    ArtifactUpdateResult,
    DataManagerArtifactCurrentness,
    DataManagerCollectionCurrentness,
    DataManagerDatabaseCurrentness,
    DataManagerReconciliationSnapshot,
    DataManagerSourceChange,
    DatabaseUpdatePlan,
    DatabaseUpdateResult,
)


_NUMERIC_ATOL = 0.00005
_UNSET = object()


@dataclass(frozen=True)
class _ArtifactGraph:
    market_id: MarketId
    members: tuple[ArtifactCollectionMemberV1, ...]
    dependency_edges: tuple[ArtifactCollectionDependencyV1, ...]


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
        report = self._catalog.scan_metadata()
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
        invalid_databases = {}
        database_evidence: list[tuple[str, str]] = []
        for database_id in self._creation.store.list_database_ids():
            try:
                loaded = self._creation.store.load_database_manifest(database_id)
                database_revisions[database_id] = loaded
                database_evidence.append((database_id, loaded.revision_id))
                known_markets.add(loaded.market_id)
            except (DataManagerCreationError, OSError, ValueError) as exc:
                failures.append(f"Database {database_id}: {exc}")
                database_evidence.append((database_id, str(exc)))
                try:
                    definition = self._creation.load_database_definition(database_id)
                    head = self._creation.store.load_database_head(database_id)
                except (DataManagerCreationError, OSError, ValueError):
                    continue
                invalid_databases[database_id] = (definition, head, str(exc))
                known_markets.add(definition.market_id)

        sources: dict[MarketId, OHLCVSourceFingerprintV1] = {}
        source_errors: dict[MarketId, str] = {}
        for market in sorted(accepted_summaries, key=_market_key):
            self._check_reconciliation_cancelled(cancelled, "before source capture")
            try:
                sources[market] = self._artifacts.source_metadata(market)
            except (ArtifactError, OSError, ValueError) as exc:
                source_errors[market] = str(exc)
                failures.append(f"{market.as_key()}: {exc}")

        managed_by_market = {}
        for market in sorted(known_markets, key=_market_key):
            self._check_reconciliation_cancelled(cancelled, "before managed-market scan")
            managed_by_market[market] = self._artifacts.list_managed_artifacts_metadata(market)

        previous_by_market: dict[MarketId, OHLCVSourceFingerprintV1] = {}
        for market in sorted(managed_by_market, key=_market_key):
            for item in managed_by_market[market]:
                self._check_reconciliation_cancelled(cancelled, "before Artifact")
                if not item.valid:
                    continue
                try:
                    previous_by_market.setdefault(
                        market,
                        self._artifacts.load_artifact_metadata(
                            market, item.artifact_id
                        ).source_ohlcv,
                    )
                except (ArtifactError, OSError, ValueError):
                    pass
        for collection in collections_by_id.values():
            previous_by_market.setdefault(collection.market_id, collection.source_ohlcv)
        for loaded in database_revisions.values():
            previous_by_market.setdefault(
                loaded.market_id, loaded.source_ohlcv
            )

        source_changes = tuple(
            self._classify_captured_source(
                previous_by_market.get(market, sources.get(market)),
                market,
                sources.get(market),
                accepted_summaries.get(market),
                cancelled,
                source_error=source_errors.get(market), metadata_only=True,
            )
            for market in sorted(known_markets, key=_market_key)
        )
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
        databases = self._reconcile_databases(
            database_revisions,
            invalid_databases,
            sources,
            accepted_summaries,
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
        metadata_only: bool = False,
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
        ):
            status, reason = "TRUNCATED", "current source coverage is shorter"
        elif (
            self._creation._same_coverage(current, previous_source)
            and current.csv_sha256 == previous_source.csv_sha256
        ):
            status, reason = "UNCHANGED", "accepted source data and coverage are unchanged"
        elif current.row_count > previous_source.row_count and (metadata_only or self._prefix_matches(
            summary.csv_path, previous_source, cancellation_requested
        )):
            status, reason = "APPEND_ONLY", (
                "Advisory metadata coverage increased; operation must verify the prefix"
                if metadata_only else "exact accepted CSV prefix is unchanged"
            )
        else:
            status, reason = (
                "HISTORICAL_MUTATION",
                "Metadata fingerprint changed; operational verification required" if metadata_only
                else "accepted source evidence differs without an exact append-only prefix",
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

    def _load_recreation_evidence(self, collection, member, members, edges):
        logical_id = member.version_key.logical_artifact_id
        try:
            head = self._artifacts.load_artifact_head(collection.market_id, logical_id)
            self._artifacts.load_artifact_by_id(collection.market_id, head.artifact_id)
        except ArtifactNotFoundError:
            pass
        else:
            raise DataManagerOperationError("existing invalid managed head cannot be recreated")
        record = self._artifacts.load_artifact_version(
            collection.market_id, logical_id, member.version_key.artifact_id
        )
        historical = self._artifacts.load_artifact_by_id(
            collection.market_id, record.artifact_id
        )
        metadata = historical.metadata
        summary = ManagedArtifactSummary(
            record.logical_artifact_id, record.portable_recipe_id, record.market_id,
            record.artifact_id, record.previous_artifact_id, metadata.recipe.tool_key,
            metadata.recipe.kind, metadata.recipe.output_names, metadata.row_count,
            metadata.first_timestamp_ms, metadata.last_timestamp_ms, metadata.created_at_utc,
        )
        return self._load_and_prove_member_artifact(
            collection, member, summary, members, edges
        )

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

    def plan_artifact_update(
        self, market_id: MarketId, root_logical_artifact_ids: Sequence[str]
    ) -> ArtifactUpdatePlan:
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        if isinstance(root_logical_artifact_ids, (str, bytes)):
            raise TypeError("Artifact roots must be a sequence")
        roots = tuple(sorted(set(root_logical_artifact_ids)))
        if not roots:
            raise ValueError("Select at least one logical Artifact root")
        for logical_id in roots:
            ManagedArtifactVersionKey(logical_id, "0" * 64)
        summaries = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts_metadata(market_id)
        }
        # Build physical-version ownership once; portable Recipe storage is irrelevant.
        owners: dict[str, set[str]] = {}
        versions = {}
        errors = {}
        for logical_id in summaries:
            try:
                records = self._artifacts.list_artifact_versions(market_id, logical_id)
                versions[logical_id] = records
                for record in records:
                    owners.setdefault(record.artifact_id, set()).add(logical_id)
            except (ArtifactError, OSError, ValueError) as exc:
                errors[logical_id] = str(exc)
        source_error = None
        try:
            source = self._artifacts.capture_accepted_source(market_id)
        except (ArtifactError, OSError, ValueError) as exc:
            source = None
            source_error = str(exc)
        members = {}
        loaded_by_id = {}
        recovery = {}
        edges = []
        blockers = [] if source_error is None else [source_error]
        pending = list(roots)
        visited = set()
        while pending:
            logical_id = pending.pop(0)
            if logical_id in visited:
                continue
            visited.add(logical_id)
            try:
                if logical_id in errors:
                    raise DataManagerOperationError(errors[logical_id])
                summary = summaries.get(logical_id)
                if summary is None:
                    raise DataManagerOperationError("no authoritative managed lineage")
                if summary.valid:
                    artifact_id = summary.artifact_id
                else:
                    try:
                        self._artifacts.load_artifact_head(market_id, logical_id)
                    except ArtifactNotFoundError:
                        pass
                    else:
                        raise DataManagerOperationError("existing invalid head cannot be recovered")
                    records = versions.get(logical_id, ())
                    by_id = {record.artifact_id: record for record in records}
                    tips = set(by_id) - {record.previous_artifact_id for record in records}
                    if len(tips) != 1:
                        raise DataManagerOperationError("surviving lineage has no unique tip")
                    artifact_id = next(iter(tips))
                    seen = set()
                    cursor = artifact_id
                    while cursor is not None:
                        if cursor in seen or cursor not in by_id:
                            raise DataManagerOperationError("surviving version chain is invalid")
                        seen.add(cursor)
                        cursor = by_id[cursor].previous_artifact_id
                    if seen != set(by_id):
                        raise DataManagerOperationError("surviving version chain is disconnected")
                    recovery[logical_id] = artifact_id
                record = self._artifacts.load_artifact_version(market_id, logical_id, artifact_id)
                loaded = self._artifacts.load_artifact_by_id(market_id, artifact_id)
                recipe = loaded.metadata.recipe
                member = ArtifactCollectionMemberV1(
                    ManagedArtifactVersionKey(logical_id, artifact_id),
                    record.portable_recipe_id, recipe.tool_key, recipe.kind,
                    recipe.output_names, loaded.metadata.values_sha256,
                )
                members[logical_id] = member
                loaded_by_id[logical_id] = loaded
                for ref in recipe.source_artifacts:
                    candidates = owners.get(ref.artifact_id, set())
                    if len(candidates) != 1:
                        raise DataManagerOperationError(
                            f"dependency {ref.role}: missing or ambiguous managed lineage"
                        )
                    dependency = next(iter(candidates))
                    edges.append(ArtifactCollectionDependencyV1(
                        dependency, logical_id, ref.role, ref.output_name
                    ))
                    pending.append(dependency)
            except (ArtifactError, DataManagerCreationError, DataManagerOperationError,
                    OSError, KeyError, ValueError) as exc:
                blockers.append(f"{logical_id}: {exc}")
        graph = _ArtifactGraph(market_id, tuple(members.values()), tuple(edges))
        stages = ()
        try:
            if any(edge.dependency_logical_artifact_id not in members for edge in edges):
                raise DataManagerOperationError("required dependency is unavailable")
            stages = self._artifact_execution_stages(graph)
        except (DataManagerOperationError, KeyError, ValueError) as exc:
            blockers.append(str(exc))
        incoming = self._incoming_collection_edges(graph)
        nodes = {}
        order = tuple(value for stage in stages for value in stage)
        for logical_id in order:
            member = members[logical_id]
            loaded = loaded_by_id[logical_id]
            metadata = loaded.metadata
            node_blockers = []
            try:
                record = self._artifacts.load_artifact_version(
                    market_id, logical_id, metadata.artifact_id
                )
                summary = ManagedArtifactSummary(
                    logical_id, record.portable_recipe_id, market_id, record.artifact_id,
                    record.previous_artifact_id, metadata.recipe.tool_key,
                    metadata.recipe.kind, metadata.recipe.output_names, metadata.row_count,
                    metadata.first_timestamp_ms, metadata.last_timestamp_ms,
                    metadata.created_at_utc,
                )
                self._load_and_prove_member_artifact(
                    graph, member, summary, members, incoming[logical_id]
                )
            except (ArtifactError, DataManagerOperationError, KeyError, ValueError) as exc:
                node_blockers.append(str(exc))
            change = self.classify_source_change(metadata.source_ohlcv, market_id)
            if change.status in {"TRUNCATED", "IDENTITY_MISMATCH", "INVALID_SOURCE"}:
                node_blockers.append(f"{change.status}: {change.reason}")
            dependencies = tuple(dict.fromkeys(
                edge.dependency_logical_artifact_id for edge in incoming[logical_id]
            ))
            if any(nodes[d].action == "BLOCKED" for d in dependencies):
                node_blockers.append("required dependency cannot be safely updated")
            refs = {ref.role: ref for ref in metadata.recipe.source_artifacts}
            current_dependencies = all(
                nodes[d].action == "REUSE_CURRENT" for d in dependencies
            ) and all(
                refs[edge.role].artifact_id == members[edge.dependency_logical_artifact_id].version_key.artifact_id
                for edge in incoming[logical_id]
            )
            action = "UPDATE"
            reasons = (change.reason if change.status != "UNCHANGED"
                       else "Required dependency head/currentness changed",)
            if logical_id in recovery:
                action = "RECREATE"
                reasons = ("Managed head missing; exact surviving Artifact lineage can be recovered.",)
            elif change.status == "UNCHANGED" and current_dependencies:
                action, reasons = "REUSE_CURRENT", ("Artifact and dependencies are current",)
            if node_blockers or source is None:
                action = "BLOCKED"
            policy = get_financial_tool_spec(member.tool_key).update_policy
            nodes[logical_id] = ArtifactUpdateNodePlan(
                member.portable_recipe_id, logical_id, member.tool_key,
                "ROOT" if logical_id in roots else "SUPPORT", action,
                None if logical_id in recovery else metadata.artifact_id,
                dependencies, policy.strategy,
                policy.effective_context_rows(metadata.recipe.parameters),
                policy.revisable_tail_rows, tuple(node_blockers), reasons,
                member.kind, recovery.get(logical_id),
            )
        payload = {
            "market": market_id.as_key(), "roots": roots,
            "source": _source_payload(source),
            "members": [member.to_dict() for member in graph.members],
            "edges": [edge.to_dict() for edge in edges],
            "nodes": [(n.logical_artifact_id, n.action, n.current_artifact_id,
                       n.reconstruction_artifact_id, n.blockers) for n in nodes.values()],
            "blockers": blockers,
        }
        return ArtifactUpdatePlan(
            _hash_payload(payload), market_id, roots, source, graph.members,
            graph.dependency_edges, stages, tuple(nodes.values()), tuple(blockers),
        )

    def execute_artifact_update(
        self, plan: ArtifactUpdatePlan, *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactUpdateResult:
        if not isinstance(plan, ArtifactUpdatePlan):
            raise TypeError("plan must be an ArtifactUpdatePlan")
        if plan.blocked:
            raise DataManagerOperationError("blocked Artifact update plan cannot execute")
        if self.plan_artifact_update(plan.market_id, plan.root_logical_artifact_ids) != plan:
            raise DataManagerOperationError("Artifact update plan is stale")
        cancelled = cancellation_requested or (lambda: False)
        publication_started = False
        reviewed_heads = {node.logical_artifact_id: node.current_artifact_id for node in plan.nodes}

        def publication_gate():
            nonlocal publication_started
            if cancelled():
                raise DataManagerOperationError("Artifact update cancelled")
            if self._artifacts.capture_accepted_source(plan.market_id) != plan.source_ohlcv:
                raise DataManagerOperationError("Artifact update source changed after review")
            for logical_id, expected_head in reviewed_heads.items():
                try:
                    actual_head = self._artifacts.load_artifact_head(plan.market_id, logical_id).artifact_id
                except ArtifactNotFoundError:
                    actual_head = None
                if actual_head != expected_head:
                    raise DataManagerOperationError("Artifact update head changed after review")
            if not publication_started and before_publish is not None:
                before_publish()
            publication_started = True

        if cancelled():
            raise DataManagerOperationError("Artifact update cancelled")
        if plan.source_ohlcv is None:
            raise DataManagerOperationError("accepted OHLCV source is unavailable")
        try:
            frame = _dataset_frame(self._loader.load(plan.market_id, cancellation_requested=cancelled))
            incoming = self._incoming_collection_edges(plan)
            nodes = {node.logical_artifact_id: node for node in plan.nodes}
            frames, metadata, artifact_ids = {}, {}, {}
            prepared, recovered, updated, reused = [], [], [], []
            for stage in plan.execution_stages:
                for logical_id in stage:
                    if cancelled():
                        raise DataManagerOperationError("Artifact update cancelled")
                    node = nodes[logical_id]
                    current_id = node.current_artifact_id
                    if node.action == "RECREATE":
                        head = self._artifacts.restore_missing_managed_artifact_head(
                            plan.market_id, logical_id, before_publish=publication_gate
                        )
                        if head.artifact_id != node.reconstruction_artifact_id:
                            raise DataManagerOperationError("Recovered Artifact differs from reviewed evidence")
                        current_id = head.artifact_id
                        reviewed_heads[logical_id] = current_id
                        recovered.append(logical_id)
                    loaded = self._artifacts.load_artifact_by_id(plan.market_id, current_id)
                    refs = tuple(ArtifactSourceRefV1(
                        edge.role, artifact_ids[edge.dependency_logical_artifact_id], edge.output_name
                    ) for edge in incoming[logical_id])
                    change = self.classify_source_change(loaded.metadata.source_ohlcv, plan.market_id)
                    if change.current_source != plan.source_ohlcv:
                        raise DataManagerOperationError("Artifact update source changed after review")
                    if (change.status == "UNCHANGED"
                            and set(refs) == set(loaded.metadata.recipe.source_artifacts)):
                        frames[logical_id], metadata[logical_id] = loaded.frame, loaded.metadata
                        artifact_ids[logical_id] = current_id
                        reused.append(logical_id)
                        continue
                    calculation = self._calculate_updated_node(
                        loaded.metadata.recipe, replace(node, current_artifact_id=current_id),
                        change, frame, frames, incoming[logical_id],
                        dependency_refs=refs,
                        full_fallback=True,
                    )
                    source_metadata = tuple({
                        metadata[edge.dependency_logical_artifact_id].artifact_id:
                        metadata[edge.dependency_logical_artifact_id]
                        for edge in incoming[logical_id]
                    }.values())
                    candidate = self._artifacts.prepare_managed_calculation(
                        plan.market_id, node.portable_recipe_id, calculation,
                        expected_source=plan.source_ohlcv, source_artifacts=refs,
                        source_metadata=source_metadata, previous_artifact_id=current_id,
                        created_at_utc=self._clock(),
                    )
                    prepared.append(candidate)
                    frames[logical_id] = calculation.to_frame()
                    metadata[logical_id] = candidate.metadata
                    artifact_ids[logical_id] = candidate.metadata.artifact_id
                    updated.append(logical_id)
            publication = None
            if prepared:
                publication = self._artifacts.publish_managed_artifact_graph(
                    tuple(prepared), expected_source=plan.source_ohlcv,
                    before_publish=publication_gate,
                )
            managed = {item.logical_artifact_id: item for item in self._artifacts.list_managed_artifacts_metadata(plan.market_id)}
            materialization = DataManagerArtifactMaterializationResult(
                plan_id=plan.plan_id, target_market_id=plan.market_id,
                source_ohlcv=plan.source_ohlcv,
                root_logical_artifact_ids=plan.root_logical_artifact_ids,
                support_logical_artifact_ids=tuple(n for n in nodes if n not in plan.root_logical_artifact_ids),
                created_artifact_ids=() if publication is None else publication.created_artifact_ids,
                reused_artifact_ids=tuple(artifact_ids[n] for n in reused),
                created_version_keys=() if publication is None else publication.created_version_keys,
                reused_version_keys=tuple(ManagedArtifactVersionKey(n, artifact_ids[n]) for n in reused),
                advanced_logical_artifact_ids=() if publication is None else publication.advanced_logical_artifact_ids,
                managed_artifacts=tuple(self._managed_entry(managed[n]) for n in nodes),
                verified_artifact_metadata=tuple(metadata.values()),
            )
            self.invalidate()
            return ArtifactUpdateResult(
                plan.plan_id, materialization, tuple(updated), tuple(recovered), tuple(reused),
                (), (), self.reconcile_all(force=True),
            )
        except (ArtifactError, DataManagerCreationError, ArtifactMaterializationValidationError,
                OSError, KeyError, ValueError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def plan_artifact_collection_update(
        self, collection_id: str
    ) -> ArtifactCollectionUpdatePlan:
        collection = self._creation.load_artifact_collection(collection_id)
        validation = self._creation.validate_artifact_collection(collection_id, collection.revision_id)
        source = collection.source_ohlcv
        change = DataManagerSourceChange(
            collection.market_id, "UNCHANGED", source, source,
            source.last_timestamp_ms, source.last_timestamp_ms, 0,
            "No-work compatibility evidence from immutable Collection",
        )
        members = {m.version_key.logical_artifact_id: m for m in collection.members}
        return ArtifactCollectionUpdatePlan(
            plan_id=_hash_payload({"collection": collection.to_dict(), "work": []}),
            collection_id=collection.collection_id,
            collection_revision_id=collection.revision_id,
            market_id=collection.market_id,
            source_change=change, source_ohlcv=source,
            root_recipe_ids=tuple(members[n].portable_recipe_id for n in collection.root_logical_artifact_ids),
            member_recipe_ids=tuple(m.portable_recipe_id for m in collection.members),
            root_logical_artifact_ids=collection.root_logical_artifact_ids,
            support_logical_artifact_ids=collection.support_logical_artifact_ids,
            starting_artifact_heads=tuple((m.version_key.logical_artifact_id, m.version_key.artifact_id) for m in collection.members),
            execution_stages=(), nodes=(), blockers=validation.blockers,
        )

    def execute_artifact_collection_update(
        self, plan: ArtifactCollectionUpdatePlan, *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionUpdateResult:
        if not isinstance(plan, ArtifactCollectionUpdatePlan):
            raise TypeError("plan must be an ArtifactCollectionUpdatePlan")
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerOperationError("Artifact Collection update cancelled")
        fresh = self.plan_artifact_collection_update(plan.collection_id)
        if fresh != plan:
            raise DataManagerOperationError("Artifact Collection update plan is stale")
        if fresh.blocked:
            raise DataManagerOperationError("blocked Artifact Collection update plan cannot execute")
        collection = self._creation.load_artifact_collection(plan.collection_id, plan.collection_revision_id)
        entries = []
        for member in collection.members:
            if cancelled():
                raise DataManagerOperationError("Artifact Collection update cancelled")
            key = member.version_key
            loaded = self._artifacts.load_artifact_by_id(collection.market_id, key.artifact_id)
            record = self._artifacts.load_artifact_version(collection.market_id, key.logical_artifact_id, key.artifact_id)
            meta = loaded.metadata
            entries.append(DataManagerManagedArtifactEntry(
                key.logical_artifact_id, member.portable_recipe_id, collection.market_id,
                key.artifact_id, record.previous_artifact_id, member.tool_key, member.kind,
                member.output_names, meta.row_count, meta.first_timestamp_ms,
                meta.last_timestamp_ms, record.created_at_utc,
            ))
        materialization = DataManagerArtifactMaterializationResult(
            plan_id=plan.plan_id, target_market_id=collection.market_id,
            source_ohlcv=collection.source_ohlcv,
            root_logical_artifact_ids=collection.root_logical_artifact_ids,
            support_logical_artifact_ids=collection.support_logical_artifact_ids,
            created_artifact_ids=(), created_version_keys=(), advanced_logical_artifact_ids=(),
            reused_artifact_ids=tuple(m.version_key.artifact_id for m in collection.members),
            reused_version_keys=tuple(m.version_key for m in collection.members),
            managed_artifacts=tuple(entries),
        )
        self.invalidate()
        return ArtifactCollectionUpdateResult(
            plan.plan_id, materialization, collection,
            self.reconcile_all(force=True, cancellation_requested=cancelled),
        )

    def _database_append_evidence(
        self,
        database_id,
        cancellation_requested=None,
        *,
        captured_source=_UNSET,
        accepted_summary=_UNSET,
    ):
        cancelled = cancellation_requested or (lambda: False)
        self._check_reconciliation_cancelled(cancelled, "before Database integrity")
        loaded = self._creation.store.read_trusted_database_revision(database_id)
        manifest = loaded.manifest
        columns, old_rows, old_timestamps = _snapshot_rows(
            loaded.values_csv, nullable_columns=_database_nullable_columns(manifest)
        )
        source = None
        suffix = ()
        blockers = []
        mode, status = "CURRENT", "CURRENT"
        reviewed = {}
        outputs = ()
        members = ()
        reviewed_edges = ()
        candidate = loaded.values_csv
        try:
            self._check_reconciliation_cancelled(cancelled, "before Database source review")
            source = (
                self._artifacts.capture_accepted_source(manifest.market_id)
                if captured_source is _UNSET
                else captured_source
            )
            summary = (
                self._accepted_summary(manifest.market_id)
                if accepted_summary is _UNSET
                else accepted_summary
            )
            if source is None or summary is None:
                blockers.append("accepted OHLCV source is unavailable")
                mode, status = "BLOCKED", "SOURCE_INVALID"
            else:
                raw = summary.csv_path.read_bytes()
                self._check_reconciliation_cancelled(cancelled, "after Database source read")
                # Source capture already established integrity (or reused exact
                # DMS session evidence). This read supplies append values.
                source_columns, source_rows, timestamps = _snapshot_rows(
                    raw, row_count=source.row_count,
                    first=source.first_timestamp_ms, last=source.last_timestamp_ms,
                )
                if (source.row_count < manifest.source_ohlcv.row_count
                        or source.last_timestamp_ms < manifest.source_ohlcv.last_timestamp_ms
                        or source.first_timestamp_ms != manifest.source_ohlcv.first_timestamp_ms):
                    blockers.append("OHLCV source coverage conflict; repair or revalidate the source; stored Database remains valid")
                    mode, status = "BLOCKED", "SOURCE_INVALID"
        except (ArtifactError, OSError, ValueError) as exc:
            blockers.append(str(exc))
            mode, status = "BLOCKED", "SOURCE_INVALID"
        if not blockers:
            suffix_indices = tuple(i for i, ts in enumerate(timestamps) if ts > manifest.last_timestamp_ms)
            suffix = tuple(timestamps[i] for i in suffix_indices)
            if suffix:
                mode, status = "APPEND", "UPDATE_AVAILABLE"
                previous = manifest.last_timestamp_ms
                step = timeframe_duration_ms(manifest.market_id.timeframe)
                for offset, timestamp in enumerate(suffix):
                    if offset % 1024 == 0:
                        self._check_reconciliation_cancelled(cancelled, "during Database suffix review")
                    expected = previous + step if step is not None else _add_calendar_months(previous, int(manifest.market_id.timeframe[:-1]))
                    if timestamp != expected:
                        blockers.append("accepted OHLCV suffix has a boundary or interior gap")
                        mode, status = "BLOCKED", "SOURCE_INVALID"
                        break
                    previous = timestamp
                if not loaded.values_csv.endswith(b"\n") or b"\r" in loaded.values_csv:
                    blockers.append("legacy Database payload cannot support canonical append without normalization")
                    mode, status = "BLOCKED", "SOURCE_INVALID"
                if not blockers:
                    try:
                        self._check_reconciliation_cancelled(cancelled, "before Database provider review")
                        members, _edges, outputs = self._creation._database_output_evidence(manifest)
                        outputs = self._creation._database_append_outputs(manifest, outputs)
                        # Preserve the existing missing-root diagnostic before graph review.
                        for logical_id in dict.fromkeys(o.logical_artifact_id for o in outputs):
                            self._artifacts.load_artifact_head(manifest.market_id, logical_id)
                        reviewed, reviewed_edges = self._creation._review_content_output_evidence(
                            manifest.market_id, outputs
                        )
                        slices = {}
                        for output in outputs:
                            self._check_reconciliation_cancelled(cancelled, "during Database provider review")
                            slices[output.column_name] = self._creation._copy_output_slice(
                                manifest.market_id, reviewed[output.logical_artifact_id], output, suffix,
                                target_coverage=(source.row_count, source.first_timestamp_ms, source.last_timestamp_ms),
                            )
                    except (ArtifactError, DataManagerCreationError, OSError, KeyError, ValueError) as exc:
                        blockers.append(str(exc))
                        mode, status = "BLOCKED", "WAITING_FOR_ARTIFACT_UPDATE"
                    if not blockers:
                        buffer = io.StringIO(newline="")
                        writer = csv.writer(buffer, lineterminator="\n")
                        for offset, index in enumerate(suffix_indices):
                            if offset % 1024 == 0:
                                self._check_reconciliation_cancelled(cancelled, "during Database suffix serialization")
                            row = dict(zip(source_columns, source_rows[index], strict=True))
                            row.update({name: tokens[offset] for name, tokens in slices.items()})
                            if any(name not in row for name in columns):
                                raise DataManagerOperationError("Database output provider mapping is unprovable")
                            writer.writerow([row[name] for name in columns])
                        candidate = loaded.values_csv + buffer.getvalue().encode("utf-8")
                        self._check_reconciliation_cancelled(cancelled, "before Database append validation")
                        _header, _rows, full_index = _snapshot_rows(
                            candidate, columns=columns,
                            nullable_columns=_database_nullable_columns(manifest),
                        )
                        if full_index != (*old_timestamps, *suffix) or not candidate.startswith(loaded.values_csv):
                            raise DataManagerOperationError("Database append changed stored rows")
        return loaded, source, suffix, members, outputs, reviewed, reviewed_edges, candidate, mode, status, tuple(blockers)

    def _plan_database_update(
        self,
        database_id,
        *,
        captured_source=_UNSET,
        accepted_summary=_UNSET,
        cancellation_requested=None,
        include_prerequisites=True,
        evidence=None,
    ):
        if evidence is None:
            evidence = self._database_append_evidence(
                database_id, cancellation_requested,
                captured_source=captured_source, accepted_summary=accepted_summary,
            )
        loaded, source, suffix, members, outputs, reviewed, reviewed_edges, candidate, mode, status, blockers = evidence
        manifest = loaded.manifest
        change = DataManagerSourceChange(
            manifest.market_id, "INVALID_SOURCE" if source is None or status == "SOURCE_INVALID" else ("APPEND_ONLY" if suffix else "UNCHANGED"),
            manifest.source_ohlcv, source, manifest.last_timestamp_ms,
            None if source is None else source.last_timestamp_ms, len(suffix),
            "Append-only snapshot reconciliation",
        )
        prerequisites = ()
        if (include_prerequisites and status == "WAITING_FOR_ARTIFACT_UPDATE" and outputs
                and all(o.logical_artifact_id is not None for o in outputs)):
            try:
                prerequisite = self.plan_artifact_update(
                    manifest.market_id, tuple(sorted({o.logical_artifact_id for o in outputs}))
                )
                prerequisites = prerequisite.nodes
                if prerequisite.blocked:
                    status = "BLOCKED_BY_DEPENDENCY"
            except (ArtifactError, DataManagerOperationError, ValueError, OSError):
                status = "BLOCKED_BY_DEPENDENCY"
        root_ids = {output.logical_artifact_id for output in outputs if output.logical_artifact_id is not None}
        heads = tuple(sorted(
            (key, member.version_key.artifact_id)
            for key, member in reviewed.items() if key in root_ids
        ))
        payload = {"database": database_id, "head": manifest.revision_id,
                   "source": _source_payload(source), "suffix": suffix,
                   "reviewed": [m.to_dict() for _, m in sorted(reviewed.items())],
                   "edges": [edge.to_dict() for edge in reviewed_edges],
                   "candidate": hashlib.sha256(candidate).hexdigest(), "mode": mode, "status": status,
                   "blockers": blockers}
        return DatabaseUpdatePlan(
            plan_id=_hash_payload(payload), database_id=database_id, database_revision_id=manifest.revision_id,
            market_id=manifest.market_id, mode=mode, status=status, source_change=change,
            source_ohlcv=source, collection_id=None, collection_revision_id=None,
            starting_artifact_heads=heads, column_names=_snapshot_rows(
                loaded.values_csv, nullable_columns=_database_nullable_columns(manifest)
            )[0],
            execution_stages=(("database",),) if mode == "APPEND" else (), blockers=blockers,
            prerequisite_nodes=prerequisites,
        )

    def plan_database_update(self, database_id):
        return self._plan_database_update(database_id)

    def execute_database_append(self, plan, *, cancellation_requested=None, before_publish=None):
        if not isinstance(plan, DatabaseUpdatePlan):
            raise TypeError("plan must be a DatabaseUpdatePlan")
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerOperationError("Database update cancelled")
        evidence = self._database_append_evidence(plan.database_id, cancelled)
        if self._plan_database_update(plan.database_id, evidence=evidence) != plan:
            raise DataManagerOperationError("Database update plan is stale")
        def verify():
            if cancelled():
                raise DataManagerOperationError("Database update cancelled")
            if (self._creation.store.load_database_manifest(plan.database_id).revision_id != plan.database_revision_id
                    or self._artifacts.capture_accepted_source(plan.market_id) != plan.source_ohlcv):
                raise DataManagerOperationError("Database update plan is stale")
            for logical_id, artifact_id in plan.starting_artifact_heads:
                if self._artifacts.load_artifact_head(plan.market_id, logical_id).artifact_id != artifact_id:
                    raise DataManagerOperationError("Database update Artifact head changed")
            if self._creation._database_append_outputs(manifest, saved_outputs) != outputs:
                raise DataManagerOperationError("Database update legacy provider binding changed")
            if self._creation._review_content_output_evidence(
                plan.market_id, outputs
            ) != (reviewed, reviewed_edges):
                raise DataManagerOperationError("Database update Artifact evidence changed")
        if plan.mode != "APPEND" or plan.blocked:
            raise DataManagerOperationError("Database update requires mode APPEND")
        loaded, source, suffix, members, outputs, reviewed, reviewed_edges, values, mode, status, blockers = evidence
        manifest = loaded.manifest
        new_members = self._creation._ordered_consumed_members(members, reviewed)
        old_provenance = self._creation._database_value_provenance(manifest)
        new_provenance = self._creation._capture_value_provenance(
            manifest.market_id, outputs, {o.column_name: reviewed[o.logical_artifact_id] for o in outputs},
            suffix[0], suffix[-1],
        )
        _old_members, _old_edges, saved_outputs = self._creation._database_output_evidence(manifest)
        sources = self._creation._database_selection_sources(manifest)
        provenance = self._creation._combine_value_provenance(
            (old_provenance, new_provenance), saved_outputs, selection_sources=sources
        )
        revised_base = self._creation._database_v3_manifest(
            manifest, values, new_members, reviewed_edges, saved_outputs,
            sources, value_provenance=provenance,
        )
        payload = revised_base.to_dict(include_revision_id=False)
        payload["source_ohlcv"] = source.to_dict()
        payload["revision_id"] = deterministic_hash(payload)
        revised = database_revision_from_dict(payload)
        def publication_gate():
            if before_publish is not None:
                before_publish()
            verify()
        published = self._creation._publish_database_revision(
            self._creation.load_database_definition(plan.database_id), revised, values,
            expected_head_revision_id=plan.database_revision_id, before_publish=publication_gate,
        )
        self.invalidate()
        return DatabaseUpdateResult(plan.plan_id, "APPEND", published, self.reconcile_all(force=True))

    def execute_database_rebuild(self, plan, **execution):
        raise DataManagerOperationError("Database rebuild is retired; only append is supported")

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
                        loaded = self._artifacts.load_artifact_metadata(
                            summary.market_id, summary.artifact_id
                        )
                        dependency_ids = tuple(
                            artifact_to_logical.get(ref.artifact_id, "")
                            for ref in loaded.recipe.source_artifacts
                        )
                        if any(not value for value in dependency_ids):
                            raise ArtifactLineageError(
                                "Artifact dependency has no managed logical identity"
                            )
                        if any(value not in resolved for value in dependency_ids):
                            continue
                        change = self._classify_captured_source(
                            loaded.source_ohlcv,
                            summary.market_id,
                            sources.get(summary.market_id),
                            accepted_summaries.get(summary.market_id),
                            cancellation_requested, metadata_only=True,
                        )
                        dependency_blocked = any(
                            resolved[value].status in {
                                "INVALID", "BLOCKED_BY_SOURCE", "BLOCKED_BY_DEPENDENCY",
                            }
                            for value in dependency_ids
                        )
                        dependency_changed = any(
                            resolved[value].status != "CURRENT" for value in dependency_ids
                        ) or any(
                            next(
                                candidate.artifact_id
                                for candidate in summaries
                                if candidate.logical_artifact_id == value
                            )
                            != next(
                                ref.artifact_id
                                for ref in loaded.recipe.source_artifacts
                                if artifact_to_logical.get(ref.artifact_id) == value
                            )
                            for value in dependency_ids
                        )
                        reasons = (change.reason,)
                        if change.status in {"INVALID_SOURCE", "IDENTITY_MISMATCH", "TRUNCATED"}:
                            status = "BLOCKED_BY_SOURCE"
                            reasons = (f"{change.status}: {change.reason}",)
                        elif dependency_blocked:
                            status = "BLOCKED_BY_DEPENDENCY"
                            reasons = ("Required Artifact dependency is invalid or blocked",)
                        elif change.status == "UNCHANGED":
                            status = "REBUILD_REQUIRED" if dependency_changed else "CURRENT"
                            if dependency_changed:
                                reasons = ("Required Artifact dependency head or currentness changed; recalculate in dependency order",)
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
                            (() if status == "CURRENT" else reasons),
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
                blockers = []
                physical_members = (tuple(ArtifactCollectionMemberV1.from_dict(record)
                                          for record in collection.value_provenance["members"])
                                    if hasattr(collection, "value_provenance") else collection.members)
                for member in physical_members:
                    try:
                        metadata = self._artifacts.load_artifact_metadata(
                            collection.market_id, member.version_key.artifact_id
                        )
                        if metadata.values_sha256 != member.values_sha256 or not self._creation._same_coverage(metadata.source_ohlcv, collection.source_ohlcv):
                            blockers.append(f"Collection member metadata differs: {member.version_key.artifact_id}")
                    except (ArtifactError, OSError, ValueError) as exc:
                        blockers.append(str(exc))
                stale = 0
                blocked = 0 if not blockers else 1
                status = "CURRENT" if not blockers else "BLOCKED_BY_DEPENDENCY"
                reasons = tuple(blockers)
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
        database_revisions,
        invalid_databases,
        sources,
        accepted_summaries,
        failures,
        cancellation_requested,
    ):
        values = []
        for database_id in sorted(database_revisions):
            self._check_reconciliation_cancelled(cancellation_requested, "before Database")
            manifest = database_revisions[database_id]
            try:
                current = sources.get(manifest.market_id)
                through = None if current is None else current.last_timestamp_ms
                newer = current is not None and through > manifest.last_timestamp_ms
                status = "UPDATE_AVAILABLE" if newer else "CURRENT"
                reasons = ("New source metadata is available; append checks run on request",) if newer else ()
                if current is None:
                    status = "SOURCE_INVALID"
                    reasons = ("Accepted source metadata is unavailable; stored snapshot remains valid",)
                elif (current.row_count < manifest.source_ohlcv.row_count
                      or current.last_timestamp_ms < manifest.source_ohlcv.last_timestamp_ms
                      or current.first_timestamp_ms != manifest.source_ohlcv.first_timestamp_ms):
                    status = "SOURCE_INVALID"
                    reasons = ("OHLCV source coverage conflict; repair or revalidate the source; stored snapshot remains valid",)
                elif newer:
                    _members, _edges, outputs = self._creation._database_output_evidence(manifest)
                    try:
                        outputs = self._creation._database_append_outputs(manifest, outputs)
                        logical_ids = tuple(dict.fromkeys(o.logical_artifact_id for o in outputs))
                    except (ArtifactError, DataManagerCreationError, OSError, ValueError) as exc:
                        logical_ids = ()
                        status = "WAITING_FOR_ARTIFACT_UPDATE"
                        reasons = (str(exc), "Stored snapshot remains valid; saved columns can be removed")
                    for logical_id in logical_ids:
                        try:
                            head = self._artifacts.load_artifact_head(manifest.market_id, logical_id)
                            metadata = self._artifacts.load_artifact_metadata(manifest.market_id, head.artifact_id)
                            if self._creation._same_coverage(metadata.source_ohlcv, current):
                                continue
                            reason = f"Artifact {logical_id} metadata does not cover the new source"
                        except (ArtifactError, OSError, ValueError) as exc:
                            reason = f"Artifact {logical_id} metadata unavailable: {exc}"
                        status = "WAITING_FOR_ARTIFACT_UPDATE"
                        reasons = (reason, "Exact append compatibility is checked on request")
                        break
                missing = 0 if current is None else max(0, current.row_count - manifest.source_ohlcv.row_count)
                values.append(DataManagerDatabaseCurrentness(
                    database_id, manifest.revision_id, manifest.market_id, status,
                    manifest.last_timestamp_ms, through, None,
                    missing, True, reasons,
                ))
            except (ArtifactError, DataManagerCreationError, OSError, ValueError) as exc:
                failures.append(f"Database {database_id}: {exc}")
                values.append(DataManagerDatabaseCurrentness(
                    database_id, manifest.revision_id, manifest.market_id, "INVALID",
                    manifest.last_timestamp_ms, None, None, 0, False, (str(exc),),
                ))
        for database_id in sorted(invalid_databases):
            definition, head, reason = invalid_databases[database_id]
            values.append(DataManagerDatabaseCurrentness(
                database_id, head.revision_id, definition.market_id, "INVALID",
                None, None, None, 0, False, (reason,),
            ))
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
        result = self._catalog.inspect_market_metadata(market)
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
        *,
        dependency_refs,
        full_fallback: bool = False,
    ) -> FinancialToolCalculationResult:
        refs_by_role = {ref.role: ref for ref in dependency_refs}

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
            from .artifact_materialization import _utc_context
            return _calculate_artifact_recipe(
                recipe,
                frame,
                tuple((ref, value) for ref, value in dependencies if value is not None),
                utc_context=(_utc_context(
                    recipe.market_id, source_change.current_source.csv_sha256, node.logical_artifact_id,
                    recipe.parameters, frame, tuple(ref.artifact_id for ref, _ in dependencies),
                ) if recipe.tool_key == "universal_trend_classifier" else None),
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
        try:
            self._require_frames_equal(old_overlap, new_overlap, "overlap")
        except DataManagerOperationError as exc:
            if not full_fallback or str(exc) != "overlap NaN-mask mismatch":
                raise
            return calculate(target_frame, dependency_frames)
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
            self._artifacts.list_managed_artifacts_metadata(collection.market_id)
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
