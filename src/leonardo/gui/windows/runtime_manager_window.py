"""Read-only Runtime Manager window driven by GUI metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from functools import partial
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataResolver,
    load_metadata_document,
)


RUNTIME_MANAGER_METADATA_ID = "runtime_manager.window"
_RUNTIME_MANAGER_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "runtime_manager.window.toml"
)
_SUMMARY_TABLE_ID = "runtime_manager.summary_table"
_SERVICES_TABLE_ID = "runtime_manager.services_table"
_TASKS_TABLE_ID = "runtime_manager.tasks_table"
_PROCESSES_TABLE_ID = "runtime_manager.processes_table"
_CONNECTIONS_TABLE_ID = "runtime_manager.connections_table"
_WINDOWS_TABLE_ID = "runtime_manager.windows_table"
_ACTIONS_TABLE_ID = "runtime_manager.actions_table"
_OPERATIONS_TABLE_ID = "runtime_manager.operations_table"
_DOWNLOADS_TABLE_ID = "runtime_manager.downloads_table"
_AUDIT_PREVIEW_TABLE_ID = "runtime_manager.audit_preview_table"
_SECTION_SUMMARY_FIELDS = (
    "app_summary",
    "session_summary",
    "services_summary",
    "tasks_summary",
    "processes_summary",
    "connections_summary",
    "windows_summary",
    "actions_summary",
    "operations_summary",
    "downloads_summary",
    "audit_summary",
    "contracts_summary",
)
_DOWNLOAD_METRICS = (
    ("total_requests", "Total Requests", ("active_request_ids", "failed_request_ids")),
    ("total_items", "Total Items", ("active_item_ids", "failed_item_ids")),
    ("requested_count", "Requested", ()),
    ("validated_count", "Validated", ()),
    ("queued_count", "Queued", ("queued_request_ids",)),
    ("running_count", "Running", ()),
    ("completed_count", "Completed", ()),
    ("failed_count", "Failed", ("failed_request_ids", "failed_item_ids")),
    ("cancelled_count", "Cancelled", ()),
    ("skipped_count", "Skipped", ()),
    ("partially_completed_count", "Partially Completed", ()),
    ("preflight_failed_count", "Preflight Failed", ("failed_request_ids",)),
    ("websocket_required_count", "WebSocket Required", ()),
    ("connection_blocked_count", "Connection Blocked", ()),
)


SnapshotProvider = Callable[[], object]
_TRACKED_RUNTIME_MANAGER_ACTION_IDS = frozenset(
    (
        "runtime_manager.refresh_snapshot",
        "runtime_manager.close",
    )
)


def load_runtime_manager_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Runtime Manager metadata profile."""

    result = load_metadata_document(_RUNTIME_MANAGER_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Runtime Manager metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class RuntimeManagerWindow(QWidget):
    """Read-only Runtime Manager view backed by an injected snapshot provider.

    The window consumes `runtime_manager.window` metadata for its identity,
    action labels, and table headers. Refresh reads a snapshot from the
    configured provider or backend and renders local table state. The class does
    not construct Core services, mutate registries, execute operations, or own
    application lifecycle.
    """

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        snapshot_provider: SnapshotProvider | None = None,
        backend: object | None = None,
        snapshot: object | None = None,
        action_observer: GuiActionObserver | None = None,
    ) -> None:
        super().__init__()
        self._profile = profile if profile is not None else load_runtime_manager_profile()
        if self._profile.metadata_id != RUNTIME_MANAGER_METADATA_ID:
            raise ValueError("profile must describe runtime_manager.window")
        if snapshot_provider is not None and backend is not None:
            raise ValueError("Provide either snapshot_provider or backend, not both")
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")

        self._snapshot_provider = (
            snapshot_provider
            if snapshot_provider is not None
            else _snapshot_provider_from_backend(backend)
        )
        self._action_observer = action_observer
        self._actions: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._last_rendered_snapshot_summary: dict[str, object] = {}
        self._refresh_called = False
        self.close_requested_locally = False
        self._status_label: QLabel | None = None

        self._apply_profile_metadata()
        self._build_window()
        self.render_snapshot(snapshot)

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective Runtime Manager metadata profile."""

        return self._profile

    @property
    def refresh_called(self) -> bool:
        """Return whether local refresh has been requested."""

        return self._refresh_called

    @property
    def last_rendered_snapshot_summary(self) -> Mapping[str, object]:
        """Return a defensive summary of the last rendered snapshot."""

        return dict(self._last_rendered_snapshot_summary)

    def table_ids(self) -> tuple[str, ...]:
        """Return metadata table IDs in display order."""

        return tuple(self._tables)

    def action_labels(self) -> Mapping[str, str]:
        """Return metadata action labels by action ID."""

        return {action_id: button.text() for action_id, button in self._actions.items()}

    def action_button_for_id(self, action_id: str) -> QPushButton:
        """Return a Runtime Manager action button by stable action ID."""

        try:
            return self._actions[action_id]
        except KeyError as error:
            raise KeyError(f"Unknown Runtime Manager action: {action_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a Runtime Manager table widget by metadata table ID."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Runtime Manager table: {table_id}") from error

    def table_headers(self, table_id: str) -> tuple[str, ...]:
        """Return visible table header labels for a metadata table ID."""

        table = self.table_for_id(table_id)
        return tuple(
            table.horizontalHeaderItem(index).text()
            for index in range(table.columnCount())
        )

    def refresh_snapshot(self) -> None:
        """Read the current snapshot from the provider and render it locally."""

        self._refresh_called = True
        if self._snapshot_provider is None:
            self.render_snapshot(None)
            self._set_status("No runtime snapshot provider configured.")
            return

        snapshot = self._snapshot_provider()
        self.render_snapshot(snapshot)

    def render_snapshot(self, snapshot: object | None) -> None:
        """Render a read-only snapshot into metadata-defined local tables."""

        rows_by_table = _rows_by_table(snapshot)
        for table_id, table in self._tables.items():
            columns = _table_column_ids(self._profile.values, table_id)
            _render_table_rows(table, columns, rows_by_table.get(table_id, ()))

        summary = _snapshot_summary(snapshot, rows_by_table)
        self._last_rendered_snapshot_summary = summary
        self._set_status(_string_value(summary, "status_message", "Runtime snapshot rendered."))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Record that closing remained local to the widget."""

        self.close_requested_locally = True
        super().closeEvent(event)

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")

        self.setWindowTitle(_string_value(identity, "title", "Runtime Manager"))
        self.setObjectName(_string_value(metadata, "object_name", "runtime_manager_window"))
        self.resize(
            _int_value(geometry, "width", 1440),
            _int_value(geometry, "height", 900),
        )

        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_window(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        identity = _mapping_at(self._profile.values, "identity")
        title = QLabel(_string_value(identity, "title", "Runtime Manager"))
        title.setObjectName("runtime_manager.title_label")

        header = QGroupBox(_region_label(self._profile.values, "header", "Header"))
        layout = QVBoxLayout(header)
        layout.addWidget(title)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox(_region_label(self._profile.values, "toolbar", "Toolbar"))
        layout = QHBoxLayout(toolbar)
        for action_id, action in _metadata_items(_mapping_at(self._profile.values, "actions")):
            button = QPushButton(_string_value(action, "label", action_id))
            button.setObjectName(action_id)
            _connect_signal(button.clicked, partial(self._handle_action, action_id))
            self._actions[action_id] = button
            layout.addWidget(button)
        return toolbar

    def _build_body(self) -> QWidget:
        body = QGroupBox(_region_label(self._profile.values, "body", "Body"))
        layout = QVBoxLayout(body)
        tabs = QTabWidget()
        tabs.setObjectName("runtime_manager.tables")
        for table_id, table_metadata in _metadata_items(_mapping_at(self._profile.values, "tables")):
            table = self._build_table(table_id, table_metadata)
            self._tables[table_id] = table
            tabs.addTab(table, _string_value(table_metadata, "label", table_id))
        layout.addWidget(tabs)
        return body

    def _build_table(self, table_id: str, table_metadata: Mapping[str, object]) -> QTableWidget:
        columns = _sorted_columns(_mapping_at(table_metadata, "columns"))
        table = QTableWidget(0, len(columns))
        table.setObjectName(table_id)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setHorizontalHeaderLabels(
            [_string_value(column, "label", column_id) for column_id, column in columns]
        )
        return table

    def _build_footer(self) -> QWidget:
        footer = QGroupBox(_region_label(self._profile.values, "footer", "Footer"))
        layout = QHBoxLayout(footer)
        status = QLabel("No runtime snapshot rendered.")
        status.setObjectName("runtime_manager.status_label")
        self._status_label = status
        layout.addWidget(status)
        return footer

    def _handle_action(self, action_id: str) -> None:
        if action_id == "runtime_manager.refresh_snapshot":
            if not self._record_action(action_id):
                return
            self.refresh_snapshot()
            return
        if action_id == "runtime_manager.close":
            if not self._record_action(action_id):
                return
            self.close()
            return
        self._set_status(f"{action_id} is read-only metadata-only behavior in this phase.")

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _record_action(self, action_id: str) -> bool:
        if (
            self._action_observer is None
            or action_id not in _TRACKED_RUNTIME_MANAGER_ACTION_IDS
        ):
            return True
        decision = self._action_observer.record_action(
            action_id,
            window_id=RUNTIME_MANAGER_METADATA_ID,
        )
        return decision.allowed


def _snapshot_provider_from_backend(backend: object | None) -> SnapshotProvider | None:
    if backend is None:
        return None
    snapshot = getattr(backend, "snapshot", None)
    if not callable(snapshot):
        raise TypeError("backend must expose a callable snapshot method")
    return snapshot


def _connect_signal(signal: object, handler: object) -> None:
    connect = getattr(signal, "connect")
    connect(handler)


def _rows_by_table(snapshot: object | None) -> dict[str, tuple[Mapping[str, object], ...]]:
    if snapshot is None:
        return {}
    return {
        _SUMMARY_TABLE_ID: _summary_rows(snapshot),
        _SERVICES_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="services",
            list_key="services",
            item_key="service",
            ids_metadata_key="service_ids",
            names_metadata_key=None,
        ),
        _TASKS_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="tasks",
            list_key="tasks",
            item_key="task",
            ids_metadata_key="task_ids",
            names_metadata_key="task_names",
        ),
        _PROCESSES_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="processes",
            list_key="processes",
            item_key="process",
            ids_metadata_key="process_ids",
            names_metadata_key="process_labels",
        ),
        _CONNECTIONS_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="connections",
            list_key="connections",
            item_key="connection",
            ids_metadata_key="connection_ids",
            names_metadata_key="connection_labels",
        ),
        _WINDOWS_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="windows",
            list_key="windows",
            item_key="window",
            ids_metadata_key="open_window_ids",
            names_metadata_key=None,
        ),
        _ACTIONS_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="actions",
            list_key="actions",
            item_key="action",
            ids_metadata_key="recent_action_ids",
            names_metadata_key=None,
        ),
        _OPERATIONS_TABLE_ID: _section_detail_rows(
            snapshot,
            section_id="operations",
            list_key="operations",
            item_key="operation",
            ids_metadata_key="operation_ids",
            names_metadata_key="operation_labels",
        ),
        _DOWNLOADS_TABLE_ID: _downloads_rows(snapshot),
        _AUDIT_PREVIEW_TABLE_ID: _audit_preview_rows(snapshot),
    }


