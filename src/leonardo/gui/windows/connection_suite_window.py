"""GUI-only Connection Suite shell with deterministic dummy display data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

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
from leonardo.gui.dummy_data import (
    connection_activity_messages,
    connection_download_overview_rows,
    connection_provider_status_rows,
    connection_websocket_status_rows,
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


CONNECTION_SUITE_METADATA_ID = "connection_suite.home.window"
_CONNECTION_SUITE_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "connection_suite.window.toml"
)
_PROVIDER_COLUMNS = ("surface", "state", "details")
_WEBSOCKET_COLUMNS = ("channel", "state", "details")
_DOWNLOAD_COLUMNS = ("queue", "scope", "progress", "state")


def load_connection_suite_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Connection Suite shell metadata profile."""

    result = load_metadata_document(_CONNECTION_SUITE_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Connection Suite metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class ConnectionSuiteWindow(QWidget):
    """Shell-only Connection Suite window using local dummy display data."""

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._profile = profile if profile is not None else load_connection_suite_profile()
        if self._profile.metadata_id != CONNECTION_SUITE_METADATA_ID:
            raise ValueError("profile must describe connection_suite.home.window")
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

        self._apply_profile_metadata()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_shell()
        self.load_dummy_status()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

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
        """Return the local dummy activity log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_dummy_status(self) -> None:
        """Render deterministic local dummy connection status data."""

        populate_table(
            self._tables["connection_suite.table.provider_status_dummy"],
            _PROVIDER_COLUMNS,
            connection_provider_status_rows(),
        )
        populate_table(
            self._tables["connection_suite.table.websocket_status_dummy"],
            _WEBSOCKET_COLUMNS,
            connection_websocket_status_rows(),
        )
        populate_table(
            self._tables["connection_suite.table.download_overview_dummy"],
            _DOWNLOAD_COLUMNS,
            connection_download_overview_rows(),
        )
        self._set_status("DUMMY connection surfaces loaded: no provider/API/websocket behavior.")
        self._set_footer("Historical Download Manager overview is shell-only.")
        self._reset_log(connection_activity_messages())

    def clear_dummy_log(self) -> None:
        """Clear the local dummy activity log."""

        if self._log_area is not None:
            self._log_area.clear()
        self._set_status("DUMMY activity log cleared locally.")

    def view_historical_download_manager(self) -> None:
        """Record a local placeholder handoff to the historical manager shell."""

        self._set_status("Historical Download Manager remains a separate GUI shell.")
        self._append_log(
            "View Historical Download Manager requested; no backend workflow executed."
        )

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")
        self.setWindowTitle(_string_value(identity, "title", "Connection Suite"))
        self.setObjectName(_string_value(metadata, "object_name", "connection_suite_window"))
        self.setProperty(
            "object_id",
            _string_value(metadata, "window_id", CONNECTION_SUITE_METADATA_ID),
        )
        self.resize(_int_value(geometry, "width", 1280), _int_value(geometry, "height", 820))
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_trace(
            root,
            "connection_suite.layout.root",
            object_type="layout",
            parent_object_id=CONNECTION_SUITE_METADATA_ID,
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Connection Suite Shell", self)
        apply_trace(
            header,
            "connection_suite.panel.header",
            object_type="panel",
            parent_object_id=CONNECTION_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(header)
        apply_trace(
            layout,
            "connection_suite.layout.header",
            object_type="layout",
            parent_object_id="connection_suite.panel.header",
        )
        title = QLabel("Connection Suite", header)
        apply_trace(
            title,
            "connection_suite.label.title",
            object_type="label",
            display_label="Connection Suite",
            parent_object_id="connection_suite.panel.header",
        )
        status = QLabel("DUMMY shell only", header)
        apply_trace(
            status,
            "connection_suite.label.status",
            object_type="status_label",
            display_label="Status",
            parent_object_id="connection_suite.panel.header",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_trace(
            toolbar,
            "connection_suite.toolbar.main",
            object_type="toolbar",
            parent_object_id=CONNECTION_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(toolbar)
        apply_trace(
            layout,
            "connection_suite.layout.toolbar",
            object_type="layout",
            parent_object_id="connection_suite.toolbar.main",
        )
        for button_id, label, action_id, action in (
            (
                "connection_suite.button.refresh_dummy_status",
                "Refresh Dummy Status",
                "connection_suite.action.refresh_dummy_status",
                self.load_dummy_status,
            ),
            (
                "connection_suite.button.clear_dummy_log",
                "Clear Dummy Log",
                "connection_suite.action.clear_dummy_log",
                self.clear_dummy_log,
            ),
            (
                "connection_suite.button.view_historical_download_manager",
                "Historical Download Manager",
                "connection_suite.action.view_historical_download_manager",
                self.view_historical_download_manager,
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_trace(
                button,
                button_id,
                object_type="button",
                display_label=label,
                parent_object_id="connection_suite.toolbar.main",
                action_id=action_id,
                tooltip="GUI shell action only. No provider, websocket, or download execution.",
            )
            button.clicked.connect(partial(self._handle_shell_action, action_id, action))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_trace(
            splitter,
            "connection_suite.splitter.overview",
            object_type="splitter",
            parent_object_id=CONNECTION_SUITE_METADATA_ID,
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
        apply_trace(
            panel,
            panel_id,
            object_type="panel",
            display_label=title,
            parent_object_id="connection_suite.splitter.overview",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            layout_id,
            object_type="layout",
            parent_object_id=panel_id,
        )
        table = configure_table(
            QTableWidget(panel),
            object_id=table_id,
            columns=columns,
            labels=labels,
            parent_object_id=panel_id,
        )
        self._tables[table_id] = table
        layout.addWidget(table)
        return panel

    def _build_activity_panel(self) -> QWidget:
        panel = QGroupBox("Dummy Activity", self)
        apply_trace(
            panel,
            "connection_suite.panel.activity_log",
            object_type="panel",
            parent_object_id="connection_suite.splitter.overview",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "connection_suite.layout.activity_log",
            object_type="layout",
            parent_object_id="connection_suite.panel.activity_log",
        )
        log = QTextEdit(panel)
        apply_trace(
            log,
            "connection_suite.text.activity_log",
            object_type="text_area",
            parent_object_id="connection_suite.panel.activity_log",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _build_footer(self) -> QWidget:
        footer = QGroupBox("Boundary", self)
        apply_trace(
            footer,
            "connection_suite.panel.footer",
            object_type="panel",
            parent_object_id=CONNECTION_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(footer)
        apply_trace(
            layout,
            "connection_suite.layout.footer",
            object_type="layout",
            parent_object_id="connection_suite.panel.footer",
        )
        label = QLabel("No provider/API/websocket/download/storage behavior is wired.", footer)
        apply_trace(
            label,
            "connection_suite.label.footer_status",
            object_type="status_label",
            parent_object_id="connection_suite.panel.footer",
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
            window_id=CONNECTION_SUITE_METADATA_ID,
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
