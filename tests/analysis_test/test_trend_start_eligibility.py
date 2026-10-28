"""Regression contracts for timing support and condition-specific controls."""
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.service import AnalysisService
from leonardo.analysis.trend_start_patterns import analysis_key, build_catalogue, run_study
from leonardo.financial_tools import UtcClassificationContext, calculate_financial_tool, get_utc_classification
from tests.analysis_test.test_analysis_service import request as binning_request
from tests.analysis_test.test_trend_start_catalogue import fixture, make_bundle, study_request, CASES
from tests.financial_tools_test.test_utc_classification import _frame, _parameters


def test_refined_unknown_timing_remains_descriptive_and_does_not_gain_ranking(tmp_path):
    from tests.analysis_test.test_trend_start_enrichment import enriched_fixture, first_event, movement
    parent, catalogue, axis, _, _ = enriched_fixture(tmp_path, known=False)
    event = first_event(catalogue)
    req = study_request(parent, catalogue, family=event["family"], refinement=movement("formation"),
        before=0, after=0, sequence_lengths=(1,), min_target=1, min_comparison=1, min_matches=1)
    study = run_study(parent, catalogue, req, axis)
    assert study.frame("events").iloc[0].refinement_eligible
    assert set(study.frame("events").coverage_basis) == {"structural_coverage_only"}
    assert not study.frame("patterns").rank_eligible.any()
    for row in study.frame("patterns").itertuples():
        assert row.ready_matched == 0
        assert not study.pattern_matches(row.pattern_id).verified_timing.any()


def _sequences(mirror=False, repeats=1):
    sequences = (CASES[1], CASES[1], CASES[2], CASES[2]) * repeats
    if mirror:
        sequences = tuple(tuple(("P" if k == "T" else "T", 220-v) for k, v in s) for s in sequences)
    return sequences


def _counted(tmp_path, *, mirror=False, known=True, repeats=1):
    delta, slope = np.resize(np.arange(-9., 10.), 56), np.resize(np.arange(1., 10.), 56)
    for anchor in (1, 15, 29):
        delta[anchor], delta[anchor-1], slope[anchor] = -9, -5, 2
    delta[43], delta[42], slope[43] = 9, -3, 8
    parent, catalog, ts, report, store, manifest = fixture(tmp_path, _sequences(mirror, repeats), known=known,
        values={"delta": np.tile(delta, repeats), "slope": np.tile(slope, repeats)})
    req = study_request(parent, catalog, kind="P" if mirror else "T",
        family="DOWN/PTPT/3,1,2,0" if mirror else "UP/TPTP/0,2,1,3",
        before=1, after=0, sequence_lengths=(2,))
    return parent, catalog, ts, req, store, manifest


def _assert_matches(study, row):
    for cohort, count, ready in (("target", row.matched, row.ready_matched),
                                ("comparison", row.comparison_matched, row.comparison_ready_matched)):
        matches = study.pattern_matches(row.pattern_id, cohort)
        assert len(matches) == count
        assert sum(matches.ranking_support) == ready
        assert all(matches.ranking_support == (matches.ready_reference & matches.verified_timing))


