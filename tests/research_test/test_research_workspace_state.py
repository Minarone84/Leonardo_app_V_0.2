from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from itertools import count
import json
from pathlib import Path

import pytest

from leonardo.research import (
    MAX_RESEARCH_CHARTS,
    ChartSessionState,
    ResearchWorkspaceState,
    ResearchWorkspaceStateError,
)


def _workspace():
    sequence = count(1)
    return ResearchWorkspaceState(
        _session_factory=lambda: ChartSessionState(
            session_id=f"session-{next(sequence)}"
        )
    )


def test_capacity_stable_slots_reuse_active_fallback_and_disposal() -> None:
    workspace = _workspace()
    created = tuple(workspace.create_chart() for _ in range(MAX_RESEARCH_CHARTS))
    assert tuple(item.slot_id for item in created) == tuple(range(1, 9))
    assert tuple(item.session_id for item in created) == tuple(
        f"session-{index}" for index in range(1, 9)
    )
    assert workspace.active_slot_id == 8
    assert workspace.is_full
    before = workspace.entries()
    with pytest.raises(ResearchWorkspaceStateError, match="eight charts"):
        workspace.create_chart()
    assert workspace.entries() == before

    removed_three = workspace.session_for(3)
    workspace.remove_chart(3)
    assert removed_three.is_disposed
    assert workspace.slot_ids() == (1, 2, 4, 5, 6, 7, 8)
    assert workspace.active_slot_id == 8
    reused = workspace.create_chart()
    assert (reused.slot_id, reused.session_id) == (3, "session-9")
    assert workspace.slot_ids() == tuple(range(1, 9))

    workspace.set_active(5)
    removed_five = workspace.session_for(5)
    workspace.remove_chart(5)
    assert removed_five.is_disposed
    assert workspace.active_slot_id == 1
    assert tuple(item.slot_id for item in workspace.entries()) == (1, 2, 3, 4, 6, 7, 8)
    assert sum(item.active for item in workspace.entries()) == 1

    sessions = tuple(workspace.session_for(slot_id) for slot_id in workspace.slot_ids())
    workspace.clear()
    assert workspace.chart_count == 0
    assert workspace.active_session is None
    assert all(session.is_disposed for session in sessions)
    assert workspace.dispose() is True
    assert workspace.dispose() is False
    with pytest.raises(ResearchWorkspaceStateError, match="disposed"):
        workspace.create_chart()


def test_invalid_slots_and_concurrent_creation_are_deterministic() -> None:
    workspace = _workspace()
    for slot_id in (0, 9, True, "1"):
        with pytest.raises(ResearchWorkspaceStateError):
            workspace.session_for(slot_id)  # type: ignore[arg-type]
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = tuple(pool.map(lambda _index: workspace.create_chart(), range(8)))
    assert sorted(item.slot_id for item in entries) == list(range(1, 9))
    assert workspace.slot_ids() == tuple(range(1, 9))
    assert len({item.session_id for item in entries}) == 8


def test_removing_final_chart_leaves_no_active_slot() -> None:
    workspace = _workspace()
    entry = workspace.create_chart()
    session = workspace.session_for(entry.slot_id)
    workspace.remove_chart(entry.slot_id)
    assert session.is_disposed
    assert workspace.active_slot_id is None
    assert workspace.active_session is None


def test_frozen_workspace_actions_replay_to_corrected_final_state() -> None:
    fixtures = Path(__file__).parents[1] / "gui_test" / "fixtures"
    frozen = json.loads(
        (fixtures / "task_1019_workspace_input.json").read_text(encoding="utf-8")
    )
    expected = json.loads(
        (fixtures / "task_1019_workspace_expected.json").read_text(encoding="utf-8")
    )["final_state"]
    workspace = _workspace()
    removed_session_ids: list[str] = []

    for action in frozen["actions"]:
        before = workspace.entries()
        if action["action"] == "open_chart":
            if action.get("expected") == "capacity_blocked":
                with pytest.raises(ResearchWorkspaceStateError, match="eight charts"):
                    workspace.create_chart()
                assert workspace.entries() == before
            else:
                entry = workspace.create_chart()
                assert entry.slot_id == action["expected_slot_id"]
                assert entry.session_id == action["session_id"]
        elif action["action"] == "activate":
            workspace.set_active(action["slot_id"])
        elif action["action"] == "remove":
            removed_session_ids.append(workspace.session_for(action["slot_id"]).session_id)
            workspace.remove_chart(action["slot_id"])
        elif action["action"] == "set_mode":
            assert workspace.entries() == before
        else:
            raise AssertionError(f"Unknown frozen action: {action['action']}")

    assert workspace.slot_ids() == tuple(expected["occupied_slot_ids"])
    assert workspace.session_for(3).session_id == expected["slot_3_session_id"]
    assert removed_session_ids == expected["removed_session_ids"]
    assert workspace.active_slot_id == expected["active_slot_id"] == 3
