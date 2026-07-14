"""Thin GUI adapter over the shared application ActionRegistry."""

from __future__ import annotations

from dataclasses import dataclass

from leonardo.core.action_registry import ActionDefinition, ActionRegistry


@dataclass(frozen=True)
class GuiActionDecision:
    allowed: bool
    reason: str = ""


class GuiActionObserver:
    def __init__(self, action_registry: ActionRegistry, *, actor_id: str = "local-user") -> None:
        if not isinstance(action_registry, ActionRegistry):
            raise TypeError("action_registry must be an ActionRegistry")
        self._registry = action_registry
        self._actor_id = actor_id

    def register_action(
        self,
        action_id: str,
        *,
        label: str | None = None,
        window_id: str | None = None,
        audit_enabled: bool = True,
    ) -> ActionDefinition:
        existing = self._registry.get_action_definition(action_id)
        if existing is not None:
            return existing
        return self._registry.register_action(
            action_id=action_id,
            label=label or action_id,
            window_id=window_id,
            audit_enabled=audit_enabled,
        )

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> GuiActionDecision:
        self.register_action(action_id, window_id=window_id)
        self._registry.record_trigger(
            action_id,
            window_id=window_id,
            actor_id=self._actor_id,
            metadata=metadata,
        )
        return GuiActionDecision(True)


def build_gui_action_observer(context: object) -> GuiActionObserver | None:
    registry = getattr(context, "action_registry", None)
    if not isinstance(registry, ActionRegistry):
        return None
    actor_id = getattr(getattr(context, "config", None), "actor_id", "local-user")
    return GuiActionObserver(registry, actor_id=actor_id)
