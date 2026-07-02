"""Audit log sinks for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from leonardo.contracts.audit import AuditEvent


@dataclass(frozen=True)
class AuditSinkFailure:
    """Structured failure captured when an audit sink operation fails."""

    sink_name: str
    operation: str
    exception_type: str
    message: str
    event_id: str | None = None


class InMemoryAuditSink:
    """
    Bounded in-memory sink for normalized audit events.

    The sink is intended for the runtime foundation and tests. Persistent file
    sinks are intentionally outside this phase.
    """

    def __init__(self, max_events: int = 1000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be greater than zero")
        self._max_events = max_events
        self._events: list[AuditEvent] = []

    @property
    def max_events(self) -> int:
        """Return the maximum number of retained events."""

        return self._max_events

    def emit(self, event: AuditEvent) -> AuditEvent:
        """Store an audit event and enforce bounded retention."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]
        return event

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return an immutable snapshot of retained events."""

        return tuple(self._events)

    def flush(self) -> None:
        """Flush retained events. In-memory retention requires no operation."""

    def close(self) -> None:
        """Close the sink. In-memory retention requires no operation."""

    def sink_failures(self) -> tuple[AuditSinkFailure, ...]:
        """Return sink failures captured by this sink."""

        return ()


class JsonlAuditSink:
    """
    Durable JSONL audit sink.

    The sink opens lazily and creates parent directories only when the first
    event is written. Each line contains one serialized audit event.
    """

    def __init__(self, path: Path | str, *, auto_flush: bool = True) -> None:
        self._path = Path(path)
        self._auto_flush = auto_flush
        self._handle = None

    @property
    def path(self) -> Path:
        """Return the configured JSONL file path."""

        return self._path

    def emit(self, event: AuditEvent) -> AuditEvent:
        """Append an event as one JSON object line."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        handle = self._open_handle()
        handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        if self._auto_flush:
            handle.flush()
        return event

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return retained events. Durable sinks do not keep live snapshots."""

        return ()

    def flush(self) -> None:
        """Flush pending writes if the sink has been opened."""

        if self._handle is not None:
            self._handle.flush()

    def close(self) -> None:
        """Close the underlying file handle. Closing is idempotent."""

        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def sink_failures(self) -> tuple[AuditSinkFailure, ...]:
        """Return sink failures captured by this sink."""

        return ()

    def _open_handle(self):
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8")
        return self._handle


class CompositeAuditSink:
    """
    Fan out audit events to multiple sinks.

    Sink failures are captured structurally and do not prevent later sinks from
    receiving the same event.
    """

    def __init__(self, sinks: tuple[object, ...]) -> None:
        if not sinks:
            raise ValueError("sinks must contain at least one sink")
        self._sinks = tuple(sinks)
        self._failures: list[AuditSinkFailure] = []

    def emit(self, event: AuditEvent) -> AuditEvent:
        """Emit one event to every configured sink."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception as exc:
                self._failures.append(
                    _failure_from_exception(
                        sink,
                        "emit",
                        exc,
                        event_id=event.event_id,
                    )
                )
        return event

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return the first non-empty live snapshot from configured sinks."""

        for sink in self._sinks:
            snapshot = _call_optional_snapshot(sink)
            if snapshot:
                return snapshot
        return ()

    def flush(self) -> None:
        """Flush all sinks and capture sink failures."""

        for sink in self._sinks:
            try:
                _call_optional(sink, "flush")
            except Exception as exc:
                self._failures.append(_failure_from_exception(sink, "flush", exc))

    def close(self) -> None:
        """Close all sinks and capture sink failures. Closing is idempotent."""

        for sink in self._sinks:
            try:
                _call_optional(sink, "close")
            except Exception as exc:
                self._failures.append(_failure_from_exception(sink, "close", exc))

    def sink_failures(self) -> tuple[AuditSinkFailure, ...]:
        """Return failures captured by this sink and child sinks."""

        failures = list(self._failures)
        for sink in self._sinks:
            failures.extend(_call_optional_failures(sink))
        return tuple(failures)


class AuditLog:
    """Facade used by Core services to emit audit events."""

    def __init__(self, sink: object | None = None) -> None:
        self._sink = sink if sink is not None else InMemoryAuditSink()
        self._failures: list[AuditSinkFailure] = []

    def emit(self, event: AuditEvent) -> AuditEvent:
        """Emit an audit event through the configured sink."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        try:
            self._sink.emit(event)
        except Exception as exc:
            self._failures.append(
                _failure_from_exception(
                    self._sink,
                    "emit",
                    exc,
                    event_id=event.event_id,
                )
            )
        return event

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return an immutable snapshot of retained audit events."""

        return _call_optional_snapshot(self._sink)

    def flush(self) -> None:
        """Flush the configured sink. Flush is idempotent."""

        try:
            _call_optional(self._sink, "flush")
        except Exception as exc:
            self._failures.append(_failure_from_exception(self._sink, "flush", exc))

    def close(self) -> None:
        """Close the configured sink. Close is idempotent."""

        try:
            _call_optional(self._sink, "close")
        except Exception as exc:
            self._failures.append(_failure_from_exception(self._sink, "close", exc))

    def sink_failures(self) -> tuple[AuditSinkFailure, ...]:
        """Return structured sink failures captured by the audit log."""

        return tuple(self._failures) + _call_optional_failures(self._sink)


def _failure_from_exception(
    sink: object,
    operation: str,
    exception: Exception,
    *,
    event_id: str | None = None,
) -> AuditSinkFailure:
    return AuditSinkFailure(
        sink_name=type(sink).__name__,
        operation=operation,
        exception_type=type(exception).__name__,
        message=str(exception),
        event_id=event_id,
    )


def _call_optional(sink: object, method_name: str) -> None:
    method = getattr(sink, method_name, None)
    if method is not None:
        method()


def _call_optional_snapshot(sink: object) -> tuple[AuditEvent, ...]:
    method = getattr(sink, "snapshot", None)
    if method is None:
        return ()
    return tuple(method())


def _call_optional_failures(sink: object) -> tuple[AuditSinkFailure, ...]:
    method = getattr(sink, "sink_failures", None)
    if method is None:
        return ()
    return tuple(method())
