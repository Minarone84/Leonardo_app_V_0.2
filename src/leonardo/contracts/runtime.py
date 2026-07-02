"""Runtime state contracts for the Leonardo V2 Core foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType

from leonardo.contracts.gui import ActionTriggerRecord, WindowRuntimeState
from leonardo.contracts.operations import OperationRuntimeState


class AppLifecycleStatus(str, Enum):
    """Lifecycle status for the Core application runtime."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class ServiceLifecycleStatus(str, Enum):
    """Lifecycle status for a registered runtime service."""

    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class TaskLifecycleStatus(str, Enum):
    """Lifecycle status for a Core-supervised async task."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AppRuntimeState:
    """Current runtime state for the Core application."""

    status: AppLifecycleStatus = AppLifecycleStatus.CREATED
    last_updated_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at_utc: datetime | None = None
    stopped_at_utc: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, AppLifecycleStatus):
            raise TypeError("status must be an AppLifecycleStatus")
        object.__setattr__(
            self,
            "last_updated_utc",
            _coerce_utc(self.last_updated_utc, "last_updated_utc"),
        )
        if self.started_at_utc is not None:
            object.__setattr__(
                self,
                "started_at_utc",
                _coerce_utc(self.started_at_utc, "started_at_utc"),
            )
        if self.stopped_at_utc is not None:
            object.__setattr__(
                self,
                "stopped_at_utc",
                _coerce_utc(self.stopped_at_utc, "stopped_at_utc"),
            )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ServiceRuntimeState:
    """Current runtime state for one registered service."""

    service_id: str
    status: ServiceLifecycleStatus = ServiceLifecycleStatus.REGISTERED
    last_updated_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    message: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.service_id or not self.service_id.strip():
            raise ValueError("service_id must be a non-empty string")
        if not isinstance(self.status, ServiceLifecycleStatus):
            raise TypeError("status must be a ServiceLifecycleStatus")
        object.__setattr__(
            self,
            "last_updated_utc",
            _coerce_utc(self.last_updated_utc, "last_updated_utc"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class TaskRuntimeState:
    """Current runtime state for one Core-supervised async task."""

    task_id: str
    task_name: str
    status: TaskLifecycleStatus
    started_at_utc: datetime
    updated_at_utc: datetime
    completed_at_utc: datetime | None = None
    operation_id: str | None = None
    service_id: str | None = None
    correlation_id: str | None = None
    error_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not self.task_name or not self.task_name.strip():
            raise ValueError("task_name must be a non-empty string")
        if not isinstance(self.status, TaskLifecycleStatus):
            raise TypeError("status must be a TaskLifecycleStatus")
        object.__setattr__(
            self,
            "started_at_utc",
            _coerce_utc(self.started_at_utc, "started_at_utc"),
        )
        object.__setattr__(
            self,
            "updated_at_utc",
            _coerce_utc(self.updated_at_utc, "updated_at_utc"),
        )
        if self.completed_at_utc is not None:
            object.__setattr__(
                self,
                "completed_at_utc",
                _coerce_utc(self.completed_at_utc, "completed_at_utc"),
            )
        _validate_optional_id(self.operation_id, "operation_id")
        _validate_optional_id(self.service_id, "service_id")
        _validate_optional_id(self.correlation_id, "correlation_id")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Immutable snapshot of current app, service, and task runtime state."""

    app_state: AppRuntimeState
    service_states: tuple[ServiceRuntimeState, ...]
    task_states: tuple[TaskRuntimeState, ...] = ()
    window_states: tuple[WindowRuntimeState, ...] = ()
    recent_action_triggers: tuple[ActionTriggerRecord, ...] = ()
    operation_states: tuple[OperationRuntimeState, ...] = ()
    captured_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.app_state, AppRuntimeState):
            raise TypeError("app_state must be an AppRuntimeState")
        object.__setattr__(self, "service_states", tuple(self.service_states))
        for service_state in self.service_states:
            if not isinstance(service_state, ServiceRuntimeState):
                raise TypeError("service_states entries must be ServiceRuntimeState")
        object.__setattr__(self, "task_states", tuple(self.task_states))
        for task_state in self.task_states:
            if not isinstance(task_state, TaskRuntimeState):
                raise TypeError("task_states entries must be TaskRuntimeState")
        object.__setattr__(self, "window_states", tuple(self.window_states))
        for window_state in self.window_states:
            if not isinstance(window_state, WindowRuntimeState):
                raise TypeError("window_states entries must be WindowRuntimeState")
        object.__setattr__(
            self,
            "recent_action_triggers",
            tuple(self.recent_action_triggers),
        )
        for trigger in self.recent_action_triggers:
            if not isinstance(trigger, ActionTriggerRecord):
                raise TypeError(
                    "recent_action_triggers entries must be ActionTriggerRecord"
                )
        object.__setattr__(self, "operation_states", tuple(self.operation_states))
        for operation_state in self.operation_states:
            if not isinstance(operation_state, OperationRuntimeState):
                raise TypeError(
                    "operation_states entries must be OperationRuntimeState"
                )
        object.__setattr__(
            self,
            "captured_at_utc",
            _coerce_utc(self.captured_at_utc, "captured_at_utc"),
        )


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _validate_optional_id(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
    return MappingProxyType(dict(value))
