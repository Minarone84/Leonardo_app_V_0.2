"""GUI-only Historical Download Manager shell."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID = "historical_download_manager.window"


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
        self._timeframe_checkboxes: dict[str, QCheckBox] = {}
        self._timeframe_layout = QVBoxLayout()
        self._status_log = QTextEdit(self)

        self.setObjectName("historical_download_manager_window")
        self.setWindowTitle("Historical Download Manager")
        self.resize(720, 640)
        self._build_layout()

    def set_available_timeframes(self, timeframes: Iterable[str]) -> None:
        """Replace displayed timeframe checkboxes with externally supplied values."""

        normalized = _normalize_string_options(timeframes, "timeframes")
        self._clear_timeframe_widgets()
        for timeframe in normalized:
            checkbox = QCheckBox(timeframe, self)
            checkbox.setObjectName(f"historical_download_manager.timeframe.{timeframe}")
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

    def timeframe_checkbox_for_value(self, timeframe: str) -> QCheckBox:
        """Return the checkbox for a displayed timeframe value."""

        try:
            return self._timeframe_checkboxes[timeframe]
        except KeyError as error:
            raise KeyError(f"Unknown Historical Download Manager timeframe: {timeframe}") from error

    def status_log(self) -> QTextEdit:
        """Return the read-only status/log surface."""

        return self._status_log

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("Historical Download Manager", self)
        title.setObjectName("historical_download_manager.title")
        layout.addWidget(title)

        form = QFormLayout()
        self._add_field(form, "exchange", "Exchange", QComboBox(self))
        self._add_field(form, "market_type", "Market Type", QComboBox(self))
        self._add_field(form, "symbol", "Symbol", QLineEdit(self))
        self._add_field(form, "start_ms", "Start ms", QLineEdit(self))
        self._add_field(form, "end_ms", "End ms", QLineEdit(self))
        limit = QLineEdit(self)
        limit.setText("200")
        self._add_field(form, "limit", "Limit", limit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Timeframes", self))
        timeframe_container = QWidget(self)
        timeframe_container.setObjectName("historical_download_manager.timeframes")
        timeframe_container.setLayout(self._timeframe_layout)
        layout.addWidget(timeframe_container)

        timeframe_buttons = QHBoxLayout()
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
        layout.addLayout(timeframe_buttons)

        action_buttons = QHBoxLayout()
        start = self._add_button("start", "Start", enabled=True)
        stop = self._add_button("stop", "Stop", enabled=False)
        maintenance = self._add_button("ohlcv_maintenance", "OHLCV Maintenance", enabled=True)
        start.clicked.connect(self.start_requested.emit)
        maintenance.clicked.connect(self.maintenance_requested.emit)
        action_buttons.addWidget(start)
        action_buttons.addWidget(stop)
        action_buttons.addWidget(maintenance)
        layout.addLayout(action_buttons)

        self._status_log.setObjectName("historical_download_manager.status_log")
        self._status_log.setReadOnly(True)
        self._status_log.setPlaceholderText("Status and log output")
        layout.addWidget(self._status_log)

    def _add_field(self, form: QFormLayout, field_id: str, label: str, widget: QWidget) -> None:
        widget.setObjectName(f"historical_download_manager.{field_id}")
        self._field_widgets[field_id] = widget
        form.addRow(label, widget)

    def _add_button(self, button_id: str, label: str, *, enabled: bool) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(f"historical_download_manager.{button_id}")
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
