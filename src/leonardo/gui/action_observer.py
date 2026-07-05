"""GUI action observation boundary for Core-compatible action tracking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.gui import ActionDefinition, ActionKind, ActionTriggerRecord
from leonardo.contracts.identity import ActorOrigin, Permission


class GuiActionObserver(Protocol):
    """
    Observe stable GUI action triggers without exposing Core services to widgets.

    Qt windows depend on this boundary only. The concrete implementation may
    bridge to Core registries from the GUI composition root.
    """

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> GuiActionDecision:
        """Record one observed GUI action trigger."""

        ...


class ActionRegistryBoundary(Protocol):
    """Action registry methods required by the GUI observer adapter."""

    def get_action_definition(self, action_id: str) -> ActionDefinition | None:
        """Return an action definition if it is already registered."""

        ...

    def register_action(self, definition: ActionDefinition) -> ActionDefinition:
        """Register an action definition."""

        ...

    def record_trigger(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        actor_id: str | None = None,
        session_id: str | None = None,
        origin: ActorOrigin | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ActionTriggerRecord:
        """Record one action trigger."""

        ...


class SessionProviderBoundary(Protocol):
    """Session provider shape required by the GUI observer adapter."""

    @property
    def current_session(self) -> object:
        """Return the current runtime session object."""

        ...


class UserPolicyBoundary(Protocol):
    """User policy methods required by the GUI observer adapter."""

    def has_permission(self, user: object, permission: Permission) -> bool:
        """Return whether the user has the requested permission."""

        ...


class AuditLogBoundary(Protocol):
    """Audit log method required for denied GUI action events."""

    def emit(self, event: AuditEvent) -> object:
        """Emit one audit event."""

        ...


@dataclass(frozen=True)
class GuiActionDecision:
    """
    Decision returned to Qt windows before local action behavior runs.

    The decision is intentionally GUI-safe: it contains stable identifiers and
    metadata only, never Core services or Qt widgets.
    """

    action_id: str
    allowed: bool
    reason: str = ""
    message: str = ""
    required_permissions: tuple[str, ...] = ()
    record: ActionTriggerRecord | None = None


TRACKED_GUI_ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        action_id="main_window.open_runtime_manager",
        label="Runtime Manager",
        kind=ActionKind.MENU,
        window_id="main_window.window",
        required_permissions=(Permission.RUNTIME_VIEW,),
    ),
    ActionDefinition(
        action_id="main_window.open_settings_inspector",
        label="Settings",
        kind=ActionKind.MENU,
        window_id="main_window.window",
        required_permissions=(Permission.GUI_SETTINGS_MANAGE,),
    ),
    ActionDefinition(
        action_id="main_window.download_data",
        label="Download Data",
        kind=ActionKind.MENU,
        window_id="main_window.window",
        is_placeholder=True,
    ),
    ActionDefinition(
        action_id="main_window.ohlcv_maintenance",
        label="OHLCV Maintenance",
        kind=ActionKind.MENU,
        window_id="main_window.window",
        is_placeholder=True,
    ),
    ActionDefinition(
        action_id="main_window.open_trading_suite",
        label="Trading Suite",
        kind=ActionKind.BUTTON,
        window_id="main_window.window",
        is_placeholder=True,
    ),
    ActionDefinition(
        action_id="main_window.open_research_suite",
        label="Research Suite",
        kind=ActionKind.BUTTON,
        window_id="main_window.window",
        is_placeholder=True,
    ),
    ActionDefinition(
        action_id="main_window.open_data_manager_suite",
        label="Data Manager Suite",
        kind=ActionKind.BUTTON,
        window_id="main_window.window",
        is_placeholder=True,
    ),
    ActionDefinition(
        action_id="main_window.open_analysis_suite",
        label="Analysis Suite",
        kind=ActionKind.BUTTON,
        window_id="main_window.window",
        is_placeholder=True,
    ),
    ActionDefinition(
        action_id="settings_inspector.save",
        label="Save",
        kind=ActionKind.BUTTON,
        required_permissions=(Permission.GUI_SETTINGS_MANAGE,),
    ),
    ActionDefinition(
        action_id="settings_inspector.apply_changes",
        label="Apply Changes",
        kind=ActionKind.BUTTON,
        required_permissions=(Permission.GUI_SETTINGS_MANAGE,),
    ),
    ActionDefinition(
        action_id="runtime_manager.refresh_snapshot",
        label="Refresh Snapshot",
        kind=ActionKind.BUTTON,
        window_id="runtime_manager.window",
        required_permissions=(Permission.RUNTIME_VIEW,),
    ),
    ActionDefinition(
        action_id="runtime_manager.close",
        label="Close",
        kind=ActionKind.BUTTON,
        window_id="runtime_manager.window",
    ),
)
TRACKED_GUI_ACTION_IDS = frozenset(
    definition.action_id for definition in TRACKED_GUI_ACTION_DEFINITIONS
)


class CoreGuiActionObserver:
    """
    Bridge GUI action observations to an ActionRegistry-compatible boundary.

    The adapter records existing stable identifiers only. It does not execute
    actions, enforce permissions, mutate widgets, or create Core services.
    """

    def __init__(
        self,
        action_registry: ActionRegistryBoundary,
        *,
        session_provider: SessionProviderBoundary | None = None,
        user_policy: UserPolicyBoundary | None = None,
        audit_log: AuditLogBoundary | None = None,
        definitions: Sequence[ActionDefinition] = TRACKED_GUI_ACTION_DEFINITIONS,
    ) -> None:
        self._action_registry = action_registry
        self._session_provider = session_provider
        self._user_policy = user_policy
        self._audit_log = audit_log
        self._definitions_by_id = {
            definition.action_id: definition for definition in definitions
        }
        self.ensure_registered_actions(definitions)

    def ensure_registered_actions(
        self,
        definitions: Sequence[ActionDefinition],
    ) -> None:
        """Register known GUI action definitions if they are not present."""

        for definition in definitions:
            if self._action_registry.get_action_definition(definition.action_id) is None:
                self._action_registry.register_action(definition)

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> GuiActionDecision:
        """Return a gate decision and record allowed tracked GUI actions."""

        if action_id not in TRACKED_GUI_ACTION_IDS:
            return GuiActionDecision(action_id=action_id, allowed=True)

        session = _current_session(self._session_provider)
        metadata_dict = dict(metadata) if metadata is not None else None
        required_permissions = self._required_permissions(action_id)
        denied_reason = self._denied_reason(session, required_permissions)
        if denied_reason:
            self._emit_denied_action(
                action_id,
                window_id=window_id,
                session=session,
                required_permissions=required_permissions,
                reason=denied_reason,
                metadata=metadata_dict,
            )
            return GuiActionDecision(
                action_id=action_id,
                allowed=False,
                reason=denied_reason,
                message=f"Action denied: {action_id}",
                required_permissions=_permission_values(required_permissions),
            )

        record = self._action_registry.record_trigger(
            action_id,
            window_id=window_id,
            actor_id=_optional_string(getattr(session, "actor_id", None)),
            session_id=_optional_string(getattr(session, "session_id", None)),
            origin=_optional_origin(getattr(session, "origin", None)),
            metadata=metadata_dict,
        )
        return GuiActionDecision(
            action_id=action_id,
            allowed=True,
            required_permissions=_permission_values(required_permissions),
            record=record,
        )

    def _required_permissions(self, action_id: str) -> tuple[Permission, ...]:
        definition = self._definitions_by_id.get(action_id)
        if definition is None:
            return ()
        return definition.required_permissions

    def _denied_reason(
        self,
        session: object | None,
        required_permissions: tuple[Permission, ...],
    ) -> str:
        if not required_permissions:
            return ""
        if self._user_policy is None:
            return "missing_user_policy"
        if session is None:
            return "missing_session"
        actor = getattr(session, "actor", None)
        if actor is None:
            return "missing_actor"
        missing = [
            permission
            for permission in required_permissions
            if not self._user_policy.has_permission(actor, permission)
        ]
        if missing:
            return "missing_permission"
        return ""

    def _emit_denied_action(
        self,
        action_id: str,
        *,
        window_id: str | None,
        session: object | None,
        required_permissions: tuple[Permission, ...],
        reason: str,
        metadata: dict[str, object] | None,
    ) -> None:
        if self._audit_log is None:
            return
        self._audit_log.emit(
            AuditEvent(
                event_type="gui.action.denied",
                message=f"Action denied: {action_id}",
                severity=AuditSeverity.WARNING,
                category=AuditCategory.RUNTIME,
                actor_id=_optional_string(getattr(session, "actor_id", None)),
                session_id=_optional_string(getattr(session, "session_id", None)),
                origin=_optional_origin(getattr(session, "origin", None)),
                window_id=window_id,
                action_id=action_id,
                payload={
                    "action_id": action_id,
                    "required_permissions": _permission_values(required_permissions),
                    "reason": reason,
                    "metadata": metadata or {},
                },
            )
        )


def build_gui_action_observer(context: object) -> GuiActionObserver | None:
    """
    Build a GUI action observer from a Core-like context when available.

    GUI-only tests and local window construction may omit action registry
    infrastructure. In that case action observation remains disabled.
    """

    action_registry = getattr(context, "action_registry", None)
    if action_registry is None:
        return None
    _require_action_registry_boundary(action_registry)

    session_provider = getattr(context, "session_manager", None)
    if session_provider is not None and not hasattr(session_provider, "current_session"):
        raise TypeError("context.session_manager must expose current_session")
    user_policy = getattr(context, "user_policy", None)
    if user_policy is not None and not callable(
        getattr(user_policy, "has_permission", None)
    ):
        raise TypeError("context.user_policy must expose callable has_permission")
    audit_log = getattr(context, "audit_log", None)
    if audit_log is not None and not callable(getattr(audit_log, "emit", None)):
        raise TypeError("context.audit_log must expose callable emit")
    return CoreGuiActionObserver(
        action_registry,
        session_provider=session_provider,
        user_policy=user_policy,
        audit_log=audit_log,
    )


def _require_action_registry_boundary(action_registry: object) -> None:
    for name in ("get_action_definition", "register_action", "record_trigger"):
        if not callable(getattr(action_registry, name, None)):
            raise TypeError(f"context.action_registry must expose callable {name}")


def _current_session(session_provider: SessionProviderBoundary | None) -> object | None:
    if session_provider is None:
        return None
    return session_provider.current_session


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_origin(value: object) -> ActorOrigin | None:
    if isinstance(value, ActorOrigin):
        return value
    return None


def _permission_values(values: tuple[Permission, ...]) -> tuple[str, ...]:
    return tuple(permission.value for permission in values)
