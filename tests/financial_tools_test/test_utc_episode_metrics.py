"""Hand-counted measurements, incomplete outcomes and persisted-evidence checks."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import (
    UtcClassificationContext, UtcEpisodeMetricsResult, calculate_financial_tool,
    get_utc_episode_metrics,
)
from tests.financial_tools_test.test_utc_classification import _frame, _parameters
from tests.financial_tools_test.test_utc_classification_compatibility import with_analysis


STANDARD = (("T", 100), ("P", 110), ("T", 105), ("P", 115), ("T", 108), ("P", 116))


def measured(sequence=STANDARD, *, tail=4, known=True, stream="measurements", frame=None):
    data = _frame(sequence, tail=tail) if frame is None else frame
    closes = tuple(int(t)+60_000 for t in data.ts_ms)
    context = UtcClassificationContext(stream_id=stream, bar_closed_at_ms=closes,
        swing_available_at_ms=tuple(c+120_000 for c in closes)) if known else None
    result = calculate_financial_tool("UTC", data, _parameters(), utc_context=context)
    return result, get_utc_episode_metrics(result)


@pytest.mark.parametrize("mirror", (False, True))
def test_hand_counted_formation_and_continuation(mirror):
    sequence = tuple(("T" if k == "P" else "P", 220-v) for k, v in STANDARD) if mirror else STANDARD
    result, report = measured(sequence)
    episode = report.episodes[0]
    formation, current = episode["formation_metrics"], episode["episode_metrics"]
    assert formation["duration"] == {"bars": 6, "ms": 360_000}
    assert formation["movement"]["spacing"]["row_count"] == 7
    assert formation["movement"]["directional_move_points"] == 15
    assert current["observed_structural"]["movement"]["directional_move_points"] == 16
    assert current["final_structural"] is None
    first, second = episode["pullbacks"]
    assert [p["phase"] for p in (first, second)] == ["formation", "continuation"]
    assert [p["depth_points"] for p in (first, second)] == [5, 7]
    assert first["retracement_of_prior_gain_pct"] == 50
    assert second["retracement_of_prior_gain_pct"] == pytest.approx(700/15)
    assert first["total_duration"] == {"bars": 4, "ms": 240_000}
    assert second["depth_pct"] == pytest.approx(700/(105 if mirror else 115))
    assert first["pullback_id"] != second["pullback_id"]
    assert formation["pullback_summary"]["internal_recovered"]["count"] == 1
    assert current["pullback_summary"]["internal_recovered"]["count"] == 2
    assert len(result.output_names) == 27


def test_retained_endpoint_is_not_the_favorable_extreme_and_tail_is_not_final():
    _, report = measured((("T",100),("P",110),("P",115),("P",112)))
    episode = report.episodes[0]
    movement = episode["episode_metrics"]["observed_structural"]["movement"]
    assert movement["signed_move_points"] == 12
    assert movement["pivot_favorable_points"] == 15
    assert movement["pivot_high"]["value"] == 115
    assert episode["episode_metrics"]["status"] == "open"
    assert episode["episode_metrics"]["final_structural"] is None
    pull = episode["pullbacks"][0]
    assert pull["status"] == "pending" and pull["depth_points"] == 3
    assert pull["launch"]["kind"] == pull["worst"]["kind"] == "P"
    _, later = measured((("T",100),("P",110),("P",115),("P",112)), tail=12)
    newer = later.episodes[0]["pullbacks"][0]
    for name in ("pullback_id", "pivot_extent_end", "phase", "interval_membership"):
        assert newer[name] == pull[name]
    assert newer["observed_duration"]["bars"] == pull["observed_duration"]["bars"]+8
    assert later.episodes[0]["formation_metrics"] == episode["formation_metrics"]


def test_accepted_unusual_formation_freezes_pending_pullback_on_later_recovery():
    sequence = (("T",100),("P",110),("T",120),("P",115))
    _, before = measured(sequence)
    _, after = measured((*sequence,("P",122)))
    first, later = before.episodes[0], after.episodes[0]
    assert first["formation_metrics"] == later["formation_metrics"]
    assert first["pullbacks"][0]["pullback_id"] == later["pullbacks"][0]["pullback_id"]
    assert first["pullbacks"][0]["status"] == "pending"
    assert later["pullbacks"][0]["status"] == "recovered"
    assert later["pullbacks"][0]["phase"] == "crosses_formation_boundary"
    assert later["episode_metrics"]["pullback_summary"]["formation_pending_at_boundary"]["count"] == 1


def test_multileg_excursion_counts_once_and_exact_recovery_is_enough():
    _, report = measured((("T",100),("P",110),("T",105),("P",120),
                          ("T",115),("P",118),("P",117),("P",120),("P",121)))
    pull = report.episodes[0]["pullbacks"][1]
    assert pull["adverse_leg_count"] == 2 and pull["depth_points"] == 5
    assert pull["recovery"]["value"] == 120 and pull["recovery"]["position"] == 15
    assert pull["total_duration"]["bars"] == 8


def test_equal_watermark_and_worst_keep_earliest_pivots():
    _, report = measured((("T",100),("P",110),("P",110),("T",105),("T",105),("P",115)))
    pull = report.episodes[0]["pullbacks"][0]
    assert pull["launch"]["position"] == 3 and pull["worst"]["position"] == 7
    assert pull["adverse_leg_count"] == 1


def test_reversal_ends_old_observation_and_cannot_recover_on_later_price():
    result, report = measured((("T",100),("P",110),("T",105),("P",120),
                              ("T",115),("P",118),("T",112),("P",121)))
    old = report.episodes[0]
    termination = next(e for e in result.analysis["utc_classification"]["continuations"] if e["kind"] == "termination")
    current = old["episode_metrics"]
    assert current["final_structural"]["movement"]["endpoint"] == termination["before"]["endpoint"]
    assert current["observation_limit"]["ts_ms"] == termination["decision_frontier_ms"]
    assert old["pullbacks"][-1]["status"] == "ended_unrecovered"
    assert old["pullbacks"][-1]["recovery"] is None
    assert old["pullbacks"][-1]["interval_membership"] == "crosses_endpoint"
    assert current["pullback_summary"]["internal_recovered"]["count"] == 1
    assert report.episodes[1]["preceding_context"]["scanner_predecessor_episode_id"] == old["episode_id"]


def test_nonpositive_percentage_references_have_separate_eligible_denominators():
    _, report = measured((("T",-10),("P",0),("T",-5),("P",5),("T",0),("P",10)))
    episode = report.episodes[0]
    move = episode["episode_metrics"]["observed_structural"]["movement"]
    assert move["signed_move_points"] == 20 and move["signed_move_pct"] is None
    assert move["percentage_reason"] == "nonpositive_reference_price"
    stats = episode["episode_metrics"]["pullback_summary"]["all_observed"]
    assert stats["depth_points"] == {"eligible_count": 2, "mean": 5, "maximum": 5}
    assert stats["depth_pct"] == {"eligible_count": 1, "mean": 100, "maximum": 100}


def test_empty_pullback_cohort_is_zero_count_and_missing_statistics():
    _, report = measured((("T",100),("P",110),("P",115)))
    summary = report.episodes[0]["episode_metrics"]["pullback_summary"]["all_observed"]
    assert summary["count"] == 0
    assert summary["depth_points"] == {"eligible_count": 0, "mean": None, "maximum": None}


def test_invalid_segment_and_ambiguous_pivots_do_not_bridge():
    data = _frame(STANDARD)
    data.loc[12, "close"] = np.nan
    data.loc[9, "peak_fractal_5"] = 199.
    _, report = measured(frame=data)
    episode = report.episodes[0]
    assert episode["episode_metrics"]["status"] == "interrupted"
    assert episode["episode_metrics"]["final_structural"] is None
    assert episode["episode_metrics"]["observation_limit"]["position"] == 11
    assert 9 not in [s["position"] for s in report.to_dict()["evidence"]["segments"][0]["swings"]]


@pytest.mark.parametrize("fault", ("digest", "input", "parameters", "axis", "mode", "version", "id",
                                  "points", "duration", "phase", "count", "known", "final", "float_time", "bool_position"))
def test_rehashed_or_mutated_metrics_are_rejected_by_semantic_validation(fault):
    result, report = measured()
    payload = report.to_dict()
    episode = payload["episodes"][0]
    if fault == "digest": payload["classification_sha256"] = "0"*64
    elif fault == "input": payload["input_key"] = "other"
    elif fault == "parameters": payload["parameters"]["trend_fractal_window"] = 7
    elif fault == "axis": payload["timestamps_ms"][0] += 1
    elif fault == "mode": payload["observation_mode"] = "as_of"
    elif fault == "version": payload["schema_version"] = "2.0"
    elif fault == "id": episode["episode_id"] = "other"
    elif fault == "points": episode["formation_metrics"]["movement"]["signed_move_points"] += 1
    elif fault == "duration": episode["formation_metrics"]["duration"]["bars"] += 1
    elif fault == "phase": episode["pullbacks"][0]["phase"] = "continuation"
    elif fault == "count": episode["episode_metrics"]["pullback_summary"]["all_observed"]["depth_pct"]["eligible_count"] = 3
    elif fault == "known": episode["pullbacks"][0]["opened_at_ms"] = 1
    elif fault == "final": episode["episode_metrics"]["final_structural"] = episode["episode_metrics"]["observed_structural"]
    elif fault == "float_time": payload["evidence"]["segments"][0]["swings"][0]["ts_ms"] = float(payload["timestamps_ms"][1])
    else: payload["evidence"]["segments"][0]["start_position"] = False
    with pytest.raises(ValueError):
        UtcEpisodeMetricsResult.from_dict(payload, classification=result.analysis["utc_classification"])


def test_three_analysis_forms_and_defensive_views():
    result, report = measured()
    for analysis in ({}, {"utc_classification": result.analysis["utc_classification"]}):
        assert get_utc_episode_metrics(with_analysis(result, analysis)) is None
    with pytest.raises(ValueError):
        with_analysis(result, {"utc_episode_metrics": report.to_dict()})
    copied = report.to_dict()
    copied["episodes"].clear()
    frame = report.to_episode_frame()
    frame.iloc[0]["formation_metrics"]["movement"]["signed_move_points"] = 900
    pulls = report.to_pullback_frame()
    pulls.iloc[0]["launch"]["value"] = -1
    assert report.episodes[0]["formation_metrics"]["movement"]["signed_move_points"] == 15
    assert report.episodes[0]["pullbacks"][0]["launch"]["value"] == 110
    assert report.to_episode_frame().episode_id.dtype == object


def test_source_numeric_strings_are_coerced_without_mutation():
    data = _frame(STANDARD)
    data["high"] = data.high.astype(str)
    data["low"] = data.low.astype(str)
    before = data.copy(deep=True)
    _, report = measured(frame=data)
    pd.testing.assert_frame_equal(before, data, check_exact=True)
    assert report.episodes[0]["formation_metrics"]["movement"]["bar_envelope_high"]["value"] == 200


def test_overflow_is_missing_optional_measurement_not_a_new_detection_failure():
    _, report = measured((("T",1e-320),("P",1.),("P",2.)))
    move = report.episodes[0]["formation_metrics"]["movement"]
    assert move["signed_move_points"] == 2.
    assert move["signed_move_pct"] is None
    assert move["unavailable_measurements"]["signed_move_pct"] == "nonfinite_result"


@pytest.mark.parametrize("fault", ("restart", "segment_tail", "missing_high"))
def test_consistently_rebuilt_witnesses_cannot_contradict_core_evidence(fault):
    from leonardo.financial_tools._calculation.utc_episode_metrics import _build_metrics
    result, report = measured((("T",105),("T",100),("P",110),("P",115)))
    evidence = report.to_dict()["evidence"]
    if fault == "restart": evidence["segments"][0]["swings"][0]["value"] = 999.
    elif fault == "segment_tail": evidence["segments"][0]["end_position"] = 7
    else: evidence["bars"][1]["high"] = None
    with pytest.raises(ValueError):
        _build_metrics(result.analysis["utc_classification"], evidence)


@pytest.mark.parametrize("mirror", (False, True))
def test_interval_spacing_retains_each_recovered_pullback_and_extension_interval(mirror):
    sequence = tuple(("T" if k == "P" else "P", 220-v) for k, v in STANDARD) if mirror else STANDARD
    data = _frame(sequence)
    data.loc[4:, "ts_ms"] += 3_600_000
    data.loc[10:, "ts_ms"] += 7_200_000
    result, report = measured(frame=data)
    episode = report.episodes[0]
    first, second = episode["pullbacks"]
    assert first["descent_duration"] == {"bars": 2, "ms": 3_720_000}
    assert first["descent_spacing"] == {"row_count": 3, "min_delta_ms": 60_000,
                                        "max_delta_ms": 3_660_000, "uniform": False}
    assert first["recovery_spacing"] == {"row_count": 3, "min_delta_ms": 60_000,
                                         "max_delta_ms": 60_000, "uniform": True}
    assert first["total_spacing"] == {"row_count": 5, "min_delta_ms": 60_000,
                                      "max_delta_ms": 3_660_000, "uniform": False}
    assert second["descent_spacing"] == first["recovery_spacing"]
    assert second["recovery_spacing"] == {"row_count": 3, "min_delta_ms": 60_000,
                                          "max_delta_ms": 7_260_000, "uniform": False}
    expected_extension = {"row_count": 5, "min_delta_ms": 60_000,
                          "max_delta_ms": 7_260_000, "uniform": False}
    assert second["total_spacing"] == expected_extension
    assert episode["episode_metrics"]["endpoint_extension_spacing"] == expected_extension
    assert episode["episode_metrics"]["endpoint_extension"] == {"bars": 4, "ms": 7_440_000}
    assert first["observed_spacing"] is second["observed_spacing"] is None
    assert episode["formation_metrics"]["pullbacks"][0]["total_spacing"] == first["total_spacing"]
    loaded = UtcEpisodeMetricsResult.from_dict(report.to_dict(), classification=result.analysis["utc_classification"])
    assert loaded.to_dict() == report.to_dict()


def test_interval_spacing_pending_and_single_row_extension_remain_distinct():
    data = _frame(STANDARD[:-1])
    data.loc[8:, "ts_ms"] += 3_600_000
    _, report = measured(frame=data)
    episode = report.episodes[0]
    pending = episode["pullbacks"][-1]
    assert pending["status"] == "pending"
    assert pending["observed_duration"] == {"bars": 6, "ms": 3_960_000}
    assert pending["observed_spacing"] == {"row_count": 7, "min_delta_ms": 60_000,
                                           "max_delta_ms": 3_660_000, "uniform": False}
    assert pending["recovery_duration"] is pending["total_duration"] is None
    assert pending["recovery_spacing"] is pending["total_spacing"] is None
    assert episode["episode_metrics"]["endpoint_extension"] == {"bars": 0, "ms": 0}
    assert episode["episode_metrics"]["endpoint_extension_spacing"] == {
        "row_count": 1, "min_delta_ms": None, "max_delta_ms": None, "uniform": None}


@pytest.mark.parametrize("field", ("descent_spacing", "recovery_spacing", "total_spacing",
                                    "observed_spacing", "endpoint_extension_spacing"))
@pytest.mark.parametrize("fault", ("missing", "incorrect"))
def test_interval_spacing_cannot_be_omitted_or_replaced_on_load(field, fault):
    result, report = measured(STANDARD[:-1] if field == "observed_spacing" else STANDARD)
    payload = report.to_dict()
    episode = payload["episodes"][0]
    target = episode["episode_metrics"] if field == "endpoint_extension_spacing" else episode["pullbacks"][-1]
    if fault == "missing":
        del target[field]
    else:
        target[field]["row_count"] += 1
    with pytest.raises(ValueError, match="disagree with retained evidence"):
        UtcEpisodeMetricsResult.from_dict(payload, classification=result.analysis["utc_classification"])
