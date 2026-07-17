import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from leonardo.gui.windows.workspace_snapshot_manager_dialog import WorkspaceSnapshotManagerDialog
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
)


def test_manager_lists_invalid_snapshot_for_delete_only():
    QApplication.instance() or QApplication([])
    invalid = ResearchWorkspaceSnapshotSummary(
        "bad file", "bad file", "", 0, None, None, False, "invalid JSON"
    )
    dialog = WorkspaceSnapshotManagerDialog((invalid,))
    dialog.snapshot_list.setCurrentRow(0)
    assert dialog.delete_button.isEnabled()
    assert not dialog.load_button.isEnabled()


def test_manager_shows_frozen_snapshot_recap():
    payload = json.loads(Path("tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json").read_text())["snapshot"]
    snapshot = ResearchWorkspaceSnapshotV1.from_dict(payload)
    summary = ResearchWorkspaceSnapshotSummary(
        snapshot.snapshot_id, snapshot.display_name, snapshot.description,
        len(snapshot.charts), snapshot.created_at_utc, snapshot.updated_at_utc,
    )
    dialog = WorkspaceSnapshotManagerDialog((summary,))
    dialog.set_snapshot(snapshot)
    assert dialog.chart_table.rowCount() == 2


@pytest.mark.parametrize("valid", (True, False))
def test_manager_requires_confirmation_before_exact_delete(monkeypatch, valid):
    QApplication.instance() or QApplication([])
    summary = ResearchWorkspaceSnapshotSummary(
        "snapshot_valid" if valid else "bad file",
        "Named Snapshot" if valid else "Invalid Snapshot",
        "",
        1 if valid else 0,
        None,
        None,
        valid,
        None if valid else "invalid JSON",
    )
    dialog = WorkspaceSnapshotManagerDialog((summary,))
    dialog.snapshot_list.setCurrentRow(0)
    emitted = []
    dialog.delete_requested.connect(emitted.append)
    prompts = []

    def reject(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", reject)
    dialog.delete_button.click()
    assert emitted == []
    assert summary.snapshot_id in prompts[0][2]
    assert summary.display_name in prompts[0][2]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog.delete_button.click()
    assert emitted == [summary.snapshot_id]
