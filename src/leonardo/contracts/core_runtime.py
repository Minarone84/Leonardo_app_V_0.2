"""Core runtime bridge contracts for command, result, and progress flow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType


class CoreRuntimeResultStatus(str, Enum):
    """Terminal status for a Core runtime command task."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CoreRuntimeMetadata:
    """
    Shared runtime identity metadata for Core bridge contracts.

    The metadata is intentionally domain-neutral. It carries stable identity
    references that let GUI-facing intent, Core tasks, operations, audit events,
    permissions, and future result delivery remain traceable without making the
    bridge own domain behavior.
    """

    schema_version: str = "1.0"
    operation_id: str | None = None
    task_id: str | None = None
    action_id: str | None = None
    window_id: str | None = None
    actor_id: str | None = None
    session_id: str | None = None
    permission: str | None = None
    required_permission: str | None = None
    denied_reason: str | None = None
    domain: str | None = None
    suite: str | None = None
    source: str | None = None
    correlation_id: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.schema_version, "schema_version")
        for field_name in (
            "operation_id",
            "task_id",
            "action_id",
            "window_id",
            "actor_id",
            "session_id",
            "permission",
            "required_permission",
            "denied_reason",
            "domain",
            "suite",
            "source",
            "correlation_id",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "extra", _readonly_mapping(self.extra))

    def with_task_id(self, task_id: str) -> CoreRuntimeMetadata:
        """Return metadata with a Core task identifier attached."""

        _validate_non_empty_string(task_id, "task_id")
        return replace(self, task_id=task_id)

    def with_operation_id(self, operation_id: str) -> CoreRuntimeMetadata:
        """Return metadata with a semantic operation identifier attached."""

        _validate_non_empty_string(operation_id, "operation_id")
        return replace(self, operation_id=operation_id)

    def with_denial(
        self,
        *,
        required_permission: str,
        denied_reason: str,
    ) -> CoreRuntimeMetadata:
        """Return metadata with authorization denial details attached."""

        _validate_non_empty_string(required_permission, "required_permission")
        _validate_non_empty_string(denied_reason, "denied_reason")
        return replace(
            self,
            required_permission=required_permission,
            denied_reason=denied_reason,
        )


@dataclass(frozen=True)
class CoreRuntimeCommand:
    """Domain-neutral command envelope submitted through the Core bridge."""

    command_id: str
    command_type: str
    metadata: CoreRuntimeMetadata = field(default_factory=CoreRuntimeMetadata)
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.command_id, "command_id")
        _validate_non_empty_string(self.command_type, "command_type")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")
        object.__setattr__(self, "payload", _readonly_mapping(self.payload))


@dataclass(frozen=True)
class CoreRuntimeQuery:
    """Domain-neutral query envelope for future read-only bridge requests."""

    query_id: str
    query_type: str
    metadata: CoreRuntimeMetadata = field(default_factory=CoreRuntimeMetadata)
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.query_id, "query_id")
        _validate_non_empty_string(self.query_type, "query_type")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")
        object.__setattr__(self, "payload", _readonly_mapping(self.payload))


@dataclass(frozen=True)
class CoreRuntimeProgress:
    """GUI-safe progress contract emitted by bridge-submitted work."""

    command_id: str
    task_id: str
    message: str
    metadata: CoreRuntimeMetadata
    current: int | None = None
    total: int | None = None
    percent: float | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.command_id, "command_id")
        _validate_non_empty_string(self.task_id, "task_id")
        _validate_non_empty_string(self.message, "message")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")
        _validate_optional_non_negative_int(self.current, "current")
        _validate_optional_non_negative_int(self.total, "total")
        if self.percent is not None:
            if type(self.percent) not in (float, int):
                raise TypeError("percent must be a number or None")
            if self.percent < 0 or self.percent > 100:
                raise ValueError("percent must be between 0 and 100")
            object.__setattr__(self, "percent", float(self.percent))
        object.__setattr__(self, "payload", _readonly_mapping(self.payload))


@dataclass(frozen=True)
class CoreRuntimeError:
    """Structured error contract for failed runtime command tasks."""

    error_type: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.error_type, "error_type")
        _validate_non_empty_string(self.message, "message")
        object.__setattr__(self, "details", _readonly_mapping(self.details))


@dataclass(frozen=True)
class CoreRuntimeResult:
    """GUI-safe terminal result for a bridge-submitted command task."""

    command_id: str
    task_id: str
    status: CoreRuntimeResultStatus
    metadata: CoreRuntimeMetadata
    payload: Mapping[str, object] = field(default_factory=dict)
    error: CoreRuntimeError | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.command_id, "command_id")
        _validate_non_empty_string(self.task_id, "task_id")
        if not isinstance(self.status, CoreRuntimeResultStatus):
            raise TypeError("status must be CoreRuntimeResultStatus")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")
        if self.error is not None and not isinstance(self.error, CoreRuntimeError):
            raise TypeError("error must be CoreRuntimeError or None")
        if self.status is CoreRuntimeResultStatus.FAILED and self.error is None:
            raise ValueError("failed results must include an error")
        object.__setattr__(self, "payload", _readonly_mapping(self.payload))


@dataclass(frozen=True)
class CoreRuntimeSubmission:
    """Accepted submission identity returned after TaskManager scheduling."""

    command_id: str
    task_id: str
    accepted: bool
    metadata: CoreRuntimeMetadata

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.command_id, "command_id")
        _validate_non_empty_string(self.task_id, "task_id")
        if type(self.accepted) is not bool:
            raise TypeError("accepted must be a bool")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")


@dataclass(frozen=True)
class CoreRuntimeCancellationRequest:
    """Request to route cancellation to a Core-supervised task."""

    task_id: str
    command_id: str | None = None
    reason: str = ""
    metadata: CoreRuntimeMetadata = field(default_factory=CoreRuntimeMetadata)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.task_id, "task_id")
        _validate_optional_string(self.command_id, "command_id")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")


@dataclass(frozen=True)
class CoreRuntimeCancellationResult:
    """Result of routing a cancellation request to TaskManager."""

    task_id: str
    requested: bool
    message: str
    metadata: CoreRuntimeMetadata

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.task_id, "task_id")
        if type(self.requested) is not bool:
            raise TypeError("requested must be a bool")
        _validate_non_empty_string(self.message, "message")
        if not isinstance(self.metadata, CoreRuntimeMetadata):
            raise TypeError("metadata must be CoreRuntimeMetadata")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _validate_optional_non_negative_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or None")


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("mapping fields must be mappings")
    for key in value:
        if not isinstance(key, str):
            raise TypeError("mapping keys must be strings")
    return MappingProxyType(dict(value))
