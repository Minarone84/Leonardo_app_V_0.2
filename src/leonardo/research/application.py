"""Core-supervised application service for full Research dataset loading."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock
from typing import Protocol
from uuid import uuid4

from leonardo.core.core_runner import (
    CallbackDispatcher,
    CoreRunner,
    ProgressCallback,
    ProgressReporter,
    ResultCallback,
    TaskResult,
    TaskSubmission,
)
from leonardo.data import MarketId
from leonardo.research.dataset import HistoricalDataset


class DatasetLoader(Protocol):
    def load(
        self,
        market_id: MarketId,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> HistoricalDataset: ...


class ResearchDatasetApplicationService:
    """Submit full dataset reads to Core without exposing worker details to GUI."""

    def __init__(self, core_runner: CoreRunner, loader: DatasetLoader) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be a CoreRunner")
        self._core_runner = core_runner
        self._loader = loader
        self._cancellations: dict[str, Event] = {}
        self._lock = RLock()

    def submit_load(
        self,
        market_id: MarketId,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        cancellation = Event()
        finished = Event()
        task_id_ref: list[str] = []
        correlation_id = uuid4().hex

        def job(reporter: ProgressReporter) -> HistoricalDataset:
            reporter.report(
                f"Loading historical dataset {market_id.as_key()}",
                current=0,
                total=None,
            )

            def on_progress(current: int, total: int) -> None:
                if cancellation.is_set():
                    return
                reporter.report(
                    f"Loading historical candles {current}/{total}",
                    current=current,
                    total=total,
                )

            dataset = self._loader.load(
                market_id,
                progress=on_progress,
                cancellation_requested=cancellation.is_set,
            )
            if cancellation.is_set():
                # The Core awaiter may already be cancelled. Never publish a completed
                # value from a cooperatively cancelled worker operation.
                raise RuntimeError("historical dataset load cancelled before publication")
            reporter.report(
                f"Historical dataset ready: {dataset.row_count} candles",
                current=dataset.row_count,
                total=dataset.row_count,
            )
            return dataset

        def on_result(result: TaskResult) -> None:
            finished.set()
            task_id = task_id_ref[0] if task_id_ref else result.task_id
            with self._lock:
                self._cancellations.pop(task_id, None)
            if result_callback is not None:
                result_callback(result)

        submission = self._core_runner.submit_blocking_job(
            job,
            task_name=f"Research dataset load {market_id.as_key()}",
            progress_callback=progress_callback,
            result_callback=on_result,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=True,
            correlation_id=correlation_id,
            metadata={
                "operation": "research_dataset_load",
                "market_id": market_id.as_key(),
            },
        )
        task_id_ref.append(submission.task_id)
        with self._lock:
            if not finished.is_set():
                self._cancellations[submission.task_id] = cancellation
        return submission

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            cancellation = self._cancellations.get(task_id)
        if cancellation is not None:
            cancellation.set()
        return self._core_runner.cancel(task_id)
