"""Chart-local callable Studies Manager for the restored Research GUI."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from leonardo.data import MarketId
from leonardo.gui.widgets.study_manager_widget import StudyManagerWidget
from leonardo.research import StudyManagerEntry


class ResearchStudiesManagerDialog(QDialog):
    """Wrap the canonical Study Manager for one chart context."""

    visibility_requested = Signal(str, bool)
    style_requested = Signal(str)
    reset_style_requested = Signal(str)
    save_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        market_id: MarketId,
        entries: Sequence[StudyManagerEntry],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        snapshot = tuple(entries)
        if not all(isinstance(item, StudyManagerEntry) for item in snapshot):
            raise TypeError("entries must contain StudyManagerEntry values")

        self.setObjectName("research_restoration.studies_manager")
        self.setWindowTitle(f"Studies — {market_id.symbol} · {market_id.timeframe}")
        self.setModal(False)
        self.resize(860, 440)
        self.setMinimumSize(720, 360)

        layout = QVBoxLayout(self)
        context = QLabel(_context_text(market_id), self)
        context.setObjectName("research_restoration.studies_manager.context")
        layout.addWidget(context)

        self._manager_widget = StudyManagerWidget(self)
        self._manager_widget.set_entries(snapshot)
        layout.addWidget(self._manager_widget, 1)

        close_button = QPushButton("Close", self)
        close_button.setObjectName("research_restoration.studies_manager.close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self._manager_widget.visibility_requested.connect(
            self.visibility_requested.emit
        )
        self._manager_widget.style_requested.connect(self.style_requested.emit)
        self._manager_widget.reset_style_requested.connect(
            self.reset_style_requested.emit
        )
        self._manager_widget.save_requested.connect(self.save_requested.emit)
        self._manager_widget.remove_requested.connect(self.remove_requested.emit)

    @property
    def manager_widget(self) -> StudyManagerWidget:
        return self._manager_widget

    @property
    def entries(self) -> tuple[StudyManagerEntry, ...]:
        return self._manager_widget.entries

    def set_entries(self, entries: Sequence[StudyManagerEntry]) -> None:
        self._manager_widget.set_entries(entries)

    def set_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._manager_widget.setEnabled(not busy)

    def prepare_for_open(
        self, entries: Sequence[StudyManagerEntry]
    ) -> None:
        self.set_entries(entries)


def _context_text(market_id: MarketId) -> str:
    exchange = market_id.exchange[:1].upper() + market_id.exchange[1:]
    return (
        "Historical Chart: "
        f"{exchange}_{market_id.market_type}_{market_id.symbol}_{market_id.timeframe}"
    )
