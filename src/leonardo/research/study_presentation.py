"""Immutable chart-local Study presentation state and ownership."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from leonardo.financial_tools import get_financial_tool_spec, resolve_output_signals
from leonardo.research.studies import ChartStudy, StudyInputSource, StudyNotFoundError


_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$")
_LINE_PATTERNS = frozenset({"solid", "dashed", "dotted"})
_RENDER_MODES = frozenset({"line", "marker"})
_GUIDE_KINDS = frozenset({"overbought", "oversold", "center", "zero"})
_GUIDE_DETAIL_ORDER = ("oversold", "center", "overbought", "zero")
_MARKER_SHAPES = frozenset(
    {"none", "circle", "square", "triangle_up", "triangle_down"}
)
_PALETTES = {
    "indicator": ("#F59E0B", "#60A5FA", "#22C55E", "#EF4444", "#06B6D4", "#A855F7"),
    "oscillator": ("#A855F7", "#22D3EE", "#F97316", "#84CC16", "#EC4899", "#60A5FA"),
    "construct": ("#06B6D4", "#E879F9", "#FACC15", "#4ADE80", "#FB7185", "#60A5FA"),
}
_STATE_COLORS = MappingProxyType(
    {"green": "#22C55E", "red": "#EF4444", "silver": "#22C55E"}
)


class StudyPresentationValidationError(ValueError):
    """Raised when chart-local presentation state is not canonical."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StudyPresentationValidationError(f"{name} must be canonical non-empty text")
    return value


def _color(value: object, name: str) -> str:
    text = _text(value, name)
    if _COLOR_RE.fullmatch(text) is None:
        raise StudyPresentationValidationError(f"{name} must be uppercase #RRGGBB")
    return text


def _finite(value: object, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise StudyPresentationValidationError(f"{name} must be finite")
    resolved = float(value)
    if not low <= resolved <= high:
        raise StudyPresentationValidationError(f"{name} must be in [{low}, {high}]")
    return resolved


def _conditional_colors(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise StudyPresentationValidationError("conditional_colors must be a mapping")
    copied: dict[str, str] = {}
    for key, color in sorted(value.items()):
        copied[_text(key, "conditional color key")] = _color(
            color, "conditional color value"
        )
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class StudyLineStyle:
    output_name: str
    color: str
    line_width: float = 1.0
    line_pattern: str = "solid"
    visible: bool = True
    render_mode: str = "line"
    marker_shape: str = "none"
    marker_size: int = 8
    conditional_driver_name: str | None = None
    conditional_colors: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_name", _text(self.output_name, "output_name"))
        object.__setattr__(self, "color", _color(self.color, "color"))
        object.__setattr__(
            self, "line_width", _finite(self.line_width, "line_width", 0.5, 5.0)
        )
        if self.line_pattern not in _LINE_PATTERNS:
            raise StudyPresentationValidationError("unsupported line_pattern")
        if type(self.visible) is not bool:
            raise StudyPresentationValidationError("visible must be a boolean")
        if self.render_mode not in _RENDER_MODES:
            raise StudyPresentationValidationError("unsupported render_mode")
        if self.marker_shape not in _MARKER_SHAPES:
            raise StudyPresentationValidationError("unsupported marker_shape")
        if type(self.marker_size) is not int or not 4 <= self.marker_size <= 24:
            raise StudyPresentationValidationError("marker_size must be from 4 through 24")
        if self.render_mode == "line" and self.marker_shape != "none":
            raise StudyPresentationValidationError("line mode requires marker_shape none")
        if self.render_mode == "marker" and self.marker_shape == "none":
            raise StudyPresentationValidationError("marker mode requires a marker shape")
        driver = self.conditional_driver_name
        if driver is not None:
            driver = _text(driver, "conditional_driver_name")
        colors = _conditional_colors(self.conditional_colors)
        if driver is None and colors:
            raise StudyPresentationValidationError(
                "conditional colors require conditional_driver_name"
            )
        object.__setattr__(self, "conditional_driver_name", driver)
        object.__setattr__(self, "conditional_colors", colors)


@dataclass(frozen=True, slots=True)
class StudyFillStyle:
    fill_id: str
    upper_output_name: str
    lower_output_name: str
    color: str
    opacity: float = 0.12
    visible: bool = True
    conditional_driver_name: str | None = None
    conditional_colors: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "fill_id", _text(self.fill_id, "fill_id"))
        upper = _text(self.upper_output_name, "upper_output_name")
        lower = _text(self.lower_output_name, "lower_output_name")
        if upper == lower:
            raise StudyPresentationValidationError("fill output names must differ")
        object.__setattr__(self, "upper_output_name", upper)
        object.__setattr__(self, "lower_output_name", lower)
        object.__setattr__(self, "color", _color(self.color, "color"))
        object.__setattr__(self, "opacity", _finite(self.opacity, "opacity", 0.0, 1.0))
        if type(self.visible) is not bool:
            raise StudyPresentationValidationError("visible must be a boolean")
        driver = self.conditional_driver_name
        if driver is not None:
            driver = _text(driver, "conditional_driver_name")
        colors = _conditional_colors(self.conditional_colors)
        if driver is None and colors:
            raise StudyPresentationValidationError(
                "conditional colors require conditional_driver_name"
            )
        object.__setattr__(self, "conditional_driver_name", driver)
        object.__setattr__(self, "conditional_colors", colors)


@dataclass(frozen=True, slots=True)
class StudyBackgroundRegionStyle:
    region_id: str
    driver_output_name: str
    color: str
    opacity: float = 0.08
    visible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _text(self.region_id, "region_id"))
        object.__setattr__(
            self,
            "driver_output_name",
            _text(self.driver_output_name, "driver_output_name"),
        )
        object.__setattr__(self, "color", _color(self.color, "color"))
        object.__setattr__(self, "opacity", _finite(self.opacity, "opacity", 0.0, 1.0))
        if type(self.visible) is not bool:
            raise StudyPresentationValidationError("visible must be a boolean")


