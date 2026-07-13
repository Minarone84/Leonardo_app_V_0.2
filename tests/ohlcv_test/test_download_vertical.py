from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from leonardo.connection import ConnectionApplicationService, ProviderCandle, ProviderRegistry
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.data import canonicalize_market_id, timeframe_to_storage_segment
from leonardo.ohlcv import DownloadBatchRequest, HistoricalDownloadService, OHLCVStore


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[tuple[str, int | None]] = []
        self.block_second_page = False
        self.second_page_started: asyncio.Event | None = None

    def supported_markets(self):
        return {"linear"}

    def supported_timeframes(self, market):
        assert market == "linear"
        return {"1m", "1M"}

    def max_historical_ohlcv_limit(self, market):
        assert market == "linear"
        return 2

    async def open(self):
        return None

    async def close(self):
        self.closed = True

    async def get_server_time_ms(self):
        return 240_000

    async def oldest_historical_ohlcv_ts_ms(self, **_kwargs):
        return 60_000

    async def fetch_ohlcv_historical(self, *, timeframe, end_ms=None, **_kwargs):
        self.calls.append((timeframe, end_ms))
        if timeframe == "1M":
            return ()
        if end_ms is None or end_ms >= 180_000:
            return (
                ProviderCandle(120_000, 2, 3, 1, 2.5, 20),
                ProviderCandle(180_000, 3, 4, 2, 3.5, 30),
            )
        if self.block_second_page and end_ms >= 60_000:
            assert self.second_page_started is not None
            self.second_page_started.set()
            await asyncio.Event().wait()
        if end_ms >= 60_000:
            return (ProviderCandle(60_000, 1, 2, 0.5, 1.5, 10),)
        return ()


def _service(tmp_path: Path, provider: _FakeProvider):
    registry = ProviderRegistry()
    registry.register("fake", lambda: provider)
    connections = ConnectionApplicationService(registry, ConnectionRegistry())
    store = OHLCVStore(tmp_path / "historical")
    service = HistoricalDownloadService(
        connections,
        store,
        AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )
    return service, store


def _request(*, timeframes=("1m",), start=60_000, end=180_000):
    return DownloadBatchRequest(
        exchange="fake",
        market_type="linear",
        symbol="btc-usdt",
        timeframes=timeframes,
        start_ms=start,
        end_ms=end,
        limit=0,
    )


def test_preflight_is_non_mutating_and_reports_workload(tmp_path: Path) -> None:
    provider = _FakeProvider()
    service, store = _service(tmp_path, provider)

    report = asyncio.run(service.preflight_batch(_request()))

    item = report.items[0]
    assert report.can_download is True
    assert item.market_id.symbol == "BTCUSDT"
    assert item.mode == "custom_range"
    assert item.expected_bars == 3
    assert item.expected_pages == 2
    assert item.page_limit == 2
    assert not store.dataset_dir(item.market_id).exists()
    assert provider.closed is True


def test_month_preflight_remains_indeterminate_and_uses_collision_safe_path(tmp_path: Path) -> None:
    provider = _FakeProvider()
    service, store = _service(tmp_path, provider)

    report = asyncio.run(service.preflight_batch(_request(timeframes=("1M",), start=0, end=2_678_400_000)))

    item = report.items[0]
    assert item.expected_bars is None
    assert item.expected_pages is None
    assert timeframe_to_storage_segment("1M") == "1mo"
    assert store.dataset_dir(item.market_id).parts[-2] == "1mo"


def test_download_persists_pages_and_leaves_validation_unknown(tmp_path: Path) -> None:
    provider = _FakeProvider()
    service, store = _service(tmp_path, provider)
    events = []

    result = asyncio.run(service.run_batch(_request(), progress=events.append))

    item = result.results[0]
    assert item.total_rows == 3
    assert item.fetched_rows == 3
    assert item.preliminary_validation_status == "ok"
    candles = store.read(item.market_id)
    assert [candle.ts_ms for candle in candles] == [60_000, 120_000, 180_000]
    sidecar = store.read_sidecar(item.market_id)
    assert sidecar.persistence_status == "committed"
    assert sidecar.validation_status == "unknown"
    assert sidecar.lineage["canonical_validation_status"] == "unknown"
    assert [event.kind for event in events].count("page_persisted") == 2


