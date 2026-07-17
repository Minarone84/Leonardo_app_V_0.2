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
    app, main, window, presenter = _composed(tmp_path)
    try:
        slots = [_open_chart(window, presenter) for _ in range(4)]
        slot_id = slots[-1]
        chart = presenter.chart_presenter(slot_id)
        widget = window.workspace_widget.slot_widget(slot_id)
        identities = (
            chart,
            chart.session,
            chart.viewport,
            chart.interaction,
            chart.chart_workspace,
            chart.chart_workspace.study_pane_ids(),
        )
        presenter.move_slot(slot_id, 2)
        assert presenter.shell_state.placement_for(slot_id).workspace_position == 2
        assert presenter.shell_state.placement_for(2).workspace_position == 4
        presenter.detach_slot(slot_id)
        floating = window.floating_chart_window(slot_id)
        assert floating is not None and window.is_chart_detached(slot_id)
        assert widget.parent() is not window.workspace_widget.grid_host
        presenter.move_slot(3, 2)
        assert presenter.shell_state.placement_for(3).workspace_position == 3
        presenter.dock_slot(slot_id)
        assert not window.is_chart_detached(slot_id)
        chart_after = presenter.chart_presenter(slot_id)
        assert (
            chart_after,
            chart_after.session,
            chart_after.viewport,
            chart_after.interaction,
            chart_after.chart_workspace,
            chart_after.chart_workspace.study_pane_ids(),
        ) == identities
        assert window.workspace_widget.slot_widget(slot_id) is widget
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
    app, main, window, presenter = _composed(tmp_path)
    try:
        slot_id = _open_chart(window, presenter)
        presenter.detach_slot(slot_id)
        session_id = presenter.session_for(slot_id).session_id
        assert window.floating_chart_window(slot_id).window_registry_id == (
            f"research_chart.{slot_id}.{session_id}"
        )
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
