from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from leonardo.connection import (
    ConnectionApplicationService,
    HistoricalProviderRequestError,
    ProviderCandle,
    ProviderRegistry,
)
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


class _GeneratedHistoryProvider(_FakeProvider):
    def __init__(self, rows=6):
        super().__init__()
        self.rows = {"1m": tuple(index * 60_000 for index in range(1, rows + 1))}

    def supported_timeframes(self, market):
        return set(self.rows)

    async def get_server_time_ms(self):
        return max((ts for values in self.rows.values() for ts in values), default=0) + 60_000

    async def oldest_historical_ohlcv_ts_ms(self, *, timeframe, **_kwargs):
        return min(self.rows[timeframe], default=None)

    async def fetch_ohlcv_historical(self, *, timeframe, start_ms=None, end_ms=None, limit=None, **_kwargs):
        self.calls.append((timeframe, end_ms))
        selected = [ts for ts in self.rows[timeframe] if (start_ms is None or ts >= start_ms) and (end_ms is None or ts <= end_ms)]
        if limit:
            selected = selected[-limit:]
        return tuple(ProviderCandle(ts, 10, 12, 9, 11, 5) for ts in selected)


def _file_state(path):
    return (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None


@pytest.mark.parametrize("persistence", ["committed", "repaired"])
def test_up_to_date_preserves_accepted_evidence(tmp_path, monkeypatch, persistence):
    from leonardo.ohlcv.maintenance import OHLCVMaintenanceService
    from leonardo.ohlcv.validation import CanonicalOHLCVValidator
    from leonardo.research.catalog import AcceptedDatasetCatalog

    provider = _GeneratedHistoryProvider()
    service, store = _service(tmp_path, provider)
    request = _request(start=None, end=None)
    first = asyncio.run(service.run_batch(request)).results[0]
    if persistence == "repaired":
        store.mark_repaired(first.market_id, repair_record={"audit": "generated repair provenance"})
    maintenance = OHLCVMaintenanceService(store, CanonicalOHLCVValidator())
    assert maintenance.validate(first.market_id).accepted
    before = [_file_state(path) for path in (store.csv_path(first.market_id), store.sidecar_path(first.market_id))]
    catalog = AcceptedDatasetCatalog(store.root)
    assert len(catalog.list_accepted()) == 1
    calls = []
    for name in ("write", "finalize"):
        original = getattr(store, name)
        def recorded(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(store, name, recorded)
    events = []
    result = asyncio.run(service.run_batch(request, progress=events.append)).results[0]
    assert [_file_state(path) for path in (store.csv_path(first.market_id), store.sidecar_path(first.market_id))] == before
    assert calls == []
    assert result.up_to_date and result.fetched_rows == 0
    assert result.downloaded_first_ts_ms is None and result.downloaded_last_ts_ms is None
    assert not any(event.kind == "page_persisted" for event in events)
    assert any("evidence unchanged" in event.message for event in events)
    assert not any("acceptance is still required" in event.message for event in events)
    assert len(catalog.list_accepted()) == 1
    assert store.read_sidecar(first.market_id).persistence_status == persistence
    assert store.read_sidecar(first.market_id).validation_status == "ok"


@pytest.mark.parametrize("state", ["partial", "unknown", "warning", "error", "missing", "invalid", "stale"])
def test_up_to_date_does_not_repair_or_promote_unaccepted_evidence(tmp_path, state):
    from leonardo.research.catalog import AcceptedDatasetCatalog

    service, store = _service(tmp_path, _GeneratedHistoryProvider())
    request = _request(start=None, end=None)
    market = asyncio.run(service.run_batch(request)).results[0].market_id
    path = store.sidecar_path(market)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if state == "missing":
        path.unlink()
    elif state == "invalid":
        path.write_text("{invalid", encoding="utf-8")
    else:
        if state == "partial":
            payload["persistence_status"] = "partial"
        elif state == "stale":
            payload["lineage"]["file_mtime_ns"] = 0
        else:
            payload["validation_status"] = state
        path.write_text(json.dumps(payload), encoding="utf-8")
    before = (_file_state(store.csv_path(market)), _file_state(path))
    assert AcceptedDatasetCatalog(store.root).list_accepted() == ()
    result = asyncio.run(service.run_batch(request)).results[0]
    assert (_file_state(store.csv_path(market)), _file_state(path)) == before
    assert result.up_to_date
    assert AcceptedDatasetCatalog(store.root).list_accepted() == ()


def test_invalid_csv_update_fails_without_mutation(tmp_path):
    service, store = _service(tmp_path, _GeneratedHistoryProvider())
    request = _request(start=None, end=None)
    market = asyncio.run(service.run_batch(request)).results[0].market_id
    store.csv_path(market).write_text("broken,csv\n", encoding="utf-8")
    before = (_file_state(store.csv_path(market)), _file_state(store.sidecar_path(market)))
    with pytest.raises(ValueError, match="CSV columns"):
        asyncio.run(service.run_batch(request))
    assert (_file_state(store.csv_path(market)), _file_state(store.sidecar_path(market))) == before


def test_real_update_still_resets_acceptance_and_reports_persistence(tmp_path):
    from leonardo.ohlcv.maintenance import OHLCVMaintenanceService
    from leonardo.ohlcv.validation import CanonicalOHLCVValidator

    provider = _GeneratedHistoryProvider(3)
    service, store = _service(tmp_path, provider)
    request = _request(start=None, end=None)
    market = asyncio.run(service.run_batch(request)).results[0].market_id
    assert OHLCVMaintenanceService(store, CanonicalOHLCVValidator()).validate(market).accepted
    provider.rows["1m"] += (240_000,)
    events = []
    item = asyncio.run(service.run_batch(request, progress=events.append)).results[0]
    assert item.fetched_rows > 0 and not item.up_to_date
    assert store.read_sidecar(market).validation_status == "unknown"
    assert any(event.kind == "page_persisted" for event in events)


@pytest.mark.parametrize("start", [60_000, None])
def test_page_ceiling_leaves_incomplete_history_partial(tmp_path, monkeypatch, start):
    from leonardo.research.catalog import AcceptedDatasetCatalog

    provider = _GeneratedHistoryProvider()
    service, store = _service(tmp_path, provider)
    service.MAX_PAGES = 2
    finalizations = []
    original = store.finalize
    def finalize(*args, **kwargs):
        finalizations.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "finalize", finalize)
    events = []
    with pytest.raises(RuntimeError, match="page.*ceiling"):
        asyncio.run(service.run_batch(_request(start=start, end=360_000), progress=events.append))
    market = canonicalize_market_id("fake", "linear", "BTCUSDT", "1m")
    assert [c.ts_ms for c in store.read(market)] == [180_000, 240_000, 300_000, 360_000]
    sidecar = store.read_sidecar(market)
    assert sidecar.persistence_status == "partial" and sidecar.validation_status == "unknown"
    assert not finalizations and provider.closed
    assert events[-1].kind == "batch_failed"
    assert not any(event.kind == "preliminary_validation_completed" for event in events)
    assert AcceptedDatasetCatalog(store.root).list_accepted() == ()
    async def reacquire():
        async with service.operation_locks.acquire(market):
            return True
    assert asyncio.run(asyncio.wait_for(reacquire(), 1.0))


@pytest.mark.parametrize("rows", [2, 4])
def test_page_ceiling_allows_completion_at_or_before_last_page(tmp_path, rows):
    service, store = _service(tmp_path, _GeneratedHistoryProvider(rows))
    service.MAX_PAGES = 2
    result = asyncio.run(service.run_batch(_request(start=60_000, end=rows * 60_000)))
    assert result.results[0].total_rows == rows
    assert store.read_sidecar(result.results[0].market_id).persistence_status == "committed"


def test_provider_exhaustion_before_ceiling_still_completes(tmp_path):
    service, store = _service(tmp_path, _GeneratedHistoryProvider(2))
    service.MAX_PAGES = 3
    result = asyncio.run(service.run_batch(_request(start=0, end=120_000)))
    assert result.results[0].total_rows == 2
    assert store.read_sidecar(result.results[0].market_id).persistence_status == "committed"


def test_empty_provider_is_not_promoted_by_page_guard(tmp_path):
    service, store = _service(tmp_path, _GeneratedHistoryProvider(0))
    service.MAX_PAGES = 2
    with pytest.raises(RuntimeError, match="no OHLCV candles"):
        asyncio.run(service.run_batch(_request(start=0, end=120_000)))
    assert not list(store.root.rglob("*.csv"))


def test_ceiling_failure_preserves_an_earlier_completed_timeframe(tmp_path):
    provider = _GeneratedHistoryProvider(2)
    provider.rows["5m"] = tuple(index * 300_000 for index in range(1, 7))
    service, store = _service(tmp_path, provider)
    service.MAX_PAGES = 2
    events = []
    with pytest.raises(RuntimeError, match="page.*ceiling"):
        asyncio.run(service.run_batch(_request(timeframes=("1m", "5m"), start=60_000, end=1_800_000), progress=events.append))
    first = canonicalize_market_id("fake", "linear", "BTCUSDT", "1m")
    second = canonicalize_market_id("fake", "linear", "BTCUSDT", "5m")
    assert store.read_sidecar(first).persistence_status == "committed"
    assert store.read_sidecar(second).persistence_status == "partial"
    assert [e.timeframe for e in events if e.kind == "item_completed"] == ["1m"]
    assert provider.closed


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


def test_page_ceiling_delivers_failed_terminal_result_through_core(tmp_path):
    from threading import Event

    from leonardo.core.core_runner import CoreRunner
    from leonardo.core.task_manager import TaskManager
    from leonardo.ohlcv.application import HistoricalDownloadApplicationService

    provider = _GeneratedHistoryProvider()
    domain, store = _service(tmp_path, provider)
    domain.MAX_PAGES = 2
    runner = CoreRunner(TaskManager())
    application = HistoricalDownloadApplicationService(runner, domain)
    settled = Event()
    results = []
    runner.start()
    try:
        application.submit_download(
            _request(end=360_000),
            result_callback=lambda result: (results.append(result), settled.set()),
        )
        assert settled.wait(3.0)
        assert len(results) == 1 and results[0].status == "failed"
        assert "page ceiling" in results[0].error_message
        market = canonicalize_market_id("fake", "linear", "BTCUSDT", "1m")
        assert store.read_sidecar(market).persistence_status == "partial"
        assert provider.closed
    finally:
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


class _ProviderFailureProbe(_FakeProvider):
    def __init__(
        self,
        failures: list[HistoricalProviderRequestError],
    ) -> None:
        super().__init__()
        self._failures = list(failures)
        self.page_attempts = 0

    async def fetch_ohlcv_historical(self, *, timeframe, end_ms=None, **kwargs):
        self.page_attempts += 1
        if self._failures:
            raise self._failures.pop(0)
        return await super().fetch_ohlcv_historical(
            timeframe=timeframe,
            end_ms=end_ms,
            **kwargs,
        )


def test_downloader_does_not_retry_permanent_provider_failure(tmp_path: Path) -> None:
    provider = _ProviderFailureProbe(
        [
            HistoricalProviderRequestError(
                "invalid symbol",
                provider="bybit",
                operation="historical_ohlcv",
                retryable=False,
                code=10001,
            )
        ]
    )
    service, _store = _service(tmp_path, provider)
    events = []

    with pytest.raises(RuntimeError, match="failed after 1 downloader attempt"):
        asyncio.run(service.run_batch(_request(), progress=events.append))

    assert provider.page_attempts == 1
    failed = next(event for event in events if event.kind == "page_failed")
    assert failed.details["provider_retryable"] is False
    assert failed.details["provider_code"] == 10001
    assert not any(event.kind == "page_retrying" for event in events)


def test_downloader_retries_transient_provider_failure_not_already_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ProviderFailureProbe(
        [
            HistoricalProviderRequestError(
                "temporary transport failure",
                provider="fake",
                operation="historical_ohlcv",
                retryable=True,
            )
        ]
    )
    service, store = _service(tmp_path, provider)
    service.RETRY_BACKOFF_SECONDS = 0.0
    events = []

    result = asyncio.run(service.run_batch(_request(), progress=events.append))

    assert result.results[0].total_rows == 3
    assert provider.page_attempts == 3
    assert any(event.kind == "page_retrying" for event in events)
    market = canonicalize_market_id("fake", "linear", "BTCUSDT", "1m")
    assert store.read_sidecar(market).persistence_status == "committed"


def test_downloader_does_not_amplify_provider_exhausted_retries(tmp_path: Path) -> None:
    provider = _ProviderFailureProbe(
        [
            HistoricalProviderRequestError(
                "provider retries exhausted",
                provider="bybit",
                operation="historical_ohlcv",
                retryable=True,
                attempts_exhausted=True,
                status=503,
            )
        ]
    )
    service, _store = _service(tmp_path, provider)
    events = []

    with pytest.raises(RuntimeError, match="failed after 1 downloader attempt"):
        asyncio.run(service.run_batch(_request(), progress=events.append))

    assert provider.page_attempts == 1
    failed = next(event for event in events if event.kind == "page_failed")
    assert failed.details["provider_attempts_exhausted"] is True
    assert not any(event.kind == "page_retrying" for event in events)
