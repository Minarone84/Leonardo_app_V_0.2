from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolKind = Literal["indicator", "oscillator", "construct"]
ValueType = Literal["int", "float", "bool", "str"]
ToolOutputMode = Literal["overlay", "oscillator-pane", "non-visual"]
ToolOutputStructure = Literal[
    "line-series",
    "multi-line-series",
    "levels",
    "bands",
    "state",
    "events",
    "analysis-only",
]
OutputSignalType = Literal["signal", "utility"]
SignalValueType = Literal["numeric", "categorical", "boolean"]
OscillatorRangeMode = Literal["auto", "fixed_bounds"]
OscillatorGuideKind = Literal["overbought", "oversold", "center", "zero"]
StyleModule = Literal[
    "line_style",
    "per_signal_line_style",
    "fill_between_signals",
    "conditional_line_color",
    "conditional_fill_color",
    "directional_line_width",
]
EditModule = Literal["single_period", "dual_period", "period_plus_float", "dual_length", "generic"]
ConstructInputBinding = Literal["unary_source", "fast_slow", "fast_mid_slow", "multi_source"]
SourceFamily = Literal["ohlc", "indicator", "oscillator", "construct"]
SourceCompatibility = Literal["mixed_numeric", "same_family", "same_oscillator_type"]
OutputCardinality = Literal["single", "matches_inputs", "one_or_more"]
ConstructOutputRole = Literal["plotted_line", "state_series", "analysis_only"]


_TOOL_KINDS = {"indicator", "oscillator", "construct"}
_VALUE_TYPES = {"int", "float", "bool", "str"}
_OUTPUT_MODES = {"overlay", "oscillator-pane", "non-visual"}
_OUTPUT_STRUCTURES = {
    "line-series", "multi-line-series", "levels", "bands", "state", "events", "analysis-only"
}
_SIGNAL_TYPES = {"signal", "utility"}
_SIGNAL_VALUE_TYPES = {"numeric", "categorical", "boolean"}
_RANGE_MODES = {"auto", "fixed_bounds"}
_GUIDE_KINDS = {"overbought", "oversold", "center", "zero"}
_STYLE_MODULES = {
    "line_style", "per_signal_line_style", "fill_between_signals", "conditional_line_color",
    "conditional_fill_color", "directional_line_width",
}
_EDIT_MODULES = {"single_period", "dual_period", "period_plus_float", "dual_length", "generic"}
_INPUT_BINDINGS = {"unary_source", "fast_slow", "fast_mid_slow", "multi_source"}
_SOURCE_FAMILIES = {"ohlc", "indicator", "oscillator", "construct"}
_SOURCE_COMPATIBILITIES = {"mixed_numeric", "same_family", "same_oscillator_type"}
_OUTPUT_CARDINALITIES = {"single", "matches_inputs", "one_or_more"}
_CONSTRUCT_OUTPUT_ROLES = {"plotted_line", "state_series", "analysis_only"}


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_member(value: str, values: set[str], field_name: str) -> None:
    if value not in values:
        raise ValueError(f"{field_name} has unsupported value: {value!r}")


@dataclass(frozen=True, slots=True)
class DataInputSpec:
    name: str
    dtype: ValueType
    required: bool = True
    label: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        _require_text(self.name, "DataInputSpec.name")
        _require_member(self.dtype, _VALUE_TYPES, "DataInputSpec.dtype")


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    dtype: ValueType
    required: bool = True
    default: object = None
    label: str = ""
    description: str = ""
    min_value: int | float | None = None
    max_value: int | float | None = None
    choices: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, "ParameterSpec.name")
        _require_member(self.dtype, _VALUE_TYPES, "ParameterSpec.dtype")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(f"ParameterSpec {self.name!r} minimum exceeds maximum")
        if self.choices and self.default is not None and self.default not in self.choices:
            raise ValueError(f"ParameterSpec {self.name!r} default is not in choices")


@dataclass(frozen=True, slots=True)
class ToolBehaviorSpec:
    output_mode: ToolOutputMode
    chart_renderable: bool
    supports_style: bool
    supports_pane_layout: bool
    supports_last_value: bool
    supported_environments: tuple[str, ...] = ("historical",)
    default_environment: str = "historical"

    def __post_init__(self) -> None:
        _require_member(self.output_mode, _OUTPUT_MODES, "ToolBehaviorSpec.output_mode")
        if not self.supported_environments:
            raise ValueError("ToolBehaviorSpec.supported_environments must not be empty")
        if self.default_environment not in self.supported_environments:
            raise ValueError("ToolBehaviorSpec.default_environment must be supported")


@dataclass(frozen=True, slots=True)
class ToolStyleCapabilities:
    supported_modules: tuple[StyleModule, ...] = ()
    supports_condition_driven_style: bool = False
    supports_utility_style_drivers: bool = False
    supports_fill_between: bool = False
    supports_per_signal_styling: bool = False

    def __post_init__(self) -> None:
        if any(module not in _STYLE_MODULES for module in self.supported_modules):
            raise ValueError("ToolStyleCapabilities.supported_modules contains unsupported values")


