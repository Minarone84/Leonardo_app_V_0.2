"""Task 1083: exact anchor projection, retained-rule counts and source invariants."""
from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal
import asyncio
import json

import pandas as pd
import pytest
from leonardo.analysis.pattern_models import FamilyScope, PatternRefinement
from leonardo.analysis.refinement_models import (AnchorDateRange as Range, GranularRefinement as D,
    GranularGroup as G, GranularPredicate as P, _plain, convert_legacy_refinement, summarize_granular_refinement)
from leonardo.analysis.pattern_refinement import (pin_patterns, evaluate_patterns, evaluate_granular_patterns,
    resolve_granular_population, search_granular_patterns, _grdate_apply, _grdate_resolve,
    _grdate_validate_presentation, _gr03_charge)
from leonardo.analysis.application import _gr03_validate_output
from tests.analysis_test.test_family_scope_refinement import multi_case, count_oracle, A, B
from tests.analysis_test.test_family_scope_application import revision_case
from tests.analysis_test.test_granular_integration import independently_count
from tests.analysis_test.test_refinement_outcomes import horizon


@pytest.mark.parametrize('start,end', [(True,3),('1',3),(1.,3),(Decimal(1),3),(-1,3),(0,2**63),(3,2),(0,False)])
def test_strict_integer_range_rejects_invalid_values(start,end):
    with pytest.raises((TypeError,ValueError)):Range(start,end)


def test_boundary_singleton_schema_and_immutable_value():
    value=Range(300,600)
    assert [value.contains(t) for t in (299,300,301,599,600,601)]==[False,True,True,True,True,False]
    assert [Range(400,400).contains(t) for t in (399,400,401)]==[False,True,False]
    assert Range(0,0).contains(0) and not any(Range(401,499).contains(t) for t in (100,200,300,400,500,600))
    assert Range.from_dict(value.to_dict())==value
    for raw in (True,'300',300.,Decimal(300),-1,2**63):
        with pytest.raises((TypeError,ValueError)):value.contains(raw)
    for payload in ({**value.to_dict(),'extra':1},{'start_ms':300,'end_ms':600},{**value.to_dict(),'kind':'wrong'}):
        with pytest.raises((TypeError,ValueError)):Range.from_dict(payload)
    with pytest.raises((TypeError,ValueError)):Range(1,2,extra=1)
    with pytest.raises(AttributeError):value.start_ms=1


@pytest.mark.parametrize('definition',[D(),D(family_scope=FamilyScope('selected',[A,B])),
    D(outcome=(G(conditions=(horizon(),)),)),
    D(common=(G(conditions=(P('context','up','boolean',allowed=(True,)),)),),
      outcome=(G(conditions=(horizon(),)),),family_scope=FamilyScope('all'))])
def test_serialized_kinds_exact_old_default_and_new_strict_shape(definition):
    old=definition.to_dict();identity=definition.identity
    assert 'anchor_range' not in old and 'anchor_range' not in _plain(definition)
    assert D.from_dict(old).identity==identity
    dated=replace(definition,anchor_range=Range(100,900));payload=dated.to_dict()
    assert set(payload)=={'kind','common','outcome','family_scope','anchor_range'}
    assert payload['kind']=='gr-date-filter-spec-v1' and D.from_dict(payload)==dated
    assert payload['common']==old['common'] and payload['outcome']==old['outcome']
    assert 'Anchor timestamps: 100 through 900 UTC ms, inclusive' in summarize_granular_refinement(dated)
    for altered in ({**old,'anchor_range':Range(100,900).to_dict()},
        {k:v for k,v in payload.items() if k!='anchor_range'}, {**payload,'anchor_range':None},
        {k:v for k,v in payload.items() if k!='family_scope'}, {**payload,'family_scope':{}},
        {**payload,'unexpected':None},{**payload,'kind':'unknown'}):
        with pytest.raises((TypeError,ValueError)):D.from_dict(altered)
    class Child(D):pass
    assert 'anchor_range' not in _plain(Child())
    @dataclass
    class Unrelated: anchor_range: object=None
    assert _plain(Unrelated())=={'anchor_range':None}
    assert _plain(P('context','up','boolean'))['basis'] is None
    assert convert_legacy_refinement(PatternRefinement(),comparison='non_start').anchor_range is None


