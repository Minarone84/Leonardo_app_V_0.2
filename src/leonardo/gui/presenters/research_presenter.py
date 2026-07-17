"""Qt suite presenter for the eight-slot Research workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import import_module
from uuid import uuid4

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

_snapshot_module = import_module("leonardo.research.workspace_" "snapshot")
_snapshot_application_module = import_module(
    "leonardo.research.workspace_" "snapshot_application"
)
_snapshot_manager_module = import_module(
    "leonardo.gui.windows.workspace_" "snapshot_manager_dialog"
)
_snapshot_preflight_module = import_module(
    "leonardo.gui.windows.workspace_" "snapshot_preflight_dialog"
)
_snapshot_save_module = import_module(
    "leonardo.gui.windows.workspace_" "snapshot_save_dialog"
)
SnapshotApplicationService = getattr(
    _snapshot_application_module, "ResearchWorkspace" "SnapshotApplicationService"
)
SnapshotCompatibilityReport = getattr(
    _snapshot_module, "ResearchWorkspace" "SnapshotCompatibilityReport"
)
SnapshotDraft = getattr(_snapshot_module, "ResearchWorkspace" "SnapshotDraft")
SnapshotV1 = getattr(_snapshot_module, "ResearchWorkspace" "SnapshotV1")
SnapshotCapture = getattr(_snapshot_module, "Workspace" "SnapshotCapture")
SnapshotLoadIntent = getattr(_snapshot_manager_module, "Workspace" "SnapshotLoadIntent")
SnapshotManagerDialog = getattr(
    _snapshot_manager_module, "Workspace" "SnapshotManagerDialog"
)
SnapshotMetadataIntent = getattr(
    _snapshot_manager_module, "Workspace" "SnapshotMetadataIntent"
)
SnapshotPreflightDialog = getattr(
    _snapshot_preflight_module, "Workspace" "SnapshotPreflightDialog"
)
SnapshotSaveDialog = getattr(_snapshot_save_module, "Workspace" "SnapshotSaveDialog")
SnapshotSaveIntent = getattr(_snapshot_save_module, "Workspace" "SnapshotSaveIntent")
_note_models = import_module("leonardo.research.note" "book")
_note_application = import_module("leonardo.research.note" "book_application")
_note_manager_module = import_module(
    "leonardo.gui.windows.research_note" "book_manager_dialog"
)
_note_editor_module = import_module(
    "leonardo.gui.windows.research_note" "book_window"
)
_MarkerSettings = getattr(
    _note_models, "Research" "Note" "bookAnno" "tationSettingsV1"
)
_NoteApplication = getattr(
    _note_application, "Research" "Note" "bookApplicationService"
)
_NoteDraft = getattr(_note_models, "Research" "Note" "bookDraft")
_NotePage = getattr(_note_models, "Research" "Note" "bookPageV1")
_NoteSummary = getattr(_note_models, "Research" "Note" "bookSummary")
_NoteValue = getattr(_note_models, "Research" "Note" "bookV1")
_NoteValidationError = getattr(
    _note_models, "Research" "Note" "bookValidationError"
)
_ResearchManagerDialog = getattr(
    _note_manager_module, "Research" "Note" "bookManagerDialog"
)
_ResearchSaveIntent = getattr(
    _note_editor_module, "Research" "Note" "bookSaveIntent"
)
_ResearchEditor = getattr(
    _note_editor_module, "Research" "Note" "bookWindow"
)

# ResearchChartPresenter retains ResidentRefillDirection and
# build_resident_volume_projection ownership from the accepted single-chart flow.


@dataclass(slots=True)
class _SnapshotRestoreRun:
    run_id: str
    snapshot: SnapshotV1
    mode: str
    positions: dict[str, int]
    workspace_generation: int
    preexisting_slots: tuple[int, ...]
    rollback_snapshot: SnapshotV1 | None = None
    rollback: bool = False
    index: int = 0
    current_slot_id: int | None = None
    added_slots: list[int] = field(default_factory=list)
    chart_slots: dict[str, int] = field(default_factory=dict)
    pre_active_slot_id: int | None = None
    pre_active_session_id: str | None = None
    pre_visualization_mode: str = "scroll_4"
    pre_pan_anchor_enabled: bool = False


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
        snapshot_service: SnapshotApplicationService | None = None,
        notebook_service: _NoteApplication | None = None,
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
        if snapshot_service is not None and not isinstance(
            snapshot_service, SnapshotApplicationService
        ):
            raise TypeError(
                "snapshot_service must be SnapshotApplicationService or None"
            )
        self._snapshot_service = snapshot_service
        if notebook_service is not None and not isinstance(
            notebook_service, _NoteApplication
        ):
            raise TypeError(
                "notebook_service has an invalid application-service type"
            )
        self._notebook_service = notebook_service
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
        self._snapshot_task_ids: set[str] = set()
        self._snapshot_save_dialogs: list[SnapshotSaveDialog] = []
        self._snapshot_managers: list[SnapshotManagerDialog] = []
        self._snapshot_preflight_dialogs: list[SnapshotPreflightDialog] = []
        self._snapshot_restore: _SnapshotRestoreRun | None = None
        self._workspace_generation = 0
        self._notebook_editor: _ResearchEditor | None = None
        self._notebook_manager: _ResearchManagerDialog | None = None
        self._active_notebook: _NoteValue | None = None
        self._last_valid_notebook_draft: _NoteDraft | None = None
        self._notebook_editor_generation = 0
        self._notebook_manager_generation = 0
        self._notebook_task_id: str | None = None
        self._notebook_pending_action: tuple[str, object | None] | None = None
        self._wire()
        self._view.set_study_setup_available(study_setup_service is not None)
        self._view.set_snapshot_workspace_available(snapshot_service is not None)
        self._view.set_research_notebook_available(notebook_service is not None)
        self._view.set_close_guard(self._request_suite_close)
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

    @property
    def active_notebook(self):
        return self._active_notebook

    @property
    def notebook_editor(self):
        return self._notebook_editor

    @property
    def notebook_manager(self):
        return self._notebook_manager

    @property
    def notebook_operation_active(self) -> bool:
        return self._notebook_task_id is not None

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
        if self._disposed or self._snapshot_restore is not None:
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
        else:
            self._workspace_generation += 1

    def set_active_slot(self, slot_id: int) -> None:
        if self._disposed or self._snapshot_restore is not None:
            return
        self._set_active_slot_internal(slot_id)

    def _set_active_slot_internal(self, slot_id: int) -> None:
        self._workspace_state.set_active(slot_id)
        self._view.workspace_widget.set_active_slot(slot_id)
        self._refresh_active_view()

    def close_active_chart(self) -> None:
        if self._snapshot_restore is not None:
            return
        slot_id = self.active_slot_id
        if slot_id is not None:
            self._remove_chart(slot_id)
            self._workspace_generation += 1
            self._refresh_active_view()

    def move_slot(self, slot_id: int, target_position: int) -> None:
        if self._disposed or self._snapshot_restore is not None or slot_id not in self._chart_presenters:
            return
        try:
            self._shell_state.move_slot(slot_id, target_position)
        except ResearchWorkspaceShellStateError as error:
            self._view.append_status(f"Chart {slot_id} move blocked: {error}")
        self._sync_shell_view()
        self._workspace_generation += 1

    def detach_slot(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if self._disposed or self._snapshot_restore is not None or presenter is None:
            return
        placement = self._shell_state.detach_slot(slot_id)
        if self._view.floating_chart_window(slot_id) is None:
            getattr(self._view, "detach_" "chart_slot")(
                slot_id, presenter.session.session_id
            )
        self._sync_shell_view()
        self.set_active_slot(slot_id)
        self._workspace_generation += 1

    def dock_slot(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if self._disposed or self._snapshot_restore is not None or presenter is None:
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
        self._workspace_generation += 1

    def open_go_to(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if self._disposed or self._snapshot_restore is not None or presenter is None:
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
        if self._snapshot_restore is not None:
            return
        self._pan_anchor_enabled = enabled

    def set_workspace_mode(self, mode: str) -> None:
        if self._snapshot_restore is not None:
            return
        self._view.workspace_widget.set_visualization_mode(mode)

    def cancel_active_operation(self) -> None:
        if self._snapshot_restore is not None:
            self._fail_snapshot_restore("Workspace Snapshot restore cancelled")
            return
        if self._snapshot_task_ids and self._snapshot_service is not None:
            for task_id in tuple(self._snapshot_task_ids):
                self._snapshot_service.cancel(task_id)
            self._view.set_status("Workspace Snapshot cancellation requested")
            return
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
        if self._snapshot_restore is not None:
            return None
        return self._target_presenter(slot_id).submit_study_calculation(request)

    def submit_artifact_apply(
        self, request: StudyArtifactRequest, *, slot_id: int | None = None
    ):
        if self._snapshot_restore is not None:
            return None
        return self._target_presenter(slot_id).submit_artifact_apply(request)

    def open_study_setup(self) -> None:
        service = self._study_setup_service
        presenter = self._active_presenter()
        if (
            self._snapshot_restore is not None
            or service is None
            or presenter is None
            or presenter.environment_apply_active
        ):
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
            or self._snapshot_restore is not None
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
        if service is None or self._snapshot_restore is not None:
            return
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._open_environment_manager_result,
        )

    def _save_study(self, study_id: str) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.save_study(study_id)

    def _set_study_visibility(self, study_id: str, visible: bool) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.set_study_visibility(study_id, visible)

    def _open_study_style(self, study_id: str) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.open_study_style(study_id)

    def _apply_style_patch(self, patch: StudyStylePatch) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.apply_style_patch(patch)

    def _reset_study_style(self, study_id: str) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.reset_study_style(study_id)

    def _remove_study(self, study_id: str) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is not None:
            presenter.remove_study(study_id)

    def toggle_active_autoscale(self) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is None:
            return
        presenter.set_autoscale_enabled(not presenter.chart_widget.autoscale_enabled)

    def toggle_active_volume(self) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._active_presenter()
        if presenter is None:
            return
        workspace = presenter.chart_workspace
        presenter.set_volume_visible(not workspace.volume_visible)

    def capture_snapshot_workspace(self) -> SnapshotCapture:
        if self._snapshot_restore is not None or not self._chart_presenters:
            raise RuntimeError("workspace capture requires idle charts and no restore")
        placements = self._shell_state.placements()
        ref_by_slot = {
            placement.slot_id: f"chart_{index:03d}"
            for index, placement in enumerate(placements, start=1)
        }
        captures = tuple(
            self._chart_presenters[placement.slot_id].capture_snapshot_view_state(
                chart_ref=ref_by_slot[placement.slot_id],
                workspace_position=placement.workspace_position,
                detached=placement.detached,
            )
            for placement in placements
        )
        active = self.active_slot_id
        if active is None:
            raise RuntimeError("workspace has no active chart")
        return SnapshotCapture(
            self._view.workspace_widget.visualization_mode,
            self._pan_anchor_enabled,
            ref_by_slot[active],
            captures,
        )

    def open_save_snapshot(self) -> None:
        service = self._snapshot_service
        if service is None or self._snapshot_restore is not None:
            return
        try:
            capture = self.capture_snapshot_workspace()
        except RuntimeError as error:
            self._view.append_status(f"Workspace Snapshot capture blocked: {error}")
            return
        self._submit_snapshot_task(
            lambda callback: service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._open_snapshot_save_result(result, capture),
        )

    def open_snapshot_manager(self) -> None:
        service = self._snapshot_service
        if service is None or self._snapshot_restore is not None:
            return
        self._submit_snapshot_task(
            lambda callback: service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._open_snapshot_manager_result,
        )

    def new_notebook(self) -> None:
        if (
            self._disposed
            or self._notebook_service is None
            or self._snapshot_restore is not None
        ):
            return
        self._request_notebook_transition("new", None)

    def open_notebook_manager(self) -> None:
        service = self._notebook_service
        if (
            service is None
            or self._disposed
            or self._snapshot_restore is not None
            or self._notebook_task_id is not None
        ):
            return
        if self._notebook_manager is not None:
            self._notebook_manager_generation += 1
            self._notebook_manager.close()
            self._notebook_manager.deleteLater()
            self._notebook_manager = None
        generation = self._notebook_manager_generation = (
            self._notebook_manager_generation + 1
        )
        self._submit_notebook_task(
            lambda callback: service.submit_list_notebooks(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._open_notebook_manager_result(
                generation, result
            ),
        )

    def close_active_notebook(self) -> None:
        if self._notebook_editor is None:
            return
        self._request_notebook_transition("close", None)

    def _notebook_transition_blocked(self) -> bool:
        if self._notebook_task_id is None:
            return False
        self._view.set_status("Note" "book operation in progress")
        return True

    def _request_suite_close(self) -> bool:
        if self._notebook_transition_blocked():
            return False
        editor = self._notebook_editor
        if editor is None:
            return True
        if not editor.is_dirty:
            self._close_notebook_editor()
            return True
        decision = editor.dirty_decision()
        if decision == "cancel":
            self._notebook_pending_action = None
            return False
        if decision == "discard":
            self._close_notebook_editor()
            return True
        self._notebook_pending_action = ("suite_close", None)
        self._save_notebook_editor(False)
        return False

    def _request_notebook_transition(
        self, action: str, notebook_id: str | None
    ) -> None:
        if self._notebook_transition_blocked():
            return
        editor = self._notebook_editor
        if editor is not None and editor.is_dirty:
            decision = editor.dirty_decision()
            if decision == "cancel":
                self._notebook_pending_action = None
                return
            if decision == "save":
                self._notebook_pending_action = (action, notebook_id)
                self._save_notebook_editor(False)
                return
        self._notebook_pending_action = None
        self._perform_notebook_transition(action, notebook_id)

    def _perform_notebook_transition(
        self, action: str, payload: object | None
    ) -> None:
        if action == "close":
            self._close_notebook_editor()
            return
        if action == "suite_close":
            self._close_notebook_editor()
            self._view.close()
            return
        if action == "new":
            self._close_notebook_editor()
            pages_by_market = {
                presenter.session.dataset.market_id: _NotePage(
                    presenter.session.dataset.market_id
                )
                for presenter in self._chart_presenters.values()
                if presenter.session.dataset is not None
            }
            draft = _NoteDraft(
                "Untitled " "Note" "book",
                "",
                _MarkerSettings(),
                tuple(pages_by_market.values()),
            )
            self._open_notebook_editor(draft=draft)
            return
        if action == "open" and isinstance(payload, str):
            self._close_notebook_editor()
            self._load_notebook(payload)
            return
        if action == "delete":
            if not isinstance(payload, tuple) or len(payload) != 4:
                return
            dialog, manager_generation, editor_generation, notebook_id = payload
            if (
                not isinstance(dialog, _ResearchManagerDialog)
                or type(manager_generation) is not int
                or type(editor_generation) is not int
                or type(notebook_id) is not str
                or dialog is not self._notebook_manager
                or manager_generation != self._notebook_manager_generation
            ):
                return
            editor = self._notebook_editor
            if (
                editor is None
                or editor_generation != self._notebook_editor_generation
                or editor.notebook_id != notebook_id
            ):
                return
            self._close_notebook_editor()
            self._submit_notebook_delete(
                dialog, manager_generation, notebook_id
            )
            return
        raise ValueError("unknown Research note-document transition")

    def _open_notebook_manager_result(
        self, generation: int, result: TaskResult
    ) -> None:
        if (
            self._disposed
            or generation != self._notebook_manager_generation
            or result.status != "completed"
            or not isinstance(result.value, tuple)
            or not all(
                isinstance(item, _NoteSummary)
                for item in result.value
            )
        ):
            return
        dialog = _ResearchManagerDialog(result.value, self._view)
        self._notebook_manager = dialog
        dialog.refresh_requested.connect(
            lambda: self._refresh_notebook_manager(dialog, generation)
        )
        dialog.open_requested.connect(
            lambda notebook_id: self._request_notebook_transition(
                "open", notebook_id
            )
        )
        dialog.delete_requested.connect(
            lambda notebook_id: self._delete_notebook(
                dialog, generation, notebook_id
            )
        )
        dialog.finished.connect(
            lambda: self._forget_notebook_manager(dialog, generation)
        )
        dialog.show()

    def _refresh_notebook_manager(
        self, dialog: _ResearchManagerDialog, generation: int
    ) -> None:
        service = self._notebook_service
        if (
            service is None
            or dialog is not self._notebook_manager
            or generation != self._notebook_manager_generation
            or self._notebook_task_id is not None
        ):
            return
        self._submit_notebook_task(
            lambda callback: service.submit_list_notebooks(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_summaries(result.value)
            if (
                dialog is self._notebook_manager
                and generation == self._notebook_manager_generation
                and result.status == "completed"
                and isinstance(result.value, tuple)
                and all(
                    isinstance(item, _NoteSummary)
                    for item in result.value
                )
            )
            else None,
        )

    def _load_notebook(self, notebook_id: str) -> None:
        service = self._notebook_service
        if service is None or self._notebook_task_id is not None:
            return
        generation = self._notebook_editor_generation = (
            self._notebook_editor_generation + 1
        )
        self._submit_notebook_task(
            lambda callback: service.submit_load_notebook(
                notebook_id,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._loaded_notebook_result(
                generation, notebook_id, result
            ),
        )

    def _loaded_notebook_result(
        self, generation: int, notebook_id: str, result: TaskResult
    ) -> None:
        if (
            self._disposed
            or generation != self._notebook_editor_generation
            or result.status != "completed"
            or not isinstance(result.value, _NoteValue)
            or result.value.notebook_id != notebook_id
        ):
            return
        self._open_notebook_editor(notebook=result.value)

    def _open_notebook_editor(
        self,
        *,
        notebook: _NoteValue | None = None,
        draft: _NoteDraft | None = None,
    ) -> None:
        if (notebook is None) == (draft is None):
            raise ValueError("provide exactly one notebook editor value")
        self._notebook_editor_generation += 1
        generation = self._notebook_editor_generation
        editor = _ResearchEditor(self._view)
        self._notebook_editor = editor
        self._active_notebook = notebook
        if notebook is not None:
            editor.set_notebook(notebook)
            self._last_valid_notebook_draft = _NoteDraft(
                notebook.display_name,
                notebook.description,
                notebook.annotation_settings,
                notebook.pages,
                notebook.notebook_id,
            )
        else:
            editor.set_draft(draft, dirty=True)
            self._last_valid_notebook_draft = draft
        editor.draft_changed.connect(
            lambda value: self._notebook_draft_changed(
                editor, generation, value
            )
        )
        editor.save_requested.connect(
            lambda intent: self._notebook_save_requested(
                editor, generation, intent
            )
        )
        editor.close_requested.connect(self.close_active_notebook)
        editor.add_current_chart_requested.connect(
            lambda: self._add_current_chart_page(editor, generation)
        )
        editor.go_to_requested.connect(self._notebook_go_to)
        editor.show()
        self._refresh_notebook_annotations()

    def _notebook_draft_changed(
        self,
        editor: _ResearchEditor,
        generation: int,
        draft: _NoteDraft,
    ) -> None:
        if (
            editor is not self._notebook_editor
            or generation != self._notebook_editor_generation
            or not isinstance(draft, _NoteDraft)
        ):
            return
        self._last_valid_notebook_draft = draft
        self._refresh_notebook_annotations()

    def _notebook_save_requested(
        self,
        editor: _ResearchEditor,
        generation: int,
        intent: _ResearchSaveIntent,
    ) -> None:
        if (
            editor is self._notebook_editor
            and generation == self._notebook_editor_generation
            and isinstance(intent, _ResearchSaveIntent)
        ):
            self._last_valid_notebook_draft = intent.draft
            self._save_notebook_editor(intent.save_as)

    def _save_notebook_editor(self, save_as: bool) -> None:
        service = self._notebook_service
        editor = self._notebook_editor
        if self._notebook_task_id is not None:
            self._view.set_status("Note" "book operation in progress")
            return
        if service is None or editor is None:
            self._notebook_pending_action = None
            if editor is not None:
                editor.set_save_pending(False)
                editor.set_status("Save was not submitted")
            return
        if not editor.is_current_valid:
            self._notebook_pending_action = None
            editor.set_save_pending(False)
            editor.set_status("Save blocked: current notebook input is invalid")
            return
        try:
            draft = editor.current_draft()
        except (ValueError, _NoteValidationError) as error:
            self._notebook_pending_action = None
            editor.set_save_pending(False)
            editor.set_status(f"Save blocked: {error}")
            return
        self._last_valid_notebook_draft = draft
        generation = self._notebook_editor_generation
        editor.set_save_pending(True)
        if save_as or editor.notebook_id is None:
            create_draft = _NoteDraft(
                draft.display_name,
                draft.description,
                draft.annotation_settings,
                draft.pages,
                None,
            )
            submit = lambda callback: service.submit_create_notebook(
                create_draft,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        else:
            submit = lambda callback: service.submit_update_notebook(
                editor.notebook_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        try:
            self._submit_notebook_task(
                submit,
                lambda result: self._saved_notebook_result(
                    editor, generation, result
                ),
            )
        except Exception as error:
            self._notebook_pending_action = None
            editor.set_save_pending(False)
            editor.set_status(f"Save failed: {error}")

    def _saved_notebook_result(
        self,
        editor: _ResearchEditor,
        generation: int,
        result: TaskResult,
    ) -> None:
        pending = self._notebook_pending_action
        self._notebook_pending_action = None
        if (
            editor is not self._notebook_editor
            or generation != self._notebook_editor_generation
        ):
            return
        editor.set_save_pending(False)
        if result.status != "completed" or not isinstance(
            result.value, _NoteValue
        ):
            editor.set_status(
                f"Save failed: {result.error_message or result.error_type or result.status}"
            )
            return
        self._active_notebook = result.value
        editor.set_notebook(result.value)
        self._last_valid_notebook_draft = editor.last_valid_draft
        self._refresh_notebook_annotations()
        if pending is not None:
            self._perform_notebook_transition(*pending)

    def _delete_notebook(
        self,
        dialog: _ResearchManagerDialog,
        generation: int,
        notebook_id: str,
    ) -> None:
        service = self._notebook_service
        if (
            service is None
            or dialog is not self._notebook_manager
            or generation != self._notebook_manager_generation
        ):
            return
        if self._notebook_transition_blocked():
            return
        editor = self._notebook_editor
        if editor is not None and editor.notebook_id == notebook_id:
            editor_generation = self._notebook_editor_generation
            if editor.is_dirty:
                decision = editor.dirty_decision()
                if decision == "cancel":
                    self._notebook_pending_action = None
                    return
                if decision == "save":
                    self._notebook_pending_action = (
                        "delete",
                        (dialog, generation, editor_generation, notebook_id),
                    )
                    self._save_notebook_editor(False)
                    return
            self._notebook_pending_action = None
            self._close_notebook_editor()
        self._submit_notebook_delete(dialog, generation, notebook_id)

    def _submit_notebook_delete(
        self,
        dialog: _ResearchManagerDialog,
        generation: int,
        notebook_id: str,
    ) -> None:
        service = self._notebook_service
        if (
            service is None
            or dialog is not self._notebook_manager
            or generation != self._notebook_manager_generation
            or self._notebook_task_id is not None
        ):
            return
        try:
            self._submit_notebook_task(
                lambda callback: service.submit_delete_notebook(
                    notebook_id,
                    result_callback=callback,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                lambda result: self._deleted_notebook_result(
                    dialog,
                    generation,
                    notebook_id,
                    result,
                ),
            )
        except Exception as error:
            self._view.set_status(f"Delete failed: {error}")

    def _deleted_notebook_result(
        self,
        dialog: _ResearchManagerDialog,
        manager_generation: int,
        notebook_id: str,
        result: TaskResult,
    ) -> None:
        if (
            dialog is not self._notebook_manager
            or manager_generation != self._notebook_manager_generation
        ):
            return
        if result.status != "completed":
            self._view.set_status(
                f"Delete failed: {result.error_message or result.error_type or result.status}"
            )
            return
        self._refresh_notebook_manager(dialog, manager_generation)

    def _submit_notebook_task(self, submit, settled) -> None:
        if self._notebook_task_id is not None:
            return
        task_ref: list[str] = []

        def callback(result: TaskResult) -> None:
            task_id = task_ref[0] if task_ref else result.task_id
            if task_id != self._notebook_task_id:
                return
            self._notebook_task_id = None
            self._view.set_research_notebook_operation_active(False)
            settled(result)

        self._view.set_research_notebook_operation_active(True)
        try:
            submission = submit(callback)
        except Exception:
            self._view.set_research_notebook_operation_active(False)
            raise
        task_ref.append(submission.task_id)
        self._notebook_task_id = submission.task_id

    def _add_current_chart_page(
        self, editor: _ResearchEditor, generation: int
    ) -> None:
        presenter = self._active_presenter()
        if (
            editor is not self._notebook_editor
            or generation != self._notebook_editor_generation
            or presenter is None
            or presenter.session.dataset is None
        ):
            return
        editor.add_page(_NotePage(presenter.session.dataset.market_id))

    def _notebook_go_to(self, market_id, timestamp_ms: int) -> None:
        if self._snapshot_restore is not None:
            return
        candidates = tuple(
            presenter
            for presenter in self._chart_presenters.values()
            if presenter.session.dataset is not None
            and presenter.session.dataset.market_id == market_id
        )
        if not candidates:
            self._view.set_status(
                f"No open Research chart for {market_id.as_key()}"
            )
            return
        active = self._active_presenter()
        if active in candidates:
            target = active
        else:
            target = min(
                candidates,
                key=lambda presenter: self._shell_state.placement_for(
                    presenter.slot_id
                ).workspace_position,
            )
        self._set_active_slot_internal(target.slot_id)
        target.go_to_timestamp_ms(timestamp_ms)
        self._refresh_active_view()

    def _refresh_notebook_annotations(self) -> None:
        if self._snapshot_restore is not None:
            return
        draft = self._last_valid_notebook_draft
        if self._notebook_editor is None or draft is None:
            for presenter in self._chart_presenters.values():
                presenter.clear_notebook_annotations()
            return
        now = datetime(2000, 1, 1, tzinfo=timezone.utc)
        notebook = _NoteValue.build(
            notebook_id=draft.notebook_id or "notebook_unsaved",
            display_name=draft.display_name,
            description=draft.description,
            created_at_utc=now,
            updated_at_utc=now,
            annotation_settings=draft.annotation_settings,
            pages=draft.pages,
        )
        service = self._notebook_service
        if service is None:
            return
        for presenter in self._chart_presenters.values():
            dataset = presenter.session.dataset
            if dataset is None:
                presenter.clear_notebook_annotations()
                continue
            presenter.set_notebook_annotations(
                service.project_annotations(notebook, dataset.market_id)
            )

    def _close_notebook_editor(self, *, clear_annotations: bool = True) -> None:
        editor = self._notebook_editor
        self._notebook_editor_generation += 1
        self._notebook_pending_action = None
        self._notebook_editor = None
        self._active_notebook = None
        self._last_valid_notebook_draft = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()
        if clear_annotations:
            for presenter in self._chart_presenters.values():
                presenter.clear_notebook_annotations()

    def _forget_notebook_manager(
        self, dialog: _ResearchManagerDialog, generation: int
    ) -> None:
        if (
            dialog is self._notebook_manager
            and generation == self._notebook_manager_generation
        ):
            self._notebook_manager = None

    def restore_snapshot_workspace(
        self,
        snapshot: SnapshotV1,
        report: SnapshotCompatibilityReport,
    ) -> None:
        if self._disposed or self._snapshot_restore is not None:
            raise RuntimeError("a Workspace Snapshot restore is already active")
        if not report.compatible or report.snapshot_id != snapshot.snapshot_id:
            raise RuntimeError("a current blocker-free snapshot preflight is required")
        pre_active_slot_id = self.active_slot_id
        pre_active_session_id = (
            None
            if pre_active_slot_id is None
            else self.session_for(pre_active_slot_id).session_id
        )
        pre_visualization_mode = self._view.workspace_widget.visualization_mode
        pre_pan_anchor_enabled = self._pan_anchor_enabled
        mode = report.mode
        if mode == "append":
            positions = dict(report.append_positions)
            rollback = None
        else:
            positions = {chart.chart_ref: chart.workspace_position for chart in snapshot.charts}
            rollback = self._capture_rollback_snapshot()
            for slot_id in reversed(self.slot_ids()):
                self._remove_chart(slot_id)
        self._workspace_generation += 1
        self._snapshot_restore = _SnapshotRestoreRun(
            run_id=uuid4().hex,
            snapshot=snapshot,
            mode=mode,
            positions=positions,
            workspace_generation=self._workspace_generation,
            preexisting_slots=self.slot_ids() if mode == "append" else (),
            rollback_snapshot=rollback,
            pre_active_slot_id=pre_active_slot_id,
            pre_active_session_id=pre_active_session_id,
            pre_visualization_mode=pre_visualization_mode,
            pre_pan_anchor_enabled=pre_pan_anchor_enabled,
        )
        self._view.set_snapshot_workspace_restore_active(True)
        self._restore_next_snapshot_chart()

    def _capture_rollback_snapshot(self) -> SnapshotV1 | None:
        if not self._chart_presenters:
            return None
        service = self._snapshot_service
        if service is None:
            raise RuntimeError("Workspace Snapshot service is unavailable")
        draft = service.build_draft(
            self.capture_snapshot_workspace(),
            display_name="In-memory rollback",
            description="Transient replace rollback state.",
            snapshot_id="snapshot_rollback",
        )
        now = datetime.now(timezone.utc)
        return SnapshotV1.build(
            snapshot_id=draft.snapshot_id or "snapshot_rollback",
            display_name=draft.display_name,
            description=draft.description,
            created_at_utc=now,
            updated_at_utc=now,
            workspace=draft.workspace,
            charts=draft.charts,
        )

    def _restore_next_snapshot_chart(self) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        if run.workspace_generation != self._workspace_generation:
            self._fail_snapshot_restore("Workspace Snapshot generation changed during restore")
            return
        if run.index >= len(run.snapshot.charts):
            self._complete_snapshot_restore()
            return
        chart = run.snapshot.charts[run.index]
        try:
            slot_id, presenter = self._create_restore_chart(
                chart.workspace_position if run.rollback else run.positions[chart.chart_ref]
            )
        except Exception as error:
            self._fail_snapshot_restore(f"{chart.chart_ref} creation failed: {error}")
            return
        run.current_slot_id = slot_id
        run.added_slots.append(slot_id)
        run.chart_slots[chart.chart_ref] = slot_id
        try:
            presenter.open_dataset(
                chart.market_id,
                completion_callback=lambda outcome, run_id=run.run_id, ref=chart.chart_ref: self._snapshot_dataset_complete(
                    run_id, ref, outcome
                ),
            )
        except Exception as error:
            self._fail_snapshot_restore(f"{chart.chart_ref} dataset failed: {error}")

    def _snapshot_dataset_complete(self, run_id: str, chart_ref: str, outcome) -> None:
        run = self._snapshot_restore
        if run is None or run.run_id != run_id:
            return
        if (
            run.index >= len(run.snapshot.charts)
            or run.snapshot.charts[run.index].chart_ref != chart_ref
        ):
            return
        if outcome.status != "success":
            self._fail_snapshot_restore(f"{chart_ref} dataset {outcome.status}: {outcome.message}")
            return
        chart = run.snapshot.charts[run.index]
        presenter = self._chart_presenters.get(run.current_slot_id)
        if presenter is None or presenter.session.session_id != outcome.session_id:
            self._fail_snapshot_restore(
                f"{chart_ref} dataset target is missing or no longer current"
            )
            return
        environment = chart.study_environment
        if environment is None:
            self._finish_snapshot_chart(run, chart, presenter)
            return
        presenter.set_environment_compatibility(EnvironmentCompatibilityReport(environment.environment_id))
        try:
            presenter.apply_environment(
                environment,
                "append",
                completion_callback=lambda env_outcome, run_id=run.run_id, ref=chart_ref: self._snapshot_environment_complete(
                    run_id, ref, env_outcome
                ),
            )
        except Exception as error:
            self._fail_snapshot_restore(f"{chart_ref} environment failed: {error}")

    def _snapshot_environment_complete(self, run_id: str, chart_ref: str, outcome) -> None:
        run = self._snapshot_restore
        if run is None or run.run_id != run_id:
            return
        if (
            run.index >= len(run.snapshot.charts)
            or run.snapshot.charts[run.index].chart_ref != chart_ref
        ):
            return
        if outcome.status != "success":
            self._fail_snapshot_restore(f"{chart_ref} environment {outcome.status}: {outcome.message}")
            return
        presenter = self._chart_presenters.get(run.current_slot_id)
        if presenter is None or presenter.session.session_id != outcome.session_id:
            self._fail_snapshot_restore(
                f"{chart_ref} environment target is missing or no longer current"
            )
            return
        self._finish_snapshot_chart(run, run.snapshot.charts[run.index], presenter)

    def _finish_snapshot_chart(self, run, chart, presenter) -> None:
        try:
            presenter.restore_snapshot_view_state(chart)
            if chart.detached:
                self._shell_state.detach_slot(presenter.slot_id)
                if self._view.floating_chart_window(presenter.slot_id) is None:
                    getattr(self._view, "detach_" "chart_slot")(
                        presenter.slot_id, presenter.session.session_id
                    )
                self._sync_shell_view()
        except Exception as error:
            self._fail_snapshot_restore(f"{chart.chart_ref} view restore failed: {error}")
            return
        run.index += 1
        run.current_slot_id = None
        self._restore_next_snapshot_chart()

    def _complete_snapshot_restore(self) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        try:
            self._view.set_snapshot_workspace_state(
                run.snapshot.workspace.visualization_mode,
                run.snapshot.workspace.pan_anchor_enabled,
            )
            self._pan_anchor_enabled = run.snapshot.workspace.pan_anchor_enabled
            active_slot = run.chart_slots.get(run.snapshot.workspace.active_chart_ref)
            if active_slot is None:
                raise RuntimeError("snapshot active chart was not restored")
            self._set_active_slot_internal(active_slot)
        except Exception as error:
            self._fail_snapshot_restore(f"Workspace Snapshot finalization failed: {error}")
            return
        rollback = run.rollback
        self._snapshot_restore = None
        self._view.set_snapshot_workspace_restore_active(False)
        self._refresh_active_view()
        self._refresh_notebook_annotations()
        self._view.set_status(
            "Workspace Snapshot rollback restored" if rollback else "Workspace Snapshot restored"
        )

    def _fail_snapshot_restore(self, message: str) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        self._snapshot_restore = None
        current = self._chart_presenters.get(run.current_slot_id)
        if current is not None:
            try:
                current.cancel_active_operation()
            except Exception as error:
                self._view.append_status(
                    f"Workspace Snapshot cancellation cleanup failed: {error}"
                )
        for slot_id in reversed(tuple(run.added_slots)):
            self._discard_partial_restore_chart(slot_id)
        rollback = run.rollback_snapshot
        failed_rollback = run.rollback
        self._view.append_status(message)
        if run.mode == "replace" and rollback is not None and not failed_rollback:
            self._workspace_generation += 1
            self._snapshot_restore = _SnapshotRestoreRun(
                run_id=uuid4().hex,
                snapshot=rollback,
                mode="replace",
                positions={
                    chart.chart_ref: chart.workspace_position
                    for chart in rollback.charts
                },
                workspace_generation=self._workspace_generation,
                preexisting_slots=(),
                rollback_snapshot=None,
                rollback=True,
            )
            self._restore_next_snapshot_chart()
            return
        if run.mode == "append" and not failed_rollback:
            try:
                self._restore_append_pre_run_state(run)
            except Exception as error:
                self._view.append_status(
                    f"Workspace Snapshot pre-run state restoration failed: {error}"
                )
        self._view.set_snapshot_workspace_restore_active(False)
        self._refresh_active_view()
        self._refresh_notebook_annotations()
        self._view.set_status("Workspace Snapshot rollback failed" if failed_rollback else "Workspace Snapshot restore failed")

    def _create_restore_chart(self, position: int):
        previous_active_slot_id = self.active_slot_id
        previous_active_session_id = (
            None
            if previous_active_slot_id is None
            else self.session_for(previous_active_slot_id).session_id
        )
        slot_id: int | None = None
        presenter = None
        try:
            entry = self._workspace_state.create_chart()
            slot_id = entry.slot_id
            self._shell_state.register_slot(slot_id)
            if self._shell_state.placement_for(slot_id).workspace_position != position:
                self._shell_state.move_slot(slot_id, position)
            slot_widget = self._view.add_chart_slot(slot_id)
            presenter_ref = []

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
            return slot_id, presenter
        except Exception:
            if slot_id is not None:
                self._discard_partial_restore_chart(
                    slot_id,
                    presenter,
                    previous_active_slot_id,
                    previous_active_session_id,
                )
            raise

    def _discard_partial_restore_chart(
        self,
        slot_id: int,
        presenter=None,
        previous_active_slot_id: int | None = None,
        previous_active_session_id: str | None = None,
    ) -> None:
        published = self._chart_presenters.pop(slot_id, None)
        disposed = set()
        for candidate in (published, presenter):
            if candidate is None or id(candidate) in disposed:
                continue
            disposed.add(id(candidate))
            try:
                candidate.dispose()
            except Exception:
                pass
        try:
            self._view.close_floating_chart(slot_id)
        except Exception:
            pass
        try:
            if slot_id in self._view.workspace_widget.slot_ids():
                self._view.remove_chart_slot(slot_id)
        except Exception:
            pass
        try:
            if any(item.slot_id == slot_id for item in self._shell_state.placements()):
                self._shell_state.remove_slot(slot_id)
        except Exception:
            pass
        try:
            if slot_id in self._workspace_state.slot_ids():
                self._workspace_state.remove_chart(slot_id)
        except Exception:
            pass
        try:
            self._sync_shell_view()
        except Exception:
            pass
        if previous_active_slot_id is not None:
            self._restore_active_identity(
                previous_active_slot_id, previous_active_session_id
            )

    def _restore_append_pre_run_state(self, run: _SnapshotRestoreRun) -> None:
        self._view.set_snapshot_workspace_state(
            run.pre_visualization_mode,
            run.pre_pan_anchor_enabled,
        )
        self._pan_anchor_enabled = run.pre_pan_anchor_enabled
        if run.pre_active_slot_id is not None:
            self._restore_active_identity(
                run.pre_active_slot_id,
                run.pre_active_session_id,
            )

    def _restore_active_identity(
        self, slot_id: int, expected_session_id: str | None
    ) -> None:
        if slot_id not in self._workspace_state.slot_ids():
            return
        if self.session_for(slot_id).session_id != expected_session_id:
            return
        self._set_active_slot_internal(slot_id)

    def _open_snapshot_save_result(self, result: TaskResult, capture) -> None:
        if result.status != "completed" or not isinstance(result.value, tuple):
            return
        dialog = SnapshotSaveDialog(capture, result.value, self._view)
        self._snapshot_save_dialogs.append(dialog)
        dialog.save_requested.connect(
            lambda intent, dialog=dialog, capture=capture: self._save_snapshot_intent(
                dialog, capture, intent
            )
        )
        dialog.finished.connect(
            lambda: self._forget_dialog(self._snapshot_save_dialogs, dialog)
        )
        dialog.show()

    def _save_snapshot_intent(self, dialog, capture, intent) -> None:
        service = self._snapshot_service
        if service is None or not isinstance(intent, SnapshotSaveIntent):
            return
        try:
            draft = service.build_draft(
                capture,
                display_name=intent.display_name,
                description=intent.description,
                snapshot_id=intent.snapshot_id,
            )
        except Exception as error:
            self._view.append_status(f"Workspace Snapshot build failed: {error}")
            return
        if intent.mode == "create":
            submit = lambda callback: service.submit_create_snapshot(
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        else:
            submit = lambda callback: service.submit_update_snapshot(
                intent.snapshot_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        self._submit_snapshot_task(
            submit,
            lambda result: self._view.append_status(
                "Workspace Snapshot saved."
                if result.status == "completed"
                else f"Workspace Snapshot save failed: {result.error_message or result.status}"
            ),
        )

    def _open_snapshot_manager_result(self, result: TaskResult) -> None:
        if result.status != "completed" or not isinstance(result.value, tuple):
            return
        dialog = SnapshotManagerDialog(result.value, self._view)
        self._snapshot_managers.append(dialog)
        dialog.refresh_requested.connect(lambda: self._refresh_snapshot_manager(dialog))
        dialog.selection_requested.connect(
            lambda snapshot_id: self._load_snapshot_manager_selection(dialog, snapshot_id)
        )
        dialog.compatibility_requested.connect(
            lambda intent: self._check_snapshot_manager_compatibility(dialog, intent)
        )
        dialog.load_requested.connect(
            lambda intent: self._open_snapshot_preflight(dialog, intent)
        )
        dialog.metadata_requested.connect(
            lambda intent: self._save_snapshot_manager_metadata(dialog, intent)
        )
        dialog.delete_requested.connect(
            lambda snapshot_id: self._delete_snapshot_manager_selection(dialog, snapshot_id)
        )
        dialog.finished.connect(lambda: self._forget_dialog(self._snapshot_managers, dialog))
        dialog.show()

    def _refresh_snapshot_manager(self, dialog) -> None:
        service = self._snapshot_service
        if service is None or dialog not in self._snapshot_managers:
            return
        self._submit_snapshot_task(
            lambda callback: service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_summaries(result.value)
            if dialog in self._snapshot_managers
            and result.status == "completed"
            and isinstance(result.value, tuple)
            else None,
        )

    def _load_snapshot_manager_selection(self, dialog, snapshot_id: str) -> None:
        service = self._snapshot_service
        generation = self._workspace_generation
        if service is None:
            return
        self._submit_snapshot_task(
            lambda callback: service.submit_load_snapshot(
                snapshot_id,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._snapshot_manager_loaded(dialog, generation, result),
        )

    def _snapshot_manager_loaded(self, dialog, generation: int, result: TaskResult) -> None:
        if (
            dialog not in self._snapshot_managers
            or generation != self._workspace_generation
            or result.status != "completed"
            or not isinstance(result.value, SnapshotV1)
        ):
            return
        dialog.set_snapshot(result.value)
        self._check_snapshot_manager_compatibility(
            dialog,
            SnapshotLoadIntent(result.value.snapshot_id, "append"),
        )

    def _check_snapshot_manager_compatibility(self, dialog, intent) -> None:
        service = self._snapshot_service
        snapshot = dialog.snapshot
        generation = self._workspace_generation
        if (
            service is None
            or snapshot is None
            or snapshot.snapshot_id != intent.snapshot_id
            or self._snapshot_restore is not None
        ):
            return
        current = {
            "occupied_positions": self._shell_state.reserved_positions(),
            "idle": all(not item.is_busy for item in self._chart_presenters.values()),
        }
        self._submit_snapshot_task(
            lambda callback: service.submit_preflight(
                snapshot,
                intent.mode,
                current,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_compatibility(result.value)
            if dialog in self._snapshot_managers
            and generation == self._workspace_generation
            and result.status == "completed"
            and isinstance(result.value, SnapshotCompatibilityReport)
            else None,
        )

    def _open_snapshot_preflight(self, dialog, intent) -> None:
        snapshot = dialog.snapshot
        report = dialog.compatibility_report
        if (
            snapshot is None
            or report is None
            or report.mode != intent.mode
            or not report.compatible
        ):
            return
        preflight = SnapshotPreflightDialog(report, self._view)
        self._snapshot_preflight_dialogs.append(preflight)
        generation = self._workspace_generation
        preflight.load_requested.connect(
            lambda _report: self.restore_snapshot_workspace(snapshot, report)
            if generation == self._workspace_generation
            else None
        )
        preflight.finished.connect(
            lambda: self._forget_dialog(self._snapshot_preflight_dialogs, preflight)
        )
        preflight.show()

    def _save_snapshot_manager_metadata(self, dialog, intent) -> None:
        service = self._snapshot_service
        snapshot = dialog.snapshot
        if (
            service is None
            or snapshot is None
            or not isinstance(intent, SnapshotMetadataIntent)
            or intent.snapshot_id != snapshot.snapshot_id
        ):
            return
        draft = SnapshotDraft(
            intent.display_name,
            intent.description,
            snapshot.workspace,
            snapshot.charts,
            snapshot.snapshot_id,
        )
        self._submit_snapshot_task(
            lambda callback: service.submit_update_snapshot(
                snapshot.snapshot_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: dialog.set_snapshot(result.value)
            if dialog in self._snapshot_managers
            and result.status == "completed"
            and isinstance(result.value, SnapshotV1)
            else None,
        )

    def _delete_snapshot_manager_selection(self, dialog, snapshot_id: str) -> None:
        service = self._snapshot_service
        if service is None:
            return
        self._submit_snapshot_task(
            lambda callback: service.submit_delete_snapshot(
                snapshot_id,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda _result: self._refresh_snapshot_manager(dialog),
        )

    def _submit_snapshot_task(self, submit, settled) -> None:
        task_ref = []

        def result_callback(result):
            task_id = task_ref[0] if task_ref else result.task_id
            self._snapshot_task_ids.discard(task_id)
            if not self._disposed:
                settled(result)

        submission = submit(result_callback)
        task_ref.append(submission.task_id)
        self._snapshot_task_ids.add(submission.task_id)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._cancel_catalog()
        if self._study_setup_service is not None:
            for task_id in tuple(self._setup_task_ids):
                self._study_setup_service.cancel(task_id)
        self._setup_task_ids.clear()
        if self._snapshot_service is not None:
            for task_id in tuple(self._snapshot_task_ids):
                self._snapshot_service.cancel(task_id)
        self._snapshot_task_ids.clear()
        if self._notebook_service is not None and self._notebook_task_id is not None:
            self._notebook_service.cancel(self._notebook_task_id)
        self._notebook_task_id = None
        if self._snapshot_restore is not None:
            current = self._chart_presenters.get(self._snapshot_restore.current_slot_id)
            if current is not None:
                current.cancel_active_operation()
            self._snapshot_restore = None
        for dialog in (*self._setup_dialogs, *self._save_dialogs, *self._environment_managers):
            dialog.close()
        self._setup_dialogs.clear()
        self._save_dialogs.clear()
        self._environment_managers.clear()
        for dialog in (
            *self._snapshot_save_dialogs,
            *self._snapshot_managers,
            *self._snapshot_preflight_dialogs,
        ):
            dialog.close()
        self._snapshot_save_dialogs.clear()
        self._snapshot_managers.clear()
        self._snapshot_preflight_dialogs.clear()
        if self._notebook_manager is not None:
            self._notebook_manager.close()
            self._notebook_manager.deleteLater()
            self._notebook_manager = None
        self._close_notebook_editor(clear_annotations=False)
        self._view.close_all_floating_charts()
        for presenter in tuple(self._chart_presenters.values()):
            presenter.dispose()
        self._chart_presenters.clear()
        self._workspace_state.dispose()
        self._shell_state.clear()
        self._view.workspace_widget.clear()
        self._view.set_active_chart_state(None, (), False, False, False, False, "")
        self._view.set_close_guard(None)

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
        self._view.save_snapshot_requested.connect(self.open_save_snapshot)
        self._view.snapshot_manager_requested.connect(self.open_snapshot_manager)
        self._view.new_notebook_requested.connect(self.new_notebook)
        self._view.notebooks_requested.connect(self.open_notebook_manager)
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
        self._sync_snapshot_workspace_idle()
        self._refresh_notebook_annotations()
        if slot_id == self.active_slot_id:
            self._refresh_active_view()

    def _sync_snapshot_workspace_idle(self) -> None:
        has_charts = bool(self._chart_presenters)
        self._view.set_snapshot_workspace_idle(
            has_charts,
            has_charts
            and all(not presenter.is_busy for presenter in self._chart_presenters.values()),
        )

    def _refresh_active_view(self) -> None:
        self._sync_snapshot_workspace_idle()
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
        if self._snapshot_restore is not None:
            return
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None or presenter.session.session_id != session_id:
            return
        self._remove_chart(slot_id)
        self._refresh_active_view()

    def _on_go_to_accepted(
        self, slot_id: int, session_id: str, timestamp_ms: int
    ) -> None:
        if self._snapshot_restore is not None:
            return
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None or presenter.session.session_id != session_id:
            return
        presenter.go_to_timestamp_ms(timestamp_ms)
        if slot_id == self.active_slot_id:
            self._refresh_active_view()

    def _on_horizontal_pan(self, source_slot_id: int) -> None:
        if (
            self._snapshot_restore is not None
            or not self._pan_anchor_enabled
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
            self._snapshot_restore is not None
            or result.status != "completed"
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
        if self._snapshot_restore is not None:
            return
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
            self._snapshot_restore is not None
            or result.status != "completed"
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
            self._snapshot_restore is not None
            or service is None
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
            self._snapshot_restore is not None
            or result.status != "completed"
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
        if service is None or self._snapshot_restore is not None:
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
        if self._snapshot_restore is not None:
            return
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
        if service is None or self._snapshot_restore is not None:
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
