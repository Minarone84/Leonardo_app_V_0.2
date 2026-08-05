from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from enum import StrEnum
from types import MappingProxyType

import pytest

from leonardo.financial_tools import (
    ALL_FINANCIAL_TOOL_SPECS,
    CONSTRUCT_SPECS,
    INDICATOR_SPECS,
    OSCILLATOR_SPECS,
    FinancialToolSpec,
    ToolUpdatePolicy,
    UpdateStrategy,
    get_financial_tool_spec,
    list_financial_tool_specs,
    resolve_output_signals,
    resolve_parameters,
    validate_catalog,
)
from leonardo.financial_tools.models import (
    OscillatorGuideLevelSpec,
    ToolEditCapabilities,
    ToolStyleCapabilities,
)


INDICATORS = (
    "sma", "ema", "tema", "hma", "kama", "bb", "hck", "strategy",
    "peaks_troughs", "universal_trend_classifier",
)
OSCILLATORS = ("rsi", "arsi", "tdirsi", "smi", "mfi", "obv", "volume")
CONSTRUCTS = (
    "dynamic_binning", "derivative", "angle", "braids", "braid_instability",
    "delta", "trap_area", "percent_span_angle", "angle_momentum",
)


def _parameter_rows(key: str) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (item.name, item.dtype, item.required, item.default, item.min_value, item.max_value, item.choices, item.label)
        for item in get_financial_tool_spec(key).parameters
    )


