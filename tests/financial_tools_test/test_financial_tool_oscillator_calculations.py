from __future__ import annotations

import numpy as np
import pandas as pd

from leonardo.financial_tools import calculate_financial_tool


def _frame(close: list[float], volume: list[float] | None = None) -> pd.DataFrame:
    values = np.asarray(close, dtype="float64")
    volumes = np.asarray(volume if volume is not None else [10.0] * len(values))
    return pd.DataFrame({
        "ts_ms": np.arange(len(values), dtype="int64") + 1,
        "high": values + 1.0, "low": values - 1.0, "close": values, "volume": volumes,
    })


def test_rsi_strict_wilder_seed_and_edges() -> None:
    rising = calculate_financial_tool("rsi", _frame([1, 2, 3, 4, 5, 6]), {"period": 3}).to_frame()["rsi_3"]
    falling = calculate_financial_tool("rsi", _frame([6, 5, 4, 3, 2, 1]), {"period": 3}).to_frame()["rsi_3"]
    flat = calculate_financial_tool("rsi", _frame([2, 2, 2, 2, 2, 2]), {"period": 3}).to_frame()["rsi_3"]
    assert rising.iloc[:3].isna().all() and rising.iloc[3:].eq(100.0).all()
    assert falling.iloc[3:].eq(0.0).all()
    assert flat.iloc[3:].eq(50.0).all()


def test_arsi_smoothers_and_flat_edge() -> None:
    data = _frame([2.0] * 20)
    for method in ("EMA", "RMA", "SMA", "TMA"):
        result = calculate_financial_tool(
            "arsi", data,
            {"period": 3, "method": method, "signal_period": 2, "signal_method": method},
        ).to_frame()
        assert result.iloc[:, 1].dropna().eq(50.0).all()


def test_tdirsi_order_and_smoothing() -> None:
    data = _frame(list(map(float, range(1, 81))))
    result = calculate_financial_tool(
        "tdirsi", data,
        {"period": 3, "band_length": 4, "fast_len": 2, "slow_len": 3,
         "fast_smo": "SMA", "slow_smo": "EMA", "band_mult": 1.5},
    )
    assert result.output_names == (
        "tdirsi_fast_ma_3_4_2_3_sma_ema", "tdirsi_slow_ma_3_4_2_3_sma_ema",
        "tdirsi_up_3_4_2_3_sma_ema", "tdirsi_dn_3_4_2_3_sma_ema",
        "tdirsi_mid_3_4_2_3_sma_ema",
    )
    assert result.to_frame().iloc[:, 1:].notna().any().all()


def test_smi_zero_range_is_zero() -> None:
    data = _frame([5.0] * 30)
    result = calculate_financial_tool("smi", data, {"k_length": 3, "d_length": 2}).to_frame()
    assert result.iloc[:, 1].dropna().eq(0.0).all()
    assert result.iloc[:, 2].dropna().eq(0.0).all()


def test_mfi_edges() -> None:
    rising = calculate_financial_tool("mfi", _frame([1, 2, 3, 4, 5]), {"period": 2}).to_frame()["mfi_2"]
    falling = calculate_financial_tool("mfi", _frame([5, 4, 3, 2, 1]), {"period": 2}).to_frame()["mfi_2"]
    flat = calculate_financial_tool("mfi", _frame([3, 3, 3, 3, 3]), {"period": 2}).to_frame()["mfi_2"]
    assert rising.iloc[1:].eq(100.0).all()
    assert falling.iloc[1:].eq(0.0).all()
    assert flat.iloc[1:].eq(50.0).all()


def test_obv_first_row_and_signs() -> None:
    data = _frame([10, 11, 10, 10, 12], [1, 2, 3, 4, 5])
    result = calculate_financial_tool("obv", data).to_frame()["obv"]
    np.testing.assert_allclose(result, [0, 2, -1, -1, 4])


def test_volume_mean_warm_up() -> None:
    data = _frame([1, 2, 3, 4], [10, 20, 30, 40])
    result = calculate_financial_tool("volume", data, {"period": 3}).to_frame()
    np.testing.assert_allclose(result.volume, data.volume)
    assert result.volume_mean_3.iloc[:2].isna().all()
    np.testing.assert_allclose(result.volume_mean_3.iloc[2:], [20, 30])
