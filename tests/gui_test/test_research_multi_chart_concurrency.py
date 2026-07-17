from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.research import (
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResearchStudyService,
    ResidentSliceService,
    StudyExecutionRequest,
)
from leonardo.gui.presenters.research_presenter import ResearchSuitePresenter
from leonardo.gui.windows.research_suite_window import ResearchSuiteWindow
from tests.research_test.test_study_execution import accepted_context


class _ControlledDatasetService(ResearchDatasetApplicationService):
    def __init__(self, dataset) -> None:
        self.dataset = dataset
        self.pending: dict[str, tuple[str, Callable[[TaskResult], None], object]] = {}
        self.cancel_counts: dict[str, int] = {}
        self._sequence = 0

    def _submission(self, kind: str, callback, value: object) -> TaskSubmission:
        self._sequence += 1
        task_id = f"{kind}-{self._sequence}"
        self.pending[task_id] = (kind, callback, value)
        return TaskSubmission(task_id, kind)

    def submit_catalog(self, *, result_callback=None, **_kwargs) -> TaskSubmission:
        return self._submission("catalog", result_callback, _catalog_report(self.dataset))

    def submit_load(self, _market_id, *, result_callback=None, **_kwargs) -> TaskSubmission:
        return self._submission("load", result_callback, self.dataset)

    def submit_resident_slice(
        self, dataset, center_index, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        resident = ResidentSliceService().slice_around_index(
            dataset,
            center_index,
            visible_max=40,
            buffer_left=10,
            buffer_right=10,
        )
        return self._submission("resident", result_callback, resident)

    def complete(self, task_id: str) -> None:
        _kind, callback, value = self.pending.pop(task_id)
        callback(TaskResult(task_id, "completed", value=value))

    def cancel(self, task_id: str) -> bool:
        self.cancel_counts[task_id] = self.cancel_counts.get(task_id, 0) + 1
        return task_id in self.pending

    def pending_ids(self, kind: str) -> tuple[str, ...]:
        return tuple(
            task_id
            for task_id, (current_kind, _callback, _value) in self.pending.items()
            if current_kind == kind
        )


class _ControlledStudyService(ResearchStudyApplicationService):
    def __init__(self, domain: ResearchStudyService) -> None:
        self.domain = domain
        self.pending: dict[str, tuple[Callable[[TaskResult], None], object]] = {}
        self.cancel_counts: dict[str, int] = {}
        self._sequence = 0

    def submit_calculation(
        self,
        attempt,
        dataset,
        studies,
        request,
        *,
        result_callback=None,
        **_kwargs,
    ) -> TaskSubmission:
        self._sequence += 1
        task_id = f"study-{self._sequence}"
        prepared = self.domain.prepare_calculation(
            attempt, dataset, studies, request
        )
        self.pending[task_id] = (result_callback, prepared)
        return TaskSubmission(task_id, "study")

    def complete(self, task_id: str) -> None:
        callback, value = self.pending.pop(task_id)
        callback(TaskResult(task_id, "completed", value=value))

    def cancel(self, task_id: str) -> bool:
        self.cancel_counts[task_id] = self.cancel_counts.get(task_id, 0) + 1
        return task_id in self.pending


def _catalog_report(dataset) -> DatasetCatalogReport:
    return DatasetCatalogReport(
        accepted=(
            AcceptedDatasetSummary(
                market_id=dataset.market_id,
                csv_path=dataset.csv_path,
                sidecar_path=dataset.csv_path.with_suffix(".json"),
                file_sha256=dataset.file_sha256,
                row_count=dataset.row_count,
                first_timestamp_ms=dataset.first_timestamp_ms,
                last_timestamp_ms=dataset.last_timestamp_ms,
                source="task-1019",
                persistence_status="committed",
                validation_status="ok",
                warnings=(),
            ),
        ),
        rejected=(),
    )


def _controlled_suite(tmp_path: Path):
    dataset, artifacts, _frame = accepted_context(tmp_path)
    data = _ControlledDatasetService(dataset)
    studies = _ControlledStudyService(ResearchStudyService(artifacts))
    window = ResearchSuiteWindow()
    presenter = ResearchSuitePresenter(window, data, studies)
    catalog_id = data.pending_ids("catalog")[0]
    data.complete(catalog_id)
    return window, presenter, data, studies


def _open_pending(presenter: ResearchSuitePresenter, data: _ControlledDatasetService):
    before = set(presenter.slot_ids())
    presenter.open_selected_dataset()
    slot_id = next(iter(set(presenter.slot_ids()) - before))
    task_id = data.pending_ids("load")[-1]
    return slot_id, task_id


def test_chart_operations_are_concurrent_isolated_and_stale_safe(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, data, studies = _controlled_suite(tmp_path)
    try:
        slot_1, load_1 = _open_pending(presenter, data)
        slot_2, load_2 = _open_pending(presenter, data)
        assert (slot_1, slot_2) == (1, 2)
        assert set(data.pending_ids("load")) == {load_1, load_2}

        data.complete(load_1)
        resident_1 = data.pending_ids("resident")[0]
        slot_3, load_3 = _open_pending(presenter, data)
        study_1 = presenter.submit_study_calculation(
            StudyExecutionRequest("sma", {"period": 3}), slot_id=1
        ).task_id
        assert load_3 in data.pending_ids("load")
        assert study_1 in studies.pending

        data.complete(load_2)
        resident_ids = data.pending_ids("resident")
        assert resident_1 in resident_ids
        assert len(resident_ids) == 2
        resident_2 = next(task_id for task_id in resident_ids if task_id != resident_1)

        presenter.set_active_slot(1)
        presenter.cancel_active_operation()
        assert data.cancel_counts[resident_1] == 1
        assert studies.cancel_counts[study_1] == 1
        assert resident_2 not in data.cancel_counts
        assert load_3 not in data.cancel_counts

        session_2 = presenter.session_for(2)
        presenter.close_active_chart()
        assert presenter.slot_ids() == (2, 3)
        assert presenter.session_for(2) is session_2
        data.complete(resident_1)
        studies.complete(study_1)

        reused, reused_load = _open_pending(presenter, data)
        assert reused == 1
        assert presenter.session_for(1).study_count == 0
        assert presenter.session_for(2) is session_2

        data.complete(resident_2)
        assert presenter.session_for(2).resident is not None
        presenter.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 3}), slot_id=2
        )
        study_2 = next(iter(studies.pending))
        presenter.set_active_slot(3)
        studies.complete(study_2)
        assert presenter.session_for(2).study_count == 1
        assert presenter.session_for(3).study_count == 0
        assert window.study_manager.entries == ()

        assert reused_load in data.pending_ids("load")
        assert load_3 in data.pending_ids("load")
    finally:
        presenter.dispose()
        window.close()


def test_suite_disposal_cancels_each_chart_task_once(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, data, studies = _controlled_suite(tmp_path)
    _slot_1, load_1 = _open_pending(presenter, data)
    _slot_2, load_2 = _open_pending(presenter, data)

    presenter.dispose()
    presenter.dispose()

    assert data.cancel_counts == {load_1: 1, load_2: 1}
    assert studies.cancel_counts == {}
    assert presenter.is_disposed is True
    assert presenter.slot_ids() == ()
    window.close()
