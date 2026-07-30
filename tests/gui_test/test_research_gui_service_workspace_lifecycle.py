from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
)
from leonardo.research import DatasetCatalogReport
from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotV1
from tests.gui_test.test_research_gui_service_catalog import (
    _complete_catalog,
    _presenter,
    _settle_qt,
)
from tests.gui_test.test_research_gui_service_chart_lifecycle import (
    _open_catalog,
    _open_pending,
)


class _ControlledSnapshotLinkService:
    def __init__(self) -> None:
        self.pending: dict[
            str, tuple[Callable[[TaskResult], None], object | None]
        ] = {}
        self.raise_on_assign = False
        self._sequence = 0

    def _submit(self, callback, value) -> TaskSubmission:
        self._sequence += 1
        task_id = f"snapshot-link-{self._sequence}"
        self.pending[task_id] = (callback, value)
        return TaskSubmission(task_id, "snapshot-link")

    def submit_assign_notebook(
        self, snapshot_id, notebook_id, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        if self.raise_on_assign:
            raise RuntimeError("synchronous assignment failure")
        return self._submit(
            result_callback,
            _workspace_snapshot(snapshot_id, notebook_id),
        )

    def submit_unassign_notebook(
        self, snapshot_id, _notebook_id, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(
            result_callback,
            _workspace_snapshot(snapshot_id, None),
        )

    def submit_list_snapshots(
        self, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(result_callback, ())

    def complete(
        self,
        task_id: str,
        *,
        status: str = "completed",
        error_message: str | None = None,
    ) -> None:
        callback, value = self.pending.pop(task_id)
        callback(
            TaskResult(
                task_id,
                status,
                value=value if status == "completed" else None,
                error_message=error_message,
            )
        )

    def cancel(self, task_id: str) -> bool:
        return task_id in self.pending


class _ControlledNotebookLinkService:
    def __init__(self) -> None:
        self.pending: dict[str, Callable[[TaskResult], None]] = {}
        self._sequence = 0

    def _submit(self, callback) -> TaskSubmission:
        self._sequence += 1
        task_id = f"notebook-link-{self._sequence}"
        self.pending[task_id] = callback
        return TaskSubmission(task_id, "notebook-link")

    def submit_delete_notebook(
        self, _notebook_id, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(result_callback)

    def submit_list_notebooks(
        self, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(result_callback)

    def complete(
        self,
        task_id: str,
        *,
        status: str = "completed",
        error_message: str | None = None,
    ) -> None:
        callback = self.pending.pop(task_id)
        callback(
            TaskResult(
                task_id,
                status,
                error_message=error_message,
            )
        )

    def cancel(self, task_id: str) -> bool:
        return task_id in self.pending


def _workspace_snapshot(
    snapshot_id: str,
    notebook_id: str | None,
) -> ResearchWorkspaceSnapshotV1:
    payload = json.loads(
        Path(
            "tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json"
        ).read_text(encoding="utf-8")
    )["snapshot"]
    legacy = ResearchWorkspaceSnapshotV1.from_dict(payload)
    return ResearchWorkspaceSnapshotV1.build(
        snapshot_id=snapshot_id,
        display_name=legacy.display_name,
        description=legacy.description,
        created_at_utc=legacy.created_at_utc,
        updated_at_utc=legacy.updated_at_utc,
        workspace=legacy.workspace,
        charts=legacy.charts,
        notebook_id=notebook_id,
    )


def _link_services(presenter):
    snapshots = _ControlledSnapshotLinkService()
    notebooks = _ControlledNotebookLinkService()
    presenter._snapshot_service = snapshots
    presenter._notebook_service = notebooks
    return snapshots, notebooks


def _ready_chart(presenter, service) -> int:
    slot_id, load_id = _open_pending(presenter, service)
    service.complete(load_id)
    service.complete(service.pending_ids("resident")[-1])
    _settle_qt()
    return slot_id


def test_real_actions_change_workspace_modes_and_position_preserves_identity() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        first = _ready_chart(presenter, service)
        second = _ready_chart(presenter, service)
        first_panel = window.workspace.chart_panel_for_slot(first)
        runtime = presenter._chart_presenters[first]
        identities = (first_panel, runtime, runtime.session, runtime.viewport)

        window.action_for_text("Fit 8").trigger()
        assert window.workspace.visualization_mode == "fit_8"
        window.action_for_text("Scroll 4").trigger()
        assert window.workspace.visualization_mode == "scroll_4"

        first_panel.position_combo.setCurrentText("2")
        assert window.workspace.shell_state.placement_for(first).workspace_position == 2
        assert window.workspace.shell_state.placement_for(second).workspace_position == 1
        assert (
            window.workspace.chart_panel_for_slot(first),
            presenter._chart_presenters[first],
            runtime.session,
            runtime.viewport,
        ) == identities
    finally:
        presenter.dispose()
        window.close()


def test_detach_dock_preserves_complete_runtime_and_window_x_docks() -> None:
    _qapp = QApplication.instance() or QApplication([])
    tracked: list[tuple[object, str, str, str, bool]] = []

    def tracker(widget, window_id, title, window_type) -> None:
        tracked.append((widget, window_id, title, window_type, widget.isVisible()))

    from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
    from tests.gui_test.test_research_gui_service_catalog import (
        _ControlledDatasetService,
        _ControlledStudyService,
        _dataset_bundle,
    )

    dataset, summary = _dataset_bundle()
    service = _ControlledDatasetService(dataset)
    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window, service, _ControlledStudyService(), tracker
    )
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id = _ready_chart(presenter, service)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        chart = presenter._chart_presenters[slot_id]
        identities = (panel, chart, chart.session, chart.viewport, chart.interaction)
        panel.detach_button.click()
        floating = window.workspace.detached_window(slot_id)
        assert floating is not None
        assert tracked[-1] == (
            floating,
            "research_restoration.detached_chart.1",
            "Research Detached Chart 1",
            "window",
            False,
        )
        assert (panel, chart, chart.session, chart.viewport, chart.interaction) == identities
        floating.close()
        assert window.workspace.detached_window(slot_id) is None
        assert (panel, chart, chart.session, chart.viewport, chart.interaction) == identities
    finally:
        presenter.dispose()
        window.close()


def test_detached_panel_close_is_permanent_once_and_slot_reuse_is_fresh() -> None:
    _qapp = QApplication.instance() or QApplication([])
    tracked_ids: list[str] = []

    def tracker(_widget, window_id, _title, _window_type) -> None:
        tracked_ids.append(window_id)

    from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
    from tests.gui_test.test_research_gui_service_catalog import (
        _ControlledDatasetService,
        _ControlledStudyService,
        _dataset_bundle,
    )

    dataset, summary = _dataset_bundle()
    service = _ControlledDatasetService(dataset)
    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window, service, _ControlledStudyService(), tracker
    )
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id = _ready_chart(presenter, service)
        old_panel = window.workspace.chart_panel_for_slot(slot_id)
        old_session = presenter._workspace_state.session_for(slot_id)
        old_panel.detach_button.click()
        old_panel.close_button.click()
        assert window.workspace.slot_ids() == ()
        assert presenter._chart_presenters == {}
        assert old_session.is_disposed

        reused = _ready_chart(presenter, service)
        new_panel = window.workspace.chart_panel_for_slot(reused)
        new_session = presenter._workspace_state.session_for(reused)
        assert reused == slot_id
        assert new_panel is not old_panel
        assert new_session is not old_session
        assert new_session.session_id != old_session.session_id
        new_panel.detach_button.click()
        assert tracked_ids.count("research_restoration.detached_chart.1") == 2
    finally:
        presenter.dispose()
        window.close()


def test_autoscale_is_chart_local_and_survives_detach_and_dock() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        first = _ready_chart(presenter, service)
        second = _ready_chart(presenter, service)
        first_panel = window.workspace.chart_panel_for_slot(first)
        second_chart = presenter._chart_presenters[second]
        second_scale = second_chart.interaction.price_scale.snapshot()
        identities = (
            first_panel,
            presenter._chart_presenters[first],
            presenter._chart_presenters[first].session,
        )

        first_panel.autoscale_button.setChecked(False)
        assert not presenter._chart_presenters[first].interaction.price_scale.autoscale_enabled
        assert second_chart.interaction.price_scale.snapshot() == second_scale
        first_panel.detach_button.click()
        first_panel.autoscale_button.setChecked(True)
        assert presenter._chart_presenters[first].interaction.price_scale.autoscale_enabled
        first_panel.detach_button.click()
        assert (
            first_panel,
            presenter._chart_presenters[first],
            presenter._chart_presenters[first].session,
        ) == identities
        assert second_chart.interaction.price_scale.snapshot() == second_scale
    finally:
        presenter.dispose()
        window.close()


def test_task_1033_keeps_financial_tools_and_studies_disabled() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        slot_id, _load_id = _open_pending(presenter, service)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        assert panel.position_combo.isEnabled()
        assert panel.detach_button.isEnabled()
        assert panel.close_button.isEnabled()
        assert not panel.go_to_button.isEnabled()
        assert not panel.autoscale_button.isEnabled()
        assert not panel.financial_tools_button.isEnabled()
        assert not panel.studies_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_link_assignment_and_unassignment_settle_after_manager_closes() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, _notebooks = _link_services(presenter)
    snapshot_id = "snapshot_current"
    notebook_id = "notebook_current"
    presenter._current_workspace_snapshot_id = snapshot_id
    try:
        manager = object()
        presenter._notebook_manager = manager
        presenter._assign_notebook(manager, snapshot_id, notebook_id)
        assignment_task = next(iter(snapshots.pending))
        assert presenter._notebook_link_operation_token is not None
        presenter._notebook_manager = None
        snapshots.complete(assignment_task)
        assert presenter._notebook_link_operation_token is None
        assert presenter._assigned_notebook_id == notebook_id
        assert window.action_for_text("Open Notebook").isEnabled()

        manager = object()
        presenter._notebook_manager = manager
        presenter._unassign_notebook(manager, snapshot_id, notebook_id)
        unassignment_task = next(iter(snapshots.pending))
        presenter._notebook_manager = None
        snapshots.complete(unassignment_task)
        assert presenter._notebook_link_operation_token is None
        assert presenter._assigned_notebook_id is None
        assert not window.action_for_text("Open Notebook").isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_link_assignment_settles_with_manager_open() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, _notebooks = _link_services(presenter)
    snapshot_id = "snapshot_current"
    notebook_id = "notebook_current"
    presenter._current_workspace_snapshot_id = snapshot_id
    manager = ResearchNotebookManagerDialog(parent=window)
    presenter._notebook_manager = manager
    try:
        presenter._assign_notebook(manager, snapshot_id, notebook_id)
        snapshots.complete(next(iter(snapshots.pending)))
        assert presenter._notebook_link_operation_token is None
        assert presenter._assigned_notebook_id == notebook_id
        assert window.action_for_text("Open Notebook").isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_link_deletion_settles_after_manager_closes() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    _snapshots, notebooks = _link_services(presenter)
    snapshot_id = "snapshot_current"
    notebook_id = "notebook_current"
    presenter._current_workspace_snapshot_id = snapshot_id
    presenter._assigned_notebook_id = notebook_id
    presenter._sync_notebook_assignment()
    manager = ResearchNotebookManagerDialog(parent=window)
    presenter._notebook_manager = manager
    try:
        presenter._delete_notebook(manager, notebook_id)
        deletion_task = next(iter(notebooks.pending))
        presenter._notebook_manager = None
        notebooks.complete(deletion_task)
        assert presenter._notebook_link_operation_token is None
        assert presenter._current_workspace_snapshot_id == snapshot_id
        assert presenter._assigned_notebook_id is None
        assert not window.action_for_text("Open Notebook").isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_link_results_cannot_overwrite_newer_presenter_state() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, _notebooks = _link_services(presenter)
    manager = ResearchNotebookManagerDialog(parent=window)
    presenter._notebook_manager = manager
    presenter._current_workspace_snapshot_id = "snapshot_old"
    try:
        presenter._assign_notebook(
            manager,
            "snapshot_old",
            "notebook_old",
        )
        old_task = next(iter(snapshots.pending))
        presenter._current_workspace_snapshot_id = "snapshot_new"
        presenter._assigned_notebook_id = "notebook_new"
        snapshots.complete(old_task)
        assert presenter._assigned_notebook_id == "notebook_new"

        presenter._notebook_manager = manager
        presenter._assign_notebook(
            manager,
            "snapshot_new",
            "notebook_stale",
        )
        stale_task = next(iter(snapshots.pending))
        stale_token = presenter._notebook_link_operation_token
        presenter._notebook_link_operation_token = "newer-operation-token"
        presenter._assigned_notebook_id = "notebook_newer"
        snapshots.complete(stale_task)
        assert stale_token != presenter._notebook_link_operation_token
        assert presenter._notebook_link_operation_token == "newer-operation-token"
        assert presenter._assigned_notebook_id == "notebook_newer"
        presenter.dispose()
        assert presenter._notebook_link_operation_token is None
    finally:
        presenter.dispose()
        window.close()


def test_link_operation_rejects_concurrency_and_clears_all_settlements() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, notebooks = _link_services(presenter)
    manager = ResearchNotebookManagerDialog(parent=window)
    presenter._notebook_manager = manager
    presenter._current_workspace_snapshot_id = "snapshot_current"
    try:
        presenter._assign_notebook(
            manager,
            "snapshot_current",
            "notebook_current",
        )
        assignment_task = next(iter(snapshots.pending))
        active_token = presenter._notebook_link_operation_token
        presenter._unassign_notebook(
            manager,
            "snapshot_current",
            "notebook_current",
        )
        presenter._delete_notebook(manager, "notebook_current")
        assert presenter._notebook_link_operation_token == active_token
        assert tuple(snapshots.pending) == (assignment_task,)
        assert not notebooks.pending
        assert (
            window._activity_log.toPlainText().count(
                "Notebook linkage operation is already in progress."
            )
            == 2
        )

        snapshots.complete(
            assignment_task,
            status="failed",
            error_message="assignment rejected",
        )
        assert presenter._notebook_link_operation_token is None
        assert presenter._assigned_notebook_id is None

        snapshots.raise_on_assign = True
        presenter._assign_notebook(
            manager,
            "snapshot_current",
            "notebook_current",
        )
        assert presenter._notebook_link_operation_token is None
        assert "synchronous assignment failure" in (
            window._activity_log.toPlainText()
        )
    finally:
        presenter.dispose()
        window.close()
