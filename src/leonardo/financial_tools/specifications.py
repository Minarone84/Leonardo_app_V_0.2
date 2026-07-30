from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .models import (
    ConstructIOSpec,
    DataInputSpec,
    FinancialToolSpec,
    OscillatorGuideLevelSpec,
    OscillatorVisualSpec,
    OutputSignalSpec,
    ParameterSpec,
    ToolBehaviorSpec,
    ToolEditCapabilities,
    ToolKind,
    ToolOutputSpec,
    ToolStyleCapabilities,
)
from .naming import CANONICAL_TOOL_ALIASES, canonicalize_tool_key, resolve_output_names


def _input(name: str, label: str) -> DataInputSpec:
    descriptions = {
        "open": "Open price series.",
        "high": "High price series.",
        "low": "Low price series.",
        "close": "Close price series.",
        "volume": "Volume series. Compute layer may resolve 'Volume' or 'volume'.",
    }
    return DataInputSpec(name, "float", label=label, description=descriptions[name])


_CLOSE = (_input("close", "Close"),)
_HLCV = (_input("high", "High"), _input("low", "Low"), _input("close", "Close"), _input("volume", "Volume"))
_OHLC = (_input("open", "Open"), _input("high", "High"), _input("low", "Low"), _input("close", "Close"))
_HLC = (_input("high", "High"), _input("low", "Low"), _input("close", "Close"))


def _param(
    name: str,
    dtype: str,
    default: object,
    label: str,
    description: str,
    *,
    required: bool = True,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    choices: tuple[object, ...] = (),
) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        dtype=dtype,
        required=required,
        default=default,
        label=label,
        description=description,
        min_value=minimum,
        max_value=maximum,
        choices=choices,
    )


def _signal(name: str, **values: object) -> OutputSignalSpec:
    return OutputSignalSpec(name=name, **values)


_OVERLAY = ToolBehaviorSpec("overlay", True, True, False, True)
_OSCILLATOR = ToolBehaviorSpec("oscillator-pane", True, True, True, True)
_NON_VISUAL = ToolBehaviorSpec("non-visual", False, False, False, False)

_LINE_STYLE = ToolStyleCapabilities(
    ("line_style", "conditional_line_color", "directional_line_width"),
    supports_condition_driven_style=True,
)
_MULTI_STYLE = ToolStyleCapabilities(
    (
        "line_style", "per_signal_line_style", "fill_between_signals",
        "conditional_line_color", "conditional_fill_color", "directional_line_width",
    ),
    supports_condition_driven_style=True,
    supports_fill_between=True,
    supports_per_signal_styling=True,
)
_UTILITY_MULTI_STYLE = ToolStyleCapabilities(
    _MULTI_STYLE.supported_modules,
    supports_condition_driven_style=True,
    supports_utility_style_drivers=True,
    supports_fill_between=True,
    supports_per_signal_styling=True,
)
_PER_SIGNAL_STYLE = ToolStyleCapabilities(("per_signal_line_style",), supports_per_signal_styling=True)
_NO_STYLE = ToolStyleCapabilities()


def _outputs(names: tuple[str, ...], structure: str, *, accepts_empty: bool = False,
             signals: tuple[OutputSignalSpec, ...] | None = None) -> ToolOutputSpec:
    return ToolOutputSpec(
        structure=structure,
        output_names=names,
        signals=tuple(_signal(name) for name in names) if signals is None else signals,
        accepts_empty=accepts_empty,
    )


def _spec(
    key: str,
    title: str,
    kind: str,
    description: str,
    data_inputs: tuple[DataInputSpec, ...],
    parameters: tuple[ParameterSpec, ...],
    output_names: tuple[str, ...],
    behavior: ToolBehaviorSpec,
    structure: str,
    *,
    form_variant: str = "default",
    style: ToolStyleCapabilities = _NO_STYLE,
    edit: str = "generic",
    signals: tuple[OutputSignalSpec, ...] | None = None,
    accepts_empty: bool = False,
    oscillator_visual: OscillatorVisualSpec | None = None,
    construct_io: ConstructIOSpec | None = None,
) -> FinancialToolSpec:
    return FinancialToolSpec(
        key=key,
        title=title,
        kind=kind,
        data_inputs=data_inputs,
        parameters=parameters,
        output_names=output_names,
        description=description,
        behavior=behavior,
        output=_outputs(output_names, structure, accepts_empty=accepts_empty, signals=signals),
        form_variant=form_variant,
        style_capabilities=style,
        edit_capabilities=ToolEditCapabilities(edit),
        oscillator_visual=oscillator_visual,
        construct_io=construct_io,
    )


def _period(default: int = 14, label: str = "Period") -> tuple[ParameterSpec, ...]:
    description = (
        "Rolling mean period for the Volume average line."
        if label == "Mean Period"
        else "Primary lookback period."
    )
    return (_param("period", "int", default, label, description, minimum=1),)


