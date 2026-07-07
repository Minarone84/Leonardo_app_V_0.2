"""Download Data boundary contracts.

The contracts in this module define immutable vocabulary for the Download Data
workflow boundary. They describe user selection, selection recap, preflight,
progress read models, completion recap, storage references, and partial
persistence state. They do not execute downloads, call provider APIs, write
files, construct runtime services, or import GUI modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType


DOWNLOAD_DATA_WORKFLOW_ID = "download_data"
DOWNLOAD_DATA_BOUNDARY_ID = "download_data_boundary"
DOWNLOAD_DATA_ARTIFACT_ID = "ohlcv__candles"
DOWNLOAD_DATA_CSV_FILENAME = "candles.csv"
DOWNLOAD_DATA_METADATA_FILENAME = "candles.meta.json"
DOWNLOAD_DATA_MESSAGE_MAX_LENGTH = 280


class DownloadDataWorkflowStatus(str, Enum):
    """Boundary-level Download Data workflow status."""

    DRAFT = "draft"
    PREFLIGHT_READY = "preflight_ready"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    READY_TO_PROCESS = "ready_to_process"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DownloadDataPreflightMode(str, Enum):
    """Preflight decision for one selected OHLCV timeframe."""

    NEW_FILE = "new_file"
    UPDATE_EXISTING = "update_existing"
    ALREADY_CURRENT = "already_current"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class DownloadDataItemStatus(str, Enum):
    """Status for one Download Data preflight, progress, or completion row."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class DownloadDataPersistenceStatus(str, Enum):
    """Persistence state for Download Data output references."""

    NOT_STARTED = "not_started"
    NOT_APPLICABLE = "not_applicable"
    NEW_FILE = "new_file"
    UPDATE_EXISTING = "update_existing"
    PARTIAL_NEW_FILE = "partial_new_file"
    PARTIAL_UPDATE = "partial_update"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadDataValidationStatus(str, Enum):
    """Validation and loadability state for OHLCV output references."""

    NOT_VALIDATED = "not_validated"
    UNKNOWN = "unknown"
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class _SerializableContract:
    """Private mixin for JSON-friendly contract serialization."""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly dictionary representation."""

        return _to_json_value(self)  # type: ignore[return-value]


@dataclass(frozen=True)
class DownloadDataBoundaryDescriptor(_SerializableContract):
    """Static descriptor for the Download Data boundary."""

    boundary_id: str
    display_name: str
    workflow_ids: tuple[str, ...]
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.boundary_id, "boundary_id")
        _validate_non_empty_string(self.display_name, "display_name")
        _normalize_string_sequence_fields(
            self,
            (
                "workflow_ids",
                "docs_refs",
                "test_refs",
                "warnings",
                "blockers",
            ),
        )
        object.__setattr__(self, "metadata", _readonly_safe_metadata(self.metadata))


@dataclass(frozen=True)
class DownloadDataWorkflowDescriptor(_SerializableContract):
    """Static descriptor for the Download Data workflow."""

    workflow_id: str
    display_name: str
    status: DownloadDataWorkflowStatus | str = DownloadDataWorkflowStatus.DRAFT
    required_permission: str | None = "download:submit"
    provider_capability_refs: tuple[str, ...] = ()
    storage_policy_refs: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        _validate_non_empty_string(self.display_name, "display_name")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataWorkflowStatus, "status"),
        )
        _validate_optional_string(self.required_permission, "required_permission")
        _normalize_string_sequence_fields(
            self,
            (
                "provider_capability_refs",
                "storage_policy_refs",
                "docs_refs",
                "test_refs",
                "warnings",
                "blockers",
            ),
        )
        object.__setattr__(self, "metadata", _readonly_safe_metadata(self.metadata))


@dataclass(frozen=True)
class DownloadDataSelectionDraft(_SerializableContract):
    """User intent before Download Data preflight."""

    exchange_id: str | None = None
    market_type: str | None = None
    symbol: str | None = None
    selected_timeframes: tuple[str, ...] = ()
    selection_complete: bool = False
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("exchange_id", "market_type", "symbol"):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "selected_timeframes",
            _normalize_string_tuple(
                self.selected_timeframes,
                "selected_timeframes",
                allow_empty=True,
            ),
        )
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))
        object.__setattr__(
            self,
            "selection_complete",
            bool(
                self.exchange_id
                and self.market_type
                and self.symbol
                and self.selected_timeframes
            ),
        )
        object.__setattr__(self, "metadata", _readonly_safe_metadata(self.metadata))


@dataclass(frozen=True)
class DownloadDataSelectionSummary(_SerializableContract):
    """Table-like recap of a complete Download Data selection."""

    exchange_id: str
    market_type: str
    symbol: str
    selected_timeframes: tuple[str, ...]
    item_count: int = 0
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_selection_identity(self.exchange_id, self.market_type, self.symbol)
        object.__setattr__(
            self,
            "selected_timeframes",
            _normalize_string_tuple(
                self.selected_timeframes,
                "selected_timeframes",
                allow_empty=False,
            ),
        )
        object.__setattr__(self, "item_count", len(self.selected_timeframes))
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))


@dataclass(frozen=True)
class DownloadDataStorageTargetRef(_SerializableContract):
    """Expected legacy-compatible OHLCV value and sidecar paths."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    artifact_id: str = DOWNLOAD_DATA_ARTIFACT_ID
    csv_path: str | None = None
    metadata_path: str | None = None
    storage_root_ref: str | None = None
    path_policy_name: str | None = "old_leonardo_ohlcv_v1"
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_storage_identity(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
        )
        if self.artifact_id != DOWNLOAD_DATA_ARTIFACT_ID:
            raise ValueError("artifact_id must be ohlcv__candles")
        csv_path = self.csv_path or _legacy_ohlcv_path(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
            DOWNLOAD_DATA_CSV_FILENAME,
        )
        metadata_path = self.metadata_path or _legacy_ohlcv_path(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
            DOWNLOAD_DATA_METADATA_FILENAME,
        )
        _validate_relative_path(csv_path, "csv_path")
        _validate_relative_path(metadata_path, "metadata_path")
        if not csv_path.endswith("/" + DOWNLOAD_DATA_CSV_FILENAME):
            raise ValueError("csv_path must end with candles.csv")
        if not metadata_path.endswith("/" + DOWNLOAD_DATA_METADATA_FILENAME):
            raise ValueError("metadata_path must end with candles.meta.json")
        object.__setattr__(self, "csv_path", csv_path)
        object.__setattr__(self, "metadata_path", metadata_path)
        _validate_optional_string(self.storage_root_ref, "storage_root_ref")
        _validate_optional_string(self.path_policy_name, "path_policy_name")
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))


