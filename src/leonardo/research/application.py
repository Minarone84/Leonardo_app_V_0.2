"""Core-supervised application service for Research dataset reads."""

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
from leonardo.research.catalog import DatasetCatalogReport
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.resident import ResidentOHLCVSlice


class DatasetCatalog(Protocol):
    def scan(self) -> DatasetCatalogReport: ...


class DatasetLoader(Protocol):
    def load(
        self,
        market_id: MarketId,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> HistoricalDataset: ...


class ResidentSlicer(Protocol):
    def slice_around_index(
        self,
        dataset: HistoricalDataset,
        center_index: int,
    ) -> ResidentOHLCVSlice: ...


class ResearchDatasetApplicationService:
    """Submit read-only Research data work to Core worker threads.

    The service coordinates execution only.  OHLCV acceptance remains owned by
    the catalog/validator boundary, full dataset truth remains owned by the
    loader, resident projections remain owned by the resident-slice service, and
    task lifecycle remains owned by ``TaskManager`` through ``CoreRunner``.
    """

    def __init__(
        self,
        core_runner: CoreRunner,
        loader: DatasetLoader,
        *,
        catalog: DatasetCatalog | None = None,
        resident_slices: ResidentSlicer | None = None,
    ) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be a CoreRunner")
        self._core_runner = core_runner
        self._loader = loader
        self._catalog = catalog
        self._resident_slices = resident_slices
        self._cancellations: dict[str, Event] = {}
        self._lock = RLock()

    def submit_catalog(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        catalog = self._catalog
        if catalog is None:
            raise RuntimeError("Research accepted-dataset catalog is not configured")
        cancellation = Event()

        def job(reporter: ProgressReporter) -> DatasetCatalogReport:
            _raise_if_cancelled(cancellation, "catalog scan")
            reporter.report("Scanning accepted historical datasets", current=0, total=None)
            report = catalog.scan()
            _raise_if_cancelled(cancellation, "catalog publication")
            reporter.report(
                f"Research catalog ready: {report.accepted_count} accepted datasets",
                current=report.accepted_count,
                total=report.accepted_count,
                details={"rejected_count": report.rejected_count},
            )
            return report

        return self._submit(
            job,
            task_name="Research accepted dataset catalog",
            operation="research_dataset_catalog",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=False,
            metadata={},
        )

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
            _raise_if_cancelled(cancellation, "dataset publication")
            reporter.report(
                f"Historical dataset ready: {dataset.row_count} candles",
                current=dataset.row_count,
                total=dataset.row_count,
            )
            return dataset

        return self._submit(
            job,
            task_name=f"Research dataset load {market_id.as_key()}",
            operation="research_dataset_load",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=True,
            metadata={"market_id": market_id.as_key()},
        )

    def submit_resident_slice(
        self,
        dataset: HistoricalDataset,
        center_index: int,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(dataset, HistoricalDataset):
            raise TypeError("dataset must be a HistoricalDataset")
        if type(center_index) is not int:
            raise TypeError("center_index must be an integer")
        slicer = self._resident_slices
        if slicer is None:
            raise RuntimeError("Research resident-slice service is not configured")
        cancellation = Event()

        def job(reporter: ProgressReporter) -> ResidentOHLCVSlice:
            _raise_if_cancelled(cancellation, "resident-slice calculation")
            reporter.report(
                f"Preparing resident candles around index {center_index}",
                current=0,
                total=None,
            )
            resident = slicer.slice_around_index(dataset, center_index)
            _raise_if_cancelled(cancellation, "resident-slice publication")
            reporter.report(
                f"Resident candles ready: {resident.row_count}",
                current=resident.row_count,
                total=resident.row_count,
            )
            return resident

        return self._submit(
            job,
            task_name=f"Research resident slice {dataset.market_id.as_key()}",
            operation="research_resident_slice",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=True,
            metadata={
                "market_id": dataset.market_id.as_key(),
                "dataset_fingerprint": dataset.file_sha256,
                "center_index": center_index,
            },
        )

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            cancellation = self._cancellations.get(task_id)
        if cancellation is not None:
            cancellation.set()
        return self._core_runner.cancel(task_id)

    def _submit(
        self,
        job: Callable[[ProgressReporter], object],
        *,
        task_name: str,
        operation: str,
        cancellation: Event,
        progress_callback: ProgressCallback | None,
        result_callback: ResultCallback | None,
        callback_dispatcher: CallbackDispatcher | None,
        allow_duplicate_name: bool,
        metadata: dict[str, object],
    ) -> TaskSubmission:
        finished = Event()
        task_id_ref: list[str] = []
        correlation_id = uuid4().hex

        def on_result(result: TaskResult) -> None:
            finished.set()
            task_id = task_id_ref[0] if task_id_ref else result.task_id
            with self._lock:
                self._cancellations.pop(task_id, None)
            if result_callback is not None:
                result_callback(result)

        submission = self._core_runner.submit_blocking_job(
            job,
            task_name=task_name,
            progress_callback=progress_callback,
            result_callback=on_result,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=allow_duplicate_name,
            correlation_id=correlation_id,
            metadata={"operation": operation, **metadata},
        )
        task_id_ref.append(submission.task_id)
        with self._lock:
            if not finished.is_set():
                self._cancellations[submission.task_id] = cancellation
        return submission


def _raise_if_cancelled(cancellation: Event, operation: str) -> None:
    if cancellation.is_set():
        raise RuntimeError(f"{operation} cancelled before publication")
