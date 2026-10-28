from dataclasses import replace
from copy import deepcopy
import json
import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.pre_event_cohorts import partition_sample
from leonardo.analysis.pattern_models import PreEventSpec
from leonardo.analysis.trend_start_patterns import run_study
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture
from tests.financial_tools_test.test_utc_classification import CASES
from tests.analysis_test.test_trend_start_enrichment import ENDED, movement


def test_crossing_and_unknown_evidence_are_excluded_from_both_partitions(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, sequences=(ENDED,)*4)
    # First episode starts at 7; its completed observation is not resolved at row15.
    req = replace(req, pre_event=PreEventSpec(history=6, chronological=True, split_ms=axis[15], max_terms=2),
                  refinement=movement(minimum=0), comparison="other_outcomes")
    study = run_study(parent, catalogue, req, axis)
    samples = study._data["samples"]
    assert samples[0]["partition"] == "excluded"
    assert samples[0]["partition_reason"] == "feature_or_evidence_crosses_split"
    assert all(s["partition"] != "discovery" for s in samples)
    assert study.frame("patterns").empty
    item = dict(samples[-1], anchor=20, evidence_start_ms=None, evidence_end_ms=None)
    partition_sample(item, study._data, req, axis[15])
    assert item["partition"] == "excluded" and "unknown" in item["partition_reason"]


def test_later_labels_cannot_select_candidates_rank_or_change_near_cap_truncation(tmp_path):
    sequences = (CASES[1], CASES[2])*4
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, sequences=sequences)
    spec = replace(req.pre_event, chronological=True, split_ms=axis[88])
    request = replace(req, pre_event=spec, min_matches=1)
    original = run_study(parent, catalogue, request, axis)
    assert {s["partition"] for s in original._data["samples"]} == {"discovery", "later"}
    changed_columns = []
    for column in parent.columns:
        frame = column.to_frame()
        frame.loc[frame.ts_ms >= axis[88], "bin_label"] = "P10"
        changed_columns.append(replace(column, _frame=frame))
    changed = replace(parent, columns=tuple(changed_columns))
    for cap in (128*1024*1024, 9000, 24000):
        r = replace(request, pre_event=replace(spec, memory_limit_bytes=cap))
        before = run_study(parent, catalogue, r, axis)
        after = run_study(changed, catalogue, r, axis)
        assert json.loads(before.context)["search"] == json.loads(after.context)["search"]
        a, b = before.frame("patterns"), after.frame("patterns")
        keep = [c for c in a if not c.startswith("later_")]
        pd.testing.assert_frame_equal(a[keep], b[keep])
    assert "retrospective_full_history" in original.context


def test_snapshot_only_background_and_preceding_context_do_not_invent_early_evidence(tmp_path):
    from leonardo.analysis.pattern_models import PatternRefinement, PrecedingContextFilter
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    req = replace(req, comparison="non_start", pre_event=replace(req.pre_event, chronological=True, split_ms=axis[88]))
    study = run_study(parent, catalogue, req, axis)
    assert all(s["partition"] == "excluded" for s in study._data["samples"] if s["ordinary"])
    context = PatternRefinement(preceding=PrecedingContextFilter(True, up=False))
    other = run_study(parent, catalogue, replace(req, comparison="other_families", refinement=context), axis)
    assert all(s["partition"] == "excluded" for s in other._data["samples"])


