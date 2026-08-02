from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from leonardo.artifacts import ArtifactService
from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
from leonardo.research import (
    DatasetCatalogReport,
    RESEARCH_FINANCIAL_TOOL_SPECS,
    ResearchStudyApplicationService,
    ResearchStudyService,
    ResearchStudySetupApplicationService,
    StudyArtifactOption,
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudySetupCatalog,
    StudySourceOption,
)
from tests.gui_test.test_research_gui_service_catalog import (
    _ControlledDatasetService,
    _dataset_bundle,
    _select_complete_summary,
    _settle_qt,
)


class ControlledStudySetupService(ResearchStudySetupApplicationService):
    def __init__(self) -> None:
        self.pending: dict[str, tuple[object, tuple, Callable, Callable | None]] = {}
        self.cancel_counts: dict[str, int] = {}
        self._sequence = 0

    def submit_catalog(
        self, dataset, studies, *, result_callback=None, callback_dispatcher=None, **_kwargs
    ) -> TaskSubmission:
        self._sequence += 1
        task_id = f"setup-{self._sequence}"
        self.pending[task_id] = (
            dataset,
            tuple(studies),
            result_callback,
            callback_dispatcher,
        )
        return TaskSubmission(task_id, "Research Study Setup catalog")

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
        value = build_catalog(dataset, studies) if catalog is None else catalog
        result = TaskResult(
            task_id,
            status,
            value=value if status == "completed" else None,
            error_message=error_message,
        )
        if dispatcher is None:
            callback(result)
        else:
            dispatcher(lambda: callback(result))

    def cancel(self, task_id: str) -> bool:
        self.cancel_counts[task_id] = self.cancel_counts.get(task_id, 0) + 1
        return task_id in self.pending


class ControlledStudyService(ResearchStudyApplicationService):
    def __init__(self, root: Path) -> None:
        self._engine = ResearchStudyService(ArtifactService(root))
        self.pending: dict[str, tuple[str, object, object, tuple, object, Callable, Callable | None]] = {}
        self.cancel_counts: dict[str, int] = {}
        self.submissions: list[tuple[str, object]] = []
        self._sequence = 0

    def submit_calculation(
        self,
        attempt,
        dataset,
        studies,
        request,
        *,
        result_callback=None,
        callback_dispatcher=None,
        **_kwargs,
    ) -> TaskSubmission:
        return self._submit(
            "calculation",
            attempt,
            dataset,
            tuple(studies),
            request,
            result_callback,
            callback_dispatcher,
        )

    def submit_artifact_apply(
        self,
        attempt,
        dataset,
        request,
        *,
        result_callback=None,
        callback_dispatcher=None,
        **_kwargs,
    ) -> TaskSubmission:
        return self._submit(
            "artifact",
            attempt,
            dataset,
            (),
            request,
            result_callback,
            callback_dispatcher,
        )

    def submit_edit(
        self,
        attempt,
        dataset,
        studies,
        request,
        *,
        result_callback=None,
        callback_dispatcher=None,
        **_kwargs,
    ) -> TaskSubmission:
        return self._submit(
            "edit",
            attempt,
            dataset,
            tuple(studies),
            request,
            result_callback,
            callback_dispatcher,
        )

    def _submit(
        self, kind, attempt, dataset, studies, request, callback, dispatcher
    ) -> TaskSubmission:
        self._sequence += 1
        task_id = f"study-{self._sequence}"
        self.pending[task_id] = (
            kind,
            attempt,
            dataset,
            studies,
            request,
            callback,
            dispatcher,
        )
        self.submissions.append((kind, request))
        return TaskSubmission(task_id, f"Research Study {kind}")

    def complete(
        self,
        task_id: str,
        *,
        status: str = "completed",
        error_message: str | None = None,
        retain: bool = False,
    ) -> None:
        kind, attempt, dataset, studies, request, callback, dispatcher = self.pending[
            task_id
        ]
        if not retain:
            self.pending.pop(task_id)
        value = None
        if status == "completed":
            if kind == "calculation":
                value = self._engine.prepare_calculation(
                    attempt, dataset, studies, request
                )
            elif kind == "edit":
                value = self._engine.prepare_edit(
                    attempt, dataset, studies, request
                )
            else:
                assert isinstance(request, StudyArtifactRequest)
                value = self._engine.prepare_calculation(
                    attempt,
                    dataset,
                    studies,
                    StudyExecutionRequest(request.tool_key, {}),
                )
        result = TaskResult(
            task_id, status, value=value, error_message=error_message
        )
        if dispatcher is None:
            callback(result)
        else:
            dispatcher(lambda: callback(result))

    def cancel(self, task_id: str) -> bool:
        self.cancel_counts[task_id] = self.cancel_counts.get(task_id, 0) + 1
        return task_id in self.pending


