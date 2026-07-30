"""Content-derived sizing for Research GUI tables."""

from __future__ import annotations

import math
from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QTableWidget, QTableWidgetItem


def resize_table_columns_to_contents(
    table: QTableWidget,
    multipliers: Mapping[int, float] | None = None,
) -> None:
    """Size columns from their content, then apply optional relative multipliers."""
    if not isinstance(table, QTableWidget):
        raise TypeError("table must be a QTableWidget")
    resolved = dict(multipliers or {})
    for column, multiplier in resolved.items():
        if type(column) is not int or not 0 <= column < table.columnCount():
            raise ValueError("multiplier column must identify an existing column")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            raise TypeError("column multipliers must be positive finite numbers")
        if not math.isfinite(float(multiplier)) or multiplier <= 0:
            raise ValueError("column multipliers must be positive finite numbers")

    table.resizeColumnsToContents()
    for column, multiplier in resolved.items():
        table.setColumnWidth(
            column,
            round(table.columnWidth(column) * float(multiplier)),
        )
    table.resizeRowsToContents()
    vertical_header = table.verticalHeader()
    vertical_header.setFrameShape(QFrame.Shape.NoFrame)
    vertical_header.setContentsMargins(0, 0, 0, 0)
    vertical_header.viewport().setContentsMargins(0, 0, 0, 0)
    alignment = (
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    )
    vertical_header.setDefaultAlignment(alignment)
    vertical_header.setStyleSheet(
        """
        QHeaderView {
            border: 0px;
            padding: 0px;
            margin: 0px;
        }

        QHeaderView::section {
            padding: 0px;
            margin: 0px;
        }
        """
    )
    for row in range(table.rowCount()):
        header_item = table.verticalHeaderItem(row)
        if header_item is None:
            displayed = table.model().headerData(
                row,
                Qt.Orientation.Vertical,
                Qt.ItemDataRole.DisplayRole,
            )
            text = "" if displayed is None else str(displayed)
            header_item = QTableWidgetItem(text or str(row + 1))
            table.setVerticalHeaderItem(row, header_item)
        elif not header_item.text():
            header_item.setText(str(row + 1))
        header_item.setTextAlignment(alignment)
        vertical_header.resizeSection(row, table.rowHeight(row))