@dataclass(frozen=True)
class DownloadDataLocalDatasetState(_SerializableContract):
    """Existing local OHLCV state observed during preflight."""

    exists: bool
    csv_path: str | None = None
    metadata_path: str | None = None
    row_count: int | None = None
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    first_timestamp_utc: str | None = None
    last_timestamp_utc: str | None = None
    persistence_status: DownloadDataPersistenceStatus | str = (
        DownloadDataPersistenceStatus.NOT_STARTED
    )
    validation_status: DownloadDataValidationStatus | str = (
        DownloadDataValidationStatus.UNKNOWN
    )
    loadable: bool = False
    accepted: bool = False
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_bool(self.exists, "exists")
        _validate_optional_relative_path(self.csv_path, "csv_path")
        _validate_optional_relative_path(self.metadata_path, "metadata_path")
        _validate_optional_non_negative_int(self.row_count, "row_count")
        _validate_timestamp_range(
            self.first_timestamp_ms,
            self.last_timestamp_ms,
            "first_timestamp_ms",
            "last_timestamp_ms",
        )
        _validate_optional_string(self.first_timestamp_utc, "first_timestamp_utc")
        _validate_optional_string(self.last_timestamp_utc, "last_timestamp_utc")
        persistence_status = _coerce_enum(
            self.persistence_status,
            DownloadDataPersistenceStatus,
            "persistence_status",
        )
        validation_status = _coerce_enum(
            self.validation_status,
            DownloadDataValidationStatus,
            "validation_status",
        )
        _validate_bool(self.loadable, "loadable")
        _validate_bool(self.accepted, "accepted")
        _validate_partial_not_accepted(
            persistence_status,
            validation_status,
            self.loadable,
            self.accepted,
        )
        object.__setattr__(self, "persistence_status", persistence_status)
        object.__setattr__(self, "validation_status", validation_status)
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))


