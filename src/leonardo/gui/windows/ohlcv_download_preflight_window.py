"""GUI-only Confirm OHLCV Download shell."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import (
    apply_identity,
    configure_table,
    populate_table,
)


OHLCV_DOWNLOAD_PREFLIGHT_WINDOW_ID = "ohlcv_download_preflight.window"
OHLCV_PREFLIGHT_COLUMNS = (
    "Timeframe",
    "Local File",
    "Mode",
    "Local Rows",
    "Local Range",
    "Planned Range",
    "Expected Bars",
    "Pages",
    "Page Limit",
    "Status",
)
_REQUEST_COLUMNS = ("item", "value", "state")
_VALIDATION_COLUMNS = ("check", "state", "details")
_WORKLOAD_COLUMNS = ("metric", "value", "details")


@dataclass(frozen=True)
class OhlcvDownloadPlanRow:
    """
    GUI-local row for the Confirm OHLCV Download work-plan table.

    The row is display data only. It does not represent backend state and does
    not authorize execution.
    """

    timeframe: str
    local_file_exists: bool
    update_existing: bool
    local_rows: int | str = ""
    local_range: str = ""
    planned_range: str = ""
    expected_bars: int | str = ""
    pages: int | str = ""
    page_limit: int | str = ""
    status: str = ""


class OhlcvDownloadPreflightWindow(QDialog):
    """
    Standalone GUI shell for OHLCV download confirmation.

    The dialog renders externally supplied preflight context and externally supplied
    work-plan rows only. It does not call Download Manager, provider, storage,
    or Core execution services.
    """

    start_download_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._warnings = QTextEdit(self)
        self._table = QTableWidget(self)

        self.setObjectName("ohlcv_download_preflight_window")
        self.setProperty("object_id", OHLCV_DOWNLOAD_PREFLIGHT_WINDOW_ID)
        self.setWindowTitle("Confirm OHLCV Download")
        self.resize(1120, 720)
        apply_theme_stylesheet(self, load_default_theme())
        self._build_layout()
        self.clear_preflight()

    def set_work_plan(
        self,
        rows: Iterable[OhlcvDownloadPlanRow | Mapping[str, object]],
    ) -> None:
        """Render externally supplied work-plan rows."""

        normalized = tuple(_coerce_row(row) for row in rows)
        self._table.setRowCount(len(normalized))
        for row_index, row in enumerate(normalized):
            values = (
                row.timeframe,
                "Existing local file" if row.local_file_exists else "Missing local file",
                "Update existing" if row.update_existing else "New download",
                row.local_rows,
                row.local_range,
                row.planned_range,
                row.expected_bars,
                row.pages,
                row.page_limit,
                row.status,
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_index, column_index, item)

    def clear_preflight(self) -> None:
        """Reset all preflight presentation surfaces to an empty state."""

        for table_id, columns in (
            ("ohlcv_download_preflight.request_summary_table", _REQUEST_COLUMNS),
            ("ohlcv_download_preflight.validation_checklist_table", _VALIDATION_COLUMNS),
            ("ohlcv_download_preflight.workload_estimate_table", _WORKLOAD_COLUMNS),
        ):
            populate_table(self._tables[table_id], columns, ())
        self._table.setRowCount(0)
        self._warnings.setPlainText("")
        self._warnings.setPlaceholderText("Warnings and blockers will appear here.")
        self._set_status("No request loaded")


    def table(self) -> QTableWidget:
        """Return the read-only work-plan table widget."""

        return self._table

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Confirm OHLCV Download table: {table_id}") from error

    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Confirm OHLCV Download button: {button_id}") from error

    def status_text(self) -> str:
        """Return the current shell status text."""

        return "" if self._status_label is None else self._status_label.text()

    def warnings_text(self) -> str:
        """Return the read-only warning panel text."""

        return self._warnings.toPlainText()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        apply_identity(
            layout,
            "ohlcv_download_preflight.layout.root",
            object_type="layout",
        )
        layout.addWidget(self._build_header())
        layout.addWidget(
            self._build_table_panel(
                "Request Summary",
                panel_id="ohlcv_download_preflight.panel.request_summary",
                table_id="ohlcv_download_preflight.request_summary_table",
                columns=_REQUEST_COLUMNS,
            )
        )
        layout.addWidget(self._build_work_plan_panel(), stretch=1)
        lower = QHBoxLayout()
        lower.setObjectName("ohlcv_download_preflight.layout.checks")
        lower.addWidget(
            self._build_table_panel(
                "Validation Checklist",
                panel_id="ohlcv_download_preflight.panel.validation_checklist",
                table_id="ohlcv_download_preflight.validation_checklist_table",
                columns=_VALIDATION_COLUMNS,
            )
        )
        lower.addWidget(
            self._build_table_panel(
                "Workload Estimate",
                panel_id="ohlcv_download_preflight.panel.workload_estimate",
                table_id="ohlcv_download_preflight.workload_estimate_table",
                columns=_WORKLOAD_COLUMNS,
            )
        )
        layout.addLayout(lower)
        layout.addWidget(self._build_warning_panel())
        layout.addWidget(self._build_actions())

    def _build_header(self) -> QWidget:
        panel = QGroupBox("Download Preflight", self)
        apply_identity(
            panel,
            "ohlcv_download_preflight.panel.header",
            object_type="panel",
        )
        layout = QHBoxLayout(panel)
        apply_identity(
            layout,
            "ohlcv_download_preflight.layout.header",
            object_type="layout",
        )
        header = QLabel("Confirm OHLCV Download", panel)
        apply_identity(
            header,
            "ohlcv_download_preflight.header",
            object_type="label",
        )
        status = QLabel("No request loaded", panel)
        apply_identity(
            status,
            "ohlcv_download_preflight.label.status",
            object_type="status_label",
        )
        self._status_label = status
        layout.addWidget(header)
        layout.addStretch(1)
        layout.addWidget(status)
        return panel

    def _build_table_panel(
        self,
        title: str,
        *,
        panel_id: str,
        table_id: str,
        columns: Sequence[str],
    ) -> QWidget:
        panel = QGroupBox(title, self)
        apply_identity(
            panel,
            panel_id,
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName(f"{panel_id}.layout")
        table = QTableWidget(panel)
        configure_table(
            table,
            object_id=table_id,
            columns=columns,
        )
        self._tables[table_id] = table
        layout.addWidget(table)
        return panel

    def _build_work_plan_panel(self) -> QWidget:
        panel = QGroupBox("Work Plan", self)
        apply_identity(
            panel,
            "ohlcv_download_preflight.panel.work_plan",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName("ohlcv_download_preflight.layout.work_plan")
        configure_table(
            self._table,
            object_id="ohlcv_download_preflight.work_plan_table",
            columns=OHLCV_PREFLIGHT_COLUMNS,
        )
        self._tables["ohlcv_download_preflight.work_plan_table"] = self._table
        layout.addWidget(self._table)
        return panel

    def _build_warning_panel(self) -> QWidget:
        panel = QGroupBox("Warnings", self)
        apply_identity(
            panel,
            "ohlcv_download_preflight.panel.warnings",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName("ohlcv_download_preflight.layout.warnings")
        apply_identity(
            self._warnings,
            "ohlcv_download_preflight.text.warnings",
            object_type="text_area",
        )
        self._warnings.setReadOnly(True)
        layout.addWidget(self._warnings)
        return panel

    def _build_actions(self) -> QWidget:
        panel = QGroupBox("Shell Actions", self)
        apply_identity(
            panel,
            "ohlcv_download_preflight.actions",
            object_type="action_container",
        )
        buttons = QHBoxLayout(panel)
        apply_identity(
            buttons,
            "ohlcv_download_preflight.layout.actions",
            object_type="layout",
        )
        buttons.addStretch(1)
        cancel = self._add_button("cancel", "Cancel")
        start = self._add_button("start_download", "Start Download")
        cancel.clicked.connect(self.close)
        start.clicked.connect(self.start_download_requested.emit)
        buttons.addWidget(cancel)
        buttons.addWidget(start)
        return panel

    def _add_button(self, button_id: str, label: str) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(f"ohlcv_download_preflight.{button_id}")
        apply_identity(
            button,
            button.objectName(),
            object_type="button",
            action_id=button.objectName(),
            display_label=label,
        )
        self._buttons[button_id] = button
        return button

    def _set_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(text)


def _coerce_row(row: OhlcvDownloadPlanRow | Mapping[str, object]) -> OhlcvDownloadPlanRow:
    if isinstance(row, OhlcvDownloadPlanRow):
        return row
    if not isinstance(row, Mapping):
        raise TypeError("work plan rows must be OhlcvDownloadPlanRow or mapping values")
    return OhlcvDownloadPlanRow(
        timeframe=_required_string(row, "timeframe"),
        local_file_exists=_required_bool(row, "local_file_exists"),
        update_existing=_required_bool(row, "update_existing"),
        local_rows=row.get("local_rows", ""),
        local_range=str(row.get("local_range", "")),
        planned_range=str(row.get("planned_range", "")),
        expected_bars=row.get("expected_bars", ""),
        pages=row.get("pages", ""),
        page_limit=row.get("page_limit", ""),
        status=str(row.get("status", "")),
    )


def _required_string(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_bool(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be a bool")
    return value