@dataclass(frozen=True, slots=True)
class ToolEditCapabilities:
    preferred_module: EditModule = "generic"

    def __post_init__(self) -> None:
        _require_member(self.preferred_module, _EDIT_MODULES, "ToolEditCapabilities.preferred_module")


@dataclass(frozen=True, slots=True)
class OutputSignalSpec:
    name: str
    signal_type: OutputSignalType = "signal"
    renderable: bool = True
    analysis_usable: bool = True
    default_visible: bool = True
    label: str = ""
    description: str = ""
    semantic_role: str = "primary"
    value_type: SignalValueType = "numeric"
    can_drive_style_rules: bool = False

    def __post_init__(self) -> None:
        _require_text(self.name, "OutputSignalSpec.name")
        _require_member(self.signal_type, _SIGNAL_TYPES, "OutputSignalSpec.signal_type")
        _require_text(self.semantic_role, "OutputSignalSpec.semantic_role")
        _require_member(self.value_type, _SIGNAL_VALUE_TYPES, "OutputSignalSpec.value_type")


@dataclass(frozen=True, slots=True)
class ToolOutputSpec:
    structure: ToolOutputStructure
    output_names: tuple[str, ...] = ()
    signals: tuple[OutputSignalSpec, ...] = ()
    accepts_empty: bool = False

    def __post_init__(self) -> None:
        _require_member(self.structure, _OUTPUT_STRUCTURES, "ToolOutputSpec.structure")
        if len(self.output_names) != len(set(self.output_names)):
            raise ValueError("ToolOutputSpec.output_names must be unique")
        if len(tuple(signal.name for signal in self.signals)) != len({signal.name for signal in self.signals}):
            raise ValueError("ToolOutputSpec signal names must be unique")


@dataclass(frozen=True, slots=True)
class OscillatorGuideLevelSpec:
    kind: OscillatorGuideKind
    value: float
    visible: bool = True
    label: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        _require_member(self.kind, _GUIDE_KINDS, "OscillatorGuideLevelSpec.kind")


@dataclass(frozen=True, slots=True)
class OscillatorVisualSpec:
    range_mode: OscillatorRangeMode
    bounds: tuple[float, float] | None = None
    guide_levels: tuple[OscillatorGuideLevelSpec, ...] = ()

    def __post_init__(self) -> None:
        _require_member(self.range_mode, _RANGE_MODES, "OscillatorVisualSpec.range_mode")
        if self.range_mode == "fixed_bounds":
            if self.bounds is None or len(self.bounds) != 2 or self.bounds[0] >= self.bounds[1]:
                raise ValueError("fixed oscillator bounds must contain two ordered values")


@dataclass(frozen=True, slots=True)
class ConstructIOSpec:
    input_binding: ConstructInputBinding
    allowed_source_families: tuple[SourceFamily, ...]
    source_compatibility: SourceCompatibility
    output_cardinality: OutputCardinality
    output_role: ConstructOutputRole

    def __post_init__(self) -> None:
        _require_member(self.input_binding, _INPUT_BINDINGS, "ConstructIOSpec.input_binding")
        if not self.allowed_source_families or any(v not in _SOURCE_FAMILIES for v in self.allowed_source_families):
            raise ValueError("ConstructIOSpec.allowed_source_families contains unsupported values")
        _require_member(
            self.source_compatibility, _SOURCE_COMPATIBILITIES, "ConstructIOSpec.source_compatibility"
        )
        _require_member(self.output_cardinality, _OUTPUT_CARDINALITIES, "ConstructIOSpec.output_cardinality")
        _require_member(self.output_role, _CONSTRUCT_OUTPUT_ROLES, "ConstructIOSpec.output_role")


@dataclass(frozen=True, slots=True)
class FinancialToolSpec:
    key: str
    title: str
    kind: ToolKind
    data_inputs: tuple[DataInputSpec, ...]
    parameters: tuple[ParameterSpec, ...]
    output_names: tuple[str, ...]
    description: str
    behavior: ToolBehaviorSpec
    output: ToolOutputSpec
    form_variant: str = "default"
    style_capabilities: ToolStyleCapabilities = ToolStyleCapabilities()
    edit_capabilities: ToolEditCapabilities = ToolEditCapabilities()
    oscillator_visual: OscillatorVisualSpec | None = None
    construct_io: ConstructIOSpec | None = None

    def __post_init__(self) -> None:
        _require_text(self.key, "FinancialToolSpec.key")
        _require_text(self.title, "FinancialToolSpec.title")
        _require_member(self.kind, _TOOL_KINDS, "FinancialToolSpec.kind")
        _require_text(self.description, "FinancialToolSpec.description")
        _require_text(self.form_variant, "FinancialToolSpec.form_variant")
        for values, label in (
            (tuple(item.name for item in self.data_inputs), "data input names"),
            (tuple(item.name for item in self.parameters), "parameter names"),
            (self.output_names, "declared output names"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"FinancialToolSpec {self.key!r} {label} must be unique")