@dataclass(frozen=True)
class DownloadDataExchangeRangeSummary(_SerializableContract):
    """Provider capability and range facts for one selected timeframe."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    first_available_timestamp_ms: int | None = None
    last_available_timestamp_ms: int | None = None
    first_available_timestamp_utc: str | None = None
    last_available_timestamp_utc: str | None = None
    page_limit: int | None = None
    source: str | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_selection_identity(self.exchange_id, self.market_type, self.symbol)
        _validate_non_empty_string(self.timeframe, "timeframe")
        _validate_timestamp_range(
            self.first_available_timestamp_ms,
            self.last_available_timestamp_ms,
            "first_available_timestamp_ms",
            "last_available_timestamp_ms",
        )
        _validate_optional_string(
            self.first_available_timestamp_utc,
            "first_available_timestamp_utc",
        )
        _validate_optional_string(
            self.last_available_timestamp_utc,
            "last_available_timestamp_utc",
        )
        _validate_optional_non_negative_int(self.page_limit, "page_limit")
        _validate_optional_string(self.source, "source")
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))


@dataclass(frozen=True)
class DownloadDataWorkloadEstimate(_SerializableContract):
    """Estimated bars and steps for one selected timeframe."""

    expected_bars: int | None = None
    expected_steps: int | None = None
    bars_per_step: int | None = None
    estimated_start_timestamp_ms: int | None = None
    estimated_end_timestamp_ms: int | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("expected_bars", "expected_steps", "bars_per_step"):
            _validate_optional_non_negative_int(getattr(self, field_name), field_name)
        _validate_timestamp_range(
            self.estimated_start_timestamp_ms,
            self.estimated_end_timestamp_ms,
            "estimated_start_timestamp_ms",
            "estimated_end_timestamp_ms",
        )
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))


@dataclass(frozen=True)
class DownloadDataPreflightItem(_SerializableContract):
    """Preflight recap row for one selected timeframe."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    mode: DownloadDataPreflightMode | str
    status: DownloadDataItemStatus | str
    local_dataset_state: DownloadDataLocalDatasetState
    exchange_range_summary: DownloadDataExchangeRangeSummary
    workload_estimate: DownloadDataWorkloadEstimate
    storage_target: DownloadDataStorageTargetRef
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_selection_identity(self.exchange_id, self.market_type, self.symbol)
        _validate_non_empty_string(self.timeframe, "timeframe")
        object.__setattr__(
            self,
            "mode",
            _coerce_enum(self.mode, DownloadDataPreflightMode, "mode"),
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataItemStatus, "status"),
        )
        _validate_instance(
            self.local_dataset_state,
            DownloadDataLocalDatasetState,
            "local_dataset_state",
        )
        _validate_instance(
            self.exchange_range_summary,
            DownloadDataExchangeRangeSummary,
            "exchange_range_summary",
        )
        _validate_instance(
            self.workload_estimate,
            DownloadDataWorkloadEstimate,
            "workload_estimate",
        )
        _validate_instance(
            self.storage_target,
            DownloadDataStorageTargetRef,
            "storage_target",
        )
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))


