from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from leonardo.audit import AuditEventV1
from leonardo.core.action_registry import ActionRegistry
from leonardo.core.app import LeonardoApp
from leonardo.core.audit_log import AuditLog, CompositeAuditSink, InMemoryAuditSink, JsonlAuditSink
from leonardo.core.config import load_default_config
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.error_router import ErrorRouter
from leonardo.core.core_runner import CoreRunner
from leonardo.core.process_manager import ProcessManager
from leonardo.core.task_manager import TaskManager
from leonardo.core.window_registry import WindowRegistry


def test_app_starts_runs_background_job_and_shuts_down(tmp_path: Path) -> None:
    config = load_default_config(tmp_path)
    app = LeonardoApp(config)
    results = []
    completed = Event()

    async def work() -> str:
        await asyncio.sleep(0.01)
        return "ok"

    app.startup()
    app.start_core_runtime()
    submission = app.core_runner.submit_coroutine(
        work(),
        task_name="smoke-job",
        result_callback=lambda result: (results.append(result), completed.set()),
    )

    assert completed.wait(2.0)
    assert results[0].task_id == submission.task_id
    assert results[0].status == "completed"
    assert results[0].value == "ok"
    assert app.task_manager.get_snapshot(submission.task_id).status == "completed"

    app.shutdown()
    assert app.status == "stopped"


def test_core_runner_progress_cancellation_and_failure() -> None:
    manager = TaskManager()
    runner = CoreRunner(manager)
    progress = []
    results = []
    done = Event()
    started = Event()

    async def cancellable(reporter):
        reporter.report("started", current=1, total=10)
        started.set()
        await asyncio.Event().wait()

    runner.start()
    submission = runner.submit_job(
        cancellable,
        task_name="cancellable",
        progress_callback=progress.append,
        result_callback=lambda result: (results.append(result), done.set()),
    )
    assert started.wait(2)
    assert progress[0].message == "started"
    assert runner.cancel(submission.task_id) is True
    assert done.wait(2)
    assert results[-1].status == "cancelled"

    failed = Event()

    async def broken(_reporter):
        raise RuntimeError("boom")

    runner.submit_job(
        broken,
        task_name="broken",
        result_callback=lambda result: (results.append(result), failed.set()),
    )
    assert failed.wait(2)
    assert results[-1].status == "failed"
    assert results[-1].error_type == "RuntimeError"
    runner.shutdown()


def test_task_manager_duplicate_name_is_rejected_and_coroutine_closed() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()

        async def work() -> None:
            await gate.wait()

        manager = TaskManager()
        first = manager.create_task(work(), task_name="same")
        duplicate = work()
        with pytest.raises(ValueError, match="already active"):
            manager.create_task(duplicate, task_name="same")
        assert duplicate.cr_frame is None
        assert manager.cancel_task(first) is True
        await manager.cancel_all()

    asyncio.run(scenario())


def test_audit_event_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    memory = InMemoryAuditSink()
    log = AuditLog(CompositeAuditSink((JsonlAuditSink(path), memory)))
    event = AuditEventV1(
        event_type="dataset.saved",
        message="Dataset saved",
        category="persistence",
        action_id="download.execute",
        details={"rows": 10},
    )
    log.emit(event)
    log.close()

    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert AuditEventV1.from_dict(payload) == event
    assert memory.snapshot() == (event,)


def test_default_audit_does_not_create_runs_directory(tmp_path: Path) -> None:
    config = load_default_config(tmp_path)
    app = LeonardoApp(config)
    app.startup()
    app.shutdown()
    assert not config.paths.runs_dir.exists()


def test_explicit_jsonl_audit_creates_file(tmp_path: Path) -> None:
    config = load_default_config(tmp_path)
    config = replace(config, audit=replace(config.audit, jsonl_enabled=True))
    app = LeonardoApp(config)
    app.startup()
    app.shutdown()
    assert config.audit.jsonl_path is not None
    assert config.audit.jsonl_path.exists()


def test_registries_own_their_runtime_state() -> None:
    connections = ConnectionRegistry()
    connections.register_connection(
        "bybit-public",
        label="Bybit Public",
        protocol="websocket",
    )
    connections.register_websocket_channel(
        "bybit-public:trades",
        connection_id="bybit-public",
        label="Trades",
    )
    connections.mark_connected("bybit-public")
    connections.record_channel_received("bybit-public:trades", count=3)
    assert connections.connection_states()[0].status == "connected"
    assert connections.websocket_channel_states()[0].received_count == 3

    windows = WindowRegistry()
    windows.register_window("main.window", title="Leonardo", window_type="main")
    windows.open_window("main.window")
    windows.focus_window("main.window")
    assert windows.open_windows()[0].window_id == "main.window"
    windows.close_window("main.window")
    assert windows.open_windows() == ()


