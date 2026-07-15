from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from threading import Event

import pytest

from leonardo.connection import (
    ConnectionApplicationService,
    HistoricalProviderRequestError,
    ProviderCandle,
    ProviderRegistry,
)
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import (
    Candle,
    CanonicalOHLCVValidator,
    HistoricalDownloadService,
    MaintenanceRepairResult,
    OHLCVMaintenanceApplicationService,
    OHLCVMaintenanceService,
    OHLCVStore,
)
from leonardo.research import AcceptedDatasetCatalog
from leonardo.storage import OHLCVSidecarV1


def _market():
    return canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")


def _maintenance(store: OHLCVStore) -> OHLCVMaintenanceService:
    return OHLCVMaintenanceService(
        store,
        CanonicalOHLCVValidator(),
        audit_log=AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )


def _write(store: OHLCVStore, candles: tuple[Candle, ...]) -> None:
    store.write(
        _market(),
        candles,
        source="test",
        persistence_status="committed",
        lineage={"download_mode": "test"},
    )


def _write_raw(store: OHLCVStore, rows: tuple[tuple[object, ...], ...]) -> None:
    market = _market()
    directory = store.dataset_dir(market)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = store.csv_path(market)
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n"
        + "".join(",".join(str(value) for value in row) + "\n" for row in rows),
        encoding="utf-8",
    )
    stat = csv_path.stat()
    timestamps = [int(row[0]) for row in rows]
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        row_count=len(rows),
        first_timestamp_ms=min(timestamps),
        last_timestamp_ms=max(timestamps),
        source="raw-test",
        persistence_status="committed",
        validation_status="unknown",
        lineage={"file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns},
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_gap_repair_plan_is_exact_and_read_only(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 12),
        ),
    )
    before = store.csv_path(_market()).read_bytes()

    plan = _maintenance(store).plan_repair(_market())

    assert plan.actionable is True
    assert len(plan.ranges) == 1
    assert plan.ranges[0].start_ts_ms == 120_000
    assert plan.ranges[0].end_ts_ms == 120_000
    assert plan.ranges[0].coverage_anchor_ts_ms == (120_000,)
    assert plan.ranges[0].issue_codes == ("timeframe_gap",)
    assert store.csv_path(_market()).read_bytes() == before


def test_invalid_candle_plan_uses_provider_replacement_range(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(120_000, 4, 3, 1, 2, 12),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )

    plan = _maintenance(store).plan_repair(_market())

    assert plan.actionable is True
    assert len(plan.ranges) == 1
    assert plan.ranges[0].start_ts_ms == 60_000
    assert plan.ranges[0].end_ts_ms == 180_000
    assert plan.ranges[0].coverage_anchor_ts_ms == (120_000,)
    assert "open_outside_range" in plan.ranges[0].issue_codes


