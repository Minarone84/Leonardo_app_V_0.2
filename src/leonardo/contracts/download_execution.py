"""Download execution planning and read-model contracts.

This module defines pure data contracts for future Download Data execution
orchestration. The contracts describe planning, layered preflight, progress,
outputs, errors, and snapshots. They do not execute downloads, call adapters,
open network connections, supervise tasks, launch processes, write files, or
import Core or GUI modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType


class DownloadExecutionPhase(str, Enum):
    """Lifecycle phase for future download execution read models."""

    PLANNED = "planned"
    PREFLIGHTING = "preflighting"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIALLY_COMPLETED = "partially_completed"
    BLOCKED = "blocked"


class DownloadExecutionErrorCategory(str, Enum):
    """Structured error category for future download execution outcomes."""

    VALIDATION = "validation"
    CAPABILITY = "capability"
    CONNECTION_UNAVAILABLE = "connection_unavailable"
    RATE_LIMITED = "rate_limited"
    PROVIDER = "provider"
    STORAGE = "storage"
    CANCELLATION = "cancellation"
    PARTIAL_COMPLETION = "partial_completion"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class DownloadPreflightLayer(str, Enum):
    """Layered preflight stage for future execution readiness checks."""

    STRUCTURAL = "structural"
    CAPABILITY = "capability"
    CONNECTION = "connection"
    STORAGE = "storage"
    CONFLICT_POLICY = "conflict_policy"
    EXECUTION_COST = "execution_cost"


class DownloadPreflightLayerStatus(str, Enum):
    """Outcome for one execution preflight layer."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DownloadExecutionPlan:
    """
    Future execution plan for one stored Download Manager request.

    The plan records orchestration identifiers and expected output refs. It does
    not own execution behavior, adapter handles, task creation, or storage
    writes.
    """

    plan_id: str
    request_id: str
    workflow_kind: str
    phase: DownloadExecutionPhase = DownloadExecutionPhase.PLANNED
    operation_id: str | None = None
    task_id: str | None = None
    connection_refs: tuple[str, ...] = ()
    adapter_ref: str | None = None
    storage_policy_ref: str | None = None
    dataset_refs: tuple[str, ...] = ()
    item_ids: tuple[str, ...] = ()
    created_at_utc: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.plan_id, "plan_id")
        _validate_non_empty_string(self.request_id, "request_id")
        _validate_non_empty_string(self.workflow_kind, "workflow_kind")
        _validate_execution_phase(self.phase)
        for field_name in (
            "operation_id",
            "task_id",
            "adapter_ref",
            "storage_policy_ref",
            "created_at_utc",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "connection_refs",
            _normalize_string_tuple(
                self.connection_refs,
                "connection_refs",
                allow_empty=True,
            ),
        )
        dataset_refs = _normalize_string_tuple(
            self.dataset_refs,
            "dataset_refs",
            allow_empty=True,
        )
        for dataset_ref in dataset_refs:
            _validate_dataset_ref(dataset_ref)
        object.__setattr__(self, "dataset_refs", dataset_refs)
        object.__setattr__(
            self,
            "item_ids",
            _normalize_string_tuple(self.item_ids, "item_ids", allow_empty=True),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadPreflightLayerResult:
    """Read model for one future execution preflight layer result."""

    layer: DownloadPreflightLayer
    status: DownloadPreflightLayerStatus
    can_continue: bool
    issues: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.layer, DownloadPreflightLayer):
            raise TypeError("layer must be a DownloadPreflightLayer")
        if not isinstance(self.status, DownloadPreflightLayerStatus):
            raise TypeError("status must be a DownloadPreflightLayerStatus")
        if type(self.can_continue) is not bool:
            raise TypeError("can_continue must be a bool")
        object.__setattr__(
            self,
            "issues",
            _normalize_string_tuple(self.issues, "issues", allow_empty=True),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadExecutionEstimate:
    """Estimated execution cost and size for one request."""

    request_id: str
    estimated_items: int | None = None
    estimated_rows: int | None = None
    estimated_candles: int | None = None
    estimated_pages: int | None = None
    estimated_bytes: int | None = None
    rate_limit_notes: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.request_id, "request_id")
        for field_name in (
            "estimated_items",
            "estimated_rows",
            "estimated_candles",
            "estimated_pages",
            "estimated_bytes",
        ):
            _validate_optional_non_negative_int(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "rate_limit_notes",
            _normalize_string_tuple(
                self.rate_limit_notes,
                "rate_limit_notes",
                allow_empty=True,
            ),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadExecutionProgress:
    """Request-level execution progress read model."""

    request_id: str
    phase: DownloadExecutionPhase
    total_items: int | None = None
    completed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    running_items: int = 0
    current_item_id: str | None = None
    current_symbol: str | None = None
    current_timeframe: str | None = None
    rows_downloaded: int | None = None
    candles_downloaded: int | None = None
    pages_fetched: int | None = None
    percent: float | None = None
    message: str = ""
    updated_at_utc: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.request_id, "request_id")
        _validate_execution_phase(self.phase)
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
        for field_name in (
            "current_item_id",
            "current_symbol",
            "current_timeframe",
            "updated_at_utc",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        for field_name in (
            "rows_downloaded",
            "candles_downloaded",
            "pages_fetched",
        ):
            _validate_optional_non_negative_int(getattr(self, field_name), field_name)
        if self.percent is not None:
            if type(self.percent) not in (float, int):
                raise TypeError("percent must be a number or None")
            if self.percent < 0 or self.percent > 100:
                raise ValueError("percent must be between 0 and 100")
            object.__setattr__(self, "percent", float(self.percent))
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadExecutionOutputRef:
    """
    Logical output reference produced by future execution.

    Relative paths are planning/read-model values only. They do not imply that
    this module creates directories or stores files.
    """

    request_id: str
    dataset_ref: str
    storage_format: str = "csv"
    validation_status: str = "unknown"
    quality_validation_status: str = "not_validated"
    item_id: str | None = None
    value_relative_path: str | None = None
    metadata_relative_path: str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.request_id, "request_id")
        _validate_dataset_ref(self.dataset_ref)
        _validate_non_empty_string(self.storage_format, "storage_format")
        _validate_non_empty_string(self.validation_status, "validation_status")
        _validate_non_empty_string(
            self.quality_validation_status,
            "quality_validation_status",
        )
        _validate_optional_string(self.item_id, "item_id")
        _validate_optional_relative_path(
            self.value_relative_path,
            "value_relative_path",
        )
        _validate_optional_relative_path(
            self.metadata_relative_path,
            "metadata_relative_path",
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadExecutionError:
    """Structured error read model for future execution failures."""

    category: DownloadExecutionErrorCategory
    message: str
    request_id: str | None = None
    item_id: str | None = None
    provider_code: str | None = None
    recoverable: bool = False
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.category, DownloadExecutionErrorCategory):
            raise TypeError("category must be a DownloadExecutionErrorCategory")
        _validate_non_empty_string(self.message, "message")
        for field_name in ("request_id", "item_id", "provider_code"):
            _validate_optional_string(getattr(self, field_name), field_name)
        if type(self.recoverable) is not bool:
            raise TypeError("recoverable must be a bool")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadExecutionSnapshot:
    """Aggregate immutable execution planning/read-model snapshot."""

    plan: DownloadExecutionPlan
    preflight_layers: tuple[DownloadPreflightLayerResult, ...] = ()
    estimate: DownloadExecutionEstimate | None = None
    progress: DownloadExecutionProgress | None = None
    outputs: tuple[DownloadExecutionOutputRef, ...] = ()
    errors: tuple[DownloadExecutionError, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, DownloadExecutionPlan):
            raise TypeError("plan must be a DownloadExecutionPlan")
        object.__setattr__(
            self,
            "preflight_layers",
            _normalize_tuple(
                self.preflight_layers,
                DownloadPreflightLayerResult,
                "preflight_layers",
            ),
        )
        if self.estimate is not None and not isinstance(
            self.estimate,
            DownloadExecutionEstimate,
        ):
            raise TypeError("estimate must be a DownloadExecutionEstimate or None")
        if self.progress is not None and not isinstance(
            self.progress,
            DownloadExecutionProgress,
        ):
            raise TypeError("progress must be a DownloadExecutionProgress or None")
        object.__setattr__(
            self,
            "outputs",
            _normalize_tuple(
                self.outputs,
                DownloadExecutionOutputRef,
                "outputs",
            ),
        )
        object.__setattr__(
            self,
            "errors",
            _normalize_tuple(self.errors, DownloadExecutionError, "errors"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


def is_terminal_execution_phase(phase: DownloadExecutionPhase | str) -> bool:
    """Return whether an execution phase represents a terminal outcome."""

    return _coerce_execution_phase(phase) in {
        DownloadExecutionPhase.COMPLETED,
        DownloadExecutionPhase.FAILED,
        DownloadExecutionPhase.CANCELLED,
        DownloadExecutionPhase.PARTIALLY_COMPLETED,
        DownloadExecutionPhase.BLOCKED,
    }


def is_running_execution_phase(phase: DownloadExecutionPhase | str) -> bool:
    """Return whether an execution phase represents active orchestration."""

    return _coerce_execution_phase(phase) in {
        DownloadExecutionPhase.PREFLIGHTING,
        DownloadExecutionPhase.READY,
        DownloadExecutionPhase.QUEUED,
        DownloadExecutionPhase.RUNNING,
        DownloadExecutionPhase.FINALIZING,
    }


def is_failed_execution_phase(phase: DownloadExecutionPhase | str) -> bool:
    """Return whether an execution phase represents a failed or blocked state."""

    return _coerce_execution_phase(phase) in {
        DownloadExecutionPhase.FAILED,
        DownloadExecutionPhase.BLOCKED,
    }


def default_execution_progress(
    request_id: str,
    phase: DownloadExecutionPhase = DownloadExecutionPhase.PLANNED,
) -> DownloadExecutionProgress:
    """Return an empty request-level execution progress read model."""

    return DownloadExecutionProgress(request_id=request_id, phase=phase)


def _validate_execution_phase(phase: DownloadExecutionPhase) -> None:
    if not isinstance(phase, DownloadExecutionPhase):
        raise TypeError("phase must be a DownloadExecutionPhase")


def _coerce_execution_phase(phase: DownloadExecutionPhase | str) -> DownloadExecutionPhase:
    if isinstance(phase, DownloadExecutionPhase):
        return phase
    if isinstance(phase, str):
        try:
            return DownloadExecutionPhase(phase)
        except ValueError as error:
            raise ValueError(f"Unknown download execution phase: {phase}") from error
    raise TypeError("phase must be a DownloadExecutionPhase or string")


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


def _validate_dataset_ref(value: str) -> None:
    _validate_non_empty_string(value, "dataset_ref")
    if not value.startswith("dataset://"):
        raise ValueError("dataset_ref must start with dataset://")


def _validate_optional_relative_path(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)
    if "\\" in value:
        raise ValueError(f"{field_name} must use POSIX-style relative paths")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"{field_name} must not be an absolute path")
    if ".." in path.as_posix():
        raise ValueError(f"{field_name} must not contain parent segments")


def _validate_non_negative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_optional_non_negative_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_negative_int(value, field_name)