@dataclass(frozen=True)
class DownloadDataPreflightSummary(_SerializableContract):
    """Aggregate preflight recap for a Download Data selection."""

    workflow_id: str
    selection_summary: DownloadDataSelectionSummary
    items: tuple[DownloadDataPreflightItem, ...]
    total_items: int = 0
    ready_items: int = 0
    blocked_items: int = 0
    new_file_items: int = 0
    update_items: int = 0
    already_current_items: int = 0
    expected_total_bars: int = 0
    expected_total_steps: int = 0
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        _validate_instance(
            self.selection_summary,
            DownloadDataSelectionSummary,
            "selection_summary",
        )
        items = _normalize_dataclass_tuple(
            self.items,
            DownloadDataPreflightItem,
            "items",
            allow_empty=True,
        )
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "total_items", len(items))
        object.__setattr__(
            self,
            "ready_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.READY),
        )
        object.__setattr__(
            self,
            "blocked_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.BLOCKED),
        )
        object.__setattr__(
            self,
            "new_file_items",
            sum(1 for item in items if item.mode is DownloadDataPreflightMode.NEW_FILE),
        )
        object.__setattr__(
            self,
            "update_items",
            sum(
                1
                for item in items
                if item.mode is DownloadDataPreflightMode.UPDATE_EXISTING
            ),
        )
        object.__setattr__(
            self,
            "already_current_items",
            sum(
                1
                for item in items
                if item.mode is DownloadDataPreflightMode.ALREADY_CURRENT
            ),
        )
        object.__setattr__(
            self,
            "expected_total_bars",
            sum(item.workload_estimate.expected_bars or 0 for item in items),
        )
        object.__setattr__(
            self,
            "expected_total_steps",
            sum(item.workload_estimate.expected_steps or 0 for item in items),
        )
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))
        object.__setattr__(self, "metadata", _readonly_safe_metadata(self.metadata))


