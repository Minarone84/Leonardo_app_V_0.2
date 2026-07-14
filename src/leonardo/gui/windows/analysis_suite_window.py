"""GUI-only Analysis Suite shell with honest empty presentation state."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import (
    apply_identity,
    configure_table,
    populate_table,
)


ANALYSIS_SUITE_WINDOW_ID = "analysis_suite.window"
_READINESS_COLUMNS = ("item", "state", "details")
_FEATURE_COLUMNS = ("feature_set", "status", "notes")
_OVERVIEW_COLUMNS = ("surface", "state", "details")
_RESULT_COLUMNS = ("result", "value", "state")
_DIAGNOSTICS_COLUMNS = ("check", "state", "details")
_QUEUE_COLUMNS = ("queue", "state", "details")


class AnalysisSuiteWindow(QWidget):
    """Shell-only Analysis Suite window using local display data."""

    def __init__(
        self,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        self._action_observer = action_observer
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._report_area: QTextEdit | None = None
        self._log_area: QTextEdit | None = None

        self._apply_window_defaults()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_shell()
        self.load_empty_state()


    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Analysis Suite button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Analysis Suite table: {table_id}") from error

    def status_text(self) -> str:
        """Return the shell status label text."""

        return "" if self._status_label is None else self._status_label.text()

    def report_text(self) -> str:
        """Return the local diagnostics report text."""

        return "" if self._report_area is None else self._report_area.toPlainText()

    def status_log_text(self) -> str:
        """Return the local status log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_empty_state(self) -> None:
        """Reset Analysis Suite presentation without synthetic analysis results."""

        for table in self._tables.values():
            table.setRowCount(0)
        if self._report_area is not None:
            self._report_area.clear()
            self._report_area.setPlaceholderText("Analysis reports will appear here.")
        if self._log_area is not None:
            self._log_area.clear()
            self._log_area.setPlaceholderText("Analysis workflow messages will appear here.")
        self._set_status("Analysis services are not connected")


    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Analysis Suite")
        self.setObjectName("analysis_suite_window")
        self.setProperty("object_id", ANALYSIS_SUITE_WINDOW_ID)
        self.resize(1280, 820)
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(
            root,
            "analysis_suite.layout.root",
            object_type="layout",
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_overview_panel())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_status_log())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Analysis Suite", self)
        apply_identity(
            header,
            "analysis_suite.panel.header",
            object_type="panel",
        )
        layout = QHBoxLayout(header)
        apply_identity(
            layout,
            "analysis_suite.layout.header",
            object_type="layout",
        )
        title = QLabel("Analysis Suite", header)
        apply_identity(
            title,
            "analysis_suite.label.title",
            object_type="label",
        )
        status = QLabel("Services not connected", header)
        apply_identity(
            status,
            "analysis_suite.label.status",
            object_type="status_label",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_overview_panel(self) -> QWidget:
        panel = QGroupBox("Analysis Workspace Overview", self)
        apply_identity(
            panel,
            "analysis_suite.panel.overview",
            object_type="panel",
        )
        layout = QGridLayout(panel)
        apply_identity(
            layout,
            "analysis_suite.layout.overview",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.overview_dummy",
            columns=_OVERVIEW_COLUMNS,
            labels=("Surface", "State", "Details"),
        )
        self._tables["analysis_suite.table.overview_dummy"] = table
        boundary = QLabel(
            "Shell boundary: analysis execution, dataset loading, report writing, "
            "and diagnostics engines are not implemented here.",
            panel,
        )
        boundary.setWordWrap(True)
        apply_identity(
            boundary,
            "analysis_suite.label.boundary_notice",
            object_type="label",
            display_label="Shell Boundary",
        )
        layout.addWidget(table, 0, 0)
        layout.addWidget(boundary, 0, 1)
        return panel

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_identity(
            toolbar,
            "analysis_suite.toolbar.main",
            object_type="toolbar",
        )
        layout = QHBoxLayout(toolbar)
        apply_identity(
            layout,
            "analysis_suite.layout.toolbar",
            object_type="layout",
        )
        for button_id, label, action_id, action in (
            (
                "analysis_suite.button.refresh",
                "Refresh",
                "analysis_suite.action.refresh",
                self.load_empty_state,
            ),
            (
                "analysis_suite.button.preview_target_plan",
                "Preview Target Plan",
                "analysis_suite.action.preview_target_plan",
                partial(self._local_action, "analysis_suite.action.preview_target_plan"),
            ),
            (
                "analysis_suite.button.preview_diagnostics",
                "Preview Diagnostics",
                "analysis_suite.action.preview_diagnostics",
                partial(self._local_action, "analysis_suite.action.preview_diagnostics"),
            ),
            (
                "analysis_suite.button.clear_view",
                "Clear Analysis View",
                "analysis_suite.action.clear_view",
                self.clear_analysis_view,
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_identity(
                button,
                button_id,
                object_type="button",
                display_label=label,
                action_id=action_id,
                tooltip="GUI shell action only. No analysis engine.",
            )
            button.clicked.connect(partial(self._handle_shell_action, action_id, action))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            splitter,
            "analysis_suite.splitter.workspace",
            object_type="splitter",
        )
        splitter.addWidget(self._build_readiness_panel())
        splitter.addWidget(self._build_planning_panel())
        splitter.addWidget(self._build_report_panel())
        splitter.addWidget(self._build_queue_panel())
        return splitter

    def _build_readiness_panel(self) -> QWidget:
        panel = QGroupBox("Readiness", self)
        apply_identity(
            panel,
            "analysis_suite.panel.readiness_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "analysis_suite.layout.readiness_dummy",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.readiness_dummy",
            columns=_READINESS_COLUMNS,
            labels=("Item", "State", "Details"),
        )
        self._tables["analysis_suite.table.readiness_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_planning_panel(self) -> QWidget:
        panel = QGroupBox("Target / Feature Planning", self)
        apply_identity(
            panel,
            "analysis_suite.panel.target_feature_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "analysis_suite.layout.target_feature_dummy",
            object_type="layout",
        )
        target = QLabel("Target plan placeholder: no labels generated.", panel)
        apply_identity(
            target,
            "analysis_suite.label.target_plan_dummy",
            object_type="label",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.feature_plan_dummy",
            columns=_FEATURE_COLUMNS,
            labels=("Feature Set", "Status", "Notes"),
        )
        self._tables["analysis_suite.table.feature_plan_dummy"] = table
        results = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.result_summary_dummy",
            columns=_RESULT_COLUMNS,
            labels=("Result", "Value", "State"),
        )
        self._tables["analysis_suite.table.result_summary_dummy"] = results
        layout.addWidget(target)
        layout.addWidget(table)
        layout.addWidget(results)
        return panel

    def _build_report_panel(self) -> QWidget:
        panel = QGroupBox("Diagnostics Report", self)
        apply_identity(
            panel,
            "analysis_suite.panel.diagnostics_report_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "analysis_suite.layout.diagnostics_report_dummy",
            object_type="layout",
        )
        report = QTextEdit(panel)
        apply_identity(
            report,
            "analysis_suite.text.diagnostics_report_dummy",
            object_type="text_area",
        )
        report.setReadOnly(True)
        self._report_area = report
        diagnostics = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.diagnostics_dummy",
            columns=_DIAGNOSTICS_COLUMNS,
            labels=("Check", "State", "Details"),
        )
        self._tables["analysis_suite.table.diagnostics_dummy"] = diagnostics
        layout.addWidget(diagnostics)
        layout.addWidget(report)
        return panel

    def _build_queue_panel(self) -> QWidget:
        panel = QGroupBox("Queue / Status", self)
        apply_identity(
            panel,
            "analysis_suite.panel.queue_status_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "analysis_suite.layout.queue_status_dummy",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.queue_status_dummy",
            columns=_QUEUE_COLUMNS,
            labels=("Queue", "State", "Details"),
        )
        self._tables["analysis_suite.table.queue_status_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_status_log(self) -> QWidget:
        panel = QGroupBox("Status / Log", self)
        apply_identity(
            panel,
            "analysis_suite.panel.status_log",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "analysis_suite.layout.status_log",
            object_type="layout",
        )
        log = QTextEdit(panel)
        apply_identity(
            log,
            "analysis_suite.text.status_log",
            object_type="text_area",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def clear_analysis_view(self) -> None:
        """Clear the current presentation-only analysis view."""

        self.load_empty_state()


    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only unavailable behavior.")
        self._append_log(f"{action_id}: no Analysis Suite engine ran.")

    def _handle_shell_action(
        self,
        action_id: str,
        handler: Callable[[], None],
    ) -> None:
        if not self._record_action(action_id):
            return
        handler()

    def _record_action(self, action_id: str) -> bool:
        if self._action_observer is None:
            return True
        decision = self._action_observer.record_action(
            action_id,
            window_id=ANALYSIS_SUITE_WINDOW_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)
