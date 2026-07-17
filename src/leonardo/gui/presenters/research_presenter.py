"""Qt presenter for the single-chart historical Research workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.chart import CandlestickInteractionState, PriceScaleState
from leonardo.gui.windows.research_suite_window import ResearchSuiteWindow
from leonardo.gui.windows.study_style_dialog import StudyStylePatch
from leonardo.research import (
    ChartSessionState,
    DatasetCatalogReport,
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
    build_resident_volume_projection,
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


class ResearchSuitePresenter(QObject):
    """Coordinate one Research chart without owning OHLCV or task truth."""

    def __init__(
        self,
        view: ResearchSuiteWindow,
        service: ResearchDatasetApplicationService,
        study_service: ResearchStudyApplicationService,
    ) -> None:
        super().__init__(view)
        if not isinstance(view, ResearchSuiteWindow):
            raise TypeError("view must be a ResearchSuiteWindow")
        if not isinstance(service, ResearchDatasetApplicationService):
            raise TypeError("service must be a ResearchDatasetApplicationService")
        if not isinstance(study_service, ResearchStudyApplicationService):
            raise TypeError("study_service must be a ResearchStudyApplicationService")
        self._view = view
        self._service = service
        self._study_service = study_service
        self._dispatcher = _QtCallbackDispatcher(self)
        self._session = ChartSessionState()
        self._viewport: HorizontalViewport | None = None
        self._interaction: CandlestickInteractionState | None = None
        self._active_catalog_task_id: str | None = None
        self._active_load_task_id: str | None = None
        self._active_slice_task_id: str | None = None
        self._open_attempt = None
        self._slice_attempt = None
        self._active_study_tasks: dict[str, tuple[str, object]] = {}
        self._wire()
        self.refresh_catalog()

    @property
    def session(self) -> ChartSessionState:
        return self._session

    @property
    def viewport(self) -> HorizontalViewport | None:
        return self._viewport

    def submit_study_calculation(self, request: StudyExecutionRequest):
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        dataset = self._session.dataset
        if dataset is None:
            raise RuntimeError("an accepted Research dataset is required")
        attempt = self._session.begin_study_apply()
        self._view.set_busy(True)
        self._view.set_status("Applying Research Study")
        try:
            submission = self._study_service.submit_calculation(
                attempt,
                dataset,
                self._session.studies,
                request,
                progress_callback=self._on_study_progress,
                result_callback=lambda result: self._on_study_apply_result(
                    result, attempt
                ),
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception:
            self._session.settle_study_apply_failure(attempt)
            self._view.set_busy(False)
            raise
        self._active_study_tasks[submission.task_id] = ("apply", attempt)
        return submission

    def submit_artifact_apply(self, request: StudyArtifactRequest):
        if not isinstance(request, StudyArtifactRequest):
            raise TypeError("request must be a StudyArtifactRequest")
        dataset = self._session.dataset
        if dataset is None:
            raise RuntimeError("an accepted Research dataset is required")
        attempt = self._session.begin_study_apply()
        self._view.set_busy(True)
        self._view.set_status("Applying Research artifact")
        try:
            submission = self._study_service.submit_artifact_apply(
                attempt,
                dataset,
                request,
                progress_callback=self._on_study_progress,
                result_callback=lambda result: self._on_study_apply_result(
                    result, attempt
                ),
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception:
            self._session.settle_study_apply_failure(attempt)
            self._view.set_busy(False)
            raise
        self._active_study_tasks[submission.task_id] = ("apply", attempt)
        return submission

    def _wire(self) -> None:
        self._view.refresh_requested.connect(self.refresh_catalog)
        self._view.open_requested.connect(self.open_selected_dataset)
        self._view.cancel_requested.connect(self.cancel_active_operation)
        self._view.closed.connect(self.dispose)
        self._view.chart_workspace.viewportChanged.connect(self._on_viewport_changed)
        manager = self._view.study_manager
        manager.visibility_requested.connect(self._set_study_visibility)
        manager.style_requested.connect(self._open_study_style)
        manager.reset_style_requested.connect(self._reset_study_style)
        manager.save_requested.connect(self._save_study)
        manager.remove_requested.connect(self._remove_study)

    def refresh_catalog(self) -> None:
        self._cancel_task(self._active_catalog_task_id)
        self._active_catalog_task_id = None
        self._view.set_busy(True)
        self._view.set_status("Scanning accepted datasets")
        self._view.append_status("Scanning canonical OHLCV storage for accepted datasets...")
        try:
            submission = self._service.submit_catalog(
                progress_callback=self._on_catalog_progress,
                result_callback=self._on_catalog_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception as error:
            self._view.set_busy(False)
            self._view.set_status("Catalog submission failed")
            self._view.append_status(f"Catalog submission failed: {error}")
            return
        self._active_catalog_task_id = submission.task_id

    def open_selected_dataset(self) -> None:
        market_id = self._view.selected_market_id()
        if market_id is None:
            self._view.append_status("No accepted dataset is selected.")
            return
        self._cancel_chart_tasks()
        attempt = self._session.begin_dataset_open(market_id)
        self._open_attempt = attempt
        self._viewport = None
        self._interaction = None
        self._view.clear_chart()
        self._view.set_busy(True)
        self._view.set_status("Loading historical dataset")
        self._view.append_status(f"Opening {market_id.as_key()}...")
        try:
            submission = self._service.submit_load(
                market_id,
                progress_callback=self._on_load_progress,
                result_callback=self._on_load_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception as error:
            self._session.settle_dataset_open_failure(attempt)
            self._view.set_busy(False)
            self._view.set_status("Dataset submission failed")
            self._view.append_status(f"Dataset submission failed: {error}")
            return
        self._active_load_task_id = submission.task_id

    def cancel_active_operation(self) -> None:
        task_ids = tuple(
            task_id
            for task_id in (
                self._active_catalog_task_id,
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
        self._view.set_status("Cancellation requested")
        self._view.append_status(
            "Cancellation requested." if cancelled else "Operation already settled."
        )

    def dispose(self) -> None:
        self._cancel_chart_tasks()
        self._cancel_task(self._active_catalog_task_id)
        self._active_catalog_task_id = None
        for task_id in tuple(self._active_study_tasks):
            self._study_service.cancel(task_id)
        self._active_study_tasks.clear()
        self._session.dispose()

    def _on_catalog_progress(self, progress: TaskProgress) -> None:
        if progress.task_id != self._active_catalog_task_id:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_catalog_result(self, result: TaskResult) -> None:
        if result.task_id != self._active_catalog_task_id:
            return
        self._active_catalog_task_id = None
        self._view.set_busy(False)
        if result.status == "completed" and isinstance(result.value, DatasetCatalogReport):
            report = result.value
            self._view.set_catalog(report.accepted)
            self._view.set_status(
                f"Ready — {report.accepted_count} accepted dataset(s)"
            )
            self._view.append_status(
                f"Catalog ready: {report.accepted_count} accepted, "
                f"{report.rejected_count} refused."
            )
            return
        self._handle_terminal_failure("Catalog", result)

    def _on_load_progress(self, progress: TaskProgress) -> None:
        if progress.task_id != self._active_load_task_id:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_load_result(self, result: TaskResult) -> None:
        if result.task_id != self._active_load_task_id:
            return
        self._active_load_task_id = None
        attempt = self._open_attempt
        self._open_attempt = None
        if attempt is None:
            return
        if result.status != "completed" or not isinstance(result.value, HistoricalDataset):
            self._session.settle_dataset_open_failure(attempt)
            self._view.set_busy(False)
            self._handle_terminal_failure("Dataset load", result)
            return
        dataset = result.value
        if not self._session.accept_dataset_open(attempt, dataset):
            return
        self._viewport = HorizontalViewport(dataset.row_count)
        self._interaction = CandlestickInteractionState(
            self._viewport,
            None,
            price_scale=PriceScaleState(),
        )
        self._request_resident(self._viewport.dataset_interest().center_index)

    def _request_resident(self, center_index: int) -> None:
        dataset = self._session.dataset
        if dataset is None:
            return
        self._cancel_task(self._active_slice_task_id)
        attempt = self._session.begin_resident_slice_request()
        self._slice_attempt = attempt
        self._view.set_busy(True)
        self._view.set_status("Preparing resident candles")
        try:
            submission = self._service.submit_resident_slice(
                dataset,
                center_index,
                progress_callback=self._on_slice_progress,
                result_callback=self._on_slice_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception as error:
            self._session.settle_resident_slice_failure(attempt)
            self._view.set_busy(False)
            self._view.set_status("Resident submission failed")
            self._view.append_status(f"Resident submission failed: {error}")
            return
        self._active_slice_task_id = submission.task_id

    def _on_slice_progress(self, progress: TaskProgress) -> None:
        if progress.task_id != self._active_slice_task_id:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_slice_result(self, result: TaskResult) -> None:
        if result.task_id != self._active_slice_task_id:
            return
        self._active_slice_task_id = None
        attempt = self._slice_attempt
        self._slice_attempt = None
        if attempt is None:
            return
        if result.status != "completed" or not isinstance(result.value, ResidentOHLCVSlice):
            self._session.settle_resident_slice_failure(attempt)
            self._view.set_busy(False)
            self._handle_terminal_failure("Resident load", result)
            return
        resident = result.value
        viewport = self._viewport
        interest = None if viewport is None else viewport.dataset_interest()
        if interest is not None and (
            interest.start_index < resident.base_index
            or interest.end_index_exclusive > resident.end_index_exclusive
        ):
            self._session.settle_resident_slice_failure(attempt)
            self._request_resident(interest.center_index)
            return
        if not self._session.accept_resident_slice(attempt, resident):
            return
        interaction = self._interaction
        if interaction is None:
            return
        interaction.set_resident(resident)
        dataset = self._session.dataset
        if dataset is None:
            self._view.set_busy(False)
            self._view.set_status("Volume projection failed")
            self._view.append_status("Volume projection failed: dataset is unavailable.")
            return
        try:
            volume_projection = build_resident_volume_projection(dataset, resident)
        except (TypeError, ValueError) as error:
            self._view.set_busy(False)
            self._view.set_status("Volume projection failed")
            self._view.append_status(f"Volume projection failed: {error}")
            return
        self._view.show_interaction_state(
            interaction,
            volume_projection=volume_projection,
        )
        self._refresh_study_state()
        self._view.set_busy(False)
        self._view.set_status("Chart ready")
        market = resident.market_id
        self._view.append_status(
            f"Chart ready: {market.symbol} {market.timeframe}; "
            f"resident {resident.base_index}–{resident.end_index_exclusive - 1}."
        )

    def _on_study_progress(self, progress: TaskProgress) -> None:
        if progress.task_id not in self._active_study_tasks:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_study_apply_result(
        self, result: TaskResult, attempt: StudyApplyAttempt
    ) -> None:
        if self._active_study_tasks.pop(result.task_id, None) is None:
            return
        if result.status == "completed" and isinstance(result.value, PreparedStudy):
            try:
                accepted = self._session.accept_study_apply(attempt, result.value)
            except (TypeError, ValueError, StudyValidationError) as error:
                self._view.append_status(f"Study Apply failed: {error}")
                accepted = False
            if accepted:
                self._refresh_study_state()
                self._view.set_status("Study applied")
                self._view.append_status(
                    f"Study applied: {result.value.study.display_name}."
                )
        else:
            self._session.settle_study_apply_failure(attempt)
            self._handle_terminal_failure("Study Apply", result)
        self._refresh_busy_state()

    def _save_study(self, study_id: str) -> None:
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
                result_callback=lambda result: self._on_study_save_result(
                    result, attempt
                ),
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception as error:
            if attempt is not None:
                self._session.settle_study_save_failure(attempt)
            self._view.append_status(f"Study Save submission failed: {error}")
            return
        self._active_study_tasks[submission.task_id] = ("save", attempt)
        self._view.set_busy(True)
        self._view.set_status("Saving Research Study")

    def _on_study_save_result(
        self, result: TaskResult, attempt: StudySaveAttempt
    ) -> None:
        if self._active_study_tasks.pop(result.task_id, None) is None:
            return
        if result.status == "completed" and isinstance(result.value, StudySaveOutcome):
            if self._session.accept_study_save(attempt, result.value):
                self._refresh_study_state()
                self._view.set_status("Study saved")
                self._view.append_status(f"Study saved: {attempt.study_id}.")
        else:
            self._session.settle_study_save_failure(attempt)
            self._handle_terminal_failure("Study Save", result)
        self._refresh_busy_state()

    def _set_study_visibility(self, study_id: str, visible: bool) -> None:
        try:
            self._session.set_study_visibility(study_id, visible)
            self._refresh_study_state()
        except (TypeError, ValueError) as error:
            self._view.append_status(f"Study visibility failed: {error}")

    def _open_study_style(self, study_id: str) -> None:
        presentation = self._presentation(study_id)
        if presentation is None:
            return
        dialog = self._view.open_study_style_dialog(presentation)
        dialog.patch_applied.connect(self._apply_style_patch)
        dialog.reset_requested.connect(self._reset_study_style)

    def _apply_style_patch(self, patch: StudyStylePatch) -> None:
        if not isinstance(patch, StudyStylePatch):
            raise TypeError("patch must be a StudyStylePatch")
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
            self._view.append_status(f"Study style failed: {error}")

    def _reset_study_style(self, study_id: str) -> None:
        try:
            self._session.reset_study_presentation(study_id)
            self._refresh_study_state()
        except (TypeError, ValueError) as error:
            self._view.append_status(f"Study style reset failed: {error}")

    def _remove_study(self, study_id: str) -> None:
        try:
            self._session.remove_study(study_id)
            self._refresh_study_state()
        except StudyDependencyError as error:
            self._view.append_status(f"Study removal blocked: {error}")
        except (TypeError, ValueError) as error:
            self._view.append_status(f"Study removal failed: {error}")

    def _presentation(self, study_id: str):
        return next(
            (
                item
                for item in self._session.study_presentations()
                if item.study_id == study_id
            ),
            None,
        )

    def _refresh_study_state(self) -> None:
        projections = tuple(
            item
            for item in self._session.study_registry.projection_snapshot()
            if isinstance(item, ResidentStudyProjection)
        )
        self._view.set_study_state(
            projections,
            self._session.study_presentations(),
            self._session.study_manager_entries(),
        )

    def _refresh_busy_state(self) -> None:
        busy = any(
            task_id is not None
            for task_id in (
                self._active_catalog_task_id,
                self._active_load_task_id,
                self._active_slice_task_id,
            )
        ) or bool(self._active_study_tasks)
        self._view.set_busy(busy)

    def _on_viewport_changed(self, _snapshot: object) -> None:
        viewport = self._viewport
        resident = self._session.resident
        if viewport is None or resident is None:
            return
        direction = viewport.resident_refill_direction(
            resident_start_index=resident.base_index,
            resident_end_index_exclusive=resident.end_index_exclusive,
            has_more_left=resident.has_more_left,
            has_more_right=resident.has_more_right,
        )
        if direction is ResidentRefillDirection.NONE:
            return
        interest = viewport.dataset_interest()
        if interest is None:
            return
        self._request_resident(interest.center_index)

    def _handle_terminal_failure(self, label: str, result: TaskResult) -> None:
        if result.status == "cancelled":
            self._view.set_status(f"{label} cancelled")
            self._view.append_status(f"{label} cancelled.")
            return
        message = result.error_message or result.error_type or "unknown error"
        self._view.set_status(f"{label} failed")
        self._view.append_status(f"{label} failed: {message}")

    def _cancel_chart_tasks(self) -> None:
        self._cancel_task(self._active_load_task_id)
        self._cancel_task(self._active_slice_task_id)
        self._active_load_task_id = None
        self._active_slice_task_id = None
        self._open_attempt = None
        self._slice_attempt = None

    def _cancel_task(self, task_id: str | None) -> None:
        if task_id is not None:
            self._service.cancel(task_id)
