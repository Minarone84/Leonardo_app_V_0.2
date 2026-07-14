"""Pure scene planning for the historical Research volume pane."""

from __future__ import annotations

import math
from dataclasses import dataclass

from leonardo.gui.chart.candlestick_scene import (
    DEFAULT_AXIS_WIDTH,
    DEFAULT_LEFT_MARGIN,
    DEFAULT_TOP_MARGIN,
    SceneLine,
    SceneRect,
)
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.viewport import ViewportSnapshot
from leonardo.research.volume import ResidentVolumeProjection

DEFAULT_BOTTOM_MARGIN = 2.0
DEFAULT_VOLUME_GRID_LINES = 4


@dataclass(frozen=True, slots=True)
class VolumeBarGlyph:
    global_index: int
    x: float
    top: float
    bottom: float
    width: float
    bullish: bool
    value: float

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


@dataclass(frozen=True, slots=True)
class VolumeMeanPoint:
    global_index: int
    x: float
    y: float
    value: float


@dataclass(frozen=True, slots=True)
class VolumeAxisTick:
    value: float
    y: float
    label: str


@dataclass(frozen=True, slots=True)
class LastVolumeTag:
    value: float
    y: float
    label: str
    bullish: bool


@dataclass(frozen=True, slots=True)
class VolumeRenderContract:
    """Immutable volume-pane renderer input."""

    viewport: ViewportSnapshot
    resident: ResidentOHLCVSlice | None
    projection: ResidentVolumeProjection | None

    def __post_init__(self) -> None:
        if not isinstance(self.viewport, ViewportSnapshot):
            raise TypeError("viewport must be a ViewportSnapshot")
        if self.resident is None or self.projection is None:
            if self.resident is not None or self.projection is not None:
                raise ValueError("resident and projection must both be set or both be None")
            return
        if not isinstance(self.resident, ResidentOHLCVSlice):
            raise TypeError("resident must be a ResidentOHLCVSlice or None")
        if not isinstance(self.projection, ResidentVolumeProjection):
            raise TypeError("projection must be a ResidentVolumeProjection or None")
        if self.resident.market_id != self.projection.market_id:
            raise ValueError("volume projection MarketId does not match resident")
        if self.resident.dataset_fingerprint != self.projection.dataset_fingerprint:
            raise ValueError("volume projection fingerprint does not match resident")
        if self.resident.base_index != self.projection.base_index:
            raise ValueError("volume projection base index does not match resident")
        if self.resident.end_index_exclusive != self.projection.end_index_exclusive:
            raise ValueError("volume projection end index does not match resident")
        if self.resident.volume != self.projection.volume:
            raise ValueError("volume projection values do not match resident")
        if self.resident.end_index_exclusive > self.viewport.dataset_count:
            raise ValueError("resident range exceeds viewport dataset_count")

    def cache_identity(self) -> tuple[object, ...]:
        viewport = self.viewport
        projection_identity: tuple[object, ...] | None = None
        if self.projection is not None:
            projection_identity = (
                self.projection.market_id,
                self.projection.dataset_fingerprint,
                self.projection.base_index,
                self.projection.end_index_exclusive,
                self.projection.period,
            )
        return (
            viewport.dataset_count,
            viewport.left_padding,
            viewport.right_padding,
            viewport.start_index,
            viewport.end_index_exclusive,
            viewport.visible_count,
            projection_identity,
        )


@dataclass(frozen=True, slots=True)
class VolumeScene:
    width: int
    height: int
    plot_rect: SceneRect
    axis_rect: SceneRect
    maximum: float
    horizontal_grid: tuple[SceneLine, ...]
    axis_ticks: tuple[VolumeAxisTick, ...]
    bars: tuple[VolumeBarGlyph, ...]
    moving_mean: tuple[VolumeMeanPoint, ...]
    center_message: str | None
    last_volume_tag: LastVolumeTag | None