def test_unparseable_numeric_row_is_not_silently_repaired(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write_raw(
        store,
        (
            (60_000, 1, 2, 0.5, 1.5, 10),
            (120_000, "bad", 2.5, 1, 2, 12),
        ),
    )

    plan = _maintenance(store).plan_repair(_market())

    assert plan.actionable is False
    assert any("numeric_value_invalid" in warning for warning in plan.warnings)


def test_repair_plan_rejects_changed_csv(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 12),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    with store.csv_path(_market()).open("a", encoding="utf-8") as handle:
        handle.write("240000,2.5,3.5,2,3,16\n")

    with pytest.raises(ValueError, match="stale because candles.csv changed"):
        maintenance.assert_repair_plan_current(plan)


class _RepairProvider:
    name = "bybit"

    def supported_markets(self):
        return {"linear"}

    def supported_timeframes(self, _market):
        return {"1m"}

    def max_historical_ohlcv_limit(self, _market):
        return 100

    async def open(self):
        return None

    async def close(self):
        return None

    async def get_server_time_ms(self):
        return 180_000

    async def oldest_historical_ohlcv_ts_ms(self, **_kwargs):
        return 60_000

    async def fetch_ohlcv_historical(self, **kwargs):
        start = kwargs.get("start_ms")
        end = kwargs.get("end_ms")
        rows = (
            ProviderCandle(60_000, 1, 2, 0.5, 1.5, 10),
            ProviderCandle(120_000, 1.5, 2.5, 1, 2, 12),
            ProviderCandle(180_000, 2, 3, 1.5, 2.5, 14),
        )
        return tuple(
            row
            for row in rows
            if (start is None or row.ts_ms >= start) and (end is None or row.ts_ms <= end)
        )


def _downloader(store: OHLCVStore) -> HistoricalDownloadService:
    registry = ProviderRegistry()
    registry.register("bybit", _RepairProvider)
    connections = ConnectionApplicationService(registry, ConnectionRegistry())
    return HistoricalDownloadService(
        connections,
        store,
        AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )


def test_explicit_repair_redownloads_gap_marks_provenance_and_admits_research(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(runner, maintenance, _downloader(store))
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_repair(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    task_result = results[0]
    assert task_result.status == "completed"
    assert isinstance(task_result.value, MaintenanceRepairResult)
    repair = task_result.value
    assert repair.outcome == "repaired_ok"
    assert repair.accepted is True
    assert repair.range_results[0].fetched_rows == 1
    assert [candle.ts_ms for candle in store.read(_market())] == [60_000, 120_000, 180_000]
    sidecar = store.read_sidecar(_market())
    assert sidecar.persistence_status == "repaired"
    assert sidecar.validation_status == "ok"
    assert sidecar.lineage["repair_count"] == 1
    assert len(sidecar.lineage["repair_history"]) == 1
    assert [item.market_id for item in AcceptedDatasetCatalog(tmp_path).list_accepted()] == [
        _market()
    ]


def test_mark_repaired_resets_validation_until_post_validation(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    # Simulate downloader replacement and its committed/unknown sidecar.
    store.write(
        _market(),
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(120_000, 1.5, 2.5, 1, 2, 12),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
        source="bybit",
        persistence_status="committed",
    )
    from leonardo.ohlcv import MaintenanceRepairRangeResult

    range_result = MaintenanceRepairRangeResult(
        repair_range=plan.ranges[0],
        fetched_rows=1,
        downloaded_first_ts_ms=120_000,
        downloaded_last_ts_ms=120_000,
        total_rows_after=3,
        file_path=store.csv_path(_market()),
    )

    sidecar = maintenance.mark_repair_completed(plan, (range_result,))

    assert sidecar.persistence_status == "repaired"
    assert sidecar.validation_status == "unknown"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


def test_provider_replacement_repairs_invalid_ohlc_anchor(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(120_000, 4, 3, 1, 2, 12),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(runner, maintenance, _downloader(store))
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_repair(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    repair = results[0].value
    assert repair.outcome == "repaired_ok"
    assert store.read(_market())[1] == Candle(120_000, 1.5, 2.5, 1, 2, 12)


class _SourceInvalidRepairProvider(_RepairProvider):
    async def fetch_ohlcv_historical(self, **kwargs):
        start = kwargs.get("start_ms")
        end = kwargs.get("end_ms")
        rows = (
            ProviderCandle(60_000, 1, 2, 0.5, 1.5, 10),
            ProviderCandle(120_000, 10, 5, 1, 2, 12),
            ProviderCandle(180_000, 2, 3, 1.5, 2.5, 14),
        )
        return tuple(
            row
            for row in rows
            if (start is None or row.ts_ms >= start) and (end is None or row.ts_ms <= end)
        )


def _source_invalid_downloader(store: OHLCVStore) -> HistoricalDownloadService:
    registry = ProviderRegistry()
    registry.register("bybit", _SourceInvalidRepairProvider)
    connections = ConnectionApplicationService(registry, ConnectionRegistry())
    return HistoricalDownloadService(
        connections,
        store,
        AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )


def test_provider_replacement_that_remains_invalid_reports_source_invalid(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(120_000, 4, 3, 1, 2, 12),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(
        runner, maintenance, _source_invalid_downloader(store)
    )
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_repair(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    task_result = results[0]
    assert task_result.status == "completed"
    assert isinstance(task_result.value, MaintenanceRepairResult)
    repair = task_result.value
    assert repair.outcome == "source_invalid"
    assert repair.source_invalid is True
    assert repair.source_invalid_anchors == (120_000,)
    assert repair.accepted is False
    assert repair.validation.report.status == "error"
    assert any(
        issue.timestamp_ms == 120_000 and issue.code == "open_outside_range"
        for issue in repair.validation.report.issues
    )
    assert any(
        "Source-invalid provider candle detected at ts_ms 120000" in warning
        and "No local correction was applied" in warning
        for warning in repair.warnings
    )
    sidecar = store.read_sidecar(_market())
    assert sidecar.persistence_status == "repaired"
    assert sidecar.validation_status == "error"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


def test_unrelated_post_repair_error_remains_validation_failed(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    store.write(
        _market(),
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(120_000, 1.5, 2.5, 1, 2, 12),
            Candle(180_000, 8, 3, 1.5, 2.5, 14),
        ),
        source="bybit",
        persistence_status="committed",
    )
    from leonardo.ohlcv import MaintenanceRepairRangeResult

    range_result = MaintenanceRepairRangeResult(
        repair_range=plan.ranges[0],
        fetched_rows=1,
        downloaded_first_ts_ms=120_000,
        downloaded_last_ts_ms=120_000,
        total_rows_after=3,
        file_path=store.csv_path(_market()),
    )
    repaired_sidecar = maintenance.mark_repair_completed(plan, (range_result,))
    validation = maintenance.validate(_market())

    result = maintenance.build_repair_result(
        plan,
        (range_result,),
        repaired_sidecar,
        validation,
    )

    assert result.outcome == "validation_failed"
    assert result.source_invalid is False
    assert result.source_invalid_anchors == ()
    assert any(issue.timestamp_ms == 180_000 for issue in result.validation.report.issues)


class _EmptyRepairProvider(_RepairProvider):
    async def fetch_ohlcv_historical(self, **_kwargs):
        return ()


def _empty_downloader(store: OHLCVStore) -> HistoricalDownloadService:
    registry = ProviderRegistry()
    registry.register("bybit", _EmptyRepairProvider)
    connections = ConnectionApplicationService(registry, ConnectionRegistry())
    return HistoricalDownloadService(
        connections,
        store,
        AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )


def test_repair_with_no_provider_rows_remains_research_blocked(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(
        runner, maintenance, _empty_downloader(store)
    )
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_repair(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    repair = results[0].value
    assert repair.outcome == "no_replacement_rows"
    assert repair.accepted is False
    sidecar = store.read_sidecar(_market())
    assert sidecar.persistence_status == "repaired"
    assert sidecar.validation_status == "warning"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


class _PermanentFailureRepairProvider(_RepairProvider):
    def __init__(self) -> None:
        self.attempts = 0

    async def fetch_ohlcv_historical(self, **_kwargs):
        self.attempts += 1
        raise HistoricalProviderRequestError(
            "Bybit API error 10001: params error",
            provider="bybit",
            operation="historical_ohlcv",
            retryable=False,
            code=10001,
        )


def test_permanent_provider_failure_during_repair_does_not_mutate_dataset(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(
        store,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
    )
    maintenance = _maintenance(store)
    plan = maintenance.plan_repair(_market())
    provider = _PermanentFailureRepairProvider()
    registry = ProviderRegistry()
    registry.register("bybit", lambda: provider)
    downloader = HistoricalDownloadService(
        ConnectionApplicationService(registry, ConnectionRegistry()),
        store,
        AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(runner, maintenance, downloader)
    completed = Event()
    results = []
    csv_before = store.csv_path(_market()).read_bytes()
    sidecar_before = store.sidecar_path(_market()).read_bytes()

    runner.start()
    try:
        application.submit_repair(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    assert results[0].status == "failed"
    assert provider.attempts == 1
    assert store.csv_path(_market()).read_bytes() == csv_before
    assert store.sidecar_path(_market()).read_bytes() == sidecar_before