def build_catalog(dataset, studies=()) -> StudySetupCatalog:
    ohlcv = tuple(
        StudySourceOption("ohlcv", name.title(), "ohlc", column_name=name)
        for name in ("open", "high", "low", "close", "volume")
    )
    study_sources = tuple(
        StudySourceOption(
            "study",
            f"{study.display_name}: {output}",
            study.result.kind,
            study_id=study.study_id,
            output_name=output,
        )
        for study in studies
        for output in study.analysis_usable_output_names
    )
    artifacts = (
        StudyArtifactOption(
            dataset.market_id,
            "a" * 64,
            "indicator",
            "sma",
            "Saved SMA",
            ("sma_20",),
            parameters={"period": 20},
        ),
    )
    return StudySetupCatalog(
        dataset.market_id,
        RESEARCH_FINANCIAL_TOOL_SPECS,
        ohlcv,
        study_sources,
        artifacts,
    )


def real_presenter(tmp_path: Path, tracker=None, bundle=None):
    dataset, summary = _dataset_bundle() if bundle is None else bundle
    dataset_service = _ControlledDatasetService(dataset)
    study_service = ControlledStudyService(tmp_path)
    setup_service = ControlledStudySetupService()
    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window,
        dataset_service,
        study_service,
        tracker,
        study_setup_service=setup_service,
    )
    return window, presenter, dataset_service, study_service, setup_service, summary


def open_ready_chart(window, presenter, dataset_service, summary) -> int:
    catalog_ids = dataset_service.pending_ids("catalog")
    if catalog_ids:
        dataset_service.complete(
            catalog_ids[0], value=DatasetCatalogReport((summary,), ())
        )
        _settle_qt()
    presenter.open_new_chart()
    _select_complete_summary(presenter)
    presenter._new_chart_dialog.create_button.click()
    _settle_qt()
    slot_id = presenter._workspace_state.active_slot_id
    assert slot_id is not None
    dataset_service.complete(dataset_service.pending_ids("load")[-1])
    dataset_service.complete(dataset_service.pending_ids("resident")[-1])
    _settle_qt()
    assert window.workspace.chart_panel_for_slot(slot_id).status_text == "Chart ready"
    return slot_id


def open_financial_tools(window, presenter, setup_service, slot_id):
    panel = window.workspace.chart_panel_for_slot(slot_id)
    panel.financial_tools_button.click()
    task_id = next(reversed(setup_service.pending))
    setup_service.complete(task_id)
    _settle_qt()
    return presenter._financial_tools_dialogs[slot_id]


