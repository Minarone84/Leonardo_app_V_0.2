from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest

from leonardo.connection import ConnectionApplicationService, ProviderCandle, ProviderRegistry
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv import (
    Candle,
    CanonicalOHLCVValidator,
    DownloadBatchRequest,
    HistoricalDownloadService,
    OHLCVMaintenanceApplicationService,
    OHLCVMaintenanceService,
    OHLCVStore,
)
from leonardo.research import AcceptedDatasetCatalog
from leonardo.storage import OHLCVSidecarV1


def _market(timeframe: str = "1m", symbol: str = "BTCUSDT") -> MarketId:
    return canonicalize_market_id("bybit", "linear", symbol, timeframe)


def _maintenance(store: OHLCVStore) -> OHLCVMaintenanceService:
    return OHLCVMaintenanceService(
        store,
        CanonicalOHLCVValidator(),
        audit_log=AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )


def _valid_candles() -> tuple[Candle, ...]:
    return (
        Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
        Candle(120_000, 1.5, 2.5, 1.0, 2.0, 12.0),
        Candle(180_000, 2.0, 3.0, 1.5, 2.5, 14.0),
    )


def _write_committed(
    store: OHLCVStore,
    market: MarketId,
    candles: tuple[Candle, ...] | None = None,
) -> None:
    store.write(
        market,
        candles or _valid_candles(),
        source="test",
        persistence_status="committed",
        lineage={"download_mode": "test"},
    )


