"""GUI-only Research Suite shell with deterministic dummy data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

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

from leonardo.gui.dummy_data import (
    research_chart_control_rows,
    research_market_context_rows,
    research_overview_rows,
    research_study_rows,
    research_workspace_rows,
    research_workspace_status,
)
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.traceable_shell_widgets import (
    apply_trace,
    configure_table,
    populate_table,
)


RESEARCH_SUITE_METADATA_ID = "research_suite.window"
_RESEARCH_SUITE_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "research_suite.window.toml"
)
_RESEARCH_STUDY_COLUMNS = ("slot", "name", "status")
_RESEARCH_WORKSPACE_COLUMNS = ("pane", "symbol", "timeframe", "status")
_RESEARCH_OVERVIEW_COLUMNS = ("surface", "state", "details")
_RESEARCH_MARKET_COLUMNS = ("field", "value", "status")
_RESEARCH_CONTROL_COLUMNS = ("control", "value", "state")


def load_research_suite_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Research Suite shell metadata profile."""

    result = load_metadata_document(_RESEARCH_SUITE_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Research Suite metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class ResearchSuiteWindow(QWidget):
    """Shell-only Research Suite window populated with local dummy display data."""

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._profile = profile if profile is not None else load_research_suite_profile()
        if self._profile.metadata_id != RESEARCH_SUITE_METADATA_ID:
            raise ValueError("profile must describe research_suite.window")
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        self._action_observer = action_observer
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._log_area: QTextEdit | None = None

        self._apply_profile_metadata()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_shell()
        self.load_dummy_workspace()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

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
        """Return the local dummy status log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_dummy_workspace(self) -> None:
        """Render deterministic local dummy data into the shell."""

        populate_table(
            self._tables["research_suite.table.overview_dummy"],
            _RESEARCH_OVERVIEW_COLUMNS,
            research_overview_rows(),
        )
        populate_table(
            self._tables["research_suite.table.study_sidebar_dummy"],
            _RESEARCH_STUDY_COLUMNS,
            research_study_rows(),
        )
        populate_table(
            self._tables["research_suite.table.market_context_dummy"],
            _RESEARCH_MARKET_COLUMNS,
            research_market_context_rows(),
        )
        populate_table(
            self._tables["research_suite.table.workspace_dummy"],
            _RESEARCH_WORKSPACE_COLUMNS,
            research_workspace_rows(),
        )
        populate_table(
            self._tables["research_suite.table.chart_controls_dummy"],
            _RESEARCH_CONTROL_COLUMNS,
            research_chart_control_rows(),
        )
        self._set_status(research_workspace_status())
        self._append_log("Loaded dummy Research Suite workspace. No chart logic ran.")

    def reset_dummy_workspace(self) -> None:
        """Reset display-only dummy tables and status."""

        for table in self._tables.values():
            table.setRowCount(0)
        self._set_status("DUMMY workspace reset: shell remains inert.")
        self._append_log("Reset dummy Research Suite workspace display.")

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")
        self.setWindowTitle(_string_value(identity, "title", "Research Suite"))
        self.setObjectName(_string_value(metadata, "object_name", "research_suite_window"))
        self.setProperty("object_id", _string_value(metadata, "window_id", RESEARCH_SUITE_METADATA_ID))
        self.resize(_int_value(geometry, "width", 1280), _int_value(geometry, "height", 820))
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_trace(
            root,
            "research_suite.layout.root",
            object_type="layout",
            parent_object_id=RESEARCH_SUITE_METADATA_ID,
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_overview_panel())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_workspace(), stretch=1)
        root.addWidget(self._build_log_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Research Suite Shell", self)
        apply_trace(
            header,
            "research_suite.panel.header",
            object_type="panel",
            parent_object_id=RESEARCH_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(header)
        apply_trace(
            layout,
            "research_suite.layout.header",
            object_type="layout",
            parent_object_id="research_suite.panel.header",
        )
        title = QLabel("Research Suite", header)
        apply_trace(
            title,
            "research_suite.label.title",
            object_type="label",
            display_label="Research Suite",
            parent_object_id="research_suite.panel.header",
        )
        status = QLabel("DUMMY shell only", header)
        apply_trace(
            status,
            "research_suite.label.status",
            object_type="status_label",
            display_label="Status",
            parent_object_id="research_suite.panel.header",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_overview_panel(self) -> QWidget:
        panel = QGroupBox("Workspace Overview", self)
        apply_trace(
            panel,
            "research_suite.panel.workspace_overview",
            object_type="panel",
            parent_object_id=RESEARCH_SUITE_METADATA_ID,
        )
        layout = QGridLayout(panel)
        apply_trace(
            layout,
            "research_suite.layout.workspace_overview",
            object_type="layout",
            parent_object_id="research_suite.panel.workspace_overview",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="research_suite.table.overview_dummy",
            columns=_RESEARCH_OVERVIEW_COLUMNS,
            labels=("Surface", "State", "Details"),
            parent_object_id="research_suite.panel.workspace_overview",
        )
        self._tables["research_suite.table.overview_dummy"] = table
        boundary = QLabel(
            "Shell boundary: chart rendering, OHLCV loading, study calculation, "
            "and persistence are not implemented here.",
            panel,
        )
        boundary.setWordWrap(True)
        apply_trace(
            boundary,
            "research_suite.label.boundary_notice",
            object_type="label",
            display_label="Shell Boundary",
            parent_object_id="research_suite.panel.workspace_overview",
        )
        layout.addWidget(table, 0, 0)
        layout.addWidget(boundary, 0, 1)
        return panel

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_trace(
            toolbar,
            "research_suite.toolbar.main",
            object_type="toolbar",
            parent_object_id=RESEARCH_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(toolbar)
        apply_trace(
            layout,
            "research_suite.layout.toolbar",
            object_type="layout",
            parent_object_id="research_suite.toolbar.main",
        )
        for button_id, label, action_id, action in (
            (
                "research_suite.button.load_dummy_workspace",
                "Load Dummy Workspace",
                "research_suite.action.load_dummy_workspace",
                self.load_dummy_workspace,
            ),
            (
                "research_suite.button.reset_dummy_workspace",
                "Reset Dummy Workspace",
                "research_suite.action.reset_dummy_workspace",
                self.reset_dummy_workspace,
            ),
            (
                "research_suite.button.add_chart_placeholder",
                "Add Chart Placeholder",
                "research_suite.action.add_chart_placeholder",
                partial(self._local_action, "research_suite.action.add_chart_placeholder"),
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_trace(
                button,
                button_id,
                object_type="button",
                display_label=label,
                parent_object_id="research_suite.toolbar.main",
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
        apply_trace(
            splitter,
            "research_suite.splitter.workspace",
            object_type="splitter",
            parent_object_id=RESEARCH_SUITE_METADATA_ID,
        )
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_tabs())
        return splitter

    def _build_sidebar(self) -> QWidget:
        sidebar = QGroupBox("Study / Environment Placeholder", self)
        apply_trace(
            sidebar,
            "research_suite.panel.study_sidebar",
            object_type="panel",
            parent_object_id="research_suite.splitter.workspace",
        )
        layout = QVBoxLayout(sidebar)
        apply_trace(
            layout,
            "research_suite.layout.study_sidebar",
            object_type="layout",
            parent_object_id="research_suite.panel.study_sidebar",
        )
        label = QLabel("Study Environment", sidebar)
        apply_trace(
            label,
            "research_suite.label.study_environment",
            object_type="label",
            parent_object_id="research_suite.panel.study_sidebar",
        )
        combo = QComboBox(sidebar)
        apply_trace(
            combo,
            "research_suite.combo.study_environment_dummy",
            object_type="combo_box",
            display_label="Study Environment",
            parent_object_id="research_suite.panel.study_sidebar",
            tooltip="Dummy in-memory environment selector.",
        )
        combo.addItems(("DUMMY research environment", "DUMMY empty workspace"))
        table = configure_table(
            QTableWidget(sidebar),
            object_id="research_suite.table.study_sidebar_dummy",
            columns=_RESEARCH_STUDY_COLUMNS,
            labels=("Slot", "Name", "Status"),
            parent_object_id="research_suite.panel.study_sidebar",
        )
        self._tables["research_suite.table.study_sidebar_dummy"] = table
        market_table = configure_table(
            QTableWidget(sidebar),
            object_id="research_suite.table.market_context_dummy",
            columns=_RESEARCH_MARKET_COLUMNS,
            labels=("Field", "Value", "Status"),
            parent_object_id="research_suite.panel.study_sidebar",
        )
        self._tables["research_suite.table.market_context_dummy"] = market_table
        layout.addWidget(label)
        layout.addWidget(combo)
        layout.addWidget(table, stretch=1)
        layout.addWidget(market_table, stretch=1)
        return sidebar

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget(self)
        apply_trace(
            tabs,
            "research_suite.tabs.workspace",
            object_type="tab_widget",
            parent_object_id="research_suite.splitter.workspace",
        )
        tabs.addTab(self._build_chart_placeholder(), "Chart Workspace")
        tabs.addTab(self._build_workspace_table_panel(), "Workspace Objects")
        return tabs

    def _build_chart_placeholder(self) -> QWidget:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        apply_trace(
            panel,
            "research_suite.panel.chart_placeholder.primary",
            object_type="chart_placeholder_panel",
            parent_object_id="research_suite.tabs.workspace",
            tooltip="Placeholder only. No candlestick renderer lives here yet.",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "research_suite.layout.chart_placeholder.primary",
            object_type="layout",
            parent_object_id="research_suite.panel.chart_placeholder.primary",
        )
        title = QLabel("Chart placeholder", panel)
        apply_trace(
            title,
            "research_suite.label.chart_placeholder.title",
            object_type="label",
            parent_object_id="research_suite.panel.chart_placeholder.primary",
        )
        message = QLabel(
            "No OHLCV rendering, study calculation, viewport logic, or persistence in this phase.",
            panel,
        )
        apply_trace(
            message,
            "research_suite.label.chart_placeholder.message",
            object_type="label",
            parent_object_id="research_suite.panel.chart_placeholder.primary",
        )
        layout.addWidget(title)
        layout.addWidget(message)
        control_panel = QGroupBox("Chart Controls Placeholder", panel)
        apply_trace(
            control_panel,
            "research_suite.panel.chart_controls",
            object_type="panel",
            parent_object_id="research_suite.panel.chart_placeholder.primary",
        )
        control_layout = QVBoxLayout(control_panel)
        apply_trace(
            control_layout,
            "research_suite.layout.chart_controls",
            object_type="layout",
            parent_object_id="research_suite.panel.chart_controls",
        )
        controls = configure_table(
            QTableWidget(control_panel),
            object_id="research_suite.table.chart_controls_dummy",
            columns=_RESEARCH_CONTROL_COLUMNS,
            labels=("Control", "Value", "State"),
            parent_object_id="research_suite.panel.chart_controls",
        )
        self._tables["research_suite.table.chart_controls_dummy"] = controls
        control_layout.addWidget(controls)
        layout.addWidget(control_panel)
        layout.addStretch(1)
        return panel

    def _build_workspace_table_panel(self) -> QWidget:
        panel = QGroupBox("Workspace Object Dummy Catalog", self)
        apply_trace(
            panel,
            "research_suite.panel.workspace_objects",
            object_type="panel",
            parent_object_id="research_suite.tabs.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "research_suite.layout.workspace_objects",
            object_type="layout",
            parent_object_id="research_suite.panel.workspace_objects",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="research_suite.table.workspace_dummy",
            columns=_RESEARCH_WORKSPACE_COLUMNS,
            labels=("Pane", "Symbol", "Timeframe", "Status"),
            parent_object_id="research_suite.panel.workspace_objects",
        )
        self._tables["research_suite.table.workspace_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("Status / Log", self)
        apply_trace(
            panel,
            "research_suite.panel.status_log",
            object_type="panel",
            parent_object_id=RESEARCH_SUITE_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "research_suite.layout.status_log",
            object_type="layout",
            parent_object_id="research_suite.panel.status_log",
        )
        log = QTextEdit(panel)
        apply_trace(
            log,
            "research_suite.text.status_log",
            object_type="text_area",
            parent_object_id="research_suite.panel.status_log",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only dummy behavior.")
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
            window_id=RESEARCH_SUITE_METADATA_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)


def _mapping_at(values: object, key: str) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        return {}
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(values: object, key: str, fallback: str) -> str:
    value = values.get(key) if hasattr(values, "get") else None
    return value if isinstance(value, str) and value else fallback


def _int_value(values: object, key: str, fallback: int) -> int:
    value = values.get(key) if hasattr(values, "get") else None
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback
