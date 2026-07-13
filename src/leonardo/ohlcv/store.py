"""Canonical OHLCV CSV and sidecar persistence."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from leonardo.data import MarketId, timeframe_to_storage_segment
from leonardo.storage import OHLCVSidecarV1

_CSV_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class Candle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class DatasetInspection:
    csv_path: Path
    sidecar_path: Path
    csv_exists: bool
    metadata_exists: bool
    metadata_valid: bool
    first_ts_ms: int | None
    last_ts_ms: int | None
    row_count: int
    source: str
    issues: tuple[str, ...]


class OHLCVStore:
    """Own the only physical write path for historical OHLCV datasets."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def dataset_dir(self, market: MarketId) -> Path:
        return (
            self._root
            / market.exchange
            / market.market_type
            / market.symbol
            / timeframe_to_storage_segment(market.timeframe)
            / "ohlcv"
        )

    def csv_path(self, market: MarketId) -> Path:
        return self.dataset_dir(market) / "candles.csv"

    def sidecar_path(self, market: MarketId) -> Path:
        return self.dataset_dir(market) / "candles.meta.json"

    def inspect(self, market: MarketId) -> DatasetInspection:
        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)
        if not csv_path.is_file():
            return DatasetInspection(
                csv_path=csv_path,
                sidecar_path=sidecar_path,
                csv_exists=False,
                metadata_exists=sidecar_path.is_file(),
                metadata_valid=False,
                first_ts_ms=None,
                last_ts_ms=None,
                row_count=0,
                source="missing",
                issues=("csv_missing",) if sidecar_path.is_file() else (),
            )

        issues: list[str] = []
        metadata_exists = sidecar_path.is_file()
        if metadata_exists:
            try:
                sidecar = self.read_sidecar(market)
                stat = csv_path.stat()
                lineage = sidecar.lineage
                fingerprint_matches = (
                    lineage.get("file_size") == stat.st_size
                    and lineage.get("file_mtime_ns") == stat.st_mtime_ns
                )
                if sidecar.market_id != market:
                    issues.append("metadata_market_mismatch")
                elif not fingerprint_matches:
                    issues.append("metadata_fingerprint_stale")
                else:
                    return DatasetInspection(
                        csv_path=csv_path,
                        sidecar_path=sidecar_path,
                        csv_exists=True,
                        metadata_exists=True,
                        metadata_valid=True,
                        first_ts_ms=sidecar.first_timestamp_ms,
                        last_ts_ms=sidecar.last_timestamp_ms,
                        row_count=sidecar.row_count,
                        source="sidecar",
                        issues=(),
                    )
            except Exception as error:
                issues.append(f"metadata_invalid:{type(error).__name__}")
        first_ts, last_ts, row_count, scan_issues = self._scan_csv_identity(csv_path)
        issues.extend(scan_issues)
        return DatasetInspection(
            csv_path=csv_path,
            sidecar_path=sidecar_path,
            csv_exists=True,
            metadata_exists=metadata_exists,
            metadata_valid=False,
            first_ts_ms=first_ts,
            last_ts_ms=last_ts,
            row_count=row_count,
            source="csv_scan",
            issues=tuple(issues),
        )

    def read(self, market: MarketId) -> list[Candle]:
        path = self.csv_path(market)
        if not path.is_file():
            return []
        candles: list[Candle] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
                raise ValueError(f"invalid OHLCV CSV columns: {reader.fieldnames!r}")
            for line_no, row in enumerate(reader, start=2):
                try:
                    candles.append(
                        Candle(
                            ts_ms=int(row["ts_ms"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                        )
                    )
                except (TypeError, ValueError, KeyError) as error:
                    raise ValueError(f"invalid OHLCV row at line {line_no}") from error
        return candles

    def write(
        self,
        market: MarketId,
        candles: Iterable[Candle],
        *,
        source: str,
        persistence_status: str,
        warnings: Iterable[str] = (),
        lineage: dict[str, object] | None = None,
    ) -> OHLCVSidecarV1:
        normalized = merge_idempotent((), candles)
        if not normalized:
            raise ValueError("cannot persist an empty OHLCV dataset")
        directory = self.dataset_dir(market)
        directory.mkdir(parents=True, exist_ok=True)
        csv_path = self.csv_path(market)
        self._write_csv_atomic(csv_path, normalized)
        return self._write_sidecar_for_existing_csv(
            market,
            normalized,
            source=source,
            persistence_status=persistence_status,
            warnings=warnings,
            lineage=lineage,
        )

    def finalize(
        self,
        market: MarketId,
        *,
        source: str,
        warnings: Iterable[str] = (),
        lineage: dict[str, object] | None = None,
    ) -> OHLCVSidecarV1:
        candles = self.read(market)
        if not candles:
            raise ValueError("cannot finalize an empty or missing OHLCV dataset")
        return self._write_sidecar_for_existing_csv(
            market,
            candles,
            source=source,
            persistence_status="committed",
            warnings=warnings,
            lineage=lineage,
        )

    def _write_sidecar_for_existing_csv(
        self,
        market: MarketId,
        candles: list[Candle],
        *,
        source: str,
        persistence_status: str,
        warnings: Iterable[str],
        lineage: dict[str, object] | None,
    ) -> OHLCVSidecarV1:
        csv_path = self.csv_path(market)
        stat = csv_path.stat()
        previous = self._try_read_sidecar(market)
        created_at = previous.created_at_utc if previous is not None else datetime.now(UTC)
        merged_lineage = dict(lineage or {})
        merged_lineage.update(
            {
                "file_size": stat.st_size,
                "file_mtime_ns": stat.st_mtime_ns,
            }
        )
        sidecar = OHLCVSidecarV1(
            market_id=market,
            file_sha256=_sha256(csv_path),
            row_count=len(candles),
            first_timestamp_ms=candles[0].ts_ms,
            last_timestamp_ms=candles[-1].ts_ms,
            source=source,
            persistence_status=persistence_status,
            validation_status="unknown",
            warnings=tuple(warnings),
            lineage=merged_lineage,
            created_at_utc=created_at,
            updated_at_utc=datetime.now(UTC),
        )
        self._write_sidecar_atomic(self.sidecar_path(market), sidecar)
        return sidecar

    def read_sidecar(self, market: MarketId) -> OHLCVSidecarV1:
        path = self.sidecar_path(market)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("OHLCV sidecar root must be an object")
        return OHLCVSidecarV1.from_dict(payload)

    def _try_read_sidecar(self, market: MarketId) -> OHLCVSidecarV1 | None:
        try:
            return self.read_sidecar(market)
        except Exception:
            return None

    @staticmethod
    def _write_csv_atomic(path: Path, candles: list[Candle]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".candles-", suffix=".csv.tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(_CSV_COLUMNS)
                for candle in candles:
                    writer.writerow(
                        (
                            candle.ts_ms,
                            candle.open,
                            candle.high,
                            candle.low,
                            candle.close,
                            candle.volume,
                        )
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_sidecar_atomic(path: Path, sidecar: OHLCVSidecarV1) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".candles-", suffix=".json.tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(sidecar.to_dict(), handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _scan_csv_identity(path: Path) -> tuple[int | None, int | None, int, tuple[str, ...]]:
        first: int | None = None
        last: int | None = None
        count = 0
        issues: list[str] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
                    return None, None, 0, ("csv_columns_invalid",)
                for row in reader:
                    timestamp = int(row["ts_ms"])
                    if first is None:
                        first = timestamp
                    last = timestamp
                    count += 1
        except Exception as error:
            issues.append(f"csv_scan_failed:{type(error).__name__}")
        return first, last, count, tuple(issues)


def merge_idempotent(existing: Iterable[Candle], incoming: Iterable[Candle]) -> list[Candle]:
    """Merge candles by open timestamp; incoming values win on overlap."""

    by_timestamp = {int(item.ts_ms): item for item in existing}
    for item in incoming:
        by_timestamp[int(item.ts_ms)] = Candle(
            ts_ms=int(item.ts_ms),
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=float(item.volume),
        )
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