def test_action_registry_invokes_same_handler_and_audits() -> None:
    log = AuditLog(InMemoryAuditSink())
    registry = ActionRegistry(log)
    calls = []
    registry.register_action(
        action_id="download.execute",
        label="Download",
        handler=lambda value: calls.append(value) or "accepted",
        window_id="download.window",
    )
    assert registry.invoke("download.execute", 7) == "accepted"
    assert calls == [7]
    assert registry.recent_triggers()[0].action_id == "download.execute"
    assert log.snapshot()[0].action_id == "download.execute"


class _FakeHandle:
    def __init__(self) -> None:
        self.pid = 42
        self.exit_code = None
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def kill(self):
        self.terminated = True
        self.exit_code = -9


def test_process_manager_tracks_processes() -> None:
    handle = _FakeHandle()
    manager = ProcessManager(
        AuditLog(InMemoryAuditSink()),
        launcher=lambda command, cwd, env: handle,
    )
    process_id = manager.launch(("python", "-V"), label="Python")
    assert manager.active_processes()[0].pid == 42
    assert manager.terminate(process_id) is True
    assert manager.poll(process_id).status == "terminated"


def test_operational_logging_and_task_lifecycle_audit(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="leonardo")
    app = LeonardoApp(load_default_config(tmp_path))
    completed = Event()

    async def work() -> str:
        await asyncio.sleep(0.01)
        return "done"

    app.startup()
    app.start_core_runtime()
    submission = app.core_runner.submit_coroutine(
        work(),
        task_name="audited-job",
        result_callback=lambda _result: completed.set(),
    )
    assert completed.wait(2.0)

    event_types = [event.event_type for event in app.audit_log.snapshot()]
    assert "task.submitted" in event_types
    assert "task.completed" in event_types
    assert app.task_manager.get_snapshot(submission.task_id).status == "completed"

    app.shutdown()
    messages = [record.getMessage() for record in caplog.records]
    assert "Application startup completed" in messages
    assert "Core runtime startup completed" in messages
    assert any(message.startswith("Task submitted: audited-job") for message in messages)
    assert any(message.startswith("Task completed: audited-job") for message in messages)
    assert "Application shutdown completed" in messages


def test_task_cancellation_and_failure_are_audited() -> None:
    audit_log = AuditLog(InMemoryAuditSink())
    manager = TaskManager(
        audit_log=audit_log,
        error_router=ErrorRouter(audit_log),
    )
    runner = CoreRunner(manager)
    started = Event()
    cancelled = Event()
    failed = Event()

    async def cancellable(_reporter):
        started.set()
        await asyncio.Event().wait()

    async def broken(_reporter):
        raise RuntimeError("audited boom")

    runner.start()
    cancelled_submission = runner.submit_job(
        cancellable,
        task_name="audited-cancel",
        result_callback=lambda _result: cancelled.set(),
    )
    assert started.wait(2.0)
    assert runner.cancel(cancelled_submission.task_id) is True
    assert cancelled.wait(2.0)

    runner.submit_job(
        broken,
        task_name="audited-failure",
        result_callback=lambda _result: failed.set(),
    )
    assert failed.wait(2.0)
    runner.shutdown()

    event_types = [event.event_type for event in audit_log.snapshot()]
    assert "task.cancel_requested" in event_types
    assert "task.cancelled" in event_types
    assert "task.failed" in event_types
    assert "error.reported" in event_types


def test_process_terminal_failure_is_audited_once() -> None:
    handle = _FakeHandle()
    audit_log = AuditLog(InMemoryAuditSink())
    manager = ProcessManager(
        audit_log,
        launcher=lambda command, cwd, env: handle,
    )
    process_id = manager.launch(("python", "-V"), label="Broken Python")
    handle.exit_code = 3

    first = manager.poll(process_id)
    second = manager.poll(process_id)

    assert first.status == "failed"
    assert first.error_message == "Process exited with code 3"
    assert second.finished_at_utc == first.finished_at_utc
    event_types = [event.event_type for event in audit_log.snapshot()]
    assert event_types.count("process.failed") == 1


class _SlowTerminateHandle(_FakeHandle):
    def terminate(self):
        self.terminated = True


def test_process_shutdown_escalates_and_audits_terminal_state() -> None:
    handle = _SlowTerminateHandle()
    audit_log = AuditLog(InMemoryAuditSink())
    manager = ProcessManager(
        audit_log,
        launcher=lambda command, cwd, env: handle,
    )
    process_id = manager.launch(("python", "-V"), label="Slow Python")

    manager.shutdown(timeout=0.05)

    snapshot = manager.get_snapshot(process_id)
    assert snapshot.status == "terminated"
    assert snapshot.exit_code == -9
    event_types = [event.event_type for event in audit_log.snapshot()]
    assert event_types.count("process.termination_requested") == 2
    assert event_types.count("process.terminated") == 1
