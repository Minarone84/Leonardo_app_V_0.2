import json
from pathlib import Path

import pytest

from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotV1,
    ResearchWorkspaceSnapshotValidationError,
)


FIXTURE = Path("tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json")


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot"]


def test_frozen_snapshot_fixture_round_trips_with_exact_content_hash():
    snapshot = ResearchWorkspaceSnapshotV1.from_dict(_payload())
    assert snapshot.content_hash == "9b716d0a2b302b6d40334e1a1dc3b5e9971f471038579210356782aad0070c36"
    assert snapshot.to_dict() == _payload()
    assert tuple(chart.workspace_position for chart in snapshot.charts) == (1, 3)


@pytest.mark.parametrize("field", ["slot_id", "session_id", "task_id", "widget_id"])
def test_runtime_fields_are_not_accepted(field):
    payload = _payload()
    payload["charts"][0][field] = "forbidden"
    with pytest.raises((TypeError, ResearchWorkspaceSnapshotValidationError)):
        ResearchWorkspaceSnapshotV1.from_dict(payload)


def test_snapshot_models_import_without_qt():
    source = Path("src/leonardo/research/workspace_snapshot.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
