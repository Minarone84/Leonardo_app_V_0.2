"""GUI-only Trading Suite shell with honest empty presentation state."""

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


TRADING_SUITE_WINDOW_ID = "trading_suite.window"
_ACCOUNT_COLUMNS = ("field", "value", "status")
_OVERVIEW_COLUMNS = ("surface", "state", "details")
_BROKER_COLUMNS = ("component", "state", "details")
_RISK_COLUMNS = ("metric", "value", "state")
_POSITION_COLUMNS = ("ref", "symbol", "side", "status")
_STRATEGY_COLUMNS = ("component", "state", "details")
_EXECUTION_COLUMNS = ("control", "state", "details")


class TradingSuiteWindow(QWidget):
    """Shell-only Trading Suite window using local display data."""

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
        """Return the local status log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_empty_state(self) -> None:
        """Reset Trading Suite presentation without synthetic account data."""

        for table in self._tables.values():
            table.setRowCount(0)
        if self._log_area is not None:
            self._log_area.clear()
            self._log_area.setPlaceholderText("Trading workflow messages will appear here.")
        self._set_status("Trading services are not connected")


    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Trading Suite")
        self.setObjectName("trading_suite_window")
        self.setProperty("object_id", TRADING_SUITE_WINDOW_ID)
        self.resize(1220, 760)
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(
            root,
            "trading_suite.layout.root",
            object_type="layout",
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_overview_panel())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_workspace(), stretch=1)
        root.addWidget(self._build_log_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Trading Suite", self)
        apply_identity(
            header,
            "trading_suite.panel.header",
            object_type="panel",
        )
        layout = QHBoxLayout(header)
        apply_identity(
            layout,
            "trading_suite.layout.header",
            object_type="layout",
        )
        title = QLabel("Trading Suite", header)
        apply_identity(
            title,
            "trading_suite.label.title",
            object_type="label",
            display_label="Trading Suite",
        )
        status = QLabel("Services not connected", header)
        apply_identity(
            status,
            "trading_suite.label.status",
            object_type="status_label",
            display_label="Status",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_overview_panel(self) -> QWidget:
        panel = QGroupBox("Trading Suite Overview", self)
        apply_identity(
            panel,
            "trading_suite.panel.overview",
            object_type="panel",
        )
        layout = QGridLayout(panel)
        apply_identity(
            layout,
            "trading_suite.layout.overview",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.overview_dummy",
            columns=_OVERVIEW_COLUMNS,
            labels=("Surface", "State", "Details"),
        )
        notice = QLabel(
            "Shell-only: broker connections, account sync, order placement, "
            "order cancellation, risk controls, strategies, and market data "
            "subscriptions are not implemented here.",
            panel,
        )
        notice.setWordWrap(True)
        apply_identity(
            notice,
            "trading_suite.label.boundary_notice",
            object_type="label",
            display_label="Shell Boundary",
        )
        self._tables["trading_suite.table.overview_dummy"] = table
        layout.addWidget(table, 0, 0)
        layout.addWidget(notice, 0, 1)
        return panel

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_identity(
            toolbar,
            "trading_suite.toolbar.main",
            object_type="toolbar",
        )
        layout = QHBoxLayout(toolbar)
        apply_identity(
            layout,
            "trading_suite.layout.toolbar",
            object_type="layout",
        )
        for button_id, label, action_id, handler, enabled in (
            (
                "trading_suite.button.refresh",
                "Refresh",
                "trading_suite.action.refresh",
                self.load_empty_state,
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
            apply_identity(
                button,
                button_id,
                object_type="button",
                display_label=label,
                action_id=action_id,
                tooltip="Presentation control only; no broker or order route is connected.",
            )
            button.setEnabled(enabled)
            button.clicked.connect(partial(self._handle_shell_action, action_id, handler))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_workspace(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            splitter,
            "trading_suite.splitter.workspace",
            object_type="splitter",
        )
        splitter.addWidget(self._build_account_panel())
        splitter.addWidget(self._build_position_panel())
        splitter.addWidget(self._build_kill_switch_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        return splitter

    def _build_account_panel(self) -> QWidget:
        panel = QGroupBox("Account / Risk", self)
        apply_identity(
            panel,
            "trading_suite.panel.account_risk_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "trading_suite.layout.account_risk_dummy",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.account_risk_dummy",
            columns=_ACCOUNT_COLUMNS,
            labels=("Field", "Value", "Status"),
        )
        self._tables["trading_suite.table.account_risk_dummy"] = table
        broker_table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.broker_account_dummy",
            columns=_BROKER_COLUMNS,
            labels=("Component", "State", "Details"),
        )
        risk_table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.risk_summary_dummy",
            columns=_RISK_COLUMNS,
            labels=("Metric", "Value", "State"),
        )
        self._tables["trading_suite.table.broker_account_dummy"] = broker_table
        self._tables["trading_suite.table.risk_summary_dummy"] = risk_table
        layout.addWidget(table)
        layout.addWidget(broker_table)
        layout.addWidget(risk_table)
        return panel

    def _build_position_panel(self) -> QWidget:
        panel = QGroupBox("Orders / Positions", self)
        apply_identity(
            panel,
            "trading_suite.panel.order_position_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "trading_suite.layout.order_position_dummy",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.order_position_dummy",
            columns=_POSITION_COLUMNS,
            labels=("Reference", "Symbol", "Side", "Status"),
        )
        self._tables["trading_suite.table.order_position_dummy"] = table
        strategy_table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.strategy_status_dummy",
            columns=_STRATEGY_COLUMNS,
            labels=("Component", "State", "Details"),
        )
        self._tables["trading_suite.table.strategy_status_dummy"] = strategy_table
        layout.addWidget(table)
        layout.addWidget(strategy_table)
        return panel

    def _build_kill_switch_panel(self) -> QWidget:
        panel = QGroupBox("Kill Switch Visual Placeholder", self)
        apply_identity(
            panel,
            "trading_suite.panel.kill_switch_visual_placeholder",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "trading_suite.layout.kill_switch_visual_placeholder",
            object_type="layout",
        )
        label = QLabel("Disabled visual placeholder. No trading control is wired.", panel)
        apply_identity(
            label,
            "trading_suite.label.kill_switch_visual_placeholder",
            object_type="label",
        )
        layout.addWidget(label)
        table = configure_table(
            QTableWidget(panel),
            object_id="trading_suite.table.execution_controls_dummy",
            columns=_EXECUTION_COLUMNS,
            labels=("Control", "State", "Details"),
        )
        self._tables["trading_suite.table.execution_controls_dummy"] = table
        layout.addWidget(table)
        layout.addStretch(1)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("Status / Log", self)
        apply_identity(
            panel,
            "trading_suite.panel.status_log",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "trading_suite.layout.status_log",
            object_type="layout",
        )
        log = QTextEdit(panel)
        apply_identity(
            log,
            "trading_suite.text.status_log",
            object_type="text_area",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only unavailable behavior.")
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
            window_id=TRADING_SUITE_WINDOW_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)
