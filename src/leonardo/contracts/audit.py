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


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


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
