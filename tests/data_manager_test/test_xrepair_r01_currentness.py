"""Publication safety must not depend on delivery of a GUI invalidation."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest

from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data_manager import DataManagerArtifactMaterializationRequest
from leonardo.data_manager.application import DataManagerApplicationService
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactRequest
from leonardo.ohlcv import OHLCVStore
from tests.data_manager_test.test_update_workflow import MARKET, _domain, _sma, _materialize
from tests.ohlcv_test.test_maintenance_repair import _maintenance


def extended(path):
    return Path('\\\\?\\' + str(path.absolute())) if os.name == 'nt' and not str(path).startswith('\\\\?\\') else path


def hashes(root):
    root = extended(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def owned(files):
    return {k: v for k, v in files.items() if '/artifacts/' in '/' + k or '/artifact_versions/' in '/' + k or k.endswith('sentinel.txt')}


def record(root, stage, historical, service):
    state = dict(files=hashes(historical), accepted=bool(service._catalog.scan().accepted))
    (root / (stage + '.json')).write_text(json.dumps(state, indent=2), encoding='utf-8')
    return state


def mutation(store, mode, monkeypatch):
    if mode == 'unchanged':
        return
    if mode == 'metadata':
        store.finalize(MARKET, source='r01')
        return
    rows = store.read(MARKET)
    # Same row count/axis and same-size payload; stale sidecar is held constant.
    rows[-1] = replace(rows[-1], volume=rows[-1].volume + 1)
    if mode == 'split':
        original = os.replace
        def replace_file(source, destination):
            if str(destination).removeprefix('\\\\?\\') == str(store.sidecar_path(MARKET)).removeprefix('\\\\?\\'):
                raise OSError('r01 split sidecar fault')
            return original(source, destination)
        with monkeypatch.context() as patch:
            patch.setattr(os, 'replace', replace_file)
            with pytest.raises(OSError, match='r01 split sidecar fault'):
                store.write(MARKET, rows, source='r01', persistence_status='partial')
    else:
        store.write(MARKET, rows, source='r01', persistence_status='committed')


@pytest.mark.parametrize('route', ('direct', 'recipe'))
@pytest.mark.parametrize('case', ('cold_split', 'warm_split', 'warm_invalidated', 'after_calculation', 'after_head', 'warm_metadata', 'warm_normal', 'warm_unchanged', 'warm_noop'))
def test_publication_refuses_changed_file_proof(tmp_path, monkeypatch, route, case):
    root = extended(tmp_path / 'd')
    service, artifacts, recipes, historical = _domain(root)
    store = OHLCVStore(historical)
    sentinel = historical / 'sentinel.txt'
    sentinel.write_text('unrelated preserved evidence', encoding='utf-8')
    # Preserve an actual older managed head/version while refusing a new graph.
    old = _materialize(service, recipes, _sma(3))
    source = artifacts.capture_accepted_source(MARKET)
    request = DataManagerDirectArtifactRequest(MARKET, source, 'sma', {'period': 4}, ())
    recipe = _sma(4)
    recipes.save_recipe(recipe)
    plan = service.plan_artifact_materialization(DataManagerArtifactMaterializationRequest(MARKET, (recipe.recipe_id,)))
    assert not plan.blocked
    service.begin_session()
    if case != 'cold_split':
        service.inspect_market(MARKET)
    before = record(tmp_path, 'before', historical, service)
    mode = 'unchanged' if case in ('warm_unchanged', 'warm_noop') else 'metadata' if case == 'warm_metadata' else 'normal' if case == 'warm_normal' else 'split'
    fired = []
    def change():
        fired.append(True)
        if case == 'warm_noop':
            import asyncio
            from leonardo.connection import ProviderCandle
            from tests.ohlcv_test.test_xrepair_r01_source_integrity import Provider, downloader, request
            rows = store.read(MARKET)
            class NoopProvider(Provider):
                async def get_server_time_ms(self):
                    return rows[-1].ts_ms + 60_000
                async def fetch_ohlcv_historical(self, **kwargs):
                    return tuple(ProviderCandle(c.ts_ms,c.open,c.high,c.low,c.close,c.volume) for c in rows[-2:])
            download, _ = downloader(store, NoopProvider())
            result = asyncio.run(download.run_batch(request(automatic=True)))
            assert result.results[0].up_to_date
            assert hashes(historical) == before['files']
        mutation(store, mode, monkeypatch)
        record(tmp_path, 'mutation', historical, service)
        if case == 'warm_invalidated':
            service.invalidate_source(MARKET)
    if case == 'after_calculation':
        def hook(stage):
            if stage == 'before_native_artifact_publication' and not fired:
                change()
        artifacts._store._failure_hook = hook
    elif case == 'after_head':
        original = artifacts._store.replace_head
        def replace_head(path, payload):
            original(path, payload)
            if not fired:
                record(tmp_path, 'head_replaced', historical, service)
                change()
        monkeypatch.setattr(artifacts._store, 'replace_head', replace_head)
    else:
        change()
    runner = CoreRunner(TaskManager())
    app = DataManagerApplicationService(runner, service)
    done, results = Event(), []
    runner.start()
    try:
        callback = lambda r: (results.append(r), done.set())
        if route == 'direct':
            app.submit_create_direct_artifact(request, result_callback=callback)
        else:
            app.submit_execute_artifact_materialization(plan, result_callback=callback)
        assert done.wait(5), 'materialization did not settle'
    finally:
        runner.shutdown()
    after = record(tmp_path, 'terminal', historical, service)
    (tmp_path / 'task_result.json').write_text(json.dumps(dict(status=results[0].status, error_type=results[0].error_type, error=results[0].error_message)), encoding='utf-8')
    assert fired == [True]
    if mode == 'unchanged':
        assert results[0].status == 'completed', results[0]
        assert after['accepted']
    else:
        assert results[0].status == 'failed', results[0]
        assert owned(after['files']) == owned(before['files'])
        assert MARKET not in service._source_evidence
        assert not after['accepted']
    for logical in old.root_logical_artifact_ids:
        assert artifacts.load_artifact_head(MARKET, logical) is not None
    assert sentinel.read_text(encoding='utf-8') == 'unrelated preserved evidence'


def test_same_size_csv_replacement_invalidates_warm_proof(tmp_path):
    service, artifacts, _, historical = _domain(extended(tmp_path / 'd'))
    service.inspect_market(MARKET)
    path = OHLCVStore(historical).csv_path(MARKET)
    sidecar = OHLCVStore(historical).sidecar_path(MARKET)
    old, side = path.read_bytes(), sidecar.read_bytes()
    # Numeric token of equal width, leaving all metadata bytes untouched.
    new = old.replace(b'100.0', b'101.0', 1)
    if new == old:
        lines = old.splitlines(keepends=True)
        fields = lines[-1].split(b',')
        volume = fields[-1]
        index = next(i for i, b in enumerate(volume) if 48 <= b <= 56)
        fields[-1] = volume[:index] + bytes([volume[index] + 1]) + volume[index+1:]
        lines[-1] = b','.join(fields)
        new = b''.join(lines)
    assert new != old and len(new) == len(old)
    temp = path.with_suffix('.replacement')
    temp.write_bytes(new)
    os.replace(temp, path)
    assert sidecar.read_bytes() == side
    with service._operation_checks():
        with pytest.raises((ValueError, RuntimeError)):
            artifacts.capture_accepted_source(MARKET)
    assert MARKET not in service._source_evidence
    assert not service._catalog.scan().accepted


@pytest.mark.parametrize('action', ('invalidate', 'end', 'cancel'))
def test_warm_waiting_lock_rechecks_generation_session_and_cancel(tmp_path, action):
    service, artifacts, _, _ = _domain(extended(tmp_path / 'd'))
    service.inspect_market(MARKET)
    lock = service._loader._lock_for(MARKET)
    entered, completed = Event(), Event()
    cancelled = [False]
    errors = []
    class Observe:
        def __enter__(self):
            entered.set()
            lock.acquire()
        def __exit__(self, *args):
            lock.release()
    # Observation-only lock wrapper delegates the real lock unchanged.
    original = service._loader._lock_for
    service._loader._lock_for = lambda market: Observe() if market == MARKET else original(market)
    def worker():
        try:
            with service._operation_checks(cancellation_requested=lambda: cancelled[0]):
                artifacts.capture_accepted_source(MARKET)
        except Exception as error:
            errors.append(error)
        finally:
            completed.set()
    lock.acquire()
    thread = Thread(target=worker)
    try:
        thread.start()
        assert entered.wait(4)
        if action == 'invalidate':
            service.invalidate_source(MARKET)
        elif action == 'end':
            service.end_session()
        else:
            cancelled[0] = True
    finally:
        lock.release()
        thread.join(4)
        service._loader._lock_for = original
    assert completed.is_set()
    assert len(errors) == 1
    assert MARKET not in service._source_evidence
