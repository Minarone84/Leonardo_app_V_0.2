from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.ohlcv import OHLCVStore
from leonardo.research import (
    AcceptedDatasetCatalog,
    DatasetNotAcceptedError,
    HistoricalDatasetLoadCancelled,
    HistoricalDatasetLoadError,
    HistoricalDatasetLoader,
)
from leonardo.storage import OHLCVSidecarV1

_HEADER = "ts_ms,open,high,low,close,volume\n"
_DEFAULT_ROWS = (
    "60000,1,2,0.5,1.5,10\n",
    "120000,1.5,2.5,1,2,12\n",
    "180000,2,3,1.5,2.5,14\n",
)


def _write_accepted_csv(
    root: Path,
    market: MarketId,
    rows: tuple[str, ...] = _DEFAULT_ROWS,
    *,
    row_count: int | None = None,
    first_timestamp_ms: int | None = None,
    last_timestamp_ms: int | None = None,
    validation_status: str = "ok",
) -> OHLCVStore:
    store = OHLCVStore(root)
    dataset_dir = store.dataset_dir(market)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    csv_path = store.csv_path(market)
    csv_path.write_text(_HEADER + "".join(rows), encoding="utf-8", newline="")
    timestamps = tuple(int(row.split(",", 1)[0]) for row in rows)
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        row_count=len(rows) if row_count is None else row_count,
        first_timestamp_ms=(min(timestamps) if first_timestamp_ms is None else first_timestamp_ms),
        last_timestamp_ms=(max(timestamps) if last_timestamp_ms is None else last_timestamp_ms),
        source="test",
        persistence_status="committed",
        validation_status=validation_status,
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return store


def _loader(root: Path, **kwargs) -> HistoricalDatasetLoader:
    return HistoricalDatasetLoader(AcceptedDatasetCatalog(root), **kwargs)


def test_loader_returns_immutable_full_dataset(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_accepted_csv(tmp_path, market)

    dataset = _loader(tmp_path).load(market)

    assert dataset.market_id == market
    assert dataset.row_count == 3
    assert dataset.ts_ms == (60_000, 120_000, 180_000)
    assert dataset.open == (1.0, 1.5, 2.0)
    assert dataset.high == (2.0, 2.5, 3.0)
    assert dataset.low == (0.5, 1.0, 1.5)
    assert dataset.close == (1.5, 2.0, 2.5)
    assert dataset.volume == (10.0, 12.0, 14.0)
    with pytest.raises(FrozenInstanceError):
        dataset.row_count = 4  # type: ignore[misc]
    with pytest.raises(TypeError):
        dataset.close[0] = 99.0  # type: ignore[index]


def test_loader_refuses_dataset_not_accepted_by_catalog(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_accepted_csv(tmp_path, market, validation_status="unknown")

    with pytest.raises(DatasetNotAcceptedError, match="validation_not_accepted"):
        _loader(tmp_path).load(market)


def test_loader_rejects_invalid_header(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = _write_accepted_csv(tmp_path, market)
    path = store.csv_path(market)
    path.write_text("timestamp,open,high,low,close,volume\n" + "".join(_DEFAULT_ROWS), encoding="utf-8")
    _rewrite_sidecar_hash(store, market)

    with pytest.raises(HistoricalDatasetLoadError, match="invalid OHLCV CSV columns"):
        _loader(tmp_path).load(market)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            (
                "60000,1,2,0.5,1.5,10\n",
                "60000,1.5,2.5,1,2,12\n",
            ),
            "duplicate timestamp",
        ),
        (
            (
                "120000,1,2,0.5,1.5,10\n",
                "60000,1.5,2.5,1,2,12\n",
            ),
            "out-of-order timestamp",
        ),
    ],
)
def test_loader_requires_strictly_increasing_timestamps(
    tmp_path: Path,
    rows: tuple[str, ...],
    message: str,
) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_accepted_csv(tmp_path, market, rows)

    with pytest.raises(HistoricalDatasetLoadError, match=message):
        _loader(tmp_path).load(market)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("60000,1,0.9,0.5,1.5,10\n", "high is below open or close"),
        ("60000,1,2,1.1,1.5,10\n", "low is above open or close"),
        ("60000,1,0.5,1,1.5,10\n", "high is below low"),
        ("60000,1,2,0.5,1.5,-1\n", "volume is negative"),
        ("60000,1,nan,0.5,1.5,10\n", "non-finite"),
    ],
)
def test_loader_enforces_ohlcv_integrity(
    tmp_path: Path,
    row: str,
    message: str,
) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_accepted_csv(tmp_path, market, (row,))

    with pytest.raises(HistoricalDatasetLoadError, match=message):
        _loader(tmp_path).load(market)


