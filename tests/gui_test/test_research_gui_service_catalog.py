from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.data import canonicalize_market_id
from leonardo.gui.research import (
    ResearchSuiteWindow,
    RestoredResearchLifecyclePresenter,
)
from leonardo.research import (
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    DatasetRejection,
    HistoricalDataset,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResidentSliceService,
)


class _ControlledDatasetService(ResearchDatasetApplicationService):
    def __init__(self, dataset: HistoricalDataset) -> None:
        self.dataset = dataset
        self.pending: dict[
            str, tuple[str, Callable[[TaskResult], None], object | None]
        ] = {}
        self.cancel_counts: dict[str, int] = {}
        self._sequence = 0

    def _submit(self, kind: str, callback, value) -> TaskSubmission:
        self._sequence += 1
        task_id = f"{kind}-{self._sequence}"
        self.pending[task_id] = (kind, callback, value)
        return TaskSubmission(task_id, kind)

    def submit_catalog(self, *, result_callback=None, **_kwargs) -> TaskSubmission:
        return self._submit("catalog", result_callback, None)

    def submit_load(self, _market_id, *, result_callback=None, **_kwargs) -> TaskSubmission:
        return self._submit("load", result_callback, self.dataset)

    def submit_resident_slice(
        self, dataset, center_index, *, result_callback=None, **_kwargs
    ) -> TaskSubmission:
        resident = ResidentSliceService().slice_around_index(dataset, center_index)
        return self._submit("resident", result_callback, resident)

    def complete(
        self,
        task_id: str,
        *,
        status: str = "completed",
        value: object | None = None,
        error_message: str | None = None,
    ) -> None:
        _kind, callback, stored = self.pending.pop(task_id)
        callback(
            TaskResult(
                task_id,
                status,
                value=stored if value is None and status == "completed" else value,
                error_message=error_message,
            )
        )

    def replay(
        self,
        task_id: str,
        *,
        status: str = "completed",
        value: object | None = None,
    ) -> None:
        _kind, callback, stored = self.pending[task_id]
        callback(
            TaskResult(
                task_id,
                status,
                value=stored if value is None and status == "completed" else value,
            )
        )

    def cancel(self, task_id: str) -> bool:
        self.cancel_counts[task_id] = self.cancel_counts.get(task_id, 0) + 1
        return task_id in self.pending

    def pending_ids(self, kind: str) -> tuple[str, ...]:
        return tuple(
            task_id
            for task_id, (pending_kind, _callback, _value) in self.pending.items()
            if pending_kind == kind
        )


class _ControlledStudyService(ResearchStudyApplicationService):
    def __init__(self) -> None:
        pass

    def cancel(self, _task_id: str) -> bool:
        return False


def _dataset_bundle() -> tuple[HistoricalDataset, AcceptedDatasetSummary]:
    market = canonicalize_market_id("bybit", "linear", "BTCUSD", "4h")
    timestamps = tuple(
        1_700_000_000_000 + index * 14_400_000
        for index in range(100)
    )
    values = tuple(float(100 + index) for index in range(100))
    dataset = HistoricalDataset(
        market_id=market,
        csv_path=Path("candles.csv"),
        file_sha256="a" * 64,
        row_count=100,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=values,
        high=tuple(value + 2.0 for value in values),
        low=tuple(value - 2.0 for value in values),
        close=tuple(value + 1.0 for value in values),
        volume=tuple(1_000.0 + index for index in range(100)),
    )
    summary = AcceptedDatasetSummary(
        market_id=market,
        csv_path=dataset.csv_path,
        sidecar_path=Path("candles.meta.json"),
        file_sha256=dataset.file_sha256,
        row_count=dataset.row_count,
        first_timestamp_ms=dataset.first_timestamp_ms,
        last_timestamp_ms=dataset.last_timestamp_ms,
        source="task-1033",
        persistence_status="committed",
        validation_status="ok",
        warnings=(),
    )
    return dataset, summary


def _presenter():
    dataset, summary = _dataset_bundle()
    service = _ControlledDatasetService(dataset)
    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window, service, _ControlledStudyService()
    )
    return window, presenter, service, summary