@dataclass(frozen=True)
class DownloadDataProgressItem(_SerializableContract):
    """Per-timeframe progress read model."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    status: DownloadDataItemStatus | str
    mode: DownloadDataPreflightMode | str
    completed_steps: int = 0
    total_steps: int = 0
    downloaded_bars: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    first_timestamp_utc: str | None = None
    last_timestamp_utc: str | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_selection_identity(self.exchange_id, self.market_type, self.symbol)
        _validate_non_empty_string(self.timeframe, "timeframe")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataItemStatus, "status"),
        )
        object.__setattr__(
            self,
            "mode",
            _coerce_enum(self.mode, DownloadDataPreflightMode, "mode"),
        )
        for field_name in ("completed_steps", "total_steps", "downloaded_bars"):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if self.completed_steps > self.total_steps:
            raise ValueError("completed_steps must not exceed total_steps")
        _validate_timestamp_range(
            self.first_timestamp_ms,
            self.last_timestamp_ms,
            "first_timestamp_ms",
            "last_timestamp_ms",
        )
        _validate_optional_string(self.first_timestamp_utc, "first_timestamp_utc")
        _validate_optional_string(self.last_timestamp_utc, "last_timestamp_utc")
        _normalize_string_sequence_fields(self, ("warnings", "errors"))


@dataclass(frozen=True)
class DownloadDataProgressMessage(_SerializableContract):
    """Bounded progress message for Download Data read models."""

    message_id: str
    timestamp_ms: int
    timestamp_utc: str
    level: str
    exchange_id: str | None = None
    market_type: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    text: str = ""

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.message_id, "message_id")
        _validate_non_negative_int(self.timestamp_ms, "timestamp_ms")
        _validate_non_empty_string(self.timestamp_utc, "timestamp_utc")
        _validate_non_empty_string(self.level, "level")
        for field_name in ("exchange_id", "market_type", "symbol", "timeframe"):
            _validate_optional_string(getattr(self, field_name), field_name)
        _validate_bounded_message(self.text, "text")


@dataclass(frozen=True)
class DownloadDataProgressSummary(_SerializableContract):
    """Aggregate progress read model for Download Data processing."""

    workflow_id: str
    operation_id: str | None = None
    task_id: str | None = None
    status: DownloadDataWorkflowStatus | str = DownloadDataWorkflowStatus.DRAFT
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    cancelled_items: int = 0
    total_steps: int = 0
    completed_steps: int = 0
    items: tuple[DownloadDataProgressItem, ...] = ()
    messages: tuple[DownloadDataProgressMessage, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        _validate_optional_string(self.operation_id, "operation_id")
        _validate_optional_string(self.task_id, "task_id")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataWorkflowStatus, "status"),
        )
        items = _normalize_dataclass_tuple(
            self.items,
            DownloadDataProgressItem,
            "items",
            allow_empty=True,
        )
        messages = _normalize_dataclass_tuple(
            self.messages,
            DownloadDataProgressMessage,
            "messages",
            allow_empty=True,
        )
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "total_items", len(items))
        object.__setattr__(
            self,
            "completed_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.COMPLETED),
        )
        object.__setattr__(
            self,
            "failed_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.FAILED),
        )
        object.__setattr__(
            self,
            "cancelled_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.CANCELLED),
        )
        object.__setattr__(self, "total_steps", sum(item.total_steps for item in items))
        object.__setattr__(
            self,
            "completed_steps",
            sum(item.completed_steps for item in items),
        )
        _normalize_string_sequence_fields(self, ("warnings", "errors"))


@dataclass(frozen=True)
class DownloadDataOutputRef(_SerializableContract):
    """Final or partial Download Data output file reference."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    artifact_id: str = DOWNLOAD_DATA_ARTIFACT_ID
    csv_path: str | None = None
    metadata_path: str | None = None
    bars_written: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    first_timestamp_utc: str | None = None
    last_timestamp_utc: str | None = None
    persistence_status: DownloadDataPersistenceStatus | str = (
        DownloadDataPersistenceStatus.NOT_STARTED
    )
    validation_status: DownloadDataValidationStatus | str = (
        DownloadDataValidationStatus.UNKNOWN
    )
    loadable: bool = False
    accepted: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_storage_identity(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
        )
        if self.artifact_id != DOWNLOAD_DATA_ARTIFACT_ID:
            raise ValueError("artifact_id must be ohlcv__candles")
        csv_path = self.csv_path or _legacy_ohlcv_path(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
            DOWNLOAD_DATA_CSV_FILENAME,
        )
        metadata_path = self.metadata_path or _legacy_ohlcv_path(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
            DOWNLOAD_DATA_METADATA_FILENAME,
        )
        _validate_relative_path(csv_path, "csv_path")
        _validate_relative_path(metadata_path, "metadata_path")
        object.__setattr__(self, "csv_path", csv_path)
        object.__setattr__(self, "metadata_path", metadata_path)
        _validate_non_negative_int(self.bars_written, "bars_written")
        _validate_timestamp_range(
            self.first_timestamp_ms,
            self.last_timestamp_ms,
            "first_timestamp_ms",
            "last_timestamp_ms",
        )
        _validate_optional_string(self.first_timestamp_utc, "first_timestamp_utc")
        _validate_optional_string(self.last_timestamp_utc, "last_timestamp_utc")
        persistence_status = _coerce_enum(
            self.persistence_status,
            DownloadDataPersistenceStatus,
            "persistence_status",
        )
        validation_status = _coerce_enum(
            self.validation_status,
            DownloadDataValidationStatus,
            "validation_status",
        )
        _validate_bool(self.loadable, "loadable")
        _validate_bool(self.accepted, "accepted")
        _validate_partial_not_accepted(
            persistence_status,
            validation_status,
            self.loadable,
            self.accepted,
        )
        object.__setattr__(self, "persistence_status", persistence_status)
        object.__setattr__(self, "validation_status", validation_status)
        _normalize_string_sequence_fields(self, ("warnings", "errors"))


