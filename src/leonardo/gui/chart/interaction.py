"""Pure interaction adapter for one historical candlestick chart.

The adapter translates local GUI gestures into the canonical horizontal
viewport and price-scale authorities.  It contains no Qt dependency and performs
no I/O, calculation, persistence, or task management.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from leonardo.gui.chart.candlestick_scene import CandlestickRenderContract
from leonardo.gui.chart.price_scale import PriceScaleSnapshot, PriceScaleState
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.viewport import HorizontalViewport


class CandlestickInteractionState:
    def __init__(
        self,
        viewport: HorizontalViewport,
        resident: ResidentOHLCVSlice | None,
        *,
        price_scale: PriceScaleState | None = None,
    ) -> None:
        if not isinstance(viewport, HorizontalViewport):
            raise TypeError("viewport must be a HorizontalViewport")
        if resident is not None and not isinstance(resident, ResidentOHLCVSlice):
            raise TypeError("resident must be a ResidentOHLCVSlice or None")
        if price_scale is not None and not isinstance(price_scale, PriceScaleState):
            raise TypeError("price_scale must be a PriceScaleState or None")
        self._viewport = viewport
        self._resident = resident
        self._price_scale = price_scale or PriceScaleState()

    @property
    def viewport(self) -> HorizontalViewport:
        return self._viewport

    @property
    def resident(self) -> ResidentOHLCVSlice | None:
        return self._resident

    @property
    def price_scale(self) -> PriceScaleState:
        return self._price_scale

    def set_resident(self, resident: ResidentOHLCVSlice | None) -> bool:
        if resident is not None and not isinstance(resident, ResidentOHLCVSlice):
            raise TypeError("resident must be a ResidentOHLCVSlice or None")
        if resident is self._resident:
            return False
        self._resident = resident
        return True

    def render_contract(
        self,
        *,
        refresh_price_scale: bool = True,
        extra_visible_prices: Iterable[float] = (),
    ) -> CandlestickRenderContract:
        viewport = self._viewport.snapshot()
        scale = (
            self._price_scale.resolve(
                viewport,
                self._resident,
                extra_visible_prices=extra_visible_prices,
            )
            if refresh_price_scale
            else self._price_scale.snapshot()
        )
        return CandlestickRenderContract(
            viewport=viewport,
            resident=self._resident,
            price_scale=scale,
        )

    def pan_horizontal_pixels(self, delta_x: float, plot_width: float) -> bool:
        width = _positive_finite(plot_width, "plot_width")
        delta = _finite(delta_x, "delta_x")
        if delta == 0:
            return False
        step = max(1, int(abs(delta) / width * self._viewport.visible_count))
        return self._viewport.pan_by(-step if delta > 0 else step)

    def zoom_horizontal(self, wheel_delta: int, relative_x: float) -> bool:
        if type(wheel_delta) is not int:
            raise TypeError("wheel_delta must be an integer")
        relative = _unit_interval(relative_x, "relative_x")
        anchor = self._viewport.global_index_at_relative(relative)
        if wheel_delta > 0:
            return self._viewport.zoom_in_at(anchor, relative)
        if wheel_delta < 0:
            return self._viewport.zoom_out_at(anchor, relative)
        return False

    def move_crosshair(self, relative_x: float) -> bool:
        relative = _unit_interval(relative_x, "relative_x")
        return self._viewport.set_crosshair(
            self._viewport.global_index_at_relative(relative)
        )

    def clear_crosshair(self) -> bool:
        return self._viewport.set_crosshair(None)

    def set_autoscale_enabled(self, enabled: bool) -> bool:
        # Resolve first so disabling autoscale seeds a real visible range.
        self._price_scale.resolve(self._viewport.snapshot(), self._resident)
        return self._price_scale.set_autoscale_enabled(enabled)

    def toggle_autoscale(self) -> bool:
        return self.set_autoscale_enabled(not self._price_scale.autoscale_enabled)

    def pan_price_pixels(self, delta_y: float, plot_height: float) -> bool:
        return self._price_scale.pan_by_pixels(delta_y, plot_height)

    def zoom_price_pixels(self, delta_y: float) -> bool:
        return self._price_scale.zoom_by_pixels(delta_y)

    def price_scale_snapshot(
        self, *, extra_visible_prices: Iterable[float] = ()
    ) -> PriceScaleSnapshot:
        return self._price_scale.resolve(
            self._viewport.snapshot(),
            self._resident,
            extra_visible_prices=extra_visible_prices,
        )


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _positive_finite(value: float, name: str) -> float:
    resolved = _finite(value, name)
    if resolved <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return resolved


def _unit_interval(value: float, name: str) -> float:
    resolved = _finite(value, name)
    return min(1.0, max(0.0, resolved))
