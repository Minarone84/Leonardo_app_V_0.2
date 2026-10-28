from __future__ import annotations

import asyncio
import gc
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from leonardo.core.app import LeonardoApp
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.config import load_default_config
from leonardo.core.core_runner import CoreRunner
from leonardo.core.process_manager import ProcessManager
from leonardo.core.task_manager import TaskManager


class _Handle:
    def __init__(self, pid):
        self.pid = pid
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.exit_code = 0

    def kill(self):
        self.exit_code = -9


def _finish_disposable_runtime(runner, thread, loop):
    thread.join(2)
    if thread.is_alive():
        runner.shutdown(timeout=2)
        thread.join(2)
    assert not thread.is_alive()
    # Red-phase shutdown failures may abandon an open loop. Only clean it after
    # its owner thread has exited; assertions observe the failure before cleanup.
    if not loop.is_closed():
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


@pytest.fixture
def blocked_runtime(tmp_path, monkeypatch):
    app = LeonardoApp(load_default_config(tmp_path))
    child = _Handle(100)
    monkeypatch.setattr(app.process_manager, "_launcher", lambda *args, **kwargs: child)
    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    entered, release, finished = Event(), Event(), Event()

    def work(_reporter):
        entered.set()
        try:
            assert release.wait(10), "test worker safety timeout"
        finally:
            finished.set()

    app.startup()
    app.start_core_runtime()
    app.process_manager.launch(("fake",), label="controlled child")
    app.connection_registry.register_connection("controlled", label="Controlled")
    app.connection_registry.mark_connected("controlled")
    app.window_registry.register_window("controlled", title="Controlled")
    app.window_registry.open_window("controlled")
    app.core_runner.submit_blocking_job(work, task_name="held-worker")
    assert entered.wait(2)
    runner = app.core_runner
    thread, loop = runner._thread, runner._loop
    try:
        yield SimpleNamespace(app=app, runner=runner, release=release, finished=finished,
                              thread=thread, loop=loop, child=child, errors=errors)
    finally:
        release.set()
        assert finished.wait(2)
        _finish_disposable_runtime(runner, thread, loop)
        app.process_manager.shutdown(timeout=.2)
        app.connection_registry.shutdown_tracking()
        app.window_registry.close_window("controlled")
        app.audit_log.close()


def test_shutdown_retry_after_worker_settlement_reaches_application_cleanup(blocked_runtime):
    state = blocked_runtime
    with pytest.raises(TimeoutError):
        state.app.shutdown(timeout=.05)
    assert state.app.status == "failed" and state.child.poll() is None
    state.release.set()
    assert state.finished.wait(2)
    state.thread.join(2)
    assert not state.thread.is_alive()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        state.app.shutdown(timeout=.5)
        gc.collect()
    assert not caught
    assert state.loop.is_closed() and not state.errors
    assert state.child.poll() is not None
    assert state.app.connection_registry.connection_states()[0].status == "disconnected"
    assert state.app.window_registry.list_windows()[0].status == "closed"
    assert state.app.status == "failed"  # Cleanup does not erase the previous failure.


def test_shutdown_retry_during_drain_never_reports_premature_success(blocked_runtime):
    state = blocked_runtime
    with pytest.raises(TimeoutError):
        state.runner.shutdown(timeout=.05)
    with pytest.raises(TimeoutError):
        state.runner.shutdown(timeout=.05)
    assert state.thread.is_alive() and not state.finished.is_set()
    assert not state.runner.is_accepting_submissions and not state.errors
    state.release.set()
    assert state.finished.wait(2)
    state.runner.shutdown(timeout=2)
    assert not state.thread.is_alive() and state.loop.is_closed() and not state.errors


def test_start_and_submissions_cannot_reopen_a_draining_runtime(blocked_runtime):
    state = blocked_runtime
    with pytest.raises(TimeoutError):
        state.runner.shutdown(timeout=.05)
    with pytest.raises(RuntimeError, match="shutting down"):
        state.runner.start()
    with pytest.raises(RuntimeError, match="not accepting"):
        state.runner.submit_job(lambda _: None, task_name="rejected")
    async def rejected():
        return None
    coroutine = rejected()
    with pytest.raises(RuntimeError):
        state.runner.submit_coroutine(coroutine, task_name="rejected-coroutine")
    assert coroutine.cr_frame is None
    assert not state.runner.is_accepting_submissions


