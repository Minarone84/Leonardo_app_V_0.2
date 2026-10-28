from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    BinningPolicy, DynamicBinningProfile, VariationContext,
    classify_dynamic_binning, fit_dynamic_binning,
)


def _context(**changes):
    return replace(VariationContext("x", canonicalize_market_id("bybit", "linear", "BTCUSD", "4h"),
                                    "test parameter with fixed settings", "1", "percent"), **changes)


def _frame(values, start=0):
    times = np.arange(start, start + len(values), dtype="int64")
    return pd.DataFrame({"ts_ms": times, "available_at_ms": times + 1, "x": values})


def _fit(values, *, measurement="value", policy=None):
    return fit_dynamic_binning(_frame(values), _context(), profile_id="test-v1",
                               calibration_as_of_ms=len(values), provenance=("synthetic",),
                               measurement=measurement, policy=policy or BinningPolicy(min_reference_count=1))


def _apply(profile, values):
    return classify_dynamic_binning(_frame(values, 10000), profile, context=_context(), mode="forward").to_frame()


def test_ties_have_exact_inclusive_counts_and_midpoint_rank():
    profile = _fit([1, 2, 3, 3, 4])
    row = _apply(profile, [3]).iloc[0]
    assert row["percentile"] == 60
    assert (row["tie_lower_percentile"], row["tie_upper_percentile"]) == (40, 80)
    assert (row["lower_tail_count"], row["upper_tail_count"], row["reference_count"]) == (4, 3, 5)
    assert (row["lower_tail_frequency"], row["upper_tail_frequency"]) == (0.8, 0.6)
    assert row["band"] == "typical"
    assert profile.values == (1, 2, 3, 4)
    assert profile.counts == (1, 1, 2, 1)


def test_exact_cutoff_enters_higher_band():
    rows = _apply(_fit(np.arange(100)), [0.5, 4.5, 24.5, 74.5, 94.5, 98.5])
    assert rows["percentile"].tolist() == [1, 5, 25, 75, 95, 99]
    assert rows["band"].tolist() == ["low", "below_typical", "typical", "above_typical", "high", "very_high"]


def test_zero_heavy_reference_does_not_split_ties_or_call_zero_rare():
    profile = _fit([0] * 990 + [1] * 10)
    rows = _apply(profile, [0, 1])
    assert rows["percentile"].tolist() == [49.5, 99.5]
    assert rows["upper_tail_label"].tolist() == ["common", "very_rare"]
    assert rows["lower_tail_label"].tolist() == ["common", "common"]
    assert profile.analysis.band_counts == (0, 0, 0, 990, 0, 0, 10)


@pytest.mark.parametrize("size, expected", [(1999, "limited_support"), (2000, "ready")])
def test_support_guard(size, expected):
    profile = _fit(np.arange(size), policy=BinningPolicy())
    row = _apply(profile, [size - 1]).iloc[0]
    assert profile.analysis.status == expected
    assert pd.isna(row["upper_tail_label"]) if size < 2000 else row["upper_tail_label"] == "very_rare"


@pytest.mark.parametrize("constant", [0, -3, 2])
def test_degenerate_reference_has_relations_without_normal_or_rare_labels(constant):
    profile = _fit([constant] * 5)
    rows = _apply(profile, [constant - 1, constant, constant + 1, np.nan])
    assert rows["range_position"].iloc[:3].tolist() == ["below", "equal", "above"]
    assert rows["band"].isna().all() and rows["upper_tail_label"].isna().all()
    assert rows["percentile"].isna().all()
    assert rows["status"].tolist() == ["degenerate_reference"] * 3 + ["missing_value"]


@pytest.mark.parametrize("values", [[], [np.nan, None]])
def test_fitting_empty_reference_is_clear_error(values):
    with pytest.raises(ValueError, match="insufficient_reference"):
        _fit(values)


