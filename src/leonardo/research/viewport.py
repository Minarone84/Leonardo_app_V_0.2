"""Pure horizontal camera mathematics for historical Research charts.

The viewport owns chart-space camera state only.  Dataset truth remains owned by
Research dataset/session services, resident truth remains owned by the chart
session, and Qt interaction/signals remain GUI responsibilities.

Chart space is the canonical dataset index domain extended by fixed empty slots
on both sides.  Negative indexes represent empty historical padding and indexes
at or beyond ``dataset_count`` represent empty future padding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


MIN_VISIBLE_BARS = 20
DEFAULT_VISIBLE_BARS = 500
MAX_VISIBLE_BARS = 2_000
DEFAULT_LEFT_PADDING = 1_000
DEFAULT_RIGHT_PADDING = 1_000
DEFAULT_REFILL_THRESHOLD = 250


class ResidentRefillDirection(str, Enum):
    """Direction in which the current resident data should be refreshed."""

    NONE = "none"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class DatasetInterest:
    """Dataset interval currently relevant to the horizontal camera.

    The interval is expressed in canonical dataset indexes and uses an exclusive
    end.  When the camera is entirely inside chart padding, the interval maps to
    the nearest real-data edge instead of inventing dataset indexes.
    """

    start_index: int
    end_index_exclusive: int

    def __post_init__(self) -> None:
        if type(self.start_index) is not int or self.start_index < 0:
            raise ValueError("start_index must be a non-negative integer")
        if type(self.end_index_exclusive) is not int:
            raise ValueError("end_index_exclusive must be an integer")
        if self.end_index_exclusive <= self.start_index:
            raise ValueError("dataset interest must contain at least one row")

    @property
    def row_count(self) -> int:
        return self.end_index_exclusive - self.start_index

    @property
    def center_index(self) -> int:
        return self.start_index + (self.row_count // 2)


@dataclass(frozen=True, slots=True)
class ViewportSnapshot:
    """Read-only projection of horizontal viewport state."""

    dataset_count: int
    left_padding: int
    right_padding: int
    domain_start: int
    domain_end_exclusive: int
    start_index: int
    end_index_exclusive: int
    visible_count: int
    crosshair_index: int | None


class HorizontalViewport:
    """Mutable horizontal camera over a fixed padded chart-space domain.

    Methods return ``True`` only when observable viewport state changed.  This
    lets a later Qt adapter emit signals and schedule paints without making this
    domain component depend on PySide6.
    """

    def __init__(
        self,
        dataset_count: int,
        *,
        visible_count: int = DEFAULT_VISIBLE_BARS,
        left_padding: int = DEFAULT_LEFT_PADDING,
        right_padding: int = DEFAULT_RIGHT_PADDING,
    ) -> None:
        self._dataset_count = _non_negative_int(dataset_count, "dataset_count")
        self._left_padding = _non_negative_int(left_padding, "left_padding")
        self._right_padding = _non_negative_int(right_padding, "right_padding")
        self._visible_count = self._clamp_visible(visible_count)
        self._start_index = self._latest_aligned_start()
        self._crosshair_index: int | None = None

    @property
    def dataset_count(self) -> int:
        return self._dataset_count

    @property
    def left_padding(self) -> int:
        return self._left_padding

    @property
    def right_padding(self) -> int:
        return self._right_padding

    @property
    def domain_start(self) -> int:
        return -self._left_padding

    @property
    def domain_end_exclusive(self) -> int:
        return self._dataset_count + self._right_padding

    @property
    def domain_size(self) -> int:
        return max(1, self.domain_end_exclusive - self.domain_start)

    @property
    def start_index(self) -> int:
        return self._start_index

    @property
    def end_index_exclusive(self) -> int:
        return self._start_index + self._visible_count

    @property
    def visible_count(self) -> int:
        return self._visible_count

    @property
    def center_index(self) -> int:
        return self._start_index + (self._visible_count // 2)

    @property
    def crosshair_index(self) -> int | None:
        return self._crosshair_index

    def snapshot(self) -> ViewportSnapshot:
        return ViewportSnapshot(
            dataset_count=self._dataset_count,
            left_padding=self._left_padding,
            right_padding=self._right_padding,
            domain_start=self.domain_start,
            domain_end_exclusive=self.domain_end_exclusive,
            start_index=self._start_index,
            end_index_exclusive=self.end_index_exclusive,
            visible_count=self._visible_count,
            crosshair_index=self._crosshair_index,
        )

    def set_dataset_count(self, dataset_count: int) -> bool:
        """Update dataset size while preserving and clamping camera position."""

        resolved = _non_negative_int(dataset_count, "dataset_count")
        before = self.snapshot()
        self._dataset_count = resolved
        self._visible_count = self._clamp_visible(self._visible_count)
        self._start_index = self._clamp_start(self._start_index)
        self._clear_invalid_crosshair()
        return self.snapshot() != before

    def set_domain_padding(self, *, left_padding: int, right_padding: int) -> bool:
        """Update chart-only padding while preserving and clamping the camera."""

        resolved_left = _non_negative_int(left_padding, "left_padding")
        resolved_right = _non_negative_int(right_padding, "right_padding")
        before = self.snapshot()
        self._left_padding = resolved_left
        self._right_padding = resolved_right
        self._visible_count = self._clamp_visible(self._visible_count)
        self._start_index = self._clamp_start(self._start_index)
        self._clear_invalid_crosshair()
        return self.snapshot() != before

    def set_window(self, start_index: int, end_index_exclusive: int) -> bool:
        """Set an explicit chart-space camera window within policy limits."""

        start = _integer(start_index, "start_index")
        end = _integer(end_index_exclusive, "end_index_exclusive")
        if end <= start:
            raise ValueError("end_index_exclusive must be greater than start_index")
        before = self.snapshot()
        self._visible_count = self._clamp_visible(end - start)
        self._start_index = self._clamp_start(start)
        self._clear_invalid_crosshair()
        return self.snapshot() != before

    def align_latest(self) -> bool:
        """Place the latest real candle at the right edge of the camera."""

        target = self._latest_aligned_start()
        if target == self._start_index:
            return False
        self._start_index = target
        return True

    def center_on_index(self, global_index: int) -> bool:
        """Center the camera on a chart-space index and clamp to the domain."""

        center = _integer(global_index, "global_index")
        target_start = center - (self._visible_count // 2)
        target_start = self._clamp_start(target_start)
        if target_start == self._start_index:
            return False
        self._start_index = target_start
        return True

    def center_on_timestamp(
        self,
        timestamp_ms: int,
        resolve_global_index: Callable[[int], int | None],
    ) -> bool:
        """Center through the chart session's canonical timestamp resolver.

        Timestamp-to-index authority stays outside the viewport.  ``False`` is
        returned when the resolver cannot map the supplied timestamp.
        """

        timestamp = _integer(timestamp_ms, "timestamp_ms")
        if not callable(resolve_global_index):
            raise TypeError("resolve_global_index must be callable")
        resolved_index = resolve_global_index(timestamp)
        if resolved_index is None:
            return False
        return self.center_on_index(_integer(resolved_index, "resolved global index"))

    def pan_left(self, step: int = 10) -> bool:
        resolved = _integer(step, "step")
        return False if resolved <= 0 else self.pan_by(-resolved)

    def pan_right(self, step: int = 10) -> bool:
        resolved = _integer(step, "step")
        return False if resolved <= 0 else self.pan_by(resolved)

    def pan_by(self, delta: int) -> bool:
        """Move the horizontal camera by signed chart slots."""

        movement = _integer(delta, "delta")
        if movement == 0:
            return False
        target = self._clamp_start(self._start_index + movement)
        if target == self._start_index:
            return False
        self._start_index = target
        return True

    def zoom_in_at(self, anchor_index: int, anchor_relative: float) -> bool:
        if self._visible_count <= self._minimum_visible():
            return False
        new_visible = max(
            self._minimum_visible(),
            int(self._visible_count * 0.8),
        )
        return self.set_visible_anchored(new_visible, anchor_index, anchor_relative)

    def zoom_out_at(self, anchor_index: int, anchor_relative: float) -> bool:
        if self._visible_count >= self._maximum_visible():
            return False
        new_visible = min(
            self._maximum_visible(),
            max(self._visible_count + 1, int(self._visible_count * 1.25)),
        )
        return self.set_visible_anchored(new_visible, anchor_index, anchor_relative)

    def set_visible_anchored(
        self,
        visible_count: int,
        anchor_index: int,
        anchor_relative: float,
    ) -> bool:
        """Change zoom while retaining the anchor's relative screen position."""

        requested_visible = _positive_int(visible_count, "visible_count")
        anchor = self._clamp_domain_index(_integer(anchor_index, "anchor_index"))
        relative = _unit_interval(anchor_relative, "anchor_relative")
        before = self.snapshot()
        self._visible_count = self._clamp_visible(requested_visible)
        anchor_position = int(round(relative * max(1, self._visible_count - 1)))
        self._start_index = self._clamp_start(anchor - anchor_position)
        self._clear_invalid_crosshair()
        return self.snapshot() != before

    def set_crosshair(self, global_index: int | None) -> bool:
        """Set chart-space crosshair state without moving the camera."""

        if global_index is None:
            resolved: int | None = None
        else:
            candidate = _integer(global_index, "global_index")
            resolved = candidate if self._index_is_in_domain(candidate) else None
        if resolved == self._crosshair_index:
            return False
        self._crosshair_index = resolved
        return True

    def global_index_at_relative(self, relative: float) -> int:
        """Map normalized horizontal position ``0..1`` to a visible slot."""

        resolved = _unit_interval(relative, "relative")
        slot = int(resolved * self._visible_count)
        slot = min(self._visible_count - 1, slot)
        return self._start_index + slot

    def relative_for_global_index(self, global_index: int) -> float:
        """Return the visible slot-center position for a chart-space index."""

        index = _integer(global_index, "global_index")
        clamped = max(self._start_index, min(self.end_index_exclusive - 1, index))
        offset = clamped - self._start_index
        return (offset + 0.5) / self._visible_count

    def dataset_interest(self) -> DatasetInterest | None:
        """Map the camera to real dataset indexes for resident-data requests."""

        if self._dataset_count <= 0:
            return None
        start = self._start_index
        end = self.end_index_exclusive
        if end <= 0:
            interest_start = 0
            interest_end = min(self._dataset_count, self._visible_count)
        elif start >= self._dataset_count:
            interest_end = self._dataset_count
            interest_start = max(0, interest_end - self._visible_count)
        else:
            interest_start = max(0, start)
            interest_end = min(self._dataset_count, end)
        return DatasetInterest(interest_start, interest_end)

    def resident_refill_direction(
        self,
        *,
        resident_start_index: int,
        resident_end_index_exclusive: int,
        has_more_left: bool,
        has_more_right: bool,
        threshold: int = DEFAULT_REFILL_THRESHOLD,
    ) -> ResidentRefillDirection:
        """Return whether the camera is approaching a resident-data edge."""

        resident_start = _non_negative_int(resident_start_index, "resident_start_index")
        resident_end = _positive_int(
            resident_end_index_exclusive,
            "resident_end_index_exclusive",
        )
        if resident_end <= resident_start:
            raise ValueError(
                "resident_end_index_exclusive must be greater than resident_start_index"
            )
        if resident_end > self._dataset_count:
            raise ValueError("resident interval exceeds dataset_count")
        left_available = _boolean(has_more_left, "has_more_left")
        right_available = _boolean(has_more_right, "has_more_right")
        resolved_threshold = _non_negative_int(threshold, "threshold")
        interest = self.dataset_interest()
        if interest is None:
            return ResidentRefillDirection.NONE

        if interest.end_index_exclusive <= resident_start:
            return (
                ResidentRefillDirection.LEFT
                if left_available
                else ResidentRefillDirection.NONE
            )
        if interest.start_index >= resident_end:
            return (
                ResidentRefillDirection.RIGHT
                if right_available
                else ResidentRefillDirection.NONE
            )

        left_distance = interest.start_index - resident_start
        right_distance = resident_end - interest.end_index_exclusive
        needs_left = left_available and left_distance <= resolved_threshold
        needs_right = right_available and right_distance <= resolved_threshold
        if needs_left and needs_right:
            if left_distance < right_distance:
                return ResidentRefillDirection.LEFT
            if right_distance < left_distance:
                return ResidentRefillDirection.RIGHT
            resident_center = resident_start + ((resident_end - resident_start) // 2)
            return (
                ResidentRefillDirection.LEFT
                if interest.center_index <= resident_center
                else ResidentRefillDirection.RIGHT
            )
        if needs_left:
            return ResidentRefillDirection.LEFT
        if needs_right:
            return ResidentRefillDirection.RIGHT
        return ResidentRefillDirection.NONE

    def _minimum_visible(self) -> int:
        return min(MIN_VISIBLE_BARS, self.domain_size)

    def _maximum_visible(self) -> int:
        return min(MAX_VISIBLE_BARS, self.domain_size)

    def _clamp_visible(self, visible_count: int) -> int:
        requested = _positive_int(visible_count, "visible_count")
        return max(self._minimum_visible(), min(requested, self._maximum_visible()))

    def _minimum_start(self) -> int:
        return self.domain_start

    def _maximum_start(self) -> int:
        return max(
            self._minimum_start(),
            self.domain_end_exclusive - self._visible_count,
        )

    def _clamp_start(self, start_index: int) -> int:
        return max(self._minimum_start(), min(start_index, self._maximum_start()))

    def _latest_aligned_start(self) -> int:
        return self._clamp_start(self._dataset_count - self._visible_count)

    def _index_is_in_domain(self, index: int) -> bool:
        return self.domain_start <= index < self.domain_end_exclusive

    def _clamp_domain_index(self, index: int) -> int:
        maximum = max(self.domain_start, self.domain_end_exclusive - 1)
        return max(self.domain_start, min(index, maximum))

    def _clear_invalid_crosshair(self) -> None:
        if self._crosshair_index is not None and not self._index_is_in_domain(
            self._crosshair_index
        ):
            self._crosshair_index = None


def _integer(value: int, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _positive_int(value: int, name: str) -> int:
    resolved = _integer(value, name)
    if resolved <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return resolved


def _non_negative_int(value: int, name: str) -> int:
    resolved = _integer(value, name)
    if resolved < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return resolved



def _boolean(value: bool, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _unit_interval(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number between 0 and 1")
    resolved = float(value)
    if resolved < 0.0 or resolved > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return resolved
