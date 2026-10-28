from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import calculate_financial_tool, get_utc_classification


CASES = (
    (("T", 100), ("P", 110), ("P", 115)),
    (("T", 100), ("P", 110), ("T", 105), ("P", 115)),
    (("T", 100), ("P", 110), ("T", 100), ("P", 115)),
    (("T", 100), ("T", 103), ("P", 110), ("P", 115)),
    (("T", 100), ("P", 110), ("P", 108), ("P", 115)),
    (("T", 100), ("P", 110), ("P", 110), ("P", 115)),
    (("T", 100), ("P", 110), ("P", 108), ("T", 105), ("P", 115)),
    (("T", 100), ("P", 110), ("T", 103), ("T", 105), ("P", 115)),
    (("T", 100), ("P", 110), ("T", 102), ("P", 108), ("T", 105), ("P", 115)),
    (("T", 100), ("P", 110), ("T", 105), ("P", 108), ("T", 106), ("P", 109), ("T", 107), ("P", 115)),
)


def _frame(sequence, *, tail=4):
    n = len(sequence) * 2 + tail
    frame = pd.DataFrame({
        "ts_ms": np.arange(n, dtype="int64") * 60_000 + 1_700_000_000_000,
        "open": 125., "high": 200., "low": 50., "close": 125., "volume": 1.,
        "peak_fractal_5": np.nan, "trough_fractal_5": np.nan,
        "peak_fractal_3": np.nan, "trough_fractal_3": np.nan,
    })
    for i, (kind, value) in enumerate(sequence):
        frame.loc[1 + 2 * i, "peak_fractal_5" if kind == "P" else "trough_fractal_5"] = value
    return frame


def _parameters():
    return {"peak_column": "peak_fractal_5", "trough_column": "trough_fractal_5"}


def _result(sequence, **kwargs):
    return calculate_financial_tool("UTC", _frame(sequence), _parameters(), **kwargs)


@pytest.mark.parametrize("sequence", CASES)
@pytest.mark.parametrize("mirror", (False, True))
def test_all_audited_formations_preserve_exact_events_and_price_order(sequence, mirror):
    if mirror:
        sequence = tuple(("T" if kind == "P" else "P", 220 - value) for kind, value in sequence)
    report = get_utc_classification(_result(sequence))
    episode = report.episodes[0]
    prices = sorted(set(value for _, value in sequence))
    key = ("DOWN" if mirror else "UP") + "/" + "".join(k for k, _ in sequence)
    key += "/" + ",".join(str(prices.index(v)) for _, v in sequence)
    assert episode["formation_key"] == key
    assert [(s["kind"], s["value"]) for s in episode["formation"]] == list(sequence)
    assert episode["origin"] == "initial_candidate"
    assert episode["confirmed_at_ms"] is None
    assert episode["status"] == "open"
    assert report.status == "retrospective"
    assert report.to_episode_frame()["formation_key"].tolist() == [key]


@pytest.mark.parametrize("sequence,origin", [
    ((("T",100),("P",110),("T",105),("T",103)), "candidate_restart"),
    ((("T",100),("P",110),("T",105),("P",115),("T",104),("T",103)), "post_break_restart"),
    ((("T",100),("P",110),("T",105),("P",115),("T",108),("P",112),("T",104)), "direct_reversal"),
    ((("P",120),("T",110),("P",115),("T",105),("P",112),("T",108),("P",116)), "direct_reversal"),
])
def test_origins_follow_actual_scanner_transition(sequence, origin):
    report = get_utc_classification(_result(sequence))
    episode = report.episodes[-1]
    assert episode["origin"] == origin
    if origin == "direct_reversal":
        assert episode["predecessor_episode_id"] == report.episodes[-2]["episode_id"]
        assert episode["shared_pivot"] == episode["formation"][0]
    else:
        assert episode["restart_chain"]


def test_continuation_does_not_reclassify_formation_and_keeps_lower_endpoint():
    report = get_utc_classification(_result((("T",100),("P",110),("P",115),("P",112))))
    episode = report.episodes[0]
    assert episode["formation_key"] == "UP/TPP/0,1,2"
    events = report.continuations
    assert events[-1]["kind"] == "endpoint_replacement"
    assert events[-1]["after"]["endpoint"]["value"] == 112
    assert events[-1]["episode_id"] == episode["episode_id"]


def test_payload_is_defensively_copied_and_rejects_unknown_version():
    result = _result(CASES[1])
    report = get_utc_classification(result)
    original = deepcopy(report.to_dict())
    copy = report.episodes
    copy[0]["formation_key"] = "corrupted"
    assert report.to_dict() == original
    payload = original.copy()
    payload["schema_version"] = "unknown"
    with pytest.raises(ValueError, match="schema"):
        type(report).from_dict(payload)


def test_invalid_price_gap_prevents_bridge_and_ambiguous_event_is_skipped():
    frame = _frame(CASES[1])
    frame.loc[4, "close"] = np.nan
    result = calculate_financial_tool("UTC", frame, _parameters())
    assert not get_utc_classification(result).episodes
    frame = _frame(CASES[1])
    frame.loc[5, "peak_fractal_5"] = 180.
    report = get_utc_classification(calculate_financial_tool("UTC", frame, _parameters()))
    assert report.episodes[0]["formation_key"] == "UP/TPP/0,1,2"


def test_anchor_reselection_preserves_origin_and_displaced_anchor():
    report = get_utc_classification(_result((("T",105),("T",100),("P",110),("P",115))))
    episode = report.episodes[0]
    assert episode["formation_key"] == "UP/TPP/0,1,2"
    assert episode["origin"] == "initial_candidate"
    assert episode["restart_chain"][0]["reason"] == "anchor_reselection"
    assert episode["restart_chain"][0]["previous_anchor"]["value"] == 105
    assert episode["restart_chain"][0]["trigger"]["value"] == 100
    assert report.to_dict()["availability_reason"] == "no_verified_availability_context"

