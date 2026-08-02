from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from leonardo.research import (
    StudyArtifactOption,
    StudyArtifactRequest,
    StudyExecutionRequest,
)
from tests.gui_test.test_research_gui_service_financial_tools import (
    build_catalog,
    open_financial_tools,
    open_ready_chart,
    real_presenter,
)
from tests.gui_test.test_research_gui_service_catalog import _settle_qt


def _select_tool(dialog, title: str) -> None:
    for row in range(dialog.tool_list.count()):
        if dialog.tool_list.item(row).text() == title:
            dialog.tool_list.setCurrentRow(row)
            return
    raise AssertionError(f"tool not found: {title}")


def _complete_catalog_refresh(setup) -> None:
    task_id = next(reversed(setup.pending))
    setup.complete(task_id)
    _settle_qt()


def _apply_tool(dialog, study_service, setup, title: str):
    _select_tool(dialog, title)
    dialog.apply_button.click()
    task_id = next(reversed(study_service.pending))
    study_service.complete(task_id)
    _settle_qt()
    _complete_catalog_refresh(setup)
    return task_id


def _three_artifact_catalog(dialog):
    options = tuple(
        StudyArtifactOption(
            dialog._catalog.market_id,
            character * 64,
            "indicator",
            "sma",
            f"Saved SMA {index}",
            (f"sma_{index}",),
            parameters={"period": index},
        )
        for character, index in (("a", 10), ("b", 20), ("c", 30))
    )
    return replace(dialog._catalog, artifact_options=options)


