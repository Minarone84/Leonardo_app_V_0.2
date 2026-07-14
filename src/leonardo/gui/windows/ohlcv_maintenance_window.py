"""GUI shell for canonical OHLCV Maintenance validation and explicit repair."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table

OHLCV_MAINTENANCE_WINDOW_ID = "ohlcv_maintenance.window"

_DATASET_COLUMNS = (
    ("exchange", "Exchange"),
    ("market_type", "Market Type"),
    ("symbol", "Symbol"),
    ("timeframe", "Timeframe"),
    ("persistence", "Persistence"),
    ("validation", "Validation"),
    ("rows", "Rows"),
    ("source", "Source"),
    ("issues", "Issues"),
)
_DETAIL_COLUMNS = (("field", "Evidence"), ("value", "Value"))
_ISSUE_COLUMNS = (
    ("severity", "Severity"),
    ("code", "Code"),
    ("message", "Message"),
    ("row", "Row"),
    ("column", "Column"),
    ("timestamp", "Timestamp ms"),
)
_REPAIR_COLUMNS = (
    ("start", "Start ms"),
    ("end", "End ms"),
    ("bars", "Est. bars"),
    ("codes", "Issue codes"),
    ("anchors", "Coverage anchors"),
    ("reason", "Reason"),
)


@dataclass(frozen=True, slots=True)
class MaintenanceDatasetRow:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    persistence: str
    validation: str
    rows: int
    source: str
    issues: str


@dataclass(frozen=True, slots=True)
class MaintenanceIssueRow:
    severity: str
    code: str
    message: str
    row: str = ""
    column: str = ""
    timestamp: str = ""


@dataclass(frozen=True, slots=True)
class MaintenanceRepairRangeRow:
    start: str
    end: str
    bars: str
    codes: str
    anchors: str
    reason: str


class OhlcvMaintenanceWindow(QWidget):
    """Presentation-only Maintenance window.

    The window displays presenter-supplied data and asks for explicit user
    confirmation. It does not scan storage, parse CSVs, validate, download, or
    persist repair results.
    """

    refresh_requested = Signal()
    validate_requested = Signal()
    plan_repair_requested = Signal()
    execute_repair_requested = Signal()
    cancel_requested = Signal()
    selection_changed = Signal(int)
    closed = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._progress = QProgressBar(self)
        self._discovery_notes = QPlainTextEdit(self)
        self._repair_summary = QPlainTextEdit(self)

        self.setObjectName("ohlcv_maintenance_window")
        self.setProperty("object_id", OHLCV_MAINTENANCE_WINDOW_ID)
        self.setWindowTitle("OHLCV Maintenance")
        self.resize(1280, 840)
        self.setMinimumSize(960, 680)
        apply_theme_stylesheet(self, load_default_theme())
        self._build_layout()
        self.reset_view()

    def button_for_id(self, button_id: str) -> QPushButton:
        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown OHLCV Maintenance button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown OHLCV Maintenance table: {table_id}") from error

    def selected_dataset_index(self) -> int | None:
        rows = self._tables["datasets"].selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def select_dataset_index(self, index: int | None) -> None:
        table = self._tables["datasets"]
        table.clearSelection()
        if index is None or index < 0 or index >= table.rowCount():
            self.selection_changed.emit(-1)
            return
        table.selectRow(index)

    def set_dataset_rows(self, rows: tuple[MaintenanceDatasetRow, ...]) -> None:
        table = self._tables["datasets"]
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.exchange,
                row.market_type,
                row.symbol,
                row.timeframe,
                row.persistence,
                row.validation,
                str(row.rows),
                row.source,
                row.issues,
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                )
                table.setItem(row_index, column_index, item)
        table.resizeRowsToContents()
        if rows:
            table.selectRow(0)
        else:
            self.selection_changed.emit(-1)

    def set_evidence_rows(self, rows: tuple[tuple[str, object], ...]) -> None:
        table = self._tables["evidence"]
        table.setRowCount(len(rows))
        for row_index, (field, value) in enumerate(rows):
            table.setItem(row_index, 0, QTableWidgetItem(str(field)))
            table.setItem(row_index, 1, QTableWidgetItem("" if value is None else str(value)))
        table.resizeRowsToContents()

    def set_issue_rows(self, rows: tuple[MaintenanceIssueRow, ...]) -> None:
        table = self._tables["issues"]
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (row.severity, row.code, row.message, row.row, row.column, row.timestamp)
            for column_index, value in enumerate(values):
                table.setItem(row_index, column_index, QTableWidgetItem(value))
        table.resizeRowsToContents()

    def set_repair_rows(self, rows: tuple[MaintenanceRepairRangeRow, ...]) -> None:
        table = self._tables["repair"]
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (row.start, row.end, row.bars, row.codes, row.anchors, row.reason)
            for column_index, value in enumerate(values):
                table.setItem(row_index, column_index, QTableWidgetItem(value))
        table.resizeRowsToContents()

    def set_repair_summary(self, text: str) -> None:
        self._repair_summary.setPlainText(str(text))

    def set_discovery_notes(self, text: str) -> None:
        self._discovery_notes.setPlainText(str(text))

    def set_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(str(text))

    def status_text(self) -> str:
        return self._status_label.text() if self._status_label is not None else ""

    def confirm_repair(self, summary: str) -> bool:
        result = QMessageBox.question(
            self,
            "Confirm OHLCV Repair",
            (
                f"{summary}\n\n"
                "This will redownload the reviewed ranges, mutate candles.csv, record repair "
                "provenance, and run canonical post-repair validation. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def set_running(self, running: bool) -> None:
        self._tables["datasets"].setEnabled(not running)
        self._buttons["refresh"].setEnabled(not running)
        self._buttons["cancel"].setEnabled(running)
        if running:
            self._buttons["validate"].setEnabled(False)
            self._buttons["plan_repair"].setEnabled(False)
            self._buttons["execute_repair"].setEnabled(False)

    def set_validate_enabled(self, enabled: bool) -> None:
        self._buttons["validate"].setEnabled(bool(enabled))

    def set_plan_repair_enabled(self, enabled: bool) -> None:
        self._buttons["plan_repair"].setEnabled(bool(enabled))

    def set_execute_repair_enabled(self, enabled: bool) -> None:
        self._buttons["execute_repair"].setEnabled(bool(enabled))

    def set_progress(self, current: int | None, total: int | None) -> None:
        if current is None or total is None or total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(current, total)))

    def reset_view(self) -> None:
        self.set_status("Ready")
        self.set_dataset_rows(())
        self.set_evidence_rows(())
        self.set_issue_rows(())
        self.set_repair_rows(())
        self.set_repair_summary("")
        self.set_discovery_notes("")
        self.set_progress(0, 1)
        self.set_running(False)
        self.set_validate_enabled(False)
        self.set_plan_repair_enabled(False)
        self.set_execute_repair_enabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(root, "ohlcv_maintenance.layout.root", object_type="layout")
        root.addWidget(self._build_header())

        datasets_panel = QGroupBox("Persisted OHLCV Datasets", self)
        apply_identity(datasets_panel, "ohlcv_maintenance.panel.datasets", object_type="panel")
        datasets_layout = QVBoxLayout(datasets_panel)
        datasets = QTableWidget(self)
        configure_table(datasets, _DATASET_COLUMNS, object_id="ohlcv_maintenance.table.datasets")
        datasets.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        datasets.itemSelectionChanged.connect(self._emit_selection_changed)
        datasets.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        datasets.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        datasets.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._tables["datasets"] = datasets
        datasets_layout.addWidget(datasets)

        notes_label = QLabel("Discovery notes", datasets_panel)
        apply_identity(notes_label, "ohlcv_maintenance.label.discovery_notes", object_type="label")
        datasets_layout.addWidget(notes_label)
        apply_identity(
            self._discovery_notes,
            "ohlcv_maintenance.discovery_notes",
            object_type="text_area",
        )
        self._discovery_notes.setReadOnly(True)
        self._discovery_notes.setMaximumHeight(72)
        self._discovery_notes.setPlaceholderText("No rejected storage entries")
        datasets_layout.addWidget(self._discovery_notes)
        root.addWidget(datasets_panel, 3)

        lower = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(lower, "ohlcv_maintenance.splitter.details", object_type="splitter")
        lower.addWidget(self._build_evidence_panel())
        lower.addWidget(self._build_issues_panel())
        lower.addWidget(self._build_repair_panel())
        lower.setStretchFactor(0, 1)
        lower.setStretchFactor(1, 2)
        lower.setStretchFactor(2, 2)
        root.addWidget(lower, 2)
        root.addWidget(self._build_controls())

    def _build_header(self) -> QWidget:
        panel = QGroupBox("OHLCV Maintenance", self)
        apply_identity(panel, "ohlcv_maintenance.panel.header", object_type="panel")
        layout = QHBoxLayout(panel)
        title = QLabel("Canonical Validation and Explicit Repair", panel)
        apply_identity(title, "ohlcv_maintenance.title", object_type="label")
        status = QLabel("Ready", panel)
        apply_identity(status, "ohlcv_maintenance.label.status", object_type="status_label")
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return panel

    def _build_evidence_panel(self) -> QWidget:
        panel = QGroupBox("Storage Evidence", self)
        apply_identity(panel, "ohlcv_maintenance.panel.evidence", object_type="panel")
        layout = QVBoxLayout(panel)
        table = QTableWidget(self)
        configure_table(table, _DETAIL_COLUMNS, object_id="ohlcv_maintenance.table.evidence")
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tables["evidence"] = table
        layout.addWidget(table)
        return panel

    def _build_issues_panel(self) -> QWidget:
        panel = QGroupBox("Validation Findings", self)
        apply_identity(panel, "ohlcv_maintenance.panel.issues", object_type="panel")
        layout = QVBoxLayout(panel)
        table = QTableWidget(self)
        configure_table(table, _ISSUE_COLUMNS, object_id="ohlcv_maintenance.table.issues")
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tables["issues"] = table
        layout.addWidget(table)
        return panel

    def _build_repair_panel(self) -> QWidget:
        panel = QGroupBox("Reviewed Repair Plan", self)
        apply_identity(panel, "ohlcv_maintenance.panel.repair", object_type="panel")
        layout = QVBoxLayout(panel)
        table = QTableWidget(self)
        configure_table(table, _REPAIR_COLUMNS, object_id="ohlcv_maintenance.table.repair")
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._tables["repair"] = table
        layout.addWidget(table)
        apply_identity(
            self._repair_summary,
            "ohlcv_maintenance.repair_summary",
            object_type="text_area",
        )
        self._repair_summary.setReadOnly(True)
        self._repair_summary.setMaximumHeight(78)
        self._repair_summary.setPlaceholderText("No repair plan prepared")
        layout.addWidget(self._repair_summary)
        return panel

    def _build_controls(self) -> QWidget:
        panel = QGroupBox("Actions", self)
        apply_identity(panel, "ohlcv_maintenance.panel.actions", object_type="action_container")
        layout = QHBoxLayout(panel)
        refresh = self._add_button("refresh", "Refresh", enabled=True)
        validate = self._add_button("validate", "Validate Selected", enabled=False)
        plan_repair = self._add_button("plan_repair", "Plan Repair", enabled=False)
        execute_repair = self._add_button("execute_repair", "Execute Repair", enabled=False)
        cancel = self._add_button("cancel", "Cancel", enabled=False)
        refresh.clicked.connect(self.refresh_requested.emit)
        validate.clicked.connect(self.validate_requested.emit)
        plan_repair.clicked.connect(self.plan_repair_requested.emit)
        execute_repair.clicked.connect(self.execute_repair_requested.emit)
        cancel.clicked.connect(self.cancel_requested.emit)
        apply_identity(
            self._progress,
            "ohlcv_maintenance.progress.operation",
            object_type="progress_bar",
        )
        self._progress.setTextVisible(True)
        for widget in (refresh, validate, plan_repair, execute_repair, cancel):
            layout.addWidget(widget)
        layout.addWidget(self._progress, 1)
        return panel

    def _add_button(self, button_id: str, label: str, *, enabled: bool) -> QPushButton:
        button = QPushButton(label, self)
        apply_identity(
            button,
            f"ohlcv_maintenance.button.{button_id}",
            object_type="button",
            action_id=f"ohlcv_maintenance.{button_id}",
        )
        button.setEnabled(enabled)
        self._buttons[button_id] = button
        return button

    def _emit_selection_changed(self) -> None:
        index = self.selected_dataset_index()
        self.selection_changed.emit(-1 if index is None else index)
