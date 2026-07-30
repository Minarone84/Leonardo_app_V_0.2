from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread

import pytest

from leonardo.research.notebook import ResearchNotebookAnnotationSettingsV1
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_store import ResearchNotebookStore
from leonardo.research.workspace_notebook_link import (
    ResearchWorkspaceNotebookLinkError,
    ResearchWorkspaceNotebookLinkService,
)
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotV1,
)
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore


FIXTURE = Path("tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json")


def _legacy_snapshot() -> ResearchWorkspaceSnapshotV1:
    return ResearchWorkspaceSnapshotV1.from_dict(
        json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot"]
    )


def _systems(tmp_path: Path):
    ticks = iter(
        datetime(2026, 7, 20, 10, tzinfo=timezone.utc) + timedelta(minutes=index)
        for index in range(40)
    )
    snapshot_store = ResearchWorkspaceSnapshotStore(
        tmp_path / "snapshots",
        clock=lambda: next(ticks),
        id_factory=lambda: "generated",
    )
    notebook_store = ResearchNotebookStore(
        tmp_path / "notebooks",
        clock=lambda: next(ticks),
        id_factory=lambda: "generated",
    )
    notebook_service = ResearchNotebookService(notebook_store)
    link = ResearchWorkspaceNotebookLinkService(snapshot_store, notebook_service)
    return snapshot_store, notebook_service, link


def _create_snapshot(store, snapshot_id: str):
    source = _legacy_snapshot()
    return store.create(
        ResearchWorkspaceSnapshotDraft(
            snapshot_id=snapshot_id,
            display_name=snapshot_id,
            description="",
            workspace=source.workspace,
            charts=source.charts,
        )
    )


def _create_notebook(service, notebook_id: str):
    return service.create_notebook(
        service.build_draft(
            notebook_id=notebook_id,
            display_name=notebook_id,
            annotation_settings=ResearchNotebookAnnotationSettingsV1(),
        )
    )


def test_assignment_replacement_multi_snapshot_and_exact_unassignment(tmp_path):
    snapshots, notebooks, link = _systems(tmp_path)
    _create_snapshot(snapshots, "snapshot_one")
    _create_snapshot(snapshots, "snapshot_two")
    _create_notebook(notebooks, "notebook_one")
    _create_notebook(notebooks, "notebook_two")

    first = link.assign_notebook("snapshot_one", "notebook_one")
    assert first.notebook_id == "notebook_one"
    assert link.assign_notebook("snapshot_one", "notebook_one") == first
    assert link.assign_notebook("snapshot_two", "notebook_one").notebook_id == (
        "notebook_one"
    )
    assert link.assign_notebook("snapshot_one", "notebook_two").notebook_id == (
        "notebook_two"
    )
    with pytest.raises(ResearchWorkspaceNotebookLinkError):
        link.unassign_notebook("snapshot_one", "notebook_one")
    assert link.unassign_notebook(
        "snapshot_one", "notebook_two"
    ).notebook_id is None


def test_reference_validation_and_missing_notebook_assignment(tmp_path):
    snapshots, notebooks, link = _systems(tmp_path)
    _create_snapshot(snapshots, "snapshot_one")
    _create_notebook(notebooks, "notebook_one")

    assert link.validate_notebook_reference(None) == ()
    assert link.validate_notebook_reference("notebook_one") == ()
    assert link.validate_notebook_reference("notebook_missing") == (
        "assigned notebook is unavailable: notebook_missing",
    )
    with pytest.raises(KeyError):
        link.assign_notebook("snapshot_one", "notebook_missing")


def test_coordinated_delete_clears_all_matching_references_only(tmp_path):
    snapshots, notebooks, link = _systems(tmp_path)
    for snapshot_id in ("snapshot_one", "snapshot_two", "snapshot_other"):
        _create_snapshot(snapshots, snapshot_id)
    for notebook_id in ("notebook_one", "notebook_other"):
        _create_notebook(notebooks, notebook_id)
    link.assign_notebook("snapshot_one", "notebook_one")
    link.assign_notebook("snapshot_two", "notebook_one")
    link.assign_notebook("snapshot_other", "notebook_other")

    deleted = link.delete_notebook_with_reference_cleanup("notebook_one")

    assert deleted.notebook_id == "notebook_one"
    assert snapshots.load("snapshot_one").notebook_id is None
    assert snapshots.load("snapshot_two").notebook_id is None
    assert snapshots.load("snapshot_other").notebook_id == "notebook_other"
    with pytest.raises(KeyError):
        notebooks.load_notebook("notebook_one")


