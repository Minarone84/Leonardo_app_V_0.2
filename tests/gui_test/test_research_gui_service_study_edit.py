from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.gui.research.financial_tools_dialog import (
    ResearchFinancialToolsDialog,
    ResearchStudyEditDialog,
)
from leonardo.research import (
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudyInputSource,
)
from tests.gui_test.test_research_gui_service_catalog import _settle_qt
from tests.gui_test.test_research_gui_service_financial_tools import (
    open_financial_tools,
    open_ready_chart,
    real_presenter,
)
from tests.gui_test.test_research_gui_service_study_apply import _select_tool
from tests.gui_test.test_research_gui_service_study_save import (
    _complete_latest_setup,
    saving_presenter,
)


def _apply_sma(dialog, studies, setup, *, period: int = 3):
    _select_tool(dialog, "SMA")
    dialog.parameter_controls["period"].setValue(period)
    dialog.apply_button.click()
    studies.complete(next(reversed(studies.pending)))
    _settle_qt()
    setup.complete(next(reversed(setup.pending)))
    _settle_qt()


def _apply_rsi(
    dialog,
    studies,
    setup,
    *,
    period: int = 3,
    oversold: float | None = None,
):
    _select_tool(dialog, "RSI")
    dialog.parameter_controls["period"].setValue(period)
    if oversold is not None:
        dialog.guide_controls["oversold"].setValue(oversold)
    dialog.apply_button.click()
    studies.complete(next(reversed(studies.pending)))
    _settle_qt()
    setup.complete(next(reversed(setup.pending)))
    _settle_qt()


def _open_edit(panel, presenter, setup, study_id):
    row = next(
        (
            item
            for item in (
                *panel.price_overlay.study_rows,
                *panel.oscillator_overlays,
            )
            if item.study_id == study_id
        )
    )
    row.edit_button.click()
    setup.complete(next(reversed(setup.pending)))
    _settle_qt()
    return presenter._study_edit_dialogs[(panel.slot_id, study_id)], row