_indicator_specs = {
    "sma": _spec("sma", "SMA", "indicator", "Simple Moving Average.", _CLOSE, _period(),
                 ("sma_{period}",), _OVERLAY, "line-series", style=_LINE_STYLE, edit="single_period"),
    "ema": _spec("ema", "EMA", "indicator", "Exponential Moving Average.", _CLOSE, _period(),
                 ("ema_{period}",), _OVERLAY, "line-series", style=_LINE_STYLE, edit="single_period"),
    "tema": _spec("tema", "TEMA", "indicator", "Triple Exponential Moving Average.", _CLOSE, _period(),
                  ("tema_{period}",), _OVERLAY, "line-series", style=_LINE_STYLE, edit="single_period"),
    "hma": _spec("hma", "HMA", "indicator", "Hull Moving Average.", _CLOSE, _period(),
                 ("hma_{period}",), _OVERLAY, "line-series", style=_LINE_STYLE, edit="single_period"),
    "kama": _spec(
        "kama", "KAMA", "indicator", "Kaufman's Adaptive Moving Average.", _CLOSE,
        (_param("fast_period", "int", 2, "Fast Period", "Fast smoothing/adaptation period.", minimum=1),
         _param("slow_period", "int", 30, "Slow Period", "Slow smoothing/adaptation period.", minimum=1)),
        ("kama_{fast_period}_{slow_period}",), _OVERLAY, "line-series", style=_LINE_STYLE, edit="dual_period",
    ),
    "bb": _spec(
        "bb", "Bollinger Bands", "indicator", "Bollinger Bands on close.", _CLOSE,
        (_param("period", "int", 14, "Period", "Primary lookback period.", minimum=1),
         _param("std", "float", 2.0, "Std Dev Multiplier", "Standard deviation multiplier.", minimum=1e-6)),
        ("bb_middle", "bb_upper_band", "bb_lower_band"), _OVERLAY, "multi-line-series",
        style=_MULTI_STYLE, edit="period_plus_float",
    ),
    "hck": _spec(
        "hck", "Hancock", "indicator", "Fast/slow EW-VWAP pair with directional color state.", _HLCV,
        (_param("fast_vwap_l", "int", 13, "Fast VWAP Length", "Fast EW-VWAP length.", minimum=1),
         _param("slow_vwap_l", "int", 48, "Slow VWAP Length", "Slow EW-VWAP length.", minimum=1)),
        ("fast_vwap", "slow_vwap", "vwap_color"), _OVERLAY, "multi-line-series",
        style=_UTILITY_MULTI_STYLE, edit="dual_length",
    ),
    "strategy": _spec(
        "strategy", "Strategy", "indicator",
        "Composite price-overlay indicator bundling six EMAs, six SMAs, Bollinger Bands, and a Hancock pair.",
        _HLCV,
        tuple(
            [_param(f"ema_{slot}_period", "int", value, f"EMA {slot} Period",
                    f"Lookback period for Strategy EMA slot {slot}.", minimum=1)
             for slot, value in enumerate((9, 20, 50, 100, 200, 400), 1)]
            + [_param(f"sma_{slot}_period", "int", value, f"SMA {slot} Period",
                      f"Lookback period for Strategy SMA slot {slot}.", minimum=1)
               for slot, value in enumerate((9, 20, 50, 100, 200, 400), 1)]
            + [_param("bb_period", "int", 20, "BB Period",
                      "Bollinger Bands lookback period inside Strategy.", minimum=1),
               _param("bb_std", "float", 2.0, "BB Std Dev Multiplier",
                      "Bollinger Bands standard deviation multiplier inside Strategy.", minimum=1e-6),
               _param("hck_fast_vwap_l", "int", 13, "HCK Fast VWAP Length",
                      "Fast EW-VWAP length for the Strategy Hancock pair.", minimum=1),
               _param("hck_slow_vwap_l", "int", 48, "HCK Slow VWAP Length",
                      "Slow EW-VWAP length for the Strategy Hancock pair.", minimum=1)]
        ),
        tuple([*(f"st_ema_{i}" for i in range(1, 7)), *(f"st_sma_{i}" for i in range(1, 7)),
               "st_bb_middle", "st_bb_upper_band", "st_bb_lower_band",
               "st_fast_vwap", "st_slow_vwap", "st_vwap_color"]),
        _OVERLAY, "multi-line-series", style=_UTILITY_MULTI_STYLE,
    ),
    "peaks_troughs": _spec(
        "peaks_troughs", "Peaks & Troughs", "indicator",
        "Confirmed fractal peak/trough detector across the fixed 3, 5, 7, 9, and 11-bar windows.",
        (_input("high", "High"), _input("low", "Low")), (),
        tuple(name for length in (3, 5, 7, 9, 11)
              for name in (f"peak_fractal_{length}", f"trough_fractal_{length}")),
        _OVERLAY, "events", style=_PER_SIGNAL_STYLE, signals=(),
    ),
    "universal_trend_classifier": None,
}


