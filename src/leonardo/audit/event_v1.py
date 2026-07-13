"""Versioned persisted audit-event schema."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

_JSON_SCALAR = str | int | float | bool | None


@dataclass(frozen=True)
class AuditEventV1:
    """Durable audit event written by current Leonardo and read by future versions."""

    event_type: str
    message: str
    severity: str = "info"
    category: str = "runtime"
    event_id: str = field(default_factory=lambda: uuid4().hex)
    schema_version: str = "1.0"
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    actor_id: str | None = None
    window_id: str | None = None
    action_id: str | None = None
    task_id: str | None = None
    process_id: str | None = None
    connection_id: str | None = None
    correlation_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "schema_version", "event_type", "message", "severity", "category"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.timestamp_utc, datetime):
            raise TypeError("timestamp_utc must be a datetime")
        if self.timestamp_utc.tzinfo is None:
            raise ValueError("timestamp_utc must be timezone-aware")
        object.__setattr__(self, "timestamp_utc", self.timestamp_utc.astimezone(UTC))
        object.__setattr__(self, "details", _normalize_mapping(self.details))

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "schema_version": self.schema_version,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "event_type": self.event_type,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "actor_id": self.actor_id,
            "window_id": self.window_id,
            "action_id": self.action_id,
            "task_id": self.task_id,
            "process_id": self.process_id,
            "connection_id": self.connection_id,
            "correlation_id": self.correlation_id,
            "details": _plain_value(self.details),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AuditEventV1":
        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")
        timestamp = data.get("timestamp_utc")
        if not isinstance(timestamp, str):
            raise TypeError("timestamp_utc must be an ISO-8601 string")
        details = data.get("details", {})
        if not isinstance(details, Mapping):
            raise TypeError("details must be a mapping")
        return cls(
            event_id=_required_text(data, "event_id"),
            schema_version=_required_text(data, "schema_version"),
            timestamp_utc=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            event_type=_required_text(data, "event_type"),
            severity=_required_text(data, "severity"),
            category=_required_text(data, "category"),
            message=_required_text(data, "message"),
            actor_id=_optional_text(data.get("actor_id")),
            window_id=_optional_text(data.get("window_id")),
            action_id=_optional_text(data.get("action_id")),
            task_id=_optional_text(data.get("task_id")),
            process_id=_optional_text(data.get("process_id")),
            connection_id=_optional_text(data.get("connection_id")),
            correlation_id=_optional_text(data.get("correlation_id")),
            details=details,
            error_type=_optional_text(data.get("error_type")),
            error_message=_optional_text(data.get("error_message")),
        )


def _required_text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional text fields must be strings or None")
    return value


def _normalize_mapping(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("details must be a mapping")
    return {str(key): _normalize_value(item) for key, item in value.items()}


def _normalize_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("audit detail floats must be finite")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("audit detail datetimes must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return _normalize_value(value.value)
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_normalize_value(item) for item in value)
    raise TypeError(f"Unsupported audit detail type: {type(value).__name__}")


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    return value
