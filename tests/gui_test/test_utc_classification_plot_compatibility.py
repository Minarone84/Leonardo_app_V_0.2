"""The nonvisual payload cannot add geometry or change UTC presentation."""
from dataclasses import replace
import os

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from leonardo.research.study_projection import project_study
from tests.financial_tools_test.test_utc_classification_compatibility import with_analysis
from tests.gui_test.test_research_gui_service_catalog import _dataset_bundle, _settle_qt
from tests.gui_test.test_research_gui_service_financial_tools import real_presenter, open_ready_chart, open_financial_tools
from tests.gui_test.test_research_gui_service_study_apply import _apply_tool, _select_tool, _complete_catalog_refresh


def chart_fixture(tmp_path):
    dataset, summary = _dataset_bundle()
    x = np.arange(dataset.row_count)
    close = 100 + np.where(x < 45, x * .4, 18 - (x - 45) * .45) + 4 * np.sin(x / 2.2)
    dataset = replace(dataset, open=tuple((close-.3).tolist()), high=tuple((close+1).tolist()),
                      low=tuple((close-1).tolist()), close=tuple(close.tolist()))
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path, bundle=(dataset, summary))
    slot = open_ready_chart(window, presenter, datasets, summary)
    panel = window.workspace.chart_panel_for_slot(slot)
    owner = presenter._chart_presenters[slot]
    dialog = open_financial_tools(window, presenter, setup, slot)
    _apply_tool(dialog, studies, setup, "Peaks & Troughs")
    _select_tool(dialog, "Universal Trend Classifier")
    dialog.apply_button.click()
    studies.complete(next(reversed(studies.pending)))
    _settle_qt()
    _complete_catalog_refresh(setup)
    dialog.close()
    return window, presenter, panel, owner


def test_current_and_legacy_analysis_render_identically(tmp_path):
    app = QApplication.instance() or QApplication([])
    window, presenter, panel, owner = chart_fixture(tmp_path)
    try:
        study = owner.session.studies[-1]
        presentation = owner.session.study_presentations()[-1]
        assert study.result.analysis["utc_classification"]["episodes"]
        current = project_study(study, owner.session.resident)
        legacy = project_study(replace(study, result=with_analysis(study.result, {})), owner.session.resident)
        pd.testing.assert_frame_equal(pd.DataFrame(current.render_series), pd.DataFrame(legacy.render_series), check_exact=True)
        pd.testing.assert_frame_equal(pd.DataFrame(current.style_driver_series), pd.DataFrame(legacy.style_driver_series), check_exact=True)
        assert len(study.result.output_names) == 27
        panel.set_study_state((legacy,), (presentation,))
        _settle_qt()
        before = panel.chart_widget._static_scene_pixmap().toImage().copy()
        panel.set_study_state((current,), (presentation,))
        _settle_qt()
        after = panel.chart_widget._static_scene_pixmap().toImage()
        assert before == after
        v1 = project_study(replace(study, result=with_analysis(study.result,
            {"utc_classification": study.result.analysis["utc_classification"]})), owner.session.resident)
        panel.set_study_state((v1,), (presentation,))
        _settle_qt()
        assert panel.chart_widget._static_scene_pixmap().toImage() == before
        assert "utc_episode_metrics" in study.result.analysis
        scene = panel.chart_widget.study_scene
        assert scene.background_regions
        assert not any("classification" in strip.output_name for strip in scene.line_strips)
    finally:
        presenter.dispose()
        window.close()