@dataclass(frozen=True, slots=True)
class StudyGuideStyle:
    guide_id: str
    kind: str
    value: float
    color: str
    line_width: float
    line_pattern: str
    visible: bool = True

    def __post_init__(self) -> None:
        guide_id = _text(self.guide_id, "guide_id")
        kind = _text(self.kind, "kind")
        if kind not in _GUIDE_KINDS:
            raise StudyPresentationValidationError("unsupported guide kind")
        if guide_id != kind:
            raise StudyPresentationValidationError(
                "guide_id must match its semantic kind"
            )
        object.__setattr__(self, "guide_id", guide_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "value",
            _finite(self.value, "guide value", -1e12, 1e12),
        )
        object.__setattr__(self, "color", _color(self.color, "guide color"))
        object.__setattr__(
            self,
            "line_width",
            _finite(self.line_width, "guide line_width", 0.5, 5.0),
        )
        if self.line_pattern not in _LINE_PATTERNS:
            raise StudyPresentationValidationError(
                "unsupported guide line_pattern"
            )
        if type(self.visible) is not bool:
            raise StudyPresentationValidationError(
                "guide visible must be a boolean"
            )


def _style_mapping(value: object) -> Mapping[str, StudyLineStyle]:
    if not isinstance(value, Mapping):
        raise StudyPresentationValidationError("signal_styles must be a mapping")
    copied: dict[str, StudyLineStyle] = {}
    for key, style in value.items():
        if not isinstance(style, StudyLineStyle) or key != style.output_name:
            raise StudyPresentationValidationError("signal style key must match output_name")
        copied[key] = style
    return MappingProxyType(copied)


def _fill_mapping(value: object) -> Mapping[str, StudyFillStyle]:
    if not isinstance(value, Mapping):
        raise StudyPresentationValidationError("fill_styles must be a mapping")
    copied: dict[str, StudyFillStyle] = {}
    for key, style in value.items():
        if not isinstance(style, StudyFillStyle) or key != style.fill_id:
            raise StudyPresentationValidationError("fill style key must match fill_id")
        copied[key] = style
    return MappingProxyType(copied)


def _background_region_mapping(
    value: object,
) -> Mapping[str, StudyBackgroundRegionStyle]:
    if not isinstance(value, Mapping):
        raise StudyPresentationValidationError(
            "background_region_styles must be a mapping"
        )
    copied: dict[str, StudyBackgroundRegionStyle] = {}
    for key, style in value.items():
        if (
            not isinstance(style, StudyBackgroundRegionStyle)
            or key != style.region_id
        ):
            raise StudyPresentationValidationError(
                "background region style key must match region_id"
            )
        copied[key] = style
    return MappingProxyType(copied)


def _guide_mapping(value: object) -> Mapping[str, StudyGuideStyle]:
    if not isinstance(value, Mapping):
        raise StudyPresentationValidationError("guide_styles must be a mapping")
    copied: dict[str, StudyGuideStyle] = {}
    kinds: set[str] = set()
    for key, style in value.items():
        if not isinstance(style, StudyGuideStyle) or key != style.guide_id:
            raise StudyPresentationValidationError(
                "guide style key must match guide_id"
            )
        if key in copied:
            raise StudyPresentationValidationError(
                "guide style IDs must be unique"
            )
        if style.kind in kinds:
            raise StudyPresentationValidationError(
                "guide semantic kinds must be unique"
            )
        copied[key] = style
        kinds.add(style.kind)
    return MappingProxyType(copied)


