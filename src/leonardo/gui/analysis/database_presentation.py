"""Disposable database metadata for the Analysis GUI, with no store access."""
from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.display_time import format_display_timestamp_ms
from leonardo.gui.windows.shell_widgets import configure_table

DATABASE_COLUMNS = (
    "Database Name", "Exchange", "Market Type", "Asset", "Timeframe",
    "Rows", "Columns", "First Timestamp", "Last Timestamp",
)

@dataclass(frozen=True)
class DatabaseDisplayEntry:
    """Injected display metadata only; not a persisted database definition."""
    database_id: str
    name: str
    exchange: str
    market_type: str
    asset: str
    timeframe: str
    rows: int | None = None
    columns: int | None = None
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None

    def display_values(self) -> tuple[str, ...]:
        return (
            self.name, self.exchange, self.market_type, self.asset, self.timeframe,
            "" if self.rows is None else f"{self.rows:,}",
            "" if self.columns is None else f"{self.columns:,}",
            format_display_timestamp_ms(self.first_timestamp_ms),
            format_display_timestamp_ms(self.last_timestamp_ms),
        )

    def sort_values(self) -> tuple[object, ...]:
        return (self.name.casefold(), self.exchange.casefold(), self.market_type.casefold(),
                self.asset.casefold(), self.timeframe.casefold(), self.rows, self.columns,
                self.first_timestamp_ms, self.last_timestamp_ms)

def display_catalog(entries) -> tuple[DatabaseDisplayEntry, ...]:
    """Reject ambiguous GUI identity before replacing a displayed catalogue."""
    result = tuple(entries)
    if any(not isinstance(entry, DatabaseDisplayEntry) for entry in result):
        raise TypeError("catalogue entries must be DatabaseDisplayEntry values")
    ids = [entry.database_id for entry in result]
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        raise ValueError("database display identity must be a non-empty string")
    if len(ids) != len(set(ids)):
        raise ValueError("database display identities must be unique")
    return result

class _DisplayItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: object) -> None:
        super().__init__(text)
        self._sort_value = sort_value
        self.setToolTip(text)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if not isinstance(other, _DisplayItem):
            return super().__lt__(other)
        left, right = self._sort_value, other._sort_value
        if left is None or right is None:
            return left is None and right is not None
        return left < right

def database_table(parent, object_id: str, *, removable: bool = False) -> QTableWidget:
    labels = ("Use" if removable else "Select", *DATABASE_COLUMNS)
    if removable:
        labels += ("Remove",)
    table = configure_table(QTableWidget(parent), object_id=object_id, columns=labels)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setMinimumWidth(0)
    table.setMinimumHeight(120)
    table.setWordWrap(False)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSortIndicator(1, Qt.SortOrder.AscendingOrder)
    if removable:
        # Keep each row's action beside its checkbox when metadata scrolls.
        table.horizontalHeader().moveSection(10, 1)
    return table

def populate_database_row(table: QTableWidget, row: int, entry: DatabaseDisplayEntry, *, checked: bool) -> None:
    check = _DisplayItem("", entry.name.casefold())
    check.setData(Qt.ItemDataRole.UserRole, entry.database_id)
    check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    check.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    check.setToolTip("Include in the workspace" if table.columnCount() == 10 else "Use in the current analysis selection")
    table.setItem(row, 0, check)
    for column, (value, sort_value) in enumerate(zip(entry.display_values(), entry.sort_values(), strict=True), 1):
        item = _DisplayItem(value, sort_value)
        item.setData(Qt.ItemDataRole.UserRole, entry.database_id)
        if column == 1:
            item.setToolTip(f"{entry.name}\nDatabase ID: {entry.database_id}")
        if column in (6, 7):
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, column, item)

def size_database_table(table: QTableWidget) -> None:
    resize_data_manager_table(table)
    table.setColumnWidth(0, 62)

