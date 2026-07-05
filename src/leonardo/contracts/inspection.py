"""Runtime inspection read-model contracts for Leonardo V2 Core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType


class RuntimeHealthStatus(str, Enum):
    """Overall health derived from Runtime Manager section statuses."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class RuntimeSectionStatus(str, Enum):
    """Health status for one runtime inspection section."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class RuntimeSectionSummary:
    """
    Summarize one Runtime Manager backend section.

    Section summaries are read models. The count represents the number of
    currently visible runtime records in the section, while metadata carries
    bounded, serialization-friendly details needed by future presentation
    layers.
    """

    section_id: str
    status: RuntimeSectionStatus
    count: int = 0
    message: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.section_id, "section_id")
        if not isinstance(self.status, RuntimeSectionStatus):
            raise TypeError("status must be a RuntimeSectionStatus")
        if type(self.count) is not int or self.count < 0:
            raise ValueError("count must be a non-negative integer")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this section summary."""

        return {
            "section_id": self.section_id,
            "status": self.status.value,
            "count": self.count,
            "message": self.message,
            "metadata": _plain_value(self.metadata),
        }


@dataclass(frozen=True)
class AuditEventPreview:
    """Bounded, presentation-neutral preview of one retained audit event."""

    event_id: str
    timestamp_utc: datetime
    severity: str
    category: str
    event_type: str
    message: str
    actor_id: str | None = None
    session_id: str | None = None
    window_id: str | None = None
    action_id: str | None = None
    operation_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.event_id, "event_id")
        object.__setattr__(
            self,
            "timestamp_utc",
            _coerce_utc(self.timestamp_utc, "timestamp_utc"),
        )
        for field_name in ("severity", "category", "event_type", "message"):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "actor_id",
            "session_id",
            "window_id",
            "action_id",
            "operation_id",
            "task_id",
            "correlation_id",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this audit event preview."""

        return {
            "event_id": self.event_id,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "severity": self.severity,
            "category": self.category,
            "event_type": self.event_type,
            "message": self.message,
            "actor_id": self.actor_id,
            "session_id": self.session_id,
            "window_id": self.window_id,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class AuditSinkFailurePreview:
    """Bounded preview of one audit sink failure captured by AuditLog."""

    sink_name: str
    operation: str
    exception_type: str
    message: str
    event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("sink_name", "operation", "exception_type", "message"):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        _validate_optional_string(self.event_id, "event_id")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this sink failure preview."""

        return {
            "sink_name": self.sink_name,
            "operation": self.operation,
            "exception_type": self.exception_type,
            "message": self.message,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class ContractRegistrySummary:
    """Summarize registered contract descriptor lifecycle counts."""

    total_contracts: int = 0
    active_contracts: int = 0
    draft_contracts: int = 0
    deprecated_contracts: int = 0
    retired_contracts: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "total_contracts",
            "active_contracts",
            "draft_contracts",
            "deprecated_contracts",
            "retired_contracts",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for contract registry counts."""

        return {
            "total_contracts": self.total_contracts,
            "active_contracts": self.active_contracts,
            "draft_contracts": self.draft_contracts,
            "deprecated_contracts": self.deprecated_contracts,
            "retired_contracts": self.retired_contracts,
        }


def _empty_downloads_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="downloads",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="0 download requests, 0 items",
        metadata={
            "available": False,
            "total_requests": 0,
            "total_items": 0,
            "requested_count": 0,
            "validated_count": 0,
            "queued_count": 0,
            "running_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "cancelled_count": 0,
            "skipped_count": 0,
            "partially_completed_count": 0,
            "preflight_failed_count": 0,
            "websocket_required_count": 0,
            "connection_blocked_count": 0,
            "active_request_ids": (),
            "queued_request_ids": (),
            "failed_request_ids": (),
            "active_item_ids": (),
            "failed_item_ids": (),
        },
    )


@dataclass(frozen=True)
class RuntimeManagerSnapshot:
    """
    Aggregate read model produced by RuntimeManagerBackend.

    The snapshot is derived from existing Core runtime owners. It owns no
    lifecycle state and its overall health is computed from section statuses.
    """

    generated_at_utc: datetime
    app_status: str
    session_id: str | None
    user_id: str | None
    username: str | None
    app_summary: RuntimeSectionSummary
    session_summary: RuntimeSectionSummary
    services_summary: RuntimeSectionSummary
    tasks_summary: RuntimeSectionSummary
    processes_summary: RuntimeSectionSummary
    connections_summary: RuntimeSectionSummary
    windows_summary: RuntimeSectionSummary
    actions_summary: RuntimeSectionSummary
    operations_summary: RuntimeSectionSummary
    audit_summary: RuntimeSectionSummary
    contracts_summary: RuntimeSectionSummary
    downloads_summary: RuntimeSectionSummary = field(
        default_factory=_empty_downloads_summary
    )
    recent_audit_events: tuple[AuditEventPreview, ...] = ()
    audit_sink_failures: tuple[AuditSinkFailurePreview, ...] = ()
    contract_registry: ContractRegistrySummary = field(
        default_factory=ContractRegistrySummary
    )
    health: RuntimeHealthStatus = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "generated_at_utc",
            _coerce_utc(self.generated_at_utc, "generated_at_utc"),
        )
        _validate_non_empty_string(self.app_status, "app_status")
        for field_name in ("session_id", "user_id", "username"):
            _validate_optional_string(getattr(self, field_name), field_name)

        for field_name in (
            "app_summary",
            "session_summary",
            "services_summary",
            "tasks_summary",
            "processes_summary",
            "connections_summary",
            "windows_summary",
            "actions_summary",
            "operations_summary",
            "downloads_summary",
            "audit_summary",
            "contracts_summary",
        ):
            if not isinstance(getattr(self, field_name), RuntimeSectionSummary):
                raise TypeError(f"{field_name} must be a RuntimeSectionSummary")

        object.__setattr__(
            self,
            "recent_audit_events",
            _normalize_tuple(
                self.recent_audit_events,
                AuditEventPreview,
                "recent_audit_events",
            ),
        )
        object.__setattr__(
            self,
            "audit_sink_failures",
            _normalize_tuple(
                self.audit_sink_failures,
                AuditSinkFailurePreview,
                "audit_sink_failures",
            ),
        )
        if not isinstance(self.contract_registry, ContractRegistrySummary):
            raise TypeError("contract_registry must be a ContractRegistrySummary")
        object.__setattr__(self, "health", _derive_health(self.sections))

    @property
    def sections(self) -> tuple[RuntimeSectionSummary, ...]:
        """Return section summaries in stable Runtime Manager display order."""

        return (
            self.app_summary,
            self.session_summary,
            self.services_summary,
            self.tasks_summary,
            self.processes_summary,
            self.connections_summary,
            self.windows_summary,
            self.actions_summary,
            self.operations_summary,
            self.downloads_summary,
            self.audit_summary,
            self.contracts_summary,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this runtime snapshot."""

        return {
            "generated_at_utc": self.generated_at_utc.isoformat(),
            "health": self.health.value,
            "app_status": self.app_status,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "username": self.username,
            "sections": [section.to_dict() for section in self.sections],
            "recent_audit_events": [
                event.to_dict() for event in self.recent_audit_events
            ],
            "audit_sink_failures": [
                failure.to_dict() for failure in self.audit_sink_failures
            ],
            "contract_registry": self.contract_registry.to_dict(),
        }


def _derive_health(
    sections: tuple[RuntimeSectionSummary, ...],
) -> RuntimeHealthStatus:
    if any(section.status is RuntimeSectionStatus.ERROR for section in sections):
        return RuntimeHealthStatus.ERROR
    if any(section.status is RuntimeSectionStatus.DEGRADED for section in sections):
        return RuntimeHealthStatus.DEGRADED
    return RuntimeHealthStatus.OK


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
    for key in value:
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        normalized[key] = _readonly_value(value[key])
    return MappingProxyType(normalized)


def _readonly_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _readonly_mapping(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_value(item) for item in value)
    return value


def _normalize_tuple(
    values: tuple[object, ...],
    expected_type: type[object],
    field_name: str,
) -> tuple[object, ...]:
    normalized = tuple(values)
    for value in normalized:
        if not isinstance(value, expected_type):
            raise TypeError(f"{field_name} entries must be {expected_type.__name__}")
    return normalized


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _coerce_utc(value, "metadata datetime").isoformat()
    return value


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)
