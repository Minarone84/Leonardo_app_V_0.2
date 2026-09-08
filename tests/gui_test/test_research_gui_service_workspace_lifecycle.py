from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from leonardo.core.core_runner import TaskProgress, TaskResult, TaskSubmission
from leonardo.gui.windows.workspace_snapshot_preflight_dialog import (
    WorkspaceSnapshotPreflightDialog,
)
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
)
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.research import DatasetCatalogReport
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotCompatibilityReport,
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
)
from tests.gui_test.test_research_gui_service_catalog import (
    _complete_catalog,
    _presenter,
    _settle_qt,
)
from tests.gui_test.test_research_gui_service_chart_lifecycle import (
    _open_catalog,
    _open_pending,
)
from tools.research_gui_dev_fixtures import build_notebook_gui_fixtures


class _ControlledSnapshotLinkService:
    def __init__(self) -> None:
        self.pending: dict[
            str, tuple[Callable[[TaskResult], None], object | None]
        ] = {}
        self.raise_on_assign = False
        self._sequence = 0
        self.list_value: object = ()

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
        return self._submit(result_callback, self.list_value)

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
        self.pending: dict[
            str, tuple[Callable[[TaskResult], None], object | None]
        ] = {}
        self._sequence = 0
        self.list_value: object = ()
        self.load_values: dict[str, object] = {}

    def _submit(self, callback, value=None) -> TaskSubmission:
        self._sequence += 1
        task_id = f"notebook-link-{self._sequence}"
        self.pending[task_id] = (callback, value)
        return TaskSubmission(task_id, "notebook-link")

    def submit_delete_notebook(
        self, _notebook_id, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(result_callback)

    def submit_list_notebooks(
        self, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(result_callback, self.list_value)

    def submit_load_notebook(
        self, notebook_id, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        return self._submit(result_callback, self.load_values[notebook_id])

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


def _snapshot_summary(
    snapshot: ResearchWorkspaceSnapshotV1,
) -> ResearchWorkspaceSnapshotSummary:
    return ResearchWorkspaceSnapshotSummary(
        snapshot.snapshot_id,
        snapshot.display_name,
        snapshot.description,
        len(snapshot.charts),
        snapshot.created_at_utc,
        snapshot.updated_at_utc,
        notebook_id=snapshot.notebook_id,
    )


def test_snapshot_and_notebook_helpers_clear_synchronous_terminal_results() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshot_results: list[TaskResult] = []
    notebook_results: list[TaskResult] = []

    def immediate_submit(task_id: str, callback) -> TaskSubmission:
        callback(TaskResult(task_id, "completed", value=()))
        return TaskSubmission(task_id, "immediate")

    try:
        presenter._submit_snapshot_task(
            lambda callback: immediate_submit("snapshot-immediate", callback),
            snapshot_results.append,
        )
        presenter._submit_notebook_task(
            lambda callback: immediate_submit("notebook-immediate", callback),
            notebook_results.append,
        )

        assert [result.task_id for result in snapshot_results] == [
            "snapshot-immediate"
        ]
        assert [result.task_id for result in notebook_results] == [
            "notebook-immediate"
        ]
        assert presenter._snapshot_task_ids == set()
        assert presenter._notebook_task_id is None
    finally:
        presenter.dispose()
        window.close()


def test_saved_workspace_refreshes_open_notebook_manager_assignments() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, notebooks = _link_services(presenter)
    saved = _workspace_snapshot("snapshot_saved", None)
    snapshots.list_value = (_snapshot_summary(saved),)
    manager = ResearchNotebookManagerDialog(parent=window)
    presenter._notebook_manager = manager
    try:
        presenter._snapshot_saved_result(
            TaskResult("snapshot-save", "completed", value=saved)
        )
        assert notebooks.pending
        notebooks.complete(next(iter(notebooks.pending)))
        assert snapshots.pending
        snapshots.complete(next(iter(snapshots.pending)))

        assert tuple(
            (item.snapshot_id, item.notebook_id)
            for item in manager.assignments
        ) == (("snapshot_saved", None),)
    finally:
        presenter.dispose()
        window.close()


def test_busy_notebook_transition_reports_visible_activity() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    presenter._notebook_task_id = "notebook-active"
    try:
        presenter._request_notebook_transition("new", None)
        assert "Notebook operation is already in progress." in (
            window._activity_log.toPlainText()
        )
    finally:
        presenter._notebook_task_id = None
        presenter.dispose()
        window.close()


def test_snapshot_capture_clamps_only_persisted_center_and_preserves_viewport() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        slot_id = _ready_chart(presenter, service)
        chart = presenter._chart_presenters[slot_id]
        dataset = chart.session.dataset
        viewport = chart.viewport
        assert dataset is not None
        assert viewport is not None

        viewport.center_on_index(25)
        before = viewport.snapshot()
        inside = chart.capture_snapshot_view_state(
            chart_ref="chart_inside",
            workspace_position=1,
            detached=False,
        )
        assert inside.viewport.center_timestamp_ms == dataset.ts_ms[25]
        assert inside.viewport.visible_count == before.visible_count
        assert viewport.snapshot() == before

        viewport.center_on_index(viewport.domain_start)
        before = viewport.snapshot()
        assert viewport.center_index < 0
        left = chart.capture_snapshot_view_state(
            chart_ref="chart_left",
            workspace_position=1,
            detached=False,
        )
        assert left.viewport.center_timestamp_ms == dataset.ts_ms[0]
        assert left.viewport.visible_count == before.visible_count
        assert viewport.snapshot() == before

        viewport.center_on_index(viewport.domain_end_exclusive - 1)
        before = viewport.snapshot()
        assert viewport.center_index >= dataset.row_count
        right = chart.capture_snapshot_view_state(
            chart_ref="chart_right",
            workspace_position=1,
            detached=False,
        )
        assert right.viewport.center_timestamp_ms == dataset.ts_ms[-1]
        assert right.viewport.visible_count == before.visible_count
        assert viewport.snapshot() == before
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize(
    ("chart_count", "detach_last"),
    ((1, False), (2, False), (2, True)),
)
def test_save_workspace_opens_for_ready_attached_and_detached_charts(
    chart_count: int,
    detach_last: bool,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshots, _notebooks = _link_services(presenter)
    try:
        _open_catalog(presenter, service, summary)
        slots = tuple(
            _ready_chart(presenter, service) for _index in range(chart_count)
        )
        if detach_last:
            window.workspace.detach_chart(slots[-1])
            _settle_qt()
        presenter._open_save_snapshot()
        task_id = next(iter(snapshots.pending))
        snapshots.complete(task_id)
        _settle_qt()
        assert presenter._snapshot_save_dialog is not None
        assert presenter._snapshot_save_dialog.isVisible()
    finally:
        presenter.dispose()
        window.close()


def test_save_workspace_blocker_is_recorded_and_shown_without_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, _notebooks = _link_services(presenter)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    try:
        presenter._open_save_snapshot()
        assert snapshots.pending == {}
        assert warnings == [
            (
                "Save Workspace",
                "Workspace Snapshot capture blocked: "
                "workspace capture requires ready charts and no restore",
            )
        ]
        assert warnings[0][1] in window._activity_log.toPlainText()
    finally:
        presenter.dispose()
        window.close()


def _restore_snapshot(summary, *, count: int = 2) -> ResearchWorkspaceSnapshotV1:
    source = _workspace_snapshot("snapshot_restore", None)
    center = 1_700_000_000_000 + 50 * 14_400_000
    charts = tuple(
        replace(
            source.charts[index % len(source.charts)],
            chart_ref=f"chart_{index + 1}",
            market_id=summary.market_id,
            workspace_position=index + 1,
            detached=False,
            study_environment=None,
            pane_sizes=tuple(
                pane
                for pane in source.charts[index % len(source.charts)].pane_sizes
                if not pane.pane_ref.startswith("study:")
            ),
            viewport=replace(
                source.charts[index % len(source.charts)].viewport,
                center_timestamp_ms=center,
            ),
        )
        for index in range(count)
    )
    return replace(
        source,
        charts=charts,
        workspace=replace(
            source.workspace,
            active_chart_ref=charts[0].chart_ref,
            visualization_mode="scroll_4",
            pan_anchor_enabled=False,
        ),
    )


def _restore_dialog(window, presenter, snapshot, mode="append", *, start=True):
    report = ResearchWorkspaceSnapshotCompatibilityReport(
        snapshot.snapshot_id,
        mode,
        True,
        (),
        append_positions=(
            tuple(
                (chart.chart_ref, chart.workspace_position)
                for chart in snapshot.charts
            )
            if mode == "append"
            else ()
        ),
    )
    dialog = WorkspaceSnapshotPreflightDialog(report, window)
    presenter._snapshot_preflight_dialog = dialog
    dialog.load_requested.connect(
        lambda _report: presenter._restore_snapshot_workspace(snapshot, report)
    )
    dialog.finished.connect(
        lambda _code: presenter._forget_snapshot_preflight(dialog)
    )
    dialog.show()
    if start:
        dialog.load_button.click()
    return dialog, report


def _settle_restore_chart(service) -> None:
    service.complete(service.pending_ids("load")[-1])
    service.complete(service.pending_ids("resident")[-1])
    _settle_qt()


def test_workspace_restore_emits_once_and_publishes_chart_creation_stage(
    monkeypatch,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, summary = _presenter()
    snapshot = _restore_snapshot(summary, count=1)
    try:
        dialog, _report = _restore_dialog(
            window, presenter, snapshot, start=False
        )
        original = presenter._create_restored_chart
        creation_statuses = []

        def observed_creation(*args, **kwargs):
            creation_statuses.append(dialog.restore_status.text())
            return original(*args, **kwargs)

        monkeypatch.setattr(
            presenter, "_create_restored_chart", observed_creation
        )
        dialog.load_button.click()
        dialog.load_button.click()
        assert creation_statuses == ["Creating Chart 1 of 1..."]
        presenter._fail_snapshot_restore("test cleanup")
        dialog.close()
    finally:
        presenter.dispose()
        window.close()


def test_workspace_restore_reports_real_progress_and_closes_on_success() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshot = _restore_snapshot(summary)
    try:
        dialog, _report = _restore_dialog(window, presenter, snapshot)
        assert dialog.isVisible()
        assert presenter._snapshot_preflight_dialog is dialog
        assert dialog.restore_active
        assert (dialog.progress.minimum(), dialog.progress.maximum()) == (0, 2)
        assert dialog.progress.value() == 0
        assert dialog.restore_status.text() == (
            "Chart 1 of 2: Loading historical dataset..."
        )
        run = presenter._snapshot_restore
        assert run is not None
        slot_id = run.current_slot_id
        assert slot_id is not None
        chart = presenter._chart_presenters[slot_id]
        load_id = service.pending_ids("load")[-1]
        chart._on_load_progress(TaskProgress(load_id, "Loading", 40, 100))
        assert (
            dialog.current_progress.minimum(),
            dialog.current_progress.maximum(),
            dialog.current_progress.value(),
        ) == (0, 100, 40)

        before = dialog.current_progress.value()
        presenter._snapshot_dataset_progress(
            "old-run",
            snapshot.charts[0].chart_ref,
            slot_id,
            chart.session.session_id,
            dialog,
            TaskProgress(load_id, "stale", 90, 100),
        )
        presenter._snapshot_dataset_progress(
            run.run_id,
            "old-chart",
            slot_id,
            chart.session.session_id,
            dialog,
            TaskProgress(load_id, "stale", 90, 100),
        )
        presenter._snapshot_dataset_progress(
            run.run_id,
            snapshot.charts[0].chart_ref,
            slot_id,
            "old-session",
            dialog,
            TaskProgress(load_id, "stale", 90, 100),
        )
        other_dialog = WorkspaceSnapshotPreflightDialog(_report, window)
        other_dialog.begin_restore(2)
        presenter._snapshot_dataset_progress(
            run.run_id,
            snapshot.charts[0].chart_ref,
            slot_id,
            chart.session.session_id,
            other_dialog,
            TaskProgress(load_id, "stale", 90, 100),
        )
        assert dialog.current_progress.value() == before
        other_dialog.show_failure("test cleanup")
        other_dialog.close()

        _settle_restore_chart(service)
        assert dialog.progress.value() == 1
        assert dialog.restore_status.text() == (
            "Chart 2 of 2: Loading historical dataset..."
        )
        assert (dialog.current_progress.minimum(), dialog.current_progress.maximum()) == (
            0,
            0,
        )
        _settle_restore_chart(service)
        assert dialog.progress.value() == 2
        assert dialog.restore_status.text() == "Workspace restored."
        assert not dialog.isVisible()
        assert presenter._snapshot_preflight_dialog is None
        assert "Workspace Snapshot restored." in window._activity_log.toPlainText()
        assert presenter._workspace_state.chart_count == 2
    finally:
        presenter.dispose()
        window.close()


def test_workspace_restore_environment_stage_is_indeterminate(
    monkeypatch,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshot = _restore_snapshot(summary, count=1)
    source = _workspace_snapshot("source", None)
    environment = next(
        chart.study_environment
        for chart in source.charts
        if chart.study_environment is not None
    )
    snapshot = replace(
        snapshot,
        charts=(replace(snapshot.charts[0], study_environment=environment),),
    )
    try:
        dialog, _report = _restore_dialog(window, presenter, snapshot)
        run = presenter._snapshot_restore
        assert run is not None and run.current_slot_id is not None
        chart = presenter._chart_presenters[run.current_slot_id]
        monkeypatch.setattr(chart, "apply_environment", lambda *_args, **_kwargs: None)
        _settle_restore_chart(service)
        assert dialog.restore_status.text() == (
            "Chart 1 of 1: Applying Study Environment..."
        )
        assert (dialog.current_progress.minimum(), dialog.current_progress.maximum()) == (
            0,
            0,
        )
        presenter._fail_snapshot_restore("test cleanup")
        dialog.close()
    finally:
        presenter.dispose()
        window.close()


def test_workspace_append_failure_stays_visible_after_cleanup() -> None:
    app = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshot = _restore_snapshot(summary, count=1)
    try:
        dialog, _report = _restore_dialog(window, presenter, snapshot)
        service.complete(
            service.pending_ids("load")[-1],
            status="failed",
            error_message="load rejected",
        )
        app.processEvents()
        assert presenter._workspace_state.chart_count == 0
        assert presenter._snapshot_restore is None
        assert dialog.isVisible()
        assert dialog.restore_status.text() == (
            "Workspace restore failed: chart_1 dataset failed: load rejected"
        )
        assert dialog.cancel_button.text() == "Close"
        assert dialog.cancel_button.isEnabled()
        dialog.cancel_button.click()
        app.processEvents()
        assert not dialog.isVisible()
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize("rollback_status", ("success", "failure"))
def test_workspace_replace_failure_reports_rollback_terminal_state(
    monkeypatch,
    rollback_status: str,
) -> None:
    app = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshot = _restore_snapshot(summary, count=1)
    rollback = replace(snapshot, snapshot_id="snapshot_rollback")
    monkeypatch.setattr(presenter, "_capture_rollback_snapshot", lambda: rollback)
    try:
        dialog, _report = _restore_dialog(window, presenter, snapshot, "replace")
        service.complete(
            service.pending_ids("load")[-1],
            status="failed",
            error_message="replacement failed",
        )
        app.processEvents()
        run = presenter._snapshot_restore
        assert run is not None and run.rollback
        assert dialog.restore_active
        assert dialog._state == "rollback"
        assert dialog.progress.value() == 0
        dialog.close()
        app.processEvents()
        assert dialog.isVisible()

        if rollback_status == "success":
            _settle_restore_chart(service)
            assert presenter._workspace_state.chart_count == 1
            assert dialog.restore_status.text() == (
                "Workspace restore failed: chart_1 dataset failed: replacement failed\n"
                "Previous workspace restored."
            )
        else:
            service.complete(
                service.pending_ids("load")[-1],
                status="failed",
                error_message="rollback failed",
            )
            app.processEvents()
            assert presenter._snapshot_restore is None
            assert dialog.restore_status.text() == (
                "Workspace restore failed: chart_1 dataset failed: replacement failed\n"
                "Rollback failed: chart_1 dataset failed: rollback failed"
            )
        assert dialog.isVisible()
        assert dialog.cancel_button.text() == "Close"
        assert dialog.cancel_button.isEnabled()
        dialog.cancel_button.click()
    finally:
        presenter.dispose()
        window.close()


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
        assert window.action_for_text("Open Assigned Notebook").isEnabled()

        manager = object()
        presenter._notebook_manager = manager
        presenter._unassign_notebook(manager, snapshot_id, notebook_id)
        unassignment_task = next(iter(snapshots.pending))
        presenter._notebook_manager = None
        snapshots.complete(unassignment_task)
        assert presenter._notebook_link_operation_token is None
        assert presenter._assigned_notebook_id is None
        assert not window.action_for_text("Open Assigned Notebook").isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_notebook_manager_new_uses_existing_editor_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshots, notebooks = _link_services(presenter)
    surfacing_calls: list[tuple[str, ResearchNotebookWindow]] = []
    for method_name in ("show", "raise_", "activateWindow"):
        original = getattr(ResearchNotebookWindow, method_name)

        def record_call(
            editor,
            *args,
            _method_name=method_name,
            _original=original,
            **kwargs,
        ):
            surfacing_calls.append((_method_name, editor))
            return _original(editor, *args, **kwargs)

        monkeypatch.setattr(ResearchNotebookWindow, method_name, record_call)
    try:
        window.show()
        qapp.processEvents()
        _open_catalog(presenter, service, summary)
        _ready_chart(presenter, service)
        _ready_chart(presenter, service)
        presenter._open_notebook_manager()
        notebooks.complete(next(iter(notebooks.pending)))
        snapshots.complete(next(iter(snapshots.pending)))
        manager = presenter._notebook_manager
        assert manager is not None

        manager._create.click()
        qapp.processEvents()

        editor = presenter._notebook_editor
        assert editor is not None
        assert presenter._notebook_manager is manager
        assert manager.isVisible()
        assert editor.isVisible()
        assert tuple(name for name, _editor in surfacing_calls) == (
            "show",
            "raise_",
            "activateWindow",
        )
        assert all(call_editor is editor for _name, call_editor in surfacing_calls)
        assert editor.current_draft().display_name == "Untitled Notebook"
        assert tuple(page.market_id for page in editor.current_draft().pages) == (
            summary.market_id,
        )
        assert presenter._current_workspace_snapshot_id is None
        assert presenter._assigned_notebook_id is None
        assert manager.assignments == ()
    finally:
        presenter.dispose()
        window.close()


def test_notebook_manager_new_opens_with_no_ready_charts() -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, _service, _summary = _presenter()
    snapshots, notebooks = _link_services(presenter)
    try:
        window.show()
        qapp.processEvents()
        presenter._open_notebook_manager()
        notebooks.complete(next(iter(notebooks.pending)))
        snapshots.complete(next(iter(snapshots.pending)))
        manager = presenter._notebook_manager
        assert manager is not None

        manager._create.click()
        qapp.processEvents()

        editor = presenter._notebook_editor
        assert editor is not None
        assert editor.isVisible()
        assert presenter._notebook_manager is manager
        assert manager.isVisible()
        assert editor.current_draft().pages == ()
        assert presenter._current_workspace_snapshot_id is None
        assert presenter._assigned_notebook_id is None
        assert manager.assignments == ()
    finally:
        presenter.dispose()
        window.close()


def test_notebook_manager_open_uses_existing_async_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    snapshots, notebooks = _link_services(presenter)
    bundle = build_notebook_gui_fixtures(summary.market_id, summary.market_id)
    notebook = bundle.notebooks[0]
    notebooks.list_value = (bundle.summaries[0],)
    notebooks.load_values[notebook.notebook_id] = notebook
    surfacing_calls: list[tuple[str, ResearchNotebookWindow]] = []
    for method_name in ("show", "raise_", "activateWindow"):
        original = getattr(ResearchNotebookWindow, method_name)

        def record_call(
            editor,
            *args,
            _method_name=method_name,
            _original=original,
            **kwargs,
        ):
            surfacing_calls.append((_method_name, editor))
            return _original(editor, *args, **kwargs)

        monkeypatch.setattr(ResearchNotebookWindow, method_name, record_call)
    try:
        window.show()
        qapp.processEvents()
        presenter._open_notebook_manager()
        notebooks.complete(next(iter(notebooks.pending)))
        snapshots.complete(next(iter(snapshots.pending)))
        manager = presenter._notebook_manager
        assert manager is not None

        manager._list.item(0).setCheckState(Qt.CheckState.Checked)
        manager._open.click()
        notebooks.complete(next(iter(notebooks.pending)))
        qapp.processEvents()

        assert presenter._notebook_manager is manager
        editor = presenter._notebook_editor
        assert editor is not None
        assert editor.notebook_id == notebook.notebook_id
        assert manager.isVisible()
        assert editor.isVisible()
        assert tuple(name for name, _editor in surfacing_calls) == (
            "show",
            "raise_",
            "activateWindow",
        )
        assert all(call_editor is editor for _name, call_editor in surfacing_calls)
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
        assert window.action_for_text("Open Assigned Notebook").isEnabled()
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
        assert not window.action_for_text("Open Assigned Notebook").isEnabled()
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