def _validate_presentation_guides(
    tool_key: str | None,
    guides: Mapping[str, StudyGuideStyle],
) -> None:
    if tool_key is None:
        if guides:
            raise StudyPresentationValidationError(
                "guide styles require a canonical tool key"
            )
        return
    visual = get_financial_tool_spec(tool_key).oscillator_visual
    expected_guides = (
        ()
        if visual is None
        else tuple(guide.kind for guide in visual.guide_levels)
    )
    if tuple(guides) != expected_guides:
        raise StudyPresentationValidationError(
            "presentation guide styles must exactly match canonical guide identities"
        )
    if visual is not None and visual.range_mode == "fixed_bounds":
        values = {guide.kind: guide.value for guide in guides.values()}
        if set(values) != {"overbought", "center", "oversold"}:
            raise StudyPresentationValidationError(
                "fixed-bound oscillator guides are incomplete"
            )
        if any(not 0.0 <= value <= 100.0 for value in values.values()):
            raise StudyPresentationValidationError(
                "fixed-bound oscillator guides must be in [0, 100]"
            )
        if not values["oversold"] < values["center"] < values["overbought"]:
            raise StudyPresentationValidationError(
                "fixed-bound oscillator guides must be ordered"
            )


@dataclass(frozen=True, slots=True)
class StudyPresentation:
    study_id: str
    visible: bool
    pane_id: str | None
    signal_styles: Mapping[str, StudyLineStyle]
    fill_styles: Mapping[str, StudyFillStyle]
    revision: int = 0
    tool_key: str | None = None
    background_region_styles: Mapping[str, StudyBackgroundRegionStyle] = field(
        default_factory=lambda: MappingProxyType({})
    )
    guide_styles: Mapping[str, StudyGuideStyle] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "study_id", _text(self.study_id, "study_id"))
        if type(self.visible) is not bool:
            raise StudyPresentationValidationError("visible must be a boolean")
        if self.pane_id is not None:
            pane = _text(self.pane_id, "pane_id")
            if pane != "price" and not pane.startswith("oscillator:"):
                raise StudyPresentationValidationError("unsupported pane_id")
        if type(self.revision) is not int or self.revision < 0:
            raise StudyPresentationValidationError("revision must be non-negative")
        if self.tool_key is not None:
            object.__setattr__(
                self,
                "tool_key",
                get_financial_tool_spec(self.tool_key).key,
            )
        object.__setattr__(self, "signal_styles", _style_mapping(self.signal_styles))
        object.__setattr__(self, "fill_styles", _fill_mapping(self.fill_styles))
        object.__setattr__(
            self,
            "background_region_styles",
            _background_region_mapping(self.background_region_styles),
        )
        guide_value = self.guide_styles
        if guide_value is None:
            visual = (
                None
                if self.tool_key is None
                else get_financial_tool_spec(self.tool_key).oscillator_visual
            )
            guide_value = (
                {}
                if visual is None
                else {
                    guide.kind: _guide_style(
                        guide.kind,
                        float(guide.value),
                        visible=guide.visible,
                    )
                    for guide in visual.guide_levels
                }
            )
        guides = _guide_mapping(guide_value)
        _validate_presentation_guides(self.tool_key, guides)
        object.__setattr__(self, "guide_styles", guides)


@dataclass(frozen=True, slots=True)
class StudyManagerEntry:
    study_id: str
    display_name: str
    tool_key: str
    tool_title: str
    source_kind: str
    saved: bool
    visible: bool
    pane_id: str | None
    pane_label: str
    dependent_study_ids: tuple[str, ...]
    compact_label: str
    parameter_summary: str
    parameter_details: str
    source_summary: str
    source_details: str
    origin_label: str


_NUMBERED_TOOL_PREFIXES = MappingProxyType(
    {
        "universal_trend_classifier": "UTC",
        "peaks_troughs": "P&T",
        "strategy": "Strategy",
    }
)
_SOURCE_ROLE_LABELS = MappingProxyType(
    {
        "source": "SRC",
        "fast": "F",
        "mid": "M",
        "slow": "S",
        "trend_peak": "TP",
        "trend_trough": "TT",
        "range_peak": "RP",
        "range_trough": "RT",
    }
)
_EXCLUDED_PARAMETERS = MappingProxyType(
    {
        "braids": frozenset({"fast", "mid", "slow"}),
        "braid_instability": frozenset({"fast", "mid", "slow"}),
        "delta": frozenset({"fast", "slow"}),
        "trap_area": frozenset({"fast", "mid", "slow"}),
        "percent_span_angle": frozenset({"source_columns"}),
        "angle_momentum": frozenset({"source_columns"}),
        "universal_trend_classifier": frozenset(
            {"fractal_window", "peak_column", "trough_column"}
        ),
    }
)


def _format_scalar(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, str):
        return value
    return str(value)


def _source_role_label(role: str) -> str:
    if role in _SOURCE_ROLE_LABELS:
        return _SOURCE_ROLE_LABELS[role]
    match = re.fullmatch(r"source_(\d+)", role)
    return f"SRC{match.group(1)}" if match is not None else role.upper()


