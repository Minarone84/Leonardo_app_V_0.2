"""Sandboxed OHLCV storage writer for the Download Data smoke slice.

This module writes the first offline smoke output under an explicit sandbox
root. It is intentionally limited to new-file OHLCV CSV and metadata sidecar
creation and does not mark written datasets accepted, loadable, or validated.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from leonardo.contracts.download_data_boundary import DOWNLOAD_DATA_ARTIFACT_ID
from leonardo.contracts.download_data_execution import (
    DownloadDataCandleSortOrder,
    DownloadDataExecutionMode,
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
    if request.sort_order is not DownloadDataCandleSortOrder.ASCENDING:
        raise ValueError("smoke storage writer requires ascending candles")

    root = _resolve_sandbox_root(sandbox_root)
    csv_path = _resolve_sandbox_child(root, request.csv_path)
    metadata_path = _resolve_sandbox_child(root, request.metadata_path)
    if csv_path.exists() or metadata_path.exists():
        raise FileExistsError("smoke storage writer only creates new files")

    candles = tuple(sorted(request.candles, key=lambda candle: candle.timestamp_ms))
    _write_candles_csv(csv_path, candles)
    _write_metadata_sidecar(metadata_path, request, candles)

    first_timestamp = candles[0].timestamp_ms if candles else None
    last_timestamp = candles[-1].timestamp_ms if candles else None
    return DownloadDataStorageWriteResult(
        target=request.target,
        status=DownloadDataStorageWriteStatus.WRITTEN,
        csv_path=request.csv_path,
        metadata_path=request.metadata_path,
        bars_written=len(candles),
        first_timestamp_ms=first_timestamp,
        last_timestamp_ms=last_timestamp,
        partial=False,
        accepted=False,
        loadable=False,
        validated=False,
        metadata={"source": "bybit", "smoke": True},
    )


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


def _write_candles_csv(csv_path: Path, candles: tuple[object, ...]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("x", newline="", encoding="utf-8") as csv_file:
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
    candles: tuple[object, ...],
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
    }
    with metadata_path.open("x", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, sort_keys=True)
