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
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
    DataManagerRecipeEntry,
)
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
DATASET = DataManagerDatasetEntry(MARKET, True, 1, 0, 0)
CATALOG = DataManagerCatalogSnapshot((DATASET,))
MARKET_SNAPSHOT = DataManagerMarketSnapshot(MARKET, DATASET, (), ())


def _populated_snapshot(artifact_id="a" * 64, recipe_id="r" * 64):
    recipe = DataManagerRecipeEntry(
        MARKET, recipe_id, "rsi", "oscillator", ("rsi",), "RSI", None
    )
    artifact = DataManagerArtifactEntry(
        MARKET,
        artifact_id,
        recipe_id,
        "rsi",
        "oscillator",
        ("rsi",),
        1,
        0,
        0,
        None,
    )
    return DataManagerMarketSnapshot(MARKET, DATASET, (recipe,), (artifact,))


def _recipe_only_snapshot(recipe_id="r" * 64):
    recipe = DataManagerRecipeEntry(
        MARKET, recipe_id, "rsi", "oscillator", ("rsi",), "RSI", None
    )
    return DataManagerMarketSnapshot(MARKET, DATASET, (recipe,), ())


class _ControlledApplication(DataManagerApplicationService):
    def __init__(self):
        self.calls = []
        self.cancelled = []
        self._counter = 0

    def _submit(self, operation, result_callback):
        self._counter += 1
        task_id = f"task-{self._counter}"
        self.calls.append((operation, task_id, result_callback))
        return TaskSubmission(task_id, operation)

    def submit_scan_catalog(self, **values):
        return self._submit("scan", values["result_callback"])

    def submit_inspect_market(self, market_id, **values):
        return self._submit(("inspect", market_id), values["result_callback"])

    def submit_preview_dataset(self, market_id, **values):
        return self._submit(("preview_dataset", market_id), values["result_callback"])

    def submit_preview_artifact(
        self, market_id, kind, tool_key, artifact_id, **values
    ):
        return self._submit(
            ("preview_artifact", market_id, kind, tool_key, artifact_id),
            values["result_callback"],
        )

    def submit_validate_artifact(
        self, market_id, kind, tool_key, artifact_id, **values
    ):
        return self._submit(
            ("validate_artifact", market_id, kind, tool_key, artifact_id),
            values["result_callback"],
        )

    def submit_delete_artifact(self, market_id, kind, tool_key, artifact_id, **values):
        return self._submit(
            ("delete_artifact", market_id, kind, tool_key, artifact_id),
            values["result_callback"],
        )

    def submit_delete_recipe(self, market_id, kind, tool_key, recipe_id, **values):
        return self._submit(
            ("delete_recipe", market_id, kind, tool_key, recipe_id),
            values["result_callback"],
        )

    def cancel(self, task_id):
        self.cancelled.append(task_id)
        return True


def test_presenter_scans_focuses_exact_market_and_ignores_stale_result() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        presenter.focus_market(MARKET, source="research")
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        inspect = service.calls[1]
        assert inspect[0] == ("inspect", MARKET)
        inspect[2](TaskResult("foreign", "completed", MARKET_SNAPSHOT))
        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 0
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        assert presenter.selected_market_id == MARKET
        assert view.selected_market_id() == MARKET
    finally:
        view.close()


def test_dispose_cancels_one_active_task_and_is_idempotent() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    presenter.dispose()
    presenter.dispose()
    assert service.cancelled == ["task-1"]


def test_same_market_focus_reinspects_once_and_reloads_persisted_objects() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        first = service.calls[-1]
        first[2](TaskResult(first[1], "completed", MARKET_SNAPSHOT))
        before = len(service.calls)

        presenter.focus_market(MARKET, source="research")
        view.market_selected.emit(MARKET)

        assert len(service.calls) == before + 1
        inspect = service.calls[-1]
        assert inspect[0] == ("inspect", MARKET)
        inspect[2](TaskResult(inspect[1], "completed", _populated_snapshot()))
        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 1
        assert view.table_for_id("data_manager.table.recipes").rowCount() == 1
    finally:
        view.close()


@pytest.mark.parametrize("include_rejection", (True, False))
def test_unavailable_focus_clears_prior_market_objects_and_actions(
    include_rejection,
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    unavailable = MarketId("bybit", "linear", "ETHUSDT", "1h")
    rejected_entry = DataManagerDatasetEntry(
        unavailable,
        False,
        rejection_code="hash",
        rejection_reason="source changed",
    )
    catalog = DataManagerCatalogSnapshot(
        (DATASET, rejected_entry) if include_rejection else (DATASET,)
    )
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", catalog))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", _populated_snapshot()))
        view.table_for_id("data_manager.table.artifacts").selectRow(0)
        view.table_for_id("data_manager.table.recipes").selectRow(0)

        presenter.focus_market(unavailable, source="research")

        assert presenter.selected_market_id is None
        assert view.selected_market_id() is None
        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 0
        assert view.table_for_id("data_manager.table.recipes").rowCount() == 0
        expected = (
            "hash: source changed"
            if include_rejection
            else "missing from canonical persistence"
        )
        assert expected in view.status_text()
        assert not view.button_for_id("data_manager.button.delete_artifact").isEnabled()
        assert not view.button_for_id("data_manager.button.delete_recipe").isEnabled()
    finally:
        view.close()


