"""Download Data execution boundary contracts.

This module defines immutable contracts for the first real Download Data
execution boundary. The contracts describe commands, execution targets,
provider page requests and results, normalized candles, storage write requests
and results, progress events, final results, errors, and plans.

The module is contract-only. It does not call provider APIs, construct network
clients, write files, inspect storage, create tasks, create operations, import
Core services, or import GUI modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from enum import Enum
import math
from types import MappingProxyType


DOWNLOAD_DATA_EXECUTION_MESSAGE_MAX_LENGTH = 280
DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_MAX = 1000
DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_DEFAULT = 200

_SENSITIVE_METADATA_KEY_TERMS = frozenset(
    {
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
        "provider",
        "adapter",
        "writer",
        "handle",
    }
)
_SENSITIVE_MESSAGE_TERMS = frozenset(
    {
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
        "handle",
    }
)
_REDACTED_MESSAGE = "[redacted]"


class DownloadDataExecutionStatus(str, Enum):
    """Lifecycle status for Download Data execution read models."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadDataExecutionMode(str, Enum):
    """Execution mode for one Download Data target or storage request."""

    NEW_FILE = "new_file"
    UPDATE_EXISTING = "update_existing"
    NO_OP = "no_op"
    PARTIAL_NEW_FILE = "partial_new_file"
    PARTIAL_UPDATE = "partial_update"


class DownloadDataExecutionDirection(str, Enum):
    """Direction of historical data traversal for an execution target."""

    FORWARD_UPDATE = "forward_update"
    BACKWARD_HISTORY = "backward_history"


class DownloadDataProviderResultStatus(str, Enum):
    """Provider page result status after a future adapter fetch."""

    OK = "ok"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_ERROR = "provider_error"
    PARSE_ERROR = "parse_error"


class DownloadDataStorageWriteStatus(str, Enum):
    """Storage write result status after a future storage boundary call."""

    PLANNED = "planned"
    WRITTEN = "written"
    PARTIALLY_WRITTEN = "partially_written"
    SKIPPED = "skipped"
    FAILED = "failed"


class DownloadDataCandleSortOrder(str, Enum):
    """Sort order for normalized candle rows."""

    ASCENDING = "ascending"
    DESCENDING = "descending"


