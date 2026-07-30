from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
from leonardo.research import (
    AcceptedDatasetSummary,
    StudyArtifactOption,
    StudyExecutionRequest,
    StudySetupCatalog,
)
from tests.gui_test.test_research_gui_service_catalog import (
    _ControlledDatasetService,
    _settle_qt,
)
from tests.gui_test.test_research_gui_service_financial_tools import (
    ControlledStudyService,
    ControlledStudySetupService,
    build_catalog,
    open_financial_tools,
    open_ready_chart,
)
from tests.gui_test.test_research_gui_service_study_apply import _select_tool
from tests.research_test.test_study_execution import accepted_context


class ControlledSavingStudyService(ControlledStudyService):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.saved_options: list[StudyArtifactOption] = []

    def submit_save(
        self,
        attempt,
        dataset,
        study,
        studies,
        *,
        result_callback=None,
        callback_dispatcher=None,
        **_kwargs,
    ) -> TaskSubmission:
        return self._submit(
            "save",
            attempt,
            dataset,
            tuple(studies),
            study,
            result_callback,
            callback_dispatcher,
        )

    def complete(
        self,
        task_id: str,
        *,
        status: str = "completed",
        error_message: str | None = None,
        retain: bool = False,
    ) -> None:
        kind = self.pending[task_id][0]
        if kind != "save":
            super().complete(
                task_id,
                status=status,
                error_message=error_message,
                retain=retain,
            )
            return
        _kind, attempt, dataset, studies, study, callback, dispatcher = self.pending[
            task_id
        ]
        if not retain:
            self.pending.pop(task_id)
        value = None
        if status == "completed":
            value = self._engine.save_study(attempt, dataset, study, studies)
            self.saved_options.append(
                StudyArtifactOption(
                    dataset.market_id,
                    value.saved_link.artifact_id,
                    value.saved_link.kind,
                    value.saved_link.tool_key,
                    study.display_name,
                    study.result.output_names,
                    study.analysis_usable_output_names,
                    parameters=study.result.parameters,
                    source_bindings=(),
                )
            )
        result = TaskResult(
            task_id,
            status,
            value=value,
            error_message=error_message,
        )
        if dispatcher is None:
            callback(result)
        else:
            dispatcher(lambda: callback(result))


class ControlledSavingSetupService(ControlledStudySetupService):
    def __init__(self, saved_options: list[StudyArtifactOption]) -> None:
        super().__init__()
        self._saved_options = saved_options

    def complete(
        self,
        task_id: str,
        *,
        status: str = "completed",
        catalog: StudySetupCatalog | None = None,
        error_message: str | None = None,
        retain: bool = False,
    ) -> None:
        dataset, studies, callback, dispatcher = self.pending[task_id]
        if not retain:
            self.pending.pop(task_id)
        if catalog is None:
            base = build_catalog(dataset, studies)
            catalog = StudySetupCatalog(
                base.market_id,
                base.tools,
                base.ohlcv_sources,
                base.study_sources,
                (*base.artifact_options, *self._saved_options),
                base.artifact_rejections,
            )
        result = TaskResult(
            task_id,
            status,
            value=catalog if status == "completed" else None,
            error_message=error_message,
        )
        if dispatcher is None:
            callback(result)
        else:
            dispatcher(lambda: callback(result))


def saving_presenter(tmp_path: Path, tracker: Callable | None = None):
    dataset, _artifacts, _frame = accepted_context(tmp_path)
    summary = AcceptedDatasetSummary(
        dataset.market_id,
        dataset.csv_path,
        dataset.csv_path.with_name("candles.meta.json"),
        dataset.file_sha256,
        dataset.row_count,
        dataset.first_timestamp_ms,
        dataset.last_timestamp_ms,
        "task-1034b",
        "committed",
        "ok",
        (),
    )
    dataset_service = _ControlledDatasetService(dataset)
    studies = ControlledSavingStudyService(tmp_path)
    setup = ControlledSavingSetupService(studies.saved_options)
    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window,
        dataset_service,
        studies,
        tracker,
        study_setup_service=setup,
    )
    return window, presenter, dataset_service, studies, setup, summary


def _complete_latest_setup(setup: ControlledSavingSetupService) -> None:
    setup.complete(next(reversed(setup.pending)))
    _settle_qt()


