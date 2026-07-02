"""Process runtime contracts for Leonardo V2 Core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType


class ProcessLifecycleStatus(str, Enum):
    """Lifecycle status for a Core-supervised operating-system process."""

    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"
    FAILED = "failed"
    KILLED = "killed"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        """Return whether this status represents terminal process history."""

        return self in {
            ProcessLifecycleStatus.STOPPED,
            ProcessLifecycleStatus.FAILED,
            ProcessLifecycleStatus.KILLED,
        }


class ProcessKind(str, Enum):
    """Supported categories for Core-supervised process requests."""

    SYSTEM = "system"
    SERVICE = "service"
    UTILITY = "utility"


@dataclass(frozen=True)
class ProcessLaunchRequest:
    """
    Request explicit launch of one supervised process.

    Commands are represented as argument tokens. Shell command strings are not
    part of this contract.
    """

    process_id: str
    label: str
    command: tuple[str, ...]
    kind: ProcessKind
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    operation_id: str | None = None
    task_id: str | None = None
    service_id: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.process_id, "process_id")
        _validate_non_empty_string(self.label, "label")
        object.__setattr__(self, "command", _normalize_command(self.command))
        if not isinstance(self.kind, ProcessKind):
            raise TypeError("kind must be a ProcessKind")
        _validate_optional_string(self.cwd, "cwd")
        object.__setattr__(self, "env", _readonly_string_mapping(self.env, "env"))
        for field_name in (
            "operation_id",
            "task_id",
            "service_id",
            "correlation_id",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ProcessRuntimeState:
    """
    Current runtime state for one Core-supervised process.

    Active process state is current truth. Terminal facts are removed from the
    active state store and retained through audit history.
    """

    process_id: str
    label: str
    kind: ProcessKind
    status: ProcessLifecycleStatus
    command: tuple[str, ...]
    updated_at_utc: datetime
    pid: int | None = None
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    exit_code: int | None = None
    operation_id: str | None = None
    task_id: str | None = None
    service_id: str | None = None
    correlation_id: str | None = None
    error_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.process_id, "process_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.kind, ProcessKind):
            raise TypeError("kind must be a ProcessKind")
        if not isinstance(self.status, ProcessLifecycleStatus):
            raise TypeError("status must be a ProcessLifecycleStatus")
        object.__setattr__(self, "command", _normalize_command(self.command))
        object.__setattr__(
            self,
            "updated_at_utc",
            _coerce_utc(self.updated_at_utc, "updated_at_utc"),
        )
        if self.pid is not None and (type(self.pid) is not int or self.pid < 0):
            raise ValueError("pid must be a non-negative integer or None")
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
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an integer or None")
        for field_name in (
            "operation_id",
            "task_id",
            "service_id",
            "correlation_id",
            "error_message",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ProcessExitRecord:
    """Terminal result for a supervised process lifecycle."""

    process_id: str
    exit_code: int | None
    status: ProcessLifecycleStatus
    completed_at_utc: datetime
    error_message: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.process_id, "process_id")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an integer or None")
        if not isinstance(self.status, ProcessLifecycleStatus):
            raise TypeError("status must be a ProcessLifecycleStatus")
        if not self.status.is_terminal:
            raise ValueError("status must be terminal")
        object.__setattr__(
            self,
            "completed_at_utc",
            _coerce_utc(self.completed_at_utc, "completed_at_utc"),
        )
        _validate_optional_string(self.error_message, "error_message")


def _normalize_command(command: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(command, str):
        raise TypeError("command must be a tuple of argument tokens")
    normalized = tuple(command)
    if not normalized:
        raise ValueError("command must contain at least one argument token")
    for token in normalized:
        _validate_non_empty_string(token, "command token")
    return normalized


def _readonly_string_mapping(
    value: Mapping[str, str],
    field_name: str,
) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{field_name} keys must be non-empty strings")
        if not isinstance(item, str):
            raise TypeError(f"{field_name} values must be strings")
        normalized[key] = item
    return MappingProxyType(normalized)


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        normalized[key] = item
    return MappingProxyType(normalized)


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)
