from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import (
    UtcClassificationContext, calculate_financial_tool, classify_utc_as_of, get_utc_classification,
)
from tests.financial_tools_test.test_utc_classification import _frame, _parameters, CASES


def _canonical(window):
    n = 120
    axis = np.arange(n)
    close = 100 + 7 * np.sin(axis / 3) + axis * .08
    data = pd.DataFrame(dict(ts_ms=1_700_000_000_000 + axis * 60_000,
                             open=close, high=close+1, low=close-1, close=close, volume=1.))
    points = calculate_financial_tool("peaks_troughs", data).to_frame()
    for column in points:
        if column != "ts_ms":
            data[column] = points[column]
    parameters = {"trend_fractal_window": window, "peak_column": f"peak_fractal_{window}",
                  "trough_column": f"trough_fractal_{window}"}
    context = UtcClassificationContext(stream_id="test/BTC/1m/utc",
                                       input_revision="revision-a",
                                       bar_closed_at_ms=tuple(int(t)+60_000 for t in data.ts_ms),
                                       canonical_window=window)
    return data, parameters, context


@pytest.mark.parametrize("window", (3, 5, 7, 9, 11))
def test_canonical_prefix_replay_uses_only_evidence_available_by_cutoff(window):
    data, parameters, context = _canonical(window)
    full = get_utc_classification(calculate_financial_tool("UTC", data, parameters, utc_context=context))
    assert full.episodes
    for cutoff_pos in range(12, len(data), 7):
        cutoff = context.bar_closed_at_ms[cutoff_pos]
        replay = classify_utc_as_of(data, parameters, context=context, as_of_ms=cutoff)
        expected = {e["episode_id"]: e["formation_key"] for e in full.episodes
                    if e["confirmed_at_ms"] <= cutoff}
        assert {e["episode_id"]: e["formation_key"] for e in replay.episodes} == expected
        assert all(e["confirmed_at_ms"] <= cutoff for e in replay.episodes)
        assert all(e["known_at_ms"] <= cutoff for e in replay.continuations)


def test_explicit_custom_availability_keeps_restart_decision_frontier():
    sequence = (("T",100),("P",110),("T",105),("T",103))
    data = _frame(sequence)
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    available = tuple(closes[min(i+2, len(data)-1)] for i in range(len(data)))
    context = UtcClassificationContext(stream_id="custom", bar_closed_at_ms=closes,
                                       swing_available_at_ms=available)
    full = get_utc_classification(calculate_financial_tool("UTC", data, _parameters(), utc_context=context))
    episode = full.episodes[0]
    assert episode["origin"] == "candidate_restart"
    assert episode["formation"][0]["ts_ms"] < episode["decision_frontier_ms"]
    assert episode["confirmed_at_ms"] == available[7]
    before = classify_utc_as_of(data, _parameters(), context=context, as_of_ms=available[7]-1)
    assert not before.episodes
    at = classify_utc_as_of(data, _parameters(), context=context, as_of_ms=available[7])
    assert at.episodes[0]["formation_key"] == episode["formation_key"]


def test_unknown_and_falsely_claimed_canonical_availability_fail_causal_requests():
    data = _frame(CASES[1])
    with pytest.raises(ValueError, match="availability"):
        classify_utc_as_of(data, _parameters(), context=UtcClassificationContext(), as_of_ms=int(data.ts_ms.iloc[-1]))
    context = UtcClassificationContext(bar_closed_at_ms=tuple(int(t)+60_000 for t in data.ts_ms),
                                       canonical_window=5)
    with pytest.raises(ValueError, match="canonical P/T"):
        calculate_financial_tool("UTC", data, _parameters(), utc_context=context)


def test_gaps_use_actual_closed_bar_timeline_and_preserve_integer_timestamps():
    data, parameters, context = _canonical(5)
    data.loc[50:, "ts_ms"] += 3_600_000
    context = replace(context, bar_closed_at_ms=tuple(int(t)+60_000 for t in data.ts_ms))
    report = get_utc_classification(calculate_financial_tool("UTC", data, parameters, utc_context=context))
    for episode in report.episodes:
        confirming = episode["formation"][-1]
        assert episode["confirmed_at_ms"] >= context.bar_closed_at_ms[confirming["position"]+2]
        assert type(episode["confirmed_at_ms"]) is int
    assert report.to_episode_frame()["confirmed_at_ms"].dtype == object


def test_context_is_utc_only_and_out_of_order_custom_delivery_is_rejected():
    data = _frame(CASES[1])
    with pytest.raises(ValueError, match="only valid for UTC"):
        calculate_financial_tool("sma", data, utc_context=UtcClassificationContext())
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    availability = list(closes)
    availability[1] = closes[-1]
    with pytest.raises(ValueError, match="out-of-order"):
        calculate_financial_tool("UTC", data, _parameters(), utc_context=UtcClassificationContext(
            bar_closed_at_ms=closes, swing_available_at_ms=tuple(availability)))


def test_close_stamped_and_delayed_custom_evidence_are_distinct_from_pivot_time():
    data = _frame(CASES[1])
    closes = tuple(int(t) for t in data.ts_ms)
    available = tuple(t + 30_000 for t in closes)
    context = UtcClassificationContext(stream_id="close-stamped", bar_closed_at_ms=closes,
                                       swing_available_at_ms=available)
    report = get_utc_classification(calculate_financial_tool("UTC", data, _parameters(), utc_context=context))
    assert report.episodes[0]["confirmed_at_ms"] == available[7]
    assert not classify_utc_as_of(data, _parameters(), context=context, as_of_ms=closes[7]).episodes
    assert classify_utc_as_of(data, _parameters(), context=context, as_of_ms=available[7]).episodes


