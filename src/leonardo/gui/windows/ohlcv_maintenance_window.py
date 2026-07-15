"""GUI shell for canonical OHLCV validation, repair, evidence recovery, and deletion."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGridLayout,
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
    ("evidence_state", "Evidence State"),
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
    evidence_state: str
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
    reconstruct_sidecar_requested = Signal()
    delete_requested = Signal()
    cancel_requested = Signal()
    selection_changed = Signal(int)
    closed = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._splitters: dict[str, QSplitter] = {}
        self._status_label: QLabel | None = None
        self._progress = QProgressBar(self)
        self._discovery_notes = QPlainTextEdit(self)
        self._repair_summary = QPlainTextEdit(self)
        self._initial_geometry_applied = False

        self.setObjectName("ohlcv_maintenance_window")
        self.setProperty("object_id", OHLCV_MAINTENANCE_WINDOW_ID)
        self.setWindowTitle("OHLCV Maintenance")
        self.resize(1120, 820)
        self.setMinimumSize(760, 640)
        self._apply_window_font_bump()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_layout()
        self._apply_maintenance_widget_fonts()
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

    def splitter_for_id(self, splitter_id: str) -> QSplitter:
        try:
            return self._splitters[splitter_id]
        except KeyError as error:
            raise KeyError(f"Unknown OHLCV Maintenance splitter: {splitter_id}") from error

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
                row.evidence_state,
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
            field_item = QTableWidgetItem(str(field))
            field_item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            )
            value_item = QTableWidgetItem("" if value is None else str(value))
            value_item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            )
            table.setItem(row_index, 0, field_item)
            table.setItem(row_index, 1, value_item)
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
            value = str(text)
            self._status_label.setText(value)
            self._status_label.setToolTip(value)

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

    def confirm_deletion(
        self,
        *,
        market_key: str,
        csv_path: str,
        sidecar_path: str | None,
    ) -> bool:
        sidecar_text = sidecar_path or "No sidecar is present"
        result = QMessageBox.warning(
            self,
            "Confirm OHLCV Dataset Deletion",
            (
                f"Delete the canonical OHLCV dataset {market_key}?\n\n"
                f"CSV: {csv_path}\n"
                f"Sidecar: {sidecar_text}\n\n"
                "This permanently removes the reviewed files, invalidates any cached "
                "Research copy, and cannot be undone. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def confirm_sidecar_reconstruction(
        self,
        *,
        market_key: str,
        evidence_state: str,
        csv_path: str,
        sidecar_path: str,
        replacing_existing: bool,
    ) -> bool:
        replacement_text = (
            "replace the existing sidecar"
            if replacing_existing
            else "create a new sidecar"
        )
        result = QMessageBox.warning(
            self,
            "Confirm OHLCV Sidecar Reconstruction",
            (
                f"Reconstruct sidecar evidence for {market_key}?\n\n"
                f"Evidence state: {evidence_state}\n"
                f"CSV: {csv_path}\n"
                f"Sidecar: {sidecar_path}\n\n"
                f"This will {replacement_text} as committed/unknown with source "
                "maintenance_reconstruction, then run canonical validation. "
                "Candle values will not be changed. Continue?"
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
            self._buttons["reconstruct_sidecar"].setEnabled(False)
            self._buttons["delete"].setEnabled(False)

    def set_validate_enabled(self, enabled: bool) -> None:
        self._buttons["validate"].setEnabled(bool(enabled))

    def set_plan_repair_enabled(self, enabled: bool) -> None:
        self._buttons["plan_repair"].setEnabled(bool(enabled))

    def set_execute_repair_enabled(self, enabled: bool) -> None:
        self._buttons["execute_repair"].setEnabled(bool(enabled))

    def set_delete_enabled(self, enabled: bool) -> None:
        self._buttons["delete"].setEnabled(bool(enabled))

    def set_reconstruct_sidecar_enabled(self, enabled: bool) -> None:
        self._buttons["reconstruct_sidecar"].setEnabled(bool(enabled))

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._buttons["cancel"].setEnabled(bool(enabled))

    def set_progress(self, current: int | None, total: int | None) -> None:
        if current is None or total is None or total <= 0:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Working…")
            return
        bounded = max(0, min(current, total))
        self._progress.setRange(0, total)
        self._progress.setValue(bounded)
        self._progress.setFormat(f"{bounded} / {total}")

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
        self.set_reconstruct_sidecar_enabled(False)
        self.set_delete_enabled(False)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_initial_screen_geometry()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        apply_identity(root, "ohlcv_maintenance.layout.root", object_type="layout")
        root.addWidget(self._build_header())

        workspace = QSplitter(Qt.Orientation.Vertical, self)
        apply_identity(
            workspace,
            "ohlcv_maintenance.splitter.workspace",
            object_type="splitter",
        )
        self._splitters["workspace"] = workspace

        overview = QSplitter(Qt.Orientation.Horizontal, workspace)
        apply_identity(
            overview,
            "ohlcv_maintenance.splitter.overview",
            object_type="splitter",
        )
        self._splitters["overview"] = overview
        overview.addWidget(self._build_datasets_panel())
        overview.addWidget(self._build_evidence_panel())
        overview.setStretchFactor(0, 3)
        overview.setStretchFactor(1, 2)
        overview.setSizes([660, 440])

        results = QSplitter(Qt.Orientation.Horizontal, workspace)
        apply_identity(
            results,
            "ohlcv_maintenance.splitter.results",
            object_type="splitter",
        )
        self._splitters["results"] = results
        results.addWidget(self._build_issues_panel())
        results.addWidget(self._build_repair_panel())
        results.setStretchFactor(0, 3)
        results.setStretchFactor(1, 2)
        results.setSizes([680, 420])

        workspace.addWidget(overview)
        workspace.addWidget(results)
        workspace.setStretchFactor(0, 3)
        workspace.setStretchFactor(1, 2)
        workspace.setSizes([480, 320])
        root.addWidget(workspace, 1)
        root.addWidget(self._build_controls())

    def _build_header(self) -> QWidget:
        panel = QGroupBox("OHLCV Maintenance", self)
        apply_identity(panel, "ohlcv_maintenance.panel.header", object_type="panel")
        layout = QHBoxLayout(panel)
        title = QLabel("Canonical Validation, Repair, Evidence Recovery, and Deletion", panel)
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        apply_identity(title, "ohlcv_maintenance.title", object_type="label")
        status = QLabel("Ready", panel)
        status.setWordWrap(True)
        status.setMinimumWidth(260)
        status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        apply_identity(status, "ohlcv_maintenance.label.status", object_type="status_label")
        self._status_label = status
        layout.addWidget(title, 2)
        layout.addStretch(1)
        layout.addWidget(status, 3)
        return panel

    def _build_datasets_panel(self) -> QWidget:
        panel = QGroupBox("Persisted OHLCV Datasets", self)
        apply_identity(panel, "ohlcv_maintenance.panel.datasets", object_type="panel")
        layout = QVBoxLayout(panel)
        datasets = QTableWidget(panel)
        configure_table(datasets, _DATASET_COLUMNS, object_id="ohlcv_maintenance.table.datasets")
        datasets.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        datasets.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        datasets.itemSelectionChanged.connect(self._emit_selection_changed)
        datasets.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        datasets.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        datasets.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._tables["datasets"] = datasets
        layout.addWidget(datasets, 1)

        notes_label = QLabel("Rejected or noncanonical storage entries", panel)
        notes_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        apply_identity(notes_label, "ohlcv_maintenance.label.discovery_notes", object_type="label")
        layout.addWidget(notes_label)
        apply_identity(
            self._discovery_notes,
            "ohlcv_maintenance.discovery_notes",
            object_type="text_area",
        )
        self._discovery_notes.setReadOnly(True)
        self._discovery_notes.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._discovery_notes.setMaximumHeight(92)
        self._discovery_notes.setPlaceholderText("No rejected storage entries")
        layout.addWidget(self._discovery_notes)
        return panel

    def _build_evidence_panel(self) -> QWidget:
        panel = QGroupBox("Selected Dataset Evidence", self)
        apply_identity(panel, "ohlcv_maintenance.panel.evidence", object_type="panel")
        layout = QVBoxLayout(panel)
        hint = QLabel(
            "Read-only canonical paths, sidecar identity, fingerprints, timeline, and validation evidence.",
            panel,
        )
        hint.setWordWrap(True)
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        apply_identity(hint, "ohlcv_maintenance.label.evidence_hint", object_type="label")
        layout.addWidget(hint)
        table = QTableWidget(panel)
        configure_table(table, _DETAIL_COLUMNS, object_id="ohlcv_maintenance.table.evidence")
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tables["evidence"] = table
        layout.addWidget(table, 1)
        return panel

    def _build_issues_panel(self) -> QWidget:
        panel = QGroupBox("Canonical Validation Findings", self)
        apply_identity(panel, "ohlcv_maintenance.panel.issues", object_type="panel")
        layout = QVBoxLayout(panel)
        table = QTableWidget(panel)
        configure_table(table, _ISSUE_COLUMNS, object_id="ohlcv_maintenance.table.issues")
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tables["issues"] = table
        layout.addWidget(table, 1)
        return panel

    def _build_repair_panel(self) -> QWidget:
        panel = QGroupBox("Reviewed Repair Plan", self)
        apply_identity(panel, "ohlcv_maintenance.panel.repair", object_type="panel")
        layout = QVBoxLayout(panel)
        table = QTableWidget(panel)
        configure_table(table, _REPAIR_COLUMNS, object_id="ohlcv_maintenance.table.repair")
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._tables["repair"] = table
        layout.addWidget(table, 1)
        apply_identity(
            self._repair_summary,
            "ohlcv_maintenance.repair_summary",
            object_type="text_area",
        )
        self._repair_summary.setReadOnly(True)
        self._repair_summary.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._repair_summary.setMinimumHeight(88)
        self._repair_summary.setMaximumHeight(132)
        self._repair_summary.setPlaceholderText("No repair plan prepared")
        layout.addWidget(self._repair_summary)
        return panel

    def _build_controls(self) -> QWidget:
        panel = QGroupBox("Actions and Operation Progress", self)
        apply_identity(panel, "ohlcv_maintenance.panel.actions", object_type="action_container")
        layout = QGridLayout(panel)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        refresh = self._add_button("refresh", "Refresh Datasets", enabled=True)
        validate = self._add_button("validate", "Validate Selected", enabled=False)
        plan_repair = self._add_button("plan_repair", "Plan Repair", enabled=False)
        execute_repair = self._add_button("execute_repair", "Execute Repair", enabled=False)
        reconstruct_sidecar = self._add_button(
            "reconstruct_sidecar",
            "Rebuild Sidecar",
            enabled=False,
        )
        delete = self._add_button("delete", "Delete Selected", enabled=False)
        cancel = self._add_button("cancel", "Cancel Active Operation", enabled=False)
        refresh.clicked.connect(self.refresh_requested.emit)
        validate.clicked.connect(self.validate_requested.emit)
        plan_repair.clicked.connect(self.plan_repair_requested.emit)
        execute_repair.clicked.connect(self.execute_repair_requested.emit)
        reconstruct_sidecar.clicked.connect(self.reconstruct_sidecar_requested.emit)
        delete.clicked.connect(self.delete_requested.emit)
        cancel.clicked.connect(self.cancel_requested.emit)
        apply_identity(
            self._progress,
            "ohlcv_maintenance.progress.operation",
            object_type="progress_bar",
        )
        self._progress.setTextVisible(True)
        self._progress.setMinimumWidth(260)

        layout.addWidget(refresh, 0, 0)
        layout.addWidget(validate, 0, 1)
        layout.addWidget(plan_repair, 0, 2)
        layout.addWidget(execute_repair, 0, 3)
        layout.addWidget(reconstruct_sidecar, 1, 0)
        layout.addWidget(delete, 1, 1)
        layout.addWidget(cancel, 1, 2)
        layout.addWidget(self._progress, 1, 3)
        for column in range(4):
            layout.setColumnStretch(column, 1)
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

    def _apply_window_font_bump(self) -> None:
        font = QFont(self.font())
        point_size = font.pointSize()
        if point_size > 0:
            font.setPointSize(point_size + 1)
        else:
            point_size_f = font.pointSizeF()
            if point_size_f > 0:
                font.setPointSizeF(point_size_f + 1.0)
        self._maintenance_font = QFont(font)
        self.setFont(font)

    def _apply_maintenance_widget_fonts(self) -> None:
        font = QFont(self._maintenance_font)
        self.setFont(font)
        for widget_type in (QLabel, QPushButton, QPlainTextEdit, QTableWidget, QGroupBox):
            for widget in self.findChildren(widget_type):
                widget.setFont(font)
        for table in self._tables.values():
            table.horizontalHeader().setFont(font)
            table.verticalHeader().setFont(font)

    def _apply_initial_screen_geometry(self) -> None:
        if self._initial_geometry_applied:
            return
        screen = None
        parent = self.parentWidget()
        if parent is not None:
            screen = parent.screen()
        if screen is None:
            screen = self.screen()
        if screen is None:
            app = QApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        if not available.isValid():
            return
        width = max(self.minimumWidth(), available.width() // 2)
        width = min(width, available.width())
        height = available.height()
        x = available.left() + (available.width() - width) // 2
        self.resize(width, height)
        self.move(x, available.top())
        self._initial_geometry_applied = True
        QTimer.singleShot(
            0,
            lambda: self._fit_initial_frame_inside_available_geometry(screen),
        )

    def _fit_initial_frame_inside_available_geometry(self, screen: object) -> None:
        available = screen.availableGeometry()
        if not available.isValid():
            return

        frame = self.frameGeometry()
        if not frame.isValid():
            return

        width = self.width()
        height = self.height()
        frame_width_delta = max(0, frame.width() - self.width())
        frame_height_delta = max(0, frame.height() - self.height())
        if frame.width() > available.width():
            width = max(self.minimumWidth(), available.width() - frame_width_delta)
        if frame.height() > available.height():
            height = max(self.minimumHeight(), available.height() - frame_height_delta)
        if width != self.width() or height != self.height():
            self.resize(width, height)
            frame = self.frameGeometry()

        target_left = available.left() + (available.width() - frame.width()) // 2
        target_top = frame.top()
        if frame.top() < available.top():
            target_top += available.top() - frame.top()
        if frame.bottom() > available.bottom():
            target_top -= frame.bottom() - available.bottom()
        target_top = max(available.top(), target_top)

        if frame.left() < available.left():
            target_left = available.left()
        if frame.right() > available.right():
            target_left = min(target_left, available.right() - frame.width() + 1)
        target_left = max(available.left(), target_left)

        current_frame = self.frameGeometry()
        client_dx = self.pos().x() - current_frame.left()
        client_dy = self.pos().y() - current_frame.top()
        self.move(target_left + client_dx, target_top + client_dy)
