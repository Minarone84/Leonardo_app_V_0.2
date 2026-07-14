from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv import Candle, OHLCVStore
from leonardo.research import AcceptedDatasetCatalog
from leonardo.storage import OHLCVSidecarV1


def _write_dataset(
    root: Path,
    market: MarketId,
    *,
    persistence_status: str = "committed",
    validation_status: str = "ok",
    candles: tuple[Candle, ...] | None = None,
) -> OHLCVStore:
    store = OHLCVStore(root)
    rows = candles or (
        Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
        Candle(120_000, 1.5, 2.5, 1.0, 2.0, 12.0),
    )
    store.write(market, rows, source="test", persistence_status=persistence_status)
    csv_path = store.csv_path(market)
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        row_count=len(rows),
        first_timestamp_ms=rows[0].ts_ms,
        last_timestamp_ms=rows[-1].ts_ms,
        source="test",
        persistence_status=persistence_status,
        validation_status=validation_status,
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return store


def _codes(report) -> set[str]:
    return {item.code for item in report.rejected}


def test_catalog_lists_only_current_accepted_datasets(tmp_path: Path) -> None:
    accepted = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    unknown = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")
    partial = canonicalize_market_id("bybit", "linear", "SOLUSDT", "1m")
    _write_dataset(tmp_path, accepted)
    _write_dataset(tmp_path, unknown, validation_status="unknown")
    _write_dataset(tmp_path, partial, persistence_status="partial")

    report = AcceptedDatasetCatalog(tmp_path).scan()

    assert [item.market_id for item in report.accepted] == [accepted]
    assert report.accepted[0].row_count == 2
    assert report.accepted[0].validation_status == "ok"
    assert report.accepted[0].persistence_status == "committed"
    assert _codes(report) == {"validation_not_accepted", "persistence_not_final"}


def test_catalog_accepts_repaired_dataset_and_month_storage_segment(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "LINKUSDT", "1M")
    store = _write_dataset(tmp_path, market, persistence_status="repaired")

    accepted = AcceptedDatasetCatalog(tmp_path).list_accepted()

    assert len(accepted) == 1
    assert accepted[0].market_id == market
    assert accepted[0].persistence_status == "repaired"
    assert accepted[0].csv_path == store.csv_path(market)
    assert "1mo" in accepted[0].csv_path.parts


def test_catalog_rejects_csv_changed_after_acceptance(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = _write_dataset(tmp_path, market)
    with store.csv_path(market).open("a", encoding="utf-8") as handle:
        handle.write("180000,2,3,1,2.5,14\n")

    report = AcceptedDatasetCatalog(tmp_path).scan()

    assert report.accepted == ()
    assert _codes(report) == {"csv_hash_mismatch"}


def test_catalog_reports_missing_and_corrupt_evidence(tmp_path: Path) -> None:
    missing_sidecar = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    missing_csv = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")
    corrupt = canonicalize_market_id("bybit", "linear", "SOLUSDT", "1m")

    store_a = _write_dataset(tmp_path, missing_sidecar)
    store_a.sidecar_path(missing_sidecar).unlink()

    store_b = _write_dataset(tmp_path, missing_csv)
    store_b.csv_path(missing_csv).unlink()

    store_c = _write_dataset(tmp_path, corrupt)
    store_c.sidecar_path(corrupt).write_text("{", encoding="utf-8")

    report = AcceptedDatasetCatalog(tmp_path).scan()

    assert report.accepted == ()
    assert _codes(report) == {"sidecar_missing", "csv_missing", "sidecar_invalid"}


def test_catalog_rejects_sidecar_market_mismatch(tmp_path: Path) -> None:
    path_market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    sidecar_market = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")
    store = _write_dataset(tmp_path, path_market)
    payload = json.loads(store.sidecar_path(path_market).read_text(encoding="utf-8"))
    payload["market_id"]["symbol"] = sidecar_market.symbol
    store.sidecar_path(path_market).write_text(json.dumps(payload), encoding="utf-8")

    report = AcceptedDatasetCatalog(tmp_path).scan()

    assert report.accepted == ()
    assert _codes(report) == {"sidecar_market_mismatch"}


def test_catalog_rejects_noncanonical_storage_identity(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "ByBit" / "linear" / "BTC-USDT" / "1m" / "ohlcv"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "candles.csv").write_text(
        "ts_ms,open,high,low,close,volume\n60000,1,2,0.5,1.5,10\n",
        encoding="utf-8",
    )

    report = AcceptedDatasetCatalog(tmp_path).scan()

    assert report.accepted == ()
    assert _codes(report) == {"noncanonical_storage_identity"}


def test_catalog_is_read_only(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = _write_dataset(tmp_path, market)
    paths = (store.csv_path(market), store.sidecar_path(market))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

    AcceptedDatasetCatalog(tmp_path).scan()

    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert after == before


def test_catalog_orders_accepted_datasets_deterministically(tmp_path: Path) -> None:
    markets = (
        canonicalize_market_id("bybit", "spot", "XRPUSDT", "1h"),
        canonicalize_market_id("bybit", "linear", "ETHUSDT", "5m"),
        canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m"),
    )
    for market in markets:
        _write_dataset(tmp_path, market)

    first = AcceptedDatasetCatalog(tmp_path).list_accepted()
    second = AcceptedDatasetCatalog(tmp_path).list_accepted()

    assert [item.market_id for item in first] == sorted(
        markets,
        key=lambda item: (item.exchange, item.market_type, item.symbol, item.timeframe),
    )
    assert first == second


def test_missing_historical_root_is_an_empty_catalog(tmp_path: Path) -> None:
    root = tmp_path / "missing"

    report = AcceptedDatasetCatalog(root).scan()

    assert report.accepted == ()
    assert report.rejected == ()


def test_catalog_uses_shared_market_id_not_legacy_dataset_id(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_dataset(tmp_path, market)

    summary = AcceptedDatasetCatalog(tmp_path).list_accepted()[0]

    assert isinstance(summary.market_id, MarketId)