PERIOD_14 = (("period", "int", True, 14, 1, None, (), "Period"),)
EXACT_PARAMETERS = {
    "sma": PERIOD_14, "ema": PERIOD_14, "tema": PERIOD_14, "hma": PERIOD_14,
    "kama": (("fast_period", "int", True, 2, 1, None, (), "Fast Period"),
             ("slow_period", "int", True, 30, 1, None, (), "Slow Period")),
    "bb": (("period", "int", True, 14, 1, None, (), "Period"),
           ("std", "float", True, 2.0, 1e-6, None, (), "Std Dev Multiplier")),
    "hck": (("fast_vwap_l", "int", True, 13, 1, None, (), "Fast VWAP Length"),
            ("slow_vwap_l", "int", True, 48, 1, None, (), "Slow VWAP Length")),
    "strategy": tuple(
        [(f"ema_{slot}_period", "int", True, value, 1, None, (), f"EMA {slot} Period")
         for slot, value in enumerate((9, 20, 50, 100, 200, 400), 1)]
        + [(f"sma_{slot}_period", "int", True, value, 1, None, (), f"SMA {slot} Period")
           for slot, value in enumerate((9, 20, 50, 100, 200, 400), 1)]
        + [("bb_period", "int", True, 20, 1, None, (), "BB Period"),
           ("bb_std", "float", True, 2.0, 1e-6, None, (), "BB Std Dev Multiplier"),
           ("hck_fast_vwap_l", "int", True, 13, 1, None, (), "HCK Fast VWAP Length"),
           ("hck_slow_vwap_l", "int", True, 48, 1, None, (), "HCK Slow VWAP Length")]
    ),
    "peaks_troughs": (),
    "universal_trend_classifier": (
        ("source", "str", True, "close", None, None, ("open", "high", "low", "close"), "Source"),
        ("fractal_window", "int", True, 5, 3, None, (3, 5, 7, 9, 11), "Fractal Window"),
        ("trend_fractal_window", "int", True, 5, 3, None, (3, 5, 7, 9, 11), "Up/Down Trend Fractal"),
        ("peak_column", "str", False, None, None, None, (), "Peak Column"),
        ("trough_column", "str", False, None, None, None, (), "Trough Column"),
        ("min_hr_band_perc", "float", True, 0.005, 0.0, None, (), "Min HR Band %"),
        ("hr_trend_length", "int", True, 20, 3, None, (), "HR Trend Length"),
        ("hr_trend_atr_mult", "float", True, 1.0, 0.0, None, (), "HR ATR Mult"),
        ("hr_trend_atr_len", "int", True, 500, 1, None, (), "HR ATR Length"),
        ("hr_trend_tol_mult", "float", True, 0.3, 0.0, None, (), "HR Trend Tolerance Mult"),
        ("hr_trend_max_gap", "int", True, 20, 1, None, (), "HR Trend Max Gap"),
        ("hr_min_inside_ratio", "float", True, 0.8, 1e-6, 1.0, (), "HR Min Inside Ratio"),
        ("min_range_swings", "int", True, 4, 4, None, (), "Min Range Swings"),
        ("range_fractal_window", "int", True, 3, 3, None, (3, 5, 7, 9, 11), "Horizontal Range Fractal"),
        ("hr_break_mode", "str", True, "close", None, None, ("close", "wick", "hybrid"), "Range Break Mode"),
    ),
    "rsi": PERIOD_14,
    "arsi": (("period", "int", True, 14, 1, None, (), "Period"),
             ("method", "str", True, "RMA", None, None, ("EMA", "SMA", "RMA", "TMA"), "Method"),
             ("signal_period", "int", True, 14, 1, None, (), "Signal Period"),
             ("signal_method", "str", True, "EMA", None, None, ("EMA", "SMA", "RMA", "TMA"), "Signal Method")),
    "tdirsi": (("period", "int", True, 14, 1, None, (), "Period"),
               ("band_length", "int", True, 34, 1, None, (), "Band Length"),
               ("band_mult", "float", False, 1.6185, 1e-6, None, (), "Band Multiplier"),
               ("fast_len", "int", False, 2, 1, None, (), "Fast Length"),
               ("slow_len", "int", False, 7, 1, None, (), "Slow Length"),
               ("fast_smo", "str", False, "EMA", None, None, ("EMA", "RMA", "SMA"), "Fast Smoother"),
               ("slow_smo", "str", False, "RMA", None, None, ("EMA", "RMA", "SMA"), "Slow Smoother")),
    "smi": (("k_length", "int", True, 14, 1, None, (), "K Length"),
            ("d_length", "int", True, 3, 1, None, (), "D Length")),
    "mfi": PERIOD_14, "obv": (),
    "volume": (("period", "int", True, 20, 1, None, (), "Mean Period"),),
    "dynamic_binning": (
        ("source_columns", "str", True, "close", None, None, (), "Source Columns"),
        ("window", "int", True, 10, 1, None, (), "Window"),
        ("multiplier", "float", False, 1.0, 1e-6, None, (), "Multiplier"),
        ("floor_quantile", "float", False, 0.05, 0.0, 1.0, (), "Floor Quantile"),
        ("global_min_step", "float", False, 1e-12, 0.0, None, (), "Global Min Step"),
        ("quantile_method", "str", False, "nearest", None, None,
         ("nearest", "lower", "higher", "midpoint", "linear"), "Quantile Method"),
        ("n_bins", "int", False, 15, 1, None, (), "Number of Bins"),
        ("boundary_eps", "float", False, 1e-12, 0.0, None, (), "Boundary Epsilon"),
    ),
    "derivative": (("order", "int", False, 1, 1, 2, (), "Derivative Order"),),
    "angle": (("unit", "str", False, "deg", None, None, ("deg", "rad"), "Unit"),),
    "braids": (("fast", "str", True, "", None, None, (), "Fast Source"),
               ("mid", "str", True, "", None, None, (), "Mid Source"),
               ("slow", "str", True, "", None, None, (), "Slow Source"),
               ("tie_policy", "str", False, "carry", None, None, ("carry", "drop"), "Tie Policy")),
    "braid_instability": (("fast", "str", True, "", None, None, (), "Fast Source"),
                          ("mid", "str", True, "", None, None, (), "Mid Source"),
                          ("slow", "str", True, "", None, None, (), "Slow Source"),
                          ("n", "int", False, 5, 1, None, (), "Instability Window")),
    "delta": (("fast", "str", True, "", None, None, (), "Fast Source"),
              ("slow", "str", True, "", None, None, (), "Slow Source"),
              ("mode", "str", False, "abs", None, None, ("abs", "pct"), "Delta Mode"),
              ("eps", "float", False, 1e-12, 0.0, None, (), "Delta Epsilon")),
    "trap_area": (("fast", "str", True, "", None, None, (), "Fast Source"),
                  ("mid", "str", False, "", None, None, (), "Mid Source"),
                  ("slow", "str", True, "", None, None, (), "Slow Source"),
                  ("zero_eps", "float", False, 0.0, 0.0, None, (), "Zero Epsilon")),
    "percent_span_angle": (("source_columns", "str", True, "close", None, None, (), "Source Columns"),
                           ("window", "int", True, 10, 1, None, (), "Window"),
                           ("unit", "str", False, "deg", None, None, ("deg", "rad"), "Unit")),
    "angle_momentum": (("source_columns", "str", True, "close", None, None, (), "Source Columns"),
                       ("n", "int", False, 3, 1, None, (), "Momentum Window")),
}

