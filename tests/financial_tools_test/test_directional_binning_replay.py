from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    DirectionalBinningPolicy, DirectionalBinningProfile, VariationContext, analyze_directional_variation,
    calculate_financial_tool, classify_directional_binning, fit_directional_binning,
)


def context(source="x"):
    return VariationContext(source, canonicalize_market_id("bybit", "linear", "BTCUSD", "1m"),
                            "synthetic prepared feature; fixed definition", "1", "percent")


def frame(values):
    times = np.arange(len(values), dtype="int64")
    return pd.DataFrame({"ts_ms": times, "available_at_ms": times + 1, "x": values})


def fit(data, source="x"):
    return fit_directional_binning(data, context(source), profile_id=source + "-profile", calibration_as_of_ms=len(data),
                                   provenance=("synthetic",), policy=DirectionalBinningPolicy(min_reference_count=100))


def features(data):
    result = data.copy()
    result["available_at_ms"] = data["ts_ms"] + 1
    for period in (20, 50):
        result[f"ema{period}"] = calculate_financial_tool("ema", data, {"period": period}).to_frame().iloc[:, 1]
    for source, fast in (("ema_delta", "ema20"), ("close_delta", "close")):
        result[source] = calculate_financial_tool("delta", result, {"fast": fast, "slow": "ema50", "mode": "pct"}).to_frame().iloc[:, 1]
    return result


@pytest.mark.parametrize("source", ["ema_delta", "close_delta"])
def test_synthetic_ema_replay_chunks_future_append_and_profile_restore(source):
    x = np.arange(400, dtype=float)
    data = pd.DataFrame({"ts_ms": np.arange(400, dtype="int64"), "close": 100 + 0.04 * x + 7 * np.sin(x / 8)})
    prepared = features(data)
    assert prepared[source].iloc[:49].isna().all()
    assert (prepared[source].dropna() > 0).any() and (prepared[source].dropna() < 0).any()
    for stop in (60, 250, 251):
        pd.testing.assert_frame_equal(features(data.iloc[:stop]), prepared.iloc[:stop], check_exact=True)
    profile = fit(prepared.iloc[:250], source)
    before = profile.to_dict()
    restored = DirectionalBinningProfile.from_dict(before)
    arriving = prepared.iloc[250:]
    batch = classify_directional_binning(arriving, profile, context=context(source), mode="forward").to_frame()
    for size in (1, 7, 64):
        pieces = [classify_directional_binning(arriving.iloc[start:start + size], restored,
                  context=context(source), mode="forward").to_frame() for start in range(0, len(arriving), size)]
        pd.testing.assert_frame_equal(pd.concat(pieces), batch, check_exact=True)
    future = pd.DataFrame({"ts_ms": [400], "available_at_ms": [401], source: [1e12]}, index=[400])
    extended = classify_directional_binning(pd.concat([arriving, future]), profile, context=context(source), mode="forward").to_frame()
    pd.testing.assert_frame_equal(extended.iloc[:-1], batch, check_exact=True)
    assert profile.to_dict() == before
    retrospective = classify_directional_binning(prepared.iloc[:60], profile, context=context(source), mode="retrospective").to_frame()
    singles = pd.concat([classify_directional_binning(prepared.iloc[i:i+1], profile, context=context(source), mode="retrospective").to_frame() for i in range(60)])
    pd.testing.assert_frame_equal(retrospective, singles, check_exact=True)
    assert retrospective["status"].eq("missing_value").sum() == 49


@pytest.mark.parametrize("mutation", ["scale", "missing", "constant", "reverse", "invalid", "remove", "add", "reorder"])
def test_other_columns_never_change_selected_source_reference_or_results(mutation):
    data = frame([-4., -1., np.nan, 0., 0.1, 0.2, 0.5, 1.])
    data["other"] = [np.nan, 1., -1., 2., np.nan, 8., 9., -7.]
    changed = data.copy()
    if mutation == "scale": changed["other"] *= 1e200
    elif mutation == "missing": changed["other"] = np.nan
    elif mutation == "constant": changed["other"] = 42
    elif mutation == "reverse": changed["other"] = changed["other"].iloc[::-1].to_numpy()
    elif mutation == "invalid": changed["other"] = "unrelated text"
    elif mutation == "remove": changed = changed.drop(columns="other")
    elif mutation == "add": changed["extra"] = "unrelated text"
    else: changed = changed[list(reversed(changed.columns))]
    reference, actual = fit(data), fit(changed)
    assert actual.to_dict() == reference.to_dict()
    assert actual.analysis.valid_count == 7
    for mode in ("forward", "retrospective"):
        query = frame([-2., 0., 0.1, np.nan, 9.])
        query["ts_ms"] += 100
        query["available_at_ms"] += 100
        a = classify_directional_binning(query, reference, context=context(), mode=mode).to_frame()
        b = classify_directional_binning(query, actual, context=context(), mode=mode).to_frame()
        pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_column_processing_order_and_other_column_override_have_no_effect():
    data = frame([-4., -1., np.nan, 0., 0.1, 0.2, 0.5, 1.])
    data["other"] = [np.nan, 1., -1., 2., np.nan, 8., 9., -7.]
    first = {name: fit(data, name).to_dict() for name in ("x", "other")}
    second = {name: fit(data, name).to_dict() for name in ("other", "x")}
    assert first == second
    analyze_directional_variation(data, "other", policy=DirectionalBinningPolicy(1, 1000, 1))
    assert fit(data).to_dict() == first["x"]


@pytest.mark.parametrize("invalid", [None, 0.5, True])
def test_missing_parameter_does_not_excuse_invalid_availability(invalid):
    data = frame([None, 1.])
    data["available_at_ms"] = pd.Series([invalid, 2], dtype=object)
    with pytest.raises(ValueError, match="available_at_ms"):
        fit(data)


def test_availability_cutoff_forward_and_retrospective_are_explicit():
    data = frame([-1., 1., 2.])
    data["available_at_ms"] += 1
    with pytest.raises(ValueError, match="after calibration_as_of"):
        fit(data)
    profile = fit_directional_binning(data, context(), profile_id="delayed", calibration_as_of_ms=4, provenance=("synthetic",))
    with pytest.raises(ValueError, match="after calibration_as_of"):
        classify_directional_binning(data, profile, context=context(), mode="forward")
    assert len(classify_directional_binning(data, profile, context=context(), mode="retrospective").to_frame()) == 3
    with pytest.raises(ValueError, match="explicitly"):
        classify_directional_binning(data, profile, context=context(), mode="implicit")
    data["available_at_ms"] = [-1, 3, 4]
    with pytest.raises(ValueError, match="precede"):
        fit(data)


def test_empty_classification_is_well_typed_and_does_not_refit():
    profile = fit(frame([1., 2.]))
    before = profile.to_dict()
    rows = classify_directional_binning(frame([]), profile, context=context(), mode="forward").to_frame()
    assert rows.empty
    assert str(rows["bin_index"].dtype) == "Int64" and str(rows["bin_label"].dtype) == "string"
    assert before == profile.to_dict()