def test_shutdown_retries_share_pending_cancellation(monkeypatch):
    manager = TaskManager()
    runner = CoreRunner(manager)
    entered, cancelled, release = Event(), Event(), Event()
    calls = []
    original = manager.cancel_all
    async def count_cancel():
        calls.append(1)
        await original()
    monkeypatch.setattr(manager, "cancel_all", count_cancel)
    async def work(_reporter):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            while not release.is_set():
                await asyncio.sleep(.005)
    runner.start()
    thread, loop = runner._thread, runner._loop
    try:
        runner.submit_job(work, task_name="cooperative-cancel")
        assert entered.wait(2)
        with pytest.raises(TimeoutError):
            runner.shutdown(timeout=.05)
        assert cancelled.is_set()
        with pytest.raises(TimeoutError):
            runner.shutdown(timeout=.05)
        assert calls == [1]
    finally:
        release.set()
        _finish_disposable_runtime(runner, thread, loop)


def test_normal_shutdown_is_repeatable_and_explicit_restart_delivers_results():
    runner = CoreRunner(TaskManager())
    for expected in (1, 2):
        done, results = Event(), []
        runner.start()
        thread, loop = runner._thread, runner._loop
        runner.start()
        assert runner._thread is thread
        try:
            runner.submit_job(lambda _: expected, task_name="normal",
                              result_callback=lambda result: (results.append(result), done.set()))
            assert done.wait(2)
            assert results[0].status == "completed" and results[0].value == expected
        finally:
            runner.shutdown(timeout=2)
        runner.shutdown(timeout=2)
        assert not thread.is_alive() and loop.is_closed()


@pytest.mark.parametrize("limit,jobs", [(3, 12), (500, 620)])
def test_history_trims_terminal_records_beyond_an_older_active_task(limit, jobs):
    async def scenario():
        manager = TaskManager(history_limit=limit)
        gate = asyncio.Event()
        async def held():
            await gate.wait()
        async def quick():
            return "result"
        first = manager.create_task(held(), task_name="oldest-active")
        created = []
        try:
            for i in range(jobs):
                identity = manager.create_task(quick(), task_name=str(i))
                created.append(identity)
                assert await manager.wait_task(identity) == "result"
                await asyncio.sleep(0)
            assert [s.task_id for s in manager.snapshots()] == [first] + created[-(limit-1):]
            manager.update_progress(first, message="still active", current=1, total=2)
            assert manager.get_snapshot(first).progress_message == "still active"
            gate.set()
            await manager.wait_task(first)
            await asyncio.sleep(0)
            assert len(manager.snapshots()) <= limit
        finally:
            gate.set()
            await manager.cancel_all()
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_history_settlement_preserves_waiters_and_terminal_audit(outcome):
    async def scenario():
        audit = AuditLog(InMemoryAuditSink())
        manager = TaskManager(history_limit=3, audit_log=audit)
        gate = asyncio.Event()
        async def work(i):
            await gate.wait()
            if outcome == "failed":
                raise ValueError(f"expected-{i}")
            return i
        ids = [manager.create_task(work(i), task_name=str(i)) for i in range(7)]
        waiters = [asyncio.create_task(manager.wait_task(identity)) for identity in ids]
        await asyncio.sleep(0)
        assert len(manager.active_tasks()) == 7 and len(manager.snapshots()) == 7
        if outcome == "cancelled":
            for identity in ids:
                assert manager.cancel_task(identity)
        else:
            gate.set()
        values = await asyncio.gather(*waiters, return_exceptions=True)
        await asyncio.sleep(0)
        assert len(manager.snapshots()) == 3 and not manager.active_tasks()
        assert [s.task_id for s in manager.snapshots()] == ids[-3:]
        if outcome == "completed":
            assert values == list(range(7))
        else:
            expected = ValueError if outcome == "failed" else asyncio.CancelledError
            assert all(isinstance(value, expected) for value in values)
        terminal = [e for e in audit.snapshot() if e.event_type == f"task.{outcome}"]
        assert sorted(e.task_id for e in terminal) == sorted(ids)
        with pytest.raises(KeyError):
            await manager.wait_task(ids[0])
    asyncio.run(scenario())


