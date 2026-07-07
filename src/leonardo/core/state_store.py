"""Runtime state store for the Leonardo V2 Core foundation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionLifecycleStatus,
    ConnectionRuntimeState,
    WebSocketChannelDefinition,
    WebSocketChannelRuntimeState,
)
from leonardo.contracts.gui import (
    ActionTriggerRecord,
    WindowDefinition,
    WindowLifecycleStatus,
    WindowRuntimeState,
)
from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.operations import OperationRuntimeState
from leonardo.contracts.processes import (
    ProcessLaunchRequest,
    ProcessLifecycleStatus,
    ProcessRuntimeState,
)
from leonardo.contracts.runtime import (
    AppLifecycleStatus,
    AppRuntimeState,
    RuntimeSnapshot,
    ServiceLifecycleStatus,
    ServiceRuntimeState,
    TaskLifecycleStatus,
    TaskRuntimeState,
)
from leonardo.core.audit_log import AuditLog


class StateStore:
    """
    Own current runtime state for the Core application and registered services.

    Runtime state is current truth. Audit events emitted by this store are
    historical truth and do not replace the current-state snapshot.
    """

    def __init__(self, audit_log: AuditLog, *, recent_action_limit: int = 100) -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        if recent_action_limit < 1:
            raise ValueError("recent_action_limit must be greater than zero")
        self._audit_log = audit_log
        self._recent_action_limit = recent_action_limit
        self._app_state = AppRuntimeState()
        self._service_states: dict[str, ServiceRuntimeState] = {}
        self._task_states: dict[str, TaskRuntimeState] = {}
        self._window_states: dict[str, WindowRuntimeState] = {}
        self._recent_action_triggers: list[ActionTriggerRecord] = []
        self._operation_states: dict[str, OperationRuntimeState] = {}
        self._process_states: dict[str, ProcessRuntimeState] = {}
        self._connection_states: dict[str, ConnectionRuntimeState] = {}
        self._websocket_channel_states: dict[str, WebSocketChannelRuntimeState] = {}

    def get_app_state(self) -> AppRuntimeState:
        """Return the current application runtime state."""

        return self._app_state

    def get_app_status(self) -> AppLifecycleStatus:
        """Return the current application lifecycle status."""

        return self._app_state.status

    def set_app_lifecycle_status(
        self,
        status: AppLifecycleStatus,
        *,
        message: str = "",
    ) -> AppRuntimeState:
        """Set the application lifecycle status and audit meaningful changes."""

        if not isinstance(status, AppLifecycleStatus):
            raise TypeError("status must be an AppLifecycleStatus")
        previous = self._app_state
        if previous.status is status:
            return previous

        now = datetime.now(UTC)
        started_at = previous.started_at_utc
        stopped_at = previous.stopped_at_utc
        if status in {AppLifecycleStatus.STARTING, AppLifecycleStatus.RUNNING}:
            started_at = started_at or now
        if status is AppLifecycleStatus.STOPPED:
            stopped_at = now

        self._app_state = replace(
            previous,
            status=status,
            last_updated_utc=now,
            started_at_utc=started_at,
            stopped_at_utc=stopped_at,
        )
        self._emit_transition_event(
            event_type="app.lifecycle.changed",
            message=message or f"Application status changed to {status.value}",
            payload={
                "old_status": previous.status,
                "new_status": status,
            },
            failed=status is AppLifecycleStatus.FAILED,
        )
        return self._app_state

    def register_service_runtime_state(
        self,
        service_id: str,
        *,
        status: ServiceLifecycleStatus = ServiceLifecycleStatus.REGISTERED,
        message: str = "",
    ) -> ServiceRuntimeState:
        """Register current runtime state for a service."""

        if not service_id or not service_id.strip():
            raise ValueError("service_id must be a non-empty string")
        if service_id in self._service_states:
            raise ValueError(f"Service runtime state already registered: {service_id}")
        if not isinstance(status, ServiceLifecycleStatus):
            raise TypeError("status must be a ServiceLifecycleStatus")

        state = ServiceRuntimeState(
            service_id=service_id,
            status=status,
            message=message,
        )
        self._service_states[service_id] = state
        self._emit_transition_event(
            event_type="service.runtime.registered",
            message=message or f"Service runtime state registered: {service_id}",
            payload={
                "service_id": service_id,
                "new_status": status,
            },
            failed=status is ServiceLifecycleStatus.FAILED,
        )
        return state

    def set_service_lifecycle_status(
        self,
        service_id: str,
        status: ServiceLifecycleStatus,
        *,
        message: str = "",
    ) -> ServiceRuntimeState:
        """Set lifecycle status for a registered service runtime state."""

        if not isinstance(status, ServiceLifecycleStatus):
            raise TypeError("status must be a ServiceLifecycleStatus")
        previous = self._service_states.get(service_id)
        if previous is None:
            raise KeyError(f"Service runtime state is not registered: {service_id}")
        if previous.status is status:
            return previous

        state = replace(
            previous,
            status=status,
            last_updated_utc=datetime.now(UTC),
            message=message,
        )
        self._service_states[service_id] = state
        self._emit_transition_event(
            event_type="service.lifecycle.changed",
            message=message or f"Service status changed to {status.value}",
            payload={
                "service_id": service_id,
                "old_status": previous.status,
                "new_status": status,
            },
            failed=status is ServiceLifecycleStatus.FAILED,
        )
        return state

    def runtime_snapshot(self) -> RuntimeSnapshot:
        """Return an immutable snapshot of current app, service, and task state."""

        return RuntimeSnapshot(
            app_state=self._app_state,
            service_states=tuple(
                self._service_states[service_id]
                for service_id in sorted(self._service_states)
            ),
            task_states=self.tasks_state(),
            window_states=self.windows_state(),
            recent_action_triggers=self.recent_action_triggers(),
            operation_states=self.operations_state(),
            process_states=self.processes_state(),
            connection_states=self.connection_states(),
            websocket_channel_states=self.websocket_channel_states(),
        )

    def task_started(
        self,
        *,
        task_id: str,
        task_name: str,
        operation_id: str | None = None,
        service_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> TaskRuntimeState:
        """Register an active task and emit a start audit event."""

        if task_id in self._task_states:
            raise ValueError(f"Task runtime state already registered: {task_id}")
        now = datetime.now(UTC)
        state = TaskRuntimeState(
            task_id=task_id,
            task_name=task_name,
            status=TaskLifecycleStatus.RUNNING,
            started_at_utc=now,
            updated_at_utc=now,
            operation_id=operation_id,
            service_id=service_id,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        self._task_states[task_id] = state
        self._emit_task_event(
            state,
            event_type="task.lifecycle.started",
            message=f"Task started: {task_name}",
            failed=False,
        )
        return state

    def task_cancel_requested(self, task_id: str) -> TaskRuntimeState:
        """Mark an active task as cancellation-requested."""

        previous = self._require_task_state(task_id)
        state = replace(
            previous,
            status=TaskLifecycleStatus.CANCEL_REQUESTED,
            updated_at_utc=datetime.now(UTC),
        )
        self._task_states[task_id] = state
        self._emit_task_event(
            state,
            event_type="task.lifecycle.cancel_requested",
            message=f"Task cancellation requested: {state.task_name}",
            failed=False,
        )
        return state

    def task_completed(self, task_id: str) -> TaskRuntimeState:
        """Record successful task completion and remove active runtime state."""

        previous = self._require_task_state(task_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=TaskLifecycleStatus.COMPLETED,
            updated_at_utc=now,
            completed_at_utc=now,
        )
        del self._task_states[task_id]
        self._emit_task_event(
            state,
            event_type="task.lifecycle.completed",
            message=f"Task completed: {state.task_name}",
            failed=False,
        )
        return state

    def task_failed(self, task_id: str, error_message: str) -> TaskRuntimeState:
        """Record task failure and remove active runtime state."""

        previous = self._require_task_state(task_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=TaskLifecycleStatus.FAILED,
            updated_at_utc=now,
            completed_at_utc=now,
            error_message=error_message,
        )
        del self._task_states[task_id]
        self._emit_task_event(
            state,
            event_type="task.lifecycle.failed",
            message=f"Task failed: {state.task_name}",
            failed=True,
        )
        return state

    def task_cancelled(self, task_id: str) -> TaskRuntimeState:
        """Record task cancellation and remove active runtime state."""

        previous = self._require_task_state(task_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=TaskLifecycleStatus.CANCELLED,
            updated_at_utc=now,
            completed_at_utc=now,
        )
        del self._task_states[task_id]
        self._emit_task_event(
            state,
            event_type="task.lifecycle.cancelled",
            message=f"Task cancelled: {state.task_name}",
            failed=False,
        )
        return state

    def tasks_state(self) -> tuple[TaskRuntimeState, ...]:
        """Return active task runtime states in deterministic task-id order."""

        return tuple(
            self._task_states[task_id]
            for task_id in sorted(self._task_states)
        )

    def window_opened(
        self,
        definition: WindowDefinition,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> WindowRuntimeState:
        """Register an open window runtime state and emit an audit event."""

        if not isinstance(definition, WindowDefinition):
            raise TypeError("definition must be a WindowDefinition")
        if definition.window_id in self._window_states:
            raise ValueError(f"Window runtime state already open: {definition.window_id}")
        now = datetime.now(UTC)
        state = WindowRuntimeState(
            window_id=definition.window_id,
            title=definition.title,
            window_type=definition.window_type,
            status=WindowLifecycleStatus.OPEN,
            opened_at_utc=now,
            updated_at_utc=now,
            owner_action_id=owner_action_id,
            current_operation_id=current_operation_id,
            metadata=metadata or dict(definition.metadata),
        )
        self._window_states[state.window_id] = state
        self._emit_window_event(
            state,
            event_type="gui.window.opened",
            message=f"Window opened: {state.title}",
        )
        return state

    def window_focused(self, window_id: str) -> WindowRuntimeState:
        """Record focus intent for an open window identity."""

        previous = self._require_window_state(window_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=WindowLifecycleStatus.FOCUSED,
            updated_at_utc=now,
            last_focus_at_utc=now,
        )
        self._window_states[window_id] = state
        self._emit_window_event(
            state,
            event_type="gui.window.focused",
            message=f"Window focused: {state.title}",
        )
        return state

    def window_close_requested(self, window_id: str) -> WindowRuntimeState:
        """Record close-request intent for an open window identity."""

        previous = self._require_window_state(window_id)
        state = replace(
            previous,
            status=WindowLifecycleStatus.CLOSE_REQUESTED,
            updated_at_utc=datetime.now(UTC),
        )
        self._window_states[window_id] = state
        self._emit_window_event(
            state,
            event_type="gui.window.close_requested",
            message=f"Window close requested: {state.title}",
        )
        return state

    def window_closed(self, window_id: str) -> WindowRuntimeState:
        """Record closed window history and remove open runtime state."""

        previous = self._require_window_state(window_id)
        state = replace(
            previous,
            status=WindowLifecycleStatus.CLOSED,
            updated_at_utc=datetime.now(UTC),
        )
        del self._window_states[window_id]
        self._emit_window_event(
            state,
            event_type="gui.window.closed",
            message=f"Window closed: {state.title}",
        )
        return state

    def windows_state(self) -> tuple[WindowRuntimeState, ...]:
        """Return open window states in deterministic window-id order."""

        return tuple(
            self._window_states[window_id]
            for window_id in sorted(self._window_states)
        )

    def action_triggered(self, record: ActionTriggerRecord) -> ActionTriggerRecord:
        """Record an action trigger and emit an audit event."""

        if not isinstance(record, ActionTriggerRecord):
            raise TypeError("record must be an ActionTriggerRecord")
        self._recent_action_triggers.append(record)
        if len(self._recent_action_triggers) > self._recent_action_limit:
            self._recent_action_triggers = self._recent_action_triggers[
                -self._recent_action_limit :
            ]
        self._audit_log.emit(
            AuditEvent(
                event_type="gui.action.triggered",
                message=f"Action triggered: {record.action_id}",
                severity=AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                actor_id=record.actor_id,
                session_id=record.session_id,
                origin=record.origin,
                window_id=record.window_id,
                action_id=record.action_id,
                correlation_id=record.correlation_id,
                payload={
                    "action_id": record.action_id,
                    "metadata": dict(record.metadata),
                },
            )
        )
        return record

    def recent_action_triggers(self) -> tuple[ActionTriggerRecord, ...]:
        """Return bounded recent action trigger records."""

        return tuple(self._recent_action_triggers)

    def operation_state_changed(
        self,
        state: OperationRuntimeState,
        *,
        event_type: str,
        message: str = "",
        failed: bool = False,
    ) -> OperationRuntimeState:
        """Apply an operation state transition and emit audit history."""

        if not isinstance(state, OperationRuntimeState):
            raise TypeError("state must be an OperationRuntimeState")
        if state.is_terminal:
            self._operation_states.pop(state.operation_id, None)
        else:
            self._operation_states[state.operation_id] = state
        self._emit_operation_event(
            state,
            event_type=event_type,
            message=message or f"Operation status changed to {state.status.value}",
            failed=failed,
        )
        return state

    def operations_state(self) -> tuple[OperationRuntimeState, ...]:
        """Return active operation states in deterministic operation-id order."""

        return tuple(
            self._operation_states[operation_id]
            for operation_id in sorted(self._operation_states)
        )

    def process_starting(
        self,
        request: ProcessLaunchRequest,
    ) -> ProcessRuntimeState:
        """Register a process launch attempt as active runtime state."""

        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("request must be a ProcessLaunchRequest")
        if request.process_id in self._process_states:
            raise ValueError(
                f"Process runtime state already registered: {request.process_id}"
            )
        now = datetime.now(UTC)
        state = ProcessRuntimeState(
            process_id=request.process_id,
            label=request.label,
            kind=request.kind,
            status=ProcessLifecycleStatus.STARTING,
            command=request.command,
            updated_at_utc=now,
            operation_id=request.operation_id,
            task_id=request.task_id,
            service_id=request.service_id,
            correlation_id=request.correlation_id,
            metadata=request.metadata,
        )
        self._process_states[state.process_id] = state
        self._emit_process_event(
            state,
            event_type="process.lifecycle.starting",
            message=f"Process starting: {state.label}",
            failed=False,
        )
        return state

    def process_running(
        self,
        process_id: str,
        *,
        pid: int | None,
    ) -> ProcessRuntimeState:
        """Mark an active process as running."""

        previous = self._require_process_state(process_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=ProcessLifecycleStatus.RUNNING,
            pid=pid,
            started_at_utc=previous.started_at_utc or now,
            updated_at_utc=now,
        )
        self._process_states[process_id] = state
        self._emit_process_event(
            state,
            event_type="process.lifecycle.running",
            message=f"Process running: {state.label}",
            failed=False,
        )
        return state

    def process_stop_requested(self, process_id: str) -> ProcessRuntimeState:
        """Mark an active process as requested to stop."""

        previous = self._require_process_state(process_id)
        state = replace(
            previous,
            status=ProcessLifecycleStatus.STOP_REQUESTED,
            updated_at_utc=datetime.now(UTC),
        )
        self._process_states[process_id] = state
        self._emit_process_event(
            state,
            event_type="process.lifecycle.stop_requested",
            message=f"Process stop requested: {state.label}",
            failed=False,
        )
        return state

    def process_stopped(
        self,
        process_id: str,
        *,
        exit_code: int | None,
    ) -> ProcessRuntimeState:
        """Record process completion and remove active runtime state."""

        return self._terminal_process_transition(
            process_id,
            ProcessLifecycleStatus.STOPPED,
            "process.lifecycle.stopped",
            exit_code=exit_code,
        )

    def process_failed(
        self,
        process_id: str,
        *,
        exit_code: int | None = None,
        error_message: str,
    ) -> ProcessRuntimeState:
        """Record process failure and remove active runtime state."""

        return self._terminal_process_transition(
            process_id,
            ProcessLifecycleStatus.FAILED,
            "process.lifecycle.failed",
            exit_code=exit_code,
            error_message=error_message,
            failed=True,
        )

    def process_killed(
        self,
        process_id: str,
        *,
        exit_code: int | None = None,
        error_message: str = "",
    ) -> ProcessRuntimeState:
        """Record forced process termination and remove active runtime state."""

        return self._terminal_process_transition(
            process_id,
            ProcessLifecycleStatus.KILLED,
            "process.lifecycle.killed",
            exit_code=exit_code,
            error_message=error_message,
            failed=True,
        )

    def processes_state(self) -> tuple[ProcessRuntimeState, ...]:
        """Return active process runtime states in deterministic order."""

        return tuple(
            self._process_states[process_id]
            for process_id in sorted(self._process_states)
        )

    def connection_registered(
        self,
        definition: ConnectionDefinition,
    ) -> ConnectionRuntimeState:
        """Register a tracked connection as current runtime state."""

        if not isinstance(definition, ConnectionDefinition):
            raise TypeError("definition must be a ConnectionDefinition")
        if definition.connection_id in self._connection_states:
            raise ValueError(
                "Connection runtime state already registered: "
                f"{definition.connection_id}"
            )
        now = datetime.now(UTC)
        state = ConnectionRuntimeState(
            connection_id=definition.connection_id,
            label=definition.label,
            kind=definition.kind,
            protocol=definition.protocol,
            direction=definition.direction,
            status=ConnectionLifecycleStatus.REGISTERED,
            registered_at_utc=now,
            updated_at_utc=now,
            service_id=definition.service_id,
            process_id=definition.process_id,
            metadata=definition.metadata,
        )
        self._connection_states[state.connection_id] = state
        self._emit_connection_event(
            state,
            event_type="connection.lifecycle.registered",
            message=f"Connection registered: {state.label}",
            failed=False,
        )
        return state

    def connection_connecting(
        self,
        connection_id: str,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Mark a tracked connection as attempting readiness."""

        return self._set_connection_status(
            connection_id,
            ConnectionLifecycleStatus.CONNECTING,
            event_type="connection.lifecycle.connecting",
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def connection_connected(
        self,
        connection_id: str,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Mark a tracked connection as ready."""

        return self._set_connection_status(
            connection_id,
            ConnectionLifecycleStatus.CONNECTED,
            event_type="connection.lifecycle.connected",
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def connection_degraded(
        self,
        connection_id: str,
        *,
        last_error_message: str,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Mark a tracked connection as degraded with diagnostic text."""

        return self._set_connection_status(
            connection_id,
            ConnectionLifecycleStatus.DEGRADED,
            event_type="connection.lifecycle.degraded",
            last_error_message=last_error_message,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def connection_disconnect_requested(
        self,
        connection_id: str,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Mark a tracked connection as requested to stop."""

        return self._set_connection_status(
            connection_id,
            ConnectionLifecycleStatus.DISCONNECT_REQUESTED,
            event_type="connection.lifecycle.disconnect_requested",
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def connection_disconnected(
        self,
        connection_id: str,
        *,
        message: str = "",
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Mark a tracked connection as stopped while retaining last-known state."""

        return self._set_connection_status(
            connection_id,
            ConnectionLifecycleStatus.DISCONNECTED,
            event_type="connection.lifecycle.disconnected",
            message=message,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def connection_failed(
        self,
        connection_id: str,
        *,
        last_error_message: str,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Mark a tracked connection as failed while retaining last-known state."""

        return self._set_connection_status(
            connection_id,
            ConnectionLifecycleStatus.FAILED,
            event_type="connection.lifecycle.failed",
            last_error_message=last_error_message,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
            failed=True,
        )

    def connection_heartbeat(
        self,
        connection_id: str,
        *,
        timestamp_utc: datetime | None = None,
    ) -> ConnectionRuntimeState:
        """Record the latest observed heartbeat timestamp for a connection."""

        previous = self._require_connection_state(connection_id)
        timestamp = _coerce_utc(
            timestamp_utc if timestamp_utc is not None else datetime.now(UTC),
            "timestamp_utc",
        )
        state = replace(
            previous,
            updated_at_utc=timestamp,
            last_heartbeat_at_utc=timestamp,
        )
        self._connection_states[connection_id] = state
        return state

    def connection_states(self) -> tuple[ConnectionRuntimeState, ...]:
        """Return connection runtime states in deterministic order."""

        return tuple(
            self._connection_states[connection_id]
            for connection_id in sorted(self._connection_states)
        )

    def websocket_channel_registered(
        self,
        definition: WebSocketChannelDefinition,
    ) -> WebSocketChannelRuntimeState:
        """Register a tracked WebSocket channel under a known connection."""

        if not isinstance(definition, WebSocketChannelDefinition):
            raise TypeError("definition must be a WebSocketChannelDefinition")
        if definition.channel_id in self._websocket_channel_states:
            raise ValueError(
                "WebSocket channel runtime state already registered: "
                f"{definition.channel_id}"
            )
        parent = self._require_connection_state(definition.connection_id)
        now = datetime.now(UTC)
        state = WebSocketChannelRuntimeState(
            channel_id=definition.channel_id,
            connection_id=definition.connection_id,
            label=definition.label,
            status=parent.status,
            registered_at_utc=now,
            updated_at_utc=now,
            metadata=definition.metadata,
        )
        self._websocket_channel_states[state.channel_id] = state
        self._emit_channel_event(
            state,
            event_type="connection.channel.registered",
            message=f"WebSocket channel registered: {state.label}",
            failed=False,
        )
        return state

    def websocket_channel_received(
        self,
        channel_id: str,
        *,
        count: int = 1,
        timestamp_utc: datetime | None = None,
    ) -> WebSocketChannelRuntimeState:
        """Record received message count for a tracked WebSocket channel."""

        return self._update_channel_counter(
            channel_id,
            field_name="received_count",
            count=count,
            timestamp_utc=timestamp_utc,
        )

    def websocket_channel_sent(
        self,
        channel_id: str,
        *,
        count: int = 1,
        timestamp_utc: datetime | None = None,
    ) -> WebSocketChannelRuntimeState:
        """Record sent message count for a tracked WebSocket channel."""

        return self._update_channel_counter(
            channel_id,
            field_name="sent_count",
            count=count,
            timestamp_utc=timestamp_utc,
        )

    def websocket_channel_error(
        self,
        channel_id: str,
        *,
        count: int = 1,
        timestamp_utc: datetime | None = None,
    ) -> WebSocketChannelRuntimeState:
        """Record error count for a tracked WebSocket channel."""

        return self._update_channel_counter(
            channel_id,
            field_name="error_count",
            count=count,
            timestamp_utc=timestamp_utc,
            status=ConnectionLifecycleStatus.DEGRADED,
        )

    def websocket_channel_states(self) -> tuple[WebSocketChannelRuntimeState, ...]:
        """Return WebSocket channel runtime states in deterministic order."""

        return tuple(
            self._websocket_channel_states[channel_id]
            for channel_id in sorted(self._websocket_channel_states)
        )

    def _set_connection_status(
        self,
        connection_id: str,
        status: ConnectionLifecycleStatus,
        *,
        event_type: str,
        message: str = "",
        last_error_message: str | None = None,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
        failed: bool = False,
    ) -> ConnectionRuntimeState:
        previous = self._require_connection_state(connection_id)
        now = datetime.now(UTC)
        connected_at = previous.connected_at_utc
        disconnected_at = previous.disconnected_at_utc
        if status is ConnectionLifecycleStatus.CONNECTED:
            connected_at = connected_at or now
            disconnected_at = None
        if status.is_terminal:
            disconnected_at = now

        state = replace(
            previous,
            status=status,
            updated_at_utc=now,
            connected_at_utc=connected_at,
            disconnected_at_utc=disconnected_at,
            last_error_message=(
                last_error_message
                if last_error_message is not None
                else previous.last_error_message
            ),
            operation_id=(
                operation_id if operation_id is not None else previous.operation_id
            ),
            task_id=task_id if task_id is not None else previous.task_id,
            correlation_id=(
                correlation_id if correlation_id is not None else previous.correlation_id
            ),
        )
        self._connection_states[connection_id] = state
        self._set_channel_status_for_connection(state.connection_id, status, now)
        self._emit_connection_event(
            state,
            event_type=event_type,
            message=(
                message
                or f"Connection status changed to {status.value}: {state.label}"
            ),
            failed=failed,
        )
        return state

    def _set_channel_status_for_connection(
        self,
        connection_id: str,
        status: ConnectionLifecycleStatus,
        updated_at_utc: datetime,
    ) -> None:
        for channel_id in sorted(self._websocket_channel_states):
            previous = self._websocket_channel_states[channel_id]
            if previous.connection_id != connection_id:
                continue
            state = replace(
                previous,
                status=status,
                updated_at_utc=updated_at_utc,
            )
            self._websocket_channel_states[channel_id] = state
            self._emit_channel_event(
                state,
                event_type="connection.channel.status_changed",
                message=(
                    "WebSocket channel status changed to "
                    f"{status.value}: {state.label}"
                ),
                failed=status is ConnectionLifecycleStatus.FAILED,
            )

    def _update_channel_counter(
        self,
        channel_id: str,
        *,
        field_name: str,
        count: int,
        timestamp_utc: datetime | None,
        status: ConnectionLifecycleStatus | None = None,
    ) -> WebSocketChannelRuntimeState:
        _validate_positive_int(count, "count")
        previous = self._require_channel_state(channel_id)
        timestamp = _coerce_utc(
            timestamp_utc if timestamp_utc is not None else datetime.now(UTC),
            "timestamp_utc",
        )
        state = replace(
            previous,
            status=status if status is not None else previous.status,
            updated_at_utc=timestamp,
            last_message_at_utc=timestamp,
            **{field_name: getattr(previous, field_name) + count},
        )
        self._websocket_channel_states[channel_id] = state
        return state

    def _emit_transition_event(
        self,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object],
        failed: bool,
    ) -> None:
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=AuditSeverity.ERROR if failed else AuditSeverity.INFO,
                category=AuditCategory.STATE,
                origin=ActorOrigin.SYSTEM,
                payload=payload,
            )
        )

    def _require_task_state(self, task_id: str) -> TaskRuntimeState:
        state = self._task_states.get(task_id)
        if state is None:
            raise KeyError(f"Task runtime state is not registered: {task_id}")
        return state

    def _require_window_state(self, window_id: str) -> WindowRuntimeState:
        state = self._window_states.get(window_id)
        if state is None:
            raise KeyError(f"Window runtime state is not open: {window_id}")
        return state

    def _require_process_state(self, process_id: str) -> ProcessRuntimeState:
        state = self._process_states.get(process_id)
        if state is None:
            raise KeyError(f"Process runtime state is not active: {process_id}")
        return state

    def _require_connection_state(self, connection_id: str) -> ConnectionRuntimeState:
        state = self._connection_states.get(connection_id)
        if state is None:
            raise KeyError(
                f"Connection runtime state is not registered: {connection_id}"
            )
        return state

    def _require_channel_state(
        self,
        channel_id: str,
    ) -> WebSocketChannelRuntimeState:
        state = self._websocket_channel_states.get(channel_id)
        if state is None:
            raise KeyError(
                f"WebSocket channel runtime state is not registered: {channel_id}"
            )
        return state

    def _terminal_process_transition(
        self,
        process_id: str,
        status: ProcessLifecycleStatus,
        event_type: str,
        *,
        exit_code: int | None,
        error_message: str = "",
        failed: bool = False,
    ) -> ProcessRuntimeState:
        previous = self._require_process_state(process_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=status,
            updated_at_utc=now,
            completed_at_utc=now,
            exit_code=exit_code,
            error_message=error_message or previous.error_message,
        )
        del self._process_states[process_id]
        self._emit_process_event(
            state,
            event_type=event_type,
            message=f"Process status changed to {status.value}: {state.label}",
            failed=failed,
        )
        return state

    def _emit_task_event(
        self,
        state: TaskRuntimeState,
        *,
        event_type: str,
        message: str,
        failed: bool,
    ) -> None:
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=AuditSeverity.ERROR if failed else AuditSeverity.INFO,
                category=AuditCategory.STATE,
                origin=ActorOrigin.SYSTEM,
                operation_id=state.operation_id,
                task_id=state.task_id,
                correlation_id=state.correlation_id,
                payload={
                    "task_id": state.task_id,
                    "task_name": state.task_name,
                    "status": state.status,
                    "service_id": state.service_id,
                    "error_message": state.error_message,
                },
            )
        )

    def _emit_window_event(
        self,
        state: WindowRuntimeState,
        *,
        event_type: str,
        message: str,
    ) -> None:
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                origin=ActorOrigin.SYSTEM,
                window_id=state.window_id,
                action_id=state.owner_action_id,
                operation_id=state.current_operation_id,
                payload={
                    "window_id": state.window_id,
                    "title": state.title,
                    "window_type": state.window_type,
                    "status": state.status,
                },
            )
        )

    def _emit_operation_event(
        self,
        state: OperationRuntimeState,
        *,
        event_type: str,
        message: str,
        failed: bool,
    ) -> None:
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=AuditSeverity.ERROR if failed else AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                actor_id=state.actor_id,
                session_id=state.session_id,
                origin=state.origin,
                window_id=state.window_id,
                action_id=state.action_id,
                operation_id=state.operation_id,
                task_id=state.task_id,
                correlation_id=state.correlation_id,
                payload={
                    "operation_id": state.operation_id,
                    "operation_kind": state.operation_kind,
                    "status": state.status,
                    "label": state.label,
                    "task_id": state.task_id,
                    "correlation_id": state.correlation_id,
                    "blockers": tuple(
                        {
                            "code": blocker.code,
                            "message": blocker.message,
                        }
                        for blocker in state.blockers
                    ),
                    "warnings": tuple(
                        {
                            "code": warning.code,
                            "message": warning.message,
                        }
                        for warning in state.warnings
                    ),
                    "error_message": state.error_message,
                },
            )
        )

    def _emit_process_event(
        self,
        state: ProcessRuntimeState,
        *,
        event_type: str,
        message: str,
        failed: bool,
    ) -> None:
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=AuditSeverity.ERROR if failed else AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                origin=ActorOrigin.SYSTEM,
                process_id=state.process_id,
                operation_id=state.operation_id,
                task_id=state.task_id,
                correlation_id=state.correlation_id,
                payload={
                    "process_id": state.process_id,
                    "label": state.label,
                    "kind": state.kind,
                    "status": state.status,
                    "command": state.command,
                    "pid": state.pid,
                    "exit_code": state.exit_code,
                    "service_id": state.service_id,
                    "error_message": state.error_message,
                },
            )
        )

    def _emit_connection_event(
        self,
        state: ConnectionRuntimeState,
        *,
        event_type: str,
        message: str,
        failed: bool,
    ) -> None:
        severity = AuditSeverity.INFO
        if failed:
            severity = AuditSeverity.ERROR
        elif state.status is ConnectionLifecycleStatus.DEGRADED:
            severity = AuditSeverity.WARNING
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=severity,
                category=AuditCategory.RUNTIME,
                origin=ActorOrigin.SYSTEM,
                operation_id=state.operation_id,
                task_id=state.task_id,
                connection_id=state.connection_id,
                correlation_id=state.correlation_id,
                payload={
                    "connection_id": state.connection_id,
                    "label": state.label,
                    "kind": state.kind,
                    "protocol": state.protocol,
                    "direction": state.direction,
                    "status": state.status,
                    "service_id": state.service_id,
                    "process_id": state.process_id,
                    "error_message": state.last_error_message,
                },
            )
        )

    def _emit_channel_event(
        self,
        state: WebSocketChannelRuntimeState,
        *,
        event_type: str,
        message: str,
        failed: bool,
    ) -> None:
        severity = AuditSeverity.ERROR if failed else AuditSeverity.INFO
        if state.status is ConnectionLifecycleStatus.DEGRADED:
            severity = AuditSeverity.WARNING
        self._audit_log.emit(
            AuditEvent(
                event_type=event_type,
                message=message,
                severity=severity,
                category=AuditCategory.RUNTIME,
                origin=ActorOrigin.SYSTEM,
                connection_id=state.connection_id,
                payload={
                    "connection_id": state.connection_id,
                    "channel_id": state.channel_id,
                    "label": state.label,
                    "status": state.status,
                    "received_count": state.received_count,
                    "sent_count": state.sent_count,
                    "error_count": state.error_count,
                },
            )
        )


def _coerce_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _validate_positive_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
