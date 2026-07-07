import pytest

from leonardo.contracts.identity import Permission, UserRef, UserRole
from leonardo.core.session_manager import create_development_administrator_session
from leonardo.core.user_policy import UserPolicy


def test_user_policy_allows_administrator_for_every_defined_permission() -> None:
    policy = UserPolicy()
    user = create_development_administrator_session().actor

    assert all(policy.has_permission(user, permission) for permission in Permission)


def test_user_policy_accepts_canonical_permission_strings() -> None:
    policy = UserPolicy()
    user = UserRef(
        user_id="download-user",
        username="Download User",
        roles=(UserRole.USER,),
        permissions=(Permission.DOWNLOAD_PREVIEW,),
    )

    assert policy.normalize_permission("download:preview") is Permission.DOWNLOAD_PREVIEW
    assert policy.has_permission(user, "download:preview") is True
    assert policy.has_permission(user, Permission.DOWNLOAD_PREVIEW) is True
    assert policy.has_permission(user, "download:execute") is False


def test_user_policy_rejects_unknown_permission_strings() -> None:
    policy = UserPolicy()
    user = create_development_administrator_session().actor

    with pytest.raises(ValueError, match="Unknown permission: download:unknown"):
        policy.has_permission(user, "download:unknown")


def test_user_policy_denies_inactive_user_even_with_explicit_permission() -> None:
    policy = UserPolicy()
    user = UserRef(
        user_id="inactive-user",
        username="Inactive User",
        roles=(UserRole.USER,),
        permissions=(Permission.TRADING_EXECUTE,),
        is_active=False,
    )

    assert policy.has_permission(user, Permission.TRADING_EXECUTE) is False
    with pytest.raises(PermissionError):
        policy.require_permission(user, Permission.TRADING_EXECUTE)