def test_core_runner_delivers_all_results_under_history_pressure():
    audit = AuditLog(InMemoryAuditSink(max_events=1000))
    manager = TaskManager(history_limit=3, audit_log=audit)
    runner = CoreRunner(manager)
    entered, release, held_done = Event(), Event(), Event()
    results = []
    def held(_reporter):
        entered.set()
        assert release.wait(10)
        return "held"
    runner.start()
    try:
        runner.submit_job(held, task_name="held", result_callback=lambda r: (results.append(r), held_done.set()))
        assert entered.wait(2)
        for i in range(30):
            done = Event()
            async def quick(_reporter, value=i):
                if value % 3 == 1:
                    raise ValueError(f"expected-{value}")
                if value % 3 == 2:
                    raise asyncio.CancelledError()
                return value
            runner.submit_job(quick, task_name=f"quick-{i}", result_callback=lambda r: (results.append(r), done.set()))
            assert done.wait(2)
        release.set()
        assert held_done.wait(2)
        assert [r.status for r in results] == ["completed", "failed", "cancelled"]*10 + ["completed"]
        assert [r.value for r in results[:30:3]] == list(range(0, 30, 3))
        assert results[-1].value == "held" and len({r.task_id for r in results}) == 31
        terminal = [e for e in audit.snapshot() if e.event_type in {"task.completed", "task.failed", "task.cancelled"}]
        assert sorted(e.task_id for e in terminal) == sorted(r.task_id for r in results)
        assert len(manager.snapshots()) <= 3
    finally:
        release.set()
        runner.shutdown(timeout=2)


@pytest.mark.parametrize("same_id", [True, False])
def test_overlapping_process_launches_preserve_identity_and_handle_ownership(same_id):
    entered, release, guard = Event(), Event(), Lock()
    handles = []
    def launcher(command, *, cwd, env):
        with guard:
            handle = _Handle(100 + len(handles))
            handles.append(handle)
            first = len(handles) == 1
        if first:
            entered.set()
            assert release.wait(5)
        return handle
    audit = AuditLog(InMemoryAuditSink())
    manager = ProcessManager(audit, launcher=launcher)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(manager.launch, ("fake",), label="first", process_id="first")
            assert entered.wait(2)
            second = pool.submit(manager.launch, ("fake",), label="second", process_id="first" if same_id else "second")
            try:
                if same_id:
                    with pytest.raises(ValueError, match="Process already registered"):
                        second.result(timeout=2)
                    assert len(handles) == 1
                else:
                    assert second.result(timeout=2) == "second"
                    assert len(handles) == 2
            finally:
                release.set()
            assert first.result(timeout=2) == "first"
        expected = 1 if same_id else 2
        assert len(manager.snapshots()) == len(handles) == expected
        manager.shutdown(timeout=.2)
        assert all(handle.poll() is not None for handle in handles)
        assert sum(e.event_type == "process.started" for e in audit.snapshot()) == expected
        manager.snapshots()
        assert sum(e.event_type == "process.terminated" for e in audit.snapshot()) == expected
    finally:
        release.set()
        for handle in handles:
            handle.kill()


def test_process_launch_failure_releases_identity_and_sequential_duplicate_rejects():
    calls = []
    child = _Handle(100)
    def launcher(command, *, cwd, env):
        calls.append(command)
        if len(calls) == 1:
            raise OSError("controlled launch failure")
        return child
    manager = ProcessManager(AuditLog(InMemoryAuditSink()), launcher=launcher)
    try:
        with pytest.raises(OSError, match="controlled launch failure"):
            manager.launch(("fake",), label="first", process_id="same")
        assert manager.launch(("fake",), label="retry", process_id="same") == "same"
        with pytest.raises(ValueError, match="Process already registered"):
            manager.launch(("fake",), label="duplicate", process_id="same")
        assert len(calls) == 2
        manager.shutdown(timeout=.2)
        assert child.poll() is not None
    finally:
        child.kill()
