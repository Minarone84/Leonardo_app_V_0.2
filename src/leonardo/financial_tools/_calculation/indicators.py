from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .common import _ema, _ew_vwap, _fractal_extrema, _numeric_series, _wma


def _empty_analysis() -> dict[str, object]:
    return {}


def _sma_values(source: pd.Series, period: int) -> pd.Series:
    return source.rolling(period, min_periods=period).mean()


def _calculate_sma(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="sma")
    period = int(parameters["period"])
    return (_sma_values(close, period),), _empty_analysis()


def _calculate_ema(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    return (_ema(_numeric_series(data, "close", context="ema"), int(parameters["period"])),), _empty_analysis()


def _calculate_tema(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    period = int(parameters["period"])
    first = _ema(_numeric_series(data, "close", context="tema"), period)
    second = _ema(first, period)
    third = _ema(second, period)
    tema = (3.0 * first - 3.0 * second + third).where(third.notna(), np.nan)
    return (tema,), _empty_analysis()


def _calculate_hma(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="hma")
    period = int(parameters["period"])
    half = max(1, int(period / 2))
    root = max(1, int(np.sqrt(period)))
    return (_wma(2.0 * _wma(close, half) - _wma(close, period), root),), _empty_analysis()


def _calculate_kama(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="kama")
    fast_period = int(parameters["fast_period"])
    slow_period = int(parameters["slow_period"])
    change = close.diff(slow_period).abs()
    volatility = close.diff().abs().rolling(slow_period, min_periods=slow_period).sum()
    efficiency = (change / (volatility + 1e-12)).clip(0.0, 1.0).fillna(0.0)
    fastest = 2.0 / (fast_period + 1.0)
    slowest = 2.0 / (slow_period + 1.0)
    smoothing = (efficiency * (fastest - slowest) + slowest) ** 2
    seed = close.rolling(slow_period, min_periods=slow_period).mean()
    values = np.full(len(close), np.nan, dtype="float64")
    start = slow_period - 1
    if start < len(close) and np.isfinite(seed.iloc[start]):
        values[start] = float(seed.iloc[start])
        for position in range(start + 1, len(close)):
            values[position] = values[position - 1] + smoothing.iloc[position] * (
                close.iloc[position] - values[position - 1]
            )
    return (pd.Series(values, index=data.index),), _empty_analysis()


def _bb_values(close: pd.Series, period: int, multiplier: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(period, min_periods=period).mean()
    sigma = close.rolling(period, min_periods=period).std(ddof=0)
    return middle, middle + multiplier * sigma, middle - multiplier * sigma


def _calculate_bb(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    values = _bb_values(
        _numeric_series(data, "close", context="bb"),
        int(parameters["period"]),
        float(parameters["std"]),
    )
    return values, _empty_analysis()


def _hck_values(data: pd.DataFrame, fast_length: int, slow_length: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = _numeric_series(data, "high", context="hck")
    low = _numeric_series(data, "low", context="hck")
    close = _numeric_series(data, "close", context="hck")
    volume = _numeric_series(data, "volume", context="hck")
    typical = (high + low + close) / 3.0
    fast = _ew_vwap(typical, volume, fast_length)
    slow = _ew_vwap(typical, volume, slow_length)
    color = pd.Series("silver", index=data.index, dtype=object)
    color.loc[fast > slow] = "green"
    color.loc[fast < slow] = "red"
    return fast, slow, color


def _calculate_hck(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    return _hck_values(data, int(parameters["fast_vwap_l"]), int(parameters["slow_vwap_l"])), _empty_analysis()


def _calculate_strategy(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    close = _numeric_series(data, "close", context="strategy")
    values: list[pd.Series] = []
    values.extend(_ema(close, int(parameters[f"ema_{slot}_period"])) for slot in range(1, 7))
    values.extend(
        _sma_values(close, int(parameters[f"sma_{slot}_period"]))
        for slot in range(1, 7)
    )
    values.extend(_bb_values(close, int(parameters["bb_period"]), float(parameters["bb_std"])))
    values.extend(_hck_values(data, int(parameters["hck_fast_vwap_l"]), int(parameters["hck_slow_vwap_l"])))
    return tuple(values), _empty_analysis()


def _peaks_troughs_values(data: pd.DataFrame) -> tuple[pd.Series, ...]:
    high = _numeric_series(data, "high", context="peaks_troughs")
    low = _numeric_series(data, "low", context="peaks_troughs")
    values: list[pd.Series] = []
    for window in (3, 5, 7, 9, 11):
        values.append(_fractal_extrema(high, window=window, peak=True))
        values.append(_fractal_extrema(low, window=window, peak=False))
    return tuple(values)


def _calculate_peaks_troughs(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    return _peaks_troughs_values(data), _empty_analysis()
