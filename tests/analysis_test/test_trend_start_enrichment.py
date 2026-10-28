"""Saved UTC evidence, inclusive predicates and independent cohort accounting."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from hashlib import sha256
from itertools import product
import json

import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.models import DatabaseUtcClassification
from leonardo.analysis.pattern_models import (
    NumericCondition, PatternRefinement, PrecedingContextFilter, PullbackFilter,
)
from leonardo.analysis.trend_start_patterns import build_catalogue, refine_event, run_study
from leonardo.financial_tools import UtcClassificationContext, calculate_financial_tool
from tests.analysis_test.test_analysis_service import make_database, request
from tests.analysis_test.test_trend_start_catalogue import study_request
from tests.analysis_test.test_trend_start_patterns import counted_fixture
from tests.financial_tools_test.test_utc_classification import _frame, _parameters
from leonardo.analysis.service import AnalysisService


STANDARD = (("T",100),("P",110),("T",105),("P",115),("T",108),("P",116))
ENDED = (("T",100),("P",110),("T",105),("P",120),("T",115),("P",118),("T",112),("P",121))


def saved_analysis(frame, *, known=True, stream="refinement", canonical=False):
    closes = tuple(int(t)+60_000 for t in frame.ts_ms)
    context = (UtcClassificationContext(stream_id=stream, bar_closed_at_ms=closes,
        canonical_window=5 if canonical else None,
        swing_available_at_ms=None if canonical else tuple(c+120_000 for c in closes)) if known else None)
    return calculate_financial_tool("UTC", frame, _parameters(), utc_context=context).analysis


def bundle_for(parent, analyses):
    reports, associations = {}, []
    for provider, analysis, first, last in analyses:
        digest = sha256(json.dumps(analysis, sort_keys=True).encode()).hexdigest()
        reports[digest] = analysis
        associations.append({"artifact_id": provider, "logical_artifact_id": "logical", "column_name": provider,
            "output_name": "uptrend", "first_timestamp_ms": first, "last_timestamp_ms": last, "report_sha256": digest})
    return DatabaseUtcClassification(parent.entry.reference, json.dumps({"schema_version": "1.0",
        "reports": reports, "associations": associations}).encode())


def enriched_fixture(tmp_path, sequence=STANDARD, *, mirror=False, known=True, mutate=None):
    if mirror:
        sequence = tuple(("P" if k == "T" else "T", 220-v) for k,v in sequence)
    frame = _frame(sequence, tail=6)
    store, manifest, saved = make_database(tmp_path, {"delta": np.resize(np.arange(-9.,10.), len(frame))})
    frame["ts_ms"] = saved.ts_ms
    if mutate is not None:
        mutate(frame)
    parent = AnalysisService(store).run(request(manifest, "delta"))
    analysis = saved_analysis(frame, known=known)
    axis = tuple(int(t) for t in frame.ts_ms)
    bundle = bundle_for(parent, [("one", analysis, axis[0], axis[-1])])
    return parent, build_catalogue(parent, bundle, axis), axis, analysis, frame


def movement(basis="completed", minimum=0, maximum=None, *, field="directional_move", unit="points", **kw):
    return PatternRefinement(basis=basis, movement_enabled=True,
        movement=(NumericCondition(field, unit, minimum, maximum),), **kw)


def first_event(catalogue):
    return catalogue.instance("logical")["events"][0]


@pytest.mark.parametrize("condition", [
    ("count", "count", True, None, None), ("count", "count", 1.5, None, None),
    ("structural", "bars", .5, None, None), ("confirmation_delay", "bars", 1, None, None),
    ("directional_move", "pct", float("nan"), None, None),
    ("directional_move", "pct", float("inf"), None, None),
    ("directional_move", "pct", 3, 2, None),
    ("structural", "seconds", Decimal("0.0001"), None, None),
    ("structural", "seconds", Decimal("1000000000000000000000000000.0001"), None, None),
    ("depth", "pct", 1, None, None), ("recovered_duration", "bars", 1.2, None, "maximum"),
])
def test_invalid_numeric_inputs(condition):
    with pytest.raises(ValueError):
        NumericCondition(*condition)


def test_immutable_exact_units_empty_groups_and_validation():
    bound = NumericCondition("structural", "hours", Decimal("0.00001"), Decimal("0.5"))
    assert (bound.unit, bound.minimum, bound.maximum) == ("ms", 36, 1_800_000)
    mean = NumericCondition("recovered_duration", "bars", Decimal("2.5"), statistic="mean")
    assert mean.minimum == Decimal("2.5")
    with pytest.raises(FrozenInstanceError):
        bound.minimum = 1
    empty = PatternRefinement(movement_enabled=True, movement=(NumericCondition("directional_move", "pct"),),
        preceding=PrecedingContextFilter(enabled=True), pullbacks=PullbackFilter(enabled=True))
    assert not empty.active
    assert not PatternRefinement(basis="observed").active
    assert json.loads(json.dumps(empty.to_dict()))["basis"] == "completed"
    with pytest.raises(ValueError, match="duplicate"):
        PatternRefinement(movement=(NumericCondition("signed_move", "points", 0),)*2)
    with pytest.raises(ValueError, match="frozen formation"):
        PatternRefinement(basis="formation", duration_enabled=True,
                          duration=(NumericCondition("observed_elapsed", "bars", 0),))
    with pytest.raises(ValueError, match="cohort"):
        PatternRefinement(basis="formation", pullbacks=PullbackFilter(True, "endpoint_context", (NumericCondition("count", "count", 0),)))
    with pytest.raises(ValueError, match="matching exact direction"):
        PrecedingContextFilter(True, previous_direction="UP", previous_family="DOWN/PTP/2,0,1")


@pytest.mark.parametrize("mirror", (False, True))
def test_exact_completed_signed_directional_and_frozen_observed(tmp_path, mirror):
    parent, catalogue, axis, analysis, _ = enriched_fixture(tmp_path, ENDED, mirror=mirror)
    event = first_event(catalogue)
    assert event["eligible"]
    completed = event["witnesses"][0]["metrics"]["episode_metrics"]
    points = completed["final_structural"]["movement"]["directional_move_points"]
    ref = movement(minimum=points, maximum=points)
    outcome = refine_event(event, ref)
    assert outcome["eligible"] and outcome["resolution"] == "resolved"
    signed = -points if mirror else points
    assert refine_event(event, movement(minimum=signed, maximum=signed, field="signed_move"))["eligible"]
    assert not refine_event(event, movement(minimum=points+1))["eligible"]
    kind = "P" if mirror else "T"
    study = run_study(parent, catalogue, study_request(parent, catalogue, kind=kind, family=event["family"], refinement=ref), axis)
    assert study.frame("events").refinement_eligible.tolist() == [True]
    assert study.frame("families").iloc[0].refined_starts == 1
    assert json.loads(study.context)["refinement"] == ref.to_dict()
    evidence = study.evidence(event["event_id"])
    assert evidence["refinement"]["projection"]["measurements"]["status"] == "ended"
    assert evidence["copied_measurement_reports"]
    evidence["refinement"]["projection"].clear()
    assert study.evidence(event["event_id"])["refinement"]["projection"]


@pytest.mark.parametrize("status", ("open", "interrupted"))
def test_completed_requires_ended_but_context_and_other_bases_do_not(tmp_path, status):
    mutate = (lambda frame: frame.__setitem__("close", frame.close.mask(frame.index == len(frame)-1))) if status == "interrupted" else None
    _, catalogue, _, _, _ = enriched_fixture(tmp_path, mutate=mutate)
    event = first_event(catalogue)
    assert event["witnesses"][0]["episode"]["status"] == status
    unavailable = refine_event(event, movement())
    assert unavailable["reasons"] == ["completed_outcome_unavailable"]
    assert refine_event(event, movement("formation", 15, 15))["eligible"]
    assert refine_event(event, movement("observed", 16, 16))["eligible"]
    context = PatternRefinement(preceding=PrecedingContextFilter(True, previous_direction="NONE"))
    assert refine_event(event, context)["eligible"]


def test_percentage_missing_does_not_block_points_and_partial_depth_is_unavailable(tmp_path):
    _, catalogue, _, _, _ = enriched_fixture(tmp_path, (("T",-10),("P",0),("T",-5),("P",5),("T",0),("P",10)))
    event = first_event(catalogue)
    assert refine_event(event, movement("observed", 20, 20))["eligible"]
    pct = refine_event(event, movement("observed", 0, unit="pct"))
    assert pct["stages"]["movement"]["status"] == "unavailable"
    assert "nonpositive_reference_price" in pct["reasons"]
    partial = PatternRefinement(basis="observed", pullbacks=PullbackFilter(True, "all_observed",
        (NumericCondition("depth", "pct", 0, 200, "maximum"),)))
    assert refine_event(event, partial)["stages"]["pullbacks"]["reason"] == "partial_pullback_statistic_support"
    points = replace(partial, pullbacks=PullbackFilter(True, "all_observed", (NumericCondition("depth", "points", 5, 5, "mean"),)))
    assert refine_event(event, points)["eligible"]


def test_zero_cohort_empty_aggregate_and_recovered_total_duration(tmp_path):
    _, catalogue, _, _, _ = enriched_fixture(tmp_path, (("T",100),("P",110),("P",115)))
    event = first_event(catalogue)
    zero = PatternRefinement(basis="observed", pullbacks=PullbackFilter(True, "internal_recovered", (NumericCondition("count", "count", 0, 0),)))
    assert refine_event(event, zero)["eligible"]
    depth = replace(zero, pullbacks=PullbackFilter(True, "internal_recovered", (NumericCondition("depth", "points", 0, 0, "mean"),)))
    assert refine_event(event, depth)["stages"]["pullbacks"]["status"] == "unavailable"
    _, other, _, _, _ = enriched_fixture(tmp_path / "duration", STANDARD)
    ref = replace(zero, pullbacks=PullbackFilter(True, "internal_recovered", (
        NumericCondition("recovered_duration", "bars", 4, 4, "mean"),
        NumericCondition("recovered_duration", "minutes", 4, 4, "maximum"))))
    assert refine_event(first_event(other), ref)["eligible"]


@pytest.mark.parametrize("up,down,horizontal", tuple(product((False, True), repeat=3)))
def test_independent_preceding_boolean_predicates(tmp_path, up, down, horizontal):
    _, catalogue, _, _, _ = enriched_fixture(tmp_path)
    event = first_event(catalogue)
    flags = event["witnesses"][0]["metrics"]["preceding_context"]["preceding_membership"]
    ref = PatternRefinement(preceding=PrecedingContextFilter(True, up, down, horizontal))
    result = refine_event(event, ref)
    assert result["eligible"] == ((up, down, horizontal) == tuple(flags[k] for k in ("uptrend", "downtrend", "horizontal_range")))
    assert result["resolution"] == "resolved"


def test_segment_start_memberships_unavailable_but_no_previous_valid(tmp_path):
    # Force the valid segment to start on the first swing.
    _, catalogue, _, _, _ = enriched_fixture(tmp_path, mutate=lambda frame: frame.loc.__setitem__((0, "close"), np.nan))
    event = first_event(catalogue)
    assert refine_event(event, PatternRefinement(preceding=PrecedingContextFilter(True, previous_direction="NONE")))["eligible"]
    result = refine_event(event, PatternRefinement(preceding=PrecedingContextFilter(True, False, False, False)))
    assert result["reasons"] == ["unavailable_at_segment_start"]
    combined = movement("formation", 100, preceding=PrecedingContextFilter(True, False, False, False))
    result = refine_event(event, combined)
    assert result["stages"]["preceding_context"]["status"] == "unavailable"
    assert result["stages"]["movement"]["status"] == "mismatch"
    assert len(result["reasons"]) == 2


def test_multiple_failures_funnel_and_selected_candidates_retained(tmp_path):
    parent, catalogue, axis, _, _ = enriched_fixture(tmp_path, ENDED)
    event = first_event(catalogue)
    ref = movement(minimum=100, duration_enabled=True, duration=(NumericCondition("structural", "bars", 100),),
        pullbacks=PullbackFilter(True, "internal_recovered", (NumericCondition("count", "count", 100),)))
    study = run_study(parent, catalogue, study_request(parent, catalogue, family=event["family"], refinement=ref), axis)
    assert study.frame("events").shape[0] == 1 and not study.frame("events").iloc[0].refinement_eligible
    assert len(study.evidence(event["event_id"])["refinement"]["reasons"]) == 3
    funnel = study.frame("refinement_funnel")
    assert all(r.incoming == r.passed+r.mismatched+r.unavailable for r in funnel.itertuples())
    target = funnel[funnel.cohort == "target"].set_index("stage")
    assert target.loc["movement", "mismatched"] == 1
    assert target.loc["duration", "incoming"] == 0
    assert target.loc["included_starts", "passed"] == 0
    assert study.frame("patterns").empty


def test_disabled_legacy_parity_and_nonstart_guard(tmp_path):
    parent, catalogue, axis, req = counted_fixture(tmp_path)
    before = run_study(parent, catalogue, req, axis)
    empty = PatternRefinement(basis="observed", movement_enabled=True, movement=(NumericCondition("signed_move", "pct"),))
    after = run_study(parent, catalogue, replace(req, refinement=empty), axis)
    for name in ("patterns", "frequencies", "families"):
        pd.testing.assert_frame_equal(before.frame(name), after.frame(name), check_exact=True)
    with pytest.raises(ValueError, match="Non-start"):
        replace(req, comparison="non_start", refinement=movement())
    assert replace(req, comparison="non_start", refinement=empty).comparison == "non_start"
    filtered = run_study(parent, catalogue, replace(req, refinement=movement()), axis)
    assert not filtered.frame("events").refinement_eligible.any()
    assert all("legacy_metrics_unavailable" in value for value in filtered.frame("events").refinement_reasons)


def test_duplicate_aliases_ids_legacy_mixture_and_order_independence(tmp_path):
    parent, catalogue, axis, analysis, frame = enriched_fixture(tmp_path, ENDED)
    other = saved_analysis(frame, stream="other-local-input-identity")
    assert analysis["utc_classification"]["episodes"][0]["episode_id"] != other["utc_classification"]["episodes"][0]["episode_id"]
    legacy = {"utc_classification": analysis["utc_classification"]}
    inputs = [("one", analysis, axis[0], axis[-1]), ("two", other, axis[0], axis[-1]), ("legacy", legacy, axis[0], axis[-1])]
    bundle = bundle_for(parent, inputs)
    payload = bundle.to_dict()
    payload["associations"].append({**payload["associations"][0], "column_name": "alias"})
    catalog = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), axis)
    result = refine_event(first_event(catalog), movement())
    assert result["eligible"] and len(result["providers"]) == 2
    assert len(first_event(catalog)["witnesses"]) == 3
    shuffled = build_catalogue(parent, bundle_for(parent, list(reversed(inputs))), axis)
    assert refine_event(first_event(shuffled), movement()) == result


def test_observed_snapshots_ambiguous_frozen_formation_agrees(tmp_path):
    parent, _, axis, analysis, frame = enriched_fixture(tmp_path)
    earlier = saved_analysis(frame.iloc[:-2].copy())
    bundle = bundle_for(parent, [("old", earlier, axis[0], axis[-3]), ("new", analysis, axis[0], axis[-1])])
    catalogue = build_catalogue(parent, bundle, axis)
    event = first_event(catalogue)
    ambiguous = refine_event(event, movement("observed"))
    assert ambiguous["resolution"] == "ambiguous_saved_measurements"
    assert ambiguous["stages"]["movement"]["status"] == "unavailable"
    frozen = refine_event(event, movement("formation"))
    assert frozen["eligible"] and len(frozen["providers"]) == 2


def test_open_to_ended_append_borrows_verified_prefix_and_requires_final_import(tmp_path):
    parent, _, axis, full, frame = enriched_fixture(tmp_path, ENDED)
    prefix = saved_analysis(frame.iloc[:12].copy())
    assert prefix["utc_classification"]["episodes"][0]["status"] == "open"
    inputs = [("old", prefix, axis[0], axis[11]), ("new", full, axis[12], axis[-1])]
    catalogue = build_catalogue(parent, bundle_for(parent, inputs), axis)
    event = first_event(catalogue)
    assert event["eligible"]
    new = next(w for w in event["witnesses"] if w["artifact_id"] == "new")
    assert new["exclusion"] == "recognition_outside_provider_coverage"
    result = refine_event(event, movement())
    assert result["eligible"] and [p["artifact_id"] for p in result["providers"]] == ["new"]
    partial = [("old", prefix, axis[0], axis[11]), ("new", full, axis[12], axis[12])]
    rejected = refine_event(first_event(build_catalogue(parent, bundle_for(parent, partial), axis)), movement())
    assert not rejected["eligible"]
    assert any("coverage" in reason for reason in rejected["reasons"])


@pytest.mark.parametrize("fault", ("hole", "price", "legacy"))
def test_prefix_holes_revisions_and_legacy_cannot_lend_outcome(tmp_path, fault):
    parent, _, axis, full, frame = enriched_fixture(tmp_path, ENDED)
    prefix = saved_analysis(frame.iloc[:12].copy())
    if fault == "price":
        revised = frame.iloc[:12].copy()
        revised.loc[4, "high"] += 1
        prefix = saved_analysis(revised)
    if fault == "legacy":
        prefix = {"utc_classification": prefix["utc_classification"]}
    inputs = [("old", prefix, axis[0], axis[11]), ("new", full, axis[12], axis[-1])]
    if fault == "hole":
        inputs[0] = ("old", prefix, axis[0], axis[3])
        inputs.append(("old", prefix, axis[5], axis[11]))
    result = refine_event(first_event(build_catalogue(parent, bundle_for(parent, inputs), axis)), movement())
    assert not result["eligible"]
    reason = {"hole": "outside_classification_coverage", "price": "conflicting_source_prefix", "legacy": "unverifiable_prefix"}[fault]
    assert reason in result["reasons"]


def test_corrupt_enrichment_raises_even_with_filters_disabled(tmp_path):
    parent, _, axis, analysis, _ = enriched_fixture(tmp_path)
    changed = deepcopy(analysis)
    changed["utc_episode_metrics"]["episodes"][0]["formation_metrics"]["duration"]["bars"] += 1
    with pytest.raises(ValueError, match="disagree"):
        build_catalogue(parent, bundle_for(parent, [("bad", changed, axis[0], axis[-1])]), axis)


def test_family_refresh_does_not_decode_reports(tmp_path, monkeypatch):
    parent, catalogue, axis, _, _ = enriched_fixture(tmp_path, ENDED)
    from leonardo.financial_tools import UtcEpisodeMetricsResult
    monkeypatch.setattr(UtcEpisodeMetricsResult, "from_dict", lambda *a, **kw: pytest.fail("revalidated during family selection"))
    rows = catalogue.families("logical", "T", refinement=movement(minimum=100))
    assert rows[0]["original_starts"] == 1 and rows[0]["refined_starts"] == 0
    event = first_event(catalogue)
    study = run_study(parent, catalogue, study_request(parent, catalogue, family=event["family"], refinement=movement(minimum=100)), axis)
    assert study.frame("families").iloc[0].refined_starts == 0


@pytest.mark.parametrize("fault", (None, "unknown_clock", "rewritten_known_availability", "missing_recognition_row"))
def test_append_tail_maturation_requires_actual_later_support(tmp_path, fault):
    parent, _, axis, full, frame = enriched_fixture(tmp_path, ENDED)
    old_frame = frame.iloc[:12].copy()
    # At the old observation frontier the pivot at old tail row 11 is not yet
    # confirmed. The appended report confirms it using a later imported close.
    old_frame.loc[11, "peak_fractal_5"] = np.nan
    prefix = saved_analysis(old_frame, known=fault != "unknown_clock")
    if fault == "unknown_clock":
        full = saved_analysis(frame, known=False)
    if fault == "rewritten_known_availability":
        # A continuation pivot with established availability may not be moved.
        context = deepcopy(full["utc_classification"]["context"])
        context["swing_available_at_ms"][9] += 60_000
        changed_context = UtcClassificationContext.from_dict(context)
        full = calculate_financial_tool("UTC", frame, _parameters(), utc_context=changed_context).analysis
    selected_axis = tuple(t for t in axis if t != axis[13]) if fault == "missing_recognition_row" else axis
    inputs = [("old", prefix, axis[0], axis[11]), ("new", full, axis[12], axis[-1])]
    catalogue = build_catalogue(parent, bundle_for(parent, inputs), selected_axis)
    result = refine_event(first_event(catalogue), movement())
    assert result["eligible"] == (fault is None)
    if fault == "unknown_clock":
        assert "unverifiable_prefix" in result["reasons"]
    elif fault == "rewritten_known_availability":
        assert "conflicting_source_prefix" in result["reasons"]


def test_unknown_to_known_tail_availability_matures_without_rewriting_prices(tmp_path):
    parent, _, axis, full, frame = enriched_fixture(tmp_path, ENDED)
    old_frame = frame.iloc[:12].copy()
    closes = tuple(int(t)+60_000 for t in old_frame.ts_ms)
    available = tuple(c+120_000 if i < 10 else None for i,c in enumerate(closes))
    prefix = calculate_financial_tool("UTC", old_frame, _parameters(),
        utc_context=UtcClassificationContext(stream_id="refinement", bar_closed_at_ms=closes,
            swing_available_at_ms=available)).analysis
    catalogue = build_catalogue(parent, bundle_for(parent,
        [("old", prefix, axis[0], axis[11]), ("new", full, axis[12], axis[-1])]), axis)
    assert refine_event(first_event(catalogue), movement())["eligible"]


def test_conflicting_completed_outcomes_do_not_use_any_provider_passes(tmp_path):
    parent, _, axis, first, frame = enriched_fixture(tmp_path, ENDED)
    changed = frame.copy()
    changed.loc[4, "high"] = 201
    second = saved_analysis(changed)
    catalogue = build_catalogue(parent, bundle_for(parent,
        [("first", first, axis[0], axis[-1]), ("second", second, axis[0], axis[-1])]), axis)
    outcome = refine_event(first_event(catalogue), movement(minimum=0))
    assert outcome["resolution"] == "ambiguous_saved_measurements"
    assert not outcome["eligible"] and len(outcome["providers"]) == 2


@pytest.mark.parametrize("mirror", (False, True))
def test_same_predicate_applies_to_both_family_cohorts_and_match_lists(tmp_path, mirror):
    parent, legacy, axis, req = counted_fixture(tmp_path, mirror=mirror)
    from tests.financial_tools_test.test_utc_classification import CASES
    sequences = (CASES[1], CASES[1], CASES[2], CASES[2])
    if mirror:
        sequences = tuple(tuple(("P" if k == "T" else "T", 220-v) for k,v in seq) for seq in sequences)
    blocks = []
    for sequence in sequences:
        frame = _frame(sequence, tail=6)
        frame.loc[len(frame)-1, "close"] = np.nan
        blocks.append(frame)
    frame = pd.concat(blocks, ignore_index=True)
    frame["ts_ms"] = axis
    analysis = saved_analysis(frame)
    catalogue = build_catalogue(parent, bundle_for(parent, [("one", analysis, axis[0], axis[-1])]), axis)
    # Every target has five-point internal depth; comparison has ten-point depth.
    refinement = PatternRefinement(basis="formation", pullbacks=PullbackFilter(True, "internal_recovered",
        (NumericCondition("depth", "points", 0, 7, "maximum"),)))
    study = run_study(parent, catalogue, replace(req, run_key=catalogue.run_key, refinement=refinement), axis)
    families = study.frame("families").set_index("family")
    assert families.loc[req.family, "refined_starts"] == 2
    assert families.refined_starts.sum() == 2
    assert study.frame("patterns").comparison_total.tolist() == [0]*len(study.frame("patterns"))
    for pattern in study.frame("patterns").itertuples():
        assert len(study.pattern_matches(pattern.pattern_id)) == pattern.matched
        assert len(study.pattern_matches(pattern.pattern_id, "comparison")) == pattern.comparison_matched
    comparison = study.frame("refinement_funnel")
    comparison = comparison[comparison.cohort == "comparison"].set_index("stage")
    assert comparison.loc["pullbacks", "mismatched"] == 2
    overview = run_study(parent, catalogue, replace(req, family=None, refinement=refinement), axis)
    assert overview.frame("patterns").empty
    assert set(overview.frame("frequencies").family) == {req.family}


def test_frozen_pending_cohort_does_not_turn_into_recovered_duration(tmp_path):
    sequence = (("T",100),("P",110),("T",120),("P",115),("P",122))
    _, catalogue, _, _, _ = enriched_fixture(tmp_path, sequence)
    event = first_event(catalogue)
    count = PatternRefinement(basis="observed", pullbacks=PullbackFilter(True, "formation_pending_at_boundary",
        (NumericCondition("count", "count", 1, 1),)))
    assert refine_event(event, count)["eligible"]
    duration = replace(count, pullbacks=PullbackFilter(True, "formation_pending_at_boundary",
        (NumericCondition("recovered_duration", "bars", 0, statistic="mean"),)))
    assert refine_event(event, duration)["stages"]["pullbacks"]["status"] == "unavailable"


def test_irregular_gaps_are_stored_intervals_not_synthetic_timeframes(tmp_path):
    parent, _, axis, _, frame = enriched_fixture(tmp_path)
    frame.loc[4:, "ts_ms"] += 3_600_000
    irregular_axis = tuple(int(t) for t in frame.ts_ms)
    analysis = saved_analysis(frame)
    catalogue = build_catalogue(parent, bundle_for(parent,
        [("one", analysis, irregular_axis[0], irregular_axis[-1])]), irregular_axis)
    event = first_event(catalogue)
    duration = PatternRefinement(basis="formation", duration_enabled=True,
        duration=(NumericCondition("structural", "bars", 6, 6), NumericCondition("structural", "minutes", 66, 66)))
    outcome = refine_event(event, duration)
    assert outcome["eligible"]
    spacing = outcome["projection"]["measurements"]["structural"]["movement"]["spacing"]
    assert spacing == {"row_count": 7, "min_delta_ms": 60_000, "max_delta_ms": 3_660_000, "uniform": False}


def test_previous_confirmed_lineage_uses_activation_order_not_start_clock(tmp_path):
    _, catalogue, _, _, _ = enriched_fixture(tmp_path, ENDED)
    events = catalogue.instance("logical")["events"]
    prior, next_event = events[:2]
    before = PatternRefinement(preceding=PrecedingContextFilter(True, previous_direction=prior["direction"], previous_family=prior["family"]))
    assert refine_event(next_event, before)["eligible"]
    assert not refine_event(next_event, PatternRefinement(preceding=PrecedingContextFilter(True, previous_direction="NONE")))["eligible"]
    assert next_event["origin"] == "direct_reversal"


def test_conflicting_prefix_cannot_be_discarded_to_select_older_completed_winner(tmp_path):
    parent, _, axis, original, frame = enriched_fixture(tmp_path, ENDED)
    revised_frame = frame.copy()
    revised_frame.loc[4, "high"] = 201
    revised = saved_analysis(revised_frame)
    inputs = [("old_complete", original, axis[0], axis[-1]), ("new_suffix", revised, axis[8], axis[-1])]
    catalogue = build_catalogue(parent, bundle_for(parent, inputs), axis)
    event = first_event(catalogue)
    assert event["eligible"]
    old = next(w for w in event["witnesses"] if w["artifact_id"] == "old_complete")
    assert old["measurement_projections"]["completed"]["reason"] == ""
    result = refine_event(event, movement())
    assert result["resolution"] == "unresolved_source_revision"
    assert result["reasons"] == ["conflicting_source_prefix"]
    assert result["conflicting_providers"] == ["new_suffix"]
    assert not result["eligible"]


def test_selector_cache_is_detached_and_contains_no_source_reports(tmp_path):
    _, catalogue, _, _, _ = enriched_fixture(tmp_path)
    selected = catalogue.selection_instances()
    assert "measurement_reports" not in selected[0]
    assert selected[0]["parameters"] == catalogue.instance("logical")["parameters"]
    assert selected[0]["events"][0]["witnesses"][0]["metrics"] is True
    selected[0]["events"].clear()
    assert catalogue.selection_instance("logical")["events"]


def test_context_only_maturation_cannot_use_unimported_recognition_row(tmp_path):
    sequence = (("T",100),("P",110),("T",105),("P",115),("T",108),("P",112),("T",104))
    parent, _, axis, _, frame = enriched_fixture(tmp_path, sequence)
    # The DOWN start is row 7; its actual preceding row 6 is a newly confirmed
    # trough in the appended report. Its recognition is row 8, outside that
    # one-row membership requirement and not a DOWN formation pivot.
    frame.loc[6, "trough_fractal_5"] = frame.loc[5, "trough_fractal_5"]
    frame.loc[5, "trough_fractal_5"] = np.nan
    full = saved_analysis(frame)
    old_frame = frame.iloc[:7].copy()
    old_frame.loc[6, "trough_fractal_5"] = np.nan
    prefix = saved_analysis(old_frame)
    inputs = [("old", prefix, axis[0], axis[6]), ("new", full, axis[7], axis[-1])]
    request = PatternRefinement(preceding=PrecedingContextFilter(True, up=True))
    complete = build_catalogue(parent, bundle_for(parent, inputs), axis)
    event = next(e for e in complete.instance("logical")["events"] if e["direction"] == "DOWN")
    assert event["eligible"]
    assert refine_event(event, request)["resolution"] == "resolved"
    incomplete_axis = tuple(t for t in axis if t != axis[8])
    missing = build_catalogue(parent, bundle_for(parent, inputs), incomplete_axis)
    event = next(e for e in missing.instance("logical")["events"] if e["direction"] == "DOWN")
    assert event["eligible"], "This must reach context resolution without changing original event eligibility"
    result = refine_event(event, request)
    assert not result["eligible"]
    assert result["stages"]["preceding_context"]["status"] == "unavailable"


def test_open_alternative_cannot_veto_completed_basis_through_unused_context(tmp_path):
    parent, _, axis, complete, frame = enriched_fixture(tmp_path, ENDED)
    old_frame = frame.iloc[:12].copy()
    old_frame.loc[0, "high"] = 201
    old = saved_analysis(old_frame)
    assert old["utc_classification"]["episodes"][0]["status"] == "open"
    catalogue = build_catalogue(parent, bundle_for(parent,
        [("old_open", old, axis[1], axis[11]), ("current_complete", complete, axis[0], axis[-1])]), axis)
    event = first_event(catalogue)
    old_witness = next(w for w in event["witnesses"] if w["artifact_id"] == "old_open")
    assert old_witness["context_projections"]["membership"]["reason"] == "conflicting_source_prefix"
    result = refine_event(event, movement(preceding=PrecedingContextFilter(True, up=False)))
    assert result["eligible"] and result["resolution"] == "resolved"
    assert [p["artifact_id"] for p in result["providers"]] == ["current_complete"]