def _source_token(source: StudyInputSource) -> str:
    value = (
        source.column_name
        if source.source_kind == "ohlcv"
        else source.output_name
    )
    return "—" if value is None else value.upper()


def _compact_study_label(
    tool_key: str,
    parameters: Mapping[str, object],
    sources: Sequence[StudyInputSource],
    ordinal: int | None = None,
) -> str:
    value = lambda name: _format_scalar(parameters[name])
    if tool_key in _NUMBERED_TOOL_PREFIXES:
        if ordinal is None:
            raise StudyPresentationValidationError(
                f"{tool_key} requires a chart-session ordinal"
            )
        return f"{_NUMBERED_TOOL_PREFIXES[tool_key]}{ordinal}"
    simple = {
        "sma": ("SMA", ("period",)),
        "ema": ("EMA", ("period",)),
        "tema": ("TEMA", ("period",)),
        "hma": ("HMA", ("period",)),
        "kama": ("KAMA", ("fast_period", "slow_period")),
        "bb": ("BB", ("period", "std")),
        "hck": ("HCK", ("fast_vwap_l", "slow_vwap_l")),
        "rsi": ("RSI", ("period",)),
        "arsi": (
            "ARSI",
            ("period", "method", "signal_period", "signal_method"),
        ),
        "tdirsi": (
            "TDI",
            (
                "period",
                "band_length",
                "band_mult",
                "fast_len",
                "slow_len",
                "fast_smo",
                "slow_smo",
            ),
        ),
        "smi": ("SMI", ("k_length", "d_length")),
        "mfi": ("MFI", ("period",)),
        "obv": ("OBV", ()),
        "volume": ("Volume", ("period",)),
    }
    if tool_key in simple:
        prefix, names = simple[tool_key]
        suffix = " ".join(value(name) for name in names)
        return prefix if not suffix else f"{prefix} {suffix}"

    by_role = {source.role: source for source in sources}
    token = lambda role: _source_token(by_role[role])
    if tool_key == "derivative":
        return f"Derivative SRC:{token('source')} O:{value('order')}"
    if tool_key == "angle":
        return f"Angle SRC:{token('source')} U:{value('unit')}"
    if tool_key == "braids":
        return (
            f"Braids F:{token('fast')}, M:{token('mid')}, S:{token('slow')}"
        )
    if tool_key == "braid_instability":
        return (
            f"Braid Instability F:{token('fast')}, M:{token('mid')}, "
            f"S:{token('slow')}, N:{value('n')}"
        )
    if tool_key == "delta":
        return (
            f"Delta F:{token('fast')}, S:{token('slow')}, M:{value('mode')}"
        )
    if tool_key == "trap_area":
        mid = token("mid") if "mid" in by_role else "—"
        return f"Trap Area F:{token('fast')}, M:{mid}, S:{token('slow')}"
    source_tokens = "/".join(_source_token(source) for source in sources)
    if tool_key == "percent_span_angle":
        return (
            f"PS Angle SRC:{source_tokens} W:{value('window')} "
            f"U:{value('unit')}"
        )
    if tool_key == "angle_momentum":
        return f"Angle Momentum SRC:{source_tokens} N:{value('n')}"
    raise StudyPresentationValidationError(
        f"unsupported Research compact-label tool: {tool_key}"
    )


def _parameter_text(
    study: ChartStudy,
    presentation: StudyPresentation,
) -> tuple[str, str]:
    spec = get_financial_tool_spec(study.result.tool_key)
    parameters = study.result.parameters
    excluded = _EXCLUDED_PARAMETERS.get(spec.key, frozenset())
    known_names = {parameter.name for parameter in spec.parameters}
    ordered = [
        (parameter.name, parameter.label or parameter.name)
        for parameter in spec.parameters
        if parameter.name in parameters and parameter.name not in excluded
    ]
    ordered.extend(
        (name, name)
        for name in sorted(parameters)
        if name not in known_names and name not in excluded
    )
    summary = "; ".join(
        f"{name}={_format_scalar(parameters[name])}" for name, _label in ordered
    )
    details = [
        f"{label}: {_format_scalar(parameters[name])}" for name, label in ordered
    ]
    ordered_guide_kinds = [
        kind
        for kind in _GUIDE_DETAIL_ORDER
        if kind in presentation.guide_styles
    ]
    ordered_guide_kinds.extend(
        sorted(
            kind
            for kind in presentation.guide_styles
            if kind not in _GUIDE_DETAIL_ORDER
        )
    )
    guides = tuple(
        presentation.guide_styles[kind] for kind in ordered_guide_kinds
    )
    if guides:
        details.append("Guide levels:")
        details.extend(
            f"{guide.kind.replace('_', ' ').title()}: "
            f"{_format_scalar(guide.value)}"
            for guide in guides
        )
    return summary or "—", (
        "\n".join(details) if details else "No user-facing parameters."
    )


