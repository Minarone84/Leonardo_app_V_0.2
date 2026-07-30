"""Service-free Workspace Snapshot manager intents and recaps."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotCompatibilityReport,
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
)
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.window_geometry import apply_initial_window_size


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotLoadIntent:
    snapshot_id: str
    mode: str


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotMetadataIntent:
    snapshot_id: str
    display_name: str
    description: str


class WorkspaceSnapshotManagerDialog(QDialog):
    refresh_requested = Signal()
    selection_requested = Signal(str)
    compatibility_requested = Signal(object)
    load_requested = Signal(object)
    metadata_requested = Signal(object)
    delete_requested = Signal(str)

    def __init__(
        self,
        summaries: tuple[ResearchWorkspaceSnapshotSummary, ...],
        parent=None,
        *,
        mode: str = "manage",
    ) -> None:
        super().__init__(parent)
        if mode not in {"load", "manage"}:
            raise ValueError("mode must be 'load' or 'manage'")
        self._mode = mode
        self.setObjectName("research.workspace_snapshot_manager_dialog")
        self.setWindowTitle(
            "Load Workspace" if mode == "load" else "Manage Workspaces"
        )
        self._summaries = tuple(summaries)
        self._snapshot: ResearchWorkspaceSnapshotV1 | None = None
        self._report: ResearchWorkspaceSnapshotCompatibilityReport | None = None
        layout = QVBoxLayout(self)
        self.snapshot_list = QListWidget(self)
        self.snapshot_list.setObjectName("research.workspace_snapshot_manager_dialog.list.snapshots")
        layout.addWidget(self.snapshot_list)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("research.workspace_snapshot_manager_dialog.edit.name")
        self.description_edit = QLineEdit(self)
        self.description_edit.setObjectName("research.workspace_snapshot_manager_dialog.edit.description")
        layout.addWidget(self.name_edit)
        layout.addWidget(self.description_edit)
        self.chart_table = QTableWidget(0, 8, self)
        self.chart_table.setObjectName("research.workspace_snapshot_manager_dialog.table.charts")
        self.chart_table.setHorizontalHeaderLabels(
            (
                "Position",
                "Exchange",
                "Market Type",
                "Asset",
                "Timeframe",
                "Detached",
                "Studies",
                "Viewport",
            )
        )
        layout.addWidget(self.chart_table)
        modes = QHBoxLayout()
        self.append_radio = QRadioButton("Append", self)
        self.append_radio.setObjectName("research.workspace_snapshot_manager_dialog.radio.append")
        self.append_radio.setChecked(True)
        self.replace_radio = QRadioButton("Replace", self)
        self.replace_radio.setObjectName("research.workspace_snapshot_manager_dialog.radio.replace")
        modes.addWidget(self.append_radio)
        modes.addWidget(self.replace_radio)
        layout.addLayout(modes)
        self.compatibility_text = QTextEdit(self)
        self.compatibility_text.setObjectName("research.workspace_snapshot_manager_dialog.text.compatibility")
        self.compatibility_text.setReadOnly(True)
        layout.addWidget(self.compatibility_text)
        buttons = QHBoxLayout()
        self.refresh_button = self._button("refresh", "Refresh")
        self.metadata_button = self._button("save_metadata", "Save Changes")
        self.metadata_button.setVisible(mode == "manage")
        self.load_button = self._button("load", "Load")
        self.delete_button = self._button("delete", "Delete")
        self.close_button = self._button("close", "Close")
        for button in (
            self.refresh_button,
            self.metadata_button,
            self.load_button,
            self.delete_button,
            self.close_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.snapshot_list.currentRowChanged.connect(self._selection_changed)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.metadata_button.clicked.connect(self._emit_metadata)
        self.load_button.clicked.connect(self._emit_load)
        self.delete_button.clicked.connect(self._emit_delete)
        self.close_button.clicked.connect(self.reject)
        self.append_radio.toggled.connect(self._mode_changed)
        self.name_edit.setReadOnly(mode == "load")
        self.description_edit.setReadOnly(mode == "load")
        apply_initial_window_size(self, parent=parent)
        self.set_summaries(self._summaries)

    @property
    def selected_snapshot_id(self) -> str | None:
        item = self.snapshot_list.currentItem()
        return None if item is None else item.data(256)

    @property
    def snapshot(self) -> ResearchWorkspaceSnapshotV1 | None:
        return self._snapshot

    @property
    def compatibility_report(self) -> ResearchWorkspaceSnapshotCompatibilityReport | None:
        return self._report

    def set_summaries(self, summaries) -> None:
        self._summaries = tuple(summaries)
        self.snapshot_list.clear()
        for summary in self._summaries:
            label = summary.display_name if summary.valid else f"{summary.display_name} [invalid]"
            item = QListWidgetItem(label)
            item.setData(256, summary.snapshot_id)
            item.setData(257, summary.valid)
            item.setToolTip(summary.rejection_reason or "")
            self.snapshot_list.addItem(item)
        self._sync()

    def set_snapshot(self, snapshot: ResearchWorkspaceSnapshotV1) -> None:
        self._snapshot = snapshot
        self._report = None
        self.name_edit.setText(snapshot.display_name)
        self.description_edit.setText(snapshot.description)
        self.chart_table.setRowCount(0)
        for chart in snapshot.charts:
            row = self.chart_table.rowCount()
            self.chart_table.insertRow(row)
            values = (
                chart.workspace_position,
                chart.market_id.exchange,
                chart.market_id.market_type,
                chart.market_id.symbol,
                chart.market_id.timeframe,
                "Yes" if chart.detached else "No",
                0 if chart.study_environment is None else len(chart.study_environment.entries),
                f"{chart.viewport.center_timestamp_ms} / {chart.viewport.visible_count}",
            )
            for column, value in enumerate(values):
                self.chart_table.setItem(row, column, QTableWidgetItem(str(value)))
        resize_table_columns_to_contents(self.chart_table)
        self.compatibility_text.clear()
        self._sync()

    def set_compatibility(self, report: ResearchWorkspaceSnapshotCompatibilityReport) -> None:
        self._report = report
        self.compatibility_text.setPlainText(
            "\n".join((*report.blockers, *report.warnings)) or "Compatible"
        )
        self._sync()

    def _button(self, suffix: str, text: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName(f"research.workspace_snapshot_manager_dialog.button.{suffix}")
        return button

    def _selection_changed(self, row: int) -> None:
        self._snapshot = None
        self._report = None
        if 0 <= row < len(self._summaries):
            summary = self._summaries[row]
            self.compatibility_text.setPlainText(summary.rejection_reason or "")
            if summary.valid:
                self.selection_requested.emit(summary.snapshot_id)
        self._sync()

    def _mode_changed(self) -> None:
        self._report = None
        if self._snapshot is not None:
            self.compatibility_requested.emit(
                WorkspaceSnapshotLoadIntent(
                    self._snapshot.snapshot_id,
                    "append" if self.append_radio.isChecked() else "replace",
                )
            )
        self._sync()

    def _emit_load(self) -> None:
        if self._snapshot is None:
            return
        self.load_requested.emit(
            WorkspaceSnapshotLoadIntent(
                self._snapshot.snapshot_id,
                "append" if self.append_radio.isChecked() else "replace",
            )
        )

    def _emit_metadata(self) -> None:
        if self._mode == "manage" and self._snapshot is not None:
            self.metadata_requested.emit(
                WorkspaceSnapshotMetadataIntent(
                    self._snapshot.snapshot_id,
                    self.name_edit.text().strip(),
                    self.description_edit.text(),
                )
            )

    def _emit_delete(self) -> None:
        snapshot_id = self.selected_snapshot_id
        if snapshot_id is None:
            return
        row = self.snapshot_list.currentRow()
        if not 0 <= row < len(self._summaries):
            return
        summary = self._summaries[row]
        decision = QMessageBox.question(
            self,
            "Delete Workspace",
            f'Delete Workspace "{summary.display_name}" ({snapshot_id})?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(snapshot_id)

    def _sync(self) -> None:
        item = self.snapshot_list.currentItem()
        valid = bool(item is not None and item.data(257))
        self.delete_button.setEnabled(item is not None)
        self.metadata_button.setEnabled(valid and self._snapshot is not None)
        self.load_button.setEnabled(
            valid
            and self._snapshot is not None
            and self._report is not None
            and self._report.compatible
        )
