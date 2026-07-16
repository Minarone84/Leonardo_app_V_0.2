from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .common import _central_difference, _numeric_frame, _numeric_series, _source_columns


def _calculate_derivative(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    source = str(bindings["source"])
    return (_central_difference(_numeric_series(data, source, context="derivative"), int(parameters["order"])),), {}


def _calculate_angle(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    source_name = str(bindings["source"])
    source = _numeric_series(data, source_name, context="angle")
    derivative = _central_difference(source, 1)
    denominator = source.abs().clip(lower=1e-12)
    values = np.arctan((derivative / denominator) * 100.0)
    if parameters["unit"] == "deg":
        values = np.degrees(values)
    return (pd.Series(values, index=data.index),), {}


def _role_frame(data: pd.DataFrame, parameters: Mapping[str, object], *, context: str) -> pd.DataFrame:
    names = tuple(str(parameters[role]).strip() for role in ("fast", "mid", "slow"))
    if any(not name for name in names):
        raise ValueError(f"{context} requires non-empty fast, mid, and slow source columns")
    source = _numeric_frame(data, names, context=context)
    source.columns = ("fast", "mid", "slow")
    return source


def _raw_braid_state(frame: pd.DataFrame) -> pd.Series:
    fast = frame["fast"]
    mid = frame["mid"]
    slow = frame["slow"]
    state = pd.Series(np.nan, index=frame.index, dtype="float64")
    state.loc[(slow > mid) & (mid > fast)] = 1.0
    state.loc[(slow > fast) & (fast > mid)] = 2.0
    state.loc[(fast > slow) & (slow > mid)] = 3.0
    state.loc[(fast > mid) & (mid > slow)] = 4.0
    state.loc[(mid > fast) & (fast > slow)] = 5.0
    state.loc[(mid > slow) & (slow > fast)] = 6.0
    return state


def _calculate_braids(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    frame = _role_frame(data, parameters, context="braids")
    raw = _raw_braid_state(frame)
    ambient = raw.ffill() if parameters["tie_policy"] == "carry" else raw
    width = frame.max(axis=1) - frame.min(axis=1)
    compression = pd.concat(
        ((frame.fast - frame.mid).abs(), (frame.fast - frame.slow).abs(), (frame.mid - frame.slow).abs()),
        axis=1,
    ).min(axis=1)
    return (ambient, width, compression), {}


def _calculate_braid_instability(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    raw = _raw_braid_state(_role_frame(data, parameters, context="braid_instability"))
    previous = raw.shift(1)
    change = (raw != previous).astype("float64")
    change.loc[raw.isna() | previous.isna()] = np.nan
    n = int(parameters["n"])
    instability = change.rolling(n, min_periods=n).mean()
    instability.iloc[:n] = np.nan
    return (instability,), {}


def _calculate_delta(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    fast = _numeric_series(data, str(parameters["fast"]), context="delta")
    slow = _numeric_series(data, str(parameters["slow"]), context="delta")
    difference = fast - slow
    if parameters["mode"] == "abs":
        return (difference,), {}
    epsilon = float(parameters["eps"])
    if not np.isfinite(epsilon) or epsilon <= 0.0:
        raise ValueError("delta.eps must be finite and > 0 in pct mode")
    return ((difference / slow.abs().clip(lower=epsilon) * 100.0).replace([np.inf, -np.inf], np.nan),), {}


def _trap_series(difference: pd.Series, zero_epsilon: float) -> pd.Series:
    values = difference.to_numpy(dtype="float64", copy=True)
    if zero_epsilon > 0.0:
        values[np.isfinite(values) & (np.abs(values) <= zero_epsilon)] = 0.0
    output = np.full(len(values), np.nan, dtype="float64")
    cumulative = 0.0
    for position, value in enumerate(values):
        if not np.isfinite(value):
            cumulative = 0.0
            continue
        previous = values[position - 1] if position else np.nan
        new_segment = (
            position == 0
            or not np.isfinite(previous)
            or value == 0.0
            or previous == 0.0
            or np.sign(value) != np.sign(previous)
        )
        if new_segment:
            cumulative = 0.0
        else:
            cumulative += 0.5 * (value + previous)
        output[position] = cumulative
    return pd.Series(output, index=difference.index)


def _calculate_trap_area(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    fast = _numeric_series(data, str(parameters["fast"]), context="trap_area")
    slow = _numeric_series(data, str(parameters["slow"]), context="trap_area")
    mid_name = parameters["mid"]
    epsilon = float(parameters["zero_eps"])
    if not isinstance(mid_name, str) or not mid_name.strip():
        return (_trap_series(fast - slow, epsilon),), {}
    mid = _numeric_series(data, mid_name, context="trap_area")
    return (
        _trap_series(fast - mid, epsilon),
        _trap_series(fast - slow, epsilon),
        _trap_series(mid - slow, epsilon),
    ), {}


def _calculate_percent_span_angle(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    columns = _source_columns(parameters["source_columns"], context="percent_span_angle.source_columns")
    window = int(parameters["window"])
    factor = 180.0 / np.pi if parameters["unit"] == "deg" else 1.0
    outputs: list[pd.Series] = []
    for column in columns:
        source = _numeric_series(data, column, context="percent_span_angle")
        valid = source.notna().astype("int64").rolling(window, min_periods=window).sum().eq(window)
        percent = source.pct_change(periods=window - 1, fill_method=None) * 100.0
        angle = pd.Series(np.arctan2(percent, float(window - 1)) * factor, index=data.index)
        outputs.append(angle.where(valid, np.nan))
    return tuple(outputs), {}


def _calculate_angle_momentum(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    columns = _source_columns(parameters["source_columns"], context="angle_momentum.source_columns")
    n = int(parameters["n"])
    outputs = []
    for column in columns:
        source = _numeric_series(data, column, context="angle_momentum")
        values = ((source - source.shift(n)) / float(n)).replace([np.inf, -np.inf], np.nan)
        values.iloc[:n] = np.nan
        outputs.append(values)
    return tuple(outputs), {}