def _ready_save_dialog(tmp_path: Path):
    values = saving_presenter(tmp_path)
    window, presenter, dataset_service, studies, setup, summary = values
    slot_id = open_ready_chart(window, presenter, dataset_service, summary)
    dialog = open_financial_tools(window, presenter, setup, slot_id)
    return (*values, slot_id, dialog)


def test_apply_is_transient_and_manager_save_persists_without_recalculation(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _datasets, studies, setup, _summary, slot_id, dialog = (
        _ready_save_dialog(tmp_path)
    )
    try:
        panel = window.workspace.chart_panel_for_slot(slot_id)
        session = presenter._workspace_state.session_for(slot_id)
        assert not hasattr(dialog, "save_artifact_button")
        _select_tool(dialog, "SMA")
        dialog.parameter_controls["period"].setValue(20)
        dialog.apply_button.click()
        _settle_qt()
        assert studies.submissions[-1][0] == "calculation"
        assert isinstance(studies.submissions[-1][1], StudyExecutionRequest)
        assert not panel.financial_tools_button.isEnabled()
        assert not panel.studies_button.isEnabled()
        assert panel.close_button.isEnabled()
        assert panel.position_combo.isEnabled()
        assert panel.detach_button.isEnabled()

        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert session.study_count == 1
        study = session.studies[0]
        assert study.saved_link is None
        assert studies.saved_options == []
        _complete_latest_setup(setup)
        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        assert manager.manager_widget.select_study(study.study_id)
        calculation_count = sum(
            kind == "calculation" for kind, _request in studies.submissions
        )
        manager.manager_widget._save.click()
        assert studies.submissions[-1][0] == "save"
        assert sum(
            kind == "calculation" for kind, _request in studies.submissions
        ) == calculation_count
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert len(setup.pending) == 1
        _complete_latest_setup(setup)
        assert session.studies[0].study_id == study.study_id
        assert session.studies[0].saved_link is not None
        artifact_id = session.studies[0].saved_link.artifact_id
        assert any(
            option.artifact_id == artifact_id
            for option in dialog._catalog.artifact_options
        )
        saved_row = next(
            row
            for row in range(dialog.saved_artifact_table.rowCount())
            if dialog.saved_artifact_table.item(row, 0).text()
            == study.display_name
        )
        assert tuple(
            dialog.saved_artifact_table.item(saved_row, column).text()
            for column in range(3)
        ) == (study.display_name, "period=20", "sma_20")
        assert manager.entries[0].saved
        assert not manager.manager_widget._save.isEnabled()
        assert presenter._financial_tools_dialogs[slot_id] is dialog
    finally:
        presenter.dispose()
        window.close()


def test_manager_save_failure_and_cancellation_preserve_unsaved_study(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, _datasets, studies, _setup, _summary, slot_id, dialog = (
        _ready_save_dialog(tmp_path)
    )
    try:
        _select_tool(dialog, "SMA")
        dialog.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        _complete_latest_setup(_setup)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        study = presenter._workspace_state.session_for(slot_id).studies[0]
        assert manager.manager_widget.select_study(study.study_id)

        manager.manager_widget._save.click()
        first = next(reversed(studies.pending))
        studies.complete(first, status="failed", error_message="save failed")
        _settle_qt()
        session = presenter._workspace_state.session_for(slot_id)
        assert session.study_count == 1
        assert session.studies[0].saved_link is None
        assert manager.manager_widget.isEnabled()

        manager.manager_widget._save.click()
        cancelled = next(reversed(studies.pending))
        studies.complete(cancelled, status="cancelled", error_message="cancelled")
        _settle_qt()
        assert session.studies[0].saved_link is None
        assert manager.manager_widget.isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_close_during_manager_save_cancels_and_rejects_late_result(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary, slot_id, dialog = (
        _ready_save_dialog(tmp_path)
    )
    try:
        _select_tool(dialog, "SMA")
        dialog.apply_button.click()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        _complete_latest_setup(setup)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        study_id = presenter._workspace_state.session_for(slot_id).studies[0].study_id
        assert manager.manager_widget.select_study(study_id)
        manager.manager_widget._save.click()
        persistence = next(reversed(studies.pending))
        panel.close_button.click()
        assert studies.cancel_counts[persistence] == 1
        studies.complete(persistence, status="cancelled", error_message="cancelled")
        _settle_qt()
        assert slot_id not in presenter._chart_presenters
        reused = open_ready_chart(window, presenter, datasets, summary)
        assert reused == slot_id
        assert presenter._workspace_state.session_for(reused).study_count == 0
    finally:
        presenter.dispose()
        window.close()
