"""Known UTC formations drive an independent, copied-evidence event catalogue."""
from dataclasses import replace
from hashlib import sha256
import json

import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.models import DatabaseUtcClassification
from leonardo.analysis.pattern_models import PatternRequest
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.trend_start_patterns import build_catalogue, run_study
from leonardo.financial_tools import UtcClassificationContext, calculate_financial_tool, get_utc_classification
from tests.analysis_test.test_analysis_service import make_database, request, reference, files
from tests.financial_tools_test.test_utc_classification import CASES, _frame, _parameters
from tests.data_manager_test.test_utc_classification_lifecycle import utc_database


def fixture(tmp_path, sequences=(CASES[1],), *, known=True, values=None):
    blocks = []
    for sequence in sequences:
        block = _frame(sequence, tail=6)
        block.loc[len(block)-1, "close"] = np.nan
        blocks.append(block)
    frame = pd.concat(blocks, ignore_index=True)
    columns = values if values is not None else {
        "delta": np.resize(np.arange(-9., 10.), len(frame)),
        "slope": np.resize(np.arange(1., 8.), len(frame))}
    store, manifest, saved = make_database(tmp_path, columns)
    frame["ts_ms"] = saved.ts_ms
    closes = tuple(int(t)+60_000 for t in frame.ts_ms)
    availability = tuple(closes[min(i+2, len(closes)-1)] if i+2 < len(closes) else None for i in range(len(closes)))
    context = UtcClassificationContext(stream_id="test/utc", bar_closed_at_ms=closes,
        swing_available_at_ms=availability) if known else None
    report = get_utc_classification(calculate_financial_tool("UTC", frame, _parameters(), utc_context=context)).to_dict()
    parent = AnalysisService(store).run(request(manifest, *columns))
    bundle = make_bundle(parent, report)
    catalogue = build_catalogue(parent, bundle, saved.ts_ms)
    return parent, catalogue, tuple(int(t) for t in saved.ts_ms), report, store, manifest


def make_bundle(parent, report, *, aliases=("utc_up",), physical="physical", logical="logical"):
    analysis = {"utc_classification": report}
    digest = sha256(json.dumps(analysis, sort_keys=True).encode()).hexdigest()
    associations = [dict(artifact_id=physical, logical_artifact_id=logical, column_name=name, output_name="uptrend",
        first_timestamp_ms=report["timestamps_ms"][0], last_timestamp_ms=report["timestamps_ms"][-1], report_sha256=digest) for name in aliases]
    return DatabaseUtcClassification(parent.entry.reference, json.dumps(dict(schema_version="1.0",
        reports={digest: analysis}, associations=associations)).encode())


def study_request(parent, catalogue, *, kind="T", family=None, **kw):
    direction = "UP" if kind == "T" else "DOWN"
    return PatternRequest(parent.entry.reference, catalogue.run_key, "logical", kind, direction,
        tuple(c.request.source for c in parent.columns), parent.entry.first_timestamp_ms, parent.entry.last_timestamp_ms,
        family=family, **kw)


def test_enrichment_does_not_change_event_families_or_pattern_results(tmp_path):
    parent, original, axis, report, _, _ = fixture(tmp_path)
    frame = _frame(CASES[1], tail=6)
    frame.loc[len(frame)-1, "close"] = np.nan
    frame["ts_ms"] = list(axis)
    result = calculate_financial_tool("UTC", frame, _parameters(),
        utc_context=UtcClassificationContext.from_dict(report["context"]))
    assert result.analysis["utc_classification"] == report
    bundle = make_bundle(parent, report)
    payload = bundle.to_dict()
    digest = sha256(json.dumps(result.analysis, sort_keys=True).encode()).hexdigest()
    payload["reports"] = {digest: result.analysis}
    for association in payload["associations"]: association["report_sha256"] = digest
    enriched = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), axis)
    assert enriched.families("logical", "T") == original.families("logical", "T")
    def facts(value):
        if isinstance(value, dict):
            return {k: facts(v) for k,v in value.items() if k not in
                    ("report_sha256", "measurement_reports", "metrics", "measurement_projections", "context_projections")}
        if isinstance(value, list): return [facts(v) for v in value]
        return value
    assert facts(enriched.instance("logical")) == facts(original.instance("logical"))
    enriched_witness = enriched.instance("logical")["events"][0]["witnesses"][0]
    assert enriched_witness["metrics"]["formation_metrics"]["movement"]["directional_move_points"] == 15
    assert enriched_witness["measurement_projections"]["formation"]["reason"] == ""
    assert original.instance("logical")["events"][0]["witnesses"][0]["metrics"] is None
    before = run_study(parent, original, study_request(parent, original), axis)
    after = run_study(parent, enriched, study_request(parent, enriched), axis)
    for name in ("events", "patterns"):
        left, right = before.frame(name), after.frame(name)
        if "evidence" in left:
            # Provider-report hashes change with the new sibling. Compare every
            # retained semantic witness while preserving that provenance change.
            assert left.evidence.tolist() != right.evidence.tolist()
            left["evidence"] = left.evidence.map(lambda v: json.dumps(facts(json.loads(v)), sort_keys=True))
            right["evidence"] = right.evidence.map(lambda v: json.dumps(facts(json.loads(v)), sort_keys=True))
        pd.testing.assert_frame_equal(left, right, check_exact=True)


