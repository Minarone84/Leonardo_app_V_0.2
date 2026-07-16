from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
import pandas as pd

from .naming import canonicalize_tool_key, resolve_output_names
from .specifications import get_financial_tool_spec, resolve_output_signals, resolve_parameters


@dataclass(frozen=True, slots=True, init=False)
class FinancialToolCalculationResult:
    tool_key: str
    kind: str
    parameters: Mapping[str, object]
    bindings: Mapping[str, object]
    output_names: tuple[str, ...]
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    _frame: pd.DataFrame = field(repr=False)
    _analysis: dict[str, object] = field(repr=False)

    def __init__(
        self,
        *,
        tool_key: str,
        kind: str,
        parameters: Mapping[str, object],
        bindings: Mapping[str, object],
        output_names: tuple[str, ...],
        frame: pd.DataFrame,
        analysis: Mapping[str, object] | None = None,
    ) -> None:
        key, canonical_kind, canonical_parameters, canonical_bindings, names = (
            self.validate_configuration(
                tool_key=tool_key,
                kind=kind,
                parameters=parameters,
                bindings=bindings,
                output_names=output_names,
            )
        )
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas.DataFrame")
        if frame.empty:
            raise ValueError("frame must not be empty")
        if tuple(frame.columns) != ("ts_ms", *names):
            raise ValueError("frame columns must exactly match ts_ms and output_names")
        if not frame.index.is_unique:
            raise ValueError("frame index labels must be unique")
        if not frame.index.is_monotonic_increasing:
            raise ValueError("frame index must be monotonic increasing")
        timestamps = frame["ts_ms"]
        if timestamps.isna().any() or timestamps.map(
            lambda value: isinstance(value, (bool, np.bool_))
        ).any():
            raise ValueError("ts_ms must contain non-null integer values")
        try:
            numeric_timestamps = pd.to_numeric(timestamps, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError("ts_ms must contain integer values") from exc
        timestamp_values = numeric_timestamps.to_numpy(dtype="float64")
        if not np.isfinite(timestamp_values).all() or not np.equal(
            timestamp_values, np.floor(timestamp_values)
        ).all():
            raise ValueError("ts_ms must contain integer values")
        if len(timestamp_values) > 1 and not np.all(np.diff(timestamp_values) > 0):
            raise ValueError("ts_ms must be strictly increasing without duplicates")
        if analysis is not None and not isinstance(analysis, Mapping):
            raise TypeError("analysis must be a mapping")
        self.validate_runtime_outputs(
            tool_key=key,
            parameters=canonical_parameters,
            bindings=canonical_bindings,
            output_names=names,
            frame=frame,
        )
        frame_copy = frame.copy(deep=True)
        object.__setattr__(self, "tool_key", key)
        object.__setattr__(self, "kind", canonical_kind)
        object.__setattr__(self, "parameters", MappingProxyType(canonical_parameters))
        object.__setattr__(self, "bindings", MappingProxyType(canonical_bindings))
        object.__setattr__(self, "output_names", names)
        object.__setattr__(self, "row_count", len(frame_copy))
        object.__setattr__(self, "first_timestamp_ms", int(frame_copy["ts_ms"].iloc[0]))
        object.__setattr__(self, "last_timestamp_ms", int(frame_copy["ts_ms"].iloc[-1]))
        object.__setattr__(self, "_frame", frame_copy)
        object.__setattr__(self, "_analysis", deepcopy(dict(analysis or {})))

    @classmethod
    def validate_configuration(
        cls,
        *,
        tool_key: str,
        kind: str,
        parameters: Mapping[str, object],
        bindings: Mapping[str, object],
        output_names: tuple[str, ...],
    ) -> tuple[str, str, dict[str, object], dict[str, object], tuple[str, ...]]:
        if not isinstance(tool_key, str) or canonicalize_tool_key(tool_key) != tool_key:
            raise ValueError("tool_key must be canonical")
        spec = get_financial_tool_spec(tool_key)
        if kind != spec.kind:
            raise ValueError("kind must match the canonical Financial Tool specification")
        if not isinstance(parameters, Mapping):
            raise TypeError("parameters must be a mapping")
        supplied_parameters = deepcopy(dict(parameters))
        canonical_parameters = resolve_parameters(tool_key, supplied_parameters)
        if supplied_parameters != canonical_parameters:
            raise ValueError("parameters must be canonical resolved parameters")
        if not isinstance(bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        canonical_bindings = deepcopy(dict(bindings))
        if tool_key in {"derivative", "angle"}:
            if set(canonical_bindings) != {"source"}:
                raise ValueError(f"{tool_key} bindings must contain exactly 'source'")
            source = canonical_bindings["source"]
            if not isinstance(source, str) or not source or source != source.strip():
                raise ValueError(f"{tool_key}.source must be a canonical non-empty string")
        elif canonical_bindings:
            raise ValueError(f"{tool_key} does not accept bindings")
        if tool_key in {"dynamic_binning", "percent_span_angle"}:
            if int(canonical_parameters["window"]) < 2:
                raise ValueError(f"{tool_key}.window must be >= 2")
        if tool_key in {"braids", "braid_instability"}:
            mid = canonical_parameters["mid"]
            if not isinstance(mid, str) or not mid.strip():
                raise ValueError(f"{tool_key}.mid must be a non-empty source column")
        if not isinstance(output_names, tuple):
            raise TypeError("output_names must be a tuple")
        names = tuple(output_names)
        if not all(isinstance(name, str) and name for name in names):
            raise ValueError("output_names must contain non-empty strings")
        if len(names) != len(set(names)):
            raise ValueError("output_names must be unique")
        naming_parameters = dict(canonical_parameters)
        naming_parameters.update(canonical_bindings)
        if names != resolve_output_names(tool_key, naming_parameters):
            raise ValueError("output_names must match canonical Financial Tool output names")
        return (
            tool_key,
            kind,
            deepcopy(dict(canonical_parameters)),
            deepcopy(canonical_bindings),
            names,
        )

    @classmethod
    def runtime_output_types(
        cls,
        *,
        tool_key: str,
        parameters: Mapping[str, object],
        bindings: Mapping[str, object],
        output_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        naming_parameters = dict(parameters)
        naming_parameters.update(dict(bindings))
        signals = resolve_output_signals(tool_key, naming_parameters)
        if tuple(signal.name for signal in signals) != output_names:
            raise ValueError("output signals must match canonical output_names")
        runtime_types = [signal.value_type for signal in signals]
        if tool_key == "braids" and runtime_types:
            runtime_types[0] = "numeric"
        return tuple(runtime_types)

    @classmethod
    def validate_runtime_outputs(
        cls,
        *,
        tool_key: str,
        parameters: Mapping[str, object],
        bindings: Mapping[str, object],
        output_names: tuple[str, ...],
        frame: pd.DataFrame,
    ) -> tuple[str, ...]:
        runtime_types = cls.runtime_output_types(
            tool_key=tool_key,
            parameters=parameters,
            bindings=bindings,
            output_names=output_names,
        )
        for name, runtime_type in zip(output_names, runtime_types, strict=True):
            values = frame[name]
            if runtime_type == "numeric":
                if values.dtype != np.dtype("float32"):
                    raise ValueError(f"{name} runtime dtype must be float32")
                numeric = values.to_numpy(dtype="float32", copy=False)
                if np.isinf(numeric).any():
                    raise ValueError(f"{name} must contain finite values or NaN")
                if tool_key == "braids" and name == output_names[0]:
                    valid = np.isnan(numeric) | np.isin(numeric, np.arange(1, 7, dtype="float32"))
                    if not valid.all():
                        raise ValueError(f"{name} must contain Braids states 1 through 6 or NaN")
            elif runtime_type == "boolean":
                if values.dtype != np.dtype("bool") or values.isna().any():
                    raise ValueError(f"{name} runtime dtype must be non-null boolean")
            elif runtime_type == "categorical":
                if values.dtype != np.dtype("object") or values.isna().any():
                    raise ValueError(f"{name} runtime dtype must be non-null object strings")
                if not values.map(lambda value: isinstance(value, str)).all():
                    raise ValueError(f"{name} must contain categorical strings")
                if tool_key in {"hck", "strategy"} and not values.isin(
                    {"red", "silver", "green"}
                ).all():
                    raise ValueError(f"{name} contains an invalid color state")
            else:
                raise ValueError(f"unsupported runtime output type: {runtime_type}")
        return runtime_types

    @property
    def analysis(self) -> dict[str, object]:
        return deepcopy(self._analysis)

    def to_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)
