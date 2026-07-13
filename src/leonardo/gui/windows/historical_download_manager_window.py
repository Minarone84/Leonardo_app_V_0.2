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
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import (
    apply_identity,
    configure_table,
)


HISTORICAL_DOWNLOAD_MANAGER_WINDOW_ID = "historical_download_manager.window"

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

        self.setObjectName("historical_download_manager_window")
        self.setProperty("object_id", HISTORICAL_DOWNLOAD_MANAGER_WINDOW_ID)
        self.setWindowTitle("Historical Download Manager")
        self.resize(980, 760)
        apply_theme_stylesheet(self, load_default_theme())
        self._build_layout()
        self.clear_view()

    def set_available_timeframes(self, timeframes: Iterable[str]) -> None:
        """Replace displayed timeframe checkboxes with externally supplied values."""

        normalized = _normalize_string_options(timeframes, "timeframes")
        previous_selection = set(self.selected_timeframes())
        self._clear_timeframe_widgets()
        for timeframe in normalized:
            checkbox = QCheckBox(timeframe, self)
            checkbox.setObjectName(f"historical_download_manager.timeframe.{timeframe}")
            checkbox.setProperty("object_id", checkbox.objectName())
            checkbox.setProperty("object_type", "checkbox")
            checkbox.setChecked(timeframe in previous_selection)
            self._timeframe_checkboxes[timeframe] = checkbox
            self._timeframe_layout.addWidget(checkbox)
        if normalized and not self.selected_timeframes():
            self._timeframe_checkboxes[normalized[0]].setChecked(True)
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



    def timeframe_checkbox_for_value(self, timeframe: str) -> QCheckBox:
        """Return the checkbox for a displayed timeframe value."""

        try:
            return self._timeframe_checkboxes[timeframe]
        except KeyError as error:
            raise KeyError(f"Unknown Historical Download Manager timeframe: {timeframe}") from error

    def status_log(self) -> QTextEdit:
        """Return the read-only status/log surface."""

        return self._status_log

    def append_status(self, message: str) -> None:
        """Append presenter-supplied status text."""

        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._status_log.append(message)

    def set_start_enabled(self, enabled: bool) -> None:
        self._buttons["start"].setEnabled(bool(enabled))

    def clear_view(self) -> None:
        """Reset the shell to an honest empty state."""

        self._status_log.clear()
        self._status_log.setPlaceholderText(
            "Download status will appear after the workflow is connected."
        )


    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        apply_identity(
            layout,
            "historical_download_manager.layout.root",
            object_type="layout",
        )
        layout.addWidget(self._build_header())

        selection_panel = QGroupBox("Selection", self)
        apply_identity(
            selection_panel,
            "historical_download_manager.selection",
            object_type="panel",
        )
        form = QFormLayout()
        apply_identity(
            form,
            "historical_download_manager.layout.selection_form",
            object_type="layout",
        )
        self._add_field(form, "exchange", "Exchange", QComboBox(self))
        self._add_field(form, "market_type", "Market Type", QComboBox(self))
        self._add_field(form, "symbol", "Symbol", QLineEdit(self))
        self._add_field(form, "start_ms", "Start ms", QLineEdit(self))
        self._add_field(form, "end_ms", "End ms", QLineEdit(self))
        limit = QLineEdit(self)
        limit.setText("0")
        limit.setPlaceholderText("0 = provider default")
        self._add_field(form, "limit", "Limit", limit)
        selection_panel.setLayout(form)
        layout.addWidget(selection_panel)

        timeframe_panel = QGroupBox("Timeframes", self)
        apply_identity(
            timeframe_panel,
            "historical_download_manager.timeframes",
            object_type="checklist",
        )
        timeframe_panel_layout = QVBoxLayout(timeframe_panel)
        apply_identity(
            timeframe_panel_layout,
            "historical_download_manager.layout.timeframe_panel",
            object_type="layout",
        )
        timeframe_container = QWidget(self)
        timeframe_container.setLayout(self._timeframe_layout)
        timeframe_panel_layout.addWidget(timeframe_container)

        timeframe_buttons = QHBoxLayout()
        apply_identity(
            timeframe_buttons,
            "historical_download_manager.layout.timeframe_buttons",
            object_type="layout",
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

        action_buttons = QHBoxLayout()
        apply_identity(
            action_buttons,
            "historical_download_manager.layout.action_buttons",
            object_type="layout",
        )
        start = self._add_button("start", "Start", enabled=True)
        maintenance = self._add_button("ohlcv_maintenance", "OHLCV Maintenance", enabled=True)
        start.clicked.connect(self.start_requested.emit)
        maintenance.clicked.connect(self.maintenance_requested.emit)
        action_buttons.addWidget(start)
        action_buttons.addWidget(maintenance)
        actions_panel = QGroupBox("Actions", self)
        apply_identity(
            actions_panel,
            "historical_download_manager.actions",
            object_type="action_container",
        )
        actions_panel.setLayout(action_buttons)
        layout.addWidget(actions_panel)

        status_panel = QGroupBox("Status Log", self)
        apply_identity(
            status_panel,
            "historical_download_manager.panel.status_log",
            object_type="panel",
        )
        status_layout = QVBoxLayout(status_panel)
        apply_identity(
            status_layout,
            "historical_download_manager.layout.status_log",
            object_type="layout",
        )
        apply_identity(
            self._status_log,
            "historical_download_manager.status_log",
            object_type="text_area",
        )
        self._status_log.setReadOnly(True)
        self._status_log.setPlaceholderText("Status and log output")
        status_layout.addWidget(self._status_log)
        layout.addWidget(status_panel)

    def _build_header(self) -> QWidget:
        header = QGroupBox("Historical Download Manager", self)
        apply_identity(
            header,
            "historical_download_manager.panel.header",
            object_type="panel",
        )
        header_layout = QHBoxLayout(header)
        apply_identity(
            header_layout,
            "historical_download_manager.layout.header",
            object_type="layout",
        )
        title = QLabel("Historical Download Manager", self)
        apply_identity(
            title,
            "historical_download_manager.title",
            object_type="label",
        )
        status = QLabel("Services not connected", self)
        apply_identity(
            status,
            "historical_download_manager.label.shell_status",
            object_type="status_label",
        )
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(status)
        return header




    def _add_field(self, form: QFormLayout, field_id: str, label: str, widget: QWidget) -> None:
        label_widget = QLabel(label, self)
        label_widget.setObjectName(f"historical_download_manager.label.{field_id}")
        label_widget.setProperty("object_id", label_widget.objectName())
        label_widget.setProperty("object_type", "label")
        widget.setObjectName(f"historical_download_manager.{field_id}")
        widget.setProperty("object_id", widget.objectName())
        widget.setProperty("object_type", widget.__class__.__name__)
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