@pytest.fixture(scope='module')
def base(tmp_path_factory):
    parent,cat,axis,request,study,families=multi_case(tmp_path_factory.mktemp('anchor_base'),comparison='non_start')
    frozen=pin_patterns(parent,cat,study,study.frame('patterns').pattern_id.tolist()[:4])
    return frozen,parent,cat,axis,request,study,families


def test_literal_projection_and_cancellation(base):
    request=replace(base[4],start_ms=100,end_ms=900)
    inputs=[('early_event',100,False,'target','discovery','passes_filters',''),
        ('lower_boundary_event',300,False,'target','discovery','passes_filters',''),
        ('comparison_event',400,False,'comparison','later','fails_outcome_definition',''),
        ('inside_prior_exclusion',500,False,'excluded','excluded','common_condition_mismatch','not_in_cohort'),
        ('upper_boundary_control',600,True,'comparison','later','ordinary_common_pass',''),
        ('outside_control',700,True,'comparison','discovery','ordinary_common_pass',''),
        ('outside_unavailable',900,False,'excluded','excluded','unavailable_requested_evidence','not_in_cohort')]
    records=[dict(zip(('row_id','anchor_ts_ms','ordinary','cohort','partition','reason','partition_reason'),r)) for r in inputs]
    samples=[dict(event_id=r['row_id'],anchor=i,ordinary=r['ordinary']) for i,r in enumerate(records) if r['cohort']!='excluded']
    original=deepcopy(records);calls=[]
    unchanged,header,summary=_grdate_apply(records,samples,D(),request,lambda:calls.append(1))
    assert unchanged is samples and records==original and header is summary is None
    kept,header,summary=_grdate_apply(records,samples,D(anchor_range=Range(300,600)),request,lambda:calls.append(1))
    assert [s['event_id'] for s in kept]==['lower_boundary_event','comparison_event','upper_boundary_control']
    assert all(any(s is prior for prior in samples) for s in kept)
    assert summary==dict(root_candidates=7,inside_candidates=4,outside_candidates=3,outside_target=1,
        outside_comparison=1,outside_previously_excluded=1,kept_target=1,kept_comparison=2,kept_excluded=1)
    for prior,row in zip(original,records,strict=True):
        inside=300<=prior['anchor_ts_ms']<=600
        assert row['ordinary']==prior['ordinary'] and row['anchor_range_check']['in_range']==inside
        assert all(row['anchor_range_check']['prior_'+key]==prior[key] for key in ('cohort','reason','partition','partition_reason'))
        assert row['reason']==(prior['reason'] if inside else 'outside_anchor_range')
    assert sum(r['cohort']=='excluded' for r in records)==4
    assert header==dict(kind='gr-date-anchor-scope-v1',root_start_ms=100,root_end_ms=900,start_ms=300,end_ms=600,inclusive=True,basis='anchor_ts_ms')
    for bounds in ((99,900),(100,901)):
        with pytest.raises(ValueError,match='original pinned interval'):_grdate_resolve(D(anchor_range=Range(*bounds)),request)
    many=[dict(original[0],row_id=str(i)) for i in range(260)]
    hits=[]
    def cancel():
        hits.append(1)
        if len(hits)==3:raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):_grdate_apply(many,[],D(anchor_range=Range(300,600)),request,cancel)
    assert sum('anchor_range_check' in row for row in many)==128


