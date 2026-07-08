"""GUI-only OHLCV Download Task shell."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


OHLCV_DOWNLOAD_TASK_METADATA_ID = "ohlcv_download_task.window"


class OhlcvDownloadTaskWindow(QDialog):
    """
    Standalone GUI shell for displaying OHLCV download task progress.

    The shell displays externally supplied progress and recap text. It does not
    own cancellation, backend execution, provider calls, or storage writes.
    """

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._summary_labels: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._overall_progress = QProgressBar(self)
        self._current_timeframe_progress = QProgressBar(self)
        self._progress_log = QTextEdit(self)
        self._final_recap = QTextEdit(self)

        self.setObjectName("ohlcv_download_task_window")
        self.setProperty("object_id", OHLCV_DOWNLOAD_TASK_METADATA_ID)
        self.setWindowTitle("OHLCV Download Task")
        self.resize(760, 560)
        self._build_layout()

    def set_job_summary(
        self,
        *,
        exchange: str = "",
        market_type: str = "",
        symbol: str = "",
        timeframes: Iterable[str] = (),
    ) -> None:
        """Set display-only job summary fields."""

        self._summary_labels["exchange"].setText(exchange)
        self._summary_labels["market_type"].setText(market_type)
        self._summary_labels["symbol"].setText(symbol)
        self._summary_labels["timeframes"].setText(", ".join(tuple(timeframes)))

    def set_overall_progress(self, value: int) -> None:
        """Set the overall progress value."""

        self._overall_progress.setValue(_bounded_progress(value))

    def set_current_timeframe_progress(self, value: int) -> None:
        """Set the current timeframe progress value."""

        self._current_timeframe_progress.setValue(_bounded_progress(value))

    def append_log_message(self, message: str) -> None:
        """Append a local progress log line."""

        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._progress_log.append(message)

    def set_final_recap(self, text: str) -> None:
        """Set the display-only final recap text."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        self._final_recap.setPlainText(text)

    def overall_progress_bar(self) -> QProgressBar:
        """Return the overall progress bar."""

        return self._overall_progress

    def current_timeframe_progress_bar(self) -> QProgressBar:
        """Return the current timeframe progress bar."""

        return self._current_timeframe_progress

    def progress_log(self) -> QTextEdit:
        """Return the read-only progress log surface."""

        return self._progress_log

    def final_recap(self) -> QTextEdit:
        """Return the read-only final recap surface."""

        return self._final_recap

    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown OHLCV Download Task button: {button_id}") from error

    def summary_text_for_id(self, summary_id: str) -> str:
        """Return a summary label value by identifier."""

        try:
            return self._summary_labels[summary_id].text()
        except KeyError as error:
            raise KeyError(f"Unknown OHLCV Download Task summary: {summary_id}") from error

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setObjectName("ohlcv_download_task.layout.root")
        header = QLabel("OHLCV Download Task", self)
        header.setObjectName("ohlcv_download_task.header")
        header.setProperty("object_id", "ohlcv_download_task.header")
        header.setProperty("object_type", "label")
        layout.addWidget(header)

        summary = QFormLayout()
        summary.setObjectName("ohlcv_download_task.layout.summary")
        for summary_id, label in (
            ("exchange", "Exchange"),
            ("market_type", "Market Type"),
            ("symbol", "Symbol"),
            ("timeframes", "Timeframes"),
        ):
            label_widget = QLabel(label, self)
            label_widget.setObjectName(f"ohlcv_download_task.label.{summary_id}")
            label_widget.setProperty("object_id", label_widget.objectName())
            label_widget.setProperty("object_type", "label")
            value = QLabel("", self)
            value.setObjectName(f"ohlcv_download_task.{summary_id}")
            value.setProperty("object_id", value.objectName())
            value.setProperty("object_type", "status_label")
            self._summary_labels[summary_id] = value
            summary.addRow(label_widget, value)
        layout.addLayout(summary)

        self._overall_progress.setObjectName("ohlcv_download_task.overall_progress")
        self._overall_progress.setProperty("object_id", "ohlcv_download_task.overall_progress")
        self._overall_progress.setProperty("object_type", "progress_bar")
        self._overall_progress.setRange(0, 100)
        self._current_timeframe_progress.setObjectName(
            "ohlcv_download_task.current_timeframe_progress"
        )
        self._current_timeframe_progress.setProperty(
            "object_id", "ohlcv_download_task.current_timeframe_progress"
        )
        self._current_timeframe_progress.setProperty("object_type", "progress_bar")
        self._current_timeframe_progress.setRange(0, 100)
        overall_label = QLabel("Overall Progress", self)
        overall_label.setObjectName("ohlcv_download_task.label.overall_progress")
        overall_label.setProperty("object_id", "ohlcv_download_task.label.overall_progress")
        layout.addWidget(overall_label)
        layout.addWidget(self._overall_progress)
        current_label = QLabel("Current Timeframe Progress", self)
        current_label.setObjectName("ohlcv_download_task.label.current_timeframe_progress")
        current_label.setProperty("object_id", "ohlcv_download_task.label.current_timeframe_progress")
        layout.addWidget(current_label)
        layout.addWidget(self._current_timeframe_progress)

        self._progress_log.setObjectName("ohlcv_download_task.progress_log")
        self._progress_log.setProperty("object_id", "ohlcv_download_task.progress_log")
        self._progress_log.setProperty("object_type", "text_area")
        self._progress_log.setReadOnly(True)
        log_label = QLabel("Progress Log", self)
        log_label.setObjectName("ohlcv_download_task.label.progress_log")
        log_label.setProperty("object_id", "ohlcv_download_task.label.progress_log")
        layout.addWidget(log_label)
        layout.addWidget(self._progress_log)

        self._final_recap.setObjectName("ohlcv_download_task.final_recap")
        self._final_recap.setProperty("object_id", "ohlcv_download_task.final_recap")
        self._final_recap.setProperty("object_type", "text_area")
        self._final_recap.setReadOnly(True)
        recap_label = QLabel("Final Recap", self)
        recap_label.setObjectName("ohlcv_download_task.label.final_recap")
        recap_label.setProperty("object_id", "ohlcv_download_task.label.final_recap")
        layout.addWidget(recap_label)
        layout.addWidget(self._final_recap)

        buttons = QHBoxLayout()
        buttons.setObjectName("ohlcv_download_task.layout.actions")
        buttons.addStretch(1)
        stop = self._add_button("stop", "Stop", enabled=False)
        ok = self._add_button("ok", "OK", enabled=True)
        ok.clicked.connect(self.close)
        buttons.addWidget(stop)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _add_button(self, button_id: str, label: str, *, enabled: bool) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(f"ohlcv_download_task.{button_id}")
        button.setProperty("object_id", button.objectName())
        button.setProperty("object_type", "button")
        button.setProperty("action_id", button.objectName())
        button.setEnabled(enabled)
        self._buttons[button_id] = button
        return button


def _bounded_progress(value: int) -> int:
    if type(value) is not int:
        raise TypeError("progress value must be an integer")
    return max(0, min(100, value))