EXACT_PARAMETER_DESCRIPTIONS = (
    ("sma", "period", "Primary lookback period."),
    ("ema", "period", "Primary lookback period."),
    ("tema", "period", "Primary lookback period."),
    ("hma", "period", "Primary lookback period."),
    ("kama", "fast_period", "Fast smoothing/adaptation period."),
    ("kama", "slow_period", "Slow smoothing/adaptation period."),
    ("bb", "period", "Primary lookback period."),
    ("bb", "std", "Standard deviation multiplier."),
    ("hck", "fast_vwap_l", "Fast EW-VWAP length."),
    ("hck", "slow_vwap_l", "Slow EW-VWAP length."),
    ("strategy", "ema_1_period", "Lookback period for Strategy EMA slot 1."),
    ("strategy", "ema_2_period", "Lookback period for Strategy EMA slot 2."),
    ("strategy", "ema_3_period", "Lookback period for Strategy EMA slot 3."),
    ("strategy", "ema_4_period", "Lookback period for Strategy EMA slot 4."),
    ("strategy", "ema_5_period", "Lookback period for Strategy EMA slot 5."),
    ("strategy", "ema_6_period", "Lookback period for Strategy EMA slot 6."),
    ("strategy", "sma_1_period", "Lookback period for Strategy SMA slot 1."),
    ("strategy", "sma_2_period", "Lookback period for Strategy SMA slot 2."),
    ("strategy", "sma_3_period", "Lookback period for Strategy SMA slot 3."),
    ("strategy", "sma_4_period", "Lookback period for Strategy SMA slot 4."),
    ("strategy", "sma_5_period", "Lookback period for Strategy SMA slot 5."),
    ("strategy", "sma_6_period", "Lookback period for Strategy SMA slot 6."),
    ("strategy", "bb_period", "Bollinger Bands lookback period inside Strategy."),
    ("strategy", "bb_std", "Bollinger Bands standard deviation multiplier inside Strategy."),
    ("strategy", "hck_fast_vwap_l", "Fast EW-VWAP length for the Strategy Hancock pair."),
    ("strategy", "hck_slow_vwap_l", "Slow EW-VWAP length for the Strategy Hancock pair."),
    ("universal_trend_classifier", "source", "OHLC source column used by the Universal Trend Classifier."),
    ("universal_trend_classifier", "fractal_window", "Compatibility alias for trend_fractal_window."),
    ("universal_trend_classifier", "trend_fractal_window", "Peaks & Troughs fractal length consumed by UTC directional trend detection."),
    ("universal_trend_classifier", "peak_column", "Legacy trend peak column override. Leave empty to use peak_fractal_{trend_fractal_window}."),
    ("universal_trend_classifier", "trough_column", "Legacy trend trough column override. Leave empty to use trough_fractal_{trend_fractal_window}."),
    ("universal_trend_classifier", "min_hr_band_perc", "Minimum horizontal-range band size as a fraction of source price."),
    ("universal_trend_classifier", "hr_trend_length", "Lookback window used to evaluate horizontal-range/trend structure."),
    ("universal_trend_classifier", "hr_trend_atr_mult", "ATR multiplier used for horizontal-range band tolerance."),
    ("universal_trend_classifier", "hr_trend_atr_len", "Rolling ATR averaging length used by the classifier."),
    ("universal_trend_classifier", "hr_trend_tol_mult", "ATR multiplier reserved for incremental/realtime trend-extension tolerance; historical directional trend detection remains strict."),
    ("universal_trend_classifier", "hr_trend_max_gap", "Maximum allowed gap between qualifying swings for horizontal-range continuity."),
    ("universal_trend_classifier", "hr_min_inside_ratio", "Minimum ratio of bars inside the candidate horizontal-range band."),
    ("universal_trend_classifier", "min_range_swings", "Minimum alternating swings required to confirm a horizontal range."),
    ("universal_trend_classifier", "range_fractal_window", "Peaks & Troughs fractal length consumed by UTC horizontal range discovery."),
    ("universal_trend_classifier", "hr_break_mode", "Horizontal-range invalidation mode after a range is active."),
    ("rsi", "period", "Primary lookback period."),
    ("arsi", "period", "Primary lookback period."),
    ("arsi", "method", "Smoothing method used for the primary ARSI numerator and denominator."),
    ("arsi", "signal_period", "Moving-average period for the ARSI signal line."),
    ("arsi", "signal_method", "Smoothing method used for the ARSI signal line."),
    ("tdirsi", "period", "Primary lookback period."),
    ("tdirsi", "band_length", "Lookback used for RSI bands."),
    ("tdirsi", "band_mult", "Band standard deviation multiplier."),
    ("tdirsi", "fast_len", "Fast smoothing length."),
    ("tdirsi", "slow_len", "Slow smoothing length."),
    ("tdirsi", "fast_smo", "Fast smoothing mode."),
    ("tdirsi", "slow_smo", "Slow smoothing mode."),
    ("smi", "k_length", "Lookback for stochastic window."),
    ("smi", "d_length", "Smoothing length."),
    ("mfi", "period", "Primary lookback period."),
    ("volume", "period", "Rolling mean period for the Volume average line."),
    ("dynamic_binning", "source_columns", "Comma-separated source column names, for example: close, volume, feature_1"),
    ("dynamic_binning", "window", "Rolling window length."),
    ("dynamic_binning", "multiplier", "Final multiplier applied to the estimated movement floor."),
    ("dynamic_binning", "floor_quantile", "Low quantile used to estimate the minimum meaningful movement floor."),
    ("dynamic_binning", "global_min_step", "Strictly-positive global fallback step for degenerate or flat series."),
    ("dynamic_binning", "quantile_method", "Quantile interpolation/method mode used by the variation estimator."),
    ("dynamic_binning", "n_bins", "Number of signed bins per side."),
    ("dynamic_binning", "boundary_eps", "Absolute tolerance used only for scalar threshold comparisons."),
    ("derivative", "order", "Derivative order. Supported values in this phase: 1 or 2."),
    ("angle", "unit", "Output angular unit for the unary angle construct."),
    ("braids", "fast", "Fast source column name."),
    ("braids", "mid", "Mid source column name."),
    ("braids", "slow", "Slow source column name."),
    ("braids", "tie_policy", "How braid-state ties are handled for the ambient braid state output."),
    ("braid_instability", "fast", "Fast source column name."),
    ("braid_instability", "mid", "Mid source column name."),
    ("braid_instability", "slow", "Slow source column name."),
    ("braid_instability", "n", "Rolling window used to compute braid instability."),
    ("delta", "fast", "Fast source column name."),
    ("delta", "slow", "Slow source column name."),
    ("delta", "mode", "Delta output mode. 'abs' emits raw signed separation. 'pct' emits signed percent-relative separation versus the slow source."),
    ("delta", "eps", "Strictly positive denominator stabilization value used only when delta mode is 'pct'."),
    ("trap_area", "fast", "Fast source column name."),
    ("trap_area", "mid", "Optional mid source column name."),
    ("trap_area", "slow", "Slow source column name."),
    ("trap_area", "zero_eps", "Near-zero threshold used for trap-area segment boundaries."),
    ("percent_span_angle", "source_columns", "Comma-separated source column names, for example: close, volume, feature_1"),
    ("percent_span_angle", "window", "Rolling window length."),
    ("percent_span_angle", "unit", "Output unit for percent-span-angle values."),
    ("angle_momentum", "source_columns", "Comma-separated source column names, for example: close, volume, feature_1"),
    ("angle_momentum", "n", "Lookback window used to compute angle momentum."),
)


