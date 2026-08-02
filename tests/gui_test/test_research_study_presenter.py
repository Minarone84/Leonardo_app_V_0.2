from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

import leonardo.research.study_execution as study_execution
from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.windows.study_style_dialog import StudyStylePatch
from leonardo.research import StudyArtifactRequest, StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import (
    _open_restored_chart,
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
    slot_id = _open_restored_chart(window, presenter)
    return app, main, window, presenter._chart_presenters[slot_id]


def test_presenter_apply_edit_save_and_artifact_apply_share_renderer(
    tmp_path: Path, monkeypatch
) -> None:
    qapp = QApplication.instance() or QApplication([])
    calculations: list[str] = []
    original_calculate = study_execution.calculate_financial_tool

    def counted_calculate(tool_key, *args, **kwargs):
        calculations.append(tool_key)
        return original_calculate(tool_key, *args, **kwargs)

    monkeypatch.setattr(
        study_execution, "calculate_financial_tool", counted_calculate
    )
    app, main, window, chart_presenter = _open(tmp_path)
    try:
        chart_presenter.submit_study_calculation(
            StudyExecutionRequest("sma", {"period": 3})
        )
        _wait_until(lambda: chart_presenter.session.study_count == 1)
        study = chart_presenter.session.studies[0]
        initial = chart_presenter.session.study_presentations()[0]
        line = replace(initial.signal_styles["sma_3"], color="#FFFFFF")
        chart_presenter.apply_style_patch(
            StudyStylePatch(study.study_id, True, (line,), ())
        )
        styled = chart_presenter.session.study_presentations()[0]
        assert styled.revision == 1
        assert not app.artifact_service.list_artifacts(study.market_id)
        row = chart_presenter._view.price_overlay.study_rows[0]
        row.values_button.click()
        assert not row.current_values_visible
        pane_id = styled.pane_id

        chart_presenter.submit_study_edit(
            study.study_id,
            StudyExecutionRequest("sma", {"period": 5}),
        )
        _wait_until(
            lambda: chart_presenter.session.studies[0].edit_request.parameters
            == {"period": 5}
        )
        edited = chart_presenter.session.studies[0]
        edited_presentation = chart_presenter.session.study_presentations()[0]
        assert edited.study_id == study.study_id
        assert edited.saved_link is None
        assert edited_presentation.pane_id == pane_id
        assert edited_presentation.signal_styles["sma_5"].color == "#FFFFFF"
        assert chart_presenter._view.price_overlay.study_rows[0] is row
        assert not row.current_values_visible
        assert calculations == ["sma", "sma"]

        chart_presenter.save_study(edited.study_id)
        _wait_until(
            lambda: chart_presenter.session.studies[0].saved_link is not None
        )
        saved = chart_presenter.session.studies[0]
        assert saved.study_id == study.study_id
        assert chart_presenter.session.study_presentations()[0] == edited_presentation
        assert saved.saved_link is not None
        artifact_id = saved.saved_link.artifact_id
        artifact_count = len(app.artifact_service.list_artifacts(saved.market_id))
        assert calculations == ["sma", "sma"]

        chart_presenter.submit_study_edit(
            saved.study_id,
            StudyExecutionRequest("sma", {"period": 7}),
        )
        _wait_until(
            lambda: chart_presenter.session.studies[0].saved_link is None
        )
        edited_saved = chart_presenter.session.studies[0]
        assert edited_saved.study_id == saved.study_id
        assert edited_saved.edit_request.parameters == {"period": 7}
        assert len(app.artifact_service.list_artifacts(saved.market_id)) == artifact_count

        chart_presenter.remove_study(edited_saved.study_id)
        assert chart_presenter.session.study_count == 0
        count_before_artifact_apply = len(calculations)
        with pytest.raises(TypeError):
            chart_presenter.submit_artifact_apply(
                StudyArtifactRequest(
                    saved.result.kind,
                    saved.result.tool_key,
                    artifact_id,
                ),
                completion_callback=object(),
            )
        outcomes = []
        chart_presenter.submit_artifact_apply(
            StudyArtifactRequest(
                saved.result.kind,
                saved.result.tool_key,
                artifact_id,
            ),
            completion_callback=outcomes.append,
        )
        _wait_until(lambda: chart_presenter.session.study_count == 1)
        artifact_study = chart_presenter.session.studies[0]
        assert len(outcomes) == 1
        assert outcomes[0].operation == "apply"
        assert outcomes[0].status == "success"
        assert outcomes[0].study_id == artifact_study.study_id
        assert len(calculations) == count_before_artifact_apply
        assert artifact_study.source_kind == "artifact"
        chart_presenter.submit_study_edit(
            artifact_study.study_id,
            artifact_study.edit_request,
        )
        _wait_until(
            lambda: chart_presenter.session.studies[0].source_kind == "calculation"
        )
        final = chart_presenter.session.studies[0]
        assert final.study_id == artifact_study.study_id
        assert final.saved_link is None
        assert len(app.artifact_service.list_artifacts(saved.market_id)) == artifact_count
        assert chart_presenter.chart_widget.study_scene is not None
        assert chart_presenter.chart_widget.study_scene.line_strips
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
