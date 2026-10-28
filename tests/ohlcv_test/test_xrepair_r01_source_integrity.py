"""R01 desired source ownership and evidence behavior; synthetic/offline only."""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest

from leonardo.connection import ConnectionApplicationService, ProviderRegistry, ProviderCandle
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import Candle, DownloadBatchRequest, HistoricalDownloadService, OHLCVStore
from leonardo.ohlcv import CanonicalOHLCVValidator, OHLCVMaintenanceApplicationService
from leonardo.ohlcv.operation_locks import OHLCVDatasetOperationLocks
from leonardo.research import AcceptedDatasetCatalog
from tests.ohlcv_test.test_maintenance_repair import _RepairProvider, _maintenance, _market


def receipt(root, label, store, market):
    files = {}
    for path in (store.csv_path(market), store.sidecar_path(market)):
        if path.exists():
            stat = path.stat()
            files[path.name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   size=stat.st_size, mtime_ns=stat.st_mtime_ns, ino=stat.st_ino)
        else:
            files[path.name] = None
    value = dict(label=label, files=files,
                 accepted=bool(AcceptedDatasetCatalog(store.root).list_accepted()))
    (root / (label + '.json')).write_text(json.dumps(value, indent=2), encoding='utf-8')
    return value


class Provider(_RepairProvider):
    mode = 'normal'
    closed = 0

    async def get_server_time_ms(self):
        return 240_000

    async def close(self):
        self.closed += 1

    async def fetch_ohlcv_historical(self, **kwargs):
        if self.mode == 'empty':
            return ()
        if self.mode == 'error':
            raise ValueError('injected provider failure before mutation')
        if kwargs['symbol'] == 'LATERUSDT':
            return (ProviderCandle(240_000, 2, 3, 1, 2, 10),)
        return await super().fetch_ohlcv_historical(**kwargs)


def downloader(store, provider=None, locks=None):
    provider = provider or Provider()
    registry = ProviderRegistry()
    registry.register('bybit', lambda: provider)
    return HistoricalDownloadService(
        ConnectionApplicationService(registry, ConnectionRegistry()), store,
        AuditLog(InMemoryAuditSink()), actor_id='r01', operation_locks=locks), provider


def request(*, automatic=False, symbol='BTCUSDT'):
    return DownloadBatchRequest(exchange='bybit', market_type='linear', symbol=symbol,
                                timeframes=('1m',), start_ms=None if automatic else 60_000,
                                end_ms=None if automatic else 180_000)


def accepted(store):
    store.write(_market(), tuple(Candle(t, 1, 2, .5, 1.5, 10) for t in (60_000, 120_000, 180_000)),
                source='r01', persistence_status='committed')
    assert _maintenance(store).validate(_market()).accepted


@pytest.mark.parametrize('mode', ('empty', 'split', 'normal', 'noop', 'error', 'cancel_write'))
def test_actual_persistence_evidence(tmp_path, monkeypatch, mode):
    store = OHLCVStore(tmp_path / 'h')
    accepted(store)
    provider = Provider()
    provider.mode = mode if mode in ('empty', 'error') else 'normal'
    service, _ = downloader(store, provider)
    before = receipt(tmp_path, 'pre', store, _market())
    if mode == 'split':
        import leonardo.ohlcv.store as store_module
        original_replace = store_module.os.replace
        def replace(source, destination):
            if Path(destination) == store.sidecar_path(_market()):
                raise OSError('injected sidecar replacement failure')
            return original_replace(source, destination)
        monkeypatch.setattr(store_module.os, 'replace', replace)
    events = []
    async def scenario():
        task = asyncio.current_task()
        def progress(event):
            events.append(event)
            if mode == 'cancel_write' and event.kind == 'page_persisted':
                task.cancel()
        try:
            return await service.run_batch(request(automatic=mode == 'noop'), progress=progress)
        except (OSError, ValueError, RuntimeError, asyncio.CancelledError):
            if mode not in ('split', 'error', 'cancel_write'):
                raise
    result = asyncio.run(scenario())
    after = receipt(tmp_path, 'post', store, _market())
    changes = [e for e in events if e.kind == 'source_evidence_changed']
    (tmp_path / 'events.json').write_text(json.dumps([dict(kind=e.kind, details=dict(e.details)) for e in events], default=str), encoding='utf-8')
    if mode in ('noop', 'error'):
        assert changes == []
        assert before['files'] == after['files']
        assert after['accepted']
        if mode == 'noop':
            assert result.results[0].up_to_date
    else:
        assert len(changes) == 1
        assert changes[0].details['market_id'] == _market().as_key()
        assert changes[0].timeframe == '1m'
        assert before['files'] != after['files']
        if mode == 'empty':
            assert result.results[0].fetched_rows == 0
            assert before['files']['candles.csv'] == after['files']['candles.csv']
            assert not after['accepted']
        if mode == 'split':
            assert not any(e.kind == 'page_persisted' for e in events)
            assert before['files']['candles.meta.json'] == after['files']['candles.meta.json']


