from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox

import leonardo.gui.presenters.research_presenter as presenter_module
from leonardo.gui.presenters.research_presenter import ResearchSuitePresenter
from leonardo.research import StudyExecutionRequest
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotCompatibilityReport,
    ResearchWorkspaceSnapshotV1,
)
from tests.gui_test.test_research_multi_chart_concurrency import (
    _controlled_suite,
    _open_pending,
)


def test_restore_coordinator_contains_append_and_replace_rollback_paths():
    source = Path("src/leonardo/gui/presenters/research_presenter.py").read_text(encoding="utf-8")
    assert "restore_snapshot_workspace" in source
    assert "rollback_snapshot" in source
    assert "reversed(tuple(run.added_slots))" in source
    assert "processEvents" not in source


def _snapshot() -> ResearchWorkspaceSnapshotV1:
    payload = json.loads(
        Path(
            "tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json"
        ).read_text(encoding="utf-8")
    )["snapshot"]
    return ResearchWorkspaceSnapshotV1.from_dict(payload)


def _append_report(snapshot: ResearchWorkspaceSnapshotV1):
    return ResearchWorkspaceSnapshotCompatibilityReport(
        snapshot.snapshot_id,
        "append",
        True,
        (),
        append_positions=tuple(
            (chart.chart_ref, index)
            for index, chart in enumerate(snapshot.charts, start=3)
        ),
    )


def _start_append_restore(tmp_path):
    window, presenter, data, studies = _controlled_suite(tmp_path)
    _open_pending(presenter, data)
    _open_pending(presenter, data)
    presenter.set_active_slot(2)
    presenter.set_workspace_mode("fit_8")
    presenter.set_pan_anchor_enabled(True)
    window.set_snapshot_workspace_state("fit_8", True)
    snapshot = _snapshot()
    presenter.restore_snapshot_workspace(snapshot, _append_report(snapshot))
    return window, presenter, data, studies, snapshot


