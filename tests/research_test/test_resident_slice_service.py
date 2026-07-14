from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.data import canonicalize_market_id
from leonardo.research import (
    DEFAULT_BUFFER_LEFT,
    DEFAULT_BUFFER_RIGHT,
    DEFAULT_RESIDENT_TARGET,
    DEFAULT_VISIBLE_MAX,
    HistoricalDataset,
    ResidentSliceService,
)


def _dataset(
    row_count: int,
    *,
    fingerprint: str = "a" * 64,
    market_symbol: str = "BTCUSDT",
    close_offset: float = 0.0,
) -> HistoricalDataset:
    market = canonicalize_market_id("bybit", "linear", market_symbol, "1m")
    timestamps = tuple((index + 1) * 60_000 for index in range(row_count))
    opens = tuple(float(index) + close_offset for index in range(row_count))
    highs = tuple(value + 2.0 for value in opens)
    lows = tuple(value - 1.0 for value in opens)
    closes = tuple(value + 1.0 for value in opens)
    volumes = tuple(float(index + 10) for index in range(row_count))
    return HistoricalDataset(
        market_id=market,
        csv_path=Path("candles.csv"),
        file_sha256=fingerprint,
        row_count=row_count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=volumes,
    )


def test_default_window_policy_matches_frozen_research_behavior() -> None:
    assert DEFAULT_VISIBLE_MAX == 2_000
    assert DEFAULT_BUFFER_LEFT == 1_500
    assert DEFAULT_BUFFER_RIGHT == 1_500
    assert DEFAULT_RESIDENT_TARGET == 5_000


def test_middle_slice_uses_full_default_resident_target() -> None:
    dataset = _dataset(10_000)

    resident = ResidentSliceService().slice_around_index(dataset, 5_000)

    assert resident.base_index == 2_500
    assert resident.end_index_exclusive == 7_500
    assert resident.row_count == 5_000
    assert resident.has_more_left is True
    assert resident.has_more_right is True
    assert resident.ts_ms == dataset.ts_ms[2_500:7_500]
    assert resident.close == dataset.close[2_500:7_500]
    assert resident.contains_global_index(2_500) is True
    assert resident.contains_global_index(7_499) is True
    assert resident.contains_global_index(7_500) is False


def test_start_edge_expands_right_to_preserve_target_size() -> None:
    dataset = _dataset(10_000)

    resident = ResidentSliceService().slice_around_index(dataset, 0)

    assert resident.base_index == 0
    assert resident.end_index_exclusive == 5_000
    assert resident.row_count == DEFAULT_RESIDENT_TARGET
    assert resident.has_more_left is False
    assert resident.has_more_right is True
    assert resident.first_timestamp_ms == dataset.first_timestamp_ms


def test_end_edge_expands_left_to_preserve_target_size() -> None:
    dataset = _dataset(10_000)

    resident = ResidentSliceService().slice_around_index(dataset, 9_999)

    assert resident.base_index == 5_000
    assert resident.end_index_exclusive == 10_000
    assert resident.row_count == DEFAULT_RESIDENT_TARGET
    assert resident.has_more_left is True
    assert resident.has_more_right is False
    assert resident.last_timestamp_ms == dataset.last_timestamp_ms


def test_short_dataset_returns_complete_dataset() -> None:
    dataset = _dataset(125)

    resident = ResidentSliceService().slice_around_index(dataset, 60)

    assert resident.base_index == 0
    assert resident.end_index_exclusive == 125
    assert resident.row_count == 125
    assert resident.has_more_left is False
    assert resident.has_more_right is False
    assert resident.ts_ms == dataset.ts_ms


def test_custom_window_sizes_preserve_old_edge_aware_formula() -> None:
    dataset = _dataset(20)

    resident = ResidentSliceService().slice_around_index(
        dataset,
        10,
        visible_max=5,
        buffer_left=2,
        buffer_right=3,
    )

    assert resident.base_index == 6
    assert resident.end_index_exclusive == 16
    assert resident.row_count == 10


