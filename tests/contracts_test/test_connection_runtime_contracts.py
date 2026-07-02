from datetime import UTC, datetime

import pytest

from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionDirection,
    ConnectionEndpoint,
    ConnectionEventRecord,
    ConnectionKind,
    ConnectionLifecycleStatus,
    ConnectionProtocol,
    ConnectionRuntimeState,
    WebSocketChannelDefinition,
    WebSocketChannelRuntimeState,
)


def test_connection_endpoint_and_definition_contracts() -> None:
    endpoint = ConnectionEndpoint(
        label="Runtime feed endpoint",
        protocol=ConnectionProtocol.WEBSOCKET,
        host="localhost",
        port=8765,
        path="/runtime",
        metadata={"purpose": "test"},
    )
    definition = ConnectionDefinition(
        connection_id="connection-1",
        label="Runtime feed",
        kind=ConnectionKind.EXTERNAL_SERVICE,
        protocol=ConnectionProtocol.WEBSOCKET,
        direction=ConnectionDirection.OUTBOUND,
        endpoint=endpoint,
        service_id="service-1",
        process_id="process-1",
        metadata={"source": "unit"},
    )

    assert endpoint.metadata["purpose"] == "test"
    assert definition.endpoint is endpoint
    assert definition.metadata["source"] == "unit"

    with pytest.raises(TypeError):
        definition.metadata["other"] = "value"


def test_connection_definition_rejects_endpoint_protocol_mismatch() -> None:
    endpoint = ConnectionEndpoint(
        label="Runtime endpoint",
        protocol=ConnectionProtocol.HTTP,
    )

    with pytest.raises(ValueError, match="protocol"):
        ConnectionDefinition(
            connection_id="connection-1",
            label="Runtime feed",
            kind=ConnectionKind.DIAGNOSTIC,
            protocol=ConnectionProtocol.WEBSOCKET,
            direction=ConnectionDirection.OUTBOUND,
            endpoint=endpoint,
        )


def test_connection_runtime_state_validates_status_and_timestamps() -> None:
    now = datetime.now(UTC)
    state = ConnectionRuntimeState(
        connection_id="connection-1",
        label="Runtime feed",
        kind=ConnectionKind.DIAGNOSTIC,
        protocol=ConnectionProtocol.INTERNAL,
        direction=ConnectionDirection.INTERNAL,
        status=ConnectionLifecycleStatus.CONNECTED,
        registered_at_utc=now,
        updated_at_utc=now,
        connected_at_utc=now,
        operation_id="operation-1",
        task_id="task-1",
        correlation_id="corr-1",
    )

    assert state.status is ConnectionLifecycleStatus.CONNECTED
    assert state.connected_at_utc == now

    with pytest.raises(ValueError, match="timezone"):
        ConnectionRuntimeState(
            connection_id="connection-2",
            label="Runtime feed",
            kind=ConnectionKind.DIAGNOSTIC,
            protocol=ConnectionProtocol.INTERNAL,
            direction=ConnectionDirection.INTERNAL,
            status=ConnectionLifecycleStatus.REGISTERED,
            registered_at_utc=datetime(2026, 7, 2, 12),
            updated_at_utc=now,
        )


def test_websocket_channel_contracts_track_counters() -> None:
    now = datetime.now(UTC)
    definition = WebSocketChannelDefinition(
        channel_id="channel-1",
        connection_id="connection-1",
        label="Runtime channel",
        topic="runtime.events",
        metadata={"scope": "test"},
    )
    state = WebSocketChannelRuntimeState(
        channel_id=definition.channel_id,
        connection_id=definition.connection_id,
        label=definition.label,
        status=ConnectionLifecycleStatus.CONNECTED,
        registered_at_utc=now,
        updated_at_utc=now,
        last_message_at_utc=now,
        received_count=2,
        sent_count=1,
        error_count=0,
    )

    assert definition.topic == "runtime.events"
    assert state.received_count == 2
    assert state.sent_count == 1

    with pytest.raises(ValueError, match="non-negative"):
        WebSocketChannelRuntimeState(
            channel_id="channel-2",
            connection_id="connection-1",
            label="Runtime channel",
            status=ConnectionLifecycleStatus.CONNECTED,
            registered_at_utc=now,
            updated_at_utc=now,
            received_count=-1,
        )


def test_connection_event_record_defaults_event_identity() -> None:
    record = ConnectionEventRecord(
        event_type="connection.lifecycle.connected",
        connection_id="connection-1",
        status=ConnectionLifecycleStatus.CONNECTED,
        channel_id="channel-1",
        message="Connection state recorded",
        correlation_id="corr-1",
    )

    assert record.event_id
    assert record.connection_id == "connection-1"
    assert record.channel_id == "channel-1"
    assert record.timestamp_utc.tzinfo is not None
