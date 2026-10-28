"""R06 public Core ownership regressions; no scheduling replacements."""
import asyncio
import gc
import inspect
import json
import os
from pathlib import Path
from threading import Event, current_thread
import warnings

import pytest

from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager


def _receipt(request, **values):
    root = (Path(os.environ["R02_OBSERVATIONS"]) if "R02_OBSERVATIONS" in os.environ
            else request.getfixturevalue("tmp_path") / "observations")
    root.mkdir(parents=True, exist_ok=True)
    import hashlib
    name = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
    (root / (name + ".json")).write_text(json.dumps(dict(node=request.node.nodeid, **values), indent=2))


def _submit(runner, route, job, **kwargs):
    if route == "coroutine":
        return runner.submit_coroutine(job, **kwargs)
    return getattr(runner, "submit_" + route)(job, **kwargs)


@pytest.mark.parametrize("route", ["job", "blocking_job", "coroutine"])
@pytest.mark.parametrize("name", ["", " \t\n", None, 7], ids=["empty", "blank", "none", "integer"])
def test_invalid_name_has_no_private_warning_or_task(route, name, request):
    manager = TaskManager()
    runner = CoreRunner(manager)
    bodies, callbacks = [], []
    async def caller():
        bodies.append("caller")
    def job(_reporter):
        bodies.append("job")
    supplied = caller() if route == "coroutine" else None
    expected = ValueError if isinstance(name, str) else TypeError
    message = "task_name must be a non-empty string" if expected is ValueError else "task_name must be a string"
    # Captured diagnostics are asserted, never filtered away. Drop all exception
    # traceback references before GC; never close Core's private wrapper here.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        runner.start()
        try:
            def rejected():
                try:
                    _submit(runner, route, supplied if supplied is not None else job,
                            task_name=name, result_callback=callbacks.append)
                except expected as error:
                    assert str(error) == message
                else:
                    pytest.fail("invalid name accepted")
            rejected()
            assert manager.snapshots() == ()
        finally:
            runner.shutdown()
        gc.collect()
    diagnostics = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    caller_state = inspect.getcoroutinestate(supplied) if supplied is not None else None
    _receipt(request, route=route, name=repr(name), warnings=diagnostics,
             caller_state=caller_state, bodies=bodies, callbacks=len(callbacks), tasks=len(manager.snapshots()))
    assert bodies == [] and callbacks == []
    if supplied is not None:
        assert caller_state == inspect.CORO_CLOSED
    assert diagnostics == []


@pytest.mark.parametrize("kind", ["sync", "async", "blocking", "coroutine"])
def test_valid_raw_name_canonical_owner_and_exact_delivery(kind, request):
    manager = TaskManager(); runner = CoreRunner(manager)
    events, results, threads = [], [], []
    done = Event()
    def body(reporter):
        threads.append(current_thread().name)
        reporter.report("one", current=1, total=1, details={"probe": True})
        return 42
    async def async_body(reporter):
        return body(reporter)
    async def coroutine():
        threads.append(current_thread().name)
        return 42
    runner.start()
    try:
        common = dict(task_name="  R06 valid \t", result_callback=lambda r: (results.append(r), done.set()),
                      correlation_id="r06-correlation", metadata={"owner": "test"})
        if kind == "coroutine":
            submission = runner.submit_coroutine(coroutine(), **common)
        else:
            submit = runner.submit_blocking_job if kind == "blocking" else runner.submit_job
            submission = submit(async_body if kind == "async" else body, progress_callback=events.append, **common)
        assert done.wait(3)
        assert submission.task_name == "  R06 valid \t"
        snapshot, = manager.snapshots()
        assert snapshot.task_name == "R06 valid" and snapshot.task_id == submission.task_id
        assert snapshot.correlation_id == "r06-correlation" and snapshot.metadata == {"owner": "test"}
        assert len(results) == 1 and results[0].task_id == submission.task_id
        assert results[0].status == "completed" and results[0].value == 42
        assert len(events) == (0 if kind == "coroutine" else 1)
        if events:
            assert events[0].task_id == submission.task_id and events[0].details == {"probe": True}
        assert threads == (["LeonardoCore"] if kind in ("async", "coroutine") else ["LeonardoWorker_0"])
        _receipt(request, task_id=submission.task_id, raw=submission.task_name, canonical=snapshot.task_name,
                 progress=len(events), terminal=len(results), threads=threads)
    finally:
        runner.shutdown()


@pytest.mark.parametrize("route", ["job", "blocking_job", "coroutine"])
def test_duplicate_rejection_allowed_duplicates_and_cancel_successor(route, request):
    runner = CoreRunner(TaskManager()); entered = Event(); release = Event()
    completed = Event(); results = []; rejected_bodies = []
    def held(_r):
        entered.set(); assert release.wait(3); return "old"
    async def held_async():
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        return "old"
    async def rejected_caller():
        rejected_bodies.append(True)
    def rejected_job(_r):
        rejected_bodies.append(True)
    def result(r):
        results.append(r); completed.set()
    runner.start()
    try:
        first = _submit(runner, route, held_async() if route == "coroutine" else held,
                        task_name="same", result_callback=result)
        assert entered.wait(3)
        supplied = rejected_caller() if route == "coroutine" else None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            with pytest.raises(ValueError, match="Task name is already active: same"):
                _submit(runner, route, supplied if supplied is not None else rejected_job, task_name=" same ")
            gc.collect()
        assert not caught and not rejected_bodies
        if supplied is not None:
            assert inspect.getcoroutinestate(supplied) == inspect.CORO_CLOSED
        # Duplicate-name allowance is explicit, with its own real TaskManager ID.
        allowed_done = Event(); allowed_results = []
        allowed = runner.submit_job(lambda _: 7, task_name="same", allow_duplicate_name=True,
                                    result_callback=lambda r: (allowed_results.append(r), allowed_done.set()))
        assert allowed_done.wait(3) and allowed_results[0].value == 7
        assert allowed.task_id != first.task_id
        assert runner.cancel(first.task_id) and completed.wait(3)
        assert results[0].status == "cancelled"
        successor_entered = Event(); successor_release = Event(); successor_done = Event(); successor_results = []
        def successor_job(_):
            successor_entered.set(); assert successor_release.wait(3); return "successor"
        successor = runner.submit_job(successor_job, task_name="same",
            result_callback=lambda r: (successor_results.append(r), successor_done.set()))
        try:
            assert successor_entered.wait(3)
            assert not runner.cancel(first.task_id)
            assert not successor_done.is_set()
        finally:
            successor_release.set()
        assert successor_done.wait(3) and successor_results[0].value == "successor"
        _receipt(request, predecessor=first.task_id, allowed=allowed.task_id, successor=successor.task_id,
                 warnings=[], old_status=results[0].status, successor_status=successor_results[0].status)
    finally:
        release.set(); runner.shutdown()


def test_public_precedence_and_none_callbacks():
    runner = CoreRunner(TaskManager())
    with pytest.raises(TypeError, match="job must be callable"):
        runner.submit_job(None, task_name="")
    with pytest.raises(RuntimeError, match="not running"):
        runner.submit_job(lambda _: None, task_name="")
    runner.start()
    try:
        ran = Event()
        runner.submit_job(lambda _: ran.set(), task_name="no callbacks")
        assert ran.wait(3)
        runner.stop_accepting_submissions()
        with pytest.raises(RuntimeError, match="not accepting"):
            runner.submit_job(lambda _: None, task_name="")
    finally:
        runner.shutdown()
