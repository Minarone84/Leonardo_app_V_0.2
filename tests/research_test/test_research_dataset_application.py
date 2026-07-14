from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import time
from threading import Event, current_thread

from leonardo.core import LeonardoApp
from leonardo.core.config import load_default_config
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv import OHLCVStore
from leonardo.research import HistoricalDataset, ResearchDatasetApplicationService
from leonardo.storage import OHLCVSidecarV1


class _RecordingLoader:
    def __init__(self, dataset: HistoricalDataset) -> None:
        self.dataset = dataset
        self.thread_name: str | None = None

    def load(self, market_id, *, progress=None, cancellation_requested=None):
        self.thread_name = current_thread().name
        if progress is not None:
            progress(1, 1)
        return self.dataset


class _DelayedLoader:
    def __init__(self, dataset: HistoricalDataset) -> None:
        self.dataset = dataset

    def load(self, market_id, *, progress=None, cancellation_requested=None):
        time.sleep(0.05)
        return self.dataset


class _CooperativeSlowLoader:
    def __init__(self, dataset: HistoricalDataset) -> None:
        self.dataset = dataset
        self.cancelled_before_publication = Event()

    def load(self, market_id, *, progress=None, cancellation_requested=None):
        while not (cancellation_requested and cancellation_requested()):
            time.sleep(0.005)
        self.cancelled_before_publication.set()
        raise RuntimeError("cancelled worker")


def _dataset(market: MarketId) -> HistoricalDataset:
    return HistoricalDataset(
        market_id=market,
        csv_path=Path("candles.csv"),
        file_sha256="a" * 64,
        row_count=1,
        first_timestamp_ms=60_000,
        last_timestamp_ms=60_000,
        ts_ms=(60_000,),
        open=(1.0,),
        high=(2.0,),
        low=(0.5,),
        close=(1.5,),
        volume=(10.0,),
    )


def test_application_service_runs_loader_in_core_worker_thread() -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    loader = _RecordingLoader(_dataset(market))
    task_manager = TaskManager()
    runner = CoreRunner(task_manager)
    service = ResearchDatasetApplicationService(runner, loader)
    result_ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        service.submit_load(
            market,
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert result_ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value == loader.dataset
        assert loader.thread_name is not None
        assert loader.thread_name.startswith("LeonardoWorker")
    finally:
        runner.shutdown()


def test_application_service_allows_concurrent_same_market_requests() -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    loader = _DelayedLoader(_dataset(market))
    task_manager = TaskManager()
    runner = CoreRunner(task_manager)
    service = ResearchDatasetApplicationService(runner, loader)
    results: list[TaskResult] = []
    both_ready = Event()

    def on_result(result: TaskResult) -> None:
        results.append(result)
        if len(results) == 2:
            both_ready.set()

    runner.start()
    try:
        service.submit_load(market, result_callback=on_result)
        service.submit_load(market, result_callback=on_result)
        assert both_ready.wait(3.0)
        assert [result.status for result in results] == ["completed", "completed"]
    finally:
        runner.shutdown()


def test_application_service_cancel_prevents_worker_publication() -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    loader = _CooperativeSlowLoader(_dataset(market))
    task_manager = TaskManager()
    runner = CoreRunner(task_manager)
    service = ResearchDatasetApplicationService(runner, loader)
    result_ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = service.submit_load(
            market,
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert service.cancel(submission.task_id) is True
        assert result_ready.wait(3.0)
        assert results[0].status == "cancelled"
        assert loader.cancelled_before_publication.wait(3.0)
    finally:
        runner.shutdown()


def test_leonardo_app_composes_real_research_dataset_service(tmp_path: Path) -> None:
    config = load_default_config(tmp_path)
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = OHLCVStore(config.paths.historical_data_dir)
    dataset_dir = store.dataset_dir(market)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    csv_path = store.csv_path(market)
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n"
        "60000,1,2,0.5,1.5,10\n"
        "120000,1.5,2.5,1,2,12\n",
        encoding="utf-8",
    )
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        row_count=2,
        first_timestamp_ms=60_000,
        last_timestamp_ms=120_000,
        source="test",
        persistence_status="committed",
        validation_status="ok",
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    result_ready = Event()
    results: list[TaskResult] = []
    try:
        app.context.research_dataset_service.submit_load(
            market,
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert result_ready.wait(3.0)
        assert results[0].status == "completed"
        assert isinstance(results[0].value, HistoricalDataset)
        assert results[0].value.row_count == 2
        snapshots = app.task_manager.snapshots()
        assert any(
            snapshot.metadata.get("operation") == "research_dataset_load"
            for snapshot in snapshots
        )
    finally:
        app.shutdown()


class _RecordingCatalog:
    def __init__(self, report) -> None:
        self.report = report
        self.thread_name: str | None = None

    def scan(self):
        self.thread_name = current_thread().name
        return self.report


class _RecordingSlicer:
    def __init__(self, resident) -> None:
        self.resident = resident
        self.thread_name: str | None = None
        self.center_index: int | None = None

    def slice_around_index(self, dataset, center_index):
        self.thread_name = current_thread().name
        self.center_index = center_index
        return self.resident


def test_application_service_runs_catalog_scan_in_core_worker_thread() -> None:
    from leonardo.research import DatasetCatalogReport

    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    loader = _RecordingLoader(_dataset(market))
    catalog = _RecordingCatalog(DatasetCatalogReport(accepted=(), rejected=()))
    task_manager = TaskManager()
    runner = CoreRunner(task_manager)
    service = ResearchDatasetApplicationService(runner, loader, catalog=catalog)
    result_ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        service.submit_catalog(
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert result_ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value == catalog.report
        assert catalog.thread_name is not None
        assert catalog.thread_name.startswith("LeonardoWorker")
    finally:
        runner.shutdown()


def test_application_service_runs_resident_slice_in_core_worker_thread() -> None:
    from leonardo.research import ResidentOHLCVSlice

    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    dataset = _dataset(market)
    resident = ResidentOHLCVSlice(
        market_id=market,
        dataset_fingerprint=dataset.file_sha256,
        base_index=0,
        end_index_exclusive=1,
        ts_ms=dataset.ts_ms,
        open=dataset.open,
        high=dataset.high,
        low=dataset.low,
        close=dataset.close,
        volume=dataset.volume,
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=dataset.first_timestamp_ms,
        last_timestamp_ms=dataset.last_timestamp_ms,
    )
    loader = _RecordingLoader(dataset)
    slicer = _RecordingSlicer(resident)
    task_manager = TaskManager()
    runner = CoreRunner(task_manager)
    service = ResearchDatasetApplicationService(
        runner,
        loader,
        resident_slices=slicer,
    )
    result_ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        service.submit_resident_slice(
            dataset,
            0,
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert result_ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value is resident
        assert slicer.center_index == 0
        assert slicer.thread_name is not None
        assert slicer.thread_name.startswith("LeonardoWorker")
    finally:
        runner.shutdown()
