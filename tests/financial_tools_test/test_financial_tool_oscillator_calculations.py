from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from leonardo.financial_tools import calculate_financial_tool
from leonardo.financial_tools._calculation.common import _rma, _smooth
from leonardo.financial_tools._calculation.oscillators import _rsi_values


FIXTURES = Path(__file__).with_name("fixtures")


def _frame(close: list[float], volume: list[float] | None = None) -> pd.DataFrame:
    values = np.asarray(close, dtype="float64")
    volumes = np.asarray(volume if volume is not None else [10.0] * len(values))
    return pd.DataFrame({
        "ts_ms": np.arange(len(values), dtype="int64") + 1,
        "high": values + 1.0, "low": values - 1.0, "close": values, "volume": volumes,
    })


def test_rma_uses_exact_old_wilder_operation_order() -> None:
    values = pd.Series([np.nan, 1.0, 2.0, 3.0, 4.0, np.nan, 5.0, 6.0])
    actual = _rma(values, 3).to_numpy()
    expected = np.asarray(
        [
            np.nan,
            np.nan,
            np.nan,
            float.fromhex("0x1.0000000000000p+1"),
            float.fromhex("0x1.5555555555556p+1"),
            np.nan,
            float.fromhex("0x1.b8e38e38e38e4p+1"),
            float.fromhex("0x1.12f684bda12f7p+2"),
        ],
        dtype="float64",
    )
    np.testing.assert_array_equal(actual, expected)


def test_tdirsi_default_output_matches_exact_donor_fixture() -> None:
    data = pd.read_csv(
        FIXTURES / "task_1015_characterization_input.csv",
        float_precision="round_trip",
    )
    record = json.loads(
        (FIXTURES / "task_1015_characterization_expected.json").read_text(
            encoding="utf-8"
        )
    )["tools"]["tdirsi"]
    result = calculate_financial_tool(
        "tdirsi",
        data,
        record["parameters"],
        bindings=record["bindings"],
    ).to_frame()
    for output_name, expected_values in record["outputs"].items():
        expected = np.asarray(
            [
                np.nan if value is None else np.float32(value)
                for value in expected_values
            ],
            dtype="float32",
        )
        assert result[output_name].dtype == np.dtype("float32")
        np.testing.assert_array_equal(
            result[output_name].to_numpy(dtype="float32", copy=False),
            expected,
        )


def test_tdirsi_preserves_old_public_rsi_float32_boundary() -> None:
    data = pd.read_csv(
        FIXTURES / "task_1015_characterization_input.csv",
        float_precision="round_trip",
    )
    record = json.loads(
        (FIXTURES / "task_1015_characterization_expected.json").read_text(
            encoding="utf-8"
        )
    )["tools"]["tdirsi"]
    parameters = record["parameters"]
    rsi = _rsi_values(data["close"].astype("float64"), int(parameters["period"]))
    donor_input = rsi.astype("float32").astype("float64")
    band_length = int(parameters["band_length"])
    basis = donor_input.rolling(band_length, min_periods=band_length).mean()
    deviation = donor_input.rolling(band_length, min_periods=band_length).std(ddof=0)
    offset = float(parameters["band_mult"]) * deviation
    upper = basis + offset
    lower = basis - offset
    expected = (
        _smooth(
            donor_input,
            int(parameters["fast_len"]),
            str(parameters["fast_smo"]),
        ),
        _smooth(
            donor_input,
            int(parameters["slow_len"]),
            str(parameters["slow_smo"]),
        ),
        upper,
        lower,
        (upper + lower) / 2.0,
    )
    unquantized_basis = rsi.rolling(
        band_length,
        min_periods=band_length,
    ).mean()
    unquantized_deviation = rsi.rolling(
        band_length,
        min_periods=band_length,
    ).std(ddof=0)
    unquantized_offset = float(parameters["band_mult"]) * unquantized_deviation
    unquantized_upper = unquantized_basis + unquantized_offset
    unquantized_lower = unquantized_basis - unquantized_offset
    unquantized = (
        _smooth(rsi, int(parameters["fast_len"]), str(parameters["fast_smo"])),
        _smooth(rsi, int(parameters["slow_len"]), str(parameters["slow_smo"])),
        unquantized_upper,
        unquantized_lower,
        (unquantized_upper + unquantized_lower) / 2.0,
    )
    production = calculate_financial_tool(
        "tdirsi",
        data,
        parameters,
        bindings=record["bindings"],
    ).to_frame()
    differs_from_unquantized = False
    for output_name, expected_values, unquantized_values in zip(
        record["output_names"],
        expected,
        unquantized,
        strict=True,
    ):
        actual = production[output_name].to_numpy(dtype="float32", copy=False)
        expected_array = expected_values.to_numpy(dtype="float32", copy=False)
        unquantized_array = unquantized_values.to_numpy(
            dtype="float32",
            copy=False,
        )
        np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected_array))
        valid = ~np.isnan(actual)
        np.testing.assert_array_equal(
            actual[valid].view(np.uint32),
            expected_array[valid].view(np.uint32),
        )
        differs_from_unquantized |= bool(
            np.any(
                actual[valid].view(np.uint32)
                != unquantized_array[valid].view(np.uint32)
            )
        )
    assert differs_from_unquantized


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
