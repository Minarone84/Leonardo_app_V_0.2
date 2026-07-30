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
    _open_restored_chart,
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
        slot_id = _open_restored_chart(window, presenter)
        chart_presenter = presenter._chart_presenters[slot_id]

        requests = (
            StudyExecutionRequest("sma", {"period": 3}, display_name="SMA A"),
            StudyExecutionRequest("sma", {"period": 3}, display_name="SMA B"),
            StudyExecutionRequest("rsi", {"period": 3}),
            StudyExecutionRequest(
                "tdirsi", {"period": 3, "band_length": 3}
            ),
            StudyExecutionRequest("smi", {"k_length": 3, "d_length": 2}),
            StudyExecutionRequest("hck", {"fast_vwap_l": 3, "slow_vwap_l": 5}),
            StudyExecutionRequest(
                "dynamic_binning",
                {},
                (StudyInputSource("source_1", "ohlcv", column_name="close"),),
            ),
        )
        for count, request in enumerate(requests, start=1):
            chart_presenter.submit_study_calculation(request)
            _wait_until(
                lambda count=count: chart_presenter.session.study_count == count
            )

        studies = chart_presenter.session.studies
        presentations = chart_presenter.session.study_presentations()
        sma_a, sma_b, rsi, tdirsi, smi, hck, dynamic = studies
        assert chart_presenter.chart_workspace.study_pane_ids() == (
            "price",
            f"oscillator:{rsi.study_id}",
            f"oscillator:{tdirsi.study_id}",
            f"oscillator:{smi.study_id}",
        )
        assert next(item for item in presentations if item.study_id == dynamic.study_id).pane_id is None
        assert (
            chart_presenter.chart_workspace.oscillator_widget(rsi.study_id)
            is not None
        )
        rsi_widget = chart_presenter.chart_workspace.oscillator_widget(rsi.study_id)
        tdirsi_widget = chart_presenter.chart_workspace.oscillator_widget(
            tdirsi.study_id
        )
        smi_widget = chart_presenter.chart_workspace.oscillator_widget(smi.study_id)
        assert rsi_widget is not None
        assert tdirsi_widget is not None
        assert smi_widget is not None
        rsi_widget._static_pixmap()
        tdirsi_widget._static_pixmap()
        smi_widget._static_pixmap()
        assert tuple(
            (guide.value, guide.color, guide.line_pattern)
            for guide in rsi_widget.scene_plan.guides
        ) == (
            (30.0, "#22C55E", "dashed"),
            (50.0, "#94A3B8", "dashed"),
            (70.0, "#EF4444", "dashed"),
        )
        assert {
            strip.color for strip in rsi_widget.scene_plan.line_strips
        }.issubset({"#22C55E", "#A855F7", "#EF4444"})
        assert tuple(
            (strip.output_name, strip.color, strip.line_pattern)
            for strip in tdirsi_widget.scene_plan.line_strips
        )[:2] == (
            (tdirsi.renderable_output_names[0], "#22C55E", "solid"),
            (tdirsi.renderable_output_names[1], "#EF4444", "solid"),
        )
        assert tdirsi_widget.scene_plan.fills
        assert all(
            fill.fill_id == "tdirsi_band"
            for fill in tdirsi_widget.scene_plan.fills
        )
        assert tuple(
            (guide.kind, guide.value, guide.color)
            for guide in smi_widget.scene_plan.guides
        ) == (("zero", 0.0, "#94A3B8"),)
        assert tuple(
            strip.color for strip in smi_widget.scene_plan.line_strips
        ) == ("#06B6D4", "#F59E0B")

        second = next(item for item in presentations if item.study_id == sma_b.study_id)
        changed = replace(second.signal_styles["sma_3"], color="#FFFFFF")
        chart_presenter.apply_style_patch(
            StudyStylePatch(sma_b.study_id, True, (changed,), ())
        )
        current = {
            item.study_id: item
            for item in chart_presenter.session.study_presentations()
        }
        assert current[sma_a.study_id].signal_styles["sma_3"].color == "#F59E0B"
        assert current[sma_b.study_id].signal_styles["sma_3"].color == "#FFFFFF"

        chart_presenter.set_study_visibility(hck.study_id, False)
        assert not next(
            item
            for item in chart_presenter.session.study_presentations()
            if item.study_id == hck.study_id
        ).visible
        chart_presenter.set_study_visibility(hck.study_id, True)
        chart_presenter.save_study(sma_a.study_id)
        _wait_until(
            lambda: chart_presenter.session.study_registry.get(
                sma_a.study_id
            ).saved_link
            is not None
        )
        chart_presenter.remove_study(rsi.study_id)
        assert chart_presenter.chart_workspace.oscillator_widget(rsi.study_id) is None
        assert any(
            item.metadata.get("operation") == "research_study_apply"
            for item in app.task_manager.snapshots()
        )
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
