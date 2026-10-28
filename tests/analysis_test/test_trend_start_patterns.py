from dataclasses import replace
import json
import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.trend_start_patterns import run_study
from tests.analysis_test.test_trend_start_catalogue import fixture, study_request, CASES


def test_refinement_keeps_complete_selection_while_matching_only_included_events(tmp_path):
    from dataclasses import replace
    from tests.analysis_test.test_trend_start_enrichment import enriched_fixture, first_event, movement, ENDED
    parent, catalogue, axis, _, _ = enriched_fixture(tmp_path, ENDED)
    event = first_event(catalogue)
    req = study_request(parent, catalogue, family=event["family"], before=0, after=0,
        sequence_lengths=(1,), refinement=movement(minimum=1000))
    rejected = run_study(parent, catalogue, req, axis)
    assert rejected.frame("events").event_id.tolist() == [event["event_id"]]
    assert rejected.frame("patterns").empty
    assert rejected.frame("families").iloc[0].original_starts == 1
    included = run_study(parent, catalogue, replace(req, refinement=movement()), axis)
    assert included.frame("events").event_id.tolist() == rejected.frame("events").event_id.tolist()
    for row in included.frame("patterns").itertuples():
        assert included.pattern_matches(row.pattern_id).event_id.tolist() == [event["event_id"]]
        assert row.matched == 1


def counted_fixture(tmp_path, *, mirror=False, missing=False):
    sequences = (CASES[1], CASES[1], CASES[2], CASES[2])
    if mirror:
        sequences = tuple(tuple(("T" if k == "P" else "P", 220-v) for k, v in seq) for seq in sequences)
    delta, slope = np.resize(np.arange(-9., 10.), 56), np.resize(np.arange(1., 10.), 56)
    for anchor in (1, 15, 29):
        delta[anchor], delta[anchor-1], slope[anchor] = -9, -5, 2
    delta[43], delta[42], slope[43] = 9, -3, 8
    if missing:
        slope[15] = np.nan
    parent, catalog, ts, *_ = fixture(tmp_path, sequences, values={"delta": delta, "slope": slope})
    kind = "P" if mirror else "T"
    direction = "DOWN" if mirror else "UP"
    family = direction + ("/PTPT/3,1,2,0" if mirror else "/TPTP/0,2,1,3")
    req = study_request(parent, catalog, kind=kind, family=family, before=1, after=0,
                        sequence_lengths=(2,), min_target=1, min_comparison=1, min_matches=1)
    return parent, catalog, ts, req


@pytest.mark.parametrize("mirror", (False, True))
def test_hand_counted_single_sequence_and_pair_ratios_and_evidence(tmp_path, mirror):
    parent, catalog, ts, req = counted_fixture(tmp_path, mirror=mirror)
    result = run_study(parent, catalog, req, ts)
    patterns = result.frame("patterns")
    for kind in ("label", "sequence", "pair"):
        selected = patterns[(patterns.kind == kind) & (patterns.matched == 2) & (patterns.comparison_matched == 1)]
        assert not selected.empty
        row = selected.iloc[0]
        assert row.assessable == row.comparison_assessable == 2
        assert row.frequency == 1 and row.comparison_frequency == .5
        assert row.frequency_ratio == 2 and row.difference_pp == 50 and row.rank_eligible
        matches = result.pattern_matches(row.pattern_id)
        assert len(matches) == 2
        assert len(result.pattern_matches(row.pattern_id, "comparison")) == 1
        assert result.event_window(matches.iloc[0].event_id).query("offset == 0 and column == 'delta'").iloc[0].raw_value == -9
    assert all(c.to_frame().iloc[1].raw_value == -9 for c in parent.columns if c.request.source == "delta")


def test_missing_pair_denominator_does_not_remove_independent_column(tmp_path):
    parent, catalog, ts, req = counted_fixture(tmp_path, missing=True)
    patterns = run_study(parent, catalog, req, ts).frame("patterns")
    delta = patterns[(patterns.kind == "label") & patterns.condition.str.startswith("delta[+0]")].iloc[0]
    pair = patterns[patterns.kind == "pair"].iloc[0]
    assert delta.assessable == 2 and pair.assessable == 1 and pair.excluded == 1


def test_zero_comparison_withholds_ratio_and_default_support_withholds_ranking(tmp_path):
    parent, catalog, ts, req = counted_fixture(tmp_path)
    patterns = run_study(parent, catalog, replace(req, origin="direct_reversal"), ts).frame("patterns")
    assert patterns.empty
    limited = run_study(parent, catalog, replace(req, min_target=20), ts).frame("patterns")
    assert not limited.rank_eligible.any() and limited.matched.max() == 2
    no_other = replace(req, start_ms=ts[0], end_ms=ts[27])
    patterns = run_study(parent, catalog, no_other, ts).frame("patterns")
    assert patterns.frequency_ratio.isna().all() and not patterns.rank_eligible.any()


def test_overview_keeps_families_separate_and_results_are_detached(tmp_path):
    parent, catalog, ts, req = counted_fixture(tmp_path)
    result = run_study(parent, catalog, replace(req, family=None), ts)
    assert len(result.frame("families")) == 2 and result.frame("patterns").empty
    assert result.frame("frequencies").family.nunique() == 2
    rows = result.frame("events")
    key = rows.iloc[0].event_id
    evidence = result.evidence(key)
    evidence["witnesses"].clear()
    rows["family"] = "bad"
    assert result.evidence(key)["witnesses"] and "bad" not in result.frame("events").family.tolist()


def test_ordinary_controls_exclude_both_directions_and_unknown_timing(tmp_path):
    down = tuple(("T" if k == "P" else "P", 220-v) for k, v in CASES[1])
    for known in (True, False):
        parent, catalog, ts, *_ = fixture(tmp_path/str(known), (CASES[1], down), known=known)
        req = study_request(parent, catalog, family="UP/TPTP/0,2,1,3", before=0, after=0,
                            sequence_lengths=(), comparison="non_start", min_target=1, min_comparison=1, min_matches=1)
        result = run_study(parent, catalog, req, ts)
        diag = result.frame("diagnostics").set_index("field").value
        if not known:
            assert diag["Comparison observations"] == 0
        else:
            assert diag["Comparison observations"] == len(ts)-2
            for pattern_id in result.frame("patterns").pattern_id:
                match = result.pattern_matches(pattern_id, "comparison")
                assert not set(match.anchor_ts_ms) & {ts[1], ts[15]}


def test_changing_one_column_or_shuffling_cannot_change_the_other_counts(tmp_path):
    parent, catalog, ts, req = counted_fixture(tmp_path)
    a = run_study(parent, catalog, req, ts)
    changed = parent.columns[1].to_frame().copy()
    value_columns = [c for c in changed if c not in ("ts_ms", "available_at_ms", "profile_id", "source", "mode", "measurement")]
    changed[value_columns] = changed[value_columns].iloc[::-1].to_numpy()
    other = replace(parent, columns=(parent.columns[0], replace(parent.columns[1], _frame=changed)))
    b = run_study(other, catalog, req, ts)
    pd.testing.assert_frame_equal(a.frame("frequencies").query("column == 'delta'").reset_index(drop=True),
                                  b.frame("frequencies").query("column == 'delta'").reset_index(drop=True))
    assert "probability" not in b.frame("patterns").columns and "p_value" not in b.frame("patterns").columns
