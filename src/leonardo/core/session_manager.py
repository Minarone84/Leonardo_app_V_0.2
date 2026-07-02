"""Session manager for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from datetime import UTC, datetime

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.identity import (
    ActorOrigin,
    SessionContext,
    UserRef,
    UserRole,
)
from leonardo.core.audit_log import AuditLog


def create_development_administrator_session(
    *,
    session_id: str = "session-admin-dev",
    started_at_utc: datetime | None = None,
) -> SessionContext:
    """
    Create the development Administrator session used by the initial runtime.

    The session is a development identity only. It does not imply password,
    credential, or external authentication support.
    """

    actor = UserRef(
        user_id="admin-dev",
        username="Administrator",
        first_name="Administrator",
        roles=(UserRole.ADMINISTRATOR,),
        metadata={"development": True},
    )
    return SessionContext(
        session_id=session_id,
        actor=actor,
        origin=ActorOrigin.DEVELOPMENT,
        started_at_utc=started_at_utc or datetime.now(UTC),
        metadata={"development": True},
    )


class SessionManager:
    """Own the current Core runtime session identity."""

    def __init__(
        self,
        *,
        audit_log: AuditLog | None = None,
        session_context: SessionContext | None = None,
    ) -> None:
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        if session_context is not None and not isinstance(session_context, SessionContext):
            raise TypeError("session_context must be a SessionContext")
        self._audit_log = audit_log
        self._current_session = (
            session_context
            if session_context is not None
            else create_development_administrator_session()
        )
        self._emit_session_started()

    @property
    def current_session(self) -> SessionContext:
        """Return the stable session context for the current runtime."""

        return self._current_session

    def _emit_session_started(self) -> None:
        if self._audit_log is None:
            return
        session = self._current_session
        self._audit_log.emit(
            AuditEvent(
                event_type="session.started",
                message=f"Session started for {session.actor.display_name}",
                severity=AuditSeverity.INFO,
                category=AuditCategory.SESSION,
                actor_id=session.actor_id,
                session_id=session.session_id,
                origin=session.origin,
                payload={
                    "username": session.actor.username,
                    "roles": [role.value for role in session.actor.roles],
                },
            )
        )
