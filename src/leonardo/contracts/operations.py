"""Operation lifecycle contracts for semantic Core workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType

from leonardo.contracts.identity import ActorOrigin


class OperationLifecycleStatus(str, Enum):
    """Lifecycle status for a semantic operation."""

    REQUESTED = "requested"
    PREFLIGHT = "preflight"
    BLOCKED = "blocked"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Return whether this status represents terminal operation history."""

        return self in {
            OperationLifecycleStatus.BLOCKED,
            OperationLifecycleStatus.COMPLETED,
            OperationLifecycleStatus.FAILED,
            OperationLifecycleStatus.CANCELLED,
        }


class OperationKind(str, Enum):
    """Operation category for semantic workflow tracking."""

    USER_WORKFLOW = "user_workflow"
    SYSTEM_WORKFLOW = "system_workflow"
    SERVICE_WORKFLOW = "service_workflow"


@dataclass(frozen=True)
class OperationBlocker:
    """Structured blocker that prevents an operation from proceeding."""

    code: str
    message: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.code, "code")
        _validate_non_empty_string(self.message, "message")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class OperationWarning:
    """Structured warning recorded for an operation."""

    code: str
    message: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.code, "code")
        _validate_non_empty_string(self.message, "message")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class OperationRuntimeState:
    """Current runtime state for an active semantic operation."""

    operation_id: str
    operation_kind: OperationKind
    status: OperationLifecycleStatus
    label: str
    requested_at_utc: datetime
    updated_at_utc: datetime
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    actor_id: str | None = None
    session_id: str | None = None
    origin: ActorOrigin | None = None
    window_id: str | None = None
    action_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    blockers: tuple[OperationBlocker, ...] = ()
    warnings: tuple[OperationWarning, ...] = ()
    error_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.operation_id, "operation_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.operation_kind, OperationKind):
            raise TypeError("operation_kind must be an OperationKind")
        if not isinstance(self.status, OperationLifecycleStatus):
            raise TypeError("status must be an OperationLifecycleStatus")
        object.__setattr__(
            self,
            "requested_at_utc",
            _coerce_utc(self.requested_at_utc, "requested_at_utc"),
        )
        object.__setattr__(
            self,
            "updated_at_utc",
            _coerce_utc(self.updated_at_utc, "updated_at_utc"),
        )
        if self.started_at_utc is not None:
            object.__setattr__(
                self,
                "started_at_utc",
                _coerce_utc(self.started_at_utc, "started_at_utc"),
            )
        if self.completed_at_utc is not None:
            object.__setattr__(
                self,
                "completed_at_utc",
                _coerce_utc(self.completed_at_utc, "completed_at_utc"),
            )
        if self.origin is not None and not isinstance(self.origin, ActorOrigin):
            raise TypeError("origin must be an ActorOrigin")
        for field_name in (
            "actor_id",
            "session_id",
            "window_id",
            "action_id",
            "task_id",
            "correlation_id",
        ):
            _validate_optional_id(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "blockers",
            _normalize_tuple(self.blockers, OperationBlocker, "blockers"),
        )
        object.__setattr__(
            self,
            "warnings",
            _normalize_tuple(self.warnings, OperationWarning, "warnings"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    @property
    def is_terminal(self) -> bool:
        """Return whether this state represents a terminal operation outcome."""

        return self.status.is_terminal


@dataclass(frozen=True)
class OperationResult:
    """Terminal result for an operation lifecycle transition."""

    operation_id: str
    status: OperationLifecycleStatus
    completed_at_utc: datetime
    error_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.operation_id, "operation_id")
        if not isinstance(self.status, OperationLifecycleStatus):
            raise TypeError("status must be an OperationLifecycleStatus")
        if not self.status.is_terminal:
            raise ValueError("status must be terminal")
        object.__setattr__(
            self,
            "completed_at_utc",
            _coerce_utc(self.completed_at_utc, "completed_at_utc"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


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


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_id(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
    return MappingProxyType(dict(value))
