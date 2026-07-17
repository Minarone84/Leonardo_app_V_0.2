from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.gui.widgets.research_chart_slot_widget import ResearchChartSlotWidget
from leonardo.gui.windows.research_chart_window import ResearchChartWindow


def test_floating_window_reparents_same_widget_and_has_session_identity() -> None:
    app = QApplication.instance() or QApplication([])
    widget = ResearchChartSlotWidget(2)
    window = ResearchChartWindow(2, "session-abc", "bybit:linear:BTCUSDT:1m")
    docks: list[int] = []
    closes: list[tuple[int, str]] = []
    window.dock_requested.connect(docks.append)
    window.close_requested.connect(lambda *args: closes.append(args))
    try:
        window.set_slot_widget(widget)
        assert window.objectName() == "research.chart_window.2.session-abc"
        assert window.findChild(
            object, "research.chart_window.2.session-abc.host"
        ) is not None
        assert window.window_registry_id == "research_chart.2.session-abc"
        assert window.minimumWidth() == 900 and window.minimumHeight() == 600
        window.findChild(
            object, "research.chart_window.2.session-abc.button.dock"
        ).click()
        assert docks == [2]
        assert window.take_slot_widget() is widget
        window.set_slot_widget(widget)
        window.show()
        app.processEvents()
        assert window.close() is False
        assert closes == [(2, "session-abc")]
        window.request_programmatic_close()
        app.processEvents()
        assert closes == [(2, "session-abc")]
    finally:
        window.request_programmatic_close()
        app.processEvents()


def test_reused_slot_produces_unique_floating_window_id() -> None:
    first = ResearchChartWindow(2, "old-session")
    second = ResearchChartWindow(2, "new-session")
    try:
        assert first.window_registry_id != second.window_registry_id
    finally:
        first.request_programmatic_close()
        second.request_programmatic_close()