def test_cancel_after_first_page_reports_exact_partial_persistence(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = _FakeProvider()
        provider.block_second_page = True
        provider.second_page_started = asyncio.Event()
        service, store = _service(tmp_path, provider)
        events = []
        task = asyncio.create_task(service.run_batch(_request(), progress=events.append))
        await asyncio.wait_for(provider.second_page_started.wait(), 1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        cancelled = next(event for event in events if event.kind == "item_cancelled")
        assert cancelled.details["partial_persistence"] is True
        assert cancelled.details["pages_written"] == 1
        assert cancelled.details["rows_written"] == 2
        market = canonicalize_market_id("fake", "linear", "BTCUSDT", "1m")
        sidecar = store.read_sidecar(market)
        assert sidecar.persistence_status == "partial"
        assert sidecar.validation_status == "unknown"

    asyncio.run(scenario())


def test_request_rejects_reversed_range(tmp_path: Path) -> None:
    provider = _FakeProvider()
    service, _store = _service(tmp_path, provider)
    with pytest.raises(ValueError, match="cannot be greater"):
        asyncio.run(service.preflight_batch(_request(start=180_000, end=60_000)))


def test_application_service_runs_preflight_and_download_through_core(tmp_path: Path) -> None:
    from threading import Event

    from leonardo.core.core_runner import CoreRunner
    from leonardo.core.task_manager import TaskManager
    from leonardo.ohlcv.application import HistoricalDownloadApplicationService

    provider = _FakeProvider()
    domain, store = _service(tmp_path, provider)
    runner = CoreRunner(TaskManager())
    application = HistoricalDownloadApplicationService(runner, domain)
    preflight_done = Event()
    download_done = Event()
    preflight_results = []
    download_results = []

    runner.start()
    application.submit_preflight(
        _request(),
        result_callback=lambda result: (preflight_results.append(result), preflight_done.set()),
    )
    assert preflight_done.wait(2.0)
    assert preflight_results[0].status == "completed"
    assert preflight_results[0].value.can_download is True

    application.submit_download(
        _request(),
        result_callback=lambda result: (download_results.append(result), download_done.set()),
    )
    assert download_done.wait(2.0)
    assert download_results[0].status == "completed"
    market = canonicalize_market_id("fake", "linear", "BTCUSDT", "1m")
    assert store.read_sidecar(market).validation_status == "unknown"
    runner.shutdown()


def test_automatic_preflight_uses_provider_candle_alignment_for_latest_closed(tmp_path: Path) -> None:
    provider = _FakeProvider()
    service, _store = _service(tmp_path, provider)
    request = DownloadBatchRequest(
        exchange="fake",
        market_type="linear",
        symbol="BTCUSDT",
        timeframes=("1m",),
        limit=0,
    )

    report = asyncio.run(service.preflight_batch(request))

    item = report.items[0]
    assert item.planned_start_ms == 60_000
    assert item.planned_end_ms == 180_000
    assert item.expected_bars == 3


def test_cancel_during_finalize_reports_committed_persistence_truth(tmp_path: Path) -> None:
    from threading import Event

    async def scenario() -> None:
        provider = _FakeProvider()
        service, store = _service(tmp_path, provider)
        finalize_started = Event()
        finalize_release = Event()
        original_finalize = store.finalize

        def blocking_finalize(*args, **kwargs):
            finalize_started.set()
            assert finalize_release.wait(2.0)
            return original_finalize(*args, **kwargs)

        store.finalize = blocking_finalize  # type: ignore[method-assign]
        events = []
        task = asyncio.create_task(service.run_batch(_request(), progress=events.append))
        assert await asyncio.to_thread(finalize_started.wait, 1.0)
        task.cancel()
        finalize_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        cancelled = next(event for event in events if event.kind == "item_cancelled")
        assert cancelled.details["download_complete"] is True
        assert cancelled.details["persistence_status"] == "committed"
        assert cancelled.details["partial_persistence"] is False

    asyncio.run(scenario())
