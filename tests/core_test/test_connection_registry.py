import pytest

from datetime import UTC, datetime

from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionDirection,
    ConnectionKind,
    ConnectionLifecycleStatus,
    ConnectionProtocol,
    WebSocketChannelDefinition,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.state_store import StateStore


def _registry() -> tuple[ConnectionRegistry, StateStore, AuditLog]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    return ConnectionRegistry(state_store), state_store, audit_log


def _definition(connection_id: str = "connection-1") -> ConnectionDefinition:
    return ConnectionDefinition(
        connection_id=connection_id,
        label="Runtime feed",
        kind=ConnectionKind.EXTERNAL_SERVICE,
        protocol=ConnectionProtocol.WEBSOCKET,
        direction=ConnectionDirection.OUTBOUND,
    )


def _channel(channel_id: str = "channel-1") -> WebSocketChannelDefinition:
    return WebSocketChannelDefinition(
        channel_id=channel_id,
        connection_id="connection-1",
        label="Runtime channel",
        topic="runtime.events",
    )


def test_connection_registry_registers_connection_and_state() -> None:
    registry, state_store, audit_log = _registry()

    definition = registry.register_connection(_definition())

    assert definition.connection_id == "connection-1"
    assert registry.list_connections() == (definition,)
    assert state_store.connection_states()[0].status is (
        ConnectionLifecycleStatus.REGISTERED
    )
    assert audit_log.snapshot()[-1].event_type == "connection.lifecycle.registered"
    assert audit_log.snapshot()[-1].connection_id == "connection-1"


def test_connection_registry_rejects_duplicate_connection_ids() -> None:
    registry, _state_store, _audit_log = _registry()
    registry.register_connection(_definition())

    with pytest.raises(ValueError, match="already registered"):
        registry.register_connection(_definition())


def test_connection_registry_rejects_duplicate_and_unknown_channels() -> None:
    registry, _state_store, _audit_log = _registry()

    with pytest.raises(KeyError, match="not registered"):
        registry.register_websocket_channel(_channel())

    registry.register_connection(_definition())
    registry.register_websocket_channel(_channel())

    with pytest.raises(ValueError, match="already registered"):
        registry.register_websocket_channel(_channel())


def test_connection_registry_records_lifecycle_in_state_and_audit() -> None:
    registry, state_store, audit_log = _registry()
    registry.register_connection(_definition())

    connecting = registry.mark_connection_connecting(
        "connection-1",
        correlation_id="corr-1",
    )
    connected = registry.mark_connection_connected("connection-1")
    registry.mark_connection_disconnect_requested("connection-1")
    disconnected = registry.mark_connection_disconnected(
        "connection-1",
        message="Connection stopped",
    )

    assert connecting.status is ConnectionLifecycleStatus.CONNECTING
    assert connected.status is ConnectionLifecycleStatus.CONNECTED
    assert disconnected.status is ConnectionLifecycleStatus.DISCONNECTED
    assert disconnected.disconnected_at_utc is not None
    assert state_store.connection_states() == (disconnected,)
    assert [event.event_type for event in audit_log.snapshot()] == [
        "connection.lifecycle.registered",
        "connection.lifecycle.connecting",
        "connection.lifecycle.connected",
        "connection.lifecycle.disconnect_requested",
        "connection.lifecycle.disconnected",
    ]
    assert audit_log.snapshot()[-1].correlation_id == "corr-1"


def test_connection_registry_records_degraded_and_failed_states() -> None:
    registry, state_store, audit_log = _registry()
    registry.register_connection(_definition())

    degraded = registry.mark_connection_degraded(
        "connection-1",
        last_error_message="Heartbeat late",
    )
    failed = registry.mark_connection_failed(
        "connection-1",
        last_error_message="Runtime feed stopped",
    )

    assert degraded.status is ConnectionLifecycleStatus.DEGRADED
    assert failed.status is ConnectionLifecycleStatus.FAILED
    assert failed.last_error_message == "Runtime feed stopped"
    assert state_store.connection_states() == (failed,)
    assert audit_log.snapshot()[-2].severity.value == "warning"
    assert audit_log.snapshot()[-1].severity.value == "error"


def test_connection_registry_records_heartbeat_timestamp() -> None:
    registry, _state_store, _audit_log = _registry()
    registry.register_connection(_definition())
    timestamp = datetime(2026, 7, 2, 12, tzinfo=UTC)

    state = registry.record_heartbeat("connection-1", timestamp_utc=timestamp)

    assert state.last_heartbeat_at_utc == timestamp
    assert state.updated_at_utc == timestamp


def test_connection_registry_records_channel_counters() -> None:
    registry, state_store, audit_log = _registry()
    registry.register_connection(_definition())
    registry.register_websocket_channel(_channel())
    timestamp = datetime(2026, 7, 2, 12, tzinfo=UTC)

    registry.mark_connection_connected("connection-1")
    received = registry.record_channel_received(
        "channel-1",
        count=2,
        timestamp_utc=timestamp,
    )
    sent = registry.record_channel_sent("channel-1", count=3)
    errored = registry.record_channel_error("channel-1", count=1)

    assert received.received_count == 2
    assert sent.sent_count == 3
    assert errored.error_count == 1
    assert errored.status is ConnectionLifecycleStatus.DEGRADED
    assert state_store.websocket_channel_states() == (errored,)
    assert "connection.channel.registered" in (
        event.event_type for event in audit_log.snapshot()
    )


def test_connection_registry_snapshots_are_defensive() -> None:
    registry, _state_store, _audit_log = _registry()
    definition = registry.register_connection(_definition())
    before_definitions = registry.list_connections()
    before_states = registry.connection_states()

    registry.mark_connection_degraded(
        "connection-1",
        last_error_message="Heartbeat late",
    )

    assert before_definitions == (definition,)
    assert before_states[0].status is ConnectionLifecycleStatus.REGISTERED
    assert registry.connection_states()[0].status is ConnectionLifecycleStatus.DEGRADED