def test_catalog_has_exact_frozen_inventory_and_order() -> None:
    assert tuple(INDICATOR_SPECS) == INDICATORS
    assert tuple(OSCILLATOR_SPECS) == OSCILLATORS
    assert tuple(CONSTRUCT_SPECS) == CONSTRUCTS
    assert tuple(ALL_FINANCIAL_TOOL_SPECS) == INDICATORS + OSCILLATORS + CONSTRUCTS
    assert len(ALL_FINANCIAL_TOOL_SPECS) == 26
    assert sum(
        len(spec.parameters) for spec in ALL_FINANCIAL_TOOL_SPECS.values()
    ) == 88


def test_exact_parameter_metadata_for_every_tool() -> None:
    assert tuple(EXACT_PARAMETERS) == INDICATORS + OSCILLATORS + CONSTRUCTS
    for key, expected in EXACT_PARAMETERS.items():
        assert _parameter_rows(key) == expected


def test_exact_parameter_descriptions_for_all_88_parameters() -> None:
    actual = tuple(
        (tool_key, parameter.name, parameter.description)
        for tool_key, spec in ALL_FINANCIAL_TOOL_SPECS.items()
        for parameter in spec.parameters
    )
    assert len(EXACT_PARAMETER_DESCRIPTIONS) == 88
    assert all(description for _, _, description in actual)
    assert actual == EXACT_PARAMETER_DESCRIPTIONS


