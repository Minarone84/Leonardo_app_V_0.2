"""Audit event contracts for the Leonardo V2 runtime foundation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from uuid import uuid4

from leonardo.contracts.identity import ActorOrigin


class AuditSeverity(str, Enum):
    """Severity assigned to an audit event."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditCategory(str, Enum):
    """High-level category assigned to an audit event."""

    LIFECYCLE = "lifecycle"
    STATE = "state"
    SESSION = "session"
    SERVICE = "service"
    ERROR = "error"
    CONTRACT = "contract"
    RUNTIME = "runtime"


@dataclass(frozen=True)
class AuditErrorPayload:
    """Structured error details attached to an audit event."""

    exception_type: str | None = None
    message: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _normalize_json_mapping(self.details))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping representation of the error payload."""

        return {
            "exception_type": self.exception_type,
            "message": self.message,
            "details": _plain_json_value(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AuditErrorPayload:
        """Build an error payload from a serialized mapping."""

        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")
        return cls(
            exception_type=_optional_string(data.get("exception_type")),
            message=_optional_string(data.get("message")),
            details=_mapping_or_empty(data.get("details")),
        )


@dataclass(frozen=True)
class AuditEvent:
    """
    Structured audit event emitted by Core services.

    Audit history is historical truth. Current runtime state belongs in the
    runtime state store and is represented separately.
    """

    event_type: str
    message: str
    severity: AuditSeverity
    category: AuditCategory
    event_id: str = field(default_factory=lambda: uuid4().hex)
    schema_version: str = "1.0"
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    actor_id: str | None = None
    session_id: str | None = None
    origin: ActorOrigin | None = None
    window_id: str | None = None
    action_id: str | None = None
    operation_id: str | None = None
    task_id: str | None = None
    process_id: str | None = None
    connection_id: str | None = None
    correlation_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    error: AuditErrorPayload | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        if not self.schema_version or not self.schema_version.strip():
            raise ValueError("schema_version must be a non-empty string")
        if not self.event_type or not self.event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        if not self.message or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if not isinstance(self.severity, AuditSeverity):
            raise TypeError("severity must be an AuditSeverity")
        if not isinstance(self.category, AuditCategory):
            raise TypeError("category must be an AuditCategory")
        if self.origin is not None and not isinstance(self.origin, ActorOrigin):
            raise TypeError("origin must be an ActorOrigin")
        if self.error is not None and not isinstance(self.error, AuditErrorPayload):
            raise TypeError("error must be an AuditErrorPayload")

        object.__setattr__(
            self,
            "timestamp_utc",
            _coerce_utc(self.timestamp_utc, "timestamp_utc"),
        )
        object.__setattr__(self, "payload", _normalize_json_mapping(self.payload))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping representation of the audit event."""

        return {
            "event_id": self.event_id,
            "schema_version": self.schema_version,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "severity": self.severity.value,
            "category": self.category.value,
            "event_type": self.event_type,
            "message": self.message,
            "actor_id": self.actor_id,
            "session_id": self.session_id,
            "origin": self.origin.value if self.origin is not None else None,
            "window_id": self.window_id,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "process_id": self.process_id,
            "connection_id": self.connection_id,
            "correlation_id": self.correlation_id,
            "payload": _plain_json_value(self.payload),
            "error": self.error.to_dict() if self.error is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AuditEvent:
        """Build an audit event from a serialized mapping."""

        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")

        error_data = data.get("error")
        if error_data is None:
            error = None
        elif isinstance(error_data, Mapping):
            error = AuditErrorPayload.from_dict(error_data)
        else:
            raise TypeError("error must be a mapping or None")

        origin_value = data.get("origin")
        return cls(
            event_id=_required_string(data, "event_id"),
            schema_version=_required_string(data, "schema_version"),
            timestamp_utc=_parse_utc_datetime(data.get("timestamp_utc")),
            severity=AuditSeverity(_required_string(data, "severity")),
            category=AuditCategory(_required_string(data, "category")),
            event_type=_required_string(data, "event_type"),
            message=_required_string(data, "message"),
            actor_id=_optional_string(data.get("actor_id")),
            session_id=_optional_string(data.get("session_id")),
            origin=ActorOrigin(origin_value) if origin_value is not None else None,
            window_id=_optional_string(data.get("window_id")),
            action_id=_optional_string(data.get("action_id")),
            operation_id=_optional_string(data.get("operation_id")),
            task_id=_optional_string(data.get("task_id")),
            process_id=_optional_string(data.get("process_id")),
            connection_id=_optional_string(data.get("connection_id")),
            correlation_id=_optional_string(data.get("correlation_id")),
            payload=_mapping_or_empty(data.get("payload")),
            error=error,
        )


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_utc_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp_utc must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _coerce_utc(parsed, "timestamp_utc")


def _normalize_json_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("JSON payloads must be mappings")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("JSON payload keys must be strings")
        normalized[key] = _normalize_json_value(item)
    return MappingProxyType(normalized)


def _normalize_json_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON float values must be finite")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _coerce_utc(value, "payload datetime").isoformat()
    if isinstance(value, Mapping):
        return _normalize_json_mapping(value)
    if isinstance(value, tuple | list):
        return tuple(_normalize_json_value(item) for item in value)
    raise TypeError(f"Unsupported JSON payload value type: {type(value).__name__}")


def _plain_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _coerce_utc(value, "payload datetime").isoformat()
    return value


def _required_string(data: Mapping[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional string fields must be strings or None")
    return value


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("serialized mapping field must be a mapping or None")
    return value
