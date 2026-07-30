from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.research import StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import (
    _open_restored_chart,
    _wait_until,
    _write_accepted_dataset,
)


def _composed(tmp_path: Path):
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    main.action_for_id("main_window.open_research_suite").trigger()
    window = composition.research_suite_window
    presenter = composition.research_suite_presenter
    assert window is not None and presenter is not None
    _wait_until(lambda: bool(window.dataset_summaries))
    return app, main, window, presenter


def _open_chart(window, presenter) -> int:
    return _open_restored_chart(window, presenter)


def test_active_aliases_explicit_routing_manager_and_style_capture(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, presenter = _composed(tmp_path)
    try:
        first = _open_chart(window, presenter)
        second = _open_chart(window, presenter)
        state = presenter._workspace_state
        chart_presenters = presenter._chart_presenters
        assert (first, second) == (1, 2)
        assert window.workspace.active_slot_id == 2
        assert state.session_for(1) is not state.session_for(2)
        assert chart_presenters[1].viewport is not chart_presenters[2].viewport

        chart_presenters[1].submit_study_calculation(
            StudyExecutionRequest("sma", {"period": 3})
        )
        chart_presenters[2].submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3})
        )
        _wait_until(lambda: state.session_for(1).study_count == 1)
        _wait_until(lambda: state.session_for(2).study_count == 1)
        assert state.session_for(1).studies[0].result.tool_key == "sma"
        assert state.session_for(2).studies[0].result.tool_key == "rsi"
        assert chart_presenters[1].chart_workspace.study_pane_ids() == ("price",)
        assert chart_presenters[2].chart_workspace.study_pane_ids() == (
            "price",
            f"oscillator:{state.session_for(2).studies[0].study_id}",
        )

        presenter._open_studies_manager(1)
        first_manager = presenter._studies_manager_dialogs[1]
        assert tuple(item.study_id for item in first_manager.entries) == (
            state.session_for(1).studies[0].study_id,
        )
        first_study = state.session_for(1).studies[0]
        dialog = chart_presenters[1].open_study_style(first_study.study_id)
        assert dialog is not None
        color, _, _, _ = dialog._line_controls["sma_3"]
        color.setText("#FFFFFF")
        window.workspace.set_active_slot(2)
        dialog.apply_patch()
        assert state.session_for(1).study_presentations()[0].signal_styles[
            "sma_3"
        ].color == "#FFFFFF"
        assert state.session_for(2).study_presentations()[0].study_id == (
            state.session_for(2).studies[0].study_id
        )
        presenter._open_studies_manager(2)
        second_manager = presenter._studies_manager_dialogs[2]
        assert tuple(item.study_id for item in second_manager.entries) == (
            state.session_for(2).studies[0].study_id,
        )

        slot_2 = window.workspace.chart_panel_for_slot(2)
        chart_presenters[2].set_autoscale_enabled(False)
        chart_presenters[2].set_volume_visible(True)
        window.workspace.set_active_slot(1)
        candle = slot_2.chart_widget
        QTest.mousePress(candle, Qt.LeftButton, pos=candle._plot_rect().center().toPoint())
        assert window.workspace.active_slot_id == 2
        assert candle._plot_dragging is True
        assert slot_2.chart_widget.autoscale_enabled is False
        assert slot_2.chart_workspace.volume_visible is True
        QTest.mouseRelease(candle, Qt.LeftButton)

        window.workspace.set_active_slot(1)
        oscillator = slot_2.chart_workspace.oscillator_widget(
            state.session_for(2).studies[0].study_id
        )
        assert oscillator is not None
        window.workspace.refresh_activation_surfaces(2)
        QTest.mousePress(
            oscillator,
            Qt.LeftButton,
            pos=oscillator._plot_rect().center().toPoint(),
        )
        assert window.workspace.active_slot_id == 2
        assert oscillator._dragging is True
        QTest.mouseRelease(oscillator, Qt.LeftButton)
        chart_presenters[2].set_volume_visible(False)
        qapp.processEvents()
        dialog.close()
        first_manager.close()
        second_manager.close()
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()


def test_close_reuse_active_fallback_and_mode_identity(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, presenter = _composed(tmp_path)
    try:
        for _ in range(3):
            _open_chart(window, presenter)
        state = presenter._workspace_state
        window.workspace.set_active_slot(2)
        first_widget = window.workspace.chart_panel_for_slot(1)
        second_session = state.session_for(2)
        identities = {
            slot_id: window.workspace.chart_panel_for_slot(slot_id)
            for slot_id in state.slot_ids()
        }
        window.workspace.set_visualization_mode("fit_8")
        window.workspace.set_visualization_mode("scroll_4")
        assert all(
            window.workspace.chart_panel_for_slot(slot_id) is widget
            for slot_id, widget in identities.items()
        )

        window.workspace.chart_panel_for_slot(2).close_button.click()
        assert second_session.is_disposed
        assert state.slot_ids() == (1, 3)
        assert window.workspace.active_slot_id == 1
        assert window.workspace.chart_panel_for_slot(1) is first_widget
        old_session_id = second_session.session_id
        reused = _open_chart(window, presenter)
        assert reused == 2
        assert state.session_for(2).session_id != old_session_id
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