def test_exact_input_metadata_for_every_tool() -> None:
    expected_names = {
        "sma": ("close",), "ema": ("close",), "tema": ("close",), "hma": ("close",),
        "kama": ("close",), "bb": ("close",), "hck": ("high", "low", "close", "volume"),
        "strategy": ("high", "low", "close", "volume"), "peaks_troughs": ("high", "low"),
        "universal_trend_classifier": ("open", "high", "low", "close"), "rsi": ("close",),
        "arsi": ("close",), "tdirsi": ("close",), "smi": ("high", "low", "close"),
        "mfi": ("high", "low", "close", "volume"), "obv": ("close", "volume"),
        "volume": ("volume",), "dynamic_binning": (), "derivative": (), "angle": (),
        "braids": (), "braid_instability": (), "delta": (), "trap_area": (),
        "percent_span_angle": (), "angle_momentum": (),
    }
    descriptions = {
        "open": "Open price series.", "high": "High price series.", "low": "Low price series.",
        "close": "Close price series.",
        "volume": "Volume series. Compute layer may resolve 'Volume' or 'volume'.",
    }
    for key, names in expected_names.items():
        assert tuple(
            (item.name, item.dtype, item.required, item.label, item.description)
            for item in get_financial_tool_spec(key).data_inputs
        ) == tuple((name, "float", True, name.title(), descriptions[name]) for name in names)


def test_catalogs_are_read_only_mapping_proxies() -> None:
    for catalog in (INDICATOR_SPECS, OSCILLATOR_SPECS, CONSTRUCT_SPECS, ALL_FINANCIAL_TOOL_SPECS):
        assert isinstance(catalog, MappingProxyType)
        with pytest.raises(TypeError):
            catalog["new"] = object()  # type: ignore[index]


def test_all_specs_are_frozen_slotted_models_with_complete_metadata() -> None:
    for key, spec in ALL_FINANCIAL_TOOL_SPECS.items():
        assert isinstance(spec, FinancialToolSpec)
        assert spec.key == key
        assert spec.title
        assert spec.description
        assert spec.form_variant
        assert spec.behavior.supported_environments == ("historical",)
        assert spec.behavior.default_environment == "historical"
        assert spec.output.output_names == spec.output_names
        assert len({item.name for item in spec.parameters}) == len(spec.parameters)
        assert len({item.name for item in spec.data_inputs}) == len(spec.data_inputs)
        with pytest.raises(FrozenInstanceError):
            spec.title = "changed"  # type: ignore[misc]
    assert all(hasattr(model, "__slots__") for model in (
        type(next(iter(ALL_FINANCIAL_TOOL_SPECS.values()))),
        type(get_financial_tool_spec("sma").parameters[0]),
        type(get_financial_tool_spec("sma").data_inputs[0]),
    ))