_UTC_NAMES = (
    "horizontal_range", "hr_start", "hr_end", "hor_upper", "hor_lower", "uptrend",
    "uptrend_start", "uptrend_end", "downtrend", "downtrend_start", "downtrend_end", "hr_uptrend",
    "hr_downtrend", "hr_start_marker", "hr_end_marker", "uptrend_start_marker", "uptrend_end_marker",
    "downtrend_start_marker", "downtrend_end_marker", "hr_breakout_attempt", "hr_pending_breakout",
    "hr_breakout_confirmed", "hr_false_breakout", "hr_reclaim", "hr_break_direction",
    "hr_break_extreme", "hr_reclaim_marker",
)
_UTC_DETAILS = (
    ("utility", False, False, "Horizontal Range", "True while a horizontal range is active.", "horizontal_range", "boolean"),
    ("utility", False, False, "HR Start", "Sparse boolean horizontal-range start event.", "hr_start", "boolean"),
    ("utility", False, False, "HR End", "Sparse boolean horizontal-range end event.", "hr_end", "boolean"),
    ("signal", True, True, "HR Upper", "Upper horizontal-range band.", "range_upper", "numeric"),
    ("signal", True, True, "HR Lower", "Lower horizontal-range band.", "range_lower", "numeric"),
    ("utility", False, False, "Uptrend", "True while an uptrend interval is active.", "uptrend", "boolean"),
    ("utility", False, False, "Uptrend Start", "Sparse boolean uptrend start event.", "uptrend_start", "boolean"),
    ("utility", False, False, "Uptrend End", "Sparse boolean uptrend end event.", "uptrend_end", "boolean"),
    ("utility", False, False, "Downtrend", "True while a downtrend interval is active.", "downtrend", "boolean"),
    ("utility", False, False, "Downtrend Start", "Sparse boolean downtrend start event.", "downtrend_start", "boolean"),
    ("utility", False, False, "Downtrend End", "Sparse boolean downtrend end event.", "downtrend_end", "boolean"),
    ("utility", False, False, "HR + Uptrend", "Composite horizontal-range/uptrend flag.", "hr_uptrend", "boolean"),
    ("utility", False, False, "HR + Downtrend", "Composite horizontal-range/downtrend flag.", "hr_downtrend", "boolean"),
    ("signal", True, True, "HR Start Marker", "Sparse price marker at horizontal-range start.", "range_start_marker", "numeric"),
    ("signal", True, True, "HR End Marker", "Sparse price marker at horizontal-range end.", "range_end_marker", "numeric"),
    ("signal", True, True, "Uptrend Start Marker", "Sparse price marker at uptrend start.", "uptrend_start_marker", "numeric"),
    ("signal", True, True, "Uptrend End Marker", "Sparse price marker at uptrend end.", "uptrend_end_marker", "numeric"),
    ("signal", True, True, "Downtrend Start Marker", "Sparse price marker at downtrend start.", "downtrend_start_marker", "numeric"),
    ("signal", True, True, "Downtrend End Marker", "Sparse price marker at downtrend end.", "downtrend_end_marker", "numeric"),
    ("utility", False, False, "HR Breakout Attempt", "Sparse boolean event when an active horizontal range is first broken.", "hr_breakout_attempt", "boolean"),
    ("utility", False, False, "HR Pending Breakout", "True while UTC is waiting for reclaim or breakout confirmation.", "hr_pending_breakout", "boolean"),
    ("utility", False, False, "HR Breakout Confirmed", "Sparse boolean event when a pending breakout survives the reclaim window.", "hr_breakout_confirmed", "boolean"),
    ("utility", False, False, "HR False Breakout", "Sparse boolean event when a pending breakout reclaims the same range in time.", "hr_false_breakout", "boolean"),
    ("utility", False, False, "HR Reclaim", "Sparse boolean event when price/source re-enters the pending range.", "hr_reclaim", "boolean"),
    ("utility", False, False, "HR Break Direction", "Breakout direction: 1 upside, -1 downside, 0 ambiguous.", "hr_break_direction", "numeric"),
    ("utility", False, False, "HR Break Extreme", "Breakout high/low extreme tracked during the pending breakout lifecycle.", "hr_break_extreme", "numeric"),
    ("utility", False, False, "HR Reclaim Marker", "Sparse source-price marker at the reclaim bar.", "hr_reclaim_marker", "numeric"),
)
_UTC_SIGNALS = tuple(
    _signal(name, signal_type=kind, renderable=renderable, analysis_usable=True,
            default_visible=visible, label=label, description=description,
            semantic_role=role, value_type=value_type, can_drive_style_rules=True)
    for name, (kind, renderable, visible, label, description, role, value_type)
    in zip(_UTC_NAMES, _UTC_DETAILS, strict=True)
)
_indicator_specs["universal_trend_classifier"] = _spec(
    "universal_trend_classifier", "Universal Trend Classifier", "indicator",
    "Price-pane market-structure classifier emitting range bands, sparse start/end markers, and non-renderable boolean state outputs.",
    _OHLC,
    (
        _param("source", "str", "close", "Source",
               "OHLC source column used by the Universal Trend Classifier.", choices=("open", "high", "low", "close")),
        _param("fractal_window", "int", 5, "Fractal Window", "Compatibility alias for trend_fractal_window.",
               minimum=3, choices=(3, 5, 7, 9, 11)),
        _param("trend_fractal_window", "int", 5, "Up/Down Trend Fractal",
               "Peaks & Troughs fractal length consumed by UTC directional trend detection.",
               minimum=3, choices=(3, 5, 7, 9, 11)),
        _param("peak_column", "str", None, "Peak Column",
               "Legacy trend peak column override. Leave empty to use peak_fractal_{trend_fractal_window}.", required=False),
        _param("trough_column", "str", None, "Trough Column",
               "Legacy trend trough column override. Leave empty to use trough_fractal_{trend_fractal_window}.", required=False),
        _param("min_hr_band_perc", "float", 0.005, "Min HR Band %",
               "Minimum horizontal-range band size as a fraction of source price.", minimum=0.0),
        _param("hr_trend_length", "int", 20, "HR Trend Length",
               "Lookback window used to evaluate horizontal-range/trend structure.", minimum=3),
        _param("hr_trend_atr_mult", "float", 1.0, "HR ATR Mult",
               "ATR multiplier used for horizontal-range band tolerance.", minimum=0.0),
        _param("hr_trend_atr_len", "int", 500, "HR ATR Length",
               "Rolling ATR averaging length used by the classifier.", minimum=1),
        _param("hr_trend_tol_mult", "float", 0.3, "HR Trend Tolerance Mult",
               "ATR multiplier reserved for incremental/realtime trend-extension tolerance; historical directional trend detection remains strict.",
               minimum=0.0),
        _param("hr_trend_max_gap", "int", 20, "HR Trend Max Gap",
               "Maximum allowed gap between qualifying swings for horizontal-range continuity.", minimum=1),
        _param("hr_min_inside_ratio", "float", 0.8, "HR Min Inside Ratio",
               "Minimum ratio of bars inside the candidate horizontal-range band.", minimum=1e-6, maximum=1.0),
        _param("min_range_swings", "int", 4, "Min Range Swings",
               "Minimum alternating swings required to confirm a horizontal range.", minimum=4),
        _param("range_fractal_window", "int", 3, "Horizontal Range Fractal",
               "Peaks & Troughs fractal length consumed by UTC horizontal range discovery.",
               minimum=3, choices=(3, 5, 7, 9, 11)),
        _param("hr_break_mode", "str", "close", "Range Break Mode",
               "Horizontal-range invalidation mode after a range is active.", choices=("close", "wick", "hybrid")),
    ),
    _UTC_NAMES, _OVERLAY, "multi-line-series", style=_PER_SIGNAL_STYLE, signals=_UTC_SIGNALS,
)
INDICATOR_SPECS = MappingProxyType(_indicator_specs)