def test_real_catalog_availability_tracking_reuse_and_phase_gates(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    tracked: list[tuple[object, str, str, str, bool]] = []

    def tracker(widget, window_id, title, window_type):
        tracked.append((widget, window_id, title, window_type, widget.isVisible()))

    window, presenter, dataset_service, study, setup, summary = real_presenter(
        tmp_path, tracker
    )
    try:
        dataset_service.complete(
            dataset_service.pending_ids("catalog")[0],
            value=DatasetCatalogReport((summary,), ()),
        )
        _settle_qt()
        presenter.open_new_chart()
        _select_complete_summary(presenter)
        presenter._new_chart_dialog.create_button.click()
        _settle_qt()
        slot_id = presenter._workspace_state.active_slot_id
        assert slot_id == 1
        panel = window.workspace.chart_panel_for_slot(slot_id)
        assert not panel.financial_tools_button.isEnabled()
        assert not panel.studies_button.isEnabled()
        dataset_service.complete(dataset_service.pending_ids("load")[0])
        dataset_service.complete(dataset_service.pending_ids("resident")[0])
        _settle_qt()
        assert panel.financial_tools_button.isEnabled()
        assert panel.studies_button.isEnabled()

        dialog = open_financial_tools(window, presenter, setup, slot_id)
        assert dialog.tool_list.count() == 25
        assert all(
            dialog.tool_list.item(row).text() != "Dynamic Binning"
            for row in range(dialog.tool_list.count())
        )
        dialog.family_combo.setCurrentText("Construct")
        assert dialog.tool_list.count() == 8
        assert all(
            dialog.tool_list.item(row).text() != "Dynamic Binning"
            for row in range(dialog.tool_list.count())
        )
        dialog.family_combo.setCurrentText("All")
        assert not hasattr(dialog, "save_artifact_button")
        dialog.saved_artifact_table.item(0, 0).setCheckState(
            Qt.CheckState.Checked
        )
        for row in range(dialog.tool_list.count()):
            if dialog.tool_list.item(row).text() == "RSI":
                dialog.tool_list.setCurrentRow(row)
                break
        dialog.parameter_controls["period"].setValue(21)
        dialog.guide_controls["oversold"].setValue(24.0)
        assert tracked[-1] == (
            dialog,
            "research_restoration.financial_tools.1",
            "Financial Tools",
            "dialog",
            False,
        )
        panel.financial_tools_button.click()
        _settle_qt()
        assert presenter._financial_tools_dialogs[slot_id] is dialog
        assert dialog.tool_list.currentItem().text() == "RSI"
        assert dialog.parameter_controls["period"].value() == 21
        assert dialog.guide_controls["oversold"].value() == 24.0
        assert "a" * 64 in dialog._checked_artifact_ids
        assert setup._sequence == 1

        dialog.apply_button.click()
        study.complete(next(reversed(study.pending)))
        _settle_qt()
        setup.complete(next(reversed(setup.pending)))
        _settle_qt()
        assert presenter._financial_tools_dialogs[slot_id] is dialog
        assert dialog.tool_list.currentItem().text() == "RSI"
        assert dialog.parameter_controls["period"].value() == 21
        assert dialog.guide_controls["oversold"].value() == 24.0
        assert "a" * 64 in dialog._checked_artifact_ids
        assert "research_gui_dev_fixtures" not in Path(
            "src/leonardo/gui/research/lifecycle_presenter.py"
        ).read_text(encoding="utf-8")
    finally:
        presenter.dispose()
        window.close()


def test_chart_local_dialogs_are_isolated_and_survive_detach_dock(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, _study, setup, summary = real_presenter(tmp_path)
    try:
        first = open_ready_chart(window, presenter, dataset_service, summary)
        first_dialog = open_financial_tools(window, presenter, setup, first)
        presenter.open_new_chart()
        _select_complete_summary(presenter)
        presenter._new_chart_dialog.create_button.click()
        dataset_service.complete(dataset_service.pending_ids("load")[-1])
        dataset_service.complete(dataset_service.pending_ids("resident")[-1])
        _settle_qt()
        second = presenter._workspace_state.active_slot_id
        assert second == 2
        second_dialog = open_financial_tools(window, presenter, setup, second)
        assert first_dialog is not second_dialog
        assert first_dialog._market_id == second_dialog._market_id

        window.workspace.detach_chart(first)
        _settle_qt()
        assert presenter._financial_tools_dialogs[first] is first_dialog
        window.workspace.dock_chart(first)
        _settle_qt()
        assert presenter._financial_tools_dialogs[first] is first_dialog
    finally:
        presenter.dispose()
        window.close()


def test_catalog_failure_cancellation_and_stale_callbacks_are_slot_safe(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, dataset_service, _study, setup, summary = real_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, dataset_service, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        panel.financial_tools_button.click()
        task_id = next(reversed(setup.pending))
        panel.financial_tools_button.click()
        assert tuple(setup.pending) == (task_id,)
        setup.complete(task_id, status="failed", error_message="catalog failed")
        _settle_qt()
        assert window.workspace.slot_ids() == (slot_id,)
        assert panel.financial_tools_button.isEnabled()

        panel.financial_tools_button.click()
        old_task = next(reversed(setup.pending))
        setup.complete(old_task, retain=True)
        _settle_qt()
        old_dialog = presenter._financial_tools_dialogs[slot_id]
        panel.financial_tools_button.click()
        assert presenter._financial_tools_dialogs[slot_id] is old_dialog
        panel.close_button.click()
        assert slot_id not in presenter._financial_tools_dialogs

        reused = open_ready_chart(window, presenter, dataset_service, summary)
        assert reused == slot_id
        setup.complete(old_task)
        _settle_qt()
        assert reused not in presenter._financial_tools_dialogs

        new_panel = window.workspace.chart_panel_for_slot(reused)
        new_panel.financial_tools_button.click()
        close_task = next(reversed(setup.pending))
        new_panel.close_button.click()
        assert setup.cancel_counts[close_task] == 1

        last = open_ready_chart(window, presenter, dataset_service, summary)
        window.workspace.chart_panel_for_slot(last).financial_tools_button.click()
        dispose_task = next(reversed(setup.pending))
        presenter.dispose()
        assert setup.cancel_counts[dispose_task] == 1
    finally:
        presenter.dispose()
        window.close()