def test_financial_tool_spec_has_exact_required_field_names() -> None:
    assert tuple(field.name for field in fields(FinancialToolSpec)) == (
        "key", "title", "kind", "data_inputs", "parameters", "output_names", "description",
        "behavior", "output", "form_variant", "style_capabilities", "edit_capabilities",
        "oscillator_visual", "construct_io", "update_policy",
    )


def test_financial_tool_update_policy_matrix_is_exact() -> None:
    overlap = {
        "sma": ("period", 0, 1, 0),
        "bb": ("period", 0, 1, 0),
        "peaks_troughs": (None, 12, 0, 5),
        "mfi": ("period", 0, 1, 0),
        "volume": ("period", 0, 1, 0),
        "derivative": (None, 3, 0, 1),
        "angle": (None, 3, 0, 1),
        "braid_instability": ("n", 0, 2, 0),
        "delta": (None, 2, 0, 0),
        "percent_span_angle": ("window", 0, 1, 0),
        "angle_momentum": ("n", 0, 1, 0),
    }
    assert len(ALL_FINANCIAL_TOOL_SPECS) == 26
    for key, spec in ALL_FINANCIAL_TOOL_SPECS.items():
        policy = spec.update_policy
        assert isinstance(policy, ToolUpdatePolicy)
        if key in overlap:
            assert policy.strategy is UpdateStrategy.OVERLAP_RECALCULATION
            assert (
                policy.parameter_name,
                policy.fixed_context_rows,
                policy.context_extra_rows,
                policy.revisable_tail_rows,
            ) == overlap[key]
        else:
            assert policy == ToolUpdatePolicy(UpdateStrategy.FULL_RECALCULATION)
        assert policy.strategy is not UpdateStrategy.STATEFUL_INCREMENTAL


def test_financial_tool_update_policy_context_resolution_and_validation() -> None:
    assert issubclass(UpdateStrategy, StrEnum)
    assert UpdateStrategy("FULL_RECALCULATION") is UpdateStrategy.FULL_RECALCULATION
    assert get_financial_tool_spec("sma").update_policy.effective_context_rows(
        {"period": 20}
    ) == 21
    assert get_financial_tool_spec(
        "peaks_troughs"
    ).update_policy.effective_context_rows({}) == 12
    with pytest.raises(ValueError):
        ToolUpdatePolicy(UpdateStrategy("FULL_RECALCULATION"), fixed_context_rows=1)
    with pytest.raises(ValueError):
        ToolUpdatePolicy(UpdateStrategy.STATEFUL_INCREMENTAL, parameter_name="period")
    with pytest.raises(ValueError):
        ToolUpdatePolicy(UpdateStrategy.OVERLAP_RECALCULATION, fixed_context_rows=-1)
    with pytest.raises(ValueError):
        UpdateStrategy("UNKNOWN")


def test_lookup_listing_and_aliases_use_canonical_specs() -> None:
    assert get_financial_tool_spec(" UTC ") is INDICATOR_SPECS["universal_trend_classifier"]
    assert get_financial_tool_spec("percent angle") is CONSTRUCT_SPECS["percent_span_angle"]
    assert list_financial_tool_specs() == tuple(ALL_FINANCIAL_TOOL_SPECS.values())
    assert tuple(spec.key for spec in list_financial_tool_specs("indicator")) == INDICATORS
    with pytest.raises(KeyError):
        get_financial_tool_spec("missing")
    with pytest.raises(ValueError):
        list_financial_tool_specs("other")


def test_parameter_resolution_applies_defaults_types_ranges_and_choices() -> None:
    values = resolve_parameters("bb", {"period": 20, "std": 3})
    assert values == {"period": 20, "std": 3.0}
    assert isinstance(values, MappingProxyType)
    with pytest.raises(TypeError):
        values["period"] = 30  # type: ignore[index]
    with pytest.raises(ValueError):
        resolve_parameters("bb", {"unknown": 1})
    with pytest.raises(ValueError):
        resolve_parameters("bb", {"period": True})
    with pytest.raises(ValueError):
        resolve_parameters("bb", {"std": False})
    with pytest.raises(ValueError):
        resolve_parameters("bb", {"period": 0})
    with pytest.raises(ValueError):
        resolve_parameters("angle", {"unit": "turns"})


