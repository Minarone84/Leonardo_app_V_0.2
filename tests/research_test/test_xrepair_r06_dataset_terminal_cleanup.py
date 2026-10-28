"""Real Core/domain/GUI regressions plus explicitly controlled insertion races."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from threading import Event, get_ident
import time

import pytest

from leonardo.core import LeonardoApp
from leonardo.core.config import load_default_config
from leonardo.core.core_runner import CoreRunner, TaskProgress, TaskResult, TaskSubmission
from leonardo.core.task_manager import TaskManager
from leonardo.research import ResearchDatasetApplicationService
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


def _receipt(request, **values):
    root = (Path(os.environ["R02_OBSERVATIONS"]) if "R02_OBSERVATIONS" in os.environ
            else request.getfixturevalue("tmp_path") / "observations")
    root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
    (root / (name + ".json")).write_text(json.dumps(dict(node=request.node.nodeid, **values), indent=2))


def _wait(predicate, *, pump=None):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        if pump is not None:
            pump()
        time.sleep(0.001)
    assert predicate(), "bounded completion not observed"


def _settled(app, task_id):
    _wait(lambda: any(s.task_id == task_id and s.status in ("completed", "failed", "cancelled")
                      for s in app.task_manager.snapshots()))
    # Queue a fence after TaskManager settlement so its existing done callbacks
    # and the existing terminal delivery have run, without servicing GUI events.
    async def fence():
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    asyncio.run_coroutine_threadsafe(fence(), app.core_runner._loop).result(3)


@pytest.fixture
def real_app(tmp_path):
    config = load_default_config(tmp_path)
    market, frame = _accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    app.startup(); app.start_core_runtime()
    try:
        yield app, market, frame
    finally:
        app.shutdown()


@pytest.mark.parametrize("operation", ["catalog", "load", "resident"])
@pytest.mark.parametrize("delivery", ["drop", "delay", "none"])
def test_real_domain_terminal_cleanup_before_outward_delivery(real_app, operation, delivery, request):
    app, market, frame = real_app
    service = app.research_dataset_service
    dataset = app.historical_dataset_loader.load(market)
    dispatched, results, progress, rows = [], [], [], []
    def dispatcher(callback):
        dispatched.append(callback)
    for attempt in range(3):
        kwargs = dict(result_callback=None if delivery == "none" else results.append,
                      progress_callback=progress.append, callback_dispatcher=dispatcher)
        if operation == "catalog":
            submission = service.submit_catalog(**kwargs)
        elif operation == "load":
            submission = service.submit_load(market, **kwargs)
        else:
            submission = service.submit_resident_slice(dataset, 20, **kwargs)
        _settled(app, submission.task_id)
        with service._lock:
            remaining = sorted(service._cancellations)
        snapshot = next(s for s in app.task_manager.snapshots() if s.task_id == submission.task_id)
        rows.append(dict(task_id=submission.task_id, keys=remaining, status=snapshot.status,
                         correlation=snapshot.correlation_id, metadata=snapshot.metadata,
                         pending_outward=len(dispatched), delivered_results=len(results)))
        _receipt(request, owner="real Core / canonical catalog, loader and resident service",
                 operation=operation, delivery=delivery, attempts=rows)
        assert remaining == []  # Desired behavior discriminant on original source.
        assert snapshot.status == "completed" and len(snapshot.correlation_id) == 32
        assert snapshot.metadata["operation"] == {"catalog": "research_dataset_catalog", "load": "research_dataset_load", "resident": "research_resident_slice"}[operation]
        if operation != "catalog":
            assert snapshot.metadata["market_id"] == market.as_key()
        if operation == "resident":
            assert snapshot.metadata["dataset_fingerprint"] == dataset.file_sha256
            assert snapshot.metadata["center_index"] == 20
        assert len(results) == (attempt if delivery == "delay" else 0)
        if delivery == "delay":
            before = len(progress)
            for callback in dispatched:
                callback()
            dispatched.clear()
            assert len(results) == attempt + 1
            assert results[-1].task_id == submission.task_id and results[-1].status == "completed"
            emitted = progress[before:]
            assert len(emitted) >= 2 and len({id(p) for p in emitted}) == len(emitted)
            assert all(p.task_id == submission.task_id for p in emitted)
            value = results[-1].value
            if operation == "catalog":
                assert value.accepted_count == 1 and value.accepted[0].market_id == market
            else:
                assert value.row_count == len(frame)
        else:
            dispatched.clear()  # Explicitly discarded delivery; never run callbacks.
            assert progress == [] and results == []
    assert len({r["correlation"] for r in rows}) == 3


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("timing", ["early", "late"])
def test_controlled_terminal_insertion_race_and_successor(status, timing, request):
    class ControlledRunner(CoreRunner):
        """Deterministic callback timing, not a real-Core/domain execution claim."""
        def __init__(self):
            super().__init__(TaskManager()); self.calls = []
        def submit_blocking_job(self, job, **kwargs):
            task_id = str(len(self.calls) + 1)
            self.calls.append((task_id, kwargs))
            assert kwargs["callback_dispatcher"] is None
            if timing == "early":
                kwargs["result_callback"](TaskResult(task_id, status))
            return TaskSubmission(task_id, kwargs["task_name"])
    runner = ControlledRunner()
    service = ResearchDatasetApplicationService(runner, object(), catalog=object())
    queued, results = [], []
    one = service.submit_catalog(result_callback=results.append, callback_dispatcher=queued.append)
    two = service.submit_catalog(result_callback=results.append, callback_dispatcher=queued.append)
    if timing == "late":
        assert set(service._cancellations) == {one.task_id, two.task_id}
        runner.calls[0][1]["result_callback"](TaskResult(one.task_id, status))
        assert set(service._cancellations) == {two.task_id}
        runner.calls[1][1]["result_callback"](TaskResult(two.task_id, status))
    assert service._cancellations == {} and results == []
    assert len(queued) == 2
    for callback in queued:
        callback()
    assert [r.task_id for r in results] == [one.task_id, two.task_id]
    assert all(r.status == status for r in results)
    _receipt(request, owner="controlled runner insertion timing", timing=timing, status=status,
             final_keys=[], callbacks=len(results), task_ids=[r.task_id for r in results])


def test_real_failure_cancel_successor_and_dispatch_outside_lock(real_app, request):
    app, market, _ = real_app
    real_loader = app.historical_dataset_loader
    entered, release, saw_cancel = Event(), Event(), Event()
    class GatedLoader:
        mode = "failure"
        def load(self, market_id, *, progress=None, cancellation_requested=None):
            if self.mode == "failure":
                raise ValueError("R06 deliberate domain refusal")
            entered.set()
            while not release.wait(0.001):
                if cancellation_requested():
                    saw_cancel.set()
                    raise RuntimeError("cooperative cancellation observed")
            return real_loader.load(market_id, progress=progress, cancellation_requested=cancellation_requested)
    loader = GatedLoader()
    service = ResearchDatasetApplicationService(app.core_runner, loader)
    queued, observed = [], []
    def dispatcher(callback):
        observed.append(dict(thread=get_ident(), lock_owned=service._lock._is_owned(), keys=sorted(service._cancellations)))
        queued.append(callback)
    try:
        failed = service.submit_load(market, result_callback=lambda r: None, callback_dispatcher=dispatcher)
        _settled(app, failed.task_id)
        assert service._cancellations == {}
        assert next(s for s in app.task_manager.snapshots() if s.task_id == failed.task_id).status == "failed"
        loader.mode = "gate"
        first = service.submit_load(market, result_callback=lambda r: None, callback_dispatcher=dispatcher)
        assert entered.wait(3) and first.task_id in service._cancellations
        assert service.cancel(first.task_id) and saw_cancel.wait(3)
        _settled(app, first.task_id)
        assert service._cancellations == {}
        entered.clear(); saw_cancel.clear()
        successor_results = []
        successor = service.submit_load(market, result_callback=successor_results.append, callback_dispatcher=dispatcher)
        assert entered.wait(3)
        assert not service.cancel(first.task_id)
        assert successor.task_id in service._cancellations and not saw_cancel.is_set()
        # Delayed predecessor notifications cannot remove a live successor.
        for cb in queued:
            cb()
        queued.clear()
        assert successor.task_id in service._cancellations
        release.set(); _settled(app, successor.task_id)
        assert service._cancellations == {}
        for cb in queued:
            cb()
        assert len(successor_results) == 1 and successor_results[0].status == "completed"
        assert all(not row["lock_owned"] for row in observed)
        _receipt(request, owner="real Core, gated cooperative loader wrapping canonical loader",
                 failed=failed.task_id, cancelled=first.task_id, successor=successor.task_id, dispatch=observed)
    finally:
        release.set()


def test_falsey_dispatcher_preserves_inline_fallback(real_app):
    app, _, _ = real_app
    class FalseyDispatcher:
        def __bool__(self):
            return False
        def __call__(self, callback):
            raise AssertionError("falsey dispatcher must use inline fallback")
    ready = Event(); results = []; progress = []
    app.research_dataset_service.submit_catalog(callback_dispatcher=FalseyDispatcher(),
        progress_callback=progress.append, result_callback=lambda r: (results.append(r), ready.set()))
    assert ready.wait(3) and len(results) == 1 and len(progress) == 2
    assert app.research_dataset_service._cancellations == {}


def test_current_composition_real_queued_owner_delivery_and_disposal(real_app, monkeypatch, request):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication
    from leonardo.gui.research.composition import create_restored_research_suite
    from leonardo.gui.research.lifecycle_presenter import RestoredResearchLifecyclePresenter
    qt = QApplication.instance() or QApplication([])
    owner = get_ident(); delivery = []
    for name in ("_on_catalog_progress", "_on_catalog_result"):
        original = getattr(RestoredResearchLifecyclePresenter, name)
        def observe(self, event, _original=original, _name=name):
            delivery.append(dict(kind=_name, task_id=event.task_id, thread=get_ident(),
                                 qt_owner=QThread.currentThread() == self.thread()))
            return _original(self, event)
        monkeypatch.setattr(RestoredResearchLifecyclePresenter, name, observe)
    app, market, _ = real_app
    window, presenter = create_restored_research_suite(app.research_dataset_service, app.research_study_service,
        app.research_study_setup_service, app.research_workspace_snapshot_service,
        app.research_notebook_service, lambda *args: None)
    try:
        first = presenter._active_catalog_task_id
        assert first is not None
        _settled(app, first)
        assert delivery == [] and app.research_dataset_service._cancellations == {}
        _wait(lambda: presenter._active_catalog_task_id is None, pump=qt.processEvents)
        assert len(window.dataset_summaries) == 1
        assert [r["kind"] for r in delivery].count("_on_catalog_result") == 1
        assert [r["kind"] for r in delivery].count("_on_catalog_progress") == 2
        assert all(r["thread"] == owner and r["qt_owner"] for r in delivery)
        presenter._refresh_catalog()
        second = presenter._active_catalog_task_id
        _settled(app, second)
        # Completed queued notifications exist, but the real presenter is retired
        # before GUI delivery. Existing _invoke_callback must discard them.
        assert presenter.dispose()
        frozen = window.dataset_summaries
        before = list(delivery)
        qt.processEvents()
        assert delivery == before and window.dataset_summaries == frozen
        assert app.research_dataset_service._cancellations == {}
        dropped = []
        third = app.research_dataset_service.submit_load(market, progress_callback=dropped.append,
            result_callback=dropped.append, callback_dispatcher=presenter._dispatch)
        _settled(app, third.task_id); qt.processEvents()
        assert not dropped and app.research_dataset_service._cancellations == {}
        assert window.dataset_summaries == frozen
        _receipt(request, owner="real factory/presenter/queued Qt signal/Core/canonical catalog",
                 gui_owner=owner, callbacks=delivery, retired_task=second, dropped_task=third.task_id,
                 retired_widget_unchanged=True, terminal_keys=[])
    finally:
        presenter.dispose(); window.close(); window.deleteLater(); qt.processEvents()
