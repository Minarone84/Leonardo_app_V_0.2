"""Single boundary for converting failures into durable audit evidence."""

from __future__ import annotations

from collections.abc import Mapping

from leonardo.audit import AuditEventV1
from leonardo.core.audit_log import AuditLog


class ErrorRouter:
    def __init__(self, audit_log: AuditLog, *, actor_id: str = "local-user") -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        self._audit_log = audit_log
        self._actor_id = actor_id

    def route_exception(
        self,
        exc: Exception,
        *,
        message: str,
        category: str = "error",
        severity: str = "error",
        task_id: str | None = None,
        process_id: str | None = None,
        connection_id: str | None = None,
        correlation_id: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> AuditEventV1:
        if not isinstance(exc, Exception):
            raise TypeError("exc must be an Exception")
        event = AuditEventV1(
            event_type="error.reported",
            message=message,
            category=category,
            severity=severity,
            actor_id=self._actor_id,
            task_id=task_id,
            process_id=process_id,
            connection_id=connection_id,
            correlation_id=correlation_id,
            details=dict(context or {}),
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        self._audit_log.emit(event)
        return event
