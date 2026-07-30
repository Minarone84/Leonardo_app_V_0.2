from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .common import _ema, _numeric_series, _rma, _smooth


def _rsi_values(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    average_gain = _rma(gain, period)
    average_loss = _rma(loss, period)
    ratio = average_gain / average_loss.replace(0.0, np.nan)
    values = 100.0 - 100.0 / (1.0 + ratio)
    values = values.mask((average_gain > 0.0) & (average_loss == 0.0), 100.0)
    values = values.mask((average_gain == 0.0) & (average_loss > 0.0), 0.0)
    values = values.mask((average_gain == 0.0) & (average_loss == 0.0), 50.0)
    return values


def _calculate_rsi(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="rsi")
    return (_rsi_values(close, int(parameters["period"])),), {}


def _calculate_arsi(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="arsi")
    period = int(parameters["period"])
    upper = close.rolling(period, min_periods=period).max()
    lower = close.rolling(period, min_periods=period).min()
    price_range = upper - lower
    upper_break = upper > upper.shift(1)
    lower_break = lower < lower.shift(1)
    difference = close.diff().mask(upper_break, price_range).mask(~upper_break & lower_break, -price_range)
    numerator = _smooth(difference, period, str(parameters["method"]))
    denominator = _smooth(difference.abs(), period, str(parameters["method"]))
    arsi = 50.0 + 50.0 * (numerator / denominator.replace(0.0, np.nan))
    arsi = arsi.mask((numerator == 0.0) & (denominator == 0.0), 50.0)
    arsi = arsi.replace([np.inf, -np.inf], np.nan).clip(0.0, 100.0)
    signal = _smooth(arsi, int(parameters["signal_period"]), str(parameters["signal_method"]))
    return (arsi, signal), {}


def _calculate_tdirsi(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="tdirsi")
    # OLD TDI consumes the finalized public RSI line after float32
    # conversion, then promotes it for subsequent rolling calculations.
    # This explicit quantization boundary preserves donor-exact behavior.
    rsi = _rsi_values(
        close,
        int(parameters["period"]),
    ).astype("float32").astype("float64")
    band_length = int(parameters["band_length"])
    basis = rsi.rolling(band_length, min_periods=band_length).mean()
    deviation = rsi.rolling(band_length, min_periods=band_length).std(ddof=0)
    offset = float(parameters["band_mult"]) * deviation
    fast = _smooth(rsi, int(parameters["fast_len"]), str(parameters["fast_smo"]))
    slow = _smooth(rsi, int(parameters["slow_len"]), str(parameters["slow_smo"]))
    upper = basis + offset
    lower = basis - offset
    return (fast, slow, upper, lower, (upper + lower) / 2.0), {}


def _calculate_smi(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    high = _numeric_series(data, "high", context="smi")
    low = _numeric_series(data, "low", context="smi")
    close = _numeric_series(data, "close", context="smi")
    k_length = int(parameters["k_length"])
    d_length = int(parameters["d_length"])
    lowest = low.rolling(k_length, min_periods=k_length).min()
    highest = high.rolling(k_length, min_periods=k_length).max()
    price_range = highest - lowest
    relative = close - (highest + lowest) / 2.0
    average_relative = _ema(_ema(relative, d_length), d_length)
    average_range = _ema(_ema(price_range, d_length), d_length)
    smi = (average_relative / (average_range / 2.0) * 100.0).where(average_range != 0.0, 0.0)
    return (smi, _ema(smi, d_length)), {}


def _calculate_mfi(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    high = _numeric_series(data, "high", context="mfi")
    low = _numeric_series(data, "low", context="mfi")
    close = _numeric_series(data, "close", context="mfi")
    volume = _numeric_series(data, "volume", context="mfi")
    period = int(parameters["period"])
    typical = (high + low + close) / 3.0
    direction = typical.diff()
    raw_flow = typical * volume
    positive = raw_flow.where(direction > 0.0, 0.0).rolling(period, min_periods=period).sum()
    negative = raw_flow.where(direction < 0.0, 0.0).rolling(period, min_periods=period).sum()
    ratio = positive / negative.replace(0.0, np.nan)
    values = 100.0 - 100.0 / (1.0 + ratio)
    values = values.mask((positive > 0.0) & (negative == 0.0), 100.0)
    values = values.mask((positive == 0.0) & (negative > 0.0), 0.0)
    values = values.mask((positive == 0.0) & (negative == 0.0), 50.0)
    return (values,), {}


def _calculate_obv(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="obv")
    volume = _numeric_series(data, "volume", context="obv")
    direction = np.sign(close.diff()).fillna(0.0)
    return ((direction * volume).fillna(0.0).cumsum(),), {}


def _calculate_volume(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    volume = _numeric_series(data, "volume", context="volume")
    period = int(parameters["period"])
    return (volume, volume.rolling(period, min_periods=period).mean()), {}
