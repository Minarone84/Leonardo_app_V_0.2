import json
from pathlib import Path

from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotV1


def _snapshot():
    payload = json.loads(
        Path("tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json").read_text(
            encoding="utf-8"
        )
    )["snapshot"]
    return ResearchWorkspaceSnapshotV1.from_dict(payload)


def test_frozen_append_position_plan_matches_authority():
    from leonardo.research.workspace_snapshot_service import ResearchWorkspaceSnapshotService

    service = object.__new__(ResearchWorkspaceSnapshotService)
    assert service.plan_append_positions(_snapshot(), (1, 4)) == (
        ("chart_002", 2),
        ("chart_001", 3),
    )
