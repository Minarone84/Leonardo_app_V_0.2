from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import calculate_financial_tool
from leonardo.financial_tools._calculation import indicators


def _frame(rows: int = 96) -> pd.DataFrame:
    x = np.arange(rows, dtype="float64")
    close = 100.0 + x + np.sin(x / 4.0)
    return pd.DataFrame({
        "ts_ms": 1_700_000_000_000 + x.astype("int64") * 60_000,
        "open": close - 0.2, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": 1_000.0 + x * 3.0,
    })


@pytest.mark.parametrize("tool,first_valid", (("sma", 4), ("ema", 4), ("tema", 12), ("hma", 5)))
def test_moving_average_warm_up(tool: str, first_valid: int) -> None:
    result = calculate_financial_tool(tool, _frame(), {"period": 5}).to_frame().iloc[:, 1]
    assert result.iloc[:first_valid].isna().all()
    assert result.iloc[first_valid:].notna().all()


def test_kama_seed_and_bb_population_standard_deviation() -> None:
    data = _frame()
    kama = calculate_financial_tool("kama", data, {"fast_period": 2, "slow_period": 5}).to_frame()["kama_2_5"]
    assert kama.iloc[:4].isna().all() and kama.iloc[4:].notna().all()
    bb = calculate_financial_tool("bb", data, {"period": 3, "std": 2.0}).to_frame()
    expected_mid = data.close.rolling(3, min_periods=3).mean()
    expected_sigma = data.close.rolling(3, min_periods=3).std(ddof=0)
    np.testing.assert_allclose(bb.bb_middle, expected_mid, equal_nan=True)
    np.testing.assert_allclose(bb.bb_upper_band, expected_mid + 2.0 * expected_sigma, equal_nan=True)


def test_hck_ew_vwap_and_colors() -> None:
    data = _frame()
    result = calculate_financial_tool("hck", data, {"fast_vwap_l": 2, "slow_vwap_l": 3}).to_frame()
    typical = (data.high + data.low + data.close) / 3.0
    expected = (
        (typical * data.volume).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
        / data.volume.ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    )
    np.testing.assert_allclose(result.fast_vwap, expected, equal_nan=True)
    assert set(result.vwap_color) <= {"red", "silver", "green"}


def test_strategy_composes_standalone_outputs() -> None:
    data = _frame(420)
    strategy = calculate_financial_tool("strategy", data).to_frame()
    ema = calculate_financial_tool("ema", data, {"period": 9}).to_frame()["ema_9"]
    sma = calculate_financial_tool("sma", data, {"period": 9}).to_frame()["sma_9"]
    bb = calculate_financial_tool("bb", data, {"period": 20, "std": 2.0}).to_frame()
    hck = calculate_financial_tool("hck", data, {"fast_vwap_l": 13, "slow_vwap_l": 48}).to_frame()
    np.testing.assert_allclose(strategy.st_ema_1, ema, equal_nan=True)
    np.testing.assert_allclose(strategy.st_sma_1, sma, equal_nan=True)
    np.testing.assert_allclose(strategy.st_bb_middle, bb.bb_middle, equal_nan=True)
    np.testing.assert_allclose(strategy.st_fast_vwap, hck.fast_vwap, equal_nan=True)
    assert strategy.st_vwap_color.tolist() == hck.vwap_color.tolist()


def test_standalone_and_strategy_share_one_sma_formula_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _frame(420)
    periods: list[int] = []

    def recording_sma(source: pd.Series, period: int) -> pd.Series:
        periods.append(period)
        return source.rolling(period, min_periods=period).mean()

    monkeypatch.setattr(indicators, "_sma_values", recording_sma)
    calculate_financial_tool("sma", data, {"period": 7})
    calculate_financial_tool("strategy", data)
    assert periods == [7, 9, 20, 50, 100, 200, 400]


def test_peaks_and_troughs_require_strict_confirmed_neighbors() -> None:
    data = _frame(12)
    data["high"] = [1, 2, 1, 2, 2, 1, 1, 3, 1, 1, 1, 1]
    data["low"] = [3, 2, 3, 2, 2, 3, 3, 1, 3, 3, 3, 3]
    result = calculate_financial_tool("peaks_troughs", data).to_frame()
    assert result.peak_fractal_3.notna().to_numpy().nonzero()[0].tolist() == [1, 7]
    assert result.trough_fractal_3.notna().to_numpy().nonzero()[0].tolist() == [1, 7]
    assert pd.isna(result.peak_fractal_11.iloc[-1])


def test_utc_internal_dependencies_and_output_types() -> None:
    data = _frame(160)
    original = data.copy(deep=True)
    result = calculate_financial_tool("universal_trend_classifier", data)
    pd.testing.assert_frame_equal(data, original)
    frame = result.to_frame()
    assert len(result.output_names) == 27
    assert tuple(frame.columns) == ("ts_ms", *result.output_names)
    assert frame.horizontal_range.dtype == bool
    assert frame.hor_upper.dtype == np.dtype("float32")


def test_utc_custom_dependency_pair_validation() -> None:
    data = _frame(160)
    with pytest.raises(ValueError):
        calculate_financial_tool("universal_trend_classifier", data, {"peak_column": "peak"})
    with pytest.raises(ValueError):
        calculate_financial_tool(
            "universal_trend_classifier", data,
            {"peak_column": "peak", "trough_column": "trough"},
        )
    custom = data.assign(peak=np.nan, trough=np.nan)
    result = calculate_financial_tool(
        "universal_trend_classifier", custom,
        {"peak_column": "peak", "trough_column": "trough"},
    )
    assert result.row_count == len(custom)
    with pytest.raises(ValueError):
        calculate_financial_tool(
            "universal_trend_classifier", data,
            {"fractal_window": 5, "trend_fractal_window": 7},
        )


def test_utc_custom_trend_dependencies_are_isolated_from_range_name_collisions() -> None:
    data = _frame(240)
    custom_peak = pd.Series(np.nan, index=data.index, dtype="float64")
    custom_trough = pd.Series(np.nan, index=data.index, dtype="float64")
    for position in range(8, len(data) - 8, 8):
        if (position // 8) % 2:
            custom_peak.iloc[position] = data.high.iloc[position] + 3.0
        else:
            custom_trough.iloc[position] = data.low.iloc[position] - 3.0

    non_colliding = data.assign(custom_peak=custom_peak, custom_trough=custom_trough)
    colliding = data.assign(peak_fractal_5=custom_peak, trough_fractal_5=custom_trough)
    non_colliding_before = non_colliding.copy(deep=True)
    colliding_before = colliding.copy(deep=True)
    common = {"fractal_window": 5, "trend_fractal_window": 5, "range_fractal_window": 5}

    expected = calculate_financial_tool(
        "universal_trend_classifier",
        non_colliding,
        {**common, "peak_column": "custom_peak", "trough_column": "custom_trough"},
    ).to_frame()
    collision = calculate_financial_tool(
        "universal_trend_classifier",
        colliding,
        {**common, "peak_column": "peak_fractal_5", "trough_column": "trough_fractal_5"},
    ).to_frame()
    internal = calculate_financial_tool("universal_trend_classifier", data, common).to_frame()

    pd.testing.assert_frame_equal(collision, expected)
    assert not expected.equals(internal)
    pd.testing.assert_frame_equal(non_colliding, non_colliding_before)
    pd.testing.assert_frame_equal(colliding, colliding_before)
