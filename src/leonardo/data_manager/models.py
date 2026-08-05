"""Immutable presentation models for the Data Manager workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Mapping

from leonardo.artifacts import (
    ArtifactVersionRecordV1,
    ManagedArtifactVersionKey,
    OHLCVSourceFingerprintV1,
)
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.recipes import (
    PortableRecipeGraphEdge,
    PortableRecipeProvenanceV1,
    PortableRecipeV1,
)
from .creation_models import (
    ArtifactCollectionRevisionV1,
    DatabaseDefinitionV1,
    DatabaseRevisionManifestV1,
    DatabaseSeedV1,
)


_CURRENT_STATUSES = frozenset({"unknown", "current", "stale", "invalid"})
_OBJECT_KINDS = frozenset({"dataset", "artifact"})
_DELETION_KINDS = frozenset({"artifact", "recipe"})
_PORTABILITY_STATUSES = frozenset(
    {"PORTABLE", "PORTABLE_WITH_DEPENDENCIES", "MARKET_BOUND", "UNSUPPORTED", "INVALID"}
)


class DataManagerOperationError(RuntimeError):
    """Raised when a Data Manager operation cannot use canonical persisted truth."""


@dataclass(frozen=True, slots=True)
class DataManagerDatasetEntry:
    market_id: MarketId | None
    accepted: bool
    row_count: int | None = None
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    source: str = ""
    persistence_status: str = ""
    validation_status: str = ""
    warnings: tuple[str, ...] = ()
    rejection_code: str = ""
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("accepted must be a boolean")
        if self.market_id is not None:
            _require_canonical_market(self.market_id)
        _text(self.source, "source")
        _text(self.persistence_status, "persistence_status")
        _text(self.validation_status, "validation_status")
        _text(self.rejection_code, "rejection_code")
        _text(self.rejection_reason, "rejection_reason")
        _optional_nonnegative_int(self.row_count, "row_count")
        _optional_nonnegative_int(self.first_timestamp_ms, "first_timestamp_ms")
        _optional_nonnegative_int(self.last_timestamp_ms, "last_timestamp_ms")
        object.__setattr__(self, "warnings", _text_tuple(self.warnings, "warnings"))
        if self.accepted:
            if self.market_id is None:
                raise ValueError("accepted datasets require market_id")
            if type(self.row_count) is not int or self.row_count <= 0:
                raise ValueError("accepted datasets require a positive row_count")
            _require_coverage(
                self.row_count,
                self.first_timestamp_ms,
                self.last_timestamp_ms,
            )
            if self.rejection_code or self.rejection_reason:
                raise ValueError("accepted datasets cannot contain rejection details")
        else:
            if not _text(self.rejection_code, "rejection_code"):
                raise ValueError("rejected datasets require rejection_code")
            if not _text(self.rejection_reason, "rejection_reason"):
                raise ValueError("rejected datasets require rejection_reason")


@dataclass(frozen=True, slots=True)
class DataManagerCatalogSnapshot:
    datasets: tuple[DataManagerDatasetEntry, ...]

    def __post_init__(self) -> None:
        datasets = tuple(self.datasets)
        if not all(isinstance(item, DataManagerDatasetEntry) for item in datasets):
            raise TypeError("datasets must contain DataManagerDatasetEntry values")
        object.__setattr__(self, "datasets", tuple(sorted(datasets, key=_dataset_key)))

    @property
    def accepted_count(self) -> int:
        return sum(item.accepted for item in self.datasets)

    @property
    def rejected_count(self) -> int:
        return len(self.datasets) - self.accepted_count

    def accepted_market(self, market_id: MarketId) -> DataManagerDatasetEntry | None:
        market = _require_canonical_market(market_id)
        return next(
            (
                item
                for item in self.datasets
                if item.accepted and item.market_id == market
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class DataManagerRecipeEntry:
    market_id: MarketId
    recipe_id: str
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    display_name: str
    created_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        _require_canonical_market(self.market_id)
        _text(self.recipe_id, "recipe_id", required=True)
        _text(self.tool_key, "tool_key", required=True)
        _text(self.kind, "kind", required=True)
        object.__setattr__(
            self, "output_names", _text_tuple(self.output_names, "output_names")
        )
        _text(self.display_name, "display_name")
        object.__setattr__(
            self,
            "created_at_utc",
            _aware_datetime(self.created_at_utc, "created_at_utc"),
        )
        _require_validity(self.valid, self.rejection_reason)


@dataclass(frozen=True, slots=True)
class DataManagerArtifactEntry:
    market_id: MarketId
    artifact_id: str
    recipe_id: str
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    created_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""
    current_status: str = "unknown"
    current_reason: str = ""

    def __post_init__(self) -> None:
        _require_canonical_market(self.market_id)
        _text(self.artifact_id, "artifact_id", required=True)
        _text(self.recipe_id, "recipe_id")
        _text(self.tool_key, "tool_key", required=True)
        _text(self.kind, "kind", required=True)
        object.__setattr__(
            self, "output_names", _text_tuple(self.output_names, "output_names")
        )
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("row_count must be a non-negative integer")
        if self.valid:
            _require_coverage(
                self.row_count,
                self.first_timestamp_ms,
                self.last_timestamp_ms,
            )
        elif (
            type(self.first_timestamp_ms) is not int
            or type(self.last_timestamp_ms) is not int
        ):
            raise TypeError("coverage timestamps must be integers")
        object.__setattr__(
            self,
            "created_at_utc",
            _aware_datetime(self.created_at_utc, "created_at_utc"),
        )
        _require_validity(self.valid, self.rejection_reason)
        _text(self.current_status, "current_status")
        if self.current_status not in _CURRENT_STATUSES:
            raise ValueError(f"invalid current_status: {self.current_status!r}")
        if not self.valid and self.current_status not in {"unknown", "invalid"}:
            raise ValueError("invalid artifacts cannot be current or stale")
        _text(self.current_reason, "current_reason")


@dataclass(frozen=True, slots=True)
class DataManagerMarketSnapshot:
    market_id: MarketId
    dataset: DataManagerDatasetEntry
    recipes: tuple[DataManagerRecipeEntry, ...]
    artifacts: tuple[DataManagerArtifactEntry, ...]

    def __post_init__(self) -> None:
        market = _require_canonical_market(self.market_id)
        if not isinstance(self.dataset, DataManagerDatasetEntry):
            raise TypeError("dataset must be a DataManagerDatasetEntry")
        if not self.dataset.accepted or self.dataset.market_id != market:
            raise ValueError("market snapshot requires its accepted dataset")
        recipes = tuple(self.recipes)
        artifacts = tuple(self.artifacts)
        if not all(
            isinstance(item, DataManagerRecipeEntry) and item.market_id == market
            for item in recipes
        ):
            raise ValueError("recipes must belong to market_id")
        if not all(
            isinstance(item, DataManagerArtifactEntry) and item.market_id == market
            for item in artifacts
        ):
            raise ValueError("artifacts must belong to market_id")
        object.__setattr__(
            self,
            "recipes",
            tuple(sorted(recipes, key=lambda item: (item.kind, item.tool_key, item.recipe_id))),
        )
        object.__setattr__(
            self,
            "artifacts",
            tuple(
                sorted(
                    artifacts,
                    key=lambda item: (item.kind, item.tool_key, item.artifact_id),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class DataManagerPreview:
    title: str
    market_id: MarketId
    object_kind: str
    object_id: str | None
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    total_rows: int
    truncated: bool
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        _text(self.title, "title", required=True)
        _require_canonical_market(self.market_id)
        _text(self.object_kind, "object_kind", required=True)
        if self.object_kind not in _OBJECT_KINDS:
            raise ValueError(f"invalid object_kind: {self.object_kind!r}")
        if self.object_kind == "dataset" and self.object_id is not None:
            raise ValueError("dataset previews cannot contain object_id")
        if self.object_kind == "artifact":
            _text(self.object_id, "object_id", required=True)
        elif self.object_id is not None:
            _text(self.object_id, "object_id")
        columns = _text_tuple(self.columns, "columns")
        if not columns:
            raise ValueError("columns cannot be empty")
        if not isinstance(self.rows, (tuple, list)):
            raise TypeError("rows must be a sequence of display rows")
        if any(not isinstance(row, (tuple, list)) for row in self.rows):
            raise TypeError("preview rows must be sequences of display strings")
        rows = tuple(tuple(row) for row in self.rows)
        if any(
            len(row) != len(columns)
            or any(not isinstance(value, str) for value in row)
            for row in rows
        ):
            raise ValueError("preview rows must contain one display string per column")
        if type(self.total_rows) is not int or self.total_rows < len(rows):
            raise ValueError("total_rows must include every projected row")
        if type(self.truncated) is not bool:
            raise TypeError("truncated must be a boolean")
        if self.truncated != (self.total_rows > len(rows)):
            raise ValueError("truncated must match projected row coverage")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a string mapping")
        metadata = dict(self.metadata)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
            raise TypeError("metadata must map strings to strings")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))


@dataclass(frozen=True, slots=True)
class DataManagerArtifactValidation:
    market_id: MarketId
    kind: str
    tool_key: str
    artifact_id: str
    status: str
    reason: str = ""

    def __post_init__(self) -> None:
        _require_canonical_market(self.market_id)
        _text(self.kind, "kind", required=True)
        _text(self.tool_key, "tool_key", required=True)
        _text(self.artifact_id, "artifact_id", required=True)
        _text(self.status, "status", required=True)
        if self.status not in {"current", "stale", "invalid"}:
            raise ValueError(f"invalid artifact validation status: {self.status!r}")
        _text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class DataManagerFocusRequest:
    market_id: MarketId
    source: str

    def __post_init__(self) -> None:
        _require_canonical_market(self.market_id)
        _text(self.source, "source", required=True)


@dataclass(frozen=True, slots=True)
class DataManagerDeletionResult:
    market_id: MarketId
    object_kind: str
    kind: str
    tool_key: str
    object_id: str

    def __post_init__(self) -> None:
        _require_canonical_market(self.market_id)
        _text(self.object_kind, "object_kind", required=True)
        if self.object_kind not in _DELETION_KINDS:
            raise ValueError(f"invalid deletion object_kind: {self.object_kind!r}")
        _text(self.kind, "kind", required=True)
        _text(self.tool_key, "tool_key", required=True)
        _text(self.object_id, "object_id", required=True)


@dataclass(frozen=True, slots=True)
class DataManagerStudyEntryPortability:
    entry_id: str
    display_name: str
    mode: str
    kind: str
    tool_key: str
    status: str
    reason: str = ""
    dependency_entry_ids: tuple[str, ...] = ()
    recipe_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.entry_id, "entry_id", required=True)
        _text(self.display_name, "display_name", required=True)
        _text(self.mode, "mode", required=True)
        _text(self.kind, "kind", required=True)
        _text(self.tool_key, "tool_key", required=True)
        if self.status not in _PORTABILITY_STATUSES:
            raise ValueError(f"invalid portability status: {self.status!r}")
        _text(self.reason, "reason")
        dependencies = _text_tuple(
            self.dependency_entry_ids, "dependency_entry_ids", allow_empty=True
        )
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("dependency_entry_ids must be unique")
        if self.recipe_id is not None:
            _sha(self.recipe_id, "recipe_id")
        if self.status in {"PORTABLE", "PORTABLE_WITH_DEPENDENCIES"}:
            if self.recipe_id is None:
                raise ValueError("portable entries require recipe_id")
        elif self.recipe_id is not None:
            raise ValueError("non-portable entries cannot contain recipe_id")
        object.__setattr__(self, "dependency_entry_ids", dependencies)


@dataclass(frozen=True, slots=True)
class DataManagerStudyEnvironmentEntry:
    environment_id: str
    display_name: str
    description: str
    origin_market_id: MarketId | None
    entry_count: int
    portable_count: int
    portable_with_dependencies_count: int
    market_bound_count: int
    unsupported_count: int
    invalid_count: int
    created_at_utc: datetime | None
    updated_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        _text(self.environment_id, "environment_id", required=True)
        _text(self.display_name, "display_name", required=True)
        _text(self.description, "description")
        if self.origin_market_id is not None:
            _require_canonical_market(self.origin_market_id)
        counts = (
            self.entry_count,
            self.portable_count,
            self.portable_with_dependencies_count,
            self.market_bound_count,
            self.unsupported_count,
            self.invalid_count,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("Study Environment counts must be non-negative integers")
        if sum(counts[1:]) != self.entry_count:
            raise ValueError("Study Environment classification counts must cover every entry")
        object.__setattr__(self, "created_at_utc", _aware_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _aware_datetime(self.updated_at_utc, "updated_at_utc"))
        _require_validity(self.valid, self.rejection_reason)


@dataclass(frozen=True, slots=True)
class DataManagerStudyEnvironmentCatalog:
    environments: tuple[DataManagerStudyEnvironmentEntry, ...]

    def __post_init__(self) -> None:
        values = tuple(self.environments)
        if not all(isinstance(item, DataManagerStudyEnvironmentEntry) for item in values):
            raise TypeError("environments must contain DataManagerStudyEnvironmentEntry values")
        object.__setattr__(
            self,
            "environments",
            tuple(sorted(values, key=lambda item: (item.display_name.casefold(), item.environment_id))),
        )


@dataclass(frozen=True, slots=True)
class DataManagerRecipeDerivationPlan:
    environment_id: str
    environment_content_hash: str
    root_entry_ids: tuple[str, ...]
    support_entry_ids: tuple[str, ...]
    entry_classifications: tuple[DataManagerStudyEntryPortability, ...]
    recipes: tuple[PortableRecipeV1, ...]
    provenances: tuple[PortableRecipeProvenanceV1, ...]
    dependency_edges: tuple[PortableRecipeGraphEdge, ...]
    execution_stages: tuple[tuple[str, ...], ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.environment_id, "environment_id", required=True)
        _sha(self.environment_content_hash, "environment_content_hash")
        roots = _text_tuple(self.root_entry_ids, "root_entry_ids", allow_empty=False)
        support = _text_tuple(self.support_entry_ids, "support_entry_ids", allow_empty=True)
        if len(set(roots)) != len(roots) or len(set(support)) != len(support):
            raise ValueError("derivation entry IDs must be unique")
        classifications = tuple(self.entry_classifications)
        recipes = tuple(self.recipes)
        provenances = tuple(self.provenances)
        edges = tuple(self.dependency_edges)
        stages = tuple(tuple(stage) for stage in self.execution_stages)
        if not all(isinstance(item, DataManagerStudyEntryPortability) for item in classifications):
            raise TypeError("entry_classifications contain invalid values")
        if not all(isinstance(item, PortableRecipeV1) for item in recipes):
            raise TypeError("recipes contain invalid values")
        if not all(isinstance(item, PortableRecipeProvenanceV1) for item in provenances):
            raise TypeError("provenances contain invalid values")
        if not all(isinstance(item, PortableRecipeGraphEdge) for item in edges):
            raise TypeError("dependency_edges contain invalid values")
        object.__setattr__(self, "root_entry_ids", roots)
        object.__setattr__(self, "support_entry_ids", support)
        object.__setattr__(self, "entry_classifications", classifications)
        object.__setattr__(self, "recipes", recipes)
        object.__setattr__(self, "provenances", provenances)
        object.__setattr__(self, "dependency_edges", edges)
        object.__setattr__(self, "execution_stages", stages)
        object.__setattr__(self, "warnings", _text_tuple(self.warnings, "warnings", allow_empty=True))
        object.__setattr__(self, "blockers", _text_tuple(self.blockers, "blockers", allow_empty=True))

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)


@dataclass(frozen=True, slots=True)
class DataManagerRecipePersistenceResult:
    environment_id: str
    root_recipe_ids: tuple[str, ...]
    support_recipe_ids: tuple[str, ...]
    collection_id: str | None = None
    revision_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.environment_id, "environment_id", required=True)
        roots = _text_tuple(self.root_recipe_ids, "root_recipe_ids", allow_empty=False)
        support = _text_tuple(self.support_recipe_ids, "support_recipe_ids", allow_empty=True)
        for value in (*roots, *support):
            _sha(value, "recipe_id")
        if (self.collection_id is None) != (self.revision_id is None):
            raise ValueError("Collection identity and revision must be supplied together")
        if self.collection_id is not None:
            _text(self.collection_id, "collection_id", required=True)
            _sha(self.revision_id, "revision_id")
        object.__setattr__(self, "root_recipe_ids", roots)
        object.__setattr__(self, "support_recipe_ids", support)


@dataclass(frozen=True, slots=True)
class DataManagerPortableRecipeEntry:
    recipe_id: str
    tool_key: str
    tool_version: str
    kind: str
    parameters: Mapping[str, object]
    output_names: tuple[str, ...]
    dependency_count: int
    ohlcv_input_count: int
    origin_market_ids: tuple[MarketId, ...]
    origin_study_environment_ids: tuple[str, ...]
    origin_study_display_names: tuple[str, ...]
    provenance_count: int
    valid: bool = True
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        _text(self.recipe_id, "recipe_id", required=True)
        if self.valid:
            _sha(self.recipe_id, "recipe_id")
        _text(self.tool_key, "tool_key")
        _text(self.tool_version, "tool_version")
        _text(self.kind, "kind")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a mapping")
        object.__setattr__(
            self,
            "parameters",
            _freeze_portable_parameter(self.parameters),
        )
        object.__setattr__(self, "output_names", _text_tuple(self.output_names, "output_names", allow_empty=True))
        if any(type(value) is not int or value < 0 for value in (self.dependency_count, self.ohlcv_input_count, self.provenance_count)):
            raise ValueError("portable Recipe counts must be non-negative integers")
        markets = tuple(self.origin_market_ids)
        if not all(isinstance(item, MarketId) for item in markets):
            raise TypeError("origin_market_ids must contain MarketId values")
        for market in markets:
            _require_canonical_market(market)
        object.__setattr__(self, "origin_market_ids", markets)
        object.__setattr__(self, "origin_study_environment_ids", _text_tuple(
            self.origin_study_environment_ids, "origin_study_environment_ids", allow_empty=True
        ))
        object.__setattr__(self, "origin_study_display_names", _text_tuple(
            self.origin_study_display_names, "origin_study_display_names", allow_empty=True
        ))
        _require_validity(self.valid, self.rejection_reason)


@dataclass(frozen=True, slots=True)
class DataManagerPortableRecipeCatalog:
    recipes: tuple[DataManagerPortableRecipeEntry, ...]

    def __post_init__(self) -> None:
        values = tuple(self.recipes)
        if not all(isinstance(item, DataManagerPortableRecipeEntry) for item in values):
            raise TypeError("recipes contain invalid Data Manager portable Recipe entries")
        object.__setattr__(
            self,
            "recipes",
            tuple(sorted(values, key=lambda item: (item.kind, item.tool_key, item.recipe_id))),
        )


@dataclass(frozen=True, slots=True)
class DataManagerStudyEnvironmentInspection:
    environment: DataManagerStudyEnvironmentEntry
    entries: tuple[DataManagerStudyEntryPortability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.environment, DataManagerStudyEnvironmentEntry):
            raise TypeError("environment must be a DataManagerStudyEnvironmentEntry")
        entries = tuple(self.entries)
        if not all(isinstance(item, DataManagerStudyEntryPortability) for item in entries):
            raise TypeError("entries must contain DataManagerStudyEntryPortability values")
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda item: (item.display_name.casefold(), item.entry_id))),
        )


@dataclass(frozen=True, slots=True)
class DataManagerPortableRecipeInspection:
    entry: DataManagerPortableRecipeEntry
    recipe: PortableRecipeV1
    provenance: tuple[PortableRecipeProvenanceV1, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entry, DataManagerPortableRecipeEntry):
            raise TypeError("entry must be a DataManagerPortableRecipeEntry")
        if not isinstance(self.recipe, PortableRecipeV1):
            raise TypeError("recipe must be a PortableRecipeV1")
        if self.entry.recipe_id != self.recipe.recipe_id:
            raise ValueError("entry and recipe identities must match")
        provenance = tuple(self.provenance)
        if not all(isinstance(item, PortableRecipeProvenanceV1) for item in provenance):
            raise TypeError("provenance must contain PortableRecipeProvenanceV1 values")
        if any(item.recipe_id != self.recipe.recipe_id for item in provenance):
            raise ValueError("provenance must belong to the inspected recipe")
        object.__setattr__(
            self,
            "provenance",
            tuple(sorted(provenance, key=lambda item: item.provenance_id)),
        )


@dataclass(frozen=True, slots=True)
class DataManagerRecipeCollectionEntry:
    collection_id: str
    revision_id: str
    display_name: str
    description: str
    root_count: int
    member_count: int
    dependency_edge_count: int
    execution_stage_count: int
    created_at_utc: datetime | None
    updated_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        _text(self.collection_id, "collection_id", required=True)
        _text(self.revision_id, "revision_id")
        _text(self.display_name, "display_name", required=True)
        _text(self.description, "description")
        counts = (
            self.root_count, self.member_count, self.dependency_edge_count,
            self.execution_stage_count,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("Recipe Collection counts must be non-negative integers")
        object.__setattr__(self, "created_at_utc", _aware_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _aware_datetime(self.updated_at_utc, "updated_at_utc"))
        _require_validity(self.valid, self.rejection_reason)


@dataclass(frozen=True, slots=True)
class DataManagerRecipeCollectionCatalog:
    collections: tuple[DataManagerRecipeCollectionEntry, ...]

    def __post_init__(self) -> None:
        values = tuple(self.collections)
        if not all(isinstance(item, DataManagerRecipeCollectionEntry) for item in values):
            raise TypeError("collections contain invalid values")
        object.__setattr__(
            self,
            "collections",
            tuple(sorted(values, key=lambda item: (item.display_name.casefold(), item.collection_id))),
        )


@dataclass(frozen=True, slots=True)
class DataManagerRecipeCollectionInspection:
    collection: DataManagerRecipeCollectionEntry
    root_recipe_ids: tuple[str, ...]
    member_recipe_ids: tuple[str, ...]
    dependency_edges: tuple[PortableRecipeGraphEdge, ...]
    execution_stages: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.collection, DataManagerRecipeCollectionEntry):
            raise TypeError("collection must be a DataManagerRecipeCollectionEntry")
        object.__setattr__(self, "root_recipe_ids", _text_tuple(
            self.root_recipe_ids, "root_recipe_ids", allow_empty=False
        ))
        object.__setattr__(self, "member_recipe_ids", _text_tuple(
            self.member_recipe_ids, "member_recipe_ids", allow_empty=False
        ))
        edges = tuple(self.dependency_edges)
        if not all(isinstance(item, PortableRecipeGraphEdge) for item in edges):
            raise TypeError("dependency_edges contain invalid values")
        object.__setattr__(self, "dependency_edges", edges)
        object.__setattr__(self, "execution_stages", tuple(tuple(stage) for stage in self.execution_stages))


@dataclass(frozen=True, slots=True)
class DataManagerArtifactMaterializationRequest:
    target_market_id: MarketId
    root_recipe_ids: tuple[str, ...] = ()
    recipe_collection_id: str | None = None
    recipe_collection_revision_id: str | None = None

    def __post_init__(self) -> None:
        _require_canonical_market(self.target_market_id)
        roots = _text_tuple(
            self.root_recipe_ids, "root_recipe_ids", allow_empty=True
        )
        if len(set(roots)) != len(roots):
            raise ValueError("root_recipe_ids must be unique")
        for recipe_id in roots:
            _sha(recipe_id, "root_recipe_id")
        direct = bool(roots) and self.recipe_collection_id is None and self.recipe_collection_revision_id is None
        collection = not roots and self.recipe_collection_id is not None
        if not direct and not collection:
            raise ValueError("exactly one materialization request mode is required")
        if collection:
            _text(self.recipe_collection_id, "recipe_collection_id", required=True)
            if self.recipe_collection_revision_id is not None:
                _sha(self.recipe_collection_revision_id, "recipe_collection_revision_id")
        object.__setattr__(self, "root_recipe_ids", roots)


@dataclass(frozen=True, slots=True)
class DataManagerArtifactMaterializationNode:
    portable_recipe_id: str
    logical_artifact_id: str
    tool_key: str
    kind: str
    role: str
    status: str
    dependency_logical_artifact_ids: tuple[str, ...]
    current_artifact_id: str | None
    previous_artifact_id: str | None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _sha(self.portable_recipe_id, "portable_recipe_id")
        _sha(self.logical_artifact_id, "logical_artifact_id")
        _text(self.tool_key, "tool_key", required=True)
        _text(self.kind, "kind", required=True)
        if self.role not in {"ROOT", "SUPPORT"}:
            raise ValueError("role must be ROOT or SUPPORT")
        if self.status not in {"REUSE_CURRENT", "CREATE", "BLOCKED"}:
            raise ValueError("invalid materialization node status")
        dependencies = _text_tuple(
            self.dependency_logical_artifact_ids,
            "dependency_logical_artifact_ids",
            allow_empty=True,
        )
        for logical_id in dependencies:
            _sha(logical_id, "dependency_logical_artifact_id")
        if self.current_artifact_id is not None:
            _sha(self.current_artifact_id, "current_artifact_id")
        if self.previous_artifact_id is not None:
            _sha(self.previous_artifact_id, "previous_artifact_id")
        blockers = _text_tuple(self.blockers, "blockers", allow_empty=True)
        if self.status == "REUSE_CURRENT":
            if self.current_artifact_id is None or blockers:
                raise ValueError("REUSE_CURRENT requires a current Artifact and no blockers")
        elif self.status == "CREATE":
            if self.current_artifact_id is not None or blockers:
                raise ValueError("CREATE requires no current Artifact and no blockers")
        elif not blockers:
            raise ValueError("BLOCKED requires blockers")
        object.__setattr__(self, "dependency_logical_artifact_ids", dependencies)
        object.__setattr__(self, "blockers", blockers)


@dataclass(frozen=True, slots=True)
class DataManagerArtifactMaterializationPlan:
    plan_id: str
    target_market_id: MarketId
    source_ohlcv: OHLCVSourceFingerprintV1
    root_recipe_ids: tuple[str, ...]
    member_recipe_ids: tuple[str, ...]
    source_recipe_collection_id: str | None
    source_recipe_collection_revision_id: str | None
    dependency_edges: tuple[PortableRecipeGraphEdge, ...]
    execution_stages: tuple[tuple[str, ...], ...]
    nodes: tuple[DataManagerArtifactMaterializationNode, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _sha(self.plan_id, "plan_id")
        market = _require_canonical_market(self.target_market_id)
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1):
            raise TypeError("source_ohlcv must be OHLCVSourceFingerprintV1")
        if self.source_ohlcv.market_id != market:
            raise ValueError("source_ohlcv MarketId must match target_market_id")
        roots = _text_tuple(self.root_recipe_ids, "root_recipe_ids", allow_empty=False)
        members = _text_tuple(self.member_recipe_ids, "member_recipe_ids", allow_empty=False)
        for recipe_id in (*roots, *members):
            _sha(recipe_id, "recipe_id")
        if not set(roots).issubset(members):
            raise ValueError("root_recipe_ids must be materialization members")
        if (self.source_recipe_collection_id is None) != (
            self.source_recipe_collection_revision_id is None
        ):
            raise ValueError("Collection identity and revision must be paired")
        if self.source_recipe_collection_id is not None:
            _text(
                self.source_recipe_collection_id,
                "source_recipe_collection_id",
                required=True,
            )
            _sha(
                self.source_recipe_collection_revision_id,
                "source_recipe_collection_revision_id",
            )
        edges = tuple(self.dependency_edges)
        nodes = tuple(self.nodes)
        stages = tuple(tuple(stage) for stage in self.execution_stages)
        if not all(isinstance(item, PortableRecipeGraphEdge) for item in edges):
            raise TypeError("dependency_edges contain invalid values")
        if not all(isinstance(item, DataManagerArtifactMaterializationNode) for item in nodes):
            raise TypeError("nodes contain invalid values")
        object.__setattr__(self, "root_recipe_ids", roots)
        object.__setattr__(self, "member_recipe_ids", members)
        object.__setattr__(self, "dependency_edges", edges)
        object.__setattr__(self, "execution_stages", stages)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "warnings", _text_tuple(self.warnings, "warnings", allow_empty=True))
        object.__setattr__(self, "blockers", _text_tuple(self.blockers, "blockers", allow_empty=True))

    @property
    def blocked(self) -> bool:
        return bool(self.blockers) or any(item.status == "BLOCKED" for item in self.nodes)


@dataclass(frozen=True, slots=True)
class DataManagerManagedArtifactEntry:
    logical_artifact_id: str
    portable_recipe_id: str
    market_id: MarketId
    artifact_id: str
    previous_artifact_id: str | None
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    created_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        _require_canonical_market(self.market_id)
        if self.valid:
            _sha(self.logical_artifact_id, "logical_artifact_id")
            _sha(self.portable_recipe_id, "portable_recipe_id")
            _sha(self.artifact_id, "artifact_id")
            if self.previous_artifact_id is not None:
                _sha(self.previous_artifact_id, "previous_artifact_id")
            _text(self.tool_key, "tool_key", required=True)
            _text(self.kind, "kind", required=True)
            _require_coverage(
                self.row_count, self.first_timestamp_ms, self.last_timestamp_ms
            )
        object.__setattr__(self, "output_names", _text_tuple(self.output_names, "output_names", allow_empty=not self.valid))
        object.__setattr__(self, "created_at_utc", _aware_datetime(self.created_at_utc, "created_at_utc"))
        _require_validity(self.valid, self.rejection_reason)


@dataclass(frozen=True, slots=True)
class DataManagerManagedArtifactHistory:
    current: DataManagerManagedArtifactEntry
    versions: tuple[ArtifactVersionRecordV1, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.current, DataManagerManagedArtifactEntry):
            raise TypeError("current must be DataManagerManagedArtifactEntry")
        versions = tuple(self.versions)
        if not all(isinstance(item, ArtifactVersionRecordV1) for item in versions):
            raise TypeError("versions must contain ArtifactVersionRecordV1 values")
        object.__setattr__(self, "versions", versions)


@dataclass(frozen=True, slots=True)
class DataManagerManagedArtifactCatalog:
    artifacts: tuple[DataManagerManagedArtifactEntry, ...]

    def __post_init__(self) -> None:
        artifacts = tuple(self.artifacts)
        if not all(isinstance(item, DataManagerManagedArtifactEntry) for item in artifacts):
            raise TypeError("artifacts must contain DataManagerManagedArtifactEntry values")
        object.__setattr__(
            self,
            "artifacts",
            tuple(
                sorted(
                    artifacts,
                    key=lambda item: (
                        item.market_id.exchange,
                        item.market_id.market_type,
                        item.market_id.symbol,
                        item.market_id.timeframe,
                        item.kind,
                        item.tool_key,
                        item.logical_artifact_id,
                    ),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class DataManagerDatabaseCatalogEntry:
    definition: DatabaseDefinitionV1
    current_manifest: DatabaseRevisionManifestV1 | None
    revision_count: int
    currentness: object | None
    valid: bool = True
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        from .update_models import DataManagerDatabaseCurrentness

        if not isinstance(self.definition, DatabaseDefinitionV1):
            raise TypeError("definition must be a DatabaseDefinitionV1")
        if self.current_manifest is not None:
            if not isinstance(self.current_manifest, DatabaseRevisionManifestV1):
                raise TypeError("current_manifest must be a DatabaseRevisionManifestV1")
            if self.current_manifest.database_id != self.definition.database_id:
                raise ValueError("current_manifest must belong to definition")
        if type(self.revision_count) is not int or self.revision_count < 0:
            raise ValueError("revision_count must be a non-negative integer")
        if self.currentness is not None:
            if not isinstance(self.currentness, DataManagerDatabaseCurrentness):
                raise TypeError("currentness must be a DataManagerDatabaseCurrentness")
            if self.currentness.database_id != self.definition.database_id:
                raise ValueError("currentness must belong to definition")
        _require_validity(self.valid, self.rejection_reason)


@dataclass(frozen=True, slots=True)
class DataManagerProductCatalogSnapshot:
    catalog: DataManagerCatalogSnapshot
    study_environments: DataManagerStudyEnvironmentCatalog
    portable_recipes: DataManagerPortableRecipeCatalog
    recipe_collections: DataManagerRecipeCollectionCatalog
    managed_artifacts: DataManagerManagedArtifactCatalog
    artifact_collections: tuple[ArtifactCollectionRevisionV1, ...]
    database_seeds: tuple[DatabaseSeedV1, ...]
    databases: tuple[DataManagerDatabaseCatalogEntry, ...]
    latest_reconciliation: object

    def __post_init__(self) -> None:
        from .update_models import DataManagerReconciliationSnapshot

        expected = (
            (self.catalog, DataManagerCatalogSnapshot, "catalog"),
            (
                self.study_environments,
                DataManagerStudyEnvironmentCatalog,
                "study_environments",
            ),
            (self.portable_recipes, DataManagerPortableRecipeCatalog, "portable_recipes"),
            (
                self.recipe_collections,
                DataManagerRecipeCollectionCatalog,
                "recipe_collections",
            ),
            (
                self.managed_artifacts,
                DataManagerManagedArtifactCatalog,
                "managed_artifacts",
            ),
            (
                self.latest_reconciliation,
                DataManagerReconciliationSnapshot,
                "latest_reconciliation",
            ),
        )
        for value, value_type, name in expected:
            if not isinstance(value, value_type):
                raise TypeError(f"{name} has an invalid type")
        collections = tuple(self.artifact_collections)
        seeds = tuple(self.database_seeds)
        databases = tuple(self.databases)
        if not all(isinstance(item, ArtifactCollectionRevisionV1) for item in collections):
            raise TypeError("artifact_collections contain invalid values")
        if not all(isinstance(item, DatabaseSeedV1) for item in seeds):
            raise TypeError("database_seeds contain invalid values")
        if not all(isinstance(item, DataManagerDatabaseCatalogEntry) for item in databases):
            raise TypeError("databases contain invalid values")
        object.__setattr__(
            self,
            "artifact_collections",
            tuple(sorted(collections, key=lambda item: (item.display_name.casefold(), item.collection_id))),
        )
        object.__setattr__(
            self,
            "database_seeds",
            tuple(sorted(seeds, key=lambda item: (item.display_name.casefold(), item.seed_id))),
        )
        object.__setattr__(
            self,
            "databases",
            tuple(sorted(databases, key=lambda item: (item.definition.display_name.casefold(), item.definition.database_id))),
        )


@dataclass(frozen=True, slots=True)
class DataManagerArtifactMaterializationResult:
    plan_id: str
    target_market_id: MarketId
    source_ohlcv: OHLCVSourceFingerprintV1
    root_logical_artifact_ids: tuple[str, ...]
    support_logical_artifact_ids: tuple[str, ...]
    created_artifact_ids: tuple[str, ...]
    reused_artifact_ids: tuple[str, ...]
    created_version_keys: tuple[ManagedArtifactVersionKey, ...]
    reused_version_keys: tuple[ManagedArtifactVersionKey, ...]
    advanced_logical_artifact_ids: tuple[str, ...]
    managed_artifacts: tuple[DataManagerManagedArtifactEntry, ...]

    def __post_init__(self) -> None:
        _sha(self.plan_id, "plan_id")
        market = _require_canonical_market(self.target_market_id)
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1) or self.source_ohlcv.market_id != market:
            raise ValueError("source_ohlcv must match target_market_id")
        validated: dict[str, tuple[str, ...]] = {}
        for name in (
            "root_logical_artifact_ids",
            "support_logical_artifact_ids",
            "created_artifact_ids",
            "reused_artifact_ids",
            "advanced_logical_artifact_ids",
        ):
            values = _text_tuple(getattr(self, name), name, allow_empty=True)
            for value in values:
                _sha(value, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(self, name, values)
            validated[name] = values
        if set(validated["root_logical_artifact_ids"]) & set(
            validated["support_logical_artifact_ids"]
        ):
            raise ValueError("root and support logical IDs must be disjoint")
        if set(validated["created_artifact_ids"]) & set(
            validated["reused_artifact_ids"]
        ):
            raise ValueError("created and reused Artifact IDs must be disjoint")
        for name in ("created_version_keys", "reused_version_keys"):
            keys = tuple(getattr(self, name))
            if not all(isinstance(item, ManagedArtifactVersionKey) for item in keys):
                raise TypeError(f"{name} must contain ManagedArtifactVersionKey values")
            if len(keys) != len(set(keys)):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(self, name, keys)
        if set(self.created_version_keys) & set(self.reused_version_keys):
            raise ValueError("created and reused version keys must be disjoint")
        managed = tuple(self.managed_artifacts)
        if not all(isinstance(item, DataManagerManagedArtifactEntry) for item in managed):
            raise TypeError("managed_artifacts contain invalid values")
        managed_logical_ids = tuple(item.logical_artifact_id for item in managed)
        if len(managed_logical_ids) != len(set(managed_logical_ids)):
            raise ValueError("managed_artifacts logical IDs must be unique")
        managed_logical_set = set(managed_logical_ids)
        required_logical_ids = set(validated["root_logical_artifact_ids"]) | set(
            validated["support_logical_artifact_ids"]
        )
        if required_logical_ids != managed_logical_set:
            raise ValueError(
                "root and support logical IDs must exactly match managed_artifacts"
            )
        managed_artifact_ids = {item.artifact_id for item in managed}
        if (
            set(validated["created_artifact_ids"])
            | set(validated["reused_artifact_ids"])
            != managed_artifact_ids
        ):
            raise ValueError(
                "created and reused Artifact evidence must exactly match managed_artifacts"
            )
        managed_version_keys = {
            ManagedArtifactVersionKey(item.logical_artifact_id, item.artifact_id)
            for item in managed
        }
        if (
            set(self.created_version_keys) | set(self.reused_version_keys)
            != managed_version_keys
        ):
            raise ValueError(
                "created and reused version-key evidence must exactly match managed_artifacts"
            )
        if not set(validated["advanced_logical_artifact_ids"]).issubset(
            managed_logical_set
        ):
            raise ValueError(
                "advanced logical Artifact IDs must belong to managed_artifacts"
            )
        object.__setattr__(self, "managed_artifacts", managed)


def _dataset_key(item: DataManagerDatasetEntry) -> tuple[object, ...]:
    if item.accepted:
        return (0, *_market_key(item.market_id), "", "")
    if item.market_id is not None:
        return (1, *_market_key(item.market_id), item.rejection_code, item.rejection_reason)
    return (2, "", "", "", "", item.rejection_code, item.rejection_reason)


def _freeze_portable_parameter(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_portable_parameter(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_portable_parameter(item) for item in value)
    return value


def _market_key(market_id: MarketId | None) -> tuple[str, str, str, str]:
    if market_id is None:
        return ("", "", "", "")
    return (
        market_id.exchange,
        market_id.market_type,
        market_id.symbol,
        market_id.timeframe,
    )


def _require_canonical_market(market_id: MarketId) -> MarketId:
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


def _require_coverage(
    row_count: int,
    first_timestamp_ms: int | None,
    last_timestamp_ms: int | None,
) -> None:
    if type(first_timestamp_ms) is not int or type(last_timestamp_ms) is not int:
        raise TypeError("coverage timestamps must be integers")
    if first_timestamp_ms < 0 or last_timestamp_ms < first_timestamp_ms:
        raise ValueError("coverage timestamps are invalid")
    if row_count <= 0:
        raise ValueError("covered data requires a positive row_count")


def _require_validity(valid: bool, rejection_reason: str) -> None:
    if type(valid) is not bool:
        raise TypeError("valid must be a boolean")
    reason = _text(rejection_reason, "rejection_reason")
    if valid and reason:
        raise ValueError("valid entries cannot contain rejection_reason")
    if not valid and not reason:
        raise ValueError("invalid entries require rejection_reason")


def _text(value: object, name: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if required and not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _text_tuple(
    values: object, name: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a sequence of strings")
    resolved = tuple(values)
    if any(not isinstance(value, str) or not value for value in resolved):
        raise ValueError(f"{name} must contain non-empty strings")
    if not allow_empty and not resolved:
        raise ValueError(f"{name} cannot be empty")
    return resolved


def _sha(value: object, name: str) -> str:
    text = _text(value, name, required=True)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return text


def _aware_datetime(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a timezone-aware datetime or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _optional_nonnegative_int(value: object, name: str) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