def assert_projection(full,narrow,bounds):
    before=full.population_report();after=narrow.population_report()
    full_definition=full.granular_definition;dated_definition=narrow.granular_definition
    assert full_definition.anchor_range is None
    assert dated_definition==replace(full_definition,anchor_range=bounds)
    for report,definition in ((before,full_definition),(after,dated_definition)):
        assert report['definition']==definition.to_dict()
        assert report['definition_id']==definition.identity
    selected=[s for s in before['samples'] if bounds.start_ms<=full._data['timestamps'][s['anchor']]<=bounds.end_ms]
    assert after['samples']==selected
    assert len(after['records'])==len(before['records'])
    status_fields=('cohort','reason','partition','partition_reason')
    for old,new in zip(before['records'],after['records'],strict=True):
        projection={k:v for k,v in new.items() if k not in ('anchor_range_check',*status_fields)}
        original={k:v for k,v in old.items() if k not in status_fields}
        for record,evidence,definition in ((old,original,full_definition),(new,projection,dated_definition)):
            predicate_report=record['predicate_report']
            if predicate_report is not None:
                evaluated=D(common=definition.common) if record['ordinary'] else definition
                assert predicate_report['definition_id']==evaluated.identity
                # Identity is checked above. Every other predicate-report field must agree.
                evidence['predicate_report']={k:v for k,v in predicate_report.items() if k!='definition_id'}
        assert projection==original
        inside=bounds.start_ms<=old['anchor_ts_ms']<=bounds.end_ms
        assert new['anchor_range_check']==dict(in_range=inside,
            **{'prior_'+key:old[key] for key in status_fields})
        expected={key:old[key] for key in status_fields} if inside else dict(
            cohort='excluded',reason='outside_anchor_range',partition='excluded',partition_reason='outside_anchor_range')
        assert {key:new[key] for key in status_fields}==expected
    c=after['anchor_range_summary']
    assert c['root_candidates']==c['inside_candidates']+c['outside_candidates']==len(before['records'])
    assert c['outside_candidates']==c['outside_target']+c['outside_comparison']+c['outside_previously_excluded']
    assert c['inside_candidates']==c['kept_target']+c['kept_comparison']+c['kept_excluded']
    assert after['summary']['cohort_excluded']==c['outside_candidates']+c['kept_excluded']
    assert narrow._data['timestamps']==full._data['timestamps']
    assert after['resolved_split_ms']==before['resolved_split_ms']


