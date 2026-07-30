from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tests.gui_test.test_research_multi_chart_presenter import _composed, _open_chart
from tests.gui_test.test_research_multi_chart_concurrency import (
    _controlled_suite,
    _open_pending,
)


def test_move_detach_dock_preserves_complete_chart_runtime_identity(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        slots = [_open_chart(window, lifecycle) for _ in range(4)]
        slot_id = slots[-1]
        chart = lifecycle._chart_presenters[slot_id]
        widget = window.workspace.chart_panel_for_slot(slot_id)
        identities = (
            chart,
            chart.session,
            chart.viewport,
            chart.interaction,
            chart.chart_workspace,
            chart.chart_workspace.study_pane_ids(),
        )
        window.workspace.move_chart(slot_id, 2)
        assert window.workspace.shell_state.placement_for(slot_id).workspace_position == 2
        assert window.workspace.shell_state.placement_for(2).workspace_position == 4
        window.workspace.detach_chart(slot_id)
        floating = window.workspace.detached_window(slot_id)
        assert floating is not None
        assert window.workspace.detached_slot_ids() == (slot_id,)
        assert widget.parent() is not window.workspace.grid_host
        window.workspace.move_chart(3, 4)
        assert window.workspace.shell_state.placement_for(3).workspace_position == 4
        window.workspace.dock_chart(slot_id)
        assert window.workspace.detached_slot_ids() == ()
        chart_after = lifecycle._chart_presenters[slot_id]
        assert (
            chart_after,
            chart_after.session,
            chart_after.viewport,
            chart_after.interaction,
            chart_after.chart_workspace,
            chart_after.chart_workspace.study_pane_ids(),
        ) == identities
        assert window.workspace.chart_panel_for_slot(slot_id) is widget
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()


def test_direct_dispose_closes_floating_shells_and_cancels_once(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, data, _studies = _controlled_suite(tmp_path)
    close_requests: list[tuple[int, str]] = []
    window.floating_close_requested.connect(lambda *args: close_requests.append(args))
    slot_id, load_id = _open_pending(presenter, data)
    session = presenter.session_for(slot_id)
    presenter.detach_slot(slot_id)
    assert window.floating_chart_window(slot_id) is not None
    presenter.dispose()
    assert window.floating_chart_window(slot_id) is None
    assert close_requests == []
    assert session.is_disposed
    assert data.cancel_counts[load_id] == 1
    presenter.dispose()
    assert data.cancel_counts[load_id] == 1
    window.close()
    qapp.processEvents()


def test_floating_window_is_tracked_through_composition(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        slot_id = _open_chart(window, lifecycle)
        window.workspace.detach_chart(slot_id)
        assert lifecycle._workspace_state.session_for(slot_id).session_id
        assert window.workspace.detached_window(slot_id).window_registry_id == (
            f"research_restoration.detached_chart.{slot_id}"
        )
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
