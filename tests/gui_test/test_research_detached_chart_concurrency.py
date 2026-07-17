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
    app, main, window, presenter = _composed(tmp_path)
    try:
        slot_id = _open_chart(window, presenter)
        widget = window.workspace_widget.slot_widget(slot_id)
        submission = presenter.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3}), slot_id=slot_id
        )
        presenter.detach_slot(slot_id)
        _wait_until(lambda: presenter.session_for(slot_id).study_count == 1)
        assert submission.task_id
        assert window.workspace_widget.slot_widget(slot_id) is widget
        assert presenter.chart_presenter(slot_id).chart_workspace.study_pane_ids()[0] == "price"
        presenter.dock_slot(slot_id)
        assert window.workspace_widget.slot_widget(slot_id) is widget
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()


def test_stale_floating_close_cannot_remove_reused_slot(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, presenter = _composed(tmp_path)
    try:
        slot_id = _open_chart(window, presenter)
        old_session = presenter.session_for(slot_id).session_id
        presenter.detach_slot(slot_id)
        presenter._on_floating_close(slot_id, old_session)
        reused = _open_chart(window, presenter)
        assert reused == slot_id
        new_session = presenter.session_for(reused).session_id
        presenter._on_floating_close(slot_id, old_session)
        assert presenter.session_for(slot_id).session_id == new_session
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
