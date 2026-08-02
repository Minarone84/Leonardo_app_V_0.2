import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.windows.workspace_snapshot_save_dialog import WorkspaceSnapshotSaveDialog
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotSummary,
    WorkspaceSnapshotCapture,
    WorkspaceSnapshotChartCapture,
    WorkspaceSnapshotPriceScaleV1,
    WorkspaceSnapshotViewportV1,
)


def test_save_dialog_has_frozen_ids_and_zero_study_recap():
    QApplication.instance() or QApplication([])
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    chart = WorkspaceSnapshotChartCapture(
        "chart_001", 1, False, market, object(), (), (),
        WorkspaceSnapshotViewportV1(1, 80), WorkspaceSnapshotPriceScaleV1(True),
        False, {"price": 720},
    )
    dialog = WorkspaceSnapshotSaveDialog(
        WorkspaceSnapshotCapture("scroll_4", False, "chart_001", (chart,))
    )
    assert dialog.objectName() == "research.workspace_snapshot_save_dialog"
    assert dialog.chart_table.rowCount() == 1
    assert not dialog.save_button.isEnabled()


def test_workspace_save_update_uses_selected_canonical_name_and_preserves_create_draft():
    app = QApplication.instance() or QApplication([])
    before = app.styleSheet()
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    chart = WorkspaceSnapshotChartCapture(
        "chart_001", 1, False, market, object(), (), (),
        WorkspaceSnapshotViewportV1(1, 80), WorkspaceSnapshotPriceScaleV1(True),
        False, {"price": 720},
    )
    summaries = (
        ResearchWorkspaceSnapshotSummary(
            "snapshot_one", "Workspace One", "First description", 1, None, None
        ),
        ResearchWorkspaceSnapshotSummary(
            "snapshot_two", "Workspace Two", "Second description", 1, None, None
        ),
    )
    dialog = WorkspaceSnapshotSaveDialog(
        WorkspaceSnapshotCapture("scroll_4", False, "chart_001", (chart,)),
        summaries,
    )
    assert "background-color: #111827" in dialog.styleSheet()
    assert "background-color: #9CA3AF" in dialog.styleSheet()
    assert app.styleSheet() == before
    assert dialog.create_radio.isChecked() and not dialog.update_radio.isChecked()
    assert not dialog.existing_combo.isEnabled()
    dialog.name_edit.setText("Create Draft")
    dialog.description_edit.setPlainText("Draft description")
    assert dialog.save_button.isEnabled()

    dialog.update_radio.setChecked(True)
    assert not dialog.create_radio.isChecked()
    assert dialog.existing_combo.isEnabled()
    assert dialog.name_edit.isReadOnly()
    assert dialog.name_edit.text() == "Workspace One"
    assert dialog.description_edit.toPlainText() == "First description"
    dialog.existing_combo.setCurrentIndex(1)
    assert dialog.name_edit.text() == "Workspace Two"
    assert dialog.description_edit.toPlainText() == "Second description"
    emitted = []
    dialog.save_requested.connect(emitted.append)
    dialog.description_edit.setPlainText("Updated")
    dialog._emit_save()
    assert emitted[0].snapshot_id == "snapshot_two"
    assert emitted[0].display_name == "Workspace Two"
    assert emitted[0].description == "Updated"

    second = WorkspaceSnapshotSaveDialog(
        WorkspaceSnapshotCapture("scroll_4", False, "chart_001", (chart,)),
        summaries,
    )
    second.name_edit.setText("Create Draft")
    second.description_edit.setPlainText("Draft description")
    second.update_radio.setChecked(True)
    second.create_radio.setChecked(True)
    assert second.name_edit.text() == "Create Draft"
    assert second.description_edit.toPlainText() == "Draft description"
    assert second.save_button.isEnabled()