def test_public_repair_excludes_later_partial_writer(tmp_path, monkeypatch):
    store = OHLCVStore(tmp_path / 'h')
    store.write(_market(), (Candle(60_000, 1, 2, .5, 1.5, 10), Candle(180_000, 1, 2, .5, 1.5, 10)), source='r01', persistence_status='committed')
    entered, release, attempted = Event(), Event(), Event()
    acquired = []
    class ObservedLocks(OHLCVDatasetOperationLocks):
        @asynccontextmanager
        async def acquire(self, market):
            later = entered.is_set() and market == _market()
            if later:
                attempted.set()
            async with super().acquire(market):
                if later:
                    acquired.append(True)
                yield
    service, provider = downloader(store, locks=ObservedLocks())
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    original = maintenance.mark_repair_completed
    def paused(*args, **kwargs):
        receipt(tmp_path, 'at_finalizer', store, _market())
        entered.set()
        assert release.wait(4), 'test finalizer release missing'
        return original(*args, **kwargs)
    monkeypatch.setattr(maintenance, 'mark_repair_completed', paused)
    runner = CoreRunner(TaskManager())
    app = OHLCVMaintenanceApplicationService(runner, maintenance, service)
    results, done, writer_done, marker = [], Event(), Event(), Event()
    async def later(_reporter):
        def progress(e):
            if e.kind == 'page_persisted':
                raise ValueError('injected later download failure after durable page')
        return await service.run_batch(request(), progress=progress)
    async def loop_marker(_reporter):
        return None
    runner.start()
    try:
        app.submit_repair(plan, result_callback=lambda r: (results.append(r), done.set()))
        assert entered.wait(4)
        runner.submit_job(later, task_name='later', result_callback=lambda r: (results.append(r), writer_done.set()))
        assert attempted.wait(4)
        runner.submit_job(loop_marker, task_name='marker', result_callback=lambda r: marker.set())
        assert marker.wait(4)
        excluded = not acquired
        if not excluded:
            assert writer_done.wait(4)
            receipt(tmp_path, 'later_failed_before_release', store, _market())
        release.set()
        assert done.wait(4) and writer_done.wait(4)
    finally:
        release.set()
        runner.shutdown()
    final = receipt(tmp_path, 'final', store, _market())
    assert sorted(r.status for r in results) == ['completed', 'failed']
    assert excluded, 'same-market writer acquired while older repair finalizer was active'
    assert not final['accepted'], 'old repair accepted a later failed download'
    assert store.read_sidecar(_market()).persistence_status == 'partial'


