"""Qt presenter for the historical OHLCV download vertical workflow."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QComboBox, QLineEdit

from leonardo.connection import ConnectionApplicationService
from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.data import canonicalize_market_id, normalize_symbol
from leonardo.gui.windows.historical_download_manager_window import HistoricalDownloadManagerWindow
from leonardo.gui.windows.ohlcv_download_preflight_window import (
    OhlcvDownloadPlanRow,
    OhlcvDownloadPreflightWindow,
)
from leonardo.gui.windows.ohlcv_download_task_window import OhlcvDownloadTaskWindow
from leonardo.ohlcv import (
    DownloadBatchRequest,
    DownloadBatchResult,
    DownloadPreflightResult,
    DownloadProgressEvent,
    HistoricalDownloadApplicationService,
    normalize_batch_request,
)

_PROGRESS_THROTTLE_MS = 250
_LIVE_PROGRESS_KINDS = frozenset({"page_persisted", "batch_progress", "page_retrying"})


class _QtCallbackDispatcher(QObject):
    requested = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.requested.connect(self._invoke, Qt.ConnectionType.QueuedConnection)

    def dispatch(self, callback: Callable[[], None]) -> None:
        self.requested.emit(callback)

    @staticmethod
    def _invoke(callback: object) -> None:
        if callable(callback):
            callback()


class HistoricalDownloadPresenter(QObject):
    """Translate GUI intent into Connection/OHLCV application-service calls."""

    def __init__(
        self,
        view: HistoricalDownloadManagerWindow,
        connection_service: ConnectionApplicationService,
        download_service: HistoricalDownloadApplicationService,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._connections = connection_service
        self._downloads = download_service
        self._dispatcher = _QtCallbackDispatcher(self)
        self._preflight_window = OhlcvDownloadPreflightWindow(parent=view)
        self._task_window = OhlcvDownloadTaskWindow(parent=view)
        self._request: DownloadBatchRequest | None = None
        self._preflight: DownloadPreflightResult | None = None
        self._active_preflight_task_id: str | None = None
        self._active_task_id: str | None = None
        self._last_cancel_event: DownloadProgressEvent | None = None
        self._pending_progress: DownloadProgressEvent | None = None
        self._last_progress_render_at = 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.timeout.connect(self._flush_pending_progress)
        self._wire()
        self._initialize_capabilities()

    @property
    def preflight_window(self) -> OhlcvDownloadPreflightWindow:
        return self._preflight_window

    @property
    def task_window(self) -> OhlcvDownloadTaskWindow:
        return self._task_window

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    def _wire(self) -> None:
        exchange = self._combo("exchange")
        market = self._combo("market_type")
        exchange.currentTextChanged.connect(self._refresh_markets)
        market.currentTextChanged.connect(self._refresh_timeframes)
        self._line("symbol").editingFinished.connect(self._normalize_symbol_field)
        self._view.start_requested.connect(self._prepare_preflight)
        self._view.closed.connect(self._on_manager_closed)
        self._preflight_window.start_download_requested.connect(self._start_confirmed_download)
        self._preflight_window.closed.connect(self._cancel_active_preflight)
        self._task_window.button_for_id("stop").clicked.connect(self._cancel_active_download)

    def _initialize_capabilities(self) -> None:
        exchange = self._combo("exchange")
        exchange.blockSignals(True)
        exchange.clear()
        exchange.addItem("")
        exchange.addItems(list(self._connections.provider_names()))
        exchange.setCurrentIndex(0)
        exchange.blockSignals(False)
        self._refresh_markets("")
        self._view.reset_form()
        self._view.set_shell_status("Ready")
        self._view.append_status("Historical Download Manager ready.")

    def _refresh_markets(self, provider_name: str) -> None:
        market = self._combo("market_type")
        current = market.currentText()
        market.blockSignals(True)
        market.clear()
        market.addItem("")
        try:
            values = self._connections.supported_markets(provider_name) if provider_name else ()
        except Exception as error:
            values = ()
            self._view.append_status(f"Provider capability error: {error}")
        market.addItems(list(values))
        index = market.findText(current)
        market.setCurrentIndex(index if index >= 0 else 0)
        market.blockSignals(False)
        self._refresh_timeframes(market.currentText())

    def _refresh_timeframes(self, market_type: str) -> None:
        provider_name = self._combo("exchange").currentText()
        try:
            values = (
                self._connections.supported_timeframes(provider_name, market_type)
                if provider_name and market_type
                else ()
            )
        except Exception as error:
            values = ()
            self._view.append_status(f"Timeframe capability error: {error}")
        self._view.set_available_timeframes(values)

    def _normalize_symbol_field(self) -> None:
        field = self._line("symbol")
        if not field.text().strip():
            return
        try:
            field.setText(normalize_symbol(field.text()))
        except ValueError as error:
            self._view.append_status(str(error))

    def _prepare_preflight(self) -> None:
        try:
            request = self._build_request()
        except (TypeError, ValueError) as error:
            self._view.append_status(f"Request rejected: {error}")
            return
        self._request = request
        self._preflight = None
        self._active_preflight_task_id = None
        self._view.set_start_enabled(False)
        self._view.set_shell_status("Preparing preflight")
        self._view.append_status("Preparing non-mutating OHLCV preflight...")
        self._show_preflight_pending(request)
        try:
            submission = self._downloads.submit_preflight(
                request,
                progress_callback=self._on_preflight_progress,
                result_callback=self._on_preflight_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
            self._active_preflight_task_id = submission.task_id
        except Exception as error:
            self._view.set_start_enabled(True)
            self._view.set_shell_status("Ready")
            self._preflight_window.set_status("Submission failed")
            self._preflight_window.set_warnings(str(error))
            self._view.append_status(f"Preflight submission failed: {error}")

    def _show_preflight_pending(self, request: DownloadBatchRequest) -> None:
        self._preflight_window.clear_preflight()
        self._preflight_window.set_request_summary(
            (
                ("Exchange", request.exchange, "selected"),
                ("Market Type", request.market_type, "selected"),
                ("Symbol", request.symbol, "selected"),
                ("Timeframes", ", ".join(request.timeframes), "selected"),
                (
                    "Start ms",
                    _display(request.start_ms),
                    "custom" if request.start_ms is not None else "automatic",
                ),
                (
                    "End ms",
                    _display(request.end_ms),
                    "custom" if request.end_ms is not None else "automatic",
                ),
                (
                    "Page limit",
                    _display(request.limit),
                    "provider default" if request.limit in (None, 0) else "requested",
                ),
            )
        )
        self._preflight_window.set_start_enabled(False)
        self._preflight_window.set_status("Preparing provider and local-data checks")
        if request.start_ms is None and request.end_ms is None:
            self._preflight_window.set_warnings(
                "Full-history preflight must discover the exchange's oldest available candle. "
                "This can take several API probes before the work plan becomes ready."
            )
        self._preflight_window.show()
        self._preflight_window.raise_()
        self._preflight_window.activateWindow()

    def _on_preflight_progress(self, progress: TaskProgress) -> None:
        if progress.task_id != self._active_preflight_task_id:
            return
        self._preflight_window.set_status(progress.message)
        self._view.set_shell_status("Preparing preflight")

    def _on_preflight_result(self, result: TaskResult) -> None:
        active_task_id = self._active_preflight_task_id
        if active_task_id is None or result.task_id != active_task_id:
            return
        self._active_preflight_task_id = None
        self._view.set_start_enabled(True)
        self._view.set_shell_status("Ready")
        if result.status != "completed" or not isinstance(result.value, DownloadPreflightResult):
            message = result.error_message or f"preflight ended with status {result.status}"
            self._preflight_window.set_status("Preflight failed")
            self._preflight_window.set_start_enabled(False)
            self._preflight_window.set_warnings(message)
            self._view.append_status(f"Preflight failed: {message}")
            return
        self._preflight = result.value
        self._render_preflight(result.value)
        self._view.append_status("Preflight ready. Review and confirm before execution.")

    def _render_preflight(self, report: DownloadPreflightResult) -> None:
        request = self._request
        assert request is not None
        self._preflight_window.clear_preflight()
        self._preflight_window.set_request_summary(
            (
                ("Exchange", report.exchange, "ready"),
                ("Market Type", report.market_type, "ready"),
                ("Symbol", report.symbol, "ready"),
                ("Timeframes", ", ".join(report.timeframes), "ready"),
                ("Start ms", _display(request.start_ms), "custom" if request.start_ms is not None else "automatic"),
                ("End ms", _display(request.end_ms), "custom" if request.end_ms is not None else "automatic"),
                ("Page limit", _display(request.limit), "provider default" if request.limit in (None, 0) else "requested"),
            )
        )
        rows = []
        warnings: list[str] = []
        total_expected_bars = 0
        determinate_bars = True
        total_expected_pages = 0
        determinate_pages = True
        checks = []
        for item in report.items:
            local_range = _range_text(item.local_first_ts_ms, item.local_last_ts_ms)
            planned_range = _range_text(item.planned_start_ms, item.planned_end_ms)
            status = "Blocked" if not item.can_download else ("Up to date" if item.up_to_date else "Ready")
            rows.append(
                OhlcvDownloadPlanRow(
                    timeframe=item.market_id.timeframe,
                    local_file_exists=item.local_csv_exists,
                    update_existing=item.mode == "update_latest",
                    local_rows=item.local_row_count,
                    local_range=local_range,
                    planned_range=planned_range,
                    expected_bars=_display(item.expected_bars),
                    pages=_display(item.expected_pages),
                    page_limit=item.page_limit,
                    status=status,
                )
            )
            checks.append(
                (
                    item.market_id.timeframe,
                    "ready" if item.can_download else "blocked",
                    item.reason or (", ".join(item.local_state_issues) or "No blockers"),
                )
            )
            if item.local_state_issues:
                warnings.append(
                    f"{item.market_id.timeframe}: local state: {', '.join(item.local_state_issues)}"
                )
            if item.reason and item.reason != "up_to_date":
                warnings.append(f"{item.market_id.timeframe}: {item.reason}")
            if item.expected_bars is None:
                determinate_bars = False
            else:
                total_expected_bars += item.expected_bars
            if item.expected_pages is None:
                determinate_pages = False
            else:
                total_expected_pages += item.expected_pages
        self._preflight_window.set_work_plan(rows)
        self._preflight_window.set_validation_checklist(checks)
        self._preflight_window.set_workload_estimate(
            (
                ("Timeframes", len(report.items), "Sequential execution"),
                ("Expected bars", total_expected_bars if determinate_bars else "Indeterminate", "Month ranges remain variable" if not determinate_bars else "Fixed-duration estimate"),
                ("Expected pages", total_expected_pages if determinate_pages else "Indeterminate", "Provider page limits applied"),
            )
        )
        self._preflight_window.set_warnings("\n".join(warnings))
        self._preflight_window.set_start_enabled(report.can_download)
        self._preflight_window.set_status("Ready for confirmation" if report.can_download else "Blocked")

    def _start_confirmed_download(self) -> None:
        if self._request is None or self._preflight is None or not self._preflight.can_download:
            self._view.append_status("Download cannot start without a successful preflight.")
            return
        self._preflight_window.hide()
        self._last_cancel_event = None
        self._pending_progress = None
        self._task_window.clear_task_state()
        self._task_window.set_job_summary(
            exchange=self._request.exchange,
            market_type=self._request.market_type,
            symbol=self._request.symbol,
            timeframes=self._request.timeframes,
        )
        self._task_window.set_overall_progress_visible(len(self._request.timeframes) > 1)
        self._task_window.set_status("Submitting download")
        self._task_window.set_running(True)
        self._task_window.show()
        self._task_window.raise_()
        self._task_window.activateWindow()
        try:
            submission = self._downloads.submit_download(
                self._request,
                progress_callback=self._on_task_progress,
                result_callback=self._on_download_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception as error:
            self._task_window.set_running(False)
            self._task_window.set_status("Submission failed")
            self._task_window.set_final_recap(f"Download submission failed: {error}")
            return
        self._active_task_id = submission.task_id
        self._task_window.set_status("Running")
        self._view.append_status(f"Download task submitted: {submission.task_id}")

    def _cancel_active_preflight(self) -> None:
        task_id = self._active_preflight_task_id
        self._active_preflight_task_id = None
        self._request = None
        self._preflight = None
        self._view.set_start_enabled(True)
        self._view.set_shell_status("Ready")
        if task_id is None:
            return
        try:
            self._downloads.cancel(task_id)
        except Exception as error:
            self._view.append_status(f"Preflight cancellation failed: {error}")
            return
        self._view.append_status("Preflight cancelled before download submission.")

    def _on_manager_closed(self) -> None:
        self._cancel_active_preflight()
        self._preflight_window.hide()
        self._request = None
        self._preflight = None

    def _cancel_active_download(self) -> None:
        task_id = self._active_task_id
        if task_id is None:
            return
        self._task_window.button_for_id("stop").setEnabled(False)
        self._task_window.set_status("Cancellation requested")
        try:
            cancelled = self._downloads.cancel(task_id)
        except Exception as error:
            self._task_window.append_log_message(f"Cancellation request failed: {error}")
            self._task_window.button_for_id("stop").setEnabled(True)
            return
        if not cancelled:
            self._task_window.append_log_message("Task was already settled before cancellation.")

    def _on_task_progress(self, progress: TaskProgress) -> None:
        event = (progress.details or {}).get("download_event")
        if not isinstance(event, DownloadProgressEvent):
            self._task_window.append_log_message(progress.message)
            return
        if event.kind == "item_cancelled":
            self._last_cancel_event = event
        if event.kind in _LIVE_PROGRESS_KINDS:
            elapsed_ms = (time.monotonic() - self._last_progress_render_at) * 1000.0
            if self._last_progress_render_at and elapsed_ms < _PROGRESS_THROTTLE_MS:
                self._pending_progress = event
                if not self._progress_timer.isActive():
                    self._progress_timer.start(max(1, int(_PROGRESS_THROTTLE_MS - elapsed_ms)))
                return
        self._flush_pending_progress()
        self._render_progress(event)

    def _flush_pending_progress(self) -> None:
        event = self._pending_progress
        self._pending_progress = None
        if event is not None:
            self._render_progress(event)

    def _render_progress(self, event: DownloadProgressEvent) -> None:
        self._last_progress_render_at = time.monotonic()
        self._task_window.append_log_message(event.message)
        if event.total is not None and event.total > 0 and event.current is not None:
            self._task_window.set_current_timeframe_progress(
                int(min(100, max(0, (event.current / event.total) * 100)))
            )
        elif event.kind == "item_completed":
            self._task_window.set_current_timeframe_progress(100)
        if event.overall_total is not None and event.overall_total > 0 and event.overall_current is not None:
            self._task_window.set_overall_progress(
                int(min(100, max(0, (event.overall_current / event.overall_total) * 100)))
            )
        if event.kind == "item_started":
            self._task_window.set_current_timeframe_progress(0)
            self._task_window.set_status(f"Running {event.timeframe}")
        elif event.kind == "page_retrying":
            self._task_window.set_status(f"Retrying {event.timeframe}")
        elif event.kind == "preliminary_validation_completed":
            self._task_window.set_status(f"Preliminary validation: {event.details.get('status')}")

    def _on_download_result(self, result: TaskResult) -> None:
        self._flush_pending_progress()
        self._active_task_id = None
        self._task_window.set_running(False)
        if result.status == "completed" and isinstance(result.value, DownloadBatchResult):
            self._task_window.set_status("Completed")
            self._task_window.set_overall_progress(100)
            self._task_window.set_current_timeframe_progress(100)
            self._task_window.set_final_recap(_success_recap(result.value))
            self._view.append_status("Historical OHLCV download completed.")
            return
        if result.status == "cancelled":
            self._task_window.set_status("Cancelled")
            self._task_window.set_final_recap(_cancel_recap(self._last_cancel_event))
            self._view.append_status("Historical OHLCV download cancelled.")
            return
        self._task_window.set_status("Failed")
        self._task_window.set_final_recap(
            f"Download failed: {result.error_type or 'Error'}: {result.error_message or 'unknown failure'}"
        )
        self._view.append_status(f"Historical OHLCV download failed: {result.error_message}")

    def _build_request(self) -> DownloadBatchRequest:
        exchange = self._combo("exchange").currentText()
        market_type = self._combo("market_type").currentText()
        symbol = self._line("symbol").text()
        timeframes = self._view.selected_timeframes()
        start_ms = _optional_non_negative_int(self._line("start_ms").text(), "start_ms")
        end_ms = _optional_non_negative_int(self._line("end_ms").text(), "end_ms")
        limit = _optional_non_negative_int(self._line("limit").text(), "limit")
        request = normalize_batch_request(
            DownloadBatchRequest(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframes=timeframes,
                start_ms=start_ms,
                end_ms=end_ms,
                limit=limit,
            )
        )
        canonical = canonicalize_market_id(
            request.exchange,
            request.market_type,
            request.symbol,
            request.timeframes[0],
        )
        self._line("symbol").setText(canonical.symbol)
        return request

    def _combo(self, field_id: str) -> QComboBox:
        widget = self._view.field_widget_for_id(field_id)
        if not isinstance(widget, QComboBox):
            raise TypeError(f"{field_id} must be a QComboBox")
        return widget

    def _line(self, field_id: str) -> QLineEdit:
        widget = self._view.field_widget_for_id(field_id)
        if not isinstance(widget, QLineEdit):
            raise TypeError(f"{field_id} must be a QLineEdit")
        return widget


def _optional_non_negative_int(text: str, field_name: str) -> int | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an integer") from error
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _display(value: object) -> str:
    return "Automatic" if value is None else str(value)


def _range_text(first: int | None, last: int | None) -> str:
    if first is None and last is None:
        return "None"
    return f"{_display(first)} → {_display(last)}"


def _success_recap(result: DownloadBatchResult) -> str:
    lines = ["Status: Completed", ""]
    for item in result.results:
        lines.extend(
            (
                f"{item.market_id.timeframe}:",
                f"  Path: {item.file_path}",
                f"  Total rows: {item.total_rows}",
                f"  Downloaded rows: {item.fetched_rows}",
                f"  Downloaded range: {_range_text(item.downloaded_first_ts_ms, item.downloaded_last_ts_ms)}",
                f"  Preliminary validation: {item.preliminary_validation_status}",
                "  Canonical validation: unknown",
                "  OHLCV Maintenance acceptance is required before trusted use.",
                "",
            )
        )
    return "\n".join(lines).rstrip()


def _cancel_recap(event: DownloadProgressEvent | None) -> str:
    if event is None:
        return "Status: Cancelled\nNo persistence details were reported."
    details = event.details
    if details.get("download_complete") and details.get("persistence_status") == "committed":
        return (
            "Status: Cancelled after the OHLCV dataset was committed\n"
            "The task was cancelled before its normal completion result was delivered.\n"
            "Canonical validation remains unknown.\n"
            "OHLCV Maintenance acceptance is required."
        )
    if not details.get("pages_written"):
        return (
            "Status: Cancelled\n"
            "Cancelled before any new OHLCV page was persisted.\n"
            "Canonical validation remains unknown."
        )
    return "\n".join(
        (
            "Status: Cancelled after partial OHLCV persistence",
            f"Pages written: {details.get('pages_written')}",
            f"Rows written: {details.get('rows_written')}",
            f"Persisted total rows: {details.get('persisted_total_rows')}",
            f"Persisted range: {_range_text(details.get('persisted_first_ts_ms'), details.get('persisted_last_ts_ms'))}",
            f"Persisted downloaded range: {_range_text(details.get('persisted_downloaded_first_ts_ms'), details.get('persisted_downloaded_last_ts_ms'))}",
            "Canonical validation remains unknown.",
            "OHLCV Maintenance acceptance is required.",
        )
    )
