"""Service-free completed Workspace Snapshot preflight dialog."""

from PySide6.QtCore import Signal
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


class WorkspaceSnapshotPreflightDialog(QDialog):
    load_requested = Signal(object)

    def __init__(self, report: ResearchWorkspaceSnapshotCompatibilityReport, parent=None):
        super().__init__(parent)
        if not isinstance(report, ResearchWorkspaceSnapshotCompatibilityReport):
            raise TypeError("report must be a Workspace Snapshot compatibility report")
        self.report = report
        self.setObjectName("research.workspace_snapshot_preflight_dialog")
        self.setWindowTitle("Workspace Snapshot Preflight")
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
        layout.addWidget(progress)
        buttons = QHBoxLayout()
        load = QPushButton("Load", self)
        load.setObjectName("research.workspace_snapshot_preflight_dialog.button.load")
        load.setEnabled(report.compatible)
        cancel = QPushButton("Cancel", self)
        cancel.setObjectName("research.workspace_snapshot_preflight_dialog.button.cancel")
        buttons.addWidget(load)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        load.clicked.connect(lambda: (self.load_requested.emit(report), self.accept()))
        cancel.clicked.connect(self.reject)