def test_loader_rechecks_sidecar_row_count_and_time_range(tmp_path: Path) -> None:
    market_a = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    market_b = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")
    _write_accepted_csv(tmp_path, market_a, row_count=4)
    _write_accepted_csv(tmp_path, market_b, first_timestamp_ms=59_000)

    loader = _loader(tmp_path)
    with pytest.raises(HistoricalDatasetLoadError, match="row count"):
        loader.load(market_a)
    with pytest.raises(HistoricalDatasetLoadError, match="first CSV timestamp"):
        loader.load(market_b)


def test_loader_rejects_sidecar_changed_during_load(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = _write_accepted_csv(tmp_path, market)
    changed = False

    def progress(_current: int, _total: int) -> None:
        nonlocal changed
        if not changed:
            changed = True
            path = store.sidecar_path(market)
            path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(HistoricalDatasetLoadError, match=r"candles\.meta\.json changed"):
        _loader(tmp_path, progress_interval_rows=1).load(market, progress=progress)


def test_loader_cache_reuses_unchanged_dataset_but_never_bypasses_acceptance(
    tmp_path: Path,
) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = _write_accepted_csv(tmp_path, market)
    loader = _loader(tmp_path)

    first = loader.load(market)
    second = loader.load(market)
    assert second is first
    assert loader.cache_size == 1

    with store.csv_path(market).open("a", encoding="utf-8") as handle:
        handle.write("240000,2.5,3.5,2,3,16\n")
    with pytest.raises(DatasetNotAcceptedError, match="csv_hash_mismatch"):
        loader.load(market)


def test_loader_cache_rechecks_changed_sidecar_evidence(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = _write_accepted_csv(tmp_path, market)
    loader = _loader(tmp_path)
    loader.load(market)

    sidecar_path = store.sidecar_path(market)
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload["row_count"] = 4
    sidecar_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(HistoricalDatasetLoadError, match="row count"):
        loader.load(market)


def test_cached_load_honors_cancellation_before_return(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_accepted_csv(tmp_path, market)
    loader = _loader(tmp_path)
    loader.load(market)
    cancelled = Event()

    def progress(_current: int, _total: int) -> None:
        cancelled.set()

    with pytest.raises(HistoricalDatasetLoadCancelled):
        loader.load(
            market,
            progress=progress,
            cancellation_requested=cancelled.is_set,
        )


def test_loader_cache_is_bounded_by_entry_count(tmp_path: Path) -> None:
    market_a = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    market_b = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")
    _write_accepted_csv(tmp_path, market_a)
    _write_accepted_csv(tmp_path, market_b)
    loader = _loader(tmp_path, max_cache_entries=1)

    first_a = loader.load(market_a)
    loader.load(market_b)
    second_a = loader.load(market_a)

    assert loader.cache_size == 1
    assert second_a is not first_a


def test_cooperative_cancellation_prevents_cache_publication(tmp_path: Path) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    _write_accepted_csv(tmp_path, market)
    loader = _loader(tmp_path, progress_interval_rows=1)
    cancelled = Event()

    def progress(_current: int, _total: int) -> None:
        cancelled.set()

    with pytest.raises(HistoricalDatasetLoadCancelled):
        loader.load(
            market,
            progress=progress,
            cancellation_requested=cancelled.is_set,
        )

    assert loader.cache_size == 0


def test_loader_requires_canonical_shared_market_id(tmp_path: Path) -> None:
    noncanonical = MarketId("ByBit", "linear", "BTC-USDT", "1MIN")

    with pytest.raises(ValueError, match="already be canonical"):
        _loader(tmp_path).load(noncanonical)


def _rewrite_sidecar_hash(store: OHLCVStore, market: MarketId) -> None:
    path = store.sidecar_path(market)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["file_sha256"] = hashlib.sha256(store.csv_path(market).read_bytes()).hexdigest()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