@pytest.mark.parametrize('mirror',(False,True),ids=('UP','DOWN'))
@pytest.mark.parametrize('mode',('directional_intensity','value','magnitude'))
@pytest.mark.parametrize('comparison',('other_families','other_outcomes','non_start','recurrence'))
def test_genuine_modes_questions_fixed_rule_counts_and_family_zero(tmp_path,mirror,mode,comparison,monkeypatch):
    parent,cat,axis,request,study,families=multi_case(tmp_path,mirror=mirror,mode=mode,comparison=comparison,
        scope=FamilyScope('all') if comparison=='other_outcomes' else None)
    assert not study.frame('patterns').empty
    frozen=pin_patterns(parent,cat,study,study.frame('patterns').pattern_id.tolist()[:4])
    import leonardo.analysis.pre_event_patterns as mining
    import leonardo.analysis.service as service
    from leonardo.data_manager.creation_store import DataManagerCreationStore
    def forbidden(*a,**k):pytest.fail('Evaluate crossed source, fit or mining boundary')
    monkeypatch.setattr(mining,'mine',forbidden)
    for name in ('fit_directional_binning','fit_dynamic_binning'):monkeypatch.setattr(service,name,forbidden)
    monkeypatch.setattr(DataManagerCreationStore,'load_database_revision',forbidden)
    converted=convert_legacy_refinement(request.refinement,comparison=comparison)
    bounds=Range(axis[len(axis)//3],axis[2*len(axis)//3])
    full=evaluate_granular_patterns(frozen,converted)
    narrow=evaluate_granular_patterns(frozen,replace(converted,anchor_range=bounds),parent=full)
    assert_projection(full,narrow,bounds);count_oracle(narrow,frozen)
    rows=narrow.frame('patterns').set_index('pattern_id')
    for pattern in frozen.patterns:
        for prefix,counts in independently_count(narrow,pattern).items():
            for key,count in counts.items():assert rows.loc[pattern.pattern_id,prefix+key]==count
    assert narrow.frame('patterns').pattern_id.tolist()==[p.pattern_id for p in frozen.patterns]
    for scope in (FamilyScope('exact',[families[0]]),FamilyScope('selected',families[:2]),FamilyScope('all')):
        definition=replace(converted,family_scope=scope,anchor_range=Range(axis[-2]+1,axis[-1]-1))
        if comparison=='other_families' and scope.mode=='all':
            with pytest.raises(ValueError):evaluate_granular_patterns(frozen,definition)
            continue
        empty=evaluate_granular_patterns(frozen,definition,parent=narrow)
        assert not empty.population_report()['samples'] and empty.frame('patterns').matched.eq(0).all()
        assert set(empty.frame('family_population').family.dropna())==set(families)
        assert empty.frame('family_population').target.eq(0).all()
        restored=evaluate_granular_patterns(frozen,replace(definition,anchor_range=None),parent=empty)
        assert 'anchor_range' not in restored.population_report()
    if comparison=='non_start':
        old=evaluate_patterns(frozen,request.refinement)
        dated=evaluate_granular_patterns(frozen,replace(converted,anchor_range=bounds),parent=old)
        changes=dated.frame('population_changes')
        ordinary={r['row_id'] for r in dated.population_report()['records'] if r['ordinary']}
        if not changes.empty:
            assert changes.loc[changes.event_id.isin(ordinary),'ordinary'].eq(True).all()


def test_repeated_narrow_widen_branch_and_exact_payload_budget(base):
    frozen,_,_,axis,_,_,_=base
    full=evaluate_granular_patterns(frozen,D())
    one=evaluate_granular_patterns(frozen,D(anchor_range=Range(axis[20],axis[-20])),parent=full)
    two=evaluate_granular_patterns(frozen,D(anchor_range=Range(axis[40],axis[-40])),parent=one)
    wide=evaluate_granular_patterns(frozen,D(anchor_range=Range(axis[0],axis[-1])),parent=full)
    assert wide.parent_id==full.evaluation_id and two.parent_id==one.evaluation_id
    pd.testing.assert_frame_equal(wide.frame('patterns'),full.frame('patterns'),check_exact=True)
    assert wide.granular_definition.identity!=full.granular_definition.identity
    reset=evaluate_granular_patterns(frozen,D(),parent=two)
    assert reset.population_report()['samples']==full.population_report()['samples']
    report=resolve_granular_population(frozen,one.granular_definition)
    charge=_gr03_charge(report)
    with pytest.raises(ValueError,match='granular_payload_limit'):
        resolve_granular_population(frozen,one.granular_definition,memory_limit_bytes=charge-1)
    assert resolve_granular_population(frozen,one.granular_definition,memory_limit_bytes=charge)['accounting']['retained_payload_bytes']==charge
    report['records'].clear()
    assert one.population_report()['records'] and frozen.original_request==base[4]


@pytest.mark.parametrize('split',('automatic','manual'))
def test_old_split_and_included_crossing_evidence(tmp_path,split):
    from leonardo.analysis.trend_start_patterns import run_study
    parent,cat,axis,request,study,_=multi_case(tmp_path,chronological=True)
    if split=='automatic':
        request=replace(request,pre_event=replace(request.pre_event,split_ms=None))
        study=run_study(parent,cat,request,axis)
    frozen=pin_patterns(parent,cat,study,study.frame('patterns').pattern_id.tolist()[:4])
    full=evaluate_granular_patterns(frozen,D());cut=frozen.resolved_split
    assert cut is not None
    for bounds in (Range(axis[0],cut-1),Range(cut,axis[-1]),Range(cut-1,cut+1),Range(axis[0]+1,axis[0]+2)):
        result=evaluate_granular_patterns(frozen,D(anchor_range=bounds),parent=full)
        assert_projection(full,result,bounds)
        assert result._data['split_ms']==cut and result.request.pre_event.split_ms==cut
    from leonardo.analysis.pre_event_cohorts import partition_sample
    # The accepted fixture cases above carry all real exclusions; no alternate split arithmetic is added.
    crossing=[r for r in full.population_report()['records'] if r['partition']=='excluded' and r['cohort']!='excluded']
    for row in crossing:
        result=evaluate_granular_patterns(frozen,D(anchor_range=Range(row['anchor_ts_ms'],row['anchor_ts_ms'])))
        kept=next(r for r in result.population_report()['records'] if r['row_id']==row['row_id'])
        assert kept['partition_reason']==row['partition_reason']


@pytest.fixture(scope='module',params=('UP','DOWN'))
def priced(request,tmp_path_factory):return revision_case(tmp_path_factory.mktemp('anchor_prices'),direction=request.param)


def test_inputs_before_and_horizon_after_singleton_do_not_shrink_source(priced):
    case=priced;definition=D(outcome=(G(conditions=(horizon(n=6,minimum=-1000),)),),family_scope=FamilyScope('all'))
    full=evaluate_granular_patterns(case.frozen,definition)
    candidates=[r for r in full.population_report()['records'] if r['cohort']=='target' and r['feature_start_ms'] is not None
                and r['horizon_windows'][0]['end_ts_ms']>r['anchor_ts_ms']]
    assert candidates
    row=candidates[len(candidates)//2];bounds=Range(row['anchor_ts_ms'],row['anchor_ts_ms'])
    result=evaluate_granular_patterns(case.frozen,replace(definition,anchor_range=bounds))
    assert_projection(full,result,bounds)
    actual=result.population_record(row['row_id'])
    assert actual['feature_start_ms']<bounds.start_ms and actual['horizon_windows'][0]['end_ts_ms']>bounds.end_ms
    assert actual['scalar_ledger']==row['scalar_ledger'] and actual['horizon_windows']==row['horizon_windows']
    assert result.population_report()['horizon_source']==full.population_report()['horizon_source']
    _gr03_validate_output(result,case.frozen,result.granular_definition,case.frozen.source_discovery_id)


@pytest.mark.parametrize('fault',('header','summary','check_type','prior_cohort','membership','final_reason','escape','duplicate','ordinary','table','stale'))
def test_defensive_date_delivery_rejects_tampered_projection(base,fault):
    frozen,_,_,axis,*_=base
    definition=D(anchor_range=Range(axis[10],axis[-10]))
    result=deepcopy(evaluate_granular_patterns(frozen,definition));report=result._data['_gr03_population'];context=json.loads(result.context)
    if fault=='header':context['anchor_range']['root_start_ms']+=1
    elif fault=='summary':report['anchor_range_summary']['inside_candidates']+=1
    elif fault=='check_type':report['records'][0]['anchor_range_check']['in_range']=1
    elif fault=='prior_cohort':report['records'][0]['anchor_range_check']['prior_cohort']='invented'
    elif fault=='membership':report['records'][0]['anchor_range_check']['in_range']=not report['records'][0]['anchor_range_check']['in_range']
    elif fault=='final_reason':report['records'][0]['reason']='invented'
    elif fault=='escape':report['samples'][0]['anchor']=0
    elif fault=='duplicate':report['samples'].append(deepcopy(report['samples'][0]))
    elif fault=='ordinary':report['samples'][0]['ordinary']=not report['samples'][0]['ordinary']
    elif fault=='table':
        frame=result.frame('population');frame.loc[0,'anchor_in_range']=not frame.loc[0,'anchor_in_range']
        result=replace(result,_tables=tuple((n,frame if n=='population' else f) for n,f in result._tables))
    else:
        result=deepcopy(evaluate_granular_patterns(frozen,D()));definition=D()
        context=json.loads(result.context);context['anchor_range']={}
    result=replace(result,context=json.dumps(context))
    with pytest.raises((ValueError,TypeError,KeyError)):_gr03_validate_output(result,frozen,definition,frozen.source_discovery_id)


def test_search_one_mine_dated_repin_clear_stale_and_empty(base,monkeypatch):
    frozen,parent,cat,axis,*_=base
    import leonardo.analysis.pre_event_patterns as mining
    import leonardo.analysis.service as service
    from leonardo.data_manager.creation_store import DataManagerCreationStore
    original=mining.mine;calls=[]
    def counted(*args,**kw):calls.append(deepcopy(args[0]['samples']));return original(*args,**kw)
    def forbidden(*a,**k):pytest.fail('Search attempted fit or source reload')
    monkeypatch.setattr(mining,'mine',counted)
    monkeypatch.setattr(service,'fit_directional_binning',forbidden)
    monkeypatch.setattr(service,'fit_dynamic_binning',forbidden)
    monkeypatch.setattr(DataManagerCreationStore,'load_database_revision',forbidden)
    definition=D(anchor_range=Range(axis[10],axis[-10]))
    expected=evaluate_granular_patterns(frozen,definition)
    candidate=search_granular_patterns(frozen,parent,cat,definition,parent_id=expected.evaluation_id)
    assert len(calls)==1 and calls[0]==expected.population_report()['samples']
    _gr03_validate_output(candidate,frozen,definition,expected.evaluation_id,search=True)
    ids=candidate.frame('patterns').pattern_id.tolist()[:4];assert ids
    repin=pin_patterns(parent,cat,candidate,ids)
    assert repin.granular_definition==definition and repin.original_request.start_ms==frozen.original_request.start_ms
    reset=evaluate_granular_patterns(repin,D())
    full=evaluate_granular_patterns(frozen,D())
    assert reset.population_report()['samples']==full.population_report()['samples']
    cleared=search_granular_patterns(repin,parent,cat,D(),parent_id=reset.evaluation_id)
    assert 'anchor_range' not in json.loads(cleared.context) and 'anchor_range_summary' not in json.loads(cleared.context)
    empty_definition=D(anchor_range=Range(axis[0]+1,axis[0]+2))
    empty=search_granular_patterns(frozen,parent,cat,empty_definition,parent_id=expected.evaluation_id)
    assert empty.frame('patterns').empty and empty.population_report()['samples']==[]
    with pytest.raises((ValueError,TypeError)):pin_patterns(parent,cat,empty,[])
    tampered=deepcopy(candidate);ctx=json.loads(tampered.context);ctx['anchor_range']['end_ms']-=1
    with pytest.raises(ValueError):pin_patterns(parent,cat,replace(tampered,context=json.dumps(ctx)),ids)


# Task 1083 R2: definition identity and numerical evidence are separate assertions.
@pytest.fixture(scope='module')
def r2_projection_pair(base):
    frozen,_,_,axis,*_=base
    column=frozen.original_request.columns[0]
    condition=P('column','raw_value','native',column=column,
        profile_id=frozen._root['columns'][column]['profile_id'],offset=-1,minimum=Decimal('-1e100'))
    definition=D(common=(G(conditions=(condition,)),))
    bounds=Range(axis[len(axis)//3],axis[2*len(axis)//3])
    full=evaluate_granular_patterns(frozen,definition)
    dated=evaluate_granular_patterns(frozen,replace(definition,anchor_range=bounds),parent=full)
    for result in (full,dated):
        records=result.population_report()['records']
        assert any(r['ordinary'] and r['predicate_report'] is not None for r in records)
        assert any(not r['ordinary'] and r['predicate_report'] is not None for r in records)
    return full,dated,bounds


def test_r2_projection_checks_owning_ids_without_mutating_reports(r2_projection_pair):
    full,dated,bounds=r2_projection_pair
    before=deepcopy((full.population_report(),dated.population_report()))
    assert full.granular_definition.identity!=dated.granular_definition.identity
    assert_projection(full,dated,bounds)
    assert (full.population_report(),dated.population_report())==before
    ordinary=[r for r in dated.population_report()['records'] if r['ordinary'] and r['predicate_report'] is not None]
    common_id=D(common=dated.granular_definition.common).identity
    assert common_id!=dated.granular_definition.identity
    assert all(r['predicate_report']['definition_id']==common_id for r in ordinary)


@pytest.mark.parametrize('fault',('full_event_id','dated_event_id','both_event_ids','ordinary_id',
    'predicate_status','scalar_value','source_resolution','prior_reason','final_status'))
def test_r2_projection_comparison_rejects_forged_identity_or_evidence(r2_projection_pair,fault):
    full,dated,bounds=deepcopy(r2_projection_pair)
    old=full._data['_gr03_population']['records'];new=dated._data['_gr03_population']['records']
    old_event=next(r for r in old if not r['ordinary'] and r['predicate_report'] is not None)
    event=next(r for r in new if r['row_id']==old_event['row_id'])
    if fault=='full_event_id':old_event['predicate_report']['definition_id']=dated.granular_definition.identity
    elif fault=='dated_event_id':event['predicate_report']['definition_id']=full.granular_definition.identity
    elif fault=='both_event_ids':
        old_event['predicate_report']['definition_id']='f'*64
        event['predicate_report']['definition_id']='f'*64
    elif fault=='ordinary_id':
        control=next(r for r in new if r['ordinary'] and r['predicate_report'] is not None)
        control['predicate_report']['definition_id']=dated.granular_definition.identity
    elif fault=='predicate_status':event['predicate_report']['status']='forged_status'
    elif fault=='scalar_value':
        assert event['scalar_ledger']
        event['scalar_ledger'][0]['value']='forged_value'
    elif fault=='source_resolution':event['source_resolution']['status']='forged_source'
    elif fault=='prior_reason':event['anchor_range_check']['prior_reason']='forged_prior_reason'
    else:event['partition_reason']='forged_final_status'
    with pytest.raises(AssertionError):assert_projection(full,dated,bounds)


def test_r2_late_projection_preserves_complete_already_resolved_reports(base,r2_projection_pair,monkeypatch):
    import leonardo.analysis.pattern_refinement as module
    frozen=base[0];definition=r2_projection_pair[1].granular_definition
    original=module._grdate_apply;seen=[]
    def observed(records,samples,spec,request,checkpoint):
        before=deepcopy(records);sample_values=deepcopy(samples)
        result=original(records,samples,spec,request,checkpoint)
        assert spec==definition
        for prior,current in zip(before,records,strict=True):
            inside=spec.anchor_range.start_ms<=prior['anchor_ts_ms']<=spec.anchor_range.end_ms
            status_fields=('cohort','reason','partition','partition_reason')
            expected=deepcopy(prior)
            expected['anchor_range_check']=dict(in_range=inside,
                **{'prior_'+key:prior[key] for key in status_fields})
            if not inside:expected.update(cohort='excluded',reason='outside_anchor_range',
                partition='excluded',partition_reason='outside_anchor_range')
            assert current==expected
            assert current['predicate_report']==prior['predicate_report']
        expected_samples=[s for s in sample_values if spec.anchor_range.start_ms<=
            frozen._root['timestamps'][s['anchor']]<=spec.anchor_range.end_ms]
        assert result[0]==expected_samples and samples==sample_values
        seen.append((len(records),sum(r['predicate_report'] is not None for r in records)))
        return result
    monkeypatch.setattr(module,'_grdate_apply',observed)
    result=module.resolve_granular_population(frozen,definition)
    assert len(seen)==1 and seen[0][0]>0 and seen[0][1]>0
    assert result['samples']==r2_projection_pair[1].population_report()['samples']
