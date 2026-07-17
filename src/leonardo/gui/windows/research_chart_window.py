"""Floating shell for an existing Research chart slot widget."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from leonardo.gui.widgets.research_chart_slot_widget import ResearchChartSlotWidget


class ResearchChartWindow(QWidget):
    dock_requested = Signal(int)
    close_requested = Signal(int, str)
    activated = Signal(int)

    def __init__(
        self,
        slot_id: int,
        session_id: str,
        market_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ValueError("slot_id must be an integer from 1 through 8")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(market_text, str):
            raise TypeError("market_text must be a string")
        self._slot_id = slot_id
        self._session_id = session_id
        self._slot_widget: ResearchChartSlotWidget | None = None
        self._programmatic_close = False
        prefix = f"research.chart_window.{slot_id}.{session_id}"
        self.setObjectName(prefix)
        self.setProperty("object_id", f"research_chart.{slot_id}.{session_id}")
        self.setWindowTitle(
            f"Chart {slot_id} \u2014 {market_text}" if market_text else f"Chart {slot_id}"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(900, 600)
        self._host = QWidget(self)
        self._host.setObjectName(f"{prefix}.host")
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        dock = QPushButton("Dock", self)
        dock.setObjectName(f"{prefix}.button.dock")
        dock.clicked.connect(lambda: self.dock_requested.emit(self._slot_id))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(dock)
        layout.addWidget(self._host, stretch=1)

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def window_registry_id(self) -> str:
        return f"research_chart.{self._slot_id}.{self._session_id}"

    def set_slot_widget(self, widget: ResearchChartSlotWidget) -> None:
        if not isinstance(widget, ResearchChartSlotWidget):
            raise TypeError("widget must be a ResearchChartSlotWidget")
        if widget.slot_id != self._slot_id:
            raise ValueError("widget slot_id must match the floating window")
        if self._slot_widget is not None and self._slot_widget is not widget:
            raise RuntimeError("floating window already contains a chart slot")
        self._slot_widget = widget
        widget.setParent(self._host)
        self._host_layout.addWidget(widget)
        widget.activated.connect(self._activate_from_slot)

    def take_slot_widget(self) -> ResearchChartSlotWidget:
        if self._slot_widget is None:
            raise RuntimeError("floating window does not contain a chart slot")
        widget = self._slot_widget
        self._slot_widget = None
        try:
            widget.activated.disconnect(self._activate_from_slot)
        except RuntimeError:
            pass
        self._host_layout.removeWidget(widget)
        widget.setParent(None)
        return widget

    def request_programmatic_close(self) -> None:
        self._programmatic_close = True
        try:
            self.close()
        except RuntimeError:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._programmatic_close:
            event.accept()
            return
        self.close_requested.emit(self._slot_id, self._session_id)
        event.ignore()

    def _activate_from_slot(self, _slot_id: int) -> None:
        self.activated.emit(self._slot_id)
        self.raise_()
        self.activateWindow()
