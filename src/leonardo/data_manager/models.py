"""Immutable presentation models for the Data Manager workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Mapping

from leonardo.data import MarketId, canonicalize_market_id


_CURRENT_STATUSES = frozenset({"unknown", "current", "stale", "invalid"})
_OBJECT_KINDS = frozenset({"dataset", "artifact"})
_DELETION_KINDS = frozenset({"artifact", "recipe"})


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


def _dataset_key(item: DataManagerDatasetEntry) -> tuple[object, ...]:
    if item.accepted:
        return (0, *_market_key(item.market_id), "", "")
    if item.market_id is not None:
        return (1, *_market_key(item.market_id), item.rejection_code, item.rejection_reason)
    return (2, "", "", "", "", item.rejection_code, item.rejection_reason)


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


def _text_tuple(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a sequence of strings")
    resolved = tuple(values)
    if any(not isinstance(value, str) or not value for value in resolved):
        raise ValueError(f"{name} must contain non-empty strings")
    return resolved


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
