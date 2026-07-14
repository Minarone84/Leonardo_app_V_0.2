from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from leonardo.research import (
    DEFAULT_LEFT_PADDING,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_RIGHT_PADDING,
    DEFAULT_VISIBLE_BARS,
    MAX_VISIBLE_BARS,
    MIN_VISIBLE_BARS,
    DatasetInterest,
    HorizontalViewport,
    ResidentRefillDirection,
)


def test_frozen_policy_matches_approved_old_research_behavior() -> None:
    assert DEFAULT_LEFT_PADDING == 1_000
    assert DEFAULT_RIGHT_PADDING == 1_000
    assert MIN_VISIBLE_BARS == 20
    assert DEFAULT_VISIBLE_BARS == 500
    assert MAX_VISIBLE_BARS == 2_000
    assert DEFAULT_REFILL_THRESHOLD == 250


def test_initial_camera_aligns_latest_real_candle_to_right_edge() -> None:
    viewport = HorizontalViewport(10_000)

    assert viewport.domain_start == -1_000
    assert viewport.domain_end_exclusive == 11_000
    assert viewport.domain_size == 12_000
    assert viewport.visible_count == 500
    assert viewport.start_index == 9_500
    assert viewport.end_index_exclusive == 10_000
    assert viewport.center_index == 9_750


def test_short_dataset_uses_left_padding_to_keep_latest_candle_at_right_edge() -> None:
    viewport = HorizontalViewport(100)

    assert viewport.start_index == -400
    assert viewport.end_index_exclusive == 100
    assert viewport.dataset_interest() == DatasetInterest(0, 100)


def test_empty_dataset_still_has_valid_chart_space_but_no_dataset_interest() -> None:
    viewport = HorizontalViewport(0)

    assert viewport.start_index == -500
    assert viewport.end_index_exclusive == 0
    assert viewport.dataset_interest() is None


def test_explicit_window_clamps_visible_policy_and_chart_domain() -> None:
    viewport = HorizontalViewport(10_000)

    assert viewport.set_window(-50_000, -49_995) is True
    assert viewport.visible_count == MIN_VISIBLE_BARS
    assert viewport.start_index == viewport.domain_start

    assert viewport.set_window(50_000, 60_000) is True
    assert viewport.visible_count == MAX_VISIBLE_BARS
    assert viewport.start_index == viewport.domain_end_exclusive - MAX_VISIBLE_BARS


def test_invalid_explicit_window_is_rejected() -> None:
    viewport = HorizontalViewport(100)

    with pytest.raises(ValueError, match="greater"):
        viewport.set_window(10, 10)


def test_pan_moves_camera_and_stops_at_fixed_padding_boundaries() -> None:
    viewport = HorizontalViewport(10_000)

    assert viewport.pan_left(100) is True
    assert viewport.start_index == 9_400
    assert viewport.pan_left(100_000) is True
    assert viewport.start_index == -1_000
    assert viewport.pan_left(1) is False

    assert viewport.pan_right(100_000) is True
    assert viewport.start_index == 10_500
    assert viewport.end_index_exclusive == 11_000
    assert viewport.pan_right(1) is False


def test_nonpositive_pan_steps_preserve_old_no_op_behavior() -> None:
    viewport = HorizontalViewport(1_000)
    start = viewport.start_index

    assert viewport.pan_left(0) is False
    assert viewport.pan_left(-1) is False
    assert viewport.pan_right(0) is False
    assert viewport.pan_right(-1) is False
    assert viewport.start_index == start


def test_pan_by_supports_signed_camera_movement() -> None:
    viewport = HorizontalViewport(1_000)
    start = viewport.start_index

    assert viewport.pan_by(-25) is True
    assert viewport.start_index == start - 25
    assert viewport.pan_by(50) is True
    assert viewport.start_index == start + 25
    assert viewport.pan_by(0) is False


def test_center_on_index_uses_old_even_window_center_policy() -> None:
    viewport = HorizontalViewport(10_000, visible_count=500)

    assert viewport.center_on_index(5_000) is True
    assert viewport.start_index == 4_750
    assert viewport.center_index == 5_000


def test_center_on_timestamp_delegates_identity_lookup_to_session_authority() -> None:
    viewport = HorizontalViewport(10_000)
    calls: list[int] = []

    def resolve(timestamp_ms: int) -> int | None:
        calls.append(timestamp_ms)
        return 4_000

    assert viewport.center_on_timestamp(1_700_000_000_000, resolve) is True
    assert calls == [1_700_000_000_000]
    assert viewport.center_index == 4_000
    assert viewport.center_on_timestamp(123, lambda _: None) is False


