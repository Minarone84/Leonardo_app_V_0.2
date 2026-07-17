"""Pure scene planning for resident price-pane Study projections."""

from __future__ import annotations

import math
from dataclasses import dataclass

from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.gui.chart.price_scale import PriceScaleSnapshot
from leonardo.research import ResidentStudyProjection, StudyPresentation
from leonardo.research.viewport import ViewportSnapshot


@dataclass(frozen=True, slots=True)
class PriceStudyBundle:
    projections: tuple[ResidentStudyProjection, ...] = ()
    presentations: tuple[StudyPresentation, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(item, ResidentStudyProjection) for item in self.projections):
            raise TypeError("projections must contain ResidentStudyProjection values")
        if not all(isinstance(item, StudyPresentation) for item in self.presentations):
            raise TypeError("presentations must contain StudyPresentation values")
        if tuple(item.study_id for item in self.projections) != tuple(
            item.study_id for item in self.presentations
        ):
            raise ValueError("projection and presentation order must match")

    def cache_identity(self) -> tuple[object, ...]:
        return tuple(
            (
                projection.study_id,
                projection.base_index,
                projection.end_index_exclusive,
                tuple((name, values) for name, values in projection.render_series.items()),
                tuple(
                    (name, values)
                    for name, values in projection.style_driver_series.items()
                ),
                presentation.revision,
                presentation.visible,
                presentation.pane_id,
            )
            for projection, presentation in zip(
                self.projections, self.presentations, strict=True
            )
        )


@dataclass(frozen=True, slots=True)
class StudyScenePoint:
    global_index: int
    x: float
    y: float
    value: float


@dataclass(frozen=True, slots=True)
class StudyLineStrip:
    study_id: str
    output_name: str
    color: str
    line_width: float
    line_pattern: str
    points: tuple[StudyScenePoint, ...]


@dataclass(frozen=True, slots=True)
class StudyMarkerGlyph:
    study_id: str
    output_name: str
    color: str
    marker_shape: str
    marker_size: int
    point: StudyScenePoint


@dataclass(frozen=True, slots=True)
class StudyFillPoint:
    global_index: int
    x: float
    upper_y: float
    lower_y: float
    upper_value: float
    lower_value: float


@dataclass(frozen=True, slots=True)
class StudyFillStrip:
    study_id: str
    fill_id: str
    color: str
    opacity: float
    points: tuple[StudyFillPoint, ...]


@dataclass(frozen=True, slots=True)
class StudyScene:
    line_strips: tuple[StudyLineStrip, ...]
    markers: tuple[StudyMarkerGlyph, ...]
    fills: tuple[StudyFillStrip, ...]
    autoscale_values: tuple[float, ...]
    cache_identity: tuple[object, ...]


def visible_price_study_values(
    bundle: PriceStudyBundle, viewport: ViewportSnapshot
) -> tuple[float, ...]:
    if not isinstance(bundle, PriceStudyBundle):
        raise TypeError("bundle must be a PriceStudyBundle")
    if not isinstance(viewport, ViewportSnapshot):
        raise TypeError("viewport must be a ViewportSnapshot")
    values: list[float] = []
    for projection, presentation in zip(
        bundle.projections, bundle.presentations, strict=True
    ):
        if not presentation.visible or presentation.pane_id != "price":
            continue
        collected_outputs: set[str] = set()
        for name, style in presentation.signal_styles.items():
            if style.visible:
                _collect_visible_series(
                    values, collected_outputs, projection, viewport, name
                )
        for fill in presentation.fill_styles.values():
            if not fill.visible:
                continue
            _collect_visible_series(
                values,
                collected_outputs,
                projection,
                viewport,
                fill.upper_output_name,
            )
            _collect_visible_series(
                values,
                collected_outputs,
                projection,
                viewport,
                fill.lower_output_name,
            )
    return tuple(values)


def _collect_visible_series(
    values: list[float],
    collected_outputs: set[str],
    projection: ResidentStudyProjection,
    viewport: ViewportSnapshot,
    output_name: str,
) -> None:
    if output_name in collected_outputs:
        return
    collected_outputs.add(output_name)
    series = projection.render_series[output_name]
    for global_index in _visible_indices(projection, viewport):
        value = series[global_index - projection.base_index]
        if _is_finite(value):
            values.append(float(value))


