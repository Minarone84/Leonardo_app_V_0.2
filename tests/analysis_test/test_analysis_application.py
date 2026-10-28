"""Shared-Core cancellation, worker drain and session lifecycle checks."""
import asyncio
from threading import Event
import time

import pytest

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.service import AnalysisService
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_analysis_service import make_database, request, reference


def wait_until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(.005)
    assert predicate()


def callbacks(results, done):
    return dict(result_callback=lambda result: (results.append(result), done.set()), callback_dispatcher=lambda callback: callback())


def test_real_store_operations_and_runtime_visibility(tmp_path):
    store, manifest, _ = make_database(tmp_path)
    manager = TaskManager()
    runner = CoreRunner(manager)
    app = AnalysisApplicationService(runner, AnalysisService(store))
    runner.start()
    session = app.begin_session()
    try:
        for submit in (lambda **kw: app.submit_catalog(session, **kw),
                       lambda **kw: app.submit_columns(session, reference(manifest), **kw),
                       lambda **kw: app.submit_analysis(session, request(manifest, "delta"), **kw)):
            results, done = [], Event()
            submission = submit(**callbacks(results, done))
            assert done.wait(5)
            assert results[0].status == "completed"
            assert manager.get_snapshot(submission.task_id).status == "completed"
            assert manager.get_snapshot(submission.task_id).metadata["area"] == "analysis"
            assert not app.is_busy(session)
        assert len(results[0].value.columns) == 1
    finally:
        app.end_session(session)
        runner.shutdown()


def test_cancelled_worker_must_drain_before_replacement_or_terminal_delivery(tmp_path, monkeypatch):
    store, _manifest, _ = make_database(tmp_path)
    service = AnalysisService(store)
    started, release, done = Event(), Event(), Event()
    def work(*, checkpoint, progress):
        started.set()
        assert release.wait(5)
        checkpoint()
    monkeypatch.setattr(service, 'catalog', work)
    manager = TaskManager()
    runner = CoreRunner(manager)
    app = AnalysisApplicationService(runner, service)
    session, results = app.begin_session(), []
    runner.start()
    try:
        submission = app.submit_catalog(session, **callbacks(results, done))
        assert started.wait(2)
        with pytest.raises(RuntimeError, match="still running"):
            app.submit_catalog(session, **callbacks([], Event()))
        assert app.cancel(session)
        wait_until(lambda: manager.get_snapshot(submission.task_id).status == 'cancelled')
        assert app.is_busy(session) and app.has_draining_workers and not done.is_set()
        another = app.begin_session()
        with pytest.raises(RuntimeError, match="cancelling"):
            app.submit_catalog(another, **callbacks([], Event()))
        app.end_session(another)
        quick = Event()
        async def quick_job():
            quick.set()
        runner.submit_coroutine(quick_job(), task_name='during-cancel')
        assert quick.wait(1)
        release.set()
        assert done.wait(2) and results[0].status == 'cancelled'
        assert not app.is_busy(session) and not app.has_draining_workers
    finally:
        release.set()
        app.end_session(session)
        runner.shutdown()


def test_cancel_before_executor_entry_does_not_leak_or_execute(tmp_path, monkeypatch):
    store, _manifest, _ = make_database(tmp_path)
    service = AnalysisService(store)
    calls = []
    monkeypatch.setattr(service, 'catalog', lambda **kw: calls.append('executed'))
    runner = CoreRunner(TaskManager(), max_worker_threads=1)
    app = AnalysisApplicationService(runner, service)
    release, started, done = Event(), Event(), Event()
    runner.start()
    def occupy(reporter):
        started.set()
        assert release.wait(5)
    runner.submit_blocking_job(occupy, task_name='occupied')
    assert started.wait(2)
    session, results = app.begin_session(), []
    try:
        app.submit_catalog(session, **callbacks(results, done))
        app.cancel(session)
        assert done.wait(2)
        assert not app.is_busy(session) and not calls
        release.set()
    finally:
        release.set()
        app.end_session(session)
        runner.shutdown()
    assert not calls


def test_disposed_session_suppresses_late_callbacks_and_releases_worker(tmp_path, monkeypatch):
    store, _manifest, _ = make_database(tmp_path)
    service = AnalysisService(store)
    started, release = Event(), Event()
    def work(**kw):
        started.set()
        assert release.wait(5)
        return "late success"
    monkeypatch.setattr(service, 'catalog', work)
    runner = CoreRunner(TaskManager())
    app = AnalysisApplicationService(runner, service)
    runner.start()
    session, results = app.begin_session(), []
    try:
        app.submit_catalog(session, **callbacks(results, Event()))
        assert started.wait(2)
        app.end_session(session)
        release.set()
        wait_until(lambda: not app.is_busy(session))
        assert results == []
        with pytest.raises(RuntimeError, match='closed'):
            app.submit_catalog(session, **callbacks([], Event()))
    finally:
        release.set()
        runner.shutdown()


def test_failed_submission_can_retry_and_unexpected_error_is_routed(tmp_path, monkeypatch):
    store, _manifest, _ = make_database(tmp_path)
    service = AnalysisService(store)
    runner = CoreRunner(TaskManager())
    app = AnalysisApplicationService(runner, service)
    session = app.begin_session()
    with pytest.raises(RuntimeError):
        app.submit_catalog(session, **callbacks([], Event()))
    assert not app.is_busy(session)
    runner.start()
    def broken(**kw):
        raise RuntimeError('unexpected test calculation')
    monkeypatch.setattr(service, 'catalog', broken)
    results, done = [], Event()
    try:
        app.submit_catalog(session, **callbacks(results, done))
        assert done.wait(2)
        assert results[0].status == 'failed' and 'unexpected test calculation' in results[0].error_message
        assert not app.is_busy(session)
    finally:
        app.end_session(session)
        runner.shutdown()
