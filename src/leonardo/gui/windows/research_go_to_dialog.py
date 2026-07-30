"""UTC Go-to-Date input dialog for one captured Research chart runtime."""

from __future__ import annotations

from datetime import UTC, datetime
import re

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.chart.navigation import parse_go_to_utc_timestamp


_INPUT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
_INPUT_ERROR = "Enter a valid UTC date and time as YYYY-MM-DD HH:mm."


class ResearchGoToDialog(QDialog):
    def __init__(
        self,
        slot_id: int,
        session_id: str,
        market_text: str,
        timeframe: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ValueError("slot_id must be an integer from 1 through 8")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(market_text, str):
            raise TypeError("market_text must be a string")
        self._slot_id = slot_id
        self._session_id = session_id
        self._timeframe = timeframe
        self._timestamp_ms: int | None = None
        self._synchronizing = False
        self.setObjectName("research.go_to_dialog")
        self.setWindowTitle("Go to Date (UTC)")
        chart = QLabel(f"Chart {slot_id} - {market_text}", self)
        chart.setObjectName("research.go_to_dialog.label.chart")
        hint = QLabel("UTC date and time", self)
        hint.setObjectName("research.go_to_dialog.label.hint")
        self._input = QLineEdit(self)
        self._input.setObjectName("research.go_to_dialog.input")
        self._input.setPlaceholderText("YYYY-MM-DD HH:mm")
        self._date = QDateEdit(self)
        self._date.setObjectName("research.go_to_dialog.input.date")
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._time = QTimeEdit(self)
        self._time.setObjectName("research.go_to_dialog.input.time")
        self._time.setDisplayFormat("HH:mm")
        calendar = QLabel("📅", self)
        calendar.setObjectName("research.go_to_dialog.icon.calendar")
        calendar.setAccessibleName("Calendar")
        calendar.setToolTip("Select UTC date")
        clock = QLabel("🕒", self)
        clock.setObjectName("research.go_to_dialog.icon.clock")
        clock.setAccessibleName("Clock")
        clock.setToolTip("Select UTC time")
        date_row = QHBoxLayout()
        date_row.addWidget(calendar)
        date_row.addWidget(self._date, 1)
        time_row = QHBoxLayout()
        time_row.addWidget(clock)
        time_row.addWidget(self._time, 1)
        self._error = QLabel("", self)
        self._error.setObjectName("research.go_to_dialog.label.error")
        go = QPushButton("Go", self)
        go.setObjectName("research.go_to_dialog.button.go")
        go.clicked.connect(self._accept_input)
        cancel = QPushButton("Cancel", self)
        cancel.setObjectName("research.go_to_dialog.button.cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(go)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(chart)
        layout.addWidget(hint)
        layout.addWidget(self._input)
        layout.addLayout(date_row)
        layout.addLayout(time_row)
        layout.addWidget(self._error)
        layout.addLayout(buttons)
        self._date.dateChanged.connect(self._sync_text_from_structured)
        self._time.timeChanged.connect(self._sync_text_from_structured)
        self._input.editingFinished.connect(self._sync_structured_from_text)
        self.prepare_for_open()

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def timestamp_ms(self) -> int | None:
        return self._timestamp_ms

    def prepare_for_open(self) -> None:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        self._set_inputs(now)
        self._error.clear()
        self._timestamp_ms = None

    def _accept_input(self) -> None:
        timestamp_ms = self._parse_input()
        if timestamp_ms is None:
            return
        selected = datetime.fromtimestamp(timestamp_ms / 1_000, UTC)
        self._set_inputs(selected)
        self._timestamp_ms = timestamp_ms
        self._error.clear()
        self.accept()

    def _sync_text_from_structured(self) -> None:
        if self._synchronizing:
            return
        date = self._date.date()
        time = self._time.time()
        self._synchronizing = True
        try:
            self._input.setText(
                f"{date.toString('yyyy-MM-dd')} {time.toString('HH:mm')}"
            )
        finally:
            self._synchronizing = False
        self._error.clear()

    def _sync_structured_from_text(self) -> None:
        if self._synchronizing:
            return
        timestamp_ms = self._parse_input()
        if timestamp_ms is None:
            return
        self._set_inputs(datetime.fromtimestamp(timestamp_ms / 1_000, UTC))
        self._error.clear()

    def _parse_input(self) -> int | None:
        text = self._input.text()
        if _INPUT_PATTERN.fullmatch(text) is None:
            self._error.setText(_INPUT_ERROR)
            return None
        try:
            return parse_go_to_utc_timestamp(text, self._timeframe)
        except (TypeError, ValueError):
            self._error.setText(_INPUT_ERROR)
            return None

    def _set_inputs(self, selected: datetime) -> None:
        self._synchronizing = True
        try:
            self._date.setDate(
                QDate(selected.year, selected.month, selected.day)
            )
            self._time.setTime(QTime(selected.hour, selected.minute, 0, 0))
            self._input.setText(selected.strftime("%Y-%m-%d %H:%M"))
        finally:
            self._synchronizing = False
