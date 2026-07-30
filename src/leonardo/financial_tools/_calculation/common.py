from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


def _numeric_series(data: pd.DataFrame, column: str, *, context: str) -> pd.Series:
    if column not in data.columns:
        raise ValueError(f"{context} requires existing column {column!r}")
    source = data[column]
    if source.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError(f"{context} column {column!r} must be numeric or null")
    try:
        return pd.to_numeric(source, errors="raise").astype("float64")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} column {column!r} must be numeric or null") from exc


def _numeric_frame(data: pd.DataFrame, columns: Sequence[str], *, context: str) -> pd.DataFrame:
    return pd.DataFrame(
        {column: _numeric_series(data, column, context=context) for column in columns},
        index=data.index,
    )


def _source_columns(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a comma-separated string")
    columns = tuple(part.strip() for part in value.split(",") if part.strip())
    if not columns:
        raise ValueError(f"{context} must contain at least one source column")
    if len(columns) != len(set(columns)):
        raise ValueError(f"{context} must not contain duplicate source columns")
    return columns


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.astype("float64").ewm(span=period, adjust=False, min_periods=period).mean()


def _wma(series: pd.Series, window: int) -> pd.Series:
    weights = np.arange(1, window + 1, dtype="float64")
    return series.rolling(window=window, min_periods=window).apply(
        lambda values: float(np.dot(values, weights) / weights.sum()),
        raw=True,
    )


def _rma(series: pd.Series, period: int) -> pd.Series:
    values = series.to_numpy(dtype="float64", copy=False)
    output = np.full(len(values), np.nan, dtype="float64")
    valid_positions = np.flatnonzero(~np.isnan(values))
    if len(valid_positions) < period:
        return pd.Series(output, index=series.index)
    seed_pos = int(valid_positions[period - 1])
    seed = float(values[valid_positions[:period]].mean())
    output[seed_pos] = seed
    previous = seed
    alpha = 1.0 / period
    for position in range(seed_pos + 1, len(values)):
        value = values[position]
        if np.isnan(value):
            continue
        previous = alpha * float(value) + (1.0 - alpha) * previous
        output[position] = previous
    return pd.Series(output, index=series.index)


def _smooth(series: pd.Series, period: int, method: str) -> pd.Series:
    normalized = method.upper()
    if normalized == "EMA":
        return _ema(series, period)
    if normalized == "RMA":
        return _rma(series, period)
    if normalized == "SMA":
        return series.rolling(period, min_periods=period).mean()
    if normalized == "TMA":
        first = series.rolling(period, min_periods=period).mean()
        return first.rolling(period, min_periods=period).mean()
    raise ValueError(f"unsupported smoother: {method!r}")


def _ew_vwap(price: pd.Series, volume: pd.Series, length: int) -> pd.Series:
    denominator = volume.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    numerator = (price * volume).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    return (numerator / denominator).where(denominator != 0.0, np.nan)


def _fractal_extrema(series: pd.Series, *, window: int, peak: bool) -> pd.Series:
    half = window // 2
    values = series.astype("float64")
    mask = pd.Series(True, index=series.index, dtype=bool)
    for offset in range(1, half + 1):
        if peak:
            mask &= values.gt(values.shift(offset)) & values.gt(values.shift(-offset))
        else:
            mask &= values.lt(values.shift(offset)) & values.lt(values.shift(-offset))
    return values.where(mask, np.nan)


def _central_difference(series: pd.Series, order: int) -> pd.Series:
    values = series.astype("float64")
    axis = pd.Series(np.arange(len(values), dtype="float64"), index=series.index)
    result = pd.Series(np.nan, index=series.index, dtype="float64")
    valid = values.notna() & axis.notna()
    previous = values.shift(1)
    current = values
    following = values.shift(-1)
    axis_previous = axis.shift(1)
    axis_current = axis
    axis_following = axis.shift(-1)
    previous_step = axis_current - axis_previous
    following_step = axis_following - axis_current
    usable = (
        valid
        & valid.shift(1, fill_value=False)
        & valid.shift(-1, fill_value=False)
        & previous_step.notna()
        & following_step.notna()
        & previous_step.gt(0.0)
        & following_step.gt(0.0)
    )
    denominator = previous_step * following_step * (previous_step + following_step)
    if order == 1:
        numerator = (
            (previous_step**2) * following
            + ((following_step**2) - (previous_step**2)) * current
            - (following_step**2) * previous
        )
    else:
        numerator = 2.0 * (
            previous_step * following
            - (previous_step + following_step) * current
            + following_step * previous
        )
    result.loc[usable] = (numerator / denominator).loc[usable]
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value