@dataclass(frozen=True)
class DownloadDataCompletionItem(_SerializableContract):
    """Final recap row for one selected timeframe."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    mode: DownloadDataPreflightMode | str
    status: DownloadDataItemStatus | str
    output_ref: DownloadDataOutputRef
    bars_downloaded: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    first_timestamp_utc: str | None = None
    last_timestamp_utc: str | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_selection_identity(self.exchange_id, self.market_type, self.symbol)
        _validate_non_empty_string(self.timeframe, "timeframe")
        object.__setattr__(
            self,
            "mode",
            _coerce_enum(self.mode, DownloadDataPreflightMode, "mode"),
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataItemStatus, "status"),
        )
        _validate_instance(self.output_ref, DownloadDataOutputRef, "output_ref")
        _validate_non_negative_int(self.bars_downloaded, "bars_downloaded")
        _validate_timestamp_range(
            self.first_timestamp_ms,
            self.last_timestamp_ms,
            "first_timestamp_ms",
            "last_timestamp_ms",
        )
        _validate_optional_string(self.first_timestamp_utc, "first_timestamp_utc")
        _validate_optional_string(self.last_timestamp_utc, "last_timestamp_utc")
        _normalize_string_sequence_fields(self, ("warnings", "errors"))


@dataclass(frozen=True)
class DownloadDataCompletionSummary(_SerializableContract):
    """Final aggregate recap for Download Data processing."""

    workflow_id: str
    status: DownloadDataWorkflowStatus | str
    total_items: int = 0
    completed_items: int = 0
    partial_items: int = 0
    failed_items: int = 0
    cancelled_items: int = 0
    output_refs: tuple[DownloadDataOutputRef, ...] = ()
    items: tuple[DownloadDataCompletionItem, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataWorkflowStatus, "status"),
        )
        output_refs = _normalize_dataclass_tuple(
            self.output_refs,
            DownloadDataOutputRef,
            "output_refs",
            allow_empty=True,
        )
        items = _normalize_dataclass_tuple(
            self.items,
            DownloadDataCompletionItem,
            "items",
            allow_empty=True,
        )
        object.__setattr__(self, "output_refs", output_refs)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "total_items", len(items))
        object.__setattr__(
            self,
            "completed_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.COMPLETED),
        )
        object.__setattr__(
            self,
            "partial_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.PARTIAL),
        )
        object.__setattr__(
            self,
            "failed_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.FAILED),
        )
        object.__setattr__(
            self,
            "cancelled_items",
            sum(1 for item in items if item.status is DownloadDataItemStatus.CANCELLED),
        )
        _normalize_string_sequence_fields(self, ("warnings", "errors"))
        object.__setattr__(self, "metadata", _readonly_safe_metadata(self.metadata))


@dataclass(frozen=True)
class DownloadDataPartialPersistenceSummary(_SerializableContract):
    """Read model for partial OHLCV output that needs later maintenance."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    csv_path: str
    metadata_path: str
    partial: bool
    persistence_status: DownloadDataPersistenceStatus | str
    bars_persisted: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    first_timestamp_utc: str | None = None
    last_timestamp_utc: str | None = None
    resumable: bool = False
    maintenance_required: bool = True
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_storage_identity(
            self.exchange_id,
            self.market_type,
            self.symbol,
            self.timeframe,
        )
        _validate_relative_path(self.csv_path, "csv_path")
        _validate_relative_path(self.metadata_path, "metadata_path")
        _validate_bool(self.partial, "partial")
        persistence_status = _coerce_enum(
            self.persistence_status,
            DownloadDataPersistenceStatus,
            "persistence_status",
        )
        if self.partial and persistence_status not in _PARTIAL_PERSISTENCE_STATUSES:
            raise ValueError("partial persistence requires a partial persistence status")
        object.__setattr__(self, "persistence_status", persistence_status)
        _validate_non_negative_int(self.bars_persisted, "bars_persisted")
        _validate_timestamp_range(
            self.first_timestamp_ms,
            self.last_timestamp_ms,
            "first_timestamp_ms",
            "last_timestamp_ms",
        )
        _validate_optional_string(self.first_timestamp_utc, "first_timestamp_utc")
        _validate_optional_string(self.last_timestamp_utc, "last_timestamp_utc")
        _validate_bool(self.resumable, "resumable")
        _validate_bool(self.maintenance_required, "maintenance_required")
        _normalize_string_sequence_fields(self, ("warnings", "errors"))


