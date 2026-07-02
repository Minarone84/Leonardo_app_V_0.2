"""Runtime state store for the Leonardo V2 Core foundation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.identity import ActorOrigin
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

    def __init__(self, audit_log: AuditLog) -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        self._audit_log = audit_log
        self._app_state = AppRuntimeState()
        self._service_states: dict[str, ServiceRuntimeState] = {}
        self._task_states: dict[str, TaskRuntimeState] = {}

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
