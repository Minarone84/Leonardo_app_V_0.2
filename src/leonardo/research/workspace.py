"""Thread-safe membership state for the eight-slot Research workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from leonardo.data import MarketId
from leonardo.research.session import ChartSessionState


MAX_RESEARCH_CHARTS = 8


class ResearchWorkspaceStateError(RuntimeError):
    """Raised when Research workspace membership cannot be changed."""


@dataclass(frozen=True, slots=True)
class ResearchChartSlotEntry:
    slot_id: int
    session_id: str
    active: bool
    selected_market_id: MarketId | None
    generation: int
    study_count: int


class ResearchWorkspaceState:
    """Own logical chart-slot membership and deterministic active selection."""

    def __init__(
        self,
        *,
        _session_factory: Callable[[], ChartSessionState] = ChartSessionState,
    ) -> None:
        if not callable(_session_factory):
            raise TypeError("_session_factory must be callable")
        self._session_factory = _session_factory
        self._sessions: dict[int, ChartSessionState] = {}
        self._active_slot_id: int | None = None
        self._disposed = False
        self._lock = RLock()

    @property
    def active_slot_id(self) -> int | None:
        with self._lock:
            return self._active_slot_id

    @property
    def active_session(self) -> ChartSessionState | None:
        with self._lock:
            if self._active_slot_id is None:
                return None
            return self._sessions[self._active_slot_id]

    @property
    def is_full(self) -> bool:
        with self._lock:
            return len(self._sessions) == MAX_RESEARCH_CHARTS

    @property
    def chart_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    @property
    def is_disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def create_chart(self) -> ResearchChartSlotEntry:
        with self._lock:
            self._ensure_active_locked()
            if len(self._sessions) >= MAX_RESEARCH_CHARTS:
                raise ResearchWorkspaceStateError(
                    "Research workspace already contains eight charts"
                )
            slot_id = next(
                slot_id
                for slot_id in range(1, MAX_RESEARCH_CHARTS + 1)
                if slot_id not in self._sessions
            )
            session = self._session_factory()
            if not isinstance(session, ChartSessionState):
                raise TypeError("_session_factory must return ChartSessionState")
            self._sessions[slot_id] = session
            self._active_slot_id = slot_id
            return self._entry_locked(slot_id)

    def remove_chart(self, slot_id: int) -> ResearchChartSlotEntry:
        with self._lock:
            self._ensure_active_locked()
            resolved = self._require_slot_id(slot_id)
            session = self._sessions.get(resolved)
            if session is None:
                raise ResearchWorkspaceStateError(
                    f"Research chart slot {resolved} is not occupied"
                )
            removed = self._entry_locked(resolved)
            del self._sessions[resolved]
            if self._active_slot_id == resolved:
                self._active_slot_id = min(self._sessions, default=None)
            session.dispose()
            return removed

    def set_active(self, slot_id: int) -> ResearchChartSlotEntry:
        with self._lock:
            self._ensure_active_locked()
            resolved = self._require_slot_id(slot_id)
            if resolved not in self._sessions:
                raise ResearchWorkspaceStateError(
                    f"Research chart slot {resolved} is not occupied"
                )
            self._active_slot_id = resolved
            return self._entry_locked(resolved)

    def session_for(self, slot_id: int) -> ChartSessionState:
        with self._lock:
            resolved = self._require_slot_id(slot_id)
            try:
                return self._sessions[resolved]
            except KeyError as error:
                raise ResearchWorkspaceStateError(
                    f"Research chart slot {resolved} is not occupied"
                ) from error

    def slot_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(self._sessions))

    def entries(self) -> tuple[ResearchChartSlotEntry, ...]:
        with self._lock:
            return tuple(self._entry_locked(slot_id) for slot_id in sorted(self._sessions))

    def clear(self) -> None:
        with self._lock:
            self._ensure_active_locked()
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            self._active_slot_id = None
            for session in sessions:
                session.dispose()

    def dispose(self) -> bool:
        with self._lock:
            if self._disposed:
                return False
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            self._active_slot_id = None
            self._disposed = True
            for session in sessions:
                session.dispose()
            return True

    def _entry_locked(self, slot_id: int) -> ResearchChartSlotEntry:
        session = self._sessions[slot_id]
        return ResearchChartSlotEntry(
            slot_id=slot_id,
            session_id=session.session_id,
            active=slot_id == self._active_slot_id,
            selected_market_id=session.selected_market_id,
            generation=session.generation,
            study_count=session.study_count,
        )

    def _ensure_active_locked(self) -> None:
        if self._disposed:
            raise ResearchWorkspaceStateError("Research workspace is disposed")

    @staticmethod
    def _require_slot_id(slot_id: int) -> int:
        if type(slot_id) is not int or not 1 <= slot_id <= MAX_RESEARCH_CHARTS:
            raise ResearchWorkspaceStateError("slot_id must be an integer from 1 through 8")
        return slot_id