def test_market_context_uses_calendar_month_closes():
    from leonardo.data import MarketId
    from leonardo.data_manager.artifact_materialization import _utc_context
    axis = pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"], utc=True).as_unit("ms").astype("int64")
    data = pd.DataFrame({"ts_ms": axis})
    context = _utc_context(MarketId("bybit", "linear", "BTCUSDT", "1M"), "revision", "logical", {"trend_fractal_window": 5}, data)
    assert context.bar_closed_at_ms == tuple(pd.to_datetime(["2024-02-01", "2024-03-01", "2024-04-01"], utc=True).as_unit("ms").astype("int64"))



@pytest.mark.parametrize("basis", ("canonical", "custom", "unknown"))
@pytest.mark.parametrize("claimed", ("pivot", "null", "late"))
def test_payload_swing_availability_is_bound_to_declared_context(basis, claimed):
    from leonardo.financial_tools import UtcClassificationResult
    data, parameters, context = _canonical(5)
    if basis == "unknown":
        context = None
    elif basis == "custom":
        closes = context.bar_closed_at_ms
        context = replace(context, canonical_window=None,
                          swing_available_at_ms=tuple(closes[i+2] if i+2 < len(data) else None
                                                      for i in range(len(data))))
    payload = get_utc_classification(calculate_financial_tool("UTC", data, parameters, utc_context=context)).to_dict()
    swing = payload["episodes"][0]["formation"][0]
    if claimed == "pivot":
        swing["available_at_ms"] = swing["ts_ms"]
    elif claimed == "late":
        swing["available_at_ms"] = swing["ts_ms"] + 240_000
    else:
        swing["available_at_ms"] = None
    if basis == "unknown" and claimed == "null":
        assert UtcClassificationResult(payload).episodes[0]["confirmed_at_ms"] is None
    else:
        with pytest.raises(ValueError, match="availability.*context"):
            UtcClassificationResult(payload)


def _restart_timing_payload(*, unknown_position=None):
    sequence = (("P",100),("T",118),("P",110),("T",94),
                ("P",108),("T",102),("T",100),("P",109))
    data = _frame(sequence)
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    availability = list(closes)
    if unknown_position is not None:
        availability[unknown_position] = None
    context = UtcClassificationContext(bar_closed_at_ms=closes,
                                       swing_available_at_ms=tuple(availability))
    return get_utc_classification(calculate_financial_tool(
        "UTC", data, _parameters(), utc_context=context)).to_dict()


@pytest.mark.parametrize("unknown_position", (None, 1, 15))
def test_payload_confirmation_includes_restart_and_actual_frontier_availability(unknown_position):
    from leonardo.financial_tools import UtcClassificationResult
    payload = _restart_timing_payload(unknown_position=unknown_position)
    episode = next(e for e in payload["episodes"]
                   if e["decision_frontier_ms"] > e["formation"][-1]["ts_ms"])
    assert episode["restart_chain"]
    # Formation alone is already available; the actual decision is still pending.
    episode["confirmed_at_ms"] = episode["decision_frontier_ms"]
    with pytest.raises(ValueError, match="confirmation precedes available evidence"):
        UtcClassificationResult(payload)


@pytest.mark.parametrize("reference", ("trigger", "previous_anchor"))
def test_restart_swing_availability_cannot_override_context(reference):
    from leonardo.financial_tools import UtcClassificationResult
    payload = _restart_timing_payload()
    swing = payload["episodes"][0]["restart_chain"][0][reference]
    swing["available_at_ms"] = swing["ts_ms"]
    with pytest.raises(ValueError, match="availability.*context"):
        UtcClassificationResult(payload)


@pytest.mark.parametrize("reference", ("swing", "before", "after"))
def test_continuation_swing_availability_cannot_override_context(reference):
    from leonardo.financial_tools import UtcClassificationResult
    data, parameters, context = _canonical(5)
    payload = get_utc_classification(calculate_financial_tool("UTC", data, parameters, utc_context=context)).to_dict()
    event = payload["continuations"][0]
    swing = event["swing"] if reference == "swing" else event[reference]["endpoint"]
    swing["available_at_ms"] = swing["ts_ms"]
    with pytest.raises(ValueError, match="availability.*context"):
        UtcClassificationResult(payload)


def test_continuation_known_time_requires_the_actual_frontier_context():
    from leonardo.financial_tools import UtcClassificationResult
    data, parameters, context = _canonical(5)
    payload = get_utc_classification(calculate_financial_tool("UTC", data, parameters, utc_context=context)).to_dict()
    event = payload["continuations"][0]
    # Move only the declared decision frontier to a later available row.
    # Its timestamp still precedes the old known-at value, so timestamps alone are insufficient.
    event["decision_frontier_ms"] += 60_000
    with pytest.raises(ValueError, match="continuation precedes available evidence"):
        UtcClassificationResult(payload)


def test_payload_canonical_window_must_match_selected_trend_window():
    from leonardo.financial_tools import UtcClassificationResult
    data, parameters, context = _canonical(5)
    payload = get_utc_classification(calculate_financial_tool("UTC", data, parameters, utc_context=context)).to_dict()
    payload["context"]["canonical_window"] = 3
    with pytest.raises(ValueError, match="window.*dependency"):
        UtcClassificationResult(payload)
