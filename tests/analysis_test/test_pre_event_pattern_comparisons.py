from dataclasses import replace
import json
import pytest

from leonardo.analysis.pattern_models import NumericCondition, PatternRefinement, PrecedingContextFilter, PullbackFilter
from leonardo.analysis.trend_start_patterns import build_catalogue, run_study
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture
from tests.analysis_test.test_trend_start_enrichment import ENDED, STANDARD, movement


def test_other_families_receive_identical_outcome_filters_and_aliases_do_not_vote(tmp_path):
    parent, catalogue, axis, req, _, _, bundle = planted_fixture(tmp_path)
    ref = PatternRefinement(basis="formation", pullbacks=PullbackFilter(True, "all_observed",
        (NumericCondition("depth", "points", maximum=7, statistic="maximum"),)))
    result = run_study(parent, catalogue, replace(req, refinement=ref), axis)
    assignments = result.frame("cohort_assignments")
    assert assignments.cohort.value_counts().to_dict() == {"target": 4, "excluded": 4}
    assert result.frame("patterns").comparison_total.eq(0).all()
    payload = bundle.to_dict()
    payload["associations"].append({**payload["associations"][0], "artifact_id": "two", "column_name": "alias"})
    aliases = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), axis)
    result2 = run_study(parent, aliases, replace(req, refinement=ref), axis)
    assert result2.frame("patterns").matched.tolist() == result.frame("patterns").matched.tolist()


def test_same_family_outcome_complement_excludes_open_and_unknown_outcomes(tmp_path):
    big = tuple((k, 100+2*(v-100)) for k, v in ENDED)
    zero = tuple((k, v-100) for k, v in ENDED)
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, sequences=(big, ENDED, STANDARD, zero))
    ref = PatternRefinement(movement_enabled=True, movement=(NumericCondition("directional_move", "points", 30),
                                                              NumericCondition("directional_move", "pct", 0)))
    study = run_study(parent, catalogue, replace(req, comparison="other_outcomes", refinement=ref), axis)
    selected = study.frame("cohort_assignments").query("family == @req.family")
    assert selected.cohort.tolist() == ["target", "comparison", "excluded", "excluded"]
    assert selected.iloc[1].failed_conditions == "directional_move_outside_bounds"
    assert selected.iloc[-1].reason == "unavailable_outcome_or_context"
    for bad in (PatternRefinement(), movement("formation", 30)):
        with pytest.raises(ValueError, match="completed-trend"):
            replace(req, comparison="other_outcomes", refinement=bad)


def test_ordinary_controls_keep_nearby_rows_but_never_recorded_starts(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    req = replace(req, comparison="non_start", refinement=movement("formation", 0))
    study = run_study(parent, catalogue, req, axis)
    starts = {e["anchor_ts_ms"] for e in catalogue.instance("logical")["events"]}
    expected = set(axis)-starts
    assert {axis[i] for i in study._data["controls"]} == expected
    assert axis[6] in expected and axis[8] in expected
    row = study.frame("patterns").iloc[0]
    ledger = study.pattern_matches(row.pattern_id, "comparison")
    assert set(ledger.anchor_ts_ms) == expected
    evidence = study.evidence(ledger.iloc[0].event_id)
    assert evidence["role"] == "ordinary_timestamp" and "facts" not in evidence
    assert study.frame("patterns").comparison_total.eq(len(expected)).all()
    with pytest.raises(ValueError, match="All origins"):
        replace(req, origin="initial_candidate")
    with pytest.raises(ValueError, match="preceding-context"):
        replace(req, refinement=PatternRefinement(preceding=PrecedingContextFilter(True, down=True)))


def test_unknown_clocks_withhold_ordinary_controls_and_refinement_reruns_preserve_bins(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, known=False)
    before = [c.profile.to_dict() for c in parent.columns]
    result = run_study(parent, catalogue, replace(req, comparison="non_start"), axis)
    assert not result._data["controls"]
    assert not result.frame("patterns").rank_eligible.any()
    refined = run_study(parent, catalogue, replace(req, refinement=movement("formation", 1000)), axis)
    assert refined.frame("patterns").empty
    assert [c.profile.to_dict() for c in parent.columns] == before
