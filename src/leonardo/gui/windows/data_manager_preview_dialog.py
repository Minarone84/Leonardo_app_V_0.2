"""Read-only bounded Data Manager preview dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from leonardo.data_manager import DataManagerPreview
from leonardo.gui.data_manager.table_presentation import (
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


class DataManagerPreviewDialog(QDialog):
    """Render one immutable preview without accessing an Area service."""

    def __init__(self, preview: DataManagerPreview, parent=None) -> None:
        if not isinstance(preview, DataManagerPreview):
            raise TypeError("preview must be a DataManagerPreview")
        super().__init__(parent)
        self.setWindowTitle(preview.title)
        apply_identity(self, "data_manager_preview.dialog", object_type="dialog")
        self.resize(980, 620)
        layout = QVBoxLayout(self)
        title = QLabel(preview.title, self)
        apply_identity(title, "data_manager_preview.label.title", object_type="label")
        metadata = QLabel(
            " | ".join(f"{key}: {value}" for key, value in preview.metadata.items()), self
        )
        metadata.setWordWrap(True)
        apply_identity(metadata, "data_manager_preview.label.metadata", object_type="label")
        table = configure_table(
            QTableWidget(self),
            object_id="data_manager_preview.table.values",
            columns=preview.columns,
            labels=tuple(
                "Timestamp" if column == "ts_ms" else column
                for column in preview.columns
            ),
        )
        table.setRowCount(len(preview.rows))
        for row_index, row in enumerate(preview.rows):
            for column_index, value in enumerate(row):
                display = (
                    format_utc_timestamp_ms(int(value))
                    if preview.columns[column_index] == "ts_ms"
                    else value
                )
                table.setItem(row_index, column_index, QTableWidgetItem(display))
        resize_data_manager_table(table)
        count = QLabel(
            f"Showing {len(preview.rows)} of {preview.total_rows} rows"
            + (" (truncated)" if preview.truncated else ""),
            self,
        )
        apply_identity(count, "data_manager_preview.label.row_count", object_type="label")
        close = QPushButton("Close", self)
        apply_identity(close, "data_manager_preview.button.close", object_type="button")
        close.clicked.connect(self.accept)
        layout.addWidget(title)
        layout.addWidget(metadata)
        layout.addWidget(table, 1)
        layout.addWidget(count)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
