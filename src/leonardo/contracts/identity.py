"""Identity contracts for the Leonardo V2 runtime foundation.

The identity contracts model runtime actor and session identity only. They do
not implement authentication providers, password handling, credential storage,
or external identity integration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType


class ActorOrigin(str, Enum):
    """Source category for a runtime actor."""

    DEVELOPMENT = "development"
    HUMAN = "human"
    SYSTEM = "system"


class UserRole(str, Enum):
    """Runtime role assigned to a user reference."""

    ADMINISTRATOR = "administrator"
    USER = "user"
    SYSTEM = "system"


class Permission(str, Enum):
    """Permission identifiers used by the initial user policy."""

    RUNTIME_VIEW = "runtime:view"
    RUNTIME_MANAGE = "runtime:manage"
    AUDIT_VIEW = "audit:view"
    SERVICE_MANAGE = "service:manage"
    ERROR_VIEW = "error:view"
    GUI_SETTINGS_MANAGE = "gui_settings:manage"


@dataclass(frozen=True)
class UserRef:
    """
    Stable runtime reference to a user or actor.

    The contract is intentionally identity-only. It contains no credentials and
    does not imply that authentication has occurred.
    """

    user_id: str
    username: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    roles: tuple[UserRole, ...] = ()
    permissions: tuple[Permission, ...] = ()
    is_active: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        if not self.username or not self.username.strip():
            raise ValueError("username must be a non-empty string")

        object.__setattr__(
            self,
            "roles",
            _normalize_enum_tuple(self.roles, UserRole, "roles"),
        )
        object.__setattr__(
            self,
            "permissions",
            _normalize_enum_tuple(self.permissions, Permission, "permissions"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    @property
    def display_name(self) -> str:
        """Return a stable human-readable display name for the user reference."""

        full_name = " ".join(
            part for part in (self.first_name.strip(), self.last_name.strip()) if part
        )
        return full_name or self.username


@dataclass(frozen=True)
class SessionContext:
    """
    Runtime session identity for Core operations.

    The session context identifies the current actor and origin. It does not
    represent authentication state or persistent user records.
    """

    session_id: str
    actor: UserRef
    origin: ActorOrigin
    started_at_utc: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id or not self.session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(self.actor, UserRef):
            raise TypeError("actor must be a UserRef")
        if not isinstance(self.origin, ActorOrigin):
            raise TypeError("origin must be an ActorOrigin")
        object.__setattr__(
            self,
            "started_at_utc",
            _coerce_utc(self.started_at_utc, "started_at_utc"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    @property
    def actor_id(self) -> str:
        """Return the actor identifier associated with this session."""

        return self.actor.user_id


def _normalize_enum_tuple(
    values: tuple[Enum, ...],
    enum_type: type[Enum],
    field_name: str,
) -> tuple[Enum, ...]:
    normalized: list[Enum] = []
    seen: set[Enum] = set()
    for value in values:
        if not isinstance(value, enum_type):
            raise TypeError(f"{field_name} entries must be {enum_type.__name__}")
        if value in seen:
            raise ValueError(f"Duplicate value in {field_name}: {value.value}")
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
    return MappingProxyType(dict(value))
