"""Slot-local presenter for one accepted Research chart workflow."""

from __future__ import annotations

from collections.abc import Callable

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.chart import CandlestickInteractionState, PriceScaleState
from leonardo.gui.widgets.research_chart_slot_widget import ResearchChartSlotWidget
from leonardo.gui.windows.study_style_dialog import StudyStyleDialog, StudyStylePatch
from leonardo.research import (
    ChartSessionState,
    HistoricalDataset,
    HorizontalViewport,
    PreparedStudy,
    ResidentOHLCVSlice,
    ResidentRefillDirection,
    ResidentStudyProjection,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    StudyApplyAttempt,
    StudyArtifactRequest,
    StudyDependencyError,
    StudyExecutionRequest,
    StudySaveAttempt,
    StudySaveOutcome,
    StudyValidationError,
    ViewportSnapshot,
    build_resident_volume_projection,
)


class ResearchChartPresenter:
    """Coordinate exactly one slot's session, tasks, and Task 1018 chart shell."""

    def __init__(
        self,
        slot_id: int,
        view: ResearchChartSlotWidget,
        session: ChartSessionState,
        service: ResearchDatasetApplicationService,
        study_service: ResearchStudyApplicationService,
        callback_dispatcher: Callable[[Callable[[], None]], None],
        state_changed: Callable[[int], None],
        suite_log: Callable[[str], None],
        current_runtime: Callable[[], bool],
        horizontal_pan_callback: Callable[[int], None] | None = None,
    ) -> None:
        if type(slot_id) is not int or slot_id != view.slot_id:
            raise ValueError("slot_id must match the Research chart slot widget")
        if not isinstance(session, ChartSessionState):
            raise TypeError("session must be a ChartSessionState")
        if not isinstance(service, ResearchDatasetApplicationService):
            raise TypeError("service must be a ResearchDatasetApplicationService")
        if not isinstance(study_service, ResearchStudyApplicationService):
            raise TypeError("study_service must be a ResearchStudyApplicationService")
        for callback, name in (
            (callback_dispatcher, "callback_dispatcher"),
            (state_changed, "state_changed"),
            (suite_log, "suite_log"),
            (current_runtime, "current_runtime"),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        self._slot_id = slot_id
        self._view = view
        self._session = session
        self._service = service
        self._study_service = study_service
        self._dispatch = callback_dispatcher
        self._state_changed = state_changed
        self._suite_log = suite_log
        self._current_runtime = current_runtime
        if horizontal_pan_callback is not None and not callable(horizontal_pan_callback):
            raise TypeError("horizontal_pan_callback must be callable or None")
        self._horizontal_pan_callback = horizontal_pan_callback
        self._viewport: HorizontalViewport | None = None
        self._interaction: CandlestickInteractionState | None = None
        self._active_load_task_id: str | None = None
        self._active_slice_task_id: str | None = None
        self._open_attempt = None
        self._slice_attempt = None
        self._active_study_tasks: dict[str, tuple[str, object]] = {}
        self._disposed = False
        self._last_viewport_snapshot: ViewportSnapshot | None = None
        self._programmatic_navigation = False
        self._view.chart_workspace.viewportChanged.connect(self._on_viewport_changed)

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def session(self) -> ChartSessionState:
        return self._session

    @property
    def viewport(self) -> HorizontalViewport | None:
        return self._viewport

    @property
    def interaction(self) -> CandlestickInteractionState | None:
        return self._interaction

    @property
    def chart_widget(self):
        return self._view.chart_widget

    @property
    def chart_workspace(self):
        return self._view.chart_workspace

    @property
    def status_text(self) -> str:
        return self._view.status_text

    @property
    def is_busy(self) -> bool:
        return any(
            task_id is not None
            for task_id in (self._active_load_task_id, self._active_slice_task_id)
        ) or bool(self._active_study_tasks)

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    def open_dataset(self, market_id):
        self._require_current()
        self._cancel_dataset_tasks()
        attempt = self._session.begin_dataset_open(market_id)
        self._open_attempt = attempt
        self._viewport = None
        self._interaction = None
        self._view.clear_chart_state()
        self._view.set_dataset(market_id)
        self._view.set_go_to_enabled(False)
        self._set_busy(True)
        self._set_status("Loading historical dataset")
        self._log(f"Opening {market_id.as_key()} in Chart {self._slot_id}...")
        try:
            submission = self._service.submit_load(
                market_id,
                progress_callback=self._on_load_progress,
                result_callback=self._on_load_result,
                callback_dispatcher=self._dispatch,
            )
        except Exception as error:
            self._session.settle_dataset_open_failure(attempt)
            self._view.set_go_to_enabled(False)
            self._set_busy(False)
            self._set_status("Dataset submission failed")
            self._log(f"Chart {self._slot_id} dataset submission failed: {error}")
            raise
        self._active_load_task_id = submission.task_id
        self._changed()
        return submission

    def cancel_active_operation(self) -> None:
        self._require_current()
        task_ids = tuple(
            task_id
            for task_id in (
                self._active_load_task_id,
                self._active_slice_task_id,
                *self._active_study_tasks,
            )
            if task_id is not None
        )
        if not task_ids:
            return
        cancelled = False
        for task_id in task_ids:
            if task_id in self._active_study_tasks:
                cancelled = self._study_service.cancel(task_id) or cancelled
            else:
                cancelled = self._service.cancel(task_id) or cancelled
        self._set_status("Cancellation requested")
        self._log(
            f"Chart {self._slot_id}: "
            + ("cancellation requested." if cancelled else "operation already settled.")
        )

    def submit_study_calculation(self, request: StudyExecutionRequest):
        self._require_current()
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        dataset = self._session.dataset
        if dataset is None:
            raise RuntimeError("an accepted Research dataset is required")
        attempt = self._session.begin_study_apply()
        self._set_busy(True)
        self._set_status("Applying Research Study")
        try:
            submission = self._study_service.submit_calculation(
                attempt,
                dataset,
                self._session.studies,
                request,
                progress_callback=self._on_study_progress,
                result_callback=lambda result: self._on_study_apply_result(result, attempt),
                callback_dispatcher=self._dispatch,
            )
        except Exception:
            self._session.settle_study_apply_failure(attempt)
            self._set_busy(False)
            raise
        self._active_study_tasks[submission.task_id] = ("apply", attempt)
        self._changed()
        return submission

    def submit_artifact_apply(self, request: StudyArtifactRequest):
        self._require_current()
        if not isinstance(request, StudyArtifactRequest):
            raise TypeError("request must be a StudyArtifactRequest")
        dataset = self._session.dataset
        if dataset is None:
            raise RuntimeError("an accepted Research dataset is required")
        attempt = self._session.begin_study_apply()
        self._set_busy(True)
        self._set_status("Applying Research artifact")
        try:
            submission = self._study_service.submit_artifact_apply(
                attempt,
                dataset,
                request,
                progress_callback=self._on_study_progress,
                result_callback=lambda result: self._on_study_apply_result(result, attempt),
                callback_dispatcher=self._dispatch,
            )
        except Exception:
            self._session.settle_study_apply_failure(attempt)
            self._set_busy(False)
            raise
        self._active_study_tasks[submission.task_id] = ("apply", attempt)
        self._changed()
        return submission

    def save_study(self, study_id: str) -> None:
        self._require_current()
        dataset = self._session.dataset
        if dataset is None:
            return
        attempt = None
        try:
            study = self._session.study_registry.get(study_id)
            attempt = self._session.begin_study_save(study_id)
            submission = self._study_service.submit_save(
                attempt,
                dataset,
                study,
                self._session.studies,
                progress_callback=self._on_study_progress,
                result_callback=lambda result: self._on_study_save_result(result, attempt),
                callback_dispatcher=self._dispatch,
            )
        except Exception as error:
            if attempt is not None:
                self._session.settle_study_save_failure(attempt)
            self._log(f"Chart {self._slot_id} Study Save submission failed: {error}")
            return
        self._active_study_tasks[submission.task_id] = ("save", attempt)
        self._set_busy(True)
        self._set_status("Saving Research Study")

    def set_study_visibility(self, study_id: str, visible: bool) -> None:
        if not self._runtime_is_current():
            return
        try:
            self._session.set_study_visibility(study_id, visible)
            self._refresh_study_state()
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study visibility failed: {error}")

    def open_study_style(self, study_id: str) -> StudyStyleDialog | None:
        if not self._runtime_is_current():
            return None
        presentation = self._presentation(study_id)
        if presentation is None:
            return None
        dialog = StudyStyleDialog(presentation, self._view)
        dialog.patch_applied.connect(self.apply_style_patch)
        dialog.reset_requested.connect(self.reset_study_style)
        dialog.show()
        return dialog

    def apply_style_patch(self, patch: StudyStylePatch) -> None:
        if not isinstance(patch, StudyStylePatch):
            raise TypeError("patch must be a StudyStylePatch")
        if not self._runtime_is_current():
            self._log(f"Chart {self._slot_id} stale Study style patch rejected.")
            return
        try:
            self._session.set_study_visibility(patch.study_id, patch.visible)
            for style in patch.signal_styles:
                self._session.replace_study_line_style(
                    patch.study_id, style.output_name, style
                )
            for style in patch.fill_styles:
                self._session.replace_study_fill_style(
                    patch.study_id, style.fill_id, style
                )
            self._refresh_study_state()
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study style failed: {error}")

    def reset_study_style(self, study_id: str) -> None:
        if not self._runtime_is_current():
            return
        try:
            self._session.reset_study_presentation(study_id)
            self._refresh_study_state()
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study style reset failed: {error}")

    def remove_study(self, study_id: str) -> None:
        if not self._runtime_is_current():
            return
        try:
            self._session.remove_study(study_id)
            self._refresh_study_state()
        except StudyDependencyError as error:
            self._log(f"Chart {self._slot_id} Study removal blocked: {error}")
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study removal failed: {error}")

    def refresh_active_manager_state(self) -> None:
        if self._runtime_is_current():
            self._changed()

    def set_autoscale_enabled(self, enabled: bool) -> bool:
        self._require_current()
        changed = self._view.chart_widget.set_autoscale_enabled(enabled)
        self._changed()
        return changed

    def set_volume_visible(self, visible: bool) -> bool:
        self._require_current()
        changed = self._view.chart_workspace.set_volume_visible(visible)
        self._changed()
        return changed

    def current_center_timestamp_ms(self) -> int | None:
        if not self._runtime_is_current() or self._viewport is None:
            return None
        return self._session.timestamp_for_global_index(self._viewport.center_index)

    def center_on_timestamp_ms(self, timestamp_ms: int) -> bool:
        self._require_current()
        if type(timestamp_ms) is not int:
            raise TypeError("timestamp_ms must be an integer")
        if self._session.dataset is None or self._viewport is None:
            self._set_status("No accepted dataset for chart navigation")
            return False
        global_index = self._session.nearest_global_index_for_timestamp(timestamp_ms)
        self._programmatic_navigation = True
        try:
            changed = self._viewport.center_on_index(global_index)
            self._last_viewport_snapshot = self._viewport.snapshot()
            if changed:
                workspace = self._view.chart_workspace
                workspace.price_chart.refresh_from_shared_state(
                    refresh_price_scale=False
                )
                workspace.volume_chart.refresh_from_shared_state()
                for study in self._session.studies:
                    oscillator = workspace.oscillator_widget(study.study_id)
                    if oscillator is not None:
                        oscillator.refresh_from_shared_state()
                workspace.price_chart.repaint()
                self._maybe_request_resident()
            return changed
        finally:
            self._programmatic_navigation = False

    def go_to_timestamp_ms(self, timestamp_ms: int) -> bool:
        changed = self.center_on_timestamp_ms(timestamp_ms)
        if self._session.dataset is not None and self._viewport is not None:
            self._set_status("Chart navigation updated")
        return changed

    def dispose(self) -> bool:
        if self._disposed:
            return False
        self._disposed = True
        self._cancel_dataset_tasks()
        for task_id in tuple(self._active_study_tasks):
            self._study_service.cancel(task_id)
        self._active_study_tasks.clear()
        self._view.set_go_to_enabled(False)
        try:
            self._view.chart_workspace.viewportChanged.disconnect(self._on_viewport_changed)
        except RuntimeError:
            pass
        self._view.set_busy(False)
        return True

    def _on_load_progress(self, progress: TaskProgress) -> None:
        if not self._accept_task_callback(progress.task_id, self._active_load_task_id):
            return
        self._set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_load_result(self, result: TaskResult) -> None:
        if not self._accept_task_callback(result.task_id, self._active_load_task_id):
            return
        self._active_load_task_id = None
        attempt = self._open_attempt
        self._open_attempt = None
        if attempt is None:
            return
        if result.status != "completed" or not isinstance(result.value, HistoricalDataset):
            self._session.settle_dataset_open_failure(attempt)
            self._view.set_go_to_enabled(False)
            self._set_busy(False)
            self._handle_terminal_failure("Dataset load", result)
            return
        dataset = result.value
        if not self._session.accept_dataset_open(attempt, dataset):
            return
        self._viewport = HorizontalViewport(dataset.row_count)
        self._interaction = CandlestickInteractionState(
            self._viewport, None, price_scale=PriceScaleState()
        )
        self._last_viewport_snapshot = self._viewport.snapshot()
        self._view.set_go_to_enabled(True)
        interest = self._viewport.dataset_interest()
        if interest is not None:
            self._request_resident(interest.center_index)

    def _request_resident(self, center_index: int) -> None:
        if not self._runtime_is_current():
            return
        dataset = self._session.dataset
        if dataset is None:
            return
        self._cancel_task(self._active_slice_task_id)
        attempt = self._session.begin_resident_slice_request()
        self._slice_attempt = attempt
        self._set_busy(True)
        self._set_status("Preparing resident candles")
        try:
            submission = self._service.submit_resident_slice(
                dataset,
                center_index,
                progress_callback=self._on_slice_progress,
                result_callback=self._on_slice_result,
                callback_dispatcher=self._dispatch,
            )
        except Exception as error:
            self._session.settle_resident_slice_failure(attempt)
            self._set_busy(False)
            self._set_status("Resident submission failed")
            self._log(f"Chart {self._slot_id} resident submission failed: {error}")
            return
        self._active_slice_task_id = submission.task_id
        self._changed()

    def _on_slice_progress(self, progress: TaskProgress) -> None:
        if not self._accept_task_callback(progress.task_id, self._active_slice_task_id):
            return
        self._set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_slice_result(self, result: TaskResult) -> None:
        if not self._accept_task_callback(result.task_id, self._active_slice_task_id):
            return
        self._active_slice_task_id = None
        attempt = self._slice_attempt
        self._slice_attempt = None
        if attempt is None:
            return
        if result.status != "completed" or not isinstance(result.value, ResidentOHLCVSlice):
            self._session.settle_resident_slice_failure(attempt)
            self._set_busy(False)
            self._handle_terminal_failure("Resident load", result)
            return
        resident = result.value
        interest = None if self._viewport is None else self._viewport.dataset_interest()
        if interest is not None and (
            interest.start_index < resident.base_index
            or interest.end_index_exclusive > resident.end_index_exclusive
        ):
            self._session.settle_resident_slice_failure(attempt)
            self._request_resident(interest.center_index)
            return
        if not self._session.accept_resident_slice(attempt, resident):
            return
        if self._interaction is None:
            return
        self._interaction.set_resident(resident)
        dataset = self._session.dataset
        if dataset is None:
            self._set_busy(False)
            self._set_status("Volume projection failed")
            self._log(f"Chart {self._slot_id} volume projection failed: dataset unavailable.")
            return
        try:
            volume_projection = build_resident_volume_projection(dataset, resident)
        except (TypeError, ValueError) as error:
            self._set_busy(False)
            self._set_status("Volume projection failed")
            self._log(f"Chart {self._slot_id} volume projection failed: {error}")
            return
        self._view.show_interaction_state(self._interaction, volume_projection)
        self._refresh_study_state()
        self._set_busy(False)
        self._set_status("Chart ready")
        market = resident.market_id
        self._log(
            f"Chart {self._slot_id} ready: {market.symbol} {market.timeframe}; "
            f"resident {resident.base_index}-{resident.end_index_exclusive - 1}."
        )

    def _on_study_progress(self, progress: TaskProgress) -> None:
        if not self._accept_task_callback(progress.task_id, progress.task_id):
            return
        if progress.task_id not in self._active_study_tasks:
            return
        self._set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_study_apply_result(self, result: TaskResult, attempt: StudyApplyAttempt) -> None:
        if not self._runtime_is_current():
            return
        if self._active_study_tasks.pop(result.task_id, None) is None:
            return
        if result.status == "completed" and isinstance(result.value, PreparedStudy):
            try:
                accepted = self._session.accept_study_apply(attempt, result.value)
            except (TypeError, ValueError, StudyValidationError) as error:
                self._log(f"Chart {self._slot_id} Study Apply failed: {error}")
                accepted = False
            if accepted:
                self._refresh_study_state()
                self._set_status("Study applied")
                self._log(
                    f"Chart {self._slot_id} Study applied: {result.value.study.display_name}."
                )
        else:
            self._session.settle_study_apply_failure(attempt)
            self._handle_terminal_failure("Study Apply", result)
        self._refresh_busy_state()

    def _on_study_save_result(self, result: TaskResult, attempt: StudySaveAttempt) -> None:
        if not self._runtime_is_current():
            return
        if self._active_study_tasks.pop(result.task_id, None) is None:
            return
        if result.status == "completed" and isinstance(result.value, StudySaveOutcome):
            if self._session.accept_study_save(attempt, result.value):
                self._refresh_study_state()
                self._set_status("Study saved")
                self._log(f"Chart {self._slot_id} Study saved: {attempt.study_id}.")
        else:
            self._session.settle_study_save_failure(attempt)
            self._handle_terminal_failure("Study Save", result)
        self._refresh_busy_state()

    def _on_viewport_changed(self, snapshot: object) -> None:
        if not self._runtime_is_current():
            return
        if not isinstance(snapshot, ViewportSnapshot):
            return
        previous = self._last_viewport_snapshot
        self._last_viewport_snapshot = snapshot
        is_horizontal_pan = (
            not self._programmatic_navigation
            and previous is not None
            and snapshot.start_index != previous.start_index
            and snapshot.visible_count == previous.visible_count
        )
        self._maybe_request_resident()
        if is_horizontal_pan and self._horizontal_pan_callback is not None:
            self._horizontal_pan_callback(self._slot_id)

    def _maybe_request_resident(self) -> None:
        resident = self._session.resident
        if self._viewport is None or resident is None:
            return
        direction = self._viewport.resident_refill_direction(
            resident_start_index=resident.base_index,
            resident_end_index_exclusive=resident.end_index_exclusive,
            has_more_left=resident.has_more_left,
            has_more_right=resident.has_more_right,
        )
        if direction is ResidentRefillDirection.NONE:
            return
        interest = self._viewport.dataset_interest()
        if interest is not None:
            self._request_resident(interest.center_index)

    def _presentation(self, study_id: str):
        return next(
            (item for item in self._session.study_presentations() if item.study_id == study_id),
            None,
        )

    def _refresh_study_state(self) -> None:
        if not self._runtime_is_current():
            return
        projections = tuple(
            item
            for item in self._session.study_registry.projection_snapshot()
            if isinstance(item, ResidentStudyProjection)
        )
        self._view.set_study_state(projections, self._session.study_presentations())
        self._changed()

    def _refresh_busy_state(self) -> None:
        self._set_busy(self.is_busy)

    def _set_busy(self, busy: bool) -> None:
        self._view.set_busy(busy)
        self._changed()

    def _set_status(self, message: str) -> None:
        self._view.set_status(message)
        self._changed()

    def _changed(self) -> None:
        if self._runtime_is_current():
            self._state_changed(self._slot_id)

    def _log(self, message: str) -> None:
        if self._runtime_is_current():
            self._suite_log(message)

    def _handle_terminal_failure(self, label: str, result: TaskResult) -> None:
        if result.status == "cancelled":
            self._set_status(f"{label} cancelled")
            self._log(f"Chart {self._slot_id} {label} cancelled.")
            return
        message = result.error_message or result.error_type or "unknown error"
        self._set_status(f"{label} failed")
        self._log(f"Chart {self._slot_id} {label} failed: {message}")

    def _cancel_dataset_tasks(self) -> None:
        self._cancel_task(self._active_load_task_id)
        self._cancel_task(self._active_slice_task_id)
        self._active_load_task_id = None
        self._active_slice_task_id = None
        self._open_attempt = None
        self._slice_attempt = None

    def _cancel_task(self, task_id: str | None) -> None:
        if task_id is not None:
            self._service.cancel(task_id)

    def _runtime_is_current(self) -> bool:
        return not self._disposed and self._current_runtime()

    def _accept_task_callback(self, task_id: str, active_task_id: str | None) -> bool:
        return self._runtime_is_current() and task_id == active_task_id

    def _require_current(self) -> None:
        if not self._runtime_is_current():
            raise RuntimeError("Research chart runtime is no longer current")
