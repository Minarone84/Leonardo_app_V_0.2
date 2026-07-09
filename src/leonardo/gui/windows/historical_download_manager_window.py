"""GUI-only Historical Download Manager shell."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.dummy_data import connection_download_overview_rows
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.traceable_shell_widgets import (
    apply_trace,
    configure_table,
    populate_table,
)


HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID = "historical_download_manager.window"
_QUEUE_COLUMNS = ("queue", "scope", "progress", "state")


class HistoricalDownloadManagerWindow(QWidget):
    """
    Standalone GUI shell for Connection Suite Download Manager intent.

    The widget owns only presentation state and local GUI signals. Timeframe
    options must be supplied by composition or tests through
    `set_available_timeframes`; the shell does not parse provider metadata,
    call backend services, or execute downloads.
    """

    start_requested = Signal()
    maintenance_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._field_widgets: dict[str, QWidget] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._timeframe_checkboxes: dict[str, QCheckBox] = {}
        self._timeframe_layout = QVBoxLayout()
        self._timeframe_layout.setObjectName("historical_download_manager.layout.timeframes")
        self._status_log = QTextEdit(self)
        self._queue_progress = QProgressBar(self)

        self.setObjectName("historical_download_manager_window")
        self.setProperty("object_id", HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID)
        self.setWindowTitle("Historical Download Manager")
        self.resize(980, 760)
        apply_theme_stylesheet(self, load_default_theme())
        self._build_layout()
        self.load_dummy_queue_overview()

    def set_available_timeframes(self, timeframes: Iterable[str]) -> None:
        """Replace displayed timeframe checkboxes with externally supplied values."""

        normalized = _normalize_string_options(timeframes, "timeframes")
        self._clear_timeframe_widgets()
        for timeframe in normalized:
            checkbox = QCheckBox(timeframe, self)
            checkbox.setObjectName(f"historical_download_manager.timeframe.{timeframe}")
            checkbox.setProperty("object_id", checkbox.objectName())
            checkbox.setProperty("object_type", "checkbox")
            checkbox.setProperty("parent_object_id", "historical_download_manager.timeframes")
            self._timeframe_checkboxes[timeframe] = checkbox
            self._timeframe_layout.addWidget(checkbox)
        self._timeframe_layout.addStretch(1)

    def available_timeframes(self) -> tuple[str, ...]:
        """Return displayed timeframe values in GUI order."""

        return tuple(self._timeframe_checkboxes)

    def selected_timeframes(self) -> tuple[str, ...]:
        """Return checked timeframe values in GUI order."""

        return tuple(
            timeframe
            for timeframe, checkbox in self._timeframe_checkboxes.items()
            if checkbox.isChecked()
        )

    def select_all_timeframes(self) -> None:
        """Check every displayed timeframe checkbox."""

        for checkbox in self._timeframe_checkboxes.values():
            checkbox.setChecked(True)

    def clear_timeframes(self) -> None:
        """Clear every displayed timeframe checkbox."""

        for checkbox in self._timeframe_checkboxes.values():
            checkbox.setChecked(False)

    def field_widget_for_id(self, field_id: str) -> QWidget:
        """Return a stable field widget by identifier."""

        try:
            return self._field_widgets[field_id]
        except KeyError as error:
            raise KeyError(f"Unknown Historical Download Manager field: {field_id}") from error

    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Historical Download Manager button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Historical Download Manager table: {table_id}") from error

    def queue_progress_bar(self) -> QProgressBar:
        """Return the shell-only dummy queue progress bar."""

        return self._queue_progress

    def timeframe_checkbox_for_value(self, timeframe: str) -> QCheckBox:
        """Return the checkbox for a displayed timeframe value."""

        try:
            return self._timeframe_checkboxes[timeframe]
        except KeyError as error:
            raise KeyError(f"Unknown Historical Download Manager timeframe: {timeframe}") from error

    def status_log(self) -> QTextEdit:
        """Return the read-only status/log surface."""

        return self._status_log

    def load_dummy_queue_overview(self) -> None:
        """Render deterministic local dummy queue data without execution."""

        populate_table(
            self._tables["historical_download_manager.table.queue_dummy"],
            _QUEUE_COLUMNS,
            connection_download_overview_rows(),
        )
        self._queue_progress.setValue(0)
        self._status_log.append(
            "Loaded dummy historical download queue. No provider/API/storage path ran."
        )

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        apply_trace(
            layout,
            "historical_download_manager.layout.root",
            object_type="layout",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        layout.addWidget(self._build_header())

        selection_panel = QGroupBox("Selection", self)
        apply_trace(
            selection_panel,
            "historical_download_manager.selection",
            object_type="panel",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        form = QFormLayout()
        apply_trace(
            form,
            "historical_download_manager.layout.selection_form",
            object_type="layout",
            parent_object_id="historical_download_manager.selection",
        )
        self._add_field(form, "exchange", "Exchange", QComboBox(self))
        self._add_field(form, "market_type", "Market Type", QComboBox(self))
        self._add_field(form, "symbol", "Symbol", QLineEdit(self))
        self._add_field(form, "start_ms", "Start ms", QLineEdit(self))
        self._add_field(form, "end_ms", "End ms", QLineEdit(self))
        limit = QLineEdit(self)
        limit.setText("200")
        self._add_field(form, "limit", "Limit", limit)
        selection_panel.setLayout(form)
        layout.addWidget(selection_panel)

        timeframe_panel = QGroupBox("Timeframes", self)
        apply_trace(
            timeframe_panel,
            "historical_download_manager.timeframes",
            object_type="checklist",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        timeframe_panel_layout = QVBoxLayout(timeframe_panel)
        apply_trace(
            timeframe_panel_layout,
            "historical_download_manager.layout.timeframe_panel",
            object_type="layout",
            parent_object_id="historical_download_manager.timeframes",
        )
        timeframes_label = QLabel("Timeframes", self)
        apply_trace(
            timeframes_label,
            "historical_download_manager.label.timeframes",
            object_type="label",
            parent_object_id="historical_download_manager.timeframes",
        )
        timeframe_panel_layout.addWidget(timeframes_label)
        timeframe_container = QWidget(self)
        timeframe_container.setLayout(self._timeframe_layout)
        timeframe_panel_layout.addWidget(timeframe_container)

        timeframe_buttons = QHBoxLayout()
        apply_trace(
            timeframe_buttons,
            "historical_download_manager.layout.timeframe_buttons",
            object_type="layout",
            parent_object_id="historical_download_manager.timeframes",
        )
        select_all = self._add_button(
            "select_all_timeframes",
            "Select All Timeframes",
            enabled=True,
        )
        clear = self._add_button(
            "clear_timeframes",
            "Clear/Deselect All Timeframes",
            enabled=True,
        )
        select_all.clicked.connect(self.select_all_timeframes)
        clear.clicked.connect(self.clear_timeframes)
        timeframe_buttons.addWidget(select_all)
        timeframe_buttons.addWidget(clear)
        timeframe_panel_layout.addLayout(timeframe_buttons)
        layout.addWidget(timeframe_panel)

        layout.addWidget(self._build_dummy_queue_panel())

        action_buttons = QHBoxLayout()
        apply_trace(
            action_buttons,
            "historical_download_manager.layout.action_buttons",
            object_type="layout",
            parent_object_id="historical_download_manager.actions",
        )
        start = self._add_button("start", "Start", enabled=True)
        stop = self._add_button("stop", "Stop", enabled=False)
        maintenance = self._add_button("ohlcv_maintenance", "OHLCV Maintenance", enabled=True)
        start.clicked.connect(self.start_requested.emit)
        maintenance.clicked.connect(self.maintenance_requested.emit)
        action_buttons.addWidget(start)
        action_buttons.addWidget(stop)
        action_buttons.addWidget(maintenance)
        actions_panel = QGroupBox("Actions", self)
        apply_trace(
            actions_panel,
            "historical_download_manager.actions",
            object_type="action_container",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        actions_panel.setLayout(action_buttons)
        layout.addWidget(actions_panel)

        status_panel = QGroupBox("Status Log", self)
        apply_trace(
            status_panel,
            "historical_download_manager.panel.status_log",
            object_type="panel",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        status_layout = QVBoxLayout(status_panel)
        apply_trace(
            status_layout,
            "historical_download_manager.layout.status_log",
            object_type="layout",
            parent_object_id="historical_download_manager.panel.status_log",
        )
        apply_trace(
            self._status_log,
            "historical_download_manager.status_log",
            object_type="text_area",
            parent_object_id="historical_download_manager.panel.status_log",
        )
        self._status_log.setReadOnly(True)
        self._status_log.setPlaceholderText("Status and log output")
        status_layout.addWidget(self._status_log)
        layout.addWidget(status_panel)

    def _build_header(self) -> QWidget:
        header = QGroupBox("Historical Download Manager Shell", self)
        apply_trace(
            header,
            "historical_download_manager.panel.header",
            object_type="panel",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        header_layout = QHBoxLayout(header)
        apply_trace(
            header_layout,
            "historical_download_manager.layout.header",
            object_type="layout",
            parent_object_id="historical_download_manager.panel.header",
        )
        title = QLabel("Historical Download Manager", self)
        apply_trace(
            title,
            "historical_download_manager.title",
            object_type="label",
            parent_object_id="historical_download_manager.panel.header",
        )
        status = QLabel("DUMMY queue/progress shell only", self)
        apply_trace(
            status,
            "historical_download_manager.label.shell_status",
            object_type="status_label",
            parent_object_id="historical_download_manager.panel.header",
        )
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(status)
        return header

    def _build_dummy_queue_panel(self) -> QWidget:
        panel = QGroupBox("Dummy Queue Overview", self)
        apply_trace(
            panel,
            "historical_download_manager.panel.queue_status_dummy",
            object_type="panel",
            parent_object_id=HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "historical_download_manager.layout.queue_status_dummy",
            object_type="layout",
            parent_object_id="historical_download_manager.panel.queue_status_dummy",
        )
        self._queue_progress.setRange(0, 100)
        self._queue_progress.setValue(0)
        apply_trace(
            self._queue_progress,
            "historical_download_manager.progress.queue_dummy",
            object_type="progress_bar",
            parent_object_id="historical_download_manager.panel.queue_status_dummy",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="historical_download_manager.table.queue_dummy",
            columns=_QUEUE_COLUMNS,
            labels=("Queue", "Scope", "Progress", "State"),
            parent_object_id="historical_download_manager.panel.queue_status_dummy",
        )
        self._tables["historical_download_manager.table.queue_dummy"] = table
        layout.addWidget(self._queue_progress)
        layout.addWidget(table)
        return panel

    def _add_field(self, form: QFormLayout, field_id: str, label: str, widget: QWidget) -> None:
        label_widget = QLabel(label, self)
        label_widget.setObjectName(f"historical_download_manager.label.{field_id}")
        label_widget.setProperty("object_id", label_widget.objectName())
        label_widget.setProperty("object_type", "label")
        widget.setObjectName(f"historical_download_manager.{field_id}")
        widget.setProperty("object_id", widget.objectName())
        widget.setProperty("object_type", widget.__class__.__name__)
        widget.setProperty("parent_object_id", "historical_download_manager.selection")
        self._field_widgets[field_id] = widget
        form.addRow(label_widget, widget)

    def _add_button(self, button_id: str, label: str, *, enabled: bool) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(f"historical_download_manager.{button_id}")
        button.setProperty("object_id", button.objectName())
        button.setProperty("object_type", "button")
        button.setProperty("action_id", button.objectName())
        button.setEnabled(enabled)
        self._buttons[button_id] = button
        return button

    def _clear_timeframe_widgets(self) -> None:
        while self._timeframe_layout.count():
            item = self._timeframe_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._timeframe_checkboxes.clear()


def _normalize_string_options(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an iterable of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} entries must be non-empty strings")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)
