"""Real catalog and base-chart lifecycle for the restored Research shell."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QDialog

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.gui.presenters.research_chart_presenter import (
    ChartOperationOutcome,
    ResearchChartPresenter,
    StudyOperationOutcome,
)
from leonardo.gui.research.chart_panel import ResearchChartPanel
from leonardo.gui.research.financial_tools_dialog import (
    ResearchFinancialToolsDialog,
    ResearchStudyApplyIntent,
    ResearchStudyEditDialog,
    ResearchStudyEditIntent,
)
from leonardo.gui.research.new_chart_dialog import ResearchNewChartDialog
from leonardo.gui.research.studies_manager_dialog import ResearchStudiesManagerDialog
from leonardo.gui.research.suite_window import ResearchSuiteWindow
from leonardo.gui.windows.research_go_to_dialog import ResearchGoToDialog
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
    ResearchNotebookSnapshotAssignment,
)
from leonardo.gui.windows.research_notebook_window import (
    ResearchNotebookSaveIntent,
    ResearchNotebookWindow,
)
from leonardo.gui.windows.study_environment_manager_dialog import (
    StudyEnvironmentApplyIntent,
    StudyEnvironmentCompatibilityIntent,
    StudyEnvironmentManagerDialog,
    StudyEnvironmentMetadataIntent,
    StudyEnvironmentTarget,
)
from leonardo.gui.windows.study_environment_save_dialog import (
    StudyEnvironmentSaveDialog,
    StudyEnvironmentSaveIntent,
)
from leonardo.gui.windows.study_style_dialog import StudyStyleDialog, StudyStylePatch
from leonardo.gui.windows.workspace_snapshot_manager_dialog import (
    WorkspaceSnapshotLoadIntent,
    WorkspaceSnapshotManagerDialog,
    WorkspaceSnapshotMetadataIntent,
)
from leonardo.gui.windows.workspace_snapshot_preflight_dialog import (
    WorkspaceSnapshotPreflightDialog,
)
from leonardo.gui.windows.workspace_snapshot_save_dialog import (
    WorkspaceSnapshotSaveDialog,
    WorkspaceSnapshotSaveIntent,
)
from leonardo.research import (
    DatasetCatalogReport,
    HistoricalDataset,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResearchStudySetupApplicationService,
    ResearchWorkspaceState,
    ResearchWorkspaceStateError,
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudySetupCatalog,
)
from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchNotebookPageV1,
    ResearchNotebookSummary,
    ResearchNotebookV1,
    ResearchNotebookValidationError,
)
from leonardo.research.notebook_application import (
    ResearchNotebookApplicationService,
)
from leonardo.research.study_environment import (
    StudyEnvironmentCompatibilityReport,
    StudyEnvironmentDraft,
    StudyEnvironmentPresentationV1,
    StudyEnvironmentSummary,
    StudyEnvironmentV1,
)
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotCompatibilityReport,
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
    WorkspaceSnapshotCapture,
)
from leonardo.research.workspace_snapshot_application import (
    ResearchWorkspaceSnapshotApplicationService,
)


@dataclass(frozen=True, slots=True)
class _StudySetupCatalogAttempt:
    task_id: str
    slot_id: int
    session_id: str
    generation: int
    presenter: ResearchChartPresenter
    dataset: HistoricalDataset
    study_ids: tuple[str, ...]
    revision: int


@dataclass(frozen=True, slots=True)
class _StudyEditOpenTarget:
    slot_id: int
    session_id: str
    generation: int
    presenter: ResearchChartPresenter
    study_id: str


@dataclass(slots=True)
class _SnapshotRestoreRun:
    run_id: str
    snapshot: ResearchWorkspaceSnapshotV1
    mode: str
    positions: dict[str, int]
    preexisting_slots: tuple[int, ...]
    rollback_snapshot: ResearchWorkspaceSnapshotV1 | None = None
    rollback: bool = False
    index: int = 0
    current_slot_id: int | None = None
    added_slots: list[int] = field(default_factory=list)
    chart_slots: dict[str, int] = field(default_factory=dict)
    pre_active_slot_id: int | None = None
    pre_active_session_id: str | None = None
    pre_visualization_mode: str = "scroll_4"
    pre_pan_anchor_enabled: bool = False
    pre_current_workspace_snapshot_id: str | None = None
    pre_assigned_notebook_id: str | None = None


class RestoredResearchLifecyclePresenter(QObject):
    """Connect the restored shell to canonical Research dataset services."""

    _callback_requested = Signal(object)

    def __init__(
        self,
        view: ResearchSuiteWindow,
        service: ResearchDatasetApplicationService,
        study_service: ResearchStudyApplicationService,
        window_tracker: Callable[[object, str, str, str], None] | None = None,
        *,
        study_setup_service: ResearchStudySetupApplicationService | None = None,
        snapshot_service: ResearchWorkspaceSnapshotApplicationService | None = None,
        notebook_service: ResearchNotebookApplicationService | None = None,
    ) -> None:
        super().__init__(view)
        if not isinstance(view, ResearchSuiteWindow):
            raise TypeError("view must be a ResearchSuiteWindow")
        if not isinstance(service, ResearchDatasetApplicationService):
            raise TypeError("service must be a ResearchDatasetApplicationService")
        if not isinstance(study_service, ResearchStudyApplicationService):
            raise TypeError(
                "study_service must be a ResearchStudyApplicationService"
            )
        if window_tracker is not None and not callable(window_tracker):
            raise TypeError("window_tracker must be callable or None")
        if study_setup_service is not None and not isinstance(
            study_setup_service, ResearchStudySetupApplicationService
        ):
            raise TypeError(
                "study_setup_service must be a "
                "ResearchStudySetupApplicationService or None"
            )
        if snapshot_service is not None and not isinstance(
            snapshot_service, ResearchWorkspaceSnapshotApplicationService
        ):
            raise TypeError(
                "snapshot_service must be "
                "ResearchWorkspaceSnapshotApplicationService or None"
            )
        if notebook_service is not None and not isinstance(
            notebook_service, ResearchNotebookApplicationService
        ):
            raise TypeError(
                "notebook_service must be "
                "ResearchNotebookApplicationService or None"
            )
        self._view = view
        self._service = service
        self._study_service = study_service
        self._workspace_state = ResearchWorkspaceState()
        self._chart_presenters: dict[int, ResearchChartPresenter] = {}
        self._go_to_dialogs: dict[int, ResearchGoToDialog] = {}
        self._financial_tools_dialogs: dict[
            int, ResearchFinancialToolsDialog
        ] = {}
        self._study_edit_dialogs: dict[
            tuple[int, str], ResearchStudyEditDialog
        ] = {}
        self._studies_manager_dialogs: dict[int, ResearchStudiesManagerDialog] = {}
        self._study_style_dialogs: dict[tuple[int, str], StudyStyleDialog] = {}
        self._study_edit_open_targets: dict[int, _StudyEditOpenTarget] = {}
        self._active_study_setup_catalog_tasks: dict[int, str] = {}
        self._study_setup_catalog_attempts: dict[
            int, _StudySetupCatalogAttempt
        ] = {}
        self._catalog_visible_study_ids: dict[int, tuple[str, ...]] = {}
        self._catalog_revisions: dict[int, int] = {}
        self._deferred_catalog_refresh: set[int] = set()
        self._financial_tools_open_requested: set[int] = set()
        self._active_catalog_task_id: str | None = None
        self._dataset_summaries = ()
        self._disposed = False
        self._last_catalog_status = ""
        self._window_tracker = window_tracker
        self._study_setup_service = study_setup_service
        self._snapshot_service = snapshot_service
        self._notebook_service = notebook_service
        self._setup_task_ids: set[str] = set()
        self._environment_save_dialogs: dict[int, StudyEnvironmentSaveDialog] = {}
        self._environment_managers: dict[int, StudyEnvironmentManagerDialog] = {}
        self._environment_manager_modes: dict[int, str] = {}
        self._snapshot_task_ids: set[str] = set()
        self._snapshot_save_dialog: WorkspaceSnapshotSaveDialog | None = None
        self._snapshot_manager: WorkspaceSnapshotManagerDialog | None = None
        self._snapshot_manager_mode: str | None = None
        self._snapshot_preflight_dialog: WorkspaceSnapshotPreflightDialog | None = None
        self._snapshot_restore: _SnapshotRestoreRun | None = None
        self._notebook_editor: ResearchNotebookWindow | None = None
        self._notebook_manager: ResearchNotebookManagerDialog | None = None
        self._active_notebook: ResearchNotebookV1 | None = None
        self._last_valid_notebook_draft: ResearchNotebookDraft | None = None
        self._notebook_task_id: str | None = None
        self._notebook_link_operation_token: str | None = None
        self._notebook_pending_action: tuple[str, object | None] | None = None
        self._current_workspace_snapshot_id: str | None = None
        self._assigned_notebook_id: str | None = None
        self._pan_anchor_enabled = False
        self._pan_anchor_in_progress = False
        self._callback_requested.connect(
            self._invoke_callback, Qt.ConnectionType.QueuedConnection
        )

        self._new_chart_dialog = ResearchNewChartDialog((), view)
        self._new_chart_dialog.accepted.connect(self._accept_new_chart)
        if window_tracker is not None:
            window_tracker(
                self._new_chart_dialog,
                "research_restoration.new_chart_dialog",
                "New Chart",
                "dialog",
            )

        self._view.new_chart_requested.connect(self.open_new_chart)
        self._view.save_study_environment_requested.connect(
            self._open_save_environment
        )
        self._view.load_study_environment_requested.connect(
            lambda: self._open_environment_manager("load")
        )
        self._view.manage_study_environments_requested.connect(
            lambda: self._open_environment_manager("manage")
        )
        self._view.save_workspace_snapshot_requested.connect(
            self._open_save_snapshot
        )
        self._view.load_workspace_snapshot_requested.connect(
            lambda: self._open_snapshot_manager("load")
        )
        self._view.manage_workspace_snapshots_requested.connect(
            lambda: self._open_snapshot_manager("manage")
        )
        self._view.create_notebook_requested.connect(self._new_notebook)
        self._view.open_notebook_requested.connect(self._open_assigned_notebook)
        self._view.notebook_manager_requested.connect(
            self._open_notebook_manager
        )
        self._view.save_notebook_requested.connect(
            lambda: self._save_notebook_editor(False)
        )
        self._view.load_notebook_requested.connect(self._open_notebook_manager)
        self._view.closed.connect(self.dispose)
        self._view.workspace.set_external_close_owner(True)
        self._view.workspace.chart_close_requested.connect(self._close_chart)
        self._view.workspace.detached_window_created.connect(
            self._track_detached_window
        )
        self._view.action_for_text("Scroll 4").triggered.connect(
            lambda checked: checked
            and self._view.workspace.set_visualization_mode("scroll_4")
        )
        self._view.action_for_text("Fit 8").triggered.connect(
            lambda checked: checked
            and self._view.workspace.set_visualization_mode("fit_8")
        )
        pan_anchor = self._view.action_for_text("Pan Anchor")
        pan_anchor.setChecked(False)
        pan_anchor.setEnabled(True)
        pan_anchor.setToolTip("")
        pan_anchor.setStatusTip("")
        pan_anchor.toggled.connect(self._set_pan_anchor_enabled)
        self._refresh_command_actions()
        self._refresh_catalog()

    def open_new_chart(self) -> None:
        if self._disposed:
            return
        self._new_chart_dialog.set_dataset_summaries(self._dataset_summaries)
        self._new_chart_dialog.reset_selection()
        self._new_chart_dialog.open()

    def dispose(self) -> bool:
        if self._disposed:
            return False
        self._disposed = True
        if self._active_catalog_task_id is not None:
            self._service.cancel(self._active_catalog_task_id)
            self._active_catalog_task_id = None
        pan_anchor = self._view.action_for_text("Pan Anchor")
        pan_anchor.setChecked(False)
        pan_anchor.setEnabled(False)
        for task_id in tuple(self._setup_task_ids):
            if self._study_setup_service is not None:
                self._study_setup_service.cancel(task_id)
        self._setup_task_ids.clear()
        for task_id in tuple(self._snapshot_task_ids):
            if self._snapshot_service is not None:
                self._snapshot_service.cancel(task_id)
        self._snapshot_task_ids.clear()
        if self._notebook_task_id is not None:
            if self._notebook_service is not None:
                self._notebook_service.cancel(self._notebook_task_id)
            self._notebook_task_id = None
        self._notebook_link_operation_token = None
        self._close_and_delete_dialog(self._new_chart_dialog)
        for slot_id in tuple(self._active_study_setup_catalog_tasks):
            self._cancel_study_setup_catalog(slot_id)
        for slot_id in tuple(self._financial_tools_dialogs):
            self._retire_financial_tools_dialog(slot_id)
        for slot_id, study_id in tuple(self._study_edit_dialogs):
            self._retire_study_edit(slot_id, study_id)
        for slot_id in tuple(self._studies_manager_dialogs):
            self._retire_studies_manager(slot_id)
        for slot_id, study_id in tuple(self._study_style_dialogs):
            self._retire_study_style(slot_id, study_id)
        self._study_edit_open_targets.clear()
        for slot_id in tuple(self._go_to_dialogs):
            self._retire_go_to_dialog(slot_id)
        for dialog in tuple(self._environment_save_dialogs.values()):
            self._close_and_delete_dialog(dialog)
        self._environment_save_dialogs.clear()
        for dialog in tuple(self._environment_managers.values()):
            self._close_and_delete_dialog(dialog)
        self._environment_managers.clear()
        self._environment_manager_modes.clear()
        for dialog in (
            self._snapshot_save_dialog,
            self._snapshot_manager,
            self._snapshot_preflight_dialog,
            self._notebook_manager,
        ):
            if dialog is not None:
                self._close_and_delete_dialog(dialog)
        if self._notebook_editor is not None:
            self._notebook_editor.hide()
            self._notebook_editor.deleteLater()
        self._snapshot_save_dialog = None
        self._snapshot_manager = None
        self._snapshot_preflight_dialog = None
        self._notebook_editor = None
        self._notebook_manager = None
        self._snapshot_restore = None
        panels = tuple(
            self._view.workspace.chart_panel_for_slot(slot_id)
            for slot_id in self._view.workspace.slot_ids()
        )
        for presenter in tuple(self._chart_presenters.values()):
            presenter.dispose()
        self._chart_presenters.clear()
        self._view.workspace.clear_all_charts()
        self._view.workspace.set_external_close_owner(False)
        for panel in panels:
            panel.deleteLater()
        self._workspace_state.dispose()
        return True

    def _refresh_catalog(self) -> None:
        self._view.set_dataset_summaries(())
        self._view.set_catalog_busy(True)
        self._append_activity("Scanning accepted historical datasets...")
        try:
            submission = self._service.submit_catalog(
                progress_callback=self._on_catalog_progress,
                result_callback=self._on_catalog_result,
                callback_dispatcher=self._dispatch,
            )
        except Exception as error:
            self._publish_catalog_failure(f"Catalog submission failed: {error}")
            return
        self._active_catalog_task_id = submission.task_id

    def _on_catalog_progress(self, progress: TaskProgress) -> None:
        if (
            self._disposed
            or progress.task_id != self._active_catalog_task_id
            or progress.message == self._last_catalog_status
        ):
            return
        self._last_catalog_status = progress.message
        self._append_activity(progress.message)

    def _on_catalog_result(self, result: TaskResult) -> None:
        if self._disposed or result.task_id != self._active_catalog_task_id:
            return
        self._active_catalog_task_id = None
        if result.status == "completed" and isinstance(
            result.value, DatasetCatalogReport
        ):
            self._dataset_summaries = tuple(result.value.accepted)
            self._view.set_dataset_summaries(self._dataset_summaries)
            self._view.set_catalog_busy(False)
            self._append_activity(
                f"Catalog ready: {len(self._dataset_summaries)} accepted dataset(s)."
            )
            return
        detail = result.error_message or result.error_type or result.status
        self._publish_catalog_failure(f"Catalog scan {result.status}: {detail}")

    def _publish_catalog_failure(self, message: str) -> None:
        self._active_catalog_task_id = None
        self._dataset_summaries = ()
        self._view.set_dataset_summaries(())
        self._view.set_catalog_busy(False)
        self._append_activity(message)

    def _accept_new_chart(self) -> None:
        if self._disposed:
            return
        summary = self._new_chart_dialog.selected_dataset_summary()
        if summary is None:
            return
        try:
            slot_id, presenter = self._create_restored_chart(summary.market_id)
        except ResearchWorkspaceStateError as error:
            self._append_activity(str(error))
            return
        try:
            presenter.open_dataset(
                summary.market_id,
                completion_callback=lambda outcome: self._on_dataset_completion(
                    presenter, outcome
                ),
            )
        except Exception as error:
            if self._chart_presenters.get(slot_id) is presenter:
                self._remove_chart(slot_id, presenter)
            self._append_activity(
                f"Chart {slot_id} dataset submission failed: {error}"
            )

    def _create_restored_chart(
        self,
        market_id,
        *,
        workspace_position: int | None = None,
    ) -> tuple[int, ResearchChartPresenter]:
        entry = self._workspace_state.create_chart()
        slot_id = entry.slot_id
        panel = ResearchChartPanel(market_id, slot_id=slot_id)
        panel.set_navigation_available(True)
        panel.set_workspace_lifecycle_available(True)
        panel.set_financial_tools_available(False)
        panel.set_studies_available(False)
        panel.set_study_overlay_actions_available(False)
        panel.go_to_requested.connect(
            lambda current=slot_id: self._open_go_to(current)
        )
        panel.financial_tools_requested.connect(
            lambda current=slot_id: self._open_financial_tools(current)
        )
        panel.studies_requested.connect(
            lambda current=slot_id: self._open_studies_manager(current)
        )
        panel.study_style_requested.connect(
            lambda study_id, current=slot_id: self._open_study_style(
                current, study_id
            )
        )
        panel.study_edit_requested.connect(
            lambda study_id, current=slot_id: self._open_study_edit(
                current, study_id
            )
        )
        panel.study_remove_requested.connect(
            lambda study_id, current=slot_id: self._remove_study(current, study_id)
        )
        try:
            self._view.workspace.add_chart(slot_id, panel)
            if workspace_position is not None:
                self._view.workspace.move_chart(slot_id, workspace_position)
            self._view.workspace.set_active_slot(slot_id)
        except Exception:
            panel.deleteLater()
            self._workspace_state.remove_chart(slot_id)
            raise

        presenter_ref: list[ResearchChartPresenter] = []

        def current_runtime() -> bool:
            return (
                not self._disposed
                and bool(presenter_ref)
                and self._chart_presenters.get(slot_id) is presenter_ref[0]
            )

        presenter = ResearchChartPresenter(
            slot_id,
            panel,
            self._workspace_state.session_for(slot_id),
            self._service,
            self._study_service,
            self._dispatch,
            self._on_chart_state_changed,
            self._append_activity,
            current_runtime,
            self._on_horizontal_pan,
        )
        presenter_ref.append(presenter)
        self._chart_presenters[slot_id] = presenter
        self._catalog_revisions[slot_id] = 0
        self._workspace_state.set_active(slot_id)
        self._refresh_command_actions()
        return slot_id, presenter

    def _on_dataset_completion(
        self,
        presenter: ResearchChartPresenter,
        outcome: ChartOperationOutcome,
    ) -> None:
        if self._disposed:
            return
        current = self._chart_presenters.get(outcome.slot_id)
        if current is not presenter or current.session.session_id != outcome.session_id:
            return
        if outcome.status == "success":
            return
        if outcome.status in {"failure", "cancelled", "cancellation", "stale"}:
            self._append_activity(
                f"Chart {outcome.slot_id} load {outcome.status}: {outcome.message}"
            )
            self._remove_chart(outcome.slot_id, presenter)

    def _on_chart_state_changed(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if presenter is None:
            return
        if presenter.status_text in {
            "Dataset submission failed",
            "Dataset load cancelled",
            "Dataset load failed",
            "Resident submission failed",
            "Resident load cancelled",
            "Resident load failed",
            "Volume projection failed",
        }:
            self._append_activity(
                f"Chart {slot_id} removed after {presenter.status_text.lower()}."
            )
            self._remove_chart(slot_id, presenter)
            return
        self._sync_financial_tools_state(slot_id, presenter)
        self._refresh_studies_manager(slot_id, presenter)
        self._refresh_study_style_dialogs(slot_id, presenter)
        self._refresh_command_actions()
        self._refresh_notebook_annotations()
        dialog = self._financial_tools_dialogs.get(slot_id)
        study_ids = tuple(study.study_id for study in presenter.session.studies)
        if (
            dialog is not None
            and not presenter.is_busy
            and slot_id not in self._active_study_setup_catalog_tasks
            and self._catalog_visible_study_ids.get(slot_id) != study_ids
        ):
            self._submit_study_setup_catalog(slot_id, open_when_ready=False)

    def _close_chart(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if presenter is not None:
            self._remove_chart(slot_id, presenter)

    def _remove_chart(
        self, slot_id: int, presenter: ResearchChartPresenter
    ) -> None:
        if self._chart_presenters.get(slot_id) is not presenter:
            return
        self._cancel_study_setup_catalog(slot_id)
        self._study_edit_open_targets.pop(slot_id, None)
        self._retire_financial_tools_dialog(slot_id)
        for current_slot, study_id in tuple(self._study_edit_dialogs):
            if current_slot == slot_id:
                self._retire_study_edit(slot_id, study_id)
        self._retire_studies_manager(slot_id)
        for current_slot, study_id in tuple(self._study_style_dialogs):
            if current_slot == slot_id:
                self._retire_study_style(current_slot, study_id)
        self._retire_go_to_dialog(slot_id)
        presenter.dispose()
        panel = None
        if slot_id in self._view.workspace.slot_ids():
            panel = self._view.workspace.remove_chart(slot_id)
        if slot_id in self._workspace_state.slot_ids():
            self._workspace_state.remove_chart(slot_id)
        self._chart_presenters.pop(slot_id, None)
        self._catalog_visible_study_ids.pop(slot_id, None)
        self._catalog_revisions.pop(slot_id, None)
        self._deferred_catalog_refresh.discard(slot_id)
        self._financial_tools_open_requested.discard(slot_id)
        if panel is not None:
            panel.deleteLater()
        self._refresh_command_actions()

    def _active_presenter(self) -> ResearchChartPresenter | None:
        slot_id = self._view.workspace.active_slot_id
        return None if slot_id is None else self._chart_presenters.get(slot_id)

    def _ready_presenters(self) -> tuple[ResearchChartPresenter, ...]:
        return tuple(
            presenter
            for presenter in self._chart_presenters.values()
            if (
                not presenter.is_disposed
                and not presenter.is_busy
                and presenter.session.dataset is not None
            )
        )

    def _refresh_command_actions(self) -> None:
        if self._disposed:
            return
        presenter = self._active_presenter()
        ready = (
            presenter is not None
            and not presenter.is_disposed
            and not presenter.is_busy
            and presenter.session.dataset is not None
        )
        environment_busy = bool(self._setup_task_ids) or (
            presenter is not None and presenter.environment_apply_active
        )
        self._view.set_study_environment_actions_state(
            bool(
                self._study_setup_service
                and ready
                and presenter.session.studies
                and not environment_busy
            ),
            bool(self._study_setup_service and ready and not environment_busy),
            bool(self._study_setup_service and not environment_busy),
        )
        snapshot_busy = bool(self._snapshot_task_ids) or self._snapshot_restore is not None
        self._view.set_workspace_snapshot_actions_state(
            bool(self._snapshot_service and self._ready_presenters() and not snapshot_busy),
            bool(self._snapshot_service and not snapshot_busy),
            bool(self._snapshot_service and not snapshot_busy),
        )
        notebook_busy = self._notebook_task_id is not None
        editor_valid = (
            self._notebook_editor is not None
            and self._notebook_editor.is_current_valid
        )
        self._view.set_notebook_actions_state(
            bool(self._notebook_service and not notebook_busy),
            bool(self._notebook_service and not notebook_busy),
            bool(editor_valid and not notebook_busy),
            bool(self._notebook_service and not notebook_busy),
        )

    def _open_save_environment(self) -> None:
        presenter = self._active_presenter()
        service = self._study_setup_service
        if (
            service is None
            or presenter is None
            or presenter.is_busy
            or presenter.environment_apply_active
            or presenter.session.dataset is None
            or not presenter.session.studies
        ):
            return
        existing = self._environment_save_dialogs.get(presenter.slot_id)
        if existing is not None:
            self._show_dialog(existing)
            return
        slot_id = presenter.slot_id
        session_id = presenter.session.session_id
        studies = presenter.session.studies
        presentations = presenter.session.study_presentations()
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._open_environment_save_result(
                result, slot_id, session_id, studies, presentations
            ),
        )

    def _open_environment_save_result(
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
            or not isinstance(result.value, tuple)
            or not all(
                isinstance(item, StudyEnvironmentSummary)
                for item in result.value
            )
            or presenter is None
            or presenter.session.session_id != session_id
        ):
            return
        existing = self._environment_save_dialogs.get(slot_id)
        if existing is not None:
            self._show_dialog(existing)
            return
        dialog = StudyEnvironmentSaveDialog(
            slot_id, session_id, tuple(studies), result.value, self._view
        )
        self._environment_save_dialogs[slot_id] = dialog
        dialog.save_requested.connect(
            lambda intent: self._save_environment_intent(
                intent, tuple(studies), tuple(presentations)
            )
        )
        dialog.finished.connect(
            lambda _code: self._forget_environment_save_dialog(slot_id, dialog)
        )
        self._track_window(
            dialog,
            f"research.environment_save.{slot_id}",
            "Save Study Environment",
        )
        dialog.show()

    def _save_environment_intent(
        self,
        intent: StudyEnvironmentSaveIntent,
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
        try:
            draft = service._service.build_environment(
                presenter.session.dataset,
                studies,
                presentations,
                display_name=intent.display_name,
                description=intent.description,
                environment_id=intent.environment_id,
                metadata_overrides=dict(intent.metadata_overrides),
            )
            entries = tuple(
                replace(
                    entry,
                    presentation=replace(
                        entry.presentation,
                        guide_styles=tuple(
                            presentation.guide_styles.values()
                        ),
                    ),
                )
                for entry, presentation in zip(
                    draft.entries,
                    presentations,
                    strict=True,
                )
            )
            draft = replace(draft, entries=entries)
        except (TypeError, ValueError) as error:
            self._append_activity(f"Study Environment build failed: {error}")
            return
        if intent.mode == "create":
            submit = lambda callback: service.submit_create_environment(
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            )
        else:
            submit = lambda callback: service.submit_update_environment(
                intent.environment_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            )
        self._submit_setup_task(
            submit,
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
        if result.status == "completed" and isinstance(
            result.value, StudyEnvironmentV1
        ):
            self._append_activity(
                f"Chart {slot_id} Study Environment saved: "
                f"{result.value.display_name}."
            )
            for dialog in tuple(self._environment_managers.values()):
                self._refresh_environment_manager(dialog)
        else:
            self._append_activity(
                f"Chart {slot_id} Study Environment save failed: "
                f"{result.error_message or result.error_type or result.status}"
            )

    def _open_environment_manager(self, mode: str) -> None:
        if mode not in {"load", "manage"}:
            raise ValueError("mode must be 'load' or 'manage'")
        service = self._study_setup_service
        presenter = self._active_presenter()
        if service is None:
            return
        key = 0 if presenter is None else presenter.slot_id
        existing = self._environment_managers.get(key)
        if existing is not None:
            if self._environment_manager_modes.get(key) == mode:
                self._show_dialog(existing)
                return
            self._close_and_delete_dialog(existing)
            self._environment_managers.pop(key, None)
            self._environment_manager_modes.pop(key, None)
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._open_environment_manager_result(
                result, key, mode
            ),
        )

    def _open_environment_manager_result(
        self, result: TaskResult, key: int, mode: str
    ) -> None:
        if (
            result.status != "completed"
            or not isinstance(result.value, tuple)
            or not all(
                isinstance(item, StudyEnvironmentSummary)
                for item in result.value
            )
        ):
            return
        existing = self._environment_managers.get(key)
        if existing is not None:
            if self._environment_manager_modes.get(key) == mode:
                self._show_dialog(existing)
                return
            self._close_and_delete_dialog(existing)
            self._environment_managers.pop(key, None)
            self._environment_manager_modes.pop(key, None)
        targets = tuple(
            StudyEnvironmentTarget(
                slot_id,
                presenter.session.session_id,
                f"Chart {slot_id}",
                self._view.workspace.shell_state.placement_for(slot_id).detached,
            )
            for slot_id, presenter in sorted(self._chart_presenters.items())
            if presenter.session.dataset is not None
        )
        dialog = StudyEnvironmentManagerDialog(
            result.value,
            targets,
            self._view,
            mode=mode,
        )
        self._environment_managers[key] = dialog
        self._environment_manager_modes[key] = mode
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
            lambda _code: self._forget_environment_manager(key, dialog)
        )
        if dialog.selected_environment_id is not None:
            self._load_manager_environment(
                dialog, dialog.selected_environment_id
            )
        self._track_window(
            dialog,
            f"research.environment_manager.{key}",
            "Study Environments",
        )
        dialog.show()

    def _load_manager_environment(
        self, dialog: StudyEnvironmentManagerDialog, environment_id: str
    ) -> None:
        service = self._study_setup_service
        if service is None or dialog not in self._environment_managers.values():
            return
        self._submit_setup_task(
            lambda callback: service.submit_load_environment(
                environment_id,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: dialog.set_environment(result.value)
            if (
                dialog in self._environment_managers.values()
                and result.status == "completed"
                and isinstance(result.value, StudyEnvironmentV1)
                and dialog.selected_environment_id == environment_id
            )
            else None,
        )

    def _refresh_environment_manager(
        self, dialog: StudyEnvironmentManagerDialog
    ) -> None:
        service = self._study_setup_service
        if service is None or dialog not in self._environment_managers.values():
            return
        self._submit_setup_task(
            lambda callback: service.submit_list_environments(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: dialog.set_summaries(result.value)
            if (
                dialog in self._environment_managers.values()
                and result.status == "completed"
                and isinstance(result.value, tuple)
            )
            else None,
        )

    def _check_manager_compatibility(
        self,
        dialog: StudyEnvironmentManagerDialog,
        intent: StudyEnvironmentCompatibilityIntent,
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
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._manager_compatibility_result(
                dialog, intent, result
            ),
        )

    def _manager_compatibility_result(
        self,
        dialog: StudyEnvironmentManagerDialog,
        intent: StudyEnvironmentCompatibilityIntent,
        result: TaskResult,
    ) -> None:
        presenter = self._chart_presenters.get(intent.slot_id)
        if (
            dialog not in self._environment_managers.values()
            or presenter is None
            or presenter.session.session_id != intent.session_id
            or result.status != "completed"
            or not isinstance(result.value, StudyEnvironmentCompatibilityReport)
        ):
            return
        presenter.set_environment_compatibility(result.value)
        dialog.set_compatibility(intent, result.value)

    def _save_manager_metadata(
        self,
        dialog: StudyEnvironmentManagerDialog,
        intent: StudyEnvironmentMetadataIntent,
    ) -> None:
        service = self._study_setup_service
        if service is None:
            return
        self._submit_setup_task(
            lambda callback: service.submit_update_environment(
                intent.environment_id,
                intent.draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: dialog.set_environment(result.value)
            if (
                dialog in self._environment_managers.values()
                and result.status == "completed"
                and isinstance(result.value, StudyEnvironmentV1)
            )
            else None,
        )

    def _apply_manager_environment(
        self,
        dialog: StudyEnvironmentManagerDialog,
        intent: StudyEnvironmentApplyIntent,
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
            self._append_activity(
                f"Chart {intent.slot_id} Study Environment Apply failed: {error}"
            )

    def _delete_manager_environment(
        self, dialog: StudyEnvironmentManagerDialog, environment_id: str
    ) -> None:
        service = self._study_setup_service
        if service is None:
            return
        self._submit_setup_task(
            lambda callback: service.submit_delete_environment(
                environment_id,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda _result: self._refresh_environment_manager(dialog),
        )

    def _forget_environment_save_dialog(
        self, slot_id: int, dialog: StudyEnvironmentSaveDialog
    ) -> None:
        if self._environment_save_dialogs.get(slot_id) is dialog:
            self._environment_save_dialogs.pop(slot_id, None)

    def _forget_environment_manager(
        self, key: int, dialog: StudyEnvironmentManagerDialog
    ) -> None:
        if self._environment_managers.get(key) is dialog:
            self._environment_managers.pop(key, None)
            self._environment_manager_modes.pop(key, None)

    def _capture_snapshot_workspace(self) -> WorkspaceSnapshotCapture:
        presenters = self._ready_presenters()
        if self._snapshot_restore is not None or not presenters:
            raise RuntimeError(
                "workspace capture requires ready charts and no restore"
            )
        placements = self._view.workspace.shell_state.placements()
        if any(
            placement.slot_id not in self._chart_presenters
            or self._chart_presenters[placement.slot_id] not in presenters
            for placement in placements
        ):
            raise RuntimeError("all workspace charts must be ready for capture")
        refs = {
            placement.slot_id: f"chart_{index:03d}"
            for index, placement in enumerate(placements, start=1)
        }
        active_slot_id = self._view.workspace.active_slot_id
        if active_slot_id is None:
            raise RuntimeError("workspace has no active chart")
        return WorkspaceSnapshotCapture(
            self._view.workspace.visualization_mode,
            self._pan_anchor_enabled,
            refs[active_slot_id],
            tuple(
                self._chart_presenters[
                    placement.slot_id
                ].capture_snapshot_view_state(
                    chart_ref=refs[placement.slot_id],
                    workspace_position=placement.workspace_position,
                    detached=placement.detached,
                )
                for placement in placements
            ),
        )

    def _open_save_snapshot(self) -> None:
        if self._snapshot_service is None or self._snapshot_restore is not None:
            return
        if self._snapshot_save_dialog is not None:
            self._show_dialog(self._snapshot_save_dialog)
            return
        try:
            capture = self._capture_snapshot_workspace()
        except RuntimeError as error:
            self._append_activity(f"Workspace Snapshot capture blocked: {error}")
            return
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._open_snapshot_save_result(result, capture),
        )

    def _open_snapshot_save_result(
        self, result: TaskResult, capture: WorkspaceSnapshotCapture
    ) -> None:
        if result.status != "completed" or not isinstance(result.value, tuple):
            return
        if self._snapshot_save_dialog is not None:
            self._show_dialog(self._snapshot_save_dialog)
            return
        dialog = WorkspaceSnapshotSaveDialog(capture, result.value, self._view)
        self._snapshot_save_dialog = dialog
        dialog.save_requested.connect(
            lambda intent: self._save_snapshot_intent(capture, intent)
        )
        dialog.finished.connect(
            lambda _code: self._forget_snapshot_save_dialog(dialog)
        )
        self._track_window(
            dialog,
            "research.workspace_snapshot_save",
            "Save Workspace",
        )
        dialog.show()

    def _save_snapshot_intent(
        self,
        capture: WorkspaceSnapshotCapture,
        intent: WorkspaceSnapshotSaveIntent,
    ) -> None:
        try:
            draft = self._snapshot_service.build_draft(
                capture,
                display_name=intent.display_name,
                description=intent.description,
                snapshot_id=intent.snapshot_id,
            )
            draft = self._snapshot_draft_with_guides(draft, capture)
        except (TypeError, ValueError) as error:
            self._append_activity(f"Workspace Snapshot build failed: {error}")
            return
        if intent.mode == "create":
            submit = lambda callback: self._snapshot_service.submit_create_snapshot(
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            )
        else:
            submit = lambda callback: self._snapshot_service.submit_update_snapshot(
                intent.snapshot_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            )
        self._submit_snapshot_task(
            submit,
            self._snapshot_saved_result,
        )

    def _snapshot_saved_result(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, ResearchWorkspaceSnapshotV1
        ):
            self._current_workspace_snapshot_id = result.value.snapshot_id
            self._assigned_notebook_id = result.value.notebook_id
            self._sync_notebook_assignment()
            self._append_activity("Workspace Snapshot saved.")
            return
        self._append_activity(
            "Workspace Snapshot save failed: "
            f"{result.error_message or result.status}"
        )

    def _open_snapshot_manager(self, mode: str) -> None:
        if mode not in {"load", "manage"}:
            raise ValueError("mode must be 'load' or 'manage'")
        if self._snapshot_service is None or self._snapshot_restore is not None:
            return
        if self._snapshot_manager is not None:
            if self._snapshot_manager_mode == mode:
                self._show_dialog(self._snapshot_manager)
                return
            self._close_and_delete_dialog(self._snapshot_manager)
            self._snapshot_manager = None
            self._snapshot_manager_mode = None
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._open_snapshot_manager_result(result, mode),
        )

    def _open_snapshot_manager_result(
        self, result: TaskResult, mode: str
    ) -> None:
        if result.status != "completed" or not isinstance(result.value, tuple):
            return
        if self._snapshot_manager is not None:
            self._show_dialog(self._snapshot_manager)
            return
        dialog = WorkspaceSnapshotManagerDialog(
            result.value, self._view, mode=mode
        )
        self._snapshot_manager = dialog
        self._snapshot_manager_mode = mode
        dialog.refresh_requested.connect(
            lambda: self._refresh_snapshot_manager(dialog)
        )
        dialog.selection_requested.connect(
            lambda snapshot_id: self._load_snapshot_manager_selection(
                dialog, snapshot_id
            )
        )
        dialog.compatibility_requested.connect(
            lambda intent: self._check_snapshot_manager_compatibility(
                dialog, intent
            )
        )
        dialog.load_requested.connect(
            lambda intent: self._open_snapshot_preflight(dialog, intent)
        )
        dialog.metadata_requested.connect(
            lambda intent: self._save_snapshot_manager_metadata(dialog, intent)
        )
        dialog.delete_requested.connect(
            lambda snapshot_id: self._delete_snapshot_manager_selection(
                dialog, snapshot_id
            )
        )
        dialog.finished.connect(
            lambda _code: self._forget_snapshot_manager(dialog)
        )
        self._track_window(
            dialog,
            "research.workspace_snapshot_manager",
            "Manage Workspaces",
        )
        dialog.show()

    def _refresh_snapshot_manager(
        self, dialog: WorkspaceSnapshotManagerDialog
    ) -> None:
        if dialog is not self._snapshot_manager:
            return
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: dialog.set_summaries(result.value)
            if (
                dialog is self._snapshot_manager
                and result.status == "completed"
                and isinstance(result.value, tuple)
            )
            else None,
        )

    def _load_snapshot_manager_selection(
        self, dialog: WorkspaceSnapshotManagerDialog, snapshot_id: str
    ) -> None:
        if dialog is not self._snapshot_manager:
            return
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_load_snapshot(
                snapshot_id,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._snapshot_manager_loaded(
                dialog, snapshot_id, result
            ),
        )

    def _snapshot_manager_loaded(
        self,
        dialog: WorkspaceSnapshotManagerDialog,
        snapshot_id: str,
        result: TaskResult,
    ) -> None:
        if (
            dialog is not self._snapshot_manager
            or result.status != "completed"
            or not isinstance(result.value, ResearchWorkspaceSnapshotV1)
            or result.value.snapshot_id != snapshot_id
        ):
            return
        dialog.set_snapshot(result.value)
        self._check_snapshot_manager_compatibility(
            dialog, WorkspaceSnapshotLoadIntent(snapshot_id, "append")
        )

    def _check_snapshot_manager_compatibility(
        self,
        dialog: WorkspaceSnapshotManagerDialog,
        intent: WorkspaceSnapshotLoadIntent,
    ) -> None:
        snapshot = dialog.snapshot
        if (
            dialog is not self._snapshot_manager
            or snapshot is None
            or snapshot.snapshot_id != intent.snapshot_id
            or self._snapshot_restore is not None
        ):
            return
        current = {
            "occupied_positions": self._view.workspace.shell_state.reserved_positions(),
            "idle": all(
                not presenter.is_busy
                for presenter in self._chart_presenters.values()
            ),
        }
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_preflight(
                snapshot,
                intent.mode,
                current,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: dialog.set_compatibility(result.value)
            if (
                dialog is self._snapshot_manager
                and result.status == "completed"
                and isinstance(
                    result.value, ResearchWorkspaceSnapshotCompatibilityReport
                )
            )
            else None,
        )

    def _open_snapshot_preflight(
        self,
        dialog: WorkspaceSnapshotManagerDialog,
        intent: WorkspaceSnapshotLoadIntent,
    ) -> None:
        snapshot = dialog.snapshot
        report = dialog.compatibility_report
        if (
            snapshot is None
            or report is None
            or report.mode != intent.mode
            or not report.compatible
        ):
            return
        if self._snapshot_preflight_dialog is not None:
            self._show_dialog(self._snapshot_preflight_dialog)
            return
        preflight = WorkspaceSnapshotPreflightDialog(report, self._view)
        self._snapshot_preflight_dialog = preflight
        preflight.load_requested.connect(
            lambda _report: self._restore_snapshot_workspace(snapshot, report)
        )
        preflight.finished.connect(
            lambda _code: self._forget_snapshot_preflight(preflight)
        )
        self._track_window(
            preflight,
            "research.workspace_snapshot_preflight",
            "Load Workspace",
        )
        preflight.show()

    def _save_snapshot_manager_metadata(
        self,
        dialog: WorkspaceSnapshotManagerDialog,
        intent: WorkspaceSnapshotMetadataIntent,
    ) -> None:
        snapshot = dialog.snapshot
        if (
            snapshot is None
            or intent.snapshot_id != snapshot.snapshot_id
            or dialog is not self._snapshot_manager
        ):
            return
        draft = ResearchWorkspaceSnapshotDraft(
            intent.display_name,
            intent.description,
            snapshot.workspace,
            snapshot.charts,
            snapshot.snapshot_id,
        )
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_update_snapshot(
                snapshot.snapshot_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._snapshot_metadata_saved_result(
                dialog,
                result,
            ),
        )

    def _snapshot_metadata_saved_result(
        self,
        dialog: WorkspaceSnapshotManagerDialog,
        result: TaskResult,
    ) -> None:
        if (
            dialog is not self._snapshot_manager
            or result.status != "completed"
            or not isinstance(result.value, ResearchWorkspaceSnapshotV1)
        ):
            return
        dialog.set_snapshot(result.value)
        self._current_workspace_snapshot_id = result.value.snapshot_id
        self._assigned_notebook_id = result.value.notebook_id
        self._sync_notebook_assignment()

    def _delete_snapshot_manager_selection(
        self, dialog: WorkspaceSnapshotManagerDialog, snapshot_id: str
    ) -> None:
        if dialog is not self._snapshot_manager:
            return
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_delete_snapshot(
                snapshot_id,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._snapshot_deleted_result(
                dialog,
                snapshot_id,
                result,
            ),
        )

    def _snapshot_deleted_result(
        self,
        dialog: WorkspaceSnapshotManagerDialog,
        snapshot_id: str,
        result: TaskResult,
    ) -> None:
        if dialog is not self._snapshot_manager:
            return
        if (
            result.status == "completed"
            and snapshot_id == self._current_workspace_snapshot_id
        ):
            self._current_workspace_snapshot_id = None
            self._assigned_notebook_id = None
            self._sync_notebook_assignment()
        self._refresh_snapshot_manager(dialog)

    def _restore_snapshot_workspace(
        self,
        snapshot: ResearchWorkspaceSnapshotV1,
        report: ResearchWorkspaceSnapshotCompatibilityReport,
    ) -> None:
        if self._snapshot_restore is not None:
            return
        active_slot_id = self._view.workspace.active_slot_id
        active_session_id = (
            None
            if active_slot_id is None
            else self._workspace_state.session_for(active_slot_id).session_id
        )
        if report.mode == "append":
            positions = dict(report.append_positions)
            rollback = None
            preexisting = self._view.workspace.slot_ids()
        else:
            positions = {
                chart.chart_ref: chart.workspace_position
                for chart in snapshot.charts
            }
            rollback = self._capture_rollback_snapshot()
            preexisting = ()
            for slot_id in tuple(self._view.workspace.slot_ids()):
                presenter = self._chart_presenters.get(slot_id)
                if presenter is not None:
                    self._remove_chart(slot_id, presenter)
        self._snapshot_restore = _SnapshotRestoreRun(
            uuid4().hex,
            snapshot,
            report.mode,
            positions,
            preexisting,
            rollback_snapshot=rollback,
            pre_active_slot_id=active_slot_id,
            pre_active_session_id=active_session_id,
            pre_visualization_mode=self._view.workspace.visualization_mode,
            pre_pan_anchor_enabled=self._pan_anchor_enabled,
            pre_current_workspace_snapshot_id=(
                self._current_workspace_snapshot_id
            ),
            pre_assigned_notebook_id=self._assigned_notebook_id,
        )
        self._refresh_command_actions()
        self._restore_next_snapshot_chart()

    def _capture_rollback_snapshot(
        self,
    ) -> ResearchWorkspaceSnapshotV1 | None:
        if not self._chart_presenters:
            return None
        draft = self._snapshot_service.build_draft(
            capture := self._capture_snapshot_workspace(),
            display_name="In-memory rollback",
            description="Transient replace rollback state.",
            snapshot_id="snapshot_rollback",
        )
        draft = self._snapshot_draft_with_guides(draft, capture)
        now = datetime.now(timezone.utc)
        return ResearchWorkspaceSnapshotV1.build(
            snapshot_id=draft.snapshot_id or "snapshot_rollback",
            display_name=draft.display_name,
            description=draft.description,
            created_at_utc=now,
            updated_at_utc=now,
            workspace=draft.workspace,
            charts=draft.charts,
        )

    @staticmethod
    def _snapshot_draft_with_guides(
        draft: ResearchWorkspaceSnapshotDraft,
        capture: WorkspaceSnapshotCapture,
    ) -> ResearchWorkspaceSnapshotDraft:
        charts = []
        for chart, captured in zip(
            draft.charts,
            capture.charts,
            strict=True,
        ):
            environment = chart.study_environment
            if environment is None:
                charts.append(chart)
                continue
            entries = tuple(
                replace(
                    entry,
                    presentation=replace(
                        entry.presentation,
                        guide_styles=tuple(
                            presentation.guide_styles.values()
                        ),
                    ),
                )
                for entry, presentation in zip(
                    environment.entries,
                    captured.presentations,
                    strict=True,
                )
            )
            environment = StudyEnvironmentV1.build(
                environment_id=environment.environment_id,
                display_name=environment.display_name,
                description=environment.description,
                created_at_utc=environment.created_at_utc,
                updated_at_utc=environment.updated_at_utc,
                created_from=environment.created_from,
                entries=entries,
            )
            charts.append(
                replace(chart, study_environment=environment)
            )
        return replace(draft, charts=tuple(charts))

    def _restore_next_snapshot_chart(self) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        if run.index >= len(run.snapshot.charts):
            self._complete_snapshot_restore()
            return
        chart = run.snapshot.charts[run.index]
        try:
            slot_id, presenter = self._create_restored_chart(
                chart.market_id,
                workspace_position=run.positions[chart.chart_ref],
            )
        except Exception as error:
            self._fail_snapshot_restore(
                f"{chart.chart_ref} creation failed: {error}"
            )
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
            self._fail_snapshot_restore(
                f"{chart.chart_ref} dataset failed: {error}"
            )

    def _snapshot_dataset_complete(
        self, run_id: str, chart_ref: str, outcome: ChartOperationOutcome
    ) -> None:
        run = self._snapshot_restore
        if (
            run is None
            or run.run_id != run_id
            or run.snapshot.charts[run.index].chart_ref != chart_ref
        ):
            return
        if outcome.status != "success":
            self._fail_snapshot_restore(
                f"{chart_ref} dataset {outcome.status}: {outcome.message}"
            )
            return
        chart = run.snapshot.charts[run.index]
        presenter = self._chart_presenters.get(run.current_slot_id)
        if presenter is None or presenter.session.session_id != outcome.session_id:
            self._fail_snapshot_restore(
                f"{chart_ref} dataset target is no longer current"
            )
            return
        if chart.study_environment is None:
            self._finish_snapshot_chart(chart, presenter)
            return
        presenter.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(
                chart.study_environment.environment_id
            )
        )
        try:
            presenter.apply_environment(
                chart.study_environment,
                "append",
                completion_callback=lambda env_outcome, current_run=run_id, ref=chart_ref: self._snapshot_environment_complete(
                    current_run, ref, env_outcome
                ),
            )
        except Exception as error:
            self._fail_snapshot_restore(
                f"{chart_ref} environment failed: {error}"
            )

    def _snapshot_environment_complete(
        self, run_id: str, chart_ref: str, outcome: ChartOperationOutcome
    ) -> None:
        run = self._snapshot_restore
        if (
            run is None
            or run.run_id != run_id
            or run.snapshot.charts[run.index].chart_ref != chart_ref
        ):
            return
        if outcome.status != "success":
            self._fail_snapshot_restore(
                f"{chart_ref} environment {outcome.status}: {outcome.message}"
            )
            return
        presenter = self._chart_presenters.get(run.current_slot_id)
        if presenter is None or presenter.session.session_id != outcome.session_id:
            self._fail_snapshot_restore(
                f"{chart_ref} environment target is no longer current"
            )
            return
        self._finish_snapshot_chart(run.snapshot.charts[run.index], presenter)

    def _finish_snapshot_chart(
        self, chart, presenter: ResearchChartPresenter
    ) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        try:
            presenter.restore_snapshot_view_state(chart)
            if chart.detached:
                self._view.workspace.detach_chart(presenter.slot_id)
        except Exception as error:
            self._fail_snapshot_restore(
                f"{chart.chart_ref} view restore failed: {error}"
            )
            return
        run.index += 1
        run.current_slot_id = None
        self._restore_next_snapshot_chart()

    def _complete_snapshot_restore(self) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        try:
            self._view.workspace.set_visualization_mode(
                run.snapshot.workspace.visualization_mode
            )
            self._pan_anchor_enabled = run.snapshot.workspace.pan_anchor_enabled
            pan_anchor = self._view.action_for_text("Pan Anchor")
            pan_anchor.setChecked(self._pan_anchor_enabled)
            active_slot = run.chart_slots[
                run.snapshot.workspace.active_chart_ref
            ]
            self._view.workspace.set_active_slot(active_slot)
            self._workspace_state.set_active(active_slot)
        except Exception as error:
            self._fail_snapshot_restore(
                f"Workspace Snapshot finalization failed: {error}"
            )
            return
        rollback = run.rollback
        if rollback:
            self._current_workspace_snapshot_id = (
                run.pre_current_workspace_snapshot_id
            )
            self._assigned_notebook_id = run.pre_assigned_notebook_id
        else:
            self._current_workspace_snapshot_id = run.snapshot.snapshot_id
            self._assigned_notebook_id = run.snapshot.notebook_id
        self._snapshot_restore = None
        self._sync_notebook_assignment()
        self._refresh_command_actions()
        self._refresh_notebook_annotations()
        self._append_activity(
            "Workspace Snapshot rollback restored."
            if rollback
            else "Workspace Snapshot restored."
        )
        if not rollback and self._assigned_notebook_id is not None:
            self._request_notebook_transition(
                "open_assigned",
                self._assigned_notebook_id,
            )

    def _fail_snapshot_restore(self, message: str) -> None:
        run = self._snapshot_restore
        if run is None:
            return
        self._snapshot_restore = None
        for slot_id in reversed(tuple(run.added_slots)):
            presenter = self._chart_presenters.get(slot_id)
            if presenter is not None:
                self._remove_chart(slot_id, presenter)
        self._append_activity(message)
        if (
            run.mode == "replace"
            and run.rollback_snapshot is not None
            and not run.rollback
        ):
            rollback = run.rollback_snapshot
            self._snapshot_restore = _SnapshotRestoreRun(
                uuid4().hex,
                rollback,
                "replace",
                {
                    chart.chart_ref: chart.workspace_position
                    for chart in rollback.charts
                },
                (),
                rollback=True,
                pre_current_workspace_snapshot_id=(
                    run.pre_current_workspace_snapshot_id
                ),
                pre_assigned_notebook_id=run.pre_assigned_notebook_id,
            )
            self._restore_next_snapshot_chart()
            return
        if run.mode == "append" and run.pre_active_slot_id is not None:
            if (
                run.pre_active_slot_id in self._view.workspace.slot_ids()
                and self._workspace_state.session_for(
                    run.pre_active_slot_id
                ).session_id
                == run.pre_active_session_id
            ):
                self._view.workspace.set_active_slot(run.pre_active_slot_id)
                self._workspace_state.set_active(run.pre_active_slot_id)
            self._view.workspace.set_visualization_mode(
                run.pre_visualization_mode
            )
            self._pan_anchor_enabled = run.pre_pan_anchor_enabled
        self._current_workspace_snapshot_id = (
            run.pre_current_workspace_snapshot_id
        )
        self._assigned_notebook_id = run.pre_assigned_notebook_id
        self._sync_notebook_assignment()
        self._refresh_command_actions()
        self._append_activity("Workspace Snapshot restore failed.")

    def _forget_snapshot_save_dialog(
        self, dialog: WorkspaceSnapshotSaveDialog
    ) -> None:
        if self._snapshot_save_dialog is dialog:
            self._snapshot_save_dialog = None

    def _forget_snapshot_manager(
        self, dialog: WorkspaceSnapshotManagerDialog
    ) -> None:
        if self._snapshot_manager is dialog:
            self._snapshot_manager = None
            self._snapshot_manager_mode = None

    def _forget_snapshot_preflight(
        self, dialog: WorkspaceSnapshotPreflightDialog
    ) -> None:
        if self._snapshot_preflight_dialog is dialog:
            self._snapshot_preflight_dialog = None

    def _new_notebook(self) -> None:
        if self._notebook_service is None:
            return
        self._request_notebook_transition("new", None)

    def _open_assigned_notebook(self) -> None:
        if (
            self._notebook_service is not None
            and self._assigned_notebook_id is not None
        ):
            self._request_notebook_transition(
                "open_assigned", self._assigned_notebook_id
            )

    def _open_notebook_manager(self) -> None:
        if (
            self._notebook_service is None
            or self._snapshot_service is None
            or self._notebook_task_id is not None
        ):
            return
        if self._notebook_manager is not None:
            self._show_dialog(self._notebook_manager)
            return
        self._submit_notebook_task(
            lambda callback: self._notebook_service.submit_list_notebooks(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            self._open_notebook_manager_result,
        )

    def _open_notebook_manager_result(self, result: TaskResult) -> None:
        if (
            result.status != "completed"
            or not isinstance(result.value, tuple)
            or not all(
                isinstance(item, ResearchNotebookSummary)
                for item in result.value
            )
        ):
            return
        if self._notebook_manager is not None:
            self._show_dialog(self._notebook_manager)
            return
        summaries = result.value
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda snapshot_result: self._open_notebook_manager_assignments(
                summaries,
                snapshot_result,
            ),
        )

    def _open_notebook_manager_assignments(
        self,
        summaries: tuple[ResearchNotebookSummary, ...],
        result: TaskResult,
    ) -> None:
        if (
            self._notebook_manager is not None
            or result.status != "completed"
            or not isinstance(result.value, tuple)
            or not all(
                isinstance(item, ResearchWorkspaceSnapshotSummary)
                for item in result.value
            )
        ):
            return
        dialog = ResearchNotebookManagerDialog(
            summaries,
            self._view,
            assignments=self._notebook_assignments(result.value),
        )
        self._notebook_manager = dialog
        dialog.refresh_requested.connect(
            lambda: self._refresh_notebook_manager(dialog)
        )
        dialog.open_requested.connect(
            lambda notebook_id: self._request_notebook_transition(
                "open", notebook_id
            )
        )
        dialog.delete_requested.connect(
            lambda notebook_id: self._delete_notebook(dialog, notebook_id)
        )
        dialog.assign_requested.connect(
            lambda notebook_id, snapshot_id: self._assign_notebook(
                dialog,
                snapshot_id,
                notebook_id,
            )
        )
        dialog.unassign_requested.connect(
            lambda notebook_id, snapshot_id: self._unassign_notebook(
                dialog,
                snapshot_id,
                notebook_id,
            )
        )
        dialog.finished.connect(
            lambda _code: self._forget_notebook_manager(dialog)
        )
        self._track_window(
            dialog,
            "research.notebook_manager",
            "Research Notebooks",
        )
        dialog.show()

    def _refresh_notebook_manager(
        self, dialog: ResearchNotebookManagerDialog
    ) -> None:
        if dialog is not self._notebook_manager:
            return
        self._submit_notebook_task(
            lambda callback: self._notebook_service.submit_list_notebooks(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._refresh_notebook_manager_summaries(
                dialog,
                result,
            ),
        )

    def _refresh_notebook_manager_summaries(
        self,
        dialog: ResearchNotebookManagerDialog,
        result: TaskResult,
    ) -> None:
        if (
            dialog is not self._notebook_manager
            or result.status != "completed"
            or not isinstance(result.value, tuple)
            or not all(
                isinstance(item, ResearchNotebookSummary)
                for item in result.value
            )
        ):
            return
        dialog.set_summaries(result.value)
        self._submit_snapshot_task(
            lambda callback: self._snapshot_service.submit_list_snapshots(
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda snapshot_result: self._refresh_notebook_assignments(
                dialog,
                snapshot_result,
            ),
        )

    def _refresh_notebook_assignments(
        self,
        dialog: ResearchNotebookManagerDialog,
        result: TaskResult,
    ) -> None:
        if (
            dialog is self._notebook_manager
            and result.status == "completed"
            and isinstance(result.value, tuple)
            and all(
                isinstance(item, ResearchWorkspaceSnapshotSummary)
                for item in result.value
            )
        ):
            dialog.set_assignments(
                self._notebook_assignments(result.value)
            )

    @staticmethod
    def _notebook_assignments(
        summaries: tuple[ResearchWorkspaceSnapshotSummary, ...],
    ) -> tuple[ResearchNotebookSnapshotAssignment, ...]:
        return tuple(
            ResearchNotebookSnapshotAssignment(
                summary.snapshot_id,
                summary.display_name,
                summary.notebook_id,
            )
            for summary in summaries
            if summary.valid
        )

    def _assign_notebook(
        self,
        dialog: ResearchNotebookManagerDialog,
        snapshot_id: str,
        notebook_id: str,
    ) -> None:
        if dialog is not self._notebook_manager:
            return
        if self._notebook_link_operation_token is not None:
            self._append_activity(
                "Notebook linkage operation is already in progress."
            )
            return
        operation_token = uuid4().hex
        self._notebook_link_operation_token = operation_token
        try:
            self._submit_snapshot_task(
                lambda callback: self._snapshot_service.submit_assign_notebook(
                    snapshot_id,
                    notebook_id,
                    result_callback=callback,
                    callback_dispatcher=self._dispatch,
                ),
                lambda result: self._notebook_assignment_result(
                    dialog,
                    snapshot_id,
                    notebook_id,
                    True,
                    operation_token,
                    result,
                ),
            )
        except Exception as exc:
            if self._notebook_link_operation_token == operation_token:
                self._notebook_link_operation_token = None
            self._append_activity(
                f"Notebook assignment update failed: {exc}"
            )

    def _unassign_notebook(
        self,
        dialog: ResearchNotebookManagerDialog,
        snapshot_id: str,
        notebook_id: str,
    ) -> None:
        if dialog is not self._notebook_manager:
            return
        if self._notebook_link_operation_token is not None:
            self._append_activity(
                "Notebook linkage operation is already in progress."
            )
            return
        operation_token = uuid4().hex
        self._notebook_link_operation_token = operation_token
        try:
            self._submit_snapshot_task(
                lambda callback: self._snapshot_service.submit_unassign_notebook(
                    snapshot_id,
                    notebook_id,
                    result_callback=callback,
                    callback_dispatcher=self._dispatch,
                ),
                lambda result: self._notebook_assignment_result(
                    dialog,
                    snapshot_id,
                    notebook_id,
                    False,
                    operation_token,
                    result,
                ),
            )
        except Exception as exc:
            if self._notebook_link_operation_token == operation_token:
                self._notebook_link_operation_token = None
            self._append_activity(
                f"Notebook assignment update failed: {exc}"
            )

    def _notebook_assignment_result(
        self,
        dialog: ResearchNotebookManagerDialog,
        snapshot_id: str,
        notebook_id: str,
        assigned: bool,
        operation_token: str,
        result: TaskResult,
    ) -> None:
        if operation_token != self._notebook_link_operation_token:
            return
        self._notebook_link_operation_token = None
        if result.status == "completed" and isinstance(
            result.value, ResearchWorkspaceSnapshotV1
        ):
            if snapshot_id == self._current_workspace_snapshot_id:
                self._assigned_notebook_id = result.value.notebook_id
                self._sync_notebook_assignment()
            self._append_activity(
                (
                    f"Notebook {notebook_id} assigned to {snapshot_id}."
                    if assigned
                    else f"Notebook {notebook_id} unassigned from {snapshot_id}."
                )
            )
        else:
            self._append_activity(
                "Notebook assignment update failed: "
                f"{result.error_message or result.status}"
            )
        if dialog is self._notebook_manager:
            self._refresh_notebook_manager(dialog)

    def _request_notebook_transition(
        self, action: str, notebook_id: str | None
    ) -> None:
        if self._notebook_task_id is not None:
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
        self, action: str, notebook_id: str | None
    ) -> None:
        if action == "new":
            self._close_notebook_editor()
            pages = tuple(
                ResearchNotebookPageV1(presenter.session.dataset.market_id)
                for presenter in self._chart_presenters.values()
                if presenter.session.dataset is not None
            )
            self._open_notebook_editor(
                draft=ResearchNotebookDraft(
                    "Untitled Notebook",
                    "",
                    ResearchNotebookAnnotationSettingsV1(),
                    pages,
                )
            )
            return
        if action in {"open", "open_assigned"} and notebook_id is not None:
            self._close_notebook_editor()
            self._load_notebook(
                notebook_id,
                assigned_snapshot_id=(
                    self._current_workspace_snapshot_id
                    if action == "open_assigned"
                    else None
                ),
            )
            return
        raise ValueError("unknown Research Notebook transition")

    def _load_notebook(
        self,
        notebook_id: str,
        *,
        assigned_snapshot_id: str | None = None,
    ) -> None:
        self._submit_notebook_task(
            lambda callback: self._notebook_service.submit_load_notebook(
                notebook_id,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            ),
            lambda result: self._loaded_notebook_result(
                notebook_id,
                assigned_snapshot_id,
                result,
            ),
        )

    def _loaded_notebook_result(
        self,
        notebook_id: str,
        assigned_snapshot_id: str | None,
        result: TaskResult,
    ) -> None:
        if (
            result.status != "completed"
            or not isinstance(result.value, ResearchNotebookV1)
            or result.value.notebook_id != notebook_id
            or (
                assigned_snapshot_id is not None
                and (
                    assigned_snapshot_id
                    != self._current_workspace_snapshot_id
                    or notebook_id != self._assigned_notebook_id
                )
            )
        ):
            if (
                assigned_snapshot_id is not None
                and result.status != "completed"
            ):
                self._append_activity(
                    "Assigned Notebook open failed: "
                    f"{result.error_message or result.status}"
                )
            return
        self._open_notebook_editor(notebook=result.value)

    def _open_notebook_editor(
        self,
        *,
        notebook: ResearchNotebookV1 | None = None,
        draft: ResearchNotebookDraft | None = None,
    ) -> None:
        if (notebook is None) == (draft is None):
            raise ValueError("provide exactly one notebook editor value")
        if self._notebook_editor is not None:
            self._close_notebook_editor()
        editor = ResearchNotebookWindow(self._view)
        self._notebook_editor = editor
        self._active_notebook = notebook
        if notebook is not None:
            editor.set_notebook(notebook)
            self._last_valid_notebook_draft = ResearchNotebookDraft(
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
            lambda value: self._notebook_draft_changed(editor, value)
        )
        editor.save_requested.connect(
            lambda intent: self._notebook_save_requested(editor, intent)
        )
        editor.close_requested.connect(
            lambda: self._request_notebook_transition_close(editor)
        )
        editor.add_current_chart_requested.connect(
            lambda: self._add_current_chart_page(editor)
        )
        editor.go_to_requested.connect(self._notebook_go_to)
        self._track_window(
            editor,
            "research.notebook_editor",
            "Research Notebook",
        )
        self._sync_notebook_assignment()
        self._refresh_command_actions()
        editor.show()
        self._refresh_notebook_annotations()

    def _request_notebook_transition_close(
        self, editor: ResearchNotebookWindow
    ) -> None:
        if editor is not self._notebook_editor:
            return
        if editor.is_dirty:
            decision = editor.dirty_decision()
            if decision == "cancel":
                return
            if decision == "save":
                self._notebook_pending_action = ("close", None)
                self._save_notebook_editor(False)
                return
        self._close_notebook_editor()

    def _notebook_draft_changed(
        self,
        editor: ResearchNotebookWindow,
        draft: ResearchNotebookDraft,
    ) -> None:
        if editor is not self._notebook_editor:
            return
        self._last_valid_notebook_draft = draft
        self._refresh_notebook_annotations()
        self._refresh_command_actions()

    def _notebook_save_requested(
        self,
        editor: ResearchNotebookWindow,
        intent: ResearchNotebookSaveIntent,
    ) -> None:
        if editor is self._notebook_editor:
            self._last_valid_notebook_draft = intent.draft
            self._save_notebook_editor(intent.save_as)

    def _save_notebook_editor(self, save_as: bool) -> None:
        editor = self._notebook_editor
        if (
            editor is None
            or self._notebook_task_id is not None
            or not editor.is_current_valid
        ):
            self._notebook_pending_action = None
            return
        try:
            draft = editor.current_draft()
        except (ValueError, ResearchNotebookValidationError) as error:
            self._notebook_pending_action = None
            editor.set_status(f"Save blocked: {error}")
            self._refresh_command_actions()
            return
        self._last_valid_notebook_draft = draft
        editor.set_save_pending(True)
        if save_as or editor.notebook_id is None:
            create_draft = ResearchNotebookDraft(
                draft.display_name,
                draft.description,
                draft.annotation_settings,
                draft.pages,
                None,
            )
            submit = lambda callback: self._notebook_service.submit_create_notebook(
                create_draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            )
        else:
            submit = lambda callback: self._notebook_service.submit_update_notebook(
                editor.notebook_id,
                draft,
                result_callback=callback,
                callback_dispatcher=self._dispatch,
            )
        self._submit_notebook_task(
            submit,
            lambda result: self._saved_notebook_result(editor, result),
        )

    def _saved_notebook_result(
        self, editor: ResearchNotebookWindow, result: TaskResult
    ) -> None:
        pending = self._notebook_pending_action
        self._notebook_pending_action = None
        if editor is not self._notebook_editor:
            return
        editor.set_save_pending(False)
        if result.status != "completed" or not isinstance(
            result.value, ResearchNotebookV1
        ):
            editor.set_status(
                "Save failed: "
                f"{result.error_message or result.error_type or result.status}"
            )
            self._refresh_command_actions()
            return
        self._active_notebook = result.value
        editor.set_notebook(result.value)
        self._last_valid_notebook_draft = editor.last_valid_draft
        self._sync_notebook_assignment()
        self._refresh_notebook_annotations()
        if self._notebook_manager is not None:
            self._refresh_notebook_manager(self._notebook_manager)
        if pending is not None:
            if pending[0] == "close":
                self._close_notebook_editor()
            else:
                self._perform_notebook_transition(*pending)

    def _delete_notebook(
        self,
        dialog: ResearchNotebookManagerDialog,
        notebook_id: str,
    ) -> None:
        if dialog is not self._notebook_manager:
            return
        if self._notebook_link_operation_token is not None:
            self._append_activity(
                "Notebook linkage operation is already in progress."
            )
            return
        if self._notebook_task_id is not None:
            return
        editor = self._notebook_editor
        if editor is not None and editor.notebook_id == notebook_id:
            if editor.is_dirty:
                decision = editor.dirty_decision()
                if decision != "discard":
                    return
            self._close_notebook_editor()
        operation_token = uuid4().hex
        self._notebook_link_operation_token = operation_token
        try:
            self._submit_notebook_task(
                lambda callback: self._notebook_service.submit_delete_notebook(
                    notebook_id,
                    result_callback=callback,
                    callback_dispatcher=self._dispatch,
                ),
                lambda result: self._deleted_notebook_result(
                    dialog, notebook_id, operation_token, result
                ),
            )
        except Exception as exc:
            if self._notebook_link_operation_token == operation_token:
                self._notebook_link_operation_token = None
            self._append_activity(f"Notebook delete failed: {exc}")

    def _deleted_notebook_result(
        self,
        dialog: ResearchNotebookManagerDialog,
        notebook_id: str,
        operation_token: str,
        result: TaskResult,
    ) -> None:
        if operation_token != self._notebook_link_operation_token:
            return
        self._notebook_link_operation_token = None
        if result.status == "completed":
            if self._assigned_notebook_id == notebook_id:
                self._assigned_notebook_id = None
                self._sync_notebook_assignment()
            self._append_activity(f"Notebook {notebook_id} deleted.")
        else:
            self._append_activity(
                "Notebook delete failed: "
                f"{result.error_message or result.status}"
            )
        if dialog is self._notebook_manager:
            self._refresh_notebook_manager(dialog)

    def _add_current_chart_page(
        self, editor: ResearchNotebookWindow
    ) -> None:
        presenter = self._active_presenter()
        if (
            editor is self._notebook_editor
            and presenter is not None
            and presenter.session.dataset is not None
        ):
            editor.add_page(
                ResearchNotebookPageV1(presenter.session.dataset.market_id)
            )

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
            self._append_activity(
                f"No open Research chart for {market_id.as_key()}."
            )
            return
        active = self._active_presenter()
        target = (
            active
            if active in candidates
            else min(
                candidates,
                key=lambda item: self._view.workspace.shell_state.placement_for(
                    item.slot_id
                ).workspace_position,
            )
        )
        self._view.workspace.set_active_slot(target.slot_id)
        self._workspace_state.set_active(target.slot_id)
        target.go_to_timestamp_ms(timestamp_ms)
        self._refresh_command_actions()

    def _refresh_notebook_annotations(self) -> None:
        if self._snapshot_restore is not None:
            return
        draft = self._last_valid_notebook_draft
        if self._notebook_editor is None or draft is None:
            for presenter in self._chart_presenters.values():
                presenter.clear_notebook_annotations()
            return
        now = datetime(2000, 1, 1, tzinfo=timezone.utc)
        notebook = ResearchNotebookV1.build(
            notebook_id=draft.notebook_id or "notebook_unsaved",
            display_name=draft.display_name,
            description=draft.description,
            created_at_utc=now,
            updated_at_utc=now,
            annotation_settings=draft.annotation_settings,
            pages=draft.pages,
        )
        for presenter in self._chart_presenters.values():
            dataset = presenter.session.dataset
            if dataset is None:
                presenter.clear_notebook_annotations()
            else:
                presenter.set_notebook_annotations(
                    self._notebook_service.project_annotations(
                        notebook, dataset.market_id
                    )
                )

    def _close_notebook_editor(self) -> None:
        editor = self._notebook_editor
        self._notebook_editor = None
        self._active_notebook = None
        self._last_valid_notebook_draft = None
        self._notebook_pending_action = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()
        for presenter in self._chart_presenters.values():
            presenter.clear_notebook_annotations()
        self._refresh_command_actions()

    def _forget_notebook_manager(
        self, dialog: ResearchNotebookManagerDialog
    ) -> None:
        if self._notebook_manager is dialog:
            self._notebook_manager = None

    def _sync_notebook_assignment(self) -> None:
        notebook_id = self._assigned_notebook_id
        name = None
        if notebook_id is not None:
            if (
                self._active_notebook is not None
                and self._active_notebook.notebook_id == notebook_id
            ):
                name = self._active_notebook.display_name
            elif self._notebook_manager is not None:
                name = next(
                    (
                        summary.display_name
                        for summary in self._notebook_manager.summaries
                        if summary.valid
                        and summary.notebook_id == notebook_id
                    ),
                    None,
                )
            if name is None:
                name = notebook_id
        self._view.set_assigned_notebook_state(name)

    def _open_financial_tools(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._disposed
            or self._study_setup_service is None
            or presenter is None
            or presenter.is_disposed
            or presenter.is_busy
            or presenter.session.dataset is None
            or presenter.viewport is None
        ):
            self._append_activity(
                f"Chart {slot_id} Financial Tools dialog target stale."
            )
            return
        self._financial_tools_open_requested.add(slot_id)
        if slot_id in self._active_study_setup_catalog_tasks:
            return
        study_ids = tuple(study.study_id for study in presenter.session.studies)
        dialog = self._financial_tools_dialogs.get(slot_id)
        if (
            dialog is not None
            and self._catalog_visible_study_ids.get(slot_id) == study_ids
        ):
            self._financial_tools_open_requested.discard(slot_id)
            dialog.prepare_for_open()
            self._show_financial_tools_dialog(dialog)
            return
        self._submit_study_setup_catalog(slot_id, open_when_ready=True)

    def _submit_study_setup_catalog(
        self, slot_id: int, *, open_when_ready: bool
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        dataset = None if presenter is None else presenter.session.dataset
        if (
            self._disposed
            or self._study_setup_service is None
            or presenter is None
            or presenter.is_disposed
            or presenter.is_busy
            or dataset is None
            or presenter.viewport is None
            or slot_id in self._active_study_setup_catalog_tasks
        ):
            if open_when_ready:
                self._financial_tools_open_requested.discard(slot_id)
            return
        studies = presenter.session.studies
        study_ids = tuple(study.study_id for study in studies)
        if open_when_ready:
            self._financial_tools_open_requested.add(slot_id)
        panel = self._view.workspace.chart_panel_for_slot(slot_id)
        panel.set_financial_tools_available(False)
        dialog = self._financial_tools_dialogs.get(slot_id)
        if dialog is not None:
            dialog.set_busy(True, "Building Financial Tools catalog...")
        self._append_activity(
            f"Chart {slot_id} Financial Tools catalog started."
        )
        try:
            submission = self._study_setup_service.submit_catalog(
                dataset,
                studies,
                result_callback=self._on_study_setup_catalog_result,
                callback_dispatcher=self._dispatch,
            )
        except Exception as error:
            self._financial_tools_open_requested.discard(slot_id)
            if dialog is not None:
                dialog.set_busy(False)
            self._append_activity(
                f"Chart {slot_id} Financial Tools catalog failed: {error}"
            )
            self._sync_financial_tools_state(slot_id, presenter)
            return
        attempt = _StudySetupCatalogAttempt(
            submission.task_id,
            slot_id,
            presenter.session.session_id,
            presenter.session.generation,
            presenter,
            dataset,
            study_ids,
            self._catalog_revisions.get(slot_id, 0),
        )
        self._active_study_setup_catalog_tasks[slot_id] = submission.task_id
        self._study_setup_catalog_attempts[slot_id] = attempt

    def _on_study_setup_catalog_result(self, result: TaskResult) -> None:
        attempt = next(
            (
                item
                for item in self._study_setup_catalog_attempts.values()
                if item.task_id == result.task_id
            ),
            None,
        )
        if attempt is None:
            return
        slot_id = attempt.slot_id
        if self._active_study_setup_catalog_tasks.get(slot_id) != result.task_id:
            return
        self._active_study_setup_catalog_tasks.pop(slot_id, None)
        self._study_setup_catalog_attempts.pop(slot_id, None)
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._disposed
            or presenter is not attempt.presenter
            or presenter is None
            or presenter.is_disposed
            or presenter.session.session_id != attempt.session_id
            or presenter.session.generation != attempt.generation
            or presenter.session.dataset is not attempt.dataset
        ):
            self._financial_tools_open_requested.discard(slot_id)
            self._study_edit_open_targets.pop(slot_id, None)
            self._append_activity(
                f"Chart {slot_id} Financial Tools dialog target stale."
            )
            return
        if attempt.revision != self._catalog_revisions.get(slot_id, 0):
            self._deferred_catalog_refresh.add(slot_id)
            self._submit_deferred_catalog_refresh(slot_id, presenter)
            return
        if result.status != "completed" or not isinstance(
            result.value, StudySetupCatalog
        ):
            self._financial_tools_open_requested.discard(slot_id)
            self._study_edit_open_targets.pop(slot_id, None)
            detail = result.error_message or result.error_type or result.status
            dialog = self._financial_tools_dialogs.get(slot_id)
            if dialog is not None:
                dialog.set_busy(False)
            self._append_activity(
                f"Chart {slot_id} Financial Tools catalog failed: {detail}"
            )
            self._sync_financial_tools_state(slot_id, presenter)
            self._submit_deferred_catalog_refresh(slot_id, presenter)
            return
        catalog = result.value
        if catalog.market_id != attempt.dataset.market_id:
            self._financial_tools_open_requested.discard(slot_id)
            self._study_edit_open_targets.pop(slot_id, None)
            self._append_activity(
                f"Chart {slot_id} Financial Tools catalog failed: MarketId mismatch"
            )
            self._sync_financial_tools_state(slot_id, presenter)
            self._submit_deferred_catalog_refresh(slot_id, presenter)
            return
        dialog = self._financial_tools_dialogs.get(slot_id)
        if dialog is None:
            dialog = ResearchFinancialToolsDialog(
                attempt.dataset.market_id, catalog, self._view
            )
            dialog.apply_requested.connect(
                lambda request, current=slot_id, captured=dialog: (
                    self._submit_study_calculation(current, captured, request)
                )
            )
            dialog.apply_saved_artifact_requested.connect(
                lambda request, current=slot_id, captured=dialog: (
                    self._submit_saved_artifact_apply(current, captured, request)
                )
            )
            self._financial_tools_dialogs[slot_id] = dialog
            if self._window_tracker is not None:
                self._window_tracker(
                    dialog,
                    f"research_restoration.financial_tools.{slot_id}",
                    "Financial Tools",
                    "dialog",
                )
        else:
            dialog.set_catalog(catalog)
        dialog.set_busy(False)
        self._catalog_visible_study_ids[slot_id] = attempt.study_ids
        self._append_activity(
            f"Chart {slot_id} Financial Tools catalog ready: "
            f"{len(catalog.tools)} tool(s)."
        )
        should_open = slot_id in self._financial_tools_open_requested
        self._financial_tools_open_requested.discard(slot_id)
        edit_target = self._study_edit_open_targets.pop(slot_id, None)
        if edit_target is not None:
            study = self._current_edit_target(edit_target)
            if study is None:
                self._append_activity(
                    f"Chart {slot_id} Study Edit target stale."
                )
            else:
                try:
                    self._show_study_edit_dialog(
                        slot_id,
                        presenter,
                        catalog,
                        study,
                    )
                except (TypeError, ValueError) as error:
                    self._append_activity(
                        f"Chart {slot_id} Study Edit form failed: {error}"
                    )
        elif should_open:
            dialog.prepare_for_open()
            self._show_financial_tools_dialog(dialog)
        self._sync_financial_tools_state(slot_id, presenter)
        self._submit_deferred_catalog_refresh(slot_id, presenter)

    def _request_study_catalog_refresh(
        self, slot_id: int, presenter: ResearchChartPresenter
    ) -> None:
        self._catalog_revisions[slot_id] = self._catalog_revisions.get(slot_id, 0) + 1
        if slot_id in self._active_study_setup_catalog_tasks:
            self._deferred_catalog_refresh.add(slot_id)
            return
        self._submit_study_setup_catalog(slot_id, open_when_ready=False)

    def _submit_deferred_catalog_refresh(
        self, slot_id: int, presenter: ResearchChartPresenter
    ) -> None:
        if (
            slot_id not in self._deferred_catalog_refresh
            or slot_id in self._active_study_setup_catalog_tasks
            or self._chart_presenters.get(slot_id) is not presenter
            or presenter.is_busy
        ):
            return
        self._deferred_catalog_refresh.discard(slot_id)
        self._submit_study_setup_catalog(slot_id, open_when_ready=False)

    def _submit_study_calculation(
        self,
        slot_id: int,
        dialog: ResearchFinancialToolsDialog,
        intent: object,
    ) -> None:
        presenter = self._financial_tools_target(slot_id, dialog)
        if presenter is None:
            self._append_activity(
                f"Chart {slot_id} Financial Tools dialog target stale."
            )
            return
        if not isinstance(intent, ResearchStudyApplyIntent):
            self._append_activity(
                f"Chart {slot_id} Study Apply submission failed: invalid request"
            )
            return
        session_id = presenter.session.session_id
        dialog.set_busy(True, "Applying Study...")
        try:
            presenter.submit_study_calculation(
                intent.request,
                completion_callback=lambda outcome, current=slot_id, captured=dialog, owner=presenter, submitted=intent, session=session_id: self._on_study_calculation_complete(
                    current,
                    captured,
                    owner,
                    session,
                    submitted,
                    outcome,
                ),
            )
        except Exception as error:
            dialog.set_busy(False)
            self._sync_financial_tools_state(slot_id, presenter)
            self._append_activity(
                f"Chart {slot_id} Study Apply submission failed: {error}"
            )

    def _on_study_calculation_complete(
        self,
        slot_id: int,
        dialog: ResearchFinancialToolsDialog,
        presenter: ResearchChartPresenter,
        session_id: str,
        intent: ResearchStudyApplyIntent,
        outcome: StudyOperationOutcome,
    ) -> None:
        if (
            self._disposed
            or self._financial_tools_dialogs.get(slot_id) is not dialog
            or self._chart_presenters.get(slot_id) is not presenter
            or presenter.is_disposed
            or presenter.session.session_id != session_id
            or outcome.slot_id != slot_id
            or outcome.session_id != session_id
        ):
            return
        if outcome.status == "success" and outcome.study_id is not None:
            presentation = self._presentation(presenter, outcome.study_id)
            if presentation is None:
                dialog.set_busy(False)
                self._append_activity(
                    f"Chart {slot_id} Study Apply failed: "
                    "accepted Study presentation is unavailable"
                )
                return
            if tuple(intent.guide_values) != tuple(presentation.guide_styles):
                dialog.set_busy(False)
                self._append_activity(
                    f"Chart {slot_id} Study Apply failed: "
                    "guide value identities do not match Study presentation"
                )
                return
            if intent.guide_values:
                try:
                    presenter.apply_guide_values(
                        outcome.study_id,
                        intent.guide_values,
                    )
                except Exception as error:
                    dialog.set_busy(False)
                    self._append_activity(
                        f"Chart {slot_id} Study guide Apply failed: {error}"
                    )
                    return
            self._append_activity(
                f"Chart {slot_id} Study Apply completed: {outcome.study_id}."
            )
            self._refresh_studies_manager(slot_id, presenter)
            self._refresh_study_style_dialogs(slot_id, presenter)
        else:
            self._append_activity(
                f"Chart {slot_id} Study Apply {outcome.status}: "
                f"{outcome.message}"
            )
            dialog.set_busy(False)
        self._sync_financial_tools_state(slot_id, presenter)

    def _open_study_edit(self, slot_id: int, study_id: str) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            not self._study_target_is_ready(slot_id, presenter, require_idle=True)
            or not self._study_exists(presenter, study_id)
        ):
            self._append_activity(
                f"Chart {slot_id} stale Study Edit target rejected."
            )
            return
        entry = next(
            (
                item
                for item in presenter.session.study_manager_entries()
                if item.study_id == study_id
            ),
            None,
        )
        if entry is None:
            self._append_activity(
                f"Chart {slot_id} stale Study Edit target rejected."
            )
            return
        if entry.dependent_study_ids:
            self._append_activity(
                f"Study {study_id} cannot be edited while required by: "
                f"{', '.join(entry.dependent_study_ids)}"
            )
            return
        existing = self._study_edit_dialogs.get((slot_id, study_id))
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        self._study_edit_open_targets[slot_id] = _StudyEditOpenTarget(
            slot_id,
            presenter.session.session_id,
            presenter.session.generation,
            presenter,
            study_id,
        )
        self._append_activity(f"Chart {slot_id} Study Edit catalog started.")
        self._submit_study_setup_catalog(slot_id, open_when_ready=False)

    def _show_study_edit_dialog(
        self,
        slot_id: int,
        presenter: ResearchChartPresenter,
        catalog: StudySetupCatalog,
        study,
    ) -> None:
        key = (slot_id, study.study_id)
        existing = self._study_edit_dialogs.get(key)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dataset = presenter.session.dataset
        presentation = self._presentation(presenter, study.study_id)
        if dataset is None or presentation is None:
            raise ValueError("Study Edit target is unavailable")
        dialog = ResearchStudyEditDialog(
            dataset.market_id,
            catalog,
            study.study_id,
            study.edit_request,
            presentation,
        )
        self._study_edit_dialogs[key] = dialog
        dialog.edit_requested.connect(
            lambda intent, current=slot_id, current_study=study.study_id, captured=dialog: (
                self._submit_study_edit_intent(
                    current,
                    current_study,
                    captured,
                    intent,
                )
            )
        )
        dialog.finished.connect(
            lambda _result, current=slot_id, current_study=study.study_id, captured=dialog: (
                self._on_study_edit_finished(
                    current,
                    current_study,
                    captured,
                )
            )
        )
        dialog.setParent(self._view, dialog.windowFlags())
        if self._window_tracker is not None:
            self._window_tracker(
                dialog,
                f"research_restoration.study_edit.{slot_id}.{study.study_id}",
                "Edit Study",
                "dialog",
            )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _current_edit_target(self, target: _StudyEditOpenTarget):
        presenter = self._chart_presenters.get(target.slot_id)
        if (
            self._disposed
            or presenter is not target.presenter
            or presenter is None
            or presenter.is_disposed
            or presenter.session.session_id != target.session_id
            or presenter.session.generation != target.generation
        ):
            return None
        return next(
            (
                study
                for study in presenter.session.studies
                if study.study_id == target.study_id
            ),
            None,
        )

    def _submit_study_edit_intent(
        self,
        slot_id: int,
        study_id: str,
        dialog: ResearchStudyEditDialog,
        intent: object,
    ) -> None:
        presenter = self._study_edit_target(slot_id, study_id, dialog)
        if (
            presenter is None
            or not isinstance(intent, ResearchStudyEditIntent)
            or intent.study_id != study_id
        ):
            self._append_activity(f"Chart {slot_id} Study Edit target stale.")
            return
        if intent.guide_changed and not intent.calculation_changed:
            try:
                presenter.apply_guide_values(study_id, intent.guide_values)
            except Exception as error:
                dialog.set_operation_failure(str(error))
                self._append_activity(
                    f"Chart {slot_id} Study guide Edit failed: {error}"
                )
                return
            study = presenter.session.study_registry.get(study_id)
            presentation = self._presentation(presenter, study_id)
            if presentation is None:
                dialog.set_operation_failure(
                    "updated Study presentation is unavailable"
                )
                return
            dialog.accept_applied_state(study.edit_request, presentation)
            self._append_activity(
                f"Chart {slot_id} Study guide Edit completed: {study_id}."
            )
            self._refresh_studies_manager(slot_id, presenter)
            return
        dialog.set_busy(True, "Editing Study...")
        try:
            presenter.submit_study_edit(
                study_id,
                intent.request,
                completion_callback=lambda outcome, current=slot_id, current_study=study_id, captured=dialog, owner=presenter, submitted=intent: self._on_study_edit_complete(
                    current,
                    current_study,
                    captured,
                    owner,
                    submitted,
                    outcome,
                ),
            )
        except Exception as error:
            dialog.set_busy(False)
            self._sync_financial_tools_state(slot_id, presenter)
            self._append_activity(
                f"Chart {slot_id} Study Edit submission failed: {error}"
            )

    def _on_study_edit_complete(
        self,
        slot_id: int,
        study_id: str,
        dialog: ResearchStudyEditDialog,
        presenter: ResearchChartPresenter,
        intent: ResearchStudyEditIntent,
        outcome: StudyOperationOutcome,
    ) -> None:
        if (
            self._disposed
            or self._study_edit_dialogs.get((slot_id, study_id)) is not dialog
            or self._chart_presenters.get(slot_id) is not presenter
            or presenter.is_disposed
            or outcome.slot_id != slot_id
            or outcome.session_id != presenter.session.session_id
        ):
            return
        if outcome.status == "success" and outcome.study_id is not None:
            if intent.guide_changed:
                try:
                    presenter.apply_guide_values(
                        study_id,
                        intent.guide_values,
                    )
                except Exception as error:
                    dialog.set_operation_failure(str(error))
                    self._append_activity(
                        f"Chart {slot_id} Study guide Edit failed: {error}"
                    )
                    return
            self._append_activity(
                f"Chart {slot_id} Study Edit completed: {outcome.study_id}."
            )
            self._refresh_studies_manager(slot_id, presenter)
            self._refresh_study_style_dialogs(slot_id, presenter)
            study = presenter.session.study_registry.get(study_id)
            presentation = self._presentation(presenter, study_id)
            if presentation is not None:
                dialog.accept_applied_state(
                    study.edit_request,
                    presentation,
                )
        else:
            self._append_activity(
                f"Chart {slot_id} Study Edit {outcome.status}: {outcome.message}"
            )
            dialog.set_busy(False)
        self._sync_financial_tools_state(slot_id, presenter)

    def _study_edit_target(
        self,
        slot_id: int,
        study_id: str,
        dialog: ResearchStudyEditDialog,
    ) -> ResearchChartPresenter | None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._disposed
            or self._study_edit_dialogs.get((slot_id, study_id)) is not dialog
            or not self._study_target_is_ready(
                slot_id,
                presenter,
                require_idle=True,
            )
            or not self._study_exists(presenter, study_id)
        ):
            return None
        return presenter

    def _on_study_edit_finished(
        self,
        slot_id: int,
        study_id: str,
        dialog: ResearchStudyEditDialog,
    ) -> None:
        key = (slot_id, study_id)
        if self._study_edit_dialogs.get(key) is dialog:
            self._study_edit_dialogs.pop(key, None)
            dialog.deleteLater()

    def _retire_study_edit(self, slot_id: int, study_id: str) -> None:
        dialog = self._study_edit_dialogs.pop((slot_id, study_id), None)
        if dialog is not None:
            self._close_and_delete_dialog(dialog)

    def _submit_saved_artifact_apply(
        self,
        slot_id: int,
        dialog: ResearchFinancialToolsDialog,
        request: object,
    ) -> None:
        presenter = self._financial_tools_target(slot_id, dialog)
        if presenter is None:
            self._append_activity(
                f"Chart {slot_id} Financial Tools dialog target stale."
            )
            return
        if not isinstance(request, StudyArtifactRequest):
            self._append_activity(
                f"Chart {slot_id} saved Artifact Apply submission failed: "
                "invalid request"
            )
            return
        dialog.set_busy(True, "Applying saved Artifact...")
        try:
            presenter.submit_artifact_apply(request)
        except Exception as error:
            dialog.set_busy(False)
            self._sync_financial_tools_state(slot_id, presenter)
            self._append_activity(
                f"Chart {slot_id} saved Artifact Apply submission failed: {error}"
            )

    def _financial_tools_target(
        self, slot_id: int, dialog: ResearchFinancialToolsDialog
    ) -> ResearchChartPresenter | None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._disposed
            or self._financial_tools_dialogs.get(slot_id) is not dialog
            or presenter is None
            or presenter.is_disposed
            or presenter.session.dataset is None
            or presenter.viewport is None
        ):
            return None
        return presenter

    def _sync_financial_tools_state(
        self, slot_id: int, presenter: ResearchChartPresenter
    ) -> None:
        if slot_id not in self._view.workspace.slot_ids():
            return
        panel = self._view.workspace.chart_panel_for_slot(slot_id)
        setup_busy = slot_id in self._active_study_setup_catalog_tasks
        chart_ready = (
            self._chart_presenters.get(slot_id) is presenter
            and not presenter.is_disposed
            and presenter.session.dataset is not None
            and presenter.viewport is not None
        )
        idle = (
            chart_ready
            and not presenter.is_busy
            and not setup_busy
        )
        available = (
            self._study_setup_service is not None
            and idle
        )
        panel.set_financial_tools_available(available)
        panel.set_studies_available(idle)
        panel.set_study_overlay_action_availability(
            style=idle, edit=idle, remove=idle, move=False
        )
        manager = self._studies_manager_dialogs.get(slot_id)
        if manager is not None:
            manager.set_busy(not idle)
        dialog = self._financial_tools_dialogs.get(slot_id)
        if dialog is not None:
            if setup_busy:
                dialog.set_busy(True, "Building Financial Tools catalog...")
            elif presenter.is_busy:
                dialog.set_busy(True, presenter.status_text)
            else:
                dialog.set_busy(False)

    def _open_studies_manager(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if not self._study_target_is_ready(slot_id, presenter, require_idle=True):
            self._append_activity(f"Chart {slot_id} Studies target stale.")
            return
        entries = presenter.session.study_manager_entries()
        dialog = self._studies_manager_dialogs.get(slot_id)
        if dialog is None:
            dataset = presenter.session.dataset
            if dataset is None:
                return
            dialog = ResearchStudiesManagerDialog(dataset.market_id, entries, self._view)
            self._studies_manager_dialogs[slot_id] = dialog
            dialog.visibility_requested.connect(
                lambda study_id, visible, current=slot_id, captured=dialog: (
                    self._set_study_visibility(current, captured, study_id, visible)
                )
            )
            dialog.style_requested.connect(
                lambda study_id, current=slot_id: self._open_study_style(
                    current, study_id
                )
            )
            dialog.reset_style_requested.connect(
                lambda study_id, current=slot_id, captured=dialog: (
                    self._reset_study_style(current, captured, study_id)
                )
            )
            dialog.save_requested.connect(
                lambda study_id, current=slot_id, captured=dialog: (
                    self._save_manager_study(current, captured, study_id)
                )
            )
            dialog.remove_requested.connect(
                lambda study_id, current=slot_id, captured=dialog: (
                    self._remove_study(current, study_id, captured)
                )
            )
            dialog.finished.connect(
                lambda _result, current=slot_id, captured=dialog: (
                    self._on_studies_manager_finished(current, captured)
                )
            )
            if self._window_tracker is not None:
                self._window_tracker(
                    dialog,
                    f"research_restoration.studies_manager.{slot_id}",
                    "Studies",
                    "dialog",
                )
        dialog.prepare_for_open(entries)
        dialog.set_busy(False)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _refresh_studies_manager(
        self, slot_id: int, presenter: ResearchChartPresenter
    ) -> None:
        dialog = self._studies_manager_dialogs.get(slot_id)
        if dialog is not None and self._chart_presenters.get(slot_id) is presenter:
            dialog.set_entries(presenter.session.study_manager_entries())

    def _set_study_visibility(
        self,
        slot_id: int,
        dialog: ResearchStudiesManagerDialog,
        study_id: str,
        visible: bool,
    ) -> None:
        presenter = self._manager_target(slot_id, dialog, study_id)
        if presenter is None:
            self._append_activity(f"Chart {slot_id} stale manager target rejected.")
            return
        presenter.set_study_visibility(study_id, visible)
        self._refresh_studies_manager(slot_id, presenter)

    def _save_manager_study(
        self,
        slot_id: int,
        dialog: ResearchStudiesManagerDialog,
        study_id: str,
    ) -> None:
        presenter = self._manager_target(slot_id, dialog, study_id)
        if presenter is None:
            self._append_activity(
                f"Chart {slot_id} stale manager Save target rejected."
            )
            return
        dialog.set_busy(True)
        self._append_activity(f"Chart {slot_id} manager Save started: {study_id}.")
        submission = presenter.save_study(
            study_id,
            completion_callback=lambda outcome, current=slot_id, captured=dialog, owner=presenter: self._on_manager_save_complete(
                current, captured, owner, outcome
            ),
        )
        if submission is None:
            dialog.set_busy(False)

    def _on_manager_save_complete(
        self,
        slot_id: int,
        dialog: ResearchStudiesManagerDialog,
        presenter: ResearchChartPresenter,
        outcome: StudyOperationOutcome,
    ) -> None:
        if (
            self._disposed
            or self._studies_manager_dialogs.get(slot_id) is not dialog
            or self._chart_presenters.get(slot_id) is not presenter
            or presenter.is_disposed
            or outcome.slot_id != slot_id
            or outcome.session_id != presenter.session.session_id
        ):
            return
        self._refresh_studies_manager(slot_id, presenter)
        if outcome.status == "success":
            self._append_activity(
                f"Chart {slot_id} manager Save completed: {outcome.study_id}."
            )
            self._request_study_catalog_refresh(slot_id, presenter)
        else:
            self._append_activity(
                f"Chart {slot_id} manager Save {outcome.status}: {outcome.message}"
            )
        self._sync_financial_tools_state(slot_id, presenter)

    def _manager_target(
        self,
        slot_id: int,
        dialog: ResearchStudiesManagerDialog,
        study_id: str,
    ) -> ResearchChartPresenter | None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._studies_manager_dialogs.get(slot_id) is not dialog
            or not self._study_target_is_ready(slot_id, presenter, require_idle=True)
            or not self._study_exists(presenter, study_id)
        ):
            return None
        return presenter

    def _on_studies_manager_finished(
        self, slot_id: int, dialog: ResearchStudiesManagerDialog
    ) -> None:
        if self._studies_manager_dialogs.get(slot_id) is dialog:
            self._studies_manager_dialogs.pop(slot_id, None)
            dialog.deleteLater()

    def _retire_studies_manager(self, slot_id: int) -> None:
        dialog = self._studies_manager_dialogs.pop(slot_id, None)
        if dialog is not None:
            self._close_and_delete_dialog(dialog)

    def _open_study_style(self, slot_id: int, study_id: str) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if not self._study_target_is_ready(slot_id, presenter, require_idle=True):
            self._append_activity(
                f"Chart {slot_id} stale Study style target rejected."
            )
            return
        presentation = self._presentation(presenter, study_id)
        if presentation is None:
            self._append_activity(
                f"Chart {slot_id} stale Study style target rejected."
            )
            return
        key = (slot_id, study_id)
        dialog = self._study_style_dialogs.get(key)
        if dialog is None:
            dialog = StudyStyleDialog(presentation)
            self._study_style_dialogs[key] = dialog
            dialog.patch_applied.connect(
                lambda patch, current=slot_id, captured=dialog: (
                    self._apply_study_style(current, captured, patch)
                )
            )
            dialog.reset_requested.connect(
                lambda current_study, current=slot_id, captured=dialog: (
                    self._reset_study_style(current, captured, current_study)
                )
            )
            dialog.finished.connect(
                lambda _result, current=slot_id, current_study=study_id, captured=dialog: self._on_study_style_finished(
                    current, current_study, captured
                )
            )
            dialog.setParent(self._view, dialog.windowFlags())
            if self._window_tracker is not None:
                self._window_tracker(
                    dialog,
                    f"research_restoration.study_style.{slot_id}.{study_id}",
                    "Study Style",
                    "dialog",
                )
        else:
            dialog.set_presentation(presentation)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _apply_study_style(
        self, slot_id: int, dialog: StudyStyleDialog, patch: object
    ) -> None:
        if not isinstance(patch, StudyStylePatch):
            return
        presenter = self._style_target(slot_id, dialog, patch.study_id)
        if presenter is None:
            self._append_activity(
                f"Chart {slot_id} stale Study style target rejected."
            )
            return
        presenter.apply_style_patch(patch)
        presentation = self._presentation(presenter, patch.study_id)
        if presentation is not None:
            dialog.set_presentation(presentation)
        self._refresh_studies_manager(slot_id, presenter)

    def _reset_study_style(
        self,
        slot_id: int,
        dialog: ResearchStudiesManagerDialog | StudyStyleDialog,
        study_id: str,
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if isinstance(dialog, StudyStyleDialog):
            presenter = self._style_target(slot_id, dialog, study_id)
        elif self._manager_target(slot_id, dialog, study_id) is None:
            presenter = None
        if presenter is None:
            self._append_activity(
                f"Chart {slot_id} stale Study style target rejected."
            )
            return
        presenter.reset_study_style(study_id)
        self._refresh_studies_manager(slot_id, presenter)

    def _remove_study(
        self,
        slot_id: int,
        study_id: str,
        manager: ResearchStudiesManagerDialog | None = None,
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if manager is not None:
            presenter = self._manager_target(slot_id, manager, study_id)
        elif not self._study_target_is_ready(
            slot_id, presenter, require_idle=True
        ) or not self._study_exists(presenter, study_id):
            presenter = None
        if presenter is None:
            self._append_activity(
                f"Chart {slot_id} stale Study removal target rejected."
            )
            return
        before = tuple(item.study_id for item in presenter.session.studies)
        presenter.remove_study(study_id)
        after = tuple(item.study_id for item in presenter.session.studies)
        self._refresh_studies_manager(slot_id, presenter)
        if study_id in before and study_id not in after:
            self._retire_study_style(slot_id, study_id)
            self._retire_study_edit(slot_id, study_id)

    def _refresh_study_style_dialogs(
        self, slot_id: int, presenter: ResearchChartPresenter
    ) -> None:
        current_ids = {item.study_id for item in presenter.session.studies}
        for current_slot, study_id in tuple(self._study_style_dialogs):
            if current_slot != slot_id:
                continue
            if study_id not in current_ids:
                self._retire_study_style(slot_id, study_id)
                continue
            presentation = self._presentation(presenter, study_id)
            if presentation is not None:
                self._study_style_dialogs[(slot_id, study_id)].set_presentation(
                    presentation
                )

    def _style_target(
        self, slot_id: int, dialog: StudyStyleDialog, study_id: str
    ) -> ResearchChartPresenter | None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._study_style_dialogs.get((slot_id, study_id)) is not dialog
            or not self._study_target_is_ready(slot_id, presenter, require_idle=True)
            or not self._study_exists(presenter, study_id)
        ):
            return None
        return presenter

    def _on_study_style_finished(
        self, slot_id: int, study_id: str, dialog: StudyStyleDialog
    ) -> None:
        key = (slot_id, study_id)
        if self._study_style_dialogs.get(key) is dialog:
            self._study_style_dialogs.pop(key, None)
            dialog.deleteLater()

    def _retire_study_style(self, slot_id: int, study_id: str) -> None:
        dialog = self._study_style_dialogs.pop((slot_id, study_id), None)
        if dialog is not None:
            self._close_and_delete_dialog(dialog)

    def _study_target_is_ready(
        self,
        slot_id: int,
        presenter: ResearchChartPresenter | None,
        *,
        require_idle: bool,
    ) -> bool:
        return bool(
            not self._disposed
            and presenter is not None
            and self._chart_presenters.get(slot_id) is presenter
            and not presenter.is_disposed
            and presenter.session.dataset is not None
            and presenter.viewport is not None
            and (not require_idle or not presenter.is_busy)
            and (
                not require_idle
                or slot_id not in self._active_study_setup_catalog_tasks
            )
        )

    @staticmethod
    def _study_exists(
        presenter: ResearchChartPresenter | None, study_id: str
    ) -> bool:
        return bool(
            presenter is not None
            and any(item.study_id == study_id for item in presenter.session.studies)
        )

    @staticmethod
    def _presentation(presenter: ResearchChartPresenter, study_id: str):
        return next(
            (
                item
                for item in presenter.session.study_presentations()
                if item.study_id == study_id
            ),
            None,
        )

    @staticmethod
    def _show_financial_tools_dialog(
        dialog: ResearchFinancialToolsDialog,
    ) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_study_setup_catalog(self, slot_id: int) -> None:
        task_id = self._active_study_setup_catalog_tasks.pop(slot_id, None)
        self._study_setup_catalog_attempts.pop(slot_id, None)
        self._study_edit_open_targets.pop(slot_id, None)
        self._financial_tools_open_requested.discard(slot_id)
        if task_id is not None and self._study_setup_service is not None:
            self._study_setup_service.cancel(task_id)

    def _retire_financial_tools_dialog(self, slot_id: int) -> None:
        dialog = self._financial_tools_dialogs.pop(slot_id, None)
        if dialog is None:
            return
        self._close_and_delete_dialog(dialog)

    def _track_detached_window(self, slot_id: int, window: object) -> None:
        if self._disposed or self._window_tracker is None:
            return
        self._window_tracker(
            window,
            window.window_registry_id,
            f"Research Detached Chart {slot_id}",
            "window",
        )

    def _open_go_to(self, slot_id: int) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._disposed
            or presenter is None
            or presenter.is_disposed
            or presenter.is_busy
            or presenter.session.dataset is None
            or presenter.viewport is None
        ):
            return
        dialog = self._go_to_dialogs.get(slot_id)
        if dialog is None:
            market = presenter.session.selected_market_id
            if market is None:
                return
            dialog = ResearchGoToDialog(
                slot_id,
                presenter.session.session_id,
                market.as_key(),
                market.timeframe,
                self._view,
            )
            dialog.accepted.connect(
                lambda current=slot_id, captured=dialog: self._accept_go_to(
                    current, captured
                )
            )
            self._go_to_dialogs[slot_id] = dialog
            if self._window_tracker is not None:
                self._window_tracker(
                    dialog,
                    f"research_restoration.go_to.{slot_id}",
                    "Go to Date (UTC)",
                    "dialog",
                )
        dialog.prepare_for_open()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _accept_go_to(
        self, slot_id: int, dialog: ResearchGoToDialog
    ) -> None:
        presenter = self._chart_presenters.get(slot_id)
        if (
            self._disposed
            or self._go_to_dialogs.get(slot_id) is not dialog
            or presenter is None
            or presenter.is_disposed
            or presenter.session.session_id != dialog.session_id
            or dialog.timestamp_ms is None
        ):
            return
        presenter.go_to_timestamp_ms(dialog.timestamp_ms)

    def _retire_go_to_dialog(self, slot_id: int) -> None:
        dialog = self._go_to_dialogs.pop(slot_id, None)
        if dialog is None:
            return
        self._close_and_delete_dialog(dialog)

    def _set_pan_anchor_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._pan_anchor_enabled = enabled

    @staticmethod
    def _close_and_delete_dialog(dialog: QDialog) -> None:
        dialog.close()
        QApplication.sendEvent(dialog, QCloseEvent())
        dialog.deleteLater()

    def _on_horizontal_pan(self, source_slot_id: int) -> None:
        if (
            self._disposed
            or not self._pan_anchor_enabled
            or self._pan_anchor_in_progress
        ):
            return
        source = self._chart_presenters.get(source_slot_id)
        if (
            source is None
            or source.is_disposed
            or source.session.dataset is None
            or source.viewport is None
        ):
            return
        timestamp_ms = source.current_center_timestamp_ms()
        if timestamp_ms is None:
            return
        self._pan_anchor_in_progress = True
        try:
            for slot_id, presenter in tuple(self._chart_presenters.items()):
                if (
                    slot_id == source_slot_id
                    or presenter.is_disposed
                    or presenter.is_busy
                    or presenter.session.dataset is None
                    or presenter.viewport is None
                ):
                    continue
                presenter.center_on_timestamp_ms(timestamp_ms)
        finally:
            self._pan_anchor_in_progress = False

    def _submit_setup_task(self, submit, settled) -> None:
        task_ref: list[str] = []

        def callback(result: TaskResult) -> None:
            task_id = task_ref[0] if task_ref else result.task_id
            self._setup_task_ids.discard(task_id)
            self._refresh_command_actions()
            if not self._disposed:
                settled(result)

        submission = submit(callback)
        task_ref.append(submission.task_id)
        self._setup_task_ids.add(submission.task_id)
        self._refresh_command_actions()

    def _submit_snapshot_task(self, submit, settled) -> None:
        task_ref: list[str] = []

        def callback(result: TaskResult) -> None:
            task_id = task_ref[0] if task_ref else result.task_id
            self._snapshot_task_ids.discard(task_id)
            self._refresh_command_actions()
            if not self._disposed:
                settled(result)

        submission = submit(callback)
        task_ref.append(submission.task_id)
        self._snapshot_task_ids.add(submission.task_id)
        self._refresh_command_actions()

    def _submit_notebook_task(self, submit, settled) -> None:
        if self._notebook_task_id is not None:
            return
        task_ref: list[str] = []

        def callback(result: TaskResult) -> None:
            task_id = task_ref[0] if task_ref else result.task_id
            if task_id != self._notebook_task_id:
                return
            self._notebook_task_id = None
            self._refresh_command_actions()
            if not self._disposed:
                settled(result)

        submission = submit(callback)
        task_ref.append(submission.task_id)
        self._notebook_task_id = submission.task_id
        self._refresh_command_actions()

    def _track_window(
        self, window: object, window_id: str, title: str
    ) -> None:
        if self._window_tracker is not None:
            self._window_tracker(window, window_id, title, "dialog")

    @staticmethod
    def _show_dialog(dialog: QDialog) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _append_activity(self, message: str) -> None:
        if not self._disposed:
            self._view.append_activity(message)

    def _dispatch(self, callback: Callable[[], None]) -> None:
        self._callback_requested.emit(callback)

    @staticmethod
    def _invoke_callback(callback: object) -> None:
        if callable(callback):
            callback()
