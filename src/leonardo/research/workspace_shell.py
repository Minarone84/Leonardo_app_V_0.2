"""Thread-safe transient placement state for Research chart shells."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


MAX_RESEARCH_WORKSPACE_POSITIONS = 8


class ResearchWorkspaceShellStateError(RuntimeError):
    """Raised when transient Research chart placement cannot be changed."""


@dataclass(frozen=True, slots=True)
class ResearchChartPlacement:
    slot_id: int
    workspace_position: int
    detached: bool


class ResearchWorkspaceShellState:
    """Own transient chart placement independently from chart membership."""

    def __init__(self) -> None:
        self._placements: dict[int, ResearchChartPlacement] = {}
        self._lock = RLock()

    def register_slot(self, slot_id: int) -> ResearchChartPlacement:
        with self._lock:
            resolved = self._require_slot_id(slot_id)
            if resolved in self._placements:
                raise ResearchWorkspaceShellStateError(
                    f"Research chart slot {resolved} already has a placement"
                )
            free = self._free_positions_locked()
            if not free:
                raise ResearchWorkspaceShellStateError(
                    "Research workspace has no free positions"
                )
            placement = ResearchChartPlacement(resolved, free[0], False)
            self._placements[resolved] = placement
            return placement

    def remove_slot(self, slot_id: int) -> ResearchChartPlacement:
        with self._lock:
            resolved = self._require_slot_id(slot_id)
            try:
                return self._placements.pop(resolved)
            except KeyError as error:
                raise ResearchWorkspaceShellStateError(
                    f"Research chart slot {resolved} has no placement"
                ) from error

    def move_slot(
        self, slot_id: int, target_position: int
    ) -> tuple[ResearchChartPlacement, ...]:
        with self._lock:
            resolved = self._require_slot_id(slot_id)
            target = self._require_position(target_position)
            source = self._placement_locked(resolved)
            if source.detached:
                raise ResearchWorkspaceShellStateError(
                    "Detached Research charts cannot be moved"
                )
            occupant = next(
                (
                    placement
                    for placement in self._placements.values()
                    if placement.workspace_position == target
                ),
                None,
            )
            if occupant is not None and occupant.detached:
                raise ResearchWorkspaceShellStateError(
                    f"Workspace position {target} is reserved by a detached chart"
                )
            if occupant is None:
                self._placements[resolved] = ResearchChartPlacement(
                    resolved, target, False
                )
            elif occupant.slot_id != resolved:
                self._placements[resolved] = ResearchChartPlacement(
                    resolved, target, False
                )
                self._placements[occupant.slot_id] = ResearchChartPlacement(
                    occupant.slot_id, source.workspace_position, False
                )
            return self._placements_locked()

    def detach_slot(self, slot_id: int) -> ResearchChartPlacement:
        with self._lock:
            placement = self._placement_locked(self._require_slot_id(slot_id))
            if placement.detached:
                return placement
            detached = ResearchChartPlacement(
                placement.slot_id, placement.workspace_position, True
            )
            self._placements[placement.slot_id] = detached
            return detached

    def dock_slot(self, slot_id: int) -> ResearchChartPlacement:
        with self._lock:
            placement = self._placement_locked(self._require_slot_id(slot_id))
            if not placement.detached:
                return placement
            attached = ResearchChartPlacement(
                placement.slot_id, placement.workspace_position, False
            )
            self._placements[placement.slot_id] = attached
            return attached

    def placement_for(self, slot_id: int) -> ResearchChartPlacement:
        with self._lock:
            return self._placement_locked(self._require_slot_id(slot_id))

    def placements(self) -> tuple[ResearchChartPlacement, ...]:
        with self._lock:
            return self._placements_locked()

    def attached_slot_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                placement.slot_id
                for placement in self._placements_locked()
                if not placement.detached
            )

    def detached_slot_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                placement.slot_id
                for placement in self._placements_locked()
                if placement.detached
            )

    def reserved_positions(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                placement.workspace_position
                for placement in self._placements_locked()
            )

    def free_positions(self) -> tuple[int, ...]:
        with self._lock:
            return self._free_positions_locked()

    def clear(self) -> None:
        with self._lock:
            self._placements.clear()

    def _placement_locked(self, slot_id: int) -> ResearchChartPlacement:
        try:
            return self._placements[slot_id]
        except KeyError as error:
            raise ResearchWorkspaceShellStateError(
                f"Research chart slot {slot_id} has no placement"
            ) from error

    def _placements_locked(self) -> tuple[ResearchChartPlacement, ...]:
        return tuple(
            sorted(
                self._placements.values(),
                key=lambda placement: placement.workspace_position,
            )
        )

    def _free_positions_locked(self) -> tuple[int, ...]:
        reserved = {
            placement.workspace_position for placement in self._placements.values()
        }
        return tuple(
            position
            for position in range(1, MAX_RESEARCH_WORKSPACE_POSITIONS + 1)
            if position not in reserved
        )

    @staticmethod
    def _require_slot_id(slot_id: int) -> int:
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ResearchWorkspaceShellStateError(
                "slot_id must be an integer from 1 through 8"
            )
        return slot_id

    @staticmethod
    def _require_position(position: int) -> int:
        if type(position) is not int or not 1 <= position <= 8:
            raise ResearchWorkspaceShellStateError(
                "workspace_position must be an integer from 1 through 8"
            )
        return position
