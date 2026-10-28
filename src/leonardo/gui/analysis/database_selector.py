"""GUI-only multiple database selection, patterned after the DMS selector."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from leonardo.gui.analysis.database_presentation import (
    DatabaseDisplayEntry, database_table, display_catalog, populate_database_row, size_database_table,
)
from leonardo.gui.windows.shell_widgets import apply_identity

DATABASE_SELECTOR_WINDOW_ID = "analysis_suite.database_selector.window"
_FILTERS = (("exchange", "Exchange"), ("market_type", "Market Type"), ("asset", "Asset"), ("timeframe", "Timeframe"))

class AnalysisDatabaseSelectorDialog(QDialog):
    """Stage checkboxes locally; only accepted choices reach the workspace."""
    refresh_requested = Signal()
    def __init__(self, *, action_observer=None, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Dialog)
        self.setWindowTitle("Select Databases")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_identity(self, DATABASE_SELECTOR_WINDOW_ID, object_type="window")
        self.resize(1240, 680)
        self._action_observer = action_observer
        self._catalog: tuple[DatabaseDisplayEntry, ...] = ()
        self._checked: set[str] = set()
        self._populating = False
        self._busy = False
        self._connected = False
        self._filters: dict[str, QComboBox] = {}
        root = QVBoxLayout(self)
        self.source_label = QLabel("No database catalogue connected.", self)
        self.source_label.setWordWrap(True)
        apply_identity(self.source_label, "analysis_suite.database_selector.source", object_type="label")
        root.addWidget(self.source_label)
        filters = QGridLayout()
        for column, (key, label) in enumerate(_FILTERS):
            filters.addWidget(QLabel(label, self), 0, column)
            combo = QComboBox(self)
            combo.addItem("All", "")
            apply_identity(combo, f"analysis_suite.database_selector.filter.{key}", object_type="combo_box")
            combo.currentIndexChanged.connect(self._populate)
            filters.addWidget(combo, 1, column)
            self._filters[key] = combo
        root.addLayout(filters)
        self.table = database_table(self, "analysis_suite.database_selector.table")
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)
        self.count_label = QLabel(self)
        apply_identity(self.count_label, "analysis_suite.database_selector.count", object_type="label")
        root.addWidget(self.count_label)
        self.empty_label = QLabel("No databases available.", self)
        apply_identity(self.empty_label, "analysis_suite.database_selector.empty", object_type="label")
        root.addWidget(self.empty_label)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh Databases", self)
        apply_identity(self.refresh_button, "analysis_suite.database_selector.button.refresh", object_type="button", action_id="analysis_suite.action.refresh_databases")
        self.refresh_button.setEnabled(False)
        self.refresh_button.clicked.connect(self.refresh_requested)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        self.add_button = QPushButton("Add Selected", self)
        self.cancel_button = QPushButton("Cancel", self)
        for button, suffix in ((self.add_button, "add"), (self.cancel_button, "cancel")):
            apply_identity(button, f"analysis_suite.database_selector.button.{suffix}", object_type="button", action_id=f"analysis_suite.database_selector.action.{suffix}")
            actions.addWidget(button)
        self.add_button.clicked.connect(self._accept_selection)
        self.cancel_button.clicked.connect(self.reject)
        root.addLayout(actions)
        self._populate()

    def set_execution_state(self, *, connected, busy, source_label):
        self._connected, self._busy = connected, busy
        self.source_label.setText(source_label)
        self.refresh_button.setEnabled(connected and not busy)
        self.table.setEnabled(not busy)
        for combo in self._filters.values():
            combo.setEnabled(not busy)
        self._sync_count(self.table.rowCount())

    def update_catalog(self, entries, *, source_label):
        selected = tuple(self._checked)
        filters = {key: combo.currentData() for key, combo in self._filters.items()}
        self.prepare(entries, selected, source_label=source_label)
        for key, value in filters.items():
            self._filters[key].setCurrentIndex(max(0, self._filters[key].findData(value)))

    def prepare(self, entries, selected_ids=(), *, source_label: str = "No database catalogue connected.") -> None:
        self._catalog = display_catalog(entries)
        available = {entry.database_id for entry in self._catalog}
        self._checked = set(selected_ids) & available
        self.source_label.setText(source_label)
        for key, _ in _FILTERS:
            combo = self._filters[key]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All", "")
            for value in sorted({getattr(entry, key) for entry in self._catalog}, key=str.casefold):
                combo.addItem(value, value)
            combo.blockSignals(False)
        self._populate()

    def filter_for_key(self, key: str) -> QComboBox:
        return self._filters[key]

    def selected_entries(self) -> tuple[DatabaseDisplayEntry, ...]:
        return tuple(entry for entry in self._catalog if entry.database_id in self._checked)

    def _populate(self) -> None:
        visible = tuple(entry for entry in self._catalog if all(
            not combo.currentData() or getattr(entry, key) == combo.currentData()
            for key, combo in self._filters.items()
        ))
        self._populating = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            populate_database_row(self.table, row, entry, checked=entry.database_id in self._checked)
        size_database_table(self.table)
        self.table.setSortingEnabled(True)
        self._populating = False
        self.empty_label.setText("No databases match these filters." if self._catalog else "No databases available.")
        self.empty_label.setVisible(not visible)
        self._sync_count(len(visible))

    def _on_item_changed(self, item) -> None:
        if self._populating or item.column() != 0:
            return
        database_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._checked.add(database_id)
        else:
            self._checked.discard(database_id)
        self._sync_count(self.table.rowCount())

    def _sync_count(self, visible: int) -> None:
        self.count_label.setText(f"{visible} of {len(self._catalog)} databases shown · {len(self._checked)} checked across all filters")
        self.add_button.setEnabled(bool(self._checked) and not self._busy)

    def _accept_selection(self) -> None:
        if not self._checked or self._busy:
            return
        if self._action_observer is not None:
            decision = self._action_observer.record_action("analysis_suite.database_selector.action.add", window_id=DATABASE_SELECTOR_WINDOW_ID)
            if not decision.allowed:
                return
        self.accept()