def _settle_qt() -> None:
    application = QApplication.instance()
    assert application is not None
    application.processEvents()


def _complete_catalog(
    service: _ControlledDatasetService,
    report: DatasetCatalogReport,
) -> None:
    service.complete(service.pending_ids("catalog")[0], value=report)
    _settle_qt()


def _select_complete_summary(presenter: RestoredResearchLifecyclePresenter) -> None:
    dialog = presenter._new_chart_dialog
    summary = dialog._dataset_summaries[0]
    market = summary.market_id
    dialog.exchange_combo.setCurrentIndex(dialog.exchange_combo.findData(market.exchange))
    dialog.market_type_combo.setCurrentIndex(
        dialog.market_type_combo.findData(market.market_type)
    )
    dialog.asset_combo.setCurrentIndex(dialog.asset_combo.findData(market.symbol))
    dialog.timeframe_combo.setCurrentIndex(
        dialog.timeframe_combo.findData(market.timeframe)
    )


def test_catalog_publishes_only_accepted_and_empty_state_is_honest() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        assert not window.action_for_text("New Chart...").isEnabled()
        rejection = DatasetRejection(
            Path("unknown"), "validation_unknown", "not accepted"
        )
        _complete_catalog(
            service, DatasetCatalogReport((summary,), (rejection,))
        )
        assert window.dataset_summaries == (summary,)
        assert window.action_for_text("New Chart...").isEnabled()
        assert all(
            item.validation_status == "ok" for item in window.dataset_summaries
        )

        presenter.dispose()
        window = ResearchSuiteWindow()
        service = _ControlledDatasetService(service.dataset)
        presenter = RestoredResearchLifecyclePresenter(
            window, service, _ControlledStudyService()
        )
        _complete_catalog(service, DatasetCatalogReport((), (rejection,)))
        assert window.action_for_text("New Chart...").isEnabled()
        presenter.open_new_chart()
        assert presenter._new_chart_dialog.info_label.text() == (
            "No accepted OHLCV datasets are available for Research."
        )
        assert not presenter._new_chart_dialog.create_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()


def test_catalog_failure_reuses_blank_dialog_and_creates_no_fixture_values() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, _summary = _presenter()
    try:
        catalog_id = service.pending_ids("catalog")[0]
        service.complete(catalog_id, status="failed", error_message="scan failed")
        _settle_qt()
        assert window.dataset_summaries == ()
        assert window.action_for_text("New Chart...").isEnabled()
        first = presenter._new_chart_dialog
        presenter.open_new_chart()
        first.reject()
        _settle_qt()
        presenter.open_new_chart()
        assert presenter._new_chart_dialog is first
        assert first.exchange_combo.currentData() == ""
        assert window.workspace.chart_count() == 0

        source = Path(
            "src/leonardo/gui/research/lifecycle_presenter.py"
        ).read_text(encoding="utf-8")
        launcher = Path(
            "tools/dev_launch_research_gui_service_wiring.py"
        ).read_text(encoding="utf-8")
        assert "research_gui_dev_fixtures" not in source
        assert "research_gui_dev_fixtures" not in launcher
        assert "dev_launch_research_gui_restoration" not in launcher
    finally:
        presenter.dispose()
        window.close()


def test_complete_selection_allows_duplicates_and_enforces_eight_charts() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        for expected_count in range(1, 9):
            presenter.open_new_chart()
            dialog = presenter._new_chart_dialog
            assert dialog.exchange_combo.currentData() == ""
            assert not dialog.create_button.isEnabled()
            _select_complete_summary(presenter)
            assert dialog.create_button.isEnabled()
            dialog.create_button.click()
            _settle_qt()
            assert window.workspace.chart_count() == expected_count
        presenter.open_new_chart()
        _select_complete_summary(presenter)
        presenter._new_chart_dialog.create_button.click()
        _settle_qt()
        assert window.workspace.slot_ids() == tuple(range(1, 9))
        assert presenter._workspace_state.chart_count == 8
        assert len(service.pending_ids("load")) == 8
    finally:
        presenter.dispose()
        window.close()
