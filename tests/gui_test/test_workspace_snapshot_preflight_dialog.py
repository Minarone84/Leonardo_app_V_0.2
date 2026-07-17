import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from leonardo.gui.windows.workspace_snapshot_preflight_dialog import WorkspaceSnapshotPreflightDialog
from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotCompatibilityReport


def test_preflight_load_is_enabled_only_without_blockers():
    QApplication.instance() or QApplication([])
    compatible = ResearchWorkspaceSnapshotCompatibilityReport(
        "snapshot_a", "replace", True, ()
    )
    dialog = WorkspaceSnapshotPreflightDialog(compatible)
    assert dialog.findChild(QPushButton, "research.workspace_snapshot_preflight_dialog.button.load").isEnabled()
    blocked = WorkspaceSnapshotPreflightDialog(
        ResearchWorkspaceSnapshotCompatibilityReport(
            "snapshot_a", "replace", False, (), ("missing dataset",)
        )
    )
    assert not blocked.findChild(QPushButton, "research.workspace_snapshot_preflight_dialog.button.load").isEnabled()