def _legacy_ohlcv_path(
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
    filename: str,
) -> str:
    return (
        PurePosixPath("data")
        / "historical"
        / exchange_id.strip()
        / market_type.strip()
        / symbol.strip()
        / timeframe.strip()
        / "ohlcv"
        / filename
    ).as_posix()


def _normalize_string_sequence_fields(value: object, field_names: tuple[str, ...]) -> None:
    for field_name in field_names:
        object.__setattr__(
            value,
            field_name,
            _normalize_string_tuple(
                getattr(value, field_name),
                field_name,
                allow_empty=True,
            ),
        )


def _normalize_string_tuple(
    values: object,
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a sequence of strings")
    try:
        normalized = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{field_name} must be a sequence of strings") from error
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    for item in normalized:
        _validate_non_empty_string(item, f"{field_name} entry")
    return normalized


def _normalize_dataclass_tuple(
    values: object,
    expected_type: type[object],
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[object, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a sequence of {expected_type.__name__}")
    try:
        normalized = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(
            f"{field_name} must be a sequence of {expected_type.__name__}"
        ) from error
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    for item in normalized:
        _validate_instance(item, expected_type, f"{field_name} entry")
    return normalized


def _coerce_enum(value: object, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as error:
            allowed = ", ".join(str(item.value) for item in enum_type)
            raise ValueError(f"{field_name} must be one of: {allowed}") from error
    raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _readonly_safe_metadata(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        _validate_safe_metadata_key(key)
        normalized[key] = _readonly_safe_value(item)
    return MappingProxyType(normalized)


def _readonly_safe_value(value: object) -> object:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        return _readonly_safe_metadata(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_safe_value(item) for item in value)
    raise TypeError("metadata values must be JSON-like")


def _validate_safe_metadata_key(value: str) -> None:
    normalized = value.strip().lower()
    for sensitive in _SENSITIVE_METADATA_KEY_PARTS:
        if sensitive in normalized:
            raise ValueError("metadata contains a sensitive key")


def _validate_selection_identity(exchange_id: str, market_type: str, symbol: str) -> None:
    _validate_non_empty_string(exchange_id, "exchange_id")
    _validate_non_empty_string(market_type, "market_type")
    _validate_non_empty_string(symbol, "symbol")


def _validate_storage_identity(
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> None:
    _validate_selection_identity(exchange_id, market_type, symbol)
    _validate_non_empty_string(timeframe, "timeframe")
    for field_name, value in (
        ("exchange_id", exchange_id),
        ("market_type", market_type),
        ("symbol", symbol),
        ("timeframe", timeframe),
    ):
        _validate_path_segment(value, field_name)


def _validate_path_segment(value: str, field_name: str) -> None:
    _validate_non_empty_string(value, field_name)
    if "/" in value or "\\" in value or ".." in value or ":" in value:
        raise ValueError(f"{field_name} must be a single relative path segment")


def _validate_instance(value: object, expected_type: type[object], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be a {expected_type.__name__}")


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _validate_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")


def _validate_non_negative_int(value: object, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_optional_non_negative_int(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_non_negative_int(value, field_name)


def _validate_timestamp_range(
    first_timestamp_ms: object,
    last_timestamp_ms: object,
    first_field_name: str,
    last_field_name: str,
) -> None:
    _validate_optional_non_negative_int(first_timestamp_ms, first_field_name)
    _validate_optional_non_negative_int(last_timestamp_ms, last_field_name)
    if (
        first_timestamp_ms is not None
        and last_timestamp_ms is not None
        and first_timestamp_ms > last_timestamp_ms
    ):
        raise ValueError(f"{first_field_name} must not be after {last_field_name}")


def _validate_optional_relative_path(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_relative_path(value, field_name)


def _validate_relative_path(value: object, field_name: str) -> None:
    _validate_non_empty_string(value, field_name)
    if "\\" in value:
        raise ValueError(f"{field_name} must use POSIX-style relative paths")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"{field_name} must not be an absolute path")
    if ".." in path.parts:
        raise ValueError(f"{field_name} must not contain parent segments")


def _validate_partial_not_accepted(
    persistence_status: DownloadDataPersistenceStatus,
    validation_status: DownloadDataValidationStatus,
    loadable: bool,
    accepted: bool,
) -> None:
    if persistence_status not in _PARTIAL_PERSISTENCE_STATUSES:
        return
    if validation_status is DownloadDataValidationStatus.VALID:
        raise ValueError("partial persistence cannot be validated")
    if loadable:
        raise ValueError("partial persistence cannot be loadable")
    if accepted:
        raise ValueError("partial persistence cannot be accepted")


def _validate_bounded_message(value: object, field_name: str) -> None:
    _validate_non_empty_string(value, field_name)
    if len(value) > DOWNLOAD_DATA_MESSAGE_MAX_LENGTH:
        raise ValueError(f"{field_name} must be at most 280 characters")


def _to_json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _to_json_value(getattr(value, field.name))
            for field in dataclass_fields(value)
        }
    if isinstance(value, Mapping):
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_to_json_value(item) for item in value]
    return value


_PARTIAL_PERSISTENCE_STATUSES = {
    DownloadDataPersistenceStatus.PARTIAL_NEW_FILE,
    DownloadDataPersistenceStatus.PARTIAL_UPDATE,
}

_SENSITIVE_METADATA_KEY_PARTS = (
    "credential",
    "credentials",
    "token",
    "secret",
    "password",
    "api_key",
    "authorization",
    "bearer",
    "client",
    "socket",
    "payload",
    "raw_payload",
    "response",
)


__all__ = [
    "DOWNLOAD_DATA_ARTIFACT_ID",
    "DOWNLOAD_DATA_BOUNDARY_ID",
    "DOWNLOAD_DATA_CSV_FILENAME",
    "DOWNLOAD_DATA_MESSAGE_MAX_LENGTH",
    "DOWNLOAD_DATA_METADATA_FILENAME",
    "DOWNLOAD_DATA_WORKFLOW_ID",
    "DownloadDataBoundaryDescriptor",
    "DownloadDataCompletionItem",
    "DownloadDataCompletionSummary",
    "DownloadDataExchangeRangeSummary",
    "DownloadDataItemStatus",
    "DownloadDataLocalDatasetState",
    "DownloadDataOutputRef",
    "DownloadDataPartialPersistenceSummary",
    "DownloadDataPersistenceStatus",
    "DownloadDataPreflightItem",
    "DownloadDataPreflightMode",
    "DownloadDataPreflightSummary",
    "DownloadDataProgressItem",
    "DownloadDataProgressMessage",
    "DownloadDataProgressSummary",
    "DownloadDataSelectionDraft",
    "DownloadDataSelectionSummary",
    "DownloadDataStorageTargetRef",
    "DownloadDataValidationStatus",
    "DownloadDataWorkflowDescriptor",
    "DownloadDataWorkflowStatus",
]