def _source_text(study: ChartStudy) -> tuple[str, str]:
    sources = study.edit_request.input_sources
    if sources:
        summary = ", ".join(
            f"{_source_role_label(source.role)}:{_source_token(source)}"
            for source in sources
        )
        details: list[str] = []
        for source in sources:
            role = _source_role_label(source.role)
            if source.source_kind == "ohlcv":
                details.append(f"{role}: OHLCV column {source.column_name}")
            elif source.source_kind == "study":
                details.append(
                    f"{role}: Study {source.study_id}, output {source.output_name}"
                )
            else:
                details.append(
                    f"{role}: Saved Artifact {source.artifact_tool_key}, "
                    f"ID {source.artifact_id[:12]}, output {source.output_name}"
                )
        return summary, "\n".join(details)
    inputs = tuple(
        item.name for item in get_financial_tool_spec(study.result.tool_key).data_inputs
    )
    if not inputs:
        return "—", "No source bindings."
    return (
        f"OHLCV: {', '.join(name.upper() for name in inputs)}",
        f"OHLCV inputs: {', '.join(inputs)}",
    )


def _pane_id(study: ChartStudy) -> str | None:
    if study.pane_role == "price":
        return "price"
    if study.pane_role == "oscillator":
        return f"oscillator:{study.study_id}"
    return None


def _line_style(
    output_name: str,
    color: str,
    *,
    visible: bool,
    line_pattern: str = "solid",
    render_mode: str = "line",
    marker_shape: str = "none",
    conditional_driver_name: str | None = None,
    conditional_colors: Mapping[str, str] = MappingProxyType({}),
) -> StudyLineStyle:
    return StudyLineStyle(
        output_name=output_name,
        color=color,
        line_pattern=line_pattern,
        visible=visible,
        render_mode=render_mode,
        marker_shape=marker_shape,
        conditional_driver_name=conditional_driver_name,
        conditional_colors=conditional_colors,
    )


def _guide_style(kind: str, value: float, *, visible: bool) -> StudyGuideStyle:
    if kind == "overbought":
        color = "#EF4444"
    elif kind == "oversold":
        color = "#22C55E"
    else:
        color = "#94A3B8"
    return StudyGuideStyle(
        guide_id=kind,
        kind=kind,
        value=value,
        color=color,
        line_width=1.0,
        line_pattern="dashed",
        visible=visible,
    )


