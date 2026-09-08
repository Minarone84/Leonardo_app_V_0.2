"""Read/manage orchestration over canonical dataset and artifact authorities."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from numbers import Integral, Real
from types import MappingProxyType
from typing import Protocol

from leonardo.artifacts import (
    ArtifactError,
    ArtifactMetadataV1,
    ArtifactRecipeV1,
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
from leonardo.financial_tools import (
    get_financial_tool_spec,
    resolve_output_signals,
    resolve_parameters,
)
from leonardo.financial_tools.construct_input_eligibility import (
    FinancialToolInputCompatibilityError,
    FinancialToolInputSource,
    validate_financial_tool_inputs,
)
from leonardo.recipes import (
    PortableRecipeGraphError,
    PortableRecipeGraphEdge,
    PortableRecipeGraphPlan,
    PortableRecipeGraphPlanner,
    PortableRecipeCollectionRevisionV1,
    PortableRecipeOHLCVInputV1,
    PortableRecipeDependencyV1,
    PortableRecipeProvenanceV1,
    PortableRecipeStore,
    PortableRecipeStoreError,
    PortableRecipeV1,
    PortableRecipeValidationError,
    build_portable_recipe,
)
from leonardo.recipes.identity import (
    normalize_portable_recipe_parameters,
    object_semantic_key,
    object_semantic_parameters,
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
    DuplicateMaintenanceCandidate,
    DuplicateMaintenanceDomain,
    DuplicateMaintenanceGroup,
    DuplicateMaintenancePreflight,
    DuplicateMaintenancePurgeDetail,
    DuplicateMaintenancePurgeResult,
    DuplicateMaintenanceScanResult,
    duplicate_maintenance_domain,
)
from .artifact_materialization import (
    ArtifactMaterializationValidationError,
    _calculate_artifact_configuration,
    _calculate_artifact_recipe,
    _calculate_recipe,
    _dataset_frame,
    _plan_id,
    _source_refs,
    _target_configuration,
    _validate_recipe_execution,
)
from .construct_sources import list_construct_source_signals
from .creation_models import (
    ArtifactCollectionDependencyV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionSelectionPlan,
    ArtifactCollectionValidation,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DatabaseCollectionReferenceV2,
    DatabaseContentAdditionPlan,
    DatabaseRevisionManifest,
    DatabaseReadiness,
    DatabaseDefinitionV1,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DatabaseSeedV1,
    DatabaseSeedCreationPlan,
    DataManagerCreationError,
    SeedOnlyDatabaseCreationPlan,
    database_collection_references,
    deterministic_hash,
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
from .direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
    DataManagerDirectArtifactRequest,
    DataManagerDirectArtifactResult,
    DataManagerDirectArtifactSource,
    _build_direct_portable_recipe,
)


_DATASET_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")


def _artifact_configuration_label(recipe: object) -> str:
    tool_key = getattr(recipe, "tool_key")
    parameters = getattr(recipe, "parameters")
    spec = get_financial_tool_spec(tool_key)
    values = tuple(
        f"{parameter.name}={_format_configuration_scalar(parameters[parameter.name])}"
        for parameter in spec.parameters
        if parameter.name in parameters
    )
    return spec.title if not values else f"{spec.title} [{', '.join(values)}]"


def _invalid_duplicate_candidate(
    object_id: str, reason: str
) -> DuplicateMaintenanceCandidate:
    return DuplicateMaintenanceCandidate(
        object_id,
        "INVALID / SKIPPED",
        reason or "persisted object is invalid",
    )


def _duplicate_scan_progress(
    domain: DuplicateMaintenanceDomain,
    current: int,
    total: int,
    progress: Callable[[int, int, str], None] | None,
    cancellation_requested: Callable[[], bool] | None,
) -> None:
    if cancellation_requested is not None and cancellation_requested():
        raise RuntimeError("Data Manager duplicate maintenance scan cancelled")
    if progress is not None:
        progress(
            current,
            total,
            f"Scanning {domain.display_name} {current} / {total}",
        )


def _duplicate_purge_progress(
    domain: DuplicateMaintenanceDomain,
    current: int,
    total: int,
    progress: Callable[[int, int, str], None] | None,
    cancellation_requested: Callable[[], bool] | None,
) -> None:
    if cancellation_requested is not None and cancellation_requested():
        raise RuntimeError("Data Manager duplicate purge cancelled")
    if progress is not None:
        progress(
            current,
            total,
            f"Purging {domain.display_name} duplicates {current} / {total}",
        )


def _sorted_duplicate_groups(
    groups: Sequence[DuplicateMaintenanceGroup],
) -> tuple[DuplicateMaintenanceGroup, ...]:
    return tuple(
        sorted(
            groups,
            key=lambda item: (
                item.canonical_id,
                tuple(candidate.object_id for candidate in item.duplicates),
            ),
        )
    )


def _database_collection_ids_for_deletion_proof(
    manifest: object,
) -> tuple[str, ...]:
    if isinstance(manifest, (DatabaseRevisionManifestV1, DatabaseRevisionManifestV2)):
        return tuple(
            reference.collection_id
            for reference in database_collection_references(manifest)
        )
    collection_id = getattr(manifest, "collection_id", None)
    if isinstance(collection_id, str) and collection_id:
        return (collection_id,)
    raise TypeError("manifest must provide Database Collection reference evidence")


def _format_configuration_scalar(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format(value, ".15g")
    return str(value)


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
    def list_managed_markets(self) -> tuple[MarketId, ...]: ...
    def list_managed_artifacts(
        self, market_id: MarketId
    ) -> tuple[ManagedArtifactSummary, ...]: ...
    def list_artifact_versions(
        self, market_id: MarketId, logical_artifact_id: str
    ) -> tuple[object, ...]: ...
    def delete_managed_artifact(
        self,
        market_id: MarketId,
        logical_artifact_id: str,
        *,
        before_delete: Callable[[], None] | None = None,
    ) -> ManagedArtifactSummary: ...


class _StudyEnvironments(Protocol):
    def list_summaries(self) -> tuple[object, ...]: ...
    def load(self, environment_id: str) -> StudyEnvironmentV1: ...


@dataclass(frozen=True, slots=True)
class _EnvironmentAnalysis:
    classifications: tuple[DataManagerStudyEntryPortability, ...]
    recipes_by_entry: Mapping[str, PortableRecipeV1]
    dependency_entries: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _DirectArtifactDependency:
    role: str
    logical_artifact_id: str
    portable_recipe_id: str
    output_name: str


@dataclass(frozen=True, slots=True)
class _DirectArtifactSemanticDependency:
    role: str
    portable_recipe_id: str
    output_name: str


@dataclass(frozen=True, slots=True)
class _DirectArtifactSemanticDescriptor:
    tool_key: str
    kind: str
    parameters: Mapping[str, object]
    bindings: Mapping[str, object]
    output_names: tuple[str, ...]
    dependencies: tuple[_DirectArtifactSemanticDependency, ...]


@dataclass(frozen=True, slots=True)
class _DirectArtifactMember:
    portable_recipe_id: str
    logical_artifact_id: str
    tool_key: str
    kind: str
    parameters: Mapping[str, object]
    bindings: Mapping[str, object]
    output_names: tuple[str, ...]
    dependencies: tuple[_DirectArtifactDependency, ...]


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
        resolved_creation_store = creation_store or DataManagerCreationStore(
            portable_recipes.root_dir
        )
        resolved_creation_store.set_collection_semantic_key_resolver(
            self._artifact_collection_semantic_key_parts
        )
        self._creation = DataManagerCreationWorkflow(
            store=resolved_creation_store,
            catalog=catalog,
            loader=loader,
            artifacts=artifacts,
            batch_materialization_planner=self._plan_batch_artifact_materialization,
            batch_materialization_executor=self._execute_direct_artifact_materialization,
            portable_recipe_resolver=self._resolve_portable_recipe_candidates,
            portable_recipe_publisher=self._publish_portable_recipe_candidates,
        )
        self._updates = DataManagerUpdateWorkflow(
            catalog,
            loader,
            artifacts,
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

    def plan_database_seed_creation(
        self, market_id: MarketId, display_name: str, **options
    ) -> DatabaseSeedCreationPlan:
        return self._creation.plan_database_seed_creation(
            market_id, display_name, **options
        )

    def execute_database_seed_creation(
        self, plan: DatabaseSeedCreationPlan, **execution
    ) -> DatabaseSeedV1:
        result = self._creation.execute_database_seed_creation(plan, **execution)
        self._updates.invalidate()
        return result

    def plan_seed_only_database_creation(
        self, seed_id: str, display_name: str, **options
    ) -> SeedOnlyDatabaseCreationPlan:
        return self._creation.plan_seed_only_database_creation(
            seed_id, display_name, **options
        )

    def execute_seed_only_database_creation(
        self, plan: SeedOnlyDatabaseCreationPlan, **execution
    ) -> DatabaseRevisionManifestV2:
        result = self._creation.execute_seed_only_database_creation(plan, **execution)
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

    def find_equivalent_artifact_collection_for_materialization(
        self,
        plan: DataManagerArtifactMaterializationPlan,
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
    ) -> ArtifactCollectionRevisionV1 | None:
        if not isinstance(plan, DataManagerArtifactMaterializationPlan):
            raise TypeError("plan must be a DataManagerArtifactMaterializationPlan")
        if plan.blocked or any(node.status != "REUSE_CURRENT" for node in plan.nodes):
            return None
        managed_by_id = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts(plan.target_market_id)
        }
        try:
            projected = tuple(
                _project_managed_artifact(managed_by_id[node.logical_artifact_id])
                for node in plan.nodes
            )
            materialization = DataManagerArtifactMaterializationResult(
                plan.plan_id,
                plan.target_market_id,
                plan.source_ohlcv,
                tuple(
                    node.logical_artifact_id
                    for node in plan.nodes
                    if node.role == "ROOT"
                ),
                tuple(
                    node.logical_artifact_id
                    for node in plan.nodes
                    if node.role == "SUPPORT"
                ),
                (),
                tuple(node.current_artifact_id for node in plan.nodes),
                (),
                tuple(
                    ManagedArtifactVersionKey(
                        node.logical_artifact_id, node.current_artifact_id
                    )
                    for node in plan.nodes
                ),
                (),
                projected,
            )
            values = self._creation._collection_values_from_materialization(
                materialization, selected_outputs
            )
            return self.creation_store.find_equivalent_collection(
                market_id=values["market_id"],
                source_ohlcv=values["source_ohlcv"],
                root_logical_artifact_ids=values["roots"],
                support_logical_artifact_ids=values["supports"],
                members=values["members"],
                selected_outputs=values["selected_outputs"],
                presentation_order=values["presentation_order"],
            )
        except (ArtifactError, DataManagerCreationError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def plan_artifact_collection_selection(
        self,
        market_id: MarketId,
        root_logical_artifact_ids: Sequence[str],
    ) -> ArtifactCollectionSelectionPlan:
        market = _canonical_market(market_id)
        if isinstance(root_logical_artifact_ids, (str, bytes, bytearray)):
            raise DataManagerCreationError(
                "root_logical_artifact_ids must be a sequence"
            )
        roots = tuple(root_logical_artifact_ids)
        if not roots or any(not isinstance(item, str) for item in roots):
            raise DataManagerCreationError(
                "one or more root logical Artifact IDs are required"
            )
        if len(roots) != len(set(roots)):
            raise DataManagerCreationError(
                "root logical Artifact IDs must be unique"
            )
        try:
            current_source = self._artifacts.capture_accepted_source(market)
            summaries = tuple(self._artifacts.list_managed_artifacts(market))
            summaries_by_id: dict[str, list[ManagedArtifactSummary]] = {}
            for summary in summaries:
                summaries_by_id.setdefault(summary.logical_artifact_id, []).append(
                    summary
                )
            for logical_id in roots:
                matches = summaries_by_id.get(logical_id, ())
                if len(matches) != 1:
                    raise DataManagerCreationError(
                        "root managed Artifact must exist exactly once: "
                        f"{logical_id}"
                    )
                if not matches[0].valid:
                    raise DataManagerCreationError(
                        "root managed Artifact is invalid: "
                        f"{matches[0].rejection_reason}"
                    )

            managed = {
                logical_id: values[0]
                for logical_id, values in summaries_by_id.items()
                if len(values) == 1 and values[0].valid
            }
            versions_by_logical_id: dict[str, tuple[object, ...]] = {}
            version_owners: dict[str, tuple[str, str]] = {}
            for summary in managed.values():
                versions = tuple(
                    self._artifacts.list_artifact_versions(
                        market, summary.logical_artifact_id
                    )
                )
                if not versions:
                    raise ArtifactLineageError(
                        "managed Artifact lineage has no versions"
                    )
                versions_by_logical_id[summary.logical_artifact_id] = versions
                for version in versions:
                    if (
                        version.logical_artifact_id
                        != summary.logical_artifact_id
                        or version.portable_recipe_id
                        != summary.portable_recipe_id
                        or version.market_id != market
                    ):
                        raise ArtifactLineageError(
                            "managed Artifact version ownership is inconsistent"
                        )
                    owner = (
                        version.logical_artifact_id,
                        version.portable_recipe_id,
                    )
                    previous = version_owners.setdefault(
                        version.artifact_id, owner
                    )
                    if previous != owner:
                        raise ArtifactLineageError(
                            "physical Artifact version has ambiguous managed ownership"
                        )

            selected_physical: dict[str, str] = {}
            member_values: dict[str, ArtifactCollectionMemberV1] = {}
            transient_members: dict[str, _DirectArtifactMember] = {}
            metadata_by_id: dict[str, ArtifactMetadataV1] = {}
            edges: list[ArtifactCollectionDependencyV1] = []
            visiting: set[str] = set()

            def collect(logical_id: str, artifact_id: str) -> None:
                previous = selected_physical.get(logical_id)
                if previous is not None:
                    if previous != artifact_id:
                        raise ArtifactLineageError(
                            "logical Artifact resolves to conflicting physical versions"
                        )
                    return
                if logical_id in visiting:
                    raise ArtifactLineageError(
                        "managed Artifact dependency graph contains a cycle"
                    )
                owner = version_owners.get(artifact_id)
                if owner is None or owner[0] != logical_id:
                    raise ArtifactLineageError(
                        "Artifact source version has no exact managed owner"
                    )
                summary = managed.get(logical_id)
                if (
                    summary is None
                    or summary.portable_recipe_id != owner[1]
                    or summary.market_id != market
                ):
                    raise ArtifactLineageError(
                        "Artifact source owner is not a current valid managed Artifact"
                    )
                versions = versions_by_logical_id.get(logical_id)
                if versions is None:
                    raise ArtifactLineageError(
                        "managed Artifact lineage has no versions"
                    )
                descriptor = self._validate_direct_artifact_semantic_lineage(
                    market, summary, versions, version_owners
                )
                selected_physical[logical_id] = artifact_id
                visiting.add(logical_id)
                loaded = self._artifacts.load_artifact_by_id(market, artifact_id)
                metadata = loaded.metadata
                recipe = metadata.recipe
                semantic_dependencies = tuple(
                    _DirectArtifactSemanticDependency(
                        ref.role,
                        version_owners[ref.artifact_id][1],
                        ref.output_name,
                    )
                    for ref in recipe.source_artifacts
                    if ref.artifact_id in version_owners
                )
                if (
                    metadata.artifact_id != artifact_id
                    or metadata.source_ohlcv != current_source
                    or recipe.market_id != market
                    or recipe.tool_key != descriptor.tool_key
                    or recipe.kind != descriptor.kind
                    or dict(recipe.parameters) != dict(descriptor.parameters)
                    or dict(recipe.bindings) != dict(descriptor.bindings)
                    or recipe.output_names != descriptor.output_names
                    or semantic_dependencies != descriptor.dependencies
                    or recipe.tool_key != summary.tool_key
                    or recipe.kind != summary.kind
                    or recipe.output_names != summary.output_names
                ):
                    raise ArtifactLineageError(
                        "exact Artifact version metadata is inconsistent"
                    )
                if recipe.tool_key == "dynamic_binning":
                    raise ArtifactLineageError(
                        "Dynamic Binning cannot be an Artifact Collection member"
                    )
                dependencies: list[_DirectArtifactDependency] = []
                for ref in recipe.source_artifacts:
                    dependency_owner = version_owners.get(ref.artifact_id)
                    if dependency_owner is None:
                        raise ArtifactLineageError(
                            "Artifact source version has no managed owner"
                        )
                    dependency_id, dependency_semantic_id = dependency_owner
                    collect(dependency_id, ref.artifact_id)
                    dependency_metadata = metadata_by_id[dependency_id]
                    if ref.output_name not in dependency_metadata.recipe.output_names:
                        raise ArtifactLineageError(
                            "Artifact dependency output is unavailable"
                        )
                    dependencies.append(
                        _DirectArtifactDependency(
                            ref.role,
                            dependency_id,
                            dependency_semantic_id,
                            ref.output_name,
                        )
                    )
                    edges.append(
                        ArtifactCollectionDependencyV1(
                            dependency_id,
                            logical_id,
                            ref.role,
                            ref.output_name,
                        )
                    )
                member = _DirectArtifactMember(
                    owner[1],
                    logical_id,
                    recipe.tool_key,
                    recipe.kind,
                    recipe.parameters,
                    recipe.bindings,
                    recipe.output_names,
                    tuple(dependencies),
                )
                self._validate_transient_member_compatibility(
                    member,
                    transient_members,
                    raw_inputs=(),
                    allow_partial_roles=True,
                )
                metadata_by_id[logical_id] = metadata
                transient_members[logical_id] = member
                member_values[logical_id] = ArtifactCollectionMemberV1(
                    ManagedArtifactVersionKey(logical_id, artifact_id),
                    owner[1],
                    recipe.tool_key,
                    recipe.kind,
                    recipe.output_names,
                    metadata.values_sha256,
                )
                visiting.remove(logical_id)

            for logical_id in roots:
                summary = managed[logical_id]
                loaded = self._load_direct_managed_artifact(
                    market, summary, current_source
                )
                if loaded.metadata.artifact_id != summary.artifact_id:
                    raise ArtifactLineageError(
                        "root managed Artifact is not its current head"
                    )
                collect(logical_id, summary.artifact_id)

            predecessor_ids: dict[str, set[str]] = {
                logical_id: set() for logical_id in member_values
            }
            for edge in edges:
                predecessor_ids[edge.dependent_logical_artifact_id].add(
                    edge.dependency_logical_artifact_id
                )
            stages: list[tuple[str, ...]] = []
            complete: set[str] = set()
            member_order = tuple(member_values)
            while len(complete) < len(member_order):
                stage = tuple(
                    logical_id
                    for logical_id in member_order
                    if logical_id not in complete
                    and predecessor_ids[logical_id] <= complete
                )
                if not stage:
                    raise ArtifactLineageError(
                        "managed Artifact dependency graph contains a cycle"
                    )
                stages.append(stage)
                complete.update(stage)
            ordered_ids = tuple(item for stage in stages for item in stage)
            root_set = set(roots)
            supports = tuple(
                logical_id for logical_id in ordered_ids if logical_id not in root_set
            )
            members = tuple(member_values[logical_id] for logical_id in ordered_ids)
            first = max(
                metadata_by_id[logical_id].first_timestamp_ms
                for logical_id in ordered_ids
            )
            last = min(
                metadata_by_id[logical_id].last_timestamp_ms
                for logical_id in ordered_ids
            )
            if first > last:
                raise DataManagerCreationError(
                    "Artifact Collection selection has no common coverage"
                )
            identity = {
                "market_id": {
                    "exchange": market.exchange,
                    "market_type": market.market_type,
                    "symbol": market.symbol,
                    "timeframe": market.timeframe,
                },
                "source_ohlcv": current_source.to_dict(),
                "root_logical_artifact_ids": list(roots),
                "members": [item.to_dict() for item in members],
                "dependency_edges": [item.to_dict() for item in edges],
                "execution_stages": [list(stage) for stage in stages],
                "first_timestamp_ms": first,
                "last_timestamp_ms": last,
            }
            return ArtifactCollectionSelectionPlan(
                deterministic_hash(identity),
                market,
                current_source,
                roots,
                supports,
                members,
                tuple(edges),
                tuple(stages),
                first,
                last,
            )
        except DataManagerCreationError:
            raise
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc

    def find_equivalent_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
        presentation_order: Sequence[str],
    ) -> ArtifactCollectionRevisionV1 | None:
        if not isinstance(plan, ArtifactCollectionSelectionPlan):
            raise TypeError("plan must be an ArtifactCollectionSelectionPlan")
        return self.creation_store.find_equivalent_collection(
            market_id=plan.market_id,
            source_ohlcv=plan.source_ohlcv,
            root_logical_artifact_ids=plan.root_logical_artifact_ids,
            support_logical_artifact_ids=plan.support_logical_artifact_ids,
            members=plan.members,
            selected_outputs=tuple(selected_outputs),
            presentation_order=tuple(presentation_order),
        )

    def create_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        display_name: str,
        *,
        description: str = "",
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        return self._create_artifact_collection_from_selection(
            plan,
            display_name,
            description=description,
            selected_outputs=selected_outputs,
            before_publish=None,
        )

    def _create_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        display_name: str,
        *,
        description: str,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
        before_publish: Callable[[], None] | None,
    ) -> ArtifactCollectionRevisionV1:
        fresh = self.plan_artifact_collection_selection(
            plan.market_id, plan.root_logical_artifact_ids
        )
        if fresh != plan:
            raise DataManagerCreationError(
                "Artifact Collection selection changed since Preview"
            )
        if before_publish is not None:
            before_publish()
        result = self._creation.create_artifact_collection_from_selection(
            plan,
            display_name,
            description=description,
            selected_outputs=selected_outputs,
        )
        self._updates.invalidate()
        return result

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
        return self._edit_artifact_collection_from_selection(
            collection_id,
            plan,
            display_name=display_name,
            description=description,
            selected_outputs=selected_outputs,
            presentation_order=presentation_order,
            expected_revision_id=expected_revision_id,
            before_publish=None,
        )

    def _edit_artifact_collection_from_selection(
        self,
        collection_id: str,
        plan: ArtifactCollectionSelectionPlan,
        *,
        display_name: str | None,
        description: str | None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
        presentation_order: Sequence[str] | None,
        expected_revision_id: str,
        before_publish: Callable[[], None] | None,
    ) -> ArtifactCollectionRevisionV1:
        fresh = self.plan_artifact_collection_selection(
            plan.market_id, plan.root_logical_artifact_ids
        )
        if fresh != plan:
            raise DataManagerCreationError(
                "Artifact Collection selection changed since Preview"
            )
        if before_publish is not None:
            before_publish()
        result = self._creation.edit_artifact_collection_from_selection(
            collection_id,
            plan,
            display_name=display_name,
            description=description,
            selected_outputs=selected_outputs,
            presentation_order=presentation_order,
            expected_revision_id=expected_revision_id,
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

    def inspect_artifact_collection_details(
        self, collection_id: str, revision_id: str | None = None
    ) -> tuple[
        ArtifactCollectionRevisionV1,
        ArtifactCollectionValidation,
        tuple[ArtifactMetadataV1, ...],
    ]:
        revision, validation = self._creation.inspect_artifact_collection(
            collection_id, revision_id
        )
        metadata_values: list[ArtifactMetadataV1] = []
        for member in revision.members:
            metadata = self._artifacts.load_artifact_by_id(
                revision.market_id,
                member.version_key.artifact_id,
            ).metadata
            if not isinstance(metadata, ArtifactMetadataV1):
                raise DataManagerOperationError(
                    "Artifact Collection member metadata is invalid"
                )
            comparisons = (
                ("artifact_id", metadata.artifact_id, member.version_key.artifact_id),
                ("market_id", metadata.recipe.market_id, revision.market_id),
                ("tool_key", metadata.recipe.tool_key, member.tool_key),
                ("kind", metadata.recipe.kind, member.kind),
                ("output_names", metadata.recipe.output_names, member.output_names),
                ("values_sha256", metadata.values_sha256, member.values_sha256),
            )
            mismatch = next(
                (name for name, actual, expected in comparisons if actual != expected),
                None,
            )
            if mismatch is not None:
                raise DataManagerOperationError(
                    "Artifact Collection member metadata does not match Collection "
                    f"truth: {mismatch}"
                )
            metadata_values.append(metadata)
        metadata_tuple = tuple(metadata_values)
        if len(metadata_tuple) != len(revision.members):
            raise DataManagerOperationError(
                "Artifact Collection member metadata count does not match Collection truth"
            )
        return revision, validation, metadata_tuple

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

    def plan_database_artifact_addition(
        self,
        database_id: str,
        root_logical_artifact_ids: Sequence[str],
    ) -> DatabaseContentAdditionPlan:
        definition = self._creation.load_database_definition(database_id)
        selection = self.plan_artifact_collection_selection(
            definition.market_id, root_logical_artifact_ids
        )
        members = {
            item.version_key.logical_artifact_id: item
            for item in selection.members
        }
        outputs = tuple(
            ArtifactCollectionOutputV1(logical_id, output_name, output_name)
            for logical_id in selection.root_logical_artifact_ids
            for output_name in members[logical_id].output_names
        )
        return self._creation.plan_database_content_addition(
            database_id,
            selection,
            selected_outputs=outputs,
            source_kind="artifacts",
        )

    def plan_database_collection_addition(
        self,
        database_id: str,
        collection_id: str,
    ) -> DatabaseContentAdditionPlan:
        collection = self._creation.load_artifact_collection(collection_id)
        validation = self._creation.validate_artifact_collection(
            collection_id, collection.revision_id
        )
        if not validation.valid:
            raise DataManagerCreationError(
                "Artifact Collection is not current and valid: "
                + "; ".join(validation.blockers)
            )
        selection = self.plan_artifact_collection_selection(
            collection.market_id, collection.root_logical_artifact_ids
        )
        if (
            selection.source_ohlcv != collection.source_ohlcv
            or selection.members != collection.members
            or selection.dependency_edges != collection.dependency_edges
        ):
            raise DataManagerCreationError(
                "Artifact Collection no longer matches current managed Artifact truth"
            )
        reference = DatabaseCollectionReferenceV2(
            collection.collection_id, collection.revision_id
        )
        return self._creation.plan_database_content_addition(
            database_id,
            selection,
            selected_outputs=collection.selected_outputs,
            source_kind="collection",
            source_collection=reference,
        )

    def execute_database_content_addition(
        self,
        plan: DatabaseContentAdditionPlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseRevisionManifestV2 | None:
        if not isinstance(plan, DatabaseContentAdditionPlan):
            raise TypeError("plan must be a DatabaseContentAdditionPlan")
        if (
            self.creation_store.load_database_head(
                plan.database_id
            ).revision_id
            != plan.starting_revision_id
        ):
            raise DataManagerCreationError("Database head changed after Preview")
        if self._artifacts.capture_accepted_source(plan.market_id) != plan.source_ohlcv:
            raise DataManagerCreationError(
                "Database update required before adding content."
            )
        if plan.source_kind == "artifacts":
            current = self.plan_database_artifact_addition(
                plan.database_id, plan.selected_root_logical_artifact_ids
            )
        else:
            if plan.source_collection is None:
                raise DataManagerCreationError(
                    "Collection Database content plan has no Collection reference"
                )
            current = self.plan_database_collection_addition(
                plan.database_id, plan.source_collection.collection_id
            )
        if current != plan:
            raise DataManagerCreationError(
                "Database content plan changed after Preview"
            )
        result = self._creation.execute_database_content_addition(
            plan,
            cancellation_requested=cancellation_requested,
            before_publish=before_publish,
        )
        if result is not None:
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
    ) -> tuple[DatabaseRevisionManifest, ...]:
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

    def delete_portable_recipe(self, recipe_id: str) -> PortableRecipeV1:
        return self._delete_portable_recipe(recipe_id, before_delete=None)

    def _delete_portable_recipe(
        self,
        recipe_id: str,
        *,
        before_delete: Callable[[], None] | None,
        canonical_winner_id: str | None = None,
    ) -> PortableRecipeV1:
        deleted = self._portable_recipes.delete_recipe(
            recipe_id,
            before_delete=before_delete,
            canonical_winner_id=canonical_winner_id,
        )
        self._updates.invalidate()
        return deleted

    def delete_recipe_collection(
        self, collection_id: str
    ) -> PortableRecipeCollectionRevisionV1:
        return self._delete_recipe_collection(collection_id, before_delete=None)

    def _delete_recipe_collection(
        self,
        collection_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> PortableRecipeCollectionRevisionV1:
        deleted = self._portable_recipes.delete_collection(
            collection_id, before_delete=before_delete
        )
        self._updates.invalidate()
        return deleted

    def delete_managed_artifact(
        self, market_id: MarketId, logical_artifact_id: str
    ) -> ManagedArtifactSummary:
        return self._delete_managed_artifact(
            market_id, logical_artifact_id, before_delete=None
        )

    def _delete_managed_artifact(
        self,
        market_id: MarketId,
        logical_artifact_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> ManagedArtifactSummary:
        market = _canonical_market(market_id)
        try:
            for revision in self._artifact_collection_revisions_for_deletion_proof():
                if revision.market_id != market:
                    continue
                if any(
                    member.version_key.logical_artifact_id == logical_artifact_id
                    for member in revision.members
                ):
                    raise DataManagerOperationError(
                        "Artifact deletion refused: referenced by an Artifact Collection"
                    )
            for revision in self._database_revisions_for_deletion_proof():
                if any(
                    key.logical_artifact_id == logical_artifact_id
                    for key in revision.artifact_version_keys
                ):
                    raise DataManagerOperationError(
                        "Artifact deletion refused: referenced by a Database"
                    )
            deleted = self._artifacts.delete_managed_artifact(
                market,
                logical_artifact_id,
                before_delete=before_delete,
            )
            self._updates.invalidate()
            return deleted
        except DataManagerOperationError:
            raise
        except Exception as exc:
            raise self._deletion_proof_error("Artifact", exc) from exc

    def delete_artifact_collection(self, collection_id: str) -> ArtifactCollectionRevisionV1:
        return self._delete_artifact_collection(collection_id, before_delete=None)

    def _delete_artifact_collection(
        self,
        collection_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> ArtifactCollectionRevisionV1:
        try:
            deleted = self.creation_store.delete_collection(
                collection_id, before_delete=before_delete
            )
            self._updates.invalidate()
            return deleted
        except DataManagerOperationError:
            raise
        except Exception as exc:
            raise self._deletion_proof_error("Artifact Collection", exc) from exc

    def _artifact_collection_revisions_for_deletion_proof(
        self,
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        values: list[ArtifactCollectionRevisionV1] = []
        for collection_id in self.creation_store.list_collection_ids():
            head = self.creation_store.load_collection_head(collection_id)
            revisions = self.creation_store.list_collection_revisions(collection_id)
            if not revisions or head.revision_id not in {
                item.revision_id for item in revisions
            }:
                raise DataManagerOperationError(
                    "Deletion refused because Artifact Collection evidence is invalid"
                )
            values.extend(revisions)
        return tuple(values)

    def _database_revisions_for_deletion_proof(self) -> tuple[object, ...]:
        values: list[object] = []
        for database_id in self.creation_store.list_database_ids():
            self.creation_store.load_database_definition(database_id)
            head = self.creation_store.load_database_head(database_id)
            revisions = self.creation_store.list_database_revisions(database_id)
            if not revisions or head.revision_id not in {
                item.revision_id for item in revisions
            }:
                raise DataManagerOperationError(
                    "Deletion refused because Database evidence is invalid"
                )
            values.extend(revisions)
        return tuple(values)

    @staticmethod
    def _deletion_proof_error(object_name: str, error: Exception) -> DataManagerOperationError:
        return DataManagerOperationError(
            f"{object_name} deletion refused because Leonardo could not prove "
            f"the selected object was unreferenced: {error}"
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
            recipe_actions = self._recipe_persistence_actions(current.recipes)
            created_recipe_ids: list[str] = []
            reused_recipe_ids: list[str] = []
            for recipe in current.recipes:
                action = dict(recipe_actions)[recipe.recipe_id]
                if action == "NEW":
                    provenance = next(
                        item
                        for item in current.provenances
                        if item.recipe_id == recipe.recipe_id
                    )
                    self._portable_recipes.persist_recipe(
                        recipe,
                        origin_kind="study_environment",
                        origin_details={
                            "environment_id": provenance.study_environment_id,
                            "environment_content_hash": (
                                provenance.study_environment_content_hash
                            ),
                            "entry_id": provenance.study_entry_id,
                        },
                    )
                    created_recipe_ids.append(recipe.recipe_id)
                else:
                    reused_recipe_ids.append(recipe.recipe_id)
            existing_provenance = {
                item.provenance_id
                for recipe_id in (*root_recipe_ids, *support_recipe_ids)
                for item in self._portable_recipes.list_provenance(recipe_id)
            }
            new_provenance_ids: list[str] = []
            existing_provenance_ids: list[str] = []
            for provenance in current.provenances:
                if provenance.provenance_id in existing_provenance:
                    existing_provenance_ids.append(provenance.provenance_id)
                else:
                    self._portable_recipes.save_provenance(provenance)
                    new_provenance_ids.append(provenance.provenance_id)
            collection_id = None
            revision_id = None
            collection_outcome = "NONE"
            if collection_metadata is not None:
                display_name, description = collection_metadata
                existing_collection = self._portable_recipes.find_equivalent_collection(
                    root_recipe_ids, collection_members
                )
                revision = self._portable_recipes.create_collection(
                    display_name,
                    description,
                    root_recipe_ids,
                    collection_members,
                )
                collection_id = revision.collection_id
                revision_id = revision.revision_id
                collection_outcome = (
                    "REUSED_EXISTING"
                    if existing_collection is not None
                    and revision.collection_id == existing_collection.collection_id
                    else "CREATED"
                )
            result = DataManagerRecipePersistenceResult(
                environment_id,
                root_recipe_ids,
                support_recipe_ids,
                collection_id,
                revision_id,
                tuple(created_recipe_ids),
                tuple(reused_recipe_ids),
                tuple(new_provenance_ids),
                tuple(existing_provenance_ids),
                collection_outcome,
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
                    summary.recipe_id, "", "", "", {}, (), (), 0, 0,
                    (), (), (), 0,
                    False, summary.rejection_reason,
                )
            else:
                try:
                    recipe = self._portable_recipes.load_recipe(summary.recipe_id)
                    provenances = self._portable_recipes.list_provenance(recipe.recipe_id)
                    persistence = self._portable_recipes.load_persistence_metadata(
                        recipe.recipe_id
                    )
                except (FileNotFoundError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
                    item = DataManagerPortableRecipeEntry(
                        summary.recipe_id, summary.tool_key, summary.tool_version,
                        summary.kind, {}, summary.output_names,
                        (),
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
                    origin_kinds = {
                        item.origin_kind
                        for item in (() if persistence is None else persistence.origins)
                    }
                    if provenances:
                        origin_kinds.add("study_environment")
                    item = DataManagerPortableRecipeEntry(
                        recipe.recipe_id,
                        recipe.tool_key,
                        recipe.tool_version,
                        recipe.kind,
                        normalize_portable_recipe_parameters(
                            recipe.tool_key,
                            recipe.parameters,
                            ohlcv_inputs=recipe.ohlcv_inputs,
                            dependencies=recipe.dependencies,
                        ),
                        recipe.output_names,
                        tuple(
                            f"{value.role}=OHLCV.{value.column_name}"
                            for value in recipe.ohlcv_inputs
                        ) + tuple(
                            f"{value.role}=Recipe[{value.recipe_id}].{value.output_name}"
                            for value in recipe.dependencies
                        ),
                        len(recipe.dependencies),
                        len(recipe.ohlcv_inputs),
                        markets,
                        tuple(sorted({value.study_environment_id for value in provenances})),
                        tuple(sorted({value.study_display_name for value in provenances})),
                        (
                            len(provenances)
                            if persistence is None
                            else len(persistence.origins)
                        ),
                        first_persisted_at_utc=(
                            None
                            if persistence is None
                            else persistence.first_persisted_at_utc
                        ),
                        origin_kinds=tuple(sorted(origin_kinds)),
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
            plan = self.plan_recipe_collection(root_recipe_ids)
            if before_publish is not None:
                before_publish()
            revision = self._portable_recipes.create_collection(
                display_name,
                description,
                plan.root_recipe_ids,
                plan.member_recipe_ids,
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
        *,
        expected_revision_id: str | None = None,
    ) -> DataManagerRecipeCollectionInspection:
        return self._update_recipe_collection(
            collection_id,
            display_name,
            description,
            root_recipe_ids,
            before_publish=None,
            expected_revision_id=expected_revision_id,
        )

    def _update_recipe_collection(
        self,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: tuple[str, ...],
        *,
        before_publish: Callable[[], None] | None,
        expected_revision_id: str | None = None,
    ) -> DataManagerRecipeCollectionInspection:
        try:
            display_name, description = _validate_collection_metadata(
                display_name, description
            )
            plan = self.plan_recipe_collection(root_recipe_ids)
            if before_publish is not None:
                before_publish()
            revision = self._portable_recipes.update_collection(
                collection_id,
                display_name,
                description,
                plan.root_recipe_ids,
                plan.member_recipe_ids,
                expected_head_revision_id=expected_revision_id,
            )
            result = self.inspect_recipe_collection(revision.collection_id)
            self._updates.invalidate()
            return result
        except DataManagerOperationError:
            raise
        except (FileNotFoundError, PortableRecipeGraphError, PortableRecipeStoreError, PortableRecipeValidationError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def plan_recipe_collection(
        self, root_recipe_ids: tuple[str, ...]
    ) -> PortableRecipeGraphPlan:
        try:
            plan = self._recipe_planner.plan(root_recipe_ids)
            recipes_by_id = {
                recipe_id: self._portable_recipes.load_recipe(recipe_id)
                for recipe_id in plan.member_recipe_ids
            }
            for recipe_id in plan.member_recipe_ids:
                _validate_recipe_execution(recipes_by_id[recipe_id], recipes_by_id)
            return plan
        except DataManagerOperationError:
            raise
        except (
            FileNotFoundError,
            KeyError,
            TypeError,
            ValueError,
            ArtifactMaterializationValidationError,
            PortableRecipeGraphError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def find_equivalent_recipe_collection(
        self, root_recipe_ids: tuple[str, ...]
    ) -> PortableRecipeCollectionRevisionV1 | None:
        plan = self.plan_recipe_collection(root_recipe_ids)
        try:
            return self._portable_recipes.find_equivalent_collection(
                plan.root_recipe_ids, plan.member_recipe_ids
            )
        except (
            FileNotFoundError,
            PortableRecipeGraphError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def list_recipe_collections(self) -> DataManagerRecipeCollectionCatalog:
        values: list[DataManagerRecipeCollectionEntry] = []
        for summary in self._portable_recipes.list_collection_summaries():
            if not summary.valid:
                values.append(
                    DataManagerRecipeCollectionEntry(
                        summary.collection_id, summary.revision_id,
                        summary.display_name, summary.description,
                        summary.root_count, summary.member_count, (), 0, 0,
                        summary.created_at_utc, summary.updated_at_utc,
                        False, summary.rejection_reason,
                    )
                )
                continue
            try:
                revision = self._portable_recipes.load_collection(summary.collection_id)
                graph = self.plan_recipe_collection(revision.root_recipe_ids)
            except (
                DataManagerOperationError,
                FileNotFoundError,
                PortableRecipeGraphError,
                PortableRecipeStoreError,
                PortableRecipeValidationError,
            ) as exc:
                values.append(
                    DataManagerRecipeCollectionEntry(
                        summary.collection_id, summary.revision_id,
                        summary.display_name, summary.description,
                        summary.root_count, summary.member_count, (), 0, 0,
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
            graph = self.plan_recipe_collection(revision.root_recipe_ids)
            if revision.member_recipe_ids != graph.member_recipe_ids:
                raise DataManagerOperationError(
                    "Collection members must match the canonical graph planner result"
                )
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
                revision.member_recipe_ids,
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
        except DataManagerOperationError:
            raise
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
            requested_graph = self._recipe_planner.plan(roots)
            requested_recipes = {
                recipe_id: self._portable_recipes.load_recipe(recipe_id)
                for recipe_id in requested_graph.member_recipe_ids
            }
            requested_graph_is_valid = True
            for recipe_id in requested_graph.member_recipe_ids:
                try:
                    _validate_recipe_execution(
                        requested_recipes[recipe_id], requested_recipes
                    )
                    _target_configuration(requested_recipes[recipe_id])
                except (KeyError, TypeError, ValueError):
                    requested_graph_is_valid = False
                    break
            if requested_graph_is_valid:
                roots = tuple(
                    dict.fromkeys(
                        (
                            self._portable_recipes.find_equivalent_recipe(
                                requested_recipes[recipe_id]
                            )
                            or requested_recipes[recipe_id]
                        ).recipe_id
                        for recipe_id in roots
                    )
                )
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

            managed = {
                item.logical_artifact_id: item
                for item in self._artifacts.list_managed_artifacts(market)
            }
            artifact_winners = self._current_artifact_semantic_winners(
                market, source, tuple(managed.values())
            )
            recipe_semantic_keys = {
                recipe_id: self._portable_recipes.semantic_key_for_recipe(
                    recipes[recipe_id], recipes=recipes
                )
                for recipe_id in graph.member_recipe_ids
            }
            logical_by_recipe = {
                recipe_id: (
                    artifact_winners[recipe_semantic_keys[recipe_id]].logical_artifact_id
                    if recipe_semantic_keys[recipe_id] in artifact_winners
                    else compute_logical_artifact_id(market, recipe_id)
                )
                for recipe_id in graph.member_recipe_ids
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
                                if (
                                    self._artifact_semantic_key(
                                        market, current.artifact_id, source
                                    )
                                    == recipe_semantic_keys[recipe_id]
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

    def build_direct_artifact_catalog(
        self, market_id: MarketId
    ) -> DataManagerDirectArtifactCatalog:
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        market = canonicalize_market_id(
            market_id.exchange,
            market_id.market_type,
            market_id.symbol,
            market_id.timeframe,
        )
        try:
            self._require_accepted(market)
            source = self._artifacts.capture_accepted_source(market)
            grouped: dict[
                tuple[str, str],
                list[object],
            ] = {}
            for signal in list_construct_source_signals(self._artifacts, market):
                if signal.source_ohlcv != source:
                    continue
                grouped.setdefault(
                    (signal.logical_artifact_id, signal.artifact_id), []
                ).append(signal)
            kind_order = {"indicator": 0, "oscillator": 1, "construct": 2}
            option_values: list[DataManagerDirectArtifactOption] = []
            for (logical_id, artifact_id), signals in grouped.items():
                loaded = self._artifacts.load_artifact_by_id(market, artifact_id)
                option_values.append(
                    DataManagerDirectArtifactOption(
                        market_id=market,
                        logical_artifact_id=logical_id,
                        artifact_id=artifact_id,
                        tool_key=signals[0].tool_key,
                        kind=signals[0].kind,
                        display_name=_artifact_configuration_label(
                            loaded.metadata.recipe
                        ),
                        output_names=tuple(
                            signal.output_name for signal in signals
                        ),
                        source_ohlcv=source,
                    )
                )
            construct_options = tuple(
                sorted(
                    option_values,
                    key=lambda item: (
                        kind_order[item.kind],
                        item.tool_key,
                        item.logical_artifact_id,
                    ),
                )
            )
            peaks_options: list[DataManagerDirectArtifactOption] = []
            for summary in self._artifacts.list_managed_artifacts(market):
                if not summary.valid or summary.tool_key != "peaks_troughs":
                    continue
                loaded = self._artifacts.load_artifact_by_id(
                    market, summary.artifact_id
                )
                if loaded.metadata.source_ohlcv != source:
                    continue
                peaks_options.append(
                    DataManagerDirectArtifactOption(
                        market_id=market,
                        logical_artifact_id=summary.logical_artifact_id,
                        artifact_id=summary.artifact_id,
                        tool_key=summary.tool_key,
                        kind=summary.kind,
                        display_name=get_financial_tool_spec(
                            summary.tool_key
                        ).title,
                        output_names=loaded.metadata.recipe.output_names,
                        source_ohlcv=source,
                    )
                )
            return DataManagerDirectArtifactCatalog(
                market_id=market,
                source_ohlcv=source,
                construct_options=construct_options,
                utc_peaks_troughs_options=tuple(
                    sorted(
                        peaks_options,
                        key=lambda item: item.logical_artifact_id,
                    )
                ),
            )
        except DataManagerOperationError:
            raise
        except (
            ArtifactError,
            FileNotFoundError,
            KeyError,
            PortableRecipeStoreError,
            PortableRecipeValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def create_direct_artifact(
        self, request: DataManagerDirectArtifactRequest
    ) -> DataManagerDirectArtifactResult:
        return self._create_direct_artifact(
            request,
            progress=None,
            cancellation_requested=None,
            before_publish=None,
        )

    def _create_direct_artifact(
        self,
        request: DataManagerDirectArtifactRequest,
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
        before_publish: Callable[[], None] | None,
    ) -> DataManagerDirectArtifactResult:
        if not isinstance(request, DataManagerDirectArtifactRequest):
            raise TypeError("request must be a DataManagerDirectArtifactRequest")
        try:
            self._require_accepted(request.market_id)
            current_source = self._artifacts.capture_accepted_source(
                request.market_id
            )
            if current_source != request.expected_source_ohlcv:
                raise DataManagerOperationError(
                    "accepted OHLCV source changed after direct Artifact setup"
                )
            source_recipe_ids, _source_artifact_recipes = (
                self._validate_direct_artifact_sources(request, current_source)
            )

            spec = get_financial_tool_spec(request.tool_key)
            if spec.kind == "construct":
                eligible = {
                    (
                        signal.logical_artifact_id,
                        signal.artifact_id,
                        signal.output_name,
                    )
                    for signal in list_construct_source_signals(
                        self._artifacts, request.market_id
                    )
                    if signal.source_ohlcv == current_source
                }
                for source in request.sources:
                    identity = (
                        source.logical_artifact_id,
                        source.artifact_id,
                        source.output_name,
                    )
                    if identity not in eligible:
                        raise DataManagerOperationError(
                            "direct Construct source is not admitted by Task 1062"
                        )

            candidate = _build_direct_portable_recipe(
                request, source_recipe_ids
            )
            plan, members = self._plan_direct_artifact_materialization(
                request, candidate, current_source
            )
            recipe = self._resolve_portable_recipe_candidates((candidate,))[0]
            if recipe != candidate:
                plan, members = self._plan_direct_artifact_materialization(
                    request, recipe, current_source
                )
            _raise_materialization_cancelled(
                cancellation_requested or (lambda: False),
                "portable Recipe publication",
            )
            self._publish_portable_recipe_candidates((recipe,))
            materialization = self._execute_direct_artifact_materialization(
                plan,
                members,
                progress=progress,
                cancellation_requested=cancellation_requested,
                before_publish=before_publish,
            )
            return DataManagerDirectArtifactResult(
                portable_recipe_id=recipe.recipe_id,
                materialization=materialization,
            )
        except DataManagerOperationError:
            raise
        except (
            ArtifactError,
            FileNotFoundError,
            KeyError,
            PortableRecipeValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def _validate_direct_artifact_sources(
        self,
        request: DataManagerDirectArtifactRequest,
        expected_source: OHLCVSourceFingerprintV1,
    ) -> tuple[dict[str, str], dict[str, ArtifactRecipeV1]]:
        managed = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts(request.market_id)
        }
        semantic_ids: dict[str, str] = {}
        recipes: dict[str, ArtifactRecipeV1] = {}
        for source in request.sources:
            summary = managed.get(source.logical_artifact_id)
            if summary is None or not summary.valid:
                raise DataManagerOperationError(
                    "direct source is not a current valid managed Artifact: "
                    f"{source.logical_artifact_id}"
                )
            if summary.artifact_id != source.artifact_id:
                raise DataManagerOperationError(
                    f"direct source head changed: {source.logical_artifact_id}"
                )
            loaded = self._load_direct_managed_artifact(
                request.market_id, summary, expected_source
            )
            if source.output_name not in loaded.metadata.recipe.output_names:
                raise DataManagerOperationError(
                    f"direct source output is unavailable: {source.output_name}"
                )
            semantic_ids[source.role] = summary.portable_recipe_id
            recipes[source.role] = loaded.metadata.recipe
        return semantic_ids, recipes

    def _load_direct_managed_artifact(
        self,
        market: MarketId,
        summary: ManagedArtifactSummary,
        expected_source: OHLCVSourceFingerprintV1,
    ):
        if not summary.valid:
            raise ArtifactLineageError(summary.rejection_reason)
        loaded = self._artifacts.load_artifact_by_id(market, summary.artifact_id)
        recipe = loaded.metadata.recipe
        if (
            summary.market_id != market
            or loaded.metadata.artifact_id != summary.artifact_id
            or loaded.metadata.source_ohlcv != expected_source
            or recipe.market_id != market
            or recipe.tool_key != summary.tool_key
            or recipe.kind != summary.kind
            or recipe.output_names != summary.output_names
        ):
            raise ArtifactLineageError(
                "current managed Artifact metadata disagrees with its summary"
            )
        return loaded

    def _plan_direct_artifact_materialization(
        self,
        request: DataManagerDirectArtifactRequest,
        root_recipe: PortableRecipeV1,
        expected_source: OHLCVSourceFingerprintV1,
    ) -> tuple[
        DataManagerArtifactMaterializationPlan,
        dict[str, _DirectArtifactMember],
    ]:
        return self._plan_transient_artifact_materialization(
            request.market_id,
            expected_source,
            ((root_recipe, request.sources),),
        )

    def _plan_batch_artifact_materialization(
        self,
        request: BatchArtifactRequest,
        root_recipes: tuple[PortableRecipeV1, ...],
    ) -> tuple[
        DataManagerArtifactMaterializationPlan,
        dict[str, _DirectArtifactMember],
    ]:
        if len(root_recipes) != len(request.branches):
            raise DataManagerOperationError(
                "batch roots do not align with requested branches"
            )
        roots = tuple(
            (
                recipe,
                tuple(
                    DataManagerDirectArtifactSource(
                        source.role,
                        source.logical_artifact_id,
                        source.artifact_id,
                        source.output_name,
                    )
                    for source in branch.sources
                    if source.source_kind == "artifact"
                ),
            )
            for branch, recipe in zip(
                request.branches, root_recipes, strict=True
            )
        )
        return self._plan_transient_artifact_materialization(
            request.market_id,
            request.expected_source_ohlcv,
            roots,
        )

    def _plan_transient_artifact_materialization(
        self,
        market: MarketId,
        expected_source: OHLCVSourceFingerprintV1,
        roots: tuple[
            tuple[PortableRecipeV1, tuple[DataManagerDirectArtifactSource, ...]],
            ...,
        ],
    ) -> tuple[
        DataManagerArtifactMaterializationPlan,
        dict[str, _DirectArtifactMember],
    ]:
        managed = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts(market)
        }
        artifact_winners = self._current_artifact_semantic_winners(
            market, expected_source, tuple(managed.values())
        )
        version_owners: dict[str, tuple[str, str]] = {}
        versions_by_logical_id: dict[str, tuple[object, ...]] = {}
        for summary in managed.values():
            if not summary.valid:
                continue
            versions = self._artifacts.list_artifact_versions(
                market, summary.logical_artifact_id
            )
            if not versions:
                raise ArtifactLineageError(
                    "managed Artifact lineage has no versions"
                )
            versions_by_logical_id[summary.logical_artifact_id] = versions
            for version in versions:
                if (
                    version.logical_artifact_id != summary.logical_artifact_id
                    or version.portable_recipe_id != summary.portable_recipe_id
                    or version.market_id != market
                ):
                    raise ArtifactLineageError(
                        "managed Artifact version ownership is inconsistent"
                    )
                owner = (
                    version.logical_artifact_id,
                    version.portable_recipe_id,
                )
                previous_owner = version_owners.setdefault(
                    version.artifact_id, owner
                )
                if previous_owner != owner:
                    raise ArtifactLineageError(
                        "physical Artifact version has ambiguous managed ownership"
                    )

        members: dict[str, _DirectArtifactMember] = {}
        visiting: set[str] = set()

        def collect(logical_id: str) -> None:
            if logical_id in members:
                return
            if logical_id in visiting:
                raise ArtifactLineageError(
                    "managed Artifact dependency graph contains a cycle"
                )
            visiting.add(logical_id)
            summary = managed.get(logical_id)
            if summary is None or not summary.valid:
                raise ArtifactLineageError(
                    f"managed Artifact dependency is unavailable: {logical_id}"
                )
            self._validate_direct_artifact_semantic_lineage(
                market,
                summary,
                versions_by_logical_id[logical_id],
                version_owners,
            )
            loaded = self._load_direct_managed_artifact(
                market, summary, expected_source
            )
            dependencies: list[_DirectArtifactDependency] = []
            for ref in loaded.metadata.recipe.source_artifacts:
                owner = version_owners.get(ref.artifact_id)
                if owner is None:
                    raise ArtifactLineageError(
                        "Artifact source version has no managed owner"
                    )
                owner_logical_id, owner_semantic_id = owner
                exact_source = self._artifacts.load_artifact_by_id(
                    market, ref.artifact_id
                )
                if (
                    exact_source.metadata.source_ohlcv != expected_source
                    or exact_source.metadata.recipe.market_id != market
                    or ref.output_name
                    not in exact_source.metadata.recipe.output_names
                ):
                    raise ArtifactLineageError(
                        "Artifact source version metadata is inconsistent"
                    )
                owner_summary = managed.get(owner_logical_id)
                if (
                    owner_summary is None
                    or not owner_summary.valid
                    or owner_summary.portable_recipe_id != owner_semantic_id
                ):
                    raise ArtifactLineageError(
                        "Artifact source owner is not a current valid managed Artifact"
                    )
                collect(owner_logical_id)
                owner_member = members[owner_logical_id]
                if ref.output_name not in owner_member.output_names:
                    raise ArtifactLineageError(
                        "current Artifact source owner does not expose the required output"
                    )
                dependencies.append(
                    _DirectArtifactDependency(
                        ref.role,
                        owner_logical_id,
                        owner_semantic_id,
                        ref.output_name,
                    )
                )
            recipe = loaded.metadata.recipe
            member = _DirectArtifactMember(
                summary.portable_recipe_id,
                logical_id,
                recipe.tool_key,
                recipe.kind,
                recipe.parameters,
                recipe.bindings,
                recipe.output_names,
                tuple(dependencies),
            )
            self._validate_transient_member_compatibility(
                member,
                members,
                raw_inputs=(),
                allow_partial_roles=True,
            )
            members[logical_id] = member
            visiting.remove(logical_id)

        for _recipe, sources in roots:
            for source in sources:
                collect(source.logical_artifact_id)

        root_logical_ids: list[str] = []
        root_recipe_ids: list[str] = []
        for root_recipe, sources in roots:
            parameters, bindings = _target_configuration(root_recipe)
            root_semantic_key = self._direct_root_semantic_key(
                market, expected_source, root_recipe, sources
            )
            existing_root = artifact_winners.get(root_semantic_key)
            root_portable_recipe_id = (
                root_recipe.recipe_id
                if existing_root is None
                else existing_root.portable_recipe_id
            )
            root_logical_id = (
                compute_logical_artifact_id(market, root_recipe.recipe_id)
                if existing_root is None
                else existing_root.logical_artifact_id
            )
            root_dependencies = tuple(
                _DirectArtifactDependency(
                    source.role,
                    source.logical_artifact_id,
                    managed[source.logical_artifact_id].portable_recipe_id,
                    source.output_name,
                )
                for source in sources
            )
            root_summary = managed.get(root_logical_id)
            if root_summary is not None:
                if not root_summary.valid:
                    raise ArtifactLineageError(root_summary.rejection_reason)
                if root_summary.portable_recipe_id != root_portable_recipe_id:
                    raise ArtifactLineageError(
                        "managed Artifact semantic identity disagrees"
                    )
                root_versions = versions_by_logical_id.get(root_logical_id)
                if root_versions is None:
                    raise ArtifactLineageError(
                        "managed Artifact lineage has no versions"
                    )
                self._validate_direct_artifact_semantic_lineage(
                    market,
                    root_summary,
                    root_versions,
                    version_owners,
                )
                if (
                    self._artifact_semantic_key(
                        market,
                        root_summary.artifact_id,
                        expected_source,
                        require_source=False,
                    )
                    != root_semantic_key
                ):
                    raise ArtifactLineageError(
                        "managed Artifact semantic identity disagrees with "
                        "requested calculation"
                    )
            root_member = _DirectArtifactMember(
                root_portable_recipe_id,
                root_logical_id,
                root_recipe.tool_key,
                root_recipe.kind,
                parameters,
                bindings,
                root_recipe.output_names,
                root_dependencies,
            )
            self._validate_transient_member_compatibility(
                root_member,
                members,
                raw_inputs=tuple(root_recipe.ohlcv_inputs),
                allow_partial_roles=False,
            )
            previous_member = members.get(root_logical_id)
            if previous_member is not None and previous_member != root_member:
                raise ArtifactLineageError(
                    "transient Artifact roots disagree on semantic identity"
                )
            members[root_logical_id] = root_member
            if root_logical_id not in root_logical_ids:
                root_logical_ids.append(root_logical_id)
                root_recipe_ids.append(root_portable_recipe_id)

        order: list[str] = []
        active: set[str] = set()
        complete: set[str] = set()

        def order_member(logical_id: str) -> None:
            if logical_id in complete:
                return
            if logical_id in active:
                raise ArtifactLineageError(
                    "direct Artifact dependency graph contains a cycle"
                )
            active.add(logical_id)
            for dependency in members[logical_id].dependencies:
                order_member(dependency.logical_artifact_id)
            active.remove(logical_id)
            complete.add(logical_id)
            order.append(logical_id)

        for root_logical_id in root_logical_ids:
            order_member(root_logical_id)
        semantic_ids = tuple(members[item].portable_recipe_id for item in order)
        if len(set(semantic_ids)) != len(semantic_ids):
            raise ArtifactLineageError(
                "direct Artifact graph contains duplicate semantic identities"
            )
        edges = tuple(
            PortableRecipeGraphEdge(
                dependency.portable_recipe_id,
                member.portable_recipe_id,
                dependency.role,
                dependency.output_name,
            )
            for logical_id in order
            for member in (members[logical_id],)
            for dependency in member.dependencies
        )
        stages = tuple((members[item].portable_recipe_id,) for item in order)
        nodes: list[DataManagerArtifactMaterializationNode] = []
        node_by_logical_id: dict[str, DataManagerArtifactMaterializationNode] = {}
        for logical_id in order:
            member = members[logical_id]
            dependency_nodes = tuple(
                node_by_logical_id[item.logical_artifact_id]
                for item in member.dependencies
            )
            current = managed.get(logical_id)
            current_artifact_id: str | None = None
            previous_artifact_id: str | None = None
            status = "CREATE"
            if current is not None:
                if not current.valid:
                    raise ArtifactLineageError(current.rejection_reason)
                if current.portable_recipe_id != member.portable_recipe_id:
                    raise ArtifactLineageError(
                        "managed Artifact semantic identity disagrees"
                    )
                previous_artifact_id = current.artifact_id
                loaded = self._artifacts.load_artifact_by_id(
                    market, current.artifact_id
                )
                if (
                    loaded.metadata.source_ohlcv == expected_source
                    and all(
                        item.status == "REUSE_CURRENT"
                        for item in dependency_nodes
                    )
                ):
                    refs = tuple(
                        ArtifactSourceRefV1(
                            dependency.role,
                            node_by_logical_id[
                                dependency.logical_artifact_id
                            ].current_artifact_id,
                            dependency.output_name,
                        )
                        for dependency in member.dependencies
                    )
                    target = loaded.metadata.recipe
                    if (
                        target.tool_key == member.tool_key
                        and target.kind == member.kind
                        and dict(target.parameters) == dict(member.parameters)
                        and dict(target.bindings) == dict(member.bindings)
                        and target.output_names == member.output_names
                        and target.source_artifacts == refs
                    ):
                        status = "REUSE_CURRENT"
                        current_artifact_id = current.artifact_id
                        previous_artifact_id = current.previous_artifact_id
            node = DataManagerArtifactMaterializationNode(
                member.portable_recipe_id,
                logical_id,
                member.tool_key,
                member.kind,
                "ROOT" if logical_id in root_logical_ids else "SUPPORT",
                status,
                tuple(
                    dependency.logical_artifact_id
                    for dependency in member.dependencies
                ),
                current_artifact_id,
                previous_artifact_id,
            )
            nodes.append(node)
            node_by_logical_id[logical_id] = node
        plan_id = _plan_id(
            target_market_id=market,
            source_ohlcv=expected_source.to_dict(),
            root_recipe_ids=tuple(root_recipe_ids),
            member_recipe_ids=semantic_ids,
            source_recipe_collection_id=None,
            source_recipe_collection_revision_id=None,
            dependency_edges=edges,
            execution_stages=stages,
        )
        return (
            DataManagerArtifactMaterializationPlan(
                plan_id,
                market,
                expected_source,
                tuple(root_recipe_ids),
                semantic_ids,
                None,
                None,
                edges,
                stages,
                tuple(nodes),
            ),
            members,
        )

    @staticmethod
    def _validate_transient_member_compatibility(
        member: _DirectArtifactMember,
        members: Mapping[str, _DirectArtifactMember],
        *,
        raw_inputs: Sequence[PortableRecipeOHLCVInputV1],
        allow_partial_roles: bool,
    ) -> None:
        sources = [
            FinancialToolInputSource(
                item.role,
                "ohlc",
                item.column_name,
                False,
                None,
                None,
                True,
                "numeric",
            )
            for item in raw_inputs
        ]
        for dependency in member.dependencies:
            owner = members.get(dependency.logical_artifact_id)
            if owner is None:
                raise ArtifactLineageError(
                    "Artifact dependency owner is unavailable for compatibility proof"
                )
            naming = dict(owner.parameters)
            naming.update(owner.bindings)
            signal = next(
                (
                    item
                    for item in resolve_output_signals(owner.tool_key, naming)
                    if item.name == dependency.output_name
                ),
                None,
            )
            if signal is None:
                raise ArtifactLineageError(
                    f"Artifact dependency output is unavailable: {dependency.output_name}"
                )
            sources.append(
                FinancialToolInputSource(
                    dependency.role,
                    owner.kind,
                    dependency.output_name,
                    True,
                    owner.tool_key,
                    owner.logical_artifact_id,
                    signal.analysis_usable,
                    signal.value_type,
                )
            )
        try:
            validate_financial_tool_inputs(
                get_financial_tool_spec(member.tool_key),
                sources,
                parameters=member.parameters,
                allow_partial_roles=allow_partial_roles,
                family_scope="dependencies",
            )
        except FinancialToolInputCompatibilityError as exc:
            raise ArtifactLineageError(str(exc)) from exc

    def _validate_direct_artifact_semantic_lineage(
        self,
        market: MarketId,
        summary: ManagedArtifactSummary,
        versions: tuple[object, ...],
        version_owners: Mapping[str, tuple[str, str]],
    ) -> _DirectArtifactSemanticDescriptor:
        expected_descriptor: _DirectArtifactSemanticDescriptor | None = None
        for version in versions:
            loaded = self._artifacts.load_artifact_by_id(
                market, version.artifact_id
            )
            recipe = loaded.metadata.recipe
            if (
                loaded.metadata.artifact_id != version.artifact_id
                or recipe.market_id != market
            ):
                raise ArtifactLineageError(
                    "managed Artifact version metadata is inconsistent"
                )
            dependencies: list[_DirectArtifactSemanticDependency] = []
            for ref in recipe.source_artifacts:
                owner = version_owners.get(ref.artifact_id)
                if owner is None:
                    raise ArtifactLineageError(
                        "Artifact source version has no managed owner"
                    )
                dependencies.append(
                    _DirectArtifactSemanticDependency(
                        ref.role,
                        owner[1],
                        ref.output_name,
                    )
                )
            descriptor = _DirectArtifactSemanticDescriptor(
                recipe.tool_key,
                recipe.kind,
                recipe.parameters,
                recipe.bindings,
                recipe.output_names,
                tuple(dependencies),
            )
            if expected_descriptor is None:
                expected_descriptor = descriptor
            elif descriptor != expected_descriptor:
                raise ArtifactLineageError(
                    "managed Artifact lineage changes semantic calculation identity"
                )
        if expected_descriptor is None:
            raise ArtifactLineageError(
                "managed Artifact lineage has no versions"
            )
        return expected_descriptor

    def _execute_direct_artifact_materialization(
        self,
        plan: DataManagerArtifactMaterializationPlan,
        members: Mapping[str, _DirectArtifactMember],
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
        before_publish: Callable[[], None] | None,
    ) -> DataManagerArtifactMaterializationResult:
        cancelled = cancellation_requested or (lambda: False)
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
                "loaded dataset does not match the direct materialization source"
            )
        target_frame = _dataset_frame(dataset)
        node_by_recipe = {
            node.portable_recipe_id: node for node in plan.nodes
        }
        member_by_recipe = {
            member.portable_recipe_id: member for member in members.values()
        }
        current = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts(
                plan.target_market_id
            )
        }
        frames: dict[str, object] = {}
        metadata: dict[str, ArtifactMetadataV1] = {}
        artifact_ids: dict[str, str] = {}
        calculations: dict[str, object] = {}
        completed = 0
        total = len(plan.nodes)
        for stage in plan.execution_stages:
            for semantic_id in stage:
                _raise_materialization_cancelled(
                    cancelled, f"Artifact {semantic_id}"
                )
                node = node_by_recipe[semantic_id]
                member = member_by_recipe[semantic_id]
                expected_head = (
                    node.current_artifact_id
                    if node.status == "REUSE_CURRENT"
                    else node.previous_artifact_id
                )
                current_summary = current.get(node.logical_artifact_id)
                if expected_head is None:
                    if current_summary is not None:
                        raise DataManagerOperationError(
                            "direct Artifact head changed before execution"
                        )
                elif (
                    current_summary is None
                    or not current_summary.valid
                    or current_summary.artifact_id != expected_head
                ):
                    raise DataManagerOperationError(
                        "direct Artifact head changed before execution"
                    )
                if node.status == "REUSE_CURRENT":
                    loaded = self._artifacts.load_artifact_by_id(
                        plan.target_market_id, node.current_artifact_id
                    )
                    if loaded.metadata.source_ohlcv != plan.source_ohlcv:
                        raise DataManagerOperationError(
                            "reused direct Artifact source changed"
                        )
                    frames[node.logical_artifact_id] = loaded.frame
                    metadata[node.logical_artifact_id] = loaded.metadata
                    artifact_ids[node.logical_artifact_id] = node.current_artifact_id
                    message = f"Reusing managed Artifact {node.logical_artifact_id}"
                else:
                    dependencies = tuple(
                        (
                            ArtifactSourceRefV1(
                                dependency.role,
                                dependency.portable_recipe_id,
                                dependency.output_name,
                            ),
                            frames[dependency.logical_artifact_id],
                        )
                        for dependency in member.dependencies
                    )
                    if node.role == "ROOT":
                        calculation = _calculate_artifact_configuration(
                            tool_key=member.tool_key,
                            kind=member.kind,
                            parameters=member.parameters,
                            bindings=member.bindings,
                            output_names=member.output_names,
                            target_frame=target_frame,
                            dependencies=dependencies,
                        )
                    else:
                        source_recipe = self._artifacts.load_artifact_by_id(
                            plan.target_market_id, node.previous_artifact_id
                        ).metadata.recipe
                        calculation = _calculate_artifact_recipe(
                            source_recipe,
                            target_frame,
                            dependencies,
                        )
                    calculations[node.logical_artifact_id] = calculation
                    frames[node.logical_artifact_id] = calculation.to_frame()
                    message = (
                        f"Calculating {member.tool_key} {completed + 1}/{total}"
                    )
                completed += 1
                if progress is not None:
                    progress(completed, total, message)

        operation_time = datetime.now(UTC)
        prepared = []
        for semantic_id in plan.member_recipe_ids:
            node = node_by_recipe[semantic_id]
            if node.status == "REUSE_CURRENT":
                continue
            _raise_materialization_cancelled(cancelled, "candidate preparation")
            member = member_by_recipe[semantic_id]
            refs = tuple(
                ArtifactSourceRefV1(
                    dependency.role,
                    artifact_ids[dependency.logical_artifact_id],
                    dependency.output_name,
                )
                for dependency in member.dependencies
            )
            source_metadata = tuple(
                {
                    metadata[dependency.logical_artifact_id].artifact_id:
                    metadata[dependency.logical_artifact_id]
                    for dependency in member.dependencies
                }.values()
            )
            candidate = self._artifacts.prepare_managed_calculation(
                plan.target_market_id,
                member.portable_recipe_id,
                calculations[node.logical_artifact_id],
                expected_source=plan.source_ohlcv,
                source_artifacts=refs,
                source_metadata=source_metadata,
                previous_artifact_id=node.previous_artifact_id,
                created_at_utc=operation_time,
            )
            prepared.append(candidate)
            artifact_ids[node.logical_artifact_id] = candidate.metadata.artifact_id
            metadata[node.logical_artifact_id] = candidate.metadata

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
            created_keys = publication.created_version_keys
            publication_reused_keys = publication.reused_version_keys
            advanced_ids = publication.advanced_logical_artifact_ids
        else:
            if (
                self._artifacts.capture_accepted_source(plan.target_market_id)
                != plan.source_ohlcv
            ):
                raise DataManagerOperationError(
                    "accepted OHLCV source changed during direct reuse"
                )
            created_ids = ()
            publication_reused_ids = ()
            created_keys = ()
            publication_reused_keys = ()
            advanced_ids = ()

        created_id_set = set(created_ids)
        publication_reused_id_set = set(publication_reused_ids)
        created_key_set = set(created_keys)
        publication_reused_key_set = set(publication_reused_keys)
        projected_created_ids: list[str] = []
        projected_reused_ids: list[str] = []
        projected_created_keys: list[ManagedArtifactVersionKey] = []
        projected_reused_keys: list[ManagedArtifactVersionKey] = []
        seen_created_ids: set[str] = set()
        seen_reused_ids: set[str] = set()
        for node in plan.nodes:
            artifact_id = artifact_ids[node.logical_artifact_id]
            key = ManagedArtifactVersionKey(node.logical_artifact_id, artifact_id)
            if (
                artifact_id in created_id_set
                and artifact_id not in seen_created_ids
            ):
                projected_created_ids.append(artifact_id)
                seen_created_ids.add(artifact_id)
            elif (
                node.status == "REUSE_CURRENT"
                or artifact_id in publication_reused_id_set
            ) and artifact_id not in seen_reused_ids:
                projected_reused_ids.append(artifact_id)
                seen_reused_ids.add(artifact_id)
            if key in created_key_set:
                projected_created_keys.append(key)
            elif (
                node.status == "REUSE_CURRENT"
                or key in publication_reused_key_set
            ):
                projected_reused_keys.append(key)
        managed_after = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts(
                plan.target_market_id
            )
        }
        projected = tuple(
            _project_managed_artifact(managed_after[node.logical_artifact_id])
            for node in plan.nodes
        )
        result = DataManagerArtifactMaterializationResult(
            plan.plan_id,
            plan.target_market_id,
            plan.source_ohlcv,
            tuple(
                node.logical_artifact_id
                for node in plan.nodes
                if node.role == "ROOT"
            ),
            tuple(
                node.logical_artifact_id
                for node in plan.nodes
                if node.role == "SUPPORT"
            ),
            tuple(projected_created_ids),
            tuple(projected_reused_ids),
            tuple(projected_created_keys),
            tuple(projected_reused_keys),
            tuple(advanced_ids),
            projected,
        )
        self._updates.invalidate()
        return result

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
        reconciliation = self._updates.cached_snapshot()
        if reconciliation is None:
            raise DataManagerOperationError(
                "Product catalog scan requires a completed reconciliation snapshot"
            )
        currentness = {
            item.database_id: item for item in reconciliation.databases
        }
        databases: list[DataManagerDatabaseCatalogEntry] = []
        for database_id in self.list_database_ids():
            definition = self.load_database_definition(database_id)
            revisions = self.list_database_revisions(database_id)
            current_manifest = (
                None
                if not revisions
                else self.load_database_revision(database_id).manifest
            )
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

    def prepare_duplicate_maintenance(
        self,
        domain: DuplicateMaintenanceDomain | str,
        market_id: MarketId | None = None,
    ) -> DuplicateMaintenancePreflight:
        exact_domain = duplicate_maintenance_domain(domain)
        if not exact_domain.requires_market:
            if market_id is not None:
                raise ValueError("global duplicate maintenance does not use MarketId")
            count = (
                len(self._portable_recipes.list_recipe_summaries())
                if exact_domain.key == "recipes"
                else len(self._portable_recipes.list_collection_summaries())
            )
            return DuplicateMaintenancePreflight(exact_domain, count)

        if market_id is None:
            raise DataManagerOperationError(
                f"{exact_domain.display_name} duplicate maintenance requires "
                "a selected accepted dataset"
            )
        market = _canonical_market(market_id)
        self._require_accepted(market)
        source = self._capture_duplicate_maintenance_source(market)
        if exact_domain.key == "artifacts":
            count = len(self._current_artifact_candidates(market, source))
        else:
            count = len(self._current_artifact_collection_candidates(market, source))
        return DuplicateMaintenancePreflight(exact_domain, count, market, source)

    def scan_duplicate_maintenance(
        self,
        preflight: DuplicateMaintenancePreflight,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> DuplicateMaintenanceScanResult:
        if not isinstance(preflight, DuplicateMaintenancePreflight):
            raise TypeError("preflight must be a DuplicateMaintenancePreflight")
        if preflight.domain.requires_market:
            market = preflight.market_id
            source = preflight.source_ohlcv
            if market is None or source is None:
                raise DataManagerOperationError(
                    "selected-OHLCV duplicate maintenance scope is incomplete"
                )
            self._require_duplicate_maintenance_source(market, source)

        scanners = {
            "recipes": self._scan_recipe_duplicates,
            "recipe_collections": self._scan_recipe_collection_duplicates,
            "artifacts": self._scan_artifact_duplicates,
            "artifact_collections": self._scan_artifact_collection_duplicates,
        }
        groups, invalid, scanned, historical = scanners[preflight.domain.key](
            preflight,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )
        if preflight.domain.requires_market:
            self._require_duplicate_maintenance_source(
                preflight.market_id, preflight.source_ohlcv
            )
        return DuplicateMaintenanceScanResult(
            preflight,
            datetime.now(UTC),
            scanned,
            groups,
            invalid,
            historical,
        )

    def purge_duplicate_maintenance(
        self,
        scan: DuplicateMaintenanceScanResult,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_delete: Callable[[], None] | None = None,
    ) -> DuplicateMaintenancePurgeResult:
        if not isinstance(scan, DuplicateMaintenanceScanResult):
            raise TypeError("scan must be a DuplicateMaintenanceScanResult")
        requested = tuple(
            (group.canonical_id, candidate)
            for group in scan.groups
            for candidate in group.duplicates
            if candidate.classification == "SAFE"
        )
        details: list[DuplicateMaintenancePurgeDetail] = []
        abort_reason = ""
        total = len(requested)
        for index, (winner_id, candidate) in enumerate(requested, start=1):
            _duplicate_purge_progress(
                scan.preflight.domain,
                index,
                total,
                progress,
                cancellation_requested,
            )
            if abort_reason:
                details.append(
                    DuplicateMaintenancePurgeDetail(
                        scan.preflight.domain,
                        candidate.object_id,
                        winner_id,
                        "FAILED",
                        f"purge aborted after unsafe persistence state: {abort_reason}",
                    )
                )
                continue
            if candidate.object_id == winner_id:
                details.append(
                    DuplicateMaintenancePurgeDetail(
                        scan.preflight.domain,
                        candidate.object_id,
                        winner_id,
                        "FAILED",
                        "invalid purge candidate equals canonical winner",
                    )
                )
                continue

            try:
                current = self.scan_duplicate_maintenance(scan.preflight)
                current_group, current_candidate = self._current_duplicate_candidate(
                    current, candidate.object_id
                )
                if current_group is None or current_candidate is None:
                    details.append(
                        DuplicateMaintenancePurgeDetail(
                            scan.preflight.domain,
                            candidate.object_id,
                            winner_id,
                            "SKIPPED STALE",
                            "candidate no longer belongs to a duplicate group",
                        )
                    )
                    continue
                if current_group.canonical_id != winner_id:
                    details.append(
                        DuplicateMaintenancePurgeDetail(
                            scan.preflight.domain,
                            candidate.object_id,
                            winner_id,
                            "SKIPPED STALE",
                            "canonical duplicate winner changed after scan",
                        )
                    )
                    continue
                if current_candidate.classification == "BLOCKED":
                    details.append(
                        DuplicateMaintenancePurgeDetail(
                            scan.preflight.domain,
                            candidate.object_id,
                            winner_id,
                            "BLOCKED",
                            current_candidate.reason
                            + ": "
                            + ", ".join(current_candidate.blockers),
                        )
                    )
                    continue
                if current_candidate.classification != "SAFE":
                    details.append(
                        DuplicateMaintenancePurgeDetail(
                            scan.preflight.domain,
                            candidate.object_id,
                            winner_id,
                            "SKIPPED STALE",
                            "candidate is no longer classified SAFE",
                        )
                    )
                    continue

                self._delete_duplicate_candidate(
                    scan.preflight,
                    candidate.object_id,
                    winner_id,
                    before_delete=before_delete,
                )
                details.append(
                    DuplicateMaintenancePurgeDetail(
                        scan.preflight.domain,
                        candidate.object_id,
                        winner_id,
                        "PURGED",
                        "duplicate deleted after current canonical revalidation",
                    )
                )
            except Exception as exc:
                result, severe = self._duplicate_purge_failure(exc)
                reason = f"{type(exc).__name__}: {exc}"
                details.append(
                    DuplicateMaintenancePurgeDetail(
                        scan.preflight.domain,
                        candidate.object_id,
                        winner_id,
                        result,
                        reason,
                    )
                )
                if severe:
                    abort_reason = reason

        return DuplicateMaintenancePurgeResult(
            scan,
            datetime.now(UTC),
            tuple(details),
        )

    @staticmethod
    def _current_duplicate_candidate(
        scan: DuplicateMaintenanceScanResult,
        candidate_id: str,
    ) -> tuple[
        DuplicateMaintenanceGroup | None,
        DuplicateMaintenanceCandidate | None,
    ]:
        for group in scan.groups:
            for candidate in group.duplicates:
                if candidate.object_id == candidate_id:
                    return group, candidate
        return None, None

    def _delete_duplicate_candidate(
        self,
        preflight: DuplicateMaintenancePreflight,
        candidate_id: str,
        winner_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> None:
        key = preflight.domain.key
        if key == "recipes":
            self._delete_portable_recipe(
                candidate_id,
                before_delete=before_delete,
                canonical_winner_id=winner_id,
            )
            return
        if key == "recipe_collections":
            self._delete_recipe_collection(
                candidate_id, before_delete=before_delete
            )
            return
        if key == "artifacts":
            if preflight.market_id is None:
                raise DataManagerOperationError("Artifact purge scope is incomplete")
            self._delete_managed_artifact(
                preflight.market_id,
                candidate_id,
                before_delete=before_delete,
            )
            return
        if key == "artifact_collections":
            self._delete_artifact_collection(
                candidate_id, before_delete=before_delete
            )
            return
        raise DataManagerOperationError("duplicate purge domain is unsupported")

    @staticmethod
    def _duplicate_purge_failure(error: Exception) -> tuple[str, bool]:
        message = str(error).casefold()
        if "referenced" in message or "source changed" in message or "unavailable" in message:
            return "BLOCKED", False
        if isinstance(error, FileNotFoundError) or "not found" in message:
            return "SKIPPED STALE", False
        severe_markers = (
            "cannot prove",
            "corrupt",
            "escapes",
            "identity",
            "reparse",
            "shared by another lineage",
            "unexpected persistence",
            "unsafe persistence",
            "revisions do not match",
        )
        return "FAILED", any(marker in message for marker in severe_markers)

    def _scan_recipe_duplicates(
        self,
        preflight: DuplicateMaintenancePreflight,
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
    ) -> tuple[
        tuple[DuplicateMaintenanceGroup, ...],
        tuple[DuplicateMaintenanceCandidate, ...],
        int,
        int,
    ]:
        summaries = self._portable_recipes.list_recipe_summaries()
        grouped: dict[bytes, list[object]] = {}
        persistence_by_id: dict[str, object | None] = {}
        persistence_errors: dict[str, str] = {}
        invalid: list[DuplicateMaintenanceCandidate] = []
        total = len(summaries)
        for index, summary in enumerate(summaries, start=1):
            try:
                semantic = self._portable_recipes.inspect_recipe_semantics(
                    summary.recipe_id
                )
                grouped.setdefault(semantic.semantic_key, []).append(semantic)
                try:
                    persistence_by_id[summary.recipe_id] = (
                        self._portable_recipes.load_persistence_metadata(
                            summary.recipe_id
                        )
                    )
                except (PortableRecipeStoreError, PortableRecipeValidationError) as exc:
                    persistence_by_id[summary.recipe_id] = None
                    persistence_errors[summary.recipe_id] = (
                        f"{type(exc).__name__}: {exc}"
                    )
            except (
                FileNotFoundError,
                PortableRecipeStoreError,
                PortableRecipeValidationError,
            ) as exc:
                reason = summary.rejection_reason or f"{type(exc).__name__}: {exc}"
                invalid.append(
                    _invalid_duplicate_candidate(summary.recipe_id, reason)
                )
            _duplicate_scan_progress(
                preflight.domain,
                index,
                total,
                progress,
                cancellation_requested,
            )

        groups: list[DuplicateMaintenanceGroup] = []
        for values in grouped.values():
            if len(values) < 2:
                continue
            timestamped = tuple(
                (
                    persistence_by_id[item.persisted_recipe_id],
                    item,
                )
                for item in values
            )
            if all(
                metadata is not None
                and metadata.first_persisted_at_utc is not None
                for metadata, _item in timestamped
            ):
                winner = min(
                    timestamped,
                    key=lambda value: (
                        value[0].first_persisted_at_utc,
                        value[1].persisted_recipe_id,
                    ),
                )[1]
                canonical_id = winner.persisted_recipe_id
                duplicate_values = tuple(
                    sorted(
                        (
                            item
                            for item in values
                            if item.persisted_recipe_id
                            != winner.persisted_recipe_id
                        ),
                        key=lambda item: item.persisted_recipe_id,
                    )
                )
                duplicates = []
                for item in duplicate_values:
                    try:
                        blockers = self._portable_recipes.recipe_deletion_blockers(
                            item.persisted_recipe_id
                        )
                    except PortableRecipeStoreError as exc:
                        blockers = (f"Recipe reference proof unavailable: {exc}",)
                    duplicates.append(
                        DuplicateMaintenanceCandidate(
                            item.persisted_recipe_id,
                            "BLOCKED" if blockers else "SAFE",
                            (
                            "historical Recipe has dependency references"
                            if blockers
                            else "Recipe matches the canonical semantic winner"
                            ),
                            blockers,
                        )
                    )
            else:
                canonical_id = ""
                duplicates = [
                    DuplicateMaintenanceCandidate(
                        item.persisted_recipe_id,
                        "REVIEW REQUIRED",
                        persistence_errors.get(
                            item.persisted_recipe_id,
                            "Recipe persistence age is unknown",
                        ),
                    )
                    for item in sorted(
                        values, key=lambda item: item.persisted_recipe_id
                    )
                ]
            if not duplicates:
                continue
            recipe = min(
                values, key=lambda item: item.persisted_recipe_id
            ).canonical_recipe
            groups.append(
                DuplicateMaintenanceGroup(
                    preflight.domain,
                    canonical_id,
                    tuple(duplicates),
                    "Equivalent executable Recipe semantics",
                    recipe.tool_key,
                    json.dumps(
                        dict(recipe.parameters),
                        sort_keys=True,
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                )
            )
        return (
            tuple(sorted(groups, key=lambda item: item.canonical_id)),
            tuple(invalid),
            total,
            0,
        )

    def _scan_recipe_collection_duplicates(
        self,
        preflight: DuplicateMaintenancePreflight,
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
    ) -> tuple[
        tuple[DuplicateMaintenanceGroup, ...],
        tuple[DuplicateMaintenanceCandidate, ...],
        int,
        int,
    ]:
        summaries = self._portable_recipes.list_collection_summaries()
        grouped: dict[frozenset[bytes], list[tuple[datetime, str]]] = {}
        invalid: list[DuplicateMaintenanceCandidate] = []
        total = len(summaries)
        for index, summary in enumerate(summaries, start=1):
            if not summary.valid:
                invalid.append(
                    _invalid_duplicate_candidate(
                        summary.collection_id, summary.rejection_reason
                    )
                )
            else:
                try:
                    revision = self._portable_recipes.load_collection(
                        summary.collection_id
                    )
                    graph = self._recipe_planner.plan(revision.root_recipe_ids)
                    if revision.member_recipe_ids != graph.member_recipe_ids:
                        raise PortableRecipeStoreError(
                            "Collection members disagree with canonical graph"
                        )
                    semantic_key = self._portable_recipes._collection_semantic_key(
                        revision.root_recipe_ids, revision.member_recipe_ids
                    )
                    created = summary.created_at_utc or revision.created_at_utc
                    grouped.setdefault(semantic_key, []).append(
                        (created, revision.collection_id)
                    )
                except (
                    FileNotFoundError,
                    PortableRecipeGraphError,
                    PortableRecipeStoreError,
                    PortableRecipeValidationError,
                ) as exc:
                    invalid.append(
                        _invalid_duplicate_candidate(
                            summary.collection_id, f"{type(exc).__name__}: {exc}"
                        )
                    )
            _duplicate_scan_progress(
                preflight.domain,
                index,
                total,
                progress,
                cancellation_requested,
            )
        groups = tuple(
            DuplicateMaintenanceGroup(
                preflight.domain,
                ordered[0][1],
                tuple(
                    DuplicateMaintenanceCandidate(
                        collection_id,
                        "SAFE",
                        "same root and member Recipe sets as the canonical winner",
                    )
                    for _created, collection_id in ordered[1:]
                ),
                "Equivalent Recipe Collection root and member sets",
            )
            for values in grouped.values()
            if len(values) > 1
            for ordered in (sorted(values, key=lambda item: (item[0], item[1])),)
        )
        return _sorted_duplicate_groups(groups), tuple(invalid), total, 0

    def _scan_artifact_duplicates(
        self,
        preflight: DuplicateMaintenancePreflight,
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
    ) -> tuple[
        tuple[DuplicateMaintenanceGroup, ...],
        tuple[DuplicateMaintenanceCandidate, ...],
        int,
        int,
    ]:
        market = preflight.market_id
        source = preflight.source_ohlcv
        if market is None or source is None:
            raise DataManagerOperationError("Artifact scan scope is incomplete")
        candidates = self._current_artifact_candidates(market, source)
        grouped: dict[bytes, list[ManagedArtifactSummary]] = {}
        invalid: list[DuplicateMaintenanceCandidate] = []
        historical = 0
        total = len(candidates)
        for index, summary in enumerate(candidates, start=1):
            if not summary.valid:
                invalid.append(
                    _invalid_duplicate_candidate(
                        summary.logical_artifact_id, summary.rejection_reason
                    )
                )
            else:
                try:
                    loaded = self._artifacts.load_artifact_by_id(
                        market, summary.artifact_id
                    )
                    metadata = loaded.metadata
                    if (
                        metadata.artifact_id != summary.artifact_id
                        or metadata.recipe.market_id != market
                        or metadata.source_ohlcv != source
                    ):
                        raise ArtifactLineageError(
                            "current managed Artifact disagrees with selected source"
                        )
                    versions = self._artifacts.list_artifact_versions(
                        market, summary.logical_artifact_id
                    )
                    if not any(
                        item.artifact_id == summary.artifact_id for item in versions
                    ):
                        raise ArtifactLineageError(
                            "current managed Artifact is absent from its history"
                        )
                    historical += max(0, len(versions) - 1)
                    semantic_key = self._artifact_semantic_key(
                        market, summary.artifact_id, source
                    )
                    grouped.setdefault(semantic_key, []).append(summary)
                except (
                    ArtifactError,
                    AttributeError,
                    FileNotFoundError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    invalid.append(
                        _invalid_duplicate_candidate(
                            summary.logical_artifact_id,
                            f"{type(exc).__name__}: {exc}",
                        )
                    )
            _duplicate_scan_progress(
                preflight.domain,
                index,
                total,
                progress,
                cancellation_requested,
            )

        groups: list[DuplicateMaintenanceGroup] = []
        for values in grouped.values():
            by_logical_id = {
                item.logical_artifact_id: item for item in values
            }
            if len(by_logical_id) < 2:
                continue
            canonical = tuple(
                item
                for item in by_logical_id.values()
                if item.logical_artifact_id
                == compute_logical_artifact_id(market, item.portable_recipe_id)
            )
            winner = (
                min(
                    canonical,
                    key=lambda item: (
                        item.created_at_utc or datetime.max.replace(tzinfo=UTC),
                        item.logical_artifact_id,
                    ),
                )
                if canonical
                else None
            )
            canonical_id = "" if winner is None else winner.logical_artifact_id
            duplicates = tuple(
                DuplicateMaintenanceCandidate(
                    item.logical_artifact_id,
                    "REVIEW REQUIRED",
                    "legacy Artifact lineage shares portable Recipe semantics",
                )
                for item in sorted(
                    by_logical_id.values(), key=lambda value: value.logical_artifact_id
                )
                if item.logical_artifact_id != canonical_id
            )
            groups.append(
                DuplicateMaintenanceGroup(
                    preflight.domain,
                    canonical_id,
                    duplicates,
                    "Different logical Artifact identities share one portable Recipe",
                )
            )
        return _sorted_duplicate_groups(groups), tuple(invalid), total, historical

    def _current_artifact_semantic_winners(
        self,
        market: MarketId,
        source: OHLCVSourceFingerprintV1,
        summaries: Sequence[ManagedArtifactSummary],
    ) -> dict[bytes, ManagedArtifactSummary]:
        grouped: dict[bytes, list[ManagedArtifactSummary]] = {}
        cache: dict[str, bytes] = {}
        for summary in summaries:
            if not summary.valid:
                continue
            try:
                key = self._artifact_semantic_key(
                    market, summary.artifact_id, source, cache
                )
            except (ArtifactError, AttributeError, FileNotFoundError, TypeError, ValueError):
                continue
            grouped.setdefault(key, []).append(summary)
        return {
            key: min(
                values,
                key=lambda item: (
                    item.logical_artifact_id
                    != compute_logical_artifact_id(market, item.portable_recipe_id),
                    item.created_at_utc or datetime.max.replace(tzinfo=UTC),
                    item.logical_artifact_id,
                ),
            )
            for key, values in grouped.items()
        }

    def _direct_root_semantic_key(
        self,
        market: MarketId,
        source: OHLCVSourceFingerprintV1,
        recipe: PortableRecipeV1,
        artifact_sources: Sequence[DataManagerDirectArtifactSource],
    ) -> bytes:
        inputs: list[dict[str, object]] = [
            {
                "role": item.role,
                "source": "ohlcv",
                "column_name": item.column_name,
            }
            for item in recipe.ohlcv_inputs
        ]
        inputs.extend(
            {
                "role": item.role,
                "source": "object",
                "object_semantic_key": self._artifact_semantic_key(
                    market, item.artifact_id, source
                ).hex(),
                "output_name": item.output_name,
            }
            for item in artifact_sources
        )
        if not inputs:
            inputs.extend(
                {
                    "role": item.name,
                    "source": "ohlcv",
                    "column_name": item.name,
                }
                for item in get_financial_tool_spec(recipe.tool_key).data_inputs
            )
        return object_semantic_key(
            recipe.tool_key,
            object_semantic_parameters(
                recipe.tool_key,
                recipe.parameters,
                has_object_inputs=bool(artifact_sources),
            ),
            tuple(sorted(inputs, key=lambda item: str(item["role"]))),
        )

    def _artifact_semantic_key(
        self,
        market: MarketId,
        artifact_id: str,
        source: OHLCVSourceFingerprintV1,
        cache: dict[str, bytes] | None = None,
        active: set[str] | None = None,
        *,
        require_source: bool = True,
    ) -> bytes:
        keys = {} if cache is None else cache
        visiting = set() if active is None else active
        current = keys.get(artifact_id)
        if current is not None:
            return current
        if artifact_id in visiting:
            raise ArtifactLineageError(
                "Artifact semantic dependency graph contains a cycle"
            )
        visiting.add(artifact_id)
        loaded = self._artifacts.load_artifact_by_id(market, artifact_id)
        metadata = loaded.metadata
        recipe = metadata.recipe
        if (
            metadata.artifact_id != artifact_id
            or (require_source and metadata.source_ohlcv != source)
            or recipe.market_id != market
        ):
            raise ArtifactLineageError(
                "Artifact semantic input disagrees with selected dataframe"
            )
        reference_roles = {item.role for item in recipe.source_artifacts}
        inputs: list[dict[str, object]] = []
        for role, value in recipe.bindings.items():
            if role in reference_roles:
                continue
            column = value
            if isinstance(column, str) and column.startswith("OHLCV."):
                column = column.removeprefix("OHLCV.")
            inputs.append(
                {
                    "role": role,
                    "source": "ohlcv",
                    "column_name": column,
                }
            )
        for reference in recipe.source_artifacts:
            inputs.append(
                {
                    "role": reference.role,
                    "source": "object",
                    "object_semantic_key": self._artifact_semantic_key(
                        market,
                        reference.artifact_id,
                        source,
                        keys,
                        visiting,
                        require_source=require_source,
                    ).hex(),
                    "output_name": reference.output_name,
                }
            )
        if not inputs:
            inputs.extend(
                {
                    "role": item.name,
                    "source": "ohlcv",
                    "column_name": item.name,
                }
                for item in get_financial_tool_spec(recipe.tool_key).data_inputs
            )
        semantic_key = object_semantic_key(
            recipe.tool_key,
            object_semantic_parameters(
                recipe.tool_key,
                recipe.parameters,
                has_object_inputs=bool(recipe.source_artifacts),
            ),
            tuple(sorted(inputs, key=lambda item: str(item["role"]))),
        )
        visiting.remove(artifact_id)
        keys[artifact_id] = semantic_key
        return semantic_key

    def _scan_artifact_collection_duplicates(
        self,
        preflight: DuplicateMaintenancePreflight,
        *,
        progress: Callable[[int, int, str], None] | None,
        cancellation_requested: Callable[[], bool] | None,
    ) -> tuple[
        tuple[DuplicateMaintenanceGroup, ...],
        tuple[DuplicateMaintenanceCandidate, ...],
        int,
        int,
    ]:
        market = preflight.market_id
        source = preflight.source_ohlcv
        if market is None or source is None:
            raise DataManagerOperationError(
                "Artifact Collection scan scope is incomplete"
            )
        candidates = self._current_artifact_collection_candidates(market, source)
        grouped: dict[tuple[object, ...], list[ArtifactCollectionRevisionV1]] = {}
        invalid: list[DuplicateMaintenanceCandidate] = []
        total = len(candidates)
        for index, revision in enumerate(candidates, start=1):
            if revision.validation_state != "valid":
                invalid.append(
                    _invalid_duplicate_candidate(
                        revision.collection_id,
                        f"current validation state is {revision.validation_state}",
                    )
                )
            else:
                try:
                    semantic_key = self._artifact_collection_semantic_key_parts(
                        revision.market_id,
                        revision.source_ohlcv,
                        revision.members,
                    )
                    grouped.setdefault(semantic_key, []).append(revision)
                except (
                    ArtifactError,
                    AttributeError,
                    FileNotFoundError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    invalid.append(
                        _invalid_duplicate_candidate(
                            revision.collection_id,
                            f"{type(exc).__name__}: {exc}",
                        )
                    )
            _duplicate_scan_progress(
                preflight.domain,
                index,
                total,
                progress,
                cancellation_requested,
            )

        database_error = ""
        try:
            database_revisions = self._database_revisions_for_deletion_proof()
        except (DataManagerOperationError, OSError, RuntimeError, TypeError, ValueError) as exc:
            database_revisions = ()
            database_error = f"Database reference evidence is invalid: {exc}"
        groups: list[DuplicateMaintenanceGroup] = []
        for values in grouped.values():
            if len(values) < 2:
                continue
            ordered = sorted(
                values, key=lambda item: (item.created_at_utc, item.collection_id)
            )
            duplicates: list[DuplicateMaintenanceCandidate] = []
            for revision in ordered[1:]:
                blockers = tuple(
                    dict.fromkeys(
                        (
                            (database_error,) if database_error else ()
                        )
                        + tuple(
                            f"Database {item.database_id} revision {item.revision_id}"
                            for item in database_revisions
                            if revision.collection_id
                            in _database_collection_ids_for_deletion_proof(item)
                        )
                    )
                )
                duplicates.append(
                    DuplicateMaintenanceCandidate(
                        revision.collection_id,
                        "BLOCKED" if blockers else "SAFE",
                        "same canonical Artifact Collection semantic key",
                        blockers,
                    )
                )
            groups.append(
                DuplicateMaintenanceGroup(
                    preflight.domain,
                    ordered[0].collection_id,
                    tuple(duplicates),
                    "Equivalent current Artifact Collection semantics",
                )
            )
        return _sorted_duplicate_groups(groups), tuple(invalid), total, 0

    def _artifact_collection_semantic_key_parts(
        self,
        market_id: object,
        source_ohlcv: object,
        members: Sequence[ArtifactCollectionMemberV1],
    ) -> tuple[object, ...]:
        if not isinstance(market_id, MarketId):
            raise TypeError("Artifact Collection market_id must be a MarketId")
        if not isinstance(source_ohlcv, OHLCVSourceFingerprintV1):
            raise TypeError(
                "Artifact Collection source_ohlcv must be an OHLCVSourceFingerprintV1"
            )
        cache: dict[str, bytes] = {}
        return (
            source_ohlcv,
            frozenset(
                self._artifact_semantic_key(
                    market_id,
                    item.version_key.artifact_id,
                    source_ohlcv,
                    cache,
                    require_source=False,
                )
                for item in members
            ),
        )

    def _capture_duplicate_maintenance_source(
        self, market: MarketId
    ) -> OHLCVSourceFingerprintV1:
        try:
            return self._artifacts.capture_accepted_source(market)
        except (ArtifactError, FileNotFoundError, OSError, RuntimeError) as exc:
            raise DataManagerOperationError(str(exc)) from exc

    def _require_duplicate_maintenance_source(
        self,
        market: MarketId | None,
        expected: OHLCVSourceFingerprintV1 | None,
    ) -> None:
        if market is None or expected is None:
            raise DataManagerOperationError(
                "selected-OHLCV duplicate maintenance scope is incomplete"
            )
        self._require_accepted(market)
        if self._capture_duplicate_maintenance_source(market) != expected:
            raise DataManagerOperationError(
                "accepted OHLCV source changed during duplicate maintenance"
            )

    def _current_artifact_candidates(
        self,
        market: MarketId,
        source: OHLCVSourceFingerprintV1,
    ) -> tuple[ManagedArtifactSummary, ...]:
        values: list[ManagedArtifactSummary] = []
        for summary in self._artifacts.list_managed_artifacts(market):
            if not summary.valid:
                values.append(summary)
                continue
            try:
                loaded = self._artifacts.load_artifact_by_id(
                    market, summary.artifact_id
                )
            except (ArtifactError, FileNotFoundError):
                values.append(summary)
                continue
            if loaded.metadata.source_ohlcv == source:
                values.append(summary)
        return tuple(values)

    def _current_artifact_collection_candidates(
        self,
        market: MarketId,
        source: OHLCVSourceFingerprintV1,
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        values: list[ArtifactCollectionRevisionV1] = []
        for collection_id in self.creation_store.list_collection_ids():
            try:
                revision = self.creation_store.load_collection(collection_id)
            except (FileNotFoundError, OSError, RuntimeError, ValueError):
                continue
            if revision.market_id == market and revision.source_ohlcv == source:
                values.append(revision)
        return tuple(values)

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
            head = self._artifacts.load_artifact_head(
                market, logical_artifact_id
            )
            if (
                head.logical_artifact_id != logical_artifact_id
                or head.artifact_id != summary.artifact_id
            ):
                raise ArtifactLineageError(
                    "managed Artifact head disagrees with summary"
                )
            versions = self._artifacts.list_artifact_versions(
                market, logical_artifact_id
            )
            if any(
                item.logical_artifact_id != logical_artifact_id
                for item in versions
            ):
                raise ArtifactLineageError(
                    "managed history contains another logical Artifact"
                )
            if any(
                item.portable_recipe_id != summary.portable_recipe_id
                for item in versions
            ):
                raise ArtifactLineageError(
                    "managed history contains another portable Recipe"
                )
            if not any(
                item.artifact_id == summary.artifact_id for item in versions
            ):
                raise ArtifactLineageError(
                    "managed history does not contain the current Artifact"
                )
            loaded = self._artifacts.load_artifact_by_id(
                market, summary.artifact_id
            )
            metadata: ArtifactMetadataV1 = loaded.metadata
            recipe: ArtifactRecipeV1 = metadata.recipe
            if (
                metadata.artifact_id != summary.artifact_id
                or recipe.market_id != summary.market_id
                or recipe.market_id != market
                or recipe.tool_key != summary.tool_key
                or recipe.kind != summary.kind
                or recipe.output_names != summary.output_names
            ):
                raise ArtifactLineageError(
                    "current managed Artifact disagrees with summary"
                )
            return DataManagerManagedArtifactHistory(
                _project_managed_artifact(summary), versions
            )
        except (
            ArtifactError,
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
        candidate_recipes = tuple(
            analysis.recipes_by_entry[item] for item in ordered_entries
        )
        recipes, resolved_recipe_ids = self._resolve_recipe_candidates(
            candidate_recipes
        )
        classifications = tuple(
            replace(
                item,
                recipe_id=(
                    item.recipe_id
                    if item.recipe_id not in resolved_recipe_ids
                    else resolved_recipe_ids[item.recipe_id]
                ),
            )
            for item in analysis.classifications
        )
        provenances: tuple[PortableRecipeProvenanceV1, ...] = ()
        graph = PortableRecipeGraphPlan((), (), (), ())
        if not blockers:
            assert environment.created_from is not None
            provenances = tuple(
                PortableRecipeProvenanceV1.build(
                    recipe_id=resolved_recipe_ids[
                        analysis.recipes_by_entry[item.entry_id].recipe_id
                    ],
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
            root_recipe_ids = tuple(dict.fromkeys(
                resolved_recipe_ids[analysis.recipes_by_entry[item].recipe_id]
                for item in roots
            ))
            graph = self._recipe_planner.plan(root_recipe_ids, recipes=recipe_by_id)
        recipe_actions = self._recipe_persistence_actions(recipes)
        equivalent_collection = None
        if recipe_actions and all(
            action == "REUSE EXISTING" for _recipe_id, action in recipe_actions
        ):
            equivalent_collection = self._portable_recipes.find_equivalent_collection(
                graph.root_recipe_ids, graph.member_recipe_ids
            )
        return DataManagerRecipeDerivationPlan(
            environment.environment_id,
            environment.content_hash,
            roots,
            support,
            classifications,
            recipes,
            provenances,
            graph.dependency_edges,
            graph.execution_stages,
            (),
            tuple(blockers),
            recipe_actions,
            None if equivalent_collection is None else equivalent_collection.collection_id,
            None if equivalent_collection is None else equivalent_collection.revision_id,
            "" if equivalent_collection is None else equivalent_collection.display_name,
        )

    def _resolve_recipe_candidates(
        self, recipes: Sequence[PortableRecipeV1]
    ) -> tuple[tuple[PortableRecipeV1, ...], dict[str, str]]:
        candidates = {item.recipe_id: item for item in recipes}
        resolved: dict[str, PortableRecipeV1] = {}
        semantic_winners: dict[bytes, PortableRecipeV1] = {}
        active: set[str] = set()

        def resolve(recipe_id: str) -> PortableRecipeV1:
            current = resolved.get(recipe_id)
            if current is not None:
                return current
            if recipe_id in active:
                raise DataManagerOperationError(
                    "portable Recipe candidate graph contains a cycle"
                )
            active.add(recipe_id)
            candidate = candidates.get(recipe_id)
            if candidate is None:
                try:
                    candidate = self._portable_recipes.load_recipe(recipe_id)
                except FileNotFoundError as exc:
                    raise DataManagerOperationError(
                        f"portable Recipe dependency is unavailable: {recipe_id}"
                    ) from exc
                resolved[recipe_id] = candidate
                active.remove(recipe_id)
                return candidate
            dependencies = tuple(
                PortableRecipeDependencyV1(
                    item.role,
                    resolve(item.recipe_id).recipe_id,
                    item.output_name,
                )
                for item in candidate.dependencies
            )
            rebuilt = build_portable_recipe(
                tool_key=candidate.tool_key,
                tool_version=candidate.tool_version,
                kind=candidate.kind,
                parameters=candidate.parameters,
                output_names=candidate.output_names,
                ohlcv_inputs=candidate.ohlcv_inputs,
                dependencies=dependencies,
            )
            available = {
                item.recipe_id: item for item in (*resolved.values(), rebuilt)
            }
            semantic_key = self._portable_recipes.semantic_key_for_recipe(
                rebuilt, recipes=available
            )
            winner = semantic_winners.get(semantic_key)
            if winner is None:
                winner = self._portable_recipes.find_equivalent_recipe(
                    rebuilt, recipes=available
                )
            if winner is None:
                winner = rebuilt
            semantic_winners.setdefault(semantic_key, winner)
            resolved[recipe_id] = winner
            active.remove(recipe_id)
            return winner

        for recipe in recipes:
            resolve(recipe.recipe_id)
        ordered = tuple(
            dict.fromkeys(resolved[item.recipe_id].recipe_id for item in recipes)
        )
        by_id = {item.recipe_id: item for item in resolved.values()}
        return tuple(by_id[item] for item in ordered), {
            recipe_id: item.recipe_id for recipe_id, item in resolved.items()
        }

    def _resolve_portable_recipe_candidates(
        self, recipes: tuple[PortableRecipeV1, ...]
    ) -> tuple[PortableRecipeV1, ...]:
        return self._resolve_recipe_candidates(recipes)[0]

    def _publish_portable_recipe_candidates(
        self, recipes: tuple[PortableRecipeV1, ...]
    ) -> None:
        for recipe in recipes:
            try:
                existing = self._portable_recipes.load_recipe(recipe.recipe_id)
            except FileNotFoundError:
                self._portable_recipes.persist_recipe(
                    recipe,
                    origin_kind="data_manager_artifact",
                    origin_details={},
                )
                continue
            if existing != recipe:
                raise DataManagerOperationError(
                    f"portable Recipe identity collision: {recipe.recipe_id}"
                )
            self._portable_recipes.record_recipe_origin(
                recipe.recipe_id,
                origin_kind="data_manager_artifact",
                origin_details={},
            )

    def _recipe_persistence_actions(
        self, recipes: Sequence[PortableRecipeV1]
    ) -> tuple[tuple[str, str], ...]:
        actions: list[tuple[str, str]] = []
        for recipe in recipes:
            try:
                existing = self._portable_recipes.load_recipe(recipe.recipe_id)
            except FileNotFoundError:
                actions.append((recipe.recipe_id, "NEW"))
                continue
            if existing != recipe:
                raise DataManagerOperationError(
                    f"portable Recipe identity collision: {recipe.recipe_id}"
                )
            actions.append((recipe.recipe_id, "REUSE EXISTING"))
        return tuple(actions)


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
        graph.member_recipe_ids,
        len(graph.dependency_edges),
        len(graph.execution_stages),
        summary.created_at_utc,
        summary.updated_at_utc,
    )
