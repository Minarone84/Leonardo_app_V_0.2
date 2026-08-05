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
    ArtifactService,
    ManagedArtifactVersionKey,
    compute_logical_artifact_id,
)
from leonardo.data import MarketId
from leonardo.financial_tools import (
    get_financial_tool_spec,
    resolve_output_names,
    resolve_parameters,
)
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeGraphPlanner,
    PortableRecipeStore,
    PortableRecipeV1,
    build_portable_recipe,
)
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader

from .creation_models import (
    ArtifactCollectionDependencyV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionValidation,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DatabaseDefinitionV1,
    DatabaseReadiness,
    DatabaseRevisionManifestV1,
    DatabaseSeedV1,
    DataManagerCreationError,
    deterministic_hash,
)
from .creation_store import DataManagerCreationStore
from .models import (
    DataManagerArtifactMaterializationRequest,
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
        portable_recipes: PortableRecipeStore,
        recipe_planner: PortableRecipeGraphPlanner,
        materialization_planner: Callable[[DataManagerArtifactMaterializationRequest], object],
        materialization_executor: Callable[..., DataManagerArtifactMaterializationResult],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._loader = loader
        self._artifacts = artifacts
        self._portable_recipes = portable_recipes
        self._recipe_planner = recipe_planner
        self._plan_materialization = materialization_planner
        self._execute_materialization = materialization_executor
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
        branch = self._collection_revision_from_materialization(
            materialization, collection_id=current.collection_id,
            display_name=current.display_name, description=current.description,
            previous=current.revision_id, created_at=current.created_at_utc,
            revised_at=self._clock(), source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            selected_outputs=selected_outputs,
        )
        member_map = {item.version_key.logical_artifact_id: item for item in current.members}
        member_map.update({item.version_key.logical_artifact_id: item for item in branch.members})
        roots = tuple(dict.fromkeys((*current.root_logical_artifact_ids, *branch.root_logical_artifact_ids)))
        supports = tuple(item for item in dict.fromkeys((*current.support_logical_artifact_ids, *branch.support_logical_artifact_ids)) if item not in roots)
        edges = tuple(dict.fromkeys((*current.dependency_edges, *branch.dependency_edges)))
        outputs = tuple(selected_outputs) if selected_outputs is not None else tuple(
            dict.fromkeys((*current.selected_outputs, *branch.selected_outputs))
        )
        order = tuple(dict.fromkeys((*current.presentation_order, *(item.column_name for item in outputs))))
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
        existing = {item.logical_artifact_id: item for item in self._artifacts.list_managed_artifacts(request.market_id)}
        recipes: dict[str, PortableRecipeV1] = {}
        unsupported: list[str] = []
        collisions: list[str] = []
        requested_columns: list[str] = []
        for index, branch in enumerate(request.branches, start=1):
            source = existing.get(branch.source_logical_artifact_id)
            if source is None or not source.valid:
                unsupported.append(f"branch {index}: source Artifact is unavailable")
                continue
            if branch.source_output not in source.output_names:
                unsupported.append(f"branch {index}: source output is unavailable")
                continue
            try:
                recipe = self._build_batch_recipe(branch, source.portable_recipe_id, source.output_names)
                visible_outputs = self._batch_visible_output_names(branch)
                if tuple(branch.requested_outputs) not in {
                    recipe.output_names,
                    visible_outputs,
                }:
                    unsupported.append(f"branch {index}: requested outputs do not match canonical outputs")
                    continue
                recipes[recipe.recipe_id] = recipe
                requested_columns.extend(recipe.output_names)
            except (DataManagerCreationError, ValueError, KeyError) as exc:
                unsupported.append(f"branch {index}: {exc}")
        for name in requested_columns:
            if requested_columns.count(name) > 1 and name not in collisions:
                collisions.append(name)
        recipe_ids = tuple(recipes)
        if recipes:
            graph = self._recipe_planner.plan(recipe_ids, recipes=recipes)
            edges = tuple((item.dependency_recipe_id, item.dependent_recipe_id, item.role, item.output_name) for item in graph.dependency_edges)
            stages = graph.execution_stages
        else:
            edges, stages = (), ()
        existing_recipe_ids = {item.recipe_id for item in self._portable_recipes.list_recipe_summaries() if item.valid}
        new_recipe_ids = tuple(item for item in recipe_ids if item not in existing_recipe_ids)
        reusable_recipe_ids = tuple(item for item in recipe_ids if item in existing_recipe_ids)
        logical_ids = tuple(compute_logical_artifact_id(request.market_id, item) for item in recipe_ids)
        current_ids = {item.logical_artifact_id for item in existing.values() if item.valid}
        blockers = tuple(unsupported)
        return BatchArtifactPlan(
            request=request, recipe_ids=recipe_ids, dependency_edges=edges,
            execution_stages=stages, new_recipe_ids=new_recipe_ids,
            reusable_recipe_ids=reusable_recipe_ids,
            new_logical_artifact_ids=tuple(item for item in logical_ids if item not in current_ids),
            reusable_logical_artifact_ids=tuple(item for item in logical_ids if item in current_ids),
            naming_collisions=tuple(collisions), unsupported_combinations=tuple(unsupported),
            blockers=blockers,
        )

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
            raise DataManagerCreationError("batch cancelled before Recipe persistence")
        existing = {item.logical_artifact_id: item for item in self._artifacts.list_managed_artifacts(plan.request.market_id)}
        recipes: list[PortableRecipeV1] = []
        for branch in plan.request.branches:
            source = existing[branch.source_logical_artifact_id]
            recipe = self._build_batch_recipe(branch, source.portable_recipe_id, source.output_names)
            self._portable_recipes.save_recipe(recipe)
            recipes.append(recipe)
        if tuple(item.recipe_id for item in recipes) != plan.recipe_ids:
            raise DataManagerCreationError("batch plan changed before execution")
        materialization_plan = self._plan_materialization(
            DataManagerArtifactMaterializationRequest(
                target_market_id=plan.request.market_id,
                root_recipe_ids=plan.recipe_ids,
            )
        )
        result = self._execute_materialization(
            materialization_plan, progress=progress,
            cancellation_requested=cancelled, before_publish=None,
        )
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Collection mutation")
        collection = None
        if plan.request.destination == "new_collection":
            collection = self.create_artifact_collection(result, collection_display_name)
        elif plan.request.destination == "collection_revision":
            collection = self.add_collection_branches(plan.request.collection_id, result)
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

    def _build_batch_recipe(
        self, branch, source_recipe_id: str, source_outputs: Sequence[str]
    ) -> PortableRecipeV1:
        parameters = dict(branch.parameters)
        dependencies: list[PortableRecipeDependencyV1] = []
        key = branch.tool_key
        if key in {"derivative", "angle"}:
            roles = ("source",)
        elif key in {"percent_span_angle", "angle_momentum"}:
            roles = ("source_1",)
        elif key == "delta":
            roles = ("fast", "slow")
        elif key == "trap_area":
            roles = ("fast", "slow") if "mid_output" not in parameters else ("fast", "mid", "slow")
        else:
            raise DataManagerCreationError("unsupported batch Construct")
        output_by_role = {roles[0]: branch.source_output}
        for role in roles[1:]:
            key_name = f"{role}_output"
            value = parameters.pop(key_name, None)
            if value is None:
                raise DataManagerCreationError(f"{key} requires explicit {key_name}")
            output_by_role[role] = str(value)
        if any(item not in source_outputs for item in output_by_role.values()):
            raise DataManagerCreationError("batch source role references an unavailable output")
        if len(set(output_by_role.values())) != len(output_by_role):
            raise DataManagerCreationError("batch source roles must use distinct outputs")
        dependencies.extend(
            PortableRecipeDependencyV1(role, source_recipe_id, output)
            for role, output in output_by_role.items()
        )
        resolved_parameters = resolve_parameters(key, parameters)
        naming_parameters = dict(resolved_parameters)
        if key in {"derivative", "angle"}:
            naming_parameters["source"] = "__research_source"
        elif key in {"percent_span_angle", "angle_momentum"}:
            naming_parameters["source_columns"] = "__research_source_1"
        elif key in {"delta", "trap_area"}:
            naming_parameters.update(
                {role: f"__research_{role}" for role in output_by_role}
            )
        outputs = resolve_output_names(key, naming_parameters)
        return build_portable_recipe(
            tool_key=key, kind=get_financial_tool_spec(key).kind,
            parameters=resolved_parameters, output_names=outputs,
            dependencies=tuple(dependencies),
        )

    @staticmethod
    def _batch_visible_output_names(branch) -> tuple[str, ...]:
        parameters = dict(branch.parameters)
        key = branch.tool_key
        if key in {"derivative", "angle"}:
            parameters["source"] = branch.source_output
        elif key in {"percent_span_angle", "angle_momentum"}:
            parameters["source_columns"] = branch.source_output
        elif key in {"delta", "trap_area"}:
            parameters["fast"] = branch.source_output
            for role in ("mid", "slow"):
                output = parameters.pop(f"{role}_output", None)
                if output is not None:
                    parameters[role] = output
        return resolve_output_names(key, parameters)

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
