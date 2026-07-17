from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.research import StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import (
    _wait_until,
    _write_accepted_dataset,
)


def test_composed_eight_chart_vertical_workflow(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    try:
        main.action_for_id("main_window.open_research_suite").trigger()
        window = composition.research_suite_window
        presenter = composition.research_suite_presenter
        assert window is not None and presenter is not None
        _wait_until(lambda: window.selected_market_id() is not None)
        for expected_count in range(1, 9):
            presenter.open_selected_dataset()
            _wait_until(lambda expected_count=expected_count: len(presenter.slot_ids()) == expected_count)
        _wait_until(lambda: all(presenter.session_for(slot).resident is not None for slot in presenter.slot_ids()))
        assert presenter.slot_ids() == tuple(range(1, 9))
        assert len({presenter.session_for(slot).session_id for slot in presenter.slot_ids()}) == 8
        before = tuple(
            (slot, presenter.session_for(slot).session_id) for slot in presenter.slot_ids()
        )
        presenter.open_selected_dataset()
        assert tuple(
            (slot, presenter.session_for(slot).session_id) for slot in presenter.slot_ids()
        ) == before

        presenter.submit_study_calculation(
            StudyExecutionRequest("sma", {"period": 3}), slot_id=1
        )
        presenter.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3}), slot_id=2
        )
        _wait_until(lambda: presenter.session_for(1).study_count == 1)
        _wait_until(lambda: presenter.session_for(2).study_count == 1)
        assert all(presenter.session_for(slot).study_count == 0 for slot in range(3, 9))

        presenter.set_active_slot(1)
        first_chart = window.chart_widget
        first_chart_id = id(first_chart)
        window.button_for_id("research_suite.button.toggle_autoscale").click()
        window.button_for_id("research_suite.button.toggle_volume").click()
        assert first_chart.autoscale_enabled is False
        assert presenter.chart_presenter(1).chart_workspace.volume_visible is True
        presenter.set_active_slot(2)
        assert window.chart_widget.autoscale_enabled is True
        assert window.chart_workspace.volume_visible is False
        assert tuple(item.study_id for item in window.study_manager.entries) == (
            presenter.session_for(2).studies[0].study_id,
        )

        identities = {
            slot: window.workspace_widget.slot_widget(slot) for slot in presenter.slot_ids()
        }
        window.workspace_widget.set_visualization_mode("fit_8")
        window.workspace_widget.set_visualization_mode("scroll_4")
        assert id(presenter.chart_presenter(1).chart_widget) == first_chart_id
        assert all(window.workspace_widget.slot_widget(slot) is widget for slot, widget in identities.items())

        presenter.set_active_slot(1)
        old_session = presenter.session_for(1)
        presenter.close_active_chart()
        assert old_session.is_disposed
        assert presenter.slot_ids() == (2, 3, 4, 5, 6, 7, 8)
        surviving = {slot: presenter.session_for(slot) for slot in presenter.slot_ids()}
        presenter.open_selected_dataset()
        _wait_until(lambda: presenter.slot_ids() == tuple(range(1, 9)))
        _wait_until(lambda: presenter.session_for(1).resident is not None)
        assert presenter.session_for(1).session_id != old_session.session_id
        assert all(presenter.session_for(slot) is session for slot, session in surviving.items())
        assert any(
            item.metadata.get("operation") == "research_dataset_load"
            for item in app.task_manager.snapshots()
        )
    finally:
        sessions = () if composition.research_suite_presenter is None else tuple(
            composition.research_suite_presenter.session_for(slot)
            for slot in composition.research_suite_presenter.slot_ids()
        )
        main.close()
        QCoreApplication.processEvents()
        assert all(session.is_disposed for session in sessions)
        app.shutdown()
        qapp.processEvents()
