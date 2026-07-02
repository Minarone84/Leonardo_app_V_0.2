"""Runtime state store for the Leonardo V2 Core foundation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.gui import (
    ActionTriggerRecord,
    WindowDefinition,
    WindowLifecycleStatus,
    WindowRuntimeState,
)
from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.operations import OperationRuntimeState
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
