"""Signal-only Study Manager table for one Research chart session."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.research import StudyManagerEntry


class StudyManagerWidget(QWidget):
    """Display immutable manager entries and emit typed user intentions."""

    visibility_requested = Signal(str, bool)
    style_requested = Signal(str)
    reset_style_requested = Signal(str)
    save_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("research.study_manager")
        self._entries: tuple[StudyManagerEntry, ...] = ()
        self._updating = False
        self._table = QTableWidget(0, 6, self)
        self._table.setObjectName("research.study_manager.table")
        self._table.setHorizontalHeaderLabels(
            ("Visible", "Study", "Tool", "Source", "Saved", "Pane")
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._empty = QLabel("No Studies", self)
        self._empty.setAlignment(Qt.AlignCenter)

        self._style = self._button("research.study_manager.button.style", "Style")
        self._reset = self._button(
            "research.study_manager.button.reset_style", "Reset Style"
        )
        self._save = self._button("research.study_manager.button.save", "Save")
        self._remove = self._button("research.study_manager.button.remove", "Remove")
        buttons = QHBoxLayout()
        buttons.addWidget(self._style)
        buttons.addWidget(self._reset)
        buttons.addStretch(1)
        buttons.addWidget(self._save)
        buttons.addWidget(self._remove)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)
        layout.addWidget(self._empty)
        layout.addLayout(buttons)

        self._table.itemSelectionChanged.connect(self._sync_buttons)
        self._table.itemChanged.connect(self._on_item_changed)
        self._style.clicked.connect(
            lambda: self._emit_selected(self.style_requested)
        )
        self._reset.clicked.connect(
            lambda: self._emit_selected(self.reset_style_requested)
        )
        self._save.clicked.connect(lambda: self._emit_selected(self.save_requested))
        self._remove.clicked.connect(
            lambda: self._emit_selected(self.remove_requested)
        )
        self._sync_buttons()

    @property
    def entries(self) -> tuple[StudyManagerEntry, ...]:
        return self._entries

    @property
    def table(self) -> QTableWidget:
        return self._table

    def set_entries(self, entries: Sequence[StudyManagerEntry]) -> None:
        snapshot = tuple(entries)
        if not all(isinstance(item, StudyManagerEntry) for item in snapshot):
            raise TypeError("entries must contain StudyManagerEntry values")
        selected_id = self.selected_study_id()
        self._entries = snapshot
        self._updating = True
        try:
            self._table.setRowCount(len(snapshot))
            for row, entry in enumerate(snapshot):
                visible = QTableWidgetItem()
                visible.setData(Qt.UserRole, entry.study_id)
                visible.setFlags(
                    Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
                )
                visible.setCheckState(Qt.Checked if entry.visible else Qt.Unchecked)
                self._table.setItem(row, 0, visible)
                values = (
                    entry.display_name,
                    entry.tool_title,
                    entry.source_kind,
                    "Yes" if entry.saved else "No",
                    entry.pane_label,
                )
                for column, value in enumerate(values, start=1):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, entry.study_id)
                    self._table.setItem(row, column, item)
                if entry.study_id == selected_id:
                    self._table.selectRow(row)
            self._table.resizeColumnsToContents()
        finally:
            self._updating = False
        self._empty.setVisible(not snapshot)
        self._table.setVisible(bool(snapshot))
        self._sync_buttons()

    def selected_study_id(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self._table.item(rows[0].row(), 0)
        return None if item is None else item.data(Qt.UserRole)

    def select_study(self, study_id: str) -> bool:
        for row, entry in enumerate(self._entries):
            if entry.study_id == study_id:
                self._table.selectRow(row)
                return True
        return False

    def _button(self, object_name: str, text: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName(object_name)
        return button

    def _selected_entry(self) -> StudyManagerEntry | None:
        study_id = self.selected_study_id()
        return next((item for item in self._entries if item.study_id == study_id), None)

    def _sync_buttons(self) -> None:
        entry = self._selected_entry()
        styleable = entry is not None and entry.pane_id is not None
        self._style.setEnabled(styleable)
        self._reset.setEnabled(styleable)
        self._save.setEnabled(entry is not None and not entry.saved)
        self._remove.setEnabled(entry is not None)

    def _emit_selected(self, signal) -> None:
        study_id = self.selected_study_id()
        if study_id is not None:
            signal.emit(study_id)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != 0:
            return
        study_id = item.data(Qt.UserRole)
        if isinstance(study_id, str):
            self.visibility_requested.emit(study_id, item.checkState() == Qt.Checked)
