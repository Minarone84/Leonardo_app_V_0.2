"""Read-only Runtime Manager backend snapshots for Leonardo V2 Core."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from leonardo.contracts.audit import AuditEvent
from leonardo.contracts.connections import ConnectionLifecycleStatus
from leonardo.contracts.inspection import (
    AuditEventPreview,
    AuditSinkFailurePreview,
    ContractRegistrySummary,
    RuntimeManagerSnapshot,
    RuntimeSectionStatus,
    RuntimeSectionSummary,
)
from leonardo.contracts.kernel import ContractStatus
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
from leonardo.core.download_manager import DownloadManager
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.process_manager import ProcessManager
from leonardo.core.service_registry import ServiceRegistry
from leonardo.core.session_manager import SessionManager
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager
from leonardo.core.window_registry import WindowRegistry


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
        if recent_audit_limit < 1:
            raise ValueError("recent_audit_limit must be greater than zero")

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
