import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget


def test_pane_snapshot_retains_hidden_volume_and_restore_rejects_unknown():
    QApplication.instance() or QApplication([])
    widget = ChartPaneWorkspaceWidget()
    widget.restore_pane_sizes({"price": 620, "volume": 180})
    assert widget.snapshot_pane_sizes() == {"price": 620, "volume": 180}
    with pytest.raises(ValueError, match="unknown pane"):
        widget.restore_pane_sizes({"unknown": 100})
