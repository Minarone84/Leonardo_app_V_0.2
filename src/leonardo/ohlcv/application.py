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
from leonardo.data import MarketId
from leonardo.ohlcv.download_service import HistoricalDownloadService
from leonardo.ohlcv.maintenance import (
    MaintenanceDiscoveryReport,
    OHLCVMaintenanceService,
)
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


class OHLCVMaintenanceApplicationService:
    """Application boundary for dataset discovery and canonical validation."""

    def __init__(self, core_runner: CoreRunner, maintenance: OHLCVMaintenanceService) -> None:
        self._core_runner = core_runner
        self._maintenance = maintenance

    def discover(self) -> MaintenanceDiscoveryReport:
        return self._maintenance.discover()

    def submit_validation(
        self,
        market: MarketId,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        correlation_id = uuid4().hex

        def job(reporter: ProgressReporter) -> object:
            reporter.report(
                f"Validating OHLCV dataset {market.as_key()}",
                current=0,
                total=1,
            )
            result = self._maintenance.validate(market, correlation_id=correlation_id)
            publication_state = "published" if result.sidecar_published else "not published"
            reporter.report(
                (
                    f"OHLCV validation {result.report.status} for {market.as_key()}; "
                    f"evidence {publication_state}"
                ),
                current=1,
                total=1,
                details={
                    "market_id": market.as_key(),
                    "validation_status": result.report.status,
                    "sidecar_published": result.sidecar_published,
                    "accepted": result.accepted,
                },
            )
            return result

        return self._core_runner.submit_blocking_job(
            job,
            task_name=f"OHLCV validation {market.exchange} {market.symbol} {market.timeframe}",
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={
                "operation": "ohlcv_validate",
                "market_id": market.as_key(),
            },
        )

    def cancel(self, task_id: str) -> bool:
        return self._core_runner.cancel(task_id)
