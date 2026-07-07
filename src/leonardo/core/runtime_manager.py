"""Read-only Runtime Manager backend snapshots for Leonardo V2 Core."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import re

from leonardo.contracts.audit import AuditEvent
from leonardo.contracts.connections import ConnectionLifecycleStatus
from leonardo.contracts.download_execution import (
    DownloadExecutionPhase,
    is_running_execution_phase,
    is_terminal_execution_phase,
)
from leonardo.contracts.inspection import (
    AuditEventPreview,
    AuditSinkFailurePreview,
    ContractRegistrySummary,
    RuntimeManagerSnapshot,
    RuntimeSectionStatus,
    RuntimeSectionSummary,
)
from leonardo.contracts.kernel import ContractStatus
from leonardo.contracts.object_map import ObjectMapSnapshot
from leonardo.contracts.operations import OperationLifecycleStatus
from leonardo.contracts.processes import ProcessLifecycleStatus
from leonardo.contracts.runtime import (
    AppLifecycleStatus,
    RuntimeSnapshot,
    ServiceLifecycleStatus,
    TaskLifecycleStatus,
)
from leonardo.core.action_registry import ActionRegistry
from leonardo.core.audit_log import AuditLog, AuditSinkFailure
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.contract_registry import ContractRegistry
from leonardo.core.download_execution_manager import DownloadExecutionManager
from leonardo.core.download_manager import DownloadManager
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.process_manager import ProcessManager
from leonardo.core.service_registry import ServiceRegistry
from leonardo.core.session_manager import SessionManager
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager
from leonardo.core.window_registry import WindowRegistry


_MAX_OBJECT_MAP_DIAGNOSTICS = 10
_MAX_OBJECT_MAP_DIAGNOSTIC_LENGTH = 160
_REDACTED_VALUE = "[redacted]"
_REDACTED_PATH = "[path]"
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    r"(?i)((?:['\"])?\b"
    r"(?:token|secret|password|passwd|api_key|apikey|authorization|bearer|credential)"
    r"\b(?:['\"])?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_BEARER_VALUE_PATTERN = re.compile(
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"
)
_WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:\\[^\s,;]+")
_POSIX_PATH_PATTERN = re.compile(r"(?<!\w)/(?:[^/\s,;]+/)+[^\s,;]+")


class RuntimeManagerBackend:
    """
    Aggregate read-only runtime inspection snapshots from Core components.

    The backend is a read-model facade for a future Runtime Manager surface. It
    does not own runtime state, emit audit events, execute registered actions,
    or start or cancel tasks.
    """

    def __init__(
        self,
        *,
        state_store: StateStore,
        session_manager: SessionManager,
        service_registry: ServiceRegistry,
        task_manager: TaskManager,
        process_manager: ProcessManager,
        connection_registry: ConnectionRegistry,
        window_registry: WindowRegistry,
        action_registry: ActionRegistry,
        operation_registry: OperationRegistry,
        audit_log: AuditLog,
        contract_registry: ContractRegistry,
        download_manager: DownloadManager | None = None,
        download_execution_manager: DownloadExecutionManager | None = None,
        object_map_snapshot_provider: Callable[[], ObjectMapSnapshot] | None = None,
        recent_audit_limit: int = 20,
    ) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        if not isinstance(session_manager, SessionManager):
            raise TypeError("session_manager must be a SessionManager")
        if not isinstance(service_registry, ServiceRegistry):
            raise TypeError("service_registry must be a ServiceRegistry")
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if not isinstance(process_manager, ProcessManager):
            raise TypeError("process_manager must be a ProcessManager")
        if not isinstance(connection_registry, ConnectionRegistry):
            raise TypeError("connection_registry must be a ConnectionRegistry")
        if not isinstance(window_registry, WindowRegistry):
            raise TypeError("window_registry must be a WindowRegistry")
        if not isinstance(action_registry, ActionRegistry):
            raise TypeError("action_registry must be an ActionRegistry")
        if not isinstance(operation_registry, OperationRegistry):
            raise TypeError("operation_registry must be an OperationRegistry")
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        if not isinstance(contract_registry, ContractRegistry):
            raise TypeError("contract_registry must be a ContractRegistry")
        if download_manager is not None and not isinstance(
            download_manager,
            DownloadManager,
        ):
            raise TypeError("download_manager must be a DownloadManager or None")
        if download_execution_manager is not None and not isinstance(
            download_execution_manager,
            DownloadExecutionManager,
        ):
            raise TypeError(
                "download_execution_manager must be a DownloadExecutionManager or None"
            )
        if recent_audit_limit < 1:
            raise ValueError("recent_audit_limit must be greater than zero")
        if object_map_snapshot_provider is not None and not callable(
            object_map_snapshot_provider
        ):
            raise TypeError(
                "object_map_snapshot_provider must be callable or None"
            )

        self._state_store = state_store
        self._session_manager = session_manager
        self._service_registry = service_registry
        self._task_manager = task_manager
        self._process_manager = process_manager
        self._connection_registry = connection_registry
        self._window_registry = window_registry
        self._action_registry = action_registry
        self._operation_registry = operation_registry
        self._audit_log = audit_log
        self._contract_registry = contract_registry
        self._download_manager = download_manager
        self._download_execution_manager = download_execution_manager
        self._object_map_snapshot_provider = object_map_snapshot_provider
        self._recent_audit_limit = recent_audit_limit

    def snapshot(self) -> RuntimeManagerSnapshot:
        """
        Return a defensive aggregate snapshot of the current Core runtime.

        Snapshot generation reads existing state only. No lifecycle transitions,
        registry writes, task operations, or audit events are performed.
        """

        runtime_snapshot = self._state_store.runtime_snapshot()
        audit_events = self._recent_audit_event_previews()
        sink_failures = self._audit_sink_failure_previews()
        contract_summary = self.contract_registry_summary()
        session = self._session_manager.current_session

        return RuntimeManagerSnapshot(
            generated_at_utc=datetime.now(UTC),
            app_status=runtime_snapshot.app_state.status.value,
            session_id=session.session_id,
            user_id=session.actor.user_id,
            username=session.actor.username,
            app_summary=self._app_summary(runtime_snapshot),
            session_summary=self._session_summary(),
            services_summary=self._services_summary(runtime_snapshot),
            tasks_summary=self._tasks_summary(),
            processes_summary=self._processes_summary(),
            connections_summary=self._connections_summary(),
            windows_summary=self._windows_summary(),
            actions_summary=self._actions_summary(),
            operations_summary=self._operations_summary(),
            downloads_summary=self._downloads_summary(),
            download_execution_summary=self._download_execution_summary(),
            object_map_summary=self._object_map_summary(),
            audit_summary=self._audit_summary(audit_events, sink_failures),
            contracts_summary=self._contracts_section_summary(contract_summary),
            recent_audit_events=audit_events,
            audit_sink_failures=sink_failures,
            contract_registry=contract_summary,
        )

    def app_summary(self) -> RuntimeSectionSummary:
        """Return the application lifecycle section summary."""

        return self._app_summary(self._state_store.runtime_snapshot())

    def services_summary(self) -> RuntimeSectionSummary:
        """Return the service registry section summary."""

        return self._services_summary(self._state_store.runtime_snapshot())

    def tasks_summary(self) -> RuntimeSectionSummary:
        """Return the active task section summary."""

        return self._tasks_summary()

    def processes_summary(self) -> RuntimeSectionSummary:
        """Return the active process section summary."""

        return self._processes_summary()

    def connections_summary(self) -> RuntimeSectionSummary:
        """Return the connection tracking section summary."""

        return self._connections_summary()

    def windows_summary(self) -> RuntimeSectionSummary:
        """Return the open window section summary."""

        return self._windows_summary()

    def actions_summary(self) -> RuntimeSectionSummary:
        """Return the recent action trigger section summary."""

        return self._actions_summary()

    def operations_summary(self) -> RuntimeSectionSummary:
        """Return the active operation section summary."""

        return self._operations_summary()

    def downloads_summary(self) -> RuntimeSectionSummary:
        """Return the Download Manager read-model section summary."""

        return self._downloads_summary()

    def download_execution_summary(self) -> RuntimeSectionSummary:
        """Return the Download Execution Manager read-model section summary."""

        return self._download_execution_summary()

    def object_map_summary(self) -> RuntimeSectionSummary:
        """Return the optional Object Map inspection section summary."""

        return self._object_map_summary()

    def audit_summary(self) -> RuntimeSectionSummary:
        """Return the retained audit history section summary."""

        return self._audit_summary(
            self._recent_audit_event_previews(),
            self._audit_sink_failure_previews(),
        )

    def contracts_summary(self) -> RuntimeSectionSummary:
        """Return the contract registry section summary."""

        return self._contracts_section_summary(self.contract_registry_summary())

    def contract_registry_summary(self) -> ContractRegistrySummary:
        """Return lifecycle counts for registered contract descriptors."""

        contracts = self._contract_registry.list_contracts()
        counts = Counter(
            registered.descriptor.status
            for registered in contracts
        )
        return ContractRegistrySummary(
            total_contracts=len(contracts),
            active_contracts=counts[ContractStatus.ACTIVE],
            draft_contracts=counts[ContractStatus.DRAFT],
            deprecated_contracts=counts[ContractStatus.DEPRECATED],
            retired_contracts=counts[ContractStatus.RETIRED],
        )

    def _app_summary(
        self,
        runtime_snapshot: RuntimeSnapshot,
    ) -> RuntimeSectionSummary:
        app_state = runtime_snapshot.app_state
        status = (
            RuntimeSectionStatus.ERROR
            if app_state.status is AppLifecycleStatus.FAILED
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="app",
            status=status,
            count=1,
            message=f"Application status is {app_state.status.value}",
            metadata={
                "status": app_state.status.value,
                "last_updated_utc": app_state.last_updated_utc,
                "started_at_utc": app_state.started_at_utc,
                "stopped_at_utc": app_state.stopped_at_utc,
            },
        )

    def _session_summary(self) -> RuntimeSectionSummary:
        session = self._session_manager.current_session
        return RuntimeSectionSummary(
            section_id="session",
            status=RuntimeSectionStatus.OK,
            count=1,
            message=f"Session actor is {session.actor.username}",
            metadata={
                "session_id": session.session_id,
                "user_id": session.actor.user_id,
                "username": session.actor.username,
                "origin": session.origin.value,
                "roles": tuple(role.value for role in session.actor.roles),
                "started_at_utc": session.started_at_utc,
            },
        )

    def _services_summary(
        self,
        runtime_snapshot: RuntimeSnapshot,
    ) -> RuntimeSectionSummary:
        registered_services = self._service_registry.list_services()
        service_states = runtime_snapshot.service_states
        service_ids = sorted(
            {
                registered.descriptor.service_id
                for registered in registered_services
            }.union(state.service_id for state in service_states)
        )
        status_counts = Counter(state.status.value for state in service_states)
        status = (
            RuntimeSectionStatus.DEGRADED
            if any(
                state.status is ServiceLifecycleStatus.FAILED
                for state in service_states
            )
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="services",
            status=status,
            count=len(service_ids),
            message=f"{len(service_ids)} services visible",
            metadata={
                "service_ids": tuple(service_ids),
                "registered_count": len(registered_services),
                "runtime_state_count": len(service_states),
                "status_counts": dict(sorted(status_counts.items())),
            },
        )

    def _tasks_summary(self) -> RuntimeSectionSummary:
        task_states = self._task_manager.active_tasks()
        status_counts = Counter(state.status.value for state in task_states)
        status = (
            RuntimeSectionStatus.DEGRADED
            if any(
                state.status
                in {
                    TaskLifecycleStatus.FAILED,
                    TaskLifecycleStatus.CANCEL_REQUESTED,
                }
                for state in task_states
            )
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="tasks",
            status=status,
            count=len(task_states),
            message=f"{len(task_states)} active tasks",
            metadata={
                "task_ids": tuple(state.task_id for state in task_states),
                "task_names": tuple(state.task_name for state in task_states),
                "operation_ids": tuple(state.operation_id for state in task_states),
                "correlation_ids": tuple(
                    state.correlation_id for state in task_states
                ),
                "status_counts": dict(sorted(status_counts.items())),
            },
        )

    def _processes_summary(self) -> RuntimeSectionSummary:
        process_states = self._process_manager.active_processes()
        status_counts = Counter(state.status.value for state in process_states)
        status = (
            RuntimeSectionStatus.DEGRADED
            if any(
                state.status
                in {
                    ProcessLifecycleStatus.FAILED,
                    ProcessLifecycleStatus.UNKNOWN,
                }
                for state in process_states
            )
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="processes",
            status=status,
            count=len(process_states),
            message=f"{len(process_states)} active processes",
            metadata={
                "process_ids": tuple(state.process_id for state in process_states),
                "process_labels": tuple(state.label for state in process_states),
                "status_counts": dict(sorted(status_counts.items())),
            },
        )

    def _connections_summary(self) -> RuntimeSectionSummary:
        connection_states = self._connection_registry.connection_states()
        channel_states = self._connection_registry.websocket_channel_states()
        status_counts = Counter(state.status.value for state in connection_states)
        channel_received_count = sum(
            state.received_count for state in channel_states
        )
        channel_sent_count = sum(state.sent_count for state in channel_states)
        channel_error_count = sum(state.error_count for state in channel_states)
        degraded_count = status_counts[ConnectionLifecycleStatus.DEGRADED.value]
        failed_count = status_counts[ConnectionLifecycleStatus.FAILED.value]
        status = (
            RuntimeSectionStatus.DEGRADED
            if degraded_count or failed_count
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="connections",
            status=status,
            count=len(connection_states),
            message=f"{len(connection_states)} connections visible",
            metadata={
                "connection_ids": tuple(
                    state.connection_id for state in connection_states
                ),
                "connection_labels": tuple(state.label for state in connection_states),
                "status_counts": dict(sorted(status_counts.items())),
                "connected_count": status_counts[
                    ConnectionLifecycleStatus.CONNECTED.value
                ],
                "degraded_count": degraded_count,
                "failed_count": failed_count,
                "disconnected_count": status_counts[
                    ConnectionLifecycleStatus.DISCONNECTED.value
                ],
                "websocket_channel_count": len(channel_states),
                "websocket_channel_ids": tuple(
                    state.channel_id for state in channel_states
                ),
                "channel_received_count": channel_received_count,
                "channel_sent_count": channel_sent_count,
                "channel_error_count": channel_error_count,
            },
        )

    def _windows_summary(self) -> RuntimeSectionSummary:
        window_states = self._window_registry.open_windows()
        definitions = self._window_registry.list_windows()
        return RuntimeSectionSummary(
            section_id="windows",
            status=RuntimeSectionStatus.OK,
            count=len(window_states),
            message=f"{len(window_states)} open windows",
            metadata={
                "open_window_ids": tuple(state.window_id for state in window_states),
                "registered_window_ids": tuple(
                    definition.window_id for definition in definitions
                ),
            },
        )

    def _actions_summary(self) -> RuntimeSectionSummary:
        recent_triggers = self._action_registry.recent_triggers()
        definitions = self._action_registry.list_actions()
        return RuntimeSectionSummary(
            section_id="actions",
            status=RuntimeSectionStatus.OK,
            count=len(recent_triggers),
            message=f"{len(recent_triggers)} recent action triggers",
            metadata={
                "recent_action_ids": tuple(
                    trigger.action_id for trigger in recent_triggers
                ),
                "registered_action_ids": tuple(
                    definition.action_id for definition in definitions
                ),
            },
        )

    def _operations_summary(self) -> RuntimeSectionSummary:
        operation_states = self._operation_registry.active_operations()
        status_counts = Counter(state.status.value for state in operation_states)
        degraded_statuses = {
            OperationLifecycleStatus.BLOCKED,
            OperationLifecycleStatus.FAILED,
            OperationLifecycleStatus.CANCEL_REQUESTED,
        }
        status = (
            RuntimeSectionStatus.DEGRADED
            if any(state.status in degraded_statuses for state in operation_states)
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="operations",
            status=status,
            count=len(operation_states),
            message=f"{len(operation_states)} active operations",
            metadata={
                "operation_ids": tuple(
                    state.operation_id for state in operation_states
                ),
                "operation_labels": tuple(state.label for state in operation_states),
                "task_ids": tuple(state.task_id for state in operation_states),
                "correlation_ids": tuple(
                    state.correlation_id for state in operation_states
                ),
                "status_counts": dict(sorted(status_counts.items())),
            },
        )

    def _downloads_summary(self) -> RuntimeSectionSummary:
        if self._download_manager is None:
            return RuntimeSectionSummary(
                section_id="downloads",
                status=RuntimeSectionStatus.OK,
                count=0,
                message="Download Manager unavailable",
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

        summary = self._download_manager.get_summary()
        status = (
            RuntimeSectionStatus.DEGRADED
            if (
                summary.failed_count
                or summary.preflight_failed_count
                or summary.connection_blocked_count
            )
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="downloads",
            status=status,
            count=summary.total_requests,
            message=_download_summary_message(
                summary.total_requests,
                summary.total_items,
            ),
            metadata={
                "available": True,
                "total_requests": summary.total_requests,
                "total_items": summary.total_items,
                "requested_count": summary.requested_count,
                "validated_count": summary.validated_count,
                "queued_count": summary.queued_count,
                "running_count": summary.running_count,
                "completed_count": summary.completed_count,
                "failed_count": summary.failed_count,
                "cancelled_count": summary.cancelled_count,
                "skipped_count": summary.skipped_count,
                "partially_completed_count": summary.partially_completed_count,
                "preflight_failed_count": summary.preflight_failed_count,
                "websocket_required_count": summary.websocket_required_count,
                "connection_blocked_count": summary.connection_blocked_count,
                "active_request_ids": summary.active_request_ids,
                "queued_request_ids": summary.queued_request_ids,
                "failed_request_ids": summary.failed_request_ids,
                "active_item_ids": summary.active_item_ids,
                "failed_item_ids": summary.failed_item_ids,
            },
        )

    def _download_execution_summary(self) -> RuntimeSectionSummary:
        if self._download_execution_manager is None:
            return RuntimeSectionSummary(
                section_id="download_execution",
                status=RuntimeSectionStatus.OK,
                count=0,
                message="Download Execution Manager unavailable",
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

        snapshots = self._download_execution_manager.list_snapshots()
        rows = tuple(_download_execution_plan_row(snapshot) for snapshot in snapshots)
        failed_plan_ids = tuple(
            row["plan_id"]
            for row in rows
            if row["phase"] == DownloadExecutionPhase.FAILED.value
        )
        completed_plan_ids = tuple(
            row["plan_id"]
            for row in rows
            if row["phase"] == DownloadExecutionPhase.COMPLETED.value
        )
        running_plan_ids = tuple(
            row["plan_id"]
            for row in rows
            if is_running_execution_phase(row["phase"])
        )
        blocked_plan_ids = tuple(
            row["plan_id"]
            for row in rows
            if row["phase"] == DownloadExecutionPhase.BLOCKED.value
        )
        active_plan_ids = tuple(
            row["plan_id"]
            for row in rows
            if not is_terminal_execution_phase(row["phase"])
        )
        error_count = sum(int(row["error_count"]) for row in rows)
        status = (
            RuntimeSectionStatus.DEGRADED
            if failed_plan_ids or blocked_plan_ids or error_count
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="download_execution",
            status=status,
            count=len(snapshots),
            message=_download_execution_summary_message(len(snapshots)),
            metadata={
                "available": True,
                "total_plans": len(snapshots),
                "active_plan_ids": active_plan_ids,
                "failed_plan_ids": failed_plan_ids,
                "completed_plan_ids": completed_plan_ids,
                "running_plan_ids": running_plan_ids,
                "blocked_plan_ids": blocked_plan_ids,
                "plan_rows": rows,
            },
        )

    def _object_map_summary(self) -> RuntimeSectionSummary:
        if self._object_map_snapshot_provider is None:
            return _empty_object_map_summary()

        try:
            snapshot = self._object_map_snapshot_provider()
        except Exception as error:  # noqa: BLE001 - read-model boundary.
            diagnostic = _object_map_failure_diagnostic(error)
            return RuntimeSectionSummary(
                section_id="object_map",
                status=RuntimeSectionStatus.DEGRADED,
                count=0,
                message="Object Map snapshot provider failed",
                metadata={
                    **_empty_object_map_metadata(available=False),
                    "error_count": 1,
                    "errors": (diagnostic,),
                    "degraded": True,
                    "provider_failed": True,
                },
            )

        if not isinstance(snapshot, ObjectMapSnapshot):
            return RuntimeSectionSummary(
                section_id="object_map",
                status=RuntimeSectionStatus.DEGRADED,
                count=0,
                message="Object Map snapshot provider returned invalid output",
                metadata={
                    **_empty_object_map_metadata(available=False),
                    "error_count": 1,
                    "errors": ("Object Map snapshot provider returned invalid output",),
                    "degraded": True,
                    "provider_failed": True,
                },
            )

        return _object_map_summary_from_snapshot(snapshot)

    def _audit_summary(
        self,
        audit_events: tuple[AuditEventPreview, ...],
        sink_failures: tuple[AuditSinkFailurePreview, ...],
    ) -> RuntimeSectionSummary:
        status = (
            RuntimeSectionStatus.DEGRADED
            if sink_failures
            else RuntimeSectionStatus.OK
        )
        return RuntimeSectionSummary(
            section_id="audit",
            status=status,
            count=len(audit_events),
            message=f"{len(audit_events)} retained audit events",
            metadata={
                "sink_failure_count": len(sink_failures),
                "recent_event_ids": tuple(event.event_id for event in audit_events),
            },
        )

    def _contracts_section_summary(
        self,
        contract_summary: ContractRegistrySummary,
    ) -> RuntimeSectionSummary:
        return RuntimeSectionSummary(
            section_id="contracts",
            status=RuntimeSectionStatus.OK,
            count=contract_summary.total_contracts,
            message=f"{contract_summary.total_contracts} contracts registered",
            metadata=contract_summary.to_dict(),
        )

    def _recent_audit_event_previews(self) -> tuple[AuditEventPreview, ...]:
        events = self._audit_log.snapshot()[-self._recent_audit_limit :]
        return tuple(_event_preview(event) for event in events)

    def _audit_sink_failure_previews(self) -> tuple[AuditSinkFailurePreview, ...]:
        return tuple(
            _sink_failure_preview(failure)
            for failure in self._audit_log.sink_failures()
        )


def _event_preview(event: AuditEvent) -> AuditEventPreview:
    return AuditEventPreview(
        event_id=event.event_id,
        timestamp_utc=event.timestamp_utc,
        severity=event.severity.value,
        category=event.category.value,
        event_type=event.event_type,
        message=event.message,
        actor_id=event.actor_id,
        session_id=event.session_id,
        window_id=event.window_id,
        action_id=event.action_id,
        operation_id=event.operation_id,
        task_id=event.task_id,
        correlation_id=event.correlation_id,
    )


def _download_summary_message(total_requests: int, total_items: int) -> str:
    request_label = "request" if total_requests == 1 else "requests"
    item_label = "item" if total_items == 1 else "items"
    return f"{total_requests} download {request_label}, {total_items} {item_label}"


def _download_execution_summary_message(total_plans: int) -> str:
    plan_label = "plan" if total_plans == 1 else "plans"
    return f"{total_plans} download execution {plan_label}"


def _download_execution_plan_row(snapshot: object) -> dict[str, object]:
    plan = snapshot.plan
    progress = snapshot.progress
    estimate = snapshot.estimate
    details = _download_execution_details(snapshot)
    return {
        "plan_id": plan.plan_id,
        "request_id": plan.request_id,
        "phase": plan.phase.value,
        "operation_id": plan.operation_id,
        "task_id": plan.task_id,
        "item_count": len(plan.item_ids),
        "preflight_layer_count": len(snapshot.preflight_layers),
        "progress_percent": progress.percent if progress is not None else None,
        "output_count": len(snapshot.outputs),
        "error_count": len(snapshot.errors),
        "details": details,
        "estimated_items": estimate.estimated_items if estimate is not None else None,
    }


def _download_execution_details(snapshot: object) -> str:
    plan = snapshot.plan
    progress = snapshot.progress
    details: list[str] = []
    if plan.connection_refs:
        details.append(f"connection_refs={', '.join(plan.connection_refs)}")
    if plan.dataset_refs:
        details.append(f"dataset_refs={', '.join(plan.dataset_refs)}")
    if plan.adapter_ref:
        details.append(f"adapter_ref={plan.adapter_ref}")
    if plan.storage_policy_ref:
        details.append(f"storage_policy_ref={plan.storage_policy_ref}")
    if progress is not None and progress.message:
        details.append(f"message={progress.message}")
    return "; ".join(details)


def _empty_object_map_summary() -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id="object_map",
        status=RuntimeSectionStatus.OK,
        count=0,
        message="Object Map unavailable",
        metadata=_empty_object_map_metadata(available=False),
    )


def _empty_object_map_metadata(*, available: bool) -> dict[str, object]:
    return {
        "available": available,
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
    }


def _object_map_summary_from_snapshot(
    snapshot: ObjectMapSnapshot,
) -> RuntimeSectionSummary:
    summaries = tuple(
        summary for section in snapshot.sections for summary in section.summaries
    )
    relationships = tuple(
        relationship
        for section in snapshot.sections
        for relationship in section.relationships
    )
    warnings = _sanitized_unique_diagnostics(
        (
            *snapshot.warnings,
            *(
                warning
                for section in snapshot.sections
                for warning in section.warnings
            ),
        )
    )
    errors = _sanitized_unique_diagnostics(
        (
            *snapshot.errors,
            *(
                error
                for section in snapshot.sections
                for error in section.errors
            ),
        )
    )
    blockers = _sanitized_unique_diagnostics(
        (
            *snapshot.blockers,
            *(
                blocker
                for section in snapshot.sections
                for blocker in section.blockers
            ),
        )
    )
    provider_ids = _sorted_unique(
        (
            *(descriptor.provider_id for descriptor in snapshot.provider_descriptors),
            *(section.provider_id for section in snapshot.sections),
        )
    )
    section_ids = _sorted_unique(section.section_id for section in snapshot.sections)
    family_ids = _sorted_unique(
        (
            *(
                family_id
                for descriptor in snapshot.provider_descriptors
                for family_id in descriptor.family_ids
            ),
            *(section.family_id for section in snapshot.sections),
            *(
                legend.family_id
                for section in snapshot.sections
                for legend in section.legends
            ),
        )
    )
    object_kinds = _sorted_unique(
        (
            *(
                object_kind
                for descriptor in snapshot.provider_descriptors
                for object_kind in descriptor.object_kinds
            ),
            *(section.object_kind for section in snapshot.sections),
            *(summary.object_ref.object_kind for summary in summaries),
            *(
                relationship.source_ref.object_kind
                for relationship in relationships
            ),
            *(
                relationship.target_ref.object_kind
                for relationship in relationships
            ),
        )
    )
    degraded = bool(errors or blockers)
    status = (
        RuntimeSectionStatus.DEGRADED
        if degraded
        else RuntimeSectionStatus.OK
    )
    return RuntimeSectionSummary(
        section_id="object_map",
        status=status,
        count=len(summaries),
        message=_object_map_summary_message(len(summaries), len(snapshot.sections)),
        metadata={
            "available": True,
            "provider_count": len(snapshot.provider_descriptors),
            "section_count": len(snapshot.sections),
            "object_count": len(summaries),
            "relationship_count": len(relationships),
            "family_ids": family_ids,
            "object_kinds": object_kinds,
            "provider_ids": provider_ids,
            "section_ids": section_ids,
            "warning_count": len(warnings),
            "error_count": len(errors),
            "blocker_count": len(blockers),
            "warnings": _bounded_diagnostics(warnings),
            "errors": _bounded_diagnostics(errors),
            "blockers": _bounded_diagnostics(blockers),
            "degraded": degraded,
        },
    )


def _object_map_summary_message(object_count: int, section_count: int) -> str:
    object_label = "object" if object_count == 1 else "objects"
    section_label = "section" if section_count == 1 else "sections"
    return f"{object_count} Object Map {object_label}, {section_count} {section_label}"


def _object_map_failure_diagnostic(error: BaseException) -> str:
    error_type = _safe_exception_type_name(error)
    message = _bounded_text(
        _sanitize_diagnostic(_exception_message_text(error)),
        max_length=_MAX_OBJECT_MAP_DIAGNOSTIC_LENGTH,
    )
    return f"Object Map snapshot provider failed: {error_type}: {message}"


def _safe_exception_type_name(error: BaseException) -> str:
    name = type(error).__name__
    return name if name.isidentifier() else "Exception"


def _exception_message_text(error: BaseException) -> str:
    args = getattr(error, "args", ())
    if not args:
        return "<no message>"
    return " ".join(_argument_text(arg) for arg in args)


def _argument_text(value: object) -> str:
    text = str(value)
    return text if text.strip() else "<blank message>"


def _bounded_diagnostics(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        _bounded_text(
            value,
            max_length=_MAX_OBJECT_MAP_DIAGNOSTIC_LENGTH,
        )
        for value in values[:_MAX_OBJECT_MAP_DIAGNOSTICS]
    )


def _sanitized_unique_diagnostics(values: tuple[str, ...]) -> tuple[str, ...]:
    return _unique_texts(tuple(_sanitize_diagnostic(value) for value in values))


def _sanitize_diagnostic(message: str) -> str:
    collapsed = " ".join(message.split())
    redacted = _BEARER_VALUE_PATTERN.sub(f"Bearer {_REDACTED_VALUE}", collapsed)
    redacted = _SENSITIVE_KEY_VALUE_PATTERN.sub(
        lambda match: f"{match.group(1)}{_REDACTED_VALUE}",
        redacted,
    )
    redacted = _WINDOWS_PATH_PATTERN.sub(_REDACTED_PATH, redacted)
    redacted = _POSIX_PATH_PATTERN.sub(_REDACTED_PATH, redacted)
    return redacted


def _bounded_text(message: str, *, max_length: int) -> str:
    if len(message) <= max_length:
        return message
    suffix = "..."
    return f"{message[: max_length - len(suffix)].rstrip()}{suffix}"


def _unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return tuple(unique)


def _sorted_unique(values: object) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for value in values
                if isinstance(value, str) and value
            }
        )
    )


def _sink_failure_preview(
    failure: AuditSinkFailure,
) -> AuditSinkFailurePreview:
    return AuditSinkFailurePreview(
        sink_name=failure.sink_name,
        operation=failure.operation,
        exception_type=failure.exception_type,
        message=failure.message,
        event_id=failure.event_id,
    )
