from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QTableWidget

from leonardo.data import MarketId
from leonardo.data_manager import DataManagerPreview
from leonardo.gui.windows.data_manager_preview_dialog import DataManagerPreviewDialog


def test_preview_dialog_renders_dynamic_read_only_cells_and_no_path() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    preview = DataManagerPreview(
        "OHLCV", market, "dataset", None, ("ts_ms", "close"),
        (("1", "2.5"),), 6, True, {"market_id": market.as_key()},
    )
    dialog = DataManagerPreviewDialog(preview)
    try:
        table = dialog.findChild(QTableWidget, "data_manager_preview.table.values")
        assert table.columnCount() == 2
        assert table.item(0, 1).text() == "2.5"
        assert table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
        assert "path" not in " ".join(
            child.text() for child in dialog.findChildren(type(dialog.findChild(QTableWidget)))
            if hasattr(child, "text")
        ).lower()
    finally:
        dialog.close()
