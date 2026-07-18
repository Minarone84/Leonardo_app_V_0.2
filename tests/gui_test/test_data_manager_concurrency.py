from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerApplicationService,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
)
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


class _Controlled(DataManagerApplicationService):
    def __init__(self):
        self.calls = []
        self.inspected = []

    def submit_scan_catalog(self, **values):
        task_id = f"task-{len(self.calls) + 1}"
        self.calls.append((task_id, values["result_callback"]))
        return TaskSubmission(task_id, "scan")

    def submit_inspect_market(self, market_id, **values):
        self.inspected.append(market_id)
        task_id = f"task-{len(self.calls) + 1}"
        self.calls.append((task_id, values["result_callback"]))
        return TaskSubmission(task_id, "inspect")

    def cancel(self, task_id):
        return True


def test_latest_focus_wins_while_one_data_manager_operation_is_active() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    first = MarketId("bybit", "linear", "BTCUSDT", "1h")
    second = MarketId("bybit", "linear", "ETHUSDT", "15m")
    view = DataManagerSuiteWindow()
    service = _Controlled()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        presenter.focus_market(first, source="research")
        presenter.focus_market(second, source="research")
        assert len(service.calls) == 1
        assert presenter.pending_focus.market_id == second
        catalog = DataManagerCatalogSnapshot(
            (
                DataManagerDatasetEntry(first, True, 1, 0, 0),
                DataManagerDatasetEntry(second, True, 1, 0, 0),
            )
        )
        task_id, callback = service.calls[0]
        callback(TaskResult(task_id, "completed", catalog))
        assert presenter.pending_focus is None
        assert view.selected_market_id() == second
        assert len(service.calls) == 2
        assert service.calls[1][0] == "task-2"
        assert service.inspected == [second]
    finally:
        view.close()


def test_latest_same_market_focus_is_reinspected_after_current_read() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    catalog = DataManagerCatalogSnapshot(
        (DataManagerDatasetEntry(market, True, 1, 0, 0),)
    )
    view = DataManagerSuiteWindow()
    service = _Controlled()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan_id, scan_callback = service.calls[0]
        scan_callback(TaskResult(scan_id, "completed", catalog))
        presenter.focus_market(market, source="research")
        first_inspect_id, first_callback = service.calls[-1]
        presenter.focus_market(market, source="research")
        presenter.focus_market(market, source="research")
        assert presenter.pending_focus.market_id == market

        first_callback(
            TaskResult(
                first_inspect_id,
                "completed",
                DataManagerMarketSnapshot(market, catalog.datasets[0], (), ()),
            )
        )

        assert presenter.pending_focus is None
        assert service.inspected == [market, market]
        assert len(service.calls) == 3
    finally:
        view.close()


def test_latest_pending_focus_wins_after_current_market_becomes_unavailable() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    first = MarketId("bybit", "linear", "BTCUSDT", "1h")
    second = MarketId("bybit", "linear", "ETHUSDT", "15m")
    first_dataset = DataManagerDatasetEntry(first, True, 1, 0, 0)
    second_dataset = DataManagerDatasetEntry(second, True, 1, 0, 0)
    catalog = DataManagerCatalogSnapshot((first_dataset, second_dataset))
    view = DataManagerSuiteWindow()
    service = _Controlled()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan_id, scan_callback = service.calls[0]
        scan_callback(TaskResult(scan_id, "completed", catalog))
        presenter.focus_market(first, source="research")
        first_id, first_callback = service.calls[-1]
        presenter.focus_market(second, source="research")

        first_callback(
            TaskResult(
                first_id,
                "failed",
                error_type="DataManagerMarketUnavailableError",
                error_message=f"Dataset {first.as_key()} is unavailable: hash: changed",
            )
        )

        assert presenter.pending_focus is None
        assert presenter.selected_market_id == second
        assert view.selected_market_id() == second
        assert service.inspected == [first, second]
        second_id, second_callback = service.calls[-1]
        second_callback(
            TaskResult(
                second_id,
                "completed",
                DataManagerMarketSnapshot(second, second_dataset, (), ()),
            )
        )
        assert view.selected_market_id() == second
    finally:
        view.close()