def test_zoom_in_keeps_anchor_near_requested_relative_position() -> None:
    viewport = HorizontalViewport(10_000)
    anchor = 9_750

    assert viewport.zoom_in_at(anchor, 0.5) is True
    assert viewport.visible_count == 400
    assert viewport.start_index == 9_550
    assert viewport.global_index_at_relative(0.5) == anchor


def test_zoom_out_is_camera_only_and_does_not_snap_latest_data_edge() -> None:
    viewport = HorizontalViewport(10_000)

    assert viewport.zoom_out_at(9_600, 0.2) is True
    assert viewport.visible_count == 625
    assert viewport.start_index == 9_475
    assert viewport.end_index_exclusive == 10_100


def test_zoom_clamps_to_minimum_and_maximum_visible_counts() -> None:
    viewport = HorizontalViewport(10_000, visible_count=MIN_VISIBLE_BARS)
    assert viewport.zoom_in_at(viewport.center_index, 0.5) is False

    assert viewport.set_visible_anchored(MAX_VISIBLE_BARS, 5_000, 0.5) is True
    assert viewport.visible_count == MAX_VISIBLE_BARS
    assert viewport.zoom_out_at(viewport.center_index, 0.5) is False


def test_zoom_anchor_is_clamped_to_chart_domain() -> None:
    viewport = HorizontalViewport(100)

    viewport.set_visible_anchored(100, -100_000, 0.0)
    assert viewport.start_index == viewport.domain_start

    viewport.set_visible_anchored(100, 100_000, 1.0)
    assert viewport.end_index_exclusive == viewport.domain_end_exclusive


def test_normalized_position_mapping_uses_discrete_slot_centers() -> None:
    viewport = HorizontalViewport(10_000, visible_count=100)
    viewport.set_window(1_000, 1_100)

    assert viewport.global_index_at_relative(0.0) == 1_000
    assert viewport.global_index_at_relative(0.999) == 1_099
    assert viewport.global_index_at_relative(1.0) == 1_099
    assert viewport.relative_for_global_index(1_000) == pytest.approx(0.005)
    assert viewport.relative_for_global_index(1_099) == pytest.approx(0.995)
    assert viewport.relative_for_global_index(-10_000) == pytest.approx(0.005)


def test_crosshair_is_camera_independent_and_domain_bounded() -> None:
    viewport = HorizontalViewport(1_000)
    start = viewport.start_index

    assert viewport.set_crosshair(500) is True
    assert viewport.crosshair_index == 500
    assert viewport.start_index == start
    assert viewport.set_crosshair(500) is False
    assert viewport.set_crosshair(10_000) is True
    assert viewport.crosshair_index is None
    assert viewport.set_crosshair(None) is False


def test_dataset_count_update_preserves_then_clamps_position() -> None:
    viewport = HorizontalViewport(10_000)
    viewport.pan_right(1_000)
    assert viewport.start_index == 10_500

    assert viewport.set_dataset_count(1_000) is True
    assert viewport.start_index == 1_500
    assert viewport.end_index_exclusive == 2_000


def test_padding_update_preserves_camera_and_clears_invalid_crosshair() -> None:
    viewport = HorizontalViewport(100, left_padding=1_000, right_padding=1_000)
    viewport.set_crosshair(-900)
    viewport.set_window(-1_000, -500)

    assert viewport.set_domain_padding(left_padding=100, right_padding=100) is True
    assert viewport.start_index == -100
    assert viewport.crosshair_index is None


def test_align_latest_restores_latest_real_data_edge() -> None:
    viewport = HorizontalViewport(10_000)
    viewport.pan_right(500)

    assert viewport.align_latest() is True
    assert viewport.end_index_exclusive == viewport.dataset_count
    assert viewport.align_latest() is False


def test_dataset_interest_clips_partial_data_overlap() -> None:
    viewport = HorizontalViewport(10_000)

    viewport.set_window(-100, 400)
    assert viewport.dataset_interest() == DatasetInterest(0, 400)

    viewport.set_window(9_800, 10_300)
    assert viewport.dataset_interest() == DatasetInterest(9_800, 10_000)


def test_dataset_interest_maps_complete_padding_to_nearest_real_edge() -> None:
    viewport = HorizontalViewport(10_000)

    viewport.set_window(-1_000, -500)
    assert viewport.dataset_interest() == DatasetInterest(0, 500)

    viewport.set_window(10_000, 10_500)
    assert viewport.dataset_interest() == DatasetInterest(9_500, 10_000)