def test_indicator_metadata_preserves_frozen_behavior_and_capabilities() -> None:
    assert get_financial_tool_spec("sma").edit_capabilities.preferred_module == "single_period"
    assert get_financial_tool_spec("kama").edit_capabilities.preferred_module == "dual_period"
    assert get_financial_tool_spec("bb").style_capabilities.supports_fill_between is True
    assert get_financial_tool_spec("hck").style_capabilities.supports_utility_style_drivers is True
    strategy = get_financial_tool_spec("strategy")
    assert len(strategy.parameters) == 16
    assert len(strategy.output_names) == 18
    peaks = get_financial_tool_spec("peaks_troughs")
    assert peaks.output.structure == "events"
    assert len(peaks.output_names) == 10


def test_universal_trend_classifier_preserves_fixed_outputs_and_semantics() -> None:
    spec = get_financial_tool_spec("universal_trend_classifier")
    assert len(spec.parameters) == 15
    assert len(spec.output_names) == 27
    signals = resolve_output_signals("utc")
    assert tuple(signal.name for signal in signals) == spec.output_names
    by_name = {signal.name: signal for signal in signals}
    assert by_name["horizontal_range"].value_type == "boolean"
    assert by_name["horizontal_range"].renderable is False
    assert by_name["hor_upper"].semantic_role == "range_upper"
    assert by_name["hr_break_direction"].value_type == "numeric"
    assert all(signal.can_drive_style_rules for signal in signals)


@pytest.mark.parametrize(
    ("key", "range_mode", "bounds", "guide_values"),
    (
        ("rsi", "fixed_bounds", (0.0, 100.0), (70.0, 50.0, 30.0)),
        ("arsi", "fixed_bounds", (0.0, 100.0), (80.0, 50.0, 20.0)),
        ("tdirsi", "fixed_bounds", (0.0, 100.0), (70.0, 50.0, 30.0)),
        ("smi", "auto", None, (0.0,)),
        ("mfi", "fixed_bounds", (0.0, 100.0), (70.0, 50.0, 30.0)),
        ("obv", "auto", None, ()),
        ("volume", "auto", None, ()),
    ),
)
def test_oscillator_visual_metadata_is_frozen(
    key: str, range_mode: str, bounds: tuple[float, float] | None, guide_values: tuple[float, ...]
) -> None:
    visual = get_financial_tool_spec(key).oscillator_visual
    assert visual is not None
    assert visual.range_mode == range_mode
    assert visual.bounds == bounds
    assert tuple(level.value for level in visual.guide_levels) == guide_values


def test_construct_metadata_preserves_nonvisual_and_binding_authority() -> None:
    dynamic = get_financial_tool_spec("dynamic_binning")
    assert dynamic.behavior.output_mode == "non-visual"
    assert dynamic.output.structure == "analysis-only"
    assert dynamic.output.accepts_empty is True
    assert dynamic.output_names == ()
    expected_bindings = {
        "derivative": "unary_source", "angle": "unary_source", "braids": "fast_mid_slow",
        "braid_instability": "fast_mid_slow", "delta": "fast_slow", "trap_area": "fast_mid_slow",
        "percent_span_angle": "multi_source", "angle_momentum": "multi_source",
    }
    for key, binding in expected_bindings.items():
        construct_io = get_financial_tool_spec(key).construct_io
        assert construct_io is not None
        assert construct_io.input_binding == binding


def test_validate_catalog_accepts_frozen_catalog() -> None:
    assert validate_catalog() is None


def test_model_literal_vocabularies_reject_unsupported_values() -> None:
    with pytest.raises(ValueError):
        ToolStyleCapabilities(("other",))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ToolEditCapabilities("other")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OscillatorGuideLevelSpec("other", 1.0)  # type: ignore[arg-type]