def _summary_rows(snapshot: object) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "section": _text_value(_field(section, "section_id", "")),
            "status": _status_text(_field(section, "status", "")),
            "count": _field(section, "count", 0),
            "details": _text_value(_field(section, "message", "")),
        }
        for section in _snapshot_sections(snapshot)
    )


def _section_detail_rows(
    snapshot: object,
    *,
    section_id: str,
    list_key: str,
    item_key: str,
    ids_metadata_key: str,
    names_metadata_key: str | None,
) -> tuple[Mapping[str, object], ...]:
    explicit_rows = _sequence_field(snapshot, list_key)
    if explicit_rows:
        return tuple(_normalize_row(item) for item in explicit_rows)

    section = _section_by_id(snapshot, section_id)
    if section is None:
        return ()

    metadata = _mapping_at_object(_field(section, "metadata", {}))
    ids = tuple(_sequence_value(metadata.get(ids_metadata_key)))
    names = (
        tuple(_sequence_value(metadata.get(names_metadata_key)))
        if names_metadata_key is not None
        else ()
    )
    if ids:
        rows: list[Mapping[str, object]] = []
        for index, item_id in enumerate(ids):
            item_label = names[index] if index < len(names) else item_id
            rows.append(
                {
                    item_key: _text_value(item_label),
                    "status": _status_text(_field(section, "status", "")),
                    "started_at": "",
                    "details": _text_value(_field(section, "message", "")),
                }
            )
        return tuple(rows)

    if _field(section, "count", 0) or _field(section, "message", ""):
        return (
            {
                item_key: section_id,
                "status": _status_text(_field(section, "status", "")),
                "started_at": "",
                "details": _text_value(_field(section, "message", "")),
            },
        )
    return ()