def build_study_scene(
    bundle: PriceStudyBundle,
    viewport: ViewportSnapshot,
    price_scale: PriceScaleSnapshot,
    plot_rect: SceneRect,
) -> StudyScene:
    if not isinstance(bundle, PriceStudyBundle):
        raise TypeError("bundle must be a PriceStudyBundle")
    if not isinstance(viewport, ViewportSnapshot):
        raise TypeError("viewport must be a ViewportSnapshot")
    if not isinstance(price_scale, PriceScaleSnapshot):
        raise TypeError("price_scale must be a PriceScaleSnapshot")
    if not isinstance(plot_rect, SceneRect):
        raise TypeError("plot_rect must be a SceneRect")

    lines: list[StudyLineStrip] = []
    markers: list[StudyMarkerGlyph] = []
    fills: list[StudyFillStrip] = []
    autoscale = visible_price_study_values(bundle, viewport)
    for projection, presentation in zip(
        bundle.projections, bundle.presentations, strict=True
    ):
        if not presentation.visible or presentation.pane_id != "price":
            continue
        indices = _visible_indices(projection, viewport)
        for fill in presentation.fill_styles.values():
            if fill.visible:
                fills.extend(
                    _fill_strips(projection, fill, indices, viewport, price_scale, plot_rect)
                )
        for output_name, style in presentation.signal_styles.items():
            if not style.visible:
                continue
            if style.render_mode == "marker":
                markers.extend(
                    _markers(projection, style, indices, viewport, price_scale, plot_rect)
                )
            else:
                lines.extend(
                    _line_strips(projection, style, indices, viewport, price_scale, plot_rect)
                )
    identity = (
        viewport.dataset_count,
        viewport.start_index,
        viewport.end_index_exclusive,
        viewport.visible_count,
        bundle.cache_identity(),
        price_scale.cache_identity(),
        plot_rect.x,
        plot_rect.y,
        plot_rect.width,
        plot_rect.height,
    )
    return StudyScene(tuple(lines), tuple(markers), tuple(fills), autoscale, identity)


def _visible_indices(
    projection: ResidentStudyProjection, viewport: ViewportSnapshot
) -> range:
    return range(
        max(projection.base_index, viewport.start_index, 0),
        min(
            projection.end_index_exclusive,
            viewport.end_index_exclusive,
            viewport.dataset_count,
        ),
    )


def _line_strips(projection, style, indices, viewport, scale, plot):
    values = projection.render_series[style.output_name]
    drivers = (
        None
        if style.conditional_driver_name is None
        else projection.style_driver_series[style.conditional_driver_name]
    )
    output: list[StudyLineStrip] = []
    current: list[StudyScenePoint] = []
    current_color: str | None = None
    for global_index in indices:
        local = global_index - projection.base_index
        value = values[local]
        if not _is_finite(value):
            _finish_line(output, projection.study_id, style, current_color, current)
            current, current_color = [], None
            continue
        state = None if drivers is None else drivers[local]
        color = style.conditional_colors.get(str(state), style.color)
        point = _point(global_index, float(value), viewport, scale, plot)
        if current and color != current_color:
            if len(current) > 1:
                _finish_line(output, projection.study_id, style, current_color, current)
            current = [current[-1]]
        current_color = color
        current.append(point)
    _finish_line(output, projection.study_id, style, current_color, current)
    return output


def _finish_line(output, study_id, style, color, points) -> None:
    if points:
        output.append(
            StudyLineStrip(
                study_id,
                style.output_name,
                color or style.color,
                style.line_width,
                style.line_pattern,
                tuple(points),
            )
        )


def _markers(projection, style, indices, viewport, scale, plot):
    values = projection.render_series[style.output_name]
    return [
        StudyMarkerGlyph(
            projection.study_id,
            style.output_name,
            style.color,
            style.marker_shape,
            style.marker_size,
            _point(global_index, float(values[global_index - projection.base_index]), viewport, scale, plot),
        )
        for global_index in indices
        if _is_finite(values[global_index - projection.base_index])
    ]


def _fill_strips(projection, style, indices, viewport, scale, plot):
    upper = projection.render_series[style.upper_output_name]
    lower = projection.render_series[style.lower_output_name]
    drivers = (
        None
        if style.conditional_driver_name is None
        else projection.style_driver_series[style.conditional_driver_name]
    )
    output: list[StudyFillStrip] = []
    current: list[StudyFillPoint] = []
    current_color: str | None = None
    for global_index in indices:
        local = global_index - projection.base_index
        high, low = upper[local], lower[local]
        if not _is_finite(high) or not _is_finite(low):
            _finish_fill(output, projection.study_id, style, current_color, current)
            current, current_color = [], None
            continue
        state = None if drivers is None else drivers[local]
        color = style.conditional_colors.get(str(state), style.color)
        x = _x(global_index, viewport, plot)
        point = StudyFillPoint(
            global_index,
            x,
            _y(float(high), scale, plot),
            _y(float(low), scale, plot),
            float(high),
            float(low),
        )
        if current and color != current_color:
            if len(current) > 1:
                _finish_fill(output, projection.study_id, style, current_color, current)
            current = [current[-1]]
        current_color = color
        current.append(point)
    _finish_fill(output, projection.study_id, style, current_color, current)
    return output


def _finish_fill(output, study_id, style, color, points) -> None:
    if points:
        output.append(
            StudyFillStrip(
                study_id,
                style.fill_id,
                color or style.color,
                style.opacity,
                tuple(points),
            )
        )


def _point(global_index, value, viewport, scale, plot) -> StudyScenePoint:
    return StudyScenePoint(
        global_index,
        _x(global_index, viewport, plot),
        _y(value, scale, plot),
        value,
    )


def _x(global_index: int, viewport: ViewportSnapshot, plot: SceneRect) -> float:
    relative = (global_index - viewport.start_index + 0.5) / viewport.visible_count
    return plot.x + relative * plot.width


def _y(value: float, scale: PriceScaleSnapshot, plot: SceneRect) -> float:
    low, high = scale.price_range.low, scale.price_range.high
    return plot.y + (high - value) / (high - low) * plot.height


def _is_finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))
