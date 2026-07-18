from __future__ import annotations

from pathlib import Path
from threading import Event
import time

import pytest

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.data import MarketId
from leonardo.data_manager import DataManagerApplicationService, DataManagerService
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.research import AcceptedDatasetSummary, DatasetCatalogReport, HistoricalDataset


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")


class _Catalog:
    def scan(self):
        return DatasetCatalogReport(
            (
                AcceptedDatasetSummary(
                    MARKET,
                    Path("candles.csv"),
                    Path("candles.meta.json"),
                    "a" * 64,
                    1,
                    0,
                    0,
                    "test",
                    "committed",
                    "ok",
                    (),
                ),
            ),
            (),
        )


class _BlockingCatalog(_Catalog):
    def __init__(self) -> None:
        self.scan_entered = Event()
        self.release_scan = Event()

    def scan(self):
        self.scan_entered.set()
        if not self.release_scan.wait(3.0):
            raise RuntimeError("catalog scan release timed out")
        return super().scan()


class _Loader:
    def __init__(self, *, block_until_cancelled: bool = False) -> None:
        self.block_until_cancelled = block_until_cancelled

    def load(self, market_id, *, progress=None, cancellation_requested=None):
        if self.block_until_cancelled:
            while not cancellation_requested():
                time.sleep(0.005)
            raise RuntimeError("cancelled loader")
        if progress is not None:
            progress(1, 1)
        return HistoricalDataset(
            MARKET,
            Path("candles.csv"),
            "a" * 64,
            1,
            0,
            0,
            (0,),
            (1.0,),
            (2.0,),
            (0.5,),
            (1.5,),
            (10.0,),
        )


class _Artifacts:
    def __init__(self) -> None:
        self.artifact_deletion_started = Event()
        self.recipe_deletion_started = Event()
        self.release_artifact_deletion = Event()
        self.release_recipe_deletion = Event()
        self.artifact_delete_calls = 0
        self.recipe_delete_calls = 0

    def list_recipes(self, market_id):
        return ()

    def list_artifacts(self, market_id):
        return ()

    def load_artifact(self, *args):
        raise AssertionError("not used")

    def validate_artifact_current(self, *args):
        raise AssertionError("not used")

    def delete_artifact(self, *args):
        self.artifact_delete_calls += 1
        self.artifact_deletion_started.set()
        self.release_artifact_deletion.wait(3.0)
        return None

    def delete_recipe(self, *args):
        self.recipe_delete_calls += 1
        self.recipe_deletion_started.set()
        self.release_recipe_deletion.wait(3.0)
        return None


class _TrackingService(DataManagerService):
    def __init__(self, catalog, loader, artifacts) -> None:
        super().__init__(catalog, loader, artifacts)
        self.artifact_worker_finished = Event()
        self.recipe_worker_finished = Event()

    def _delete_artifact(self, *args, **kwargs):
        try:
            return super()._delete_artifact(*args, **kwargs)
        finally:
            self.artifact_worker_finished.set()

    def _delete_recipe(self, *args, **kwargs):
        try:
            return super()._delete_recipe(*args, **kwargs)
        finally:
            self.recipe_worker_finished.set()


def _application(loader=None, artifacts=None, catalog=None, service=None):
    manager = TaskManager()
    runner = CoreRunner(manager)
    domain = service or DataManagerService(
        catalog or _Catalog(), loader or _Loader(), artifacts or _Artifacts()
    )
    return manager, runner, DataManagerApplicationService(runner, domain)


def test_application_runs_catalog_through_core_and_tracks_operation() -> None:
    manager, runner, application = _application()
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        application.submit_scan_catalog(
            result_callback=lambda result: (results.append(result), ready.set())
        )
        assert ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value.accepted_count == 1
        assert any(
            item.metadata.get("operation") == "data_manager.scan_catalog"
            for item in manager.snapshots()
        )
    finally:
        runner.shutdown()


def test_preview_cancellation_is_cooperative_before_publication() -> None:
    manager, runner, application = _application(loader=_Loader(block_until_cancelled=True))
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = application.submit_preview_dataset(
            MARKET,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        assert application.cancel(submission.task_id)
        assert ready.wait(3.0)
        assert results[0].status == "cancelled"
    finally:
        runner.shutdown()


@pytest.mark.parametrize("object_kind", ("artifact", "recipe"))
def test_pre_delete_cancellation_prevents_worker_publication(object_kind) -> None:
    catalog = _BlockingCatalog()
    artifacts = _Artifacts()
    service = _TrackingService(catalog, _Loader(), artifacts)
    _manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submit = (
            application.submit_delete_artifact
            if object_kind == "artifact"
            else application.submit_delete_recipe
        )
        submission = submit(
            MARKET,
            "indicator",
            "sma",
            ("a" if object_kind == "artifact" else "r") * 64,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        assert catalog.scan_entered.wait(3.0)
        assert application.cancel(submission.task_id) is True
        assert artifacts.artifact_delete_calls == 0
        assert artifacts.recipe_delete_calls == 0
        catalog.release_scan.set()
        worker_finished = (
            service.artifact_worker_finished
            if object_kind == "artifact"
            else service.recipe_worker_finished
        )
        assert worker_finished.wait(3.0)
        assert ready.wait(3.0)
        assert results[0].status == "cancelled"
        assert artifacts.artifact_delete_calls == 0
        assert artifacts.recipe_delete_calls == 0
    finally:
        catalog.release_scan.set()
        runner.shutdown()


@pytest.mark.parametrize("object_kind", ("artifact", "recipe"))
def test_cancellation_is_refused_after_canonical_deletion_starts(object_kind) -> None:
    artifacts = _Artifacts()
    _manager, runner, application = _application(artifacts=artifacts)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submit = (
            application.submit_delete_artifact
            if object_kind == "artifact"
            else application.submit_delete_recipe
        )
        object_id = ("a" if object_kind == "artifact" else "r") * 64
        submission = submit(
            MARKET,
            "indicator",
            "sma",
            object_id,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        deletion_started = (
            artifacts.artifact_deletion_started
            if object_kind == "artifact"
            else artifacts.recipe_deletion_started
        )
        assert deletion_started.wait(3.0)
        assert application.cancel(submission.task_id) is False
        if object_kind == "artifact":
            artifacts.release_artifact_deletion.set()
        else:
            artifacts.release_recipe_deletion.set()
        assert ready.wait(3.0)
        assert results[0].value == DataManagerDeletionResult(
            MARKET, object_kind, "indicator", "sma", object_id
        )
        assert artifacts.artifact_delete_calls == (object_kind == "artifact")
        assert artifacts.recipe_delete_calls == (object_kind == "recipe")
    finally:
        artifacts.release_artifact_deletion.set()
        artifacts.release_recipe_deletion.set()
        runner.shutdown()