def _guide(kind: str, value: float, label: str, description: str) -> OscillatorGuideLevelSpec:
    return OscillatorGuideLevelSpec(kind, value, label=label, description=description)


_BOUNDED_GUIDES = (
    _guide("overbought", 70.0, "Overbought", "Default overbought guide level for bounded RSI-like oscillators."),
    _guide("center", 50.0, "Center", "Default center guide level for bounded RSI-like oscillators."),
    _guide("oversold", 30.0, "Oversold", "Default oversold guide level for bounded RSI-like oscillators."),
)
_ARSI_GUIDES = (
    _guide("overbought", 80.0, "Overbought", "Default overbought guide level for ARSI."),
    _guide("center", 50.0, "Center", "Default center guide level for ARSI."),
    _guide("oversold", 20.0, "Oversold", "Default oversold guide level for ARSI."),
)
_BOUNDED = OscillatorVisualSpec("fixed_bounds", (0.0, 100.0), _BOUNDED_GUIDES)
_ARSI_VISUAL = OscillatorVisualSpec("fixed_bounds", (0.0, 100.0), _ARSI_GUIDES)
_AUTO = OscillatorVisualSpec("auto")
_ZERO = OscillatorVisualSpec("auto", guide_levels=(
    _guide("zero", 0.0, "Zero", "Default zero guide level for centered oscillators."),
))


_oscillator_specs = {
    "rsi": _spec("rsi", "RSI", "oscillator", "Wilder RSI.", _CLOSE, _period(), ("rsi_{period}",),
                 _OSCILLATOR, "line-series", oscillator_visual=_BOUNDED),
    "arsi": _spec(
        "arsi", "ARSI", "oscillator", "Ultimate RSI-style ARSI with configurable main and signal smoothing.",
        _CLOSE,
        (_param("period", "int", 14, "Period", "Primary lookback period.", minimum=1),
         _param("method", "str", "RMA", "Method",
                "Smoothing method used for the primary ARSI numerator and denominator.", choices=("EMA", "SMA", "RMA", "TMA")),
         _param("signal_period", "int", 14, "Signal Period",
                "Moving-average period for the ARSI signal line.", minimum=1),
         _param("signal_method", "str", "EMA", "Signal Method",
                "Smoothing method used for the ARSI signal line.", choices=("EMA", "SMA", "RMA", "TMA"))),
        ("arsi_{period}_{method}", "arsi_signal_{period}_{method}_{signal_period}_{signal_method}"),
        _OSCILLATOR, "multi-line-series", oscillator_visual=_ARSI_VISUAL,
    ),
    "tdirsi": _spec(
        "tdirsi", "TDI RSI", "oscillator", "Traders Dynamic Index based on RSI.", _CLOSE,
        (_param("period", "int", 14, "Period", "Primary lookback period.", minimum=1),
         _param("band_length", "int", 34, "Band Length", "Lookback used for RSI bands.", minimum=1),
         _param("band_mult", "float", 1.6185, "Band Multiplier",
                "Band standard deviation multiplier.", required=False, minimum=1e-6),
         _param("fast_len", "int", 2, "Fast Length", "Fast smoothing length.", required=False, minimum=1),
         _param("slow_len", "int", 7, "Slow Length", "Slow smoothing length.", required=False, minimum=1),
         _param("fast_smo", "str", "EMA", "Fast Smoother", "Fast smoothing mode.",
                required=False, choices=("EMA", "RMA", "SMA")),
         _param("slow_smo", "str", "RMA", "Slow Smoother", "Slow smoothing mode.",
                required=False, choices=("EMA", "RMA", "SMA"))),
        tuple(f"{prefix}_{{period}}_{{band_length}}_{{fast_len}}_{{slow_len}}_{{fast_smo}}_{{slow_smo}}"
              for prefix in ("tdirsi_fast_ma", "tdirsi_slow_ma", "tdirsi_up", "tdirsi_dn", "tdirsi_mid")),
        _OSCILLATOR, "multi-line-series", oscillator_visual=_BOUNDED,
    ),
    "smi": _spec(
        "smi", "SMI", "oscillator", "Stochastic Momentum Index.", _HLC,
        (_param("k_length", "int", 14, "K Length", "Lookback for stochastic window.", minimum=1),
         _param("d_length", "int", 3, "D Length", "Smoothing length.", minimum=1)),
        ("smi_{k_length}_{d_length}", "smi_signal_{k_length}_{d_length}"),
        _OSCILLATOR, "multi-line-series", oscillator_visual=_ZERO,
    ),
    "mfi": _spec("mfi", "MFI", "oscillator", "Money Flow Index.", _HLCV, _period(),
                 ("mfi_{period}",), _OSCILLATOR, "line-series", oscillator_visual=_BOUNDED),
    "obv": _spec("obv", "OBV", "oscillator", "On-Balance Volume.",
                 (_input("close", "Close"), _input("volume", "Volume")), (), ("obv",),
                 _OSCILLATOR, "line-series", oscillator_visual=_AUTO),
    "volume": _spec("volume", "Volume", "oscillator", "Raw traded volume with configurable rolling mean.",
                    (_input("volume", "Volume"),), _period(20, "Mean Period"),
                    ("volume", "volume_mean_{period}"), _OSCILLATOR, "multi-line-series", oscillator_visual=_AUTO),
}
OSCILLATOR_SPECS = MappingProxyType(_oscillator_specs)


