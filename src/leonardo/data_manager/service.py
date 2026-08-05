"""Read/manage orchestration over canonical dataset and artifact authorities."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral, Real
from types import MappingProxyType
from typing import Protocol

from leonardo.artifacts import (
    ArtifactError,
    ArtifactMetadataV1,
    ArtifactLineageError,
    ArtifactService,
    ArtifactSourceRefV1,
    compute_logical_artifact_id,
    ManagedArtifactVersionKey,
    ManagedArtifactSummary,
    OHLCVSourceFingerprintV1,
    ArtifactSummary,
    RecipeSummary,
)
from leonardo.data import (
    MarketId,
    canonicalize_market_id,
    normalize_exchange,
    normalize_market_type,
    normalize_symbol,
    normalize_timeframe,
)
from leonardo.recipes import (
    PortableRecipeGraphError,
    PortableRecipeGraphPlan,
    PortableRecipeGraphPlanner,
    PortableRecipeOHLCVInputV1,
    PortableRecipeDependencyV1,
    PortableRecipeProvenanceV1,
    PortableRecipeStore,
    PortableRecipeStoreError,
    PortableRecipeV1,
    PortableRecipeValidationError,
    build_portable_recipe,
)
from leonardo.research import (
    AcceptedDatasetCatalog,
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    DatasetRejection,
    HistoricalDataset,
    HistoricalDatasetLoadError,
    HistoricalDatasetLoader,
    StudyEnvironmentEntryV1,
    StudyEnvironmentNotFoundError,
    StudyEnvironmentSourceV1,
    StudyEnvironmentStore,
    StudyEnvironmentV1,
    StudyEnvironmentValidationError,
)

from .models import (
    DataManagerArtifactMaterializationNode,
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationRequest,
    DataManagerArtifactMaterializationResult,
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerDeletionResult,
    DataManagerMarketSnapshot,
    DataManagerManagedArtifactEntry,
    DataManagerManagedArtifactCatalog,
    DataManagerManagedArtifactHistory,
    DataManagerOperationError,
    DataManagerPreview,
    DataManagerRecipeEntry,
    DataManagerPortableRecipeCatalog,
    DataManagerPortableRecipeEntry,
    DataManagerPortableRecipeInspection,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionCatalog,
    DataManagerRecipeCollectionEntry,
    DataManagerRecipeCollectionInspection,
    DataManagerRecipeDerivationPlan,
    DataManagerRecipePersistenceResult,
    DataManagerStudyEntryPortability,
    DataManagerStudyEnvironmentCatalog,
    DataManagerStudyEnvironmentEntry,
    DataManagerStudyEnvironmentInspection,
    DataManagerDatabaseCatalogEntry,
)
from .artifact_materialization import (
    ArtifactMaterializationValidationError,
    _calculate_recipe,
    _dataset_frame,
    _plan_id,
    _source_refs,
    _target_configuration,
    _validate_recipe_execution,
)
from .creation_models import (
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionValidation,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DatabaseReadiness,
    DatabaseDefinitionV1,
    DatabaseRevisionManifestV1,
    DatabaseSeedV1,
)
from .creation_service import DataManagerCreationWorkflow
from .creation_store import DataManagerCreationStore
from .update_models import (
    ArtifactCollectionUpdatePlan,
    ArtifactCollectionUpdateResult,
    DataManagerReconciliationSnapshot,
    DatabaseUpdatePlan,
    DatabaseUpdateResult,
)
from .update_service import DataManagerUpdateWorkflow


_DATASET_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")


class DataManagerMarketUnavailableError(DataManagerOperationError):
    """Raised when canonical persistence no longer accepts an exact market."""


class _Catalog(Protocol):
    def scan(self) -> DatasetCatalogReport: ...


class _Loader(Protocol):
    def load(
        self,
        market_id: MarketId,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> HistoricalDataset: ...


class _Artifacts(Protocol):
    def list_recipes(self, market_id: MarketId) -> tuple[RecipeSummary, ...]: ...
    def list_artifacts(self, market_id: MarketId) -> tuple[ArtifactSummary, ...]: ...
    def load_artifact(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> object: ...
    def validate_artifact_current(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> ArtifactSummary: ...
    def delete_artifact(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> ArtifactSummary: ...
    def delete_recipe(
        self, market_id: MarketId, kind: str, tool_key: str, recipe_id: str
    ) -> RecipeSummary: ...


class _StudyEnvironments(Protocol):
    def list_summaries(self) -> tuple[object, ...]: ...
    def load(self, environment_id: str) -> StudyEnvironmentV1: ...


@dataclass(frozen=True, slots=True)
class _EnvironmentAnalysis:
    classifications: tuple[DataManagerStudyEntryPortability, ...]
    recipes_by_entry: Mapping[str, PortableRecipeV1]
    dependency_entries: Mapping[str, tuple[str, ...]]


class DataManagerService:
    """Project canonical persisted truth into immutable Data Manager values."""

    def __init__(
        self,
        catalog: AcceptedDatasetCatalog | _Catalog,
        loader: HistoricalDatasetLoader | _Loader,
        artifacts: ArtifactService | _Artifacts,
        study_environments: StudyEnvironmentStore | _StudyEnvironments,
        portable_recipes: PortableRecipeStore,
        recipe_planner: PortableRecipeGraphPlanner,
        creation_store: DataManagerCreationStore | None = None,
    ) -> None:
        _require_methods(catalog, "catalog", ("scan",))
        _require_methods(loader, "loader", ("load",))
        _require_methods(
            artifacts,
            "artifacts",
            (
                "list_recipes",
                "list_artifacts",
                "load_artifact",
                "validate_artifact_current",
                "delete_artifact",
                "delete_recipe",
            ),
        )
        _require_methods(
            study_environments,
            "study_environments",
            ("list_summaries", "load"),
        )
        if not isinstance(portable_recipes, PortableRecipeStore):
            raise TypeError("portable_recipes must be a PortableRecipeStore")
        if not isinstance(recipe_planner, PortableRecipeGraphPlanner):
            raise TypeError("recipe_planner must be a PortableRecipeGraphPlanner")
        self._catalog = catalog
        self._loader = loader
        self._artifacts = artifacts
        self._study_environments = study_environments
        self._portable_recipes = portable_recipes
        self._recipe_planner = recipe_planner
        self._creation = DataManagerCreationWorkflow(
            store=creation_store or DataManagerCreationStore(portable_recipes.root_dir),
            catalog=catalog,
            loader=loader,
            artifacts=artifacts,
            portable_recipes=portable_recipes,
            recipe_planner=recipe_planner,
            materialization_planner=self.plan_artifact_materialization,
            materialization_executor=self._execute_artifact_materialization,
        )
        self._updates = DataManagerUpdateWorkflow(
            catalog,
            loader,
            artifacts,
            portable_recipes,
            recipe_planner,
            self._creation,
        )

    @property
    def creation_store(self) -> DataManagerCreationStore:
        return self._creation.store

    def create_database_seed(
        self,
        market_id: MarketId,
        display_name: str,
        *,
        description: str = "",
        selected_ohlcv_columns: Sequence[str] = (
            "open", "high", "low", "close", "volume"
        ),
        selected_range_start_ms: int | None = None,
        selected_range_end_ms: int | None = None,
    ) -> DatabaseSeedV1:
        result = self._creation.create_database_seed(
            market_id,
            display_name,
            description=description,
            selected_ohlcv_columns=selected_ohlcv_columns,
            selected_range_start_ms=selected_range_start_ms,
            selected_range_end_ms=selected_range_end_ms,
        )
        self._updates.invalidate()
        return result

    def list_database_seeds(self) -> tuple[DatabaseSeedV1, ...]:
        return self._creation.list_database_seeds()

    def scan_creation_foundations(self):
        return (
            self.scan_study_environments(),
            self.scan_portable_recipes(),
            self.list_recipe_collections(),
            self.list_database_seeds(),
            self.list_artifact_collections(),
            self.list_database_ids(),
        )

    def load_database_seed(self, seed_id: str) -> DatabaseSeedV1:
        return self._creation.load_database_seed(seed_id)

    def inspect_database_seed(self, seed_id: str) -> DatabaseSeedV1:
        return self._creation.inspect_database_seed(seed_id)

    def validate_database_seed(self, seed_id: str) -> tuple[bool, tuple[str, ...]]:
        return self._creation.validate_database_seed(seed_id)

    def delete_database_seed(self, seed_id: str) -> DatabaseSeedV1:
        result = self._creation.delete_database_seed(seed_id)
        self._updates.invalidate()
        return result

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
        result = self._creation.create_artifact_collection(
            materialization,
            display_name,
            description=description,
            source_recipe_collection_id=source_recipe_collection_id,
            source_recipe_collection_revision_id=source_recipe_collection_revision_id,
            selected_outputs=selected_outputs,
        )
        self._updates.invalidate()
        return result

    def list_artifact_collections(self) -> tuple[ArtifactCollectionRevisionV1, ...]:
        return self._creation.list_artifact_collections()

    def list_artifact_collection_revisions(
        self, collection_id: str
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        return self._creation.list_artifact_collection_revisions(collection_id)

    def load_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionRevisionV1:
        return self._creation.load_artifact_collection(collection_id, revision_id)

    def inspect_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> tuple[ArtifactCollectionRevisionV1, ArtifactCollectionValidation]:
        return self._creation.inspect_artifact_collection(collection_id, revision_id)

    def validate_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionValidation:
        return self._creation.validate_artifact_collection(collection_id, revision_id)

    def revise_artifact_collection(self, collection_id: str, **changes) -> ArtifactCollectionRevisionV1:
        result = self._creation.revise_artifact_collection(collection_id, **changes)
        self._updates.invalidate()
        return result

    def add_artifact_collection_branches(
        self,
        collection_id: str,
        materialization: DataManagerArtifactMaterializationResult,
        *,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        result = self._creation.add_collection_branches(
            collection_id, materialization, selected_outputs=selected_outputs
        )
        self._updates.invalidate()
        return result

    def plan_batch_artifacts(self, request: BatchArtifactRequest) -> BatchArtifactPlan:
        return self._creation.plan_batch_artifacts(request)

    def execute_batch_artifacts(self, plan: BatchArtifactPlan, **execution):
        result = self._creation.execute_batch_artifacts(plan, **execution)
        self._updates.invalidate()
        return result

    def assess_database_readiness(
        self,
        seed_id: str,
        collection_id: str,
        collection_revision_id: str | None = None,
    ) -> DatabaseReadiness:
        return self._creation.assess_database_readiness(
            seed_id, collection_id, collection_revision_id
        )

    def build_database_revision(
        self, seed_id: str, collection_id: str, **options
    ) -> DatabaseRevisionManifestV1:
        result = self._creation.build_database_revision(seed_id, collection_id, **options)
        self._updates.invalidate()
        return result

    def reconcile_update_status(
        self,
        *,
        force: bool = False,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> DataManagerReconciliationSnapshot:
        return self._updates.reconcile_all(
            force=force,
            cancellation_requested=cancellation_requested,
        )

    def latest_update_status(self) -> DataManagerReconciliationSnapshot:
        return self._updates.latest_snapshot()

    def invalidate_update_status(self) -> None:
        self._updates.invalidate()

    def plan_artifact_collection_update(
        self, collection_id: str
    ) -> ArtifactCollectionUpdatePlan:
        return self._updates.plan_artifact_collection_update(collection_id)

    def execute_artifact_collection_update(
        self, plan: ArtifactCollectionUpdatePlan, **execution
    ) -> ArtifactCollectionUpdateResult:
        return self._updates.execute_artifact_collection_update(plan, **execution)

    def plan_database_update(self, database_id: str) -> DatabaseUpdatePlan:
        return self._updates.plan_database_update(database_id)

    def execute_database_append(
        self, plan: DatabaseUpdatePlan, **execution
    ) -> DatabaseUpdateResult:
        return self._updates.execute_database_append(plan, **execution)

    def execute_database_rebuild(
        self, plan: DatabaseUpdatePlan, **execution
    ) -> DatabaseUpdateResult:
        return self._updates.execute_database_rebuild(plan, **execution)

    def list_database_ids(self) -> tuple[str, ...]:
        return self._creation.list_database_ids()

    def load_database_definition(self, database_id: str) -> DatabaseDefinitionV1:
        return self._creation.load_database_definition(database_id)

    def list_database_revisions(
        self, database_id: str
    ) -> tuple[DatabaseRevisionManifestV1, ...]:
        return self._creation.list_database_revisions(database_id)

    def load_database_revision(
        self, database_id: str, revision_id: str | None = None
    ):
        return self._creation.load_database_revision(database_id, revision_id)

    def scan_catalog(self) -> DataManagerCatalogSnapshot:
        return _project_catalog(self._catalog.scan())

    def inspect_market(self, market_id: MarketId) -> DataManagerMarketSnapshot:
        market = _canonical_market(market_id)
        dataset = self._require_accepted(market)
        recipes = tuple(_project_recipe(item) for item in self._artifacts.list_recipes(market))
        artifacts = tuple(
            _project_artifact(item) for item in self._artifacts.list_artifacts(market)
        )
        return DataManagerMarketSnapshot(market, dataset, recipes, artifacts)

    def preview_dataset(
        self, market_id: MarketId, *, limit: int = 200
    ) -> DataManagerPreview:
        return self._preview_dataset(
            market_id,
            limit=limit,
            progress=None,
            cancellation_requested=None,
        )

    def _preview_dataset(
        self,
        market_id: MarketId,
        *,
        limit: int,
        progress: Callable[[int, int], None] | None,
        cancellation_requested: Callable[[], bool] | None,
    ) -> DataManagerPreview:
        market = _canonical_market(market_id)
        _validate_limit(limit)
        self._require_accepted(market)
        dataset = self._loader.load(
            market,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )
        source_rows = tuple(
            zip(
                dataset.ts_ms,
                dataset.open,
                dataset.high,
                dataset.low,
                dataset.close,
                dataset.volume,
                strict=True,
            )
        )
        rows = _bounded_rows(source_rows, limit)
        display_rows = tuple(
            (_format_timestamp(row[0]), *(_format_cell(value) for value in row[1:]))
            for row in rows
        )
        return DataManagerPreview(
            title=f"OHLCV - {market.as_key()}",
            market_id=market,
            object_kind="dataset",
            object_id=None,
            columns=_DATASET_COLUMNS,
            rows=display_rows,
            total_rows=dataset.row_count,
            truncated=dataset.row_count > len(display_rows),
            metadata={
                "market_id": market.as_key(),
                "row_count": str(dataset.row_count),
                "first_timestamp_ms": str(dataset.first_timestamp_ms),
                "last_timestamp_ms": str(dataset.last_timestamp_ms),
            },
        )

    def preview_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        limit: int = 200,
    ) -> DataManagerPreview:
        market = _canonical_market(market_id)
        _validate_limit(limit)
        self._require_accepted(market)
        loaded = self._artifacts.load_artifact(market, kind, tool_key, artifact_id)
        metadata = loaded.metadata
        output_names = tuple(metadata.recipe.output_names)
        columns = ("ts_ms", *output_names)
        frame = loaded.frame
        source_rows = tuple(
            tuple(frame[column].iloc[index] for column in columns)
            for index in range(len(frame.index))
        )
        rows = _bounded_rows(source_rows, limit)
        display_rows = tuple(
            (_format_timestamp(row[0]), *(_format_cell(value) for value in row[1:]))
            for row in rows
        )
        return DataManagerPreview(
            title=f"Artifact {artifact_id}",
            market_id=market,
            object_kind="artifact",
            object_id=artifact_id,
            columns=columns,
            rows=display_rows,
            total_rows=metadata.row_count,
            truncated=metadata.row_count > len(display_rows),
            metadata={
                "market_id": market.as_key(),
                "artifact_id": artifact_id,
                "recipe_id": metadata.recipe.recipe_id,
                "tool_key": metadata.recipe.tool_key,
                "kind": metadata.recipe.kind,
                "row_count": str(metadata.row_count),
                "first_timestamp_ms": str(metadata.first_timestamp_ms),
                "last_timestamp_ms": str(metadata.last_timestamp_ms),
            },
        )

    def validate_artifact_current(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
    ) -> DataManagerArtifactValidation:
        market = _canonical_market(market_id)
        self._require_accepted(market)
        try:
            self._artifacts.validate_artifact_current(
                market, kind, tool_key, artifact_id
            )
        except ArtifactLineageError as error:
            return DataManagerArtifactValidation(
                market, kind, tool_key, artifact_id, "stale", str(error)
            )
        except ArtifactError as error:
            return DataManagerArtifactValidation(
                market, kind, tool_key, artifact_id, "invalid", str(error)
            )
        return DataManagerArtifactValidation(
            market, kind, tool_key, artifact_id, "current", ""
        )

    def delete_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
    ) -> DataManagerDeletionResult:
        return self._delete_artifact(
            market_id, kind, tool_key, artifact_id, before_delete=None
        )

    def _delete_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> DataManagerDeletionResult:
        market = _canonical_market(market_id)
        self._require_accepted(market)
        if before_delete is not None:
            before_delete()
        self._artifacts.delete_artifact(market, kind, tool_key, artifact_id)
        result = DataManagerDeletionResult(
            market, "artifact", kind, tool_key, artifact_id
        )
        self._updates.invalidate()
        return result

    def delete_recipe(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        recipe_id: str,
    ) -> DataManagerDeletionResult:
        return self._delete_recipe(
            market_id, kind, tool_key, recipe_id, before_delete=None
        )

    def _delete_recipe(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        recipe_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> DataManagerDeletionResult:
        market = _canonical_market(market_id)
        self._require_accepted(market)
        if before_delete is not None:
            before_delete()
        self._artifacts.delete_recipe(market, kind, tool_key, recipe_id)
        return DataManagerDeletionResult(
            market, "recipe", kind, tool_key, recipe_id
        )

    def _require_accepted(self, market: MarketId) -> DataManagerDatasetEntry:
        snapshot = self.scan_catalog()
        accepted = snapshot.accepted_market(market)
        if accepted is not None:
            return accepted
        rejected = next(
            (item for item in snapshot.datasets if item.market_id == market),
            None,
        )
        if rejected is not None:
            raise DataManagerMarketUnavailableError(
                f"Dataset {market.as_key()} is unavailable: "
                f"{rejected.rejection_code}: {rejected.rejection_reason}"
            )
        raise DataManagerMarketUnavailableError(
            f"Dataset {market.as_key()} is missing from canonical persistence"
        )

    def scan_study_environments(
        self,
        *,
        exchange: str | None = None,
        market_type: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        display_name_text: str | None = None,
    ) -> DataManagerStudyEnvironmentCatalog:
        filters = _environment_filters(
            exchange, market_type, symbol, timeframe, display_name_text
        )
        values: list[DataManagerStudyEnvironmentEntry] = []
        for summary in self._study_environments.list_summaries():
            if not summary.valid:
                item = DataManagerStudyEnvironmentEntry(
                    environment_id=summary.environment_id,
                    display_name=summary.display_name,
                    description=summary.description,
                    origin_market_id=None,
                    entry_count=summary.entry_count,
                    portable_count=0,
                    portable_with_dependencies_count=0,
                    market_bound_count=0,
                    unsupported_count=0,
                    invalid_count=summary.entry_count,
                    created_at_utc=summary.created_at_utc,
                    updated_at_utc=summary.updated_at_utc,
                    valid=False,
                    rejection_reason=summary.rejection_reason or "invalid Study Environment",
                )
            else:
                try:
                    environment = self._study_environments.load(summary.environment_id)
                    analysis = self._analyze_environment(environment)
                except (StudyEnvironmentValidationError, StudyEnvironmentNotFoundError) as exc:
                    item = DataManagerStudyEnvironmentEntry(
                        summary.environment_id,
                        summary.display_name,
                        summary.description,
                        None,
                        summary.entry_count,
                        0,
                        0,
                        0,
                        0,
                        summary.entry_count,
                        summary.created_at_utc,
                        summary.updated_at_utc,
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                else:
                    counts = {
                        status: sum(
                            item.status == status for item in analysis.classifications
                        )
                        for status in (
                            "PORTABLE",
                            "PORTABLE_WITH_DEPENDENCIES",
                            "MARKET_BOUND",
                            "UNSUPPORTED",
                            "INVALID",
                        )
                    }
                    item = DataManagerStudyEnvironmentEntry(
                        environment.environment_id,
                        environment.display_name,
                        environment.description,
                        environment.created_from,
                        len(environment.entries),
                        counts["PORTABLE"],
                        counts["PORTABLE_WITH_DEPENDENCIES"],
                        counts["MARKET_BOUND"],
                        counts["UNSUPPORTED"],
                        counts["INVALID"],
                        environment.created_at_utc,
                        environment.updated_at_utc,
                    )
            if _environment_matches(item, filters):
                values.append(item)
        return DataManagerStudyEnvironmentCatalog(tuple(values))

    def inspect_study_environment(
        self, environment_id: str
    ) -> DataManagerStudyEnvironmentInspection:
        try:
            environment = self._study_environments.load(environment_id)
            analysis = self._analyze_environment(environment)
            catalog = self.scan_study_environments()
            entry = next(
                item
                for item in catalog.environments
                if item.environment_id == environment_id
            )
            return DataManagerStudyEnvironmentInspection(
                entry, analysis.classifications
            )
        except (
            StopIteration,
            StudyEnvironmentNotFoundError,
            StudyEnvironmentValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def plan_recipe_derivation(
        self, environment_id: str, root_entry_ids: tuple[str, ...]
    ) -> DataManagerRecipeDerivationPlan:
        try:
            environment = self._study_environments.load(environment_id)
            return self._build_derivation_plan(environment, root_entry_ids)
        except (
            FileNotFoundError,
            PortableRecipeGraphError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
            StudyEnvironmentNotFoundError,
            StudyEnvironmentValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def persist_recipe_derivation(
        self,
        environment_id: str,
        root_entry_ids: tuple[str, ...],
        *,
        create_collection: bool,
        collection_display_name: str = "",
        collection_description: str = "",
    ) -> DataManagerRecipePersistenceResult:
        return self._persist_recipe_derivation(
            environment_id,
            root_entry_ids,
            create_collection=create_collection,
            collection_display_name=collection_display_name,
            collection_description=collection_description,
            before_publish=None,
        )

    def _persist_recipe_derivation(
        self,
        environment_id: str,
        root_entry_ids: tuple[str, ...],
        *,
        create_collection: bool,
        collection_display_name: str = "",
        collection_description: str = "",
        before_publish: Callable[[], None] | None,
    ) -> DataManagerRecipePersistenceResult:
        try:
            first = self._build_derivation_plan(
                self._study_environments.load(environment_id), root_entry_ids
            )
            current = self._build_derivation_plan(
                self._study_environments.load(environment_id), root_entry_ids
            )
            if first != current:
                raise DataManagerOperationError(
                    "Study Environment derivation changed before persistence"
                )
            if current.blocked:
                raise DataManagerOperationError("; ".join(current.blockers))
            collection_metadata = (
                _validate_collection_metadata(
                    collection_display_name, collection_description
                )
                if create_collection
                else None
            )
            recipe_by_entry = {
                item.entry_id: item.recipe_id
                for item in current.entry_classifications
                if item.recipe_id is not None
            }
            root_recipe_ids = tuple(recipe_by_entry[item] for item in current.root_entry_ids)
            support_recipe_ids = tuple(
                recipe_by_entry[item] for item in current.support_entry_ids
            )
            collection_members: tuple[str, ...] = ()
            if collection_metadata is not None:
                graph = self._recipe_planner.plan(
                    root_recipe_ids,
                    recipes={item.recipe_id: item for item in current.recipes},
                )
                collection_members = graph.member_recipe_ids
            if before_publish is not None:
                before_publish()
            for recipe in current.recipes:
                self._portable_recipes.save_recipe(recipe)
            for provenance in current.provenances:
                self._portable_recipes.save_provenance(provenance)
            collection_id = None
            revision_id = None
            if collection_metadata is not None:
                display_name, description = collection_metadata
                revision = self._portable_recipes.create_collection(
                    display_name,
                    description,
                    root_recipe_ids,
                    collection_members,
                )
                collection_id = revision.collection_id
                revision_id = revision.revision_id
            result = DataManagerRecipePersistenceResult(
                environment_id,
                root_recipe_ids,
                support_recipe_ids,
                collection_id,
                revision_id,
            )
            if collection_id is not None:
                self._updates.invalidate()
            return result
        except DataManagerOperationError:
            raise
        except (
            FileNotFoundError,
            PortableRecipeGraphError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
            StudyEnvironmentNotFoundError,
            StudyEnvironmentValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def scan_portable_recipes(
        self,
        *,
        origin_exchange: str | None = None,
        origin_market_type: str | None = None,
        origin_symbol: str | None = None,
        origin_timeframe: str | None = None,
        tool_key: str | None = None,
        display_name_text: str | None = None,
    ) -> DataManagerPortableRecipeCatalog:
        filters = _recipe_filters(
            origin_exchange,
            origin_market_type,
            origin_symbol,
            origin_timeframe,
            tool_key,
            display_name_text,
        )
        entries: list[DataManagerPortableRecipeEntry] = []
        for summary in self._portable_recipes.list_recipe_summaries():
            if not summary.valid:
                item = DataManagerPortableRecipeEntry(
                    summary.recipe_id, "", "", "", {}, (), 0, 0, (), (), (), 0,
                    False, summary.rejection_reason,
                )
            else:
                try:
                    recipe = self._portable_recipes.load_recipe(summary.recipe_id)
                    provenances = self._portable_recipes.list_provenance(recipe.recipe_id)
                except (FileNotFoundError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
                    item = DataManagerPortableRecipeEntry(
                        summary.recipe_id, summary.tool_key, summary.tool_version,
                        summary.kind, {}, summary.output_names,
                        summary.dependency_count, summary.ohlcv_input_count,
                        (), (), (), 0, False, f"{type(exc).__name__}: {exc}",
                    )
                else:
                    markets = tuple(sorted(
                        {item.origin_market_id for item in provenances},
                        key=lambda value: (
                            value.exchange, value.market_type, value.symbol, value.timeframe
                        ),
                    ))
                    item = DataManagerPortableRecipeEntry(
                        recipe.recipe_id,
                        recipe.tool_key,
                        recipe.tool_version,
                        recipe.kind,
                        recipe.parameters,
                        recipe.output_names,
                        len(recipe.dependencies),
                        len(recipe.ohlcv_inputs),
                        markets,
                        tuple(sorted({value.study_environment_id for value in provenances})),
                        tuple(sorted({value.study_display_name for value in provenances})),
                        len(provenances),
                    )
            if _recipe_matches(item, filters):
                entries.append(item)
        return DataManagerPortableRecipeCatalog(tuple(entries))

    def inspect_portable_recipe(
        self, recipe_id: str
    ) -> DataManagerPortableRecipeInspection:
        try:
            recipe = self._portable_recipes.load_recipe(recipe_id)
            provenance = self._portable_recipes.list_provenance(recipe_id)
            entry = next(
                item
                for item in self.scan_portable_recipes().recipes
                if item.recipe_id == recipe_id
            )
            if not entry.valid:
                raise DataManagerOperationError(entry.rejection_reason)
            return DataManagerPortableRecipeInspection(entry, recipe, provenance)
        except DataManagerOperationError:
            raise
        except (
            FileNotFoundError,
            StopIteration,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def create_recipe_collection(
        self, display_name: str, description: str, root_recipe_ids: tuple[str, ...]
    ) -> DataManagerRecipeCollectionInspection:
        return self._create_recipe_collection(
            display_name, description, root_recipe_ids, before_publish=None
        )

    def _create_recipe_collection(
        self,
        display_name: str,
        description: str,
        root_recipe_ids: tuple[str, ...],
        *,
        before_publish: Callable[[], None] | None,
    ) -> DataManagerRecipeCollectionInspection:
        try:
            display_name, description = _validate_collection_metadata(
                display_name, description
            )
            plan = self._recipe_planner.plan(root_recipe_ids)
            if before_publish is not None:
                before_publish()
            revision = self._portable_recipes.create_collection(
                display_name, description, root_recipe_ids, plan.member_recipe_ids
            )
            result = self.inspect_recipe_collection(revision.collection_id)
            self._updates.invalidate()
            return result
        except (FileNotFoundError, PortableRecipeGraphError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def update_recipe_collection(
        self,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: tuple[str, ...],
    ) -> DataManagerRecipeCollectionInspection:
        return self._update_recipe_collection(
            collection_id,
            display_name,
            description,
            root_recipe_ids,
            before_publish=None,
        )

    def _update_recipe_collection(
        self,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: tuple[str, ...],
        *,
        before_publish: Callable[[], None] | None,
    ) -> DataManagerRecipeCollectionInspection:
        try:
            display_name, description = _validate_collection_metadata(
                display_name, description
            )
            plan = self._recipe_planner.plan(root_recipe_ids)
            if before_publish is not None:
                before_publish()
            self._portable_recipes.update_collection(
                collection_id, display_name, description, root_recipe_ids, plan.member_recipe_ids
            )
            result = self.inspect_recipe_collection(collection_id)
            self._updates.invalidate()
            return result
        except DataManagerOperationError:
            raise
        except (FileNotFoundError, PortableRecipeGraphError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def list_recipe_collections(self) -> DataManagerRecipeCollectionCatalog:
        values: list[DataManagerRecipeCollectionEntry] = []
        for summary in self._portable_recipes.list_collection_summaries():
            if not summary.valid:
                values.append(
                    DataManagerRecipeCollectionEntry(
                        summary.collection_id, summary.revision_id,
                        summary.display_name, summary.description,
                        summary.root_count, summary.member_count, 0, 0,
                        summary.created_at_utc, summary.updated_at_utc,
                        False, summary.rejection_reason,
                    )
                )
                continue
            try:
                revision = self._portable_recipes.load_collection(summary.collection_id)
                graph = self._recipe_planner.plan(revision.root_recipe_ids)
            except (FileNotFoundError, PortableRecipeGraphError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
                values.append(
                    DataManagerRecipeCollectionEntry(
                        summary.collection_id, summary.revision_id,
                        summary.display_name, summary.description,
                        summary.root_count, summary.member_count, 0, 0,
                        summary.created_at_utc, summary.updated_at_utc,
                        False, f"{type(exc).__name__}: {exc}",
                    )
                )
            else:
                values.append(_collection_entry(summary, graph))
        return DataManagerRecipeCollectionCatalog(tuple(values))

    def list_recipe_collection_revisions(self, collection_id: str):
        try:
            return self._portable_recipes.list_collection_revisions(collection_id)
        except (FileNotFoundError, PortableRecipeStoreError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def inspect_recipe_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> DataManagerRecipeCollectionInspection:
        try:
            revision = (
                self._portable_recipes.load_collection(collection_id)
                if revision_id is None
                else self._portable_recipes.load_collection_revision(
                    collection_id, revision_id
                )
            )
            graph = self._recipe_planner.plan(revision.root_recipe_ids)
            revisions = self._portable_recipes.list_collection_revisions(collection_id)
            created_at = revisions[0].created_at_utc if revisions else revision.created_at_utc
            current_summary = next(
                (
                    item
                    for item in self._portable_recipes.list_collection_summaries()
                    if item.collection_id == collection_id
                ),
                None,
            )
            updated_at = (
                current_summary.updated_at_utc
                if current_summary is not None and current_summary.revision_id == revision.revision_id
                else revision.created_at_utc
            )
            entry = DataManagerRecipeCollectionEntry(
                revision.collection_id,
                revision.revision_id,
                revision.display_name,
                revision.description,
                len(revision.root_recipe_ids),
                len(revision.member_recipe_ids),
                len(graph.dependency_edges),
                len(graph.execution_stages),
                created_at,
                updated_at,
            )
            return DataManagerRecipeCollectionInspection(
                entry,
                revision.root_recipe_ids,
                revision.member_recipe_ids,
                graph.dependency_edges,
                graph.execution_stages,
            )
        except (FileNotFoundError, StopIteration, PortableRecipeGraphError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def plan_artifact_materialization(
        self, request: DataManagerArtifactMaterializationRequest
    ) -> DataManagerArtifactMaterializationPlan:
        if not isinstance(request, DataManagerArtifactMaterializationRequest):
            raise TypeError(
                "request must be a DataManagerArtifactMaterializationRequest"
            )
        try:
            market = request.target_market_id
            self._require_accepted(market)
            source = self._artifacts.capture_accepted_source(market)
            collection_id = request.recipe_collection_id
            collection_revision_id = request.recipe_collection_revision_id
            if collection_id is None:
                roots = request.root_recipe_ids
            else:
                if collection_revision_id is None:
                    revision = self._portable_recipes.load_collection(collection_id)
                else:
                    revision = self._portable_recipes.load_collection_revision(
                        collection_id, collection_revision_id
                    )
                roots = revision.root_recipe_ids
                collection_revision_id = revision.revision_id
            graph = self._recipe_planner.plan(roots)
            recipes = {
                recipe_id: self._portable_recipes.load_recipe(recipe_id)
                for recipe_id in graph.member_recipe_ids
            }
            blockers_by_recipe: dict[str, list[str]] = {
                recipe_id: [] for recipe_id in graph.member_recipe_ids
            }
            for recipe_id in graph.member_recipe_ids:
                try:
                    _validate_recipe_execution(recipes[recipe_id], recipes)
                    _target_configuration(recipes[recipe_id])
                except (KeyError, TypeError, ValueError) as exc:
                    blockers_by_recipe[recipe_id].append(str(exc))

            logical_by_recipe = {
                recipe_id: compute_logical_artifact_id(market, recipe_id)
                for recipe_id in graph.member_recipe_ids
            }
            managed = {
                item.logical_artifact_id: item
                for item in self._artifacts.list_managed_artifacts(market)
            }
            nodes: list[DataManagerArtifactMaterializationNode] = []
            node_by_recipe: dict[str, DataManagerArtifactMaterializationNode] = {}
            root_set = set(roots)
            dependencies_by_recipe: dict[str, tuple[str, ...]] = {}
            for recipe_id in graph.member_recipe_ids:
                recipe = recipes[recipe_id]
                dependencies_by_recipe[recipe_id] = tuple(
                    dict.fromkeys(item.recipe_id for item in recipe.dependencies)
                )
                blockers = blockers_by_recipe[recipe_id]
                dependency_nodes = tuple(
                    node_by_recipe[item]
                    for item in dependencies_by_recipe[recipe_id]
                    if item in node_by_recipe
                )
                if any(item.status == "BLOCKED" for item in dependency_nodes):
                    blockers.append("dependency materialization is blocked")
                logical_id = logical_by_recipe[recipe_id]
                current = managed.get(logical_id)
                current_artifact_id: str | None = None
                previous_artifact_id: str | None = None
                status = "CREATE"
                if current is not None and not current.valid:
                    blockers.append(current.rejection_reason)
                elif current is not None:
                    previous_artifact_id = current.artifact_id
                    try:
                        if current.portable_recipe_id != recipe_id:
                            raise ArtifactLineageError(
                                "managed portable Recipe identity disagrees"
                            )
                        loaded = self._artifacts.load_artifact_by_id(
                            market, current.artifact_id
                        )
                        if loaded.metadata.source_ohlcv != source:
                            status = "CREATE"
                        elif any(
                            item.status != "REUSE_CURRENT"
                            for item in dependency_nodes
                        ):
                            status = "CREATE"
                        else:
                            parameters, bindings = _target_configuration(recipe)
                            dependency_artifact_ids = {
                                dependency_id: node_by_recipe[dependency_id].current_artifact_id
                                for dependency_id in dependencies_by_recipe[recipe_id]
                            }
                            if any(
                                value is None
                                for value in dependency_artifact_ids.values()
                            ):
                                status = "CREATE"
                            else:
                                refs = _source_refs(
                                    recipe,
                                    {
                                        key: value
                                        for key, value in dependency_artifact_ids.items()
                                        if value is not None
                                    },
                                )
                                target_recipe = loaded.metadata.recipe
                                if (
                                    target_recipe.tool_key == recipe.tool_key
                                    and target_recipe.kind == recipe.kind
                                    and dict(target_recipe.parameters) == parameters
                                    and dict(target_recipe.bindings) == bindings
                                    and target_recipe.output_names == recipe.output_names
                                    and target_recipe.source_artifacts == refs
                                ):
                                    status = "REUSE_CURRENT"
                                    current_artifact_id = current.artifact_id
                                    previous_artifact_id = current.previous_artifact_id
                                else:
                                    status = "CREATE"
                    except ArtifactError as exc:
                        blockers.append(str(exc))
                if blockers:
                    status = "BLOCKED"
                    current_artifact_id = None
                node = DataManagerArtifactMaterializationNode(
                    recipe_id,
                    logical_id,
                    recipe.tool_key,
                    recipe.kind,
                    "ROOT" if recipe_id in root_set else "SUPPORT",
                    status,
                    tuple(
                        logical_by_recipe[item]
                        for item in dependencies_by_recipe[recipe_id]
                    ),
                    current_artifact_id,
                    previous_artifact_id,
                    tuple(blockers),
                )
                nodes.append(node)
                node_by_recipe[recipe_id] = node
            plan_blockers = tuple(
                f"{node.portable_recipe_id}: {blocker}"
                for node in nodes
                for blocker in node.blockers
            )
            plan_id = _plan_id(
                target_market_id=market,
                source_ohlcv=source.to_dict(),
                root_recipe_ids=roots,
                member_recipe_ids=graph.member_recipe_ids,
                source_recipe_collection_id=collection_id,
                source_recipe_collection_revision_id=collection_revision_id,
                dependency_edges=graph.dependency_edges,
                execution_stages=graph.execution_stages,
            )
            return DataManagerArtifactMaterializationPlan(
                plan_id,
                market,
                source,
                roots,
                graph.member_recipe_ids,
                collection_id,
                collection_revision_id,
                graph.dependency_edges,
                graph.execution_stages,
                tuple(nodes),
                (),
                plan_blockers,
            )
        except (
            ArtifactError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
            PortableRecipeGraphError,
            ArtifactMaterializationValidationError,
            FileNotFoundError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def execute_artifact_materialization(
        self, plan: DataManagerArtifactMaterializationPlan
    ) -> DataManagerArtifactMaterializationResult:
        return self._execute_artifact_materialization(
            plan,
            progress=None,
            cancellation_requested=None,
            before_publish=None,
        )

    def _execute_artifact_materialization(
        self,
        plan: DataManagerArtifactMaterializationPlan,
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
        before_publish: Callable[[], None] | None,
    ) -> DataManagerArtifactMaterializationResult:
        if not isinstance(plan, DataManagerArtifactMaterializationPlan):
            raise TypeError("plan must be DataManagerArtifactMaterializationPlan")
        if plan.blocked:
            raise DataManagerOperationError("blocked materialization plan cannot execute")
        cancelled = cancellation_requested or (lambda: False)
        try:
            _raise_materialization_cancelled(cancelled, "plan recomputation")
            request = DataManagerArtifactMaterializationRequest(
                target_market_id=plan.target_market_id,
                root_recipe_ids=(
                    plan.root_recipe_ids
                    if plan.source_recipe_collection_id is None
                    else ()
                ),
                recipe_collection_id=plan.source_recipe_collection_id,
                recipe_collection_revision_id=plan.source_recipe_collection_revision_id,
            )
            recomputed = self.plan_artifact_materialization(request)
            if recomputed.plan_id != plan.plan_id:
                raise DataManagerOperationError(
                    "materialization plan semantics or source changed"
                )
            if recomputed.blocked:
                raise DataManagerOperationError(
                    "materialization plan acquired new blockers"
                )
            _raise_materialization_cancelled(cancelled, "dataset loading")
            dataset = self._loader.load(
                plan.target_market_id,
                cancellation_requested=cancelled,
            )
            if (
                dataset.market_id != plan.target_market_id
                or dataset.file_sha256 != plan.source_ohlcv.csv_sha256
                or dataset.row_count != plan.source_ohlcv.row_count
                or dataset.first_timestamp_ms != plan.source_ohlcv.first_timestamp_ms
                or dataset.last_timestamp_ms != plan.source_ohlcv.last_timestamp_ms
            ):
                raise DataManagerOperationError(
                    "loaded dataset does not match the materialization source"
                )
            target_frame = _dataset_frame(dataset)
            recipes = {
                recipe_id: self._portable_recipes.load_recipe(recipe_id)
                for recipe_id in recomputed.member_recipe_ids
            }
            node_by_recipe = {
                node.portable_recipe_id: node for node in recomputed.nodes
            }
            frames_by_recipe: dict[str, object] = {}
            metadata_by_recipe: dict[str, ArtifactMetadataV1] = {}
            artifact_ids_by_recipe: dict[str, str] = {}
            calculations: dict[str, object] = {}
            completed = 0
            total = len(recomputed.nodes)
            for stage in recomputed.execution_stages:
                for recipe_id in sorted(stage):
                    _raise_materialization_cancelled(cancelled, f"Recipe {recipe_id}")
                    node = node_by_recipe[recipe_id]
                    if node.status == "REUSE_CURRENT":
                        if node.current_artifact_id is None:
                            raise DataManagerOperationError(
                                "reused materialization node has no current Artifact"
                            )
                        loaded = self._artifacts.load_artifact_by_id(
                            plan.target_market_id, node.current_artifact_id
                        )
                        if loaded.metadata.source_ohlcv != plan.source_ohlcv:
                            raise DataManagerOperationError(
                                "reused managed Artifact source changed"
                            )
                        frames_by_recipe[recipe_id] = loaded.frame
                        metadata_by_recipe[recipe_id] = loaded.metadata
                        artifact_ids_by_recipe[recipe_id] = node.current_artifact_id
                        message = f"Reusing managed Artifact {node.logical_artifact_id}"
                    else:
                        try:
                            calculation = _calculate_recipe(
                                recipes[recipe_id],
                                recipes,
                                target_frame,
                                frames_by_recipe,
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            raise DataManagerOperationError(
                                "managed Artifact calculation failed for Recipe "
                                f"{recipe_id} ({recipes[recipe_id].tool_key}): {exc}"
                            ) from exc
                        calculations[recipe_id] = calculation
                        frames_by_recipe[recipe_id] = calculation.result.to_frame()
                        message = (
                            f"Calculating {recipes[recipe_id].tool_key} "
                            f"{completed + 1}/{total}"
                        )
                    completed += 1
                    if progress is not None:
                        progress(completed, total, message)

            operation_created_at = datetime.now(UTC)
            prepared = []
            for recipe_id in recomputed.member_recipe_ids:
                node = node_by_recipe[recipe_id]
                if node.status == "REUSE_CURRENT":
                    continue
                _raise_materialization_cancelled(cancelled, "candidate preparation")
                recipe = recipes[recipe_id]
                refs = _source_refs(recipe, artifact_ids_by_recipe)
                source_metadata_by_id = {
                    metadata_by_recipe[item.recipe_id].artifact_id:
                    metadata_by_recipe[item.recipe_id]
                    for item in recipe.dependencies
                }
                source_metadata = tuple(source_metadata_by_id.values())
                calculation = calculations[recipe_id]
                candidate = self._artifacts.prepare_managed_calculation(
                    plan.target_market_id,
                    recipe_id,
                    calculation.result,
                    expected_source=plan.source_ohlcv,
                    source_artifacts=refs,
                    source_metadata=source_metadata,
                    previous_artifact_id=node.previous_artifact_id,
                    created_at_utc=operation_created_at,
                )
                prepared.append(candidate)
                artifact_ids_by_recipe[recipe_id] = candidate.metadata.artifact_id
                metadata_by_recipe[recipe_id] = candidate.metadata

            _raise_materialization_cancelled(cancelled, "publication")
            if progress is not None:
                progress(total, total, "Publishing managed Artifact graph")
            if prepared:
                publication = self._artifacts.publish_managed_artifact_graph(
                    tuple(prepared),
                    expected_source=plan.source_ohlcv,
                    before_publish=before_publish,
                )
                created_ids = publication.created_artifact_ids
                publication_reused_ids = publication.reused_artifact_ids
                publication_created_keys = publication.created_version_keys
                publication_reused_keys = publication.reused_version_keys
                advanced_ids = publication.advanced_logical_artifact_ids
            else:
                current_source = self._artifacts.capture_accepted_source(
                    plan.target_market_id
                )
                if current_source != plan.source_ohlcv:
                    raise DataManagerOperationError(
                        "accepted OHLCV source changed during reused materialization"
                    )
                created_ids = ()
                publication_reused_ids = ()
                publication_created_keys = ()
                publication_reused_keys = ()
                advanced_ids = ()
            created_id_set = set(created_ids)
            publication_reused_id_set = set(publication_reused_ids)
            publication_created_key_set = set(publication_created_keys)
            publication_reused_key_set = set(publication_reused_keys)
            projected_created_ids: list[str] = []
            projected_reused_ids: list[str] = []
            projected_created_keys: list[ManagedArtifactVersionKey] = []
            projected_reused_keys: list[ManagedArtifactVersionKey] = []
            seen_created_ids: set[str] = set()
            seen_reused_ids: set[str] = set()
            seen_created_keys: set[ManagedArtifactVersionKey] = set()
            seen_reused_keys: set[ManagedArtifactVersionKey] = set()
            for node in recomputed.nodes:
                artifact_id = artifact_ids_by_recipe[node.portable_recipe_id]
                version_key = ManagedArtifactVersionKey(
                    node.logical_artifact_id, artifact_id
                )
                if artifact_id in created_id_set:
                    if artifact_id not in seen_created_ids:
                        projected_created_ids.append(artifact_id)
                        seen_created_ids.add(artifact_id)
                elif (
                    node.status == "REUSE_CURRENT"
                    or artifact_id in publication_reused_id_set
                ) and artifact_id not in seen_reused_ids:
                    projected_reused_ids.append(artifact_id)
                    seen_reused_ids.add(artifact_id)
                if version_key in publication_created_key_set:
                    if version_key not in seen_created_keys:
                        projected_created_keys.append(version_key)
                        seen_created_keys.add(version_key)
                elif (
                    node.status == "REUSE_CURRENT"
                    or version_key in publication_reused_key_set
                ) and version_key not in seen_reused_keys:
                    projected_reused_keys.append(version_key)
                    seen_reused_keys.add(version_key)
            managed_by_id = {
                item.logical_artifact_id: item
                for item in self._artifacts.list_managed_artifacts(plan.target_market_id)
            }
            projected = tuple(
                _project_managed_artifact(managed_by_id[node.logical_artifact_id])
                for node in recomputed.nodes
            )
            result = DataManagerArtifactMaterializationResult(
                plan_id=plan.plan_id,
                target_market_id=plan.target_market_id,
                source_ohlcv=plan.source_ohlcv,
                root_logical_artifact_ids=tuple(
                    node_by_recipe[recipe_id].logical_artifact_id
                    for recipe_id in recomputed.root_recipe_ids
                ),
                support_logical_artifact_ids=tuple(
                    node.logical_artifact_id
                    for node in recomputed.nodes
                    if node.role == "SUPPORT"
                ),
                created_artifact_ids=tuple(projected_created_ids),
                reused_artifact_ids=tuple(projected_reused_ids),
                created_version_keys=tuple(projected_created_keys),
                reused_version_keys=tuple(projected_reused_keys),
                advanced_logical_artifact_ids=tuple(advanced_ids),
                managed_artifacts=projected,
            )
            self._updates.invalidate()
            return result
        except DataManagerOperationError:
            raise
        except (
            ArtifactError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
            PortableRecipeGraphError,
            HistoricalDatasetLoadError,
            ArtifactMaterializationValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def inspect_managed_artifact(
        self, market_id: MarketId, logical_artifact_id: str
    ) -> DataManagerManagedArtifactHistory:
        return self.list_managed_artifact_versions(market_id, logical_artifact_id)

    def scan_managed_artifacts(self) -> DataManagerManagedArtifactCatalog:
        list_markets = getattr(self._artifacts, "list_managed_markets", None)
        list_artifacts = getattr(self._artifacts, "list_managed_artifacts", None)
        if not callable(list_markets) or not callable(list_artifacts):
            return DataManagerManagedArtifactCatalog(())
        values = tuple(
            _project_managed_artifact(summary)
            for market_id in list_markets()
            for summary in list_artifacts(market_id)
        )
        return DataManagerManagedArtifactCatalog(values)

    def scan_product_catalogs(self) -> DataManagerProductCatalogSnapshot:
        reconciliation = self.latest_update_status()
        currentness = {
            item.database_id: item for item in reconciliation.databases
        }
        databases: list[DataManagerDatabaseCatalogEntry] = []
        for database_id in self.list_database_ids():
            definition = self.load_database_definition(database_id)
            revisions = self.list_database_revisions(database_id)
            current_manifest = revisions[-1] if revisions else None
            databases.append(
                DataManagerDatabaseCatalogEntry(
                    definition=definition,
                    current_manifest=current_manifest,
                    revision_count=len(revisions),
                    currentness=currentness.get(database_id),
                )
            )
        return DataManagerProductCatalogSnapshot(
            catalog=self.scan_catalog(),
            study_environments=self.scan_study_environments(),
            portable_recipes=self.scan_portable_recipes(),
            recipe_collections=self.list_recipe_collections(),
            managed_artifacts=self.scan_managed_artifacts(),
            artifact_collections=self.list_artifact_collections(),
            database_seeds=self.list_database_seeds(),
            databases=tuple(databases),
            latest_reconciliation=reconciliation,
        )

    def list_managed_artifact_versions(
        self, market_id: MarketId, logical_artifact_id: str
    ) -> DataManagerManagedArtifactHistory:
        market = _canonical_market(market_id)
        try:
            summary = next(
                item
                for item in self._artifacts.list_managed_artifacts(market)
                if item.logical_artifact_id == logical_artifact_id
            )
            if not summary.valid:
                raise ArtifactLineageError(summary.rejection_reason)
            recipe = self._portable_recipes.load_recipe(summary.portable_recipe_id)
            if recipe.recipe_id != summary.portable_recipe_id:
                raise ArtifactLineageError("portable Recipe identity disagrees")
            versions = self._artifacts.list_artifact_versions(
                market, logical_artifact_id
            )
            if any(
                item.portable_recipe_id != summary.portable_recipe_id
                for item in versions
            ):
                raise ArtifactLineageError(
                    "managed history contains another portable Recipe"
                )
            return DataManagerManagedArtifactHistory(
                _project_managed_artifact(summary), versions
            )
        except (
            ArtifactError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
            StopIteration,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def _analyze_environment(self, environment: StudyEnvironmentV1) -> _EnvironmentAnalysis:
        classifications: list[DataManagerStudyEntryPortability] = []
        recipes: dict[str, PortableRecipeV1] = {}
        dependency_entries: dict[str, tuple[str, ...]] = {}
        entries = tuple(environment.entries)
        by_id = {item.entry_id: item for item in entries}
        index_by_id = {item.entry_id: index for index, item in enumerate(entries)}

        for index, entry in enumerate(entries):
            status = "PORTABLE"
            reason = ""
            dependencies: list[tuple[StudyEnvironmentSourceV1, str]] = []
            artifact_owner: dict[str, str] = {}
            if environment.created_from is None:
                status = "UNSUPPORTED"
                reason = "Study Environment has no canonical origin MarketId"
            elif entry.mode == "artifact":
                status = "MARKET_BOUND"
                reason = "artifact-mode Study entries are target-bound"
            elif entry.tool_key == "dynamic_binning":
                status = "UNSUPPORTED"
                reason = "dynamic_binning is not a portable Recipe"
            else:
                for source in entry.sources:
                    owner_id = None
                    if source.source_kind == "environment":
                        owner_id = source.source_entry_id
                    elif source.source_kind == "artifact":
                        candidates = tuple(
                            candidate.entry_id
                            for candidate in entries[:index]
                            if candidate.mode == "calculation"
                            and candidate.kind == source.artifact_kind
                            and candidate.tool_key == source.artifact_tool_key
                            and source.output_name in candidate.expected_output_names
                        )
                        if len(candidates) != 1:
                            status = "MARKET_BOUND"
                            reason = (
                                "Artifact source does not map to exactly one earlier "
                                "calculation entry"
                            )
                            break
                        owner_id = candidates[0]
                        prior_owner = artifact_owner.setdefault(source.artifact_id, owner_id)
                        if prior_owner != owner_id:
                            status = "MARKET_BOUND"
                            reason = "Artifact source roles do not resolve to one prior entry"
                            break
                    if owner_id is not None:
                        owner = by_id.get(owner_id)
                        if owner is None or index_by_id[owner_id] >= index:
                            status = "INVALID"
                            reason = "dependency does not reference an earlier entry"
                            break
                        owner_classification = next(
                            item for item in classifications if item.entry_id == owner_id
                        )
                        if owner_classification.status not in {
                            "PORTABLE", "PORTABLE_WITH_DEPENDENCIES"
                        }:
                            status = "MARKET_BOUND"
                            reason = "dependency entry is not portable"
                            break
                        dependencies.append((source, owner_id))

            recipe = None
            if status == "PORTABLE":
                ohlcv = tuple(
                    PortableRecipeOHLCVInputV1(source.role, source.column_name)
                    for source in entry.sources
                    if source.source_kind == "ohlcv"
                )
                recipe_dependencies = tuple(
                    PortableRecipeDependencyV1(
                        source.role,
                        recipes[owner_id].recipe_id,
                        source.output_name,
                    )
                    for source, owner_id in dependencies
                )
                if recipe_dependencies:
                    status = "PORTABLE_WITH_DEPENDENCIES"
                recipe = build_portable_recipe(
                    tool_key=entry.tool_key,
                    kind=entry.kind,
                    parameters=entry.parameters,
                    output_names=entry.expected_output_names,
                    ohlcv_inputs=ohlcv,
                    dependencies=recipe_dependencies,
                )
                recipes[entry.entry_id] = recipe
                dependency_entries[entry.entry_id] = tuple(
                    dict.fromkeys(owner_id for _source, owner_id in dependencies)
                )
            classifications.append(
                DataManagerStudyEntryPortability(
                    entry.entry_id,
                    entry.display_name,
                    entry.mode,
                    entry.kind,
                    entry.tool_key,
                    status,
                    reason,
                    dependency_entries.get(entry.entry_id, ()),
                    None if recipe is None else recipe.recipe_id,
                )
            )
        return _EnvironmentAnalysis(
            tuple(classifications),
            MappingProxyType(recipes),
            MappingProxyType(dependency_entries),
        )

    def _build_derivation_plan(
        self, environment: StudyEnvironmentV1, root_entry_ids: tuple[str, ...]
    ) -> DataManagerRecipeDerivationPlan:
        roots = tuple(root_entry_ids)
        if not roots or any(not isinstance(item, str) or not item for item in roots):
            raise DataManagerOperationError("root_entry_ids must contain at least one entry")
        if len(set(roots)) != len(roots):
            raise DataManagerOperationError("root_entry_ids must be unique")
        analysis = self._analyze_environment(environment)
        classification_by_id = {
            item.entry_id: item for item in analysis.classifications
        }
        entry_by_id = {item.entry_id: item for item in environment.entries}
        blockers: list[str] = []
        for root in roots:
            entry = entry_by_id.get(root)
            if entry is None:
                blockers.append(f"selected root does not exist: {root}")
                continue
            if entry.mode != "calculation":
                blockers.append(f"selected root is not a calculation entry: {root}")
                continue
            classification = classification_by_id[root]
            if classification.status not in {"PORTABLE", "PORTABLE_WITH_DEPENDENCIES"}:
                blockers.append(
                    f"selected root {root} is {classification.status}: {classification.reason}"
                )

        included: set[str] = set()

        def include(entry_id: str) -> None:
            if entry_id in included:
                return
            for dependency_id in analysis.dependency_entries.get(entry_id, ()):
                include(dependency_id)
            included.add(entry_id)

        if not blockers:
            for root in roots:
                include(root)
        ordered_entries = tuple(
            item.entry_id for item in environment.entries if item.entry_id in included
        )
        support = tuple(item for item in ordered_entries if item not in set(roots))
        recipes = tuple(analysis.recipes_by_entry[item] for item in ordered_entries)
        provenances: tuple[PortableRecipeProvenanceV1, ...] = ()
        graph = PortableRecipeGraphPlan((), (), (), ())
        if not blockers:
            assert environment.created_from is not None
            provenances = tuple(
                PortableRecipeProvenanceV1.build(
                    recipe_id=analysis.recipes_by_entry[item.entry_id].recipe_id,
                    origin_market_id=environment.created_from,
                    study_environment_id=environment.environment_id,
                    study_environment_content_hash=environment.content_hash,
                    study_environment_updated_at_utc=environment.updated_at_utc,
                    study_environment_display_name=environment.display_name,
                    study_entry_id=item.entry_id,
                    study_display_name=item.display_name,
                    study_description=item.user_metadata.description,
                )
                for item in environment.entries
                if item.entry_id in included
            )
            recipe_by_id = {item.recipe_id: item for item in recipes}
            root_recipe_ids = tuple(
                analysis.recipes_by_entry[item].recipe_id for item in roots
            )
            graph = self._recipe_planner.plan(root_recipe_ids, recipes=recipe_by_id)
        return DataManagerRecipeDerivationPlan(
            environment.environment_id,
            environment.content_hash,
            roots,
            support,
            analysis.classifications,
            recipes,
            provenances,
            graph.dependency_edges,
            graph.execution_stages,
            (),
            tuple(blockers),
        )


def _validate_collection_metadata(
    display_name: object, description: object
) -> tuple[str, str]:
    if (
        not isinstance(display_name, str)
        or not display_name
        or display_name != display_name.strip()
    ):
        raise DataManagerOperationError(
            "Collection display name must be canonical non-empty text"
        )
    if not isinstance(description, str) or description != description.strip():
        raise DataManagerOperationError("Collection description must be canonical text")
    return display_name, description


def _project_catalog(report: DatasetCatalogReport) -> DataManagerCatalogSnapshot:
    entries = [
        DataManagerDatasetEntry(
            market_id=item.market_id,
            accepted=True,
            row_count=item.row_count,
            first_timestamp_ms=item.first_timestamp_ms,
            last_timestamp_ms=item.last_timestamp_ms,
            source=item.source,
            persistence_status=item.persistence_status,
            validation_status=item.validation_status,
            warnings=tuple(item.warnings),
        )
        for item in report.accepted
    ]
    entries.extend(
        DataManagerDatasetEntry(
            market_id=item.market_id,
            accepted=False,
            rejection_code=item.code,
            rejection_reason=item.reason,
        )
        for item in report.rejected
    )
    return DataManagerCatalogSnapshot(tuple(entries))


def _project_recipe(summary: RecipeSummary) -> DataManagerRecipeEntry:
    return DataManagerRecipeEntry(
        market_id=summary.market_id,
        recipe_id=summary.recipe_id,
        tool_key=summary.tool_key,
        kind=summary.kind,
        output_names=tuple(summary.output_names),
        display_name=summary.display_name,
        created_at_utc=summary.created_at_utc,
        valid=summary.valid,
        rejection_reason=summary.rejection_reason or "",
    )


def _project_artifact(summary: ArtifactSummary) -> DataManagerArtifactEntry:
    return DataManagerArtifactEntry(
        market_id=summary.market_id,
        artifact_id=summary.artifact_id,
        recipe_id=summary.recipe_id,
        tool_key=summary.tool_key,
        kind=summary.kind,
        output_names=tuple(summary.output_names),
        row_count=summary.row_count,
        first_timestamp_ms=summary.first_timestamp_ms,
        last_timestamp_ms=summary.last_timestamp_ms,
        created_at_utc=summary.created_at_utc,
        valid=summary.valid,
        rejection_reason=summary.rejection_reason or "",
        current_status="unknown" if summary.valid else "invalid",
    )


def _project_managed_artifact(
    summary: ManagedArtifactSummary,
) -> DataManagerManagedArtifactEntry:
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


def _raise_materialization_cancelled(
    cancellation_requested: Callable[[], bool], stage: str
) -> None:
    if cancellation_requested():
        raise RuntimeError(
            f"Data Manager operation cancelled before {stage}"
        )


def _bounded_rows(rows: Sequence[tuple[object, ...]], limit: int) -> tuple[tuple[object, ...], ...]:
    total = len(rows)
    if total <= limit:
        return tuple(rows)
    head = (limit + 1) // 2
    tail = limit // 2
    return (*rows[:head], *rows[total - tail :])


def _format_timestamp(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DataManagerOperationError("timestamp values must be numeric integers")
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 0:
        raise DataManagerOperationError("timestamp values must be finite non-negative integers")
    return str(int(numeric))


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        numeric = float(value)
        if math.isnan(numeric):
            return ""
        if not math.isfinite(numeric):
            raise DataManagerOperationError("preview values cannot contain infinity")
        return format(numeric, ".15g")
    raise DataManagerOperationError(
        f"preview values must be strings, booleans, or finite numbers: {type(value).__name__}"
    )


def _validate_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("preview limit must be an integer from 1 through 500")


def _canonical_market(market_id: MarketId) -> MarketId:
    if not isinstance(market_id, MarketId):
        raise TypeError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        market_id.exchange,
        market_id.market_type,
        market_id.symbol,
        market_id.timeframe,
    )
    if canonical != market_id:
        raise ValueError(f"market_id must already be canonical: {canonical!r}")
    return market_id


def _require_methods(value: object, name: str, methods: tuple[str, ...]) -> None:
    missing = [method for method in methods if not callable(getattr(value, method, None))]
    if missing:
        raise TypeError(f"{name} must expose callable methods: {', '.join(missing)}")


def format_created_at(value: datetime | None) -> str:
    """Return one stable display timestamp for GUI projections."""

    if value is None:
        return ""
    if not isinstance(value, datetime):
        raise TypeError("created_at_utc must be a timezone-aware datetime or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at_utc must be timezone-aware")
    resolved = value.astimezone(UTC)
    return resolved.isoformat().replace("+00:00", "Z")


def _optional_filter(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text or None")
    return value.strip()


def _environment_filters(
    exchange: str | None,
    market_type: str | None,
    symbol: str | None,
    timeframe: str | None,
    display_name_text: str | None,
) -> tuple[str | None, ...]:
    return (
        None if exchange is None else normalize_exchange(_optional_filter(exchange, "exchange")),
        None if market_type is None else normalize_market_type(_optional_filter(market_type, "market_type")),
        None if symbol is None else normalize_symbol(_optional_filter(symbol, "symbol")),
        None if timeframe is None else normalize_timeframe(_optional_filter(timeframe, "timeframe")),
        None if display_name_text is None else _optional_filter(display_name_text, "display_name_text").casefold(),
    )


def _environment_matches(
    item: DataManagerStudyEnvironmentEntry, filters: tuple[str | None, ...]
) -> bool:
    exchange, market_type, symbol, timeframe, display = filters
    if display is not None and display not in item.display_name.casefold():
        return False
    if all(value is None for value in (exchange, market_type, symbol, timeframe)):
        return True
    market = item.origin_market_id
    if market is None:
        return False
    return all(
        expected is None or actual == expected
        for actual, expected in zip(
            (market.exchange, market.market_type, market.symbol, market.timeframe),
            (exchange, market_type, symbol, timeframe),
            strict=True,
        )
    )


def _recipe_filters(
    exchange: str | None,
    market_type: str | None,
    symbol: str | None,
    timeframe: str | None,
    tool_key: str | None,
    display_name_text: str | None,
) -> tuple[str | None, ...]:
    market_filters = _environment_filters(
        exchange, market_type, symbol, timeframe, None
    )[:4]
    return (
        *market_filters,
        None if tool_key is None else _optional_filter(tool_key, "tool_key"),
        None if display_name_text is None else _optional_filter(display_name_text, "display_name_text").casefold(),
    )


def _recipe_matches(
    item: DataManagerPortableRecipeEntry, filters: tuple[str | None, ...]
) -> bool:
    exchange, market_type, symbol, timeframe, tool_key, display = filters
    if tool_key is not None and item.tool_key != tool_key:
        return False
    if display is not None and not any(
        display in name.casefold() for name in item.origin_study_display_names
    ):
        return False
    market_filters = (exchange, market_type, symbol, timeframe)
    if all(value is None for value in market_filters):
        return True
    return any(
        all(
            expected is None or actual == expected
            for actual, expected in zip(
                (market.exchange, market.market_type, market.symbol, market.timeframe),
                market_filters,
                strict=True,
            )
        )
        for market in item.origin_market_ids
    )


def _collection_entry(summary, graph: PortableRecipeGraphPlan) -> DataManagerRecipeCollectionEntry:
    return DataManagerRecipeCollectionEntry(
        summary.collection_id,
        summary.revision_id,
        summary.display_name,
        summary.description,
        summary.root_count,
        summary.member_count,
        len(graph.dependency_edges),
        len(graph.execution_stages),
        summary.created_at_utc,
        summary.updated_at_utc,
    )
