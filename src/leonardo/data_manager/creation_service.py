"""Canonical Data Manager creation workflows over accepted service authorities."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import StringIO

import pandas as pd

from leonardo.artifacts import (
    ArtifactError,
    ArtifactService,
    ManagedArtifactVersionKey,
    compute_logical_artifact_id,
)
from leonardo.data import MarketId
from leonardo.financial_tools import get_financial_tool_spec, resolve_output_names, resolve_parameters
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeOHLCVInputV1,
    PortableRecipeV1,
    build_portable_recipe,
)
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader

from .creation_models import (
    ArtifactCollectionDependencyV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionSelectionPlan,
    ArtifactCollectionValidation,
    BatchArtifactBranchRequest,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DatabaseDefinitionV1,
    DatabaseReadiness,
    DatabaseRevisionManifestV1,
    DatabaseSeedV1,
    DataManagerCreationError,
    deterministic_hash,
)
from .construct_batch import visible_output_names
from .construct_sources import list_construct_source_signals
from .direct_artifact import (
    DataManagerDirectArtifactSource,
    DataManagerDirectArtifactRequest,
    _build_direct_portable_recipe,
    _validate_source_roles,
)
from .creation_store import DataManagerCreationStore
from .models import (
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationResult,
)


class DataManagerCreationWorkflow:
    """Coordinate Data Manager creation while preserving canonical owners."""

    def __init__(
        self,
        *,
        store: DataManagerCreationStore,
        catalog: AcceptedDatasetCatalog | object,
        loader: HistoricalDatasetLoader | object,
        artifacts: ArtifactService | object,
        batch_materialization_planner: Callable[
            [BatchArtifactRequest, tuple[PortableRecipeV1, ...]],
            tuple[DataManagerArtifactMaterializationPlan, object],
        ],
        batch_materialization_executor: Callable[..., DataManagerArtifactMaterializationResult],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._loader = loader
        self._artifacts = artifacts
        self._plan_batch_materialization = batch_materialization_planner
        self._execute_batch_materialization = batch_materialization_executor
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def store(self) -> DataManagerCreationStore:
        return self._store

    def create_database_seed(
        self,
        market_id: MarketId,
        display_name: str,
        *,
        description: str = "",
        selected_ohlcv_columns: Sequence[str] = ("open", "high", "low", "close", "volume"),
        selected_range_start_ms: int | None = None,
        selected_range_end_ms: int | None = None,
    ) -> DatabaseSeedV1:
        source = self._artifacts.capture_accepted_source(market_id)
        dataset = self._loader.load(market_id)
        if dataset.file_sha256 != source.csv_sha256 or dataset.row_count != source.row_count:
            raise DataManagerCreationError("loaded OHLCV does not match accepted source evidence")
        start = dataset.first_timestamp_ms if selected_range_start_ms is None else selected_range_start_ms
        end = dataset.last_timestamp_ms if selected_range_end_ms is None else selected_range_end_ms
        seed = DatabaseSeedV1(
            seed_id=self._store.new_seed_id(), display_name=display_name,
            description=description, market_id=market_id, source_ohlcv=source,
            source_row_count=dataset.row_count,
            first_timestamp_ms=dataset.first_timestamp_ms,
            last_timestamp_ms=dataset.last_timestamp_ms,
            selected_ohlcv_columns=tuple(selected_ohlcv_columns),
            selected_range_start_ms=start, selected_range_end_ms=end,
            created_at_utc=self._clock(),
        )
        return self._store.save_seed(seed)

    def list_database_seeds(self) -> tuple[DatabaseSeedV1, ...]:
        return self._store.list_seeds()

    def load_database_seed(self, seed_id: str) -> DatabaseSeedV1:
        return self._store.load_seed(seed_id)

    def inspect_database_seed(self, seed_id: str) -> DatabaseSeedV1:
        return self.load_database_seed(seed_id)

    def validate_database_seed(self, seed_id: str) -> tuple[bool, tuple[str, ...]]:
        seed = self.load_database_seed(seed_id)
        blockers: list[str] = []
        try:
            current = self._artifacts.capture_accepted_source(seed.market_id)
            dataset = self._loader.load(seed.market_id)
            if current != seed.source_ohlcv:
                blockers.append("accepted OHLCV fingerprint changed")
            if dataset.file_sha256 != seed.source_ohlcv.csv_sha256:
                blockers.append("loaded OHLCV bytes changed")
            timestamps = set(dataset.ts_ms)
            if seed.selected_range_start_ms not in timestamps or seed.selected_range_end_ms not in timestamps:
                blockers.append("selected source range is no longer exact")
        except Exception as exc:
            blockers.append(f"source unavailable: {exc}")
        return not blockers, tuple(blockers)

    def delete_database_seed(self, seed_id: str) -> DatabaseSeedV1:
        return self._store.delete_seed(seed_id)

    def create_artifact_collection(
        self,
        materialization: DataManagerArtifactMaterializationResult,
        display_name: str,
        *,
        description: str = "",
        source_recipe_collection_id: str | None = None,
        source_recipe_collection_revision_id: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(materialization, DataManagerArtifactMaterializationResult):
            raise TypeError("materialization must be a DataManagerArtifactMaterializationResult")
        collection_id = self._store.new_collection_id()
        now = self._clock()
        revision = self._collection_revision_from_materialization(
            materialization, collection_id=collection_id, display_name=display_name,
            description=description, previous=None, created_at=now, revised_at=now,
            source_recipe_collection_id=source_recipe_collection_id,
            source_recipe_collection_revision_id=source_recipe_collection_revision_id,
            selected_outputs=selected_outputs,
        )
        return self._store.save_collection_revision(revision, expected_head_revision_id=None)

    def create_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        display_name: str,
        *,
        description: str = "",
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(plan, ArtifactCollectionSelectionPlan):
            raise TypeError("plan must be an ArtifactCollectionSelectionPlan")
        outputs = self._selection_outputs(plan, selected_outputs)
        now = self._clock()
        revision = self._build_collection_revision(
            collection_id=self._store.new_collection_id(),
            display_name=display_name,
            description=description,
            market_id=plan.market_id,
            roots=plan.root_logical_artifact_ids,
            supports=plan.support_logical_artifact_ids,
            members=plan.members,
            edges=plan.dependency_edges,
            selected_outputs=outputs,
            presentation_order=tuple(item.column_name for item in outputs),
            source_recipe_collection_id=None,
            source_recipe_collection_revision_id=None,
            source_ohlcv=plan.source_ohlcv,
            first_timestamp_ms=plan.first_timestamp_ms,
            last_timestamp_ms=plan.last_timestamp_ms,
            previous_revision_id=None,
            created_at_utc=now,
            revised_at_utc=now,
        )
        return self._store.save_collection_revision(
            revision, expected_head_revision_id=None
        )

    def edit_artifact_collection_from_selection(
        self,
        collection_id: str,
        plan: ArtifactCollectionSelectionPlan,
        *,
        display_name: str | None = None,
        description: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        presentation_order: Sequence[str] | None = None,
        expected_revision_id: str,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(plan, ArtifactCollectionSelectionPlan):
            raise TypeError("plan must be an ArtifactCollectionSelectionPlan")
        current = self.load_artifact_collection(collection_id)
        if current.revision_id != expected_revision_id:
            raise DataManagerCreationError(
                "Artifact Collection revision changed before Edit"
            )
        if current.market_id != plan.market_id:
            raise DataManagerCreationError(
                "Artifact Collection selection MarketId differs"
            )
        member_by_id = {
            item.version_key.logical_artifact_id: item for item in plan.members
        }
        if selected_outputs is None:
            output_values = [
                item
                for item in current.selected_outputs
                if item.logical_artifact_id in member_by_id
                and item.output_name
                in member_by_id[item.logical_artifact_id].output_names
            ]
            selected_pairs = {
                (item.logical_artifact_id, item.output_name)
                for item in output_values
            }
            old_roots = set(current.root_logical_artifact_ids)
            for logical_id in plan.root_logical_artifact_ids:
                if logical_id in old_roots:
                    continue
                for output_name in member_by_id[logical_id].output_names:
                    pair = (logical_id, output_name)
                    if pair not in selected_pairs:
                        output_values.append(
                            ArtifactCollectionOutputV1(
                                logical_id, output_name, output_name
                            )
                        )
                        selected_pairs.add(pair)
            outputs = tuple(output_values)
        else:
            outputs = tuple(selected_outputs)
        if presentation_order is None:
            columns = {item.column_name for item in outputs}
            order = tuple(
                item for item in current.presentation_order if item in columns
            )
            order = (*order, *(item.column_name for item in outputs if item.column_name not in order))
        else:
            order = tuple(presentation_order)
        revised = self._build_collection_revision(
            collection_id=current.collection_id,
            display_name=current.display_name if display_name is None else display_name,
            description=current.description if description is None else description,
            market_id=plan.market_id,
            roots=plan.root_logical_artifact_ids,
            supports=plan.support_logical_artifact_ids,
            members=plan.members,
            edges=plan.dependency_edges,
            selected_outputs=outputs,
            presentation_order=order,
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=(
                current.source_recipe_collection_revision_id
            ),
            source_ohlcv=plan.source_ohlcv,
            first_timestamp_ms=plan.first_timestamp_ms,
            last_timestamp_ms=plan.last_timestamp_ms,
            previous_revision_id=current.revision_id,
            created_at_utc=current.created_at_utc,
            revised_at_utc=self._clock(),
        )
        return self._store.save_collection_revision(
            revised, expected_head_revision_id=current.revision_id
        )

    def list_artifact_collections(self) -> tuple[ArtifactCollectionRevisionV1, ...]:
        return tuple(self._store.load_collection(item) for item in self._store.list_collection_ids())

    def list_artifact_collection_revisions(
        self, collection_id: str
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        return self._store.list_collection_revisions(collection_id)

    def load_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionRevisionV1:
        return self._store.load_collection(collection_id, revision_id)

    def inspect_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> tuple[ArtifactCollectionRevisionV1, ArtifactCollectionValidation]:
        revision = self.load_artifact_collection(collection_id, revision_id)
        return revision, self.validate_artifact_collection(collection_id, revision.revision_id)

    def revise_artifact_collection(
        self,
        collection_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        presentation_order: Sequence[str] | None = None,
        remove_root_logical_artifact_ids: Sequence[str] = (),
    ) -> ArtifactCollectionRevisionV1:
        current = self.load_artifact_collection(collection_id)
        roots = tuple(item for item in current.root_logical_artifact_ids if item not in set(remove_root_logical_artifact_ids))
        if not roots:
            raise DataManagerCreationError("Artifact Collection must retain at least one root")
        required = self._required_members(roots, current.dependency_edges)
        members = tuple(item for item in current.members if item.version_key.logical_artifact_id in required)
        supports = tuple(item for item in required if item not in roots)
        outputs = tuple(selected_outputs) if selected_outputs is not None else tuple(
            item for item in current.selected_outputs if item.logical_artifact_id in required
        )
        order = tuple(presentation_order) if presentation_order is not None else tuple(
            item for item in current.presentation_order if item in {output.column_name for output in outputs}
        )
        revised = self._build_collection_revision(
            collection_id=current.collection_id,
            display_name=current.display_name if display_name is None else display_name,
            description=current.description if description is None else description,
            market_id=current.market_id, roots=roots, supports=supports, members=members,
            edges=tuple(edge for edge in current.dependency_edges if edge.dependency_logical_artifact_id in required and edge.dependent_logical_artifact_id in required),
            selected_outputs=outputs, presentation_order=order,
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            source_ohlcv=current.source_ohlcv,
            first_timestamp_ms=current.first_timestamp_ms,
            last_timestamp_ms=current.last_timestamp_ms,
            previous_revision_id=current.revision_id,
            created_at_utc=current.created_at_utc, revised_at_utc=self._clock(),
        )
        return self._store.save_collection_revision(
            revised, expected_head_revision_id=current.revision_id
        )

    def add_collection_branches(
        self,
        collection_id: str,
        materialization: DataManagerArtifactMaterializationResult,
        *,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        current = self.load_artifact_collection(collection_id)
        if current.market_id != materialization.target_market_id or current.source_ohlcv != materialization.source_ohlcv:
            raise DataManagerCreationError("Artifact branches are incompatible with the Collection")
        branch_member_ids = {
            item.logical_artifact_id for item in materialization.managed_artifacts
        }
        branch_outputs = (
            None
            if selected_outputs is None
            else tuple(
                item
                for item in selected_outputs
                if item.logical_artifact_id in branch_member_ids
            )
            or None
        )
        branch = self._collection_revision_from_materialization(
            materialization, collection_id=current.collection_id,
            display_name=current.display_name, description=current.description,
            previous=current.revision_id, created_at=current.created_at_utc,
            revised_at=self._clock(), source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            selected_outputs=branch_outputs,
        )
        member_map = {item.version_key.logical_artifact_id: item for item in current.members}
        member_map.update({item.version_key.logical_artifact_id: item for item in branch.members})
        roots = tuple(dict.fromkeys((*current.root_logical_artifact_ids, *branch.root_logical_artifact_ids)))
        supports = tuple(item for item in dict.fromkeys((*current.support_logical_artifact_ids, *branch.support_logical_artifact_ids)) if item not in roots)
        edges = tuple(dict.fromkeys((*current.dependency_edges, *branch.dependency_edges)))
        if selected_outputs is not None:
            outputs = tuple(selected_outputs)
            order = tuple(item.column_name for item in outputs)
        else:
            outputs = tuple(
                dict.fromkeys((*current.selected_outputs, *branch.selected_outputs))
            )
            order = tuple(
                dict.fromkeys(
                    (*current.presentation_order, *(item.column_name for item in outputs))
                )
            )
        revised = self._build_collection_revision(
            collection_id=current.collection_id, display_name=current.display_name,
            description=current.description, market_id=current.market_id, roots=roots,
            supports=supports, members=tuple(member_map.values()), edges=edges,
            selected_outputs=outputs, presentation_order=order,
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            source_ohlcv=current.source_ohlcv,
            first_timestamp_ms=max(current.first_timestamp_ms, branch.first_timestamp_ms),
            last_timestamp_ms=min(current.last_timestamp_ms, branch.last_timestamp_ms),
            previous_revision_id=current.revision_id, created_at_utc=current.created_at_utc,
            revised_at_utc=self._clock(),
        )
        return self._store.save_collection_revision(revised, expected_head_revision_id=current.revision_id)

    def advance_artifact_collection(
        self,
        collection_id: str,
        materialization: DataManagerArtifactMaterializationResult,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(materialization, DataManagerArtifactMaterializationResult):
            raise TypeError(
                "materialization must be a DataManagerArtifactMaterializationResult"
            )
        current = self.load_artifact_collection(collection_id)
        if current.market_id != materialization.target_market_id:
            raise DataManagerCreationError(
                "materialization MarketId does not match Artifact Collection"
            )
        candidate = self._collection_revision_from_materialization(
            materialization,
            collection_id=current.collection_id,
            display_name=current.display_name,
            description=current.description,
            previous=current.revision_id,
            created_at=current.created_at_utc,
            revised_at=self._clock(),
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=(
                current.source_recipe_collection_revision_id
            ),
            selected_outputs=current.selected_outputs,
        )
        if set(candidate.root_logical_artifact_ids) != set(
            current.root_logical_artifact_ids
        ):
            raise DataManagerCreationError("Artifact Collection roots cannot change")
        if set(candidate.support_logical_artifact_ids) != set(
            current.support_logical_artifact_ids
        ):
            raise DataManagerCreationError("Artifact Collection supports cannot change")
        if {item.version_key.logical_artifact_id for item in candidate.members} != {
            item.version_key.logical_artifact_id for item in current.members
        }:
            raise DataManagerCreationError("Artifact Collection member set cannot change")
        if candidate.dependency_edges != current.dependency_edges:
            raise DataManagerCreationError(
                "Artifact Collection dependency edges cannot change"
            )
        if candidate.selected_outputs != current.selected_outputs:
            raise DataManagerCreationError(
                "Artifact Collection selected outputs cannot change"
            )
        if candidate.presentation_order != current.presentation_order:
            raise DataManagerCreationError(
                "Artifact Collection presentation order cannot change"
            )
        if (
            candidate.source_recipe_collection_id
            != current.source_recipe_collection_id
            or candidate.source_recipe_collection_revision_id
            != current.source_recipe_collection_revision_id
        ):
            raise DataManagerCreationError(
                "Artifact Collection Recipe Collection references cannot change"
            )
        return self._store.save_collection_revision(
            candidate,
            expected_head_revision_id=current.revision_id,
        )

    def validate_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionValidation:
        revision = self.load_artifact_collection(collection_id, revision_id)
        blockers: list[str] = []
        try:
            if self._artifacts.capture_accepted_source(revision.market_id) != revision.source_ohlcv:
                blockers.append("accepted OHLCV fingerprint changed")
        except Exception as exc:
            blockers.append(f"accepted OHLCV unavailable: {exc}")
        frames: dict[str, pd.DataFrame] = {}
        for member in revision.members:
            try:
                loaded = self._artifacts.load_artifact_by_id(
                    revision.market_id, member.version_key.artifact_id
                )
                metadata = loaded.metadata
                if metadata.values_sha256 != member.values_sha256:
                    blockers.append(f"Artifact payload changed: {member.version_key.logical_artifact_id}")
                if metadata.source_ohlcv != revision.source_ohlcv:
                    blockers.append(f"Artifact source changed: {member.version_key.logical_artifact_id}")
                frames[member.version_key.logical_artifact_id] = loaded.frame
            except Exception as exc:
                blockers.append(f"Artifact unavailable {member.version_key.logical_artifact_id}: {exc}")
        first, last, rows = self._usable_coverage(revision, frames, blockers)
        return ArtifactCollectionValidation(
            revision.collection_id, revision.revision_id, not blockers, not blockers and rows > 0,
            tuple(dict.fromkeys(blockers)), first, last, rows,
            len(revision.selected_outputs),
        )

    def plan_batch_artifacts(self, request: BatchArtifactRequest) -> BatchArtifactPlan:
        if not isinstance(request, BatchArtifactRequest):
            raise TypeError("request must be a BatchArtifactRequest")
        if request.destination == "collection_revision":
            collection = self.load_artifact_collection(request.collection_id)
            if (
                collection.market_id != request.market_id
                or collection.source_ohlcv != request.expected_source_ohlcv
            ):
                raise DataManagerCreationError(
                    "Batch destination is incompatible with the selected MarketId "
                    "or OHLCV fingerprint"
                )
        branch_recipes = self._validated_batch_recipes(request)
        try:
            materialization, _members = self._plan_batch_materialization(
                request, branch_recipes
            )
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc
        return self._project_batch_plan(request, branch_recipes, materialization)

    def execute_batch_artifacts(
        self,
        plan: BatchArtifactPlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        collection_display_name: str = "Batch Artifact Collection",
    ) -> tuple[DataManagerArtifactMaterializationResult, ArtifactCollectionRevisionV1 | None]:
        if not isinstance(plan, BatchArtifactPlan) or plan.blocked:
            raise DataManagerCreationError("blocked batch plan cannot execute")
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Artifact validation")
        recipes = self._validated_batch_recipes(plan.request)
        try:
            materialization_plan, members = self._plan_batch_materialization(
                plan.request, recipes
            )
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc
        if self._project_batch_plan(
            plan.request, recipes, materialization_plan
        ) != plan:
            raise DataManagerCreationError("batch Artifact graph changed before execution")
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Artifact publication")
        try:
            result = self._execute_batch_materialization(
                materialization_plan, members, progress=progress,
                cancellation_requested=cancelled, before_publish=None,
            )
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Collection mutation")
        collection = None
        selected_outputs = self._batch_collection_outputs(plan, recipes)
        if plan.request.destination == "new_collection":
            collection = self.create_artifact_collection(
                result,
                collection_display_name,
                selected_outputs=selected_outputs,
            )
        elif plan.request.destination == "collection_revision":
            collection = self.add_collection_branches(
                plan.request.collection_id,
                result,
                selected_outputs=selected_outputs,
            )
        return result, collection

    def assess_database_readiness(
        self, seed_id: str, collection_id: str, collection_revision_id: str | None = None
    ) -> DatabaseReadiness:
        seed = self.load_database_seed(seed_id)
        collection = self.load_artifact_collection(collection_id, collection_revision_id)
        blockers: list[str] = []
        seed_valid, seed_blockers = self.validate_database_seed(seed_id)
        if not seed_valid:
            blockers.extend(seed_blockers)
        validation = self.validate_artifact_collection(collection_id, collection.revision_id)
        blockers.extend(validation.blockers)
        if seed.market_id != collection.market_id:
            blockers.append("Seed and Artifact Collection MarketId differ")
        if seed.source_ohlcv != collection.source_ohlcv:
            blockers.append("Seed and Artifact Collection OHLCV fingerprints differ")
        columns = ("ts_ms", *seed.selected_ohlcv_columns, *collection.presentation_order)
        if len(columns) != len(set(columns)):
            blockers.append("Database output-column collision")
        first = None
        last = None
        rows = 0
        warmup = 0
        if not blockers:
            frame, warmup = self._database_frame(seed, collection)
            if frame.empty:
                blockers.append("Database has no common usable rows")
            else:
                first = int(frame["ts_ms"].iloc[0])
                last = int(frame["ts_ms"].iloc[-1])
                rows = len(frame)
        return DatabaseReadiness(
            seed.seed_id, collection.collection_id, collection.revision_id,
            not blockers, tuple(dict.fromkeys(blockers)), first, last, rows,
            len(columns), tuple(columns), warmup,
        )

    def build_database_revision(
        self,
        seed_id: str,
        collection_id: str,
        *,
        collection_revision_id: str | None = None,
        database_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseRevisionManifestV1:
        cancelled = cancellation_requested or (lambda: False)
        seed = self.load_database_seed(seed_id)
        collection = self.load_artifact_collection(collection_id, collection_revision_id)
        readiness = self.assess_database_readiness(seed_id, collection_id, collection.revision_id)
        if not readiness.ready:
            raise DataManagerCreationError("Database is not ready: " + "; ".join(readiness.blockers))
        if cancelled():
            raise DataManagerCreationError("Database build cancelled before materialization")
        frame, _warmup = self._database_frame(seed, collection)
        values = frame.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
        values_hash = sha256(values).hexdigest()
        exact_database_id = database_id or self._store.new_database_id()
        previous = None
        if database_id is not None:
            previous = self._store.load_database_head(database_id).revision_id
            definition = self._store.load_database_definition(database_id)
            if definition.seed_id != seed.seed_id or definition.market_id != seed.market_id:
                raise DataManagerCreationError(
                    "Database definition cannot change Seed or MarketId"
                )
        else:
            definition = DatabaseDefinitionV1(
                exact_database_id,
                seed.display_name if display_name is None else display_name,
                seed.description if description is None else description,
                seed.market_id,
                seed.seed_id,
                self._clock(),
            )
        now = self._clock()
        members = collection.members
        mapping = {item: item for item in readiness.column_names}
        payload = {
            "schema_version": "1.0", "object_type": "database_revision",
            "database_id": exact_database_id,
            "display_name": definition.display_name,
            "description": definition.description,
            "seed_id": seed.seed_id,
            "market_id": {"exchange": seed.market_id.exchange, "market_type": seed.market_id.market_type,
                          "symbol": seed.market_id.symbol, "timeframe": seed.market_id.timeframe},
            "source_ohlcv": seed.source_ohlcv.to_dict(),
            "collection_id": collection.collection_id,
            "collection_revision_id": collection.revision_id,
            "collection_manifest_hash": collection.revision_id,
            "artifact_version_keys": [{"logical_artifact_id": item.version_key.logical_artifact_id,
                                        "artifact_id": item.version_key.artifact_id} for item in members],
            "artifact_payload_hashes": [item.values_sha256 for item in members],
            "portable_recipe_ids": list(collection.source_portable_recipe_ids),
            "column_mapping": mapping,
            "first_timestamp_ms": readiness.first_usable_timestamp_ms,
            "last_timestamp_ms": readiness.last_usable_timestamp_ms,
            "row_count": readiness.row_count, "column_count": readiness.column_count,
            "values_sha256": values_hash, "previous_revision_id": previous,
            "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        }
        revision_id = deterministic_hash(payload)
        manifest = DatabaseRevisionManifestV1(
            database_id=exact_database_id, revision_id=revision_id,
            display_name=payload["display_name"], description=payload["description"],
            seed_id=seed.seed_id, market_id=seed.market_id, source_ohlcv=seed.source_ohlcv,
            collection_id=collection.collection_id, collection_revision_id=collection.revision_id,
            collection_manifest_hash=collection.revision_id,
            artifact_version_keys=tuple(item.version_key for item in members),
            artifact_payload_hashes=tuple(item.values_sha256 for item in members),
            portable_recipe_ids=collection.source_portable_recipe_ids,
            column_mapping=mapping, first_timestamp_ms=readiness.first_usable_timestamp_ms,
            last_timestamp_ms=readiness.last_usable_timestamp_ms,
            row_count=readiness.row_count, column_count=readiness.column_count,
            values_sha256=values_hash, previous_revision_id=previous,
            created_at_utc=now,
        )
        if cancelled():
            raise DataManagerCreationError("Database build cancelled before publication")

        def publication_gate() -> None:
            if cancelled():
                raise DataManagerCreationError("Database build cancelled before publication")
            if self._artifacts.capture_accepted_source(seed.market_id) != seed.source_ohlcv:
                raise DataManagerCreationError("OHLCV changed before Database publication")
            if before_publish is not None:
                before_publish()

        return self._store.publish_database_revision(
            definition, manifest, values, expected_head_revision_id=previous,
            before_publish=publication_gate,
        )

    def list_database_ids(self) -> tuple[str, ...]:
        return self._store.list_database_ids()

    def load_database_definition(self, database_id: str) -> DatabaseDefinitionV1:
        return self._store.load_database_definition(database_id)

    def list_database_revisions(self, database_id: str) -> tuple[DatabaseRevisionManifestV1, ...]:
        return self._store.list_database_revisions(database_id)

    def load_database_revision(self, database_id: str, revision_id: str | None = None):
        loaded = self._store.load_database_revision(database_id, revision_id)
        if sha256(loaded.values_csv).hexdigest() != loaded.manifest.values_sha256:
            raise DataManagerCreationError("Database values payload hash disagrees")
        return loaded

    def _collection_revision_from_materialization(
        self, materialization: DataManagerArtifactMaterializationResult, *,
        collection_id: str, display_name: str, description: str,
        previous: str | None, created_at: datetime, revised_at: datetime,
        source_recipe_collection_id: str | None,
        source_recipe_collection_revision_id: str | None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
    ) -> ArtifactCollectionRevisionV1:
        artifact_by_id = {item.artifact_id: item for item in materialization.managed_artifacts}
        logical_by_artifact = {item.artifact_id: item.logical_artifact_id for item in materialization.managed_artifacts}
        members: list[ArtifactCollectionMemberV1] = []
        edges: list[ArtifactCollectionDependencyV1] = []
        for entry in materialization.managed_artifacts:
            loaded = self._artifacts.load_artifact_by_id(materialization.target_market_id, entry.artifact_id)
            metadata = loaded.metadata
            members.append(ArtifactCollectionMemberV1(
                ManagedArtifactVersionKey(entry.logical_artifact_id, entry.artifact_id),
                entry.portable_recipe_id, entry.tool_key, entry.kind, entry.output_names,
                metadata.values_sha256,
            ))
            for ref in metadata.recipe.source_artifacts:
                dependency_id = logical_by_artifact.get(ref.artifact_id)
                if dependency_id is None:
                    raise DataManagerCreationError("materialization result omits a supporting dependency")
                edges.append(ArtifactCollectionDependencyV1(
                    dependency_id, entry.logical_artifact_id, ref.role, ref.output_name
                ))
        if selected_outputs is None:
            outputs: list[ArtifactCollectionOutputV1] = []
            used: set[str] = set()
            for logical_id in materialization.root_logical_artifact_ids:
                entry = next(item for item in materialization.managed_artifacts if item.logical_artifact_id == logical_id)
                for output in entry.output_names:
                    column = output
                    if column in used:
                        raise DataManagerCreationError(
                            f"selected output-column collision requires explicit mapping: {column}"
                        )
                    used.add(column)
                    outputs.append(ArtifactCollectionOutputV1(logical_id, output, column))
        else:
            outputs = list(selected_outputs)
        return self._build_collection_revision(
            collection_id=collection_id, display_name=display_name, description=description,
            market_id=materialization.target_market_id,
            roots=materialization.root_logical_artifact_ids,
            supports=materialization.support_logical_artifact_ids,
            members=tuple(members), edges=tuple(edges), selected_outputs=tuple(outputs),
            presentation_order=tuple(item.column_name for item in outputs),
            source_recipe_collection_id=source_recipe_collection_id,
            source_recipe_collection_revision_id=source_recipe_collection_revision_id,
            source_ohlcv=materialization.source_ohlcv,
            first_timestamp_ms=max(item.first_timestamp_ms for item in materialization.managed_artifacts),
            last_timestamp_ms=min(item.last_timestamp_ms for item in materialization.managed_artifacts),
            previous_revision_id=previous, created_at_utc=created_at, revised_at_utc=revised_at,
        )

    @staticmethod
    def _selection_outputs(
        plan: ArtifactCollectionSelectionPlan,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
    ) -> tuple[ArtifactCollectionOutputV1, ...]:
        if selected_outputs is not None:
            return tuple(selected_outputs)
        member_by_id = {
            item.version_key.logical_artifact_id: item for item in plan.members
        }
        outputs: list[ArtifactCollectionOutputV1] = []
        used: set[str] = set()
        for logical_id in plan.root_logical_artifact_ids:
            for output_name in member_by_id[logical_id].output_names:
                if output_name in used:
                    raise DataManagerCreationError(
                        "selected output-column collision requires explicit mapping: "
                        f"{output_name}"
                    )
                used.add(output_name)
                outputs.append(
                    ArtifactCollectionOutputV1(
                        logical_id, output_name, output_name
                    )
                )
        return tuple(outputs)

    def _build_collection_revision(self, **values) -> ArtifactCollectionRevisionV1:
        payload = {
            "schema_version": "1.0", "object_type": "artifact_collection_revision",
            "collection_id": values["collection_id"], "display_name": values["display_name"],
            "description": values["description"],
            "market_id": {"exchange": values["market_id"].exchange, "market_type": values["market_id"].market_type,
                          "symbol": values["market_id"].symbol, "timeframe": values["market_id"].timeframe},
            "root_logical_artifact_ids": list(values["roots"]),
            "support_logical_artifact_ids": list(values["supports"]),
            "members": [item.to_dict() for item in values["members"]],
            "dependency_edges": [item.to_dict() for item in values["edges"]],
            "selected_outputs": [item.to_dict() for item in values["selected_outputs"]],
            "presentation_order": list(values["presentation_order"]),
            "source_portable_recipe_ids": sorted({item.portable_recipe_id for item in values["members"]}),
            "source_recipe_collection_id": values["source_recipe_collection_id"],
            "source_recipe_collection_revision_id": values["source_recipe_collection_revision_id"],
            "source_ohlcv": values["source_ohlcv"].to_dict(),
            "first_timestamp_ms": values["first_timestamp_ms"],
            "last_timestamp_ms": values["last_timestamp_ms"],
            "validation_state": "valid", "database_ready": True,
            "previous_revision_id": values["previous_revision_id"],
            "created_at_utc": values["created_at_utc"].isoformat().replace("+00:00", "Z"),
            "revised_at_utc": values["revised_at_utc"].isoformat().replace("+00:00", "Z"),
        }
        return ArtifactCollectionRevisionV1(
            collection_id=values["collection_id"], revision_id=deterministic_hash(payload),
            display_name=values["display_name"], description=values["description"],
            market_id=values["market_id"], root_logical_artifact_ids=tuple(values["roots"]),
            support_logical_artifact_ids=tuple(values["supports"]), members=tuple(values["members"]),
            dependency_edges=tuple(values["edges"]), selected_outputs=tuple(values["selected_outputs"]),
            presentation_order=tuple(values["presentation_order"]),
            source_portable_recipe_ids=tuple(payload["source_portable_recipe_ids"]),
            source_recipe_collection_id=values["source_recipe_collection_id"],
            source_recipe_collection_revision_id=values["source_recipe_collection_revision_id"],
            source_ohlcv=values["source_ohlcv"], first_timestamp_ms=values["first_timestamp_ms"],
            last_timestamp_ms=values["last_timestamp_ms"], validation_state="valid",
            database_ready=True, previous_revision_id=values["previous_revision_id"],
            created_at_utc=values["created_at_utc"], revised_at_utc=values["revised_at_utc"],
        )

    def _validated_batch_recipes(
        self, request: BatchArtifactRequest
    ) -> tuple[PortableRecipeV1, ...]:
        current_source = self._artifacts.capture_accepted_source(request.market_id)
        if current_source != request.expected_source_ohlcv:
            raise DataManagerCreationError(
                "accepted OHLCV source changed after Batch Preview"
            )
        try:
            catalogue = {
                (
                    item.logical_artifact_id,
                    item.artifact_id,
                    item.output_name,
                ): item
                for item in list_construct_source_signals(
                    self._artifacts, request.market_id
                )
                if item.source_ohlcv == current_source
            }
        except (ArtifactError, OSError, ValueError) as exc:
            raise DataManagerCreationError(
                f"Construct Source Catalogue is unavailable: {exc}"
            ) from exc
        managed = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts(request.market_id)
        }
        recipes: list[PortableRecipeV1] = []
        for index, branch in enumerate(request.branches, start=1):
            source_recipe_ids: dict[str, str] = {}
            for source in branch.sources:
                if source.source_kind == "current_ohlcv":
                    if (
                        source.market_id != request.market_id
                        or source.source_ohlcv != request.expected_source_ohlcv
                    ):
                        raise DataManagerCreationError(
                            f"branch {index}: current OHLCV source identity changed"
                        )
                    continue
                identity = (
                    source.logical_artifact_id,
                    source.artifact_id,
                    source.output_name,
                )
                admitted = catalogue.get(identity)
                if admitted is None:
                    raise DataManagerCreationError(
                        f"branch {index}: frozen source is no longer admitted"
                    )
                if admitted.source_ohlcv != request.expected_source_ohlcv:
                    raise DataManagerCreationError(
                        f"branch {index}: source OHLCV fingerprint changed"
                    )
                summary = managed.get(source.logical_artifact_id)
                if summary is None or not summary.valid:
                    raise DataManagerCreationError(
                        f"branch {index}: source Artifact is unavailable or invalid"
                    )
                if summary.artifact_id != source.artifact_id:
                    raise DataManagerCreationError(
                        f"branch {index}: source Artifact head changed"
                    )
                if source.output_name not in summary.output_names:
                    raise DataManagerCreationError(
                        f"branch {index}: selected source output disappeared"
                    )
                loaded = self._artifacts.load_artifact_by_id(
                    request.market_id, source.artifact_id
                )
                if loaded.metadata.source_ohlcv != request.expected_source_ohlcv:
                    raise DataManagerCreationError(
                        f"branch {index}: source Artifact OHLCV changed"
                    )
                if source.output_name not in loaded.metadata.recipe.output_names:
                    raise DataManagerCreationError(
                        f"branch {index}: selected source output disappeared"
                    )
                source_recipe_ids[source.role] = summary.portable_recipe_id
            recipe = self._build_batch_portable_recipe(
                request,
                branch,
                source_recipe_ids,
            )
            if branch.requested_outputs != visible_output_names(
                branch.tool_key, branch.parameters, branch.sources
            ):
                raise DataManagerCreationError(
                    f"branch {index}: requested outputs do not match canonical visible outputs"
                )
            recipes.append(recipe)
        if (
            self._artifacts.capture_accepted_source(request.market_id)
            != request.expected_source_ohlcv
        ):
            raise DataManagerCreationError(
                "accepted OHLCV source changed during batch validation"
            )
        return tuple(recipes)

    @staticmethod
    def _build_batch_portable_recipe(
        request: BatchArtifactRequest,
        branch: BatchArtifactBranchRequest,
        source_recipe_ids: Mapping[str, str],
    ) -> PortableRecipeV1:
        artifact_sources = tuple(
            source for source in branch.sources if source.source_kind == "artifact"
        )
        raw_sources = tuple(
            source
            for source in branch.sources
            if source.source_kind == "current_ohlcv"
        )
        if not raw_sources:
            direct_sources = tuple(
                DataManagerDirectArtifactSource(
                    source.role,
                    source.logical_artifact_id,
                    source.artifact_id,
                    source.output_name,
                )
                for source in artifact_sources
            )
            direct_request = DataManagerDirectArtifactRequest(
                market_id=request.market_id,
                expected_source_ohlcv=request.expected_source_ohlcv,
                tool_key=branch.tool_key,
                parameters=branch.parameters,
                sources=direct_sources,
            )
            return _build_direct_portable_recipe(
                direct_request, source_recipe_ids
            )

        spec = get_financial_tool_spec(branch.tool_key)
        roles = tuple(source.role for source in branch.sources)
        _validate_source_roles(spec.key, spec.kind, roles)
        resolved = dict(resolve_parameters(spec.key, branch.parameters))
        naming = dict(resolved)
        bound_names = {
            source.role: source.column
            if source.source_kind == "current_ohlcv"
            else f"__research_{source.role}"
            for source in branch.sources
        }
        if spec.key in {"derivative", "angle"}:
            naming["source"] = bound_names["source"]
        elif spec.key == "delta":
            naming.update(fast=bound_names["fast"], slow=bound_names["slow"])
        elif spec.key in {"braids", "braid_instability"}:
            naming.update(
                fast=bound_names["fast"],
                mid=bound_names["mid"],
                slow=bound_names["slow"],
            )
        elif spec.key == "trap_area":
            naming.update(fast=bound_names["fast"], slow=bound_names["slow"])
            if "mid" in roles:
                naming["mid"] = bound_names["mid"]
            else:
                naming.pop("mid", None)
        elif spec.key in {"percent_span_angle", "angle_momentum"}:
            naming["source_columns"] = ",".join(
                bound_names[f"source_{index}"]
                for index in range(1, len(roles) + 1)
            )
        dependencies = tuple(
            PortableRecipeDependencyV1(
                source.role,
                source_recipe_ids[source.role],
                source.output_name,
            )
            for source in artifact_sources
        )
        ohlcv_inputs = tuple(
            PortableRecipeOHLCVInputV1(source.role, source.column)
            for source in raw_sources
        )
        return build_portable_recipe(
            tool_key=spec.key,
            kind=spec.kind,
            parameters=resolved,
            output_names=resolve_output_names(spec.key, naming),
            ohlcv_inputs=ohlcv_inputs,
            dependencies=dependencies,
        )

    def _project_batch_plan(
        self,
        request: BatchArtifactRequest,
        recipes: tuple[PortableRecipeV1, ...],
        materialization: DataManagerArtifactMaterializationPlan,
    ) -> BatchArtifactPlan:
        branch_recipe_ids = tuple(recipe.recipe_id for recipe in recipes)
        recipe_ids = tuple(dict.fromkeys(branch_recipe_ids))
        node_by_recipe = {
            node.portable_recipe_id: node for node in materialization.nodes
        }
        branch_nodes = tuple(node_by_recipe[item] for item in branch_recipe_ids)
        branch_reuse = tuple(
            node.status == "REUSE_CURRENT" for node in branch_nodes
        )
        new_recipe_ids = tuple(
            recipe_id
            for recipe_id in recipe_ids
            if node_by_recipe[recipe_id].status != "REUSE_CURRENT"
        )
        reusable_recipe_ids = tuple(
            recipe_id
            for recipe_id in recipe_ids
            if node_by_recipe[recipe_id].status == "REUSE_CURRENT"
        )
        new_logical_ids = tuple(
            node_by_recipe[item].logical_artifact_id for item in new_recipe_ids
        )
        reusable_logical_ids = tuple(
            node_by_recipe[item].logical_artifact_id
            for item in reusable_recipe_ids
        )
        collisions = self._batch_output_collisions(
            request,
            recipes,
            tuple(node.logical_artifact_id for node in branch_nodes),
        )
        return BatchArtifactPlan(
            request=request,
            branch_recipe_ids=branch_recipe_ids,
            branch_reuse_current=branch_reuse,
            recipe_ids=recipe_ids,
            dependency_edges=tuple(
                (
                    edge.dependency_recipe_id,
                    edge.dependent_recipe_id,
                    edge.role,
                    edge.output_name,
                )
                for edge in materialization.dependency_edges
            ),
            execution_stages=materialization.execution_stages,
            new_recipe_ids=new_recipe_ids,
            reusable_recipe_ids=reusable_recipe_ids,
            new_logical_artifact_ids=new_logical_ids,
            reusable_logical_artifact_ids=reusable_logical_ids,
            naming_collisions=collisions,
            unsupported_combinations=(),
            blockers=(),
        )

    def _batch_output_collisions(
        self,
        request: BatchArtifactRequest,
        recipes: Sequence[PortableRecipeV1],
        logical_ids: Sequence[str],
    ) -> tuple[str, ...]:
        if request.destination == "individual":
            return ()
        owners: dict[str, tuple[str, str]] = {}
        if request.destination == "collection_revision":
            current = self.load_artifact_collection(request.collection_id)
            owners.update(
                {
                    item.column_name: (
                        item.logical_artifact_id,
                        item.output_name,
                    )
                    for item in current.selected_outputs
                }
            )
        collisions: list[str] = []
        for branch, recipe, logical_id in zip(
            request.branches, recipes, logical_ids, strict=True
        ):
            for output, column in zip(
                recipe.output_names, branch.requested_outputs, strict=True
            ):
                owner = (logical_id, output)
                previous = owners.setdefault(column, owner)
                if previous != owner and column not in collisions:
                    collisions.append(column)
        return tuple(collisions)

    def _batch_collection_outputs(
        self,
        plan: BatchArtifactPlan,
        recipes: Sequence[PortableRecipeV1],
    ) -> tuple[ArtifactCollectionOutputV1, ...] | None:
        if plan.request.destination == "individual":
            return None
        outputs: list[ArtifactCollectionOutputV1] = []
        seen: set[tuple[str, str, str]] = set()
        if plan.request.destination == "collection_revision":
            current = self.load_artifact_collection(plan.request.collection_id)
            for item in current.selected_outputs:
                identity = (
                    item.logical_artifact_id,
                    item.output_name,
                    item.column_name,
                )
                if identity not in seen:
                    seen.add(identity)
                    outputs.append(item)
        for branch, recipe in zip(plan.request.branches, recipes, strict=True):
            logical_id = compute_logical_artifact_id(
                plan.request.market_id, recipe.recipe_id
            )
            for output, column in zip(
                recipe.output_names, branch.requested_outputs, strict=True
            ):
                identity = (logical_id, output, column)
                if identity not in seen:
                    seen.add(identity)
                    outputs.append(
                        ArtifactCollectionOutputV1(logical_id, output, column)
                    )
        return tuple(outputs)

    @staticmethod
    def _required_members(
        roots: Sequence[str], edges: Sequence[ArtifactCollectionDependencyV1]
    ) -> set[str]:
        required = set(roots)
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if edge.dependent_logical_artifact_id in required and edge.dependency_logical_artifact_id not in required:
                    required.add(edge.dependency_logical_artifact_id)
                    changed = True
        return required

    @staticmethod
    def _usable_coverage(
        collection: ArtifactCollectionRevisionV1,
        frames: Mapping[str, pd.DataFrame],
        blockers: list[str],
    ) -> tuple[int | None, int | None, int]:
        aligned: pd.DataFrame | None = None
        for selected in collection.selected_outputs:
            frame = frames.get(selected.logical_artifact_id)
            if frame is None:
                continue
            if "ts_ms" not in frame or selected.output_name not in frame:
                blockers.append(f"selected output unavailable: {selected.column_name}")
                continue
            values = frame[["ts_ms", selected.output_name]].rename(columns={selected.output_name: selected.column_name})
            if values["ts_ms"].duplicated().any() or not values["ts_ms"].is_monotonic_increasing:
                blockers.append(f"Artifact timestamps invalid: {selected.column_name}")
                continue
            aligned = values if aligned is None else aligned.merge(values, on="ts_ms", how="inner", validate="one_to_one")
        if aligned is None or aligned.empty:
            return None, None, 0
        mask = aligned[list(collection.presentation_order)].notna().all(axis=1)
        usable = aligned.loc[mask]
        if usable.empty:
            return None, None, 0
        return int(usable["ts_ms"].iloc[0]), int(usable["ts_ms"].iloc[-1]), len(usable)

    def _database_frame(
        self, seed: DatabaseSeedV1, collection: ArtifactCollectionRevisionV1
    ) -> tuple[pd.DataFrame, int]:
        dataset = self._loader.load(seed.market_id)
        frame = pd.DataFrame({
            "ts_ms": dataset.ts_ms, "open": dataset.open, "high": dataset.high,
            "low": dataset.low, "close": dataset.close, "volume": dataset.volume,
        })
        frame = frame.loc[
            frame["ts_ms"].between(seed.selected_range_start_ms, seed.selected_range_end_ms),
            ["ts_ms", *seed.selected_ohlcv_columns],
        ].copy()
        member_by_id = {item.version_key.logical_artifact_id: item for item in collection.members}
        for output in collection.selected_outputs:
            member = member_by_id[output.logical_artifact_id]
            loaded = self._artifacts.load_artifact_by_id(seed.market_id, member.version_key.artifact_id)
            values = loaded.frame[["ts_ms", output.output_name]].rename(columns={output.output_name: output.column_name})
            frame = frame.merge(values, on="ts_ms", how="inner", validate="one_to_one")
        mask = frame[list(collection.presentation_order)].notna().all(axis=1)
        warmup = int((~mask).sum())
        frame = frame.loc[mask, ["ts_ms", *seed.selected_ohlcv_columns, *collection.presentation_order]].reset_index(drop=True)
        if frame["ts_ms"].duplicated().any() or not frame["ts_ms"].is_monotonic_increasing:
            raise DataManagerCreationError("Database timestamps must be monotonic and unique")
        return frame, warmup
