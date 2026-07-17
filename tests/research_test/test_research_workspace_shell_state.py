from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from leonardo.research import (
    ResearchChartPlacement,
    ResearchWorkspaceShellState,
    ResearchWorkspaceShellStateError,
)


FIXTURES = Path(__file__).parents[1] / "gui_test" / "fixtures"


def test_frozen_placement_action_replay() -> None:
    actions = json.loads(
        (FIXTURES / "task_1020_chart_shell_input.json").read_text(encoding="utf-8")
    )["placement_actions"]
    expected = json.loads(
        (FIXTURES / "task_1020_chart_shell_expected.json").read_text(encoding="utf-8")
    )["placement_final"]
    state = ResearchWorkspaceShellState()
    for item in actions:
        try:
            if item["action"] == "register":
                state.register_slot(item["slot_id"])
            elif item["action"] == "move":
                state.move_slot(item["slot_id"], item["target_position"])
            elif item["action"] == "detach":
                state.detach_slot(item["slot_id"])
            elif item["action"] == "dock":
                state.dock_slot(item["slot_id"])
            else:
                state.remove_slot(item["slot_id"])
        except ResearchWorkspaceShellStateError:
            assert item.get("expected") == "blocked_detached_reservation"
    assert [
        {
            "slot_id": item.slot_id,
            "workspace_position": item.workspace_position,
            "detached": item.detached,
        }
        for item in state.placements()
    ] == expected["placements"]
    assert list(state.attached_slot_ids()) == expected["attached_slot_order"]
    assert list(state.detached_slot_ids()) == expected["detached_slot_order"]
    assert list(state.reserved_positions()) == expected["reserved_positions"]
    assert list(state.free_positions()) == expected["free_positions"]


def test_moves_swap_empty_and_reject_detached_without_mutation() -> None:
    state = ResearchWorkspaceShellState()
    state.register_slot(1)
    state.register_slot(2)
    state.move_slot(1, 2)
    assert state.placement_for(1).workspace_position == 2
    assert state.placement_for(2).workspace_position == 1
    state.move_slot(2, 5)
    assert state.placement_for(2).workspace_position == 5
    state.detach_slot(1)
    before = state.placements()
    with pytest.raises(ResearchWorkspaceShellStateError):
        state.move_slot(2, 2)
    assert state.placements() == before
    with pytest.raises(ResearchWorkspaceShellStateError):
        state.move_slot(1, 3)


def test_detach_dock_remove_snapshots_and_validation() -> None:
    state = ResearchWorkspaceShellState()
    assert state.register_slot(4) == ResearchChartPlacement(4, 1, False)
    assert state.detach_slot(4) == ResearchChartPlacement(4, 1, True)
    assert state.detach_slot(4) == ResearchChartPlacement(4, 1, True)
    assert state.dock_slot(4) == ResearchChartPlacement(4, 1, False)
    assert state.dock_slot(4) == ResearchChartPlacement(4, 1, False)
    assert state.remove_slot(4) == ResearchChartPlacement(4, 1, False)
    assert state.free_positions() == tuple(range(1, 9))
    for invalid in (True, 0, 9, 1.0, "1"):
        with pytest.raises(ResearchWorkspaceShellStateError):
            state.register_slot(invalid)  # type: ignore[arg-type]


def test_registration_is_thread_safe_and_clear_is_defensive() -> None:
    state = ResearchWorkspaceShellState()
    with ThreadPoolExecutor(max_workers=8) as executor:
        placements = tuple(executor.map(state.register_slot, range(1, 9)))
    assert {item.slot_id for item in placements} == set(range(1, 9))
    assert state.reserved_positions() == tuple(range(1, 9))
    snapshot = state.placements()
    state.clear()
    assert len(snapshot) == 8
    assert state.placements() == ()