def test_missing_alignment_range_flags_and_collision_safe_results():
    profile = _fit([1, 2, 3])
    data = _frame([None, 0, 2, 4], 10000)
    data["x_lab"] = ["original"] * 4
    data.index = [4, 8, 12, 16]
    before = data.copy(deep=True)
    result = classify_dynamic_binning(data, profile, context=_context(), mode="forward")
    rows = result.to_frame()
    pd.testing.assert_frame_equal(before, data)
    assert rows.index.tolist() == [4, 8, 12, 16]
    assert rows["status"].tolist() == ["missing_value", "outside_reference_range", "ready", "outside_reference_range"]
    assert rows["band"].iloc[1:].tolist() == ["very_low", "typical", "very_high"]
    assert pd.isna(rows["lower_tail_label"].iloc[1])
    assert pd.isna(rows["upper_tail_label"].iloc[3])
    assert rows["lower_tail_count"].iloc[1] == 0 and rows["upper_tail_count"].iloc[3] == 0
    rows.loc[12, "raw_value"] = 500
    assert result.to_frame().loc[12, "raw_value"] == 2


def test_magnitude_preserves_negative_direction_and_does_not_mirror():
    profile = _fit([-9, -3, -1], measurement="magnitude")
    rows = _apply(profile, [-9, 9])
    assert rows["percentile"].iloc[0] == rows["percentile"].iloc[1]
    assert rows["direction"].tolist() == [-1, 1]
    signed = _fit([-9, -3, -1])
    assert signed.values == (-9, -3, -1)
    assert _apply(signed, [1])["outside_reference_range"].iloc[0]


@pytest.mark.parametrize("scale", [1e-14, 1000])
def test_rank_and_band_scale_invariance(scale):
    reference = np.array([-4, -2, 0, 2, 2, 4], dtype=float)
    observations = np.array([-6, -4, -1, 0, 2, 3, 6], dtype=float)
    first = _apply(_fit(reference), observations)
    second = _apply(_fit(reference * scale), observations * scale)
    columns = ["percentile", "band", "lower_tail_count", "upper_tail_count", "outside_reference_range"]
    pd.testing.assert_frame_equal(first[columns], second[columns])


@pytest.mark.parametrize("kind", ["skew", "bimodal", "negative"])
def test_empirical_counts_match_independent_direct_count_oracle(kind):
    rng = np.random.default_rng(1234)
    reference = (rng.exponential(size=1000) if kind == "skew" else
                 np.r_[rng.normal(-3, 0.2, 500), rng.normal(4, 0.5, 500)] if kind == "bimodal" else
                 -rng.exponential(size=1000))
    observations = np.r_[reference[::111], -20, 0, 20]
    rows = _apply(_fit(reference), observations)
    for index, value in enumerate(observations):
        less, equal = sum(reference < value), sum(reference == value)
        assert rows["percentile"].iloc[index] == 100 * (less + equal / 2) / len(reference)
        assert rows["lower_tail_count"].iloc[index] == sum(reference <= value)
        assert rows["upper_tail_count"].iloc[index] == sum(reference >= value)


@pytest.mark.parametrize("field, value", [
    ("unit", "absolute"), ("parameter_version", "2"), ("parameter_definition", "different period"),
    ("source", "other"), ("market_id", canonicalize_market_id("bybit", "linear", "XRPUSDT", "4h")),
    ("market_id", canonicalize_market_id("bybit", "linear", "BTCUSD", "1h")),
])
def test_context_mismatch_is_rejected(field, value):
    with pytest.raises(ValueError, match="context"):
        classify_dynamic_binning(_frame([1], 100), _fit([1, 2]), context=_context(**{field: value}), mode="forward")


def test_availability_checks_calibration_forward_and_retrospective():
    data = _frame([1, 2, 3])
    with pytest.raises(ValueError, match="after calibration_as_of"):
        fit_dynamic_binning(data, _context(), profile_id="x", calibration_as_of_ms=2, provenance=("test",))
    profile = _fit([1, 2, 3])
    with pytest.raises(ValueError, match="after calibration_as_of"):
        classify_dynamic_binning(data, profile, context=_context(), mode="forward")
    rows = classify_dynamic_binning(data, profile, context=_context(), mode="retrospective").to_frame()
    assert rows["mode"].eq("retrospective").all()
    data.loc[1, "available_at_ms"] = 0
    with pytest.raises(ValueError, match="cannot precede"):
        classify_dynamic_binning(data, profile, context=_context(), mode="retrospective")


