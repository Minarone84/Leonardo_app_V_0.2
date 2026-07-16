from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from ._calculation.constructs import (
    _calculate_angle,
    _calculate_angle_momentum,
    _calculate_braid_instability,
    _calculate_braids,
    _calculate_delta,
    _calculate_derivative,
    _calculate_percent_span_angle,
    _calculate_trap_area,
)
from ._calculation.dynamic_binning import _calculate_dynamic_binning
from ._calculation.indicators import (
    _calculate_bb,
    _calculate_ema,
    _calculate_hck,
    _calculate_hma,
    _calculate_kama,
    _calculate_peaks_troughs,
    _calculate_sma,
    _calculate_strategy,
    _calculate_tema,
)
from ._calculation.oscillators import (
    _calculate_arsi,
    _calculate_mfi,
    _calculate_obv,
    _calculate_rsi,
    _calculate_smi,
    _calculate_tdirsi,
    _calculate_volume,
)
from ._calculation.universal_trend_classifier import _calculate_universal_trend_classifier
from .calculation_models import FinancialToolCalculationResult
from .naming import canonicalize_tool_key, resolve_output_names
from .specifications import get_financial_tool_spec, resolve_output_signals, resolve_parameters


_Calculation = Callable[
    [pd.DataFrame, Mapping[str, object], Mapping[str, object]],
    tuple[tuple[pd.Series, ...], Mapping[str, object]],
]

_DISPATCH: dict[str, _Calculation] = {
    "sma": _calculate_sma,
    "ema": _calculate_ema,
    "tema": _calculate_tema,
    "hma": _calculate_hma,
    "kama": _calculate_kama,
    "bb": _calculate_bb,
    "hck": _calculate_hck,
    "strategy": _calculate_strategy,
    "peaks_troughs": _calculate_peaks_troughs,
    "universal_trend_classifier": _calculate_universal_trend_classifier,
    "rsi": _calculate_rsi,
    "arsi": _calculate_arsi,
    "tdirsi": _calculate_tdirsi,
    "smi": _calculate_smi,
    "mfi": _calculate_mfi,
    "obv": _calculate_obv,
    "volume": _calculate_volume,
    "derivative": _calculate_derivative,
    "angle": _calculate_angle,
    "braids": _calculate_braids,
    "braid_instability": _calculate_braid_instability,
    "delta": _calculate_delta,
    "trap_area": _calculate_trap_area,
    "percent_span_angle": _calculate_percent_span_angle,
    "angle_momentum": _calculate_angle_momentum,
    "dynamic_binning": _calculate_dynamic_binning,
}


def _validate_input(data: object, required_columns: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas.DataFrame")
    if data.empty:
        raise ValueError("data must not be empty")
    if not data.columns.is_unique:
        raise ValueError("data column labels must be unique")
    if not data.index.is_unique:
        raise ValueError("data index labels must be unique")
    if not data.index.is_monotonic_increasing:
        raise ValueError("data index must be monotonic increasing")
    if "ts_ms" not in data.columns:
        raise ValueError("data must contain ts_ms")
    timestamps = data["ts_ms"]
    if timestamps.isna().any() or timestamps.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError("ts_ms must contain non-null integer values")
    try:
        numeric_timestamps = pd.to_numeric(timestamps, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("ts_ms must contain integer values") from exc
    numeric_values = numeric_timestamps.to_numpy(dtype="float64")
    if not np.isfinite(numeric_values).all() or not np.equal(numeric_values, np.floor(numeric_values)).all():
        raise ValueError("ts_ms must contain integer values")
    if len(numeric_values) > 1 and not np.all(np.diff(numeric_values) > 0):
        raise ValueError("ts_ms must be strictly increasing without duplicates")
    missing = tuple(column for column in required_columns if column not in data.columns)
    if missing:
        raise ValueError(f"missing required input columns: {missing}")
    for column in required_columns:
        values = data[column]
        if values.map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(f"required input column {column!r} must be numeric or null")
        try:
            pd.to_numeric(values, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"required input column {column!r} must be numeric or null") from exc
    return data


def _resolve_bindings(
    key: str,
    data: pd.DataFrame,
    bindings: Mapping[str, object] | None,
) -> dict[str, object]:
    supplied = dict(bindings or {})
    if key not in {"derivative", "angle"}:
        if supplied:
            raise ValueError(f"{key} does not accept bindings")
        return {}
    if set(supplied) != {"source"}:
        raise ValueError(f"{key} bindings must contain exactly 'source'")
    source = supplied["source"]
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{key}.source must be a non-empty string")
    source = source.strip()
    if source not in data.columns:
        raise ValueError(f"{key}.source column does not exist: {source!r}")
    values = data[source]
    if values.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError(f"{key}.source must be numeric")
    try:
        pd.to_numeric(values, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key}.source must be numeric") from exc
    return {"source": source}


def _runtime_constraints(key: str, parameters: Mapping[str, object]) -> None:
    if key in {"dynamic_binning", "percent_span_angle"} and int(parameters["window"]) < 2:
        raise ValueError(f"{key}.window must be >= 2")
    if key in {"braids", "braid_instability"}:
        mid = parameters["mid"]
        if not isinstance(mid, str) or not mid.strip():
            raise ValueError(f"{key}.mid must be a non-empty source column")


def calculate_financial_tool(
    tool_key: str,
    data: pd.DataFrame,
    parameters: Mapping[str, object] | None = None,
    *,
    bindings: Mapping[str, object] | None = None,
) -> FinancialToolCalculationResult:
    key = canonicalize_tool_key(tool_key)
    spec = get_financial_tool_spec(key)
    validated = _validate_input(data, tuple(item.name for item in spec.data_inputs if item.required))
    resolved_parameters = resolve_parameters(key, parameters)
    resolved_bindings = _resolve_bindings(key, validated, bindings)
    _runtime_constraints(key, resolved_parameters)

    naming_parameters = dict(resolved_parameters)
    naming_parameters.update(resolved_bindings)
    output_names = resolve_output_names(key, naming_parameters)
    signals = resolve_output_signals(key, naming_parameters)
    if tuple(signal.name for signal in signals) != output_names:
        raise RuntimeError(f"calculation output signal mismatch for {key}")

    working = validated.copy(deep=True)
    outputs, analysis = _DISPATCH[key](working, resolved_parameters, resolved_bindings)
    if len(outputs) != len(output_names):
        raise RuntimeError(f"calculation output count mismatch for {key}")

    frame = pd.DataFrame(index=validated.index)
    frame["ts_ms"] = validated["ts_ms"].copy(deep=True)
    for name, signal, values in zip(output_names, signals, outputs, strict=True):
        if not values.index.equals(validated.index) or len(values) != len(validated):
            raise RuntimeError(f"calculation output alignment mismatch for {key}.{name}")
        if signal.value_type == "boolean":
            frame[name] = values.astype(bool)
        elif signal.value_type == "categorical" and key not in {"braids"}:
            frame[name] = values.astype(object)
        else:
            frame[name] = pd.to_numeric(values, errors="raise").astype("float32")

    if tuple(frame.columns) != ("ts_ms", *output_names):
        raise RuntimeError(f"calculation frame column mismatch for {key}")
    if not frame.index.equals(validated.index) or not frame["ts_ms"].equals(validated["ts_ms"]):
        raise RuntimeError(f"calculation frame identity mismatch for {key}")

    return FinancialToolCalculationResult(
        tool_key=key,
        kind=spec.kind,
        parameters=resolved_parameters,
        bindings=resolved_bindings,
        output_names=output_names,
        frame=frame,
        analysis=analysis,
    )