def _construct_io(binding: str, families: tuple[str, ...], compatibility: str,
                  cardinality: str, role: str) -> ConstructIOSpec:
    return ConstructIOSpec(binding, families, compatibility, cardinality, role)


_ALL_SOURCES = ("ohlc", "indicator", "oscillator", "construct")
_construct_specs = {
    "dynamic_binning": _spec(
        "dynamic_binning", "Dynamic Binning", "construct",
        "Non-visual construct that estimates per-series movement floors and fits deterministic signed bins.", (),
        (_param("source_columns", "str", "close", "Source Columns",
                "Comma-separated source column names, for example: close, volume, feature_1"),
         _param("window", "int", 10, "Window", "Rolling window length.", minimum=1),
         _param("multiplier", "float", 1.0, "Multiplier",
                "Final multiplier applied to the estimated movement floor.", required=False, minimum=1e-6),
         _param("floor_quantile", "float", 0.05, "Floor Quantile",
                "Low quantile used to estimate the minimum meaningful movement floor.",
                required=False, minimum=0.0, maximum=1.0),
         _param("global_min_step", "float", 1e-12, "Global Min Step",
                "Strictly-positive global fallback step for degenerate or flat series.",
                required=False, minimum=0.0),
         _param("quantile_method", "str", "nearest", "Quantile Method",
                "Quantile interpolation/method mode used by the variation estimator.", required=False,
                choices=("nearest", "lower", "higher", "midpoint", "linear")),
         _param("n_bins", "int", 15, "Number of Bins", "Number of signed bins per side.",
                required=False, minimum=1),
         _param("boundary_eps", "float", 1e-12, "Boundary Epsilon",
                "Absolute tolerance used only for scalar threshold comparisons.",
                required=False, minimum=0.0)),
        (), _NON_VISUAL, "analysis-only", accepts_empty=True, signals=(),
    ),
    "derivative": _spec(
        "derivative", "Derivatives", "construct", "Unary construct computing first or second derivative.", (),
        (_param("order", "int", 1, "Derivative Order",
                "Derivative order. Supported values in this phase: 1 or 2.",
                required=False, minimum=1, maximum=2),),
        (), _OSCILLATOR, "line-series", form_variant="construct_unary_source", signals=(),
        construct_io=_construct_io("unary_source", _ALL_SOURCES, "mixed_numeric", "single", "plotted_line"),
    ),
    "angle": _spec(
        "angle", "Angles", "construct", "Unary construct computing the canonical angle of the selected source.", (),
        (_param("unit", "str", "deg", "Unit", "Output angular unit for the unary angle construct.",
                required=False, choices=("deg", "rad")),),
        (), _OSCILLATOR, "line-series", form_variant="construct_unary_source", signals=(),
        construct_io=_construct_io("unary_source", _ALL_SOURCES, "mixed_numeric", "single", "plotted_line"),
    ),
    "braids": _spec(
        "braids", "Braids", "construct",
        "Braid structural construct emitting ambient state, width, and compression for fast, mid, and slow sources.", (),
        (_param("fast", "str", "", "Fast Source", "Fast source column name."),
         _param("mid", "str", "", "Mid Source", "Mid source column name."),
         _param("slow", "str", "", "Slow Source", "Slow source column name."),
         _param("tie_policy", "str", "carry", "Tie Policy",
                "How braid-state ties are handled for the ambient braid state output.",
                required=False, choices=("carry", "drop"))),
        (), _OSCILLATOR, "multi-line-series", form_variant="construct_fms", signals=(),
        construct_io=_construct_io("fast_mid_slow", ("indicator", "oscillator", "construct"),
                                   "same_family", "one_or_more", "state_series"),
    ),
    "braid_instability": _spec(
        "braid_instability", "Braid Instability", "construct",
        "Temporal braid-stability construct measuring rolling raw braid-state churn.", (),
        (_param("fast", "str", "", "Fast Source", "Fast source column name."),
         _param("mid", "str", "", "Mid Source", "Mid source column name."),
         _param("slow", "str", "", "Slow Source", "Slow source column name."),
         _param("n", "int", 5, "Instability Window",
                "Rolling window used to compute braid instability.", required=False, minimum=1)),
        (), _OSCILLATOR, "line-series", form_variant="construct_fms", signals=(),
        construct_io=_construct_io("fast_mid_slow", ("indicator", "oscillator", "construct"),
                                   "same_family", "single", "plotted_line"),
    ),
    "delta": _spec(
        "delta", "Delta", "construct",
        "Directional relational construct computing fast-minus-slow in raw or percent-relative mode.", (),
        (_param("fast", "str", "", "Fast Source", "Fast source column name."),
         _param("slow", "str", "", "Slow Source", "Slow source column name."),
         _param("mode", "str", "abs", "Delta Mode",
                "Delta output mode. 'abs' emits raw signed separation. 'pct' emits signed percent-relative separation versus the slow source.",
                required=False, choices=("abs", "pct")),
         _param("eps", "float", 1e-12, "Delta Epsilon",
                "Strictly positive denominator stabilization value used only when delta mode is 'pct'.",
                required=False, minimum=0.0)),
        (), _OSCILLATOR, "multi-line-series", form_variant="construct_fs", signals=(),
        construct_io=_construct_io("fast_slow", _ALL_SOURCES, "mixed_numeric", "one_or_more", "plotted_line"),
    ),
    "trap_area": _spec(
        "trap_area", "Trap Area", "construct",
        "Cumulative trapezoidal area between ordered faster/slower signal pairs.", (),
        (_param("fast", "str", "", "Fast Source", "Fast source column name."),
         _param("mid", "str", "", "Mid Source", "Optional mid source column name.", required=False),
         _param("slow", "str", "", "Slow Source", "Slow source column name."),
         _param("zero_eps", "float", 0.0, "Zero Epsilon",
                "Near-zero threshold used for trap-area segment boundaries.", required=False, minimum=0.0)),
        (), _OSCILLATOR, "multi-line-series", form_variant="construct_fms", signals=(),
        construct_io=_construct_io("fast_mid_slow", _ALL_SOURCES, "mixed_numeric", "one_or_more", "plotted_line"),
    ),
    "percent_span_angle": _spec(
        "percent_span_angle", "Percent Span Angle", "construct",
        "Windowed percent-span angle on selected source columns.", (),
        (_param("source_columns", "str", "close", "Source Columns",
                "Comma-separated source column names, for example: close, volume, feature_1"),
         _param("window", "int", 10, "Window", "Rolling window length.", minimum=1),
         _param("unit", "str", "deg", "Unit", "Output unit for percent-span-angle values.",
                required=False, choices=("deg", "rad"))),
        (), _OSCILLATOR, "multi-line-series", form_variant="construct_multi_source", signals=(),
        construct_io=_construct_io("multi_source", _ALL_SOURCES, "mixed_numeric", "matches_inputs", "plotted_line"),
    ),
    "angle_momentum": _spec(
        "angle_momentum", "Angle Momentum", "construct",
        "Signed average angle change per bar on selected angle-like source columns.", (),
        (_param("source_columns", "str", "close", "Source Columns",
                "Comma-separated source column names, for example: close, volume, feature_1"),
         _param("n", "int", 3, "Momentum Window",
                "Lookback window used to compute angle momentum.", required=False, minimum=1)),
        (), _OSCILLATOR, "multi-line-series", form_variant="construct_multi_source", signals=(),
        construct_io=_construct_io("multi_source", _ALL_SOURCES, "mixed_numeric", "matches_inputs", "plotted_line"),
    ),
}
CONSTRUCT_SPECS = MappingProxyType(_construct_specs)


