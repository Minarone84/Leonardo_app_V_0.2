"""Service-free Research Notebook manager dialog."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from leonardo.research.notebook import ResearchNotebookSummary


class ResearchNotebookManagerDialog(QDialog):
    """Display notebook summaries and emit immutable selection intent."""

    refresh_requested = Signal()
    open_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(
        self,
        summaries: tuple[ResearchNotebookSummary, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("research.notebook_manager_dialog")
        self.setWindowTitle("Research Notebooks")
        self.resize(760, 500)
        self._summaries: tuple[ResearchNotebookSummary, ...] = ()
        self._list = QListWidget(self)
        self._list.setObjectName(
            "research.notebook_manager_dialog.list.notebooks"
        )
        self._name = QLineEdit(self)
        self._name.setObjectName("research.notebook_manager_dialog.edit.name")
        self._name.setReadOnly(True)
        self._description = QLineEdit(self)
        self._description.setObjectName(
            "research.notebook_manager_dialog.edit.description"
        )
        self._description.setReadOnly(True)
        self._pages = QTableWidget(0, 1, self)
        self._pages.setObjectName(
            "research.notebook_manager_dialog.table.pages"
        )
        self._pages.setHorizontalHeaderLabels(("MarketId",))
        self._validation = QLabel("", self)
        self._validation.setObjectName(
            "research.notebook_manager_dialog.label.validation"
        )
        self._refresh = QPushButton("Refresh", self)
        self._refresh.setObjectName(
            "research.notebook_manager_dialog.button.refresh"
        )
        self._open = QPushButton("Open", self)
        self._open.setObjectName(
            "research.notebook_manager_dialog.button.open"
        )
        self._delete = QPushButton("Delete", self)
        self._delete.setObjectName(
            "research.notebook_manager_dialog.button.delete"
        )
        self._close = QPushButton("Close", self)
        self._close.setObjectName(
            "research.notebook_manager_dialog.button.close"
        )
        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        actions = QHBoxLayout()
        actions.addWidget(self._validation, stretch=1)
        actions.addWidget(self._refresh)
        actions.addWidget(self._open)
        actions.addWidget(self._delete)
        actions.addWidget(self._close)
        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(form)
        layout.addWidget(self._pages)
        layout.addLayout(actions)
        self._list.currentRowChanged.connect(self._selection_changed)
        self._refresh.clicked.connect(self.refresh_requested.emit)
        self._open.clicked.connect(self._emit_open)
        self._delete.clicked.connect(self._confirm_delete)
        self._close.clicked.connect(self.close)
        self.set_summaries(summaries)

    @property
    def summaries(self) -> tuple[ResearchNotebookSummary, ...]:
        return self._summaries

    def set_summaries(
        self, summaries: tuple[ResearchNotebookSummary, ...]
    ) -> None:
        values = tuple(summaries)
        if not all(isinstance(item, ResearchNotebookSummary) for item in values):
            raise TypeError("summaries must contain ResearchNotebookSummary values")
        self._summaries = values
        self._list.clear()
        for summary in values:
            label = summary.display_name or summary.notebook_id
            if not summary.valid:
                label = f"{label} (invalid)"
            item = QListWidgetItem(label)
            item.setData(256, summary.notebook_id)
            self._list.addItem(item)
        if values:
            self._list.setCurrentRow(0)
        else:
            self._selection_changed(-1)

    def _selected(self) -> ResearchNotebookSummary | None:
        row = self._list.currentRow()
        return self._summaries[row] if 0 <= row < len(self._summaries) else None

    def _selection_changed(self, _row: int) -> None:
        summary = self._selected()
        if summary is None:
            self._name.clear()
            self._description.clear()
            self._pages.setRowCount(0)
            self._validation.clear()
            self._open.setEnabled(False)
            self._delete.setEnabled(False)
            return
        self._name.setText(summary.display_name)
        self._description.setText(summary.description)
        self._pages.setRowCount(len(summary.page_market_ids))
        for row, market in enumerate(summary.page_market_ids):
            self._pages.setItem(row, 0, QTableWidgetItem(market.as_key()))
        self._validation.setText(
            summary.rejection_reason
            or (
                f"{summary.page_count} page(s) | {summary.note_count} note(s) | "
                f"{summary.potential_trade_count} trade(s) | "
                f"{summary.point_of_interest_count} POI(s)"
            )
        )
        self._open.setEnabled(summary.valid)
        self._delete.setEnabled(True)

    def _emit_open(self) -> None:
        summary = self._selected()
        if summary is not None and summary.valid:
            self.open_requested.emit(summary.notebook_id)

    def _confirm_delete(self) -> None:
        summary = self._selected()
        if summary is None:
            return
        if QMessageBox.question(
            self,
            "Delete Research Notebook",
            f"Delete {summary.display_name or summary.notebook_id}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes:
            self.delete_requested.emit(summary.notebook_id)