def build_default_study_presentation(study: ChartStudy) -> StudyPresentation:
    """Build deterministic chart-local defaults from Task 1014 truth."""

    if not isinstance(study, ChartStudy):
        raise StudyPresentationValidationError("study must be a ChartStudy")
    spec = get_financial_tool_spec(study.result.tool_key)
    resolved = resolve_output_signals(
        study.result.tool_key,
        {**dict(study.result.parameters), **dict(study.result.bindings)},
    )
    signal_by_name = {signal.name: signal for signal in resolved}
    palette = _PALETTES[study.result.kind]
    styles: dict[str, StudyLineStyle] = {}
    for index, output_name in enumerate(study.renderable_output_names):
        signal = signal_by_name[output_name]
        styles[output_name] = _line_style(
            output_name,
            palette[index % len(palette)],
            visible=signal.default_visible,
        )

    fills: dict[str, StudyFillStyle] = {}
    background_regions: dict[str, StudyBackgroundRegionStyle] = {}
    guides = (
        {}
        if spec.oscillator_visual is None
        else {
            guide.kind: _guide_style(
                guide.kind,
                float(guide.value),
                visible=guide.visible,
            )
            for guide in spec.oscillator_visual.guide_levels
        }
    )
    if spec.key == "bb":
        styles["bb_middle"] = _line_style("bb_middle", "#F59E0B", visible=True)
        for name in ("bb_upper_band", "bb_lower_band"):
            styles[name] = _line_style(
                name, "#60A5FA", visible=True, line_pattern="dashed"
            )
        fills["bb_band"] = StudyFillStyle(
            "bb_band", "bb_upper_band", "bb_lower_band", "#60A5FA", 0.12, True
        )
    elif spec.key in {"hck", "strategy"}:
        prefix = "" if spec.key == "hck" else "st_"
        fast = f"{prefix}fast_vwap"
        slow = f"{prefix}slow_vwap"
        driver = f"{prefix}vwap_color"
        styles[fast] = _line_style(
            fast,
            "#22C55E",
            visible=True,
            conditional_driver_name=driver,
            conditional_colors=_STATE_COLORS,
        )
        styles[slow] = _line_style(
            slow,
            "#22C55E",
            visible=True,
            conditional_driver_name=driver,
            conditional_colors=_STATE_COLORS,
        )
        fills[f"{prefix}hck_band"] = StudyFillStyle(
            f"{prefix}hck_band",
            fast,
            slow,
            "#22C55E",
            0.08,
            True,
            conditional_driver_name=driver,
            conditional_colors=_STATE_COLORS,
        )
    elif spec.key == "peaks_troughs":
        for output_name in study.renderable_output_names:
            peak = output_name.startswith("peak_")
            styles[output_name] = _line_style(
                output_name,
                "#22C55E" if peak else "#EF4444",
                visible=signal_by_name[output_name].default_visible,
                render_mode="marker",
                marker_shape="triangle_down" if peak else "triangle_up",
            )
    elif spec.key == "rsi":
        output_name = study.renderable_output_names[0]
        styles[output_name] = _line_style(
            output_name, "#A855F7", visible=styles[output_name].visible
        )
    elif spec.key == "arsi":
        for output_name in study.renderable_output_names:
            styles[output_name] = _line_style(
                output_name,
                "#FF5D00" if output_name.startswith("arsi_signal_") else "#8B5CF6",
                visible=styles[output_name].visible,
            )
    elif spec.key == "mfi":
        output_name = study.renderable_output_names[0]
        styles[output_name] = _line_style(
            output_name, "#14B8A6", visible=styles[output_name].visible
        )
    elif spec.key == "tdirsi":
        for output_name in study.renderable_output_names:
            if output_name.startswith("tdirsi_fast_ma_"):
                color, pattern = "#22C55E", "solid"
            elif output_name.startswith("tdirsi_slow_ma_"):
                color, pattern = "#EF4444", "solid"
            elif output_name.startswith(("tdirsi_up_", "tdirsi_dn_")):
                color, pattern = "#60A5FA", "dashed"
            else:
                color, pattern = "#F59E0B", "solid"
            styles[output_name] = _line_style(
                output_name,
                color,
                visible=styles[output_name].visible,
                line_pattern=pattern,
            )
        upper = next(
            name for name in study.renderable_output_names
            if name.startswith("tdirsi_up_")
        )
        lower = next(
            name for name in study.renderable_output_names
            if name.startswith("tdirsi_dn_")
        )
        fills["tdirsi_band"] = StudyFillStyle(
            "tdirsi_band", upper, lower, "#60A5FA", 0.10, True
        )
    elif spec.key == "smi":
        for output_name in study.renderable_output_names:
            styles[output_name] = _line_style(
                output_name,
                "#F59E0B" if output_name.startswith("smi_signal_") else "#06B6D4",
                visible=styles[output_name].visible,
            )
    elif spec.key == "universal_trend_classifier":
        for output_name in study.renderable_output_names:
            if output_name.endswith("_marker"):
                styles[output_name] = _line_style(
                    output_name,
                    styles[output_name].color,
                    visible=signal_by_name[output_name].default_visible,
                    render_mode="marker",
                    marker_shape="circle",
                )
        background_regions = {
            "utc_uptrend": StudyBackgroundRegionStyle(
                "utc_uptrend", "uptrend", "#22C55E"
            ),
            "utc_downtrend": StudyBackgroundRegionStyle(
                "utc_downtrend", "downtrend", "#EF4444"
            ),
        }

    presentation = StudyPresentation(
        study_id=study.study_id,
        visible=True,
        pane_id=_pane_id(study),
        signal_styles=styles,
        fill_styles=fills,
        revision=0,
        tool_key=study.result.tool_key,
        background_region_styles=background_regions,
        guide_styles=guides,
    )
    _validate_for_study(study, presentation)
    return presentation


def _validate_for_study(study: ChartStudy, presentation: StudyPresentation) -> None:
    if presentation.study_id != study.study_id or presentation.pane_id != _pane_id(study):
        raise StudyPresentationValidationError("presentation identity does not match Study")
    if presentation.tool_key != study.result.tool_key:
        raise StudyPresentationValidationError(
            "presentation tool key does not match Study result tool key"
        )
    if tuple(presentation.signal_styles) != study.renderable_output_names:
        raise StudyPresentationValidationError(
            "presentation signal styles must exactly match renderable outputs"
        )
    drivers = set(study.style_driver_output_names)
    outputs = set(study.renderable_output_names)
    for style in presentation.signal_styles.values():
        if style.conditional_driver_name is not None and style.conditional_driver_name not in drivers:
            raise StudyPresentationValidationError("unknown conditional line driver")
    for fill in presentation.fill_styles.values():
        if fill.upper_output_name not in outputs or fill.lower_output_name not in outputs:
            raise StudyPresentationValidationError("fill outputs must be renderable")
        if fill.conditional_driver_name is not None and fill.conditional_driver_name not in drivers:
            raise StudyPresentationValidationError("unknown conditional fill driver")
    for region in presentation.background_region_styles.values():
        if region.driver_output_name not in drivers:
            raise StudyPresentationValidationError("unknown background region driver")


