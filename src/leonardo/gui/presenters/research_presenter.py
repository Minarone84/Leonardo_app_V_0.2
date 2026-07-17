"""Qt suite presenter for the eight-slot Research workspace."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.presenters.research_chart_presenter import ResearchChartPresenter
from leonardo.gui.windows.research_suite_window import ResearchSuiteWindow
from leonardo.gui.windows.study_style_dialog import StudyStylePatch
from leonardo.research import (
    ChartSessionState,
    DatasetCatalogReport,
    HorizontalViewport,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResearchWorkspaceState,
    ResearchWorkspaceStateError,
    StudyArtifactRequest,
    StudyExecutionRequest,
)

# ResearchChartPresenter retains ResidentRefillDirection and
# build_resident_volume_projection ownership from the accepted single-chart flow.


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
    """Coordinate shared catalog truth and active routing across chart slots."""

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
        self._workspace_state = ResearchWorkspaceState()
        self._chart_presenters: dict[int, ResearchChartPresenter] = {}
        self._active_catalog_task_id: str | None = None
        self._disposed = False
        self._wire()
        self.refresh_catalog()

    @property
    def workspace_state(self) -> ResearchWorkspaceState:
        return self._workspace_state

    @property
    def active_slot_id(self) -> int | None:
        return self._workspace_state.active_slot_id

    @property
    def session(self) -> ChartSessionState:
        session = self._workspace_state.active_session
        if session is None:
            raise RuntimeError("Research workspace has no active chart")
        return session

    @property
    def viewport(self) -> HorizontalViewport | None:
        slot_id = self.active_slot_id
        if slot_id is None:
            raise RuntimeError("Research workspace has no active chart")
        return self.chart_presenter(slot_id).viewport

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    def slot_ids(self) -> tuple[int, ...]:
        return self._workspace_state.slot_ids()

    def session_for(self, slot_id: int) -> ChartSessionState:
        return self._workspace_state.session_for(slot_id)

    def viewport_for(self, slot_id: int) -> HorizontalViewport | None:
        return self.chart_presenter(slot_id).viewport

    def chart_presenter(self, slot_id: int) -> ResearchChartPresenter:
        try:
            return self._chart_presenters[slot_id]
        except KeyError as error:
            raise ResearchWorkspaceStateError(
                f"Research chart slot {slot_id} is not occupied"
            ) from error

    def refresh_catalog(self) -> None:
        if self._disposed:
            return
        self._cancel_catalog()
        self._view.set_catalog_busy(True)
        self._view.set_status("Scanning accepted datasets")
        self._view.append_status("Scanning canonical OHLCV storage for accepted datasets...")
        try:
            submission = self._service.submit_catalog(
                progress_callback=self._on_catalog_progress,
                result_callback=self._on_catalog_result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        except Exception as error:
            self._view.set_catalog_busy(False)
            self._view.set_status("Catalog submission failed")
            self._view.append_status(f"Catalog submission failed: {error}")
            return
        self._active_catalog_task_id = submission.task_id

    def open_selected_dataset(self) -> None:
        if self._disposed:
            return
        market_id = self._view.selected_market_id()
        if market_id is None:
            self._view.append_status("No accepted dataset is selected.")
            return
        try:
            entry = self._workspace_state.create_chart()
        except ResearchWorkspaceStateError:
            self._view.set_status("Research workspace is full")
            self._view.append_status("Eight Research charts are already open.")
            self._refresh_active_view()
            return
        slot_id = entry.slot_id
        slot_widget = self._view.add_chart_slot(slot_id)
        presenter_ref: list[ResearchChartPresenter] = []

        def current_runtime() -> bool:
            return (
                not self._disposed
                and bool(presenter_ref)
                and self._chart_presenters.get(slot_id) is presenter_ref[0]
            )

        presenter = ResearchChartPresenter(
            slot_id,
            slot_widget,
            self._workspace_state.session_for(slot_id),
            self._service,
            self._study_service,
            self._dispatcher.dispatch,
            self._on_chart_state_changed,
            self._view.append_status,
            current_runtime,
        )
        presenter_ref.append(presenter)
        self._chart_presenters[slot_id] = presenter
        self._view.workspace_widget.set_active_slot(slot_id)
        self._refresh_active_view()
        try:
            presenter.open_dataset(market_id)
        except Exception:
            self._remove_chart(slot_id)
            self._refresh_active_view()

    def set_active_slot(self, slot_id: int) -> None:
        if self._disposed:
            return
        self._workspace_state.set_active(slot_id)
        self._view.workspace_widget.set_active_slot(slot_id)
        self._refresh_active_view()

    def close_active_chart(self) -> None:
        slot_id = self.active_slot_id
        if slot_id is not None:
            self._remove_chart(slot_id)
            self._refresh_active_view()

    def cancel_active_operation(self) -> None:
        if self._active_catalog_task_id is not None:
            cancelled = self._service.cancel(self._active_catalog_task_id)
            self._view.set_status("Cancellation requested")
            self._view.append_status(
                "Catalog cancellation requested."
                if cancelled
                else "Catalog operation already settled."
            )
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.cancel_active_operation()

    def submit_study_calculation(
        self, request: StudyExecutionRequest, *, slot_id: int | None = None
    ):
        return self._target_presenter(slot_id).submit_study_calculation(request)

    def submit_artifact_apply(
        self, request: StudyArtifactRequest, *, slot_id: int | None = None
    ):
        return self._target_presenter(slot_id).submit_artifact_apply(request)

    def _save_study(self, study_id: str) -> None:
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.save_study(study_id)

    def _set_study_visibility(self, study_id: str, visible: bool) -> None:
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.set_study_visibility(study_id, visible)

    def _open_study_style(self, study_id: str) -> None:
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.open_study_style(study_id)

    def _apply_style_patch(self, patch: StudyStylePatch) -> None:
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.apply_style_patch(patch)

    def _reset_study_style(self, study_id: str) -> None:
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.reset_study_style(study_id)

    def _remove_study(self, study_id: str) -> None:
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.remove_study(study_id)

    def toggle_active_autoscale(self) -> None:
        presenter = self._active_presenter()
        if presenter is None:
            return
        presenter.set_autoscale_enabled(not presenter.chart_widget.autoscale_enabled)

    def toggle_active_volume(self) -> None:
        presenter = self._active_presenter()
        if presenter is None:
            return
        workspace = presenter.chart_workspace
        presenter.set_volume_visible(not workspace.volume_visible)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._cancel_catalog()
        for presenter in tuple(self._chart_presenters.values()):
            presenter.dispose()
        self._chart_presenters.clear()
        self._workspace_state.dispose()
        self._view.workspace_widget.clear()
        self._view.set_active_chart_state(None, (), False, False, False, False, "")

    def _wire(self) -> None:
        self._view.refresh_requested.connect(self.refresh_catalog)
        self._view.open_requested.connect(self.open_selected_dataset)
        self._view.cancel_requested.connect(self.cancel_active_operation)
        self._view.close_active_requested.connect(self.close_active_chart)
        self._view.autoscale_requested.connect(self.toggle_active_autoscale)
        self._view.volume_requested.connect(self.toggle_active_volume)
        self._view.closed.connect(self.dispose)
        self._view.workspace_widget.active_slot_requested.connect(self.set_active_slot)
        manager = self._view.study_manager
        manager.visibility_requested.connect(self._set_study_visibility)
        manager.style_requested.connect(self._open_study_style)
        manager.reset_style_requested.connect(self._reset_study_style)
        manager.save_requested.connect(self._save_study)
        manager.remove_requested.connect(self._remove_study)

    def _on_catalog_progress(self, progress: TaskProgress) -> None:
        if self._disposed or progress.task_id != self._active_catalog_task_id:
            return
        self._view.set_status(progress.message)
        self._view.set_progress(progress.current, progress.total)

    def _on_catalog_result(self, result: TaskResult) -> None:
        if self._disposed or result.task_id != self._active_catalog_task_id:
            return
        self._active_catalog_task_id = None
        self._view.set_catalog_busy(False)
        if result.status == "completed" and isinstance(result.value, DatasetCatalogReport):
            report = result.value
            self._view.set_catalog(report.accepted)
            self._view.set_status(f"Ready - {report.accepted_count} accepted dataset(s)")
            self._view.append_status(
                f"Catalog ready: {report.accepted_count} accepted, "
                f"{report.rejected_count} refused."
            )
            self._refresh_active_view()
            return
        self._handle_catalog_failure(result)

    def _on_chart_state_changed(self, slot_id: int) -> None:
        if self._disposed or slot_id not in self._chart_presenters:
            return
        if slot_id == self.active_slot_id:
            self._refresh_active_view()

    def _refresh_active_view(self) -> None:
        presenter = self._active_presenter()
        if presenter is None:
            self._view.workspace_widget.set_active_slot(None)
            self._view.set_active_chart_state(None, (), False, False, False, False, "")
            self._view.set_workspace_full(self._workspace_state.is_full)
            return
        session = presenter.session
        self._view.workspace_widget.set_active_slot(presenter.slot_id)
        chart = presenter.chart_widget
        workspace = presenter.chart_workspace
        self._view.set_active_chart_state(
            presenter.slot_id,
            session.study_manager_entries(),
            presenter.is_busy,
            chart.autoscale_enabled,
            workspace.volume_visible,
            workspace.volume_chart.projection is not None,
            presenter.status_text,
        )
        self._view.set_active_chart_market(session.selected_market_id)
        self._view.set_workspace_full(self._workspace_state.is_full)

    def _remove_chart(self, slot_id: int) -> None:
        presenter = self._chart_presenters.pop(slot_id, None)
        if presenter is None:
            return
        presenter.dispose()
        self._workspace_state.remove_chart(slot_id)
        self._view.remove_chart_slot(slot_id)

    def _active_presenter(self) -> ResearchChartPresenter | None:
        slot_id = self.active_slot_id
        return None if slot_id is None else self._chart_presenters.get(slot_id)

    def _target_presenter(self, slot_id: int | None) -> ResearchChartPresenter:
        if slot_id is None:
            presenter = self._active_presenter()
            if presenter is None:
                raise RuntimeError("Research workspace has no active chart")
            return presenter
        return self.chart_presenter(slot_id)

    def _cancel_catalog(self) -> None:
        if self._active_catalog_task_id is not None:
            self._service.cancel(self._active_catalog_task_id)
        self._active_catalog_task_id = None

    def _handle_catalog_failure(self, result: TaskResult) -> None:
        if result.status == "cancelled":
            self._view.set_status("Catalog cancelled")
            self._view.append_status("Catalog cancelled.")
            return
        message = result.error_message or result.error_type or "unknown error"
        self._view.set_status("Catalog failed")
        self._view.append_status(f"Catalog failed: {message}")