@pytest.mark.parametrize("mirror", (False, True))
@pytest.mark.parametrize("known", (False, True))
def test_default_thresholds_require_verified_timing_without_losing_descriptions(tmp_path, mirror, known):
    parent, catalog, ts, req, *_ = _counted(tmp_path, mirror=mirror, known=known, repeats=10)
    study = run_study(parent, catalog, req, ts)
    patterns, events = study.frame("patterns"), study.frame("events")
    assert (req.min_target, req.min_comparison, req.min_matches) == (20, 20, 5)
    assert len(events) == 20
    for kind in ("label", "sequence", "pair"):
        row = patterns[(patterns.kind == kind) & (patterns.matched == 20) & (patterns.comparison_matched == 10)].iloc[0]
        assert (row.assessable, row.comparison_assessable, row.frequency_ratio) == (20, 20, 2)
        assert (row.ready_matched, row.ready_assessable, row.comparison_ready_matched,
                row.comparison_ready_assessable) == ((20, 20, 10, 20) if known else (0, 0, 0, 0))
        assert (row.timing_withheld, row.comparison_timing_withheld) == ((0, 0) if known else (20, 20))
        assert row.rank_eligible == known
        assert row.rank_ratio == 2 if known else pd.isna(row.rank_ratio)
        if not known:
            assert row.rank_reason == "unverified_confirmation_timing"
        _assert_matches(study, row)
    if not known:
        assert not patterns.rank_eligible.any() and events.confirmed_at_ms.isna().all()
        assert set(events.coverage_basis) == {"structural_coverage_only"}
    event = events.iloc[0]
    assert study.evidence(event.event_id)["witnesses"]
    assert study.event_window(event.event_id).query("column == 'delta' and offset == 0").iloc[0].raw_value == -9
    assert study.frame("frequencies").query("column == 'delta' and offset == 0").matched.sum() == 20
    diagnostics = study.frame("diagnostics").set_index("field").value
    assert diagnostics["Target starts withheld from ranking for unverified timing"] == (0 if known else 20)
    assert diagnostics["Comparison starts withheld from ranking for unverified timing"] == (0 if known else 20)


