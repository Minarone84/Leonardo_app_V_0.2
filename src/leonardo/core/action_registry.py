"""Action observability registry for Leonardo V2 Core."""

from __future__ import annotations

from datetime import UTC, datetime

from leonardo.contracts.gui import ActionDefinition, ActionTriggerRecord
from leonardo.contracts.identity import ActorOrigin
from leonardo.core.state_store import StateStore


class ActionRegistry:
    """
    Register action definitions and record action triggers.

    The registry tracks trigger history only. It does not execute commands,
    start operations, or store GUI widgets.
    """

    def __init__(self, state_store: StateStore) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        self._state_store = state_store
        self._definitions: dict[str, ActionDefinition] = {}

    def register_action(self, definition: ActionDefinition) -> ActionDefinition:
        """Register an action definition by stable action identifier."""

        if not isinstance(definition, ActionDefinition):
            raise TypeError("definition must be an ActionDefinition")
        if definition.action_id in self._definitions:
            raise ValueError(f"Action already registered: {definition.action_id}")
        self._definitions[definition.action_id] = definition
        return definition

    def get_action_definition(self, action_id: str) -> ActionDefinition | None:
        """Return a registered action definition, if present."""

        return self._definitions.get(action_id)

    def list_actions(self) -> tuple[ActionDefinition, ...]:
        """Return registered action definitions in deterministic order."""

        return tuple(
            self._definitions[action_id]
            for action_id in sorted(self._definitions)
        )

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
        """Record that a registered action was triggered."""

        self._require_definition(action_id)
        record = ActionTriggerRecord(
            action_id=action_id,
            window_id=window_id,
            actor_id=actor_id,
            session_id=session_id,
            origin=origin,
            triggered_at_utc=datetime.now(UTC),
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        return self._state_store.action_triggered(record)

    def recent_triggers(self) -> tuple[ActionTriggerRecord, ...]:
        """Return bounded recent action trigger records."""

        return self._state_store.recent_action_triggers()

    def _require_definition(self, action_id: str) -> ActionDefinition:
        definition = self._definitions.get(action_id)
        if definition is None:
            raise KeyError(f"Action is not registered: {action_id}")
        return definition
