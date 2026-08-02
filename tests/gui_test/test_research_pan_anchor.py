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


def test_pan_anchor_is_off_by_default_and_horizontal_pan_preserves_target_zoom(
    tmp_path: Path,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        source = _open_chart(window, lifecycle)
        target = _open_chart(window, lifecycle)
        detached_target = _open_chart(window, lifecycle)
        window.workspace.detach_chart(detached_target)
        source_presenter = lifecycle._chart_presenters[source]
        target_presenter = lifecycle._chart_presenters[target]
        detached_presenter = lifecycle._chart_presenters[detached_target]
        source_viewport = source_presenter.viewport
        target_viewport = target_presenter.viewport
        detached_viewport = detached_presenter.viewport
        assert (
            source_viewport is not None
            and target_viewport is not None
            and detached_viewport is not None
        )
        pan_anchor = window.action_for_text("Pan Anchor")
        assert pan_anchor.isCheckable() and not pan_anchor.isChecked()
        quick = window.quick_button_for_action("Pan Anchor")
        assert "#FCA5A5" in quick.styleSheet()
        assert quick.accessibleName() == "Pan Anchor off"
        assert quick.toolTip() == (
            "Pan Anchor is off. Charts may be panned independently."
        )
        before = target_viewport.snapshot()
        source_viewport.pan_left(7)
        source_presenter.chart_workspace.viewportChanged.emit(
            source_viewport.snapshot()
        )
        assert target_viewport.snapshot() == before
        pan_anchor.trigger()
        assert "#86EFAC" in quick.styleSheet()
        assert quick.accessibleName() == "Pan Anchor on"
        assert quick.toolTip() == (
            "Pan Anchor is on. Horizontal user panning keeps ready charts "
            "aligned by UTC timestamp."
        )
        target_visible = target_viewport.visible_count
        detached_before = detached_viewport.snapshot()
        target_scale = target_presenter.interaction.price_scale.snapshot()
        source_viewport.pan_left(5)
        source_presenter.chart_workspace.viewportChanged.emit(
            source_viewport.snapshot()
        )
        assert target_viewport.visible_count == target_visible
        assert target_presenter.interaction.price_scale.snapshot() == target_scale
        assert detached_viewport.snapshot() != detached_before
        after_pan = target_viewport.snapshot()
        source_viewport.zoom_in_at(source_viewport.center_index, 0.5)
        source_presenter.chart_workspace.viewportChanged.emit(
            source_viewport.snapshot()
        )
        assert target_viewport.snapshot() == after_pan
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()


def test_pan_anchor_silently_skips_loading_target(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, data, _studies = _controlled_suite(tmp_path)
    try:
        source, source_load = _open_pending(presenter, data)
        data.complete(source_load)
        source_resident = data.pending_ids("resident")[-1]
        data.complete(source_resident)
        target, target_load = _open_pending(presenter, data)
        target_presenter = presenter.chart_presenter(target)
        status_before = target_presenter.status_text
        viewport_before = target_presenter.viewport
        active_task_before = target_presenter._active_load_task_id
        pending_before = data.pending_ids("load")
        presenter.set_pan_anchor_enabled(True)
        presenter._on_horizontal_pan(source)
        assert target_presenter.status_text == status_before == "Loading historical dataset"
        assert target_presenter.viewport is viewport_before is None
        assert target_presenter._active_load_task_id == active_task_before == target_load
        assert data.pending_ids("load") == pending_before
    finally:
        presenter.dispose()
        window.close()
        qapp.processEvents()


def test_programmatic_go_to_does_not_reenter_pan_anchor(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        first = _open_chart(window, lifecycle)
        second = _open_chart(window, lifecycle)
        window.action_for_text("Pan Anchor").trigger()
        first_presenter = lifecycle._chart_presenters[first]
        second_viewport = lifecycle._chart_presenters[second].viewport
        second_before = second_viewport.snapshot()
        timestamp = lifecycle._workspace_state.session_for(first).dataset.ts_ms[0]
        first_presenter.go_to_timestamp_ms(timestamp)
        assert second_viewport.snapshot() == second_before
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
