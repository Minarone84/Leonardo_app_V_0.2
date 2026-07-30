import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotV1,
    ResearchWorkspaceSnapshotValidationError,
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
    values = iter(
        (
            datetime(2026, 7, 17, 11, tzinfo=timezone.utc),
            datetime(2026, 7, 17, 12, tzinfo=timezone.utc),
            datetime(2026, 7, 17, 13, tzinfo=timezone.utc),
            datetime(2026, 7, 17, 14, tzinfo=timezone.utc),
            datetime(2026, 7, 17, 15, tzinfo=timezone.utc),
            datetime(2026, 7, 17, 16, tzinfo=timezone.utc),
        )
    )
    store = ResearchWorkspaceSnapshotStore(
        tmp_path / "snapshots", clock=lambda: next(values)
    )
    assert store.list_summaries() == ()
    assert not store.root_dir.exists()
    created = store.create(_draft(_snapshot()))
    assert created.schema_version == "1.1"
    assert created.notebook_id is None
    assert json.loads(store.snapshot_path(created.snapshot_id).read_text())[
        "notebook_id"
    ] is None
    assert store.load(created.snapshot_id) == created
    assert store.list_summaries()[0].chart_count == 2
    original_workspace = created.workspace
    original_charts = created.charts
    assigned = store.replace_notebook_id(created.snapshot_id, "notebook_one")
    assert assigned.notebook_id == "notebook_one"
    assert assigned.created_at_utc == created.created_at_utc
    assert assigned.updated_at_utc > created.updated_at_utc
    assert assigned.workspace == original_workspace
    assert assigned.charts == original_charts
    assert assigned.content_hash != created.content_hash

    replaced = store.replace_notebook_id(created.snapshot_id, "notebook_two")
    assert replaced.notebook_id == "notebook_two"
    assert replaced.content_hash != assigned.content_hash
    updated = store.update(created.snapshot_id, _draft(created, name="Updated Layout"))
    assert updated.created_at_utc == created.created_at_utc
    assert updated.display_name == "Updated Layout"
    assert updated.notebook_id == "notebook_two"
    assert updated.workspace == original_workspace
    assert updated.charts == original_charts
    unassigned = store.replace_notebook_id(created.snapshot_id, None)
    assert unassigned.notebook_id is None
    assert store.list_summaries()[0].notebook_id is None
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        store.replace_notebook_id(created.snapshot_id, "../invalid")
    store.delete(created.snapshot_id)
    assert store.list_summaries() == ()


def test_store_loads_schema_1_0_without_rewriting_bytes(tmp_path):
    snapshot = _snapshot()
    root = tmp_path / "snapshots"
    root.mkdir()
    path = root / f"{snapshot.snapshot_id}.json"
    original = snapshot.canonical_json_bytes()
    path.write_bytes(original)

    loaded = ResearchWorkspaceSnapshotStore(root).load(snapshot.snapshot_id)

    assert loaded.schema_version == "1.0"
    assert loaded.notebook_id is None
    assert path.read_bytes() == original


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
