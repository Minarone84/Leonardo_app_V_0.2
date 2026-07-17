"""UTC Go-to-Date input dialog for one captured Research chart runtime."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.chart.navigation import (
    go_to_input_format_hint,
    parse_go_to_utc_timestamp,
)


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
        self.setObjectName("research.go_to_dialog")
        self.setWindowTitle("Go to Date (UTC)")
        chart = QLabel(f"Chart {slot_id} - {market_text}", self)
        chart.setObjectName("research.go_to_dialog.label.chart")
        hint = QLabel(f"UTC: {go_to_input_format_hint(timeframe)}", self)
        hint.setObjectName("research.go_to_dialog.label.hint")
        self._input = QLineEdit(self)
        self._input.setObjectName("research.go_to_dialog.input")
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
        layout.addWidget(self._error)
        layout.addLayout(buttons)

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def timestamp_ms(self) -> int | None:
        return self._timestamp_ms

    def _accept_input(self) -> None:
        try:
            timestamp_ms = parse_go_to_utc_timestamp(
                self._input.text(), self._timeframe
            )
        except (TypeError, ValueError) as error:
            self._error.setText(str(error))
            return
        self._timestamp_ms = timestamp_ms
        self._error.clear()
        self.accept()
