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
    app, main, window, presenter = _composed(tmp_path)
    try:
        source = _open_chart(window, presenter)
        target = _open_chart(window, presenter)
        detached_target = _open_chart(window, presenter)
        presenter.detach_slot(detached_target)
        source_viewport = presenter.viewport_for(source)
        target_viewport = presenter.viewport_for(target)
        detached_viewport = presenter.viewport_for(detached_target)
        assert (
            source_viewport is not None
            and target_viewport is not None
            and detached_viewport is not None
        )
        pan_anchor = window.button_for_id("research_suite.button.pan_anchor")
        assert pan_anchor.isCheckable() and not pan_anchor.isChecked()
        before = target_viewport.snapshot()
        source_viewport.pan_left(7)
        presenter.chart_presenter(source).chart_workspace.viewportChanged.emit(
            source_viewport.snapshot()
        )
        assert target_viewport.snapshot() == before
        pan_anchor.click()
        target_visible = target_viewport.visible_count
        detached_before = detached_viewport.snapshot()
        target_scale = presenter.chart_presenter(target).interaction.price_scale.snapshot()
        source_viewport.pan_left(5)
        presenter.chart_presenter(source).chart_workspace.viewportChanged.emit(
            source_viewport.snapshot()
        )
        assert target_viewport.visible_count == target_visible
        assert presenter.chart_presenter(target).interaction.price_scale.snapshot() == target_scale
        assert detached_viewport.snapshot() != detached_before
        after_pan = target_viewport.snapshot()
        source_viewport.zoom_in_at(source_viewport.center_index, 0.5)
        presenter.chart_presenter(source).chart_workspace.viewportChanged.emit(
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
    app, main, window, presenter = _composed(tmp_path)
    try:
        first = _open_chart(window, presenter)
        second = _open_chart(window, presenter)
        window.button_for_id("research_suite.button.pan_anchor").click()
        second_before = presenter.viewport_for(second).snapshot()
        timestamp = presenter.session_for(first).dataset.ts_ms[0]
        presenter.chart_presenter(first).go_to_timestamp_ms(timestamp)
        assert presenter.viewport_for(second).snapshot() == second_before
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
