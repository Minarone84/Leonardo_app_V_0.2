"""Real evidence producer to active presenter, with correlation and deduplication."""
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.ohlcv import OHLCVStore, DownloadProgressEvent
from tests.gui_test.test_historical_download_lifecycle import workflow
from tests.ohlcv_test.test_xrepair_r01_source_integrity import Provider, accepted, downloader, request, _market
from tests.data_manager_test.test_xrepair_r01_currentness import extended, mutation, owned, hashes
from tests.data_manager_test.test_update_workflow import _domain, MARKET
from tests.data_manager_test.test_direct_artifact_creation import _request
from tests.gui_test.test_data_manager_presenter import _ControlledApplication
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from PySide6.QtCore import QCoreApplication, QEvent


@pytest.mark.parametrize('mode', ('empty', 'split', 'normal', 'noop', 'error', 'cancel_write'))
def test_real_download_events_notify_active_presenter_once(workflow, tmp_path, monkeypatch, mode):
    w = workflow
    w.start()
    task_id = w.presenter.active_task_id
    w.presenter._active_download_request = request(automatic=mode == 'noop')
    store = OHLCVStore(tmp_path / 'h')
    accepted(store)
    provider = Provider()
    provider.mode = mode if mode in ('empty', 'error') else 'normal'
    service, _ = downloader(store, provider)
    if mode == 'split':
        import os
        original = os.replace
        def replace_file(src, dst):
            if Path(dst) == store.sidecar_path(_market()):
                raise OSError('split notification test')
            return original(src, dst)
        monkeypatch.setattr(os, 'replace', replace_file)
    events = []
    async def scenario():
        task = asyncio.current_task()
        def progress(event):
            events.append(event)
            w.presenter._on_task_progress(TaskProgress(task_id, event.message, details={'download_event': event}))
            if mode == 'cancel_write' and event.kind == 'page_persisted':
                task.cancel()
        try:
            result = await service.run_batch(w.presenter._active_download_request, progress=progress)
        except (OSError, ValueError, RuntimeError, asyncio.CancelledError):
            assert mode in ('split', 'error', 'cancel_write')
            result = None
        return result
    result = asyncio.run(scenario())
    assert w.notifications == ([] if mode in ('noop', 'error') else [_market()])
    if result is not None:
        w.presenter._on_download_result(TaskResult(task_id, 'completed', result))
        assert w.notifications == ([] if mode == 'noop' else [_market()])


@pytest.mark.parametrize('identity', ('active', 'old_task', 'foreign_market', 'foreign_timeframe', 'missing_market'))
def test_evidence_correlation_before_throttling(workflow, identity):
    w = workflow
    w.start()
    req = w.presenter._active_download_request
    from leonardo.data import canonicalize_market_id
    market = canonicalize_market_id(req.exchange, req.market_type, req.symbol, '1m')
    task = w.presenter.active_task_id if identity != 'old_task' else 'old-task'
    key = market.as_key() if identity != 'foreign_market' else 'bybit/linear/ETHUSDT/1m'
    event = DownloadProgressEvent('source_evidence_changed', 'actual evidence changed',
        '5m' if identity == 'foreign_timeframe' else '1m',
        details={} if identity == 'missing_market' else {'market_id': key})
    for _ in range(2):
        w.presenter._on_task_progress(TaskProgress(task, event.message, details={'download_event': event}))
    assert w.notifications == ([market] if identity == 'active' else [])


def test_notification_route_invalidates_real_dms_proof_and_refuses_publication(workflow, tmp_path, monkeypatch):
    w = workflow
    service, artifacts, _, historical = _domain(extended(tmp_path / 'd'))
    application = _ControlledApplication()
    application._service = service
    view = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(view, application)
    try:
        service.inspect_market(MARKET)
        req = _request(service, MARKET, 'sma', {'period': 4})
        before = owned(hashes(historical))
        w.start()
        w.presenter._active_download_request = request()
        w.presenter._on_ohlcv_evidence_changed = presenter.notify_external_ohlcv_change
        store = OHLCVStore(historical)
        provider = Provider()
        provider.mode = 'empty'
        download, _ = downloader(store, provider)
        def progress(event):
            w.presenter._on_task_progress(TaskProgress(w.presenter.active_task_id, event.message, details={'download_event': event}))
        asyncio.run(download.run_batch(request(), progress=progress))
        assert MARKET not in service._source_evidence
        with pytest.raises((ValueError, RuntimeError)):
            service.create_direct_artifact(req)
        assert owned(hashes(historical)) == before
    finally:
        presenter.dispose()
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(view, QEvent.Type.DeferredDelete)
