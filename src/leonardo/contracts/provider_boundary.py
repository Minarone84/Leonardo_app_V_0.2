"""Provider boundary descriptor contracts for Leonardo V2.

The contracts in this module define static provider, capability, session,
subscription, and message-trace vocabulary. They are immutable descriptor and
read-model shapes only. They do not register providers, inspect modules,
construct transports, execute subscriptions, mutate runtime state, or implement
provider-specific behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from types import MappingProxyType

from leonardo.contracts.identity import Permission


class ProviderKind(str, Enum):
    """Canonical category for a provider descriptor."""

    EXCHANGE = "exchange"
    BROKER = "broker"
    FILE_SOURCE = "file_source"
    MOCK = "mock"
    LOCAL = "local"
    SERVICE = "service"


class ProviderLifecycleStatus(str, Enum):
    """Lifecycle state for static provider descriptors."""

    PLANNED = "planned"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


class ProviderCapabilityKind(str, Enum):
    """Canonical category for provider capability descriptors."""

    HISTORICAL_DATA = "historical_data"
    LIVE_STREAM = "live_stream"
    ACCOUNT_READ = "account_read"
    ORDER_SUBMIT = "order_submit"
    FILE_READ = "file_read"
    DATA_IMPORT = "data_import"
    WEBSOCKET_SUBSCRIBE = "websocket_subscribe"
    METADATA = "metadata"


class ProviderSessionStatus(str, Enum):
    """Safe lifecycle summary for provider session descriptors."""

    PLANNED = "planned"
    PREPARED = "prepared"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    CLOSED = "closed"


class ProviderConnectionKind(str, Enum):
    """Connection category declared by provider boundary descriptors."""

    REST = "rest"
    WEBSOCKET = "websocket"
    FILE = "file"
    LOCAL = "local"
    MOCK = "mock"


class ProviderSubscriptionStatus(str, Enum):
    """Safe lifecycle summary for provider subscription descriptors."""

    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    DEGRADED = "degraded"
    FAILED = "failed"
    CLOSED = "closed"


class ProviderMessageTraceKind(str, Enum):
    """Bounded message metadata category."""

    METADATA = "metadata"
    HEARTBEAT = "heartbeat"
    DATA = "data"
    ERROR = "error"
    CONTROL = "control"


class ProviderMessageDirection(str, Enum):
    """Direction for bounded provider message trace metadata."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ProviderAuditPolicy(str, Enum):
    """Audit expectation declared by provider boundary descriptors."""

    NONE = "none"
    SUMMARY = "summary"
    REQUIRED = "required"
    DENIED_ONLY = "denied_only"


class ProviderAuthenticationMode(str, Enum):
    """Safe authentication-mode summary without credential material."""

    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    TOKEN = "token"
    SESSION = "session"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderDescriptor:
    """
    Static descriptor for an external or internal capability source.

    The descriptor identifies provider identity and declared capability scope.
    It has no registration side effects and carries no runtime handles.
    """

    provider_id: str
    display_name: str
    description: str
    provider_kind: ProviderKind | str
    owner_domain: str
    owner_component: str
    lifecycle_status: ProviderLifecycleStatus | str = ProviderLifecycleStatus.PLANNED
    version: str = "1.0"
    supported_capability_ids: tuple[str, ...] = ()
    supported_connection_kinds: tuple[ProviderConnectionKind | str, ...] = ()
    supports_websocket: bool = False
    supports_polling: bool = False
    supports_batch: bool = False
    required_permissions: tuple[Permission | str, ...] = ()
    object_family_ids: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    metadata_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "provider_id",
            "display_name",
            "description",
            "owner_domain",
            "owner_component",
            "version",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "provider_kind",
            _coerce_enum(self.provider_kind, ProviderKind, "provider_kind"),
        )
        object.__setattr__(
            self,
            "lifecycle_status",
            _coerce_enum(
                self.lifecycle_status,
                ProviderLifecycleStatus,
                "lifecycle_status",
            ),
        )
        object.__setattr__(
            self,
            "supported_connection_kinds",
            _normalize_enum_value_tuple(
                self.supported_connection_kinds,
                ProviderConnectionKind,
                "supported_connection_kinds",
            ),
        )
        _normalize_provider_descriptor_sequences(self)
        for field_name in (
            "supports_websocket",
            "supports_polling",
            "supports_batch",
        ):
            _validate_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ProviderCapabilityDescriptor:
    """
    Static descriptor for one provider capability.

    Capabilities describe what can be requested from a provider boundary. They
    do not identify adapter classes, construct runtime handles, or execute work.
    """

    capability_id: str
    provider_id: str
    capability_kind: ProviderCapabilityKind | str
    label: str
    description: str
    required_permission: Permission | str
    connection_required: bool = False
    websocket_required: bool = False
    supports_streaming: bool = False
    supports_batch: bool = False
    input_schema_ref: str | None = None
    result_schema_ref: str | None = None
    rate_limit_ref: str | None = None
    audit_category: str = "provider"
    audit_policy: ProviderAuditPolicy | str = ProviderAuditPolicy.SUMMARY
    object_family_ids: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "capability_id",
            "provider_id",
            "label",
            "description",
            "audit_category",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "capability_kind",
            _coerce_enum(
                self.capability_kind,
                ProviderCapabilityKind,
                "capability_kind",
            ),
        )
        object.__setattr__(
            self,
            "required_permission",
            _normalize_permission_ref(self.required_permission, "required_permission"),
        )
        object.__setattr__(
            self,
            "audit_policy",
            _coerce_enum(self.audit_policy, ProviderAuditPolicy, "audit_policy"),
        )
        for field_name in (
            "connection_required",
            "websocket_required",
            "supports_streaming",
            "supports_batch",
        ):
            _validate_bool(getattr(self, field_name), field_name)
        for field_name in ("input_schema_ref", "result_schema_ref", "rate_limit_ref"):
            _validate_optional_string(getattr(self, field_name), field_name)
        _normalize_descriptor_sequences(self)