def test_profile_owns_immutable_distribution_and_defensive_payload():
    data = _frame([1, 2, 3, 3, 4])
    provenance = ["test"]
    profile = fit_dynamic_binning(data, _context(), profile_id="immutable", calibration_as_of_ms=5, provenance=provenance)
    snapshot = profile.to_dict()
    provenance.append("changed")
    data["x"] = 100
    snapshot["values"][0] = -100
    assert profile.values[0] == 1 and profile.provenance == ("test",)
    with pytest.raises(FrozenInstanceError):
        profile.profile_id = "changed"
    with pytest.raises(ValueError):
        profile._ordered.flags.writeable = True
    restored = DynamicBinningProfile.from_dict(json.loads(json.dumps(profile.to_dict(), allow_nan=False)))
    assert restored == profile


@pytest.mark.parametrize("case", [
    "schema", "algorithm", "extra", "counts", "order", "nan", "cutoffs",
    "support", "occupancy", "bool_version", "magnitude", "span", "context",
])
def test_corrupt_profile_payload_is_rejected(case):
    payload = _fit([1, 2, 3, 3, 4]).to_dict()
    if case == "schema":
        payload["schema_version"] = 2
    elif case == "algorithm":
        payload["algorithm_version"] = "unknown"
    elif case == "extra":
        payload["extra"] = True
    elif case == "counts":
        payload["counts"][1] += 1
    elif case == "order":
        payload["values"].reverse()
    elif case == "nan":
        payload["values"][0] = float("nan")
    elif case == "cutoffs":
        payload["policy"]["cutoffs"][1] = 0
    elif case == "support":
        payload["analysis"]["status"] = "limited_support"
    elif case == "occupancy":
        payload["analysis"]["band_counts"] = [5, 0, 0, 0, 0, 0, 0]
    elif case == "bool_version":
        payload["schema_version"] = True
    elif case == "magnitude":
        payload["measurement"] = "magnitude"
    elif case == "span":
        payload["analysis"]["reference_end_ms"] = 200
    else:
        payload["context"]["market_id"]["timeframe"] = "4 hours"
    with pytest.raises(ValueError):
        DynamicBinningProfile.from_dict(payload)


def test_custom_cutoffs_and_empty_application():
    profile = _fit(range(100), policy=BinningPolicy(cutoffs=(10, 20, 30, 70, 80, 90), min_reference_count=1))
    assert _apply(profile, [8, 10])["band"].tolist() == ["very_low", "low"]
    result = classify_dynamic_binning(_frame([]), profile, context=_context(), mode="forward")
    assert result.to_frame().empty


def test_fresh_process_profile_json_round_trip(tmp_path):
    profile = _fit([1, 2, 3, 3, 4])
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile.to_dict(), allow_nan=False), encoding="utf-8")
    program = """
import json, sys
import pandas as pd
from pathlib import Path
from leonardo.financial_tools import DynamicBinningProfile, classify_dynamic_binning
p = DynamicBinningProfile.from_dict(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
data = pd.DataFrame({'ts_ms': [10000,10001], 'available_at_ms': [10001,10002], 'x': [3, 6]})
rows = classify_dynamic_binning(data, p, context=p.context, mode='forward').to_frame()
print(json.dumps(rows.astype(object).where(rows.notna(), None).to_dict(orient='records'), allow_nan=False))
"""
    completed = subprocess.run([sys.executable, "-B", "-c", program, str(path)], capture_output=True, text=True, check=True)
    rows = _apply(profile, [3, 6])
    expected = rows.astype(object).where(rows.notna(), None).to_dict(orient="records")
    assert json.loads(completed.stdout) == expected


@pytest.mark.parametrize("edits", [
    {"zero_count": 5, "positive_count": 0},
    {"negative_count": 5, "positive_count": 0},
    {"mean": 4.0}, {"std": 0.0}, {"q1": 1.0, "median": 1.0, "q3": 4.0},
])
def test_restoration_rejects_diagnostics_contradicting_the_distribution(edits):
    payload = _fit([1, 2, 3, 3, 4]).to_dict()
    payload["analysis"].update(edits)
    with pytest.raises(ValueError, match="profile.*(sign counts|statistics)"):
        DynamicBinningProfile.from_dict(payload)


