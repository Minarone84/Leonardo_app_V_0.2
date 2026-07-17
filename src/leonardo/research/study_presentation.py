"""Immutable chart-local Study presentation state and ownership."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from leonardo.financial_tools import get_financial_tool_spec, resolve_output_signals
from leonardo.research.studies import ChartStudy, StudyNotFoundError


_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$")
_LINE_PATTERNS = frozenset({"solid", "dashed", "dotted"})
_RENDER_MODES = frozenset({"line", "marker"})
_MARKER_SHAPES = frozenset(
    {"none", "circle", "square", "triangle_up", "triangle_down"}
)
_PALETTES = {
    "indicator": ("#F59E0B", "#60A5FA", "#22C55E", "#EF4444", "#06B6D4", "#A855F7"),
    "oscillator": ("#A855F7", "#22D3EE", "#F97316", "#84CC16", "#EC4899", "#60A5FA"),
    "construct": ("#06B6D4", "#E879F9", "#FACC15", "#4ADE80", "#FB7185", "#60A5FA"),
}
_STATE_COLORS = MappingProxyType(
    {"green": "#22C55E", "red": "#EF4444", "silver": "#94A3B8"}
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


@dataclass(frozen=True, slots=True)
class StudyPresentation:
    study_id: str
    visible: bool
    pane_id: str | None
    signal_styles: Mapping[str, StudyLineStyle]
    fill_styles: Mapping[str, StudyFillStyle]
    revision: int = 0

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
        object.__setattr__(self, "signal_styles", _style_mapping(self.signal_styles))
        object.__setattr__(self, "fill_styles", _fill_mapping(self.fill_styles))


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
        styles[slow] = _line_style(slow, "#60A5FA", visible=True)
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
        if {"hor_upper", "hor_lower"}.issubset(styles):
            fills["utc_range"] = StudyFillStyle(
                "utc_range", "hor_upper", "hor_lower", "#60A5FA", 0.10, True
            )

    presentation = StudyPresentation(
        study_id=study.study_id,
        visible=True,
        pane_id=_pane_id(study),
        signal_styles=styles,
        fill_styles=fills,
        revision=0,
    )
    _validate_for_study(study, presentation)
    return presentation


def _validate_for_study(study: ChartStudy, presentation: StudyPresentation) -> None:
    if presentation.study_id != study.study_id or presentation.pane_id != _pane_id(study):
        raise StudyPresentationValidationError("presentation identity does not match Study")
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


class StudyPresentationRegistry:
    """Own ordered mutable presentation state for one chart session."""

    def __init__(self) -> None:
        self._presentations: dict[str, StudyPresentation] = {}

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

    def reset(self, study: ChartStudy) -> StudyPresentation:
        current = self.get(study.study_id)
        default = build_default_study_presentation(study)
        if (
            current.visible == default.visible
            and current.pane_id == default.pane_id
            and current.signal_styles == default.signal_styles
            and current.fill_styles == default.fill_styles
        ):
            return current
        return self._replace(study, replace(default, revision=current.revision + 1))

    def remove(self, study_id: str) -> StudyPresentation:
        try:
            return self._presentations.pop(study_id)
        except KeyError as exc:
            raise StudyNotFoundError(f"Study presentation not found: {study_id}") from exc

    def clear(self) -> int:
        count = len(self._presentations)
        self._presentations.clear()
        return count

    def manager_entries(self, studies: Sequence[ChartStudy]) -> tuple[StudyManagerEntry, ...]:
        snapshot = tuple(studies)
        study_ids = {study.study_id for study in snapshot}
        if study_ids != set(self._presentations):
            raise StudyPresentationValidationError("Study and presentation registries differ")
        entries: list[StudyManagerEntry] = []
        for study in snapshot:
            presentation = self.get(study.study_id)
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
                )
            )
        return tuple(entries)

    def _replace(
        self, study: ChartStudy, presentation: StudyPresentation
    ) -> StudyPresentation:
        _validate_for_study(study, presentation)
        self._presentations[study.study_id] = presentation
        return presentation
