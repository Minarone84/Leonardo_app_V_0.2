"""Old numeric contract, strict current payload, and exact replay invariants."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import FinancialToolCalculationResult, UtcClassificationResult, calculate_financial_tool, classify_utc_as_of, get_utc_classification
from tests.financial_tools_test.test_utc_classification import CASES, _frame, _parameters
from tests.financial_tools_test.test_utc_classification_timing import _canonical


def with_analysis(result, analysis):
    return FinancialToolCalculationResult(tool_key=result.tool_key, kind=result.kind,
        parameters=result.parameters, bindings=result.bindings, output_names=result.output_names,
        frame=result.to_frame(), analysis=analysis)


@pytest.mark.parametrize("length", (1, 2, 4, 120))
def test_short_and_full_inputs_preserve_27_outputs_without_context(length):
    data, params, context = _canonical(5)
    data = data.iloc[:length].copy()
    # Recalculate centered dependencies on the truncated frame.
    pt = calculate_financial_tool("peaks_troughs", data).to_frame()
    for name in pt.columns[1:]:
        data[name] = pt[name]
    context = replace(context, bar_closed_at_ms=context.bar_closed_at_ms[:length])
    unknown = calculate_financial_tool("UTC", data, params)
    known = calculate_financial_tool("universal_trend_classifier", data, params, utc_context=context)
    assert len(known.output_names) == 27
    pd.testing.assert_frame_equal(known.to_frame(), unknown.to_frame(), check_exact=True)
    legacy = with_analysis(known, {})
    assert get_utc_classification(legacy).status == "legacy_unavailable"
    pd.testing.assert_frame_equal(legacy.to_frame(), known.to_frame(), check_exact=True)


@pytest.mark.parametrize("fault", ("version", "rank", "context_length", "early_event", "missing", "unknown_section"))
def test_malformed_current_payload_cannot_be_treated_as_legacy(fault):
    data, params, context = _canonical(5)
    result = calculate_financial_tool("UTC", data, params, utc_context=context)
    analysis = result.analysis
    payload = analysis["utc_classification"]
    if fault == "version": payload["schema_version"] = "99"
    elif fault == "rank": payload["episodes"][0]["formation_key"] = "UP/TPP/0,0,0"
    elif fault == "context_length": payload["context"]["bar_closed_at_ms"].pop()
    elif fault == "early_event": payload["continuations"][0]["known_at_ms"] = 1
    elif fault == "missing": payload.pop("episodes")
    else: analysis["invented"] = {}
    with pytest.raises(ValueError):
        with_analysis(result, analysis)


def test_replay_empty_cutoff_append_identity_and_configuration_separation():
    data, params, context = _canonical(5)
    empty = classify_utc_as_of(data, params, context=context, as_of_ms=int(data.ts_ms.iloc[0]))
    assert empty.episodes == () and empty.to_dict()["timestamps_ms"] == []
    first = classify_utc_as_of(data, params, context=context, as_of_ms=context.bar_closed_at_ms[75])
    later = classify_utc_as_of(data, params, context=context, as_of_ms=context.bar_closed_at_ms[-1])
    lookup = {e["episode_id"]: e for e in later.episodes}
    for episode in first.episodes:
        assert lookup[episode["episode_id"]]["formation"] == episode["formation"]
        assert lookup[episode["episode_id"]]["confirmed_at_ms"] == episode["confirmed_at_ms"]
    other = classify_utc_as_of(data, params, context=replace(context, stream_id="other/ETH"), as_of_ms=context.bar_closed_at_ms[-1])
    assert not set(lookup).intersection(e["episode_id"] for e in other.episodes)


def test_identical_price_words_retain_distinct_equality_relationships():
    strict = get_utc_classification(calculate_financial_tool("UTC", _frame(CASES[1]), _parameters()))
    equal = get_utc_classification(calculate_financial_tool("UTC", _frame(CASES[2]), _parameters()))
    assert strict.episodes[0]["formation_key"] != equal.episodes[0]["formation_key"]


@pytest.mark.parametrize("path", (
    ("episodes", 0, "segment_start_ms"),
    ("episodes", 0, "decision_frontier_ms"),
    ("episodes", 0, "formation", 0, "ts_ms"),
    ("continuations", 0, "decision_frontier_ms"),
    ("continuations", 0, "swing", "ts_ms"),
))
def test_payload_rejects_float_timestamps_even_when_numerically_equal(path):
    data, params, context = _canonical(5)
    payload = get_utc_classification(calculate_financial_tool("UTC", data, params, utc_context=context)).to_dict()
    owner = payload
    for key in path[:-1]:
        owner = owner[key]
    owner[path[-1]] = float(owner[path[-1]])
    with pytest.raises(ValueError, match="int64"):
        UtcClassificationResult(payload)


def test_payload_rejects_float_restart_timestamp():
    data = _frame((("T", 100), ("P", 110), ("T", 105), ("T", 103)))
    payload = get_utc_classification(calculate_financial_tool("UTC", data, _parameters())).to_dict()
    restart = payload["episodes"][0]["restart_chain"][0]
    restart["restart_ts_ms"] = float(restart["restart_ts_ms"])
    with pytest.raises(ValueError, match="int64"):
        UtcClassificationResult(payload)


@pytest.mark.parametrize("order", ("decision", "availability"))
def test_payload_rejects_reordered_continuation_evidence(order):
    data, params, context = _canonical(5)
    payload = get_utc_classification(calculate_financial_tool("UTC", data, params, utc_context=context)).to_dict()
    if order == "decision":
        payload["continuations"].reverse()
    else:
        payload["continuations"][0]["known_at_ms"] = payload["continuations"][-1]["known_at_ms"]
    with pytest.raises(ValueError, match=f"{order} order"):
        UtcClassificationResult(payload)


@pytest.mark.parametrize("basis", ("unknown", "canonical", "custom"))
def test_numeric_string_pt_inputs_preserve_outputs_and_caller_frame(basis):
    data, parameters, context = _canonical(5)
    if basis == "unknown":
        context = None
    elif basis == "custom":
        closes = context.bar_closed_at_ms
        context = replace(context, canonical_window=None,
                          swing_available_at_ms=tuple(closes[i+2] if i+2 < len(data) else None
                                                      for i in range(len(data))))
    expected = calculate_financial_tool("UTC", data, parameters, utc_context=context)
    strings = data.copy(deep=True)
    for column in (parameters["peak_column"], parameters["trough_column"]):
        strings[column] = strings[column].map(lambda value: str(value) if pd.notna(value) else value)
    before = strings.copy(deep=True)
    actual = calculate_financial_tool("UTC", strings, parameters, utc_context=context)
    pd.testing.assert_frame_equal(actual.to_frame(), expected.to_frame(), check_exact=True)
    assert len(actual.output_names) == 27
    pd.testing.assert_frame_equal(strings, before, check_exact=True)
    assert [e["formation"] for e in get_utc_classification(actual).episodes] == [
        e["formation"] for e in get_utc_classification(expected).episodes]


@pytest.mark.parametrize("bad", ("not-a-number", True))
def test_invalid_pt_inputs_remain_rejected(bad):
    data = _frame(CASES[1])
    data["peak_fractal_5"] = data["peak_fractal_5"].astype(object)
    data.loc[3, "peak_fractal_5"] = bad
    with pytest.raises(ValueError, match="numeric or null"):
        calculate_financial_tool("UTC", data, _parameters())
