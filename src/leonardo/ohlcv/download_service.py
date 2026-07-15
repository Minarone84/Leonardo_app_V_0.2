"""Historical OHLCV planning, download execution, and persistence orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager

from leonardo.audit import AuditEventV1
from leonardo.connection import (
    ConnectionApplicationService,
    HistoricalOHLCVProvider,
    HistoricalProviderRequestError,
)
from leonardo.core.audit_log import AuditLog
from leonardo.data import MarketId, canonicalize_market_id, timeframe_duration_ms
from leonardo.ohlcv.operation_locks import OHLCVDatasetOperationLocks
from leonardo.ohlcv.models import (
    DownloadBatchRequest,
    DownloadBatchResult,
    DownloadItemResult,
    DownloadPlan,
    DownloadPreflightItem,
    DownloadPreflightResult,
    DownloadProgressEvent,
)
from leonardo.ohlcv.store import Candle, DatasetInspection, OHLCVStore, merge_idempotent
from leonardo.ohlcv.validation import PreliminaryOHLCVValidator

ProgressSink = Callable[[DownloadProgressEvent], None]


class HistoricalDownloadService:
    REQUEST_TIMEOUT_SECONDS = 30.0
    MAX_REQUEST_ATTEMPTS = 3
    RETRY_BACKOFF_SECONDS = 1.0
    MAX_PAGES = 10_000

    def __init__(
        self,
        connection_service: ConnectionApplicationService,
        store: OHLCVStore,
        audit_log: AuditLog,
        *,
        actor_id: str,
        operation_locks: OHLCVDatasetOperationLocks | None = None,
    ) -> None:
        self._connections = connection_service
        self._store = store
        self._validator = PreliminaryOHLCVValidator()
        self._audit_log = audit_log
        self._actor_id = actor_id
        self._operation_locks = operation_locks or OHLCVDatasetOperationLocks()

    @property
    def store(self) -> OHLCVStore:
        return self._store

    @property
    def operation_locks(self) -> OHLCVDatasetOperationLocks:
        return self._operation_locks

    async def preflight_batch(self, request: DownloadBatchRequest) -> DownloadPreflightResult:
        normalized = normalize_batch_request(request)
        items: list[DownloadPreflightItem] = []
        async with self._connections.provider_session(normalized.exchange) as provider:
            for timeframe in normalized.timeframes:
                market = canonicalize_market_id(
                    normalized.exchange,
                    normalized.market_type,
                    normalized.symbol,
                    timeframe,
                )
                inspection = await asyncio.to_thread(self._store.inspect, market)
                plan = await self._build_plan(provider, market, normalized, inspection)
                requires_lower_bound = (
                    normalized.start_ms is None
                    and normalized.end_ms is None
                    and inspection.row_count == 0
                )
                can_download = not (requires_lower_bound and plan.effective_start_ms is None)
                reason = plan.reason
                if not can_download:
                    reason = "oldest_available_timestamp_unresolved"
                items.append(
                    DownloadPreflightItem(
                        market_id=market,
                        mode=plan.mode,
                        path=inspection.csv_path,
                        local_csv_exists=inspection.csv_exists,
                        local_metadata_exists=inspection.metadata_exists,
                        local_metadata_valid=inspection.metadata_valid,
                        local_first_ts_ms=inspection.first_ts_ms,
                        local_last_ts_ms=inspection.last_ts_ms,
                        local_row_count=inspection.row_count,
                        local_state_issues=inspection.issues,
                        exchange_oldest_ts_ms=plan.oldest_available_ts_ms,
                        exchange_youngest_ts_ms=plan.latest_closed_ts_ms or plan.planned_end_ms,
                        planned_start_ms=plan.effective_start_ms,
                        planned_end_ms=plan.planned_end_ms,
                        expected_bars=plan.expected_bars,
                        expected_pages=plan.expected_pages,
                        page_limit=plan.page_limit,
                        up_to_date=plan.up_to_date,
                        can_download=can_download,
                        reason=reason,
                    )
                )
        return DownloadPreflightResult(
            exchange=normalized.exchange,
            market_type=normalized.market_type,
            symbol=normalized.symbol,
            timeframes=normalized.timeframes,
            items=tuple(items),
        )

    async def run_batch(
        self,
        request: DownloadBatchRequest,
        *,
        progress: ProgressSink | None = None,
        correlation_id: str | None = None,
    ) -> DownloadBatchResult:
        normalized = normalize_batch_request(request)
        self._emit_progress(
            progress,
            DownloadProgressEvent(
                kind="batch_started",
                message="Historical OHLCV batch started",
                overall_current=0,
                overall_total=len(normalized.timeframes),
                details={"timeframes": normalized.timeframes},
            ),
        )
        self._audit(
            "download.batch_started",
            "Historical OHLCV batch started",
            correlation_id=correlation_id,
            details={
                "exchange": normalized.exchange,
                "market_type": normalized.market_type,
                "symbol": normalized.symbol,
                "timeframes": normalized.timeframes,
                "start_ms": normalized.start_ms,
                "end_ms": normalized.end_ms,
                "limit": normalized.limit,
            },
        )
        results: list[DownloadItemResult] = []
        completed: list[str] = []
        try:
            async with self._connections.provider_session(normalized.exchange) as provider:
                for index, timeframe in enumerate(normalized.timeframes, start=1):
                    market = canonicalize_market_id(
                        normalized.exchange,
                        normalized.market_type,
                        normalized.symbol,
                        timeframe,
                    )
                    self._emit_progress(
                        progress,
                        DownloadProgressEvent(
                            kind="item_started",
                            message=f"Starting {timeframe} download",
                            timeframe=timeframe,
                            current=0,
                            total=None,
                            overall_current=len(completed),
                            overall_total=len(normalized.timeframes),
                            details={"timeframe_index": index},
                        ),
                    )
                    result = await self._run_one(
                        provider,
                        market,
                        normalized,
                        progress=progress,
                        correlation_id=correlation_id,
                        overall_current=len(completed),
                        overall_total=len(normalized.timeframes),
                    )
                    results.append(result)
                    completed.append(timeframe)
                    self._emit_progress(
                        progress,
                        DownloadProgressEvent(
                            kind="item_completed",
                            message=f"Completed {timeframe}",
                            timeframe=timeframe,
                            current=1,
                            total=1,
                            overall_current=len(completed),
                            overall_total=len(normalized.timeframes),
                            details={
                                "path": str(result.file_path),
                                "total_rows": result.total_rows,
                                "fetched_rows": result.fetched_rows,
                                "validation_status": result.preliminary_validation_status,
                            },
                        ),
                    )
                    self._emit_progress(
                        progress,
                        DownloadProgressEvent(
                            kind="batch_progress",
                            message=f"Completed {len(completed)} of {len(normalized.timeframes)} timeframes",
                            overall_current=len(completed),
                            overall_total=len(normalized.timeframes),
                            details={"completed_timeframes": tuple(completed)},
                        ),
                    )
        except asyncio.CancelledError:
            self._emit_progress(
                progress,
                DownloadProgressEvent(
                    kind="batch_cancelled",
                    message="Historical OHLCV batch cancelled",
                    overall_current=len(completed),
                    overall_total=len(normalized.timeframes),
                    details={
                        "completed_timeframes": tuple(completed),
                        "remaining_timeframes": normalized.timeframes[len(completed):],
                    },
                ),
            )
            self._audit(
                "download.batch_cancelled",
                "Historical OHLCV batch cancelled",
                correlation_id=correlation_id,
                details={"completed_timeframes": tuple(completed)},
            )
            raise
        except Exception as error:
            self._emit_progress(
                progress,
                DownloadProgressEvent(
                    kind="batch_failed",
                    message=f"Historical OHLCV batch failed: {error}",
                    overall_current=len(completed),
                    overall_total=len(normalized.timeframes),
                    details={"error_type": type(error).__name__, "error": str(error)},
                ),
            )
            self._audit(
                "download.batch_failed",
                "Historical OHLCV batch failed",
                severity="error",
                correlation_id=correlation_id,
                details={"completed_timeframes": tuple(completed)},
                error=error,
            )
            raise
        batch = DownloadBatchResult(
            requested_timeframes=normalized.timeframes,
            completed_timeframes=tuple(completed),
            results=tuple(results),
        )
        self._emit_progress(
            progress,
            DownloadProgressEvent(
                kind="batch_completed",
                message="Historical OHLCV batch completed",
                overall_current=len(completed),
                overall_total=len(normalized.timeframes),
                details={"completed_timeframes": tuple(completed)},
            ),
        )
        self._audit(
            "download.batch_completed",
            "Historical OHLCV batch completed",
            correlation_id=correlation_id,
            details={
                "completed_timeframes": tuple(completed),
                "result_count": len(results),
            },
        )
        return batch

    async def run_repair_batches(
        self,
        requests: Sequence[DownloadBatchRequest],
        *,
        before_first_write: Callable[[], None],
        progress: ProgressSink | None = None,
        correlation_id: str | None = None,
    ) -> tuple[DownloadBatchResult, ...]:
        """Execute reviewed repair ranges under one dataset lock.

        The stale-plan precondition runs after the shared downloader lock is
        acquired, and the lock remains held across every reviewed range.
        """

        normalized = tuple(normalize_batch_request(request) for request in requests)
        if not normalized:
            raise ValueError("repair requires at least one range request")
        first = normalized[0]
        if len(first.timeframes) != 1:
            raise ValueError("repair requests must contain exactly one timeframe")
        market = canonicalize_market_id(
            first.exchange, first.market_type, first.symbol, first.timeframes[0]
        )
        for request in normalized[1:]:
            if len(request.timeframes) != 1:
                raise ValueError("repair requests must contain exactly one timeframe")
            candidate = canonicalize_market_id(
                request.exchange, request.market_type, request.symbol, request.timeframes[0]
            )
            if candidate != market:
                raise ValueError("all repair requests must target the same MarketId")

        results: list[DownloadBatchResult] = []
        async with self._operation_locks.acquire(market):
            await asyncio.to_thread(before_first_write)
            async with self._connections.provider_session(market.exchange) as provider:
                for index, request in enumerate(normalized, start=1):
                    item = await self._run_one(
                        provider,
                        market,
                        request,
                        progress=progress,
                        correlation_id=correlation_id,
                        overall_current=index - 1,
                        overall_total=len(normalized),
                        lock_already_held=True,
                    )
                    results.append(
                        DownloadBatchResult(
                            requested_timeframes=(market.timeframe,),
                            completed_timeframes=(market.timeframe,),
                            results=(item,),
                        )
                    )
        return tuple(results)

    async def _run_one(
        self,
        provider: HistoricalOHLCVProvider,
        market: MarketId,
        request: DownloadBatchRequest,
        *,
        progress: ProgressSink | None,
        correlation_id: str | None,
        overall_current: int,
        overall_total: int,
        lock_already_held: bool = False,
    ) -> DownloadItemResult:
        lock_context = (
            _already_locked()
            if lock_already_held
            else self._operation_locks.acquire(market)
        )
        async with lock_context:
            existing = await asyncio.to_thread(self._store.read, market)
            inspection = await asyncio.to_thread(self._store.inspect, market)
            plan = await self._build_plan(provider, market, request, inspection)
            pages_written = 0
            rows_written = 0
            download_complete = False
            downloaded_first: int | None = None
            downloaded_last: int | None = None
            self._emit_progress(
                progress,
                DownloadProgressEvent(
                    kind="plan_ready",
                    message=f"{market.timeframe} plan ready: {plan.mode}",
                    timeframe=market.timeframe,
                    current=0,
                    total=plan.expected_bars,
                    overall_current=overall_current,
                    overall_total=overall_total,
                    details={
                        "mode": plan.mode,
                        "planned_start_ms": plan.effective_start_ms,
                        "planned_end_ms": plan.planned_end_ms,
                        "expected_pages": plan.expected_pages,
                        "page_limit": plan.page_limit,
                        "up_to_date": plan.up_to_date,
                    },
                ),
            )
            try:
                if not plan.up_to_date:
                    end_cursor = plan.end_cursor_ms
                    last_cursor: int | None = None
                    fetched_total = 0
                    for page_no in range(1, plan.max_pages + 1):
                        if end_cursor is not None and end_cursor < 0:
                            break
                        if last_cursor is not None and end_cursor is not None and end_cursor >= last_cursor:
                            raise RuntimeError(
                                "paging end cursor did not move backwards "
                                f"(current={end_cursor}, previous={last_cursor})"
                            )
                        last_cursor = end_cursor
                        batch = await self._fetch_page_with_retries(
                            provider,
                            market,
                            start_ms=plan.effective_start_ms,
                            end_ms=end_cursor,
                            limit=plan.page_limit,
                            page_no=page_no,
                            expected_pages=plan.expected_pages,
                            progress=progress,
                            overall_current=overall_current,
                            overall_total=overall_total,
                        )
                        if not batch:
                            break
                        incoming = [
                            Candle(
                                ts_ms=int(item.ts_ms),
                                open=float(item.open),
                                high=float(item.high),
                                low=float(item.low),
                                close=float(item.close),
                                volume=float(item.volume),
                            )
                            for item in batch
                        ]
                        incoming.sort(key=lambda item: item.ts_ms)
                        if (
                            request.start_ms is None
                            and request.end_ms is None
                            and page_no == 1
                            and incoming
                        ):
                            newest_source = batch[-1]
                            if not bool(getattr(newest_source, "is_closed", True)):
                                incoming = incoming[:-1]
                            elif (
                                plan.latest_closed_ts_ms is not None
                                and incoming[-1].ts_ms > plan.latest_closed_ts_ms
                            ):
                                incoming = incoming[:-1]
                        if plan.effective_start_ms is not None:
                            incoming = [
                                item for item in incoming if item.ts_ms >= plan.effective_start_ms
                            ]
                        if plan.planned_end_ms is not None:
                            incoming = [
                                item for item in incoming if item.ts_ms <= plan.planned_end_ms
                            ]
                        if not incoming:
                            break
                        merged = merge_idempotent(existing, incoming)
                        write_task = asyncio.create_task(
                            asyncio.to_thread(
                                self._store.write,
                                market,
                                merged,
                                source=provider.name,
                                persistence_status="partial",
                                lineage={
                                    "download_mode": plan.mode,
                                    "planned_start_ms": plan.effective_start_ms,
                                    "planned_end_ms": plan.planned_end_ms,
                                    "pages_written": pages_written + 1,
                                },
                            )
                        )
                        cancelled_during_write = False
                        try:
                            await asyncio.shield(write_task)
                        except asyncio.CancelledError:
                            cancelled_during_write = True
                            await write_task
                        existing = merged
                        pages_written += 1
                        rows_written += len(incoming)
                        fetched_total += len(incoming)
                        page_first = incoming[0].ts_ms
                        page_last = incoming[-1].ts_ms
                        downloaded_first = (
                            page_first if downloaded_first is None else min(downloaded_first, page_first)
                        )
                        downloaded_last = (
                            page_last if downloaded_last is None else max(downloaded_last, page_last)
                        )
                        self._emit_progress(
                            progress,
                            DownloadProgressEvent(
                                kind="page_persisted",
                                message=(
                                    f"{market.timeframe}: persisted page {page_no} "
                                    f"({len(incoming)} rows)"
                                ),
                                timeframe=market.timeframe,
                                current=fetched_total,
                                total=plan.expected_bars,
                                overall_current=overall_current,
                                overall_total=overall_total,
                                details={
                                    "page": page_no,
                                    "expected_pages": plan.expected_pages,
                                    "page_rows": len(incoming),
                                    "total_rows": len(existing),
                                    "path": str(self._store.csv_path(market)),
                                    "progress_ratio": _progress_ratio(fetched_total, plan.expected_bars),
                                },
                            ),
                        )
                        self._audit(
                            "download.page_persisted",
                            f"OHLCV page persisted for {market.as_key()}",
                            correlation_id=correlation_id,
                            details={
                                "market_id": market.as_key(),
                                "page": page_no,
                                "page_rows": len(incoming),
                                "total_rows": len(existing),
                            },
                        )
                        if cancelled_during_write:
                            raise asyncio.CancelledError
                        oldest_ts = incoming[0].ts_ms
                        if plan.effective_start_ms is not None and oldest_ts <= plan.effective_start_ms:
                            break
                        end_cursor = oldest_ts - 1
                    if not existing:
                        raise RuntimeError(
                            f"provider returned no OHLCV candles for {market.as_key()}"
                        )
                download_complete = True
                report = await asyncio.to_thread(self._validator.validate, self._store, market)
                warning_messages = tuple(
                    item.message for item in report.issues if item.severity == "warning"
                )
                finalize_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._store.finalize,
                        market,
                        source=provider.name,
                        warnings=warning_messages,
                        lineage={
                            "download_mode": plan.mode,
                            "planned_start_ms": plan.effective_start_ms,
                            "planned_end_ms": plan.planned_end_ms,
                            "pages_written": pages_written,
                            "preliminary_validation_status": report.status,
                            "canonical_validation_status": "unknown",
                        },
                    )
                )
                cancelled_during_finalize = False
                try:
                    await asyncio.shield(finalize_task)
                except asyncio.CancelledError:
                    cancelled_during_finalize = True
                    await finalize_task
                if cancelled_during_finalize:
                    raise asyncio.CancelledError
                self._emit_progress(
                    progress,
                    DownloadProgressEvent(
                        kind="preliminary_validation_completed",
                        message=(
                            f"{market.timeframe}: preliminary validation {report.status}; "
                            "OHLCV Maintenance acceptance is still required"
                        ),
                        timeframe=market.timeframe,
                        current=plan.expected_bars if plan.expected_bars is not None else len(existing),
                        total=plan.expected_bars,
                        overall_current=overall_current,
                        overall_total=overall_total,
                        details={
                            "status": report.status,
                            "issues": report.messages,
                            "row_count": report.row_count,
                            "validation_status": "unknown",
                        },
                    ),
                )
                return DownloadItemResult(
                    market_id=market,
                    file_path=self._store.csv_path(market),
                    total_rows=len(existing),
                    fetched_rows=rows_written,
                    downloaded_first_ts_ms=downloaded_first,
                    downloaded_last_ts_ms=downloaded_last,
                    preliminary_validation_status=report.status,
                    preliminary_validation_issues=report.messages,
                )
            except asyncio.CancelledError:
                try:
                    persistence_status = self._store.read_sidecar(market).persistence_status
                except Exception:
                    persistence_status = None
                details = {
                    "partial_persistence": pages_written > 0 and persistence_status != "committed",
                    "download_complete": download_complete,
                    "persistence_status": persistence_status,
                    "pages_written": pages_written,
                    "rows_written": rows_written,
                    "persisted_total_rows": len(existing),
                    "persisted_first_ts_ms": existing[0].ts_ms if existing else None,
                    "persisted_last_ts_ms": existing[-1].ts_ms if existing else None,
                    "persisted_downloaded_first_ts_ms": downloaded_first,
                    "persisted_downloaded_last_ts_ms": downloaded_last,
                    "path": str(self._store.csv_path(market)) if pages_written else None,
                }
                self._emit_progress(
                    progress,
                    DownloadProgressEvent(
                        kind="item_cancelled",
                        message=f"{market.timeframe} download cancelled",
                        timeframe=market.timeframe,
                        overall_current=overall_current,
                        overall_total=overall_total,
                        details=details,
                    ),
                )
                self._audit(
                    "download.item_cancelled",
                    f"OHLCV download cancelled for {market.as_key()}",
                    correlation_id=correlation_id,
                    details={"market_id": market.as_key(), **details},
                )
                raise

    async def _build_plan(
        self,
        provider: HistoricalOHLCVProvider,
        market: MarketId,
        request: DownloadBatchRequest,
        inspection: DatasetInspection,
    ) -> DownloadPlan:
        adapter_limit = provider.max_historical_ohlcv_limit(market.market_type)
        adapter_limit = int(adapter_limit) if adapter_limit is not None and adapter_limit > 0 else None
        page_limit = adapter_limit or 500
        if request.limit not in (None, 0):
            page_limit = int(request.limit)
            if adapter_limit is not None:
                page_limit = min(page_limit, adapter_limit)
        mode = "custom_range" if request.start_ms is not None or request.end_ms is not None else "new_download"
        effective_start = request.start_ms
        latest_closed: int | None = None
        oldest_available: int | None = None
        derived_from_now = False
        if request.end_ms is not None:
            end_cursor = request.end_ms
        elif inspection.row_count > 0 and request.start_ms is None:
            mode = "update_latest"
            effective_start = inspection.last_ts_ms
            latest_closed = await self._latest_closed_ts(provider, market)
            if latest_closed is not None:
                end_cursor = latest_closed
            else:
                end_cursor = await provider.get_server_time_ms()
                derived_from_now = True
        else:
            latest_closed = await self._latest_closed_ts(provider, market)
            if latest_closed is not None:
                end_cursor = latest_closed
            else:
                end_cursor = await provider.get_server_time_ms()
                derived_from_now = True
            if request.start_ms is None and request.end_ms is None:
                try:
                    oldest_available = await provider.oldest_historical_ohlcv_ts_ms(
                        market=market.market_type,
                        symbol=market.symbol,
                        timeframe=market.timeframe,
                        limit=page_limit,
                    )
                except NotImplementedError:
                    oldest_available = None
                effective_start = oldest_available
        expected_bars = _expected_bars(effective_start, end_cursor, market.timeframe)
        expected_pages = (
            None if expected_bars is None else (0 if expected_bars == 0 else (expected_bars + page_limit - 1) // page_limit)
        )
        up_to_date = (
            mode == "update_latest"
            and latest_closed is not None
            and effective_start is not None
            and effective_start >= latest_closed
        )
        if up_to_date:
            expected_bars = 0
            expected_pages = 0
        return DownloadPlan(
            mode=mode,
            effective_start_ms=effective_start,
            end_cursor_ms=end_cursor,
            planned_end_ms=end_cursor,
            latest_closed_ts_ms=latest_closed,
            oldest_available_ts_ms=oldest_available,
            page_limit=page_limit,
            max_pages=self.MAX_PAGES,
            expected_bars=expected_bars,
            expected_pages=expected_pages,
            determinate_progress=expected_bars is not None,
            up_to_date=up_to_date,
            reason="up_to_date" if up_to_date else None,
            derived_from_now=derived_from_now,
        )

    async def _fetch_page_with_retries(
        self,
        provider: HistoricalOHLCVProvider,
        market: MarketId,
        *,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        page_no: int,
        expected_pages: int | None,
        progress: ProgressSink | None,
        overall_current: int,
        overall_total: int,
    ) -> Sequence[object]:
        last_error: BaseException | None = None
        attempts_made = 0
        for attempt in range(1, self.MAX_REQUEST_ATTEMPTS + 1):
            attempts_made = attempt
            try:
                return await asyncio.wait_for(
                    provider.fetch_ohlcv_historical(
                        market=market.market_type,
                        symbol=market.symbol,
                        timeframe=market.timeframe,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        limit=limit,
                    ),
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                last_error = error
                retryable = True
                provider_retry_exhausted = False
                provider_details: dict[str, object] = {}
                if isinstance(error, HistoricalProviderRequestError):
                    retryable = error.retryable
                    provider_retry_exhausted = error.attempts_exhausted
                    provider_details = {
                        "provider": error.provider,
                        "provider_operation": error.operation,
                        "provider_retryable": error.retryable,
                        "provider_attempts_exhausted": error.attempts_exhausted,
                        "provider_status": error.status,
                        "provider_code": error.code,
                    }
                should_retry = (
                    attempt < self.MAX_REQUEST_ATTEMPTS
                    and retryable
                    and not provider_retry_exhausted
                )
                kind = "page_retrying" if should_retry else "page_failed"
                self._emit_progress(
                    progress,
                    DownloadProgressEvent(
                        kind=kind,
                        message=(
                            f"{market.timeframe}: page {page_no} attempt {attempt} failed: {error}"
                        ),
                        timeframe=market.timeframe,
                        overall_current=overall_current,
                        overall_total=overall_total,
                        details={
                            "page": page_no,
                            "expected_pages": expected_pages,
                            "attempt": attempt,
                            "error_type": type(error).__name__,
                            "error": str(error),
                            **provider_details,
                        },
                    ),
                )
                if not should_retry:
                    break
                await asyncio.sleep(self.RETRY_BACKOFF_SECONDS * attempt)
        assert last_error is not None
        raise RuntimeError(
            f"OHLCV page {page_no} failed after {attempts_made} downloader attempt(s): "
            f"{last_error}"
        ) from last_error

    async def _latest_closed_ts(
        self,
        provider: HistoricalOHLCVProvider,
        market: MarketId,
    ) -> int | None:
        server_time = await provider.get_server_time_ms()
        recent = await provider.fetch_ohlcv_historical(
            market=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            end_ms=server_time,
            limit=2,
        )
        closed = [
            int(item.ts_ms)
            for item in recent
            if bool(getattr(item, "is_closed", True)) and int(item.ts_ms) <= server_time
        ]
        return max(closed) if closed else None

    def _audit(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "info",
        correlation_id: str | None,
        details: dict[str, object],
        error: Exception | None = None,
    ) -> None:
        self._audit_log.emit(
            AuditEventV1(
                event_type=event_type,
                category="ohlcv",
                severity=severity,
                message=message,
                actor_id=self._actor_id,
                action_id="download.execute",
                correlation_id=correlation_id,
                details=details,
                error_type=type(error).__name__ if error is not None else None,
                error_message=str(error) if error is not None else None,
            )
        )

    @staticmethod
    def _emit_progress(progress: ProgressSink | None, event: DownloadProgressEvent) -> None:
        if progress is not None:
            progress(event)


@asynccontextmanager
async def _already_locked() -> AsyncIterator[None]:
    yield


def normalize_batch_request(request: DownloadBatchRequest) -> DownloadBatchRequest:
    if not isinstance(request, DownloadBatchRequest):
        raise TypeError("request must be a DownloadBatchRequest")
    if request.start_ms is not None and (type(request.start_ms) is not int or request.start_ms < 0):
        raise ValueError("start_ms must be a non-negative integer or None")
    if request.end_ms is not None and (type(request.end_ms) is not int or request.end_ms < 0):
        raise ValueError("end_ms must be a non-negative integer or None")
    if request.start_ms is not None and request.end_ms is not None and request.start_ms > request.end_ms:
        raise ValueError("start_ms cannot be greater than end_ms")
    if request.limit is not None and (type(request.limit) is not int or request.limit < 0):
        raise ValueError("limit must be a non-negative integer or None")
    normalized_timeframes: list[str] = []
    seen: set[str] = set()
    first_market: MarketId | None = None
    for raw in request.timeframes:
        market = canonicalize_market_id(
            request.exchange,
            request.market_type,
            request.symbol,
            str(raw or ""),
        )
        first_market = first_market or market
        if market.timeframe not in seen:
            seen.add(market.timeframe)
            normalized_timeframes.append(market.timeframe)
    if first_market is None or not normalized_timeframes:
        raise ValueError("at least one timeframe is required")
    return DownloadBatchRequest(
        exchange=first_market.exchange,
        market_type=first_market.market_type,
        symbol=first_market.symbol,
        timeframes=tuple(normalized_timeframes),
        start_ms=request.start_ms,
        end_ms=request.end_ms,
        limit=request.limit,
    )


def _expected_bars(start_ms: int | None, end_ms: int | None, timeframe: str) -> int | None:
    if start_ms is None or end_ms is None:
        return None
    duration = timeframe_duration_ms(timeframe)
    if duration is None:
        return None
    if end_ms < start_ms:
        return 0
    return ((end_ms - start_ms) // duration) + 1


def _progress_ratio(current: int, total: int | None) -> float | None:
    if total is None or total <= 0:
        return None
    return min(1.0, max(0.0, current / total))
