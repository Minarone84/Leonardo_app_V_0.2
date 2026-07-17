"""Qt suite presenter for the eight-slot Research workspace."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.presenters.research_chart_presenter import ResearchChartPresenter
from leonardo.gui.windows.research_suite_window import ResearchSuiteWindow
from leonardo.gui.windows.study_environment_manager_dialog import (
    EnvironmentApplyIntent,
    EnvironmentCompatibilityIntent,
    EnvironmentManagerDialog,
    EnvironmentMetadataIntent,
    EnvironmentTarget,
)
from leonardo.gui.windows.study_environment_save_dialog import (
    EnvironmentSaveDialog,
    EnvironmentSaveIntent,
)
from leonardo.gui.windows.study_setup_dialog import StudySetupDialog
from leonardo.gui.windows.study_style_dialog import StudyStylePatch
from leonardo.research import (
    ChartSessionState,
    DatasetCatalogReport,
    HorizontalViewport,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResearchStudySetupApplicationService,
    ResearchWorkspaceState,
    ResearchWorkspaceStateError,
    ResearchWorkspaceShellState,
    ResearchWorkspaceShellStateError,
    StudyArtifactRequest,
    StudyExecutionRequest,
)
from leonardo.research.study_environment import (
    EnvironmentCompatibilityReport,
    EnvironmentSummary,
    EnvironmentV1,
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
        study_setup_service: ResearchStudySetupApplicationService | None = None,
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
        if study_setup_service is not None and not isinstance(
            study_setup_service, ResearchStudySetupApplicationService
        ):
            raise TypeError(
                "study_setup_service must be ResearchStudySetupApplicationService or None"
            )
        self._study_setup_service = study_setup_service
        self._dispatcher = _QtCallbackDispatcher(self)
        self._workspace_state = ResearchWorkspaceState()
        self._shell_state = ResearchWorkspaceShellState()
        self._chart_presenters: dict[int, ResearchChartPresenter] = {}
        self._active_catalog_task_id: str | None = None
        self._disposed = False
        self._pan_anchor_enabled = False
        self._pan_anchor_in_progress = False
        self._setup_task_ids: set[str] = set()
        self._setup_dialogs: list[StudySetupDialog] = []
        self._save_dialogs: list[EnvironmentSaveDialog] = []
        self._environment_managers: list[EnvironmentManagerDialog] = []
        self._wire()
        self._view.set_study_setup_available(study_setup_service is not None)
        self.refresh_catalog()

    @property
    def workspace_state(self) -> ResearchWorkspaceState:
        return self._workspace_state

    @property
    def active_slot_id(self) -> int | None:
        return self._workspace_state.active_slot_id

    @property
    def shell_state(self) -> ResearchWorkspaceShellState:
        return self._shell_state

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
        self._shell_state.register_slot(slot_id)
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
            self._on_horizontal_pan,
        )
        presenter_ref.append(presenter)
        self._chart_presenters[slot_id] = presenter
        slot_widget.position_change_requested.connect(self.move_slot)
        slot_widget.go_to_requested.connect(self.open_go_to)
        slot_widget.detach_requested.connect(self.detach_slot)
        slot_widget.dock_requested.connect(self.dock_slot)
        self._sync_shell_view()
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

    def move_slot(self, slot_id: int, target_position: int) -> None:
        if self._disposed or slot_id not in self._chart_presenters:
            return
        try:
            self._shell_state.move_slot(slot_id, target_position)
        except ResearchWorkspaceShellStateError as error:
            self._view.append_status(f"Chart {slot_id} move blocked: {error}")
        self._sync_shell_view()

    def detach_slot(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if self._disposed or presenter is None:
            return
        placement = self._shell_state.detach_slot(slot_id)
        if self._view.floating_chart_window(slot_id) is None:
            getattr(self._view, "detach_" "chart_slot")(
                slot_id, presenter.session.session_id
            )
        self._sync_shell_view()
        self.set_active_slot(slot_id)

    def dock_slot(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if self._disposed or presenter is None:
            return
        window = self._view.floating_chart_window(slot_id)
        if window is None or window.session_id != presenter.session.session_id:
            return
        getattr(self._view, "dock_" "chart_slot")(
            slot_id, presenter.session.session_id
        )
        self._shell_state.dock_slot(slot_id)
        self._sync_shell_view()
        self.set_active_slot(slot_id)

    def open_go_to(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if self._disposed or presenter is None:
            return
        market = presenter.session.selected_market_id
        if market is None:
            return
        self._view.open_go_to_dialog(
            slot_id,
            presenter.session.session_id,
            market.as_key(),
            market.timeframe,
        )

    def set_pan_anchor_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._pan_anchor_enabled = enabled

    def cancel_active_operation(self) -> None:
        if self._setup_task_ids and self._study_setup_service is not None:
            for task_id in tuple(self._setup_task_ids):
                self._study_setup_service.cancel(task_id)
            self._view.set_status("Study Setup cancellation requested")
            return
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

    def open_study_setup(self) -> None:
        service = self._study_setup_service
        presenter = self._active_presenter()
        if service is None or presenter is None or presenter.environment_apply_active:
            return
        dataset = presenter.session.dataset
        if dataset is None:
            return
        slot_id = presenter.slot_id
        session_id = presenter.session.session_id
        self._submit_setup_task(
            lambda callback: service.submit_catalog(
                dataset,
                presenter.session.studies,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._open_setup_dialog_result(
                result, slot_id, session_id
            ),
        )

    def open_save_environment(self) -> None:
        service = self._study_setup_service
        presenter = self._active_presenter()
        if (
            service is None
            or presenter is None
            or presenter.environment_apply_active
            or not presenter.session.studies
        ):
            return
        slot_id = presenter.slot_id
        session_id = presenter.session.session_id
        studies = presenter.session.studies
        presentations = presenter.session.study_presentations()
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._open_save_dialog_result(
                result,
                slot_id,
                session_id,
                studies,
                presentations,
            ),
        )

    def open_environment_manager(self) -> None:
        service = self._study_setup_service
        if service is None:
            return
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._open_environment_manager_result,
        )

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
        if self._study_setup_service is not None:
            for task_id in tuple(self._setup_task_ids):
                self._study_setup_service.cancel(task_id)
        self._setup_task_ids.clear()
        for dialog in (*self._setup_dialogs, *self._save_dialogs, *self._environment_managers):
            dialog.close()
        self._setup_dialogs.clear()
        self._save_dialogs.clear()
        self._environment_managers.clear()
        self._view.close_all_floating_charts()
        for presenter in tuple(self._chart_presenters.values()):
            presenter.dispose()
        self._chart_presenters.clear()
        self._workspace_state.dispose()
        self._shell_state.clear()
        self._view.workspace_widget.clear()
        self._view.set_active_chart_state(None, (), False, False, False, False, "")

    def _wire(self) -> None:
        self._view.refresh_requested.connect(self.refresh_catalog)
        self._view.open_requested.connect(self.open_selected_dataset)
        self._view.cancel_requested.connect(self.cancel_active_operation)
        self._view.close_active_requested.connect(self.close_active_chart)
        self._view.autoscale_requested.connect(self.toggle_active_autoscale)
        self._view.volume_requested.connect(self.toggle_active_volume)
        self._view.pan_anchor_toggled.connect(self.set_pan_anchor_enabled)
        self._view.floating_dock_requested.connect(self.dock_slot)
        self._view.floating_close_requested.connect(self._on_floating_close)
        self._view.go_to_accepted.connect(self._on_go_to_accepted)
        self._view.add_study_requested.connect(self.open_study_setup)
        self._view.save_environment_requested.connect(self.open_save_environment)
        self._view.study_environments_requested.connect(self.open_environment_manager)
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
            dataset_ready=session.dataset is not None,
            environment_apply_active=presenter.environment_apply_active,
        )
        self._view.set_active_chart_market(session.selected_market_id)
        self._view.set_workspace_full(self._workspace_state.is_full)

    def _remove_chart(self, slot_id: int) -> None:
        presenter = self._chart_presenters.pop(slot_id, None)
        if presenter is None:
            return
        presenter.dispose()
        self._view.close_floating_chart(slot_id)
        self._workspace_state.remove_chart(slot_id)
        self._shell_state.remove_slot(slot_id)
        self._view.remove_chart_slot(slot_id)
        self._sync_shell_view()

    def _sync_shell_view(self) -> None:
        for placement in self._shell_state.placements():
            self._view.set_slot_placement(
                placement.slot_id,
                placement.workspace_position,
                placement.detached,
            )
        self._view.apply_attached_slot_order(self._shell_state.attached_slot_ids())

    def _on_floating_close(self, slot_id: int, session_id: str) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None or presenter.session.session_id != session_id:
            return
        self._remove_chart(slot_id)
        self._refresh_active_view()

    def _on_go_to_accepted(
        self, slot_id: int, session_id: str, timestamp_ms: int
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None or presenter.session.session_id != session_id:
            return
        presenter.go_to_timestamp_ms(timestamp_ms)
        if slot_id == self.active_slot_id:
            self._refresh_active_view()

    def _on_horizontal_pan(self, source_slot_id: int) -> None:
        if (
            not self._pan_anchor_enabled
            or self._pan_anchor_in_progress
            or source_slot_id not in self._chart_presenters
        ):
            return
        timestamp_ms = self._chart_presenters[
            source_slot_id
        ].current_center_timestamp_ms()
        if timestamp_ms is None:
            return
        self._pan_anchor_in_progress = True
        try:
            for slot_id, presenter in tuple(self._chart_presenters.items()):
                if (
                    slot_id == source_slot_id
                    or presenter.is_disposed
                    or presenter.session.dataset is None
                    or presenter.viewport is None
                ):
                    continue
                presenter.center_on_timestamp_ms(timestamp_ms)
        finally:
            self._pan_anchor_in_progress = False

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

    def _submit_setup_task(self, submit, handler) -> None:
        if self._disposed:
            return
        task_ref: list[str] = []
        settled = [False]

        def callback(result: TaskResult) -> None:
            settled[0] = True
            task_id = task_ref[0] if task_ref else result.task_id
            self._setup_task_ids.discard(task_id)
            if not self._disposed:
                handler(result)

        try:
            submission = submit(callback)
        except Exception as error:
            self._view.append_status(f"Study Setup submission failed: {error}")
            return
        task_ref.append(submission.task_id)
        if not settled[0]:
            self._setup_task_ids.add(submission.task_id)

    def _open_setup_dialog_result(
        self, result: TaskResult, slot_id: int, session_id: str
    ) -> None:
        from leonardo.research import StudySetupCatalog

        presenter = self._chart_presenters.get(slot_id)
        if (
            result.status != "completed"
            or not isinstance(result.value, StudySetupCatalog)
            or presenter is None
            or presenter.session.session_id != session_id
        ):
            return
        dialog = StudySetupDialog(result.value, self._view)
        self._setup_dialogs.append(dialog)
        dialog.request_submitted.connect(
            lambda request: self._accept_setup_request(
                slot_id, session_id, request
            )
        )
        dialog.finished.connect(
            lambda _code, current=dialog: self._forget_dialog(
                self._setup_dialogs, current
            )
        )
        dialog.show()

    def _accept_setup_request(self, slot_id: int, session_id: str, request) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None or presenter.session.session_id != session_id:
            return
        try:
            if isinstance(request, StudyExecutionRequest):
                presenter.submit_study_calculation(request)
            elif isinstance(request, StudyArtifactRequest):
                presenter.submit_artifact_apply(request)
        except (RuntimeError, TypeError, ValueError) as error:
            self._view.append_status(f"Chart {slot_id} Study Setup failed: {error}")

    def _open_save_dialog_result(
        self,
        result: TaskResult,
        slot_id: int,
        session_id: str,
        studies,
        presentations,
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            result.status != "completed"
            or presenter is None
            or presenter.session.session_id != session_id
            or not isinstance(result.value, tuple)
            or not all(isinstance(item, EnvironmentSummary) for item in result.value)
        ):
            return
        dialog = EnvironmentSaveDialog(
            slot_id, session_id, tuple(studies), result.value, self._view
        )
        self._save_dialogs.append(dialog)
        dialog.save_requested.connect(
            lambda intent: self._save_environment_intent(
                intent, tuple(studies), tuple(presentations)
            )
        )
        dialog.finished.connect(
            lambda _code, current=dialog: self._forget_dialog(
                self._save_dialogs, current
            )
        )
        dialog.show()

    def _save_environment_intent(
        self,
        intent: EnvironmentSaveIntent,
        studies,
        presentations,
    ) -> None:
        service = self._study_setup_service
        presenter = self._chart_presenters.get(intent.slot_id)
        if (
            service is None
            or presenter is None
            or presenter.session.session_id != intent.session_id
            or presenter.session.dataset is None
        ):
            return
        self._submit_setup_task(
            lambda callback: service.submit_save_chart_environment(
                presenter.session.dataset,
                studies,
                presentations,
                display_name=intent.display_name,
                description=intent.description,
                environment_id=intent.environment_id,
                metadata_overrides=dict(intent.metadata_overrides),
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._environment_save_result(
                result, intent.slot_id, intent.session_id
            ),
        )

    def _environment_save_result(
        self, result: TaskResult, slot_id: int, session_id: str
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None or presenter.session.session_id != session_id:
            return
        if result.status == "completed" and isinstance(result.value, EnvironmentV1):
            self._view.append_status(
                f"Chart {slot_id} Study Environment saved: {result.value.display_name}."
            )
        else:
            self._view.append_status(
                f"Chart {slot_id} Study Environment save failed: "
                f"{result.error_message or result.error_type or result.status}"
            )

    def _open_environment_manager_result(self, result: TaskResult) -> None:
        if (
            result.status != "completed"
            or not isinstance(result.value, tuple)
            or not all(isinstance(item, EnvironmentSummary) for item in result.value)
        ):
            return
        targets = tuple(
            EnvironmentTarget(
                slot_id,
                presenter.session.session_id,
                f"Chart {slot_id}",
                self._shell_state.placement_for(slot_id).detached,
            )
            for slot_id, presenter in sorted(self._chart_presenters.items())
            if presenter.session.dataset is not None
        )
        dialog = EnvironmentManagerDialog(result.value, targets, self._view)
        self._environment_managers.append(dialog)
        dialog.environment_selected.connect(
            lambda environment_id: self._load_manager_environment(
                dialog, environment_id
            )
        )
        dialog.refresh_requested.connect(
            lambda: self._refresh_environment_manager(dialog)
        )
        dialog.compatibility_requested.connect(
            lambda intent: self._check_manager_compatibility(dialog, intent)
        )
        dialog.metadata_save_requested.connect(
            lambda intent: self._save_manager_metadata(dialog, intent)
        )
        dialog.apply_requested.connect(
            lambda intent: self._apply_manager_environment(dialog, intent)
        )
        dialog.delete_requested.connect(
            lambda environment_id: self._delete_manager_environment(
                dialog, environment_id
            )
        )
        dialog.finished.connect(
            lambda _code, current=dialog: self._forget_dialog(
                self._environment_managers, current
            )
        )
        if dialog.selected_environment_id is not None:
            self._load_manager_environment(
                dialog, dialog.selected_environment_id
            )
        dialog.show()

    def _load_manager_environment(
        self, dialog: EnvironmentManagerDialog, environment_id: str
    ) -> None:
        service = self._study_setup_service
        if service is None or dialog not in self._environment_managers:
            return
        self._submit_setup_task(
            lambda callback: service.submit_load_environment(
                environment_id,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_environment(result.value)
            if (
                dialog in self._environment_managers
                and result.status == "completed"
                and isinstance(result.value, EnvironmentV1)
                and dialog.selected_environment_id == environment_id
            )
            else None,
        )

    def _refresh_environment_manager(
        self, dialog: EnvironmentManagerDialog
    ) -> None:
        service = self._study_setup_service
        if service is None or dialog not in self._environment_managers:
            return
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_summaries(result.value)
            if (
                dialog in self._environment_managers
                and result.status == "completed"
                and isinstance(result.value, tuple)
            )
            else None,
        )

    def _check_manager_compatibility(
        self,
        dialog: EnvironmentManagerDialog,
        intent: EnvironmentCompatibilityIntent,
    ) -> None:
        service = self._study_setup_service
        presenter = self._chart_presenters.get(intent.slot_id)
        environment = dialog.environment
        if (
            service is None
            or presenter is None
            or presenter.session.session_id != intent.session_id
            or presenter.session.dataset is None
            or environment is None
            or environment.environment_id != intent.environment_id
        ):
            return
        self._submit_setup_task(
            lambda callback: service.submit_compatibility(
                environment,
                presenter.session.dataset,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._manager_compatibility_result(
                dialog, intent, result
            ),
        )

    def _manager_compatibility_result(
        self,
        dialog: EnvironmentManagerDialog,
        intent: EnvironmentCompatibilityIntent,
        result: TaskResult,
    ) -> None:
        presenter = self._chart_presenters.get(intent.slot_id)
        if (
            dialog not in self._environment_managers
            or presenter is None
            or presenter.session.session_id != intent.session_id
            or result.status != "completed"
            or not isinstance(result.value, EnvironmentCompatibilityReport)
        ):
            return
        presenter.set_environment_compatibility(result.value)
        dialog.set_compatibility(intent, result.value)

    def _save_manager_metadata(
        self,
        dialog: EnvironmentManagerDialog,
        intent: EnvironmentMetadataIntent,
    ) -> None:
        service = self._study_setup_service
        if service is None:
            return
        self._submit_setup_task(
            lambda callback: service.submit_update_environment(
                intent.environment_id,
                intent.draft,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_environment(result.value)
            if (
                dialog in self._environment_managers
                and result.status == "completed"
                and isinstance(result.value, EnvironmentV1)
            )
            else None,
        )

    def _apply_manager_environment(
        self,
        dialog: EnvironmentManagerDialog,
        intent: EnvironmentApplyIntent,
    ) -> None:
        presenter = self._chart_presenters.get(intent.slot_id)
        environment = dialog.environment
        if (
            presenter is None
            or presenter.session.session_id != intent.session_id
            or environment is None
            or environment.environment_id != intent.environment_id
        ):
            return
        try:
            presenter.apply_environment(environment, intent.mode)
        except (RuntimeError, TypeError, ValueError) as error:
            self._view.append_status(
                f"Chart {intent.slot_id} Study Environment Apply failed: {error}"
            )

    def _delete_manager_environment(
        self, dialog: EnvironmentManagerDialog, environment_id: str
    ) -> None:
        service = self._study_setup_service
        if service is None:
            return
        self._submit_setup_task(
            lambda callback: service.submit_delete_environment(
                environment_id,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda _result: self._refresh_environment_manager(dialog)
            if dialog in self._environment_managers
            else None,
        )

    @staticmethod
    def _forget_dialog(collection: list, dialog) -> None:
        if dialog in collection:
            collection.remove(dialog)

    def _handle_catalog_failure(self, result: TaskResult) -> None:
        if result.status == "cancelled":
            self._view.set_status("Catalog cancelled")
            self._view.append_status("Catalog cancelled.")
            return
        message = result.error_message or result.error_type or "unknown error"
        self._view.set_status("Catalog failed")
        self._view.append_status(f"Catalog failed: {message}")