@pytest.mark.parametrize("sequence", CASES)
@pytest.mark.parametrize("mirror", (False, True))
def test_twenty_exact_families_and_starting_swings(tmp_path, sequence, mirror):
    if mirror:
        sequence = tuple(("T" if k == "P" else "P", 220-v) for k, v in sequence)
    parent, catalog, ts, report, _, _ = fixture(tmp_path, (sequence,))
    kind = "P" if mirror else "T"
    families = catalog.families("logical", kind)
    assert len(families) == 1 and families[0]["starts"] == 1
    assert families[0]["family"] == report["episodes"][0]["formation_key"]
    assert not catalog.families("logical", "T" if mirror else "P")
    result = run_study(parent, catalog, study_request(parent, catalog, kind=kind), ts)
    event = result.frame("events").iloc[0]
    assert event.anchor_ts_ms == ts[1] and event.event_kind == kind
    assert event.confirmed_at_ms > event.starting_available_at_ms > event.anchor_ts_ms
    assert event.confirmation_delay_bars == len(sequence)*2


def test_aliases_and_repeated_providers_count_once_with_all_witnesses(tmp_path):
    parent, _, ts, report, _, _ = fixture(tmp_path)
    bundle = make_bundle(parent, report, aliases=("alias1", "alias2"))
    payload = bundle.to_dict()
    payload["associations"].append({**payload["associations"][0], "artifact_id": "second"})
    catalog = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), ts)
    instance = catalog.instance("logical")
    assert instance["inspected_episodes"] == 2 and instance["duplicate_witnesses"] == 1
    assert len(instance["events"]) == 1 and len(instance["events"][0]["witnesses"]) == 2
    assert instance["aliases"] == ["alias1", "alias2"]
    instance["events"].clear()
    assert len(catalog.instance("logical")["events"]) == 1


@pytest.mark.parametrize("known", (False, True))
def test_unknown_timing_and_context_outside_selected_coverage(tmp_path, known):
    parent, _, ts, report, _, _ = fixture(tmp_path, known=known)
    bundle = make_bundle(parent, report)
    catalog = build_catalogue(parent, bundle, ts)
    event = catalog.instance("logical")["events"][0]
    assert event["coverage_basis"] == ("verified_confirmation" if known else "structural_coverage_only")
    payload = bundle.to_dict()
    payload["associations"][0]["first_timestamp_ms"] = ts[3]
    excluded = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), ts).instance("logical")["events"][0]
    assert not excluded["eligible"] and "coverage" in excluded["exclusion"]


def test_conflicting_frozen_facts_rejected_and_ranks_not_collapsed(tmp_path):
    parent, catalog, ts, report, _, _ = fixture(tmp_path, (CASES[1], CASES[2]))
    assert len(catalog.families("logical", "T")) == 2
    bundle = make_bundle(parent, report)
    conflicting = json.loads(json.dumps(report))
    conflicting["episodes"][0]["formation"][1]["value"] += .5
    from leonardo.financial_tools import UtcClassificationResult
    UtcClassificationResult.from_dict(conflicting)
    payload = bundle.to_dict()
    payload["reports"]["conflict"] = {"utc_classification": conflicting}
    payload["associations"].append({**payload["associations"][0], "artifact_id": "second", "report_sha256": "conflict"})
    with pytest.raises(ValueError, match="Conflicting frozen"):
        build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), ts)


@pytest.mark.parametrize("bad", [dict(event_kind="P"), dict(trend_direction="DOWN"),
    dict(event_role="trend_end"), dict(family="DOWN/PTPT/3,1,2,0"), dict(columns=("delta",)*2), dict(before=101)])
