"""Task 1080: integration uses real saved sources and independent label enumeration."""
from copy import deepcopy
from dataclasses import fields, replace
from decimal import Decimal
import asyncio
import json

import pandas as pd
import pytest

from leonardo.analysis.pattern_models import PatternRefinement, PrecedingContextFilter, NumericCondition, PullbackFilter
from leonardo.analysis.refinement_models import GranularPredicate as P, GranularGroup as G, GranularRefinement as D
from leonardo.analysis.refinement_models import convert_legacy_refinement, summarize_granular_refinement
from leonardo.analysis.pattern_refinement import (
    pin_patterns, evaluate_patterns, evaluate_granular_patterns, search_granular_patterns,
    resolve_granular_population, validate_granular_definition, _gr03_charge,
)
from tests.analysis_test.test_granular_evidence import make_case, quantity, spec
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture, TOLERANT
from tests.analysis_test.test_trend_start_enrichment import movement
from leonardo.analysis.trend_start_patterns import run_study


@pytest.fixture(scope='module')
def genuine(tmp_path_factory):
    return make_case(tmp_path_factory.mktemp('granular_integration'))


@pytest.mark.parametrize('basis',('completed','formation','observed'))
@pytest.mark.parametrize('enabled',(False,True))
def test_explicit_conversion_preserves_exact_active_and_inactive_values(basis,enabled):
    old=PatternRefinement(basis=basis,preceding=PrecedingContextFilter(enabled,False,True,None,'NONE'),
        movement_enabled=enabled,movement=(NumericCondition('directional_move','pct',Decimal('1E-23'),Decimal('1E30')),NumericCondition('signed_move','points')),
        duration_enabled=enabled,duration=(NumericCondition('structural','minutes',Decimal('.00005')),),
        pullbacks=PullbackFilter(enabled,'internal_recovered',(NumericCondition('count','count',0),NumericCondition('depth','pct',0,statistic='mean'))))
    new=convert_legacy_refinement(old,comparison='other_families')
    assert [p.field for p in new.common[0].conditions]==['up','down','range','previous_direction','previous_family']
    assert [p.allowed for p in new.common[0].conditions]==[(False,),(True,),(),('NONE',),()]
    assert all(g.enabled==enabled for g in new.common+new.outcome)
    assert new.outcome[0].conditions[0].minimum==Decimal('1E-23') and new.outcome[0].conditions[1].minimum is None
    assert new.outcome[1].conditions[0].unit=='ms' and new.outcome[1].conditions[0].minimum==3
    assert new.outcome[2].conditions[0].minimum==0
    assert D.from_dict(new.to_dict())==new==convert_legacy_refinement(old,comparison='other_families')
    summary=summarize_granular_refinement(new)
    assert 'common:' in summary and 'outcome:' in summary
    if enabled:assert '1E-23' in summary and basis in summary


@pytest.mark.parametrize('comparison',('other_families','other_outcomes','non_start'))
@pytest.mark.parametrize('mirror',(False,True))
@pytest.mark.parametrize('mode',('directional_intensity','value','magnitude'))
def test_converted_population_and_full_frozen_counts_match_legacy(tmp_path,comparison,mirror,mode):
    frozen,*_=make_case(tmp_path,comparison=comparison,mirror=mirror,mode=mode)
    refinement=movement(minimum=15)
    legacy=evaluate_patterns(frozen,refinement)
    definition=convert_legacy_refinement(refinement,comparison=comparison)
    current=evaluate_granular_patterns(frozen,definition,parent=legacy)
    assert current.parent_id==legacy.evaluation_id
    pd.testing.assert_frame_equal(legacy.frame('patterns'),current.frame('patterns'))
    for before,after in zip(legacy._data['samples'],current._data['samples'],strict=True):assert before==after
    report=current.population_report()
    assert report==resolve_granular_population(frozen,definition)
    assert current.frame('population').event_id.tolist()==[r['row_id'] for r in report['records']]
    for pattern in frozen.patterns:
        for cohort in ('target','comparison'):
            pd.testing.assert_frame_equal(current.pattern_matches(pattern.pattern_id,cohort),legacy.pattern_matches(pattern.pattern_id,cohort))


