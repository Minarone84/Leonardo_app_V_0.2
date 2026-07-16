from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import calculate_financial_tool


def _frame(rows: int = 12) -> pd.DataFrame:
    x = np.arange(rows, dtype="float64")
    return pd.DataFrame({
        "ts_ms": x.astype("int64") + 1,
        "close": x**2 + 10.0,
        "fast": x + 3.0,
        "mid": x + 2.0,
        "slow": x + 1.0,
    })


def test_derivative_orders_and_nan_boundaries() -> None:
    data = _frame()
    first = calculate_financial_tool("derivative", data, {"order": 1}, bindings={"source": "close"}).to_frame()["close__d1"]
    second = calculate_financial_tool("derivative", data, {"order": 2}, bindings={"source": "close"}).to_frame()["close__d2"]
    assert pd.isna(first.iloc[0]) and pd.isna(first.iloc[-1])
    np.testing.assert_allclose(first.iloc[1:-1], 2.0 * np.arange(1, len(data) - 1))
    np.testing.assert_allclose(second.iloc[1:-1], 2.0)
    gap = data.copy(); gap.loc[5, "close"] = np.nan
    output = calculate_financial_tool("derivative", gap, bindings={"source": "close"}).to_frame()["close__d1"]
    assert output.iloc[4:7].isna().all()


def test_angle_degrees_and_radians() -> None:
    data = _frame()
    deg = calculate_financial_tool("angle", data, {"unit": "deg"}, bindings={"source": "close"}).to_frame()["close__ang"]
    rad = calculate_financial_tool("angle", data, {"unit": "rad"}, bindings={"source": "close"}).to_frame()["close__ang"]
    np.testing.assert_allclose(deg, np.degrees(rad), equal_nan=True, rtol=1e-6, atol=1e-6)


def test_braid_states_ties_policies_width_and_compression() -> None:
    data = _frame(8)
    data[["fast", "mid", "slow"]] = [
        [1, 2, 3], [2, 1, 3], [3, 1, 2], [3, 2, 1],
        [2, 3, 1], [1, 3, 2], [2, 2, 1], [np.nan, 4, 1],
    ]
    drop = calculate_financial_tool("braids", data, {"fast": "fast", "mid": "mid", "slow": "slow", "tie_policy": "drop"}).to_frame()
    carry = calculate_financial_tool("braids", data, {"fast": "fast", "mid": "mid", "slow": "slow", "tie_policy": "carry"}).to_frame()
    np.testing.assert_allclose(drop.iloc[:6, 1], [1, 2, 3, 4, 5, 6])
    assert drop.iloc[6:, 1].isna().all()
    assert carry.iloc[6:, 1].eq(6.0).all()
    np.testing.assert_allclose(drop.iloc[:, 2], [2, 2, 2, 2, 2, 2, 1, 3])
    np.testing.assert_allclose(drop.iloc[:, 3], [1, 1, 1, 1, 1, 1, 0, 3])


def test_braid_instability_uses_raw_state() -> None:
    data = _frame(7)
    data[["fast", "mid", "slow"]] = [[1, 2, 3], [1, 2, 3], [2, 2, 3], [1, 2, 3], [3, 2, 1], [3, 2, 1], [3, 2, 1]]
    output = calculate_financial_tool("braid_instability", data, {"fast": "fast", "mid": "mid", "slow": "slow", "n": 2}).to_frame().iloc[:, 1]
    assert output.iloc[:5].isna().all()
    assert output.iloc[5] == 0.5 and output.iloc[6] == 0.0


def test_delta_absolute_percent_and_epsilon() -> None:
    data = _frame(4)
    data["fast"] = [2, 3, 4, np.nan]; data["slow"] = [1, 0, -2, 1]
    absolute = calculate_financial_tool("delta", data, {"fast": "fast", "slow": "slow", "mode": "abs"}).to_frame().iloc[:, 1]
    percent = calculate_financial_tool("delta", data, {"fast": "fast", "slow": "slow", "mode": "pct", "eps": 0.5}).to_frame().iloc[:, 1]
    np.testing.assert_allclose(absolute, [1, 3, 6, np.nan], equal_nan=True)
    np.testing.assert_allclose(percent, [100, 600, 300, np.nan], equal_nan=True)
    with pytest.raises(ValueError):
        calculate_financial_tool("delta", data, {"fast": "fast", "slow": "slow", "mode": "pct", "eps": 0.0})


def test_trap_area_resets_at_sign_zero_and_gap() -> None:
    data = _frame(9)
    data["fast"] = [2, 3, 4, 1, 1, np.nan, 3, 4, 5]
    data["slow"] = [1, 1, 1, 1, 2, 1, 1, 1, 1]
    output = calculate_financial_tool("trap_area", data, {"fast": "fast", "mid": None, "slow": "slow", "zero_eps": 0.0}).to_frame().iloc[:, 1]
    np.testing.assert_allclose(output, [0, 1.5, 4, 0, 0, np.nan, 0, 2.5, 6], equal_nan=True)


def test_percent_span_requires_contiguous_window_and_momentum_lag() -> None:
    data = _frame(8)
    data.loc[3, "close"] = np.nan
    percent = calculate_financial_tool("percent_span_angle", data, {"source_columns": "close", "window": 3, "unit": "deg"}).to_frame().iloc[:, 1]
    assert percent.iloc[:2].isna().all() and percent.iloc[3:6].isna().all()
    momentum = calculate_financial_tool("angle_momentum", _frame(8), {"source_columns": "close", "n": 2}).to_frame().iloc[:, 1]
    assert momentum.iloc[:2].isna().all()
    np.testing.assert_allclose(momentum.iloc[2:], (np.arange(2, 8) ** 2 - np.arange(0, 6) ** 2) / 2.0)


def test_dynamic_binning_payload_and_source_rejection() -> None:
    data = _frame(20)
    result = calculate_financial_tool("dynamic_binning", data, {"source_columns": "close,fast", "window": 4})
    assert result.output_names == ()
    assert tuple(result.to_frame().columns) == ("ts_ms",)
    assert set(result.analysis) == {"steps", "variation_diagnostics", "binning_artifact", "labeled_rows"}
    with pytest.raises(ValueError):
        calculate_financial_tool("dynamic_binning", data, {"source_columns": "missing", "window": 4})
    with pytest.raises(ValueError):
        calculate_financial_tool("percent_span_angle", data, {"source_columns": "close", "window": 1})
    with pytest.raises(ValueError):
        calculate_financial_tool("braids", data, {"fast": "fast", "mid": None, "slow": "slow"})