def _reconcile_study_presentation(
    current_study: ChartStudy,
    replacement_study: ChartStudy,
    current: StudyPresentation,
) -> StudyPresentation:
    if (
        current_study.study_id != replacement_study.study_id
        or current_study.result.tool_key != replacement_study.result.tool_key
    ):
        raise StudyPresentationValidationError(
            "edited Study presentation identity must remain unchanged"
        )
    default = build_default_study_presentation(replacement_study)
    old_outputs = current_study.renderable_output_names
    new_outputs = replacement_study.renderable_output_names
    old_drivers = current_study.style_driver_output_names
    new_drivers = replacement_study.style_driver_output_names

    def remap_driver(driver: str | None) -> str | None:
        if driver is None:
            return None
        try:
            index = old_drivers.index(driver)
        except ValueError:
            return None
        return new_drivers[index] if index < len(new_drivers) else None

    styles = dict(default.signal_styles)
    for index, output_name in enumerate(new_outputs):
        if index >= len(old_outputs):
            continue
        old_style = current.signal_styles[old_outputs[index]]
        driver = remap_driver(old_style.conditional_driver_name)
        styles[output_name] = replace(
            old_style,
            output_name=output_name,
            conditional_driver_name=driver,
            conditional_colors=(
                old_style.conditional_colors
                if driver is not None
                else MappingProxyType({})
            ),
        )

    fills = dict(default.fill_styles)
    for fill_id, new_fill in default.fill_styles.items():
        old_fill = current.fill_styles.get(fill_id)
        if old_fill is None:
            continue
        driver = remap_driver(old_fill.conditional_driver_name)
        fills[fill_id] = replace(
            new_fill,
            color=old_fill.color,
            opacity=old_fill.opacity,
            visible=old_fill.visible,
            conditional_driver_name=driver,
            conditional_colors=(
                old_fill.conditional_colors
                if driver is not None
                else MappingProxyType({})
            ),
        )

    regions = dict(default.background_region_styles)
    for region_id, new_region in default.background_region_styles.items():
        old_region = current.background_region_styles.get(region_id)
        if old_region is not None:
            regions[region_id] = replace(
                new_region,
                color=old_region.color,
                opacity=old_region.opacity,
                visible=old_region.visible,
            )

    if tuple(current.guide_styles) != tuple(default.guide_styles):
        raise StudyPresentationValidationError(
            "edited Study guide identity sequence changed"
        )

    reconciled = replace(
        default,
        visible=current.visible,
        pane_id=current.pane_id,
        signal_styles=styles,
        fill_styles=fills,
        revision=current.revision,
        background_region_styles=regions,
        guide_styles=current.guide_styles,
    )
    _validate_for_study(replacement_study, reconciled)
    return reconciled