def independently_count(result,pattern):
    """Enumerate supplied labels and coverage; no production matcher/count helpers."""
    data=result._data
    totals={prefix:dict(total=0,assessable=0,matched=0,exact_matched=0,ready_assessable=0,ready_matched=0)
        for prefix in ('','comparison_','later_','later_comparison_')}
    for sample in result.population_report()['samples']:
        if sample['partition']=='excluded':continue
        prefix=('later_' if sample['partition']=='later' else '')+('comparison_' if sample['cohort']=='comparison' else '')
        count=totals[prefix];count['total']+=1
        values=[];ready=True
        for term in pattern.terms:
            a=sample['anchor'];i=a+term.offset
            if not (0<=i<len(data['timestamps']) and data['coverage'][a] and data['coverage'][i] and data['breaks'][a]==data['breaks'][i]):break
            if sample['ordinary'] and data['control_uncovered'][a+1]!=data['control_uncovered'][i]:break
            column=data['columns'][term.column]
            frame=column['frame'];field='bin_label' if column['measurement']=='directional_intensity' else 'band'
            raw=frame.iloc[i][field]
            if pd.isna(raw):break
            values.append(str(raw));ready=ready and bool(column['ready'][i])
        if len(values)!=len(pattern.terms):continue
        count['assessable']+=1
        hit=all(v in t.allowed for v,t in zip(values,pattern.terms,strict=True))
        exact=all(v==t.center for v,t in zip(values,pattern.terms,strict=True))
        count['matched']+=hit;count['exact_matched']+=exact
        count['ready_assessable']+=ready and sample['timing'];count['ready_matched']+=hit and ready and sample['timing']
    return totals


