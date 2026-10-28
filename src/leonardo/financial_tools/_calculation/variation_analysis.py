"""Empirical distribution preparation shared by analysis and profile fitting."""

from __future__ import annotations

from numbers import Real

import numpy as np
import pandas as pd

from ..variation_models import (
    BinningPolicy, VariationAnalysis, _distribution_statistics, _empirical_rank, _integer, _measurement, _text,
)


def _timestamps(data: pd.DataFrame, name: str, *, ordered: bool) -> np.ndarray:
    if name not in data.columns:
        raise ValueError(f"data must contain {name}")
    result = []
    for row, value in data[name].items():
        try:
            result.append(_integer(value, name))
        except ValueError as exc:
            raise ValueError(f"{name} at row {row!r}: {exc}") from exc
    values = np.asarray(result, dtype="int64")
    if ordered and len(values) > 1 and np.any(values[1:] <= values[:-1]):
        raise ValueError(f"{name} must be strictly increasing without duplicates")
    return values


def _input_values(data: pd.DataFrame, source: str, measurement: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _text(source, "source")
    _measurement(measurement)
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas.DataFrame")
    if not data.columns.is_unique or not data.index.is_unique or not data.index.is_monotonic_increasing:
        raise ValueError("data requires unique columns and a unique increasing index")
    timestamps = _timestamps(data, "ts_ms", ordered=True)
    if source not in data.columns:
        raise ValueError(f"missing source column {source!r}")
    values = []
    for row, value in data[source].items():
        if value is None or value is pd.NA or (isinstance(value, Real) and pd.isna(value)):
            values.append(np.nan)
        elif isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(value):
            raise ValueError(f"source {source!r} at row {row!r} must be finite numeric or missing")
        else:
            values.append(float(value))
    raw = np.asarray(values, dtype="float64")
    return timestamps, raw, np.abs(raw) if measurement == "magnitude" else raw.copy()


def _analyze(
    data: pd.DataFrame, source: str, measurement: str, policy: BinningPolicy
) -> tuple[VariationAnalysis, tuple[float, ...], tuple[int, ...]]:
    if not isinstance(policy, BinningPolicy):
        raise TypeError("policy must be a BinningPolicy")
    timestamps, raw, measured = _input_values(data, source, measurement)
    valid = measured[~np.isnan(measured)]
    values, counts = np.unique(valid, return_counts=True)
    size = len(valid)
    occupancy = [0] * 7
    stats = dict.fromkeys(("minimum", "maximum", "mean", "std", "median", "q1", "q3"))
    if size:
        stats = _distribution_statistics(values, counts)
        if len(values) > 1:
            ranks, _, _ = _empirical_rank(values, np.cumsum((0, *counts), dtype="int64"), values)
            for band, count in zip(np.searchsorted(policy.cutoffs, ranks, side="right"), counts):
                occupancy[int(band)] += int(count)
    status = ("insufficient_reference" if not size else "degenerate_reference" if len(values) == 1
              else "limited_support" if size < policy.min_reference_count else "ready")
    report = VariationAnalysis(
        source=source, measurement=measurement, row_count=len(data), valid_count=size,
        missing_count=len(data) - size, distinct_count=len(values),
        zero_count=int(np.count_nonzero(raw == 0)), positive_count=int(np.count_nonzero(raw > 0)),
        negative_count=int(np.count_nonzero(raw < 0)),
        reference_start_ms=int(timestamps[0]) if len(timestamps) else None,
        reference_end_ms=int(timestamps[-1]) if len(timestamps) else None,
        **stats, status=status, band_counts=tuple(occupancy),
    )
    return report, tuple(float(value) for value in values), tuple(int(count) for count in counts)
