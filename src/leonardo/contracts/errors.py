"""Error reporting contracts for the Leonardo V2 Core foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from uuid import uuid4


class ErrorSeverity(str, Enum):
    """Severity assigned to an error report."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ErrorReport:
    """Structured report for an exception or explicit runtime error."""

    message: str
    severity: ErrorSeverity
    error_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    exception_type: str | None = None
    exception_message: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.error_id or not self.error_id.strip():
            raise ValueError("error_id must be a non-empty string")
        if not self.message or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if not isinstance(self.severity, ErrorSeverity):
            raise TypeError("severity must be an ErrorSeverity")
        object.__setattr__(
            self,
            "timestamp_utc",
            _coerce_utc(self.timestamp_utc, "timestamp_utc"),
        )
        object.__setattr__(self, "context", _readonly_mapping(self.context))


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("context must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise TypeError("context keys must be strings")
    return MappingProxyType(dict(value))
