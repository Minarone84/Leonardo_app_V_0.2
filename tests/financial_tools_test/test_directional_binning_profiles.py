from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    BinningPolicy, DirectionalBinningPolicy, DirectionalBinningProfile, DynamicBinningProfile, VariationContext,
    classify_directional_binning, fit_directional_binning, fit_dynamic_binning,
)
from leonardo.financial_tools.directional_variation_models import _DirectionalReference


def context(**changes):
    return replace(VariationContext("x", canonicalize_market_id("bybit", "linear", "BTCUSD", "4h"),
                                    "synthetic construct", "1", "percent"), **changes)


def frame(values, start=0):
    times = np.arange(start, start + len(values), dtype="int64")
    return pd.DataFrame({"ts_ms": times, "available_at_ms": times + 1, "x": values})


def fit(values, policy=None):
    return fit_directional_binning(frame(values), context(), profile_id="directional-test",
                                   calibration_as_of_ms=len(values), provenance=("synthetic",),
                                   policy=policy or DirectionalBinningPolicy(min_reference_count=1))


def apply(profile, values):
    return classify_directional_binning(frame(values, 100000), profile, context=context(), mode="forward").to_frame()


@pytest.mark.parametrize("positive_bins,negative_bins", [(1, 1), (2, 2), (10, 10), (7, 13), (1000, 1000)])
def test_counts_ranks_and_bins_match_independent_fraction_oracle(positive_bins, negative_bins):
    reference = [-8., -5., -2., -2., 0., 0.1, 0.2, 0.2, 0.8, 1.6]
    queries = [-9., -8., -6., -2., -0.01, 0.01, 0.1, 0.2, 0.5, 1.6, 3.]
    rows = apply(fit(reference, DirectionalBinningPolicy(positive_bins, negative_bins, 1)), queries)
    for value, (_, row) in zip(queries, rows.iterrows(), strict=True):
        side = [abs(x) for x in reference if (x > 0 if value > 0 else x < 0)]
        smaller = sum(x < abs(value) for x in side)
        tied = sum(x == abs(value) for x in side)
        small_tail = sum(x <= abs(value) for x in side)
        large_tail = sum(x >= abs(value) for x in side)
        rank = Fraction(smaller, len(side)) + Fraction(tied, 2 * len(side))
        bins = positive_bins if value > 0 else negative_bins
        expected = 1 + sum(rank >= Fraction(k, bins) for k in range(1, bins))
        assert row["directional_percentile"] == pytest.approx(100 * float(rank))
        assert row["bin_index"] == expected and row["bin_count"] == bins
        assert row["small_magnitude_tail_count"] == small_tail and row["large_magnitude_tail_count"] == large_tail
        assert row["conditional_large_tail_frequency"] == large_tail / len(side)
        assert row["whole_large_tail_frequency"] == large_tail / len(reference)
        assert row["direction_frequency"] == len(side) / len(reference)
        assert row["bin_label"] == f"{'P' if value > 0 else 'N'}{expected:02d}"


def test_exact_cutoffs_and_negative_intensity_order():
    reference = list(range(1, 101)) + list(range(-100, 0))
    rows = apply(fit(reference), [10, 10.5, 90.5, 100, -1, -100, -101])
    assert rows["bin_index"].tolist() == [1, 2, 10, 10, 1, 10, 10]
    assert rows["directional_percentile"].tolist() == [9.5, 10, 90, 99.5, 0.5, 99.5, 100]
    assert rows["conditional_large_tail_label"].iloc[2] == "common"
    assert rows["conditional_large_tail_label"].iloc[3] == "very_rare"
    assert pd.isna(rows["conditional_large_tail_label"].iloc[6])


@pytest.mark.parametrize("sign", [-1, 1])
def test_one_sign_profile_does_not_mirror_and_unseen_sign_has_no_bin(sign):
    profile = fit(np.array([1, 2, 4]) * sign)
    row = apply(profile, [sign * 2, -sign * 2]).iloc[1]
    assert row["status"] == "uncalibrated_direction"
    assert row["directional_reference_count"] == 0 and row["direction_frequency"] == 0
    for name in ("directional_percentile", "bin_index", "bin_label", "conditional_large_tail_label", "outside_reference_range"):
        assert pd.isna(row[name])
    populated = profile.analysis.positive if sign == 1 else profile.analysis.negative
    absent = profile.analysis.negative if sign == 1 else profile.analysis.positive
    assert populated.values == (1., 2., 4.) and absent.values == ()


