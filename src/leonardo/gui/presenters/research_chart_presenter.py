"""Slot-local presenter for one accepted Research chart workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from importlib import import_module
from typing import Any, Protocol
from uuid import uuid4

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.chart import CandlestickInteractionState, PriceScaleState
from leonardo.gui.chart.annotation_scene import (
    ResearchChartAnnotationBundle,
    ResearchChartAnnotationProjection,
)
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
    StudyEditAttempt,
    StudyExecutionRequest,
    StudyGuideStyle,
    StudyInputSource,
    StudySaveAttempt,
    StudySaveOutcome,
    StudyValidationError,
    ViewportSnapshot,
    build_resident_volume_projection,
)
from leonardo.research.study_environment import (
    EnvironmentCompatibilityReport,
    EnvironmentEntryV1,
    EnvironmentV1,
)
_snapshot_models = import_module("leonardo.research.workspace_" "snapshot")
SnapshotChartCapture = getattr(_snapshot_models, "Workspace" "SnapshotChartCapture")
SnapshotChartV1 = getattr(_snapshot_models, "Workspace" "SnapshotChartV1")
SnapshotPriceScaleV1 = getattr(_snapshot_models, "Workspace" "SnapshotPriceScaleV1")
SnapshotViewportV1 = getattr(_snapshot_models, "Workspace" "SnapshotViewportV1")
_note_models = import_module("leonardo.research.note" "book")
_ResearchAnnotation = getattr(
    _note_models, "Research" "Note" "bookAnnotation"
)


class _ResearchChartView(Protocol):
    @property
    def slot_id(self) -> int: ...

    @property
    def chart_widget(self) -> Any: ...

    @property
    def chart_workspace(self) -> Any: ...

    @property
    def status_text(self) -> str: ...

    def clear_chart_state(self) -> None: ...

    def set_dataset(self, market_id) -> None: ...

    def set_go_to_enabled(self, enabled: bool) -> None: ...

    def set_status(self, message: str) -> None: ...

    def set_progress(self, current: int | None, total: int | None) -> None: ...

    def set_busy(self, busy: bool) -> None: ...

    def show_interaction_state(self, state, volume_projection) -> None: ...

    def set_study_state(self, projections, presentations) -> None: ...

    def set_study_snapshot(self, projections, presentations, entries) -> None: ...


@dataclass(frozen=True, slots=True)
class ChartOperationOutcome:
    status: str
    slot_id: int
    session_id: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class StudyOperationOutcome:
    slot_id: int
    session_id: str
    operation: str
    status: str
    message: str
    study_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.slot_id) is not int or self.slot_id < 1:
            raise ValueError("slot_id must be a positive integer")
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be non-empty text")
        if self.operation not in {"apply", "edit", "save"}:
            raise ValueError("operation must be apply, edit, or save")
        if self.status not in {"success", "failure", "cancelled", "stale"}:
            raise ValueError("invalid Study operation status")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        if self.study_id is not None and (
            not isinstance(self.study_id, str) or not self.study_id
        ):
            raise ValueError("study_id must be non-empty text or None")


@dataclass(slots=True)
class _EnvironmentRun:
    run_id: str
    environment: EnvironmentV1
    mode: str
    session_id: str
    generation: int
    existing_study_ids: tuple[str, ...]
    entry_index: int = 0
    current_task_id: str | None = None
    entry_to_study: dict[str, str] | None = None
    added_study_ids: list[str] | None = None
    completion_callback: Callable[[ChartOperationOutcome], None] | None = None

    def __post_init__(self) -> None:
        self.entry_to_study = {}
        self.added_study_ids = []


class ResearchChartPresenter:
    """Coordinate exactly one slot's session, tasks, and Task 1018 chart shell."""

    def __init__(
        self,
        slot_id: int,
        view: _ResearchChartView,
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
        self._study_completion_callbacks: dict[
            str, Callable[[StudyOperationOutcome], None]
        ] = {}
        self._environment_report: EnvironmentCompatibilityReport | None = None
        self._environment_run: _EnvironmentRun | None = None
        self._dataset_completion: Callable[[ChartOperationOutcome], None] | None = None
        self._last_environment_entry_map: dict[str, str] = {}
        self._disposed = False
        self._last_viewport_snapshot: ViewportSnapshot | None = None
        self._programmatic_navigation = False
        self._notebook_annotations: tuple[_ResearchAnnotation, ...] = ()
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

    @property
    def environment_apply_active(self) -> bool:
        return self._environment_run is not None

    def set_environment_compatibility(
        self, report: EnvironmentCompatibilityReport | None
    ) -> None:
        if report is not None and not isinstance(
            report, EnvironmentCompatibilityReport
        ):
            raise TypeError("report must be an environment compatibility report or None")
        self._environment_report = report
        self._changed()

    def open_dataset(self, market_id, *, completion_callback=None):
        self._require_current()
        if completion_callback is not None and not callable(completion_callback):
            raise TypeError("completion_callback must be callable or None")
        self._cancel_dataset_tasks()
        self._dataset_completion = completion_callback
        attempt = self._session.begin_dataset_open(market_id)
        self._open_attempt = attempt
        self._viewport = None
        self._interaction = None
        self.clear_notebook_annotations()
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
            self._complete_dataset("failure", str(error))
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

    def submit_study_calculation(
        self,
        request: StudyExecutionRequest,
        *,
        completion_callback: Callable[[StudyOperationOutcome], None] | None = None,
    ):
        self._require_current()
        if completion_callback is not None and not callable(completion_callback):
            raise TypeError("completion_callback must be callable or None")
        if self.environment_apply_active:
            raise RuntimeError("an environment Apply run is active for this chart")
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
        if completion_callback is not None:
            self._study_completion_callbacks[submission.task_id] = completion_callback
        self._changed()
        return submission

    def submit_artifact_apply(self, request: StudyArtifactRequest):
        self._require_current()
        if self.environment_apply_active:
            raise RuntimeError("an environment Apply run is active for this chart")
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

    def submit_study_edit(
        self,
        study_id: str,
        request: StudyExecutionRequest,
        *,
        completion_callback: Callable[[StudyOperationOutcome], None] | None = None,
    ):
        self._require_current()
        if completion_callback is not None and not callable(completion_callback):
            raise TypeError("completion_callback must be callable or None")
        if self.environment_apply_active:
            raise RuntimeError("an environment Apply run is active for this chart")
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        dataset = self._session.dataset
        if dataset is None:
            raise RuntimeError("an accepted Research dataset is required")
        attempt = self._session.begin_study_edit(study_id)
        self._set_busy(True)
        self._set_status("Editing Research Study")
        try:
            submission = self._study_service.submit_edit(
                attempt,
                dataset,
                self._session.studies,
                request,
                progress_callback=self._on_study_progress,
                result_callback=lambda result: self._on_study_edit_result(
                    result, attempt
                ),
                callback_dispatcher=self._dispatch,
            )
        except Exception:
            self._session.settle_study_edit_failure(attempt)
            self._set_busy(False)
            raise
        self._active_study_tasks[submission.task_id] = ("edit", attempt)
        if completion_callback is not None:
            self._study_completion_callbacks[submission.task_id] = completion_callback
        self._changed()
        return submission

    def save_study(
        self,
        study_id: str,
        *,
        completion_callback: Callable[[StudyOperationOutcome], None] | None = None,
    ):
        self._require_current()
        if completion_callback is not None and not callable(completion_callback):
            raise TypeError("completion_callback must be callable or None")
        if self.environment_apply_active:
            self._log(f"Chart {self._slot_id} Study Save blocked by environment Apply.")
            return
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
            self._invoke_study_completion(
                completion_callback,
                self._study_outcome("save", "failure", str(error), study_id),
            )
            return None
        self._active_study_tasks[submission.task_id] = ("save", attempt)
        if completion_callback is not None:
            self._study_completion_callbacks[submission.task_id] = completion_callback
        self._set_busy(True)
        self._set_status("Saving Research Study")
        return submission

    def set_study_visibility(self, study_id: str, visible: bool) -> None:
        if not self._runtime_is_current():
            return
        if self.environment_apply_active:
            self._log(f"Chart {self._slot_id} Study visibility blocked by environment Apply.")
            return
        try:
            self._session.set_study_visibility(study_id, visible)
            self._refresh_study_state()
            self._log(f"Chart {self._slot_id} Study visibility changed: {study_id}.")
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study visibility failed: {error}")

    def open_study_style(self, study_id: str) -> StudyStyleDialog | None:
        if not self._runtime_is_current():
            return None
        if self.environment_apply_active:
            return None
        presentation = self._presentation(study_id)
        if presentation is None:
            return None
        dialog = StudyStyleDialog(presentation)
        dialog.patch_applied.connect(self.apply_style_patch)
        dialog.reset_requested.connect(self.reset_study_style)
        dialog.setParent(self._view, dialog.windowFlags())
        dialog.show()
        return dialog

    def apply_style_patch(self, patch: StudyStylePatch) -> None:
        if not isinstance(patch, StudyStylePatch):
            raise TypeError("patch must be a StudyStylePatch")
        if not self._runtime_is_current():
            self._log(f"Chart {self._slot_id} stale Study style patch rejected.")
            return
        if self.environment_apply_active:
            self._log(f"Chart {self._slot_id} Study style blocked by environment Apply.")
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
            self._log(f"Chart {self._slot_id} Study style applied: {patch.study_id}.")
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study style failed: {error}")

    def apply_guide_values(
        self,
        study_id: str,
        guide_values: Mapping[str, float],
    ) -> None:
        self._require_current()
        if self.environment_apply_active:
            raise RuntimeError(
                "an environment Apply run is active for this chart"
            )
        current = self._presentation(study_id)
        if current is None:
            raise StudyValidationError("Study presentation is unavailable")
        if tuple(guide_values) != tuple(current.guide_styles):
            raise StudyValidationError(
                "guide value identities do not match Study presentation"
            )
        styles = tuple(
            replace(
                current.guide_styles[guide_id],
                value=value,
            )
            for guide_id, value in guide_values.items()
        )
        self._apply_guide_styles(study_id, styles)

    def _apply_guide_styles(
        self,
        study_id: str,
        styles: tuple[StudyGuideStyle, ...],
    ) -> None:
        if not all(isinstance(style, StudyGuideStyle) for style in styles):
            raise StudyValidationError("guide values are invalid")
        study = self._session.study_registry.get(study_id)
        self._session._presentations.replace_guide_styles(study, styles)
        self._refresh_study_state()
        self._log(
            f"Chart {self._slot_id} Study guides applied: {study_id}."
        )

    def reset_study_style(self, study_id: str) -> None:
        if not self._runtime_is_current():
            return
        if self.environment_apply_active:
            return
        try:
            self._session.reset_study_presentation(study_id)
            self._refresh_study_state()
            self._log(f"Chart {self._slot_id} Study style reset: {study_id}.")
        except (TypeError, ValueError) as error:
            self._log(f"Chart {self._slot_id} Study style reset failed: {error}")

    def remove_study(self, study_id: str) -> None:
        if not self._runtime_is_current():
            return
        if self.environment_apply_active:
            self._log(f"Chart {self._slot_id} Study removal blocked by environment Apply.")
            return
        try:
            self._session.remove_study(study_id)
            self._refresh_study_state()
            self._log(f"Chart {self._slot_id} Study removed: {study_id}.")
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

    def set_notebook_annotations(
        self, annotations: tuple[_ResearchAnnotation, ...]
    ) -> bool:
        if not self._runtime_is_current():
            return False
        values = tuple(annotations)
        if not all(isinstance(item, _ResearchAnnotation) for item in values):
            raise TypeError(
                "annotations must contain Research annotation values"
            )
        dataset = self._session.dataset
        if dataset is None:
            return False
        if any(item.market_id != dataset.market_id for item in values):
            return False
        self._notebook_annotations = values
        self._rebuild_notebook_annotations()
        return True

    def clear_notebook_annotations(self) -> None:
        self._notebook_annotations = ()
        self._view.chart_workspace.clear_notebook_annotations()

    def _rebuild_notebook_annotations(self) -> None:
        if not self._runtime_is_current():
            return
        dataset = self._session.dataset
        resident = self._session.resident
        if dataset is None or resident is None:
            self._view.chart_workspace.clear_notebook_annotations()
            return
        if any(
            item.market_id != dataset.market_id
            for item in self._notebook_annotations
        ):
            self.clear_notebook_annotations()
            return
        projections = tuple(
            ResearchChartAnnotationProjection(
                item,
                self._session.nearest_global_index_for_timestamp(
                    item.timestamp_ms
                ),
            )
            for item in self._notebook_annotations
        )
        self._view.chart_workspace.set_notebook_annotations(
            ResearchChartAnnotationBundle(dataset.market_id, projections)
        )

    def apply_environment(
        self, environment: EnvironmentV1, mode: str, *, completion_callback=None
    ) -> None:
        self._require_current()
        if completion_callback is not None and not callable(completion_callback):
            raise TypeError("completion_callback must be callable or None")
        if not isinstance(environment, EnvironmentV1):
            raise TypeError("environment must use the version 1 schema")
        if mode not in {"append", "replace"}:
            raise ValueError("environment Apply mode must be append or replace")
        if self._session.dataset is None or self._viewport is None:
            raise RuntimeError("an accepted dataset and viewport are required")
        if self._environment_run is not None:
            raise RuntimeError("an environment Apply run is already active")
        if self._active_study_tasks:
            raise RuntimeError("a conflicting Study mutation is active")
        report = self._environment_report
        if (
            report is None
            or report.environment_id != environment.environment_id
            or not report.compatible
        ):
            raise RuntimeError("a current blocker-free compatibility report is required")
        self._environment_run = _EnvironmentRun(
            run_id=uuid4().hex,
            environment=environment,
            mode=mode,
            session_id=self._session.session_id,
            generation=self._session.generation,
            existing_study_ids=tuple(study.study_id for study in self._session.studies),
            completion_callback=completion_callback,
        )
        self._set_busy(True)
        self._set_status("Applying Study Environment")
        self._submit_environment_entry()

    def cancel_environment_apply(self) -> bool:
        run = self._environment_run
        if run is None:
            return False
        if run.current_task_id is None:
            self._rollback_environment(
                "Environment Apply cancelled", status="cancellation"
            )
            return True
        cancelled = self._study_service.cancel(run.current_task_id)
        self._set_status("Environment cancellation requested")
        return cancelled

    def dispose(self) -> bool:
        if self._disposed:
            return False
        if self._environment_run is not None:
            run = self._environment_run
            if run.current_task_id is not None:
                self._study_service.cancel(run.current_task_id)
                self._active_study_tasks.pop(run.current_task_id, None)
            self._rollback_environment(
                "Environment Apply cancelled by chart close", status="disposal"
            )
        self._disposed = True
        self._complete_dataset("disposal", "chart disposed")
        self._cancel_dataset_tasks()
        for task_id in tuple(self._active_study_tasks):
            self._study_service.cancel(task_id)
        self._active_study_tasks.clear()
        self._study_completion_callbacks.clear()
        self._view.set_go_to_enabled(False)
        self.clear_notebook_annotations()
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
            self._complete_dataset(result.status, result.error_message or result.error_type or "")
            return
        dataset = result.value
        if not self._session.accept_dataset_open(attempt, dataset):
            self._complete_dataset("stale", "dataset generation is no longer current")
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
            self._complete_dataset("stale", "resident generation is no longer current")
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
        self._rebuild_notebook_annotations()
        self._set_busy(False)
        self._set_status("Chart ready")
        market = resident.market_id
        self._log(
            f"Chart {self._slot_id} ready: {market.symbol} {market.timeframe}; "
            f"resident {resident.base_index}-{resident.end_index_exclusive - 1}."
        )
        self._complete_dataset("success")

    def _on_study_progress(self, progress: TaskProgress) -> None:
        if not self._accept_task_callback(progress.task_id, progress.task_id):
            return
        if progress.task_id not in self._active_study_tasks:
            return
        self._set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_study_apply_result(self, result: TaskResult, attempt: StudyApplyAttempt) -> None:
        if not self._runtime_is_current():
            self._active_study_tasks.pop(result.task_id, None)
            self._study_completion_callbacks.pop(result.task_id, None)
            return
        active = self._active_study_tasks.pop(result.task_id, None)
        completion = self._study_completion_callbacks.pop(result.task_id, None)
        if active != ("apply", attempt):
            return
        if result.status == "completed" and isinstance(result.value, PreparedStudy):
            error_message = ""
            try:
                accepted = self._session.accept_study_apply(attempt, result.value)
            except (TypeError, ValueError, StudyValidationError) as error:
                self._log(f"Chart {self._slot_id} Study Apply failed: {error}")
                accepted = False
                error_message = str(error)
            if accepted:
                self._set_status("Study applied")
                self._log(
                    f"Chart {self._slot_id} Study applied: {result.value.study.display_name}."
                )
                self._invoke_study_completion(
                    completion,
                    self._study_outcome(
                        "apply",
                        "success",
                        "Study applied",
                        result.value.study.study_id,
                    ),
                )
                self._refresh_study_state()
            else:
                status = "failure" if error_message else "stale"
                message = error_message or "Study Apply target is stale"
                self._set_status(f"Study Apply {status}")
                self._invoke_study_completion(
                    completion,
                    self._study_outcome(
                        "apply", status, message, result.value.study.study_id
                    ),
                )
        else:
            self._session.settle_study_apply_failure(attempt)
            self._handle_terminal_failure("Study Apply", result)
            self._invoke_study_completion(
                completion,
                self._study_outcome(
                    "apply",
                    "cancelled" if result.status == "cancelled" else "failure",
                    result.error_message or result.error_type or result.status,
                    attempt.study_id,
                ),
            )
        self._refresh_busy_state()

    def _on_study_save_result(self, result: TaskResult, attempt: StudySaveAttempt) -> None:
        if not self._runtime_is_current():
            self._active_study_tasks.pop(result.task_id, None)
            self._study_completion_callbacks.pop(result.task_id, None)
            return
        active = self._active_study_tasks.pop(result.task_id, None)
        completion = self._study_completion_callbacks.pop(result.task_id, None)
        if active != ("save", attempt):
            return
        if result.status == "completed" and isinstance(result.value, StudySaveOutcome):
            if self._session.accept_study_save(attempt, result.value):
                self._refresh_study_state()
                self._set_status("Study saved")
                self._log(f"Chart {self._slot_id} Study saved: {attempt.study_id}.")
                self._invoke_study_completion(
                    completion,
                    self._study_outcome(
                        "save", "success", "Study saved", attempt.study_id
                    ),
                )
            else:
                self._set_status("Study Save stale")
                self._invoke_study_completion(
                    completion,
                    self._study_outcome(
                        "save",
                        "stale",
                        "Study Save target is stale",
                        attempt.study_id,
                    ),
                )
        else:
            self._session.settle_study_save_failure(attempt)
            self._handle_terminal_failure("Study Save", result)
            self._invoke_study_completion(
                completion,
                self._study_outcome(
                    "save",
                    "cancelled" if result.status == "cancelled" else "failure",
                    result.error_message or result.error_type or result.status,
                    attempt.study_id,
                ),
            )
        self._refresh_busy_state()

    def _on_study_edit_result(self, result: TaskResult, attempt: StudyEditAttempt) -> None:
        if not self._runtime_is_current():
            self._active_study_tasks.pop(result.task_id, None)
            self._study_completion_callbacks.pop(result.task_id, None)
            return
        active = self._active_study_tasks.pop(result.task_id, None)
        completion = self._study_completion_callbacks.pop(result.task_id, None)
        if active != ("edit", attempt):
            return
        if result.status == "completed" and isinstance(result.value, PreparedStudy):
            error_message = ""
            try:
                accepted = self._session.accept_study_edit(attempt, result.value)
            except (
                TypeError,
                ValueError,
                StudyDependencyError,
                StudyValidationError,
            ) as error:
                self._log(f"Chart {self._slot_id} Study Edit failed: {error}")
                accepted = False
                error_message = str(error)
            if accepted:
                self._refresh_study_state()
                self._set_status("Study edited")
                self._log(
                    f"Chart {self._slot_id} Study edited: "
                    f"{result.value.study.display_name}."
                )
                self._invoke_study_completion(
                    completion,
                    self._study_outcome(
                        "edit",
                        "success",
                        "Study edited",
                        result.value.study.study_id,
                    ),
                )
            else:
                status = "failure" if error_message else "stale"
                message = error_message or "Study Edit target is stale"
                self._set_status(f"Study Edit {status}")
                self._invoke_study_completion(
                    completion,
                    self._study_outcome(
                        "edit", status, message, attempt.study_id
                    ),
                )
        else:
            self._session.settle_study_edit_failure(attempt)
            self._handle_terminal_failure("Study Edit", result)
            self._invoke_study_completion(
                completion,
                self._study_outcome(
                    "edit",
                    "cancelled" if result.status == "cancelled" else "failure",
                    result.error_message or result.error_type or result.status,
                    attempt.study_id,
                ),
            )
        self._refresh_busy_state()

    def _study_outcome(
        self,
        operation: str,
        status: str,
        message: str,
        study_id: str | None,
    ) -> StudyOperationOutcome:
        return StudyOperationOutcome(
            self._slot_id,
            self._session.session_id,
            operation,
            status,
            message,
            study_id,
        )

    def _invoke_study_completion(
        self,
        callback: Callable[[StudyOperationOutcome], None] | None,
        outcome: StudyOperationOutcome,
    ) -> None:
        if callback is None or not self._runtime_is_current():
            return
        try:
            callback(outcome)
        except Exception as error:
            self._log(
                f"Chart {self._slot_id} Study completion callback failed: {error}"
            )

    def _submit_environment_entry(self) -> None:
        run = self._environment_run
        dataset = self._session.dataset
        if run is None or dataset is None or not self._environment_run_is_current(run):
            self._rollback_environment(
                "Environment Apply target is stale", status="stale"
            )
            return
        if run.entry_index >= len(run.environment.entries):
            self._complete_environment_run()
            return
        entry = run.environment.entries[run.entry_index]
        request = self._environment_request(entry, run.entry_to_study or {})
        attempt = self._session.begin_study_apply()
        try:
            if isinstance(request, StudyExecutionRequest):
                submission = self._study_service.submit_calculation(
                    attempt,
                    dataset,
                    self._session.studies,
                    request,
                    progress_callback=self._on_study_progress,
                    result_callback=lambda result, run_id=run.run_id, item=entry, token=attempt: self._on_environment_entry_result(
                        result, token, run_id, item
                    ),
                    callback_dispatcher=self._dispatch,
                )
            else:
                submission = self._study_service.submit_artifact_apply(
                    attempt,
                    dataset,
                    request,
                    progress_callback=self._on_study_progress,
                    result_callback=lambda result, run_id=run.run_id, item=entry, token=attempt: self._on_environment_entry_result(
                        result, token, run_id, item
                    ),
                    callback_dispatcher=self._dispatch,
                )
        except Exception as error:
            self._session.settle_study_apply_failure(attempt)
            self._rollback_environment(
                f"Environment entry {entry.entry_id} submission failed: {error}"
            )
            return
        run.current_task_id = submission.task_id
        self._active_study_tasks[submission.task_id] = ("environment", attempt)
        self._changed()

    def _on_environment_entry_result(
        self,
        result: TaskResult,
        attempt: StudyApplyAttempt,
        run_id: str,
        entry: EnvironmentEntryV1,
    ) -> None:
        run = self._environment_run
        if (
            run is None
            or run.run_id != run_id
            or run.current_task_id != result.task_id
            or not self._environment_run_is_current(run)
        ):
            return
        run.current_task_id = None
        self._active_study_tasks.pop(result.task_id, None)
        if result.status != "completed" or not isinstance(result.value, PreparedStudy):
            self._session.settle_study_apply_failure(attempt)
            message = result.error_message or result.error_type or result.status
            self._rollback_environment(
                f"Environment entry {entry.entry_id} failed: {message}",
                status="cancellation" if result.status == "cancelled" else "failure",
            )
            return
        accepted = False
        try:
            accepted = self._session.accept_study_apply(attempt, result.value)
            study = result.value.study
            if not accepted:
                raise StudyValidationError("prepared Study was not current")
            if study.result.output_names != entry.expected_output_names:
                raise StudyValidationError("environment output names do not match")
            run.added_study_ids.append(study.study_id)
            run.entry_to_study[entry.entry_id] = study.study_id
            self._apply_environment_presentation(study.study_id, entry)
        except Exception as error:
            if accepted and result.value.study.study_id not in run.added_study_ids:
                run.added_study_ids.append(result.value.study.study_id)
            self._rollback_environment(
                f"Environment entry {entry.entry_id} publication failed: {error}"
            )
            return
        run.entry_index += 1
        self._refresh_study_state()
        self._submit_environment_entry()

    def _environment_request(
        self,
        entry: EnvironmentEntryV1,
        mapped: dict[str, str],
    ) -> StudyExecutionRequest | StudyArtifactRequest:
        if entry.mode == "artifact":
            return StudyArtifactRequest(
                entry.kind,
                entry.tool_key,
                entry.artifact_id,
                display_name=entry.display_name,
                user_metadata=entry.user_metadata,
            )
        sources = []
        for source in entry.sources:
            if source.source_kind == "ohlcv":
                sources.append(
                    StudyInputSource(
                        role=source.role,
                        source_kind="ohlcv",
                        column_name=source.column_name,
                    )
                )
            elif source.source_kind == "environment":
                study_id = mapped.get(source.source_entry_id or "")
                if study_id is None:
                    raise StudyValidationError("environment dependency was not accepted")
                sources.append(
                    StudyInputSource(
                        role=source.role,
                        source_kind="study",
                        study_id=study_id,
                        output_name=source.output_name,
                    )
                )
            else:
                sources.append(
                    StudyInputSource(
                        role=source.role,
                        source_kind="artifact",
                        artifact_kind=source.artifact_kind,
                        artifact_tool_key=source.artifact_tool_key,
                        artifact_id=source.artifact_id,
                        output_name=source.output_name,
                    )
                )
        return StudyExecutionRequest(
            entry.tool_key,
            entry.parameters,
            tuple(sources),
            display_name=entry.display_name,
            user_metadata=entry.user_metadata,
        )

    def _apply_environment_presentation(
        self, study_id: str, entry: EnvironmentEntryV1
    ) -> None:
        current = self._presentation(study_id)
        if current is None:
            raise StudyValidationError("accepted Study presentation is unavailable")
        expected_lines = tuple(current.signal_styles)
        supplied_lines = tuple(item.output_name for item in entry.presentation.line_styles)
        expected_fills = tuple(current.fill_styles)
        supplied_fills = tuple(item.fill_id for item in entry.presentation.fill_styles)
        expected_guides = tuple(current.guide_styles)
        supplied_guides = tuple(
            item.guide_id for item in entry.presentation.guide_styles
        )
        legacy_tdirsi_without_fill = (
            entry.tool_key == "tdirsi"
            and expected_lines == supplied_lines
            and expected_fills == ("tdirsi_band",)
            and supplied_fills == ()
        )
        if expected_lines != supplied_lines or (
            expected_fills != supplied_fills and not legacy_tdirsi_without_fill
        ) or (supplied_guides and expected_guides != supplied_guides):
            raise StudyValidationError("environment presentation styles do not match Study")
        self._session.set_study_visibility(study_id, entry.presentation.visible)
        for style in entry.presentation.line_styles:
            self._session.replace_study_line_style(study_id, style.output_name, style)
        for style in entry.presentation.fill_styles:
            self._session.replace_study_fill_style(study_id, style.fill_id, style)
        if entry.presentation.guide_styles:
            self._apply_guide_styles(
                study_id,
                entry.presentation.guide_styles,
            )

    def _complete_environment_run(self) -> None:
        run = self._environment_run
        if run is None:
            return
        if run.mode == "replace":
            try:
                for study_id in reversed(run.existing_study_ids):
                    self._session.remove_study(study_id)
            except Exception as error:
                self._rollback_environment(
                    f"Environment replace finalization failed: {error}"
                )
                return
        name = run.environment.display_name
        self._last_environment_entry_map = dict(run.entry_to_study or {})
        self._environment_run = None
        self._environment_report = None
        self._refresh_study_state()
        self._refresh_busy_state()
        self._set_status("Study Environment applied")
        self._log(f"Chart {self._slot_id} Study Environment applied: {name}.")
        self._dispatch_completion(run.completion_callback, "success")

    def _rollback_environment(self, message: str, *, status: str = "failure") -> None:
        run = self._environment_run
        if run is None:
            return
        for study_id in reversed(tuple(run.added_study_ids or ())):
            try:
                self._session.remove_study(study_id)
            except (KeyError, StudyDependencyError, StudyValidationError):
                pass
        if run.current_task_id is not None:
            self._active_study_tasks.pop(run.current_task_id, None)
        self._environment_run = None
        self._environment_report = None
        if self._runtime_is_current():
            self._refresh_study_state()
            self._refresh_busy_state()
            self._set_status("Study Environment failed")
            self._log(f"Chart {self._slot_id} {message}")
        self._dispatch_completion(run.completion_callback, status, message)

    def capture_snapshot_view_state(
        self,
        *,
        chart_ref: str,
        workspace_position: int,
        detached: bool,
    ) -> SnapshotChartCapture:
        self._require_current()
        dataset = self._session.dataset
        viewport = self._viewport
        interaction = self._interaction
        if dataset is None or viewport is None or interaction is None or self.is_busy:
            raise RuntimeError("chart must be idle with an accepted dataset and viewport")
        center_timestamp = self._session.timestamp_for_global_index(viewport.center_index)
        if center_timestamp is None:
            raise RuntimeError("viewport center timestamp is unavailable")
        scale = interaction.price_scale
        manual = scale.manual_range
        price = SnapshotPriceScaleV1(
            scale.autoscale_enabled,
            None if scale.autoscale_enabled else manual.low if manual is not None else scale.last_auto_range.low,
            None if scale.autoscale_enabled else manual.high if manual is not None else scale.last_auto_range.high,
        )
        return SnapshotChartCapture(
            chart_ref=chart_ref,
            workspace_position=workspace_position,
            detached=detached,
            market_id=dataset.market_id,
            dataset=dataset,
            studies=self._session.studies,
            presentations=self._session.study_presentations(),
            viewport=SnapshotViewportV1(center_timestamp, viewport.visible_count),
            price_scale=price,
            volume_visible=self._view.chart_workspace.volume_visible,
            pane_sizes=self._view.chart_workspace.snapshot_pane_sizes(),
        )

    def restore_snapshot_view_state(self, chart: SnapshotChartV1) -> None:
        self._require_current()
        if not isinstance(chart, SnapshotChartV1):
            raise TypeError("chart must be SnapshotChartV1")
        if self._viewport is None or self._interaction is None or self._session.dataset is None:
            raise RuntimeError("chart dataset and viewport are required")
        center = self._session.nearest_global_index_for_timestamp(
            chart.viewport.center_timestamp_ms
        )
        self._programmatic_navigation = True
        try:
            self._viewport.set_visible_anchored(chart.viewport.visible_count, center, 0.5)
            self._viewport.center_on_index(center)
            if chart.price_scale.autoscale_enabled:
                self._interaction.price_scale.reset_manual_range()
            else:
                self._interaction.price_scale.set_manual_range(
                    chart.price_scale.manual_low, chart.price_scale.manual_high
                )
            self.set_volume_visible(chart.volume_visible)
            entry_to_study = self._last_environment_entry_map
            runtime_sizes: dict[str, int] = {}
            for item in chart.pane_sizes:
                pane_ref = item.pane_ref
                if pane_ref.startswith("study:"):
                    entry_id = pane_ref.removeprefix("study:")
                    try:
                        pane_ref = f"oscillator:{entry_to_study[entry_id]}"
                    except KeyError as exc:
                        raise ValueError("Study pane entry was not restored") from exc
                runtime_sizes[pane_ref] = item.size
            self._view.chart_workspace.restore_pane_sizes(runtime_sizes)
            self._last_viewport_snapshot = self._viewport.snapshot()
            self._view.chart_workspace.refresh_from_shared_state()
            self._maybe_request_resident()
        finally:
            self._programmatic_navigation = False

    def _complete_dataset(self, status: str, message: str = "") -> None:
        callback = self._dataset_completion
        self._dataset_completion = None
        self._dispatch_completion(callback, status, message)

    def _dispatch_completion(self, callback, status: str, message: str = "") -> None:
        if callback is None:
            return
        outcome = ChartOperationOutcome(
            status, self._slot_id, self._session.session_id, message
        )
        self._dispatch(lambda: callback(outcome))

    def _environment_run_is_current(self, run: _EnvironmentRun) -> bool:
        return (
            self._runtime_is_current()
            and self._session.session_id == run.session_id
            and self._session.generation == run.generation
        )

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
        presentations = self._session.study_presentations()
        set_snapshot = getattr(self._view, "set_study_snapshot", None)
        if callable(set_snapshot):
            set_snapshot(
                projections,
                presentations,
                self._session.study_manager_entries(),
            )
        else:
            self._view.set_study_state(projections, presentations)
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
        had_active = self._active_load_task_id is not None or self._active_slice_task_id is not None
        self._cancel_task(self._active_load_task_id)
        self._cancel_task(self._active_slice_task_id)
        self._active_load_task_id = None
        self._active_slice_task_id = None
        self._open_attempt = None
        self._slice_attempt = None
        if had_active:
            self._complete_dataset("cancellation", "dataset operation superseded")

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
