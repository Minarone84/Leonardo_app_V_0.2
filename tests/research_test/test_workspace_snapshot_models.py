import json
from dataclasses import replace
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
    raw = FIXTURE.read_bytes()
    snapshot = ResearchWorkspaceSnapshotV1.from_dict(_payload())
    assert snapshot.content_hash == "9b716d0a2b302b6d40334e1a1dc3b5e9971f471038579210356782aad0070c36"
    assert snapshot.schema_version == "1.0"
    assert snapshot.notebook_id is None
    assert snapshot.to_dict() == _payload()
    assert snapshot.canonical_json_bytes() == (
        json.dumps(
            _payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    assert b'"notebook_id"' not in snapshot.canonical_json_bytes()
    assert raw
    assert tuple(chart.workspace_position for chart in snapshot.charts) == (1, 3)


def test_schema_1_1_serializes_null_and_assigned_notebook_identity():
    legacy = ResearchWorkspaceSnapshotV1.from_dict(_payload())
    unassigned = ResearchWorkspaceSnapshotV1.build(
        snapshot_id=legacy.snapshot_id,
        display_name=legacy.display_name,
        description=legacy.description,
        created_at_utc=legacy.created_at_utc,
        updated_at_utc=legacy.updated_at_utc,
        workspace=legacy.workspace,
        charts=legacy.charts,
    )
    assigned = ResearchWorkspaceSnapshotV1.build(
        snapshot_id=legacy.snapshot_id,
        display_name=legacy.display_name,
        description=legacy.description,
        created_at_utc=legacy.created_at_utc,
        updated_at_utc=legacy.updated_at_utc,
        workspace=legacy.workspace,
        charts=legacy.charts,
        notebook_id="notebook_research",
    )

    assert unassigned.schema_version == "1.1"
    assert unassigned.to_dict()["notebook_id"] is None
    assert assigned.to_dict()["notebook_id"] == "notebook_research"
    assert assigned.content_hash != unassigned.content_hash
    assert ResearchWorkspaceSnapshotV1.from_dict(assigned.to_dict()) == assigned


@pytest.mark.parametrize(
    "notebook_id",
    ["", " notebook", "notebook ", "../notebook", "folder/notebook"],
)
def test_schema_1_1_rejects_invalid_notebook_ids(notebook_id):
    legacy = ResearchWorkspaceSnapshotV1.from_dict(_payload())
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        ResearchWorkspaceSnapshotV1.build(
            snapshot_id=legacy.snapshot_id,
            display_name=legacy.display_name,
            description=legacy.description,
            created_at_utc=legacy.created_at_utc,
            updated_at_utc=legacy.updated_at_utc,
            workspace=legacy.workspace,
            charts=legacy.charts,
            notebook_id=notebook_id,
        )


def test_snapshot_schema_versions_enforce_exact_keys():
    legacy = _payload()
    with_notebook = dict(legacy, notebook_id=None)
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        ResearchWorkspaceSnapshotV1.from_dict(with_notebook)

    current = ResearchWorkspaceSnapshotV1.build(
        snapshot_id="snapshot_current",
        display_name="Current",
        description="",
        created_at_utc=ResearchWorkspaceSnapshotV1.from_dict(legacy).created_at_utc,
        updated_at_utc=ResearchWorkspaceSnapshotV1.from_dict(legacy).updated_at_utc,
        workspace=ResearchWorkspaceSnapshotV1.from_dict(legacy).workspace,
        charts=ResearchWorkspaceSnapshotV1.from_dict(legacy).charts,
    ).to_dict()
    current.pop("notebook_id")
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        ResearchWorkspaceSnapshotV1.from_dict(current)

    unknown = dict(legacy, schema_version="2.0")
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        ResearchWorkspaceSnapshotV1.from_dict(unknown)

    extra = dict(legacy, unexpected=True)
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        ResearchWorkspaceSnapshotV1.from_dict(extra)


def test_schema_1_0_instance_cannot_carry_notebook_id():
    legacy = ResearchWorkspaceSnapshotV1.from_dict(_payload())
    with pytest.raises(ResearchWorkspaceSnapshotValidationError):
        replace(legacy, notebook_id="notebook_research")


@pytest.mark.parametrize("field", ["slot_id", "session_id", "task_id", "widget_id"])
def test_runtime_fields_are_not_accepted(field):
    payload = _payload()
    payload["charts"][0][field] = "forbidden"
    with pytest.raises((TypeError, ResearchWorkspaceSnapshotValidationError)):
        ResearchWorkspaceSnapshotV1.from_dict(payload)


def test_snapshot_models_import_without_qt():
    source = Path("src/leonardo/research/workspace_snapshot.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
