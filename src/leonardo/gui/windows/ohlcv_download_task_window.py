"""GUI-only OHLCV Download Task shell."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.dummy_data import (
    ohlcv_task_log_messages,
    ohlcv_task_output_rows,
    ohlcv_task_stage_rows,
)
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.traceable_shell_widgets import (
    apply_trace,
    configure_table,
    populate_table,
)


OHLCV_DOWNLOAD_TASK_METADATA_ID = "ohlcv_download_task.window"
_STAGE_COLUMNS = ("stage", "state", "details")
_OUTPUT_COLUMNS = ("item", "value", "state")


class OhlcvDownloadTaskWindow(QDialog):
    """
    Standalone GUI shell for displaying OHLCV download task progress.

    The shell displays local dummy task context plus externally supplied
    progress and recap text. It does not own cancellation, backend execution,
    provider calls, or storage writes.
    """

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._summary_labels: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._overall_progress = QProgressBar(self)
        self._current_timeframe_progress = QProgressBar(self)
        self._progress_log = QTextEdit(self)
        self._final_recap = QTextEdit(self)

        self.setObjectName("ohlcv_download_task_window")
        self.setProperty("object_id", OHLCV_DOWNLOAD_TASK_METADATA_ID)
        self.setWindowTitle("OHLCV Download Task")
        self.resize(960, 760)
        apply_theme_stylesheet(self, load_default_theme())
        self._build_layout()
        self.load_dummy_task_state()

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

    def load_dummy_task_state(self) -> None:
        """Render deterministic local dummy task status."""

        self.set_job_summary(
            exchange="Bybit dummy",
            market_type="linear dummy",
            symbol="BTCUSDT dummy",
            timeframes=("1h", "4h"),
        )
        self.set_overall_progress(0)
        self.set_current_timeframe_progress(0)
        populate_table(
            self._tables["ohlcv_download_task.stage_table"],
            _STAGE_COLUMNS,
            ohlcv_task_stage_rows(),
        )
        populate_table(
            self._tables["ohlcv_download_task.output_summary_table"],
            _OUTPUT_COLUMNS,
            ohlcv_task_output_rows(),
        )
        self._progress_log.setPlainText("\n".join(ohlcv_task_log_messages()))
        self.set_final_recap("DUMMY output disabled; no storage writes.")
        self._set_status("DUMMY task shell loaded: no task manager/provider/storage.")

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

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown OHLCV Download Task table: {table_id}") from error

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

    def status_text(self) -> str:
        """Return the current shell status text."""

        return "" if self._status_label is None else self._status_label.text()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        apply_trace(
            layout,
            "ohlcv_download_task.layout.root",
            object_type="layout",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_summary_panel())
        layout.addWidget(self._build_progress_panel())
        body = QHBoxLayout()
        body.setObjectName("ohlcv_download_task.layout.task_body")
        body.addWidget(
            self._build_table_panel(
                "Dummy Stage List",
                panel_id="ohlcv_download_task.panel.stages",
                table_id="ohlcv_download_task.stage_table",
                columns=_STAGE_COLUMNS,
            )
        )
        body.addWidget(
            self._build_table_panel(
                "Dummy Output Summary",
                panel_id="ohlcv_download_task.panel.output_summary",
                table_id="ohlcv_download_task.output_summary_table",
                columns=_OUTPUT_COLUMNS,
            )
        )
        layout.addLayout(body)
        layout.addWidget(self._build_log_panel())
        layout.addWidget(self._build_recap_panel())
        layout.addWidget(self._build_actions())

    def _build_header(self) -> QWidget:
        panel = QGroupBox("Task Shell", self)
        apply_trace(
            panel,
            "ohlcv_download_task.panel.header",
            object_type="panel",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        layout = QHBoxLayout(panel)
        apply_trace(
            layout,
            "ohlcv_download_task.layout.header",
            object_type="layout",
            parent_object_id="ohlcv_download_task.panel.header",
        )
        header = QLabel("OHLCV Download Task", panel)
        apply_trace(
            header,
            "ohlcv_download_task.header",
            object_type="label",
            parent_object_id="ohlcv_download_task.panel.header",
        )
        status = QLabel("DUMMY shell only", panel)
        apply_trace(
            status,
            "ohlcv_download_task.label.status",
            object_type="status_label",
            parent_object_id="ohlcv_download_task.panel.header",
        )
        self._status_label = status
        layout.addWidget(header)
        layout.addStretch(1)
        layout.addWidget(status)
        return panel

    def _build_summary_panel(self) -> QWidget:
        panel = QGroupBox("Dummy Request Summary", self)
        apply_trace(
            panel,
            "ohlcv_download_task.summary",
            object_type="summary_panel",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        summary = QFormLayout(panel)
        apply_trace(
            summary,
            "ohlcv_download_task.layout.summary",
            object_type="layout",
            parent_object_id="ohlcv_download_task.summary",
        )
        for summary_id, label in (
            ("exchange", "Exchange"),
            ("market_type", "Market Type"),
            ("symbol", "Symbol"),
            ("timeframes", "Timeframes"),
        ):
            label_widget = QLabel(label, panel)
            apply_trace(
                label_widget,
                f"ohlcv_download_task.label.{summary_id}",
                object_type="label",
                parent_object_id="ohlcv_download_task.summary",
            )
            value = QLabel("", panel)
            apply_trace(
                value,
                f"ohlcv_download_task.{summary_id}",
                object_type="status_label",
                parent_object_id="ohlcv_download_task.summary",
            )
            self._summary_labels[summary_id] = value
            summary.addRow(label_widget, value)
        return panel

    def _build_progress_panel(self) -> QWidget:
        panel = QGroupBox("Dummy Progress", self)
        apply_trace(
            panel,
            "ohlcv_download_task.panel.progress",
            object_type="panel",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName("ohlcv_download_task.layout.progress")
        self._configure_progress(
            self._overall_progress,
            object_id="ohlcv_download_task.overall_progress",
            parent_object_id="ohlcv_download_task.panel.progress",
        )
        self._configure_progress(
            self._current_timeframe_progress,
            object_id="ohlcv_download_task.current_timeframe_progress",
            parent_object_id="ohlcv_download_task.panel.progress",
        )
        overall_label = QLabel("Overall Progress", panel)
        apply_trace(
            overall_label,
            "ohlcv_download_task.label.overall_progress",
            object_type="label",
            parent_object_id="ohlcv_download_task.panel.progress",
        )
        current_label = QLabel("Current Timeframe Progress", panel)
        apply_trace(
            current_label,
            "ohlcv_download_task.label.current_timeframe_progress",
            object_type="label",
            parent_object_id="ohlcv_download_task.panel.progress",
        )
        layout.addWidget(overall_label)
        layout.addWidget(self._overall_progress)
        layout.addWidget(current_label)
        layout.addWidget(self._current_timeframe_progress)
        return panel

    def _build_table_panel(
        self,
        title: str,
        *,
        panel_id: str,
        table_id: str,
        columns: Sequence[str],
    ) -> QWidget:
        panel = QGroupBox(title, self)
        apply_trace(
            panel,
            panel_id,
            object_type="panel",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName(f"{panel_id}.layout")
        table = QTableWidget(panel)
        configure_table(
            table,
            object_id=table_id,
            columns=columns,
            parent_object_id=panel_id,
        )
        self._tables[table_id] = table
        layout.addWidget(table)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("Dummy Progress Log", self)
        apply_trace(
            panel,
            "ohlcv_download_task.panel.progress_log",
            object_type="panel",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName("ohlcv_download_task.layout.progress_log")
        self._progress_log.setReadOnly(True)
        apply_trace(
            self._progress_log,
            "ohlcv_download_task.progress_log",
            object_type="text_area",
            parent_object_id="ohlcv_download_task.panel.progress_log",
        )
        log_label = QLabel("Progress Log", panel)
        apply_trace(
            log_label,
            "ohlcv_download_task.label.progress_log",
            object_type="label",
            parent_object_id="ohlcv_download_task.panel.progress_log",
        )
        layout.addWidget(log_label)
        layout.addWidget(self._progress_log)
        return panel

    def _build_recap_panel(self) -> QWidget:
        panel = QGroupBox("Dummy Final Recap", self)
        apply_trace(
            panel,
            "ohlcv_download_task.panel.final_recap",
            object_type="panel",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        layout.setObjectName("ohlcv_download_task.layout.final_recap")
        self._final_recap.setReadOnly(True)
        apply_trace(
            self._final_recap,
            "ohlcv_download_task.final_recap",
            object_type="text_area",
            parent_object_id="ohlcv_download_task.panel.final_recap",
        )
        recap_label = QLabel("Final Recap", panel)
        apply_trace(
            recap_label,
            "ohlcv_download_task.label.final_recap",
            object_type="label",
            parent_object_id="ohlcv_download_task.panel.final_recap",
        )
        layout.addWidget(recap_label)
        layout.addWidget(self._final_recap)
        return panel

    def _build_actions(self) -> QWidget:
        panel = QGroupBox("Shell Actions", self)
        apply_trace(
            panel,
            "ohlcv_download_task.actions",
            object_type="action_container",
            parent_object_id=OHLCV_DOWNLOAD_TASK_METADATA_ID,
        )
        buttons = QHBoxLayout(panel)
        apply_trace(
            buttons,
            "ohlcv_download_task.layout.actions",
            object_type="layout",
            parent_object_id="ohlcv_download_task.actions",
        )
        buttons.addStretch(1)
        stop = self._add_button("stop", "Cancel Dummy", enabled=False)
        ok = self._add_button("ok", "OK", enabled=True)
        ok.clicked.connect(self.close)
        buttons.addWidget(stop)
        buttons.addWidget(ok)
        return panel

    def _configure_progress(
        self,
        progress: QProgressBar,
        *,
        object_id: str,
        parent_object_id: str,
    ) -> None:
        apply_trace(
            progress,
            object_id,
            object_type="progress_bar",
            parent_object_id=parent_object_id,
        )
        progress.setRange(0, 100)

    def _add_button(self, button_id: str, label: str, *, enabled: bool) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(f"ohlcv_download_task.{button_id}")
        apply_trace(
            button,
            button.objectName(),
            object_type="button",
            parent_object_id="ohlcv_download_task.actions",
            action_id=button.objectName(),
            display_label=label,
        )
        button.setEnabled(enabled)
        self._buttons[button_id] = button
        return button

    def _set_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(text)


def _bounded_progress(value: int) -> int:
    if type(value) is not int:
        raise TypeError("progress value must be an integer")
    return max(0, min(100, value))
