"""Pure vertical price-scale state for historical Research charts.

The price scale is GUI presentation state.  It owns autoscale/manual-y mode and
its explicit manual range, but it does not own OHLCV truth, horizontal camera
state, studies, or rendering.  Autoscale is derived from the visible resident
candles and optional visible price values supplied by future overlay code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.viewport import ViewportSnapshot

_MIN_SPAN = 1e-12
_DEFAULT_PADDING_FRACTION = 0.04


@dataclass(frozen=True, slots=True)
class PriceRange:
    low: float
    high: float

    def __post_init__(self) -> None:
        low = _finite(self.low, "low")
        high = _finite(self.high, "high")
        if high <= low:
            raise ValueError("high must be greater than low")

    @property
    def span(self) -> float:
        return self.high - self.low

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) * 0.5


@dataclass(frozen=True, slots=True)
class PriceScaleSnapshot:
    autoscale_enabled: bool
    price_range: PriceRange

    def __post_init__(self) -> None:
        if type(self.autoscale_enabled) is not bool:
            raise TypeError("autoscale_enabled must be a boolean")
        if not isinstance(self.price_range, PriceRange):
            raise TypeError("price_range must be a PriceRange")

    def cache_identity(self) -> tuple[object, ...]:
        return (
            self.autoscale_enabled,
            self.price_range.low,
            self.price_range.high,
        )


class PriceScaleState:
    """Canonical mutable vertical presentation state for one price pane."""

    def __init__(self, *, autoscale_enabled: bool = True) -> None:
        if type(autoscale_enabled) is not bool:
            raise TypeError("autoscale_enabled must be a boolean")
        self._autoscale_enabled = autoscale_enabled
        self._manual_range: PriceRange | None = None
        self._last_auto_range = PriceRange(0.0, 1.0)

    @property
    def autoscale_enabled(self) -> bool:
        return self._autoscale_enabled

    @property
    def manual_range(self) -> PriceRange | None:
        return self._manual_range

    @property
    def last_auto_range(self) -> PriceRange:
        return self._last_auto_range

    def resolve(
        self,
        viewport: ViewportSnapshot,
        resident: ResidentOHLCVSlice | None,
        *,
        extra_visible_prices: Iterable[float] = (),
    ) -> PriceScaleSnapshot:
        auto_range = visible_price_range(
            viewport,
            resident,
            extra_visible_prices=extra_visible_prices,
        )
        self._last_auto_range = auto_range
        if self._autoscale_enabled:
            resolved = auto_range
        else:
            if self._manual_range is None:
                self._manual_range = auto_range
            resolved = self._manual_range
        return PriceScaleSnapshot(self._autoscale_enabled, resolved)

    def snapshot(self) -> PriceScaleSnapshot:
        """Return the current explicit scale without rescanning visible data."""

        resolved = (
            self._last_auto_range
            if self._autoscale_enabled
            else (self._manual_range or self._last_auto_range)
        )
        return PriceScaleSnapshot(self._autoscale_enabled, resolved)

    def set_autoscale_enabled(self, enabled: bool) -> bool:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        if enabled == self._autoscale_enabled:
            return False
        if not enabled and self._manual_range is None:
            self._manual_range = self._last_auto_range
        self._autoscale_enabled = enabled
        return True

    def set_manual_range(self, low: float, high: float) -> bool:
        resolved = PriceRange(low, high)
        changed = self._manual_range != resolved or self._autoscale_enabled
        self._manual_range = resolved
        self._autoscale_enabled = False
        return changed

    def reset_manual_range(self) -> bool:
        changed = self._manual_range is not None or not self._autoscale_enabled
        self._manual_range = None
        self._autoscale_enabled = True
        return changed

    def pan_by_pixels(self, delta_y: float, plot_height: float) -> bool:
        """Pan a manual price range; positive y movement shifts prices upward."""

        if self._autoscale_enabled:
            return False
        height = _positive_finite(plot_height, "plot_height")
        delta = _finite(delta_y, "delta_y")
        current = self._manual_range or self._last_auto_range
        shift = (delta / height) * current.span
        return self.set_manual_range(current.low + shift, current.high + shift)

    def zoom_by_pixels(self, delta_y: float) -> bool:
        """Zoom a manual range around its midpoint using the old chart behavior."""

        if self._autoscale_enabled:
            return False
        delta = _finite(delta_y, "delta_y")
        current = self._manual_range or self._last_auto_range
        factor = max(0.15, min(8.0, 1.0 + (delta / 180.0)))
        new_span = max(_MIN_SPAN, current.span * factor)
        midpoint = current.midpoint
        return self.set_manual_range(
            midpoint - new_span * 0.5,
            midpoint + new_span * 0.5,
        )


def visible_price_range(
    viewport: ViewportSnapshot,
    resident: ResidentOHLCVSlice | None,
    *,
    extra_visible_prices: Iterable[float] = (),
    padding_fraction: float = _DEFAULT_PADDING_FRACTION,
) -> PriceRange:
    """Return an autoscale range from visible candles and optional overlays."""

    if not isinstance(viewport, ViewportSnapshot):
        raise TypeError("viewport must be a ViewportSnapshot")
    padding = _finite(padding_fraction, "padding_fraction")
    if padding < 0:
        raise ValueError("padding_fraction must be non-negative")

    values: list[float] = []
    if resident is not None:
        if not isinstance(resident, ResidentOHLCVSlice):
            raise TypeError("resident must be a ResidentOHLCVSlice or None")
        start = max(viewport.start_index, resident.base_index, 0)
        end = min(
            viewport.end_index_exclusive,
            resident.end_index_exclusive,
            viewport.dataset_count,
        )
        for global_index in range(start, end):
            local = global_index - resident.base_index
            values.append(_finite(resident.low[local], "resident low"))
            values.append(_finite(resident.high[local], "resident high"))

    for value in extra_visible_prices:
        values.append(_finite(value, "extra visible price"))

    if not values:
        return PriceRange(0.0, 1.0)

    low = min(values)
    high = max(values)
    span = high - low
    if span <= _MIN_SPAN:
        expansion = max(abs(high) * 0.01, 1.0)
        return PriceRange(low - expansion, high + expansion)
    expansion = span * padding
    return PriceRange(low - expansion, high + expansion)


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _positive_finite(value: float, name: str) -> float:
    resolved = _finite(value, name)
    if resolved <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return resolved