def _audit_preview_rows(snapshot: object) -> tuple[Mapping[str, object], ...]:
    events = _sequence_field(snapshot, "recent_audit_events")
    return tuple(
        {
            "timestamp": _text_value(
                _field(event, "timestamp", _field(event, "timestamp_utc", ""))
            ),
            "severity": _text_value(_field(event, "severity", "")),
            "event_type": _text_value(_field(event, "event_type", "")),
            "message": _text_value(_field(event, "message", "")),
            "event_id": _text_value(_field(event, "event_id", "")),
            "category": _text_value(_field(event, "category", "")),
            "actor_id": _text_value(_field(event, "actor_id", "")),
            "session_id": _text_value(_field(event, "session_id", "")),
            "window_id": _text_value(_field(event, "window_id", "")),
            "action_id": _text_value(_field(event, "action_id", "")),
            "operation_id": _text_value(_field(event, "operation_id", "")),
            "task_id": _text_value(_field(event, "task_id", "")),
            "correlation_id": _text_value(_field(event, "correlation_id", "")),
        }
        for event in events
    )


def _downloads_rows(snapshot: object) -> tuple[Mapping[str, object], ...]:
    section = _section_by_id(snapshot, "downloads")
    if section is None:
        return ()

    metadata = _mapping_at_object(_field(section, "metadata", {}))
    return tuple(
        {
            "metric": label,
            "value": metadata.get(metadata_key, 0),
            "details": _details_for(metadata, detail_keys),
        }
        for metadata_key, label, detail_keys in _DOWNLOAD_METRICS
    )


