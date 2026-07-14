"""Application-service boundary for Historical Download GUI and future AI callers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
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
    MaintenanceDeletionPlan,
    MaintenanceDeletionResult,
    MaintenanceDiscoveryReport,
    MaintenanceRepairPlan,
    MaintenanceRepairRangeResult,
    OHLCVMaintenanceService,
    repair_range_result,
)
from leonardo.ohlcv.models import DownloadBatchRequest, DownloadProgressEvent
from leonardo.ohlcv.operation_locks import OHLCVDatasetOperationLocks


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
    """Application boundary for discovery, validation, repair, and deletion."""

    def __init__(
        self,
        core_runner: CoreRunner,
        maintenance: OHLCVMaintenanceService,
        downloader: HistoricalDownloadService | None = None,
        *,
        operation_locks: OHLCVDatasetOperationLocks | None = None,
        cache_invalidator: Callable[[MarketId], bool] | None = None,
    ) -> None:
        self._core_runner = core_runner
        self._maintenance = maintenance
        self._downloader = downloader
        inherited_locks = downloader.operation_locks if downloader is not None else None
        self._operation_locks = (
            operation_locks or inherited_locks or OHLCVDatasetOperationLocks()
        )
        self._cache_invalidator = cache_invalidator

    def discover(self) -> MaintenanceDiscoveryReport:
        return self._maintenance.discover()

    def submit_deletion_plan(
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
                f"Preparing controlled deletion for {market.as_key()}",
                current=0,
                total=1,
            )
            plan = self._maintenance.plan_deletion(market, correlation_id=correlation_id)
            reporter.report(
                "Controlled deletion is ready for explicit confirmation",
                current=1,
                total=1,
                details={
                    "market_id": market.as_key(),
                    "csv_path": str(plan.evidence.csv.path),
                    "sidecar_present": plan.evidence.sidecar is not None,
                },
            )
            return plan

        return self._core_runner.submit_blocking_job(
            job,
            task_name=f"OHLCV deletion plan {market.exchange} {market.symbol} {market.timeframe}",
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={
                "operation": "ohlcv_deletion_plan",
                "market_id": market.as_key(),
            },
        )

    def submit_deletion(
        self,
        plan: MaintenanceDeletionPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(plan, MaintenanceDeletionPlan):
            raise TypeError("plan must be a MaintenanceDeletionPlan")
        correlation_id = uuid4().hex

        async def job(reporter: ProgressReporter) -> object:
            reporter.report(
                f"Waiting for exclusive access to {plan.market_id.as_key()}",
                current=0,
                total=2,
            )
            async with self._operation_locks.acquire(plan.market_id):
                reporter.report(
                    f"Deleting reviewed OHLCV files for {plan.market_id.as_key()}",
                    current=1,
                    total=2,
                )

                def delete_and_invalidate() -> MaintenanceDeletionResult:
                    result = self._maintenance.delete_dataset(
                        plan,
                        correlation_id=correlation_id,
                    )
                    cache_invalidated = False
                    if self._cache_invalidator is not None:
                        cache_invalidated = self._cache_invalidator(plan.market_id)
                    return replace(result, cache_invalidated=cache_invalidated)

                mutation_task = asyncio.create_task(asyncio.to_thread(delete_and_invalidate))
                cancellation_arrived_after_start = False
                try:
                    result = await asyncio.shield(mutation_task)
                except asyncio.CancelledError:
                    cancellation_arrived_after_start = True
                    result = await mutation_task
            reporter.report(
                f"OHLCV dataset deleted: {plan.market_id.as_key()}",
                current=2,
                total=2,
                details={
                    "market_id": plan.market_id.as_key(),
                    "cache_invalidated": result.cache_invalidated,
                    "cleanup_warnings": result.store_result.cleanup_warnings,
                    "cancellation_arrived_after_start": cancellation_arrived_after_start,
                },
            )
            return result

        return self._core_runner.submit_job(
            job,
            task_name=f"OHLCV delete {plan.market_id.exchange} {plan.market_id.symbol} {plan.market_id.timeframe}",
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={
                "operation": "ohlcv_delete",
                "market_id": plan.market_id.as_key(),
            },
        )

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

    def submit_repair_plan(
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
                f"Planning OHLCV repair for {market.as_key()}",
                current=0,
                total=1,
            )
            plan = self._maintenance.plan_repair(market, correlation_id=correlation_id)
            reporter.report(
                plan.message,
                current=1,
                total=1,
                details={
                    "market_id": market.as_key(),
                    "actionable": plan.actionable,
                    "range_count": len(plan.ranges),
                },
            )
            return plan

        return self._core_runner.submit_blocking_job(
            job,
            task_name=f"OHLCV repair plan {market.exchange} {market.symbol} {market.timeframe}",
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={
                "operation": "ohlcv_repair_plan",
                "market_id": market.as_key(),
            },
        )

    def submit_repair(
        self,
        plan: MaintenanceRepairPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(plan, MaintenanceRepairPlan):
            raise TypeError("plan must be a MaintenanceRepairPlan")
        if self._downloader is None:
            raise RuntimeError("OHLCV repair requires the historical download service")
        correlation_id = uuid4().hex

        async def job(reporter: ProgressReporter) -> object:
            total_steps = len(plan.ranges) + 2
            reporter.report(
                f"Executing reviewed OHLCV repair for {plan.market_id.as_key()}",
                current=0,
                total=total_steps,
            )
            requests = tuple(
                DownloadBatchRequest(
                    exchange=plan.market_id.exchange,
                    market_type=plan.market_id.market_type,
                    symbol=plan.market_id.symbol,
                    timeframes=(plan.market_id.timeframe,),
                    start_ms=repair_range.start_ts_ms,
                    end_ms=repair_range.end_ts_ms,
                )
                for repair_range in plan.ranges
            )

            def on_download_progress(event: DownloadProgressEvent) -> None:
                reporter.report(
                    f"Repair download: {event.message}",
                    current=event.overall_current,
                    total=total_steps,
                    details={"download_event": event},
                )

            batches = await self._downloader.run_repair_batches(
                requests,
                before_first_write=lambda: self._maintenance.assert_repair_plan_current(plan),
                progress=on_download_progress,
                correlation_id=correlation_id,
            )
            if len(batches) != len(plan.ranges):
                raise RuntimeError("repair execution did not return every reviewed range")
            range_results: list[MaintenanceRepairRangeResult] = []
            for repair_range, batch in zip(plan.ranges, batches, strict=True):
                if len(batch.results) != 1:
                    raise RuntimeError("repair range did not return exactly one dataset result")
                range_results.append(repair_range_result(repair_range, batch.results[0]))

            repaired_sidecar = await asyncio.to_thread(
                self._maintenance.mark_repair_completed,
                plan,
                tuple(range_results),
                correlation_id=correlation_id,
            )
            reporter.report(
                "Repair persistence finalized; running canonical post-repair validation",
                current=len(plan.ranges) + 1,
                total=total_steps,
            )
            validation = await asyncio.to_thread(
                self._maintenance.validate,
                plan.market_id,
                correlation_id=correlation_id,
            )
            result = self._maintenance.build_repair_result(
                plan,
                tuple(range_results),
                repaired_sidecar,
                validation,
                correlation_id=correlation_id,
            )
            reporter.report(
                f"OHLCV repair completed: {result.outcome}",
                current=total_steps,
                total=total_steps,
                details={
                    "market_id": plan.market_id.as_key(),
                    "outcome": result.outcome,
                    "accepted": result.accepted,
                },
            )
            return result

        return self._core_runner.submit_job(
            job,
            task_name=(
                f"OHLCV repair {plan.market_id.exchange} "
                f"{plan.market_id.symbol} {plan.market_id.timeframe}"
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            correlation_id=correlation_id,
            metadata={
                "operation": "ohlcv_repair",
                "market_id": plan.market_id.as_key(),
                "range_count": len(plan.ranges),
            },
        )

    def cancel(self, task_id: str) -> bool:
        return self._core_runner.cancel(task_id)