def test_calculation_and_saved_artifact_apply_use_canonical_service(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        session = presenter._workspace_state.session_for(slot_id)

        for expected, title, key in (
            (1, "SMA", "sma"),
            (2, "Bollinger Bands", "bb"),
            (3, "RSI", "rsi"),
        ):
            _select_tool(dialog, title)
            dialog.apply_button.click()
            kind, request = studies.submissions[-1]
            assert kind == "calculation"
            assert isinstance(request, StudyExecutionRequest)
            assert request.tool_key == key
            assert not dialog.apply_button.isEnabled()
            assert not dialog.apply_saved_artifact_button.isEnabled()
            assert not panel.financial_tools_button.isEnabled()
            assert panel.close_button.isEnabled()
            assert panel.position_combo.isEnabled()
            assert panel.detach_button.isEnabled()
            studies.complete(next(reversed(studies.pending)))
            _settle_qt()
            assert session.study_count == expected
            assert len({item.study_id for item in session.studies}) == expected
            if key == "rsi":
                presentation = session.study_presentations()[-1]
                assert {
                    guide_id: guide.value
                    for guide_id, guide in presentation.guide_styles.items()
                } == {
                    "overbought": 70.0,
                    "center": 50.0,
                    "oversold": 30.0,
                }
                assert presentation.revision == 0
            assert len(setup.pending) == 1
            _complete_catalog_refresh(setup)
            assert any(
                option.study_id == session.studies[-1].study_id
                for option in dialog._catalog.study_sources
            )
            assert panel.financial_tools_button.isEnabled()

        dialog.family_combo.setCurrentText("All")
        _select_tool(dialog, "SMA")
        saved = dialog.saved_artifact_table.item(0, 0)
        assert saved.data(Qt.ItemDataRole.UserRole).artifact_id == "a" * 64
        saved.setCheckState(Qt.CheckState.Checked)
        dialog.apply_saved_artifact_button.click()
        kind, request = studies.submissions[-1]
        assert kind == "artifact"
        assert isinstance(request, StudyArtifactRequest)
        assert request.artifact_id == "a" * 64
        assert not dialog.saved_artifact_table.isEnabled()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert session.study_count == 4
        _complete_catalog_refresh(setup)
        assert (
            dialog.saved_artifact_table.item(0, 0).checkState()
            == Qt.CheckState.Unchecked
        )
        assert not dialog.apply_saved_artifact_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_custom_rsi_creation_applies_guides_after_one_calculation(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        session = presenter._workspace_state.session_for(slot_id)
        _select_tool(dialog, "RSI")
        dialog.guide_controls["oversold"].setValue(25.0)
        submissions_before = len(studies.submissions)
        dialog.apply_button.click()
        assert len(studies.submissions) == submissions_before + 1
        kind, request = studies.submissions[-1]
        assert kind == "calculation"
        assert dict(request.parameters) == {"period": 14}
        task_id = next(reversed(studies.pending))
        studies.complete(task_id)
        _settle_qt()

        assert len(studies.submissions) == submissions_before + 1
        assert session.study_count == 1
        study = session.studies[0]
        presentation = session.study_presentations()[0]
        assert study.edit_request == request
        assert dict(study.result.parameters) == {"period": 14}
        assert {
            guide_id: guide.value
            for guide_id, guide in presentation.guide_styles.items()
        } == {
            "overbought": 70.0,
            "center": 50.0,
            "oversold": 25.0,
        }
        assert presentation.revision == 1
        oscillator = panel.chart_workspace.oscillator_widget(study.study_id)
        assert oscillator is not None
        assert ("oversold", 25.0) in tuple(
            (guide.kind, guide.value)
            for guide in oscillator.scene_plan.guides
        )
        _complete_catalog_refresh(setup)
    finally:
        presenter.dispose()
        window.close()


def test_checked_saved_artifacts_apply_sequentially_in_visible_order(
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
        for row in range(3):
            dialog.saved_artifact_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
            )
        dialog.apply_saved_artifact_button.click()
        assert tuple(studies.pending) == ("study-1",)
        maximum_pending = len(studies.pending)
        expected_ids = ("a" * 64, "b" * 64, "c" * 64)
        for expected_count in range(1, 4):
            task_id = next(iter(studies.pending))
            studies.complete(task_id)
            _settle_qt()
            maximum_pending = max(maximum_pending, len(studies.pending))
            assert (
                presenter._workspace_state.session_for(slot_id).study_count
                == expected_count
            )
            if expected_count < 3:
                assert len(studies.pending) == 1
        assert maximum_pending == 1
        assert tuple(
            request.artifact_id
            for kind, request in studies.submissions
            if kind == "artifact"
        ) == expected_ids
        assert all(
            dialog.saved_artifact_table.item(row, 0).checkState()
            == Qt.CheckState.Unchecked
            for row in range(3)
        )
        setup.complete(
            next(reversed(setup.pending)),
            catalog=_three_artifact_catalog(dialog),
        )
        _settle_qt()
        assert dialog.status_label.text() == "Applied 3 saved Artifacts."
    finally:
        presenter.dispose()
        window.close()


def test_checked_saved_artifact_failure_stops_batch_and_retains_checks(
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
        for row in range(3):
            dialog.saved_artifact_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
            )
        dialog.apply_saved_artifact_button.click()
        studies.complete(next(iter(studies.pending)))
        _settle_qt()
        studies.complete(
            next(iter(studies.pending)),
            status="failed",
            error_message="artifact failed",
        )
        _settle_qt()
        assert tuple(
            request.artifact_id
            for kind, request in studies.submissions
            if kind == "artifact"
        ) == ("a" * 64, "b" * 64)
        assert tuple(
            dialog.saved_artifact_table.item(row, 0).checkState()
            for row in range(3)
        ) == (
            Qt.CheckState.Unchecked,
            Qt.CheckState.Checked,
            Qt.CheckState.Checked,
        )
        setup.complete(
            next(reversed(setup.pending)),
            catalog=_three_artifact_catalog(dialog),
        )
        _settle_qt()
        assert dialog.apply_saved_artifact_button.isEnabled()
        assert (
            presenter._workspace_state.session_for(slot_id).study_count == 1
        )
        assert dialog.status_label.text().startswith(
            "Saved Artifact batch stopped at 2 of 3:"
        )
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize(
    ("title", "guide_id", "guide_value"),
    (
        ("ARSI", "oversold", 15.0),
        ("MFI", "oversold", 25.0),
        ("TDI RSI", "oversold", 25.0),
        ("SMI", "zero", -5.0),
    ),
)
def test_other_oscillator_creation_guides_remain_presentation_only(
    tmp_path: Path,
    title: str,
    guide_id: str,
    guide_value: float,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _select_tool(dialog, title)
        dialog.guide_controls[guide_id].setValue(guide_value)
        dialog.apply_button.click()
        assert len(studies.submissions) == 1
        request = studies.submissions[0][1]
        assert guide_id not in request.parameters
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        session = presenter._workspace_state.session_for(slot_id)
        assert session.study_count == 1
        assert (
            session.study_presentations()[0]
            .guide_styles[guide_id]
            .value
            == guide_value
        )
        assert len(studies.submissions) == 1
        _complete_catalog_refresh(setup)
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize("title", ("SMA", "Hancock"))
def test_non_guide_creation_does_not_apply_presentation_guides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    title: str,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        chart_presenter = presenter._chart_presenters[slot_id]
        calls: list[object] = []
        monkeypatch.setattr(
            chart_presenter,
            "apply_guide_values",
            lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
        )
        _select_tool(dialog, title)
        assert dialog.guide_controls == {}
        dialog.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert presenter._workspace_state.session_for(slot_id).study_count == 1
        assert calls == []
        assert len(studies.submissions) == 1
        _complete_catalog_refresh(setup)
    finally:
        presenter.dispose()
        window.close()


def test_utc_apply_uses_one_current_peaks_owner_and_four_injected_roles(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(dialog, studies, setup, "Peaks & Troughs")
        session = presenter._workspace_state.session_for(slot_id)
        owner = session.studies[0]

        _select_tool(dialog, "Universal Trend Classifier")
        assert dialog.source_selector.selected_owner_key == (
            "study",
            owner.study_id,
        )
        dialog.parameter_controls["trend_fractal_window"].setCurrentIndex(
            dialog.parameter_controls["trend_fractal_window"].findData(7)
        )
        dialog.parameter_controls["range_fractal_window"].setCurrentIndex(
            dialog.parameter_controls["range_fractal_window"].findData(5)
        )
        submissions_before = len(studies.submissions)
        dialog.apply_button.click()
        assert len(studies.submissions) == submissions_before + 1
        kind, request = studies.submissions[-1]
        assert kind == "calculation"
        assert tuple(source.role for source in request.input_sources) == (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
        assert tuple(source.output_name for source in request.input_sources) == (
            "peak_fractal_7",
            "trough_fractal_7",
            "peak_fractal_5",
            "trough_fractal_5",
        )
        assert {source.study_id for source in request.input_sources} == {
            owner.study_id
        }
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert session.studies[-1].result.tool_key == (
            "universal_trend_classifier"
        )
        _complete_catalog_refresh(setup)
    finally:
        presenter.dispose()
        window.close()


def test_utc_saved_peaks_artifact_owner_applies_and_multiple_owners_require_choice(
    tmp_path: Path,
) -> None:
    from tests.gui_test.test_research_gui_service_study_save import (
        saving_presenter,
    )

    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = saving_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _apply_tool(dialog, studies, setup, "Peaks & Troughs")
        session = presenter._workspace_state.session_for(slot_id)
        current_owner = session.studies[0]
        saved = studies._engine._artifacts.save_calculation(
            session.dataset.market_id,
            current_owner.result,
            display_name="Saved Peaks & Troughs",
        )
        artifact = StudyArtifactOption(
            session.dataset.market_id,
            saved.metadata.artifact_id,
            "indicator",
            "peaks_troughs",
            "Saved Peaks & Troughs",
            current_owner.result.output_names,
            current_owner.analysis_usable_output_names,
        )
        catalog = build_catalog(session.dataset, session.studies)
        catalog = type(catalog)(
            catalog.market_id,
            catalog.tools,
            catalog.ohlcv_sources,
            catalog.study_sources,
            (*catalog.artifact_options, artifact),
            catalog.artifact_rejections,
        )
        presenter._request_study_catalog_refresh(
            slot_id, presenter._chart_presenters[slot_id]
        )
        setup.complete(next(reversed(setup.pending)), catalog=catalog)
        _settle_qt()

        _select_tool(dialog, "Universal Trend Classifier")
        assert dialog.source_selector.owner_count == 2
        assert dialog.source_selector.selected_owner_key is None
        assert not dialog.apply_button.isEnabled()
        dialog.source_selector.select_owner(
            "artifact", saved.metadata.artifact_id
        )
        assert dialog.apply_button.isEnabled()
        dialog.apply_button.click()
        request = studies.submissions[-1][1]
        assert {source.artifact_id for source in request.input_sources} == {
            saved.metadata.artifact_id
        }
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert session.studies[-1].result.tool_key == (
            "universal_trend_classifier"
        )
    finally:
        presenter.dispose()
        window.close()


def test_apply_failure_cancellation_and_submission_failure_restore_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _select_tool(dialog, "RSI")
        dialog.guide_controls["oversold"].setValue(25.0)

        dialog.apply_button.click()
        failed = next(reversed(studies.pending))
        studies.complete(failed, status="failed", error_message="calculation failed")
        _settle_qt()
        assert presenter._workspace_state.session_for(slot_id).study_count == 0
        assert dialog.apply_button.isEnabled()
        assert presenter._workspace_state.session_for(slot_id).study_count == 0
        assert panel.financial_tools_button.isEnabled()

        dialog.apply_button.click()
        cancelled = next(reversed(studies.pending))
        studies.complete(cancelled, status="cancelled", error_message="cancelled")
        _settle_qt()
        assert dialog.apply_button.isEnabled()
        assert "Study Apply cancelled" in window._activity_log.toPlainText()

        def reject_submission(*_args, **_kwargs):
            raise RuntimeError("submission rejected")

        monkeypatch.setattr(studies, "submit_calculation", reject_submission)
        dialog.apply_button.click()
        _settle_qt()
        assert dialog.apply_button.isEnabled()
        assert "submission failed" in window._activity_log.toPlainText()
        assert window.workspace.slot_ids() == (slot_id,)
    finally:
        presenter.dispose()
        window.close()


def test_close_during_apply_cancels_and_late_result_cannot_reach_reused_slot(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, studies, setup, summary = real_presenter(
        tmp_path
    )
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        dialog = open_financial_tools(window, presenter, setup, slot_id)
        _select_tool(dialog, "RSI")
        dialog.guide_controls["oversold"].setValue(25.0)
        dialog.apply_button.click()
        old_task = next(reversed(studies.pending))
        old_session = presenter._workspace_state.session_for(slot_id)
        window.workspace.chart_panel_for_slot(slot_id).close_button.click()
        assert studies.cancel_counts[old_task] == 1
        assert old_session.is_disposed

        reused = open_ready_chart(window, presenter, dataset_service, summary)
        new_session = presenter._workspace_state.session_for(reused)
        assert reused == slot_id
        studies.complete(old_task)
        _settle_qt()
        assert new_session.study_count == 0
        assert reused not in presenter._financial_tools_dialogs

        second_dialog = open_financial_tools(window, presenter, setup, reused)
        _select_tool(second_dialog, "RSI")
        second_dialog.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert new_session.study_count == 1
        _complete_catalog_refresh(setup)
    finally:
        presenter.dispose()
        window.close()
