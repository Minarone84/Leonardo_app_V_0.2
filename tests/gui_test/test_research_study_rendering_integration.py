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
from leonardo.gui.windows.study_style_dialog import StudyStylePatch
from leonardo.research import StudyExecutionRequest, StudyInputSource
from tests.gui_test.test_research_single_chart_integration import (
    _wait_until,
    _write_accepted_dataset,
)


def test_full_composed_study_rendering_workflow(tmp_path: Path) -> None:
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
        window.button_for_id("research_suite.button.open_chart").click()
        _wait_until(lambda: window.status_text() == "Chart ready")

        requests = (
            StudyExecutionRequest("sma", {"period": 3}, display_name="SMA A"),
            StudyExecutionRequest("sma", {"period": 3}, display_name="SMA B"),
            StudyExecutionRequest("rsi", {"period": 3}),
            StudyExecutionRequest("hck", {"fast_vwap_l": 3, "slow_vwap_l": 5}),
            StudyExecutionRequest(
                "dynamic_binning",
                {},
                (StudyInputSource("source_1", "ohlcv", column_name="close"),),
            ),
        )
        for count, request in enumerate(requests, start=1):
            presenter.submit_study_calculation(request)
            _wait_until(lambda count=count: presenter.session.study_count == count)

        studies = presenter.session.studies
        presentations = presenter.session.study_presentations()
        sma_a, sma_b, rsi, hck, dynamic = studies
        assert window.chart_workspace.study_pane_ids() == (
            "price",
            f"oscillator:{rsi.study_id}",
        )
        assert next(item for item in presentations if item.study_id == dynamic.study_id).pane_id is None
        assert window.chart_workspace.oscillator_widget(rsi.study_id) is not None

        second = next(item for item in presentations if item.study_id == sma_b.study_id)
        changed = replace(second.signal_styles["sma_3"], color="#FFFFFF")
        presenter._apply_style_patch(StudyStylePatch(sma_b.study_id, True, (changed,), ()))
        current = {item.study_id: item for item in presenter.session.study_presentations()}
        assert current[sma_a.study_id].signal_styles["sma_3"].color == "#F59E0B"
        assert current[sma_b.study_id].signal_styles["sma_3"].color == "#FFFFFF"

        presenter._set_study_visibility(hck.study_id, False)
        assert not next(item for item in presenter.session.study_presentations() if item.study_id == hck.study_id).visible
        presenter._set_study_visibility(hck.study_id, True)
        presenter._save_study(sma_a.study_id)
        _wait_until(lambda: presenter.session.study_registry.get(sma_a.study_id).saved_link is not None)
        presenter._remove_study(rsi.study_id)
        assert window.chart_workspace.oscillator_widget(rsi.study_id) is None
        assert any(
            item.metadata.get("operation") == "research_study_apply"
            for item in app.task_manager.snapshots()
        )
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
