from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research import (
    ChartSessionDisposedError,
    ChartSessionState,
    ChartSessionStateError,
    HistoricalDataset,
    ResidentOHLCVSlice,
    ResidentSliceService,
)


def _dataset(
    market: MarketId | None = None,
    *,
    fingerprint: str = "a" * 64,
    row_count: int = 20,
) -> HistoricalDataset:
    resolved_market = market or canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    timestamps = tuple((index + 1) * 60_000 for index in range(row_count))
    opens = tuple(float(index + 100) for index in range(row_count))
    return HistoricalDataset(
        market_id=resolved_market,
        csv_path=Path("candles.csv"),
        file_sha256=fingerprint,
        row_count=row_count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=opens,
        high=tuple(value + 2.0 for value in opens),
        low=tuple(value - 1.0 for value in opens),
        close=tuple(value + 1.0 for value in opens),
        volume=tuple(float(index + 10) for index in range(row_count)),
    )


def _opened_session(dataset: HistoricalDataset | None = None) -> tuple[ChartSessionState, HistoricalDataset]:
    resolved_dataset = dataset or _dataset()
    session = ChartSessionState(session_id="chart-1")
    attempt = session.begin_dataset_open(resolved_dataset.market_id)
    assert session.accept_dataset_open(attempt, resolved_dataset) is True
    return session, resolved_dataset


def _resident(dataset: HistoricalDataset, center_index: int = 10) -> ResidentOHLCVSlice:
    return ResidentSliceService().slice_around_index(
        dataset,
        center_index,
        visible_max=5,
        buffer_left=2,
        buffer_right=3,
    )


def test_new_session_has_no_dataset_or_resident_truth() -> None:
    session = ChartSessionState(session_id="chart-1")

    assert session.session_id == "chart-1"
    assert session.generation == 0
    assert session.selected_market_id is None
    assert session.dataset is None
    assert session.resident is None
    assert session.dataset_count == 0
    assert session.resident_count == 0
    assert session.dataset_open_pending is False
    assert session.resident_slice_pending is False
    assert session.is_disposed is False


def test_begin_dataset_open_creates_generation_and_resets_old_truth() -> None:
    first = _dataset()
    second_market = canonicalize_market_id("bybit", "linear", "ETHUSDT", "5m")
    session, _ = _opened_session(first)
    slice_attempt = session.begin_resident_slice_request()
    assert session.accept_resident_slice(slice_attempt, _resident(first)) is True

    open_attempt = session.begin_dataset_open(second_market)

    assert open_attempt.generation == 2
    assert open_attempt.market_id == second_market
    assert session.generation == 2
    assert session.selected_market_id == second_market
    assert session.dataset is None
    assert session.resident is None
    assert session.dataset_open_pending is True
    assert session.resident_slice_pending is False


def test_current_dataset_open_publishes_shared_immutable_reference() -> None:
    dataset = _dataset()
    session = ChartSessionState(session_id="chart-1")
    attempt = session.begin_dataset_open(dataset.market_id)

    assert session.accept_dataset_open(attempt, dataset) is True
    assert session.dataset is dataset
    assert session.dataset_fingerprint == dataset.file_sha256
    assert session.dataset_count == dataset.row_count
    assert session.dataset_open_pending is False


def test_stale_dataset_open_cannot_replace_newer_generation() -> None:
    first = _dataset()
    second = _dataset(
        canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m"),
        fingerprint="b" * 64,
    )
    session = ChartSessionState(session_id="chart-1")
    stale = session.begin_dataset_open(first.market_id)
    current = session.begin_dataset_open(second.market_id)

    assert session.accept_dataset_open(stale, first) is False
    assert session.accept_dataset_open(current, second) is True
    assert session.dataset is second


