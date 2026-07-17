import json
from datetime import datetime, timezone
from pathlib import Path

from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotV1,
)
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore


def _snapshot():
    payload = json.loads(
        Path("tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json").read_text(
            encoding="utf-8"
        )
    )["snapshot"]
    return ResearchWorkspaceSnapshotV1.from_dict(payload)


def _draft(snapshot, *, name=None):
    return ResearchWorkspaceSnapshotDraft(
        snapshot_id=snapshot.snapshot_id,
        display_name=name or snapshot.display_name,
        description=snapshot.description,
        workspace=snapshot.workspace,
        charts=snapshot.charts,
    )


def test_store_create_update_load_list_and_delete(tmp_path):
    now = datetime(2026, 7, 17, 11, tzinfo=timezone.utc)
    store = ResearchWorkspaceSnapshotStore(tmp_path / "snapshots", clock=lambda: now)
    assert store.list_summaries() == ()
    assert not store.root_dir.exists()
    created = store.create(_draft(_snapshot()))
    assert store.load(created.snapshot_id) == created
    assert store.list_summaries()[0].chart_count == 2
    updated = store.update(created.snapshot_id, _draft(created, name="Updated Layout"))
    assert updated.created_at_utc == created.created_at_utc
    assert updated.display_name == "Updated Layout"
    store.delete(created.snapshot_id)
    assert store.list_summaries() == ()


def test_invalid_direct_child_remains_visible_and_is_exactly_deletable(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    path = root / "Invalid Name.json"
    path.write_text("{}", encoding="utf-8")
    store = ResearchWorkspaceSnapshotStore(root)
    summary = store.list_summaries()[0]
    assert not summary.valid
    store.delete("Invalid Name")
    assert not path.exists()
