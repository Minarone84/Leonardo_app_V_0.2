"""Pure scene planning for the historical Research candlestick renderer.

This module deliberately has no PySide6 dependency. It converts immutable
Research resident data and horizontal viewport snapshots into immutable drawing
geometry. The Qt widget owns painting and pixmap caching only; it does not own
market data, camera state, price-scale state, or financial calculations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from leonardo.gui.chart.price_scale import PriceScaleSnapshot
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.viewport import ViewportSnapshot

DEFAULT_AXIS_WIDTH = 64.0
DEFAULT_TIME_AXIS_HEIGHT = 24.0
DEFAULT_LEFT_MARGIN = 2.0
DEFAULT_TOP_MARGIN = 4.0
DEFAULT_HORIZONTAL_GRID_LINES = 8
DEFAULT_PRICE_TICK_COUNT = 6
_MIN_PRICE_SPAN = 1e-12


@dataclass(frozen=True, slots=True)
class SceneRect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.width < 0 or self.height < 0:
            raise ValueError("scene rectangle dimensions must be non-negative")

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True, slots=True)
class SceneLine:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class PriceAxisTick:
    price: float
    y: float
    label: str


@dataclass(frozen=True, slots=True)
class LastPriceTag:
    price: float
    y: float
    label: str
    bullish: bool


@dataclass(frozen=True, slots=True)
class TimeAxisTick:
    global_index: int
    timestamp_ms: int
    x: float
    label: str


@dataclass(frozen=True, slots=True)
class CandleGlyph:
    """One normal or pixel-compressed candle drawing instruction."""

    first_global_index: int
    last_global_index: int
    x: float
    wick_top: float
    wick_bottom: float
    body_top: float
    body_bottom: float
    body_width: float
    bullish: bool
    compressed: bool
    open_price: float
    high_price: float
    low_price: float
    close_price: float

    @property
    def body_height(self) -> float:
        return max(1.0, self.body_bottom - self.body_top)


@dataclass(frozen=True, slots=True)
class CandlestickRenderContract:
    """Immutable renderer input owned by upstream Research/GUI coordination."""

    viewport: ViewportSnapshot
    resident: ResidentOHLCVSlice | None
    price_scale: PriceScaleSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.viewport, ViewportSnapshot):
            raise TypeError("viewport must be a ViewportSnapshot")
        if self.price_scale is not None and not isinstance(self.price_scale, PriceScaleSnapshot):
            raise TypeError("price_scale must be a PriceScaleSnapshot or None")
        if self.resident is not None:
            if not isinstance(self.resident, ResidentOHLCVSlice):
                raise TypeError("resident must be a ResidentOHLCVSlice or None")
            if self.resident.end_index_exclusive > self.viewport.dataset_count:
                raise ValueError("resident range exceeds viewport dataset_count")

    def cache_identity(self) -> tuple[object, ...]:
        resident_identity: tuple[object, ...] | None = None
        if self.resident is not None:
            resident_identity = (
                self.resident.market_id,
                self.resident.dataset_fingerprint,
                self.resident.base_index,
                self.resident.end_index_exclusive,
            )
        viewport = self.viewport
        return (
            viewport.dataset_count,
            viewport.left_padding,
            viewport.right_padding,
            viewport.start_index,
            viewport.end_index_exclusive,
            viewport.visible_count,
            resident_identity,
            None if self.price_scale is None else self.price_scale.cache_identity(),
        )


@dataclass(frozen=True, slots=True)
class CandlestickScene:
    width: int
    height: int
    plot_rect: SceneRect
    price_axis_rect: SceneRect
    time_axis_rect: SceneRect
    price_low: float
    price_high: float
    horizontal_grid: tuple[SceneLine, ...]
    vertical_grid: tuple[SceneLine, ...]
    price_ticks: tuple[PriceAxisTick, ...]
    time_ticks: tuple[TimeAxisTick, ...]
    candles: tuple[CandleGlyph, ...]
    left_gap_rect: SceneRect | None
    left_gap_message: str | None
    center_message: str | None
    last_price_tag: LastPriceTag | None


@dataclass(frozen=True, slots=True)
class _VisibleCandle:
    global_index: int
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float


def build_candlestick_scene(
    contract: CandlestickRenderContract,
    *,
    width: int,
    height: int,
) -> CandlestickScene:
    """Build deterministic render geometry for one static candlestick scene."""

    if not isinstance(contract, CandlestickRenderContract):
        raise TypeError("contract must be a CandlestickRenderContract")
    if type(width) is not int or width <= 0:
        raise ValueError("width must be a positive integer")
    if type(height) is not int or height <= 0:
        raise ValueError("height must be a positive integer")

    plot = SceneRect(
        DEFAULT_LEFT_MARGIN,
        DEFAULT_TOP_MARGIN,
        max(1.0, width - DEFAULT_LEFT_MARGIN - DEFAULT_AXIS_WIDTH),
        max(1.0, height - DEFAULT_TOP_MARGIN - DEFAULT_TIME_AXIS_HEIGHT),
    )
    price_axis = SceneRect(plot.right, plot.y, DEFAULT_AXIS_WIDTH, plot.height)
    time_axis = SceneRect(plot.x, plot.bottom, plot.width, DEFAULT_TIME_AXIS_HEIGHT)

    visible = _visible_candles(contract)
    if contract.price_scale is None:
        price_low, price_high = _price_range(visible)
    else:
        price_low = contract.price_scale.price_range.low
        price_high = contract.price_scale.price_range.high
    price_ticks = _price_ticks(plot, price_low, price_high)
    time_ticks = _time_ticks(contract, plot)
    horizontal_grid = tuple(
        SceneLine(plot.x, tick.y, plot.right, tick.y) for tick in price_ticks
    )
    vertical_grid = tuple(
        SceneLine(tick.x, plot.y, tick.x, plot.bottom) for tick in time_ticks
    )
    candle_glyphs = _candle_glyphs(
        visible,
        contract.viewport,
        plot,
        price_low,
        price_high,
    )
    left_gap_rect = _left_gap_rect(contract.viewport, plot)
    last_price_tag = _last_price_tag(visible, plot, price_low, price_high)

    center_message: str | None = None
    if contract.viewport.dataset_count == 0 or contract.resident is None:
        center_message = "No accepted OHLCV data"

    return CandlestickScene(
        width=width,
        height=height,
        plot_rect=plot,
        price_axis_rect=price_axis,
        time_axis_rect=time_axis,
        price_low=price_low,
        price_high=price_high,
        horizontal_grid=horizontal_grid,
        vertical_grid=vertical_grid,
        price_ticks=price_ticks,
        time_ticks=time_ticks,
        candles=candle_glyphs,
        left_gap_rect=left_gap_rect,
        left_gap_message="No older data" if left_gap_rect is not None else None,
        center_message=center_message,
        last_price_tag=last_price_tag,
    )



def _last_price_tag(
    visible: tuple[_VisibleCandle, ...],
    plot: SceneRect,
    low: float,
    high: float,
) -> LastPriceTag | None:
    if not visible:
        return None
    last = visible[-1]
    span = high - low
    return LastPriceTag(
        price=last.close,
        y=_y_for_price(plot, last.close, low, high),
        label=_format_price(last.close, span),
        bullish=last.close >= last.open,
    )

def _visible_candles(contract: CandlestickRenderContract) -> tuple[_VisibleCandle, ...]:
    resident = contract.resident
    if resident is None:
        return ()
    viewport = contract.viewport
    start = max(viewport.start_index, resident.base_index, 0)
    end = min(
        viewport.end_index_exclusive,
        resident.end_index_exclusive,
        viewport.dataset_count,
    )
    if end <= start:
        return ()

    output: list[_VisibleCandle] = []
    for global_index in range(start, end):
        local = global_index - resident.base_index
        output.append(
            _VisibleCandle(
                global_index=global_index,
                timestamp_ms=resident.ts_ms[local],
                open=resident.open[local],
                high=resident.high[local],
                low=resident.low[local],
                close=resident.close[local],
            )
        )
    return tuple(output)


def _price_range(visible: tuple[_VisibleCandle, ...]) -> tuple[float, float]:
    if not visible:
        return (0.0, 1.0)
    low = min(candle.low for candle in visible)
    high = max(candle.high for candle in visible)
    span = high - low
    if span <= _MIN_PRICE_SPAN:
        expansion = max(abs(high) * 0.01, 1.0)
        return (low - expansion, high + expansion)
    padding = span * 0.04
    return (low - padding, high + padding)


def _price_ticks(
    plot: SceneRect,
    low: float,
    high: float,
) -> tuple[PriceAxisTick, ...]:
    span = high - low
    ticks: list[PriceAxisTick] = []
    for index in range(DEFAULT_PRICE_TICK_COUNT):
        relative = index / (DEFAULT_PRICE_TICK_COUNT - 1)
        price = high - relative * span
        y = plot.y + relative * plot.height
        ticks.append(PriceAxisTick(price=price, y=y, label=_format_price(price, span)))
    return tuple(ticks)


def _format_price(value: float, span: float) -> str:
    absolute_span = abs(span)
    if absolute_span >= 1_000:
        decimals = 0
    elif absolute_span >= 10:
        decimals = 2
    elif absolute_span >= 0.1:
        decimals = 4
    else:
        decimals = 6
    return f"{value:.{decimals}f}"


def _candle_glyphs(
    visible: tuple[_VisibleCandle, ...],
    viewport: ViewportSnapshot,
    plot: SceneRect,
    low: float,
    high: float,
) -> tuple[CandleGlyph, ...]:
    if not visible:
        return ()
    cell_width = plot.width / max(1, viewport.visible_count)
    if cell_width < 2.0:
        return _compressed_glyphs(visible, viewport, plot, low, high)

    body_width = max(1.0, max(3.0, cell_width) * 0.65)
    return tuple(
        _glyph_from_ohlc(
            first_global_index=candle.global_index,
            last_global_index=candle.global_index,
            x=_x_for_index(viewport, plot, candle.global_index),
            body_width=body_width,
            compressed=False,
            open_price=candle.open,
            high_price=candle.high,
            low_price=candle.low,
            close_price=candle.close,
            plot=plot,
            price_low=low,
            price_high=high,
        )
        for candle in visible
    )


def _compressed_glyphs(
    visible: tuple[_VisibleCandle, ...],
    viewport: ViewportSnapshot,
    plot: SceneRect,
    low: float,
    high: float,
) -> tuple[CandleGlyph, ...]:
    buckets: list[list[_VisibleCandle]] = []
    last_pixel: int | None = None
    for candle in visible:
        pixel = int(math.floor(_x_for_index(viewport, plot, candle.global_index)))
        if last_pixel != pixel:
            buckets.append([candle])
            last_pixel = pixel
        else:
            buckets[-1].append(candle)

    glyphs: list[CandleGlyph] = []
    for bucket in buckets:
        first = bucket[0]
        last = bucket[-1]
        x = math.floor(_x_for_index(viewport, plot, first.global_index)) + 0.5
        glyphs.append(
            _glyph_from_ohlc(
                first_global_index=first.global_index,
                last_global_index=last.global_index,
                x=x,
                body_width=1.0,
                compressed=True,
                open_price=first.open,
                high_price=max(item.high for item in bucket),
                low_price=min(item.low for item in bucket),
                close_price=last.close,
                plot=plot,
                price_low=low,
                price_high=high,
            )
        )
    return tuple(glyphs)


def _glyph_from_ohlc(
    *,
    first_global_index: int,
    last_global_index: int,
    x: float,
    body_width: float,
    compressed: bool,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    plot: SceneRect,
    price_low: float,
    price_high: float,
) -> CandleGlyph:
    open_y = _y_for_price(plot, open_price, price_low, price_high)
    close_y = _y_for_price(plot, close_price, price_low, price_high)
    return CandleGlyph(
        first_global_index=first_global_index,
        last_global_index=last_global_index,
        x=x,
        wick_top=_y_for_price(plot, high_price, price_low, price_high),
        wick_bottom=_y_for_price(plot, low_price, price_low, price_high),
        body_top=min(open_y, close_y),
        body_bottom=max(open_y, close_y),
        body_width=body_width,
        bullish=close_price >= open_price,
        compressed=compressed,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
    )


def _x_for_index(
    viewport: ViewportSnapshot,
    plot: SceneRect,
    global_index: int,
) -> float:
    relative = (global_index - viewport.start_index + 0.5) / viewport.visible_count
    return plot.x + relative * plot.width


def _y_for_price(plot: SceneRect, price: float, low: float, high: float) -> float:
    span = max(_MIN_PRICE_SPAN, high - low)
    relative = (high - price) / span
    return plot.y + min(1.0, max(0.0, relative)) * plot.height


def _left_gap_rect(
    viewport: ViewportSnapshot,
    plot: SceneRect,
) -> SceneRect | None:
    if viewport.start_index >= 0:
        return None
    gap_slots = min(-viewport.start_index, viewport.visible_count)
    if gap_slots <= 0:
        return None
    width = plot.width * (gap_slots / viewport.visible_count)
    return SceneRect(plot.x, plot.y, width, plot.height)


def _time_ticks(
    contract: CandlestickRenderContract,
    plot: SceneRect,
) -> tuple[TimeAxisTick, ...]:
    viewport = contract.viewport
    target_count = max(2, min(12, int(plot.width // 100)))
    offsets = _even_offsets(viewport.visible_count, target_count)
    ticks: list[TimeAxisTick] = []
    seen: set[tuple[int, str]] = set()
    display_span_ms = _display_span_ms(contract)

    for offset in offsets:
        global_index = viewport.start_index + offset
        timestamp = _timestamp_for_global_index(contract, global_index)
        if timestamp is None:
            continue
        label = _format_timestamp(timestamp, display_span_ms)
        identity = (global_index, label)
        if identity in seen:
            continue
        seen.add(identity)
        ticks.append(
            TimeAxisTick(
                global_index=global_index,
                timestamp_ms=timestamp,
                x=_x_for_index(viewport, plot, global_index),
                label=label,
            )
        )
    return tuple(ticks)


def _even_offsets(visible_count: int, target_count: int) -> tuple[int, ...]:
    if visible_count <= 1:
        return (0,)
    count = min(visible_count, target_count)
    return tuple(
        min(visible_count - 1, round(index * (visible_count - 1) / (count - 1)))
        for index in range(count)
    )


def _timestamp_for_global_index(
    contract: CandlestickRenderContract,
    global_index: int,
) -> int | None:
    resident = contract.resident
    if resident is None or resident.row_count == 0:
        return None
    if resident.base_index <= global_index < resident.end_index_exclusive:
        return resident.ts_ms[global_index - resident.base_index]

    timeframe_ms = _inferred_timeframe_ms(resident)
    if timeframe_ms is None:
        return None
    if global_index < 0 and resident.base_index == 0:
        return resident.ts_ms[0] + global_index * timeframe_ms
    if (
        global_index >= contract.viewport.dataset_count
        and resident.end_index_exclusive == contract.viewport.dataset_count
    ):
        last_global_index = contract.viewport.dataset_count - 1
        return resident.ts_ms[-1] + (global_index - last_global_index) * timeframe_ms
    return None


def _inferred_timeframe_ms(resident: ResidentOHLCVSlice) -> int | None:
    if resident.row_count < 2:
        return None
    deltas = [
        resident.ts_ms[index] - resident.ts_ms[index - 1]
        for index in range(1, min(resident.row_count, 64))
    ]
    positive = [delta for delta in deltas if delta > 0]
    if not positive:
        return None
    positive.sort()
    return positive[len(positive) // 2]


def _display_span_ms(contract: CandlestickRenderContract) -> int:
    first = _timestamp_for_global_index(contract, contract.viewport.start_index)
    last = _timestamp_for_global_index(
        contract,
        contract.viewport.end_index_exclusive - 1,
    )
    if first is None or last is None:
        resident = contract.resident
        if resident is None:
            return 0
        return max(0, resident.last_timestamp_ms - resident.first_timestamp_ms)
    return max(0, last - first)


def _format_timestamp(timestamp_ms: int, span_ms: int) -> str:
    moment = datetime.fromtimestamp(timestamp_ms / 1_000, tz=timezone.utc)
    day_ms = 86_400_000
    if span_ms < day_ms:
        return moment.strftime("%H:%M")
    if span_ms < 120 * day_ms:
        return moment.strftime("%d %b")
    if span_ms < 730 * day_ms:
        return moment.strftime("%b %Y")
    return moment.strftime("%Y")
