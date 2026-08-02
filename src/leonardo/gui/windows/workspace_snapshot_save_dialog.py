"""Service-free Workspace Snapshot create/update intent dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotSummary,
    WorkspaceSnapshotCapture,
)
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.window_geometry import apply_initial_window_size


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotSaveIntent:
    mode: str
    snapshot_id: str | None
    display_name: str
    description: str


class WorkspaceSnapshotSaveDialog(QDialog):
    save_requested = Signal(object)

    def __init__(
        self,
        capture: WorkspaceSnapshotCapture,
        summaries: tuple[ResearchWorkspaceSnapshotSummary, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("research.workspace_snapshot_save_dialog")
        self.setWindowTitle("Save Workspace")
        self._capture = capture
        self._summaries = tuple(item for item in summaries if item.valid)
        self._create_name = ""
        self._create_description = ""
        self.setStyleSheet(
            "QRadioButton::indicator {"
            " background-color: #111827; border: 1px solid #9CA3AF;"
            " width: 13px; height: 13px; border-radius: 7px;"
            "}"
            "QRadioButton::indicator:checked {"
            " background-color: #9CA3AF; border: 1px solid #D1D5DB;"
            "}"
        )
        layout = QVBoxLayout(self)
        modes = QHBoxLayout()
        self.create_radio = QRadioButton("Create", self)
        self.create_radio.setObjectName("research.workspace_snapshot_save_dialog.radio.create")
        self.create_radio.setChecked(True)
        self.update_radio = QRadioButton("Update", self)
        self.update_radio.setObjectName("research.workspace_snapshot_save_dialog.radio.update")
        modes.addWidget(self.create_radio)
        modes.addWidget(self.update_radio)
        layout.addLayout(modes)
        self.existing_combo = QComboBox(self)
        self.existing_combo.setObjectName("research.workspace_snapshot_save_dialog.combo.existing")
        for summary in self._summaries:
            self.existing_combo.addItem(summary.display_name, summary.snapshot_id)
        layout.addWidget(self.existing_combo)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("research.workspace_snapshot_save_dialog.edit.name")
        self.name_edit.setPlaceholderText("Workspace name")
        layout.addWidget(self.name_edit)
        self.description_edit = QPlainTextEdit(self)
        self.description_edit.setObjectName("research.workspace_snapshot_save_dialog.edit.description")
        self.description_edit.setPlaceholderText("Description")
        line_spacing = self.description_edit.fontMetrics().lineSpacing()
        document_margins = round(
            self.description_edit.document().documentMargin() * 2
        )
        self.description_edit.setMinimumHeight(
            3 * line_spacing
            + 2 * self.description_edit.frameWidth()
            + document_margins
        )
        layout.addWidget(self.description_edit)
        self.chart_table = QTableWidget(0, 11, self)
        self.chart_table.setObjectName("research.workspace_snapshot_save_dialog.table.charts")
        self.chart_table.setHorizontalHeaderLabels(
            (
                "Position",
                "Exchange",
                "Market Type",
                "Asset",
                "Timeframe",
                "Detached",
                "Studies",
                "Viewport center UTC",
                "Visible bars",
                "Scale",
                "Volume",
            )
        )
        for chart in capture.charts:
            row = self.chart_table.rowCount()
            self.chart_table.insertRow(row)
            values = (
                chart.workspace_position,
                chart.market_id.exchange,
                chart.market_id.market_type,
                chart.market_id.symbol,
                chart.market_id.timeframe,
                "Yes" if chart.detached else "No",
                len(chart.studies),
                chart.viewport.center_timestamp_ms,
                chart.viewport.visible_count,
                "Autoscale" if chart.price_scale.autoscale_enabled else "Manual",
                "Visible" if chart.volume_visible else "Hidden",
            )
            for column, value in enumerate(values):
                self.chart_table.setItem(row, column, QTableWidgetItem(str(value)))
        resize_table_columns_to_contents(self.chart_table)
        layout.addWidget(self.chart_table)
        self.validation_label = QLabel("", self)
        self.validation_label.setObjectName("research.workspace_snapshot_save_dialog.label.validation")
        layout.addWidget(self.validation_label)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName("research.workspace_snapshot_save_dialog.button.save")
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("research.workspace_snapshot_save_dialog.button.cancel")
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self._emit_save)
        self.cancel_button.clicked.connect(self.reject)
        self.update_radio.toggled.connect(self._mode_changed)
        self.existing_combo.currentIndexChanged.connect(self._populate_existing)
        self.name_edit.textChanged.connect(self._sync)
        apply_initial_window_size(self, parent=parent)
        self._sync()

    def _populate_existing(self) -> None:
        if not self.update_radio.isChecked() or self.existing_combo.currentIndex() < 0:
            return
        summary = self._summaries[self.existing_combo.currentIndex()]
        self.name_edit.setText(summary.display_name)
        self.description_edit.setPlainText(summary.description)

    def _mode_changed(self, update: bool) -> None:
        if update:
            self._create_name = self.name_edit.text()
            self._create_description = self.description_edit.toPlainText()
            self._populate_existing()
        else:
            self.name_edit.setText(self._create_name)
            self.description_edit.setPlainText(self._create_description)
        self._sync()

    def _sync(self) -> None:
        update = self.update_radio.isChecked()
        self.existing_combo.setEnabled(update)
        self.name_edit.setReadOnly(update)
        name = self.name_edit.text().strip()
        if update:
            valid = self.existing_combo.currentIndex() >= 0
        else:
            duplicate = any(
                item.display_name.casefold() == name.casefold()
                for item in self._summaries
            )
            valid = bool(name) and not duplicate
        self.validation_label.setText("" if valid else "Enter a unique non-empty workspace name.")
        self.save_button.setEnabled(valid)

    def _emit_save(self) -> None:
        update = self.update_radio.isChecked()
        snapshot_id = self.existing_combo.currentData() if update else None
        display_name = self.name_edit.text().strip()
        if update:
            summary = self._summaries[self.existing_combo.currentIndex()]
            display_name = summary.display_name
        self.save_requested.emit(
            WorkspaceSnapshotSaveIntent(
                "update" if update else "create",
                snapshot_id,
                display_name,
                self.description_edit.toPlainText(),
            )
        )
        self.accept()