def _details_for(
    metadata: Mapping[str, object],
    keys: Sequence[str],
) -> str:
    details: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if value:
            details.append(f"{key}={_text_value(value)}")
    return "; ".join(details)


def _snapshot_summary(
    snapshot: object | None,
    rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    if snapshot is None:
        return {
            "status": "empty",
            "status_message": "No runtime snapshot available.",
            "summary_rows": 0,
            "service_rows": 0,
            "task_rows": 0,
            "download_rows": 0,
            "audit_preview_rows": 0,
        }

    health = _text_value(_field(snapshot, "health", "unknown"))
    generated_at = _text_value(
        _field(snapshot, "generated_at", _field(snapshot, "generated_at_utc", ""))
    )
    summary_rows = len(rows_by_table.get(_SUMMARY_TABLE_ID, ()))
    service_rows = len(rows_by_table.get(_SERVICES_TABLE_ID, ()))
    task_rows = len(rows_by_table.get(_TASKS_TABLE_ID, ()))
    download_rows = len(rows_by_table.get(_DOWNLOADS_TABLE_ID, ()))
    audit_rows = len(rows_by_table.get(_AUDIT_PREVIEW_TABLE_ID, ()))
    return {
        "status": "rendered",
        "health": health,
        "generated_at": generated_at,
        "summary_rows": summary_rows,
        "service_rows": service_rows,
        "task_rows": task_rows,
        "download_rows": download_rows,
        "audit_preview_rows": audit_rows,
        "status_message": f"Runtime snapshot rendered: {health}",
    }


def _render_table_rows(
    table: QTableWidget,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, column_id in enumerate(columns):
            table.setItem(
                row_index,
                column_index,
                QTableWidgetItem(_text_value(row.get(column_id, ""))),
            )


def _snapshot_sections(snapshot: object) -> tuple[object, ...]:
    sections = _field(snapshot, "sections", None)
    if sections is not None:
        return tuple(_sequence_value(sections))
    return tuple(
        section
        for field_name in _SECTION_SUMMARY_FIELDS
        if (section := _field(snapshot, field_name, None)) is not None
    )


def _section_by_id(snapshot: object, section_id: str) -> object | None:
    for section in _snapshot_sections(snapshot):
        if _field(section, "section_id", "") == section_id:
            return section
    return None


def _sequence_field(value: object, key: str) -> tuple[object, ...]:
    return tuple(_sequence_value(_field(value, key, ())))


def _sequence_value(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Mapping):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _normalize_row(item: object) -> Mapping[str, object]:
    if isinstance(item, Mapping):
        return item
    return {
        "service": _text_value(_field(item, "service", _field(item, "service_id", ""))),
        "task": _text_value(_field(item, "task", _field(item, "task_name", _field(item, "task_id", "")))),
        "status": _status_text(_field(item, "status", "")),
        "started_at": _text_value(_field(item, "started_at", _field(item, "started_at_utc", ""))),
        "details": _text_value(_field(item, "details", _field(item, "message", ""))),
    }


def _table_column_ids(values: Mapping[str, object], table_id: str) -> tuple[str, ...]:
    tables = _mapping_at(values, "tables")
    table = _mapping_at(tables, table_id)
    return tuple(column_id for column_id, _ in _sorted_columns(_mapping_at(table, "columns")))


def _mapping_at(values: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _mapping_at_object(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _field(value: object, key: str, fallback: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, fallback)
    return getattr(value, key, fallback)


def _string_value(values: Mapping[str, object], key: str, fallback: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _int_value(values: Mapping[str, object], key: str, fallback: int) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


def _text_value(value: object) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return ", ".join(f"{key}={_text_value(item)}" for key, item in value.items())
    if isinstance(value, tuple | list):
        return ", ".join(_text_value(item) for item in value)
    return str(value)


def _status_text(value: object) -> str:
    return _text_value(value)


def _region_label(values: Mapping[str, object], region_id: str, fallback: str) -> str:
    region = _mapping_at(_mapping_at(values, "regions"), region_id)
    return _string_value(region, "label", fallback)


def _metadata_items(values: Mapping[str, object]) -> tuple[tuple[str, Mapping[str, object]], ...]:
    return tuple(
        (key, item)
        for key, item in values.items()
        if isinstance(key, str) and isinstance(item, Mapping)
    )


def _sorted_columns(values: Mapping[str, object]) -> tuple[tuple[str, Mapping[str, object]], ...]:
    return tuple(
        (key, item)
        for key, item in sorted(
            values.items(),
            key=lambda entry: _int_value(entry[1], "order", 0)
            if isinstance(entry[1], Mapping)
            else 0,
        )
        if isinstance(key, str) and isinstance(item, Mapping)
    )
