from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tests.gui_test.test_research_gui_service_catalog import (
    _dataset_bundle,
    _select_complete_summary,
    _settle_qt,
)
from tests.gui_test.test_research_gui_service_financial_tools import (
    open_financial_tools,
    open_ready_chart,
    real_presenter,
)
from tests.gui_test.test_research_gui_service_study_apply import (
    _apply_tool,
    _complete_catalog_refresh,
    _select_tool,
)
from leonardo.research.study_projection import project_study


def _large_bundle():
    dataset, summary = _dataset_bundle()
    count = 6_000
    timestamps = tuple(
        1_700_000_000_000 + index * 14_400_000 for index in range(count)
    )
    values = tuple(float(100 + index) for index in range(count))
    dataset = replace(
        dataset,
        row_count=count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=values,
        high=tuple(value + 2.0 for value in values),
        low=tuple(value - 2.0 for value in values),
        close=tuple(value + 1.0 for value in values),
        volume=tuple(1_000.0 + index for index in range(count)),
    )
    summary = replace(
        summary,
        row_count=count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )
    return dataset, summary


def test_dynamic_price_oscillator_overlays_and_refill_reuse(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    bundle = _large_bundle()
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path, bundle=bundle
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        chart_presenter = presenter._chart_presenters[slot_id]
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        window.show()
        _settle_qt()

        _apply_tool(dialog, studies, setup, "SMA")
        assert [row.display_name for row in panel.price_overlay.study_rows] == [
            "SMA 14"
        ]
        assert any(
            strip.output_name.startswith("sma_")
            for strip in panel.chart_widget.study_scene.line_strips
        ), tuple(
            strip.output_name for strip in panel.chart_widget.study_scene.line_strips
        )
        sma_study_id = chart_presenter.session.studies[0].study_id
        panel.price_overlay.study_rows[0].edit_button.click()
        setup.complete(next(reversed(setup.pending)))
        _settle_qt()
        edit_dialog = presenter._study_edit_dialogs[(slot_id, sma_study_id)]
        edit_dialog.parameter_controls["period"].setValue(20)
        edit_dialog.apply_edit_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert chart_presenter.session.studies[0].study_id == sma_study_id
        assert panel.price_overlay.study_rows[0].display_name == "SMA 20"

        _apply_tool(dialog, studies, setup, "Bollinger Bands")
        assert [
            row.display_name for row in panel.price_overlay.study_rows
        ] == ["SMA 20", "BB 14 2"]
        assert panel.chart_widget.study_scene.fills

        _apply_tool(dialog, studies, setup, "RSI")
        rsi_study = chart_presenter.session.studies[-1]
        assert panel.chart_workspace.study_pane_ids() == (
            "price",
            f"oscillator:{rsi_study.study_id}",
        )
        assert len(panel.oscillator_overlays) == 1
        oscillator = panel.oscillator_overlays[0]
        oscillator_widget = panel.chart_workspace.oscillator_widget(rsi_study.study_id)
        assert panel.price_overlay.isVisible()
        assert oscillator.isVisible()
        assert oscillator.parentWidget() is oscillator_widget
        assert oscillator_widget._interaction is panel.chart_widget.interaction_state
        assert oscillator._interaction_state is panel.chart_widget.interaction_state
        assert oscillator.title_label.text() == "RSI 14"
        assert (
            "Parameters:\n"
            "Period: 14\n"
            "Guide levels:\n"
            "Oversold: 30\n"
            "Center: 50\n"
            "Overbought: 70"
        ) in oscillator.title_label.toolTip()

        price_row = panel.price_overlay.study_rows[0]
        price_row.values_button.click()
        oscillator.values_button.click()
        assert not price_row.current_values_visible
        assert not oscillator.current_values_visible
        for row in panel.price_overlay.study_rows:
            assert row.values_button.isEnabled()
            assert row.style_button.isEnabled()
            assert row.edit_button.isEnabled()
            assert row.edit_button.toolTip() == "Edit computation parameters"
            assert row.remove_button.isEnabled()
        assert oscillator.values_button.isEnabled()
        assert oscillator.style_button.isEnabled()
        assert oscillator.edit_button.isEnabled()
        assert oscillator.edit_button.toolTip() == "Edit computation parameters"
        assert oscillator.remove_button.isEnabled()
        assert not oscillator.move_up_button.isEnabled()
        assert not oscillator.move_down_button.isEnabled()

        dialog_identity = id(dialog)
        price_overlay_identity = id(panel.price_overlay)
        price_row_identity = id(price_row)
        oscillator_identity = id(oscillator)
        result_identities = tuple(id(study.result) for study in chart_presenter.session.studies)
        old_projection = oscillator._projection
        old_base = chart_presenter.session.resident.base_index
        price_values_before = price_row.values_label.text()
        oscillator.values_label.setText("stale")
        oscillator_values_before = oscillator.values_label.text()
        chart_presenter.center_on_timestamp_ms(bundle[0].ts_ms[0])
        refill_task = chart_presenter._active_slice_task_id
        assert refill_task is not None
        assert dataset_service.pending[refill_task][2].base_index == 0
        dataset_service.complete(refill_task)
        _settle_qt()

        assert chart_presenter.session.resident.base_index != old_base
        assert id(presenter._financial_tools_dialogs[slot_id]) == dialog_identity
        assert id(panel.price_overlay) == price_overlay_identity
        assert id(panel.price_overlay.study_rows[0]) == price_row_identity
        assert id(panel.oscillator_overlays[0]) == oscillator_identity
        assert panel.price_overlay.isVisible()
        assert panel.oscillator_overlays[0].isVisible()
        assert panel.oscillator_overlays[0]._projection is not old_projection
        assert panel.price_overlay.study_rows[0].values_label.text() != price_values_before
        assert panel.oscillator_overlays[0].values_label.text() != oscillator_values_before
        assert not panel.price_overlay.study_rows[0].current_values_visible
        assert not panel.oscillator_overlays[0].current_values_visible
        assert tuple(id(study.result) for study in chart_presenter.session.studies) == (
            result_identities
        )

        pane_identity = id(
            panel.chart_workspace.oscillator_widget(rsi_study.study_id)
        )
        window.workspace.detach_chart(slot_id)
        _settle_qt()
        window.workspace.dock_chart(slot_id)
        _settle_qt()
        assert id(panel.price_overlay) == price_overlay_identity
        assert id(panel.oscillator_overlays[0]) == oscillator_identity
        assert panel.price_overlay.isVisible()
        assert panel.oscillator_overlays[0].isVisible()
        assert id(
            panel.chart_workspace.oscillator_widget(rsi_study.study_id)
        ) == pane_identity

        chart_presenter.session.remove_study(rsi_study.study_id)
        chart_presenter._refresh_study_state()
        _settle_qt()
        assert panel.chart_workspace.oscillator_widget(rsi_study.study_id) is None
        assert panel.oscillator_overlays == ()
    finally:
        presenter.dispose()
        window.close()


def test_two_charts_do_not_share_studies_panes_or_overlays(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        first = open_ready_chart(window, presenter, dataset_service, summary)
        first_dialog = open_financial_tools(window, presenter, setup, first)
        _apply_tool(first_dialog, studies, setup, "RSI")

        presenter.open_new_chart()
        _select_complete_summary(presenter)
        presenter._new_chart_dialog.create_button.click()
        dataset_service.complete(dataset_service.pending_ids("load")[-1])
        dataset_service.complete(dataset_service.pending_ids("resident")[-1])
        _settle_qt()
        second = presenter._workspace_state.active_slot_id
        assert second == 2
        first_panel = window.workspace.chart_panel_for_slot(first)
        second_panel = window.workspace.chart_panel_for_slot(second)
        assert first_panel.oscillator_overlays
        assert second_panel.oscillator_overlays == ()
        assert presenter._workspace_state.session_for(first).study_count == 1
        assert presenter._workspace_state.session_for(second).study_count == 0

        second_dialog = open_financial_tools(window, presenter, setup, second)
        _apply_tool(second_dialog, studies, setup, "SMA")
        assert second_panel.price_overlay.study_rows
        assert first_panel.price_overlay is not second_panel.price_overlay
        assert first_panel.oscillator_overlays[0].parentWidget() is not (
            second_panel.chart_widget
        )
    finally:
        presenter.dispose()
        window.close()


def test_tdirsi_and_smi_styles_fill_refill_edit_and_detach_are_chart_local(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    bundle = _large_bundle()
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path, bundle=bundle
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        chart_presenter = presenter._chart_presenters[slot_id]
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(dialog, studies, setup, "TDI RSI")
        _apply_tool(dialog, studies, setup, "SMI")
        tdirsi, smi = chart_presenter.session.studies
        presentations = {
            item.study_id: item
            for item in chart_presenter.session.study_presentations()
        }
        tdirsi_presentation = presentations[tdirsi.study_id]
        assert tuple(
            (style.color, style.line_pattern)
            for style in tdirsi_presentation.signal_styles.values()
        ) == (
            ("#22C55E", "solid"),
            ("#EF4444", "solid"),
            ("#60A5FA", "dashed"),
            ("#60A5FA", "dashed"),
            ("#F59E0B", "solid"),
        )
        assert tuple(
            style.color
            for style in presentations[smi.study_id].signal_styles.values()
        ) == ("#06B6D4", "#F59E0B")

        custom_fill = replace(
            tdirsi_presentation.fill_styles["tdirsi_band"],
            color="#123456",
            opacity=0.25,
            visible=True,
        )
        chart_presenter.session.replace_study_fill_style(
            tdirsi.study_id, "tdirsi_band", custom_fill
        )
        chart_presenter._refresh_study_state()
        panel.chart_widget._static_scene_pixmap()
        price_scene = panel.chart_widget.study_scene
        assert price_scene is not None
        price_render_before = (price_scene.line_strips, price_scene.fills)
        tdirsi_widget = panel.chart_workspace.oscillator_widget(tdirsi.study_id)
        smi_widget = panel.chart_workspace.oscillator_widget(smi.study_id)
        assert tdirsi_widget is not None and smi_widget is not None
        tdirsi_widget._static_pixmap()
        smi_widget._static_pixmap()
        assert tdirsi_widget.scene_plan.fills
        assert {
            (item.color, item.opacity) for item in tdirsi_widget.scene_plan.fills
        } == {("#123456", 0.25)}
        assert tuple(
            (guide.kind, guide.color)
            for guide in smi_widget.scene_plan.guides
        ) == (("zero", "#94A3B8"),)

        chart_presenter.center_on_timestamp_ms(bundle[0].ts_ms[0])
        refill_task = chart_presenter._active_slice_task_id
        assert refill_task is not None
        dataset_service.complete(refill_task)
        _settle_qt()
        retained = {
            item.study_id: item
            for item in chart_presenter.session.study_presentations()
        }[tdirsi.study_id]
        assert retained.fill_styles["tdirsi_band"] == custom_fill
        panel.chart_widget._static_scene_pixmap()
        assert panel.chart_widget.study_scene is not None
        assert (
            panel.chart_widget.study_scene.line_strips,
            panel.chart_widget.study_scene.fills,
        ) == price_render_before

        pane_identity = id(tdirsi_widget)
        window.workspace.detach_chart(slot_id)
        _settle_qt()
        window.workspace.dock_chart(slot_id)
        _settle_qt()
        assert id(panel.chart_workspace.oscillator_widget(tdirsi.study_id)) == (
            pane_identity
        )

        overlay = next(
            item
            for item in panel.oscillator_overlays
            if item.study_id == tdirsi.study_id
        )
        overlay.edit_button.click()
        setup.complete(next(reversed(setup.pending)))
        _settle_qt()
        edit_dialog = presenter._study_edit_dialogs[
            (slot_id, tdirsi.study_id)
        ]
        edit_dialog.parameter_controls["period"].setValue(10)
        edit_dialog.apply_edit_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        edited = chart_presenter.session.studies[0]
        edited_fill = chart_presenter.session.study_presentations()[0].fill_styles[
            "tdirsi_band"
        ]
        assert edited.study_id == tdirsi.study_id
        assert edited_fill.color == "#123456"
        assert edited_fill.opacity == 0.25
        assert edited_fill.visible is True
        assert edited_fill.upper_output_name == edited.renderable_output_names[2]
        assert edited_fill.lower_output_name == edited.renderable_output_names[3]

        chart_presenter.remove_study(tdirsi.study_id)
        chart_presenter.remove_study(smi.study_id)
        _settle_qt()
        assert panel.chart_workspace.study_pane_ids() == ("price",)
        assert panel.oscillator_overlays == ()
    finally:
        presenter.dispose()
        window.close()


def test_hck_and_strategy_embedded_hck_share_conditional_rendering_policy(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        chart_presenter = presenter._chart_presenters[slot_id]
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(dialog, studies, setup, "Hancock")
        _apply_tool(dialog, studies, setup, "Strategy")

        presentations = {
            item.tool_key: item
            for item in chart_presenter.session.study_presentations()
        }
        for tool_key, prefix in (("hck", ""), ("strategy", "st_")):
            presentation = presentations[tool_key]
            driver = f"{prefix}vwap_color"
            for output_name in (
                f"{prefix}fast_vwap",
                f"{prefix}slow_vwap",
            ):
                style = presentation.signal_styles[output_name]
                assert style.visible
                assert style.conditional_driver_name == driver
                assert style.conditional_colors["green"] == "#22C55E"
                assert style.conditional_colors["silver"] == "#22C55E"
                assert style.conditional_colors["red"] == "#EF4444"
                assert style.color != "#60A5FA"
            fill = presentation.fill_styles[f"{prefix}hck_band"]
            assert fill.conditional_driver_name == driver
            assert fill.opacity == 0.08
            assert fill.conditional_colors["silver"] == "#22C55E"
            assert driver not in presentation.signal_styles

        panel.chart_widget._static_scene_pixmap()
        scene = panel.chart_widget.study_scene
        assert scene is not None
        assert {"hck_band", "st_hck_band"}.issubset(
            {fill.fill_id for fill in scene.fills}
        )
        assert not any(
            strip.color == "#60A5FA"
            for strip in scene.line_strips
            if strip.output_name
            in {
                "fast_vwap",
                "slow_vwap",
                "st_fast_vwap",
                "st_slow_vwap",
            }
        )
    finally:
        presenter.dispose()
        window.close()


def test_utc_production_apply_projects_regions_and_preserves_existing_geometry(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        chart_presenter = presenter._chart_presenters[slot_id]
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(dialog, studies, setup, "Peaks & Troughs")
        peaks = chart_presenter.session.studies[-1]

        _select_tool(dialog, "Universal Trend Classifier")
        assert dialog.source_selector.selected_owner_key == (
            "study",
            peaks.study_id,
        )
        assert dialog.apply_button.isEnabled()
        dialog.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        _complete_catalog_refresh(setup)

        utc = chart_presenter.session.studies[-1]
        presentation = chart_presenter.session.study_presentations()[-1]
        assert tuple(presentation.background_region_styles) == (
            "utc_uptrend",
            "utc_downtrend",
        )
        projection = project_study(utc, chart_presenter.session.resident)
        count = len(projection.ts_ms)
        drivers = dict(projection.style_driver_series)
        drivers["uptrend"] = tuple(index in (1, 2) for index in range(count))
        drivers["downtrend"] = tuple(index in (4, 5) for index in range(count))
        render_series = dict(projection.render_series)
        render_series["hor_upper"] = (110.0,) * count
        render_series["hor_lower"] = (90.0,) * count
        marker_name = next(
            name
            for name, style in presentation.signal_styles.items()
            if style.render_mode == "marker"
        )
        render_series[marker_name] = tuple(
            100.0 if index == 2 else float("nan") for index in range(count)
        )
        projection = replace(
            projection,
            render_series=render_series,
            style_driver_series=drivers,
        )
        panel.set_study_state((projection,), (presentation,))
        _settle_qt()
        panel.chart_widget._static_scene_pixmap()

        scene = panel.chart_widget.study_scene
        assert scene is not None
        assert {item.region_id for item in scene.background_regions} == {
            "utc_uptrend",
            "utc_downtrend",
        }
        assert not any(fill.fill_id == "utc_range" for fill in scene.fills)
        assert any(
            strip.output_name in {"hor_upper", "hor_lower"}
            for strip in scene.line_strips
        )
        assert scene.markers
        assert not {
            strip.output_name for strip in scene.line_strips
        }.intersection({"uptrend", "downtrend"})

        chart_presenter.remove_study(utc.study_id)
        _settle_qt()
        panel.chart_widget._static_scene_pixmap()
        scene = panel.chart_widget.study_scene
        assert scene is not None
        assert not any(
            item.study_id == utc.study_id for item in scene.background_regions
        )
        assert not any(fill.study_id == utc.study_id for fill in scene.fills)
        assert not any(
            strip.study_id == utc.study_id for strip in scene.line_strips
        )
        assert not any(marker.study_id == utc.study_id for marker in scene.markers)
    finally:
        presenter.dispose()
        window.close()
