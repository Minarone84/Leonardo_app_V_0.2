import pytest

from leonardo.contracts.identity import Permission, UserRef, UserRole
from leonardo.core.audit_log import AuditLog
from leonardo.core.session_manager import (
    SessionManager,
    create_development_administrator_session,
)
from leonardo.core.user_policy import UserPolicy


def test_development_administrator_session_is_stable_and_audited() -> None:
    audit_log = AuditLog()
    manager = SessionManager(audit_log=audit_log)

    first = manager.current_session
    second = manager.current_session

    assert first is second
    assert first.actor.user_id == "admin-dev"
    assert UserRole.ADMINISTRATOR in first.actor.roles
    assert audit_log.snapshot()[0].event_type == "session.started"


def test_user_policy_allows_administrator_all_permissions() -> None:
    session = create_development_administrator_session()
    policy = UserPolicy()

    assert policy.has_permission(session.actor, Permission.SERVICE_MANAGE) is True
    assert policy.has_permission(session.actor, Permission.GUI_SETTINGS_MANAGE) is True


def test_user_policy_requires_explicit_non_admin_permission() -> None:
    user = UserRef(
        user_id="runtime-user",
        username="Runtime User",
        roles=(UserRole.USER,),
        permissions=(Permission.RUNTIME_VIEW,),
    )
    policy = UserPolicy()

    assert policy.has_permission(user, Permission.RUNTIME_VIEW) is True
    assert policy.has_permission(user, Permission.SERVICE_MANAGE) is False
    with pytest.raises(PermissionError):
        policy.require_permission(user, Permission.SERVICE_MANAGE)
