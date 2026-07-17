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
from leonardo.research import StudyArtifactRequest, StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import (
    _wait_until,
    _write_accepted_dataset,
)


def _open(tmp_path: Path):
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
    window.button_for_id("research_suite.button.open_chart").click()
    _wait_until(lambda: window.status_text() == "Chart ready")
    return app, main, window, presenter


def test_presenter_apply_style_save_and_artifact_apply_share_renderer(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, presenter = _open(tmp_path)
    try:
        presenter.submit_study_calculation(StudyExecutionRequest("sma", {"period": 3}))
        _wait_until(lambda: presenter.session.study_count == 1)
        study = presenter.session.studies[0]
        initial = presenter.session.study_presentations()[0]
        line = replace(initial.signal_styles["sma_3"], color="#FFFFFF")
        presenter._apply_style_patch(
            StudyStylePatch(study.study_id, True, (line,), ())
        )
        styled = presenter.session.study_presentations()[0]
        assert styled.revision == 1
        assert not app.artifact_service.list_artifacts(study.market_id)

        presenter._save_study(study.study_id)
        _wait_until(lambda: presenter.session.studies[0].saved_link is not None)
        saved = presenter.session.studies[0]
        assert saved.study_id == study.study_id
        assert presenter.session.study_presentations()[0] == styled
        assert saved.saved_link is not None

        presenter._remove_study(saved.study_id)
        assert presenter.session.study_count == 0
        presenter.submit_artifact_apply(
            StudyArtifactRequest(
                saved.result.kind,
                saved.result.tool_key,
                saved.saved_link.artifact_id,
            )
        )
        _wait_until(lambda: presenter.session.study_count == 1)
        assert window.chart_widget.study_scene is not None
        assert window.chart_widget.study_scene.line_strips
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
