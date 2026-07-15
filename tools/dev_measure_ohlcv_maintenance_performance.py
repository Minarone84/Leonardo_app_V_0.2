"""Measure OHLCV Maintenance discovery, validation, memory, and cancellation.

The tool uses only temporary synthetic datasets. It does not access providers,
credentials, or the configured historical-data directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv import (
    CanonicalOHLCVValidator,
    OHLCVMaintenanceService,
    OHLCVStore,
    ValidationCancelled,
)
from leonardo.storage import OHLCVSidecarV1


def main() -> int:
    args = _parse_args()
    with tempfile.TemporaryDirectory(prefix="leo-task1013-") as temp_dir:
        root = Path(temp_dir)
        large_root = root / "large"
        discovery_root = root / "discovery"
        store = OHLCVStore(large_root)
        market = canonicalize_market_id("benchmark", "linear", "BTCUSDT", "1m")
        _write_committed_rows(store, market, args.rows)

        validator = CanonicalOHLCVValidator()
        elapsed_samples: list[float] = []
        report = None
        for _ in range(args.repetitions):
            started = time.perf_counter()
            report = validator.validate(store, market)
            elapsed_samples.append(time.perf_counter() - started)
        assert report is not None
        validation_seconds = statistics.median(elapsed_samples)
        rows_per_second = args.rows / validation_seconds

        memory_rows = min(args.rows, args.memory_rows)
        memory_store = OHLCVStore(root / "memory")
        memory_market = canonicalize_market_id("benchmark", "linear", "ETHUSDT", "1m")
        _write_committed_rows(memory_store, memory_market, memory_rows)
        tracemalloc.start()
        validator.validate(memory_store, memory_market)
        _current, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        discovery_store = OHLCVStore(discovery_root)
        _write_discovery_fixtures(discovery_store, args.datasets)
        maintenance = OHLCVMaintenanceService(discovery_store, validator)
        started = time.perf_counter()
        discovery = maintenance.discover()
        discovery_seconds = time.perf_counter() - started

        cancellation_seconds = _measure_cancellation(store, market)

        results = {
            "rows": args.rows,
            "file_size_bytes": store.csv_path(market).stat().st_size,
            "validation_seconds_median": round(validation_seconds, 6),
            "validation_rows_per_second": round(rows_per_second, 2),
            "validation_samples_seconds": [round(item, 6) for item in elapsed_samples],
            "memory_rows": memory_rows,
            "peak_python_memory_bytes": peak_bytes,
            "discovery_datasets": len(discovery.datasets),
            "discovery_seconds": round(discovery_seconds, 6),
            "cancellation_seconds": round(cancellation_seconds, 6),
            "validation_status": report.status,
        }
        print(json.dumps(results, indent=2, sort_keys=True))

        failures: list[str] = []
        if report.status != "ok":
            failures.append(f"validation status was {report.status!r}")
        if rows_per_second < args.minimum_rows_per_second:
            failures.append(
                f"validation throughput {rows_per_second:.0f} rows/s is below "
                f"{args.minimum_rows_per_second:.0f} rows/s"
            )
        if peak_bytes > args.maximum_peak_memory_mib * 1024 * 1024:
            failures.append(
                f"peak Python memory {peak_bytes / 1024 / 1024:.1f} MiB exceeds "
                f"{args.maximum_peak_memory_mib:.1f} MiB"
            )
        if len(discovery.datasets) != args.datasets:
            failures.append(
                f"discovery returned {len(discovery.datasets)} of {args.datasets} datasets"
            )
        if discovery_seconds > args.maximum_discovery_seconds:
            failures.append(
                f"discovery took {discovery_seconds:.2f}s, above "
                f"{args.maximum_discovery_seconds:.2f}s"
            )
        if cancellation_seconds > args.maximum_cancellation_seconds:
            failures.append(
                f"cancellation took {cancellation_seconds:.2f}s, above "
                f"{args.maximum_cancellation_seconds:.2f}s"
            )
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}")
            return 1

        print("TASK 1013 PERFORMANCE SMOKE: PASS")
        return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--memory-rows", type=int, default=100_000)
    parser.add_argument("--datasets", type=int, default=500)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--minimum-rows-per-second", type=float, default=25_000)
    parser.add_argument("--maximum-peak-memory-mib", type=float, default=64.0)
    parser.add_argument("--maximum-discovery-seconds", type=float, default=10.0)
    parser.add_argument("--maximum-cancellation-seconds", type=float, default=2.0)
    args = parser.parse_args()
    for name in ("rows", "memory_rows", "datasets", "repetitions"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return args


def _write_committed_rows(store: OHLCVStore, market: MarketId, rows: int) -> None:
    csv_path = store.csv_path(market)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with csv_path.open("wb") as handle:
        header = b"ts_ms,open,high,low,close,volume\n"
        handle.write(header)
        digest.update(header)
        for index in range(rows):
            line = f"{index * 60000},100,101,99,100.5,1\n".encode("ascii")
            handle.write(line)
            digest.update(line)
    stat = csv_path.stat()
    now = datetime.now(UTC)
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=digest.hexdigest(),
        row_count=rows,
        first_timestamp_ms=0,
        last_timestamp_ms=(rows - 1) * 60000,
        source="task1013_performance",
        persistence_status="committed",
        validation_status="unknown",
        lineage={"file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns},
        created_at_utc=now,
        updated_at_utc=now,
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _write_discovery_fixtures(store: OHLCVStore, count: int) -> None:
    for index in range(count):
        market = canonicalize_market_id(
            "benchmark",
            "linear",
            f"SYM{index:05d}USDT",
            "1m",
        )
        _write_committed_rows(store, market, 1)


def _measure_cancellation(store: OHLCVStore, market: MarketId) -> float:
    maintenance = OHLCVMaintenanceService(store, CanonicalOHLCVValidator())
    sidecar_before = store.sidecar_path(market).read_bytes()
    cancel_requested = Event()
    progress_seen = Event()

    def on_progress(current: int, _total: int | None) -> None:
        if current >= 8_192:
            progress_seen.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            maintenance.validate,
            market,
            cancel_requested=cancel_requested.is_set,
            progress_callback=on_progress,
        )
        if not progress_seen.wait(5.0):
            raise RuntimeError("validation did not emit measurable progress")
        started = time.perf_counter()
        cancel_requested.set()
        try:
            future.result(timeout=5.0)
        except ValidationCancelled:
            pass
        else:
            raise RuntimeError("validation completed instead of honoring cancellation")
        elapsed = time.perf_counter() - started

    if store.sidecar_path(market).read_bytes() != sidecar_before:
        raise RuntimeError("cancelled validation mutated sidecar evidence")
    return elapsed


if __name__ == "__main__":
    raise SystemExit(main())