def test_lead_window_and_gap_do_not_impute_or_cross_segments(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    request = replace(req, pre_event=replace(req.pre_event, lead=3, history=2))
    study = run_study(parent, catalogue, request, axis)
    assert all(t["offset"] in (-4, -3) for row in study.frame("patterns").conditions for t in json.loads(row))
    event = study.frame("events").iloc[0]
    window = study.event_window(event.event_id)
    assert set(window[window.use == "mined history"].offset) == {-4, -3}
    long = run_study(parent, catalogue, replace(req, pre_event=replace(req.pre_event, lead=100, history=100)), axis)
    assert long.event_window(event.event_id).offset.min() == -199
    # Imported UTC segment separators already make the long required paths unavailable.
    assert long.frame("patterns").empty


@pytest.mark.parametrize("copied_start", (0, 3))
def test_ordinary_partition_requires_an_eligible_covering_provider(tmp_path, copied_start):
    from leonardo.analysis.service import AnalysisService
    from leonardo.analysis.trend_start_patterns import build_catalogue
    from leonardo.financial_tools import UtcClassificationContext, calculate_financial_tool
    from tests.analysis_test.test_analysis_service import make_database, request
    from tests.analysis_test.test_trend_start_catalogue import study_request
    from tests.analysis_test.test_trend_start_enrichment import bundle_for, saved_analysis
    from tests.financial_tools_test.test_utc_classification import _frame, _parameters

    # Keep a genuinely confirmed target and an older, unconfirmed tail in two
    # calculated reports. Only the later revision can supply ordinary controls.
    first = _frame(CASES[1], tail=6)
    first.loc[len(first)-1, "close"] = np.nan
    prefix = first.iloc[[0]*6].copy()
    old_frame = pd.concat((prefix, first, _frame(CASES[2], tail=0)), ignore_index=True)
    new_frame = pd.concat((old_frame, old_frame.iloc[[0]*16]), ignore_index=True)
    for name in ("peak_fractal_5", "trough_fractal_5"):
        new_frame.loc[len(old_frame)-1:, name] = np.nan
    values = {name: np.resize(np.arange(1., 11.), len(new_frame)) for name in ("delta", "slope")}
    store, manifest, saved = make_database(tmp_path, values)
    new_frame["ts_ms"] = saved.ts_ms
    old_frame["ts_ms"] = saved.ts_ms.iloc[:len(old_frame)].to_numpy()
    closes = tuple(int(t)+60000 for t in old_frame.ts_ms)
    old = calculate_financial_tool("UTC", old_frame, _parameters(), utc_context=UtcClassificationContext(
        stream_id="refinement", bar_closed_at_ms=closes,
        swing_available_at_ms=tuple(t+120000 for t in closes[:-1])+(None,))).analysis
    new = saved_analysis(new_frame)
    old_confirmations = [e["confirmed_at_ms"] for e in old["utc_classification"]["episodes"]]
    new_confirmations = [e["confirmed_at_ms"] for e in new["utc_classification"]["episodes"]]
    assert old["utc_classification"]["availability_status"] == "known"
    assert old_confirmations == [new_confirmations[0], None] and len(new_confirmations) == 1
    parent = AnalysisService(store).run(request(manifest, *values, minimum=2))
    axis = tuple(int(t) for t in saved.ts_ms)
    bundle = bundle_for(parent, [("old", old, axis[0], axis[len(old_frame)-1]),
                                 ("new", new, axis[copied_start], axis[-1])])
    catalogue = build_catalogue(parent, bundle, axis)
    instance = catalogue.instance("logical")
    target = instance["events"][0]
    assert target["eligible"] and target["coverage_basis"] == "verified_confirmation"
    assert {w["artifact_id"] for w in target["witnesses"]} == {"old", "new"}
    req = study_request(parent, catalogue, family=target["family"], comparison="non_start",
        min_target=1, min_comparison=1, min_matches=1,
        pre_event=PreEventSpec(history=2, chronological=True, split_ms=axis[32], max_terms=2))
    study = run_study(parent, catalogue, req, axis)
    sample = next(s for s in study._data["samples"] if s["ordinary"] and s["anchor"] == 3)
    assert sample["partition"] == "excluded"
    if copied_start:
        assert sample["evidence_start_ms"] is sample["evidence_end_ms"] is None
        assert sample["partition_reason"] == "unknown_feature_or_evidence_boundary"
    else:
        later = next(e for e in instance["observation_evidence"] if e["artifact_id"] == "new")
        assert sample["evidence_end_ms"] == later["observed_at_ms"] > axis[32]
        assert sample["partition_reason"] == "feature_or_evidence_crosses_split"
    assert {e["artifact_id"]: e["control_eligible"] for e in instance["observation_evidence"]} == {
        "old": False, "new": True}
    patterns = study.frame("patterns")
    assert not patterns.empty
    for prefix in ("comparison_", "later_comparison_"):
        for count in ("total", "assessable", "matched", "exact_matched", "ready_assessable", "ready_matched"):
            assert patterns[prefix+count].eq(0).all()
    assert not patterns.rank_eligible.any()
    ledger = study.pattern_matches(patterns.iloc[0].pattern_id, "comparison")
    assert not ledger.empty and ledger.partition.eq("excluded").all()
    assert not ledger.ranking_support.any()


def _reviewed_append_fixture(tmp_path, *, mirror=False, fault=None):
    from leonardo.analysis.trend_start_patterns import build_catalogue
    from leonardo.financial_tools import UtcClassificationContext, calculate_financial_tool
    from tests.analysis_test.test_trend_start_enrichment import bundle_for, saved_analysis
    from tests.financial_tools_test.test_utc_classification import _frame, _parameters

    parent, _, axis, request, *_ = planted_fixture(tmp_path, sequences=(ENDED,)*4, mirror=mirror)
    sequence = tuple(("P" if k == "T" else "T", 220-v) for k, v in ENDED) if mirror else ENDED
    blocks = []
    for _ in range(4):
        block = _frame(sequence, tail=8)
        block = pd.concat((block.iloc[[0]*6].copy().reset_index(drop=True), block), ignore_index=True)
        block.loc[len(block)-1, "close"] = np.nan
        blocks.append(block)
    frame = pd.concat(blocks, ignore_index=True)
    frame = pd.concat((frame, frame.iloc[[0]*(100+(-len(frame)) % 10)]), ignore_index=True)
    assert len(frame) == len(axis)
    frame["ts_ms"] = axis
    old_frame = frame.iloc[:18].copy()
    if fault == "conflicting_prefix":
        old_frame.loc[10, "high"] += 1
    full, old = saved_analysis(frame), saved_analysis(old_frame)
    if fault in ("unknown_formation", "unknown_outcome"):
        # Recalculate coherent reports with genuinely unknown swing clocks.
        def calculate(source):
            closes = tuple(int(t)+60_000 for t in source.ts_ms)
            unknown = 13 if fault == "unknown_formation" else 19
            available = tuple(None if i == unknown else t+120_000 for i, t in enumerate(closes))
            return calculate_financial_tool("UTC", source, _parameters(), utc_context=UtcClassificationContext(
                stream_id="refinement", bar_closed_at_ms=closes, swing_available_at_ms=available)).analysis
        full, old = calculate(frame), calculate(old_frame)
    inputs = [("old", old, axis[0], axis[17]), ("new", full, axis[18], axis[-1])]
    if fault == "incomplete_prefix":
        inputs = [("old", old, axis[0], axis[9]), ("old", old, axis[11], axis[17]), inputs[1]]
    if fault in ("missing_formation_row", "missing_outcome_row"):
        missing = axis[15 if fault == "missing_formation_row" else 21]
        axis = tuple(t for t in axis if t != missing)
        columns = []
        for column in parent.columns:
            labels = column.to_frame()
            columns.append(replace(column, _frame=labels[labels.ts_ms != missing].reset_index(drop=True)))
        parent = replace(parent, columns=tuple(columns))
    bundles = (bundle_for(parent, [("full", full, axis[0], axis[-1])]), bundle_for(parent, inputs))
    catalogues = tuple(build_catalogue(parent, bundle, axis) for bundle in bundles)
    request = replace(request, refinement=movement(), min_matches=1,
        pre_event=PreEventSpec(history=6, lead=1, max_terms=2, chronological=True,
                              split_ms=1700001740000))
    return parent, catalogues, axis, request


def _preserved_chronology_study(parent, catalogue, request, axis):
    before_catalogue = catalogue.to_dict()
    profiles = [deepcopy(column.profile.to_dict()) for column in parent.columns]
    frames = [column.to_frame() for column in parent.columns]
    study = run_study(parent, catalogue, replace(request, run_key=catalogue.run_key), axis)
    assert catalogue.to_dict() == before_catalogue
    assert [column.profile.to_dict() for column in parent.columns] == profiles
    for column, before in zip(parent.columns, frames):
        pd.testing.assert_frame_equal(column.to_frame(), before)
    return study


@pytest.mark.parametrize("mirror", (False, True))
def test_reviewed_append_completed_chronology_matches_complete_provider(tmp_path, mirror):
    parent, catalogues, axis, request = _reviewed_append_fixture(tmp_path, mirror=mirror)
    studies = [_preserved_chronology_study(parent, c, request, axis) for c in catalogues]
    projections = []
    for study in studies:
        sample = next(s for s in study._data["samples"] if s["anchor"] == 7 and s["cohort"] == "target")
        refined = study._data["events"][sample["event_id"]]["refinement"]
        assert refined["eligible"] and refined["resolution"] == "resolved"
        projections.append(refined["projection"])
        assert (sample["feature_start_ms"], sample["cutoff_ms"]) == (1700000060000, 1700000360000)
        assert (sample["evidence_start_ms"], sample["evidence_end_ms"]) == (1700000420000, 1700001320000)
        assert request.pre_event.split_ms == 1700001740000 and sample["partition"] == "discovery"
        patterns = study.frame("patterns")
        assert patterns.kind.eq("combination").sum() == 30 and len(patterns) == 42
    assert projections[0] == projections[1]
    pd.testing.assert_frame_equal(studies[0].frame("patterns"), studies[1].frame("patterns"))


@pytest.mark.parametrize("mirror", (False, True))
def test_reviewed_append_measured_comparison_keeps_chronology(tmp_path, mirror):
    parent, catalogues, axis, request = _reviewed_append_fixture(tmp_path, mirror=mirror)
    request = replace(request, comparison="other_outcomes", refinement=movement(minimum=100))
    samples = []
    for catalogue in catalogues:
        study = _preserved_chronology_study(parent, catalogue, request, axis)
        sample = next(s for s in study._data["samples"] if s["anchor"] == 7)
        refined = study._data["events"][sample["event_id"]]["refinement"]
        assert not refined["eligible"] and refined["resolution"] == "resolved"
        assert refined["stages"]["movement"]["status"] == "mismatch"
        assert sample["cohort"] == "comparison" and sample["partition"] == "discovery"
        assert (sample["evidence_start_ms"], sample["evidence_end_ms"]) == (1700000420000, 1700001320000)
        samples.append(sample)
    assert samples[0] == samples[1]


@pytest.mark.parametrize("mirror", (False, True))
def test_reviewed_append_crossing_cannot_supply_candidates_or_ranked_support(tmp_path, mirror):
    parent, catalogues, axis, request = _reviewed_append_fixture(tmp_path, mirror=mirror)
    # Isolate the first genuine event; its outcome becomes available after this split.
    request = replace(request, start_ms=axis[7], end_ms=axis[29],
                      pre_event=replace(request.pre_event, split_ms=axis[18]))
    for catalogue in catalogues:
        study = _preserved_chronology_study(parent, catalogue, request, axis)
        assert len(study._data["samples"]) == 1
        sample = study._data["samples"][0]
        assert sample["partition"] == "excluded"
        assert sample["partition_reason"] == "feature_or_evidence_crosses_split"
        assert sum(s["partition"] == "discovery" for s in study._data["samples"]) == 0
        assert sum(s["partition"] == "later" for s in study._data["samples"]) == 0
        assert study.frame("patterns").empty
        assert not any(study._data["populations"].values())
        assert json.loads(study.context)["search"]["examined"] == 0


@pytest.mark.parametrize("fault", ("missing_formation_row", "missing_outcome_row", "unknown_formation",
                                 "unknown_outcome", "incomplete_prefix", "conflicting_prefix"))
def test_reviewed_append_bad_source_evidence_cannot_enter_ranked_support(tmp_path, fault):
    parent, catalogues, axis, request = _reviewed_append_fixture(tmp_path, fault=fault)
    request = replace(request, start_ms=1700000420000, end_ms=request.pre_event.split_ms)
    study = _preserved_chronology_study(parent, catalogues[1], request, axis)
    event = next(e for e in study._data["events"].values() if e["anchor_ts_ms"] == 1700000420000)
    if fault == "conflicting_prefix":
        assert event["refinement"]["resolution"] == "unresolved_source_revision"
    elif fault == "incomplete_prefix":
        assert "outside_classification_coverage" in event["refinement"]["reasons"]
    elif fault == "missing_outcome_row":
        assert not event["refinement"]["eligible"]
    assert all(s["partition"] == "excluded" for s in study._data["samples"])
    assert study.frame("patterns").empty
    assert not any(study._data["populations"].values())
    assert json.loads(study.context)["search"]["examined"] == 0


@pytest.mark.parametrize("basis", ("disabled", "formation", "observed"))
def test_reviewed_append_exception_does_not_extend_other_refinement_paths(tmp_path, basis):
    from leonardo.analysis.pattern_models import PatternRefinement
    from leonardo.analysis.pre_event_cohorts import _event_interval
    from leonardo.analysis.trend_start_patterns import refine_event
    parent, catalogues, axis, request = _reviewed_append_fixture(tmp_path)
    request = replace(request, refinement=PatternRefinement() if basis == "disabled" else movement(basis))
    instance = catalogues[1].instance("logical")
    event = next(e for e in instance["events"] if e["anchor_ts_ms"] == axis[7])
    event["refinement"] = refine_event(event, request.refinement)
    assert any(w["exclusion"] == "recognition_outside_provider_coverage" for w in event["witnesses"])
    without_excluded = deepcopy(event)
    without_excluded["witnesses"] = [w for w in event["witnesses"] if not w["exclusion"]]
    positions = {t: i for i, t in enumerate(axis)}
    assert _event_interval(event, request, instance, positions) == _event_interval(
        without_excluded, request, instance, positions)


@pytest.mark.parametrize("reason", ("pivot_outside_database", "pivot_outside_classification_coverage",
                                    "confirmation_beyond_covered_history"))
def test_completed_chronology_does_not_bypass_other_exclusion_guards(tmp_path, reason):
    from leonardo.analysis.pre_event_cohorts import _event_interval
    from leonardo.analysis.trend_start_patterns import refine_event
    parent, catalogues, axis, request = _reviewed_append_fixture(tmp_path)
    instance = catalogues[1].instance("logical")
    event = next(e for e in instance["events"] if e["anchor_ts_ms"] == axis[7])
    event["refinement"] = refine_event(event, request.refinement)
    positions = {t: i for i, t in enumerate(axis)}
    assert _event_interval(event, request, instance, positions) == (1700000420000, 1700001320000)
    # Exercise the internal guard in isolation, not a fabricated saved report.
    carrier = next(w for w in event["witnesses"] if w["artifact_id"] == "new")
    carrier["exclusion"] = reason
    assert _event_interval(event, request, instance, positions) == (None, None)
