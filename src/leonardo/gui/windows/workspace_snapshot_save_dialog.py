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
        self.setWindowTitle("Save Workspace Snapshot")
        self._capture = capture
        self._summaries = tuple(item for item in summaries if item.valid)
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
        self.name_edit.setPlaceholderText("Snapshot name")
        layout.addWidget(self.name_edit)
        self.description_edit = QLineEdit(self)
        self.description_edit.setObjectName("research.workspace_snapshot_save_dialog.edit.description")
        self.description_edit.setPlaceholderText("Description")
        layout.addWidget(self.description_edit)
        self.chart_table = QTableWidget(0, 8, self)
        self.chart_table.setObjectName("research.workspace_snapshot_save_dialog.table.charts")
        self.chart_table.setHorizontalHeaderLabels(
            ("Position", "Market", "Detached", "Studies", "Viewport center UTC", "Visible bars", "Scale", "Volume")
        )
        for chart in capture.charts:
            row = self.chart_table.rowCount()
            self.chart_table.insertRow(row)
            values = (
                chart.workspace_position,
                chart.market_id.as_key(),
                "Yes" if chart.detached else "No",
                len(chart.studies),
                chart.viewport.center_timestamp_ms,
                chart.viewport.visible_count,
                "Autoscale" if chart.price_scale.autoscale_enabled else "Manual",
                "Visible" if chart.volume_visible else "Hidden",
            )
            for column, value in enumerate(values):
                self.chart_table.setItem(row, column, QTableWidgetItem(str(value)))
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
        self.update_radio.toggled.connect(self._sync)
        self.existing_combo.currentIndexChanged.connect(self._populate_existing)
        self.name_edit.textChanged.connect(self._sync)
        self._sync()

    def _populate_existing(self) -> None:
        if not self.update_radio.isChecked() or self.existing_combo.currentIndex() < 0:
            return
        summary = self._summaries[self.existing_combo.currentIndex()]
        self.name_edit.setText(summary.display_name)
        self.description_edit.setText(summary.description)

    def _sync(self) -> None:
        update = self.update_radio.isChecked()
        self.existing_combo.setEnabled(update)
        name = self.name_edit.text().strip()
        duplicate = any(
            item.display_name.casefold() == name.casefold()
            for item in self._summaries
        )
        valid = bool(name) and ((update and self.existing_combo.currentIndex() >= 0) or not duplicate)
        self.validation_label.setText("" if valid else "Enter a unique non-empty snapshot name.")
        self.save_button.setEnabled(valid)

    def _emit_save(self) -> None:
        update = self.update_radio.isChecked()
        snapshot_id = self.existing_combo.currentData() if update else None
        self.save_requested.emit(
            WorkspaceSnapshotSaveIntent(
                "update" if update else "create",
                snapshot_id,
                self.name_edit.text().strip(),
                self.description_edit.text(),
            )
        )
        self.accept()
