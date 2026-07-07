"""Runtime inspection read-model contracts for Leonardo V2 Core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from math import isfinite
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


class SuiteRuntimeSummaryStatus(str, Enum):
    """Read-only availability status for one suite or area summary."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ProviderRuntimeSummaryStatus(str, Enum):
    """Read-only availability status for one provider runtime summary."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class DownloadDataRuntimeSummaryStatus(str, Enum):
    """Read-only availability status for one Download Data runtime summary."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class SuiteRuntimeSummary:
    """
    Compact read-only Runtime Manager summary for a future suite or area.

    The summary is supplied by future app composition or suite owners. It does
    not contain provider callables, suite objects, descriptors, command
    implementations, or mutable runtime state.
    """

    suite_id: str | None
    area_id: str | None
    display_name: str
    status: SuiteRuntimeSummaryStatus | str
    module_count: int = 0
    active_operation_count: int = 0
    active_task_count: int = 0
    object_map_section_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    degraded: bool = False
    unavailable_reason: str | None = None
    last_activity_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_string(self.suite_id, "suite_id")
        _validate_optional_string(self.area_id, "area_id")
        if self.suite_id is None and self.area_id is None:
            raise ValueError("suite_id or area_id must identify the summary")
        _validate_non_empty_string(self.display_name, "display_name")
        object.__setattr__(
            self,
            "status",
            _coerce_suite_runtime_status(self.status),
        )
        for field_name in (
            "module_count",
            "active_operation_count",
            "active_task_count",
            "object_map_section_count",
            "warning_count",
            "error_count",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if type(self.degraded) is not bool:
            raise TypeError("degraded must be a bool")
        _validate_optional_string(self.unavailable_reason, "unavailable_reason")
        _validate_optional_string(self.last_activity_at, "last_activity_at")
        for field_name in ("warnings", "errors", "docs_refs", "test_refs"):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this suite runtime summary."""

        return {
            "suite_id": self.suite_id,
            "area_id": self.area_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "module_count": self.module_count,
            "active_operation_count": self.active_operation_count,
            "active_task_count": self.active_task_count,
            "object_map_section_count": self.object_map_section_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "degraded": self.degraded,
            "unavailable_reason": self.unavailable_reason,
            "last_activity_at": self.last_activity_at,
            "metadata": _plain_value(self.metadata),
            "docs_refs": list(self.docs_refs),
            "test_refs": list(self.test_refs),
        }


@dataclass(frozen=True)
class ProviderRuntimeSummary:
    """
    Compact read-only Runtime Manager summary for a provider boundary.

    The summary is supplied by future app composition or provider owners. It
    carries bounded provider/session/subscription counts and diagnostics only.
    It does not contain provider objects, runtime handles, transport clients,
    credentials, raw message bodies, or mutable runtime state.
    """

    provider_id: str
    display_name: str
    status: ProviderRuntimeSummaryStatus | str
    provider_kind: str | None = None
    capability_count: int = 0
    session_count: int = 0
    active_session_count: int = 0
    connected_session_count: int = 0
    subscription_count: int = 0
    active_subscription_count: int = 0
    message_trace_count: int = 0
    object_map_section_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    degraded: bool = False
    unavailable_reason: str | None = None
    last_activity_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.provider_id, "provider_id")
        _validate_non_empty_string(self.display_name, "display_name")
        _validate_optional_string(self.provider_kind, "provider_kind")
        object.__setattr__(
            self,
            "status",
            _coerce_provider_runtime_status(self.status),
        )
        for field_name in (
            "capability_count",
            "session_count",
            "active_session_count",
            "connected_session_count",
            "subscription_count",
            "active_subscription_count",
            "message_trace_count",
            "object_map_section_count",
            "warning_count",
            "error_count",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if type(self.degraded) is not bool:
            raise TypeError("degraded must be a bool")
        _validate_optional_string(self.unavailable_reason, "unavailable_reason")
        _validate_optional_string(self.last_activity_at, "last_activity_at")
        for field_name in ("warnings", "errors", "docs_refs", "test_refs"):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_provider_runtime_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this provider runtime summary."""

        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "provider_kind": self.provider_kind,
            "capability_count": self.capability_count,
            "session_count": self.session_count,
            "active_session_count": self.active_session_count,
            "connected_session_count": self.connected_session_count,
            "subscription_count": self.subscription_count,
            "active_subscription_count": self.active_subscription_count,
            "message_trace_count": self.message_trace_count,
            "object_map_section_count": self.object_map_section_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "degraded": self.degraded,
            "unavailable_reason": self.unavailable_reason,
            "last_activity_at": self.last_activity_at,
            "metadata": _plain_value(self.metadata),
            "docs_refs": list(self.docs_refs),
            "test_refs": list(self.test_refs),
        }


