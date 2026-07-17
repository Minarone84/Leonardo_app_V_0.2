from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.gui.widgets.research_chart_slot_widget import ResearchChartSlotWidget
from leonardo.research import HorizontalViewport, build_resident_volume_projection
from leonardo.gui.chart import CandlestickInteractionState
from tests.research_test.test_chart_session_state import _dataset, _resident


def test_slot_widget_ids_activation_state_and_clear() -> None:
    app = QApplication.instance() or QApplication([])
    widget = ResearchChartSlotWidget(3)
    activated: list[int] = []
    widget.activated.connect(activated.append)
    try:
        assert widget.objectName() == "research.chart_slot.3"
        for suffix in (
            "header", "label.position", "label.dataset", "label.status", "chart"
        ):
            assert widget.findChild(object, f"research.chart_slot.3.{suffix}") is not None
        workspaces = widget.findChildren(ChartPaneWorkspaceWidget)
        assert workspaces == [widget.chart_workspace]
        assert widget.chart_widget is widget.chart_workspace.price_chart
        widget.set_active(True)
        assert widget.property("active") is True
        market = MarketId("bybit", "linear", "BTCUSDT", "1m")
        widget.set_dataset(market)
        widget.set_status("Chart ready")
        widget.set_busy(True)
        assert widget.dataset_text == market.as_key()
        assert widget.status_text == "Chart ready"
        QTest.mouseClick(widget, Qt.LeftButton)
        assert activated == [3]

        QTest.mouseClick(widget._header, Qt.LeftButton)
        assert activated == [3, 3]
        QTest.mouseClick(widget._position, Qt.LeftButton)
        assert activated == [3, 3, 3]
        QTest.mouseClick(widget._dataset, Qt.RightButton)
        QCoreApplication.sendEvent(widget._status, QEvent(QEvent.Type.Enter))
        assert activated == [3, 3, 3]

        dataset = _dataset(row_count=20)
        resident = _resident(dataset)
        interaction = CandlestickInteractionState(
            HorizontalViewport(dataset.row_count), resident
        )
        widget.show_interaction_state(
            interaction, build_resident_volume_projection(dataset, resident)
        )
        widget.chart_workspace.set_volume_visible(True)
        widget.resize(900, 600)
        widget.show()
        app.processEvents()

        candle = widget.chart_widget
        QTest.mousePress(candle, Qt.LeftButton, pos=candle._plot_rect().center().toPoint())
        assert activated == [3, 3, 3, 3]
        assert candle._plot_dragging is True
        QTest.mouseRelease(candle, Qt.LeftButton)

        volume = widget.chart_workspace.volume_chart
        QTest.mousePress(volume, Qt.LeftButton, pos=volume._plot_rect().center().toPoint())
        assert activated == [3, 3, 3, 3, 3]
        assert volume._dragging is True
        QTest.mouseRelease(volume, Qt.LeftButton)
        widget.clear_chart_state()
        assert widget.dataset_text == "No dataset"
        assert widget.status_text == "Empty"
        assert widget.chart_workspace.volume_visible is False
    finally:
        widget.close()
        app.processEvents()


def test_slot_widget_has_no_service_or_filesystem_ownership() -> None:
    path = Path("src/leonardo/gui/widgets/research_chart_slot_widget.py")
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    for forbidden in (
        "ResearchDatasetApplicationService",
        "ResearchStudyApplicationService",
        "ArtifactService",
        "calculate_financial_tool",
        "pathlib",
        "open(",
    ):
        assert forbidden not in source
