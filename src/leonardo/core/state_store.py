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
        """Return an immutable snapshot of current app and service state."""

        return RuntimeSnapshot(
            app_state=self._app_state,
            service_states=tuple(
                self._service_states[service_id]
                for service_id in sorted(self._service_states)
            ),
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
