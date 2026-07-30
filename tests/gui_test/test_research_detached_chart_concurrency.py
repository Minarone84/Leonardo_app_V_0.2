from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.research import StudyExecutionRequest
from tests.gui_test.test_research_multi_chart_presenter import _composed, _open_chart
from tests.gui_test.test_research_single_chart_integration import _wait_until


def test_study_operation_completes_in_same_widget_while_detached(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        slot_id = _open_chart(window, lifecycle)
        widget = window.workspace.chart_panel_for_slot(slot_id)
        chart_presenter = lifecycle._chart_presenters[slot_id]
        submission = chart_presenter.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3})
        )
        window.workspace.detach_chart(slot_id)
        _wait_until(
            lambda: lifecycle._workspace_state.session_for(slot_id).study_count == 1
        )
        assert submission.task_id
        assert window.workspace.chart_panel_for_slot(slot_id) is widget
        assert chart_presenter.chart_workspace.study_pane_ids()[0] == "price"
        window.workspace.dock_chart(slot_id)
        assert window.workspace.chart_panel_for_slot(slot_id) is widget
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()


def test_stale_floating_close_cannot_remove_reused_slot(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        slot_id = _open_chart(window, lifecycle)
        window.workspace.detach_chart(slot_id)
        old_window = window.workspace.detached_window(slot_id)
        old_panel = window.workspace.chart_panel_for_slot(slot_id)
        old_panel.close_button.click()
        qapp.processEvents()
        assert slot_id not in lifecycle._chart_presenters
        reused = _open_chart(window, lifecycle)
        assert reused == slot_id
        new_session = lifecycle._workspace_state.session_for(reused)
        old_window.close()
        qapp.processEvents()
        assert lifecycle._workspace_state.session_for(slot_id) is new_session
        assert not new_session.is_disposed
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
