from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest

from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv import (
    CanonicalOHLCVValidator,
    OHLCVMaintenanceApplicationService,
    OHLCVMaintenanceService,
    OHLCVStore,
    ValidationCancelled,
)
from leonardo.storage import OHLCVSidecarV1


def _market(symbol: str = "BTCUSDT") -> MarketId:
    return canonicalize_market_id("benchmark", "linear", symbol, "1m")


def _write_committed_rows(store: OHLCVStore, market: MarketId, rows: int) -> None:
    csv_path = store.csv_path(market)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("ts_ms,open,high,low,close,volume\n")
        for index in range(rows):
            handle.write(f"{index * 60000},100,101,99,100.5,1\n")
    stat = csv_path.stat()
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    now = datetime.now(UTC)
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=digest,
        row_count=rows,
        first_timestamp_ms=0,
        last_timestamp_ms=(rows - 1) * 60000,
        source="performance_test",
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


def _wait_until(predicate, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_canonical_validation_reports_bounded_row_progress(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed_rows(store, market, 20_000)
    progress: list[tuple[int, int | None]] = []

    report = CanonicalOHLCVValidator().validate(
        store,
        market,
        progress_callback=lambda current, total: progress.append((current, total)),
        progress_interval_rows=5_000,
    )

    assert report.status == "ok"
    assert progress == [
        (5_000, 20_000),
        (10_000, 20_000),
        (15_000, 20_000),
        (20_000, 20_000),
    ]


def test_cancelled_validation_never_publishes_sidecar_evidence(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed_rows(store, market, 30_000)
    sidecar_before = store.sidecar_path(market).read_bytes()
    cancelled = Event()

    def cancel_after_first_chunk(current: int, _total: int | None) -> None:
        if current >= 5_000:
            cancelled.set()

    maintenance = OHLCVMaintenanceService(store, CanonicalOHLCVValidator())
    with pytest.raises(ValidationCancelled):
        maintenance.validate(
            market,
            cancel_requested=cancelled.is_set,
            progress_callback=cancel_after_first_chunk,
        )

    assert store.sidecar_path(market).read_bytes() == sidecar_before
    assert store.read_sidecar(market).validation_status == "unknown"


def test_application_cancellation_stops_worker_before_publication(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed_rows(store, market, 200_000)
    sidecar_before = store.sidecar_path(market).read_bytes()
    runner = CoreRunner(TaskManager())
    maintenance = OHLCVMaintenanceService(store, CanonicalOHLCVValidator())
    application = OHLCVMaintenanceApplicationService(runner, maintenance)
    progress_seen = Event()
    result_seen = Event()
    results = []

    runner.start()
    try:
        submission = application.submit_validation(
            market,
            progress_callback=lambda progress: (
                progress_seen.set() if (progress.current or 0) >= 8_192 else None
            ),
            result_callback=lambda result: (results.append(result), result_seen.set()),
        )
        assert progress_seen.wait(2.0)
        assert application.cancel(submission.task_id) is True
        assert result_seen.wait(2.0)
        assert results[0].status == "cancelled"
        assert _wait_until(
            lambda: submission.task_id not in application._validation_cancel_events,
            timeout=2.0,
        )
        assert store.sidecar_path(market).read_bytes() == sidecar_before
        assert store.read_sidecar(market).validation_status == "unknown"
    finally:
        runner.shutdown()


def test_canonical_validation_hashes_large_csv_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from leonardo.ohlcv import validation as validation_module

    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed_rows(store, market, 10_000)
    original_sha256 = validation_module._sha256
    hashed_paths: list[Path] = []

    def counted_sha256(path: Path, **kwargs) -> str:
        hashed_paths.append(path)
        return original_sha256(path, **kwargs)

    monkeypatch.setattr(validation_module, "_sha256", counted_sha256)

    result = OHLCVMaintenanceService(store, CanonicalOHLCVValidator()).validate(market)

    assert result.accepted is True
    assert hashed_paths.count(store.csv_path(market)) == 1