class StudyPresentationRegistry:
    """Own ordered mutable presentation state for one chart session."""

    def __init__(self) -> None:
        self._presentations: dict[str, StudyPresentation] = {}
        self._study_ordinals: dict[str, int] = {}
        self._next_ordinals: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._presentations)

    def snapshot(self) -> tuple[StudyPresentation, ...]:
        return tuple(self._presentations.values())

    def get(self, study_id: str) -> StudyPresentation:
        try:
            return self._presentations[study_id]
        except KeyError as exc:
            raise StudyNotFoundError(f"Study presentation not found: {study_id}") from exc

    def register(self, study: ChartStudy) -> StudyPresentation:
        if study.study_id in self._presentations:
            raise StudyPresentationValidationError("duplicate Study presentation ID")
        presentation = build_default_study_presentation(study)
        self._presentations[study.study_id] = presentation
        if study.result.tool_key in _NUMBERED_TOOL_PREFIXES:
            ordinal = self._next_ordinals.get(study.result.tool_key, 1)
            self._study_ordinals[study.study_id] = ordinal
            self._next_ordinals[study.result.tool_key] = ordinal + 1
        return presentation

    def set_visibility(self, study: ChartStudy, visible: bool) -> StudyPresentation:
        if type(visible) is not bool:
            raise StudyPresentationValidationError("visible must be a boolean")
        current = self.get(study.study_id)
        if current.visible == visible:
            return current
        return self._replace(study, replace(current, visible=visible, revision=current.revision + 1))

    def replace_line_style(
        self, study: ChartStudy, output_name: str, style: StudyLineStyle
    ) -> StudyPresentation:
        current = self.get(study.study_id)
        if output_name not in current.signal_styles or style.output_name != output_name:
            raise StudyPresentationValidationError("line style output does not match Study")
        if current.signal_styles[output_name] == style:
            return current
        styles = dict(current.signal_styles)
        styles[output_name] = style
        return self._replace(
            study,
            replace(current, signal_styles=styles, revision=current.revision + 1),
        )

    def replace_fill_style(
        self, study: ChartStudy, fill_id: str, style: StudyFillStyle
    ) -> StudyPresentation:
        current = self.get(study.study_id)
        if fill_id not in current.fill_styles or style.fill_id != fill_id:
            raise StudyPresentationValidationError("fill style ID does not match Study")
        if current.fill_styles[fill_id] == style:
            return current
        fills = dict(current.fill_styles)
        fills[fill_id] = style
        return self._replace(
            study,
            replace(current, fill_styles=fills, revision=current.revision + 1),
        )

    def replace_guide_styles(
        self,
        study: ChartStudy,
        styles: Sequence[StudyGuideStyle],
    ) -> StudyPresentation:
        current = self.get(study.study_id)
        snapshot = tuple(styles)
        if tuple(style.guide_id for style in snapshot) != tuple(
            current.guide_styles
        ):
            raise StudyPresentationValidationError(
                "guide style identities do not match Study"
            )
        replacement = {style.guide_id: style for style in snapshot}
        if current.guide_styles == replacement:
            return current
        return self._replace(
            study,
            replace(
                current,
                guide_styles=replacement,
                revision=current.revision + 1,
            ),
        )

    def reset(self, study: ChartStudy) -> StudyPresentation:
        current = self.get(study.study_id)
        default = build_default_study_presentation(study)
        if (
            current.visible == default.visible
            and current.pane_id == default.pane_id
            and current.signal_styles == default.signal_styles
            and current.fill_styles == default.fill_styles
            and current.background_region_styles == default.background_region_styles
            and current.guide_styles == default.guide_styles
        ):
            return current
        return self._replace(study, replace(default, revision=current.revision + 1))

    def reconcile_for_edit(
        self,
        current_study: ChartStudy,
        replacement_study: ChartStudy,
    ) -> StudyPresentation:
        current = self.get(current_study.study_id)
        return _reconcile_study_presentation(
            current_study, replacement_study, current
        )

    def replace_for_edit(
        self,
        replacement_study: ChartStudy,
        presentation: StudyPresentation,
    ) -> StudyPresentation:
        self.get(replacement_study.study_id)
        _validate_for_study(replacement_study, presentation)
        self._presentations[replacement_study.study_id] = presentation
        return presentation

    def remove(self, study_id: str) -> StudyPresentation:
        try:
            presentation = self._presentations.pop(study_id)
            self._study_ordinals.pop(study_id, None)
            return presentation
        except KeyError as exc:
            raise StudyNotFoundError(f"Study presentation not found: {study_id}") from exc

    def clear(self) -> int:
        count = len(self._presentations)
        self._presentations.clear()
        self._study_ordinals.clear()
        self._next_ordinals.clear()
        return count

    def manager_entries(self, studies: Sequence[ChartStudy]) -> tuple[StudyManagerEntry, ...]:
        snapshot = tuple(studies)
        study_ids = {study.study_id for study in snapshot}
        if study_ids != set(self._presentations):
            raise StudyPresentationValidationError("Study and presentation registries differ")
        entries: list[StudyManagerEntry] = []
        for study in snapshot:
            presentation = self.get(study.study_id)
            if study.result.tool_key == "dynamic_binning":
                continue
            compact_label = _compact_study_label(
                study.result.tool_key,
                study.result.parameters,
                study.edit_request.input_sources,
                self._study_ordinals.get(study.study_id),
            )
            parameter_summary, parameter_details = _parameter_text(
                study, presentation
            )
            source_summary, source_details = _source_text(study)
            dependents = tuple(
                candidate.study_id
                for candidate in snapshot
                if any(ref.study_id == study.study_id for ref in candidate.source_studies)
            )
            entries.append(
                StudyManagerEntry(
                    study_id=study.study_id,
                    display_name=study.display_name,
                    tool_key=study.result.tool_key,
                    tool_title=get_financial_tool_spec(study.result.tool_key).title,
                    source_kind=study.source_kind,
                    saved=study.saved_link is not None,
                    visible=presentation.visible,
                    pane_id=presentation.pane_id,
                    pane_label=(
                        "Price"
                        if presentation.pane_id == "price"
                        else "Oscillator"
                        if presentation.pane_id is not None
                        else "Non-visual"
                    ),
                    dependent_study_ids=dependents,
                    compact_label=compact_label,
                    parameter_summary=parameter_summary,
                    parameter_details=parameter_details,
                    source_summary=source_summary,
                    source_details=source_details,
                    origin_label=(
                        "Calculated"
                        if study.source_kind == "calculation"
                        else "Saved Artifact"
                    ),
                )
            )
        return tuple(entries)

    def _replace(
        self, study: ChartStudy, presentation: StudyPresentation
    ) -> StudyPresentation:
        _validate_for_study(study, presentation)
        self._presentations[study.study_id] = presentation
        return presentation
