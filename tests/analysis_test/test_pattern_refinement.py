"""GR-01 frozen evaluation: genuine saved UTC fixtures and independent label counts."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import sys

import pandas as pd
import pytest

from leonardo.analysis.pattern_models import PatternRefinement, NumericCondition, PrecedingContextFilter, PullbackFilter
from leonardo.analysis.pattern_refinement import pin_patterns, evaluate_patterns
from leonardo.analysis.refinement_models import FrozenPatternSet
from leonardo.analysis.trend_start_patterns import run_study, _hash
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture, find_rule, TOLERANT
from tests.analysis_test.test_trend_start_enrichment import ENDED, STANDARD, movement
from tests.analysis_test.test_pre_event_pattern_stability import _reviewed_append_fixture, _preserved_chronology_study
from tests.financial_tools_test.test_utc_classification import CASES


def discover(tmp_path, **kwargs):
    parent, catalogue, axis, request, *_ = planted_fixture(tmp_path, **kwargs)
    return parent, catalogue, run_study(parent, catalogue, request, axis)


def pin_all(parent, catalogue, study):
    return pin_patterns(parent, catalogue, study, study.frame("patterns").pattern_id.tolist())


def parity(study, evaluated):
    old = study.frame("patterns").set_index("pattern_id")
    current = evaluated.frame("patterns").set_index("pattern_id")
    shared = [c for c in current if c in old]
    pd.testing.assert_frame_equal(current[shared], old.loc[current.index, shared])
    for identity in current.index:
        for cohort in ("target", "comparison"):
            actual, expected = evaluated.pattern_matches(identity, cohort), study.pattern_matches(identity, cohort)
            if expected.empty and not len(expected.columns):
                assert actual.empty and len(actual.columns) == 15
            else:
                pd.testing.assert_frame_equal(actual, expected)
            assert json.loads(actual.attrs["pattern_detail"]) == json.loads(expected.attrs["pattern_detail"])


@pytest.mark.parametrize("mirror", (False, True), ids=("UP", "DOWN"))
@pytest.mark.parametrize("radius", (0, 1), ids=("exact", "tolerant"))
def test_parity_and_independent_counts(tmp_path, mirror, radius):
    parent, catalogue, study = discover(tmp_path, mirror=mirror, radius=radius, **({"planted":TOLERANT} if radius else {}))
    frozen = pin_all(parent, catalogue, study)
    evaluated = evaluate_patterns(frozen, study.request.refinement)
    parity(study, evaluated)
    row = find_rule(study, ("P03","P07") if radius else ("P03","P03"))
    counted = evaluated.frame("patterns").set_index("pattern_id").loc[row.pattern_id]
    # Independent direct enumeration: raw saved labels, no observe/count helper.
    terms = json.loads(row.conditions)
    source = {c.request.source:c.to_frame().set_index("ts_ms") for c in parent.columns}
    axis = study._data["timestamps"]
    for cohort, prefix in (("target",""),("comparison","comparison_")):
        assigned = evaluated.frame("cohort_assignments")
        anchors = assigned[assigned.cohort == cohort].anchor_ts_ms.tolist()
        valid = hits = exact = 0
        for anchor in anchors:
            values = [source[t["column"]].loc[axis[axis.index(anchor)+t["offset"]],"bin_label"] for t in terms]
            if any(pd.isna(v) for v in values):
                continue
            valid += 1
            hits += all(v in t["allowed"] for v,t in zip(values,terms))
            exact += all(v == t["center"] for v,t in zip(values,terms))
        assert (counted[prefix+"assessable"],counted[prefix+"matched"],counted[prefix+"exact_matched"]) == (valid,hits,exact)
    assert (counted.matched,counted.comparison_matched) == ((4,1) if radius else (2,0))
    assert set(evaluated.frame("patterns").kind) == {"single baseline","combination"}
    assert evaluated.frame("population_changes").change.eq("unchanged").all()


def test_no_recomputation_and_selection_order(tmp_path, monkeypatch):
    parent, catalogue, study = discover(tmp_path, radius=1, planted=TOLERANT, positive_bins=2)
    ids = study.frame("patterns").pattern_id.tolist()
    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden recomputation")
    patched = []
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith("leonardo.") or module is None:
            continue
        for name,value in tuple(vars(module).items()):
            if callable(value) and (name in ("mine","terms_for_column","run_study","run_pre_event","calculate_financial_tool")
                    or name.startswith(("fit_","classify_","analyze_directional","analyze_variation","measure_utc","get_utc"))):
                monkeypatch.setattr(module,name,forbidden)
                patched.append(module_name+"."+name)
    from leonardo.analysis.service import AnalysisService
    monkeypatch.setattr(AnalysisService,"run",forbidden)
    monkeypatch.setattr(AnalysisService,"run_patterns",forbidden)
    assert any(n.endswith("pre_event_patterns.mine") for n in patched)
    frozen = pin_patterns(parent,catalogue,study,list(reversed(ids)))
    assert [p.pattern_id for p in frozen.patterns] == ids
    assert [p.original_order for p in frozen.patterns] == list(range(1,len(ids)+1))
    current = evaluate_patterns(frozen,study.request.refinement)
    parity(study,current)
    assert any(len(t.centers)>1 for p in frozen.patterns for t in p.terms)


@pytest.mark.parametrize("bad", ([],["missing"],[None],[3],[""],["x","x"],"single",list(map(str,range(501)))))
def test_invalid_selections(tmp_path,bad):
    parent,catalogue,study = discover(tmp_path)
    with pytest.raises(ValueError): pin_patterns(parent,catalogue,study,bad)


@pytest.mark.parametrize("fault", ("reference","run_key","frame","axis","profile","context","event","report","conditions","identity","legacy","overview"))
def test_source_binding_rejects_changed_inputs(tmp_path,fault):
    parent,catalogue,study = discover(tmp_path)
    ids = study.frame("patterns").pattern_id.tolist()[:2]
    if fault == "reference":
        catalogue = replace(catalogue,reference=replace(catalogue.reference,values_sha256="f"*64))
    elif fault == "run_key": catalogue = replace(catalogue,run_key="wrong")
    elif fault in ("frame","axis"):
        parent.columns[0]._frame.loc[0,"ts_ms" if fault=="axis" else "value"] = 0
    elif fault == "profile":
        study._data["columns"][parent.columns[0].request.source]["profile_id"] = "wrong"
    elif fault == "context":
        context = json.loads(study.context);context["utc_parameters"] = {}
        study = replace(study,context=json.dumps(context))
    elif fault in ("event","report"):
        payload = catalogue.to_dict()
        inst = payload["instances"][0]
        if fault == "event": inst["events"][0]["facts"]["origin"] = "forged"
        else: inst["measurement_reports"].clear()
        catalogue = replace(catalogue,_json=json.dumps(payload))
    elif fault == "conditions":
        next(f for n,f in study._tables if n=="patterns").loc[0,"conditions"] = "[]"
    elif fault == "identity":
        old=ids[0];new="f"*64
        next(f for n,f in study._tables if n=="patterns").loc[0,"pattern_id"] = new
        study._data["patterns"][new]=study._data["patterns"].pop(old);ids[0]=new
    else:
        study=replace(study,request=replace(study.request,**({"pre_event":None} if fault=="legacy" else {"family":None})))
    with pytest.raises(ValueError): pin_patterns(parent,catalogue,study,ids)


def test_already_filtered_root_reset_zero_and_lineage(tmp_path):
    parent,catalogue,axis,req,*_ = planted_fixture(tmp_path)
    original_filter = PatternRefinement(basis="formation",pullbacks=PullbackFilter(True,"all_observed",
        (NumericCondition("depth","points",maximum=7,statistic="maximum"),)))
    study=run_study(parent,catalogue,replace(req,refinement=original_filter),axis)
    frozen=pin_all(parent,catalogue,study)
    initial=evaluate_patterns(frozen,original_filter)
    parity(study,initial)
    loosened=evaluate_patterns(frozen,PatternRefinement(),parent=initial)
    assert loosened.frame("patterns").comparison_total.eq(4).all()
    assert (loosened.frame("population_changes").change=="included").any()
    empty=evaluate_patterns(frozen,movement("formation",10000),parent=loosened)
    assert len(empty.frame("patterns"))==len(frozen.patterns)
    assert empty.frame("patterns").matched.eq(0).all()
    assert empty.frame("patterns").frequency.isna().all()
    ledger=empty.pattern_matches(frozen.patterns[0].pattern_id)
    assert ledger.empty and len(ledger.columns)==15 and "pattern_detail" in ledger.attrs
    restored=evaluate_patterns(frozen,original_filter,parent=empty)
    pd.testing.assert_frame_equal(initial.frame("patterns"),restored.frame("patterns"))
    assert initial.evaluation_id != restored.evaluation_id
    assert evaluate_patterns(frozen,original_filter).evaluation_id==initial.evaluation_id
    assert initial.parent_id==frozen.source_discovery_id and restored.parent_id==empty.evaluation_id
    assert not initial.frame("patterns").support_eligible.any()
    with pytest.raises(ValueError):
        evaluate_patterns(pin_patterns(parent,catalogue,study,[frozen.patterns[0].pattern_id]),original_filter,parent=initial)
    other=replace(frozen,root_id="other")
    with pytest.raises(ValueError): evaluate_patterns(other,original_filter,parent=initial)


def test_outcome_complement_both_periods_and_unavailable(tmp_path):
    big=tuple((k,100+2*(v-100)) for k,v in ENDED)
    zero=tuple((k,v-100) for k,v in ENDED)
    parent,catalogue,axis,req,*_=planted_fixture(tmp_path,sequences=(big,ENDED,big,ENDED,STANDARD,zero))
    starts=[e for e in catalogue.instance("logical")["events"] if e["family"]==req.family]
    split=axis[axis.index(starts[2]["anchor_ts_ms"])-7]
    ref=PatternRefinement(movement_enabled=True,movement=(NumericCondition("directional_move","points",30),
                                                         NumericCondition("directional_move","pct",0)))
    req=replace(req,comparison="other_outcomes",refinement=ref,min_matches=1,
                pre_event=replace(req.pre_event,chronological=True,split_ms=split))
    study=run_study(parent,catalogue,req,axis);frozen=pin_all(parent,catalogue,study)
    result=evaluate_patterns(frozen,ref);parity(study,result)
    rows=result.frame("cohort_assignments").query("family == @req.family")
    assert rows.cohort.tolist()==["target","comparison","target","comparison","excluded","excluded"]
    assert set(rows[rows.cohort=="target"].partition)=={"discovery","later"}
    assert set(rows[rows.cohort=="comparison"].partition)=={"discovery","later"}
    assert result.frame("patterns").later_matched.gt(0).any()
    changed=evaluate_patterns(frozen,movement(minimum=100),parent=result)
    assert (changed.frame("population_changes").change=="reassigned").any()
    with pytest.raises(ValueError,match="completed-trend"): evaluate_patterns(frozen,PatternRefinement())
    preceding=replace(ref,preceding=PrecedingContextFilter(True,down=True))
    expected=run_study(parent,catalogue,replace(req,refinement=preceding),axis)
    actual=evaluate_patterns(frozen,preceding)
    pd.testing.assert_frame_equal(expected.frame("cohort_assignments"),actual.frame("cohort_assignments"))


@pytest.mark.parametrize("copied_start", (0,3))
def test_ordinary_eligible_clock_and_control_identity(tmp_path,monkeypatch,copied_start):
    import tests.analysis_test.test_pre_event_pattern_stability as stability
    captured=[]
    def record(parent,catalogue,request,axis,**kwargs):
        study=run_study(parent,catalogue,request,axis,**kwargs)
        captured.append((parent,catalogue,study));return study
    monkeypatch.setattr(stability,"run_study",record)
    # Reuse the genuine two-provider fixture and execute its original assertions unchanged.
    stability.test_ordinary_partition_requires_an_eligible_covering_provider(tmp_path,copied_start)
    parent,catalogue,study=captured[-1]
    frozen=pin_all(parent,catalogue,study);result=evaluate_patterns(frozen,study.request.refinement)
    parity(study,result)
    ledger=result.pattern_matches(frozen.patterns[0].pattern_id,"comparison")
    assert ledger.partition.eq("excluded").all() and not ledger.ranking_support.any()
    identity=ledger.iloc[0].event_id
    assert result.evidence(identity)["role"]=="ordinary_timestamp"
    assert "facts" not in result.evidence(identity)
    starts={e["anchor_ts_ms"] for e in catalogue.instance("logical")["events"]}
    assert not starts & set(ledger.anchor_ts_ms)
    for bad in ("control:1","control:"+str(next(iter(starts))),"control:000"+identity.split(":")[1]):
        with pytest.raises(ValueError): result.evidence(bad)
        with pytest.raises(ValueError): result.event_window(bad)
    with pytest.raises(ValueError,match="preceding-context"):
        evaluate_patterns(frozen,PatternRefinement(preceding=PrecedingContextFilter(True,down=True)))


@pytest.mark.parametrize("mirror",(False,True),ids=("UP","DOWN"))
def test_F1_complete_and_reviewed_append(tmp_path,mirror):
    parent,catalogues,axis,req=_reviewed_append_fixture(tmp_path,mirror=mirror)
    results=[]
    for catalogue in catalogues:
        study=_preserved_chronology_study(parent,catalogue,req,axis)
        assert len(study.frame("patterns"))==42 and study.frame("patterns").kind.eq("combination").sum()==30
        result=evaluate_patterns(pin_all(parent,catalogue,study),req.refinement)
        parity(study,result);results.append(result)
        sample=next(s for s in result._data["samples"] if s["anchor"]==7)
        assert (sample["evidence_start_ms"],sample["evidence_end_ms"],sample["partition"])==(1700000420000,1700001320000,"discovery")
    pd.testing.assert_frame_equal(results[0].frame("patterns"),results[1].frame("patterns"))


@pytest.mark.parametrize("fault",("missing_formation_row","missing_outcome_row","unknown_formation","unknown_outcome","incomplete_prefix","conflicting_prefix"))
def test_F1_bad_evidence_remains_excluded(tmp_path,fault):
    parent,catalogues,axis,req=_reviewed_append_fixture(tmp_path,fault=fault)
    req=replace(req,pre_event=replace(req.pre_event,split_ms=axis[-2]))
    catalogue=catalogues[1]
    study=_preserved_chronology_study(parent,catalogue,req,axis)
    result=evaluate_patterns(pin_all(parent,catalogue,study),req.refinement)
    first=result.frame("cohort_assignments").query("anchor_ts_ms == 1700000420000").iloc[0]
    assert first.cohort=="excluded" or first.partition=="excluded"
    parity(study,result)


def test_split_boundary_added_evidence_reset_and_automatic_split(tmp_path):
    parent,catalogues,axis,req=_reviewed_append_fixture(tmp_path)
    cat=catalogues[1]
    req=replace(req,refinement=movement("formation"),pre_event=replace(req.pre_event,split_ms=1700001320000))
    study=_preserved_chronology_study(parent,cat,req,axis);frozen=pin_all(parent,cat,study)
    first=evaluate_patterns(frozen,req.refinement)
    later=evaluate_patterns(frozen,movement(),parent=first)
    assert later.frame("patterns").matched.eq(0).all()
    change=later.frame("population_changes").query("anchor_ts_ms == 1700000420000").iloc[0]
    assert (change.parent_cohort,change.current_cohort,change.current_partition,change.change)==("target","target","excluded","status_changed")
    reset=evaluate_patterns(frozen,req.refinement,parent=later)
    pd.testing.assert_frame_equal(first.frame("patterns"),reset.frame("patterns"))
    auto_req=replace(req,pre_event=replace(req.pre_event,split_ms=None))
    auto=_preserved_chronology_study(parent,cat,auto_req,axis)
    pinned=pin_all(parent,cat,auto)
    assert pinned.original_request.pre_event.split_ms is None
    assert pinned.metadata()["automatic_split"]
    for ref in (movement(),movement("formation",10000),auto_req.refinement):
        result=evaluate_patterns(pinned,ref)
        assert result.request.pre_event.split_ms==json.loads(auto.context)["split_ms"]


def test_missing_cells_gap_and_unknown_timing(tmp_path):
    parent,catalogue,axis,req,*_=planted_fixture(tmp_path,known=False)
    position=axis.index(catalogue.instance("logical")["events"][0]["anchor_ts_ms"])-1
    parent.columns[1]._frame.loc[position,"bin_label"]=None
    study=run_study(parent,catalogue,replace(req,min_matches=1),axis)
    result=evaluate_patterns(pin_all(parent,catalogue,study),study.request.refinement)
    parity(study,result)
    row=find_rule(study,("P03","P03"))
    counts=result.frame("patterns").set_index("pattern_id").loc[row.pattern_id]
    assert (counts.assessable,counts.matched,counts.ready_matched)==(3,1,0)
    window=result.event_window(next(iter(study._data["events"])))
    assert not window.empty
    assert not result.frame("patterns").support_eligible.any()


def test_incomplete_memory_and_model_selection_bounds(tmp_path):
    parent,catalogue,axis,req,*_=planted_fixture(tmp_path)
    study=run_study(parent,catalogue,replace(req,pre_event=replace(req.pre_event,candidate_limit=5)),axis)
    frozen=pin_all(parent,catalogue,study)
    result=evaluate_patterns(frozen,req.refinement)
    assert not frozen.metadata()["original_search"]["complete"]
    assert result.frame("patterns").support_reason.eq("source_discovery_incomplete").all()
    with pytest.raises(ValueError,match="evaluation_match_state_limit.*required=.*allowed="):
        evaluate_patterns(frozen,req.refinement,memory_limit_bytes=1)
    for value in (True,0,128*1024*1024+1,1.5):
        with pytest.raises(ValueError): evaluate_patterns(frozen,req.refinement,memory_limit_bytes=value)
    required=json.loads(result.context)["estimated_retained_match_state_bytes"]
    pd.testing.assert_frame_equal(result.frame("patterns"),evaluate_patterns(frozen,req.refinement,memory_limit_bytes=required).frame("patterns"))
    # Model-level cap only: these size specimens are not source-authentic mined rules.
    one=replace(frozen,patterns=(frozen.patterns[0],))
    assert len(one.patterns)==1
    many=tuple(replace(one.patterns[0],pattern_id=_hash(("size-only",i)),original_order=i+1) for i in range(501))
    assert len(replace(one,patterns=many[:500]).patterns)==500
    with pytest.raises(ValueError): replace(one,patterns=many)


def test_detachment_cancellation_and_public_views(tmp_path):
    parent,catalogue,study=discover(tmp_path,radius=1,planted=TOLERANT)
    frozen=pin_all(parent,catalogue,study);result=evaluate_patterns(frozen,study.request.refinement)
    before=result.frame("patterns");ids=before.pattern_id.tolist()
    parent.columns[0]._frame.loc[:,"bin_label"]="changed"
    study._data["events"].clear();study._data["columns"]["delta"]["frame"].loc[:,"bin_label"]="changed"
    metadata=frozen.metadata();metadata["source"].clear()
    original_view=frozen.original_patterns();original_view.loc[:,"conditions"]="changed"
    for name in ("patterns","cohort_assignments","refinement_funnel","population_changes","diagnostics"):
        frame=result.frame(name);frame.iloc[:,:]=None;frame.attrs["x"]={"y":[]}
    event_id=next(iter(result._data["events"]))
    result.evidence(event_id)["facts"].clear()
    window=result.event_window(event_id);window.iloc[:,:]=None
    ledger=result.pattern_matches(ids[0]);ledger.attrs.clear();ledger.iloc[:,:]=None
    pd.testing.assert_frame_equal(before,evaluate_patterns(frozen,frozen.original_request.refinement,parent=result).frame("patterns"))
    with pytest.raises(FrozenInstanceError): frozen.set_id="change"
    with pytest.raises(ValueError): result.pattern_matches("unknown")
    with pytest.raises(ValueError): result.pattern_matches(ids[0],"unknown")
    with pytest.raises(KeyError): result.frame("unknown")
    def cancel(): raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError,match="cancelled"): result.pattern_matches(ids[0],checkpoint=cancel)
    with pytest.raises(RuntimeError,match="cancelled"): evaluate_patterns(frozen,PatternRefinement(),checkpoint=cancel)
    def stop_progress(*args): raise RuntimeError("cancelled progress")
    with pytest.raises(RuntimeError,match="cancelled progress"): evaluate_patterns(frozen,PatternRefinement(),progress=stop_progress)
    pd.testing.assert_frame_equal(before,evaluate_patterns(frozen,frozen.original_request.refinement).frame("patterns"))


def test_mid_work_cancellation_is_local(tmp_path,monkeypatch):
    parent,catalogue,study=discover(tmp_path)
    original=study.frame("patterns")
    calls=0
    def stop_pin():
        nonlocal calls
        calls+=1
        if calls==8: raise RuntimeError("pin cancelled")
    with pytest.raises(RuntimeError,match="pin cancelled"):
        pin_patterns(parent,catalogue,study,original.pattern_id.tolist(),checkpoint=stop_pin)
    frozen=pin_all(parent,catalogue,study)
    import leonardo.analysis.pattern_refinement as engine
    real_observe=engine.observe;observed=0
    def track(*args):
        nonlocal observed
        observed+=1
        return real_observe(*args)
    monkeypatch.setattr(engine,"observe",track)
    def stop_masks():
        if observed>=8: raise RuntimeError("mask cancelled")
    with pytest.raises(RuntimeError,match="mask cancelled"): evaluate_patterns(frozen,study.request.refinement,checkpoint=stop_masks)
    result=evaluate_patterns(frozen,study.request.refinement)
    calls=0
    def stop_detail():
        nonlocal calls
        calls+=1
        if calls==10: raise RuntimeError("detail cancelled")
    with pytest.raises(RuntimeError,match="detail cancelled"):
        result.pattern_matches(frozen.patterns[0].pattern_id,checkpoint=stop_detail)
    pd.testing.assert_frame_equal(original,study.frame("patterns"))
    parity(study,evaluate_patterns(frozen,study.request.refinement))


def test_zero_matches_positive_denominator_and_later_only(tmp_path):
    big=tuple((k,100+2*(v-100)) for k,v in ENDED)
    parent,catalogue,axis,req,*_=planted_fixture(tmp_path,sequences=(ENDED,ENDED,big,big))
    starts=[e for e in catalogue.instance("logical")["events"] if e["family"]==req.family]
    split=axis[axis.index(starts[2]["anchor_ts_ms"])-7]
    req=replace(req,refinement=movement("formation"),min_matches=1)
    study=run_study(parent,catalogue,req,axis)
    planted=find_rule(study,("P03","P03"))
    frozen=pin_all(parent,catalogue,study)
    restricted=evaluate_patterns(frozen,movement("formation",minimum=30))
    row=restricted.frame("patterns").set_index("pattern_id").loc[planted.pattern_id]
    assert (row.total,row.assessable,row.matched,row.frequency)==(2,2,0,0)
    assert not row.support_eligible
    chrono=run_study(parent,catalogue,replace(req,pre_event=replace(req.pre_event,chronological=True,split_ms=split)),axis)
    pinned=pin_all(parent,catalogue,chrono)
    later=evaluate_patterns(pinned,movement("formation",minimum=30))
    assert later.frame("patterns").total.eq(0).all() and later.frame("patterns").frequency.isna().all()
    assert later.frame("patterns").later_total.eq(2).all() and later.frame("patterns").later_matched.gt(0).any()
    parity(chrono,evaluate_patterns(pinned,chrono.request.refinement))


@pytest.mark.parametrize("known",(True,False),ids=("known","unknown"))
def test_both_direction_start_exclusion_and_unknown_control_clocks(tmp_path,known):
    down=tuple(("P" if k=="T" else "T",220-v) for k,v in CASES[1])
    parent,catalogue,axis,req,*_=planted_fixture(tmp_path,sequences=(CASES[1],down,CASES[2],down),known=known)
    req=replace(req,comparison="non_start",min_matches=1)
    study=run_study(parent,catalogue,req,axis)
    frozen=pin_all(parent,catalogue,study);result=evaluate_patterns(frozen,req.refinement)
    parity(study,result)
    events=catalogue.instance("logical")["events"]
    assert {e["direction"] for e in events}=={"UP","DOWN"}
    ledger=result.pattern_matches(frozen.patterns[0].pattern_id,"comparison")
    if known:
        assert not ledger.empty
        assert not {e["anchor_ts_ms"] for e in events} & set(ledger.anchor_ts_ms)
        assert all(result.evidence(i)["role"]=="ordinary_timestamp" for i in ledger.event_id)
    else:
        assert ledger.empty and len(ledger.columns)==15
        assert result.frame("patterns").comparison_total.eq(0).all()


def test_absolute_row_positions_id_formulas_and_types(tmp_path):
    parent,catalogue,study=discover(tmp_path)
    ids=study.frame("patterns").pattern_id.tolist()
    selected=[ids[-1],ids[2]]
    frozen=pin_patterns(parent,catalogue,study,selected)
    assert [p.original_order for p in frozen.patterns]==[3,len(ids)]
    assert frozen.root_id==_hash(("gr01-root-v1",frozen.source_discovery_id))
    assert frozen.source_discovery_id==_hash(("gr01-discovery-v1",frozen.metadata()["source"]))
    assert frozen.set_id==_hash(("gr01-set-v1",frozen.root_id,[ids[2],ids[-1]]))
    again=pin_patterns(parent,catalogue,study,list(reversed(selected)))
    assert (again.root_id,again.set_id)==(frozen.root_id,frozen.set_id)
    result=evaluate_patterns(frozen,study.request.refinement)
    assert result.evaluation_id==_hash(("gr01-evaluation-v1",frozen.set_id,frozen.source_discovery_id,study.request.refinement.to_dict()))
    with pytest.raises(TypeError): pin_patterns(None,catalogue,study,selected)
    with pytest.raises(TypeError): evaluate_patterns(frozen,None)
    with pytest.raises(TypeError): evaluate_patterns(None,study.request.refinement)


def test_segment_gap_and_128_sample_cancellation(tmp_path,monkeypatch):
    parent,catalogue,axis,req,*_=planted_fixture(tmp_path)
    req=replace(req,comparison="non_start",min_matches=1)
    study=run_study(parent,catalogue,req,axis)
    frozen=pin_all(parent,catalogue,study);result=evaluate_patterns(frozen,req.refinement)
    # A control just inside a later UTC segment cannot borrow a label across its boundary.
    instance=catalogue.instance("logical")
    boundaries=instance["segment_starts"][1:]
    first=next(t for t in boundaries if t>axis[0])
    identity="control:"+str(axis[axis.index(first)+1])
    eligible=[p for p in frozen.patterns if any(t.offset<=-2 for t in p.terms)]
    ledger=result.pattern_matches(eligible[0].pattern_id,"comparison")
    case=ledger[ledger.event_id==identity]
    assert len(case)==1 and not case.iloc[0].assessable
    import leonardo.analysis.pattern_refinement as engine
    original=engine.observe;calls=0;cancelled_at=[]
    def observe(*args):
        nonlocal calls
        calls+=1
        return original(*args)
    def checkpoint():
        if calls>=128:
            cancelled_at.append(calls)
            raise RuntimeError("128 sample checkpoint")
    monkeypatch.setattr(engine,"observe",observe)
    with pytest.raises(RuntimeError,match="128 sample checkpoint"):
        evaluate_patterns(frozen,req.refinement,checkpoint=checkpoint)
    assert cancelled_at==[128]
    parity(study,evaluate_patterns(frozen,req.refinement))


# R2: bind every supplied source input to the original discovery-time stamp.
from pathlib import Path
import os
import subprocess

from leonardo.analysis.pattern_refinement import _pin_source_binding
from leonardo.analysis.trend_start_patterns import build_catalogue, analysis_key
from leonardo.financial_tools import fit_directional_binning, fit_dynamic_binning
from tests.analysis_test.test_trend_start_enrichment import saved_analysis, bundle_for
from tests.financial_tools_test.test_utc_classification import _frame


def _r2_reject_unchanged(parent, catalogue, study, message="source_discovery_binding_mismatch"):
    rows = study.frame("patterns")
    before = (catalogue.to_dict(), deepcopy(study._data["events"]), study.context,
              study._data.get("_pin_source_binding"))
    frames = [c.to_frame() for c in parent.columns]
    profiles = [c.profile.to_dict() if c.profile else None for c in parent.columns]
    with pytest.raises(ValueError, match=message):
        pin_patterns(parent, catalogue, study, rows.pattern_id.tolist()[:3])
    assert before == (catalogue.to_dict(), study._data["events"], study.context,
                      study._data.get("_pin_source_binding"))
    pd.testing.assert_frame_equal(rows, study.frame("patterns"))
    for column, frame, profile in zip(parent.columns, frames, profiles):
        pd.testing.assert_frame_equal(column.to_frame(), frame)
        assert (column.profile.to_dict() if column.profile else None) == profile


@pytest.mark.parametrize("mirror", (False, True), ids=("UP", "DOWN"))
def test_r2_genuine_extra_provider_under_reused_catalogue_key(tmp_path, mirror):
    parent, catalogue, axis, req, _, _, bundle = planted_fixture(tmp_path, mirror=mirror)
    req = replace(req, comparison="non_start", pre_event=replace(req.pre_event, chronological=True, split_ms=axis[100]))
    study = run_study(parent, catalogue, req, axis)
    block = _frame(CASES[1], tail=8)
    early = pd.concat((block.iloc[[0]*6], block), ignore_index=True).iloc[:7].copy()
    early["ts_ms"] = axis[:7]
    prefix = saved_analysis(early)
    assert not prefix["utc_classification"]["episodes"]
    full = next(iter(bundle.to_dict()["reports"].values()))
    alternative = build_catalogue(parent, bundle_for(parent, [("one", full, axis[0], axis[-1]),
        ("early", {"utc_classification":prefix["utc_classification"]}, axis[0], axis[6])]), axis)
    assert catalogue.reference == alternative.reference and catalogue.run_key == alternative.run_key
    for field in ("events", "measurement_reports"):
        assert catalogue.instance("logical")[field] == alternative.instance("logical")[field]
    assert catalogue.instance("logical")["observation_evidence"] != alternative.instance("logical")["observation_evidence"]
    original = evaluate_patterns(pin_all(parent, catalogue, study), req.refinement)
    assert json.loads(original.context)["population_counts"]["comparison_"] == 0
    _r2_reject_unchanged(parent, alternative, study)
    parity(study, evaluate_patterns(pin_all(parent, catalogue, study), req.refinement))


@pytest.mark.parametrize("mirror", (False, True), ids=("UP", "DOWN"))
@pytest.mark.parametrize("mode", ("directional_intensity", "value", "magnitude"))
def test_r2_genuine_scaled_profile_same_id(tmp_path, mirror, mode):
    parent, catalogue, study = discover(tmp_path, mirror=mirror, measurement=mode)
    column = parent.columns[0]
    old = column.profile
    frame = column.to_frame()
    scaled = pd.DataFrame({"ts_ms":frame.ts_ms, "available_at_ms":frame.available_at_ms,
                           column.request.source:frame.raw_value*100})
    fit = fit_directional_binning if mode == "directional_intensity" else fit_dynamic_binning
    profile = fit(scaled, old.context, profile_id=old.profile_id, calibration_as_of_ms=old.calibration_as_of_ms,
        provenance=old.provenance, policy=old.policy, **({} if mode == "directional_intensity" else {"measurement":mode}))
    supplied = replace(parent, columns=(replace(column, profile=profile), *parent.columns[1:]))
    assert profile.profile_id == old.profile_id and profile.to_dict() != old.to_dict()
    assert analysis_key(supplied) == analysis_key(parent)
    pd.testing.assert_frame_equal(supplied.columns[0].to_frame(), frame)
    _r2_reject_unchanged(supplied, catalogue, study)
    assert parent.columns[0].profile is old
    pin_all(parent, catalogue, study)


def test_r2_changed_clock_rejects_even_when_current_counts_are_equal(tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    req = replace(req, comparison="non_start", pre_event=replace(req.pre_event, chronological=True, split_ms=axis[100]))
    study = run_study(parent, catalogue, req, axis)
    payload = catalogue.to_dict()
    clock = payload["instances"][0]["observation_evidence"][0]
    assert clock["control_eligible"] and clock["known"]
    clock["observed_at_ms"] += 60_000
    alternative = replace(catalogue, _json=json.dumps(payload))
    # Detached boundary mismatch, deliberately not a persisted-report validation claim.
    fresh = run_study(parent, alternative, req, axis)
    pd.testing.assert_frame_equal(study.frame("patterns"), fresh.frame("patterns"))
    pd.testing.assert_frame_equal(study.frame("cohort_assignments"), fresh.frame("cohort_assignments"))
    _r2_reject_unchanged(parent, alternative, study)


@pytest.mark.parametrize("mode", ("directional_intensity", "value", "magnitude"))
def test_r2_complete_profile_payload_beyond_term_bins(tmp_path, mode):
    parent, catalogue, study = discover(tmp_path, measurement=mode)
    column = parent.columns[0]
    profile = replace(column.profile, provenance=(*column.profile.provenance, "additional-reference-evidence"))
    assert profile.analysis == column.profile.analysis
    assert profile.profile_id == column.profile.profile_id
    assert "additional-reference-evidence" not in study.frame("patterns").conditions.str.cat()
    _r2_reject_unchanged(replace(parent, columns=(replace(column, profile=profile), *parent.columns[1:])), catalogue, study)


def _r2_reverse_dicts(value):
    if isinstance(value, dict):
        return {k:_r2_reverse_dicts(v) for k,v in reversed(tuple(value.items()))}
    if isinstance(value, list):
        return [_r2_reverse_dicts(v) for v in value]
    return value


@pytest.mark.parametrize("mode", ("directional_intensity", "value", "magnitude"))
def test_r2_equal_detached_inputs_and_dictionary_order(tmp_path, mode):
    parent, catalogue, study = discover(tmp_path, measurement=mode)
    copied = replace(parent, columns=tuple(replace(c, _frame=c.to_frame(),
        profile=type(c.profile).from_dict(_r2_reverse_dicts(c.profile.to_dict()))) for c in parent.columns))
    reordered = replace(catalogue, _json=json.dumps(_r2_reverse_dicts(catalogue.to_dict())))
    original = pin_all(parent, catalogue, study)
    actual = pin_all(copied, reordered, study)
    assert (actual.root_id, actual.set_id) == (original.root_id, original.set_id)
    parity(study, evaluate_patterns(actual, study.request.refinement))
    instance = reordered.instance(study.request.instance_id)
    stamp = _pin_source_binding(copied, instance, study._data["timestamps"])
    instance["events"][0]["refinement"] = {"disposable":"ignored"}
    assert _pin_source_binding(copied, instance, study._data["timestamps"]) == stamp
    assert instance["events"][0]["refinement"] == {"disposable":"ignored"}


@pytest.mark.parametrize("bad", (None, "", " ", 7, {}, []))
def test_r2_missing_invalid_stamp_requires_explicit_discovery(tmp_path, bad, monkeypatch):
    parent, catalogue, study = discover(tmp_path)
    if bad is None:
        study._data.pop("_pin_source_binding")
    else:
        study._data["_pin_source_binding"] = bad
    import leonardo.analysis.pattern_refinement as engine
    def forbidden(*args, **kwargs):
        raise AssertionError("missing stamp must not be recreated")
    monkeypatch.setattr(engine, "_pin_source_binding", forbidden)
    _r2_reject_unchanged(parent, catalogue, study, "source_discovery_binding_missing: rerun the original discovery explicitly")
    assert not study.frame("patterns").empty  # old transient studies remain inspectable


@pytest.mark.parametrize("field", ("raw_value", "profile_payload", "descriptor"))
def test_r2_original_input_mutation_before_pinning(tmp_path, field):
    parent, catalogue, study = discover(tmp_path)
    column = parent.columns[0]
    if field == "raw_value":
        column._frame.loc[0, "raw_value"] += 1
    elif field == "profile_payload":
        object.__setattr__(column.profile, "provenance", (*column.profile.provenance, "mutated-input"))
    else:
        parent = replace(parent, columns=(replace(column, column=replace(column.column, unit="changed")), *parent.columns[1:]))
    _r2_reject_unchanged(parent, catalogue, study)


@pytest.mark.parametrize("fault", ("content", "profile"))
def test_r2_unselected_third_analyzed_column_is_bound(tmp_path, fault):
    from leonardo.analysis.service import AnalysisService
    from tests.analysis_test.test_analysis_service import request as bin_request
    old, _, axis, req, store, manifest, bundle = planted_fixture(tmp_path)
    parent = AnalysisService(store).run(bin_request(manifest, "delta", "volume_change", "close"))
    catalogue = build_catalogue(parent, bundle, axis)
    req = replace(req, run_key=analysis_key(parent))
    study = run_study(parent, catalogue, req, axis)
    assert "close" not in req.columns and len(parent.columns) == 3
    column = parent.columns[-1]
    assert column.profile is not None
    if fault == "content":
        frame = column.to_frame(); frame.loc[0, "raw_value"] += 1
        column = replace(column, _frame=frame)
    else:
        column = replace(column, profile=replace(column.profile, provenance=(*column.profile.provenance, "changed-third")))
    _r2_reject_unchanged(replace(parent, columns=(*parent.columns[:-1], column)), catalogue, study)
    pin_all(parent, catalogue, study)


def test_r2_binding_scope_order_duplicates_and_no_profile(tmp_path):
    parent, catalogue, study = discover(tmp_path)
    instance, axis = catalogue.instance("logical"), study._data["timestamps"]
    stamp = _pin_source_binding(parent, instance, axis)
    assert isinstance(stamp, str) and json.loads(stamp)["kind"] == "gr01-pin-source-v1"
    assert _pin_source_binding(replace(parent, columns=tuple(reversed(parent.columns))), instance, axis) != stamp
    changed = deepcopy(instance); changed["events"].reverse()
    assert _pin_source_binding(parent, changed, axis) != stamp
    for supplied, timestamps in ((replace(parent, columns=(*parent.columns, parent.columns[0])), axis),
                                  (parent, tuple(reversed(axis))), (parent, (axis[0],)*len(axis))):
        with pytest.raises(ValueError): _pin_source_binding(supplied, instance, timestamps)
    for entry in (replace(parent.entry, rows=parent.entry.rows+1), replace(parent.entry, name="changed")):
        assert _pin_source_binding(replace(parent, entry=entry), instance, axis) != stamp
    empty = replace(parent, columns=(replace(parent.columns[0], profile=None), *parent.columns[1:]))
    payload = json.loads(_pin_source_binding(empty, instance, axis))
    assert payload["columns"][0]["profile"] == {"type":None,"payload_hash":None}


def test_r2_binding_cancellation_does_not_corrupt_discovery(tmp_path, monkeypatch):
    import leonardo.analysis.pattern_refinement as engine
    parent, catalogue, study = discover(tmp_path)
    instance, axis = catalogue.instance("logical"), study._data["timestamps"]
    before = deepcopy(instance)
    expected = _pin_source_binding(parent, instance, axis)
    frames = [c.to_frame() for c in parent.columns]
    for stop in (2, 6, 10, 12, 13):
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == stop: raise RuntimeError("binding cancelled")
        with pytest.raises(RuntimeError, match="binding cancelled"):
            _pin_source_binding(parent, instance, axis, checkpoint=cancel)
        assert instance == before
        assert _pin_source_binding(parent, instance, axis) == expected
    def cancel_capture(*args, **kwargs):
        raise RuntimeError("capture cancelled")
    with monkeypatch.context() as patch:
        patch.setattr(engine, "_pin_source_binding", cancel_capture)
        with pytest.raises(RuntimeError, match="capture cancelled"):
            run_study(parent, catalogue, study.request, axis)
    fresh = run_study(parent, catalogue, study.request, axis)
    assert fresh._data["_pin_source_binding"] == expected
    for column, frame in zip(parent.columns, frames): pd.testing.assert_frame_equal(column.to_frame(), frame)
    parity(study, evaluate_patterns(pin_all(parent, catalogue, study), study.request.refinement))


@pytest.mark.parametrize("first", ("pre_event_patterns", "pattern_refinement"))
def test_r2_fresh_interpreter_import_orders(first):
    root = Path(__file__).resolve().parents[2]
    second = "pattern_refinement" if first == "pre_event_patterns" else "pre_event_patterns"
    script = ("import importlib,json; names=" + repr((first, second)) +
              "; print(json.dumps({n:importlib.import_module('leonardo.analysis.'+n).__file__ for n in names}))")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(root/"src")+os.pathsep+str(root))
    process = subprocess.run([sys.executable, "-B", "-c", script], cwd=root, env=env, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert not process.stderr
    paths = json.loads(process.stdout)
    assert all(Path(path).is_relative_to(root/"src") for path in paths.values())
