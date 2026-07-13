"""Window runtime-state authority without Qt ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock


@dataclass(frozen=True)
class WindowSnapshot:
    window_id: str
    title: str
    window_type: str
    status: str
    opened_at_utc: datetime | None
    focused_at_utc: datetime | None
    closed_at_utc: datetime | None
    metadata: dict[str, object]


@dataclass
class _WindowRecord:
    window_id: str
    title: str
    window_type: str
    status: str = "registered"
    opened_at_utc: datetime | None = None
    focused_at_utc: datetime | None = None
    closed_at_utc: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class WindowRegistry:
    def __init__(self) -> None:
        self._records: dict[str, _WindowRecord] = {}
        self._lock = RLock()

    def register_window(
        self,
        window_id: str,
        *,
        title: str,
        window_type: str = "window",
        metadata: dict[str, object] | None = None,
    ) -> WindowSnapshot:
        _text(window_id, "window_id")
        _text(title, "title")
        with self._lock:
            if window_id in self._records:
                existing = self._records[window_id]
                if existing.title == title and existing.window_type == window_type:
                    return _snapshot(existing)
                raise ValueError(f"Window already registered: {window_id}")
            record = _WindowRecord(
                window_id=window_id,
                title=title,
                window_type=window_type,
                metadata=dict(metadata or {}),
            )
            self._records[window_id] = record
            return _snapshot(record)

    def open_window(self, window_id: str) -> WindowSnapshot:
        with self._lock:
            record = self._require_locked(window_id)
            record.status = "open"
            record.opened_at_utc = record.opened_at_utc or datetime.now(UTC)
            record.closed_at_utc = None
            return _snapshot(record)

    def focus_window(self, window_id: str) -> WindowSnapshot:
        with self._lock:
            record = self._require_locked(window_id)
            if record.status != "open":
                raise RuntimeError(f"Window is not open: {window_id}")
            record.focused_at_utc = datetime.now(UTC)
            return _snapshot(record)

    def request_window_close(self, window_id: str) -> WindowSnapshot:
        with self._lock:
            record = self._require_locked(window_id)
            record.status = "close_requested"
            return _snapshot(record)

    def close_window(self, window_id: str) -> WindowSnapshot:
        with self._lock:
            record = self._require_locked(window_id)
            record.status = "closed"
            record.closed_at_utc = datetime.now(UTC)
            return _snapshot(record)

    def list_windows(self) -> tuple[WindowSnapshot, ...]:
        with self._lock:
            return tuple(_snapshot(self._records[key]) for key in sorted(self._records))

    def open_windows(self) -> tuple[WindowSnapshot, ...]:
        return tuple(item for item in self.list_windows() if item.status in {"open", "close_requested"})

    def _require_locked(self, window_id: str) -> _WindowRecord:
        record = self._records.get(window_id)
        if record is None:
            raise KeyError(f"Window is not registered: {window_id}")
        return record


def _snapshot(record: _WindowRecord) -> WindowSnapshot:
    return WindowSnapshot(
        window_id=record.window_id,
        title=record.title,
        window_type=record.window_type,
        status=record.status,
        opened_at_utc=record.opened_at_utc,
        focused_at_utc=record.focused_at_utc,
        closed_at_utc=record.closed_at_utc,
        metadata=dict(record.metadata),
    )


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
