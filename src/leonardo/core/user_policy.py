"""User policy checks for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from leonardo.contracts.identity import Permission, UserRef, UserRole

PermissionInput = Permission | str


class UserPolicy:
    """
    Evaluate explicit runtime permissions for user references.

    Administrator users are allowed all permissions. Non-admin users must carry
    the requested permission explicitly.
    """

    def normalize_permission(self, permission: PermissionInput) -> Permission:
        """Return a defined permission enum from a permission contract value."""

        if isinstance(permission, Permission):
            return permission
        if isinstance(permission, str):
            try:
                return Permission(permission)
            except ValueError as exc:
                raise ValueError(f"Unknown permission: {permission}") from exc
        raise TypeError("permission must be a Permission or string")

    def has_permission(self, user: UserRef, permission: PermissionInput) -> bool:
        """Return whether the user has the requested permission."""

        if not isinstance(user, UserRef):
            raise TypeError("user must be a UserRef")
        normalized_permission = self.normalize_permission(permission)
        if not user.is_active:
            return False
        if UserRole.ADMINISTRATOR in user.roles:
            return True
        return normalized_permission in user.permissions

    def require_permission(self, user: UserRef, permission: PermissionInput) -> None:
        """
        Require a permission or raise ``PermissionError``.

        The method performs authorization only. It does not authenticate users.
        """

        normalized_permission = self.normalize_permission(permission)
        if not self.has_permission(user, normalized_permission):
            raise PermissionError(
                f"User {user.user_id} does not have permission "
                f"{normalized_permission.value}"
            )
