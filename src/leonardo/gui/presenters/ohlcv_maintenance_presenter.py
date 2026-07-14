"""Presenter for the canonical OHLCV Maintenance GUI workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.ohlcv import (
    MaintenanceDatasetSummary,
    MaintenanceDiscoveryReport,
    MaintenanceValidationResult,
    OHLCVMaintenanceApplicationService,
)
from leonardo.gui.windows.ohlcv_maintenance_window import (
    MaintenanceDatasetRow,
    MaintenanceIssueRow,
    OhlcvMaintenanceWindow,
)


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


class OhlcvMaintenancePresenter(QObject):
    """Translate Maintenance GUI intent into canonical application calls."""

    def __init__(
        self,
        view: OhlcvMaintenanceWindow,
        maintenance_service: OHLCVMaintenanceApplicationService,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._maintenance = maintenance_service
        self._dispatcher = _QtCallbackDispatcher(self)
        self._datasets: tuple[MaintenanceDatasetSummary, ...] = ()
        self._active_task_id: str | None = None
        self._wire()
        self.refresh()

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    def refresh(self) -> None:
        if self._active_task_id is not None:
            return
        selected_key = self._selected_market_key()
        self._view.set_status("Discovering persisted datasets")
        try:
            report = self._maintenance.discover()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._datasets = ()
            self._view.set_dataset_rows(())
            self._view.set_evidence_rows(())
            self._view.set_issue_rows(())
            self._view.set_discovery_notes(f"Discovery failed: {type(error).__name__}: {error}")
            self._view.set_status("Discovery failed")
            self._view.set_validate_enabled(False)
            return
        self._render_discovery(report, selected_key=selected_key)

    def _wire(self) -> None:
        self._view.refresh_requested.connect(self.refresh)
        self._view.validate_requested.connect(self._submit_validation)
        self._view.cancel_requested.connect(self._cancel_validation)
        self._view.selection_changed.connect(self._on_selection_changed)
        self._view.closed.connect(self._cancel_validation)

    def _render_discovery(
        self,
        report: MaintenanceDiscoveryReport,
        *,
        selected_key: str | None,
    ) -> None:
        self._datasets = report.datasets
        self._view.set_dataset_rows(tuple(_dataset_row(item) for item in report.datasets))
        if report.rejected:
            self._view.set_discovery_notes(
                "\n".join(
                    f"{item.code}: {item.dataset_dir} — {item.reason}"
                    for item in report.rejected
                )
            )
        else:
            self._view.set_discovery_notes("")
        selected_index = _index_for_market_key(report.datasets, selected_key)
        if selected_index is not None:
            self._view.select_dataset_index(selected_index)
        if not report.datasets:
            self._view.set_status("No persisted OHLCV datasets found")
            self._view.set_validate_enabled(False)
            self._view.set_evidence_rows(())
            return
        self._view.set_status(f"Ready — {len(report.datasets)} dataset(s)")
        self._render_selection(self._view.selected_dataset_index())

    def _on_selection_changed(self, index: int) -> None:
        self._render_selection(None if index < 0 else index)

    def _render_selection(self, index: int | None) -> None:
        if index is None or index < 0 or index >= len(self._datasets):
            self._view.set_evidence_rows(())
            self._view.set_validate_enabled(False)
            return
        summary = self._datasets[index]
        self._view.set_evidence_rows(
            (
                ("MarketId", summary.market_id.as_key()),
                ("CSV path", summary.csv_path),
                ("Sidecar path", summary.sidecar_path),
                ("CSV exists", summary.csv_exists),
                ("Sidecar exists", summary.sidecar_exists),
                ("Persistence", summary.persistence_status),
                ("Validation", summary.validation_status),
                ("Rows", summary.row_count),
                ("Source", summary.source),
                ("Discovery issues", ", ".join(summary.issues) or "None"),
            )
        )
        self._view.set_validate_enabled(self._active_task_id is None)

    def _submit_validation(self) -> None:
        if self._active_task_id is not None:
            return
        index = self._view.selected_dataset_index()
        if index is None or index < 0 or index >= len(self._datasets):
            self._view.set_status("Select a dataset before validation")
            self._view.set_validate_enabled(False)
            return
        summary = self._datasets[index]
        self._view.set_running(True)
        self._view.set_progress(0, 1)
        self._view.set_issue_rows(())
        self._view.set_status(f"Submitting validation — {summary.market_id.as_key()}")
        try:
            submission = self._maintenance.submit_validation(
                summary.market_id,
                progress_callback=self._on_progress,
                result_callback=self._on_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._view.set_running(False)
            self._view.set_status(f"Submission failed: {type(error).__name__}: {error}")
            self._render_selection(index)
            return
        self._active_task_id = submission.task_id

    def _on_progress(self, progress: TaskProgress) -> None:
        if progress.task_id != self._active_task_id:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_result(self, task_result: TaskResult) -> None:
        if task_result.task_id != self._active_task_id:
            return
        selected_key = self._selected_market_key()
        self._active_task_id = None
        self._view.set_running(False)
        self._view.set_progress(1, 1)
        if task_result.status == "completed" and isinstance(
            task_result.value, MaintenanceValidationResult
        ):
            result = task_result.value
            self._view.set_issue_rows(tuple(_issue_row(item) for item in result.report.issues))
            self._view.set_status(_result_status_text(result))
            self._refresh_after_result(selected_key)
            return
        if task_result.status == "cancelled":
            self._view.set_status("Validation cancelled")
            self._refresh_after_result(selected_key)
            return
        message = task_result.error_message or f"task ended with status {task_result.status}"
        self._view.set_status(
            f"Validation failed: {task_result.error_type or 'Error'}: {message}"
        )
        self._refresh_after_result(selected_key)

    def _refresh_after_result(self, selected_key: str | None) -> None:
        try:
            report = self._maintenance.discover()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._view.set_discovery_notes(
                f"Post-validation refresh failed: {type(error).__name__}: {error}"
            )
            self._view.set_validate_enabled(True)
            return
        current_status = self._view_status_text()
        self._render_discovery(report, selected_key=selected_key)
        self._view.set_status(current_status)

    def _cancel_validation(self) -> None:
        task_id = self._active_task_id
        if task_id is None:
            return
        if self._maintenance.cancel(task_id):
            self._view.set_status("Cancellation requested")

    def _selected_market_key(self) -> str | None:
        index = self._view.selected_dataset_index()
        if index is None or index < 0 or index >= len(self._datasets):
            return None
        return self._datasets[index].market_id.as_key()

    def _view_status_text(self) -> str:
        return self._view.status_text()


def _dataset_row(summary: MaintenanceDatasetSummary) -> MaintenanceDatasetRow:
    return MaintenanceDatasetRow(
        exchange=summary.market_id.exchange,
        market_type=summary.market_id.market_type,
        symbol=summary.market_id.symbol,
        timeframe=summary.market_id.timeframe,
        persistence=summary.persistence_status,
        validation=summary.validation_status,
        rows=summary.row_count,
        source=summary.source,
        issues=", ".join(summary.issues),
    )


def _issue_row(issue: object) -> MaintenanceIssueRow:
    return MaintenanceIssueRow(
        severity=str(getattr(issue, "severity")),
        code=str(getattr(issue, "code")),
        message=str(getattr(issue, "message")),
        row=_optional_text(getattr(issue, "row_number", None)),
        column=_optional_text(getattr(issue, "column", None)),
        timestamp=_optional_text(getattr(issue, "timestamp_ms", None)),
    )


def _optional_text(value: object | None) -> str:
    return "" if value is None else str(value)


def _index_for_market_key(
    datasets: tuple[MaintenanceDatasetSummary, ...],
    market_key: str | None,
) -> int | None:
    if market_key is None:
        return None
    for index, item in enumerate(datasets):
        if item.market_id.as_key() == market_key:
            return index
    return None


def _result_status_text(result: MaintenanceValidationResult) -> str:
    market_key = result.report.market_id.as_key()
    if result.publication_error:
        return f"Publication failed — {market_key}: {result.publication_error}"
    if not result.sidecar_published:
        return f"Validation {result.report.status}; evidence not published — {market_key}"
    if result.accepted:
        changed = "updated" if result.publication_changed else "already current"
        return f"Accepted — {market_key}; evidence {changed}"
    if result.report.status == "warning":
        return f"Warning — {market_key}; Research admission remains blocked"
    return f"Rejected — {market_key}; Research admission remains blocked"
