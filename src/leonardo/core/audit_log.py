"""Audit log base for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from leonardo.contracts.audit import AuditEvent


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


class AuditLog:
    """Facade used by Core services to emit audit events."""

    def __init__(self, sink: InMemoryAuditSink | None = None) -> None:
        self._sink = sink if sink is not None else InMemoryAuditSink()

    def emit(self, event: AuditEvent) -> AuditEvent:
        """Emit an audit event through the configured sink."""

        return self._sink.emit(event)

    def snapshot(self) -> tuple[AuditEvent, ...]:
        """Return an immutable snapshot of retained audit events."""

        return self._sink.snapshot()