@dataclass(frozen=True)
class ProviderSessionDescriptor:
    """
    Safe read-model descriptor for provider session metadata.

    The descriptor may reference provider, connection, actor, and active
    capability identifiers. It stores only bounded metadata and no runtime
    execution handles.
    """

    provider_session_id: str
    provider_id: str
    connection_id: str | None = None
    actor_id: str | None = None
    session_id: str | None = None
    status: ProviderSessionStatus | str = ProviderSessionStatus.PLANNED
    authentication_mode: ProviderAuthenticationMode | str = ProviderAuthenticationMode.NONE
    started_at: str | None = None
    last_heartbeat_at: str | None = None
    active_capability_ids: tuple[str, ...] = ()
    warning_count: int = 0
    error_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("provider_session_id", "provider_id"):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "connection_id",
            "actor_id",
            "session_id",
            "started_at",
            "last_heartbeat_at",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProviderSessionStatus, "status"),
        )
        object.__setattr__(
            self,
            "authentication_mode",
            _coerce_enum(
                self.authentication_mode,
                ProviderAuthenticationMode,
                "authentication_mode",
            ),
        )
        for field_name in ("warning_count", "error_count"):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        for field_name in (
            "active_capability_ids",
            "warnings",
            "errors",
            "docs_refs",
            "test_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_safe_metadata(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class ProviderSubscriptionDescriptor:
    """
    Static subscription intent or binding descriptor.

    The descriptor records subscription identity and references. It does not
    subscribe, unsubscribe, reconnect, or store message content.
    """

    subscription_id: str
    provider_id: str
    provider_session_id: str | None = None
    capability_id: str | None = None
    connection_id: str | None = None
    websocket_channel_id: str | None = None
    topic: str | None = None
    subscription_kind: ProviderCapabilityKind | str = (
        ProviderCapabilityKind.WEBSOCKET_SUBSCRIBE
    )
    status: ProviderSubscriptionStatus | str = ProviderSubscriptionStatus.PLANNED
    created_at: str | None = None
    updated_at: str | None = None
    last_message_at: str | None = None
    message_count: int = 0
    error_count: int = 0
    required_permission: Permission | str | None = None
    object_family_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("subscription_id", "provider_id"):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "provider_session_id",
            "capability_id",
            "connection_id",
            "websocket_channel_id",
            "topic",
            "created_at",
            "updated_at",
            "last_message_at",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "subscription_kind",
            _coerce_enum(
                self.subscription_kind,
                ProviderCapabilityKind,
                "subscription_kind",
            ),
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProviderSubscriptionStatus, "status"),
        )
        for field_name in ("message_count", "error_count"):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if self.required_permission is not None:
            object.__setattr__(
                self,
                "required_permission",
                _normalize_permission_ref(
                    self.required_permission,
                    "required_permission",
                ),
            )
        _normalize_descriptor_sequences(self)