def test_committed_artifact_delete_survives_refresh_failure() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", _populated_snapshot()))
        view.table_for_id("data_manager.table.artifacts").selectRow(0)

        view.delete_artifact_requested.emit()
        deletion = service.calls[-1]
        assert deletion[0][0] == "delete_artifact"
        deletion[2](
            TaskResult(
                deletion[1],
                "completed",
                DataManagerDeletionResult(
                    MARKET, "artifact", "oscillator", "rsi", "a" * 64
                ),
            )
        )
        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 0
        assert view.status_text() == "Deletion completed; refreshing catalog"
        refresh = service.calls[-1]
        assert refresh[0] == ("inspect", MARKET)
        refresh[2](TaskResult(refresh[1], "failed", error_message="disk unavailable"))

        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 0
        assert view.status_text() == (
            "Deletion completed; catalog refresh failed: disk unavailable"
        )
        assert sum(call[0][0] == "delete_artifact" for call in service.calls) == 1

        presenter.refresh()
        manual_scan = service.calls[-1]
        manual_scan[2](TaskResult(manual_scan[1], "completed", CATALOG))
        manual_inspect = service.calls[-1]
        manual_inspect[2](
            TaskResult(manual_inspect[1], "completed", MARKET_SNAPSHOT)
        )
        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 0
        assert sum(call[0][0] == "delete_artifact" for call in service.calls) == 1
    finally:
        view.close()


def test_stale_deletion_result_cannot_clear_newer_identity() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    newer = _populated_snapshot(artifact_id="b" * 64)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", newer))
        view.table_for_id("data_manager.table.artifacts").selectRow(0)

        presenter._settle_deletion(
            TaskResult(
                "stale",
                "completed",
                DataManagerDeletionResult(
                    MARKET, "artifact", "oscillator", "rsi", "a" * 64
                ),
            ),
            (MARKET, "oscillator", "rsi", "a" * 64),
            "artifact",
        )

        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 1
        assert view.selected_artifact().artifact_id == "b" * 64
    finally:
        view.close()


def test_committed_recipe_delete_filters_exact_row_before_refresh() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", _recipe_only_snapshot()))
        view.table_for_id("data_manager.table.recipes").selectRow(0)

        view.delete_recipe_requested.emit()
        deletion = service.calls[-1]
        deletion[2](
            TaskResult(
                deletion[1],
                "completed",
                DataManagerDeletionResult(
                    MARKET, "recipe", "oscillator", "rsi", "r" * 64
                ),
            )
        )

        assert view.table_for_id("data_manager.table.recipes").rowCount() == 0
        assert view.status_text() == "Deletion completed; refreshing catalog"
        assert sum(call[0][0] == "delete_recipe" for call in service.calls) == 1
        refresh = service.calls[-1]
        refresh[2](TaskResult(refresh[1], "completed", MARKET_SNAPSHOT))
        assert view.status_text() == "Deletion completed; catalog refreshed"
    finally:
        view.close()


@pytest.mark.parametrize(
    "operation",
    (
        "preview_dataset",
        "preview_artifact",
        "validate_artifact",
        "delete_artifact",
        "delete_recipe",
    ),
)
def test_market_unavailable_operation_clears_stale_actions(operation) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", _populated_snapshot()))
        if operation == "delete_recipe":
            view.table_for_id("data_manager.table.recipes").selectRow(0)
        elif operation != "preview_dataset":
            view.table_for_id("data_manager.table.artifacts").selectRow(0)

        getattr(view, f"{operation}_requested").emit()
        call = service.calls[-1]
        message = f"Dataset {MARKET.as_key()} is unavailable: hash: changed"
        call[2](
            TaskResult(
                call[1],
                "failed",
                error_type="DataManagerMarketUnavailableError",
                error_message=message,
            )
        )

        assert presenter.selected_market_id is None
        assert view.selected_market_id() is None
        assert view.table_for_id("data_manager.table.artifacts").rowCount() == 0
        assert view.table_for_id("data_manager.table.recipes").rowCount() == 0
        assert view.status_text() == message
        assert not view.button_for_id("data_manager.button.preview_dataset").isEnabled()
        assert not view.button_for_id("data_manager.button.delete_artifact").isEnabled()
        assert not view.button_for_id("data_manager.button.delete_recipe").isEnabled()
    finally:
        view.close()


def test_stale_cached_focus_clears_when_fresh_inspection_is_unavailable() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        message = f"Dataset {MARKET.as_key()} is unavailable: hash: changed"
        inspect[2](
            TaskResult(
                inspect[1],
                "failed",
                error_type="DataManagerMarketUnavailableError",
                error_message=message,
            )
        )
        assert presenter.selected_market_id is None
        assert view.selected_market_id() is None
        assert view.status_text() == message
    finally:
        view.close()


def test_ordinary_preview_failure_preserves_current_selection() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", _populated_snapshot()))
        view.table_for_id("data_manager.table.artifacts").selectRow(0)

        view.preview_artifact_requested.emit()
        preview = service.calls[-1]
        preview[2](
            TaskResult(
                preview[1],
                "failed",
                error_type="OSError",
                error_message="ordinary preview failure",
            )
        )

        assert presenter.selected_market_id == MARKET
        assert view.selected_market_id() == MARKET
        assert view.selected_artifact().artifact_id == "a" * 64
        assert view.button_for_id("data_manager.button.delete_artifact").isEnabled()
    finally:
        view.close()


def test_ordinary_lineage_validation_preserves_selected_market_and_artifact() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", _populated_snapshot()))
        view.table_for_id("data_manager.table.artifacts").selectRow(0)

        view.validate_artifact_requested.emit()
        validation = service.calls[-1]
        validation[2](
            TaskResult(
                validation[1],
                "completed",
                DataManagerArtifactValidation(
                    MARKET,
                    "oscillator",
                    "rsi",
                    "a" * 64,
                    "stale",
                    "source changed",
                ),
            )
        )

        assert presenter.selected_market_id == MARKET
        assert view.selected_market_id() == MARKET
        assert view.selected_artifact().artifact_id == "a" * 64
        assert view.status_text() == "Artifact is stale"
    finally:
        view.close()