@dataclass(frozen=True)
class DownloadDataRuntimeSummary:
    """
    Compact read-only Runtime Manager summary for Download Data runtime state.

    The summary is supplied by future app composition or Download Data owners.
    It carries bounded workflow counts and diagnostics only. It does not contain
    provider objects, adapters, storage writers, GUI widgets, runtime task
    objects, transport handles, credentials, raw payloads, or mutable runtime
    state.
    """

    workflow_id: str
    display_name: str
    status: DownloadDataRuntimeSummaryStatus | str
    selection_count: int = 0
    preflight_count: int = 0
    ready_preflight_count: int = 0
    blocked_preflight_count: int = 0
    running_progress_count: int = 0
    completed_progress_count: int = 0
    completion_count: int = 0
    partial_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    output_ref_count: int = 0
    storage_target_count: int = 0
    partial_persistence_count: int = 0
    expected_total_bars: int = 0
    expected_total_steps: int = 0
    completed_steps: int = 0
    downloaded_bars: int = 0
    warning_count: int = 0
    error_count: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    degraded: bool = False
    unavailable_reason: str | None = None
    last_activity_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.workflow_id, "workflow_id")
        _validate_non_empty_string(self.display_name, "display_name")
        object.__setattr__(
            self,
            "status",
            _coerce_download_data_runtime_status(self.status),
        )
        for field_name in (
            "selection_count",
            "preflight_count",
            "ready_preflight_count",
            "blocked_preflight_count",
            "running_progress_count",
            "completed_progress_count",
            "completion_count",
            "partial_count",
            "failed_count",
            "cancelled_count",
            "output_ref_count",
            "storage_target_count",
            "partial_persistence_count",
            "expected_total_bars",
            "expected_total_steps",
            "completed_steps",
            "downloaded_bars",
            "warning_count",
            "error_count",
        ):
            _validate_non_negative_int(getattr(self, field_name), field_name)
        if type(self.degraded) is not bool:
            raise TypeError("degraded must be a bool")
        _validate_optional_string(self.unavailable_reason, "unavailable_reason")
        _validate_optional_string(self.last_activity_at, "last_activity_at")
        for field_name in ("warnings", "errors", "docs_refs", "test_refs"):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_download_data_runtime_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this Download Data summary."""

        return {
            "workflow_id": self.workflow_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "selection_count": self.selection_count,
            "preflight_count": self.preflight_count,
            "ready_preflight_count": self.ready_preflight_count,
            "blocked_preflight_count": self.blocked_preflight_count,
            "running_progress_count": self.running_progress_count,
            "completed_progress_count": self.completed_progress_count,
            "completion_count": self.completion_count,
            "partial_count": self.partial_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "output_ref_count": self.output_ref_count,
            "storage_target_count": self.storage_target_count,
            "partial_persistence_count": self.partial_persistence_count,
            "expected_total_bars": self.expected_total_bars,
            "expected_total_steps": self.expected_total_steps,
            "completed_steps": self.completed_steps,
            "downloaded_bars": self.downloaded_bars,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "degraded": self.degraded,
            "unavailable_reason": self.unavailable_reason,
            "last_activity_at": self.last_activity_at,
            "metadata": _plain_value(self.metadata),
            "docs_refs": list(self.docs_refs),
            "test_refs": list(self.test_refs),
        }


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


def _empty_download_execution_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="download_execution",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="0 download execution plans",
        metadata={
            "available": False,
            "total_plans": 0,
            "active_plan_ids": (),
            "failed_plan_ids": (),
            "completed_plan_ids": (),
            "running_plan_ids": (),
            "blocked_plan_ids": (),
            "plan_rows": (),
        },
    )


def _empty_object_map_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="object_map",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="Object Map unavailable",
        metadata={
            "available": False,
            "provider_count": 0,
            "section_count": 0,
            "object_count": 0,
            "relationship_count": 0,
            "family_ids": (),
            "object_kinds": (),
            "provider_ids": (),
            "section_ids": (),
            "warning_count": 0,
            "error_count": 0,
            "blocker_count": 0,
            "warnings": (),
            "errors": (),
            "blockers": (),
            "degraded": False,
        },
    )


def _empty_provider_runtime_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="provider_runtime",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="Provider runtime summaries unavailable",
        metadata={
            "available": False,
            "summary_count": 0,
            "provider_count": 0,
            "capability_count": 0,
            "session_count": 0,
            "active_session_count": 0,
            "connected_session_count": 0,
            "subscription_count": 0,
            "active_subscription_count": 0,
            "message_trace_count": 0,
            "object_map_section_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "degraded_count": 0,
            "unavailable_count": 0,
            "provider_ids": (),
            "warnings": (),
            "errors": (),
            "unavailable_reasons": (),
            "last_activity_at": None,
            "summary_rows": (),
            "degraded": False,
            "provider_failed": False,
        },
    )


def _empty_suite_runtime_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="suite_runtime",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="Suite runtime summaries unavailable",
        metadata={
            "available": False,
            "summary_count": 0,
            "suite_count": 0,
            "area_count": 0,
            "module_count": 0,
            "active_operation_count": 0,
            "active_task_count": 0,
            "object_map_section_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "degraded_count": 0,
            "unavailable_count": 0,
            "suite_ids": (),
            "area_ids": (),
            "warnings": (),
            "errors": (),
            "unavailable_reasons": (),
            "last_activity_at": None,
            "summary_rows": (),
            "degraded": False,
            "provider_failed": False,
        },
    )


def _empty_download_data_runtime_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="download_data_runtime",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="Download Data runtime summaries unavailable",
        metadata={
            "available": False,
            "summary_count": 0,
            "workflow_count": 0,
            "selection_count": 0,
            "preflight_count": 0,
            "ready_preflight_count": 0,
            "blocked_preflight_count": 0,
            "running_progress_count": 0,
            "completed_progress_count": 0,
            "completion_count": 0,
            "partial_count": 0,
            "failed_count": 0,
            "cancelled_count": 0,
            "output_ref_count": 0,
            "storage_target_count": 0,
            "partial_persistence_count": 0,
            "expected_total_bars": 0,
            "expected_total_steps": 0,
            "completed_steps": 0,
            "downloaded_bars": 0,
            "warning_count": 0,
            "error_count": 0,
            "degraded_count": 0,
            "unavailable_count": 0,
            "workflow_ids": (),
            "warnings": (),
            "errors": (),
            "unavailable_reasons": (),
            "last_activity_at": None,
            "summary_rows": (),
            "degraded": False,
            "download_data_failed": False,
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
    download_execution_summary: RuntimeSectionSummary = field(
        default_factory=_empty_download_execution_summary
    )
    object_map_summary: RuntimeSectionSummary = field(
        default_factory=_empty_object_map_summary
    )
    provider_runtime_summary: RuntimeSectionSummary = field(
        default_factory=_empty_provider_runtime_summary
    )
    suite_runtime_summary: RuntimeSectionSummary = field(
        default_factory=_empty_suite_runtime_summary
    )
    download_data_runtime_summary: RuntimeSectionSummary = field(
        default_factory=_empty_download_data_runtime_summary
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
            "download_execution_summary",
            "object_map_summary",
            "provider_runtime_summary",
            "suite_runtime_summary",
            "download_data_runtime_summary",
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
            self.download_execution_summary,
            self.object_map_summary,
            self.provider_runtime_summary,
            self.suite_runtime_summary,
            self.download_data_runtime_summary,
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


def _coerce_suite_runtime_status(
    value: SuiteRuntimeSummaryStatus | str,
) -> SuiteRuntimeSummaryStatus:
    if isinstance(value, SuiteRuntimeSummaryStatus):
        return value
    if isinstance(value, str):
        try:
            return SuiteRuntimeSummaryStatus(value)
        except ValueError as error:
            allowed = ", ".join(status.value for status in SuiteRuntimeSummaryStatus)
            raise ValueError(f"status must be one of: {allowed}") from error
    raise TypeError("status must be a SuiteRuntimeSummaryStatus or string")


def _coerce_provider_runtime_status(
    value: ProviderRuntimeSummaryStatus | str,
) -> ProviderRuntimeSummaryStatus:
    if isinstance(value, ProviderRuntimeSummaryStatus):
        return value
    if isinstance(value, str):
        try:
            return ProviderRuntimeSummaryStatus(value)
        except ValueError as error:
            allowed = ", ".join(status.value for status in ProviderRuntimeSummaryStatus)
            raise ValueError(f"status must be one of: {allowed}") from error
    raise TypeError("status must be a ProviderRuntimeSummaryStatus or string")


def _coerce_download_data_runtime_status(
    value: DownloadDataRuntimeSummaryStatus | str,
) -> DownloadDataRuntimeSummaryStatus:
    if isinstance(value, DownloadDataRuntimeSummaryStatus):
        return value
    if isinstance(value, str):
        try:
            return DownloadDataRuntimeSummaryStatus(value)
        except ValueError as error:
            allowed = ", ".join(
                status.value for status in DownloadDataRuntimeSummaryStatus
            )
            raise ValueError(f"status must be one of: {allowed}") from error
    raise TypeError("status must be a DownloadDataRuntimeSummaryStatus or string")


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


def _readonly_provider_runtime_metadata(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key in value:
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        _validate_provider_runtime_metadata_key(key)
        normalized[key] = _readonly_provider_runtime_value(value[key])
    return MappingProxyType(normalized)


def _validate_provider_runtime_metadata_key(value: str) -> None:
    normalized = value.strip().lower()
    for sensitive in _SENSITIVE_PROVIDER_RUNTIME_METADATA_KEY_PARTS:
        if sensitive in normalized:
            raise ValueError("metadata keys must not contain provider-sensitive terms")


def _readonly_provider_runtime_value(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError("metadata float values must be finite")
        return value
    if isinstance(value, Mapping):
        return _readonly_provider_runtime_metadata(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_provider_runtime_value(item) for item in value)
    if callable(value):
        raise TypeError("metadata values must be JSON-compatible")
    if isinstance(value, bytes | bytearray | memoryview | set | frozenset):
        raise TypeError("metadata values must be JSON-compatible")
    raise TypeError("metadata values must be JSON-compatible")


def _readonly_download_data_runtime_metadata(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key in value:
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        _validate_download_data_runtime_metadata_key(key)
        normalized[key] = _readonly_download_data_runtime_value(value[key])
    return MappingProxyType(normalized)


def _validate_download_data_runtime_metadata_key(value: str) -> None:
    normalized = value.strip().lower()
    for sensitive in _SENSITIVE_DOWNLOAD_DATA_RUNTIME_METADATA_KEY_PARTS:
        if sensitive in normalized:
            raise ValueError("metadata keys must not contain sensitive terms")


def _readonly_download_data_runtime_value(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError("metadata float values must be finite")
        return value
    if isinstance(value, Mapping):
        return _readonly_download_data_runtime_metadata(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_download_data_runtime_value(item) for item in value)
    if callable(value):
        raise TypeError("metadata values must be JSON-compatible")
    if isinstance(value, bytes | bytearray | memoryview | set | frozenset):
        raise TypeError("metadata values must be JSON-compatible")
    raise TypeError("metadata values must be JSON-compatible")


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


def _normalize_string_tuple(
    values: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    normalized = tuple(values)
    for value in normalized:
        _validate_non_empty_string(value, f"{field_name} entry")
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


def _validate_non_negative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


_SENSITIVE_PROVIDER_RUNTIME_METADATA_KEY_PARTS = (
    "credential",
    "credentials",
    "token",
    "secret",
    "password",
    "api_key",
    "authorization",
    "bearer",
    "client",
    "socket",
    "payload",
    "raw_payload",
    "response",
)

_SENSITIVE_DOWNLOAD_DATA_RUNTIME_METADATA_KEY_PARTS = (
    "credential",
    "credentials",
    "token",
    "secret",
    "password",
    "api_key",
    "authorization",
    "bearer",
    "client",
    "socket",
    "payload",
    "raw_payload",
    "response",
    "provider",
    "adapter",
    "writer",
    "handle",
)
