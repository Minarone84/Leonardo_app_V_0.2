"""GUI-only Confirm OHLCV Download shell."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID = "ohlcv_download_preflight.window"
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

    The dialog renders a table-like recap and local buttons only. It does not
    call Download Manager, provider, storage, or Core execution services.
    """

    start_download_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._buttons: dict[str, QPushButton] = {}
        self._table = QTableWidget(self)

        self.setObjectName("ohlcv_download_preflight_window")
        self.setWindowTitle("Confirm OHLCV Download")
        self.resize(980, 520)
        self._build_layout()

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
        self._table.resizeColumnsToContents()

    def table(self) -> QTableWidget:
        """Return the read-only work-plan table widget."""

        return self._table

    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Confirm OHLCV Download button: {button_id}") from error

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        header = QLabel("Confirm OHLCV Download", self)
        header.setObjectName("ohlcv_download_preflight.header")
        layout.addWidget(header)

        self._table.setObjectName("ohlcv_download_preflight.work_plan_table")
        self._table.setColumnCount(len(OHLCV_PREFLIGHT_COLUMNS))
        self._table.setHorizontalHeaderLabels(OHLCV_PREFLIGHT_COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = self._add_button("cancel", "Cancel")
        start = self._add_button("start_download", "Start Download")
        cancel.clicked.connect(self.close)
        start.clicked.connect(self.start_download_requested.emit)
        buttons.addWidget(cancel)
        buttons.addWidget(start)
        layout.addLayout(buttons)

    def _add_button(self, button_id: str, label: str) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(f"ohlcv_download_preflight.{button_id}")
        self._buttons[button_id] = button
        return button


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
