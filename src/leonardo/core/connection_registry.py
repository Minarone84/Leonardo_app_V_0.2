"""Connection observability registry for Leonardo V2 Core."""

from __future__ import annotations

from datetime import datetime

from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionLifecycleStatus,
    ConnectionRuntimeState,
    WebSocketChannelDefinition,
    WebSocketChannelRuntimeState,
)
from leonardo.core.state_store import StateStore


class ConnectionRegistry:
    """
    Register connection definitions and track runtime connection identity state.

    The registry stores definitions and delegates current runtime state to
    `StateStore`. It does not store client handles, callbacks, open streams, or
    transport objects.
    """

    def __init__(self, state_store: StateStore) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        self._state_store = state_store
        self._definitions: dict[str, ConnectionDefinition] = {}
        self._channel_definitions: dict[str, WebSocketChannelDefinition] = {}

    def register_connection(
        self,
        definition: ConnectionDefinition,
    ) -> ConnectionDefinition:
        """Register a connection definition by stable connection identifier."""

        if not isinstance(definition, ConnectionDefinition):
            raise TypeError("definition must be a ConnectionDefinition")
        if definition.connection_id in self._definitions:
            raise ValueError(
                f"Connection already registered: {definition.connection_id}"
            )
        self._state_store.connection_registered(definition)
        self._definitions[definition.connection_id] = definition
        return definition

    def get_connection_definition(
        self,
        connection_id: str,
    ) -> ConnectionDefinition | None:
        """Return a registered connection definition, if present."""

        return self._definitions.get(connection_id)

    def list_connections(self) -> tuple[ConnectionDefinition, ...]:
        """Return registered connection definitions in deterministic order."""

        return tuple(
            self._definitions[connection_id]
            for connection_id in sorted(self._definitions)
        )

    def register_websocket_channel(
        self,
        definition: WebSocketChannelDefinition,
    ) -> WebSocketChannelDefinition:
        """Register a WebSocket channel under a known connection."""

        if not isinstance(definition, WebSocketChannelDefinition):
            raise TypeError("definition must be a WebSocketChannelDefinition")
        if definition.channel_id in self._channel_definitions:
            raise ValueError(
                f"WebSocket channel already registered: {definition.channel_id}"
            )
        self._require_definition(definition.connection_id)
        self._state_store.websocket_channel_registered(definition)
        self._channel_definitions[definition.channel_id] = definition
        return definition

    def get_websocket_channel_definition(
        self,
        channel_id: str,
    ) -> WebSocketChannelDefinition | None:
        """Return a registered WebSocket channel definition, if present."""

        return self._channel_definitions.get(channel_id)

    def list_websocket_channels(self) -> tuple[WebSocketChannelDefinition, ...]:
        """Return registered WebSocket channel definitions in deterministic order."""

        return tuple(
            self._channel_definitions[channel_id]
            for channel_id in sorted(self._channel_definitions)
        )

    def mark_connection_connecting(
        self,
        connection_id: str,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Record that a registered connection is attempting readiness."""

        self._require_definition(connection_id)
        return self._state_store.connection_connecting(
            connection_id,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def mark_connection_connected(
        self,
        connection_id: str,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Record that a registered connection is ready."""

        self._require_definition(connection_id)
        return self._state_store.connection_connected(
            connection_id,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def mark_connection_degraded(
        self,
        connection_id: str,
        *,
        last_error_message: str,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Record that a registered connection is degraded."""

        self._require_definition(connection_id)
        return self._state_store.connection_degraded(
            connection_id,
            last_error_message=last_error_message,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def mark_connection_disconnect_requested(
        self,
        connection_id: str,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Record stop intent for a registered connection identity."""

        self._require_definition(connection_id)
        return self._state_store.connection_disconnect_requested(
            connection_id,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def mark_connection_disconnected(
        self,
        connection_id: str,
        *,
        message: str = "",
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Record that a registered connection identity stopped."""

        self._require_definition(connection_id)
        return self._state_store.connection_disconnected(
            connection_id,
            message=message,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def mark_connection_failed(
        self,
        connection_id: str,
        *,
        last_error_message: str,
        operation_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionRuntimeState:
        """Record that a registered connection identity failed."""

        self._require_definition(connection_id)
        return self._state_store.connection_failed(
            connection_id,
            last_error_message=last_error_message,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    def record_heartbeat(
        self,
        connection_id: str,
        *,
        timestamp_utc: datetime | None = None,
    ) -> ConnectionRuntimeState:
        """Record the latest observed heartbeat timestamp for a connection."""

        self._require_definition(connection_id)
        return self._state_store.connection_heartbeat(
            connection_id,
            timestamp_utc=timestamp_utc,
        )

    def record_channel_received(
        self,
        channel_id: str,
        *,
        count: int = 1,
        timestamp_utc: datetime | None = None,
    ) -> WebSocketChannelRuntimeState:
        """Record received message count for a registered channel."""

        self._require_channel_definition(channel_id)
        return self._state_store.websocket_channel_received(
            channel_id,
            count=count,
            timestamp_utc=timestamp_utc,
        )

    def record_channel_sent(
        self,
        channel_id: str,
        *,
        count: int = 1,
        timestamp_utc: datetime | None = None,
    ) -> WebSocketChannelRuntimeState:
        """Record sent message count for a registered channel."""

        self._require_channel_definition(channel_id)
        return self._state_store.websocket_channel_sent(
            channel_id,
            count=count,
            timestamp_utc=timestamp_utc,
        )

    def record_channel_error(
        self,
        channel_id: str,
        *,
        count: int = 1,
        timestamp_utc: datetime | None = None,
    ) -> WebSocketChannelRuntimeState:
        """Record error count for a registered channel."""

        self._require_channel_definition(channel_id)
        return self._state_store.websocket_channel_error(
            channel_id,
            count=count,
            timestamp_utc=timestamp_utc,
        )

    def connection_states(self) -> tuple[ConnectionRuntimeState, ...]:
        """Return defensive connection runtime state snapshots."""

        return self._state_store.connection_states()

    def websocket_channel_states(self) -> tuple[WebSocketChannelRuntimeState, ...]:
        """Return defensive WebSocket channel runtime state snapshots."""

        return self._state_store.websocket_channel_states()

    def shutdown_tracking(
        self,
        *,
        reason: str = "Application shutdown",
    ) -> tuple[ConnectionRuntimeState, ...]:
        """
        Mark active tracked connection identities as disconnected.

        The registry owns only runtime observability state. This method does not
        close provider clients, network streams, or WebSocket transports.
        """

        stopped: list[ConnectionRuntimeState] = []
        for state in self.connection_states():
            if state.status.is_terminal:
                continue
            if state.status is not ConnectionLifecycleStatus.DISCONNECT_REQUESTED:
                self.mark_connection_disconnect_requested(state.connection_id)
            stopped.append(
                self.mark_connection_disconnected(
                    state.connection_id,
                    message=reason,
                )
            )
        return tuple(stopped)

    def _require_definition(self, connection_id: str) -> ConnectionDefinition:
        definition = self._definitions.get(connection_id)
        if definition is None:
            raise KeyError(f"Connection is not registered: {connection_id}")
        return definition

    def _require_channel_definition(
        self,
        channel_id: str,
    ) -> WebSocketChannelDefinition:
        definition = self._channel_definitions.get(channel_id)
        if definition is None:
            raise KeyError(f"WebSocket channel is not registered: {channel_id}")
        return definition
