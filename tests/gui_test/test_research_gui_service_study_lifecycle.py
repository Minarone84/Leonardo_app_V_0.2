from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tests.gui_test.test_research_gui_service_catalog import _settle_qt
from tests.gui_test.test_research_gui_service_financial_tools import (
    open_financial_tools,
    open_ready_chart,
    real_presenter,
)
from tests.gui_test.test_research_gui_service_study_apply import (
    _three_artifact_catalog,
    _apply_tool,
    _complete_catalog_refresh,
    _select_tool,
)


def _presentation(session, study_id: str):
    return next(
        item for item in session.study_presentations() if item.study_id == study_id
    )


def _study(session, study_id: str):
    return next((item for item in session.studies if item.study_id == study_id), None)


def _line_color(session, study_id: str) -> str:
    presentation = _presentation(session, study_id)
    return next(iter(presentation.signal_styles.values())).color


def test_overlay_and_manager_style_share_chart_local_owner_and_refresh_baseline(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    tracked: list[tuple[object, str, str, str, bool]] = []

    def tracker(widget, window_id, title, window_type):
        tracked.append((widget, window_id, title, window_type, widget.isVisible()))

    window, presenter, datasets, studies, setup, summary = real_presenter(
        tmp_path, tracker
    )
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        financial = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(financial, studies, setup, "SMA")
        _apply_tool(financial, studies, setup, "RSI")
        session = presenter._workspace_state.session_for(slot_id)
        sma, rsi = session.studies
        result_identity = id(sma.result)
        default_sma_color = _line_color(session, sma.study_id)
        default_rsi_color = _line_color(session, rsi.study_id)

        price_row = panel.price_overlay.study_rows[0]
        price_row.style_button.click()
        _settle_qt()
        sma_dialog = presenter._study_style_dialogs[(slot_id, sma.study_id)]
        assert tracked[-1] == (
            sma_dialog,
            f"research_restoration.study_style.{slot_id}.{sma.study_id}",
            "Study Style",
            "dialog",
            False,
        )
        price_row.style_button.click()
        assert presenter._study_style_dialogs[(slot_id, sma.study_id)] is sma_dialog

        color, _width, _pattern, _visible = next(
            iter(sma_dialog._line_controls.values())
        )
        color.setText("#FFFFFF")
        sma_dialog.apply_patch()
        _settle_qt()
        assert _line_color(session, sma.study_id) == "#FFFFFF"
        assert id(_study(session, sma.study_id).result) == result_identity
        assert next(iter(sma_dialog.presentation.signal_styles.values())).color == (
            "#FFFFFF"
        )

        color.setText("#00FFFF")
        sma_dialog.apply_patch()
        _settle_qt()
        assert _line_color(session, sma.study_id) == "#00FFFF"

        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        assert manager.manager_widget.select_study(sma.study_id)
        manager.manager_widget._style.click()
        assert presenter._study_style_dialogs[(slot_id, sma.study_id)] is sma_dialog

        oscillator = panel.oscillator_overlays[0]
        oscillator.style_button.click()
        _settle_qt()
        rsi_dialog = presenter._study_style_dialogs[(slot_id, rsi.study_id)]
        assert rsi_dialog is not sma_dialog
        rsi_color, _width, _pattern, _visible = next(
            iter(rsi_dialog._line_controls.values())
        )
        rsi_color.setText("#ABCDEF")
        rsi_dialog.apply_patch()
        assert _line_color(session, rsi.study_id) == "#ABCDEF"

        assert manager.manager_widget.select_study(rsi.study_id)
        manager.manager_widget._reset.click()
        assert _line_color(session, rsi.study_id) == default_rsi_color
        assert manager.manager_widget.selected_study_id() == rsi.study_id

        sma_dialog.reset_button.click()
        _settle_qt()
        assert _line_color(session, sma.study_id) == default_sma_color
        assert (slot_id, sma.study_id) not in presenter._study_style_dialogs
    finally:
        presenter.dispose()
        window.close()


def test_overlay_phase_gates_visibility_and_remove_price_and_oscillator_studies(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        financial = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(financial, studies, setup, "SMA")
        _apply_tool(financial, studies, setup, "RSI")
        session = presenter._workspace_state.session_for(slot_id)
        sma, rsi = session.studies
        price_row = panel.price_overlay.study_rows[0]
        oscillator = panel.oscillator_overlays[0]

        assert price_row.values_button.isEnabled()
        assert price_row.style_button.isEnabled()
        assert price_row.edit_button.isEnabled()
        assert price_row.edit_button.toolTip() == "Edit computation parameters"
        assert price_row.remove_button.isEnabled()
        assert oscillator.values_button.isEnabled()
        assert oscillator.style_button.isEnabled()
        assert oscillator.edit_button.isEnabled()
        assert oscillator.edit_button.toolTip() == "Edit computation parameters"
        assert oscillator.remove_button.isEnabled()
        assert not oscillator.move_up_button.isEnabled()
        assert not oscillator.move_down_button.isEnabled()
        assert oscillator.move_up_button.toolTip() == (
            "Pane ordering is not available in this integration phase."
        )
        assert oscillator.move_down_button.toolTip() == (
            "Pane ordering is not available in this integration phase."
        )

        price_row.values_button.click()
        oscillator.values_button.click()
        assert not price_row.current_values_visible
        assert not oscillator.current_values_visible

        _select_tool(financial, "Bollinger Bands")
        financial.apply_button.click()
        assert price_row.values_button.isEnabled()
        assert not price_row.style_button.isEnabled()
        assert not price_row.edit_button.isEnabled()
        assert price_row.edit_button.toolTip() == (
            "Computation Edit is not available while the chart is busy."
        )
        assert not price_row.remove_button.isEnabled()
        assert oscillator.values_button.isEnabled()
        assert not oscillator.style_button.isEnabled()
        assert not oscillator.edit_button.isEnabled()
        assert oscillator.edit_button.toolTip() == (
            "Computation Edit is not available while the chart is busy."
        )
        assert not oscillator.remove_button.isEnabled()
        assert not panel.studies_button.isEnabled()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        _complete_catalog_refresh(setup)

        price_row = next(
            row for row in panel.price_overlay.study_rows if row.study_id == sma.study_id
        )
        price_row.style_button.click()
        sma_dialog = presenter._study_style_dialogs[(slot_id, sma.study_id)]
        price_row.remove_button.click()
        _settle_qt()
        assert _study(session, sma.study_id) is None
        assert all(row.study_id != sma.study_id for row in panel.price_overlay.study_rows)
        assert (slot_id, sma.study_id) not in presenter._study_style_dialogs
        assert not sma_dialog.isVisible()
        _complete_catalog_refresh(setup)

        oscillator = next(
            item for item in panel.oscillator_overlays if item.study_id == rsi.study_id
        )
        oscillator.style_button.click()
        oscillator.remove_button.click()
        _settle_qt()
        assert _study(session, rsi.study_id) is None
        assert panel.chart_workspace.oscillator_widget(rsi.study_id) is None
        assert all(item.study_id != rsi.study_id for item in panel.oscillator_overlays)
        assert (slot_id, rsi.study_id) not in presenter._study_style_dialogs
        _complete_catalog_refresh(setup)

        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        remaining = session.studies[0]
        assert manager.manager_widget.select_study(remaining.study_id)
        manager.manager_widget._remove.click()
        _settle_qt()
        assert session.study_count == 0
        assert manager.entries == ()
        _complete_catalog_refresh(setup)
    finally:
        presenter.dispose()
        window.close()


def test_dependency_block_close_and_slot_reuse_reject_retired_style_target(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        financial = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(financial, studies, setup, "SMA")
        session = presenter._workspace_state.session_for(slot_id)
        source = session.studies[0]

        _select_tool(financial, "Derivatives")
        option = next(
            item
            for item in financial._catalog.study_sources
            if item.study_id == source.study_id
        )
        financial.source_selector.select_option("source", option)
        financial.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        _complete_catalog_refresh(setup)
        assert session.study_count == 2

        source_row = next(
            row
            for row in panel.price_overlay.study_rows
            if row.study_id == source.study_id
        )
        source_row.style_button.click()
        retired_dialog = presenter._study_style_dialogs[(slot_id, source.study_id)]
        retired_patch = retired_dialog.build_patch()
        source_row.remove_button.click()
        _settle_qt()
        assert _study(session, source.study_id) is not None
        assert session.study_count == 2
        assert "Study removal blocked" in window._activity_log.toPlainText()

        panel.close_button.click()
        assert slot_id not in presenter._study_style_dialogs
        assert not retired_dialog.isVisible()
        reused = open_ready_chart(window, presenter, datasets, summary)
        assert reused == slot_id
        new_session = presenter._workspace_state.session_for(reused)
        presenter._apply_study_style(reused, retired_dialog, retired_patch)
        assert new_session.study_count == 0
        assert "stale Study style target rejected" in window._activity_log.toPlainText()

        new_panel = window.workspace.chart_panel_for_slot(reused)
        new_panel.studies_button.click()
        new_manager = presenter._studies_manager_dialogs[reused]
        presenter.dispose()
        assert presenter._studies_manager_dialogs == {}
        assert presenter._study_style_dialogs == {}
        assert not new_manager.isVisible()
    finally:
        presenter.dispose()
        window.close()


def test_chart_close_cancels_saved_artifact_batch_and_rejects_late_next(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        dialog.set_catalog(_three_artifact_catalog(dialog))
        for row in range(2):
            dialog.saved_artifact_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
            )
        dialog.apply_saved_artifact_button.click()
        first_task = next(iter(studies.pending))
        window.workspace.chart_panel_for_slot(slot_id).close_button.click()
        assert studies.cancel_counts[first_task] == 1
        assert slot_id not in presenter._saved_artifact_batch_runs
        studies.complete(first_task)
        _settle_qt()
        assert len(
            [
                request
                for kind, request in studies.submissions
                if kind == "artifact"
            ]
        ) == 1
        reused = open_ready_chart(window, presenter, datasets, summary)
        assert reused == slot_id
        assert presenter._workspace_state.session_for(reused).study_count == 0
    finally:
        presenter.dispose()
        window.close()


def test_chart_close_during_financial_tools_save_calculation_prevents_save(
    tmp_path: Path,
) -> None:
    from tests.gui_test.test_research_gui_service_study_save import (
        saving_presenter,
    )

    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = saving_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _select_tool(dialog, "SMA")
        dialog.save_button.click()
        calculation = next(iter(studies.pending))
        window.workspace.chart_panel_for_slot(slot_id).close_button.click()
        assert studies.cancel_counts[calculation] == 1
        assert slot_id not in presenter._financial_tools_save_runs
        studies.complete(calculation)
        _settle_qt()
        assert all(kind != "save" for kind, _request in studies.submissions)
        reused = open_ready_chart(window, presenter, datasets, summary)
        assert reused == slot_id
        assert presenter._workspace_state.session_for(reused).study_count == 0
    finally:
        presenter.dispose()
        window.close()
