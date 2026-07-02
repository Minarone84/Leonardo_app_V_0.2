"""Error router for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from leonardo.contracts.audit import (
    AuditCategory,
    AuditErrorPayload,
    AuditEvent,
    AuditSeverity,
)
from leonardo.contracts.errors import ErrorReport, ErrorSeverity
from leonardo.contracts.identity import SessionContext
from leonardo.core.audit_log import AuditLog


class ErrorRouter:
    """
    Convert runtime errors into structured reports and audit events.

    The router reports errors; it does not suppress exceptions raised by callers
    or by the configured audit log.
    """

    def __init__(
        self,
        audit_log: AuditLog,
        *,
        session_context_provider: Callable[[], SessionContext | None] | None = None,
    ) -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        self._audit_log = audit_log
        self._session_context_provider = session_context_provider

    def route_exception(
        self,
        exception: BaseException,
        *,
        message: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        session_id: str | None = None,
        correlation_id: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> ErrorReport:
        """Create and audit an error report for an exception."""

        if not isinstance(exception, BaseException):
            raise TypeError("exception must be a BaseException")
        report = ErrorReport(
            message=message or str(exception) or type(exception).__name__,
            severity=severity,
            exception_type=type(exception).__name__,
            exception_message=str(exception),
            session_id=session_id or self._current_session_id(),
            correlation_id=correlation_id,
            context=context or {},
        )
        self._emit_error_report(report)
        return report

    def route_error(
        self,
        message: str,
        *,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        session_id: str | None = None,
        correlation_id: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> ErrorReport:
        """Create and audit an explicit runtime error report."""

        report = ErrorReport(
            message=message,
            severity=severity,
            session_id=session_id or self._current_session_id(),
            correlation_id=correlation_id,
            context=context or {},
        )
        self._emit_error_report(report)
        return report

    def _current_session_id(self) -> str | None:
        if self._session_context_provider is None:
            return None
        session = self._session_context_provider()
        if session is None:
            return None
        if not isinstance(session, SessionContext):
            raise TypeError("session_context_provider must return SessionContext or None")
        return session.session_id

    def _emit_error_report(self, report: ErrorReport) -> None:
        self._audit_log.emit(
            AuditEvent(
                event_type="error.reported",
                message=report.message,
                severity=_audit_severity(report.severity),
                category=AuditCategory.ERROR,
                session_id=report.session_id,
                correlation_id=report.correlation_id,
                payload={
                    "error_id": report.error_id,
                    "severity": report.severity,
                    "context": dict(report.context),
                },
                error=AuditErrorPayload(
                    exception_type=report.exception_type,
                    message=report.exception_message or report.message,
                ),
            )
        )


def _audit_severity(severity: ErrorSeverity) -> AuditSeverity:
    if not isinstance(severity, ErrorSeverity):
        raise TypeError("severity must be an ErrorSeverity")
    if severity is ErrorSeverity.INFO:
        return AuditSeverity.INFO
    if severity is ErrorSeverity.WARNING:
        return AuditSeverity.WARNING
    if severity is ErrorSeverity.CRITICAL:
        return AuditSeverity.CRITICAL
    return AuditSeverity.ERROR