def test_partial_cleanup_failure_rolls_back_and_prevents_delete(
    tmp_path, monkeypatch
):
    snapshots, notebooks, link = _systems(tmp_path)
    for snapshot_id in ("snapshot_one", "snapshot_two"):
        _create_snapshot(snapshots, snapshot_id)
    _create_notebook(notebooks, "notebook_one")
    link.assign_notebook("snapshot_one", "notebook_one")
    link.assign_notebook("snapshot_two", "notebook_one")
    original = snapshots.replace_notebook_id
    calls = 0

    def fail_second(snapshot_id, notebook_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("cleanup failed")
        return original(snapshot_id, notebook_id)

    monkeypatch.setattr(snapshots, "replace_notebook_id", fail_second)
    with pytest.raises(ResearchWorkspaceNotebookLinkError, match="cleanup failed"):
        link.delete_notebook_with_reference_cleanup("notebook_one")
    assert snapshots.load("snapshot_one").notebook_id == "notebook_one"
    assert snapshots.load("snapshot_two").notebook_id == "notebook_one"
    assert notebooks.load_notebook("notebook_one").notebook_id == "notebook_one"


def test_notebook_delete_failure_restores_references(tmp_path, monkeypatch):
    snapshots, notebooks, link = _systems(tmp_path)
    _create_snapshot(snapshots, "snapshot_one")
    _create_notebook(notebooks, "notebook_one")
    link.assign_notebook("snapshot_one", "notebook_one")

    def fail(_notebook_id):
        raise OSError("delete failed")

    monkeypatch.setattr(notebooks, "delete_notebook", fail)
    with pytest.raises(OSError, match="delete failed"):
        link.delete_notebook_with_reference_cleanup("notebook_one")
    assert snapshots.load("snapshot_one").notebook_id == "notebook_one"


def test_delete_rollback_failure_reports_both_failures(tmp_path, monkeypatch):
    snapshots, notebooks, link = _systems(tmp_path)
    _create_snapshot(snapshots, "snapshot_one")
    _create_notebook(notebooks, "notebook_one")
    link.assign_notebook("snapshot_one", "notebook_one")
    original = snapshots.replace_notebook_id

    def fail_restore(snapshot_id, notebook_id):
        if notebook_id == "notebook_one":
            raise OSError("rollback failed")
        return original(snapshot_id, notebook_id)

    monkeypatch.setattr(snapshots, "replace_notebook_id", fail_restore)
    monkeypatch.setattr(
        notebooks,
        "delete_notebook",
        lambda _notebook_id: (_ for _ in ()).throw(OSError("delete failed")),
    )
    with pytest.raises(
        ResearchWorkspaceNotebookLinkError,
        match="delete failed.*rollback failed",
    ):
        link.delete_notebook_with_reference_cleanup("notebook_one")


def test_assignment_and_delete_share_one_serialization_lock(tmp_path, monkeypatch):
    snapshots, notebooks, link = _systems(tmp_path)
    _create_snapshot(snapshots, "snapshot_one")
    _create_notebook(notebooks, "notebook_one")
    entered = Event()
    release = Event()
    finished = Event()
    original = notebooks.load_notebook

    def blocked(notebook_id):
        entered.set()
        release.wait(2)
        return original(notebook_id)

    monkeypatch.setattr(notebooks, "load_notebook", blocked)
    assigning = Thread(
        target=link.assign_notebook,
        args=("snapshot_one", "notebook_one"),
    )
    deleting = Thread(
        target=lambda: (
            link.delete_notebook_with_reference_cleanup("notebook_one"),
            finished.set(),
        )
    )
    assigning.start()
    assert entered.wait(1)
    deleting.start()
    assert not finished.wait(0.05)
    release.set()
    assigning.join(2)
    deleting.join(2)
    assert finished.is_set()


def test_link_public_api_contains_no_gui_or_path_values():
    annotations = ResearchWorkspaceNotebookLinkService.__dict__
    source = Path(
        "src/leonardo/research/workspace_notebook_link.py"
    ).read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "QWidget" not in source
    assert "Path" not in source
    assert annotations
