"""Hand-counted stored-label predicates and reusable real UTC/binning fixtures."""
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.pattern_models import PreEventSpec
from leonardo.analysis.pre_event_patterns import Term, terms_for_column
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.trend_start_patterns import build_catalogue, run_study
from tests.analysis_test.test_analysis_service import make_database, request
from tests.analysis_test.test_trend_start_catalogue import study_request
from tests.analysis_test.test_trend_start_enrichment import bundle_for, saved_analysis
from tests.financial_tools_test.test_utc_classification import CASES, _frame


JOINT = ((3, 3), (3, 3), (7, 7), (7, 7), (3, 7), (3, 7), (7, 3), (7, 3))
TOLERANT = ((2, 6), (4, 8), (2, 8), (4, 6), (2, 6), (9, 2), (9, 2), (9, 2))


def planted_fixture(tmp_path, *, planted=JOINT, sequences=None, mirror=False, known=True, radius=0,
                    positive_bins=10, negative_bins=10, measurement="directional_intensity"):
    sequences = sequences or (CASES[1],)*4+(CASES[2],)*4
    blocks, anchors, size = [], [], 0
    for sequence in sequences:
        if mirror:
            sequence = tuple(("P" if k == "T" else "T", 220-v) for k, v in sequence)
        block = _frame(sequence, tail=8)
        prefix = block.iloc[[0]*6].copy().reset_index(drop=True)
        block = pd.concat((prefix, block), ignore_index=True)
        block.loc[len(block)-1, "close"] = np.nan
        anchors.append(size+7)
        size += len(block)
        blocks.append(block)
    frame = pd.concat(blocks, ignore_index=True)
    # Keep a large neutral reservoir and an exactly uniform calibration distribution.
    pad = 100 + (-len(frame)) % 10
    frame = pd.concat((frame, frame.iloc[[0]*pad]), ignore_index=True)
    values = {name: np.tile(np.arange(1., 11.), len(frame)//10) for name in ("delta", "volume_change")}
    for index, (name, offset) in enumerate((("delta", -4), ("volume_change", -1))):
        placements = {anchor+offset: pair[index] for anchor, pair in zip(anchors, planted)}
        reserved = set(placements)
        for position, value in placements.items():
            donor = next(i for i, actual in enumerate(values[name]) if i not in reserved and actual == value)
            values[name][donor], values[name][position] = values[name][position], values[name][donor]
            reserved.add(donor)
    store, manifest, saved = make_database(tmp_path, values)
    frame["ts_ms"] = saved.ts_ms
    parent = AnalysisService(store).run(request(manifest, *values, minimum=2, positive_bins=positive_bins,
                                               negative_bins=negative_bins, measurement=measurement))
    analysis = saved_analysis(frame, known=known)
    axis = tuple(int(t) for t in frame.ts_ms)
    bundle = bundle_for(parent, [("one", analysis, axis[0], axis[-1])])
    catalogue = build_catalogue(parent, bundle, axis)
    direction, kind = ("DOWN", "P") if mirror else ("UP", "T")
    family = direction+("/PTPT/3,1,2,0" if mirror else "/TPTP/0,2,1,3")
    req = study_request(parent, catalogue, kind=kind, family=family, before=6, after=2,
        min_target=1, min_comparison=1, min_matches=2, pre_event=PreEventSpec(max_terms=2, tolerance=radius))
    return parent, catalogue, axis, req, store, manifest, bundle


def find_rule(study, centers, *, offsets=(-4, -1)):
    names = ("delta", "volume_change")
    for row in study.frame("patterns").itertuples():
        terms = json.loads(row.conditions)
        if len(terms) == 2 and all((t["column"], t["offset"], t["center"]) == (name, offset, center)
                                for t, name, offset, center in zip(terms, names, offsets, centers)):
            return row
    raise AssertionError(f"Missing planted rule {centers}")


def test_spec_is_immutable_strictly_negative_and_retains_column_overrides():
    spec = PreEventSpec(history=6, lead=3, tolerance=1, overrides=(("momentum", 0),))
    assert spec.offsets == (-8, -7, -6, -5, -4, -3)
    assert spec.radius("delta") == 1 and spec.radius("momentum") == 0
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError): spec.lead = 0
    for kwargs in ({"lead": 0}, {"history": 101}, {"tolerance": 2}, {"candidate_limit": 0}, {"max_terms": 5},
                   {"overrides": (("a", 0), ("a", 1))}, {"split_ms": 1}, {"history": True}):
        with pytest.raises(ValueError): PreEventSpec(**kwargs)
    for offset in (0, 1):
        with pytest.raises(ValueError, match="negative"):
            Term("a", offset, "p", ("P01",), ("P01",), "[]")


def test_tolerance_uses_profile_indices_and_stays_on_its_sign(tmp_path):
    values = {"delta": np.tile(np.r_[np.arange(-120., 0.), 0, np.arange(1., 121.)], 2)}
    store, manifest, _ = make_database(tmp_path, values)
    parent = AnalysisService(store).run(request(manifest, "delta", positive_bins=120, negative_bins=7))
    column = parent.columns[0]
    terms = terms_for_column(column, "delta", (-1,), 1)
    by_center = {t.center: t for t in terms}
    assert by_center["P100"].allowed == ("P99", "P100", "P101")
    assert by_center["N01"].allowed == ("N01", "N02")
    assert by_center["N07"].allowed == ("N06", "N07")
    assert by_center["Zero"].allowed == ("Zero",)
    assert all(not ({"Zero", "P01"} & set(t.allowed)) for t in terms if t.center.startswith("N"))


def test_empty_bins_are_not_skipped_and_unordered_modes_are_exact_only(tmp_path):
    store, manifest, _ = make_database(tmp_path, {"delta": [1., 2.]*20})
    column = AnalysisService(store).run(request(manifest, "delta")).columns[0]
    bins = column.profile.analysis.positive.to_dict()["bins"]
    assert any(not b["count"] for b in bins)
    term = next(t for t in terms_for_column(column, "delta", (-1,), 1) if t.center == "P03")
    assert term.allowed == ("P02", "P03", "P04")
    dynamic = AnalysisService(store).run(request(manifest, "delta", measurement="value")).columns[0]
    with pytest.raises(ValueError, match="directional-bin"):
        terms_for_column(dynamic, "delta", (-1,), 1)
    assert all(t.allowed == (t.center,) for t in terms_for_column(dynamic, "delta", (-1,), 0))


@pytest.mark.parametrize("values", ([1.]*20, [-1.]*20, [0.]*20, [np.nan]*20))
def test_degenerate_zero_and_absent_references_never_gain_wildcards(tmp_path, values):
    store, manifest, _ = make_database(tmp_path, {"delta": values})
    column = AnalysisService(store).run(request(manifest, "delta")).columns[0]
    terms = terms_for_column(column, "delta", (-1,), 0)
    assert not terms or all(t.allowed == ("Zero",) for t in terms)
