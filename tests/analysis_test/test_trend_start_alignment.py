from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.trend_start_patterns import run_study, _continuity
from tests.analysis_test.test_trend_start_catalogue import fixture, study_request, CASES


def test_missing_labels_and_history_edges_remain_per_column(tmp_path):
    delta = np.arange(-7., 7.)
    delta[1] = np.nan
    parent, catalog, ts, *_ = fixture(tmp_path, values={"delta": delta, "slope": np.arange(1., 15.)})
    result = run_study(parent, catalog, study_request(parent, catalog), ts)
    f = result.frame("frequencies")
    assert f[(f.column == "delta") & (f.offset == 0)].iloc[0].assessable == 0
    assert f[(f.column == "slope") & (f.offset == 0)].iloc[0].assessable == 1
    assert f[f.offset == -20].unavailable.tolist() == [1, 1]
    event = result.frame("events").iloc[0]
    window = result.event_window(event.event_id)
    assert len(window) == 41*2
    row = window[(window.column == "delta") & (window.offset == 0)].iloc[0]
    assert pd.isna(row.raw_value) and row.status == "missing_value"
    assert row.ts_ms == ts[1] and row.elapsed_ms == 0
    window.loc[:, "raw_value"] = 42
    assert pd.isna(result.event_window(event.event_id).query("column == 'delta' and offset == 0").iloc[0].raw_value)


def test_zero_constant_and_single_sign_are_not_fabricated_bins(tmp_path):
    parent, catalog, ts, *_ = fixture(tmp_path, values={"zero": np.zeros(14), "constant": np.ones(14),
        "negative": -np.arange(1., 15.)})
    result = run_study(parent, catalog, study_request(parent, catalog), ts)
    f = result.frame("frequencies").query("offset == 0")
    assert f.query("column == 'zero'").iloc[0].label == "Zero"
    assert f.query("column == 'constant'").iloc[0].assessable == 0
    assert f.query("column == 'negative'").iloc[0].label.startswith("N")


def test_axis_mismatch_is_not_repaired_or_nearest_joined(tmp_path):
    parent, catalog, ts, *_ = fixture(tmp_path)
    bad = parent.columns[0].to_frame()
    bad.loc[0, "ts_ms"] += 1
    altered = replace(parent, columns=(replace(parent.columns[0], _frame=bad), *parent.columns[1:]))
    with pytest.raises(ValueError, match="axes"):
        run_study(altered, catalog, study_request(parent, catalog), ts)
    with pytest.raises(ValueError, match="identities"):
        run_study(parent, catalog, replace(study_request(parent, catalog), run_key="stale"), ts)


def test_calendar_fixed_gaps_and_segment_boundaries_use_actual_rows():
    ts = tuple(int(pd.Timestamp(t, tz="UTC").timestamp()*1000) for t in ("2024-01-31", "2024-02-29", "2024-03-31"))
    instance = {"coverage": ((ts[0], ts[-1]),), "segment_starts": []}
    breaks, coverage = _continuity(ts, "1M", instance)
    assert breaks.tolist() == [0, 0, 0] and all(coverage)
    instance = {"coverage": ((0, 240000),), "segment_starts": [240000]}
    breaks, _ = _continuity((0, 60000, 180000, 240000), "1m", instance)
    assert breaks.tolist() == [0, 0, 1, 2]


def test_anchor_date_filter_does_not_crop_event_window_or_refit(tmp_path):
    parent, catalog, ts, *_ = fixture(tmp_path, (CASES[1], CASES[2]))
    before = [c.to_frame() for c in parent.columns]
    req = replace(study_request(parent, catalog), start_ms=ts[1], end_ms=ts[1])
    result = run_study(parent, catalog, req, ts)
    assert len(result.frame("events")) == 1
    window = result.event_window(result.frame("events").iloc[0].event_id)
    assert window.query("offset == 1").iloc[0].ts_ms == ts[2]
    for column, original in zip(parent.columns, before, strict=True):
        pd.testing.assert_frame_equal(column.to_frame(), original)


def test_all_missing_column_still_has_issue_rows(tmp_path):
    parent, catalog, ts, *_ = fixture(tmp_path, values={"missing": np.full(14, np.nan)})
    result = run_study(parent, catalog, study_request(parent, catalog), ts)
    assert result.frame("frequencies").assessable.sum() == 0
    assert result.frame("frequencies").unavailable.sum() == 41
