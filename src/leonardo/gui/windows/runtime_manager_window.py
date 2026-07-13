"""Read-only Runtime Manager backed by direct manager snapshots."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table, populate_table

RUNTIME_MANAGER_WINDOW_ID = "runtime_manager.window"
_TABLES = {
    "runtime_manager.table.tasks": (("task_id", "Task ID"), ("task_name", "Task"), ("status", "Status"), ("progress_message", "Progress")),
    "runtime_manager.table.processes": (("process_id", "Process ID"), ("label", "Label"), ("status", "Status"), ("pid", "PID")),
    "runtime_manager.table.connections": (("connection_id", "Connection ID"), ("label", "Label"), ("status", "Status"), ("protocol", "Protocol")),
    "runtime_manager.table.windows": (("window_id", "Window ID"), ("title", "Title"), ("status", "Status"), ("window_type", "Type")),
    "runtime_manager.table.actions": (("action_id", "Action ID"), ("label", "Label"), ("window_id", "Window"), ("risk_level", "Risk")),
    "runtime_manager.table.audit": (("timestamp_utc", "Timestamp"), ("severity", "Severity"), ("event_type", "Event"), ("message", "Message")),
}
_TAB_LABELS = {
    "runtime_manager.table.tasks": "Tasks",
    "runtime_manager.table.processes": "Processes",
    "runtime_manager.table.connections": "Connections",
    "runtime_manager.table.windows": "Windows",
    "runtime_manager.table.actions": "Actions",
    "runtime_manager.table.audit": "Audit",
}


class RuntimeManagerWindow(QWidget):
    def __init__(
        self,
        *,
        snapshot_provider: Callable[[], object] | None = None,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Runtime Manager")
        self.setObjectName("runtime_manager_window")
        self.setProperty("object_id", RUNTIME_MANAGER_WINDOW_ID)
        self.resize(1200, 760)
        self.setMinimumSize(900, 560)
        self._snapshot_provider = snapshot_provider
        self._action_observer = action_observer
        self._tables: dict[str, QTableWidget] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._status_label: QLabel | None = None
        self._last_rendered_snapshot_summary = ""
        self._refresh_called = False
        apply_theme_stylesheet(self, load_default_theme())
        self._build_window()

    @property
    def refresh_called(self) -> bool:
        return self._refresh_called

    @property
    def last_rendered_snapshot_summary(self) -> str:
        return self._last_rendered_snapshot_summary

    def table_ids(self) -> tuple[str, ...]:
        return tuple(self._tables)

    def action_labels(self) -> Mapping[str, str]:
        return {key: button.text() for key, button in self._buttons.items()}

    def action_button_for_id(self, action_id: str) -> QPushButton:
        return self._buttons[action_id]

    def table_for_id(self, table_id: str) -> QTableWidget:
        return self._tables[table_id]

    def table_headers(self, table_id: str) -> tuple[str, ...]:
        table = self.table_for_id(table_id)
        return tuple(
            table.horizontalHeaderItem(index).text()
            for index in range(table.columnCount())
        )

    def status_text(self) -> str:
        return "" if self._status_label is None else self._status_label.text()

    def refresh_snapshot(self) -> object | None:
        self._refresh_called = True
        if self._snapshot_provider is None:
            self._set_status("Runtime snapshot provider is unavailable.")
            return None
        snapshot = self._snapshot_provider()
        self.render_snapshot(snapshot)
        return snapshot

    def render_snapshot(self, snapshot: object) -> None:
        mapping = _mapping(snapshot)
        table_rows = {
            "runtime_manager.table.tasks": _rows(mapping.get("tasks")),
            "runtime_manager.table.processes": _rows(mapping.get("processes")),
            "runtime_manager.table.connections": _rows(mapping.get("connections")),
            "runtime_manager.table.windows": _rows(mapping.get("windows")),
            "runtime_manager.table.actions": _rows(mapping.get("actions")),
            "runtime_manager.table.audit": _rows(mapping.get("recent_events")),
        }
        for table_id, rows in table_rows.items():
            columns = tuple(column_id for column_id, _ in _TABLES[table_id])
            populate_table(self._tables[table_id], columns, rows)
        app_status = str(mapping.get("app_status", "unknown"))
        counts = ", ".join(
            f"{_TAB_LABELS[table_id].lower()}={len(rows)}"
            for table_id, rows in table_rows.items()
        )
        self._last_rendered_snapshot_summary = f"app={app_status}; {counts}"
        self._set_status(f"Runtime snapshot rendered: {self._last_rendered_snapshot_summary}")

    def _build_window(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(root, "runtime_manager.layout.root", object_type="layout")

        header = QGroupBox("Runtime Manager", self)
        apply_identity(header, "runtime_manager.panel.header", object_type="panel")
        header_layout = QHBoxLayout(header)
        title = QLabel("Live application state from authoritative managers", header)
        apply_identity(title, "runtime_manager.label.title", object_type="label")
        self._status_label = QLabel("Ready", header)
        apply_identity(self._status_label, "runtime_manager.label.status", object_type="status_label")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self._status_label)
        root.addWidget(header)

        toolbar = QGroupBox("Actions", self)
        toolbar_layout = QHBoxLayout(toolbar)
        refresh = QPushButton("Refresh", toolbar)
        apply_identity(refresh, "runtime_manager.refresh_snapshot", object_type="button", action_id="runtime_manager.refresh_snapshot")
        refresh.clicked.connect(self._handle_refresh)
        close = QPushButton("Close", toolbar)
        apply_identity(close, "runtime_manager.close", object_type="button", action_id="runtime_manager.close")
        close.clicked.connect(self.close)
        self._buttons["runtime_manager.refresh_snapshot"] = refresh
        self._buttons["runtime_manager.close"] = close
        toolbar_layout.addWidget(refresh)
        toolbar_layout.addWidget(close)
        toolbar_layout.addStretch(1)
        root.addWidget(toolbar)

        tabs = QTabWidget(self)
        tabs.setObjectName("runtime_manager.tabs")
        for table_id, columns in _TABLES.items():
            table = QTableWidget(tabs)
            apply_identity(table, table_id, object_type="table")
            configure_table(table, columns)
            self._tables[table_id] = table
            tabs.addTab(table, _TAB_LABELS[table_id])
        root.addWidget(tabs, stretch=1)

    def _handle_refresh(self) -> None:
        if self._action_observer is not None:
            self._action_observer.record_action(
                "runtime_manager.refresh_snapshot",
                window_id=RUNTIME_MANAGER_WINDOW_ID,
            )
        self.refresh_snapshot()

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)


def _mapping(value: object) -> dict[str, object]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name))
    }


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_mapping(item) for item in value)
    return ()