_all_financial_tool_specs = {
    **INDICATOR_SPECS,
    **OSCILLATOR_SPECS,
    **CONSTRUCT_SPECS,
}
ALL_FINANCIAL_TOOL_SPECS = MappingProxyType(_all_financial_tool_specs)


def get_financial_tool_spec(key: str) -> FinancialToolSpec:
    canonical = canonicalize_tool_key(key)
    try:
        return ALL_FINANCIAL_TOOL_SPECS[canonical]
    except KeyError as exc:
        raise KeyError(f"Unknown financial tool: {key}") from exc


def list_financial_tool_specs(kind: ToolKind | None = None) -> tuple[FinancialToolSpec, ...]:
    if kind is None:
        return tuple(ALL_FINANCIAL_TOOL_SPECS.values())
    if kind not in {"indicator", "oscillator", "construct"}:
        raise ValueError(f"Unsupported financial tool kind: {kind!r}")
    return tuple(spec for spec in ALL_FINANCIAL_TOOL_SPECS.values() if spec.kind == kind)


def _coerce_parameter(parameter: ParameterSpec, value: object) -> object:
    if value is None and not parameter.required:
        return None
    if parameter.dtype == "bool":
        if type(value) is not bool:
            raise ValueError(f"Parameter {parameter.name!r} must be bool")
        resolved = value
    elif parameter.dtype == "int":
        if type(value) is not int:
            raise ValueError(f"Parameter {parameter.name!r} must be int")
        resolved = value
    elif parameter.dtype == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Parameter {parameter.name!r} must be float")
        resolved = float(value)
    elif parameter.dtype == "str":
        if type(value) is not str:
            raise ValueError(f"Parameter {parameter.name!r} must be str")
        resolved = value
    else:
        raise ValueError(f"Unsupported parameter type: {parameter.dtype!r}")
    if parameter.min_value is not None and resolved < parameter.min_value:
        raise ValueError(f"Parameter {parameter.name!r} is below its minimum")
    if parameter.max_value is not None and resolved > parameter.max_value:
        raise ValueError(f"Parameter {parameter.name!r} exceeds its maximum")
    if parameter.choices and resolved not in parameter.choices:
        raise ValueError(f"Parameter {parameter.name!r} is not an accepted choice")
    return resolved


