"""Window observability registry for Leonardo V2 Core."""

from __future__ import annotations

from leonardo.contracts.gui import WindowDefinition, WindowRuntimeState
from leonardo.core.state_store import StateStore


class WindowRegistry:
    """
    Register window definitions and track runtime window identity state.

    The registry stores definitions and state only. It does not store widgets,
    import Qt, or perform GUI focus behavior.
    """

    def __init__(self, state_store: StateStore) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        self._state_store = state_store
        self._definitions: dict[str, WindowDefinition] = {}

    def register_window(self, definition: WindowDefinition) -> WindowDefinition:
        """Register a window definition by stable window identifier."""

        if not isinstance(definition, WindowDefinition):
            raise TypeError("definition must be a WindowDefinition")
        if definition.window_id in self._definitions:
            raise ValueError(f"Window already registered: {definition.window_id}")
        self._definitions[definition.window_id] = definition
        return definition

    def get_window_definition(self, window_id: str) -> WindowDefinition | None:
        """Return a registered window definition, if present."""

        return self._definitions.get(window_id)

    def list_windows(self) -> tuple[WindowDefinition, ...]:
        """Return registered window definitions in deterministic order."""

        return tuple(
            self._definitions[window_id]
            for window_id in sorted(self._definitions)
        )

    def open_window(
        self,
        window_id: str,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> WindowRuntimeState:
        """Record that a registered window identity was opened."""

        definition = self._require_definition(window_id)
        return self._state_store.window_opened(
            definition,
            owner_action_id=owner_action_id,
            current_operation_id=current_operation_id,
            metadata=metadata,
        )

    def focus_window(self, window_id: str) -> WindowRuntimeState:
        """Record a focus intent for an open window identity."""

        self._require_definition(window_id)
        return self._state_store.window_focused(window_id)

    def request_window_close(self, window_id: str) -> WindowRuntimeState:
        """Record a close request for an open window identity."""

        self._require_definition(window_id)
        return self._state_store.window_close_requested(window_id)

    def close_window(self, window_id: str) -> WindowRuntimeState:
        """Record that an open window identity was closed."""

        self._require_definition(window_id)
        return self._state_store.window_closed(window_id)

    def open_windows(self) -> tuple[WindowRuntimeState, ...]:
        """Return open window runtime states."""

        return self._state_store.windows_state()

    def _require_definition(self, window_id: str) -> WindowDefinition:
        definition = self._definitions.get(window_id)
        if definition is None:
            raise KeyError(f"Window is not registered: {window_id}")
        return definition
