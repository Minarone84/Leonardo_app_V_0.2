"""GUI-only Connection Suite shell with honest empty presentation state."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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


CONNECTION_SUITE_WINDOW_ID = "connection_suite.home.window"
_PROVIDER_COLUMNS = ("surface", "state", "details")
_WEBSOCKET_COLUMNS = ("channel", "state", "details")
_DOWNLOAD_COLUMNS = ("queue", "scope", "progress", "state")


class ConnectionSuiteWindow(QWidget):
    """Connection Suite shell awaiting application services."""

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
        self._footer_label: QLabel | None = None
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
            raise KeyError(f"Unknown Connection Suite button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Connection Suite table: {table_id}") from error

    def status_text(self) -> str:
        """Return the shell status label text."""

        return "" if self._status_label is None else self._status_label.text()

    def activity_log_text(self) -> str:
        """Return the local activity log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_empty_state(self) -> None:
        """Reset Connection Suite presentation without inventing provider state."""

        for table in self._tables.values():
            table.setRowCount(0)
        self._set_status("Connection services are not configured")
        self._set_footer("No provider or historical-download service is connected.")
        self._reset_log(("Connection Suite ready. No provider session is active.",))


    def clear_activity_log(self) -> None:
        """Clear the local activity log."""

        if self._log_area is not None:
            self._log_area.clear()
        self._set_status("Activity log cleared")


    def view_historical_download_manager(self) -> None:
        """Record a local placeholder handoff to the historical manager shell."""

        self._set_status("Historical Download Manager remains a separate GUI shell.")
        self._append_log(
            "View Historical Download Manager requested; no backend workflow executed."
        )

    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Connection Suite")
        self.setObjectName("connection_suite_window")
        self.setProperty("object_id", CONNECTION_SUITE_WINDOW_ID)
        self.resize(1280, 820)
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(
            root,
            "connection_suite.layout.root",
            object_type="layout",
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Connection Suite", self)
        apply_identity(
            header,
            "connection_suite.panel.header",
            object_type="panel",
        )
        layout = QHBoxLayout(header)
        apply_identity(
            layout,
            "connection_suite.layout.header",
            object_type="layout",
        )
        title = QLabel("Connection Suite", header)
        apply_identity(
            title,
            "connection_suite.label.title",
            object_type="label",
            display_label="Connection Suite",
        )
        status = QLabel("Services not connected", header)
        apply_identity(
            status,
            "connection_suite.label.status",
            object_type="status_label",
            display_label="Status",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_identity(
            toolbar,
            "connection_suite.toolbar.main",
            object_type="toolbar",
        )
        layout = QHBoxLayout(toolbar)
        apply_identity(
            layout,
            "connection_suite.layout.toolbar",
            object_type="layout",
        )
        for button_id, label, action_id, action in (
            (
                "connection_suite.button.refresh_status",
                "Refresh",
                "connection_suite.action.refresh_status",
                self.load_empty_state,
            ),
            (
                "connection_suite.button.clear_log",
                "Clear Log",
                "connection_suite.action.clear_log",
                self.clear_activity_log,
            ),
            (
                "connection_suite.button.view_historical_download_manager",
                "Historical Download Manager",
                "connection_suite.action.view_historical_download_manager",
                self.view_historical_download_manager,
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_identity(
                button,
                button_id,
                object_type="button",
                display_label=label,
                action_id=action_id,
                tooltip="Presentation action only; no provider execution is connected.",
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
            "connection_suite.splitter.overview",
            object_type="splitter",
        )
        splitter.addWidget(
            self._build_table_panel(
                panel_id="connection_suite.panel.provider_status",
                layout_id="connection_suite.layout.provider_status",
                table_id="connection_suite.table.provider_status_dummy",
                title="Provider / Account / API",
                columns=_PROVIDER_COLUMNS,
                labels=("Surface", "State", "Details"),
            )
        )
        splitter.addWidget(
            self._build_table_panel(
                panel_id="connection_suite.panel.websocket_status",
                layout_id="connection_suite.layout.websocket_status",
                table_id="connection_suite.table.websocket_status_dummy",
                title="WebSocket / Connection",
                columns=_WEBSOCKET_COLUMNS,
                labels=("Channel", "State", "Details"),
            )
        )
        splitter.addWidget(
            self._build_table_panel(
                panel_id="connection_suite.panel.download_overview",
                layout_id="connection_suite.layout.download_overview",
                table_id="connection_suite.table.download_overview_dummy",
                title="Historical Download Overview",
                columns=_DOWNLOAD_COLUMNS,
                labels=("Queue", "Scope", "Progress", "State"),
            )
        )
        splitter.addWidget(self._build_activity_panel())
        return splitter

    def _build_table_panel(
        self,
        *,
        panel_id: str,
        layout_id: str,
        table_id: str,
        title: str,
        columns: tuple[str, ...],
        labels: tuple[str, ...],
    ) -> QWidget:
        panel = QGroupBox(title, self)
        apply_identity(
            panel,
            panel_id,
            object_type="panel",
            display_label=title,
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            layout_id,
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id=table_id,
            columns=columns,
            labels=labels,
        )
        self._tables[table_id] = table
        layout.addWidget(table)
        return panel

    def _build_activity_panel(self) -> QWidget:
        panel = QGroupBox("Activity", self)
        apply_identity(
            panel,
            "connection_suite.panel.activity_log",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "connection_suite.layout.activity_log",
            object_type="layout",
        )
        log = QTextEdit(panel)
        apply_identity(
            log,
            "connection_suite.text.activity_log",
            object_type="text_area",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _build_footer(self) -> QWidget:
        footer = QGroupBox("Boundary", self)
        apply_identity(
            footer,
            "connection_suite.panel.footer",
            object_type="panel",
        )
        layout = QHBoxLayout(footer)
        apply_identity(
            layout,
            "connection_suite.layout.footer",
            object_type="layout",
        )
        label = QLabel("No provider/API/websocket/download/storage behavior is wired.", footer)
        apply_identity(
            label,
            "connection_suite.label.footer_status",
            object_type="status_label",
        )
        self._footer_label = label
        layout.addWidget(label)
        layout.addStretch(1)
        return footer

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
            window_id=CONNECTION_SUITE_WINDOW_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _set_footer(self, message: str) -> None:
        if self._footer_label is not None:
            self._footer_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)

    def _reset_log(self, messages: tuple[str, ...]) -> None:
        if self._log_area is None:
            return
        self._log_area.clear()
        for message in messages:
            self._log_area.append(message)
