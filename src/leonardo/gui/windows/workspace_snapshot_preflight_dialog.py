"""Service-free Workspace Snapshot preflight and restore-progress dialog."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotCompatibilityReport
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.window_geometry import apply_initial_window_size


class WorkspaceSnapshotPreflightDialog(QDialog):
    load_requested = Signal(object)

    def __init__(self, report: ResearchWorkspaceSnapshotCompatibilityReport, parent=None):
        super().__init__(parent)
        if not isinstance(report, ResearchWorkspaceSnapshotCompatibilityReport):
            raise TypeError("report must be a Workspace Snapshot compatibility report")
        self.report = report
        self.setObjectName("research.workspace_snapshot_preflight_dialog")
        self.setWindowTitle("Load Workspace")
        layout = QVBoxLayout(self)
        mode = QLabel(report.mode.title(), self)
        mode.setObjectName("research.workspace_snapshot_preflight_dialog.label.mode")
        layout.addWidget(mode)
        table = QTableWidget(0, 4, self)
        table.setObjectName("research.workspace_snapshot_preflight_dialog.table.charts")
        table.setHorizontalHeaderLabels(("Position", "Chart", "Compatible", "Details"))
        for chart in report.charts:
            row = table.rowCount()
            table.insertRow(row)
            values = (
                chart.workspace_position,
                chart.chart_ref,
                "Yes" if chart.compatible else "No",
                "; ".join((*chart.blockers, *chart.warnings)),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table = table
        resize_table_columns_to_contents(table)
        layout.addWidget(table)
        text = QTextEdit(self)
        text.setObjectName("research.workspace_snapshot_preflight_dialog.text.report")
        text.setReadOnly(True)
        text.setPlainText("\n".join((*report.blockers, *report.warnings)) or "Compatible")
        layout.addWidget(text)
        progress = QProgressBar(self)
        progress.setObjectName("research.workspace_snapshot_preflight_dialog.progress")
        progress.setRange(0, 1)
        progress.setValue(1)
        self.progress = progress
        layout.addWidget(progress)
        current_progress = QProgressBar(self)
        current_progress.setObjectName(
            "research.workspace_snapshot_preflight_dialog.progress.current"
        )
        current_progress.setRange(0, 1)
        current_progress.setValue(0)
        current_progress.hide()
        self.current_progress = current_progress
        layout.addWidget(current_progress)
        restore_status = QLabel("", self)
        restore_status.setObjectName(
            "research.workspace_snapshot_preflight_dialog.label.restore_status"
        )
        self.restore_status = restore_status
        layout.addWidget(restore_status)
        buttons = QHBoxLayout()
        load = QPushButton("Load Workspace", self)
        load.setObjectName("research.workspace_snapshot_preflight_dialog.button.load")
        load.setEnabled(report.compatible)
        cancel = QPushButton("Cancel", self)
        cancel.setObjectName("research.workspace_snapshot_preflight_dialog.button.cancel")
        buttons.addWidget(load)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.load_button = load
        self.cancel_button = cancel
        self._state = "preflight"
        self._total_charts = 0
        load.clicked.connect(self._request_load)
        cancel.clicked.connect(self.reject)
        apply_initial_window_size(self, parent=parent)

    @property
    def restore_active(self) -> bool:
        return self._state in {"restore", "rollback"}

    def begin_restore(self, total_charts: int) -> None:
        self._begin_active("restore", total_charts, "Preparing Workspace restore...")

    def begin_rollback(self, total_charts: int) -> None:
        self._begin_active(
            "rollback",
            total_charts,
            "Workspace restore failed. Restoring previous workspace...",
        )

    def set_restore_stage(self, message: str) -> None:
        if not self.restore_active:
            return
        self.restore_status.setText(message)
        self.set_current_indeterminate()

    def set_current_indeterminate(self) -> None:
        if not self.restore_active:
            return
        self.current_progress.show()
        self.current_progress.setRange(0, 0)

    def set_current_progress(self, current: int | None, total: int | None) -> None:
        if not self.restore_active:
            return
        self.current_progress.show()
        if (
            type(current) is int
            and type(total) is int
            and total > 0
            and 0 <= current <= total
        ):
            self.current_progress.setRange(0, total)
            self.current_progress.setValue(current)
            return
        self.current_progress.setRange(0, 0)

    def complete_chart(self, completed: int, total: int) -> None:
        if not self.restore_active:
            return
        if type(completed) is not int or type(total) is not int:
            raise TypeError("chart progress must use integers")
        if total != self._total_charts or not 0 <= completed <= total:
            raise ValueError("chart progress must match the active restore")
        self.progress.setValue(completed)
        self.current_progress.setRange(0, 1)
        self.current_progress.setValue(1)
        self.restore_status.setText(f"Chart {completed} of {total} complete.")

    def show_success(self) -> None:
        if not self.restore_active:
            return
        self.progress.setValue(self._total_charts)
        self.current_progress.setRange(0, 1)
        self.current_progress.setValue(1)
        self.restore_status.setText("Workspace restored.")
        self._state = "success"

    def show_failure(self, message: str) -> None:
        self._show_terminal(f"Workspace restore failed: {message}")

    def show_rollback_success(self, original_message: str) -> None:
        self._show_terminal(
            f"Workspace restore failed: {original_message}\n"
            "Previous workspace restored."
        )

    def show_rollback_failure(
        self, original_message: str, rollback_message: str
    ) -> None:
        self._show_terminal(
            f"Workspace restore failed: {original_message}\n"
            f"Rollback failed: {rollback_message}"
        )

    def reject(self) -> None:
        if self.restore_active:
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.restore_active:
            event.ignore()
            return
        super().closeEvent(event)

    def _request_load(self) -> None:
        if self._state != "preflight" or not self.load_button.isEnabled():
            return
        self.load_requested.emit(self.report)
        if self._state == "preflight":
            self.begin_restore(len(self.report.charts))

    def _begin_active(self, state: str, total_charts: int, message: str) -> None:
        if type(total_charts) is not int or total_charts < 0:
            raise ValueError("total_charts must be a non-negative integer")
        self._state = state
        self._total_charts = total_charts
        self.progress.setRange(0, total_charts)
        self.progress.setValue(0)
        self.current_progress.show()
        self.current_progress.setRange(0, 0)
        self.restore_status.setText(message)
        self.load_button.setEnabled(False)
        self.cancel_button.setText("Cancel")
        self.cancel_button.setEnabled(False)

    def _show_terminal(self, message: str) -> None:
        self._state = "failure"
        self.current_progress.setRange(0, 1)
        self.current_progress.setValue(0)
        self.restore_status.setText(message)
        self.load_button.setEnabled(False)
        self.cancel_button.setText("Close")
        self.cancel_button.setEnabled(True)