def test_zero_only_profile_missing_alignment_and_defensive_results():
    profile = fit([0, -0.0, None])
    data = frame([None, 0, 1, -1], 100)
    data.index = [4, 8, 12, 16]
    data["bin_label"] = "source label"
    before = data.copy(deep=True)
    result = classify_directional_binning(data, profile, context=context(), mode="forward")
    rows = result.to_frame()
    assert rows["status"].tolist() == ["missing_value", "zero_value", "uncalibrated_direction", "uncalibrated_direction"]
    assert rows["bin_label"].isna().all()
    assert rows["zero_reference_count"].tolist() == [2] * 4
    assert rows["zero_reference_frequency"].tolist() == [1.] * 4
    assert rows.index.tolist() == [4, 8, 12, 16]
    pd.testing.assert_frame_equal(data, before)
    rows.loc[8, "raw_value"] = 99
    assert result.to_frame().loc[8, "raw_value"] == 0


@pytest.mark.parametrize("values", [[], [None, np.nan]])
def test_empty_reference_fit_rejected(values):
    with pytest.raises(ValueError, match="insufficient_reference"):
        fit(values)


@pytest.mark.parametrize("count", [1999, 2000])
def test_default_support_is_per_side(count):
    profile = fit(list(range(1, count + 1)) + list(range(-3000, 0)), DirectionalBinningPolicy())
    rows = apply(profile, [count, -3000])
    assert rows["support_status"].tolist() == ["limited_support" if count == 1999 else "ready", "ready"]
    assert rows["bin_label"].notna().all()
    assert pd.isna(rows["conditional_large_tail_label"].iloc[0]) if count == 1999 else rows["conditional_large_tail_label"].iloc[0] == "very_rare"
    assert rows["conditional_large_tail_label"].iloc[1] == "very_rare"


def test_degenerate_side_preserves_relations_without_bins_or_rarity():
    rows = apply(fit([-3] * 3000 + [1, 2, 4]), [-4, -3, -2, 2])
    assert rows["range_position"].tolist() == ["above", "equal", "below", "inside"]
    assert rows["status"].iloc[:3].eq("degenerate_reference").all()
    assert rows["bin_label"].iloc[:3].isna().all() and rows["directional_percentile"].iloc[:3].isna().all()
    assert rows["conditional_large_tail_label"].iloc[:3].isna().all()
    assert rows["status"].iloc[3] == "ready"


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("other", [[], [0.01], [1000, 2000], [0.1] * 200])
def test_opposite_sign_changes_do_not_change_conditional_results(sign, other):
    own = [sign * x for x in [1, 2, 2, 5, 9]]
    first = fit(own + [-sign, -3 * sign])
    second = fit(own + [-sign * x for x in other])
    side = "positive" if sign == 1 else "negative"
    assert getattr(first.analysis, side).to_dict() == getattr(second.analysis, side).to_dict()
    a, b = apply(first, own), apply(second, own)
    conditional = [name for name in a if name not in ("whole_reference_count", "zero_reference_frequency", "direction_frequency", "whole_small_tail_frequency", "whole_large_tail_frequency")]
    pd.testing.assert_frame_equal(a[conditional], b[conditional], check_exact=True)
    assert b["whole_large_tail_frequency"].iloc[0] == b["large_magnitude_tail_count"].iloc[0] / (len(own) + len(other))


def test_bin_count_change_leaves_other_side_and_all_ranks_and_tails_unchanged():
    reference = [-9, -3, -1, 0, 1, 2, 4, 8]
    first = fit(reference)
    second = fit(reference, DirectionalBinningPolicy(3, 10, 1))
    assert first.analysis.negative.to_dict() == second.analysis.negative.to_dict()
    a, b = apply(first, [-3, 1, 2, 8]), apply(second, [-3, 1, 2, 8])
    pd.testing.assert_series_equal(a.iloc[0], b.iloc[0], check_exact=True)
    unchanged = [name for name in a if not name.startswith("bin_")]
    pd.testing.assert_frame_equal(a[unchanged], b[unchanged], check_exact=True)


