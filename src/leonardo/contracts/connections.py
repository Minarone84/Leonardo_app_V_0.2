"""Connection runtime contracts for Leonardo V2 Core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from uuid import uuid4


class ConnectionProtocol(str, Enum):
    """Protocol family used to describe a tracked connection identity."""

    WEBSOCKET = "websocket"
    HTTP = "http"
    TCP = "tcp"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ConnectionKind(str, Enum):
    """Core-visible category for a tracked connection identity."""

    MARKET_DATA = "market_data"
    INTERNAL_SERVICE = "internal_service"
    EXTERNAL_SERVICE = "external_service"
    DIAGNOSTIC = "diagnostic"
    UNKNOWN = "unknown"


class ConnectionLifecycleStatus(str, Enum):
    """Lifecycle status for a tracked connection identity."""

    REGISTERED = "registered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECT_REQUESTED = "disconnect_requested"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        """Return whether this status represents terminal connection history."""

        return self in {
            ConnectionLifecycleStatus.DISCONNECTED,
            ConnectionLifecycleStatus.FAILED,
        }


class ConnectionDirection(str, Enum):
    """Direction assigned to a tracked connection identity."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConnectionEndpoint:
    """
    Descriptive endpoint identity for a tracked connection.

    Endpoint values are labels and address descriptors only. The contract does
    not carry client handles, open streams, or runtime callbacks.
    """

    label: str
    protocol: ConnectionProtocol
    host: str | None = None
    port: int | None = None
    path: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.protocol, ConnectionProtocol):
            raise TypeError("protocol must be a ConnectionProtocol")
        _validate_optional_string(self.host, "host")
        _validate_optional_string(self.path, "path")
        if self.port is not None and (
            type(self.port) is not int or self.port < 1 or self.port > 65535
        ):
            raise ValueError("port must be an integer from 1 through 65535 or None")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ConnectionDefinition:
    """Stable definition for a connection tracked by Core observability."""

    connection_id: str
    label: str
    kind: ConnectionKind
    protocol: ConnectionProtocol
    direction: ConnectionDirection
    endpoint: ConnectionEndpoint | None = None
    service_id: str | None = None
    process_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.connection_id, "connection_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.kind, ConnectionKind):
            raise TypeError("kind must be a ConnectionKind")
        if not isinstance(self.protocol, ConnectionProtocol):
            raise TypeError("protocol must be a ConnectionProtocol")
        if not isinstance(self.direction, ConnectionDirection):
            raise TypeError("direction must be a ConnectionDirection")
        if self.endpoint is not None:
            if not isinstance(self.endpoint, ConnectionEndpoint):
                raise TypeError("endpoint must be a ConnectionEndpoint or None")
            if self.endpoint.protocol is not self.protocol:
                raise ValueError("endpoint protocol must match connection protocol")
        _validate_optional_string(self.service_id, "service_id")
        _validate_optional_string(self.process_id, "process_id")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ConnectionRuntimeState:
    """
    Current or last-known runtime state for a tracked connection.

    Connection definitions are long-lived. Terminal connection states remain in
    the current runtime snapshot as last-known state until a future owner
    explicitly removes or replaces the definition.
    """

    connection_id: str
    label: str
    kind: ConnectionKind
    protocol: ConnectionProtocol
    direction: ConnectionDirection
    status: ConnectionLifecycleStatus
    registered_at_utc: datetime
    updated_at_utc: datetime
    connected_at_utc: datetime | None = None
    disconnected_at_utc: datetime | None = None
    last_heartbeat_at_utc: datetime | None = None
    last_error_message: str | None = None
    service_id: str | None = None
    process_id: str | None = None
    operation_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.connection_id, "connection_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.kind, ConnectionKind):
            raise TypeError("kind must be a ConnectionKind")
        if not isinstance(self.protocol, ConnectionProtocol):
            raise TypeError("protocol must be a ConnectionProtocol")
        if not isinstance(self.direction, ConnectionDirection):
            raise TypeError("direction must be a ConnectionDirection")
        if not isinstance(self.status, ConnectionLifecycleStatus):
            raise TypeError("status must be a ConnectionLifecycleStatus")
        object.__setattr__(
            self,
            "registered_at_utc",
            _coerce_utc(self.registered_at_utc, "registered_at_utc"),
        )
        object.__setattr__(
            self,
            "updated_at_utc",
            _coerce_utc(self.updated_at_utc, "updated_at_utc"),
        )
        for field_name in (
            "connected_at_utc",
            "disconnected_at_utc",
            "last_heartbeat_at_utc",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _coerce_utc(value, field_name))
        for field_name in (
            "last_error_message",
            "service_id",
            "process_id",
            "operation_id",
            "task_id",
            "correlation_id",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class WebSocketChannelDefinition:
    """Stable definition for a WebSocket channel tracked under a connection."""

    channel_id: str
    connection_id: str
    label: str
    topic: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.channel_id, "channel_id")
        _validate_non_empty_string(self.connection_id, "connection_id")
        _validate_non_empty_string(self.label, "label")
        _validate_optional_string(self.topic, "topic")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class WebSocketChannelRuntimeState:
    """Current or last-known runtime state for a tracked WebSocket channel."""

    channel_id: str
    connection_id: str
    label: str
    status: ConnectionLifecycleStatus
    registered_at_utc: datetime
    updated_at_utc: datetime
    last_message_at_utc: datetime | None = None
    received_count: int = 0
    sent_count: int = 0
    error_count: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.channel_id, "channel_id")
        _validate_non_empty_string(self.connection_id, "connection_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.status, ConnectionLifecycleStatus):
            raise TypeError("status must be a ConnectionLifecycleStatus")
        object.__setattr__(
            self,
            "registered_at_utc",
            _coerce_utc(self.registered_at_utc, "registered_at_utc"),
        )
        object.__setattr__(
            self,
            "updated_at_utc",
            _coerce_utc(self.updated_at_utc, "updated_at_utc"),
        )
        if self.last_message_at_utc is not None:
            object.__setattr__(
                self,
                "last_message_at_utc",
                _coerce_utc(self.last_message_at_utc, "last_message_at_utc"),
            )
        for field_name in ("received_count", "sent_count", "error_count"):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ConnectionEventRecord:
    """Structured record describing one tracked connection event."""

    event_type: str
    connection_id: str
    status: ConnectionLifecycleStatus
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str = field(default_factory=lambda: uuid4().hex)
    channel_id: str | None = None
    message: str = ""
    correlation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.event_type, "event_type")
        _validate_non_empty_string(self.connection_id, "connection_id")
        if not isinstance(self.status, ConnectionLifecycleStatus):
            raise TypeError("status must be a ConnectionLifecycleStatus")
        object.__setattr__(
            self,
            "timestamp_utc",
            _coerce_utc(self.timestamp_utc, "timestamp_utc"),
        )
        _validate_non_empty_string(self.event_id, "event_id")
        _validate_optional_string(self.channel_id, "channel_id")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        _validate_optional_string(self.correlation_id, "correlation_id")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        normalized[key] = item
    return MappingProxyType(normalized)


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
