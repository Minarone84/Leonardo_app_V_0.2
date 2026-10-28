from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools.variation import analyze_variation
from leonardo.financial_tools.variation_models import BinningPolicy


def _frame(values):
    return pd.DataFrame({"ts_ms": pd.Series(range(len(values)), dtype="int64"), "x": values})


def test_hand_calculated_levels_and_magnitude():
    data = _frame([-4.0, -2.0, 0.0, 2.0, 4.0, np.nan])
    report = analyze_variation(data, "x", policy=BinningPolicy(min_reference_count=5))
    assert (report.valid_count, report.missing_count, report.distinct_count) == (5, 1, 5)
    assert (report.negative_count, report.zero_count, report.positive_count) == (2, 1, 2)
    assert (report.mean, report.median, report.q1, report.q3) == (0, 0, -2, 2)
    assert report.std == pytest.approx(np.sqrt(8))
    assert (report.minimum, report.maximum) == (-4, 4)
    assert report.band_counts == (0, 0, 1, 3, 1, 0, 0)
    magnitude = analyze_variation(data, "x", measurement="magnitude")
    assert magnitude.mean == pytest.approx(2.4)
    assert (magnitude.minimum, magnitude.maximum, magnitude.distinct_count) == (0, 4, 3)
    assert magnitude.negative_count == 2
    assert magnitude.status == "limited_support"
    json.dumps(magnitude.to_dict(), allow_nan=False)


@pytest.mark.parametrize("values, status", [
    ([], "insufficient_reference"), ([None, np.nan], "insufficient_reference"),
    ([0, 0], "degenerate_reference"), ([7], "degenerate_reference"),
    ([2, 2, None], "degenerate_reference"),
])
def test_empty_missing_and_degenerate_references(values, status):
    report = analyze_variation(_frame(values), "x")
    assert report.status == status
    assert sum(report.band_counts) == 0
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("invalid", [np.inf, -np.inf, True, "1", "bad", complex(1, 2)])
def test_invalid_values_name_source_and_row(invalid):
    data = _frame(pd.Series([1, invalid], dtype=object))
    with pytest.raises(ValueError, match="source 'x' at row 1"):
        analyze_variation(data, "x")


@pytest.mark.parametrize("case", ["duplicate_ts", "reverse_ts", "duplicate_index", "reverse_index",
                                  "duplicate_columns", "missing_ts", "fractional_ts", "bool_ts"])
def test_structural_input_validation(case):
    data = _frame([1.0, 2.0])
    if case == "duplicate_ts":
        data["ts_ms"] = [1, 1]
    elif case == "reverse_ts":
        data["ts_ms"] = [2, 1]
    elif case == "duplicate_index":
        data.index = [0, 0]
    elif case == "reverse_index":
        data.index = [2, 1]
    elif case == "duplicate_columns":
        data.columns = ["ts_ms", "ts_ms"]
    elif case == "missing_ts":
        data = data.drop(columns="ts_ms")
    elif case == "fractional_ts":
        data["ts_ms"] = [0.5, 1.5]
    else:
        data["ts_ms"] = [False, True]
    with pytest.raises(ValueError):
        analyze_variation(data, "x")


def test_gaps_are_preserved_and_not_differenced():
    data = _frame([10, None, 20, None, 30])
    data["ts_ms"] = [0, 1, 100, 200, 300]
    report = analyze_variation(data, "x")
    assert (report.mean, report.missing_count, report.reference_end_ms) == (20, 2, 300)
    assert report.std == pytest.approx(np.std([10, 20, 30]))


@pytest.mark.parametrize("scale", [1e-14, 1, 1000, 1e300])
def test_statistics_and_occupancy_under_rescaling(scale):
    report = analyze_variation(_frame(np.array([-4, -2, 0, 2, 4]) * scale), "x")
    assert report.std / scale == pytest.approx(np.sqrt(8))
    assert report.q3 / scale == pytest.approx(2)
    assert report.band_counts == (0, 0, 1, 3, 1, 0, 0)


@pytest.mark.parametrize("cutoffs", [(1, 5), (1, 5, 25, 25, 95, 99), (0, 5, 25, 75, 95, 99),
                                    (1, 5, 25, 75, 95, 100), (1, 5, 25, 75, 95, np.nan)])
def test_invalid_policy(cutoffs):
    with pytest.raises(ValueError):
        BinningPolicy(cutoffs=cutoffs)


def test_finite_extreme_inputs_do_not_overflow_descriptive_statistics():
    report = analyze_variation(_frame([-1e308, 0, 1e308]), "x")
    assert np.isfinite(report.std)
    json.dumps(report.to_dict(), allow_nan=False)


@pytest.mark.parametrize("values, expected", [
    ([1e-300, 2e-300, 3e-300, 1e308], [1.75e-300, 2.5e-300, 2.5e307]),
    ([0, 1e-300, 2e-300, 1e308], [7.5e-301, 1.5e-300, 2.5e307]),
    ([-1e308, 1e308], [-5e307, 0, 5e307]),
    ([1e308, 1.7e308], [1.175e308, 1.35e308, 1.525e308]),
    ([1, 1, 1, 3, 3, 8], [1, 2, 3]),
])
def test_linear_quartiles_preserve_small_values_and_avoid_overflow(values, expected):
    report = analyze_variation(_frame(values), "x")
    np.testing.assert_allclose([report.q1, report.median, report.q3], expected, rtol=1e-14, atol=0)
    assert report.valid_count == len(values)
    assert np.isfinite(report.mean) and np.isfinite(report.std)
    json.dumps(report.to_dict(), allow_nan=False)


def test_frequency_weighted_statistics_match_expanded_observations():
    values = np.repeat([-7., -1., 0., 3., 20.], [13, 4, 17, 40, 2])
    report = analyze_variation(_frame(values), "x")
    np.testing.assert_allclose([report.mean, report.std], [np.mean(values), np.std(values, ddof=0)],
                               rtol=1e-14, atol=0)
    np.testing.assert_allclose([report.q1, report.median, report.q3], np.quantile(values, [.25, .5, .75]),
                               rtol=1e-14, atol=0)
