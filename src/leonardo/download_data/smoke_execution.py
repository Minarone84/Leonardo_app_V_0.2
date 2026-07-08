"""Offline Bybit OHLCV smoke execution helper.

The helper composes request construction, fixture transport normalization, and
sandboxed storage writes into execution read models. It does not call live
network APIs, integrate with GUI, or register runtime services.
"""

from __future__ import annotations

from pathlib import Path

from leonardo.contracts.download_data_execution import (
    DownloadDataExecutionDirection,
    DownloadDataExecutionMode,
    DownloadDataExecutionProgressEvent,
    DownloadDataExecutionResult,
    DownloadDataExecutionStatus,
    DownloadDataExecutionTarget,
    DownloadDataProviderPageRequest,
    DownloadDataStorageWriteRequest,
)
from leonardo.download_data.bybit_ohlcv import (
    BybitKlineTransport,
    fetch_bybit_kline_page,
)
from leonardo.download_data.ohlcv_storage_writer import write_ohlcv_smoke_new_file


SMOKE_EXCHANGE_ID = "bybit"
SMOKE_MARKET_TYPE = "spot"
SMOKE_SYMBOL = "BTCUSDT"
SMOKE_TIMEFRAME = "1m"
SMOKE_INTERVAL = "1"
SMOKE_LIMIT = 10


def run_bybit_ohlcv_smoke_slice(
    *,
    sandbox_root: str | Path,
    transport: BybitKlineTransport,
) -> DownloadDataExecutionResult:
    """Run the offline Bybit OHLCV smoke slice against fixture transport."""

    target = _smoke_target()
    provider_request = _smoke_provider_request()
    prepared_event = _progress_event(
        event_id="bybit-smoke-progress-1",
        target=target,
        status=DownloadDataExecutionStatus.PENDING,
        message="Smoke request prepared",
    )
    page_result = fetch_bybit_kline_page(provider_request, transport)
    normalized_event = _progress_event(
        event_id="bybit-smoke-progress-2",
        target=target,
        status=DownloadDataExecutionStatus.RUNNING,
        message="Fixture page normalized",
        completed_steps=1,
        total_steps=2,
        downloaded_bars=len(page_result.candles),
    )
    write_request = DownloadDataStorageWriteRequest(
        target=target,
        candles=page_result.candles,
        csv_path=_smoke_csv_relative_path(),
        metadata_path=_smoke_metadata_relative_path(),
        write_mode=DownloadDataExecutionMode.NEW_FILE,
    )
    storage_result = write_ohlcv_smoke_new_file(
        write_request,
        sandbox_root=sandbox_root,
    )
    completed_event = _progress_event(
        event_id="bybit-smoke-progress-3",
        target=target,
        status=DownloadDataExecutionStatus.COMPLETED,
        message="Sandbox storage completed",
        completed_steps=2,
        total_steps=2,
        downloaded_bars=len(page_result.candles),
        written_bars=storage_result.bars_written,
    )
    return DownloadDataExecutionResult(
        workflow_id="download-data-bybit-ohlcv-smoke",
        status=DownloadDataExecutionStatus.COMPLETED,
        targets=(target,),
        storage_results=(storage_result,),
        progress_events=(
            prepared_event,
            normalized_event,
            completed_event,
        ),
        total_bars_downloaded=len(page_result.candles),
    )


def _smoke_target() -> DownloadDataExecutionTarget:
    return DownloadDataExecutionTarget(
        exchange_id=SMOKE_EXCHANGE_ID,
        market_type=SMOKE_MARKET_TYPE,
        symbol=SMOKE_SYMBOL,
        timeframe=SMOKE_TIMEFRAME,
        storage_target_ref=_smoke_csv_relative_path(),
        mode=DownloadDataExecutionMode.NEW_FILE,
        direction=DownloadDataExecutionDirection.BACKWARD_HISTORY,
        limit=SMOKE_LIMIT,
    )


def _smoke_provider_request() -> DownloadDataProviderPageRequest:
    return DownloadDataProviderPageRequest(
        exchange_id=SMOKE_EXCHANGE_ID,
        market_type=SMOKE_MARKET_TYPE,
        symbol=SMOKE_SYMBOL,
        timeframe=SMOKE_TIMEFRAME,
        category=SMOKE_MARKET_TYPE,
        interval=SMOKE_INTERVAL,
        limit=SMOKE_LIMIT,
        direction=DownloadDataExecutionDirection.BACKWARD_HISTORY,
    )


def _progress_event(
    *,
    event_id: str,
    target: DownloadDataExecutionTarget,
    status: DownloadDataExecutionStatus,
    message: str,
    completed_steps: int = 0,
    total_steps: int = 2,
    downloaded_bars: int = 0,
    written_bars: int = 0,
) -> DownloadDataExecutionProgressEvent:
    return DownloadDataExecutionProgressEvent(
        event_id=event_id,
        workflow_id="download-data-bybit-ohlcv-smoke",
        target=target,
        status=status,
        message=message,
        timestamp_ms=1_700_000_000_000 + completed_steps,
        completed_steps=completed_steps,
        total_steps=total_steps,
        downloaded_bars=downloaded_bars,
        written_bars=written_bars,
    )


def _smoke_csv_relative_path() -> str:
    return "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv"


def _smoke_metadata_relative_path() -> str:
    return "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json"
