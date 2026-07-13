"""Operational audit sinks for Leonardo Light V2."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from leonardo.audit import AuditEventV1


class AuditSink(Protocol):
    def emit(self, event: AuditEventV1) -> AuditEventV1: ...
    def snapshot(self) -> tuple[AuditEventV1, ...]: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class AuditSinkFailure:
    sink_name: str
    operation: str
    error_type: str
    message: str


class InMemoryAuditSink:
    def __init__(self, max_events: int = 1000) -> None:
        if type(max_events) is not int or max_events <= 0:
            raise ValueError("max_events must be a positive integer")
        self._events: deque[AuditEventV1] = deque(maxlen=max_events)
        self._lock = RLock()

    @property
    def max_events(self) -> int:
        return int(self._events.maxlen or 0)

    def emit(self, event: AuditEventV1) -> AuditEventV1:
        if not isinstance(event, AuditEventV1):
            raise TypeError("event must be an AuditEventV1")
        with self._lock:
            self._events.append(event)
        return event

    def snapshot(self) -> tuple[AuditEventV1, ...]:
        with self._lock:
            return tuple(self._events)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class JsonlAuditSink:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._handle = None
        self._lock = RLock()

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, event: AuditEventV1) -> AuditEventV1:
        if not isinstance(event, AuditEventV1):
            raise TypeError("event must be an AuditEventV1")
        with self._lock:
            handle = self._open_handle()
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
            handle.flush()
        return event

    def snapshot(self) -> tuple[AuditEventV1, ...]:
        if not self._path.exists():
            return ()
        events: list[AuditEventV1] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(AuditEventV1.from_dict(json.loads(line)))
        return tuple(events)

    def flush(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None

    def _open_handle(self):
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8")
        return self._handle


class CompositeAuditSink:
    def __init__(self, sinks: tuple[AuditSink, ...]) -> None:
        if not sinks:
            raise ValueError("sinks cannot be empty")
        self._sinks = tuple(sinks)
        self._failures: list[AuditSinkFailure] = []

    def emit(self, event: AuditEventV1) -> AuditEventV1:
        delivered = False
        for sink in self._sinks:
            try:
                sink.emit(event)
                delivered = True
            except Exception as exc:  # final sink boundary
                self._failures.append(_failure(sink, "emit", exc))
        if not delivered:
            raise RuntimeError("No audit sink accepted the event")
        return event

    def snapshot(self) -> tuple[AuditEventV1, ...]:
        for sink in self._sinks:
            try:
                events = sink.snapshot()
            except Exception as exc:  # final sink boundary
                self._failures.append(_failure(sink, "snapshot", exc))
                continue
            if events:
                return events
        return ()

    def flush(self) -> None:
        for sink in self._sinks:
            try:
                sink.flush()
            except Exception as exc:  # final sink boundary
                self._failures.append(_failure(sink, "flush", exc))

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception as exc:  # final sink boundary
                self._failures.append(_failure(sink, "close", exc))

    def sink_failures(self) -> tuple[AuditSinkFailure, ...]:
        return tuple(self._failures)


class AuditLog:
    def __init__(self, sink: AuditSink) -> None:
        self._sink = sink

    def emit(self, event: AuditEventV1) -> AuditEventV1:
        return self._sink.emit(event)

    def snapshot(self) -> tuple[AuditEventV1, ...]:
        return self._sink.snapshot()

    def flush(self) -> None:
        self._sink.flush()

    def close(self) -> None:
        self._sink.close()

    def sink_failures(self) -> tuple[AuditSinkFailure, ...]:
        method = getattr(self._sink, "sink_failures", None)
        return tuple(method()) if callable(method) else ()


def _failure(sink: object, operation: str, exc: Exception) -> AuditSinkFailure:
    return AuditSinkFailure(
        sink_name=type(sink).__name__,
        operation=operation,
        error_type=type(exc).__name__,
        message=str(exc),
    )