def test_out_of_range_indexes_clamp_to_nearest_dataset_edge() -> None:
    dataset = _dataset(10_000)
    service = ResidentSliceService()

    left = service.slice_around_index(dataset, -10_000)
    right = service.slice_around_index(dataset, 100_000)

    assert (left.base_index, left.end_index_exclusive) == (0, 5_000)
    assert (right.base_index, right.end_index_exclusive) == (5_000, 10_000)


def test_timestamp_lookup_uses_nearest_candle_and_prefers_earlier_on_tie() -> None:
    dataset = _dataset(20)
    service = ResidentSliceService()

    exact = service.slice_around_timestamp(
        dataset,
        dataset.ts_ms[10],
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )
    tie = service.slice_around_timestamp(
        dataset,
        (dataset.ts_ms[9] + dataset.ts_ms[10]) // 2,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )

    assert exact.base_index == 10
    assert exact.ts_ms == (dataset.ts_ms[10],)
    assert tie.base_index == 9
    assert tie.ts_ms == (dataset.ts_ms[9],)


def test_timestamp_lookup_clamps_before_and_after_dataset() -> None:
    dataset = _dataset(20)
    service = ResidentSliceService()

    first = service.slice_around_timestamp(
        dataset,
        -1,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )
    last = service.slice_around_timestamp(
        dataset,
        dataset.last_timestamp_ms + 1_000_000,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )

    assert first.base_index == 0
    assert last.base_index == dataset.row_count - 1


def test_resident_payload_is_deeply_immutable() -> None:
    resident = ResidentSliceService().slice_around_index(_dataset(20), 10)

    with pytest.raises(FrozenInstanceError):
        resident.base_index = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        resident.close[0] = 99.0  # type: ignore[index]


def test_identical_slice_reuses_cached_payload() -> None:
    dataset = _dataset(10_000)
    service = ResidentSliceService()

    first = service.slice_around_index(dataset, 5_000)
    second = service.slice_around_timestamp(dataset, dataset.ts_ms[5_000])

    assert second is first
    assert service.cache_size == 1


def test_new_dataset_fingerprint_evicts_old_market_slices() -> None:
    original = _dataset(10_000, fingerprint="a" * 64, close_offset=0.0)
    replacement = _dataset(10_000, fingerprint="b" * 64, close_offset=100.0)
    service = ResidentSliceService()

    old_slice = service.slice_around_index(original, 5_000)
    new_slice = service.slice_around_index(replacement, 5_000)

    assert new_slice is not old_slice
    assert new_slice.dataset_fingerprint == replacement.file_sha256
    assert new_slice.close[0] != old_slice.close[0]
    assert service.cache_size == 1


def test_slice_cache_is_bounded_by_entry_count() -> None:
    dataset = _dataset(100)
    service = ResidentSliceService(max_cache_entries=2)

    first = service.slice_around_index(
        dataset,
        10,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )
    service.slice_around_index(
        dataset,
        20,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )
    service.slice_around_index(
        dataset,
        30,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )
    reloaded = service.slice_around_index(
        dataset,
        10,
        visible_max=1,
        buffer_left=0,
        buffer_right=0,
    )

    assert service.cache_size == 2
    assert reloaded is not first


def test_dataset_invalidation_removes_only_matching_market() -> None:
    dataset_a = _dataset(100, market_symbol="BTCUSDT")
    dataset_b = _dataset(100, market_symbol="ETHUSDT")
    service = ResidentSliceService()
    service.slice_around_index(dataset_a, 50)
    service.slice_around_index(dataset_b, 50)

    assert service.invalidate_dataset(dataset_a.market_id) == 1
    assert service.cache_size == 1
    assert service.invalidate_dataset(dataset_a.market_id) == 0
    assert service.clear_cache() == 1
    assert service.cache_size == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"visible_max": 0}, "visible_max"),
        ({"visible_max": True}, "visible_max"),
        ({"buffer_left": -1}, "buffer_left"),
        ({"buffer_right": -1}, "buffer_right"),
    ],
)
def test_invalid_window_sizes_are_rejected(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ResidentSliceService().slice_around_index(_dataset(20), 10, **kwargs)
