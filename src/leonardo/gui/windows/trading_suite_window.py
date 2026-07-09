"""GUI-only Trading Suite shell with deterministic dummy data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

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
from leonardo.gui.dummy_data import (
    trading_account_rows,
    trading_broker_account_rows,
    trading_execution_control_rows,
    trading_overview_rows,
    trading_position_rows,
    trading_risk_summary_rows,
    trading_strategy_status_rows,
)
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


TRADING_SUITE_METADATA_ID = "trading_suite.window"
_TRADING_SUITE_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "trading_suite.window.toml"
)
_ACCOUNT_COLUMNS = ("field", "value", "status")
_OVERVIEW_COLUMNS = ("surface", "state", "details")
_BROKER_COLUMNS = ("component", "state", "details")
_RISK_COLUMNS = ("metric", "value", "state")
_POSITION_COLUMNS = ("ref", "symbol", "side", "status")
_STRATEGY_COLUMNS = ("component", "state", "details")
_EXECUTION_COLUMNS = ("control", "state", "details")


def load_trading_suite_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Trading Suite shell metadata profile."""

    result = load_metadata_document(_TRADING_SUITE_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Trading Suite metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class TradingSuiteWindow(QWidget):
    """Shell-only Trading Suite window using local dummy display data."""

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._profile = profile if profile is not None else load_trading_suite_profile()
        if self._profile.metadata_id != TRADING_SUITE_METADATA_ID:
            raise ValueError("profile must describe trading_suite.window")
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
        self.load_dummy_trading_state()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Trading Suite button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Trading Suite table: {table_id}") from error

    def status_text(self) -> str:
        """Return the shell status label text."""

        return "" if self._status_label is None else self._status_label.text()

    def status_log_text(self) -> str:
        """Return the local dummy status log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_dummy_trading_state(self) -> None:
        """Render deterministic dummy trading shell rows."""

        populate_table(
            self._tables["trading_suite.table.overview_dummy"],
            _OVERVIEW_COLUMNS,
            trading_overview_rows(),
        )
        populate_table(
            self._tables["trading_suite.table.account_risk_dummy"],
            _ACCOUNT_COLUMNS,
            trading_account_rows(),
        )
        populate_table(
            self._tables["trading_suite.table.broker_account_dummy"],
            _BROKER_COLUMNS,
            trading_broker_account_rows(),
        )
        populate_table(
            self._tables["trading_suite.table.risk_summary_dummy"],
            _RISK_COLUMNS,
            trading_risk_summary_rows(),
        )
        populate_table(
            self._tables["trading_suite.table.order_position_dummy"],
            _POSITION_COLUMNS,
            trading_position_rows(),
        )
        populate_table(
            self._tables["trading_suite.table.strategy_status_dummy"],
            _STRATEGY_COLUMNS,
            trading_strategy_status_rows(),
        )
        populate_table(
            self._tables["trading_suite.table.execution_controls_dummy"],
            _EXECUTION_COLUMNS,
            trading_execution_control_rows(),
        )
        self._set_status(
            "DUMMY trading shell loaded: no broker/order/risk behavior."
        )
        self._append_log(
            "Loaded dummy Trading Suite display. No broker, order routing, "
            "strategy, risk, or market data behavior ran."
        )

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")
        self.setWindowTitle(_string_value(identity, "title", "Trading Suite"))
        self.setObjectName(_string_value(metadata, "object_name", "trading_suite_window"))
        self.setProperty(
            "object_id",
            _string_value(metadata, "window_id", TRADING_SUITE_METADATA_ID),
        )
        self.resize(_int_value(geometry, "width", 1220), _int_value(geometry, "height", 760))
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_trace(
            root,
            "trading_suite.layout.root",
            object_type="layout",
            parent_object_id=TRADING_SUITE_METADATA_ID,
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_overview_panel())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_workspace(), stretch=1)
        root.addWidget(self._build_log_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Trading Suite Shell", self)
        apply_trace(
            header,
            "trading_suite.panel.header",
            object_type="panel",
            parent_object_id=TRADING_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(header)
        apply_trace(
            layout,
            "trading_suite.layout.header",
            object_type="layout",
            parent_object_id="trading_suite.panel.header",
        )
        title = QLabel("Trading Suite", header)
        apply_trace(
            title,
            "trading_suite.label.title",
            object_type="label",
            display_label="Trading Suite",
            parent_object_id="trading_suite.panel.header",
        )
        status = QLabel("DUMMY shell only", header)
        apply_trace(
            status,
            "trading_suite.label.status",
            object_type="status_label",
            display_label="Status",
            parent_object_id="trading_suite.panel.header",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_overview_panel(self) -> QWidget:
        panel = QGroupBox("Trading Suite Overview", self)
        apply_trace(
            panel,
            "trading_suite.panel.overview",
            object_type="panel",
            parent_object_id=TRADING_SUITE_METADATA_ID,
        )
        layout = QGridLayout(panel)
        apply_trace(
            layout,
            "trading_suite.layout.overview",
            object_type="layout",
            parent_object_id="trading_suite.panel.overview",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.overview_dummy",
            columns=_OVERVIEW_COLUMNS,
            labels=("Surface", "State", "Details"),
            parent_object_id="trading_suite.panel.overview",
        )
        notice = QLabel(
            "Shell-only: broker connections, account sync, order placement, "
            "order cancellation, risk controls, strategies, and market data "
            "subscriptions are not implemented here.",
            panel,
        )
        notice.setWordWrap(True)
        apply_trace(
            notice,
            "trading_suite.label.boundary_notice",
            object_type="label",
            display_label="Shell Boundary",
            parent_object_id="trading_suite.panel.overview",
        )
        self._tables["trading_suite.table.overview_dummy"] = table
        layout.addWidget(table, 0, 0)
        layout.addWidget(notice, 0, 1)
        return panel

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_trace(
            toolbar,
            "trading_suite.toolbar.main",
            object_type="toolbar",
            parent_object_id=TRADING_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(toolbar)
        apply_trace(
            layout,
            "trading_suite.layout.toolbar",
            object_type="layout",
            parent_object_id="trading_suite.toolbar.main",
        )
        for button_id, label, action_id, handler, enabled in (
            (
                "trading_suite.button.load_dummy_trading_state",
                "Load Dummy Trading State",
                "trading_suite.action.load_dummy_trading_state",
                self.load_dummy_trading_state,
                True,
            ),
            (
                "trading_suite.button.preview_paper_shell",
                "Preview Paper Shell",
                "trading_suite.action.preview_paper_shell",
                partial(self._local_action, "trading_suite.action.preview_paper_shell"),
                True,
            ),
            (
                "trading_suite.button.kill_switch_visual",
                "Kill Switch Placeholder",
                "trading_suite.action.kill_switch_placeholder",
                partial(
                    self._local_action,
                    "trading_suite.action.kill_switch_placeholder",
                ),
                True,
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_trace(
                button,
                button_id,
                object_type="button",
                display_label=label,
                parent_object_id="trading_suite.toolbar.main",
                action_id=action_id,
                tooltip="GUI-only dummy control; no broker or order route exists here.",
            )
            button.setEnabled(enabled)
            button.clicked.connect(partial(self._handle_shell_action, action_id, handler))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_workspace(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_trace(
            splitter,
            "trading_suite.splitter.workspace",
            object_type="splitter",
            parent_object_id=TRADING_SUITE_METADATA_ID,
        )
        splitter.addWidget(self._build_account_panel())
        splitter.addWidget(self._build_position_panel())
        splitter.addWidget(self._build_kill_switch_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        return splitter

    def _build_account_panel(self) -> QWidget:
        panel = QGroupBox("Account / Risk Dummy", self)
        apply_trace(
            panel,
            "trading_suite.panel.account_risk_dummy",
            object_type="panel",
            parent_object_id="trading_suite.splitter.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "trading_suite.layout.account_risk_dummy",
            object_type="layout",
            parent_object_id="trading_suite.panel.account_risk_dummy",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.account_risk_dummy",
            columns=_ACCOUNT_COLUMNS,
            labels=("Field", "Value", "Status"),
            parent_object_id="trading_suite.panel.account_risk_dummy",
        )
        self._tables["trading_suite.table.account_risk_dummy"] = table
        broker_table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.broker_account_dummy",
            columns=_BROKER_COLUMNS,
            labels=("Component", "State", "Details"),
            parent_object_id="trading_suite.panel.account_risk_dummy",
        )
        risk_table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.risk_summary_dummy",
            columns=_RISK_COLUMNS,
            labels=("Metric", "Value", "State"),
            parent_object_id="trading_suite.panel.account_risk_dummy",
        )
        self._tables["trading_suite.table.broker_account_dummy"] = broker_table
        self._tables["trading_suite.table.risk_summary_dummy"] = risk_table
        layout.addWidget(table)
        layout.addWidget(broker_table)
        layout.addWidget(risk_table)
        return panel

    def _build_position_panel(self) -> QWidget:
        panel = QGroupBox("Orders / Positions Dummy", self)
        apply_trace(
            panel,
            "trading_suite.panel.order_position_dummy",
            object_type="panel",
            parent_object_id="trading_suite.splitter.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "trading_suite.layout.order_position_dummy",
            object_type="layout",
            parent_object_id="trading_suite.panel.order_position_dummy",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.order_position_dummy",
            columns=_POSITION_COLUMNS,
            labels=("Reference", "Symbol", "Side", "Status"),
            parent_object_id="trading_suite.panel.order_position_dummy",
        )
        self._tables["trading_suite.table.order_position_dummy"] = table
        strategy_table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.strategy_status_dummy",
            columns=_STRATEGY_COLUMNS,
            labels=("Component", "State", "Details"),
            parent_object_id="trading_suite.panel.order_position_dummy",
        )
        self._tables["trading_suite.table.strategy_status_dummy"] = strategy_table
        layout.addWidget(table)
        layout.addWidget(strategy_table)
        return panel

    def _build_kill_switch_panel(self) -> QWidget:
        panel = QGroupBox("Kill Switch Visual Placeholder", self)
        apply_trace(
            panel,
            "trading_suite.panel.kill_switch_visual_placeholder",
            object_type="panel",
            parent_object_id="trading_suite.splitter.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "trading_suite.layout.kill_switch_visual_placeholder",
            object_type="layout",
            parent_object_id="trading_suite.panel.kill_switch_visual_placeholder",
        )
        label = QLabel("Disabled visual placeholder. No trading control is wired.", panel)
        apply_trace(
            label,
            "trading_suite.label.kill_switch_visual_placeholder",
            object_type="label",
            parent_object_id="trading_suite.panel.kill_switch_visual_placeholder",
        )
        layout.addWidget(label)
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.execution_controls_dummy",
            columns=_EXECUTION_COLUMNS,
            labels=("Control", "State", "Details"),
            parent_object_id="trading_suite.panel.kill_switch_visual_placeholder",
        )
        self._tables["trading_suite.table.execution_controls_dummy"] = table
        layout.addWidget(table)
        layout.addStretch(1)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("Status / Log", self)
        apply_trace(
            panel,
            "trading_suite.panel.status_log",
            object_type="panel",
            parent_object_id=TRADING_SUITE_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "trading_suite.layout.status_log",
            object_type="layout",
            parent_object_id="trading_suite.panel.status_log",
        )
        log = QTextEdit(panel)
        apply_trace(
            log,
            "trading_suite.text.status_log",
            object_type="text_area",
            parent_object_id="trading_suite.panel.status_log",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only dummy behavior.")
        self._append_log(f"{action_id}: no broker, order, or trading behavior ran.")

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
            window_id=TRADING_SUITE_METADATA_ID,
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
