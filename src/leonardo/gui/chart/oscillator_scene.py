"""Pure scene planning for one resident oscillator Study projection."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from leonardo.financial_tools import get_financial_tool_spec
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.research import ResidentStudyProjection, StudyPresentation
from leonardo.research.viewport import ViewportSnapshot


@dataclass(frozen=True, slots=True)
class OscillatorGuide:
    kind: str
    value: float
    y: float


@dataclass(frozen=True, slots=True)
class OscillatorPoint:
    global_index: int
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
    guides: tuple[OscillatorGuide, ...]
    line_strips: tuple[OscillatorLineStrip, ...]
    time_ticks: tuple[OscillatorTimeTick, ...]
    center_message: str | None
    cache_identity: tuple[object, ...]


def build_oscillator_scene(
    projection: ResidentStudyProjection,
    presentation: StudyPresentation,
    viewport: ViewportSnapshot,
    plot_rect: SceneRect,
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

    visible_values = _visible_values(projection, presentation, viewport)
    spec = get_financial_tool_spec(_tool_key_from_styles(projection, presentation))
    visual = spec.oscillator_visual
    if visual is not None and visual.range_mode == "fixed_bounds":
        low, high = visual.bounds
    else:
        low, high = _auto_range(visible_values)
    guides = () if visual is None else tuple(
        OscillatorGuide(item.kind, float(item.value), _y(float(item.value), low, high, plot_rect))
        for item in sorted(
            (guide for guide in visual.guide_levels if guide.visible),
            key=lambda guide: guide.value,
        )
    )
    strips: list[OscillatorLineStrip] = []
    if presentation.visible:
        for name, style in presentation.signal_styles.items():
            if not style.visible or style.render_mode != "line":
                continue
            current: list[OscillatorPoint] = []
            values = projection.render_series[name]
            for global_index in _visible_indices(projection, viewport):
                value = values[global_index - projection.base_index]
                if not _finite(value):
                    if current:
                        strips.append(
                            OscillatorLineStrip(
                                name, style.color, style.line_width, style.line_pattern, tuple(current)
                            )
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
                strips.append(
                    OscillatorLineStrip(
                        name, style.color, style.line_width, style.line_pattern, tuple(current)
                    )
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
        plot_rect,
    )
    return OscillatorScene(
        projection.study_id,
        pane_id,
        plot_rect,
        low,
        high,
        guides,
        tuple(strips),
        _time_ticks(projection, viewport, plot_rect),
        None if visible_values else "No visible oscillator data",
        identity,
    )


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