def test_overlay_edit_reuses_dialog_and_preserves_identity_style_values_and_pane(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_sma(dialog, studies, setup)
        session = presenter._workspace_state.session_for(slot_id)
        original = session.studies[0]
        presentation = session.study_presentations()[0]
        output_name = original.renderable_output_names[0]
        session.replace_study_line_style(
            original.study_id,
            output_name,
            replace(
                presentation.signal_styles[output_name],
                color="#FFFFFF",
                line_width=3.0,
                line_pattern="dotted",
            ),
        )
        presenter._chart_presenters[slot_id]._refresh_study_state()
        row = panel.price_overlay.study_rows[0]
        row.values_button.click()
        assert not row.current_values_visible

        edit_dialog, same_row = _open_edit(
            panel, presenter, setup, original.study_id
        )
        assert isinstance(dialog, ResearchFinancialToolsDialog)
        assert isinstance(edit_dialog, ResearchStudyEditDialog)
        assert edit_dialog is not dialog
        assert same_row is row
        assert not hasattr(edit_dialog, "family_combo")
        assert not hasattr(edit_dialog, "tool_list")
        assert not hasattr(edit_dialog, "saved_artifact_table")
        assert not hasattr(edit_dialog, "apply_saved_artifact_button")
        assert edit_dialog.tool_title_label.text() == "SMA"
        assert edit_dialog.description_label.text()
        assert edit_dialog.apply_edit_button.text() == "Apply Edit"
        assert not edit_dialog.apply_edit_button.isEnabled()
        assert edit_dialog.parameter_controls["period"].value() == 3
        applies: list[object] = []
        edit_dialog.edit_requested.connect(applies.append)
        edit_dialog.parameter_controls["period"].setValue(5)
        assert edit_dialog.apply_edit_button.isEnabled()
        edit_dialog.apply_edit_button.click()
        assert applies[0].study_id == original.study_id
        assert applies[0].request.parameters == {"period": 5}
        assert applies[0].calculation_changed
        assert not applies[0].guide_changed
        assert studies.submissions[-1][0] == "edit"
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()

        edited = session.studies[0]
        current = session.study_presentations()[0]
        new_output = edited.renderable_output_names[0]
        assert edited.study_id == original.study_id
        assert edited.saved_link is None
        assert panel.price_overlay.study_rows[0] is row
        assert not row.current_values_visible
        assert current.pane_id == presentation.pane_id
        assert current.signal_styles[new_output].color == "#FFFFFF"
        assert current.signal_styles[new_output].line_width == 3.0
        assert current.signal_styles[new_output].line_pattern == "dotted"
        assert presenter._financial_tools_dialogs[slot_id] is dialog
        assert presenter._study_edit_dialogs[(slot_id, original.study_id)] is edit_dialog
        assert edit_dialog.apply_edit_button.text() == "Apply Edit"
        assert edit_dialog.parameter_controls["period"].value() == 5
        same_row.edit_button.click()
        _settle_qt()
        assert presenter._study_edit_dialogs[(slot_id, original.study_id)] is edit_dialog
    finally:
        presenter.dispose()
        window.close()


def test_guide_only_edit_is_dirty_validated_and_preserves_study_truth(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        ordinary = open_financial_tools(window, presenter, setup, slot_id)
        _apply_rsi(ordinary, studies, setup, oversold=25.0)
        session = presenter._workspace_state.session_for(slot_id)
        original = session.studies[0]
        original_result = original.result
        original_origin = original.source_kind
        original_saved_link = original.saved_link
        original_presentation = session.study_presentations()[0]
        edit_dialog, _row = _open_edit(
            panel, presenter, setup, original.study_id
        )
        _select_tool(ordinary, "RSI")

        assert tuple(edit_dialog.guide_controls) == (
            "overbought",
            "center",
            "oversold",
        )
        assert tuple(ordinary.parameter_controls) == tuple(
            edit_dialog.parameter_controls
        )
        assert tuple(type(item) for item in ordinary.parameter_controls.values()) == tuple(
            type(item) for item in edit_dialog.parameter_controls.values()
        )
        assert ordinary.source_selector.schema == edit_dialog.source_selector.schema
        assert tuple(ordinary.guide_controls) == tuple(edit_dialog.guide_controls)
        assert tuple(type(item) for item in ordinary.guide_controls.values()) == tuple(
            type(item) for item in edit_dialog.guide_controls.values()
        )
        assert {
            name: control.value()
            for name, control in edit_dialog.guide_controls.items()
        } == {
            "overbought": 70.0,
            "center": 50.0,
            "oversold": 25.0,
        }
        oversold = edit_dialog.guide_controls["oversold"]
        assert not edit_dialog.apply_edit_button.isEnabled()
        oversold.setValue(20.0)
        assert edit_dialog.apply_edit_button.isEnabled()
        oversold.setValue(25.0)
        assert not edit_dialog.apply_edit_button.isEnabled()
        oversold.setValue(75.0)
        assert not edit_dialog.apply_edit_button.isEnabled()
        oversold.setValue(20.0)

        submissions_before = len(studies.submissions)
        edit_dialog.apply_edit_button.click()
        assert len(studies.submissions) == submissions_before
        current = session.study_registry.get(original.study_id)
        presentation = session.study_presentations()[0]
        assert current.study_id == original.study_id
        assert current.result is original_result
        assert current.source_kind == original_origin
        assert current.saved_link == original_saved_link
        assert presentation.guide_styles["oversold"].value == 20.0
        assert presentation.revision == original_presentation.revision + 1
        assert not edit_dialog.apply_edit_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_hck_creation_and_edit_share_two_parameters_without_guides(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        ordinary = open_financial_tools(window, presenter, setup, slot_id)
        _select_tool(ordinary, "Hancock")
        assert tuple(ordinary.parameter_controls) == (
            "fast_vwap_l",
            "slow_vwap_l",
        )
        assert ordinary.guide_controls == {}
        ordinary.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        setup.complete(next(reversed(setup.pending)))
        _settle_qt()
        study = presenter._workspace_state.session_for(slot_id).studies[0]
        edit_dialog, _row = _open_edit(
            panel,
            presenter,
            setup,
            study.study_id,
        )
        _select_tool(ordinary, "Hancock")
        assert tuple(edit_dialog.parameter_controls) == tuple(
            ordinary.parameter_controls
        )
        assert tuple(type(item) for item in edit_dialog.parameter_controls.values()) == tuple(
            type(item) for item in ordinary.parameter_controls.values()
        )
        assert edit_dialog.source_selector.schema == ordinary.source_selector.schema
        assert edit_dialog.guide_controls == {}
        assert not hasattr(edit_dialog, "family_combo")
        assert not hasattr(edit_dialog, "saved_artifact_table")
    finally:
        presenter.dispose()
        window.close()


def test_utc_edit_restores_owner_and_tracks_owner_and_window_changes(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    malformed_dialog = None
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        ordinary = open_financial_tools(window, presenter, setup, slot_id)
        for _index in range(2):
            _select_tool(ordinary, "Peaks & Troughs")
            ordinary.apply_button.click()
            studies.complete(next(reversed(studies.pending)))
            _settle_qt()
            setup.complete(next(reversed(setup.pending)))
            _settle_qt()
        session = presenter._workspace_state.session_for(slot_id)
        owners = session.studies

        _select_tool(ordinary, "Universal Trend Classifier")
        assert ordinary.source_selector.owner_count == 2
        ordinary.source_selector.select_owner("study", owners[0].study_id)
        ordinary.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        setup.complete(next(reversed(setup.pending)))
        _settle_qt()
        utc = session.studies[-1]

        edit_dialog, _row = _open_edit(panel, presenter, setup, utc.study_id)
        assert edit_dialog.source_selector.selected_owner_key == (
            "study",
            owners[0].study_id,
        )
        assert not edit_dialog.apply_edit_button.isEnabled()
        edit_dialog.source_selector.select_owner("study", owners[1].study_id)
        assert edit_dialog.apply_edit_button.isEnabled()
        edit_dialog.source_selector.select_owner("study", owners[0].study_id)
        assert not edit_dialog.apply_edit_button.isEnabled()

        edit_dialog.source_selector.select_owner("study", owners[1].study_id)
        before = len(studies.submissions)
        edit_dialog.apply_edit_button.click()
        assert len(studies.submissions) == before + 1
        owner_request = studies.submissions[-1][1]
        assert {source.study_id for source in owner_request.input_sources} == {
            owners[1].study_id
        }
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        if setup.pending:
            setup.complete(next(reversed(setup.pending)))
            _settle_qt()
        assert not edit_dialog.apply_edit_button.isEnabled()

        trend = edit_dialog.parameter_controls["trend_fractal_window"]
        trend.setCurrentIndex(trend.findData(7))
        assert edit_dialog.apply_edit_button.isEnabled()
        before = len(studies.submissions)
        edit_dialog.apply_edit_button.click()
        assert len(studies.submissions) == before + 1
        window_request = studies.submissions[-1][1]
        assert tuple(
            source.output_name for source in window_request.input_sources
        )[:2] == ("peak_fractal_7", "trough_fractal_7")
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()

        current_request = session.studies[-1].edit_request
        mixed_sources = list(current_request.input_sources)
        mixed_sources[-1] = StudyInputSource(
            "range_trough",
            "study",
            study_id=owners[0].study_id,
            output_name=mixed_sources[-1].output_name,
        )
        malformed = StudyExecutionRequest(
            current_request.tool_key,
            current_request.parameters,
            tuple(mixed_sources),
            display_name=current_request.display_name,
            user_metadata=current_request.user_metadata,
        )
        with pytest.raises(
            ValueError,
            match="one Peaks & Troughs owner",
        ):
            malformed_dialog = ResearchStudyEditDialog(
                session.dataset.market_id,
                edit_dialog._catalog,
                utc.study_id,
                malformed,
                session.study_presentations()[-1],
            )
    finally:
        if malformed_dialog is not None:
            malformed_dialog.close()
        presenter.dispose()
        window.close()


def test_combined_edit_applies_guides_only_after_successful_computation(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        ordinary = open_financial_tools(window, presenter, setup, slot_id)
        _apply_rsi(ordinary, studies, setup)
        session = presenter._workspace_state.session_for(slot_id)
        study = session.studies[0]
        edit_dialog, _row = _open_edit(
            panel, presenter, setup, study.study_id
        )
        edit_dialog.parameter_controls["period"].setValue(5)
        edit_dialog.guide_controls["oversold"].setValue(25.0)
        edit_dialog.apply_edit_button.click()
        assert (
            session.study_presentations()[0]
            .guide_styles["oversold"]
            .value
        ) == 30.0

        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        if setup.pending:
            _complete_latest_setup(setup)
        current = session.study_registry.get(study.study_id)
        assert current.result.parameters["period"] == 5
        assert (
            session.study_presentations()[0]
            .guide_styles["oversold"]
            .value
        ) == 25.0
    finally:
        presenter.dispose()
        window.close()


def test_failed_combined_edit_leaves_guide_state_unchanged(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        ordinary = open_financial_tools(window, presenter, setup, slot_id)
        _apply_rsi(ordinary, studies, setup)
        session = presenter._workspace_state.session_for(slot_id)
        study = session.studies[0]
        before = session.study_presentations()[0]
        edit_dialog, _row = _open_edit(
            panel, presenter, setup, study.study_id
        )
        edit_dialog.parameter_controls["period"].setValue(5)
        edit_dialog.guide_controls["oversold"].setValue(25.0)
        edit_dialog.apply_edit_button.click()
        studies.complete(
            next(reversed(studies.pending)),
            status="failed",
            error_message="failed",
        )
        _settle_qt()
        assert session.study_presentations()[0] == before
        assert edit_dialog.apply_edit_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_or_cancelled_edit_preserves_original_gui_and_session(
    tmp_path: Path, status: str
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_sma(dialog, studies, setup)
        session = presenter._workspace_state.session_for(slot_id)
        study = session.studies[0]
        before = (
            session.studies,
            session.study_registry.projection_snapshot(),
            session.study_presentations(),
        )
        edit_dialog, row = _open_edit(panel, presenter, setup, study.study_id)
        edit_dialog.parameter_controls["period"].setValue(5)
        edit_dialog.apply_edit_button.click()
        studies.complete(
            next(reversed(studies.pending)),
            status=status,
            error_message=status,
        )
        _settle_qt()
        assert (
            session.studies,
            session.study_registry.projection_snapshot(),
            session.study_presentations(),
        ) == before
        assert panel.price_overlay.study_rows[0] is row
        assert edit_dialog.apply_edit_button.text() == "Apply Edit"
        assert edit_dialog.parameter_controls["period"].value() == 5
        assert edit_dialog.apply_edit_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_saved_and_artifact_loaded_edit_clear_saved_state_and_block_dependents(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = saving_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_sma(dialog, studies, setup)
        session = presenter._workspace_state.session_for(slot_id)
        study = session.studies[0]
        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        assert manager.manager_widget.select_study(study.study_id)
        manager.manager_widget._save.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        _complete_latest_setup(setup)
        saved_link = session.studies[0].saved_link
        assert saved_link is not None
        artifact_count = len(
            studies._engine._artifacts.list_artifacts(session.dataset.market_id)
        )

        edit_dialog, _row = _open_edit(panel, presenter, setup, study.study_id)
        edit_dialog.parameter_controls["period"].setValue(5)
        edit_dialog.apply_edit_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert session.studies[0].saved_link is None
        assert len(
            studies._engine._artifacts.list_artifacts(session.dataset.market_id)
        ) == artifact_count

        apply_attempt = session.begin_study_apply()
        prepared = studies._engine.prepare_artifact(
            apply_attempt,
            session.dataset,
            StudyArtifactRequest(
                saved_link.kind,
                saved_link.tool_key,
                saved_link.artifact_id,
            ),
        )
        assert session.accept_study_apply(apply_attempt, prepared)
        presenter._chart_presenters[slot_id]._refresh_study_state()
        presenter._on_chart_state_changed(slot_id)
        if setup.pending:
            _complete_latest_setup(setup)
        loaded = session.studies[-1]
        assert loaded.source_kind == "artifact"
        artifact_dialog, _loaded_row = _open_edit(
            panel, presenter, setup, loaded.study_id
        )
        artifact_dialog.parameter_controls["period"].setValue(6)
        artifact_dialog.apply_edit_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert session.study_registry.get(loaded.study_id).source_kind == "calculation"
        assert session.study_registry.get(loaded.study_id).saved_link is None

        source = session.studies[0]
        dependent_attempt = session.begin_study_apply()
        dependent = studies._engine.prepare_calculation(
            dependent_attempt,
            session.dataset,
            session.studies,
            StudyExecutionRequest(
                "derivative",
                {"order": 1},
                (
                    StudyInputSource(
                        "source",
                        "study",
                        study_id=source.study_id,
                        output_name=source.analysis_usable_output_names[0],
                    ),
                ),
            ),
        )
        assert session.accept_study_apply(dependent_attempt, dependent)
        presenter._chart_presenters[slot_id]._refresh_study_state()
        presenter._on_chart_state_changed(slot_id)
        if setup.pending:
            _complete_latest_setup(setup)
        pending_before = tuple(setup.pending)
        source_row = next(
            item
            for item in panel.price_overlay.study_rows
            if item.study_id == source.study_id
        )
        source_row.edit_button.click()
        assert tuple(setup.pending) == pending_before
        assert (
            "cannot be edited while required by"
            in window._activity_log.toPlainText()
        )
    finally:
        presenter.dispose()
        window.close()
