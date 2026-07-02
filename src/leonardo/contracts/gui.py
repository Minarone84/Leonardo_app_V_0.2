"""GUI observability contracts without GUI framework dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType

from leonardo.contracts.identity import ActorOrigin, Permission


class WindowLifecycleStatus(str, Enum):
    """Lifecycle status for a runtime-visible window identity."""

    OPEN = "open"
    FOCUSED = "focused"
    CLOSE_REQUESTED = "close_requested"
    CLOSED = "closed"


class ActionKind(str, Enum):
    """Stable action kind for menu, button, command, or shortcut triggers."""

    MENU = "menu"
    BUTTON = "button"
    COMMAND = "command"
    SHORTCUT = "shortcut"


@dataclass(frozen=True)
class WindowDefinition:
    """Describe a registered GUI window identity without storing a widget."""

    window_id: str
    title: str
    window_type: str
    is_singleton: bool = True
    required_permissions: tuple[Permission, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.window_id, "window_id")
        _validate_non_empty_string(self.title, "title")
        _validate_non_empty_string(self.window_type, "window_type")
        object.__setattr__(
            self,
            "required_permissions",
            _normalize_permissions(self.required_permissions),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class WindowRuntimeState:
    """Current runtime state for an open or closing window identity."""

    window_id: str
    title: str
    window_type: str
    status: WindowLifecycleStatus
    opened_at_utc: datetime
    updated_at_utc: datetime
    last_focus_at_utc: datetime | None = None
    owner_action_id: str | None = None
    current_operation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.window_id, "window_id")
        _validate_non_empty_string(self.title, "title")
        _validate_non_empty_string(self.window_type, "window_type")
        if not isinstance(self.status, WindowLifecycleStatus):
            raise TypeError("status must be a WindowLifecycleStatus")
        object.__setattr__(
            self,
            "opened_at_utc",
            _coerce_utc(self.opened_at_utc, "opened_at_utc"),
        )
        object.__setattr__(
            self,
            "updated_at_utc",
            _coerce_utc(self.updated_at_utc, "updated_at_utc"),
        )
        if self.last_focus_at_utc is not None:
            object.__setattr__(
                self,
                "last_focus_at_utc",
                _coerce_utc(self.last_focus_at_utc, "last_focus_at_utc"),
            )
        _validate_optional_id(self.owner_action_id, "owner_action_id")
        _validate_optional_id(self.current_operation_id, "current_operation_id")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ActionDefinition:
    """Describe a stable GUI action identity without execution behavior."""

    action_id: str
    label: str
    kind: ActionKind
    window_id: str | None = None
    description: str = ""
    is_destructive: bool = False
    requires_confirmation: bool = False
    is_placeholder: bool = False
    required_permissions: tuple[Permission, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.action_id, "action_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.kind, ActionKind):
            raise TypeError("kind must be an ActionKind")
        _validate_optional_id(self.window_id, "window_id")
        object.__setattr__(
            self,
            "required_permissions",
            _normalize_permissions(self.required_permissions),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ActionTriggerRecord:
    """Record one observed action trigger without executing the action."""

    action_id: str
    triggered_at_utc: datetime
    window_id: str | None = None
    actor_id: str | None = None
    session_id: str | None = None
    origin: ActorOrigin | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.action_id, "action_id")
        object.__setattr__(
            self,
            "triggered_at_utc",
            _coerce_utc(self.triggered_at_utc, "triggered_at_utc"),
        )
        _validate_optional_id(self.window_id, "window_id")
        _validate_optional_id(self.actor_id, "actor_id")
        _validate_optional_id(self.session_id, "session_id")
        _validate_optional_id(self.correlation_id, "correlation_id")
        if self.origin is not None and not isinstance(self.origin, ActorOrigin):
            raise TypeError("origin must be an ActorOrigin")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _normalize_permissions(values: tuple[Permission, ...]) -> tuple[Permission, ...]:
    normalized: list[Permission] = []
    seen: set[Permission] = set()
    for value in values:
        if not isinstance(value, Permission):
            raise TypeError("required_permissions entries must be Permission")
        if value in seen:
            raise ValueError(f"Duplicate required permission: {value.value}")
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


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
