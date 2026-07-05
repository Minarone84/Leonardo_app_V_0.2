"""GUI action observation boundary for Core-compatible action tracking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from leonardo.contracts.gui import ActionDefinition, ActionKind, ActionTriggerRecord
from leonardo.contracts.identity import ActorOrigin


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
    ) -> object:
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


TRACKED_GUI_ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        action_id="main_window.open_runtime_manager",
        label="Open Runtime Manager",
        kind=ActionKind.MENU,
        window_id="main_window.window",
    ),
    ActionDefinition(
        action_id="main_window.open_settings_inspector",
        label="Open Settings Inspector",
        kind=ActionKind.MENU,
        window_id="main_window.window",
    ),
    ActionDefinition(
        action_id="settings_inspector.save",
        label="Save",
        kind=ActionKind.BUTTON,
    ),
    ActionDefinition(
        action_id="settings_inspector.apply_changes",
        label="Apply Changes",
        kind=ActionKind.BUTTON,
    ),
    ActionDefinition(
        action_id="runtime_manager.refresh_snapshot",
        label="Refresh Snapshot",
        kind=ActionKind.BUTTON,
        window_id="runtime_manager.window",
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
        definitions: Sequence[ActionDefinition] = TRACKED_GUI_ACTION_DEFINITIONS,
    ) -> None:
        self._action_registry = action_registry
        self._session_provider = session_provider
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
    ) -> ActionTriggerRecord | None:
        """Record one tracked GUI action through the ActionRegistry boundary."""

        if action_id not in TRACKED_GUI_ACTION_IDS:
            return None

        session = _current_session(self._session_provider)
        return self._action_registry.record_trigger(
            action_id,
            window_id=window_id,
            actor_id=_optional_string(getattr(session, "actor_id", None)),
            session_id=_optional_string(getattr(session, "session_id", None)),
            origin=_optional_origin(getattr(session, "origin", None)),
            metadata=dict(metadata) if metadata is not None else None,
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
    return CoreGuiActionObserver(
        action_registry,
        session_provider=session_provider,
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
