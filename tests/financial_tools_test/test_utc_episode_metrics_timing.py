"""Measurements retain historical/causal boundaries and immutable formation facts."""
from dataclasses import replace

import pytest

from leonardo.financial_tools import (
    UtcClassificationContext, calculate_financial_tool, classify_utc_as_of,
    get_utc_episode_metrics, measure_utc_as_of,
)
from leonardo.financial_tools._calculation.utc_episode_metrics import _digest
from tests.financial_tools_test.test_utc_classification import _frame, _parameters
from tests.financial_tools_test.test_utc_classification_timing import _canonical
from tests.financial_tools_test.test_utc_episode_metrics import measured, STANDARD


@pytest.mark.parametrize("window", (3,5,7,9,11))
def test_asof_report_binds_final_classification_and_cannot_see_future(window):
    data, parameters, context = _canonical(window)
    for pos in (0,30,60,90,119):
        cutoff = context.bar_closed_at_ms[pos]
        report = measure_utc_as_of(data, parameters, context=context, as_of_ms=cutoff)
        core = classify_utc_as_of(data, parameters, context=context, as_of_ms=cutoff)
        value = report.to_dict()
        assert value["classification_sha256"] == _digest(core.to_dict())
        assert value["as_of_ms"] == cutoff and value["observation_mode"] == "as_of"
        assert report.context_at_cutoff["last_available_bar"]["position"] == pos
        for episode in report.episodes:
            assert episode["formation_metrics"]["confirmed_at_ms"] <= cutoff
            assert episode["episode_metrics"]["available_at_ms"] <= cutoff
            for pull in episode["pullbacks"]:
                assert pull["opened_at_ms"] <= cutoff
                assert pull["recovered_at_ms"] is None or pull["recovered_at_ms"] <= cutoff
        if pos > 10:
            prefix = data.iloc[:pos+1].copy()
            pt = calculate_financial_tool("peaks_troughs", prefix).to_frame()
            for name in pt.columns[1:]: prefix[name] = pt[name]
            prefix_context = replace(context, bar_closed_at_ms=context.bar_closed_at_ms[:pos+1])
            other = measure_utc_as_of(prefix, parameters, context=prefix_context, as_of_ms=cutoff)
            other_value = other.to_dict()
            # Unused centered P/T columns and tail availability still participate in
            # the original input fingerprint; equivalent facts need not share it.
            for binding in ("input_key", "classification_sha256"):
                other_value.pop(binding)
            assert other_value == {k:v for k,v in value.items() if k not in ("input_key", "classification_sha256")}


def test_empty_prefix_and_unknown_availability():
    data, params, context = _canonical(5)
    empty = measure_utc_as_of(data, params, context=context, as_of_ms=int(data.ts_ms.iloc[0]))
    assert not empty.episodes
    assert empty.context_at_cutoff["last_available_bar"] is None
    assert empty.context_at_cutoff["published_membership"] is None
    with pytest.raises(ValueError, match="availability"):
        measure_utc_as_of(data, params, context=UtcClassificationContext(), as_of_ms=int(data.ts_ms.iloc[-1]))
    _, unknown = measured(known=False)
    formation = unknown.episodes[0]["formation_metrics"]
    assert formation["movement"]["available_at_ms"] is None
    assert formation["confirmation_delay_ms"] is None


def test_restart_confirmation_uses_frontier_not_earlier_pivot_only():
    data = _frame((("T",100),("P",110),("T",105),("T",103)))
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    available = tuple(closes[min(i+2,len(data)-1)] for i in range(len(data)))
    ctx = UtcClassificationContext(stream_id="restart", bar_closed_at_ms=closes, swing_available_at_ms=available)
    result = calculate_financial_tool("UTC", data, _parameters(), utc_context=ctx)
    episode = get_utc_episode_metrics(result).episodes[0]
    assert episode["formation_metrics"]["confirmed_at_ms"] == available[7]
    assert episode["formation_metrics"]["movement"]["available_at_ms"] == available[7]
    assert not measure_utc_as_of(data, _parameters(), context=ctx, as_of_ms=available[7]-1).episodes
    assert measure_utc_as_of(data, _parameters(), context=ctx, as_of_ms=available[7]).episodes