def test_request_rejects_contradictory_context(tmp_path, bad):
    parent, catalog, *_ = fixture(tmp_path)
    with pytest.raises(ValueError):
        replace(study_request(parent, catalog), **bad)


def test_real_v6_reader_separates_instances_and_preserves_saved_bytes(tmp_path):
    domain, _, _, _, manifest = utc_database(tmp_path, windows=(5, 7))
    service = AnalysisService(domain._creation.store)
    parent = service.run(request(manifest, "close"))
    before = files(domain._creation.store.root_dir)
    catalog = service.load_pattern_catalogue(parent)
    assert len(catalog.to_dict()["instances"]) == 2
    assert {i["parameters"]["trend_fractal_window"] for i in catalog.to_dict()["instances"]} == {5, 7}
    for instance in catalog.to_dict()["instances"]:
        req = replace(study_request(parent, catalog), instance_id=instance["instance_id"])
        result = service.run_patterns(parent, req)
        assert not result.frame("events").empty
    assert files(domain._creation.store.root_dir) == before


def test_legacy_catalogue_does_not_invent_events(tmp_path):
    store, manifest, _ = make_database(tmp_path)
    service = AnalysisService(store)
    catalog = service.load_pattern_catalogue(service.run(request(manifest, "delta")))
    assert catalog.to_dict() == {"status": "legacy_unavailable", "instances": []}


@pytest.mark.parametrize("sequence,origin", [
    ((("T",100),("P",110),("T",105),("T",103)), "candidate_restart"),
    ((("T",100),("P",110),("T",105),("P",115),("T",104),("T",103)), "post_break_restart"),
    ((("T",100),("P",110),("T",105),("P",115),("T",108),("P",112),("T",104)), "direct_reversal"),
    ((("P",120),("T",110),("P",115),("T",105),("P",112),("T",108),("P",116)), "direct_reversal"),
])
def test_restart_and_reversal_keep_frozen_anchor_and_continuation_separate(tmp_path, sequence, origin):
    parent, catalogue, ts, report, *_ = fixture(tmp_path, (sequence,))
    original = json.dumps(report, sort_keys=True)
    last = report["episodes"][-1]
    kind = last["formation"][0]["kind"]
    result = run_study(parent, catalogue, study_request(parent, catalogue, kind=kind, origin=origin), ts)
    row = result.frame("events").iloc[-1]
    assert row.anchor_ts_ms == last["formation"][0]["ts_ms"] and row.origin == origin
    evidence = result.evidence(row.event_id)
    assert evidence["facts"]["formation"] == last["formation"]
    assert "continuations" not in evidence["facts"]
    assert all(c["episode_id"] == w["episode"]["episode_id"] for w in evidence["witnesses"] for c in w["continuations"])
    assert "interrupted" in row.statuses
    if origin == "direct_reversal":
        assert last["shared_pivot"] == last["formation"][0]
        assert sum(e["anchor_ts_ms"] == row.anchor_ts_ms and e["event_kind"] == kind
                   for e in catalogue.instance("logical")["events"]) == 1
        assert evidence["witnesses"][0]["episode"]["predecessor_episode_id"] == report["episodes"][-2]["episode_id"]
    assert json.dumps(report, sort_keys=True) == original


def test_appended_provider_confirms_one_start_using_prior_coverage(tmp_path):
    parent, _, ts, full, *_ = fixture(tmp_path)
    from leonardo.financial_tools import classify_utc_as_of
    data = _frame(CASES[1], tail=6)
    data["ts_ms"] = ts
    data.loc[len(data)-1, "close"] = np.nan
    context = UtcClassificationContext.from_dict(full["context"])
    cutoff = full["episodes"][0]["confirmed_at_ms"]-1
    prefix = classify_utc_as_of(data, _parameters(), context=context, as_of_ms=cutoff).to_dict()
    assert prefix["episodes"] == []
    first = make_bundle(parent, prefix, physical="first").to_dict()
    final = make_bundle(parent, full, physical="appended").to_dict()
    first["associations"][0]["last_timestamp_ms"] = ts[8]
    final["associations"][0]["first_timestamp_ms"] = ts[9]
    first["reports"].update(final["reports"])
    first["associations"].extend(final["associations"])
    bundle = DatabaseUtcClassification(parent.entry.reference, json.dumps(first).encode())
    catalogue = build_catalogue(parent, bundle, ts)
    event = catalogue.instance("logical")["events"][0]
    assert len(catalogue.instance("logical")["events"]) == 1 and event["eligible"]
    assert event["anchor_ts_ms"] == ts[1]
    assert event["witnesses"][0]["recognition_ms"] == ts[9]
    # A legacy old interval cannot fill the needed prior pivot coverage.
    first["reports"][first["associations"][0]["report_sha256"]] = {}
    missing = build_catalogue(parent, replace(bundle, _payload=json.dumps(first).encode()), ts).instance("logical")
    assert not missing["events"][0]["eligible"] and missing["legacy_intervals"]