@dataclass(frozen=True)
class _SerializableContract:
    """Private mixin for JSON-friendly contract serialization."""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly dictionary representation."""

        return _to_json_value(self)  # type: ignore[return-value]


@dataclass(frozen=True)
class DownloadDataExecutionTarget(_SerializableContract):
    """One selected exchange, market, symbol, and timeframe execution target."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    storage_target_ref: str
    mode: DownloadDataExecutionMode | str
    direction: DownloadDataExecutionDirection | str
    requested_start_timestamp_ms: int | None = None
    requested_end_timestamp_ms: int | None = None
    local_latest_timestamp_ms: int | None = None
    provider_earliest_timestamp_ms: int | None = None
    provider_latest_timestamp_ms: int | None = None
    limit: int | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "exchange_id",
            "market_type",
            "symbol",
            "timeframe",
            "storage_target_ref",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "mode",
            _coerce_enum(self.mode, DownloadDataExecutionMode, "mode"),
        )
        object.__setattr__(
            self,
            "direction",
            _coerce_enum(
                self.direction,
                DownloadDataExecutionDirection,
                "direction",
            ),
        )
        _validate_timestamp_range(
            self.requested_start_timestamp_ms,
            self.requested_end_timestamp_ms,
            "requested_start_timestamp_ms",
            "requested_end_timestamp_ms",
        )
        _validate_optional_non_negative_int(
            self.local_latest_timestamp_ms,
            "local_latest_timestamp_ms",
        )
        _validate_timestamp_range(
            self.provider_earliest_timestamp_ms,
            self.provider_latest_timestamp_ms,
            "provider_earliest_timestamp_ms",
            "provider_latest_timestamp_ms",
        )
        _validate_optional_page_limit(self.limit, "limit")
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataExecutionCommand(_SerializableContract):
    """Core-routed command intent for future Download Data execution."""

    command_id: str
    workflow_id: str
    request_id: str
    targets: tuple[DownloadDataExecutionTarget, ...]
    operation_id: str | None = None
    dry_run: bool = False
    sandbox_root_ref: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("command_id", "workflow_id", "request_id"):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        _validate_optional_string(self.operation_id, "operation_id")
        _validate_bool(self.dry_run, "dry_run")
        _validate_optional_string(self.sandbox_root_ref, "sandbox_root_ref")
        _validate_optional_string(self.created_at, "created_at")
        object.__setattr__(
            self,
            "targets",
            _normalize_dataclass_tuple(
                self.targets,
                DownloadDataExecutionTarget,
                "targets",
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataProviderPageRequest(_SerializableContract):
    """One future provider adapter page fetch request."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    category: str
    interval: str
    start_timestamp_ms: int | None = None
    end_timestamp_ms: int | None = None
    limit: int = DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_DEFAULT
    direction: DownloadDataExecutionDirection | str = (
        DownloadDataExecutionDirection.BACKWARD_HISTORY
    )
    page_index: int = 0
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "exchange_id",
            "market_type",
            "symbol",
            "timeframe",
            "category",
            "interval",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        _validate_timestamp_range(
            self.start_timestamp_ms,
            self.end_timestamp_ms,
            "start_timestamp_ms",
            "end_timestamp_ms",
        )
        _validate_required_page_limit(self.limit, "limit")
        object.__setattr__(
            self,
            "direction",
            _coerce_enum(
                self.direction,
                DownloadDataExecutionDirection,
                "direction",
            ),
        )
        _validate_non_negative_int(self.page_index, "page_index")
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataNormalizedCandle(_SerializableContract):
    """Canonical normalized OHLCV candle row."""

    timestamp_ms: int
    open: str | int | float
    high: str | int | float
    low: str | int | float
    close: str | int | float
    volume: str | int | float
    turnover: str | int | float | None = None
    source_order: int | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_negative_int(self.timestamp_ms, "timestamp_ms")
        for field_name in ("open", "high", "low", "close", "volume"):
            _validate_decimal_like(getattr(self, field_name), field_name)
        if self.turnover is not None:
            _validate_decimal_like(self.turnover, "turnover")
        _validate_optional_non_negative_int(self.source_order, "source_order")
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataProviderPageResult(_SerializableContract):
    """Provider page result returned by a future provider adapter boundary."""

    request: DownloadDataProviderPageRequest
    status: DownloadDataProviderResultStatus | str
    candles: tuple[DownloadDataNormalizedCandle, ...] = ()
    sort_order: DownloadDataCandleSortOrder | str = (
        DownloadDataCandleSortOrder.ASCENDING
    )
    next_page_cursor: str | None = None
    rate_limit_reset_at: int | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_instance(
            self.request,
            DownloadDataProviderPageRequest,
            "request",
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(
                self.status,
                DownloadDataProviderResultStatus,
                "status",
            ),
        )
        object.__setattr__(
            self,
            "candles",
            _normalize_dataclass_tuple(
                self.candles,
                DownloadDataNormalizedCandle,
                "candles",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "sort_order",
            _coerce_enum(
                self.sort_order,
                DownloadDataCandleSortOrder,
                "sort_order",
            ),
        )
        _validate_optional_string(self.next_page_cursor, "next_page_cursor")
        _validate_optional_non_negative_int(
            self.rate_limit_reset_at,
            "rate_limit_reset_at",
        )
        _normalize_string_sequence_fields(self, ("warnings", "errors"))
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataStorageWriteRequest(_SerializableContract):
    """Storage boundary request for a future OHLCV write operation."""

    target: DownloadDataExecutionTarget
    candles: tuple[DownloadDataNormalizedCandle, ...]
    csv_path: str
    metadata_path: str
    write_mode: DownloadDataExecutionMode | str
    deduplicate: bool = True
    sort_order: DownloadDataCandleSortOrder | str = (
        DownloadDataCandleSortOrder.ASCENDING
    )
    atomic: bool = True
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_instance(
            self.target,
            DownloadDataExecutionTarget,
            "target",
        )
        object.__setattr__(
            self,
            "candles",
            _normalize_dataclass_tuple(
                self.candles,
                DownloadDataNormalizedCandle,
                "candles",
                allow_empty=True,
            ),
        )
        _validate_relative_path(self.csv_path, "csv_path")
        _validate_relative_path(self.metadata_path, "metadata_path")
        object.__setattr__(
            self,
            "write_mode",
            _coerce_enum(self.write_mode, DownloadDataExecutionMode, "write_mode"),
        )
        _validate_bool(self.deduplicate, "deduplicate")
        sort_order = _coerce_enum(
            self.sort_order,
            DownloadDataCandleSortOrder,
            "sort_order",
        )
        if sort_order is not DownloadDataCandleSortOrder.ASCENDING:
            raise ValueError("storage write requests require ascending candles")
        object.__setattr__(self, "sort_order", sort_order)
        _validate_bool(self.atomic, "atomic")
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataStorageWriteResult(_SerializableContract):
    """Storage boundary result after a future OHLCV write operation."""

    target: DownloadDataExecutionTarget
    status: DownloadDataStorageWriteStatus | str
    csv_path: str
    metadata_path: str
    bars_written: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    partial: bool = False
    accepted: bool = False
    loadable: bool = False
    validated: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_instance(
            self.target,
            DownloadDataExecutionTarget,
            "target",
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataStorageWriteStatus, "status"),
        )
        _validate_relative_path(self.csv_path, "csv_path")
        _validate_relative_path(self.metadata_path, "metadata_path")
        _validate_non_negative_int(self.bars_written, "bars_written")
        _validate_timestamp_range(
            self.first_timestamp_ms,
            self.last_timestamp_ms,
            "first_timestamp_ms",
            "last_timestamp_ms",
        )
        for field_name in ("partial", "accepted", "loadable", "validated"):
            _validate_bool(getattr(self, field_name), field_name)
        if self.partial and (self.accepted or self.loadable or self.validated):
            raise ValueError("partial storage results cannot be accepted/loadable/validated")
        _normalize_string_sequence_fields(self, ("warnings", "errors"))
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataExecutionProgressEvent(_SerializableContract):
    """Progress event read model emitted by a future execution boundary."""

    event_id: str
    workflow_id: str
    target: DownloadDataExecutionTarget
    status: DownloadDataExecutionStatus | str
    message: str
    timestamp_ms: int
    operation_id: str | None = None
    task_id: str | None = None
    completed_steps: int = 0
    total_steps: int = 0
    downloaded_bars: int = 0
    written_bars: int = 0
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.event_id, "event_id")
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        _validate_instance(
            self.target,
            DownloadDataExecutionTarget,
            "target",
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataExecutionStatus, "status"),
        )
        object.__setattr__(
            self,
            "message",
            _bounded_redacted_message(self.message, "message"),
        )
        _validate_non_negative_int(self.timestamp_ms, "timestamp_ms")
        _validate_optional_string(self.operation_id, "operation_id")
        _validate_optional_string(self.task_id, "task_id")
        for field_name in (
            "completed_steps",
            "total_steps",
            "downloaded_bars",
            "written_bars",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if self.completed_steps > self.total_steps:
            raise ValueError("completed_steps must not exceed total_steps")
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataExecutionError(_SerializableContract):
    """Structured execution error read model."""

    error_id: str
    status: DownloadDataProviderResultStatus | str
    code: str
    message: str
    target: DownloadDataExecutionTarget | None = None
    retryable: bool = False
    provider_error: bool = False
    storage_error: bool = False
    rate_limited: bool = False
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.error_id, "error_id")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(
                self.status,
                DownloadDataProviderResultStatus,
                "status",
            ),
        )
        _validate_non_empty_string(self.code, "code")
        object.__setattr__(
            self,
            "message",
            _bounded_redacted_message(self.message, "message"),
        )
        if self.target is not None:
            _validate_instance(
                self.target,
                DownloadDataExecutionTarget,
                "target",
            )
        for field_name in (
            "retryable",
            "provider_error",
            "storage_error",
            "rate_limited",
        ):
            _validate_bool(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataExecutionResult(_SerializableContract):
    """Final Download Data execution result read model."""

    workflow_id: str
    status: DownloadDataExecutionStatus | str
    targets: tuple[DownloadDataExecutionTarget, ...]
    storage_results: tuple[DownloadDataStorageWriteResult, ...] = ()
    progress_events: tuple[DownloadDataExecutionProgressEvent, ...] = ()
    operation_id: str | None = None
    total_bars_downloaded: int = 0
    total_bars_written: int = 0
    partial_count: int = 0
    failed_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[DownloadDataExecutionError, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        _validate_optional_string(self.operation_id, "operation_id")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, DownloadDataExecutionStatus, "status"),
        )
        object.__setattr__(
            self,
            "targets",
            _normalize_dataclass_tuple(
                self.targets,
                DownloadDataExecutionTarget,
                "targets",
                allow_empty=False,
            ),
        )
        storage_results = _normalize_dataclass_tuple(
            self.storage_results,
            DownloadDataStorageWriteResult,
            "storage_results",
            allow_empty=True,
        )
        progress_events = _normalize_dataclass_tuple(
            self.progress_events,
            DownloadDataExecutionProgressEvent,
            "progress_events",
            allow_empty=True,
        )
        errors = _normalize_dataclass_tuple(
            self.errors,
            DownloadDataExecutionError,
            "errors",
            allow_empty=True,
        )
        object.__setattr__(self, "storage_results", storage_results)
        object.__setattr__(self, "progress_events", progress_events)
        object.__setattr__(self, "errors", errors)
        _validate_non_negative_int(
            self.total_bars_downloaded,
            "total_bars_downloaded",
        )
        _validate_non_negative_int(self.total_bars_written, "total_bars_written")
        _validate_non_negative_int(self.partial_count, "partial_count")
        _validate_non_negative_int(self.failed_count, "failed_count")
        object.__setattr__(
            self,
            "total_bars_downloaded",
            _aggregate_downloaded_bars(
                progress_events,
                self.total_bars_downloaded,
            ),
        )
        object.__setattr__(
            self,
            "total_bars_written",
            sum(result.bars_written for result in storage_results),
        )
        object.__setattr__(
            self,
            "partial_count",
            sum(1 for result in storage_results if result.partial),
        )
        object.__setattr__(
            self,
            "failed_count",
            sum(
                1
                for result in storage_results
                if result.status is DownloadDataStorageWriteStatus.FAILED
            )
            + len(errors),
        )
        _normalize_string_sequence_fields(self, ("warnings",))
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class DownloadDataExecutionPlan(_SerializableContract):
    """Read-only execution plan for future Download Data execution."""

    plan_id: str
    workflow_id: str
    targets: tuple[DownloadDataExecutionTarget, ...]
    provider_page_requests: tuple[DownloadDataProviderPageRequest, ...] = ()
    storage_write_requests: tuple[DownloadDataStorageWriteRequest, ...] = ()
    expected_steps: int = 0
    expected_bars: int | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.plan_id, "plan_id")
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        object.__setattr__(
            self,
            "targets",
            _normalize_dataclass_tuple(
                self.targets,
                DownloadDataExecutionTarget,
                "targets",
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "provider_page_requests",
            _normalize_dataclass_tuple(
                self.provider_page_requests,
                DownloadDataProviderPageRequest,
                "provider_page_requests",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "storage_write_requests",
            _normalize_dataclass_tuple(
                self.storage_write_requests,
                DownloadDataStorageWriteRequest,
                "storage_write_requests",
                allow_empty=True,
            ),
        )
        _validate_non_negative_int(self.expected_steps, "expected_steps")
        _validate_optional_non_negative_int(self.expected_bars, "expected_bars")
        _normalize_string_sequence_fields(self, ("warnings", "blockers"))
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


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


def _readonly_safe_metadata(
    value: object,
    field_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        _validate_safe_metadata_key(key)
        normalized[key] = _readonly_safe_value(item, field_name)
    return MappingProxyType(normalized)


def _readonly_safe_value(value: object, field_name: str) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{field_name} float values must be finite")
        return value
    if isinstance(value, Mapping):
        return _readonly_safe_metadata(value, field_name)
    if isinstance(value, tuple | list):
        return tuple(_readonly_safe_value(item, field_name) for item in value)
    raise TypeError(f"{field_name} values must be JSON-like")


def _validate_safe_metadata_key(value: str) -> None:
    normalized = _normalized_sensitive_text(value)
    for term in _SENSITIVE_METADATA_KEY_TERMS:
        if term in normalized:
            raise ValueError(f"metadata key is not allowed: {value}")


def _bounded_redacted_message(value: str, field_name: str) -> str:
    _validate_non_empty_string(value, field_name)
    if len(value) > DOWNLOAD_DATA_EXECUTION_MESSAGE_MAX_LENGTH:
        raise ValueError(
            f"{field_name} must be at most "
            f"{DOWNLOAD_DATA_EXECUTION_MESSAGE_MAX_LENGTH} characters"
        )
    if _contains_sensitive_message_text(value):
        return _REDACTED_MESSAGE
    return value


def _contains_sensitive_message_text(value: str) -> bool:
    normalized = _normalized_sensitive_text(value)
    return any(term in normalized for term in _SENSITIVE_MESSAGE_TERMS)


def _normalized_sensitive_text(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _validate_instance(value: object, expected_type: type[object], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be {expected_type.__name__}")


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
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


def _validate_required_page_limit(value: object, field_name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    if value > DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_MAX:
        raise ValueError(
            f"{field_name} must not exceed {DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_MAX}"
        )


def _validate_optional_page_limit(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_required_page_limit(value, field_name)


def _validate_timestamp_range(
    start: int | None,
    end: int | None,
    start_field: str,
    end_field: str,
) -> None:
    _validate_optional_non_negative_int(start, start_field)
    _validate_optional_non_negative_int(end, end_field)
    if start is not None and end is not None and start > end:
        raise ValueError(f"{start_field} must not be greater than {end_field}")


def _validate_decimal_like(value: object, field_name: str) -> None:
    if type(value) is bool:
        raise TypeError(f"{field_name} must be a decimal-like value")
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite")
        return
    if isinstance(value, str) and value.strip():
        return
    raise ValueError(f"{field_name} must be a decimal-like value")


def _validate_relative_path(value: object, field_name: str) -> None:
    _validate_non_empty_string(value, field_name)
    path = value.strip()  # type: ignore[union-attr]
    if "\\" in path:
        raise ValueError(f"{field_name} must use POSIX-style relative paths")
    if path.startswith("/"):
        raise ValueError(f"{field_name} must be relative")
    parts = path.split("/")
    if not parts or any(part in {"", "."} for part in parts):
        raise ValueError(f"{field_name} must be a normalized relative path")
    if ".." in parts:
        raise ValueError(f"{field_name} must not contain parent segments")
    if ":" in parts[0]:
        raise ValueError(f"{field_name} must not be an absolute path")


def _aggregate_downloaded_bars(
    progress_events: tuple[object, ...],
    explicit_total: int,
) -> int:
    if not progress_events:
        return explicit_total
    return max(
        explicit_total,
        max(
            event.downloaded_bars
            for event in progress_events
            if isinstance(event, DownloadDataExecutionProgressEvent)
        ),
    )


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


__all__ = [
    "DOWNLOAD_DATA_EXECUTION_MESSAGE_MAX_LENGTH",
    "DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_DEFAULT",
    "DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_MAX",
    "DownloadDataCandleSortOrder",
    "DownloadDataExecutionCommand",
    "DownloadDataExecutionDirection",
    "DownloadDataExecutionError",
    "DownloadDataExecutionMode",
    "DownloadDataExecutionPlan",
    "DownloadDataExecutionProgressEvent",
    "DownloadDataExecutionResult",
    "DownloadDataExecutionStatus",
    "DownloadDataExecutionTarget",
    "DownloadDataNormalizedCandle",
    "DownloadDataProviderPageRequest",
    "DownloadDataProviderPageResult",
    "DownloadDataProviderResultStatus",
    "DownloadDataStorageWriteRequest",
    "DownloadDataStorageWriteResult",
    "DownloadDataStorageWriteStatus",
]