def test_direct_profile_construction_validates_distribution_statistics():
    profile = _fit([1, 2, 3, 3, 4])
    with pytest.raises(ValueError, match="profile.*statistics"):
        replace(profile, analysis=replace(profile.analysis, mean=4.0))


def test_signed_profile_checks_positive_and_negative_counts_separately():
    payload = _fit([-3, -1, 0, 2, 2, 4]).to_dict()
    payload["analysis"].update(positive_count=2, negative_count=3)
    with pytest.raises(ValueError, match="profile.*sign counts"):
        DynamicBinningProfile.from_dict(payload)


def test_magnitude_profile_checks_zero_count_without_inventing_original_signs():
    payload = _fit([-4, -2, 0, 2, 4], measurement="magnitude").to_dict()
    payload["analysis"].update(positive_count=4, negative_count=0)
    # The absolute distribution cannot recover the original positive/negative split.
    restored = DynamicBinningProfile.from_dict(payload)
    assert restored.analysis.positive_count == 4 and restored.analysis.negative_count == 0
    payload["analysis"].update(zero_count=2, positive_count=3)
    with pytest.raises(ValueError, match="profile.*sign counts"):
        DynamicBinningProfile.from_dict(payload)


@pytest.mark.parametrize("values", [[1e-300, 2e-300, 3e-300, 1e308], [0, 1e-300, 2e-300, 1e308]])
@pytest.mark.parametrize("measurement", ["value", "magnitude"])
def test_mixed_scale_profiles_fit_restore_and_preserve_empirical_order(values, measurement):
    profile = _fit(values, measurement=measurement)
    restored = DynamicBinningProfile.from_dict(json.loads(json.dumps(profile.to_dict(), allow_nan=False)))
    rows = _apply(restored, values)
    assert rows["percentile"].tolist() == [12.5, 37.5, 62.5, 87.5]
    assert rows["lower_tail_count"].tolist() == [1, 2, 3, 4]
    assert rows["upper_tail_count"].tolist() == [4, 3, 2, 1]
    np.testing.assert_allclose([restored.analysis.q1, restored.analysis.median, restored.analysis.q3],
                               np.quantile(values, [.25, .5, .75]), rtol=1e-14, atol=0)
    pd.testing.assert_frame_equal(rows, _apply(profile, values), check_exact=True)


@pytest.mark.parametrize("field", ["q1", "median", "std"])
def test_statistic_validation_has_no_absolute_tolerance_that_hides_tiny_values(field):
    payload = _fit([0, 1e-300, 2e-300, 3e-300]).to_dict()
    payload["analysis"][field] = 0.0
    if field == "median":
        payload["analysis"]["q1"] = 0.0
    with pytest.raises(ValueError, match="profile.*statistics"):
        DynamicBinningProfile.from_dict(payload)


def test_restoration_allows_roundoff_but_rejects_changed_statistics():
    payload = _fit([1, 2, 3, 3, 4]).to_dict()
    payload["analysis"]["mean"] = np.nextafter(payload["analysis"]["mean"], np.inf)
    payload["analysis"]["std"] = np.nextafter(payload["analysis"]["std"], np.inf)
    payload["analysis"]["q1"] *= 1 + 5e-13
    DynamicBinningProfile.from_dict(payload)
    payload["analysis"]["q1"] = 2 * (1 + 1e-10)
    with pytest.raises(ValueError, match="profile.*statistics"):
        DynamicBinningProfile.from_dict(payload)


def test_large_frequency_profile_does_not_require_expanding_observations():
    payload = _fit([1, 3]).to_dict()
    count = 10**12
    payload["counts"] = [count, count]
    payload["analysis"].update(row_count=2*count, valid_count=2*count, positive_count=2*count,
                                reference_end_ms=2*count-1, band_counts=[0, 0, 0, count, count, 0, 0],
                                q1=1.0, median=2.0, q3=3.0)
    payload["calibration_as_of_ms"] = 2*count
    restored = DynamicBinningProfile.from_dict(payload)
    assert (restored.analysis.q1, restored.analysis.median, restored.analysis.q3) == (1, 2, 3)
    assert (restored.analysis.mean, restored.analysis.std) == (2, 1)
