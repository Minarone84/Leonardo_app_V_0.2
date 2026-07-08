"""Sandboxed OHLCV storage writer for the Download Data smoke slice.

This module writes offline smoke outputs under an explicit sandbox root. It
supports new-file and update-existing modes for sandbox OHLCV CSV and metadata
sidecar files. It does not mark written datasets accepted, loadable, or
validated.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from leonardo.contracts.download_data_boundary import DOWNLOAD_DATA_ARTIFACT_ID
from leonardo.contracts.download_data_execution import (
    DownloadDataCandleSortOrder,
    DownloadDataExecutionMode,
    DownloadDataNormalizedCandle,
    DownloadDataStorageWriteRequest,
    DownloadDataStorageWriteResult,
    DownloadDataStorageWriteStatus,
)


CSV_FIELDNAMES = (
    "timestamp_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
)


@dataclass(frozen=True)
class OhlcvSandboxStoragePreflight:
    """Sandbox-only read model for OHLCV storage path inspection."""

    exchange_id: str
    market_type: str
    symbol: str
    timeframe: str
    csv_path: str
    metadata_path: str
    csv_exists: bool
    metadata_exists: bool
    mode: DownloadDataExecutionMode
    local_latest_timestamp_ms: int | None


def inspect_ohlcv_smoke_storage(
    *,
    sandbox_root: str | Path,
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> OhlcvSandboxStoragePreflight:
    """Inspect sandbox OHLCV CSV and metadata state for one target identity."""

    _validate_identity(exchange_id, "exchange_id")
    _validate_identity(market_type, "market_type")
    _validate_identity(symbol, "symbol")
    _validate_identity(timeframe, "timeframe")

    root = _resolve_sandbox_root(sandbox_root)
    csv_path = _ohlcv_csv_relative_path(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
    )
    metadata_path = _ohlcv_metadata_relative_path(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
    )
    resolved_csv_path = _resolve_sandbox_child(root, csv_path)
    resolved_metadata_path = _resolve_sandbox_child(root, metadata_path)
    csv_exists = resolved_csv_path.exists()
    metadata_exists = resolved_metadata_path.exists()
    mode = (
        DownloadDataExecutionMode.UPDATE_EXISTING
        if csv_exists or metadata_exists
        else DownloadDataExecutionMode.NEW_FILE
    )
    latest = None
    if mode is DownloadDataExecutionMode.UPDATE_EXISTING:
        latest = _latest_timestamp_from_metadata(
            resolved_metadata_path,
            exchange_id=exchange_id,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        if latest is None and csv_exists:
            latest = _latest_timestamp_from_csv(resolved_csv_path)

    return OhlcvSandboxStoragePreflight(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        csv_path=csv_path,
        metadata_path=metadata_path,
        csv_exists=csv_exists,
        metadata_exists=metadata_exists,
        mode=mode,
        local_latest_timestamp_ms=latest,
    )


def write_ohlcv_smoke(
    request: DownloadDataStorageWriteRequest,
    *,
    sandbox_root: str | Path,
) -> DownloadDataStorageWriteResult:
    """Write or update smoke OHLCV CSV and metadata under a sandbox root."""

    if not isinstance(request, DownloadDataStorageWriteRequest):
        raise TypeError("request must be DownloadDataStorageWriteRequest")
    if request.write_mode not in (
        DownloadDataExecutionMode.NEW_FILE,
        DownloadDataExecutionMode.UPDATE_EXISTING,
    ):
        raise ValueError("smoke storage writer supports new_file and update_existing")
    if request.sort_order is not DownloadDataCandleSortOrder.ASCENDING:
        raise ValueError("smoke storage writer requires ascending candles")

    root = _resolve_sandbox_root(sandbox_root)
    csv_path = _resolve_sandbox_child(root, request.csv_path)
    metadata_path = _resolve_sandbox_child(root, request.metadata_path)
    incoming_candles = tuple(
        sorted(request.candles, key=lambda candle: candle.timestamp_ms)
    )

    if request.write_mode is DownloadDataExecutionMode.NEW_FILE:
        if csv_path.exists() or metadata_path.exists():
            raise FileExistsError("smoke storage writer cannot overwrite new files")
        stored_candles = incoming_candles
        existing_count = 0
        local_latest_timestamp_ms = None
        write_exclusive = True
    else:
        existing_candles = _read_candles_csv(csv_path) if csv_path.exists() else ()
        existing_count = len(existing_candles)
        existing_latest_timestamp_ms = _latest_timestamp(existing_candles)
        local_latest_timestamp_ms = (
            request.target.local_latest_timestamp_ms
            if request.target.local_latest_timestamp_ms is not None
            else existing_latest_timestamp_ms
        )
        stored_candles = _merge_candles(existing_candles, incoming_candles)
        write_exclusive = False

    _write_candles_csv(csv_path, stored_candles, exclusive=write_exclusive)
    _write_metadata_sidecar(
        metadata_path,
        request,
        stored_candles,
        exclusive=write_exclusive,
        existing_bars=existing_count,
        incoming_bars=len(incoming_candles),
        local_latest_timestamp_ms=local_latest_timestamp_ms,
    )

    first_timestamp = stored_candles[0].timestamp_ms if stored_candles else None
    last_timestamp = stored_candles[-1].timestamp_ms if stored_candles else None
    return DownloadDataStorageWriteResult(
        target=request.target,
        status=DownloadDataStorageWriteStatus.WRITTEN,
        csv_path=request.csv_path,
        metadata_path=request.metadata_path,
        bars_written=len(stored_candles),
        first_timestamp_ms=first_timestamp,
        last_timestamp_ms=last_timestamp,
        partial=False,
        accepted=False,
        loadable=False,
        validated=False,
        metadata={
            "source": "bybit",
            "smoke": True,
            "mode": request.write_mode.value,
            "existing_bars": existing_count,
            "incoming_bars": len(incoming_candles),
            "deduplicate_policy": "incoming_replaces_existing",
            "local_latest_timestamp_ms": local_latest_timestamp_ms,
        },
    )


def write_ohlcv_smoke_new_file(
    request: DownloadDataStorageWriteRequest,
    *,
    sandbox_root: str | Path,
) -> DownloadDataStorageWriteResult:
    """Write smoke OHLCV CSV and metadata under an explicit sandbox root."""

    if not isinstance(request, DownloadDataStorageWriteRequest):
        raise TypeError("request must be DownloadDataStorageWriteRequest")
    if request.write_mode is not DownloadDataExecutionMode.NEW_FILE:
        raise ValueError("smoke storage writer supports new_file mode only")
    return write_ohlcv_smoke(request, sandbox_root=sandbox_root)


def _resolve_sandbox_root(sandbox_root: str | Path) -> Path:
    if sandbox_root is None:
        raise ValueError("sandbox_root is required")
    if isinstance(sandbox_root, str) and not sandbox_root.strip():
        raise ValueError("sandbox_root is required")

    root = Path(sandbox_root).resolve()
    if root == Path.cwd().resolve():
        raise ValueError("sandbox_root must not be the project root")
    return root


def _resolve_sandbox_child(root: Path, relative_path: str) -> Path:
    child = (root / relative_path).resolve()
    if not child.is_relative_to(root):
        raise ValueError("output path must stay under sandbox_root")
    return child


def _write_candles_csv(
    csv_path: Path,
    candles: tuple[DownloadDataNormalizedCandle, ...],
    *,
    exclusive: bool,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    open_mode = "x" if exclusive else "w"
    with csv_path.open(open_mode, newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp_ms": candle.timestamp_ms,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "turnover": "" if candle.turnover is None else candle.turnover,
                }
            )


def _write_metadata_sidecar(
    metadata_path: Path,
    request: DownloadDataStorageWriteRequest,
    candles: tuple[DownloadDataNormalizedCandle, ...],
    *,
    exclusive: bool,
    existing_bars: int,
    incoming_bars: int,
    local_latest_timestamp_ms: int | None,
) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "exchange_id": request.target.exchange_id,
        "market_type": request.target.market_type,
        "symbol": request.target.symbol,
        "timeframe": request.target.timeframe,
        "artifact_id": DOWNLOAD_DATA_ARTIFACT_ID,
        "persistence_status": request.write_mode.value,
        "bars_written": len(candles),
        "first_timestamp_ms": candles[0].timestamp_ms if candles else None,
        "last_timestamp_ms": candles[-1].timestamp_ms if candles else None,
        "partial": False,
        "accepted": False,
        "loadable": False,
        "validated": False,
        "source": "bybit",
        "smoke": True,
        "mode": request.write_mode.value,
        "existing_bars": existing_bars,
        "incoming_bars": incoming_bars,
        "deduplicate_policy": "incoming_replaces_existing",
        "local_latest_timestamp_ms": local_latest_timestamp_ms,
    }
    open_mode = "x" if exclusive else "w"
    with metadata_path.open(open_mode, encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, sort_keys=True)


def _read_candles_csv(csv_path: Path) -> tuple[DownloadDataNormalizedCandle, ...]:
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = tuple(csv.DictReader(csv_file))
    return tuple(_candle_from_csv_row(row) for row in rows)


def _candle_from_csv_row(row: dict[str, str]) -> DownloadDataNormalizedCandle:
    try:
        timestamp_ms = int(row["timestamp_ms"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("OHLCV CSV row has invalid timestamp_ms") from error
    return DownloadDataNormalizedCandle(
        timestamp_ms=timestamp_ms,
        open=_required_csv_value(row, "open"),
        high=_required_csv_value(row, "high"),
        low=_required_csv_value(row, "low"),
        close=_required_csv_value(row, "close"),
        volume=_required_csv_value(row, "volume"),
        turnover=_optional_csv_value(row, "turnover"),
    )


def _required_csv_value(row: dict[str, str], field_name: str) -> str:
    value = row.get(field_name)
    if value is None or value == "":
        raise ValueError(f"OHLCV CSV row has invalid {field_name}")
    return value


def _optional_csv_value(row: dict[str, str], field_name: str) -> str | None:
    value = row.get(field_name)
    if value is None or value == "":
        return None
    return value


def _merge_candles(
    existing: tuple[DownloadDataNormalizedCandle, ...],
    incoming: tuple[DownloadDataNormalizedCandle, ...],
) -> tuple[DownloadDataNormalizedCandle, ...]:
    by_timestamp = {candle.timestamp_ms: candle for candle in existing}
    for candle in incoming:
        by_timestamp[candle.timestamp_ms] = candle
    return tuple(by_timestamp[timestamp] for timestamp in sorted(by_timestamp))


def _latest_timestamp(
    candles: tuple[DownloadDataNormalizedCandle, ...],
) -> int | None:
    if not candles:
        return None
    return max(candle.timestamp_ms for candle in candles)


def _latest_timestamp_from_metadata(
    metadata_path: Path,
    *,
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> int | None:
    if not metadata_path.exists():
        return None
    try:
        metadata: Any = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    expected = {
        "exchange_id": exchange_id,
        "market_type": market_type,
        "symbol": symbol,
        "timeframe": timeframe,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            return None
    latest = metadata.get("last_timestamp_ms")
    if type(latest) is int and latest >= 0:
        return latest
    return None


def _latest_timestamp_from_csv(csv_path: Path) -> int | None:
    return _latest_timestamp(_read_candles_csv(csv_path))


def _ohlcv_csv_relative_path(
    *,
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> str:
    return f"historical/{exchange_id}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv"


def _ohlcv_metadata_relative_path(
    *,
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> str:
    return (
        f"historical/{exchange_id}/{market_type}/{symbol}/{timeframe}"
        "/ohlcv/candles.meta.json"
    )


def _validate_identity(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