def test_profile_and_exported_payload_are_immutable():
    profile = fit([-3, -1, 1, 2])
    with pytest.raises(FrozenInstanceError):
        profile.profile_id = "changed"
    for side in (profile.analysis.positive, profile.analysis.negative):
        with pytest.raises(ValueError):
            side._ordered.flags.writeable = True
        with pytest.raises(ValueError):
            side._cumulative.flags.writeable = True
    payload = profile.to_dict()
    payload["analysis"]["positive"]["values"][0] = 999
    assert profile.analysis.positive.values == (1., 2.)


@pytest.mark.parametrize("case", ["version", "bool_version", "algorithm", "extra", "policy", "count", "values", "status", "bins", "span", "zero", "source", "mean", "frequency", "bool_count", "provenance", "cutoff"])
def test_corrupt_profiles_are_rejected(case):
    payload = fit([-3, -1, 0, 1, 2]).to_dict()
    analysis, side = payload["analysis"], payload["analysis"]["positive"]
    if case == "version": payload["schema_version"] = 1
    elif case == "bool_version": payload["schema_version"] = True
    elif case == "algorithm": payload["algorithm_version"] = "unknown"
    elif case == "extra": payload["extra"] = 1
    elif case == "policy": analysis["policy"]["positive_bins"] = 12
    elif case == "count": side["counts"][0] = 10
    elif case == "values": side["values"] = [2., 1.]
    elif case == "status": side["status"] = "absent_reference"
    elif case == "bins": side["bins"][0]["count"] = 20
    elif case == "span": analysis["reference_end_ms"] = -10
    elif case == "zero": analysis["zero_count"] = 2
    elif case == "source": analysis["source"] = "other"
    elif case == "mean": side["magnitude_statistics"]["mean"] = 0.
    elif case == "frequency": analysis["positive_frequency"] = 0.9
    elif case == "bool_count": side["bins"][0]["count"] = False
    elif case == "provenance": payload["provenance"] = ["x", "x"]
    else: payload["calibration_as_of_ms"] = 0
    with pytest.raises(ValueError):
        DirectionalBinningProfile.from_dict(payload)


def test_old_and_new_versions_do_not_silently_convert():
    old = fit_dynamic_binning(frame([-2, -1, 1, 2]), context(), profile_id="old", calibration_as_of_ms=4,
                              provenance=("synthetic",), policy=BinningPolicy(min_reference_count=1))
    with pytest.raises(ValueError):
        DirectionalBinningProfile.from_dict(old.to_dict())
    with pytest.raises(ValueError):
        DynamicBinningProfile.from_dict(fit([-2, -1, 1, 2]).to_dict())
    assert DynamicBinningProfile.from_dict(old.to_dict()).to_dict() == old.to_dict()


def test_fresh_process_profile_round_trip(tmp_path):
    profile = fit([-3, -1, 0, 1, 2, None])
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile.to_dict(), allow_nan=False))
    code = "import json,sys; from leonardo.financial_tools import DirectionalBinningProfile; p=json.load(open(sys.argv[1])); print(json.dumps(DirectionalBinningProfile.from_dict(p).to_dict(),sort_keys=True))"
    output = subprocess.check_output([sys.executable, "-B", "-c", code, str(path)], text=True)
    assert json.loads(output) == profile.to_dict()


def test_large_frequency_bin_arithmetic_avoids_int64_overflow():
    count = 2**62 - 1
    side = _DirectionalReference(1, 1000, 1, (1., 2.), (count, count))
    report = side.to_dict()
    assert report["reference_count"] == 2 * count
    assert [(entry["bin_index"], entry["count"]) for entry in report["bins"] if entry["count"]] == [(251, count), (751, count)]
    assert _DirectionalReference.from_dict(report).to_dict() == report
    with pytest.raises(ValueError, match="int64"):
        _DirectionalReference(1, 10, 1, (1., 2.), (2**62, 2**62))


@pytest.mark.parametrize("field,value", [("source", "y"), ("unit", "other"), ("parameter_definition", "other"), ("parameter_version", "2"),
                                        ("market_id", canonicalize_market_id("bybit", "linear", "ETHUSD", "4h"))])
def test_context_identity_is_enforced(field, value):
    with pytest.raises(ValueError, match="context"):
        classify_directional_binning(frame([1], 100), fit([1, 2]), context=context(**{field: value}), mode="forward")