def test_append_cancel_restores_exact_active_mode_and_pan_anchor(tmp_path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _data, _studies, _snapshot_value = _start_append_restore(
        tmp_path
    )
    original_session = presenter.session_for(2).session_id
    try:
        assert presenter.active_slot_id == 3
        presenter.cancel_active_operation()
        assert presenter.slot_ids() == (1, 2)
        assert presenter.active_slot_id == 2
        assert presenter.session_for(2).session_id == original_session
        assert window.workspace_widget.visualization_mode == "fit_8"
        assert presenter._pan_anchor_enabled is True
        assert window.button_for_id("research_suite.button.pan_anchor").isChecked()
        assert presenter._snapshot_restore is None
    finally:
        presenter.dispose()
        window.close()


def test_restore_fences_user_mutations_and_releases_them_after_settlement(
    tmp_path, monkeypatch
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _data, _studies, _snapshot_value = _start_append_restore(
        tmp_path
    )
    target = presenter.chart_presenter(3)
    calls = {
        name: Mock()
        for name in (
            "submit_study_calculation",
            "submit_artifact_apply",
            "save_study",
            "set_study_visibility",
            "open_study_style",
            "apply_style_patch",
            "reset_study_style",
            "remove_study",
            "set_autoscale_enabled",
            "set_volume_visible",
        )
    }
    for name, callback in calls.items():
        monkeypatch.setattr(target, name, callback)
    existing_session = presenter.session_for(1).session_id
    mode = window.findChild(QComboBox, "research_suite.combo.workspace_mode")
    try:
        assert window.button_for_id("research_suite.button.cancel").isEnabled()
        for control_id in (
            "research_suite.button.open_chart",
            "research_suite.button.close_active_chart",
            "research_suite.button.toggle_autoscale",
            "research_suite.button.toggle_volume",
            "research_suite.button.pan_anchor",
            "research_suite.button.add_study",
            "research_suite.button.save_environment",
            "research_suite.button.study_environments",
        ):
            assert not window.button_for_id(control_id).isEnabled()
        assert mode is not None and not mode.isEnabled()
        assert not window.study_manager.isEnabled()
        assert all(
            not window.workspace_widget.slot_widget(slot_id).isEnabled()
            for slot_id in presenter.slot_ids()
        )

        presenter.set_active_slot(1)
        presenter.set_workspace_mode("scroll_4")
        presenter.set_pan_anchor_enabled(False)
        mode.setCurrentIndex(mode.findData("scroll_4"))
        presenter.toggle_active_autoscale()
        presenter.toggle_active_volume()
        presenter.submit_study_calculation(object())
        presenter.submit_artifact_apply(object())
        presenter._accept_setup_request(3, target.session.session_id, object())
        presenter._save_study("study")
        presenter._set_study_visibility("study", False)
        presenter._open_study_style("study")
        presenter._apply_style_patch(object())
        presenter._reset_study_style("study")
        presenter._remove_study("study")
        presenter._apply_manager_environment(None, None)
        presenter._on_floating_close(1, existing_session)

        assert presenter.active_slot_id == 3
        assert window.workspace_widget.visualization_mode == "fit_8"
        assert presenter._pan_anchor_enabled is True
        assert 1 in presenter.slot_ids()
        assert all(not callback.called for callback in calls.values())

        presenter.cancel_active_operation()
        presenter.set_active_slot(1)
        presenter.set_workspace_mode("scroll_4")
        presenter.set_pan_anchor_enabled(False)
        assert presenter.active_slot_id == 1
        assert window.workspace_widget.visualization_mode == "scroll_4"
        assert presenter._pan_anchor_enabled is False
        assert mode.isEnabled()
        assert window.study_manager.isEnabled()
        assert all(
            window.workspace_widget.slot_widget(slot_id).isEnabled()
            for slot_id in presenter.slot_ids()
        )
        active = presenter.chart_presenter(1)
        post_calls = {
            name: Mock()
            for name in (
                "submit_study_calculation",
                "save_study",
                "set_study_visibility",
                "open_study_style",
                "apply_style_patch",
                "reset_study_style",
                "remove_study",
                "set_autoscale_enabled",
                "set_volume_visible",
                "apply_environment",
            )
        }
        for name, callback in post_calls.items():
            monkeypatch.setattr(active, name, callback)
        request = StudyExecutionRequest("sma", {"period": 3})
        presenter.submit_study_calculation(request)
        presenter._accept_setup_request(1, active.session.session_id, request)
        presenter._save_study("study")
        presenter._set_study_visibility("study", False)
        presenter._open_study_style("study")
        presenter._apply_style_patch(object())
        presenter._reset_study_style("study")
        presenter._remove_study("study")
        presenter.toggle_active_autoscale()
        presenter.toggle_active_volume()
        environment = SimpleNamespace(environment_id="environment")
        presenter._apply_manager_environment(
            SimpleNamespace(environment=environment),
            SimpleNamespace(
                slot_id=1,
                session_id=active.session.session_id,
                environment_id="environment",
                mode="append",
            ),
        )
        assert all(callback.called for callback in post_calls.values())
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize(
    "failure_phase", ("shell_move", "view_add", "construction", "publication")
)
def test_restore_chart_creation_is_transactional(
    tmp_path, monkeypatch, failure_phase
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _data, _studies = _controlled_suite(tmp_path)
    if failure_phase == "shell_move":
        monkeypatch.setattr(
            presenter._shell_state,
            "move_slot",
            Mock(side_effect=RuntimeError("shell move failed")),
        )
    elif failure_phase == "view_add":
        original = window.add_chart_slot

        def fail_after_add(slot_id):
            original(slot_id)
            raise RuntimeError("view add failed")

        monkeypatch.setattr(window, "add_chart_slot", fail_after_add)
    elif failure_phase == "construction":
        monkeypatch.setattr(
            presenter_module,
            "ResearchChartPresenter",
            Mock(side_effect=RuntimeError("construction failed")),
        )
    else:
        monkeypatch.setattr(
            presenter,
            "_sync_shell_view",
            Mock(side_effect=RuntimeError("publication failed")),
        )
    try:
        with pytest.raises(RuntimeError):
            presenter._create_restore_chart(2)
        assert presenter.slot_ids() == ()
        assert presenter.shell_state.placements() == ()
        assert window.workspace_widget.slot_ids() == ()
        assert presenter._chart_presenters == {}
        assert presenter.active_slot_id is None
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize("phase", ("dataset_missing", "environment_reused"))
def test_current_run_target_mismatch_fails_and_old_callbacks_are_ignored(
    tmp_path, phase
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _data, _studies, snapshot = _start_append_restore(tmp_path)
    run = presenter._snapshot_restore
    assert run is not None
    chart_ref = snapshot.charts[0].chart_ref
    current_slot = run.current_slot_id
    current_session = presenter.session_for(current_slot).session_id
    try:
        presenter._snapshot_dataset_complete(
            "old-run", chart_ref, SimpleNamespace(status="success", session_id=current_session)
        )
        assert presenter._snapshot_restore is run
        if phase == "dataset_missing":
            presenter._discard_partial_restore_chart(current_slot)
            presenter._snapshot_dataset_complete(
                run.run_id,
                chart_ref,
                SimpleNamespace(status="success", session_id=current_session),
            )
        else:
            presenter._snapshot_environment_complete(
                run.run_id,
                chart_ref,
                SimpleNamespace(status="success", session_id="reused-session"),
            )
        assert presenter._snapshot_restore is None
        assert presenter.slot_ids() == (1, 2)
        assert presenter.active_slot_id == 2
        assert "restore failed" in window.status_text().lower()
        presenter._snapshot_dataset_complete(
            run.run_id,
            chart_ref,
            SimpleNamespace(status="success", session_id=current_session),
        )
        assert presenter._snapshot_restore is None
    finally:
        presenter.dispose()
        window.close()