def test_current_open_rejects_dataset_for_wrong_market() -> None:
    btc = _dataset()
    eth = _dataset(canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m"))
    session = ChartSessionState(session_id="chart-1")
    attempt = session.begin_dataset_open(btc.market_id)

    with pytest.raises(ValueError, match="MarketId"):
        session.accept_dataset_open(attempt, eth)
    assert session.dataset is None
    assert session.dataset_open_pending is True


def test_open_failure_settles_only_current_attempt() -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    session = ChartSessionState(session_id="chart-1")
    stale = session.begin_dataset_open(market)
    current = session.begin_dataset_open(market)

    assert session.settle_dataset_open_failure(stale) is False
    assert session.dataset_open_pending is True
    assert session.settle_dataset_open_failure(current) is True
    assert session.dataset_open_pending is False
    assert session.dataset is None


def test_resident_request_requires_accepted_dataset() -> None:
    session = ChartSessionState(session_id="chart-1")

    with pytest.raises(ChartSessionStateError, match="no accepted dataset"):
        session.begin_resident_slice_request()


def test_current_resident_slice_is_published_without_copying() -> None:
    session, dataset = _opened_session()
    resident = _resident(dataset)
    attempt = session.begin_resident_slice_request()

    assert session.accept_resident_slice(attempt, resident) is True
    assert session.resident is resident
    assert session.resident_count == resident.row_count
    assert session.resident_slice_pending is False


def test_new_slice_request_makes_older_result_stale() -> None:
    session, dataset = _opened_session()
    first = session.begin_resident_slice_request()
    second = session.begin_resident_slice_request()

    assert first.request_id != second.request_id
    assert session.accept_resident_slice(first, _resident(dataset, 5)) is False
    current_resident = _resident(dataset, 15)
    assert session.accept_resident_slice(second, current_resident) is True
    assert session.resident is current_resident


def test_current_resident_result_must_match_dataset_identity_and_range() -> None:
    session, dataset = _opened_session()
    attempt = session.begin_resident_slice_request()
    resident = _resident(dataset)
    wrong_market = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")

    with pytest.raises(ValueError, match="MarketId"):
        session.accept_resident_slice(attempt, replace(resident, market_id=wrong_market))

    attempt = session.begin_resident_slice_request()
    with pytest.raises(ValueError, match="fingerprint"):
        session.accept_resident_slice(
            attempt,
            replace(resident, dataset_fingerprint="b" * 64),
        )

    attempt = session.begin_resident_slice_request()
    shifted_timestamps = tuple(value + 1 for value in resident.ts_ms)
    with pytest.raises(ValueError, match="OHLCV"):
        session.accept_resident_slice(
            attempt,
            replace(
                resident,
                ts_ms=shifted_timestamps,
                first_timestamp_ms=shifted_timestamps[0],
                last_timestamp_ms=shifted_timestamps[-1],
            ),
        )

    attempt = session.begin_resident_slice_request()
    changed_close = list(resident.close)
    changed_close[0] += 1.0
    with pytest.raises(ValueError, match="OHLCV"):
        session.accept_resident_slice(
            attempt,
            replace(resident, close=tuple(changed_close)),
        )


def test_resident_failure_preserves_previous_resident_truth() -> None:
    session, dataset = _opened_session()
    first_attempt = session.begin_resident_slice_request()
    first_resident = _resident(dataset, 5)
    assert session.accept_resident_slice(first_attempt, first_resident) is True

    failing_attempt = session.begin_resident_slice_request()
    assert session.settle_resident_slice_failure(failing_attempt) is True
    assert session.resident is first_resident
    assert session.resident_slice_pending is False


def test_timestamp_lookup_uses_shared_timeline_and_prefers_earlier_on_tie() -> None:
    session, dataset = _opened_session()
    exact_timestamp = dataset.ts_ms[10]
    tie_timestamp = (dataset.ts_ms[9] + dataset.ts_ms[10]) // 2

    assert session.exact_global_index_for_timestamp(exact_timestamp) == 10
    assert session.exact_global_index_for_timestamp(exact_timestamp + 1) is None
    assert session.nearest_global_index_for_timestamp(tie_timestamp) == 9
    assert session.nearest_global_index_for_timestamp(-1) == 0
    assert session.nearest_global_index_for_timestamp(10**18) == dataset.row_count - 1
    assert session.timestamp_for_global_index(10) == exact_timestamp
    assert session.timestamp_for_global_index(-1) is None
    assert session.timestamp_for_global_index(dataset.row_count) is None


def test_global_and_resident_index_translation_is_explicit() -> None:
    session, dataset = _opened_session()
    attempt = session.begin_resident_slice_request()
    resident = _resident(dataset, 10)
    assert session.accept_resident_slice(attempt, resident) is True

    assert session.resident_index_for_global(resident.base_index) == 0
    assert session.resident_index_for_global(resident.last_global_index) == resident.row_count - 1
    assert session.resident_index_for_global(resident.end_index_exclusive) is None
    assert session.global_index_for_resident(0) == resident.base_index
    assert session.global_index_for_resident(resident.row_count - 1) == resident.last_global_index
    with pytest.raises(IndexError):
        session.global_index_for_resident(resident.row_count)


def test_lookup_and_translation_require_published_truth() -> None:
    session = ChartSessionState(session_id="chart-1")

    with pytest.raises(ChartSessionStateError):
        session.exact_global_index_for_timestamp(60_000)
    with pytest.raises(ChartSessionStateError):
        session.resident_index_for_global(0)


def test_attempt_from_different_session_is_rejected() -> None:
    dataset = _dataset()
    first = ChartSessionState(session_id="chart-1")
    second = ChartSessionState(session_id="chart-2")
    foreign_attempt = first.begin_dataset_open(dataset.market_id)

    with pytest.raises(ValueError, match="different chart session"):
        second.accept_dataset_open(foreign_attempt, dataset)


def test_dispose_invalidates_attempts_and_releases_shared_references() -> None:
    session, dataset = _opened_session()
    resident_attempt = session.begin_resident_slice_request()
    resident = _resident(dataset)

    assert session.dispose() is True
    assert session.dispose() is False
    assert session.is_disposed is True
    assert session.selected_market_id is None
    assert session.dataset is None
    assert session.resident is None
    assert session.dataset_count == 0
    assert session.resident_count == 0
    assert session.dataset_open_pending is False
    assert session.resident_slice_pending is False
    assert session.accept_resident_slice(resident_attempt, resident) is False
    with pytest.raises(ChartSessionDisposedError):
        session.begin_dataset_open(dataset.market_id)
    with pytest.raises(ChartSessionDisposedError):
        session.nearest_global_index_for_timestamp(dataset.first_timestamp_ms)


def test_attempt_tokens_are_immutable() -> None:
    session = ChartSessionState(session_id="chart-1")
    attempt = session.begin_dataset_open(_dataset().market_id)

    with pytest.raises(FrozenInstanceError):
        attempt.generation = 4  # type: ignore[misc]
