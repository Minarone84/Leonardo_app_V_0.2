"""Application-service boundary for Historical Download GUI and future AI callers."""

from __future__ import annotations

from uuid import uuid4

from leonardo.core.core_runner import (
    CallbackDispatcher,
    CoreRunner,
    ProgressCallback,
    ProgressReporter,
    ResultCallback,
    TaskSubmission,
)
from leonardo.ohlcv.download_service import HistoricalDownloadService
from leonardo.ohlcv.models import DownloadBatchRequest, DownloadProgressEvent


class HistoricalDownloadApplicationService:
    def __init__(self, core_runner: CoreRunner, downloader: HistoricalDownloadService) -> None:
        self._core_runner = core_runner
        self._downloader = downloader

    def submit_preflight(
        self,
        request: DownloadBatchRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        correlation_id = uuid4().hex

        async def job(reporter: ProgressReporter) -> object:
            reporter.report("Preparing historical OHLCV preflight")
            result = await self._downloader.preflight_batch(request)
            reporter.report(
                "Historical OHLCV preflight ready",
                current=len(result.items),
                total=len(result.items),
            )
            return result

        return self._core_runner.submit_job(
            job,
            task_name=f"OHLCV preflight {request.exchange} {request.symbol}",
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={"operation": "ohlcv_preflight"},
        )

    def submit_download(
        self,
        request: DownloadBatchRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        correlation_id = uuid4().hex

        async def job(reporter: ProgressReporter) -> object:
            def on_progress(event: DownloadProgressEvent) -> None:
                reporter.report(
                    event.message,
                    current=event.current,
                    total=event.total,
                    details={"download_event": event},
                )

            return await self._downloader.run_batch(
                request,
                progress=on_progress,
                correlation_id=correlation_id,
            )

        return self._core_runner.submit_job(
            job,
            task_name=f"OHLCV download {request.exchange} {request.symbol}",
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={"operation": "ohlcv_download"},
        )

    def cancel(self, task_id: str) -> bool:
        return self._core_runner.cancel(task_id)
