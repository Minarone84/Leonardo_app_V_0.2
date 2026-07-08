"""Offline Bybit OHLCV smoke execution helper.

The helper composes request construction, fixture transport normalization, and
sandboxed storage writes into execution read models. It does not call live
network APIs, integrate with GUI, or register runtime services.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

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
    bybit_public_kline_http_transport,
    fetch_bybit_kline_page,
)
from leonardo.download_data.ohlcv_storage_writer import (
    inspect_ohlcv_smoke_storage,
    write_ohlcv_smoke,
)


SMOKE_EXCHANGE_ID = "bybit"
SMOKE_MARKET_TYPE = "spot"
SMOKE_SYMBOL = "BTCUSDT"
SMOKE_TIMEFRAME = "1m"
SMOKE_INTERVAL = "1"
SMOKE_LIMIT = 10
LIVE_BYBIT_SMOKE_ENV_VAR = "LEONARDO_ALLOW_LIVE_BYBIT_SMOKE"


def run_bybit_ohlcv_smoke_slice(
    *,
    sandbox_root: str | Path,
    transport: BybitKlineTransport,
    exchange_id: str = SMOKE_EXCHANGE_ID,
    market_type: str = SMOKE_MARKET_TYPE,
    symbol: str = SMOKE_SYMBOL,
    timeframe: str = SMOKE_TIMEFRAME,
    limit: int = SMOKE_LIMIT,
) -> DownloadDataExecutionResult:
    """Run the offline Bybit OHLCV smoke slice against fixture transport."""

    storage_preflight = inspect_ohlcv_smoke_storage(
        sandbox_root=sandbox_root,
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
    )
    target = _smoke_target(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
        mode=storage_preflight.mode,
        local_latest_timestamp_ms=storage_preflight.local_latest_timestamp_ms,
    )
    provider_request = _smoke_provider_request(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
        mode=storage_preflight.mode,
        local_latest_timestamp_ms=storage_preflight.local_latest_timestamp_ms,
    )
    event_scope = f"{_safe_event_part(symbol)}-{_safe_event_part(timeframe)}"
    mode_value = storage_preflight.mode.value
    prepared_event = _progress_event(
        event_id=f"bybit-smoke-{event_scope}-progress-1",
        target=target,
        status=DownloadDataExecutionStatus.PENDING,
        message=f"Smoke {mode_value} request prepared",
    )
    page_result = fetch_bybit_kline_page(provider_request, transport)
    normalized_event = _progress_event(
        event_id=f"bybit-smoke-{event_scope}-progress-2",
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
        csv_path=storage_preflight.csv_path,
        metadata_path=storage_preflight.metadata_path,
        write_mode=storage_preflight.mode,
    )
    storage_result = write_ohlcv_smoke(
        write_request,
        sandbox_root=sandbox_root,
    )
    completed_event = _progress_event(
        event_id=f"bybit-smoke-{event_scope}-progress-3",
        target=target,
        status=DownloadDataExecutionStatus.COMPLETED,
        message=f"Sandbox storage {mode_value} completed",
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


def run_bybit_ohlcv_live_smoke(
    *,
    sandbox_root: str | Path | None = None,
    allow_live: bool = False,
    transport: BybitKlineTransport | None = None,
) -> DownloadDataExecutionResult:
    """Run the Bybit public smoke only after an explicit live gate."""

    if not allow_live and os.environ.get(LIVE_BYBIT_SMOKE_ENV_VAR) != "1":
        raise PermissionError(
            f"set {LIVE_BYBIT_SMOKE_ENV_VAR}=1 or pass allow_live=True"
        )
    root = (
        Path(tempfile.mkdtemp(prefix="leonardo-bybit-live-smoke-"))
        if sandbox_root is None
        else sandbox_root
    )
    active_transport = transport or bybit_public_kline_http_transport
    return run_bybit_ohlcv_smoke_slice(
        sandbox_root=root,
        transport=active_transport,
    )


def fixture_bybit_kline_transport(params: object) -> dict[str, object]:
    """Return deterministic fixture OHLCV rows for offline smoke execution."""

    values = dict(params)  # type: ignore[arg-type]
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": str(values.get("category", SMOKE_MARKET_TYPE)),
            "symbol": str(values.get("symbol", SMOKE_SYMBOL)),
            "list": [
                [
                    "1700000120000",
                    "42020.0",
                    "42030.0",
                    "42010.0",
                    "42025.0",
                    "1.3",
                    "54600.0",
                ],
                [
                    "1700000060000",
                    "42005.0",
                    "42020.0",
                    "42000.0",
                    "42015.0",
                    "1.2",
                    "50400.0",
                ],
                [
                    "1700000000000",
                    "42000.0",
                    "42010.0",
                    "41990.0",
                    "42005.0",
                    "1.1",
                    "46200.0",
                ],
            ],
        },
    }


def _smoke_target(
    *,
    exchange_id: str = SMOKE_EXCHANGE_ID,
    market_type: str = SMOKE_MARKET_TYPE,
    symbol: str = SMOKE_SYMBOL,
    timeframe: str = SMOKE_TIMEFRAME,
    limit: int = SMOKE_LIMIT,
    mode: DownloadDataExecutionMode = DownloadDataExecutionMode.NEW_FILE,
    local_latest_timestamp_ms: int | None = None,
) -> DownloadDataExecutionTarget:
    direction = (
        DownloadDataExecutionDirection.FORWARD_UPDATE
        if mode is DownloadDataExecutionMode.UPDATE_EXISTING
        else DownloadDataExecutionDirection.BACKWARD_HISTORY
    )
    return DownloadDataExecutionTarget(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        storage_target_ref=_smoke_csv_relative_path(
            exchange_id=exchange_id,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        ),
        mode=mode,
        direction=direction,
        requested_start_timestamp_ms=local_latest_timestamp_ms,
        local_latest_timestamp_ms=local_latest_timestamp_ms,
        limit=limit,
    )


def _smoke_provider_request(
    *,
    exchange_id: str = SMOKE_EXCHANGE_ID,
    market_type: str = SMOKE_MARKET_TYPE,
    symbol: str = SMOKE_SYMBOL,
    timeframe: str = SMOKE_TIMEFRAME,
    limit: int = SMOKE_LIMIT,
    mode: DownloadDataExecutionMode = DownloadDataExecutionMode.NEW_FILE,
    local_latest_timestamp_ms: int | None = None,
) -> DownloadDataProviderPageRequest:
    direction = (
        DownloadDataExecutionDirection.FORWARD_UPDATE
        if mode is DownloadDataExecutionMode.UPDATE_EXISTING
        else DownloadDataExecutionDirection.BACKWARD_HISTORY
    )
    return DownloadDataProviderPageRequest(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        category=market_type,
        interval=_bybit_interval_for_timeframe(timeframe),
        start_timestamp_ms=local_latest_timestamp_ms,
        limit=limit,
        direction=direction,
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


def _smoke_csv_relative_path(
    *,
    exchange_id: str = SMOKE_EXCHANGE_ID,
    market_type: str = SMOKE_MARKET_TYPE,
    symbol: str = SMOKE_SYMBOL,
    timeframe: str = SMOKE_TIMEFRAME,
) -> str:
    return f"historical/{exchange_id}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv"


def _smoke_metadata_relative_path(
    *,
    exchange_id: str = SMOKE_EXCHANGE_ID,
    market_type: str = SMOKE_MARKET_TYPE,
    symbol: str = SMOKE_SYMBOL,
    timeframe: str = SMOKE_TIMEFRAME,
) -> str:
    return f"historical/{exchange_id}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.meta.json"


def _bybit_interval_for_timeframe(timeframe: str) -> str:
    mapping = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "6h": "360",
        "12h": "720",
        "1d": "D",
        "1w": "W",
    }
    try:
        return mapping[timeframe]
    except KeyError as error:
        raise ValueError(f"Unsupported Bybit smoke timeframe: {timeframe}") from error


def _safe_event_part(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)