def test_recognition_uses_actual_later_close_and_rejects_beyond_provider(tmp_path):
    from tests.financial_tools_test.test_utc_classification_timing import _restart_timing_payload
    report = _restart_timing_payload()
    store, manifest, saved = make_database(tmp_path, {"delta": np.arange(len(report["timestamps_ms"]), dtype=float)})
    parent = AnalysisService(store).run(request(manifest, "delta"))
    # Use report timestamps as a detached axis for this structural coverage fixture.
    ts = tuple(report["timestamps_ms"])
    bundle = make_bundle(parent, report)
    catalogue = build_catalogue(parent, bundle, ts)
    event = next(e for e in catalogue.instance("logical")["events"]
                 if e["facts"]["decision_frontier_ms"] > e["facts"]["formation"][-1]["ts_ms"])
    assert event["witnesses"][0]["recognition_ms"] == event["facts"]["decision_frontier_ms"]
    payload = bundle.to_dict()
    payload["associations"][0]["last_timestamp_ms"] = event["facts"]["decision_frontier_ms"]-1
    excluded = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), ts)
    assert not next(e for e in excluded.instance("logical")["events"] if e["event_id"] == event["event_id"])["eligible"]


def test_known_confirmation_later_than_structural_pivots_needs_provider_ownership(tmp_path):
    parent, _, ts, report, *_ = fixture(tmp_path)
    bundle = make_bundle(parent, report)
    payload = bundle.to_dict()
    payload["associations"][0]["last_timestamp_ms"] = ts[8]
    event = build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), ts).instance("logical")["events"][0]
    assert event["exclusion"] == "recognition_outside_provider_coverage"
    assert event["witnesses"][0]["recognition_ms"] == ts[9]
    short_axis = tuple(t for t in ts if t != ts[1])
    assert build_catalogue(parent, bundle, short_axis).instance("logical")["events"][0]["exclusion"] == "pivot_outside_database"


def test_same_word_different_ranks_and_conflicting_configurations(tmp_path):
    parent, catalogue, ts, report, *_ = fixture(tmp_path, (CASES[1], CASES[2]))
    keys = [r["family"] for r in catalogue.families("logical", "T")]
    assert {k.split("/")[1] for k in keys} == {"TPTP"} and len(keys) == 2
    bundle = make_bundle(parent, report)
    payload = bundle.to_dict()
    changed = json.loads(json.dumps(report))
    changed["parameters"]["range_fractal_window"] = 5
    payload["reports"]["other"] = {"utc_classification": changed}
    payload["associations"].append({**payload["associations"][0], "artifact_id": "other", "report_sha256": "other"})
    with pytest.raises(ValueError, match="conflicting rules or configuration"):
        build_catalogue(parent, replace(bundle, _payload=json.dumps(payload).encode()), ts)


def test_actual_v6_append_reconciles_physical_versions_and_keeps_old_start(tmp_path):
    from tests.data_manager_test.test_update_workflow import _append, MARKET
    domain, _, historical, materialization, original = utc_database(tmp_path, collection=True)
    service = AnalysisService(domain._creation.store)
    parent = service.run(request(original, "close"))
    old_catalogue = service.load_pattern_catalogue(parent)
    old_bytes = domain.load_database_revision(original.database_id)
    _append(historical)
    domain.execute_artifact_update(domain.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids))
    appended = domain.execute_database_append(domain.plan_database_update(original.database_id)).database_revision
    new_parent = service.run(request(appended, "close"))
    catalogue = service.load_pattern_catalogue(new_parent)
    old = old_catalogue.to_dict()["instances"][0]
    new = catalogue.to_dict()["instances"][0]
    assert {e["event_id"] for e in old["events"]} <= {e["event_id"] for e in new["events"]}
    assert len(new["providers"]) == 2 and new["duplicate_witnesses"] >= 1
    assert domain.load_database_revision(original.database_id, original.revision_id) == old_bytes
