"""Pure scene planning for one resident oscillator Study projection."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from leonardo.financial_tools import get_financial_tool_spec
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.research import (
    ResidentOHLCVSlice,
    ResidentStudyProjection,
    StudyPresentation,
)
from leonardo.research.viewport import ViewportSnapshot


@dataclass(frozen=True, slots=True)
class OscillatorGuide:
    kind: str
    value: float
    y: float
    color: str
    line_width: float
    line_pattern: str


@dataclass(frozen=True, slots=True)
class OscillatorReferenceLevel:
    value: float
    y: float
    line_width: float


@dataclass(frozen=True, slots=True)
class OscillatorPoint:
    global_index: float
    x: float
    y: float
    value: float


@dataclass(frozen=True, slots=True)
class OscillatorLineStrip:
    output_name: str
    color: str
    line_width: float
    line_pattern: str
    points: tuple[OscillatorPoint, ...]


@dataclass(frozen=True, slots=True)
class OscillatorFillPoint:
    global_index: int
    x: float
    upper_y: float
    lower_y: float


@dataclass(frozen=True, slots=True)
class OscillatorFillStrip:
    fill_id: str
    color: str
    opacity: float
    points: tuple[OscillatorFillPoint, ...]


@dataclass(frozen=True, slots=True)
class OscillatorHistogramBar:
    global_index: int
    x: float
    top: float
    bottom: float
    width: float
    direction: str
    value: float


@dataclass(frozen=True, slots=True)
class OscillatorTimeTick:
    global_index: int
    timestamp_ms: int
    x: float
    label: str


@dataclass(frozen=True, slots=True)
class OscillatorScene:
    study_id: str
    pane_id: str
    plot_rect: SceneRect
    axis_low: float
    axis_high: float
    reference_levels: tuple[OscillatorReferenceLevel, ...]
    guides: tuple[OscillatorGuide, ...]
    fills: tuple[OscillatorFillStrip, ...]
    histogram_bars: tuple[OscillatorHistogramBar, ...]
    line_strips: tuple[OscillatorLineStrip, ...]
    time_ticks: tuple[OscillatorTimeTick, ...]
    center_message: str | None
    cache_identity: tuple[object, ...]


def build_oscillator_scene(
    projection: ResidentStudyProjection,
    presentation: StudyPresentation,
    viewport: ViewportSnapshot,
    plot_rect: SceneRect,
    resident: ResidentOHLCVSlice | None = None,
) -> OscillatorScene:
    if not isinstance(projection, ResidentStudyProjection):
        raise TypeError("projection must be a ResidentStudyProjection")
    if not isinstance(presentation, StudyPresentation):
        raise TypeError("presentation must be a StudyPresentation")
    if projection.study_id != presentation.study_id:
        raise ValueError("projection and presentation Study IDs differ")
    pane_id = f"oscillator:{projection.study_id}"
    if presentation.pane_id != pane_id:
        raise ValueError("presentation is not the matching oscillator pane")
    if not isinstance(viewport, ViewportSnapshot):
        raise TypeError("viewport must be a ViewportSnapshot")
    if not isinstance(plot_rect, SceneRect):
        raise TypeError("plot_rect must be a SceneRect")
    if resident is not None and not isinstance(resident, ResidentOHLCVSlice):
        raise TypeError("resident must be a ResidentOHLCVSlice or None")

    tool_key = presentation.tool_key
    if tool_key is None:
        tool_key = _tool_key_from_styles(projection, presentation)
    threshold_tool_key = presentation.tool_key
    visible_values = _visible_values(projection, presentation, viewport)
    spec = get_financial_tool_spec(tool_key)
    visual = spec.oscillator_visual
    visible_guides = tuple(
        guide
        for guide in presentation.guide_styles.values()
        if guide.visible
    )
    if tool_key == "braids":
        low, high = 0.5, 6.5
    elif tool_key == "volume":
        low, high = _volume_range(visible_values)
    elif visual is not None and visual.range_mode == "fixed_bounds":
        low, high = visual.bounds
    else:
        low, high = _auto_range(
            visible_values + tuple(guide.value for guide in visible_guides)
        )
    reference_levels = (
        tuple(
            OscillatorReferenceLevel(
                float(value),
                _y(float(value), low, high, plot_rect),
                0.5,
            )
            for value in range(1, 7)
        )
        if tool_key == "braids"
        else ()
    )
    guides = tuple(
        OscillatorGuide(
            item.kind,
            float(item.value),
            _y(float(item.value), low, high, plot_rect),
            item.color,
            item.line_width,
            item.line_pattern,
        )
        for item in sorted(
            visible_guides,
            key=lambda guide: guide.value,
        )
    )
    fills = _fill_strips(
        projection,
        presentation,
        viewport,
        plot_rect,
        low,
        high,
    )
    histogram_bars = _volume_histogram_bars(
        projection,
        presentation,
        viewport,
        plot_rect,
        low,
        high,
        resident,
    ) if tool_key == "volume" else ()
    strips: list[OscillatorLineStrip] = []
    if presentation.visible:
        for name, style in presentation.signal_styles.items():
            if tool_key == "volume" and name == "volume":
                continue
            if not style.visible or style.render_mode != "line":
                continue
            current: list[OscillatorPoint] = []
            values = projection.render_series[name]
            threshold_values = _threshold_values(
                threshold_tool_key,
                name,
                presentation,
            )
            for global_index in _visible_indices(projection, viewport):
                value = values[global_index - projection.base_index]
                if not _finite(value):
                    if current:
                        _append_line_run(
                            strips,
                            name,
                            style.color,
                            style.line_width,
                            style.line_pattern,
                            tuple(current),
                            threshold_values,
                        )
                        current = []
                    continue
                current.append(
                    OscillatorPoint(
                        global_index,
                        _x(global_index, viewport, plot_rect),
                        _y(float(value), low, high, plot_rect),
                        float(value),
                    )
                )
            if current:
                _append_line_run(
                    strips,
                    name,
                    style.color,
                    style.line_width,
                    style.line_pattern,
                    tuple(current),
                    threshold_values,
                )
    identity = (
        projection.study_id,
        projection.base_index,
        projection.end_index_exclusive,
        tuple((name, values) for name, values in projection.render_series.items()),
        presentation.revision,
        presentation.visible,
        viewport.start_index,
        viewport.end_index_exclusive,
        low,
        high,
        reference_levels,
        plot_rect,
        guides,
        fills,
        tuple(strips),
        _threshold_identity(threshold_tool_key, presentation),
        histogram_bars,
    )
    return OscillatorScene(
        projection.study_id,
        pane_id,
        plot_rect,
        low,
        high,
        reference_levels,
        guides,
        fills,
        histogram_bars,
        tuple(strips),
        _time_ticks(projection, viewport, plot_rect),
        None if visible_values else "No visible oscillator data",
        identity,
    )


def _threshold_values(
    tool_key: str | None,
    output_name: str,
    presentation: StudyPresentation,
) -> tuple[float, float] | None:
    if tool_key not in {"rsi", "arsi", "mfi"}:
        return None
    if tool_key == "arsi" and (
        not output_name.startswith("arsi_")
        or output_name.startswith("arsi_signal_")
    ):
        return None
    levels = {
        guide.kind: float(guide.value)
        for guide in presentation.guide_styles.values()
        if guide.kind in {"oversold", "overbought"}
    }
    if set(levels) != {"oversold", "overbought"}:
        return None
    return levels["oversold"], levels["overbought"]


def _threshold_identity(
    tool_key: str | None,
    presentation: StudyPresentation,
) -> tuple[object, ...]:
    if tool_key not in {"rsi", "arsi", "mfi"}:
        return ()
    return tuple(
        (guide.kind, float(guide.value), guide.visible)
        for guide in presentation.guide_styles.values()
        if guide.kind in {"oversold", "overbought"}
    )


def _append_line_run(
    strips: list[OscillatorLineStrip],
    output_name: str,
    base_color: str,
    line_width: float,
    line_pattern: str,
    points: tuple[OscillatorPoint, ...],
    thresholds: tuple[float, float] | None,
) -> None:
    if thresholds is None or len(points) < 2:
        strips.append(
            OscillatorLineStrip(
                output_name, base_color, line_width, line_pattern, points
            )
        )
        return
    lower, upper = thresholds
    for first, second in zip(points, points[1:]):
        segment_points = _split_threshold_segment(first, second, lower, upper)
        for start, end in zip(segment_points, segment_points[1:]):
            midpoint = (start.value + end.value) / 2.0
            color = (
                "#22C55E"
                if midpoint < lower
                else "#EF4444"
                if midpoint > upper
                else base_color
            )
            _append_or_merge_line_strip(
                strips,
                OscillatorLineStrip(
                    output_name,
                    color,
                    line_width,
                    line_pattern,
                    (start, end),
                ),
            )


def _split_threshold_segment(
    first: OscillatorPoint,
    second: OscillatorPoint,
    lower: float,
    upper: float,
) -> tuple[OscillatorPoint, ...]:
    if first.value == second.value:
        return first, second
    crossings: list[tuple[float, float]] = []
    minimum, maximum = sorted((first.value, second.value))
    for threshold in (lower, upper):
        if minimum < threshold < maximum:
            ratio = (threshold - first.value) / (second.value - first.value)
            crossings.append((ratio, threshold))
    points = [first]
    for ratio, threshold in sorted(crossings):
        points.append(
            OscillatorPoint(
                first.global_index
                + ratio * (second.global_index - first.global_index),
                first.x + ratio * (second.x - first.x),
                first.y + ratio * (second.y - first.y),
                threshold,
            )
        )
    points.append(second)
    return tuple(points)


def _append_or_merge_line_strip(
    strips: list[OscillatorLineStrip], candidate: OscillatorLineStrip
) -> None:
    if strips:
        previous = strips[-1]
        if (
            previous.output_name == candidate.output_name
            and previous.color == candidate.color
            and previous.line_width == candidate.line_width
            and previous.line_pattern == candidate.line_pattern
            and previous.points[-1] == candidate.points[0]
        ):
            strips[-1] = OscillatorLineStrip(
                previous.output_name,
                previous.color,
                previous.line_width,
                previous.line_pattern,
                previous.points + candidate.points[1:],
            )
            return
    strips.append(candidate)


def _fill_strips(
    projection: ResidentStudyProjection,
    presentation: StudyPresentation,
    viewport: ViewportSnapshot,
    plot_rect: SceneRect,
    low: float,
    high: float,
) -> tuple[OscillatorFillStrip, ...]:
    if not presentation.visible:
        return ()
    strips: list[OscillatorFillStrip] = []
    for fill in presentation.fill_styles.values():
        if not fill.visible:
            continue
        upper_values = projection.render_series.get(fill.upper_output_name)
        lower_values = projection.render_series.get(fill.lower_output_name)
        if upper_values is None or lower_values is None:
            continue
        current: list[OscillatorFillPoint] = []
        for global_index in _visible_indices(projection, viewport):
            offset = global_index - projection.base_index
            upper = upper_values[offset]
            lower = lower_values[offset]
            if not _finite(upper) or not _finite(lower):
                if len(current) >= 2:
                    strips.append(
                        OscillatorFillStrip(
                            fill.fill_id, fill.color, fill.opacity, tuple(current)
                        )
                    )
                current = []
                continue
            current.append(
                OscillatorFillPoint(
                    global_index,
                    _x(global_index, viewport, plot_rect),
                    _y(float(upper), low, high, plot_rect),
                    _y(float(lower), low, high, plot_rect),
                )
            )
        if len(current) >= 2:
            strips.append(
                OscillatorFillStrip(
                    fill.fill_id, fill.color, fill.opacity, tuple(current)
                )
            )
    return tuple(strips)


def _volume_histogram_bars(
    projection: ResidentStudyProjection,
    presentation: StudyPresentation,
    viewport: ViewportSnapshot,
    plot_rect: SceneRect,
    low: float,
    high: float,
    resident: ResidentOHLCVSlice | None,
) -> tuple[OscillatorHistogramBar, ...]:
    style = presentation.signal_styles.get("volume")
    if not presentation.visible or style is None or not style.visible:
        return ()
    values = projection.render_series["volume"]
    width = max(1.0, plot_rect.width / viewport.visible_count * 0.8)
    bottom = _y(0.0, low, high, plot_rect)
    output: list[OscillatorHistogramBar] = []
    for global_index in _visible_indices(projection, viewport):
        value = values[global_index - projection.base_index]
        if not _finite(value):
            continue
        output.append(
            OscillatorHistogramBar(
                global_index,
                _x(global_index, viewport, plot_rect),
                _y(float(value), low, high, plot_rect),
                bottom,
                width,
                _volume_direction(resident, global_index),
                float(value),
            )
        )
    return tuple(output)


def _volume_direction(
    resident: ResidentOHLCVSlice | None, global_index: int
) -> str:
    if resident is None or not resident.contains_global_index(global_index):
        return "neutral"
    local_index = global_index - resident.base_index
    open_value = resident.open[local_index]
    close_value = resident.close[local_index]
    if not _finite(open_value) or not _finite(close_value):
        return "neutral"
    return "bullish" if float(close_value) >= float(open_value) else "bearish"


def _tool_key_from_styles(
    projection: ResidentStudyProjection, presentation: StudyPresentation
) -> str:
    del projection
    output_names = tuple(presentation.signal_styles)
    first_output = output_names[0] if output_names else ""
    prefixes = (
        ("tdirsi_", "tdirsi"),
        ("arsi_", "arsi"),
        ("rsi_", "rsi"),
        ("smi_", "smi"),
        ("mfi_", "mfi"),
        ("obv", "obv"),
        ("volume", "volume"),
    )
    for prefix, tool_key in prefixes:
        if first_output.startswith(prefix):
            return tool_key
    if len(output_names) == 1 and re.fullmatch(r".+__d[1-9]\d*", first_output):
        return "derivative"
    if len(output_names) == 1 and re.fullmatch(r".+__ang", first_output):
        return "angle"
    if len(output_names) == 3:
        base = output_names[0]
        if output_names == (base, f"{base}_width", f"{base}_compression"):
            return "braids"
    if len(output_names) == 1 and re.fullmatch(r".+_inst_[1-9]\d*", first_output):
        return "braid_instability"
    if len(output_names) == 1 and re.fullmatch(r".+_delta", first_output):
        return "delta"
    if len(output_names) in (1, 3) and all(
        re.fullmatch(r".+_trapA", name) for name in output_names
    ):
        return "trap_area"
    if output_names and all(
        re.fullmatch(r".+_ang_pct_span_[1-9]\d*", name) for name in output_names
    ):
        return "percent_span_angle"
    if output_names and all(
        re.fullmatch(r".+_ang_mtm_[1-9]\d*", name) for name in output_names
    ):
        return "angle_momentum"
    raise ValueError("oscillator projection outputs do not match Task 1014")


def _visible_values(projection, presentation, viewport):
    if not presentation.visible:
        return ()
    output: list[float] = []
    for name, style in presentation.signal_styles.items():
        if not style.visible:
            continue
        values = projection.render_series[name]
        for index in _visible_indices(projection, viewport):
            value = values[index - projection.base_index]
            if _finite(value):
                output.append(float(value))
    return tuple(output)


def _auto_range(values: tuple[float, ...]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    low, high = min(values), max(values)
    if high == low:
        expansion = max(1.0, abs(high) * 0.01)
        return low - expansion, high + expansion
    padding = (high - low) * 0.05
    return low - padding, high + padding


def _volume_range(values: tuple[float, ...]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    high = max(values)
    if high <= 0.0:
        return 0.0, 1.0
    return 0.0, high * 1.05


def _visible_indices(projection, viewport):
    return range(
        max(projection.base_index, viewport.start_index, 0),
        min(projection.end_index_exclusive, viewport.end_index_exclusive, viewport.dataset_count),
    )


def _x(index, viewport, plot):
    return plot.x + (index - viewport.start_index + 0.5) / viewport.visible_count * plot.width


def _y(value, low, high, plot):
    return plot.y + (high - value) / (high - low) * plot.height


def _finite(value):
    return type(value) in (int, float) and math.isfinite(float(value))


def _time_ticks(projection, viewport, plot) -> tuple[OscillatorTimeTick, ...]:
    indices = tuple(_visible_indices(projection, viewport))
    if not indices:
        return ()
    count = max(2, min(12, int(plot.width // 100)))
    positions = tuple(
        min(len(indices) - 1, round(index * (len(indices) - 1) / (min(len(indices), count) - 1)))
        for index in range(min(len(indices), count))
    ) if len(indices) > 1 else (0,)
    timestamps = tuple(
        projection.ts_ms[index - projection.base_index] for index in indices
    )
    span = max(timestamps) - min(timestamps)
    output: list[OscillatorTimeTick] = []
    for position in positions:
        global_index = indices[position]
        timestamp = projection.ts_ms[global_index - projection.base_index]
        output.append(
            OscillatorTimeTick(
                global_index,
                timestamp,
                _x(global_index, viewport, plot),
                _format_timestamp(timestamp, span),
            )
        )
    return tuple(output)


def _format_timestamp(timestamp_ms: int, span_ms: int) -> str:
    moment = datetime.fromtimestamp(timestamp_ms / 1_000, tz=timezone.utc)
    if span_ms <= 2 * 24 * 60 * 60 * 1_000:
        return moment.strftime("%H:%M")
    if span_ms <= 90 * 24 * 60 * 60 * 1_000:
        return moment.strftime("%d %b")
    if span_ms <= 3 * 365 * 24 * 60 * 60 * 1_000:
        return moment.strftime("%b %Y")
    return moment.strftime("%Y")
