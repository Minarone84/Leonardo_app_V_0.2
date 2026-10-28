from dataclasses import replace
import json
import pandas as pd
import pytest

from leonardo.analysis.trend_start_patterns import run_study
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture, find_rule, TOLERANT


@pytest.mark.parametrize("mirror", (False, True))
def test_joint_signal_survives_zero_marginal_contrast_and_lists_reconcile(tmp_path, mirror):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, mirror=mirror)
    study = run_study(parent, catalogue, req, axis)
    row = find_rule(study, ("P03", "P03"))
    assert (row.matched, row.assessable, row.comparison_matched, row.comparison_assessable) == (2, 4, 0, 4)
    assert row.difference_pp == 50 and row.frequency_ratio is None and row.rank_eligible
    frame = study.frame("patterns")
    for name, offset in (("delta", -4), ("volume_change", -1)):
        single = frame[(frame.kind == "single baseline") & (frame.condition == f"{name}[{offset:+d}] in {{P03}}")].iloc[0]
        assert single.matched == single.comparison_matched == 2 and single.difference_pp == 0
    for cohort, expected in (("target", 2), ("comparison", 0)):
        ledger = study.pattern_matches(row.pattern_id, cohort)
        assert len(ledger) == 4 and ledger.matched.sum() == expected
        detail = json.loads(ledger.attrs["pattern_detail"])
        assert all(r["assessable"] == 4 for r in detail["simpler_on_same_assessable_rows"])
    assert all(t["offset"] < 0 for value in frame.conditions for t in json.loads(value))


def test_tolerance_is_applied_before_support_pruning_and_unobserved_centers_exist(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, planted=TOLERANT, radius=1)
    req = replace(req, min_matches=3)
    study = run_study(parent, catalogue, req, axis)
    row = find_rule(study, ("P03", "P07"))
    assert (row.matched, row.exact_matched, row.added_by_tolerance) == (4, 0, 4)
    assert (row.comparison_matched, row.comparison_exact_matched, row.comparison_added_by_tolerance) == (1, 0, 1)
    for cohort, expected in (("target", 4), ("comparison", 1)):
        ledger = study.pattern_matches(row.pattern_id, cohort)
        assert ledger.matched.sum() == expected and not ledger.exact_match.any()
    exact = run_study(parent, catalogue, replace(req, pre_event=replace(req.pre_event, tolerance=0)), axis)
    assert not any(json.loads(v)[0]["center"] == "P03" for v in exact.frame("patterns").conditions
                   if len(json.loads(v)) == 2 and json.loads(v)[0]["offset"] == -4)


def test_event_future_and_inspection_length_do_not_change_pre_event_statistics(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    original = run_study(parent, catalogue, req, axis)
    anchors = [axis.index(e["anchor_ts_ms"]) for e in catalogue.instance("logical")["events"]]
    columns = []
    for column in parent.columns:
        frame = column.to_frame()
        for anchor in anchors:
            frame.loc[[anchor, anchor+1], "bin_label"] = "P10"
        columns.append(replace(column, _frame=frame))
    changed = run_study(replace(parent, columns=tuple(columns)), catalogue, replace(req, after=20), axis)
    pd.testing.assert_frame_equal(original.frame("patterns"), changed.frame("patterns"))
    reordered = run_study(parent, catalogue, replace(req, columns=tuple(reversed(req.columns))), axis)
    pd.testing.assert_frame_equal(original.frame("patterns"), reordered.frame("patterns"))


def test_missing_and_limited_cells_keep_visible_denominators_and_no_ranking(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    event = catalogue.instance("logical")["events"][0]
    position = axis.index(event["anchor_ts_ms"])-1
    frame = parent.columns[1].to_frame()
    frame.loc[position, "bin_label"] = None
    frame["support_status"] = "limited_support"
    changed = replace(parent, columns=(parent.columns[0], replace(parent.columns[1], _frame=frame)))
    study = run_study(changed, catalogue, replace(req, min_matches=1), axis)
    row = find_rule(study, ("P03", "P03"))
    assert (row.total, row.assessable, row.excluded, row.matched) == (4, 3, 1, 1)
    assert not row.rank_eligible and row.ready_matched == 0
    ledger = study.pattern_matches(row.pattern_id)
    assert ledger.assessable.eq(False).sum() == 1
    assert all(v["assessable"] == 3 for v in json.loads(ledger.attrs["pattern_detail"])["simpler_on_same_assessable_rows"])


def test_limits_cancellation_baseline_only_and_detached_results(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    for setting in ({"candidate_limit": 5}, {"memory_limit_bytes": 10}):
        study = run_study(parent, catalogue, replace(req, pre_event=replace(req.pre_event, **setting)), axis)
        context = json.loads(study.context)
        assert not context["search"]["complete"]
        rows = study.frame("patterns")
        assert rows.empty or not rows.rank_eligible.any()
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        run_study(parent, catalogue, req, axis, checkpoint=cancel)
    study = run_study(parent, catalogue, replace(req, pre_event=replace(req.pre_event, history=1)), axis)
    assert set(study.frame("patterns").kind) == {"single baseline"}
    rows = study.frame("patterns")
    rows.loc[:, "condition"] = "changed"
    assert "changed" not in study.frame("patterns").condition.tolist()
    assert not any(n in study.frame("patterns") for n in ("probability", "p_value", "confidence"))
