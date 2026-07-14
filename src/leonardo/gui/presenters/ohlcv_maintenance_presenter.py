"""Presenter for canonical OHLCV Maintenance validation and explicit repair."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.windows.ohlcv_maintenance_window import (
    MaintenanceDatasetRow,
    MaintenanceIssueRow,
    MaintenanceRepairRangeRow,
    OhlcvMaintenanceWindow,
)
from leonardo.ohlcv import (
    MaintenanceDatasetSummary,
    MaintenanceDeletionPlan,
    MaintenanceDeletionResult,
    MaintenanceDiscoveryReport,
    MaintenanceRepairPlan,
    MaintenanceRepairResult,
    MaintenanceValidationResult,
    OHLCVMaintenanceApplicationService,
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
        self._repair_plan: MaintenanceRepairPlan | None = None
        self._active_task_id: str | None = None
        self._active_operation: str | None = None
        self._wire()
        self.refresh()

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    @property
    def repair_plan(self) -> MaintenanceRepairPlan | None:
        return self._repair_plan

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
            self._clear_repair_plan()
            self._view.set_discovery_notes(f"Discovery failed: {type(error).__name__}: {error}")
            self._view.set_status("Discovery failed")
            self._set_selection_actions(False)
            return
        self._render_discovery(report, selected_key=selected_key)

    def _wire(self) -> None:
        self._view.refresh_requested.connect(self.refresh)
        self._view.validate_requested.connect(self._submit_validation)
        self._view.plan_repair_requested.connect(self._submit_repair_plan)
        self._view.execute_repair_requested.connect(self._execute_repair)
        self._view.delete_requested.connect(self._submit_deletion_plan)
        self._view.cancel_requested.connect(self._cancel_operation)
        self._view.selection_changed.connect(self._on_selection_changed)
        self._view.closed.connect(self._cancel_operation)

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
                    f"{item.code}: {item.dataset_dir} — {item.reason}" for item in report.rejected
                )
            )
        else:
            self._view.set_discovery_notes("")
        selected_index = _index_for_market_key(report.datasets, selected_key)
        if selected_index is not None:
            self._view.select_dataset_index(selected_index)
        if not report.datasets:
            self._view.set_status("No persisted OHLCV datasets found")
            self._view.set_evidence_rows(())
            self._set_selection_actions(False)
            return
        self._view.set_status(f"Ready — {len(report.datasets)} dataset(s)")
        self._render_selection(self._view.selected_dataset_index(), invalidate_plan=False)

    def _on_selection_changed(self, index: int) -> None:
        self._render_selection(None if index < 0 else index, invalidate_plan=True)

    def _render_selection(self, index: int | None, *, invalidate_plan: bool) -> None:
        if invalidate_plan:
            self._clear_repair_plan()
        if index is None or index < 0 or index >= len(self._datasets):
            self._view.set_evidence_rows(())
            self._set_selection_actions(False)
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
        available = self._active_task_id is None
        self._view.set_validate_enabled(available)
        self._view.set_plan_repair_enabled(available)
        self._view.set_delete_enabled(available and summary.csv_exists)
        self._view.set_execute_repair_enabled(
            available
            and self._repair_plan is not None
            and self._repair_plan.actionable
            and self._repair_plan.market_id == summary.market_id
        )

    def _submit_validation(self) -> None:
        summary = self._selected_summary("validation")
        if summary is None or self._active_task_id is not None:
            return
        self._clear_repair_plan()
        self._begin_operation("validation", f"Submitting validation — {summary.market_id.as_key()}")
        try:
            submission = self._maintenance.submit_validation(
                summary.market_id,
                progress_callback=self._on_progress,
                result_callback=self._on_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._submission_failed(error)
            return
        self._active_task_id = submission.task_id

    def _submit_repair_plan(self) -> None:
        summary = self._selected_summary("repair planning")
        if summary is None or self._active_task_id is not None:
            return
        self._clear_repair_plan()
        self._begin_operation("repair_plan", f"Submitting repair plan — {summary.market_id.as_key()}")
        try:
            submission = self._maintenance.submit_repair_plan(
                summary.market_id,
                progress_callback=self._on_progress,
                result_callback=self._on_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._submission_failed(error)
            return
        self._active_task_id = submission.task_id

    def _execute_repair(self) -> None:
        if self._active_task_id is not None:
            return
        summary = self._selected_summary("repair execution")
        plan = self._repair_plan
        if summary is None or plan is None or not plan.actionable:
            self._view.set_status("Prepare an actionable repair plan before execution")
            self._view.set_execute_repair_enabled(False)
            return
        if plan.market_id != summary.market_id:
            self._clear_repair_plan()
            self._view.set_status("Repair plan no longer matches the selected dataset")
            return
        confirmation = (
            f"{plan.market_id.as_key()} — {len(plan.ranges)} reviewed range(s), "
            f"approximately {_estimated_total(plan)} bars"
        )
        if not self._view.confirm_repair(confirmation):
            self._view.set_status("Repair cancelled before execution")
            return
        self._begin_operation("repair", f"Submitting repair — {plan.market_id.as_key()}")
        try:
            submission = self._maintenance.submit_repair(
                plan,
                progress_callback=self._on_progress,
                result_callback=self._on_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._submission_failed(error)
            return
        self._active_task_id = submission.task_id

    def _submit_deletion_plan(self) -> None:
        summary = self._selected_summary("deletion")
        if summary is None or self._active_task_id is not None:
            return
        if not summary.csv_exists:
            self._view.set_status("Deletion requires an existing canonical candles.csv")
            self._view.set_delete_enabled(False)
            return
        self._clear_repair_plan()
        self._begin_operation(
            "deletion_plan",
            f"Preparing controlled deletion — {summary.market_id.as_key()}",
        )
        try:
            submission = self._maintenance.submit_deletion_plan(
                summary.market_id,
                progress_callback=self._on_progress,
                result_callback=self._on_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._submission_failed(error)
            return
        self._active_task_id = submission.task_id

    def _confirm_and_submit_deletion(self, plan: MaintenanceDeletionPlan) -> None:
        sidecar_path = (
            str(plan.evidence.sidecar.path) if plan.evidence.sidecar is not None else None
        )
        confirmed = self._view.confirm_deletion(
            market_key=plan.market_id.as_key(),
            csv_path=str(plan.evidence.csv.path),
            sidecar_path=sidecar_path,
        )
        if not confirmed:
            self._view.set_status("Dataset deletion cancelled before execution")
            self._render_selection(self._view.selected_dataset_index(), invalidate_plan=False)
            return
        self._begin_operation(
            "deletion",
            f"Submitting controlled deletion — {plan.market_id.as_key()}",
        )
        try:
            submission = self._maintenance.submit_deletion(
                plan,
                progress_callback=self._on_progress,
                result_callback=self._on_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._submission_failed(error)
            return
        self._active_task_id = submission.task_id

    def _begin_operation(self, operation: str, status: str) -> None:
        self._active_operation = operation
        self._view.set_running(True)
        self._view.set_cancel_enabled(operation != "deletion")
        self._view.set_progress(0, 1)
        self._view.set_status(status)
        if operation != "repair_plan":
            self._view.set_issue_rows(())

    def _submission_failed(self, error: Exception) -> None:
        operation = self._active_operation or "operation"
        self._active_operation = None
        self._view.set_running(False)
        self._view.set_status(f"{operation} submission failed: {type(error).__name__}: {error}")
        self._render_selection(self._view.selected_dataset_index(), invalidate_plan=False)

    def _on_progress(self, progress: TaskProgress) -> None:
        if progress.task_id != self._active_task_id:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_result(self, task_result: TaskResult) -> None:
        if task_result.task_id != self._active_task_id:
            return
        operation = self._active_operation or "operation"
        selected_key = self._selected_market_key()
        self._active_task_id = None
        self._active_operation = None
        self._view.set_running(False)
        self._view.set_progress(1, 1)
        if task_result.status == "completed":
            if isinstance(task_result.value, MaintenanceDeletionPlan):
                self._confirm_and_submit_deletion(task_result.value)
                return
            if isinstance(task_result.value, MaintenanceDeletionResult):
                result = task_result.value
                self._clear_repair_plan()
                self._view.set_issue_rows(())
                self._view.set_repair_summary("")
                self._view.set_status(_deletion_result_text(result))
                self._refresh_after_result(None)
                return
            if isinstance(task_result.value, MaintenanceValidationResult):
                result = task_result.value
                self._view.set_issue_rows(tuple(_issue_row(item) for item in result.report.issues))
                self._view.set_status(_validation_status_text(result))
                self._refresh_after_result(selected_key)
                return
            if isinstance(task_result.value, MaintenanceRepairPlan):
                self._render_repair_plan(task_result.value)
                self._view.set_status(task_result.value.message)
                self._render_selection(self._view.selected_dataset_index(), invalidate_plan=False)
                return
            if isinstance(task_result.value, MaintenanceRepairResult):
                result = task_result.value
                self._view.set_issue_rows(
                    tuple(_issue_row(item) for item in result.validation.report.issues)
                )
                self._view.set_repair_summary(_repair_result_text(result))
                self._view.set_status(_repair_result_text(result))
                self._clear_repair_plan(keep_summary=True)
                self._refresh_after_result(selected_key)
                return
        if task_result.status == "cancelled":
            self._view.set_status(f"{operation.replace('_', ' ').title()} cancelled")
            self._refresh_after_result(selected_key)
            return
        message = task_result.error_message or f"task ended with status {task_result.status}"
        self._view.set_status(
            f"{operation.replace('_', ' ').title()} failed: "
            f"{task_result.error_type or 'Error'}: {message}"
        )
        self._refresh_after_result(selected_key)

    def _render_repair_plan(self, plan: MaintenanceRepairPlan) -> None:
        self._repair_plan = plan
        self._view.set_issue_rows(
            tuple(_issue_row(item) for item in plan.validation_report.issues)
        )
        self._view.set_repair_rows(tuple(_repair_row(item) for item in plan.ranges))
        summary_parts = [plan.message]
        if plan.warnings:
            summary_parts.append("Warnings: " + " | ".join(plan.warnings))
        self._view.set_repair_summary("\n".join(summary_parts))
        self._view.set_execute_repair_enabled(plan.actionable)

    def _clear_repair_plan(self, *, keep_summary: bool = False) -> None:
        self._repair_plan = None
        self._view.set_repair_rows(())
        if not keep_summary:
            self._view.set_repair_summary("")
        self._view.set_execute_repair_enabled(False)

    def _refresh_after_result(self, selected_key: str | None) -> None:
        try:
            report = self._maintenance.discover()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._view.set_discovery_notes(
                f"Post-operation refresh failed: {type(error).__name__}: {error}"
            )
            self._render_selection(self._view.selected_dataset_index(), invalidate_plan=False)
            return
        current_status = self._view.status_text()
        self._render_discovery(report, selected_key=selected_key)
        self._view.set_status(current_status)

    def _cancel_operation(self) -> None:
        task_id = self._active_task_id
        if task_id is None:
            return
        if self._active_operation == "deletion":
            self._view.set_status("Confirmed deletion cannot be cancelled after execution starts")
            return
        if self._maintenance.cancel(task_id):
            self._view.set_status("Cancellation requested")

    def _selected_summary(self, operation: str) -> MaintenanceDatasetSummary | None:
        index = self._view.selected_dataset_index()
        if index is None or index < 0 or index >= len(self._datasets):
            self._view.set_status(f"Select a dataset before {operation}")
            self._set_selection_actions(False)
            return None
        return self._datasets[index]

    def _selected_market_key(self) -> str | None:
        index = self._view.selected_dataset_index()
        if index is None or index < 0 or index >= len(self._datasets):
            return None
        return self._datasets[index].market_id.as_key()

    def _set_selection_actions(self, enabled: bool) -> None:
        self._view.set_validate_enabled(enabled)
        self._view.set_plan_repair_enabled(enabled)
        self._view.set_delete_enabled(enabled)
        self._view.set_execute_repair_enabled(False)


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


def _repair_row(item: object) -> MaintenanceRepairRangeRow:
    return MaintenanceRepairRangeRow(
        start=str(getattr(item, "start_ts_ms")),
        end=str(getattr(item, "end_ts_ms")),
        bars=_optional_text(getattr(item, "estimated_bars", None)),
        codes=", ".join(getattr(item, "issue_codes")),
        anchors=", ".join(str(value) for value in getattr(item, "coverage_anchor_ts_ms")),
        reason=str(getattr(item, "reason")),
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


def _deletion_result_text(result: MaintenanceDeletionResult) -> str:
    market_key = result.plan.market_id.as_key()
    warnings = result.store_result.cleanup_warnings
    cache_text = "Research cache invalidated" if result.cache_invalidated else "no cached Research copy"
    if warnings:
        return (
            f"Deleted — {market_key}; {cache_text}; cleanup warning: "
            + " | ".join(warnings)
        )
    return f"Deleted — {market_key}; {cache_text}"


def _validation_status_text(result: MaintenanceValidationResult) -> str:
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


def _repair_result_text(result: MaintenanceRepairResult) -> str:
    market_key = result.plan.market_id.as_key()
    if result.outcome == "repaired_ok":
        return f"Repair accepted — {market_key}; Research admission is available"
    if result.outcome == "no_replacement_rows":
        return f"Repair fetched no replacement rows — {market_key}"
    if result.outcome == "coverage_missing_anchor":
        return f"Repair coverage missed required anchors — {market_key}"
    if result.outcome == "publication_failed":
        return f"Repair validation publication failed — {market_key}"
    if result.outcome == "repaired_warning":
        return f"Repair completed with warnings — {market_key}; Research remains blocked"
    return f"Repair completed but validation failed — {market_key}; Research remains blocked"


def _estimated_total(plan: MaintenanceRepairPlan) -> str:
    values = [item.estimated_bars for item in plan.ranges]
    if any(value is None for value in values):
        return "an unknown number of"
    return str(sum(int(value) for value in values if value is not None))
