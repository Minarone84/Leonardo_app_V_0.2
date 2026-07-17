import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.windows.workspace_snapshot_save_dialog import WorkspaceSnapshotSaveDialog
from leonardo.research.workspace_snapshot import (
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