def build_volume_scene(
    contract: VolumeRenderContract,
    *,
    width: int,
    height: int,
) -> VolumeScene:
    if not isinstance(contract, VolumeRenderContract):
        raise TypeError("contract must be a VolumeRenderContract")
    if type(width) is not int or width <= 0:
        raise ValueError("width must be a positive integer")
    if type(height) is not int or height <= 0:
        raise ValueError("height must be a positive integer")

    plot = SceneRect(
        DEFAULT_LEFT_MARGIN,
        DEFAULT_TOP_MARGIN,
        max(1.0, width - DEFAULT_LEFT_MARGIN - DEFAULT_AXIS_WIDTH),
        max(1.0, height - DEFAULT_TOP_MARGIN - DEFAULT_BOTTOM_MARGIN),
    )
    axis = SceneRect(plot.right, plot.y, DEFAULT_AXIS_WIDTH, plot.height)
    visible = _visible_rows(contract)
    real_values = [row[1] for row in visible]
    real_values.extend(row[3] for row in visible if row[3] is not None)
    maximum = max(real_values, default=0.0)
    if maximum > 0:
        maximum *= 1.05
    else:
        maximum = 1.0

    ticks = _axis_ticks(plot, maximum)
    grid = tuple(SceneLine(plot.x, tick.y, plot.right, tick.y) for tick in ticks)
    bars = _bar_glyphs(contract.viewport, visible, plot, maximum)
    mean_points = _mean_points(contract.viewport, visible, plot, maximum)
    tag = _last_volume_tag(visible, plot, maximum)
    center_message: str | None = None
    if contract.resident is None:
        center_message = "No accepted OHLCV data"
    elif not visible:
        center_message = "No resident volume in view"

    return VolumeScene(
        width=width,
        height=height,
        plot_rect=plot,
        axis_rect=axis,
        maximum=maximum,
        horizontal_grid=grid,
        axis_ticks=ticks,
        bars=bars,
        moving_mean=mean_points,
        center_message=center_message,
        last_volume_tag=tag,
    )


def _visible_rows(
    contract: VolumeRenderContract,
) -> tuple[tuple[int, float, bool, float | None], ...]:
    projection = contract.projection
    if projection is None:
        return ()
    rows: list[tuple[int, float, bool, float | None]] = []
    for global_index in range(
        contract.viewport.start_index,
        contract.viewport.end_index_exclusive,
    ):
        local = projection.local_index_for_global(global_index)
        if local is None:
            continue
        value = float(projection.volume[local])
        mean = projection.moving_mean[local]
        if not math.isfinite(value) or value < 0:
            continue
        if mean is not None and not math.isfinite(float(mean)):
            mean = None
        rows.append((global_index, value, projection.bullish[local], mean))
    return tuple(rows)


def _axis_ticks(plot: SceneRect, maximum: float) -> tuple[VolumeAxisTick, ...]:
    ticks: list[VolumeAxisTick] = []
    for offset in range(DEFAULT_VOLUME_GRID_LINES + 1):
        fraction = offset / DEFAULT_VOLUME_GRID_LINES
        value = maximum * (1.0 - fraction)
        y = plot.y + fraction * plot.height
        ticks.append(VolumeAxisTick(value=value, y=y, label=_format_volume(value)))
    return tuple(ticks)


def _bar_glyphs(
    viewport: ViewportSnapshot,
    visible: tuple[tuple[int, float, bool, float | None], ...],
    plot: SceneRect,
    maximum: float,
) -> tuple[VolumeBarGlyph, ...]:
    slot_width = plot.width / max(1, viewport.visible_count)
    body_width = max(1.0, slot_width * 0.8)
    bars: list[VolumeBarGlyph] = []
    for global_index, value, bullish, _mean in visible:
        x = _x_for_index(viewport, plot, global_index)
        top = plot.bottom - (value / maximum) * plot.height
        bars.append(
            VolumeBarGlyph(
                global_index=global_index,
                x=x,
                top=top,
                bottom=plot.bottom,
                width=body_width,
                bullish=bullish,
                value=value,
            )
        )
    return tuple(bars)


def _mean_points(
    viewport: ViewportSnapshot,
    visible: tuple[tuple[int, float, bool, float | None], ...],
    plot: SceneRect,
    maximum: float,
) -> tuple[VolumeMeanPoint, ...]:
    points: list[VolumeMeanPoint] = []
    for global_index, _value, _bullish, mean in visible:
        if mean is None:
            continue
        resolved = float(mean)
        points.append(
            VolumeMeanPoint(
                global_index=global_index,
                x=_x_for_index(viewport, plot, global_index),
                y=plot.bottom - (resolved / maximum) * plot.height,
                value=resolved,
            )
        )
    return tuple(points)


def _last_volume_tag(
    visible: tuple[tuple[int, float, bool, float | None], ...],
    plot: SceneRect,
    maximum: float,
) -> LastVolumeTag | None:
    if not visible:
        return None
    _index, value, bullish, _mean = visible[-1]
    return LastVolumeTag(
        value=value,
        y=plot.bottom - (value / maximum) * plot.height,
        label=_format_volume(value),
        bullish=bullish,
    )


def _x_for_index(
    viewport: ViewportSnapshot,
    plot: SceneRect,
    global_index: int,
) -> float:
    relative = (
        global_index - viewport.start_index + 0.5
    ) / max(1, viewport.visible_count)
    return plot.x + relative * plot.width


def _format_volume(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"
