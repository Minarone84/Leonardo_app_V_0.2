"""Download Manager contracts for request and read-model state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from types import MappingProxyType


class DownloadWorkflowKind(str, Enum):
    """User-visible Download Manager workflow category."""

    DOWNLOAD_DATA = "download_data"
    OHLCV_MAINTENANCE = "ohlcv_maintenance"


class DownloadStatus(str, Enum):
    """Lifecycle status for download requests, items, and results."""

    REQUESTED = "requested"
    VALIDATED = "validated"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    PARTIALLY_COMPLETED = "partially_completed"


class DownloadTimeframeMode(str, Enum):
    """How a request resolves target timeframes."""

    EXPLICIT = "explicit"
    ALL = "all"
    DEFAULT = "default"
    SUPPORTED = "supported"


class DownloadRangeMode(str, Enum):
    """How a request resolves target date or history ranges."""

    EXPLICIT = "explicit"
    LATEST = "latest"
    MISSING_ONLY = "missing_only"
    FULL_HISTORY = "full_history"


class DownloadConflictPolicy(str, Enum):
    """Policy for handling output that already exists."""

    SKIP_EXISTING = "skip_existing"
    OVERWRITE = "overwrite"
    APPEND = "append"
    MERGE = "merge"
    REPAIR_GAPS = "repair_gaps"


class DownloadPriority(str, Enum):
    """Queue priority requested for future download execution."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class DownloadValidationSeverity(str, Enum):
    """Severity for preflight and validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DownloadValidationIssue:
    """Structured validation or preflight issue for a request or item."""

    code: str
    severity: DownloadValidationSeverity
    message: str
    field: str | None = None
    item_id: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.code, "code")
        if not isinstance(self.severity, DownloadValidationSeverity):
            raise TypeError("severity must be a DownloadValidationSeverity")
        _validate_non_empty_string(self.message, "message")
        _validate_optional_string(self.field, "field")
        _validate_optional_string(self.item_id, "item_id")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadRequest:
    """
    User or system request to create Download Manager work.

    The request describes intent only. It does not execute network calls,
    create output files, or carry active client handles.
    """

    request_id: str
    workflow_kind: DownloadWorkflowKind
    batch_id: str | None = None
    source: str | None = None
    market: str | None = None
    symbols: tuple[str, ...] = ()
    timeframe_mode: DownloadTimeframeMode = DownloadTimeframeMode.DEFAULT
    timeframes: tuple[str, ...] = ()
    range_mode: DownloadRangeMode = DownloadRangeMode.LATEST
    start: str | None = None
    end: str | None = None
    conflict_policy: DownloadConflictPolicy = DownloadConflictPolicy.SKIP_EXISTING
    priority: DownloadPriority = DownloadPriority.NORMAL
    requested_by: str | None = None
    correlation_id: str | None = None
    connection_ref: str | None = None
    websocket_required: bool = False
    preflight_required: bool = True
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.request_id, "request_id")
        if not isinstance(self.workflow_kind, DownloadWorkflowKind):
            raise TypeError("workflow_kind must be a DownloadWorkflowKind")
        for field_name in (
            "batch_id",
            "source",
            "market",
            "start",
            "end",
            "requested_by",
            "correlation_id",
            "connection_ref",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "symbols",
            _normalize_string_tuple(self.symbols, "symbols", allow_empty=False),
        )
        if not isinstance(self.timeframe_mode, DownloadTimeframeMode):
            raise TypeError("timeframe_mode must be a DownloadTimeframeMode")
        normalized_timeframes = _normalize_string_tuple(
            self.timeframes,
            "timeframes",
            allow_empty=self.timeframe_mode is not DownloadTimeframeMode.EXPLICIT,
        )
        object.__setattr__(self, "timeframes", normalized_timeframes)
        if not isinstance(self.range_mode, DownloadRangeMode):
            raise TypeError("range_mode must be a DownloadRangeMode")
        if not isinstance(self.conflict_policy, DownloadConflictPolicy):
            raise TypeError("conflict_policy must be a DownloadConflictPolicy")
        if not isinstance(self.priority, DownloadPriority):
            raise TypeError("priority must be a DownloadPriority")
        if type(self.websocket_required) is not bool:
            raise TypeError("websocket_required must be a bool")
        if type(self.preflight_required) is not bool:
            raise TypeError("preflight_required must be a bool")
        object.__setattr__(
            self,
            "tags",
            _normalize_string_tuple(self.tags, "tags", allow_empty=True),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadPreflight:
    """Read model for validating whether a download request can run."""

    request_id: str
    status: DownloadStatus
    can_run: bool
    required_connections: tuple[str, ...] = ()
    missing_connections: tuple[str, ...] = ()
    websocket_required: bool = False
    websocket_available: bool | None = None
    estimated_items: int | None = None
    estimated_symbols: int | None = None
    estimated_timeframes: int | None = None
    issues: tuple[DownloadValidationIssue, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.request_id, "request_id")
        if not isinstance(self.status, DownloadStatus):
            raise TypeError("status must be a DownloadStatus")
        if type(self.can_run) is not bool:
            raise TypeError("can_run must be a bool")
        object.__setattr__(
            self,
            "required_connections",
            _normalize_string_tuple(
                self.required_connections,
                "required_connections",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "missing_connections",
            _normalize_string_tuple(
                self.missing_connections,
                "missing_connections",
                allow_empty=True,
            ),
        )
        if type(self.websocket_required) is not bool:
            raise TypeError("websocket_required must be a bool")
        if self.websocket_available is not None and type(self.websocket_available) is not bool:
            raise TypeError("websocket_available must be a bool or None")
        for field_name in (
            "estimated_items",
            "estimated_symbols",
            "estimated_timeframes",
        ):
            _validate_optional_non_negative_int(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "issues",
            _normalize_tuple(
                self.issues,
                DownloadValidationIssue,
                "issues",
            ),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadProgress:
    """Request-level or item-level progress read model."""

    total_items: int | None = None
    completed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    running_items: int = 0
    percent: float | None = None
    current_item_id: str | None = None
    current_symbol: str | None = None
    current_timeframe: str | None = None
    message: str = ""
    bytes_downloaded: int | None = None
    rows_downloaded: int | None = None
    candles_downloaded: int | None = None
    started_at_utc: str | None = None
    updated_at_utc: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_optional_non_negative_int(self.total_items, "total_items")
        for field_name in (
            "completed_items",
            "failed_items",
            "skipped_items",
            "running_items",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if self.total_items is not None:
            current_total = (
                self.completed_items
                + self.failed_items
                + self.skipped_items
                + self.running_items
            )
            if current_total > self.total_items:
                raise ValueError(
                    "completed, failed, skipped, and running counts must not "
                    "exceed total_items"
                )
        if self.percent is not None:
            if type(self.percent) not in (float, int):
                raise TypeError("percent must be a number or None")
            if self.percent < 0 or self.percent > 100:
                raise ValueError("percent must be between 0 and 100")
            object.__setattr__(self, "percent", float(self.percent))
        for field_name in (
            "current_item_id",
            "current_symbol",
            "current_timeframe",
            "started_at_utc",
            "updated_at_utc",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        for field_name in (
            "bytes_downloaded",
            "rows_downloaded",
            "candles_downloaded",
        ):
            _validate_optional_non_negative_int(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadRequestItem:
    """Per-symbol and per-timeframe download work read model."""

    item_id: str
    request_id: str
    workflow_kind: DownloadWorkflowKind
    symbol: str
    timeframe: str
    status: DownloadStatus
    source: str | None = None
    market: str | None = None
    operation_id: str | None = None
    task_id: str | None = None
    process_id: str | None = None
    connection_id: str | None = None
    channel_id: str | None = None
    progress: DownloadProgress | None = None
    validation_issues: tuple[DownloadValidationIssue, ...] = ()
    created_at_utc: str | None = None
    updated_at_utc: str | None = None
    last_error: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.item_id, "item_id")
        _validate_non_empty_string(self.request_id, "request_id")
        if not isinstance(self.workflow_kind, DownloadWorkflowKind):
            raise TypeError("workflow_kind must be a DownloadWorkflowKind")
        _validate_non_empty_string(self.symbol, "symbol")
        _validate_non_empty_string(self.timeframe, "timeframe")
        if not isinstance(self.status, DownloadStatus):
            raise TypeError("status must be a DownloadStatus")
        for field_name in (
            "source",
            "market",
            "operation_id",
            "task_id",
            "process_id",
            "connection_id",
            "channel_id",
            "created_at_utc",
            "updated_at_utc",
            "last_error",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        if self.progress is not None and not isinstance(
            self.progress,
            DownloadProgress,
        ):
            raise TypeError("progress must be a DownloadProgress or None")
        object.__setattr__(
            self,
            "validation_issues",
            _normalize_tuple(
                self.validation_issues,
                DownloadValidationIssue,
                "validation_issues",
            ),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadResult:
    """Terminal or aggregate result read model for a download request."""

    request_id: str
    status: DownloadStatus
    output_refs: tuple[str, ...] = ()
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.request_id, "request_id")
        if not isinstance(self.status, DownloadStatus):
            raise TypeError("status must be a DownloadStatus")
        object.__setattr__(
            self,
            "output_refs",
            _normalize_string_tuple(self.output_refs, "output_refs", allow_empty=True),
        )
        for field_name in ("completed_count", "failed_count", "skipped_count"):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        _validate_optional_string(self.error, "error")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadSummary:
    """Aggregate Download Manager read model for inspection surfaces."""

    total_requests: int = 0
    total_items: int = 0
    requested_count: int = 0
    validated_count: int = 0
    queued_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    skipped_count: int = 0
    partially_completed_count: int = 0
    active_request_ids: tuple[str, ...] = ()
    queued_request_ids: tuple[str, ...] = ()
    failed_request_ids: tuple[str, ...] = ()
    active_item_ids: tuple[str, ...] = ()
    failed_item_ids: tuple[str, ...] = ()
    websocket_required_count: int = 0
    connection_blocked_count: int = 0
    preflight_failed_count: int = 0
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "total_requests",
            "total_items",
            "requested_count",
            "validated_count",
            "queued_count",
            "running_count",
            "completed_count",
            "failed_count",
            "cancelled_count",
            "skipped_count",
            "partially_completed_count",
            "websocket_required_count",
            "connection_blocked_count",
            "preflight_failed_count",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        for field_name in (
            "active_request_ids",
            "queued_request_ids",
            "failed_request_ids",
            "active_item_ids",
            "failed_item_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(
                    getattr(self, field_name),
                    field_name,
                    allow_empty=True,
                ),
            )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


def _normalize_string_tuple(
    values: tuple[str, ...],
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    normalized = tuple(values)
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    for item in normalized:
        _validate_non_empty_string(item, f"{field_name} entry")
    return normalized


def _normalize_tuple(
    values: tuple[object, ...],
    expected_type: type[object],
    field_name: str,
) -> tuple[object, ...]:
    normalized = tuple(values)
    for value in normalized:
        if not isinstance(value, expected_type):
            raise TypeError(f"{field_name} entries must be {expected_type.__name__}")
    return normalized


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        normalized[key] = _readonly_value(item)
    return MappingProxyType(normalized)


def _readonly_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _readonly_mapping(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_value(item) for item in value)
    return value


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _validate_non_negative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_optional_non_negative_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_negative_int(value, field_name)
