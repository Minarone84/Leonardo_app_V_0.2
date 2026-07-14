"""GUI-only Research Suite shell with honest empty presentation state."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTabWidget,
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


RESEARCH_SUITE_WINDOW_ID = "research_suite.window"
_RESEARCH_STUDY_COLUMNS = ("slot", "name", "status")
_RESEARCH_WORKSPACE_COLUMNS = ("pane", "symbol", "timeframe", "status")
_RESEARCH_OVERVIEW_COLUMNS = ("surface", "state", "details")
_RESEARCH_MARKET_COLUMNS = ("field", "value", "status")
_RESEARCH_CONTROL_COLUMNS = ("control", "value", "state")


class ResearchSuiteWindow(QWidget):
    """Research Suite shell awaiting application services."""

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
            raise KeyError(f"Unknown Research Suite button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Research Suite table: {table_id}") from error

    def status_text(self) -> str:
        """Return the shell status label text."""

        return "" if self._status_label is None else self._status_label.text()

    def status_log_text(self) -> str:
        """Return the local status log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_empty_state(self) -> None:
        """Reset Research Suite presentation without synthetic research data."""

        for table in self._tables.values():
            table.setRowCount(0)
        if self._log_area is not None:
            self._log_area.clear()
            self._log_area.setPlaceholderText("Research workflow messages will appear here.")
        self._set_status("Research services are not connected")


    def clear_workspace_view(self) -> None:
        """Clear the current presentation-only workspace view."""

        self.load_empty_state()


    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Research Suite")
        self.setObjectName("research_suite_window")
        self.setProperty("object_id", RESEARCH_SUITE_WINDOW_ID)
        self.resize(1280, 820)
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(
            root,
            "research_suite.layout.root",
            object_type="layout",
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_overview_panel())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_workspace(), stretch=1)
        root.addWidget(self._build_log_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Research Suite", self)
        apply_identity(
            header,
            "research_suite.panel.header",
            object_type="panel",
        )
        layout = QHBoxLayout(header)
        apply_identity(
            layout,
            "research_suite.layout.header",
            object_type="layout",
        )
        title = QLabel("Research Suite", header)
        apply_identity(
            title,
            "research_suite.label.title",
            object_type="label",
            display_label="Research Suite",
        )
        status = QLabel("Services not connected", header)
        apply_identity(
            status,
            "research_suite.label.status",
            object_type="status_label",
            display_label="Status",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_overview_panel(self) -> QWidget:
        panel = QGroupBox("Workspace Overview", self)
        apply_identity(
            panel,
            "research_suite.panel.workspace_overview",
            object_type="panel",
        )
        layout = QGridLayout(panel)
        apply_identity(
            layout,
            "research_suite.layout.workspace_overview",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="research_suite.table.overview_dummy",
            columns=_RESEARCH_OVERVIEW_COLUMNS,
            labels=("Surface", "State", "Details"),
        )
        self._tables["research_suite.table.overview_dummy"] = table
        boundary = QLabel(
            "Shell boundary: chart rendering, OHLCV loading, study calculation, "
            "and persistence are not implemented here.",
            panel,
        )
        boundary.setWordWrap(True)
        apply_identity(
            boundary,
            "research_suite.label.boundary_notice",
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
            "research_suite.toolbar.main",
            object_type="toolbar",
        )
        layout = QHBoxLayout(toolbar)
        apply_identity(
            layout,
            "research_suite.layout.toolbar",
            object_type="layout",
        )
        for button_id, label, action_id, action in (
            (
                "research_suite.button.refresh",
                "Refresh",
                "research_suite.action.refresh",
                self.load_empty_state,
            ),
            (
                "research_suite.button.clear_workspace",
                "Clear Workspace",
                "research_suite.action.clear_workspace",
                self.clear_workspace_view,
            ),
            (
                "research_suite.button.add_chart_placeholder",
                "Add Chart Placeholder",
                "research_suite.action.add_chart_placeholder",
                partial(self._local_action, "research_suite.action.add_chart_placeholder"),
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_identity(
                button,
                button_id,
                object_type="button",
                display_label=label,
                action_id=action_id,
                tooltip="GUI shell action only. No chart renderer or study calculation.",
            )
            button.clicked.connect(partial(self._handle_shell_action, action_id, action))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_workspace(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            splitter,
            "research_suite.splitter.workspace",
            object_type="splitter",
        )
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_tabs())
        return splitter

    def _build_sidebar(self) -> QWidget:
        sidebar = QGroupBox("Study / Environment Placeholder", self)
        apply_identity(
            sidebar,
            "research_suite.panel.study_sidebar",
            object_type="panel",
        )
        layout = QVBoxLayout(sidebar)
        apply_identity(
            layout,
            "research_suite.layout.study_sidebar",
            object_type="layout",
        )
        label = QLabel("Study Environment", sidebar)
        apply_identity(
            label,
            "research_suite.label.study_environment",
            object_type="label",
        )
        combo = QComboBox(sidebar)
        apply_identity(
            combo,
            "research_suite.combo.study_environment_dummy",
            object_type="combo_box",
            display_label="Study Environment",
            tooltip="Presentation-only environment selector.",
        )
        combo.addItems(("No research environment configured", "Empty workspace"))
        table = configure_table(
            QTableWidget(sidebar),
            object_id="research_suite.table.study_sidebar_dummy",
            columns=_RESEARCH_STUDY_COLUMNS,
            labels=("Slot", "Name", "Status"),
        )
        self._tables["research_suite.table.study_sidebar_dummy"] = table
        market_table = configure_table(
            QTableWidget(sidebar),
            object_id="research_suite.table.market_context_dummy",
            columns=_RESEARCH_MARKET_COLUMNS,
            labels=("Field", "Value", "Status"),
        )
        self._tables["research_suite.table.market_context_dummy"] = market_table
        layout.addWidget(label)
        layout.addWidget(combo)
        layout.addWidget(table, stretch=1)
        layout.addWidget(market_table, stretch=1)
        return sidebar

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget(self)
        apply_identity(
            tabs,
            "research_suite.tabs.workspace",
            object_type="tab_widget",
        )
        tabs.addTab(self._build_chart_placeholder(), "Chart Workspace")
        tabs.addTab(self._build_workspace_table_panel(), "Workspace Objects")
        return tabs

    def _build_chart_placeholder(self) -> QWidget:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        apply_identity(
            panel,
            "research_suite.panel.chart_placeholder.primary",
            object_type="chart_placeholder_panel",
            tooltip="Placeholder only. No candlestick renderer lives here yet.",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "research_suite.layout.chart_placeholder.primary",
            object_type="layout",
        )
        title = QLabel("Chart placeholder", panel)
        apply_identity(
            title,
            "research_suite.label.chart_placeholder.title",
            object_type="label",
        )
        message = QLabel(
            "No OHLCV rendering, study calculation, viewport logic, or persistence in this phase.",
            panel,
        )
        apply_identity(
            message,
            "research_suite.label.chart_placeholder.message",
            object_type="label",
        )
        layout.addWidget(title)
        layout.addWidget(message)
        control_panel = QGroupBox("Chart Controls Placeholder", panel)
        apply_identity(
            control_panel,
            "research_suite.panel.chart_controls",
            object_type="panel",
        )
        control_layout = QVBoxLayout(control_panel)
        apply_identity(
            control_layout,
            "research_suite.layout.chart_controls",
            object_type="layout",
        )
        controls = configure_table(
            QTableWidget(control_panel),
            object_id="research_suite.table.chart_controls_dummy",
            columns=_RESEARCH_CONTROL_COLUMNS,
            labels=("Control", "Value", "State"),
        )
        self._tables["research_suite.table.chart_controls_dummy"] = controls
        control_layout.addWidget(controls)
        layout.addWidget(control_panel)
        layout.addStretch(1)
        return panel

    def _build_workspace_table_panel(self) -> QWidget:
        panel = QGroupBox("Workspace Objects", self)
        apply_identity(
            panel,
            "research_suite.panel.workspace_objects",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "research_suite.layout.workspace_objects",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="research_suite.table.workspace_dummy",
            columns=_RESEARCH_WORKSPACE_COLUMNS,
            labels=("Pane", "Symbol", "Timeframe", "Status"),
        )
        self._tables["research_suite.table.workspace_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("Status / Log", self)
        apply_identity(
            panel,
            "research_suite.panel.status_log",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "research_suite.layout.status_log",
            object_type="layout",
        )
        log = QTextEdit(panel)
        apply_identity(
            log,
            "research_suite.text.status_log",
            object_type="text_area",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is unavailable in the reset baseline.")
        self._append_log(f"{action_id}: no chart logic executed.")

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
            window_id=RESEARCH_SUITE_WINDOW_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)
