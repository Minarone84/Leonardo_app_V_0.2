"""Coarse operational connection tracking for Leonardo Light V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock


@dataclass(frozen=True)
class ConnectionSnapshot:
    connection_id: str
    label: str
    status: str
    kind: str
    protocol: str
    direction: str
    last_heartbeat_utc: datetime | None
    last_error_message: str | None
    metadata: dict[str, object]


@dataclass(frozen=True)
class ChannelSnapshot:
    channel_id: str
    connection_id: str
    label: str
    received_count: int
    sent_count: int
    error_count: int
    last_message_at_utc: datetime | None


@dataclass
class _ConnectionRecord:
    connection_id: str
    label: str
    kind: str
    protocol: str
    direction: str
    status: str = "registered"
    last_heartbeat_utc: datetime | None = None
    last_error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class _ChannelRecord:
    channel_id: str
    connection_id: str
    label: str
    received_count: int = 0
    sent_count: int = 0
    error_count: int = 0
    last_message_at_utc: datetime | None = None


class ConnectionRegistry:
    """Own coarse connection state. Provider semantics remain in Connection Area."""

    def __init__(self) -> None:
        self._connections: dict[str, _ConnectionRecord] = {}
        self._channels: dict[str, _ChannelRecord] = {}
        self._lock = RLock()

    def register_connection(
        self,
        connection_id: str,
        *,
        label: str,
        kind: str = "external_service",
        protocol: str = "unknown",
        direction: str = "outbound",
        metadata: dict[str, object] | None = None,
    ) -> ConnectionSnapshot:
        _require_text(connection_id, "connection_id")
        _require_text(label, "label")
        with self._lock:
            if connection_id in self._connections:
                raise ValueError(f"Connection already registered: {connection_id}")
            record = _ConnectionRecord(
                connection_id=connection_id,
                label=label,
                kind=kind,
                protocol=protocol,
                direction=direction,
                metadata=dict(metadata or {}),
            )
            self._connections[connection_id] = record
            return _connection_snapshot(record)

    def register_websocket_channel(
        self,
        channel_id: str,
        *,
        connection_id: str,
        label: str,
    ) -> ChannelSnapshot:
        with self._lock:
            if connection_id not in self._connections:
                raise KeyError(f"Unknown connection: {connection_id}")
            if channel_id in self._channels:
                raise ValueError(f"Channel already registered: {channel_id}")
            record = _ChannelRecord(channel_id, connection_id, label)
            self._channels[channel_id] = record
            return _channel_snapshot(record)

    def mark_connecting(self, connection_id: str) -> ConnectionSnapshot:
        return self._set_status(connection_id, "connecting")

    def mark_connected(self, connection_id: str) -> ConnectionSnapshot:
        return self._set_status(connection_id, "connected", clear_error=True)

    def mark_degraded(self, connection_id: str, *, error: str) -> ConnectionSnapshot:
        return self._set_status(connection_id, "degraded", error=error)

    def mark_disconnect_requested(self, connection_id: str) -> ConnectionSnapshot:
        return self._set_status(connection_id, "disconnect_requested")

    def mark_disconnected(self, connection_id: str) -> ConnectionSnapshot:
        return self._set_status(connection_id, "disconnected")

    def mark_failed(self, connection_id: str, *, error: str) -> ConnectionSnapshot:
        return self._set_status(connection_id, "failed", error=error)

    def record_heartbeat(
        self,
        connection_id: str,
        *,
        timestamp_utc: datetime | None = None,
    ) -> ConnectionSnapshot:
        with self._lock:
            record = self._require_connection_locked(connection_id)
            record.last_heartbeat_utc = _utc(timestamp_utc)
            return _connection_snapshot(record)

    def record_channel_received(self, channel_id: str, *, count: int = 1) -> ChannelSnapshot:
        return self._update_channel(channel_id, "received_count", count)

    def record_channel_sent(self, channel_id: str, *, count: int = 1) -> ChannelSnapshot:
        return self._update_channel(channel_id, "sent_count", count)

    def record_channel_error(self, channel_id: str, *, count: int = 1) -> ChannelSnapshot:
        return self._update_channel(channel_id, "error_count", count)

    def connection_states(self) -> tuple[ConnectionSnapshot, ...]:
        with self._lock:
            return tuple(
                _connection_snapshot(self._connections[key])
                for key in sorted(self._connections)
            )

    def websocket_channel_states(self) -> tuple[ChannelSnapshot, ...]:
        with self._lock:
            return tuple(
                _channel_snapshot(self._channels[key])
                for key in sorted(self._channels)
            )

    def shutdown_tracking(self) -> tuple[ConnectionSnapshot, ...]:
        stopped = []
        for snapshot in self.connection_states():
            if snapshot.status not in {"disconnected", "failed"}:
                stopped.append(self.mark_disconnected(snapshot.connection_id))
        return tuple(stopped)

    def _set_status(
        self,
        connection_id: str,
        status: str,
        *,
        error: str | None = None,
        clear_error: bool = False,
    ) -> ConnectionSnapshot:
        with self._lock:
            record = self._require_connection_locked(connection_id)
            record.status = status
            if clear_error:
                record.last_error_message = None
            elif error is not None:
                record.last_error_message = error
            return _connection_snapshot(record)

    def _update_channel(self, channel_id: str, field_name: str, count: int) -> ChannelSnapshot:
        if type(count) is not int or count <= 0:
            raise ValueError("count must be a positive integer")
        with self._lock:
            record = self._channels.get(channel_id)
            if record is None:
                raise KeyError(f"Unknown channel: {channel_id}")
            setattr(record, field_name, getattr(record, field_name) + count)
            record.last_message_at_utc = datetime.now(UTC)
            return _channel_snapshot(record)

    def _require_connection_locked(self, connection_id: str) -> _ConnectionRecord:
        record = self._connections.get(connection_id)
        if record is None:
            raise KeyError(f"Unknown connection: {connection_id}")
        return record


def _connection_snapshot(record: _ConnectionRecord) -> ConnectionSnapshot:
    return ConnectionSnapshot(
        connection_id=record.connection_id,
        label=record.label,
        status=record.status,
        kind=record.kind,
        protocol=record.protocol,
        direction=record.direction,
        last_heartbeat_utc=record.last_heartbeat_utc,
        last_error_message=record.last_error_message,
        metadata=dict(record.metadata),
    )


def _channel_snapshot(record: _ChannelRecord) -> ChannelSnapshot:
    return ChannelSnapshot(
        channel_id=record.channel_id,
        connection_id=record.connection_id,
        label=record.label,
        received_count=record.received_count,
        sent_count=record.sent_count,
        error_count=record.error_count,
        last_message_at_utc=record.last_message_at_utc,
    )


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return current.astimezone(UTC)
