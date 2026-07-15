from __future__ import annotations

from types import MappingProxyType

import pytest

from leonardo.financial_tools import (
    CANONICAL_TOOL_ALIASES,
    build_source_token,
    canonicalize_tool_key,
    resolve_output_names,
    resolve_output_signals,
)


def test_exact_canonical_aliases() -> None:
    assert isinstance(CANONICAL_TOOL_ALIASES, MappingProxyType)
    assert CANONICAL_TOOL_ALIASES == {
        "utc": "universal_trend_classifier",
        "dynamic_binning_analysis": "dynamic_binning",
        "derivative_analysis": "derivative",
        "angle_analysis": "angle",
        "braid_state_analysis": "braids",
        "trap_area_analysis": "trap_area",
        "percent_angle": "percent_span_angle",
        "percent_angle_analysis": "percent_span_angle",
        "percent_span_angle_analysis": "percent_span_angle",
    }
    assert canonicalize_tool_key("Percent Span Angle Analysis") == "percent_span_angle"
    assert canonicalize_tool_key("slope") == "slope"
    with pytest.raises(TypeError):
        CANONICAL_TOOL_ALIASES["new"] = "sma"  # type: ignore[index]
    with pytest.raises(ValueError):
        canonicalize_tool_key("  ")


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("close", "close"),
        ("EMA 14 Close", "ema_14_close"),
        ("rsi(14)_close", "rsi_14_close"),
        ("close__ang", "close__ang"),
        ("close__dlt__ema_14", "close__dlt__ema_14"),
        ("", "unknown"),
    ),
)
def test_build_source_token_preserves_donor_behavior(source: object, expected: str) -> None:
    assert build_source_token(source) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    (
        ("sma", ("sma_14",)), ("ema", ("ema_14",)), ("tema", ("tema_14",)),
        ("hma", ("hma_14",)), ("kama", ("kama_2_30",)),
        ("bb", ("bb_middle", "bb_upper_band", "bb_lower_band")),
        ("hck", ("fast_vwap", "slow_vwap", "vwap_color")),
        ("peaks_troughs", tuple(name for length in (3, 5, 7, 9, 11)
                                 for name in (f"peak_fractal_{length}", f"trough_fractal_{length}"))),
        ("rsi", ("rsi_14",)),
        ("arsi", ("arsi_14_rma", "arsi_signal_14_rma_14_ema")),
        ("tdirsi", ("tdirsi_fast_ma_14_34_2_7_ema_rma", "tdirsi_slow_ma_14_34_2_7_ema_rma",
                    "tdirsi_up_14_34_2_7_ema_rma", "tdirsi_dn_14_34_2_7_ema_rma",
                    "tdirsi_mid_14_34_2_7_ema_rma")),
        ("smi", ("smi_14_3", "smi_signal_14_3")),
        ("mfi", ("mfi_14",)), ("obv", ("obv",)),
        ("volume", ("volume", "volume_mean_20")),
        ("dynamic_binning", ()),
        ("percent_span_angle", ("close_ang_pct_span_10",)),
        ("angle_momentum", ("close_ang_mtm_3",)),
    ),
)
def test_default_output_names_cover_static_and_default_bound_tools(key: str, expected: tuple[str, ...]) -> None:
    assert resolve_output_names(key) == expected


def test_strategy_and_utc_fixed_output_names() -> None:
    strategy = resolve_output_names("strategy")
    assert strategy[:2] == ("st_ema_1", "st_ema_2")
    assert strategy[-3:] == ("st_fast_vwap", "st_slow_vwap", "st_vwap_color")
    assert len(strategy) == 18
    utc = resolve_output_names("utc")
    assert utc[:5] == ("horizontal_range", "hr_start", "hr_end", "hor_upper", "hor_lower")
    assert utc[-3:] == ("hr_break_direction", "hr_break_extreme", "hr_reclaim_marker")
    assert len(utc) == 27


def test_parameterized_indicator_and_oscillator_names() -> None:
    assert resolve_output_names("ema", {"period": 20}) == ("ema_20",)
    assert resolve_output_names("rsi", {"period": 14}) == ("rsi_14",)
    assert resolve_output_names("volume", {"period": 50}) == ("volume", "volume_mean_50")


def test_construct_output_names_preserve_donor_runtime_policy() -> None:
    assert resolve_output_names("derivative", {"source": "close", "order": 1}) == ("close__d1",)
    assert resolve_output_names("derivative_analysis", {"source": "EMA 14", "order": 2}) == ("ema_14__d2",)
    assert resolve_output_names("angle", {"source": "close"}) == ("close__ang",)
    assert resolve_output_names("braids", {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"}) == (
        "ema_9_ema_20_ema_50", "ema_9_ema_20_ema_50_width", "ema_9_ema_20_ema_50_compression",
    )
    assert resolve_output_names("braid_instability", {
        "fast": "ema_9", "mid": "ema_20", "slow": "ema_50", "n": 8,
    }) == ("ema_9_ema_20_ema_50_inst_8",)
    assert resolve_output_names("delta", {"fast": "ema_9", "slow": "ema_20"}) == ("ema_9_ema_20_delta",)
    assert resolve_output_names("delta", {"fast": "ema_9", "slow": "ema_20", "mode": "pct"}) == (
        "ema_9_ema_20_delta_pct",
    )
    assert resolve_output_names("trap_area_analysis", {"fast": "ema_9", "slow": "ema_50"}) == (
        "ema_9_ema_50_trapA",
    )
    assert resolve_output_names("trap_area", {
        "fast": "ema_9", "mid": "ema_20", "slow": "ema_50",
    }) == ("ema_9_ema_20_trapA", "ema_9_ema_50_trapA", "ema_20_ema_50_trapA")
    assert resolve_output_names("percent_angle", {"source_columns": "close, ema_20", "window": 5}) == (
        "close_ang_pct_span_5", "ema_20_ang_pct_span_5",
    )
    assert resolve_output_names("angle_momentum", {"source_columns": "close__ang, ema_20__ang", "n": 4}) == (
        "close__ang_ang_mtm_4", "ema_20__ang_ang_mtm_4",
    )


def test_invalid_or_missing_construct_sources_are_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_output_names("derivative")
    with pytest.raises(ValueError):
        resolve_output_names("delta")
    with pytest.raises(ValueError):
        resolve_output_names("braids", {"fast": "ema_9", "slow": "ema_50"})
    with pytest.raises(ValueError):
        resolve_output_names("percent_span_angle", {"source_columns": ""})
    with pytest.raises(KeyError):
        resolve_output_names("slope")


def test_resolved_output_signals_use_resolved_names_and_semantics() -> None:
    signals = resolve_output_signals("braids", {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"})
    assert tuple(signal.name for signal in signals) == resolve_output_names(
        "braids", {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"}
    )
    assert signals[0].value_type == "categorical"
    assert signals[1].renderable is False
    assert resolve_output_signals("dynamic_binning") == ()


def test_naming_is_deterministic_and_does_not_mutate_parameter_mapping() -> None:
    parameters = {"fast": "ema_9", "mid": "ema_20", "slow": "ema_50"}
    original = dict(parameters)
    first = resolve_output_names("braids", parameters)
    second = resolve_output_names("braids", parameters)
    assert first == second
    assert parameters == original


def test_unknown_output_name_key_raises_key_error() -> None:
    with pytest.raises(KeyError):
        resolve_output_names("not_a_tool")
