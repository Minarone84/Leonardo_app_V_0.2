"""Floating GUI shell for one existing restored Research chart panel."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from leonardo.gui.research.chart_panel import ResearchChartPanel


class ResearchDetachedChartWindow(QWidget):
    """Temporarily host the same Research chart panel outside the workspace."""

    dock_requested = Signal(int)

    def __init__(
        self,
        slot_id: int,
        chart_panel: ResearchChartPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ValueError("slot_id must be an integer from 1 through 8")
        if not isinstance(chart_panel, ResearchChartPanel):
            raise TypeError("chart_panel must be a ResearchChartPanel")
        self._slot_id = slot_id
        self._chart_panel: ResearchChartPanel | None = chart_panel
        self._programmatic_close = False
        self.setObjectName(f"research_restoration.detached_chart.{slot_id}")
        self.setWindowTitle(chart_panel.dataset_label.text())
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        chart_panel.setParent(self)
        layout.addWidget(chart_panel)

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def window_registry_id(self) -> str:
        return f"research_restoration.detached_chart.{self._slot_id}"

    @property
    def chart_panel(self) -> ResearchChartPanel:
        if self._chart_panel is None:
            raise RuntimeError("detached window does not contain a chart panel")
        return self._chart_panel

    def take_chart_panel(self) -> ResearchChartPanel:
        panel = self.chart_panel
        self._chart_panel = None
        self.layout().removeWidget(panel)
        panel.setParent(None)
        return panel

    def request_programmatic_close(self) -> None:
        self._programmatic_close = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._programmatic_close:
            event.accept()
            return
        event.ignore()
        self.dock_requested.emit(self._slot_id)
