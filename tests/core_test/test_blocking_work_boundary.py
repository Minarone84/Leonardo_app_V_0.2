from __future__ import annotations

import asyncio
import time
from threading import Event

from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager


def test_blocking_job_does_not_block_core_event_loop() -> None:
    runner = CoreRunner(TaskManager())
    release = Event()
    blocking_started = Event()
    async_completed = Event()
    blocking_completed = Event()

    def blocking(_reporter) -> str:
        blocking_started.set()
        release.wait(2.0)
        return "blocking-done"

    async def quick() -> str:
        await asyncio.sleep(0.01)
        return "async-done"

    runner.start()
    started_at = time.monotonic()
    runner.submit_blocking_job(
        blocking,
        task_name="blocking",
        result_callback=lambda _result: blocking_completed.set(),
    )
    submit_elapsed = time.monotonic() - started_at
    assert submit_elapsed < 0.5
    assert blocking_started.wait(1.0)

    runner.submit_coroutine(
        quick(),
        task_name="quick",
        result_callback=lambda _result: async_completed.set(),
    )
    assert async_completed.wait(1.0)
    assert not blocking_completed.is_set()

    release.set()
    assert blocking_completed.wait(1.0)
    runner.shutdown()


def test_legacy_submit_job_routes_synchronous_callable_to_worker() -> None:
    runner = CoreRunner(TaskManager())
    release = Event()
    started = Event()
    quick_completed = Event()

    def blocking(_reporter) -> None:
        started.set()
        release.wait(2.0)

    async def quick(_reporter) -> None:
        await asyncio.sleep(0.01)

    runner.start()
    before = time.monotonic()
    runner.submit_job(blocking, task_name="legacy-blocking")
    assert time.monotonic() - before < 0.5
    assert started.wait(1.0)
    runner.submit_job(
        quick,
        task_name="quick-after-legacy",
        result_callback=lambda _result: quick_completed.set(),
    )
    assert quick_completed.wait(1.0)
    release.set()
    runner.shutdown()
