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
    _open_restored_chart,
    _select_new_chart_dialog,
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
        _wait_until(lambda: bool(window.dataset_summaries))
        state = presenter._workspace_state
        for _ in range(8):
            _open_restored_chart(window, presenter)
        assert state.slot_ids() == tuple(range(1, 9))
        assert len({state.session_for(slot).session_id for slot in state.slot_ids()}) == 8
        before = tuple(
            (slot, state.session_for(slot).session_id) for slot in state.slot_ids()
        )
        presenter.open_new_chart()
        _select_new_chart_dialog(presenter)
        assert tuple(
            (slot, state.session_for(slot).session_id) for slot in state.slot_ids()
        ) == before

        presenter._chart_presenters[1].submit_study_calculation(
            StudyExecutionRequest("sma", {"period": 3})
        )
        presenter._chart_presenters[2].submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3})
        )
        _wait_until(lambda: state.session_for(1).study_count == 1)
        _wait_until(lambda: state.session_for(2).study_count == 1)
        assert all(state.session_for(slot).study_count == 0 for slot in range(3, 9))

        window.workspace.set_active_slot(1)
        first_panel = window.workspace.chart_panel_for_slot(1)
        first_chart = first_panel.chart_widget
        first_chart_id = id(first_chart)
        presenter._chart_presenters[1].set_autoscale_enabled(False)
        presenter._chart_presenters[1].set_volume_visible(True)
        assert first_chart.autoscale_enabled is False
        assert first_panel.chart_workspace.volume_visible is True
        window.workspace.set_active_slot(2)
        second_panel = window.workspace.chart_panel_for_slot(2)
        assert second_panel.chart_widget.autoscale_enabled is True
        assert second_panel.chart_workspace.volume_visible is False
        presenter._open_studies_manager(2)
        manager = presenter._studies_manager_dialogs[2]
        assert tuple(item.study_id for item in manager.entries) == (
            state.session_for(2).studies[0].study_id,
        )

        identities = {
            slot: window.workspace.chart_panel_for_slot(slot)
            for slot in state.slot_ids()
        }
        window.workspace.set_visualization_mode("fit_8")
        window.workspace.set_visualization_mode("scroll_4")
        assert id(presenter._chart_presenters[1].chart_widget) == first_chart_id
        assert all(
            window.workspace.chart_panel_for_slot(slot) is widget
            for slot, widget in identities.items()
        )

        window.workspace.set_active_slot(1)
        old_session = state.session_for(1)
        window.workspace.chart_panel_for_slot(1).close_button.click()
        assert old_session.is_disposed
        assert state.slot_ids() == (2, 3, 4, 5, 6, 7, 8)
        surviving = {slot: state.session_for(slot) for slot in state.slot_ids()}
        assert _open_restored_chart(window, presenter) == 1
        assert state.session_for(1).session_id != old_session.session_id
        assert all(
            state.session_for(slot) is session
            for slot, session in surviving.items()
        )
        assert any(
            item.metadata.get("operation") == "research_dataset_load"
            for item in app.task_manager.snapshots()
        )
        manager.close()
    finally:
        current = composition.research_suite_presenter
        sessions = (
            ()
            if current is None
            else tuple(
                current._workspace_state.session_for(slot)
                for slot in current._workspace_state.slot_ids()
            )
        )
        main.close()
        QCoreApplication.processEvents()
        assert all(session.is_disposed for session in sessions)
        app.shutdown()
        qapp.processEvents()