def _write_raw_dataset(
    store: OHLCVStore,
    market: MarketId,
    *,
    header: tuple[str, ...] = ("ts_ms", "open", "high", "low", "close", "volume"),
    rows: tuple[tuple[object, ...], ...],
    persistence_status: str = "committed",
    sidecar_market: MarketId | None = None,
) -> None:
    directory = store.dataset_dir(market)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = store.csv_path(market)
    csv_path.write_text(
        ",".join(header)
        + "\n"
        + "".join(",".join(str(value) for value in row) + "\n" for row in rows),
        encoding="utf-8",
    )
    stat = csv_path.stat()
    timestamps: list[int] = []
    if "ts_ms" in header:
        index = header.index("ts_ms")
        for row in rows:
            try:
                timestamps.append(int(row[index]))
            except (TypeError, ValueError, IndexError):
                pass
    first = timestamps[0] if timestamps else None
    last = timestamps[-1] if timestamps else None
    if first is not None and last is not None and first > last:
        first, last = min(timestamps), max(timestamps)
    sidecar = OHLCVSidecarV1(
        market_id=sidecar_market or market,
        file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        row_count=len(rows),
        first_timestamp_ms=first,
        last_timestamp_ms=last,
        source="raw-test",
        persistence_status=persistence_status,
        validation_status="unknown",
        lineage={"file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns},
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _codes(result) -> set[str]:
    return set(result.report.issue_codes)


def test_unknown_downloaded_dataset_becomes_research_accepted_without_csv_mutation(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    csv_path = store.csv_path(market)
    before_csv = (csv_path.read_bytes(), csv_path.stat().st_mtime_ns)
    assert store.read_sidecar(market).validation_status == "unknown"

    discovery = _maintenance(store).discover()
    assert len(discovery.datasets) == 1
    assert discovery.datasets[0].market_id == market
    assert discovery.datasets[0].validation_status == "unknown"

    result = _maintenance(store).validate(market)

    assert result.accepted is True
    assert result.sidecar_published is True
    assert result.publication_changed is True
    assert result.report.status == "ok"
    assert store.read_sidecar(market).validation_status == "ok"
    assert (csv_path.read_bytes(), csv_path.stat().st_mtime_ns) == before_csv
    accepted = AcceptedDatasetCatalog(tmp_path).list_accepted()
    assert [item.market_id for item in accepted] == [market]
    assert not tuple(store.dataset_dir(market).glob("*.tmp"))


@pytest.mark.parametrize(
    ("candles", "expected_code"),
    [
        ((Candle(60_000, 3.0, 2.0, 1.0, 1.5, 10.0),), "open_outside_range"),
        ((Candle(60_000, 1.0, 2.0, 0.5, 1.5, -1.0),), "negative_volume"),
        ((Candle(60_000, float("nan"), 2.0, 0.5, 1.5, 10.0),), "non_finite_value"),
    ],
)
def test_domain_errors_publish_error_and_remain_excluded(
    tmp_path: Path,
    candles: tuple[Candle, ...],
    expected_code: str,
) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market, candles)

    result = _maintenance(store).validate(market)

    assert result.report.status == "error"
    assert expected_code in _codes(result)
    assert result.sidecar_published is True
    assert result.accepted is False
    assert store.read_sidecar(market).validation_status == "error"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


def test_fixed_timeframe_gap_publishes_warning_and_research_rejects(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(
        store,
        market,
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(180_000, 2, 3, 1.5, 2.5, 12),
        ),
    )

    result = _maintenance(store).validate(market)

    assert result.report.status == "warning"
    assert "timeframe_gap" in _codes(result)
    assert result.sidecar_published is True
    assert store.read_sidecar(market).validation_status == "warning"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


@pytest.mark.parametrize(
    ("rows", "expected_code"),
    [
        (
            (
                (60_000, 1, 2, 0.5, 1.5, 10),
                (60_000, 1, 2, 0.5, 1.5, 10),
            ),
            "duplicate_timestamp",
        ),
        (
            (
                (60_000, 1, 2, 0.5, 1.5, 10),
                (180_000, 1, 2, 0.5, 1.5, 10),
                (120_000, 1, 2, 0.5, 1.5, 10),
            ),
            "timestamp_out_of_order",
        ),
        (
            (
                (60_000, "bad", 2, 0.5, 1.5, 10),
                (120_000, 1, 2, 0.5, 1.5, 10),
            ),
            "numeric_value_invalid",
        ),
        (
            (
                (60_000, 1, 2, 0.5, 1.5, 10),
                ("bad", 1, 2, 0.5, 1.5, 10),
            ),
            "timestamp_invalid",
        ),
    ],
)
def test_raw_csv_defects_are_reported_deterministically(
    tmp_path: Path,
    rows: tuple[tuple[object, ...], ...],
    expected_code: str,
) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_raw_dataset(store, market, rows=rows)

    first = _maintenance(store).validate(market)
    second_report = CanonicalOHLCVValidator().validate(store, market)

    assert first.report.status == "error"
    assert expected_code in _codes(first)
    assert first.report.issue_codes == second_report.issue_codes
    assert store.read_sidecar(market).validation_status == "error"


def test_invalid_schema_reports_missing_and_ordered_column_errors(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_raw_dataset(
        store,
        market,
        header=("open", "ts_ms", "high", "low", "close"),
        rows=((1, 60_000, 2, 0.5, 1.5),),
    )

    result = _maintenance(store).validate(market)

    assert result.report.status == "error"
    assert {"missing_column", "column_order_invalid"} <= _codes(result)
    assert result.sidecar_published is True
    assert store.read_sidecar(market).validation_status == "error"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_sidecar", "sidecar_missing"),
        ("missing_csv", "csv_missing"),
        ("partial", "persistence_not_final"),
        ("unsupported_sidecar", "sidecar_invalid"),
        ("identity_mismatch", "sidecar_market_mismatch"),
        ("stale_hash", "sidecar_hash_stale"),
    ],
)
def test_untrusted_or_incomplete_evidence_never_publishes_acceptance(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)

    if mutation == "missing_sidecar":
        store.sidecar_path(market).unlink()
    elif mutation == "missing_csv":
        store.csv_path(market).unlink()
    elif mutation == "partial":
        _write_raw_dataset(store, market, rows=((60_000, 1, 2, 0.5, 1.5, 10),), persistence_status="partial")
    elif mutation == "unsupported_sidecar":
        payload = json.loads(store.sidecar_path(market).read_text(encoding="utf-8"))
        payload["schema_version"] = "2.0"
        store.sidecar_path(market).write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "identity_mismatch":
        payload = json.loads(store.sidecar_path(market).read_text(encoding="utf-8"))
        payload["market_id"]["symbol"] = "ETHUSDT"
        store.sidecar_path(market).write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "stale_hash":
        with store.csv_path(market).open("a", encoding="utf-8") as handle:
            handle.write("240000,3,4,2.5,3.5,16\n")

    result = _maintenance(store).validate(market)

    assert expected_code in _codes(result)
    assert result.sidecar_published is False
    assert result.accepted is False
    if store.sidecar_path(market).is_file() and mutation not in {"unsupported_sidecar", "identity_mismatch"}:
        assert store.read_sidecar(market).validation_status != "ok"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()



def test_empty_dataset_publishes_error_without_false_acceptance(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_raw_dataset(store, market, rows=())

    result = _maintenance(store).validate(market)

    assert result.report.status == "error"
    assert "dataset_empty" in _codes(result)
    assert result.sidecar_published is True
    assert store.read_sidecar(market).validation_status == "error"
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


def test_sidecar_row_count_mismatch_blocks_publication(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    payload = json.loads(store.sidecar_path(market).read_text(encoding="utf-8"))
    payload["row_count"] = 4
    store.sidecar_path(market).write_text(json.dumps(payload), encoding="utf-8")

    result = _maintenance(store).validate(market)

    assert "sidecar_row_count_mismatch" in _codes(result)
    assert result.sidecar_published is False
    assert store.read_sidecar(market).validation_status == "unknown"


def test_previously_accepted_dataset_is_rejected_after_csv_mutation(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    assert _maintenance(store).validate(market).accepted is True
    assert AcceptedDatasetCatalog(tmp_path).list_accepted()

    with store.csv_path(market).open("a", encoding="utf-8") as handle:
        handle.write("240000,3,4,2.5,3.5,16\n")

    result = _maintenance(store).validate(market)

    assert "sidecar_hash_stale" in _codes(result)
    assert result.sidecar_published is False
    assert AcceptedDatasetCatalog(tmp_path).list_accepted() == ()


def test_sidecar_write_failure_leaves_previous_unknown_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    sidecar_path = store.sidecar_path(market)
    before = (sidecar_path.read_bytes(), sidecar_path.stat().st_mtime_ns)

    def fail_write(_path, _sidecar):
        raise OSError("simulated atomic publication failure")

    monkeypatch.setattr(store, "_write_sidecar_atomic", fail_write)

    result = _maintenance(store).validate(market)

    assert result.sidecar_published is False
    assert "simulated atomic publication failure" in (result.publication_error or "")
    assert (sidecar_path.read_bytes(), sidecar_path.stat().st_mtime_ns) == before
    assert store.read_sidecar(market).validation_status == "unknown"


def test_noncanonical_or_unsupported_timeframe_is_rejected_at_boundary(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    invalid = MarketId("bybit", "linear", "BTCUSDT", "13x")

    with pytest.raises(ValueError, match="invalid timeframe unit"):
        CanonicalOHLCVValidator().validate(store, invalid)

def test_csv_change_during_validation_blocks_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from leonardo.ohlcv import validation as validation_module

    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    original_sha256 = validation_module._sha256
    changed = False

    def mutate_after_hash(path: Path) -> str:
        nonlocal changed
        result = original_sha256(path)
        if path.name == "candles.csv" and not changed:
            changed = True
            with path.open("a", encoding="utf-8") as handle:
                handle.write("240000,3,4,2.5,3.5,16\n")
        return result

    monkeypatch.setattr(validation_module, "_sha256", mutate_after_hash)

    result = _maintenance(store).validate(market)

    assert "csv_changed_during_validation" in _codes(result)
    assert result.sidecar_published is False
    assert store.read_sidecar(market).validation_status == "unknown"


def test_sidecar_change_after_validation_causes_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    original_publish = store.publish_validation

    def mutate_then_publish(*args, **kwargs):
        path = store.sidecar_path(market)
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(store, "publish_validation", mutate_then_publish)

    result = _maintenance(store).validate(market)

    assert result.report.status == "ok"
    assert result.sidecar_published is False
    assert result.publication_error is not None
    assert store.read_sidecar(market).validation_status == "unknown"


def test_revalidation_is_idempotent_and_does_not_rewrite_sidecar(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    service = _maintenance(store)

    first = service.validate(market)
    sidecar_path = store.sidecar_path(market)
    after_first = (sidecar_path.read_bytes(), sidecar_path.stat().st_mtime_ns)
    second = service.validate(market)
    after_second = (sidecar_path.read_bytes(), sidecar_path.stat().st_mtime_ns)

    assert first.publication_changed is True
    assert second.publication_changed is False
    assert first.report.status == second.report.status == "ok"
    assert first.report.issue_codes == second.report.issue_codes == ()
    assert after_second == after_first


def _utc_ms(year: int, month: int, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


def test_calendar_month_cadence_is_accepted_without_fixed_duration_warning(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market("1M")
    _write_committed(
        store,
        market,
        (
            Candle(_utc_ms(2026, 1), 1, 2, 0.5, 1.5, 10),
            Candle(_utc_ms(2026, 2), 1.5, 2.5, 1, 2, 11),
            Candle(_utc_ms(2026, 3), 2, 3, 1.5, 2.5, 12),
        ),
    )

    result = _maintenance(store).validate(market)

    assert result.report.status == "ok"
    assert result.accepted is True
    assert "timeframe_gap" not in _codes(result)


def test_calendar_month_gap_is_warning_and_not_accepted(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market("1M")
    _write_committed(
        store,
        market,
        (
            Candle(_utc_ms(2026, 1), 1, 2, 0.5, 1.5, 10),
            Candle(_utc_ms(2026, 3), 2, 3, 1.5, 2.5, 12),
        ),
    )

    result = _maintenance(store).validate(market)

    assert result.report.status == "warning"
    assert "timeframe_gap" in _codes(result)
    assert result.accepted is False


def test_discovery_reports_noncanonical_storage_without_promoting_it(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    bad = tmp_path / "ByBit" / "linear" / "BTC-USDT" / "1m" / "ohlcv"
    bad.mkdir(parents=True)
    (bad / "candles.csv").write_text("ts_ms,open,high,low,close,volume\n", encoding="utf-8")

    report = _maintenance(store).discover()

    assert report.datasets == ()
    assert [item.code for item in report.rejected] == ["noncanonical_storage_identity"]


class _DownloadProvider:
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

    async def fetch_ohlcv_historical(self, **_kwargs):
        return (
            ProviderCandle(60_000, 1, 2, 0.5, 1.5, 10),
            ProviderCandle(120_000, 1.5, 2.5, 1, 2, 12),
            ProviderCandle(180_000, 2, 3, 1.5, 2.5, 14),
        )


def test_real_download_to_maintenance_to_research_vertical(tmp_path: Path) -> None:
    registry = ProviderRegistry()
    registry.register("bybit", _DownloadProvider)
    connections = ConnectionApplicationService(registry, ConnectionRegistry())
    store = OHLCVStore(tmp_path)
    downloader = HistoricalDownloadService(
        connections,
        store,
        AuditLog(InMemoryAuditSink()),
        actor_id="tester",
    )
    request = DownloadBatchRequest(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframes=("1m",),
        start_ms=60_000,
        end_ms=180_000,
    )

    downloaded = asyncio.run(downloader.run_batch(request))
    market = downloaded.results[0].market_id
    assert store.read_sidecar(market).validation_status == "unknown"

    maintained = _maintenance(store).validate(market)

    assert maintained.accepted is True
    assert [item.market_id for item in AcceptedDatasetCatalog(tmp_path).list_accepted()] == [market]


def test_application_service_runs_validation_through_shared_core(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market()
    _write_committed(store, market)
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(runner, _maintenance(store))
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_validation(
            market,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(2.0)
        assert results[0].status == "completed"
        assert results[0].value.accepted is True
        assert store.read_sidecar(market).validation_status == "ok"
    finally:
        runner.shutdown()


def test_leonardo_app_composes_one_maintenance_service(tmp_path: Path) -> None:
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import load_default_config

    app = LeonardoApp(load_default_config(tmp_path))

    assert app.context.ohlcv_maintenance_service is app.ohlcv_maintenance_service
    assert app.ohlcv_maintenance_domain._store is app.ohlcv_store
    assert app.ohlcv_maintenance_service._core_runner is app.core_runner


def test_calendar_month_end_of_month_progression_is_accepted(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    market = _market("1M", symbol="ETHUSDT")
    _write_committed(
        store,
        market,
        (
            Candle(_utc_ms(2026, 1, 31), 1, 2, 0.5, 1.5, 10),
            Candle(_utc_ms(2026, 2, 28), 1.5, 2.5, 1, 2, 11),
            Candle(_utc_ms(2026, 3, 31), 2, 3, 1.5, 2.5, 12),
        ),
    )

    result = _maintenance(store).validate(market)

    assert result.report.status == "ok"
    assert result.accepted is True
