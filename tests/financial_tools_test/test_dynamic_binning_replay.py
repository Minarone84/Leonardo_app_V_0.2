from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    BinningPolicy, VariationContext, calculate_financial_tool,
    classify_dynamic_binning, fit_dynamic_binning,
)


def _features(data):
    result = data[["ts_ms", "close"]].copy()
    result["available_at_ms"] = data["ts_ms"] + 1
    for period in (20, 50):
        result[f"ema{period}"] = calculate_financial_tool("ema", data, {"period": period}).to_frame().iloc[:, 1]
    for source, fast in (("d1", "ema20"), ("d2", "close")):
        result[source] = calculate_financial_tool("delta", result, {"fast": fast, "slow": "ema50", "mode": "pct"}).to_frame().iloc[:, 1]
    return result


def _context(source):
    return VariationContext(source, canonicalize_market_id("bybit", "linear", "BTCUSD", "1m"),
                            f"delta_pct({source}; EMA20/EMA50 or close/EMA50; canonical epsilon)", "1", "percent")


def _synthetic(rows=400):
    x = np.arange(rows, dtype=float)
    close = 100 + 0.04 * x + 7 * np.sin(x / 8)
    return pd.DataFrame({"ts_ms": np.arange(rows, dtype="int64"), "close": close})


@pytest.mark.parametrize("source", ["d1", "d2"])
@pytest.mark.parametrize("measurement", ["value", "magnitude"])
def test_fixed_profile_batch_chunks_single_row_and_future_append(source, measurement):
    features = _features(_synthetic())
    context = _context(source)
    profile = fit_dynamic_binning(features.iloc[:250], context, profile_id=f"{source}-{measurement}",
                                  calibration_as_of_ms=250, provenance=("dummy",),
                                  measurement=measurement, policy=BinningPolicy(min_reference_count=100))
    original = profile.to_dict()
    heldout = features.iloc[250:]
    batch = classify_dynamic_binning(heldout, profile, context=context, mode="forward").to_frame()
    for size in (1, 7, 64):
        chunks = [classify_dynamic_binning(heldout.iloc[start:start + size], profile,
                  context=context, mode="forward").to_frame() for start in range(0, len(heldout), size)]
        pd.testing.assert_frame_equal(pd.concat(chunks), batch, check_exact=True)
    # An application-only future shock must not refit or alter prior labels.
    future = pd.DataFrame({"ts_ms": [400], "available_at_ms": [401], source: [1e12]}, index=[400])
    extended = classify_dynamic_binning(pd.concat([heldout, future]), profile, context=context, mode="forward").to_frame()
    pd.testing.assert_frame_equal(extended.iloc[:-1], batch, check_exact=True)
    assert profile.to_dict() == original
    refit = fit_dynamic_binning(pd.concat([features, future]), context, profile_id="explicit-new-profile",
                                calibration_as_of_ms=401, provenance=("dummy-refit",), measurement=measurement)
    assert refit.profile_id != profile.profile_id
    assert profile.to_dict() == original


def test_causal_ema_delta_prefixes_and_warmup():
    data = _synthetic()
    full = _features(data)
    assert full[["d1", "d2"]].iloc[:49].isna().all().all()
    assert full[["d1", "d2"]].iloc[49:].notna().all().all()
    for stop in (50, 100, 250, 251, 399):
        prefix = _features(data.iloc[:stop])
        pd.testing.assert_frame_equal(prefix, full.iloc[:stop], check_exact=True)


@pytest.mark.parametrize("tool", ["derivative", "angle"])
def test_centered_feature_requires_following_observation(tool):
    data = _synthetic(80)
    whole = calculate_financial_tool(tool, data, bindings={"source": "close"}).to_frame().iloc[:, 1]
    prefix = calculate_financial_tool(tool, data.iloc[:60], bindings={"source": "close"}).to_frame().iloc[:, 1]
    assert pd.isna(prefix.iloc[-1]) and pd.notna(whole.iloc[59])
    assert prefix.iloc[-2] == whole.iloc[58]
    context = _context("x")
    # Value assigned to bar t needs the next bar, itself available at t + 2 here.
    reference = pd.DataFrame({"ts_ms": data["ts_ms"].iloc[:50], "available_at_ms": data["ts_ms"].iloc[:50] + 2,
                              "x": whole.iloc[:50]})
    with pytest.raises(ValueError, match="after calibration_as_of"):
        fit_dynamic_binning(reference, context, profile_id="premature", calibration_as_of_ms=50, provenance=("dummy",))
    profile = fit_dynamic_binning(reference, context, profile_id="delayed", calibration_as_of_ms=51, provenance=("dummy",))
    arriving = pd.DataFrame({"ts_ms": [50], "available_at_ms": [52], "x": [whole.iloc[50]]})
    result = classify_dynamic_binning(arriving, profile, context=context, mode="forward").to_frame()
    assert result["available_at_ms"].iloc[0] == 52


def test_missing_warmup_rows_are_identical_under_single_row_replay():
    data = _features(_synthetic())
    context = _context("d1")
    profile = fit_dynamic_binning(data, context, profile_id="retrospective", calibration_as_of_ms=400, provenance=("dummy",))
    batch = classify_dynamic_binning(data.iloc[:60], profile, context=context, mode="retrospective").to_frame()
    replay = pd.concat([classify_dynamic_binning(data.iloc[i:i+1], profile, context=context, mode="retrospective").to_frame()
                        for i in range(60)])
    pd.testing.assert_frame_equal(replay, batch, check_exact=True)
    assert batch["status"].eq("missing_value").sum() == 49