def test_refill_direction_is_none_when_interest_is_safely_inside_resident() -> None:
    viewport = HorizontalViewport(10_000)
    viewport.set_window(3_000, 3_500)

    assert viewport.resident_refill_direction(
        resident_start_index=2_500,
        resident_end_index_exclusive=7_500,
        has_more_left=True,
        has_more_right=True,
    ) is ResidentRefillDirection.NONE


def test_refill_direction_detects_left_threshold() -> None:
    viewport = HorizontalViewport(10_000)
    viewport.set_window(2_700, 3_200)

    assert viewport.resident_refill_direction(
        resident_start_index=2_500,
        resident_end_index_exclusive=7_500,
        has_more_left=True,
        has_more_right=True,
    ) is ResidentRefillDirection.LEFT


def test_refill_direction_detects_right_threshold() -> None:
    viewport = HorizontalViewport(10_000)
    viewport.set_window(6_800, 7_300)

    assert viewport.resident_refill_direction(
        resident_start_index=2_500,
        resident_end_index_exclusive=7_500,
        has_more_left=True,
        has_more_right=True,
    ) is ResidentRefillDirection.RIGHT


def test_refill_direction_handles_camera_outside_resident() -> None:
    viewport = HorizontalViewport(10_000)

    viewport.set_window(500, 1_000)
    assert viewport.resident_refill_direction(
        resident_start_index=2_500,
        resident_end_index_exclusive=7_500,
        has_more_left=True,
        has_more_right=True,
    ) is ResidentRefillDirection.LEFT

    viewport.set_window(9_000, 9_500)
    assert viewport.resident_refill_direction(
        resident_start_index=2_500,
        resident_end_index_exclusive=7_500,
        has_more_left=True,
        has_more_right=True,
    ) is ResidentRefillDirection.RIGHT


def test_refill_direction_respects_dataset_edge_flags() -> None:
    viewport = HorizontalViewport(10_000)
    viewport.set_window(0, 500)

    assert viewport.resident_refill_direction(
        resident_start_index=0,
        resident_end_index_exclusive=5_000,
        has_more_left=False,
        has_more_right=True,
    ) is ResidentRefillDirection.NONE


def test_refill_direction_chooses_nearest_edge_when_both_thresholds_match() -> None:
    viewport = HorizontalViewport(
        1_000,
        visible_count=500,
        left_padding=0,
        right_padding=0,
    )
    viewport.set_window(400, 900)

    assert viewport.resident_refill_direction(
        resident_start_index=0,
        resident_end_index_exclusive=1_000,
        has_more_left=True,
        has_more_right=True,
        threshold=600,
    ) is ResidentRefillDirection.RIGHT


def test_dataset_interest_is_frozen_and_validated() -> None:
    interest = DatasetInterest(10, 20)
    assert interest.row_count == 10
    assert interest.center_index == 15

    with pytest.raises(FrozenInstanceError):
        interest.start_index = 1  # type: ignore[misc]
    with pytest.raises(ValueError, match="at least one"):
        DatasetInterest(10, 10)


def test_snapshot_is_frozen_and_tracks_current_state() -> None:
    viewport = HorizontalViewport(1_000)
    viewport.pan_left(25)
    viewport.set_crosshair(500)
    snapshot = viewport.snapshot()

    assert snapshot.start_index == viewport.start_index
    assert snapshot.crosshair_index == 500
    with pytest.raises(FrozenInstanceError):
        snapshot.start_index = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: HorizontalViewport(-1), "dataset_count"),
        (lambda: HorizontalViewport(True), "dataset_count"),
        (lambda: HorizontalViewport(1, visible_count=0), "visible_count"),
        (lambda: HorizontalViewport(1, left_padding=-1), "left_padding"),
        (lambda: HorizontalViewport(1, right_padding=-1), "right_padding"),
        (lambda: HorizontalViewport(1).pan_by(True), "delta"),
        (lambda: HorizontalViewport(1).set_visible_anchored(100, 0, 1.1), "anchor_relative"),
    ],
)
def test_invalid_viewport_inputs_are_rejected(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_refill_rejects_resident_interval_outside_dataset_truth() -> None:
    viewport = HorizontalViewport(1_000)

    with pytest.raises(ValueError, match="exceeds dataset_count"):
        viewport.resident_refill_direction(
            resident_start_index=0,
            resident_end_index_exclusive=1_001,
            has_more_left=False,
            has_more_right=False,
        )


def test_refill_requires_boolean_edge_flags() -> None:
    viewport = HorizontalViewport(1_000)

    with pytest.raises(ValueError, match="has_more_left"):
        viewport.resident_refill_direction(
            resident_start_index=0,
            resident_end_index_exclusive=1_000,
            has_more_left=1,  # type: ignore[arg-type]
            has_more_right=False,
        )