@dataclass(frozen=True)
class ProviderMessageTraceDescriptor:
    """
    Bounded metadata descriptor for one observed provider message.

    The descriptor records only safe message metadata such as kind, direction,
    size, and key names. It does not contain raw message values.
    """

    message_trace_id: str
    provider_id: str
    provider_session_id: str | None = None
    subscription_id: str | None = None
    connection_id: str | None = None
    websocket_channel_id: str | None = None
    direction: ProviderMessageDirection | str = ProviderMessageDirection.UNKNOWN
    message_kind: ProviderMessageTraceKind | str = ProviderMessageTraceKind.METADATA
    observed_at: str | None = None
    payload_kind: str | None = None
    payload_size_bytes: int | None = None
    payload_key_count: int | None = None
    payload_keys: tuple[str, ...] = ()
    correlation_id: str | None = None
    warning_count: int = 0
    error_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("message_trace_id", "provider_id"):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "provider_session_id",
            "subscription_id",
            "connection_id",
            "websocket_channel_id",
            "observed_at",
            "payload_kind",
            "correlation_id",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "direction",
            _coerce_enum(self.direction, ProviderMessageDirection, "direction"),
        )
        object.__setattr__(
            self,
            "message_kind",
            _coerce_enum(
                self.message_kind,
                ProviderMessageTraceKind,
                "message_kind",
            ),
        )
        for field_name in (
            "payload_size_bytes",
            "payload_key_count",
            "warning_count",
            "error_count",
        ):
            _validate_optional_non_negative_int(getattr(self, field_name), field_name)
        for field_name in (
            "payload_keys",
            "warnings",
            "errors",
            "docs_refs",
            "test_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )


def _normalize_provider_descriptor_sequences(value: ProviderDescriptor) -> None:
    object.__setattr__(
        value,
        "required_permissions",
        _normalize_permission_tuple(value.required_permissions, "required_permissions"),
    )
    for field_name in (
        "supported_capability_ids",
        "object_family_ids",
        "docs_refs",
        "test_refs",
        "metadata_refs",
        "warnings",
        "blockers",
    ):
        object.__setattr__(
            value,
            field_name,
            _normalize_string_tuple(getattr(value, field_name), field_name),
        )


def _normalize_descriptor_sequences(value: object) -> None:
    for field_name in (
        "object_family_ids",
        "docs_refs",
        "test_refs",
        "warnings",
        "blockers",
        "errors",
    ):
        if not hasattr(value, field_name):
            continue
        object.__setattr__(
            value,
            field_name,
            _normalize_string_tuple(getattr(value, field_name), field_name),
        )


def _normalize_permission_tuple(
    values: tuple[Permission | str, ...],
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of permissions")
    return tuple(_normalize_permission_ref(value, f"{field_name} entry") for value in values)


def _normalize_permission_ref(value: Permission | str, field_name: str) -> str:
    if isinstance(value, Permission):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty permission string")
    if value.startswith("suite" + ":"):
        raise ValueError(
            f"{field_name} must use an established area permission namespace"
        )
    return value.strip()


def _normalize_enum_value_tuple(
    values: tuple[Enum | str, ...],
    enum_type: type[Enum],
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple")
    return tuple(
        str(_coerce_enum(value, enum_type, f"{field_name} entry").value)
        for value in tuple(values)
    )


def _normalize_string_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    normalized = tuple(values)
    for item in normalized:
        _validate_non_empty_string(item, f"{field_name} entry")
    return normalized


def _coerce_enum(
    value: object,
    enum_type: type[Enum],
    field_name: str,
) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as error:
            allowed = ", ".join(item.value for item in enum_type)
            raise ValueError(f"{field_name} must be one of: {allowed}") from error
    raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _readonly_safe_metadata(
    value: Mapping[str, object],
    field_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        _validate_safe_metadata_key(key, f"{field_name} key")
        normalized[key] = _readonly_safe_value(item, f"{field_name}.{key}")
    return MappingProxyType(normalized)


def _readonly_safe_value(value: object, field_name: str) -> object:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        return _readonly_safe_metadata(value, field_name)
    if isinstance(value, tuple | list):
        return tuple(
            _readonly_safe_value(item, f"{field_name} entry") for item in value
        )
    raise TypeError(f"{field_name} must contain JSON-like metadata values")


def _validate_safe_metadata_key(value: str, field_name: str) -> None:
    normalized = value.strip().lower()
    for sensitive in _SENSITIVE_METADATA_KEY_PARTS:
        if sensitive in normalized:
            raise ValueError(f"{field_name} contains sensitive provider metadata")


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


_SENSITIVE_METADATA_KEY_PARTS = (
    "credential",
    "token",
    "secret",
    "password",
    "api_key",
    "client",
    "socket",
    "payload",
)


__all__ = [
    "ProviderAuditPolicy",
    "ProviderAuthenticationMode",
    "ProviderCapabilityDescriptor",
    "ProviderCapabilityKind",
    "ProviderConnectionKind",
    "ProviderDescriptor",
    "ProviderKind",
    "ProviderLifecycleStatus",
    "ProviderMessageDirection",
    "ProviderMessageTraceDescriptor",
    "ProviderMessageTraceKind",
    "ProviderSessionDescriptor",
    "ProviderSessionStatus",
    "ProviderSubscriptionDescriptor",
    "ProviderSubscriptionStatus",
]
