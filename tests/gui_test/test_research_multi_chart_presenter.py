from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.research import StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import (
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
    _wait_until(lambda: window.selected_market_id() is not None)
    return app, main, window, presenter


def _open_chart(window, presenter) -> int:
    before = set(presenter.slot_ids())
    window.button_for_id("research_suite.button.open_chart").click()
    _wait_until(lambda: len(presenter.slot_ids()) == len(before) + 1)
    slot_id = next(iter(set(presenter.slot_ids()) - before))
    _wait_until(lambda: presenter.session_for(slot_id).resident is not None)
    return slot_id


def test_active_aliases_explicit_routing_manager_and_style_capture(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, presenter = _composed(tmp_path)
    try:
        first = _open_chart(window, presenter)
        second = _open_chart(window, presenter)
        assert (first, second) == (1, 2)
        assert presenter.active_slot_id == 2
        assert presenter.session is presenter.session_for(2)
        assert presenter.viewport is presenter.viewport_for(2)
        assert presenter.session_for(1) is not presenter.session_for(2)
        assert presenter.viewport_for(1) is not presenter.viewport_for(2)

        presenter.submit_study_calculation(
            StudyExecutionRequest("sma", {"period": 3}), slot_id=1
        )
        presenter.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3}), slot_id=2
        )
        _wait_until(lambda: presenter.session_for(1).study_count == 1)
        _wait_until(lambda: presenter.session_for(2).study_count == 1)
        assert presenter.session_for(1).studies[0].result.tool_key == "sma"
        assert presenter.session_for(2).studies[0].result.tool_key == "rsi"
        assert presenter.chart_presenter(1).chart_workspace.study_pane_ids() == ("price",)
        assert presenter.chart_presenter(2).chart_workspace.study_pane_ids() == (
            "price",
            f"oscillator:{presenter.session_for(2).studies[0].study_id}",
        )

        presenter.set_active_slot(1)
        assert tuple(item.study_id for item in window.study_manager.entries) == (
            presenter.session_for(1).studies[0].study_id,
        )
        first_study = presenter.session_for(1).studies[0]
        dialog = presenter.chart_presenter(1).open_study_style(first_study.study_id)
        assert dialog is not None
        color, _, _, _ = dialog._line_controls["sma_3"]
        color.setText("#FFFFFF")
        presenter.set_active_slot(2)
        dialog.apply_patch()
        assert presenter.session_for(1).study_presentations()[0].signal_styles[
            "sma_3"
        ].color == "#FFFFFF"
        assert presenter.session_for(2).study_presentations()[0].study_id == (
            presenter.session_for(2).studies[0].study_id
        )
        assert tuple(item.study_id for item in window.study_manager.entries) == (
            presenter.session_for(2).studies[0].study_id,
        )

        slot_2 = window.workspace_widget.slot_widget(2)
        activation_requests: list[int] = []
        slot_2.activated.connect(activation_requests.append)
        presenter.chart_presenter(2).set_autoscale_enabled(False)
        presenter.chart_presenter(2).set_volume_visible(True)
        presenter.set_active_slot(1)
        candle = slot_2.chart_widget
        QTest.mousePress(candle, Qt.LeftButton, pos=candle._plot_rect().center().toPoint())
        assert presenter.active_slot_id == 2
        assert activation_requests == [2]
        assert candle._plot_dragging is True
        assert tuple(item.study_id for item in window.study_manager.entries) == (
            presenter.session_for(2).studies[0].study_id,
        )
        assert window.button_for_id(
            "research_suite.button.toggle_autoscale"
        ).text() == "Enable Autoscale"
        assert window.button_for_id(
            "research_suite.button.toggle_volume"
        ).text() == "Hide Volume"
        QTest.mouseRelease(candle, Qt.LeftButton)

        presenter.set_active_slot(1)
        oscillator = slot_2.chart_workspace.oscillator_widget(
            presenter.session_for(2).studies[0].study_id
        )
        assert oscillator is not None
        QTest.mousePress(
            oscillator,
            Qt.LeftButton,
            pos=oscillator._plot_rect().center().toPoint(),
        )
        assert presenter.active_slot_id == 2
        assert activation_requests == [2, 2]
        assert oscillator._dragging is True
        assert tuple(item.study_id for item in window.study_manager.entries) == (
            presenter.session_for(2).studies[0].study_id,
        )
        QTest.mouseRelease(oscillator, Qt.LeftButton)
        presenter.chart_presenter(2).set_volume_visible(False)
        qapp.processEvents()
        dialog.close()
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()


def test_close_reuse_active_fallback_and_mode_identity(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, presenter = _composed(tmp_path)
    try:
        for _ in range(3):
            _open_chart(window, presenter)
        presenter.set_active_slot(2)
        first_widget = window.workspace_widget.slot_widget(1)
        second_session = presenter.session_for(2)
        identities = {
            slot_id: window.workspace_widget.slot_widget(slot_id)
            for slot_id in presenter.slot_ids()
        }
        window.workspace_widget.set_visualization_mode("fit_8")
        window.workspace_widget.set_visualization_mode("scroll_4")
        assert all(
            window.workspace_widget.slot_widget(slot_id) is widget
            for slot_id, widget in identities.items()
        )

        window.button_for_id("research_suite.button.close_active_chart").click()
        assert second_session.is_disposed
        assert presenter.slot_ids() == (1, 3)
        assert presenter.active_slot_id == 1
        assert window.workspace_widget.slot_widget(1) is first_widget
        old_session_id = second_session.session_id
        reused = _open_chart(window, presenter)
        assert reused == 2
        assert presenter.session_for(2).session_id != old_session_id
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
