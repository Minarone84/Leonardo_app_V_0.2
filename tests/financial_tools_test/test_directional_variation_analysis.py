from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import DirectionalBinningPolicy, DirectionalVariationAnalysis, analyze_directional_variation


def frame(values):
    times = np.arange(len(values), dtype="int64")
    return pd.DataFrame({"ts_ms": times, "available_at_ms": times + 1, "x": values})


def test_defaults_and_asymmetric_references_are_independent():
    policy = DirectionalBinningPolicy()
    assert (policy.positive_bins, policy.negative_bins, policy.min_reference_count) == (10, 10, 2000)
    report = analyze_directional_variation(frame([-9, -3, -1, 0, 0.1, 0.2, None, pd.NA]), "x")
    assert report.positive.values == (0.1, 0.2)
    assert report.negative.values == (1.0, 3.0, 9.0)
    assert (report.row_count, report.valid_count, report.missing_count, report.zero_count) == (8, 6, 2, 1)
    assert report.reference_kind == "mixed"
    payload = report.to_dict()
    assert payload["positive_frequency"] == 2 / 6 and payload["negative_frequency"] == 3 / 6
    assert payload["positive"]["magnitude_statistics"]["mean"] == pytest.approx(0.15)
    assert payload["negative"]["magnitude_statistics"]["mean"] == pytest.approx(13 / 3)
    assert DirectionalVariationAnalysis.from_dict(json.loads(json.dumps(payload, allow_nan=False))).to_dict() == payload


@pytest.mark.parametrize("field", ["positive_bins", "negative_bins"])
@pytest.mark.parametrize("value", [0, -1, 1001, 1.5, True, np.nan, "10", None])
def test_invalid_counts_are_rejected(field, value):
    with pytest.raises(ValueError):
        DirectionalBinningPolicy(**{field: value})


@pytest.mark.parametrize("value", [0, -1, 1.5, True, np.inf])
def test_invalid_minimum_support(value):
    with pytest.raises(ValueError):
        DirectionalBinningPolicy(min_reference_count=value)


@pytest.mark.parametrize("values,kind,positive,negative", [
    ([1, 2, 0, None], "positive_only", 2, 0), ([-1, -2, 0, None], "negative_only", 0, 2),
    ([0, -0.0, None], "zero_only", 0, 0), ([None, np.nan], "empty", 0, 0), ([], "empty", 0, 0),
])
def test_sign_coverage_and_zero_are_not_forced(values, kind, positive, negative):
    report = analyze_directional_variation(frame(values), "x")
    assert report.reference_kind == kind
    assert report.positive.reference_count == positive and report.negative.reference_count == negative
    assert report.status == ("insufficient_reference" if kind == "empty" else "available")
    for side in (report.positive, report.negative):
        if not side.reference_count:
            assert side.status == "absent_reference"
            assert side.to_dict()["occupied_bins"] == 0
            assert all(entry["count"] == 0 and entry["observed_signed_minimum"] is None for entry in side.to_dict()["bins"])


def test_constant_and_limited_sides_have_separate_statuses():
    report = analyze_directional_variation(frame([-4] * 2500 + [1, 2]), "x")
    assert report.negative.status == "degenerate_reference"
    assert report.positive.status == "limited_support"
    assert report.negative.to_dict()["occupied_bins"] == 0


@pytest.mark.parametrize("invalid", [True, np.inf, -np.inf, "1.0", 2j])
def test_invalid_selected_values_are_named(invalid):
    with pytest.raises(ValueError, match="source 'x'"):
        analyze_directional_variation(frame([1, invalid]), "x")


def test_ties_remain_together_and_requested_bins_are_not_shrunk():
    report = analyze_directional_variation(frame([-5, -5, -1, 1, 1, 2]), "x",
                                          policy=DirectionalBinningPolicy(1000, 3, 1))
    positive, negative = report.positive.to_dict(), report.negative.to_dict()
    assert positive["bin_count"] == 1000 and positive["occupied_bins"] == 2
    assert positive["empty_bins"] == 998
    assert sorted(entry["count"] for entry in positive["bins"] if entry["count"]) == [1, 2]
    assert negative["bins"][-1]["observed_signed_minimum"] == -5
    assert negative["bins"][-1]["observed_signed_maximum"] == -5


@pytest.mark.parametrize("scale", [1e-200, 1, 1e200])
def test_finite_scaling_preserves_directional_occupancy(scale):
    values = np.array([-9., -4., -1., 0., 0.1, 0.5, 2.])
    reference = analyze_directional_variation(frame(values), "x")
    result = analyze_directional_variation(frame(values * scale), "x")
    for name in ("positive", "negative"):
        original = getattr(reference, name).to_dict()
        actual = getattr(result, name).to_dict()
        assert [entry["count"] for entry in original["bins"]] == [entry["count"] for entry in actual["bins"]]


def test_extreme_finite_magnitudes_and_gaps_remain_finite():
    data = frame([-1e308, -1e-300, 1e-300, 1e308, None])
    data["ts_ms"] = [1, 10, 100, 1000, 10000]
    report = analyze_directional_variation(data, "x")
    json.dumps(report.to_dict(), allow_nan=False)
    assert (report.reference_start_ms, report.reference_end_ms) == (1, 10000)
    assert report.positive.values == (1e-300, 1e308)


@pytest.mark.parametrize("case", ["duplicate_index", "reversed_index", "duplicate_columns", "missing_source", "missing_ts", "bad_ts"])
def test_structural_validation_is_retained(case):
    data = frame([1, 2])
    if case == "duplicate_index":
        data.index = [0, 0]
    elif case == "reversed_index":
        data.index = [1, 0]
    elif case == "duplicate_columns":
        data.columns = ["ts_ms", "x", "x"]
    elif case == "missing_source":
        data = data.drop(columns="x")
    elif case == "missing_ts":
        data = data.drop(columns="ts_ms")
    else:
        data["ts_ms"] = [1, 1]
    with pytest.raises(ValueError):
        analyze_directional_variation(data, "x")