@pytest.mark.parametrize('mirror',(False,True))
@pytest.mark.parametrize('mode,radius',(('directional_intensity',0),('directional_intensity',1),('value',0),('magnitude',0)))
def test_independent_label_counts_all_periods_and_tolerance(tmp_path,mirror,mode,radius):
    parent,cat,axis,request,*_=planted_fixture(tmp_path,mirror=mirror,measurement=mode,radius=radius,planted=TOLERANT)
    request=replace(request,pre_event=replace(request.pre_event,chronological=True,split_ms=axis[len(axis)//2]))
    study=run_study(parent,cat,request,axis)
    frozen=pin_patterns(parent,cat,study,study.frame('patterns').pattern_id.tolist()[::5][:15])
    result=evaluate_granular_patterns(frozen,D())
    rows=result.frame('patterns').set_index('pattern_id')
    for pattern in frozen.patterns:
        for prefix,counts in independently_count(result,pattern).items():
            for key,count in counts.items():assert rows.loc[pattern.pattern_id,prefix+key]==count
            expected=counts['matched']/counts['assessable'] if counts['assessable'] else None
            actual=rows.loc[pattern.pattern_id,prefix+'frequency']
            assert pd.isna(actual) if expected is None else actual==expected


def test_shared_matcher_purity_and_exact_budget(genuine,monkeypatch):
    import leonardo.analysis.pattern_refinement as engine
    import leonardo.analysis.pre_event_patterns as patterns
    frozen=genuine[0];calls=[];original=engine.resolve_granular_population
    def tracked(*a,**kw):calls.append(True);return original(*a,**kw)
    monkeypatch.setattr(engine,'resolve_granular_population',tracked)
    def forbidden(*a,**kw):pytest.fail('evaluation attempted discovery')
    monkeypatch.setattr(patterns,'mine',forbidden);monkeypatch.setattr(patterns,'terms_for_column',forbidden)
    result=evaluate_granular_patterns(frozen,D())
    assert len(calls)==1
    context=json.loads(result.context);charge=context['retained_total_bytes']
    equal=evaluate_granular_patterns(frozen,D(),memory_limit_bytes=charge)
    pd.testing.assert_frame_equal(result.frame('patterns'),equal.frame('patterns'))
    with pytest.raises(ValueError,match='limit'):evaluate_granular_patterns(frozen,D(),memory_limit_bytes=charge-1)
    assert evaluate_granular_patterns(frozen,D()).evaluation_id==result.evaluation_id


def test_search_repin_full_root_and_zero_rules(genuine):
    frozen,parent,cat,*_=genuine
    definition=spec(quantity(minimum=15))
    result=search_granular_patterns(frozen,parent,cat,definition,parent_id=frozen.source_discovery_id)
    assert not result.frame('patterns').empty and result.granular_definition==definition
    repin=pin_patterns(parent,cat,result,result.frame('patterns').pattern_id.tolist()[:12])
    assert repin.granular_definition==definition and repin.root_id!=frozen.root_id
    same=evaluate_granular_patterns(repin,definition)
    old=result.frame('patterns').set_index('pattern_id');new=same.frame('patterns').set_index('pattern_id')
    shared=[k for k in new if k in old]
    pd.testing.assert_frame_equal(new[shared],old.loc[new.index,shared])
    reset=evaluate_granular_patterns(repin,D(),parent=same)
    assert reset.population_report()['summary']['target_total']>same.population_report()['summary']['target_total']
    zero=evaluate_granular_patterns(repin,spec(quantity(minimum=9999)),parent=reset)
    assert zero.frame('patterns').pattern_id.tolist()==[p.pattern_id for p in repin.patterns]
    assert zero.frame('patterns').matched.eq(0).all()


@pytest.mark.parametrize('fault',('missing_definition','changed_definition','population','samples','stamp','atom','mask','context','profile','column','catalogue','missing_source_stamp'))
def test_granular_discovery_binding_rejects_substitutions(genuine,fault):
    frozen,parent,cat,*_=deepcopy(genuine)
    definition=spec(quantity(minimum=0))
    result=search_granular_patterns(frozen,parent,cat,definition,parent_id=frozen.source_discovery_id)
    ids=result.frame('patterns').pattern_id.tolist()[:2]
    if fault=='missing_definition':result._data.pop('_gr03_definition')
    elif fault=='changed_definition':result._data['_gr03_definition']=D()
    elif fault=='population':result._data['_gr03_population']['records'][0]['reason']='changed'
    elif fault=='samples':result._data['samples']=[]
    elif fault=='stamp':result._data['_gr03_discovery_binding']='changed'
    elif fault=='atom':result._data['patterns'][ids[0]]['indices']=(999999,)
    elif fault=='mask':result._data['patterns'][ids[0]]['masks']=(0,0,0,0)
    elif fault=='context':result=replace(result,context=json.dumps({**json.loads(result.context),'definition_id':'changed'}))
    elif fault=='profile':
        column=parent.columns[0];profile=replace(column.profile,context=replace(column.profile.context,unit='changed'))
        parent=replace(parent,columns=(replace(column,profile=profile),*parent.columns[1:]))
    elif fault=='column':parent.columns[-1]._frame.loc[0,'bin_label']='changed'
    elif fault=='catalogue':
        payload=cat.to_dict();payload['instances'][0]['control_coverage']=[];cat=replace(cat,_json=json.dumps(payload))
    else:result._data.pop('_pin_source_binding')
    with pytest.raises((TypeError,ValueError)):pin_patterns(parent,cat,result,ids)


def test_accessors_context_detach_and_control_membership(genuine,tmp_path):
    frozen=genuine[0];context=frozen.filter_context();context['columns'].clear()
    assert frozen.filter_context()['columns']
    legacy=evaluate_patterns(frozen,PatternRefinement())
    assert legacy.granular_definition is None
    with pytest.raises(ValueError):legacy.population_report()
    control,*_=make_case(tmp_path,comparison='non_start')
    pid=control._root['columns']['delta']['profile_id']
    definition=D(common=(G(conditions=(P('column','raw_value','native',column='delta',profile_id=pid,offset=-1,minimum=9999),)),))
    current=evaluate_granular_patterns(control,definition)
    record=next(r for r in current.population_report()['records'] if r['ordinary'])
    assert record['cohort']=='excluded'
    assert current.evidence(record['row_id'])['granular_population_record']==record
    assert not current.event_window(record['row_id']).empty
    record['reason']='tampered'
    assert current.population_record(record['row_id'])['reason']!='tampered'
    for bad in (1,None,False):
        with pytest.raises(TypeError):current.population_record(bad)
    for bad in ('control:1','unknown'):
        with pytest.raises(KeyError):current.evidence(bad)
    assert [f.name for f in fields(type(current))]==['root_id','set_id','evaluation_id','parent_id','request','context','_tables','_data']


def test_cancellation_retry_and_empty_search_inspection(genuine):
    frozen,parent,cat,*_=genuine;before=deepcopy(frozen.metadata())
    calls=[]
    def cancel():
        calls.append(True)
        if len(calls)==8:raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):evaluate_granular_patterns(frozen,D(),checkpoint=cancel)
    assert frozen.metadata()==before
    result=search_granular_patterns(frozen,parent,cat,spec(quantity(minimum=99999)),parent_id=frozen.source_discovery_id)
    assert result.frame('patterns').empty and not result.frame('population').empty
    with pytest.raises(ValueError):pin_patterns(parent,cat,result,[])
    assert evaluate_granular_patterns(frozen,D()).frame('patterns').matched.gt(0).any()


def test_maximum_legacy_conversion_and_rejections():
    from leonardo.analysis.pattern_models import MOVEMENT_FIELDS,DURATION_FIELDS
    old=PatternRefinement(preceding=PrecedingContextFilter(True,False,True,False,'DOWN','DOWN/PTPT/3,1,2,0'),
        movement_enabled=True,movement=tuple(NumericCondition(f,u,0) for f in MOVEMENT_FIELDS for u in ('points','pct')),
        duration_enabled=True,duration=tuple(NumericCondition(f,u,0) for f in DURATION_FIELDS for u in ('bars','ms') if (f,u)!=('confirmation_delay','bars')),
        pullbacks=PullbackFilter(True,'internal_recovered',(NumericCondition('count','count',0),
            *(NumericCondition(f,u,0,statistic=s) for f,units in (('depth',('points','pct')),('recovered_duration',('bars','ms'))) for u in units for s in ('mean','maximum')))))
    converted=convert_legacy_refinement(old,comparison='other_outcomes')
    assert converted.active_count==31 and [len(g.conditions) for g in converted.common+converted.outcome]==[5,10,7,9]
    for bad in (None,{},D()):
        with pytest.raises(TypeError):convert_legacy_refinement(bad,comparison='other_families')
    with pytest.raises(ValueError):convert_legacy_refinement(old,comparison='non_start')
    with pytest.raises(ValueError):convert_legacy_refinement(PatternRefinement(),comparison='other_outcomes')
    with pytest.raises(ValueError):convert_legacy_refinement(old,comparison='unknown')


def test_hand_counted_nine_event_contrast_and_missing_outcome():
    from leonardo.analysis.refinement_models import ResolvedFilterValue
    from leonardo.analysis.pattern_refinement import evaluate_granular_predicates,_granular_assign
    vectors=(('E1',True,4,20),('E2',True,3,40),('E3',True,-1,18),('E4',True,1.5,22),
        ('E5',False,4,20),('E6',False,.2,16),('E7',False,1,70),('E8',False,-2,25),('E9',True,None,20))
    outcome=quantity(unit='pct',minimum=3);common=quantity('duration','structural','bars',minimum=12,maximum=30)
    for definition,expected in ((spec(outcome),(2,1,2,3)),(spec(outcome,common=(G(conditions=(common,)),)),(1,1,2,2))):
        cells=[0,0,0,0];excluded=[]
        for identity,match,move,bars in vectors:
            values={outcome.measurement_key:ResolvedFilterValue(move) if move is not None else ResolvedFilterValue(unavailable_reason='saved_metric_missing'),
                common.measurement_key:ResolvedFilterValue(bars)}
            report=evaluate_granular_predicates(definition,values);cohort,_=_granular_assign('other_outcomes',False,True,report)
            if cohort=='excluded':excluded.append(identity);continue
            cells[(0 if cohort=='target' else 2)+(0 if match else 1)]+=1
        assert tuple(cells)==expected and 'E9' in excluded
        contrast=100*(cells[0]/sum(cells[:2])-cells[2]/sum(cells[2:]))
        assert contrast==pytest.approx(80/3 if not definition.common else 0)


def test_reordering_canonical_definitions_and_actual_mixed_parent(genuine):
    frozen=genuine[0]
    a=quantity(minimum=0);b=quantity('duration','structural','seconds',minimum=1)
    same=replace(b,unit='ms',minimum=1000)
    assert spec(b).identity==spec(same).identity
    first=evaluate_granular_patterns(frozen,spec(a,b))
    reordered=evaluate_granular_patterns(frozen,spec(b,a),parent=first)
    assert first.granular_definition.identity!=reordered.granular_definition.identity
    pd.testing.assert_frame_equal(first.frame('patterns'),reordered.frame('patterns'))
    assert first.population_report()['samples']==reordered.population_report()['samples']
    simple=evaluate_patterns(frozen,PatternRefinement(),parent=reordered)
    assert simple.parent_id==reordered.evaluation_id
    with pytest.raises(ValueError):evaluate_granular_patterns(frozen,D(),parent=replace(first,set_id='foreign'))


def test_rule_missingness_remains_inside_population(tmp_path):
    def missing(parent,cat,axis,request,*_):
        for column in parent.columns:
            for offset in request.pre_event.offsets:column._frame.loc[7+offset,'bin_label']=None
        return parent,cat,axis,request
    frozen,*_=make_case(tmp_path,transform=missing)
    result=evaluate_granular_patterns(frozen,D())
    member=next(r for r in result.population_report()['records'] if r['anchor']==7)
    assert member['cohort']=='target'
    for pattern in frozen.patterns:
        occurrence=result.pattern_matches(pattern.pattern_id)
        assert not occurrence.set_index('event_id').loc[member['row_id'],'assessable']


def test_search_calls_single_accepted_resolver_and_miner(genuine,monkeypatch):
    import leonardo.analysis.pattern_refinement as engine
    import leonardo.analysis.pre_event_patterns as mining
    import leonardo.analysis.service as service
    frozen,parent,cat,*_=genuine;calls=[]
    resolver=engine.resolve_granular_population;miner=mining.mine
    def resolve(*a,**kw):calls.append('resolve');return resolver(*a,**kw)
    def mine(*a,**kw):calls.append('mine');return miner(*a,**kw)
    monkeypatch.setattr(engine,'resolve_granular_population',resolve);monkeypatch.setattr(mining,'mine',mine)
    for name in ('fit_directional_binning','classify_directional_binning','fit_dynamic_binning','classify_dynamic_binning'):
        monkeypatch.setattr(service,name,lambda *a,**kw:pytest.fail('refit/classification during search'))
    current=search_granular_patterns(frozen,parent,cat,D(),parent_id=frozen.source_discovery_id)
    assert calls==['resolve','mine'] and not current.frame('patterns').empty
    old=replace(frozen,_root={k:v for k,v in frozen._root.items() if k!='_gr03_source_binding'})
    with pytest.raises(ValueError,match='repin'):search_granular_patterns(old,parent,cat,D(),parent_id=frozen.source_discovery_id)
    assert not evaluate_patterns(old,PatternRefinement()).frame('patterns').empty


@pytest.mark.parametrize('component',('populations','timing_mask','controls'))
def test_discovery_population_mask_and_cohort_tampering(genuine,component):
    frozen,parent,cat,*_=genuine
    result=search_granular_patterns(frozen,parent,cat,D(),parent_id=frozen.source_discovery_id)
    result._data[component]={'':0} if component=='populations' else 0 if component=='timing_mask' else ()
    with pytest.raises(ValueError):pin_patterns(parent,cat,result,result.frame('patterns').pattern_id.tolist()[:2])


def test_later_labels_do_not_choose_discovery_rules(tmp_path):
    parent,cat,axis,request,*_=planted_fixture(tmp_path)
    request=replace(request,pre_event=replace(request.pre_event,chronological=True,split_ms=axis[len(axis)//2]))
    outputs=[]
    for altered in (False,True):
        source=deepcopy(parent)
        if altered:
            for col in source.columns:col._frame.loc[col._frame.ts_ms>=request.pre_event.split_ms,'bin_label']='P10'
        original=run_study(source,cat,request,axis)
        frozen=pin_patterns(source,cat,original,original.frame('patterns').pattern_id.tolist()[:3])
        output=search_granular_patterns(frozen,source,cat,D(),parent_id=frozen.source_discovery_id)
        columns=['pattern_id','condition','matched','assessable','comparison_matched','comparison_assessable','rank_eligible','rank_reason','difference_pp']
        outputs.append(output.frame('patterns')[columns])
    pd.testing.assert_frame_equal(*outputs)


# Task 1080 R2: authoritative row-kind projection, with original tests preserved.
@pytest.mark.parametrize('mirror',(False,True),ids=('UP','DOWN'))
def test_r2_ordinary_exclusions_mixed_parents_and_granular_source(tmp_path,mirror):
    frozen,parent,catalogue,axis,request=make_case(tmp_path,comparison='non_start',mirror=mirror)
    pid=frozen._root['columns']['delta']['profile_id']
    condition=P('column','raw_value','native',column='delta',profile_id=pid,offset=-1,minimum=9999)
    restriction=D(common=(G(conditions=(condition,)),))
    baseline=evaluate_granular_patterns(frozen,D())
    excluded=evaluate_granular_patterns(frozen,restriction,parent=baseline)
    controls={r['row_id'] for r in excluded.population_report()['records'] if r['ordinary']}
    transitions=excluded.frame('population_changes').set_index('event_id').loc[sorted(controls)]
    transitioned=transitions[(transitions.parent_cohort=='comparison')&(transitions.current_cohort=='excluded')]
    assert len(transitioned)==269 and transitioned.ordinary.eq(True).all()
    assert transitioned.change.eq('excluded').all()
    assert excluded.frame('patterns').comparison_total.eq(0).all()
    assert excluded.frame('patterns').matched.eq(0).all()
    assert excluded.population_report()==resolve_granular_population(frozen,restriction)
    repeated=evaluate_granular_patterns(frozen,restriction,parent=excluded)
    again=repeated.frame('population_changes').set_index('event_id').loc[sorted(controls)]
    assert again.ordinary.eq(True).all() and again.change.eq('unchanged').all()
    restored=evaluate_granular_patterns(frozen,D(),parent=excluded)
    entered=restored.frame('population_changes').set_index('event_id').loc[transitioned.index]
    assert entered.change.eq('included').all() and entered.ordinary.eq(True).all()
    pd.testing.assert_frame_equal(restored.frame('patterns'),baseline.frame('patterns'))
    simple=evaluate_patterns(frozen,request.refinement)
    mixed=evaluate_granular_patterns(frozen,restriction,parent=simple)
    back=evaluate_patterns(frozen,request.refinement,parent=excluded)
    assert mixed.parent_id==simple.evaluation_id and back.parent_id==excluded.evaluation_id
    assert mixed.frame('population_changes').set_index('event_id').loc[transitioned.index].ordinary.eq(True).all()
    assert back.frame('population_changes').set_index('event_id').loc[transitioned.index].ordinary.eq(True).all()
    pd.testing.assert_frame_equal(simple.frame('patterns'),back.frame('patterns'))
    for result in (excluded,repeated,mixed):
        events={r['row_id'] for r in result.population_report()['records'] if not r['ordinary']}
        assert events
        assert result.frame('population_changes').set_index('event_id').loc[sorted(events)].ordinary.eq(False).all()
    narrow=D(common=(G(conditions=(replace(condition,offset=-4,minimum=2,maximum=8),)),))
    found=search_granular_patterns(frozen,parent,catalogue,narrow,parent_id=baseline.evaluation_id)
    assert not found.frame('patterns').empty
    repin=pin_patterns(parent,catalogue,found,found.frame('patterns').pattern_id.tolist()[:4])
    source_controls={r['row_id'] for r in repin._root['_gr03_population']['records'] if r['ordinary'] and r['cohort']=='excluded'}
    assert source_controls
    source_simple=evaluate_patterns(repin,request.refinement)
    source_same=evaluate_granular_patterns(repin,narrow)
    for result in (source_simple,source_same):
        assert result.parent_id==repin.source_discovery_id
        rows=result.frame('population_changes').set_index('event_id').loc[sorted(source_controls)]
        assert rows.ordinary.eq(True).all()
    assert source_same.frame('population_changes').set_index('event_id').loc[sorted(source_controls)].change.eq('unchanged').all()
    pd.testing.assert_frame_equal(simple.frame('patterns'),evaluate_patterns(frozen,request.refinement).frame('patterns'))


def test_r2_status_projection_is_optional_pure_and_uses_recorded_type():
    from leonardo.analysis.pattern_refinement import _statuses as _r2_statuses
    assignments=[dict(event_id='ordinary-looking-event',anchor_ts_ms=10,cohort='excluded',partition='excluded',reason='filter',partition_reason='not_in_cohort'),
        dict(event_id='not-a-control-prefix',anchor_ts_ms=20,cohort='excluded',partition='excluded',reason='filter',partition_reason='not_in_cohort')]
    samples=[dict(event_id='ordinary-looking-event',anchor=0,ordinary=True,cohort='comparison',partition='discovery',partition_reason='ok')]
    population={'records':[{'row_id':'ordinary-looking-event','ordinary':False},{'row_id':'not-a-control-prefix','ordinary':True},{'row_id':'absent','ordinary':True}]}
    original=deepcopy((assignments,samples,population))
    old=_r2_statuses(assignments,samples,[10,20])
    assert old==_r2_statuses(assignments,samples,[10,20],population=None)
    expected=deepcopy(old);expected['ordinary-looking-event']['ordinary']=False;expected['not-a-control-prefix']['ordinary']=True
    assert _r2_statuses(assignments,samples,[10,20],population=population)==expected
    assert (assignments,samples,population)==original and 'absent' not in expected
    from leonardo.analysis.pattern_refinement import _changes as _r2_changes
    row=expected['not-a-control-prefix'];included=dict(row,cohort='comparison')
    assert _r2_changes({}, {'x':included})[0]['change']=='included'
    assert _r2_changes({'x':included},{})[0]['change']=='excluded'
    assert _r2_changes({'x':row},{'x':row})[0]['change']=='unchanged'
