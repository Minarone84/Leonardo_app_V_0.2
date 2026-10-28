"""Analysis interaction and presentation over an injected presenter."""
from __future__ import annotations

from functools import partial
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMenuBar,
    QProgressBar, QPushButton, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.analysis.database_presentation import (
    DATABASE_COLUMNS, DatabaseDisplayEntry, database_table, display_catalog,
    populate_database_row, size_database_table,
)
from leonardo.gui.analysis.database_selector import AnalysisDatabaseSelectorDialog
from leonardo.gui.analysis.variation_binning_tab import VariationBinningTab
from leonardo.gui.analysis.trend_start_patterns_tab import TrendStartPatternsTab
from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table

ANALYSIS_SUITE_WINDOW_ID = "analysis_suite.window"

class AnalysisSuiteWindow(QWidget):
    """Own local display selection only, never databases or calculations."""
    closing = Signal()
    refresh_requested = Signal()
    cancel_requested = Signal()
    def __init__(self, *, action_observer: GuiActionObserver | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if action_observer is not None and not callable(getattr(action_observer, "record_action", None)):
            raise TypeError("action_observer must expose callable record_action")
        self._action_observer = action_observer
        self._catalog: tuple[DatabaseDisplayEntry, ...] = ()
        self._selected: dict[str, DatabaseDisplayEntry] = {}
        self._source_label = "No database catalogue connected."
        self._source_details = ()
        self._selector: AnalysisDatabaseSelectorDialog | None = None
        self._populating = False
        self._connected = False
        self._busy = False
        self._buttons: dict[str, QPushButton] = {}
        self.setWindowTitle("Analysis Suite")
        self.setObjectName("analysis_suite_window")
        self.setProperty("object_id", ANALYSIS_SUITE_WINDOW_ID)
        self.resize(1280, 820)
        apply_theme_stylesheet(self, load_default_theme())
        self._build_shell()
        self._sync_selection()

    def button_for_id(self, button_id: str) -> QPushButton:
        return self._buttons[button_id]

    def table_for_id(self, table_id: str) -> QTableWidget:
        tables = {"analysis_suite.table.selected_databases": self.selected_table, "analysis_suite.table.inspector": self.inspector}
        return tables[table_id]

    def status_text(self) -> str:
        return self.status_label.text()

    def status_log_text(self) -> str:
        return self.log.toPlainText()

    def report_text(self) -> str:
        return ""

    def set_database_catalog(self, entries, *, source_label: str = "Database display catalogue supplied.") -> None:
        """Accept injected metadata; perform no scan, frame load or persistence."""
        self._catalog = display_catalog(entries)
        self._source_label = source_label
        self.catalog_label.setText(source_label)
        if self._selector is not None:
            self._selector.update_catalog(self._catalog, source_label=source_label)

    def reconcile_database_catalog(self, entries, *, invalidated_ids=(), source_label):
        """Replace display entries and invalidate only explicitly changed sources."""
        use_ids = set(self.enabled_database_ids())
        self.set_database_catalog(entries, source_label=source_label)
        available = {entry.database_id: entry for entry in self._catalog}
        for identity in set(invalidated_ids) | (set(self._selected) - set(available)):
            self.variation_tab.clear_source_columns(identity)
        self._selected = {identity: available[identity] for identity in self._selected if identity in available}
        self._render_selection(use_ids)

    def set_execution_state(self, *, connected, busy, source_ready=False, message=""):
        self._connected, self._busy = connected, busy
        self.selected_table.setEnabled(not busy)
        self.variation_tab.set_execution_state(connected=connected, busy=busy, source_ready=source_ready, message=message)
        self.pattern_tab.set_execution_state(connected=connected, busy=busy)
        self.cancel_button.setEnabled(connected and busy)
        self.cancel_button.setToolTip("Request cancellation; the current calculation may need to finish." if busy else "No operation is running.")
        if self._selector is not None:
            self._selector.set_execution_state(connected=connected, busy=busy, source_label=self._source_label)

    def set_operation(self, name, state, message, *, current=None, total=None):
        self.cancel_button.setText("Cancel " + name if state in ("Running", "Cancelling") else "Cancel")
        for key, value in (("name", name), ("state", state), ("status", message)):
            self.operation_labels[key].setText(value)
        self.status_label.setText(message)
        self.progress.setEnabled(state in ("Running", "Cancelling"))
        if state in ("Running", "Cancelling") and not total:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, max(1, total or 1))
            self.progress.setValue(current or 0)

    def show_source_details(self, fields):
        """Retain only the presenter's display projection across Inspector redraws."""
        self._source_details = tuple(fields)
        self._inspect_selected()

    def refresh_display_time(self):
        use_ids = set(self.enabled_database_ids())
        self._render_selection(use_ids)
        self.variation_tab.results.refresh_display_time()
        self.pattern_tab.refresh_display_time()
        if self._selector is not None:
            self._selector.update_catalog(self._catalog, source_label=self._source_label)

    def selected_databases(self) -> tuple[DatabaseDisplayEntry, ...]:
        return tuple(self._selected.values())

    def set_database_columns(self, database_id: str, entries, *, source_label: str = "Injected column display metadata.") -> None:
        """Supply GUI column metadata only; never inspect or load a database."""
        if database_id not in {entry.database_id for entry in self._catalog}:
            raise ValueError("column metadata requires a database ID in the display catalogue")
        self.variation_tab.set_database_columns(database_id, entries, source_label=source_label)

    def enabled_database_ids(self) -> tuple[str, ...]:
        return tuple(self.selected_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                     for row in range(self.selected_table.rowCount())
                     if self.selected_table.item(row, 0).checkState() == Qt.CheckState.Checked)

    def open_database_selector(self) -> None:
        if not self._record_action("analysis_suite.action.select_databases"):
            return
        if self._selector is None:
            self._selector = AnalysisDatabaseSelectorDialog(action_observer=self._action_observer, parent=self)
            self._selector.accepted.connect(self._accept_databases)
            self._selector.refresh_requested.connect(self.refresh_requested)
        if self._selector.isVisible():
            self._selector.raise_()
            self._selector.activateWindow()
            return
        self._selector.prepare(self._catalog, self._selected, source_label=self._source_label)
        self._selector.set_execution_state(connected=self._connected, busy=self._busy, source_label=self._source_label)
        self._selector.open()

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        menu = QMenuBar(self)
        apply_identity(menu, "analysis_suite.menu_bar", object_type="menu_bar")
        databases = menu.addMenu("Databases")
        action = databases.addAction("Select Databases…")
        apply_identity(action, "analysis_suite.menu.select_databases", object_type="action", action_id="analysis_suite.action.select_databases")
        action.triggered.connect(self.open_database_selector)
        root.setMenuBar(menu)
        toolbar = QHBoxLayout()
        select = QPushButton("Select Databases…", self)
        apply_identity(select, "analysis_suite.button.select_databases", object_type="button", action_id="analysis_suite.action.select_databases")
        select.clicked.connect(self.open_database_selector)
        self._buttons["analysis_suite.button.select_databases"] = select
        toolbar.addWidget(select)
        self.catalog_label = QLabel(self._source_label, self)
        self.catalog_label.setWordWrap(True)
        apply_identity(self.catalog_label, "analysis_suite.label.catalog_source", object_type="label")
        toolbar.addWidget(self.catalog_label, 1)
        root.addLayout(toolbar)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(self.workspace_splitter, "analysis_suite.splitter.workspace", object_type="splitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        left = QSplitter(Qt.Orientation.Vertical, self.workspace_splitter)
        apply_identity(left, "analysis_suite.splitter.inputs", object_type="splitter")
        left.setChildrenCollapsible(False)
        left.addWidget(self._build_selected_panel())
        left.addWidget(self._reserved_panel("Variation Analyzer / Dynamic Binning", "Configure columns and parameters in the Variation & Binning tab of Analysis Workspace.", "variation"))
        left.setSizes([400, 320])
        self.workspace_splitter.addWidget(left)
        self.workspace_splitter.addWidget(self._build_analysis_workspace())
        right = QSplitter(Qt.Orientation.Vertical, self.workspace_splitter)
        apply_identity(right, "analysis_suite.splitter.details", object_type="splitter")
        right.setChildrenCollapsible(False)
        right.addWidget(self._build_operation())
        right.addWidget(self._build_details())
        right.setSizes([290, 430])
        self.workspace_splitter.addWidget(right)
        for index, stretch in enumerate((3, 4, 2)):
            self.workspace_splitter.setStretchFactor(index, stretch)
        self.workspace_splitter.setSizes([440, 480, 320])
        root.addWidget(self.workspace_splitter, 1)
        self.status_label = QLabel("Analysis services are not connected", self)
        apply_identity(self.status_label, "analysis_suite.label.status", object_type="status_label")
        root.addWidget(self.status_label)

    def _build_selected_panel(self) -> QGroupBox:
        panel = QGroupBox("Selected Databases", self)
        apply_identity(panel, "analysis_suite.panel.selected_databases", object_type="group_box")
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        self.selection_count = QLabel("0 selected · 0 checked for use", panel)
        apply_identity(self.selection_count, "analysis_suite.label.selection_count", object_type="label")
        layout.addWidget(self.selection_count)
        self.selected_table = database_table(panel, "analysis_suite.table.selected_databases", removable=True)
        self.selected_table.itemChanged.connect(self._selection_changed)
        self.selected_table.itemSelectionChanged.connect(self._inspect_selected)
        layout.addWidget(self.selected_table, 1)
        self.empty_label = QLabel("No databases selected. Use Select Databases to add one or more.", panel)
        self.empty_label.setWordWrap(True)
        apply_identity(self.empty_label, "analysis_suite.label.selection_empty", object_type="label")
        layout.addWidget(self.empty_label)
        return panel

    def _reserved_panel(self, title: str, text: str, key: str) -> QGroupBox:
        panel = QGroupBox(title, self)
        apply_identity(panel, f"analysis_suite.panel.{key}", object_type="group_box")
        panel.setMinimumWidth(180)
        layout = QVBoxLayout(panel)
        label = QLabel(text, panel)
        label.setWordWrap(True)
        apply_identity(label, f"analysis_suite.label.{key}_empty", object_type="label")
        layout.addWidget(label)
        layout.addStretch(1)
        return panel

    def _build_analysis_workspace(self) -> QGroupBox:
        panel = QGroupBox("Analysis Workspace", self)
        apply_identity(panel, "analysis_suite.panel.analysis", object_type="group_box")
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 26, 10, 10)
        self.analysis_tabs = QTabWidget(panel)
        apply_identity(self.analysis_tabs, "analysis_suite.tabs.workspace", object_type="tab_widget")
        self.variation_tab = VariationBinningTab(self.analysis_tabs)
        self.analysis_tabs.addTab(self.variation_tab, "Variation && Binning")
        self.pattern_tab = TrendStartPatternsTab(self.analysis_tabs)
        self.analysis_tabs.addTab(self.pattern_tab, "Trend Start Patterns")
        layout.addWidget(self.analysis_tabs)
        return panel

    def _build_operation(self) -> QGroupBox:
        panel = QGroupBox("Operation", self)
        apply_identity(panel, "analysis_suite.operation.surface", object_type="group_box")
        panel.setMinimumWidth(240)
        layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.operation_labels = {}
        for label, value, key in (("Operation", "None", "name"), ("State", "Idle", "state"), ("Status", "No operation running", "status")):
            widget = QLabel(value, panel)
            widget.setWordWrap(True)
            apply_identity(widget, f"analysis_suite.operation.{key}", object_type="label")
            form.addRow(label, widget)
            self.operation_labels[key] = widget
        layout.addLayout(form)
        progress = QProgressBar(panel)
        apply_identity(progress, "analysis_suite.operation.progress", object_type="progress_bar")
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setEnabled(False)
        self.progress = progress
        layout.addWidget(progress)
        cancel = QPushButton("Cancel", panel)
        apply_identity(cancel, "analysis_suite.operation.cancel", object_type="button", action_id="analysis_suite.action.cancel_binning")
        cancel.setEnabled(False)
        cancel.setToolTip("No operation is running.")
        self.cancel_button = cancel
        cancel.clicked.connect(self.cancel_requested)
        layout.addWidget(cancel)
        layout.addStretch(1)
        return panel

    def _build_details(self) -> QGroupBox:
        panel = QGroupBox("Inspector / Log", self)
        apply_identity(panel, "analysis_suite.panel.details", object_type="group_box")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 26, 10, 10)
        tabs = QTabWidget(panel)
        apply_identity(tabs, "analysis_suite.tabs.details", object_type="tab_widget")
        self.inspector = configure_table(QTableWidget(tabs), object_id="analysis_suite.table.inspector", columns=("Field", "Value"))
        self.inspector.setMinimumWidth(0)
        self.inspector.setWordWrap(False)
        tabs.addTab(self.inspector, "Inspector")
        self.log = QTextEdit(tabs)
        apply_identity(self.log, "analysis_suite.text.status_log", object_type="text_area")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Database selection messages will appear here.")
        tabs.addTab(self.log, "Log")
        layout.addWidget(tabs)
        return panel

    def _accept_databases(self) -> None:
        entries = self._selector.selected_entries()
        use_ids = set(self.enabled_database_ids())
        added = 0
        for entry in entries:
            if entry.database_id not in self._selected:
                self._selected[entry.database_id] = entry
                use_ids.add(entry.database_id)
                added += 1
        self._render_selection(use_ids)
        self.log.append(f"Added {added} database(s) to the workspace. Choose one in Variation & Binning to load its columns.")

    def _render_selection(self, use_ids: set[str]) -> None:
        self._populating = True
        current = self.selected_table.currentItem()
        current_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self.selected_table.setSortingEnabled(False)
        self.selected_table.setRowCount(0)
        self.selected_table.setRowCount(len(self._selected))
        for row, entry in enumerate(self._selected.values()):
            populate_database_row(self.selected_table, row, entry, checked=entry.database_id in use_ids)
            remove = QPushButton("Remove", self.selected_table)
            apply_identity(remove, f"analysis_suite.remove.{entry.database_id}", object_type="button", action_id="analysis_suite.action.remove_database", tooltip="Remove from this workspace only.")
            remove.clicked.connect(partial(self.remove_database, entry.database_id))
            self.selected_table.setCellWidget(row, 10, remove)
        size_database_table(self.selected_table)
        self.selected_table.setColumnWidth(10, 90)
        self.selected_table.setSortingEnabled(True)
        self._populating = False
        if current_id in self._selected:
            for row in range(self.selected_table.rowCount()):
                if self.selected_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == current_id:
                    self.selected_table.selectRow(row)
                    break
        self._inspect_selected()
        self._sync_selection()

    def remove_database(self, database_id: str) -> None:
        if self._busy or database_id not in self._selected or not self._record_action("analysis_suite.action.remove_database"):
            return
        use_ids = set(self.enabled_database_ids())
        entry = self._selected.pop(database_id)
        self._render_selection(use_ids)
        self.log.append(f"Removed {entry.name} from the workspace. The database is unchanged.")

    def _selection_changed(self, item) -> None:
        if not self._populating and item.column() == 0:
            self._sync_selection()
            self._inspect_selected()

    def _sync_selection(self) -> None:
        self.selection_count.setText(f"{len(self._selected)} selected · {len(self.enabled_database_ids())} checked for use")
        self.empty_label.setVisible(not self._selected)
        use_ids = set(self.enabled_database_ids())
        self.variation_tab.set_databases(entry for entry in self._selected.values() if entry.database_id in use_ids)

    def _inspect_selected(self) -> None:
        if self._populating:
            return
        fields = []
        row = self.selected_table.currentRow()
        if row >= 0:
            database_id = self.selected_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            entry = self._selected.get(database_id)
            if entry is not None:
                fields.extend((("Database ID", database_id), *zip(DATABASE_COLUMNS, entry.display_values()), ("Use", "Checked" if database_id in self.enabled_database_ids() else "Unchecked")))
        fields.extend(self._source_details)
        self.inspector.setRowCount(len(fields))
        for index, (key, value) in enumerate(fields):
            self.inspector.setItem(index, 0, QTableWidgetItem(key))
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            self.inspector.setItem(index, 1, item)
        resize_data_manager_table(self.inspector)

    def _record_action(self, action_id: str) -> bool:
        return self._action_observer is None or self._action_observer.record_action(action_id, window_id=ANALYSIS_SUITE_WINDOW_ID).allowed

    def closeEvent(self, event) -> None:
        if self._selector is not None:
            self._selector.reject()
        self.closing.emit()
        super().closeEvent(event)