def resolve_parameters(
    tool_key: str,
    overrides: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    spec = get_financial_tool_spec(tool_key)
    supplied = dict(overrides or {})
    known = {parameter.name for parameter in spec.parameters}
    unknown = tuple(sorted(set(supplied) - known))
    if unknown:
        raise ValueError(f"Unknown parameters for {spec.key}: {unknown}")
    resolved: dict[str, object] = {}
    for parameter in spec.parameters:
        if parameter.name in supplied:
            value = supplied[parameter.name]
        elif parameter.default is not None or not parameter.required or parameter.dtype == "str":
            value = parameter.default
        else:
            raise ValueError(f"Missing required parameter: {parameter.name}")
        resolved[parameter.name] = _coerce_parameter(parameter, value)
    return MappingProxyType(resolved)


def _dynamic_signal(tool_key: str, name: str) -> OutputSignalSpec:
    if tool_key == "braids":
        if name.endswith("_width"):
            return _signal(name, renderable=False, default_visible=False, label="Braid Width",
                           description="Total braid envelope spread. Retained for analysis/chaining, not chart rendering.",
                           semantic_role="analysis")
        if name.endswith("_compression"):
            return _signal(name, renderable=False, default_visible=False, label="Braid Compression",
                           description="Minimum pairwise braid separation. Retained for analysis/chaining, not chart rendering.",
                           semantic_role="analysis")
        return _signal(name, label="Braid Ambient State", description="Categorical braid ordering state series.",
                       semantic_role="state", value_type="categorical", can_drive_style_rules=True)
    labels = {
        "derivative": ("Derivative", "Derivative of the selected source."),
        "angle": ("Angle", "Unary angular transform of the selected source."),
        "braid_instability": ("Braid Instability", "Rolling instability score of raw braid state changes."),
        "trap_area": ("Trap Area", "Trap-area series for one configured faster/slower pair."),
        "percent_span_angle": ("Percent Span Angle", "Windowed percent-span angular orientation series."),
        "angle_momentum": ("Angle Momentum", "Average signed angle change per bar over the configured lag window."),
    }
    label, description = labels.get(tool_key, ("Delta", "Signed raw separation of fast versus slow."))
    return _signal(name, label=label, description=description)


def _resolved_indicator_signals(key: str, names: tuple[str, ...]) -> tuple[OutputSignalSpec, ...]:
    moving_average_labels = {
        "sma": ("SMA", "Primary SMA line."),
        "ema": ("EMA", "Primary EMA line."),
        "tema": ("TEMA", "Primary TEMA line."),
        "hma": ("HMA", "Primary HMA line."),
        "kama": ("KAMA", "Primary KAMA line."),
    }
    if key in moving_average_labels:
        label, description = moving_average_labels[key]
        return (_signal(names[0], label=label, description=description, can_drive_style_rules=True),)
    if key == "bb":
        details = (
            ("BB Middle", "Bollinger middle band.", "center"),
            ("BB Upper Band", "Bollinger upper band.", "upper"),
            ("BB Lower Band", "Bollinger lower band.", "lower"),
        )
        return tuple(_signal(name, label=label, description=description, semantic_role=role,
                             can_drive_style_rules=True)
                     for name, (label, description, role) in zip(names, details, strict=True))
    if key == "hck":
        return (
            _signal(names[0], label="Fast VWAP", description="Fast EW-VWAP line.",
                    semantic_role="fast", can_drive_style_rules=True),
            _signal(names[1], label="Slow VWAP", description="Slow EW-VWAP line.",
                    semantic_role="slow", can_drive_style_rules=True),
            _signal(names[2], signal_type="utility", renderable=False, analysis_usable=False,
                    default_visible=False, label="VWAP Color State",
                    description="Auxiliary directional color state. Not a canonical plotted line.",
                    semantic_role="state", value_type="categorical", can_drive_style_rules=True),
        )
    if key == "strategy":
        signals: list[OutputSignalSpec] = []
        for slot, name in enumerate(names[:6], 1):
            signals.append(_signal(name, label=f"EMA {slot}", description=f"Strategy EMA slot {slot}.",
                                   semantic_role="ema", can_drive_style_rules=True))
        for slot, name in enumerate(names[6:12], 1):
            signals.append(_signal(name, label=f"SMA {slot}", description=f"Strategy SMA slot {slot}.",
                                   semantic_role="sma", can_drive_style_rules=True))
        details = (
            ("BB Middle", "Strategy Bollinger middle band.", "center"),
            ("BB Upper Band", "Strategy Bollinger upper band.", "upper"),
            ("BB Lower Band", "Strategy Bollinger lower band.", "lower"),
            ("Fast VWAP", "Strategy fast EW-VWAP line.", "fast"),
            ("Slow VWAP", "Strategy slow EW-VWAP line.", "slow"),
        )
        signals.extend(_signal(name, label=label, description=description, semantic_role=role,
                               can_drive_style_rules=True)
                       for name, (label, description, role) in zip(names[12:17], details, strict=True))
        signals.append(_signal(
            names[17], signal_type="utility", renderable=False, analysis_usable=False,
            default_visible=False, label="VWAP Color State",
            description="Strategy auxiliary directional color state. Not a canonical plotted line.",
            semantic_role="state", value_type="categorical", can_drive_style_rules=True,
        ))
        return tuple(signals)
    if key == "peaks_troughs":
        return tuple(
            _signal(
                name,
                default_visible=length == 3,
                label=f"{kind.title()} {length}",
                description=(
                    f"Confirmed {length}-bar {kind} fractal event using the bar "
                    f"{'high' if kind == 'peak' else 'low'} as the marker price."
                ),
                semantic_role=kind,
                can_drive_style_rules=True,
            )
            for length in (3, 5, 7, 9, 11)
            for kind, name in (("peak", f"peak_fractal_{length}"), ("trough", f"trough_fractal_{length}"))
        )
    raise KeyError(key)


def _resolved_oscillator_signals(key: str, names: tuple[str, ...]) -> tuple[OutputSignalSpec, ...]:
    if key in {"rsi", "mfi", "obv"}:
        labels = {"rsi": ("RSI", "Primary RSI line."),
                  "mfi": ("MFI", "Primary money flow index line."),
                  "obv": ("OBV", "Primary on-balance volume line.")}
        label, description = labels[key]
        return (_signal(names[0], label=label, description=description),)
    if key == "arsi":
        return (
            _signal(names[0], label="ARSI", description="Primary Ultimate RSI-style ARSI line."),
            _signal(names[1], label="ARSI Signal", description="Moving average signal line of ARSI.",
                    semantic_role="signal"),
        )
    if key == "tdirsi":
        details = (
            ("Fast MA", "Fast smoothed RSI line."), ("Slow MA", "Slow smoothed RSI line."),
            ("Upper Band", "Upper RSI volatility band."), ("Lower Band", "Lower RSI volatility band."),
            ("Mid Band", "Mid RSI volatility band."),
        )
        return tuple(_signal(name, label=label, description=description)
                     for name, (label, description) in zip(names, details, strict=True))
    if key == "smi":
        return (
            _signal(names[0], label="SMI", description="Primary stochastic momentum index line."),
            _signal(names[1], label="SMI Signal", description="SMI signal line."),
        )
    if key == "volume":
        return (
            _signal(names[0], label="Volume", description="Raw traded volume from the canonical OHLCV dataset.",
                    can_drive_style_rules=True),
            _signal(names[1], label="Volume Mean", description="Rolling mean of traded volume.",
                    semantic_role="mean", can_drive_style_rules=True),
        )
    raise KeyError(key)


def resolve_output_signals(
    tool_key: str,
    parameters: Mapping[str, object] | None = None,
) -> tuple[OutputSignalSpec, ...]:
    spec = get_financial_tool_spec(tool_key)
    names = resolve_output_names(spec.key, parameters)
    if spec.key == "universal_trend_classifier":
        return tuple(
            OutputSignalSpec(
                name=name,
                signal_type=template.signal_type,
                renderable=template.renderable,
                analysis_usable=template.analysis_usable,
                default_visible=template.default_visible,
                label=template.label,
                description=template.description,
                semantic_role=template.semantic_role,
                value_type=template.value_type,
                can_drive_style_rules=template.can_drive_style_rules,
            )
            for name, template in zip(names, spec.output.signals, strict=True)
        )
    if spec.kind == "indicator":
        return _resolved_indicator_signals(spec.key, names)
    if spec.kind == "oscillator":
        return _resolved_oscillator_signals(spec.key, names)
    if spec.key == "dynamic_binning":
        return ()
    signals = tuple(_dynamic_signal(spec.key, name) for name in names)
    if spec.key == "delta":
        resolved = resolve_parameters(spec.key, parameters)
        if resolved["mode"] == "pct":
            return tuple(_signal(signal.name, label="Delta %",
                                 description="Signed percent-relative separation of fast versus slow.")
                         for signal in signals)
    return signals


def validate_catalog() -> None:
    expected_counts = {"indicator": 10, "oscillator": 7, "construct": 9}
    family_keys = (tuple(INDICATOR_SPECS), tuple(OSCILLATOR_SPECS), tuple(CONSTRUCT_SPECS))
    flattened_keys = tuple(key for family in family_keys for key in family)
    if len(flattened_keys) != len(set(flattened_keys)):
        raise ValueError("financial tool keys must be unique across families")
    if len(ALL_FINANCIAL_TOOL_SPECS) != 26:
        raise ValueError("financial tool catalog must contain exactly 26 tools")
    for kind, expected in expected_counts.items():
        if len(list_financial_tool_specs(kind)) != expected:
            raise ValueError(f"financial tool catalog must contain exactly {expected} {kind} tools")
    for alias, target in CANONICAL_TOOL_ALIASES.items():
        if alias in ALL_FINANCIAL_TOOL_SPECS:
            raise ValueError(f"financial tool alias collides with canonical key: {alias!r}")
        if target not in ALL_FINANCIAL_TOOL_SPECS:
            raise ValueError(f"financial tool alias points to unknown key: {alias!r}")
    for family in (INDICATOR_SPECS, OSCILLATOR_SPECS, CONSTRUCT_SPECS):
        titles = tuple(spec.title for spec in family.values())
        if len(titles) != len(set(titles)):
            raise ValueError("financial tool titles must be unique within each family")
    binding_examples: dict[str, Mapping[str, object]] = {
        "derivative": {"source": "close"},
        "angle": {"source": "close"},
        "braids": {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"},
        "braid_instability": {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"},
        "delta": {"fast": "ema_9", "slow": "ema_20"},
        "trap_area": {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"},
    }
    for key, spec in ALL_FINANCIAL_TOOL_SPECS.items():
        if key != spec.key or canonicalize_tool_key(key) != key:
            raise ValueError(f"non-canonical financial tool key: {key!r}")
        resolve_parameters(key)
        if spec.output.output_names != spec.output_names:
            raise ValueError(f"output declaration mismatch for {key}")
        output_names = resolve_output_names(key, binding_examples.get(key))
        if len(output_names) != len(set(output_names)):
            raise ValueError(f"resolved output names must be unique for {key}")
        if spec.kind == "construct" and key != "dynamic_binning" and spec.construct_io is None:
            raise ValueError(f"construct requires ConstructIOSpec: {key}")
        if spec.kind == "oscillator" and spec.oscillator_visual is None:
            raise ValueError(f"oscillator requires OscillatorVisualSpec: {key}")
        if spec.kind != "oscillator" and spec.oscillator_visual is not None:
            raise ValueError(f"non-oscillator must not contain OscillatorVisualSpec: {key}")
    dynamic_binning = CONSTRUCT_SPECS["dynamic_binning"]
    if dynamic_binning.behavior.chart_renderable or dynamic_binning.behavior.output_mode != "non-visual":
        raise ValueError("dynamic_binning must remain non-visual")


validate_catalog()
