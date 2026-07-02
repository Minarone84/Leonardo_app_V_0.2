"""User policy checks for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from leonardo.contracts.identity import Permission, UserRef, UserRole


class UserPolicy:
    """
    Evaluate explicit runtime permissions for user references.

    Administrator users are allowed all permissions. Non-admin users must carry
    the requested permission explicitly.
    """

    def has_permission(self, user: UserRef, permission: Permission) -> bool:
        """Return whether the user has the requested permission."""

        if not isinstance(user, UserRef):
            raise TypeError("user must be a UserRef")
        if not isinstance(permission, Permission):
            raise TypeError("permission must be a Permission")
        if not user.is_active:
            return False
        if UserRole.ADMINISTRATOR in user.roles:
            return True
        return permission in user.permissions

    def require_permission(self, user: UserRef, permission: Permission) -> None:
        """
        Require a permission or raise ``PermissionError``.

        The method performs authorization only. It does not authenticate users.
        """

        if not self.has_permission(user, permission):
            raise PermissionError(
                f"User {user.user_id} does not have permission {permission.value}"
            )