@pytest.mark.parametrize('mode', ('normal', 'failure', 'cancel_before', 'cancel_during', 'cancel_repeated', 'range_failure'))
def test_finalizer_lifecycle_and_lock_drain(tmp_path, mode):
    store = OHLCVStore(tmp_path / 'h')
    accepted(store)
    provider = Provider()
    if mode == 'range_failure':
        provider.mode = 'error'
    service, _ = downloader(store, provider)
    async def scenario():
        entered, release = Event(), Event()
        calls, same, other = [], [], []
        def finish(batches):
            calls.append(batches)
            assert provider.closed == 1
            entered.set()
            assert release.wait(4)
            if mode == 'failure':
                raise ValueError('actual finalizer failure')
        def progress(event):
            if mode == 'cancel_before' and event.kind == 'preliminary_validation_completed':
                task.cancel()
        task = asyncio.create_task(service.run_repair_batches((request(),), before_first_write=lambda: None,
                                                             after_ranges=finish, progress=progress))
        async def contender(market, values):
            async with service.operation_locks.acquire(market):
                values.append(True)
        contenders = []
        try:
            if mode in ('cancel_before', 'range_failure'):
                with pytest.raises(asyncio.CancelledError if mode == 'cancel_before' else RuntimeError):
                    await task
                assert calls == []
                return
            assert await asyncio.to_thread(entered.wait, 4)
            contenders = [asyncio.create_task(contender(_market(), same)), asyncio.create_task(contender(canonicalize_market_id('bybit','linear','ETHUSDT','1m'), other))]
            await asyncio.sleep(0)
            assert other == [True] and same == []
            if mode.startswith('cancel_'):
                task.cancel()
                await asyncio.sleep(0)
                if mode == 'cancel_repeated':
                    task.cancel()
                    await asyncio.sleep(0)
                assert not task.done() and same == []
            release.set()
            if mode.startswith('cancel_'):
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif mode == 'failure':
                with pytest.raises(ValueError, match='actual finalizer failure'):
                    await task
            else:
                result = await task
                assert result == calls[0] and isinstance(result, tuple)
            await asyncio.gather(*contenders)
            assert same == [True] and len(calls) == 1
        finally:
            release.set()
            await asyncio.gather(task, *contenders, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('timestamps', ((10**30, 10**30 + 1),
    (int(datetime(2024,1,31,tzinfo=timezone.utc).timestamp()*1000), int(datetime(2024,2,29,tzinfo=timezone.utc).timestamp()*1000)),
    (int(datetime(2023,1,31,tzinfo=timezone.utc).timestamp()*1000), int(datetime(2023,2,28,tzinfo=timezone.utc).timestamp()*1000))))
def test_monthly_conversion_structured_and_read_only(tmp_path, timestamps):
    path = tmp_path / 'candles.csv'
    path.write_text('ts_ms,open,high,low,close,volume\n' + ''.join(f'{t},1,2,.5,1.5,10\n' for t in timestamps), encoding='utf-8')
    before = path.read_bytes()
    issues = []
    counts = CanonicalOHLCVValidator._scan_csv(path, canonicalize_market_id('bybit','linear','BTCUSDT','1M'), issues,
        cancel_requested=None, progress_callback=None, progress_interval_rows=1, expected_rows=2)
    assert counts == (2, timestamps[0], timestamps[1])
    assert path.read_bytes() == before
    if timestamps[0] == 10**30:
        errors = [i for i in issues if i.code == 'timestamp_out_of_range']
        assert len(errors) == 1 and errors[0].severity == 'error'
        assert (errors[0].row_number, errors[0].column, errors[0].timestamp_ms) == (3, 'ts_ms', timestamps[1])
    else:
        assert issues == []


@pytest.mark.parametrize('mode', ('huge', 'calendar_limit', 'cancel'))
def test_public_calendar_report_and_cancellation(tmp_path, mode):
    from leonardo.ohlcv.validation import ValidationCancelled
    market = canonicalize_market_id('bybit', 'linear', 'BTCUSDT', '1M')
    store = OHLCVStore(tmp_path / 'h')
    first = 10**30 if mode == 'huge' else int(datetime(9999,12,1,tzinfo=timezone.utc).timestamp()*1000) if mode == 'calendar_limit' else 0
    store.write(market, (Candle(first,1,2,.5,1.5,10), Candle(first+1,1,2,.5,1.5,10)), source='r01', persistence_status='committed')
    before = {p.name: p.read_bytes() for p in store.dataset_dir(market).iterdir()}
    if mode == 'cancel':
        with pytest.raises(ValidationCancelled):
            CanonicalOHLCVValidator().validate(store, market, cancel_requested=lambda: True)
    else:
        report = CanonicalOHLCVValidator().validate(store, market)
        assert report.status == 'error'
        assert any(i.severity == 'error' for i in report.issues)
        if mode == 'huge':
            assert any(i.code == 'timestamp_out_of_range' for i in report.issues)
    assert {p.name: p.read_bytes() for p in store.dataset_dir(market).iterdir()} == before


def test_uncertain_stat_evidence_does_not_hide_original_failure(tmp_path, monkeypatch):
    store = OHLCVStore(tmp_path / 'h')
    accepted(store)
    service, _ = downloader(store)
    original = Path.stat
    calls = []
    def stat(path, *args, **kwargs):
        if path == store.csv_path(_market()):
            calls.append(True)
            raise PermissionError('injected witness access refusal')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', stat)
    events = []
    with pytest.raises(PermissionError, match='injected witness access refusal'):
        asyncio.run(service.run_batch(request(), progress=events.append))
    changes = [e for e in events if e.kind == 'source_evidence_changed']
    assert len(changes) == 1 and calls
    assert changes[0].details['changed_files']['csv']['before']['state'] == 'uncertain'
    assert changes[0].details['changed_files']['csv']['after']['state'] == 'uncertain'