@pytest.mark.parametrize("mirror", (False, True))
@pytest.mark.parametrize("unknown_target,unknown_comparison", ((True, False), (False, True), (True, True)))
def test_mixed_populations_rank_only_verified_subset(tmp_path, mirror, unknown_target, unknown_comparison):
    parent, _, ts, req, *_ = _counted(tmp_path, mirror=mirror, repeats=2)
    blocks = []
    for sequence in _sequences(mirror, 2):
        block = _frame(sequence, tail=6)
        block.loc[len(block)-1, "close"] = np.nan
        blocks.append(block)
    frame = pd.concat(blocks, ignore_index=True)
    frame["ts_ms"] = ts
    unknown_blocks = ({1, 5} if unknown_target else set()) | ({2} if unknown_comparison else set())
    closes = tuple(t+60_000 for t in ts)
    available = tuple(None if i//14 in unknown_blocks or i+2 >= len(ts) else closes[i+2] for i in range(len(ts)))
    context = UtcClassificationContext(stream_id="test/utc", bar_closed_at_ms=closes, swing_available_at_ms=available)
    report = get_utc_classification(calculate_financial_tool("UTC", frame, _parameters(), utc_context=context)).to_dict()
    catalog = build_catalogue(parent, make_bundle(parent, report), ts)
    study = run_study(parent, catalog, replace(req, min_target=1, min_comparison=1, min_matches=1), ts)
    patterns = study.frame("patterns")
    for kind in ("label", "sequence", "pair"):
        row = patterns[(patterns.kind == kind) & (patterns.matched == 4) & (patterns.comparison_matched == 2)].iloc[0]
        assert (row.assessable, row.comparison_assessable, row.frequency_ratio) == (4, 4, 2)
        assert row.ready_assessable == row.ready_matched == (2 if unknown_target else 4)
        assert row.comparison_ready_assessable == (3 if unknown_comparison else 4)
        assert row.comparison_ready_matched == (1 if unknown_comparison else 2)
        assert row.rank_ratio == (3 if unknown_comparison else 2) and row.rank_eligible
        assert row.timing_withheld == (2 if unknown_target else 0)
        assert row.comparison_timing_withheld == (1 if unknown_comparison else 0)
        _assert_matches(study, row)
    stricter = run_study(parent, catalog, replace(req, min_target=4, min_comparison=4, min_matches=1), ts)
    assert not stricter.frame("patterns").rank_eligible.any()


def _edge(tmp_path, *, mirror=False, columns=None):
    sequence = _sequences(mirror)[0]
    raw = np.arange(1., 15.)
    raw[12:14] = 2
    parent, catalog, ts, *_ = fixture(tmp_path, (sequence,), values=columns or {"delta": raw})
    req = study_request(parent, catalog, kind="P" if mirror else "T",
        family="DOWN/PTPT/3,1,2,0" if mirror else "UP/TPTP/0,2,1,3", before=0, after=2,
        sequence_lengths=(), comparison="non_start", min_target=1, min_comparison=1, min_matches=1)
    return parent, catalog, ts, req


@pytest.mark.parametrize("mirror", (False, True))
def test_history_edge_controls_use_required_terms_and_matching_counts(tmp_path, mirror):
    parent, catalog, ts, req = _edge(tmp_path, mirror=mirror)
    study = run_study(parent, catalog, req, ts)
    patterns = study.frame("patterns")
    row = patterns[patterns.condition.str.startswith("delta[+0]")].iloc[0]
    assert (row.matched, row.assessable, row.comparison_matched, row.comparison_assessable) == (1, 1, 2, 10)
    assert (row.comparison_total, row.comparison_excluded, row.frequency_ratio) == (10, 0, 5)
    _assert_matches(study, row)
    matches = study.pattern_matches(row.pattern_id, "comparison")
    assert set(matches.anchor_ts_ms) == {ts[12], ts[13]}
    assert "outside_history" in set(study.event_window(matches.iloc[-1].event_id).status)
    later = patterns[patterns.condition.str.startswith("delta[+2]")].iloc[0]
    assert (later.comparison_total, later.comparison_assessable, later.comparison_excluded) == (10, 8, 2)
    _assert_matches(study, later)
    inclusive = run_study(parent, catalog, replace(req, start_ms=ts[1], end_ms=ts[12]), ts)
    row = inclusive.frame("patterns").query("kind == 'label'")
    row = row[row.condition.str.startswith("delta[+0]")].iloc[0]
    assert (row.comparison_total, row.comparison_matched, row.frequency_ratio) == (9, 1, 9)
    _assert_matches(inclusive, row)


@pytest.mark.parametrize("boundary", ("classification_hole", "control_hole", "segment", "time_gap"))
def test_unused_boundary_keeps_anchor_but_required_path_is_excluded(tmp_path, boundary):
    parent, catalog, ts, req = _edge(tmp_path)
    payload = catalog.to_dict()
    instance = payload["instances"][0]
    if boundary in ("classification_hole", "control_hole"):
        field = "coverage" if boundary == "classification_hole" else "control_coverage"
        instance[field] = [[ts[0], ts[9]], [ts[11], ts[-1]]]
    elif boundary == "segment":
        instance["segment_starts"].append(ts[10])
    else:
        # Detached observation-axis fixture: the formation is before the gap.
        ts = tuple(t + (60_000 if i >= 10 else 0) for i, t in enumerate(ts))
        frames = []
        for column in parent.columns:
            frame = column.to_frame()
            frame["ts_ms"] = ts
            frames.append(replace(column, _frame=frame))
        parent = replace(parent, columns=tuple(frames))
        instance["coverage"] = instance["control_coverage"] = [[ts[0], ts[-1]]]
        req = replace(req, end_ms=ts[-1])
    catalog = replace(catalog, _json=json.dumps(payload))
    study = run_study(parent, catalog, req, ts)
    patterns = study.frame("patterns")
    zero = patterns[patterns.condition.str.startswith("delta[+0]")].iloc[0]
    later = patterns[patterns.condition.str.startswith("delta[+2]")].iloc[0]
    hole = boundary.endswith("hole")
    assert (zero.comparison_total, zero.comparison_assessable, zero.comparison_excluded) == ((9, 9, 0) if hole else (10, 10, 0))
    assert later.comparison_total == (9 if hole else 10)
    assert later.comparison_assessable == (5 if hole else 6)
    assert later.comparison_excluded == 4
    for row in patterns.itertuples():
        _assert_matches(study, row)


def test_sequences_pairs_and_missing_required_labels_keep_separate_denominators(tmp_path):
    delta = np.arange(1., 15.)
    delta[12], delta[13] = 1, 2
    slope = np.arange(1., 15.)
    slope[12], slope[13] = np.nan, 2
    parent, catalog, ts, req = _edge(tmp_path, columns={"delta": delta, "slope": slope})
    study = run_study(parent, catalog, replace(req, before=1, sequence_lengths=(2,)), ts)
    patterns = study.frame("patterns")
    # Requested windows exclude 0..4. Controls 5..13 remain, including the tail.
    for row in patterns.itertuples():
        _assert_matches(study, row)
    seq = patterns.query("kind == 'sequence'")
    delta_seq = seq[seq.condition.str.startswith("delta")].iloc[0]
    slope_seq = seq[seq.condition.str.startswith("slope")].iloc[0]
    pair = patterns.query("kind == 'pair'").iloc[0]
    assert (delta_seq.comparison_matched, delta_seq.comparison_assessable, delta_seq.comparison_total) == (1, 9, 9)
    assert (slope_seq.comparison_matched, slope_seq.comparison_assessable, slope_seq.comparison_excluded) == (0, 7, 2)
    assert (pair.comparison_matched, pair.comparison_assessable, pair.comparison_excluded) == (1, 8, 1)


@pytest.mark.parametrize("known", (False, True))
def test_zero_and_limited_reference_support_still_require_verified_timing(tmp_path, known):
    parent, catalog, ts, req, store, manifest = _counted(tmp_path, known=known)
    limited = AnalysisService(store).run(binning_request(manifest, "delta", "slope", minimum=1000))
    # The unchanged UTC evidence is valid for this independently keyed binning run.
    catalog = replace(catalog, run_key=analysis_key(limited))
    study = run_study(limited, catalog, replace(req, run_key=catalog.run_key, min_target=1, min_comparison=1, min_matches=1), ts)
    assert study.frame("patterns").matched.max() == 2
    assert study.frame("patterns").ready_assessable.sum() == 0
    assert not study.frame("patterns").rank_eligible.any()
    parent, catalog, ts, *_ = fixture(tmp_path/"zero", _sequences(), known=known,
        values={"zero": np.zeros(56), "constant": np.ones(56)})
    req = study_request(parent, catalog, family="UP/TPTP/0,2,1,3", before=0, after=0,
        sequence_lengths=(), min_target=1, min_comparison=1, min_matches=1)
    study = run_study(parent, catalog, req, ts)
    rows = study.frame("patterns")
    assert len(rows) == 1 and rows.iloc[0].condition == "zero[+0] = Zero"
    row = rows.iloc[0]
    assert (row.matched, row.comparison_matched, row.frequency_ratio) == (2, 2, 1)
    assert row.rank_eligible == known
    _assert_matches(study, row)


@pytest.mark.parametrize("mirror", (False, True))
def test_full_windows_still_exclude_both_trend_directions(tmp_path, mirror):
    up, down = CASES[1], _sequences(True)[0]
    parent, catalog, ts, *_ = fixture(tmp_path, (up, down))
    req = study_request(parent, catalog, kind="P" if mirror else "T",
        family="DOWN/PTPT/3,1,2,0" if mirror else "UP/TPTP/0,2,1,3", before=1, after=2,
        sequence_lengths=(2,), comparison="non_start", min_target=1, min_comparison=1, min_matches=1)
    study = run_study(parent, catalog, req, ts)
    # Starts at 1 and 15 exclude [0,4] and [12,18], regardless of target direction.
    expected = set(range(5, 12)) | set(range(19, 28))
    assert set(study._data["controls"]) == expected
    for row in study.frame("patterns").itertuples():
        assert row.comparison_total == 16
        _assert_matches(study, row)
        matches = study.pattern_matches(row.pattern_id, "comparison")
        assert set(matches.anchor_ts_ms) <= {ts[i] for i in expected}