def test_actual_gap_duration_and_retrospective_context_are_explicit():
    data = _frame(STANDARD)
    data.loc[5:, "ts_ms"] += 3_600_000
    _, report = measured(frame=data)
    episode = report.episodes[0]
    assert episode["formation_metrics"]["duration"] == {"bars": 6, "ms": 3_960_000}
    spacing = episode["formation_metrics"]["movement"]["spacing"]
    assert spacing == {"row_count":7,"min_delta_ms":60_000,"max_delta_ms":3_660_000,"uniform":False}
    preceding = episode["preceding_context"]
    assert preceding["interpretation"] == "retrospective" and preceding["available_at_ms"] is None
    assert preceding["preceding_bar"]["position"] == 0
    assert preceding["preceding_membership"] == {"uptrend":False,"downtrend":False,"horizontal_range":False}


def test_input_local_identity_is_not_promised_to_survive_append():
    _, first = measured(STANDARD, tail=4, stream=None)
    _, later = measured(STANDARD, tail=8, stream=None)
    assert first.episodes[0]["episode_id"] != later.episodes[0]["episode_id"]
    a, b = first.episodes[0]["formation_metrics"], later.episodes[0]["formation_metrics"]
    assert a["movement"] == b["movement"]


@pytest.mark.parametrize("availability", ("future", "unknown"))
@pytest.mark.parametrize("boundary", ("model", "analysis"))
def test_asof_loader_rejects_consistent_unavailable_nonwitness_swing(availability, boundary, monkeypatch):
    from leonardo.financial_tools import UtcEpisodeMetricsResult
    from leonardo.financial_tools._calculation import utc_episode_metrics as engine
    from leonardo.financial_tools.utc_classification import _validate_utc_analysis
    data = _frame(STANDARD)
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    times = [c+120_000 for c in closes]
    if availability == "unknown":
        times[9] = None
    context = UtcClassificationContext(stream_id="cutoff-load", bar_closed_at_ms=closes,
                                       swing_available_at_ms=tuple(times))
    cutoff = closes[9]
    core = classify_utc_as_of(data, _parameters(), context=context, as_of_ms=cutoff).to_dict()
    report = measure_utc_as_of(data, _parameters(), context=context, as_of_ms=cutoff)
    evidence = report.to_dict()["evidence"]
    assert 9 not in [s["position"] for s in evidence["segments"][0]["swings"]]
    assert all(s["position"] != 9 for e in core["episodes"] for s in e["formation"])
    assert all(e["swing"]["position"] != 9 for e in core["continuations"])
    evidence["segments"][0]["swings"].append({"kind": "T", "position": 9,
        "ts_ms": int(data.ts_ms.iloc[9]), "value": 108., "available_at_ms": times[9]})
    validate = engine._validate_evidence
    # Build a fully consistent malformed report without the as-of guard, then
    # restore the real validator before exercising the public load boundaries.
    with monkeypatch.context() as patch:
        patch.setattr(engine, "_validate_evidence", lambda core, evidence:
            validate({**core, "status": "retrospective", "as_of_ms": None}, evidence))
        payload = engine._build_metrics(core, evidence)
    assert len(payload["episodes"][0]["pullbacks"]) == 2
    with pytest.raises(ValueError, match="as-of cutoff"):
        if boundary == "model":
            UtcEpisodeMetricsResult.from_dict(payload, classification=core)
        else:
            _validate_utc_analysis({"utc_classification": core, "utc_episode_metrics": payload})


def test_asof_loader_accepts_exact_cutoff_and_historical_unknown_availability():
    from leonardo.financial_tools import UtcEpisodeMetricsResult
    data = _frame(STANDARD)
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    cutoff = closes[9]
    times = [c+120_000 for c in closes]
    times[9] = cutoff
    context = UtcClassificationContext(stream_id="cutoff-load", bar_closed_at_ms=closes,
                                       swing_available_at_ms=tuple(times))
    core = classify_utc_as_of(data, _parameters(), context=context, as_of_ms=cutoff)
    report = measure_utc_as_of(data, _parameters(), context=context, as_of_ms=cutoff)
    loaded = UtcEpisodeMetricsResult.from_dict(report.to_dict(), classification=core)
    assert loaded.to_dict() == report.to_dict()
    assert loaded.episodes[0]["pullbacks"][-1]["opened_at_ms"] == cutoff
    assert loaded.episodes[0]["episode_metrics"]["available_at_ms"] == cutoff
    result, historical = measured(known=False)
    assert UtcEpisodeMetricsResult.from_dict(historical.to_dict(),
        classification=result.analysis["utc_classification"]).to_dict() == historical.to_dict()
    assert historical.episodes[0]["pullbacks"][-1]["opened_at_ms"] is None
