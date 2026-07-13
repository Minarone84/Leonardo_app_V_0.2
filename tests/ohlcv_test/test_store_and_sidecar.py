from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv.store import Candle, OHLCVStore
from leonardo.storage import OHLCVSidecarV1


def test_valid_sidecar_supports_fast_inspection(tmp_path: Path, monkeypatch) -> None:
    store = OHLCVStore(tmp_path)
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store.write(
        market,
        (Candle(60_000, 1, 2, 0.5, 1.5, 10),),
        source="bybit",
        persistence_status="partial",
    )
    monkeypatch.setattr(
        store,
        "_scan_csv_identity",
        lambda _path: (_ for _ in ()).throw(AssertionError("CSV scan should not run")),
    )
    inspection = store.inspect(market)
    assert inspection.metadata_valid is True
    assert inspection.source == "sidecar"
    assert inspection.row_count == 1


def test_sidecar_rejects_bad_hash_version_time_and_lineage() -> None:
    now = datetime.now(UTC)
    common = dict(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        row_count=1,
        first_timestamp_ms=1,
        last_timestamp_ms=1,
        source="bybit",
        persistence_status="committed",
    )
    with pytest.raises(ValueError, match="SHA-256"):
        OHLCVSidecarV1(file_sha256="bad", **common)
    with pytest.raises(ValueError, match="schema_version"):
        OHLCVSidecarV1(file_sha256="a" * 64, schema_version="2.0", **common)
    with pytest.raises(ValueError, match="earlier"):
        OHLCVSidecarV1(
            file_sha256="a" * 64,
            created_at_utc=now,
            updated_at_utc=now - timedelta(seconds=1),
            **common,
        )
    with pytest.raises(ValueError, match="JSON-safe"):
        OHLCVSidecarV1(file_sha256="a" * 64, lineage={"bad": object()}, **common)


def test_finalize_updates_sidecar_without_rewriting_csv(tmp_path: Path) -> None:
    from leonardo.data import canonicalize_market_id
    from leonardo.ohlcv.store import Candle, OHLCVStore

    store = OHLCVStore(tmp_path)
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store.write(
        market,
        (Candle(60_000, 1, 2, 0.5, 1.5, 10),),
        source="test",
        persistence_status="partial",
    )
    csv_path = store.csv_path(market)
    before = (csv_path.read_bytes(), csv_path.stat().st_mtime_ns)

    sidecar = store.finalize(market, source="test")

    after = (csv_path.read_bytes(), csv_path.stat().st_mtime_ns)
    assert before == after
    assert sidecar.persistence_status == "committed"
