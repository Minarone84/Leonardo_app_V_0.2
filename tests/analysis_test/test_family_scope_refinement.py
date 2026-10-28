"""Family membership changes preserve the saved source and frozen rule meanings."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json

import pandas as pd
import pytest

from leonardo.analysis.pattern_models import FamilyScope, PatternRefinement, _gr05_resolve_scope, _gr05_resolve_selection
from leonardo.analysis.refinement_models import GranularRefinement as D, GranularGroup as G, GranularPredicate as P, convert_legacy_refinement, _plain
from leonardo.analysis.pattern_refinement import (pin_patterns, evaluate_patterns, evaluate_granular_patterns,
    resolve_granular_population, search_granular_patterns, _gr05_search_family_patterns, _gr05_family_population)
from leonardo.analysis.pre_event_cohorts import _gr05_family_universe
from leonardo.analysis.trend_start_patterns import run_study
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture
from tests.analysis_test.test_trend_start_enrichment import ENDED, movement
from tests.financial_tools_test.test_utc_classification import CASES

A, B, C = 'UP/TPP/0,1,2', 'UP/TPPP/0,1,1,2', 'UP/TPPP/0,2,1,3'


def multi_case(path, *, mirror=False, mode='directional_intensity', comparison='other_families', scope=None, origin=None, chronological=False):
    parent, cat, axis, request, *_ = planted_fixture(path, sequences=CASES+(ENDED,)*4, mirror=mirror, measurement=mode)
    universe = _gr05_family_universe(cat.instance('logical')['events'], event_kind=request.event_kind, start_ms=request.start_ms, end_ms=request.end_ms)
    assert len(universe) >= 3
    scope = scope or FamilyScope('selected', universe[:2])
    refinement = movement(minimum=0) if comparison == 'other_outcomes' else PatternRefinement()
    request = replace(request, family=None, comparison=comparison, origin=origin, min_matches=1,
        refinement=replace(refinement, family_scope=scope),
        pre_event=replace(request.pre_event, history=4, chronological=chronological,
            split_ms=axis[len(axis)//2] if chronological else None))
    study = run_study(parent, cat, request, axis)
    return parent, cat, axis, request, study, universe


@pytest.fixture(scope='module', params=[(m,d) for m in ('directional_intensity','value','magnitude') for d in (False,True)])
def source(request, tmp_path_factory):
    mode, mirror = request.param
    return multi_case(tmp_path_factory.mktemp('gr05'), mode=mode, mirror=mirror)


@pytest.mark.parametrize('mode,members', [('exact',[A]),('selected',[B,A]),('all',[])])
def test_scope_is_canonical_detached_and_strict(mode,members):
    value=FamilyScope(mode,members); snapshot=value.to_dict(); members.append(C)
    assert value.to_dict()==snapshot and FamilyScope.from_dict(snapshot)==value
    assert tuple(sorted(value.families))==value.families
    assert PatternRefinement(family_scope=value).active is False
    assert not D(family_scope=value).active and D(family_scope=value).active_count==0
    for altered in ({**snapshot,'extra':1},{**snapshot,'kind':'wrong'},{k:v for k,v in snapshot.items() if k!='families'}):
        with pytest.raises((ValueError,TypeError)): FamilyScope.from_dict(altered)


@pytest.mark.parametrize('mode,members', [('exact',[]),('exact',[A,B]),('selected',[]),('all',[A]),('unknown',[A]),
    ('selected',[A,A]),('selected',[A,'DOWN/PT/1,0']),('selected',['UP/PT/1,0']),('selected',['UP/TPT/0,1']),
    ('selected',[' UP/TP/0,1']),('selected',[True]),('selected',{A}),('selected',A)])
def test_invalid_scope_shapes(mode,members):
    with pytest.raises((ValueError,TypeError)): FamilyScope(mode,members)


@pytest.mark.parametrize('scope', [FamilyScope('all'),FamilyScope('selected',[A,B,C]),FamilyScope('exact',['UP/TP/0,1']),FamilyScope('exact',['DOWN/PT/1,0'])])
def test_source_membership_and_empty_complement(scope):
    with pytest.raises(ValueError):
        _gr05_resolve_selection(scope,source_selection=None,universe=[A,B,C],direction='UP',comparison='other_families')


def test_singleton_complement_and_schema_identity():
    descriptor=_gr05_resolve_selection(FamilyScope('selected',[A]),source_selection=None,universe=[A],direction='UP',comparison='other_families')
    assert descriptor['comparison_families']==[]
    assert D(family_scope=FamilyScope('selected',[A,B])).identity==D(family_scope=FamilyScope('selected',[B,A])).identity
    old=PatternRefinement(); assert 'family_scope' not in old.to_dict() and 'family_scope' not in _plain(old)
    plain=D(); assert plain.to_dict()=={'kind':'gr03-filter-spec-v1','common':[],'outcome':[]}
    assert 'family_scope' not in _plain(plain)
    horizon=P('horizon','terminal_directional','pct',horizon_bars=6,minimum=0)
    for definition in (plain,D(outcome=(G(conditions=(horizon,)),)),D(family_scope=FamilyScope('selected',[A,B]),outcome=(G(conditions=(horizon,)),))):
        assert D.from_dict(definition.to_dict())==definition
    scoped=D(family_scope=FamilyScope('all')).to_dict()
    for value in ({**scoped,'family_scope':None},{k:v for k,v in scoped.items() if k!='family_scope'},
                  {**scoped,'kind':'gr03-filter-spec-v1'},{**scoped,'extra':False}):
        with pytest.raises((TypeError,ValueError)):D.from_dict(value)
    assert convert_legacy_refinement(PatternRefinement(family_scope=FamilyScope('all')),comparison='recurrence').family_scope==FamilyScope('all')


def test_pool_is_one_miner_call_and_overview_remains_separate(source,monkeypatch):
    parent,cat,axis,request,study,universe=source
    import leonardo.analysis.pre_event_patterns as module
    original=module.mine;calls=[]
    def counted(*args,**kw):calls.append([s['event_id'] for s in args[0]['samples']]);return original(*args,**kw)
    monkeypatch.setattr(module,'mine',counted)
    pooled=run_study(parent,cat,request,axis)
    assert len(calls)==1 and len(calls[0])==len(set(calls[0]))
    assert pooled.frame('patterns').equals(study.frame('patterns'))
    overview=run_study(parent,cat,replace(request,refinement=PatternRefinement()),axis)
    assert overview.frame('patterns').empty and 'family_scope' not in json.loads(overview.context)
    with pytest.raises(ValueError):pin_patterns(parent,cat,overview,['absent'])
    with pytest.raises(ValueError):replace(request,pre_event=None)


def test_exact_and_selected_singleton_numerical_parity(source):
    parent,cat,axis,request,_,universe=source
    old=replace(request,family=universe[0],refinement=PatternRefinement())
    studies=[run_study(parent,cat,r,axis) for r in (old,replace(old,family=None,refinement=PatternRefinement(family_scope=FamilyScope('exact',[universe[0]]))),
        replace(old,refinement=PatternRefinement(family_scope=FamilyScope('selected',[universe[0]]))))]
    for study in studies[1:]:
        pd.testing.assert_frame_equal(studies[0].frame('patterns'),study.frame('patterns'),check_exact=True)
        assert studies[0]._data['samples']==study._data['samples']


def test_frozen_scope_widening_defaults_and_numerical_oracle(source,monkeypatch):
    parent,cat,axis,request,study,universe=source
    ids=study.frame('patterns').pattern_id.tolist()[:8]
    frozen=pin_patterns(parent,cat,study,ids)
    import leonardo.analysis.pre_event_patterns as mining
    monkeypatch.setattr(mining,'mine',lambda *a,**k:pytest.fail('fixed evaluation must not mine'))
    pooled=evaluate_patterns(frozen,request.refinement)
    narrow=evaluate_patterns(frozen,PatternRefinement(family_scope=FamilyScope('exact',[universe[0]])),parent=pooled)
    inherited=evaluate_patterns(frozen,PatternRefinement(),parent=narrow)
    assert inherited._data['samples']==pooled._data['samples']
    assert inherited.frame('patterns').pattern_id.tolist()==ids
    all_members=universe[:-1]
    wide=evaluate_patterns(frozen,PatternRefinement(family_scope=FamilyScope('selected',all_members)),parent=narrow)
    assert len([s for s in wide._data['samples'] if s['cohort']=='target']) >= len([s for s in pooled._data['samples'] if s['cohort']=='target'])
    for result in (pooled,narrow,inherited,wide):
        count_oracle(result,frozen)
        family=result.frame('family_population')
        assert set(family.family)==set(universe)
        assert all(family.candidate_rows==family.target+family.comparison+family.cohort_excluded)
        for cohort in ('target','comparison'):
            assert all(family[cohort]==family[cohort+'_discovery']+family[cohort+'_later']+family[cohort+'_chronology_excluded'])


def count_oracle(result,frozen):
    """Read literal cells and row paths, without calling production observe/mask/stats."""
    data=result._data
    for pattern in frozen.patterns:
        expectations={}
        for sample in data['samples']:
            anchor=sample['anchor'];tokens=[];valid=True
            for term in pattern.terms:
                position=anchor+term.offset
                if position<0 or position>=len(data['timestamps']):valid=False;break
                lo,hi=sorted((anchor,position))
                if not all(data['coverage'][lo:hi+1]) or data['breaks'][lo]!=data['breaks'][hi]:valid=False;break
                if sample['ordinary'] and data['control_uncovered'][hi+1]!=data['control_uncovered'][lo]:valid=False;break
                token=data['columns'][term.column]['tokens'][position]
                if token is None:valid=False;break
                tokens.append(token)
            hit=valid and all(v in t.allowed for v,t in zip(tokens,pattern.terms,strict=True))
            exact=valid and all(v==t.center for v,t in zip(tokens,pattern.terms,strict=True))
            expectations[sample['event_id']]=(valid,hit,exact)
        for cohort in ('target','comparison'):
            frame=result.pattern_matches(pattern.pattern_id,cohort)
            for row in frame.to_dict('records'):
                assert (row['assessable'],row['matched'],row['exact_match'])==expectations[row['event_id']]
            detail=json.loads(frame.attrs['pattern_detail']);breakdown=detail['family_breakdown']
            for partition in ('discovery','later','excluded'):
                selected=[s for s in data['samples'] if s['cohort']==cohort and s['partition']==partition]
                family_rows=[r for r in breakdown if r['cohort']==cohort and r['partition']==partition]
                assert sum(r['total'] for r in family_rows)==len(selected)
                assert sum(r['assessable'] for r in family_rows)==sum(expectations[s['event_id']][0] for s in selected)
                assert sum(r['matched'] for r in family_rows)==sum(expectations[s['event_id']][1] for s in selected)
                assert sum(r['exact_matched'] for r in family_rows)==sum(expectations[s['event_id']][2] for s in selected)
                for row in family_rows:
                    assert row['frequency']==(row['matched']/row['assessable'] if row['assessable'] else None)


@pytest.mark.parametrize('comparison',('other_families','other_outcomes','non_start','recurrence'))
@pytest.mark.parametrize('mirror',(False,True))
def test_granular_scopes_comparisons_and_search(tmp_path,comparison,mirror):
    parent,cat,axis,request,study,universe=multi_case(tmp_path,mirror=mirror,comparison=comparison,
        scope=FamilyScope('all') if comparison!='other_families' else None)
    assert not study.frame('patterns').empty
    frozen=pin_patterns(parent,cat,study,study.frame('patterns').pattern_id.tolist()[:6])
    column=frozen._root['columns']['delta']
    predicate=P('column','raw_value','native',column='delta',profile_id=column['profile_id'],offset=-1,minimum=1)
    definition=D(outcome=(G(conditions=(predicate,)),),family_scope=request.refinement.family_scope)
    result=evaluate_granular_patterns(frozen,definition)
    count_oracle(result,frozen)
    report=result.population_report();assert report['family_scope']==json.loads(result.context)['family_scope']
    rows=report['records'];assert len(rows)==len({r['row_id'] for r in rows})
    if comparison=='recurrence':
        assert not any(r['cohort']=='comparison' for r in rows)
        assert result.frame('patterns').comparison_frequency.isna().all()
        assert not result.frame('patterns').support_eligible.any()
    if comparison=='non_start':
        assert sum(r['ordinary'] for r in report['family_population'])==1
    discovered=search_granular_patterns(frozen,parent,cat,definition,parent_id=result.evaluation_id)
    assert discovered.frame('patterns').shape[0]>0
    pinned=pin_patterns(parent,cat,discovered,discovered.frame('patterns').pattern_id.tolist()[::3][:3])
    again=evaluate_granular_patterns(pinned,definition)
    for row in again.frame('patterns').to_dict('records'):
        original=discovered.frame('patterns').set_index('pattern_id').loc[row['pattern_id']]
        for name in ('matched','assessable','comparison_matched','comparison_assessable'):assert row[name]==original[name]


def test_origin_zero_and_chronology_rows_remain_visible(tmp_path):
    parent,cat,axis,request,study,universe=multi_case(tmp_path,comparison='recurrence',scope=FamilyScope('all'),origin='candidate_restart')
    assert set(study.frame('family_population').family)==set(universe)
    assert any(study.frame('family_population').candidate_rows==0)
    first_anchor=cat.instance('logical')['events'][0]['anchor_ts_ms']
    chronological=run_study(parent,cat,replace(request,origin=None,pre_event=replace(request.pre_event,chronological=True,split_ms=first_anchor+60_000)),axis)
    assert set(chronological.frame('family_population').family)==set(universe)
    assert sum(chronological.frame('family_population').target_chronology_excluded)>0


@pytest.mark.parametrize('field',('_gr05_scope','_gr05_discovery_binding','_gr05_family_population'))
def test_scoped_discovery_cannot_downgrade_or_tamper(source,field):
    parent,cat,_,_,study,_=source
    bad=deepcopy(study);bad._data.pop(field)
    with pytest.raises(ValueError):pin_patterns(parent,cat,bad,bad.frame('patterns').pattern_id.tolist()[:1])


def test_unequal_family_sizes_use_counts():
    from leonardo.analysis.pre_event_patterns import _gr05_family_breakdown
    scope=_gr05_resolve_selection(FamilyScope('all'),source_selection=None,universe=[A,B],direction='UP',comparison='recurrence')
    events={str(i):{'family':A if i==0 else B} for i in range(10)}
    samples=[dict(event_id=str(i),ordinary=False,cohort='target',partition='discovery') for i in range(10)]
    data=dict(_gr05_scope=scope,events=events,samples=samples,patterns={'rule':{'masks':(1023,1023,3,3)}},timing_mask=1023)
    rows=_gr05_family_breakdown(data,'rule',lambda:None)
    actual=[r for r in rows if r['cohort']=='target' and r['partition']=='discovery']
    assert [(r['matched'],r['assessable']) for r in actual]==[(1,1),(1,9)]
    assert Fraction(sum(r['matched'] for r in actual),sum(r['assessable'] for r in actual))==Fraction(1,5)
    assert sum(Fraction(r['matched'],r['assessable']) for r in actual)/2!=Fraction(1,5)


@pytest.mark.parametrize('question,selected,target,comparison,excluded',[
    ('other_families',(A,B),('A1','B1'),('C1',),('A2','A3','B2','B3','C2','C3')),
    ('other_outcomes',(A,B),('A1','B1'),('A2','B2'),('A3','B3','C1','C2','C3')),
    ('other_outcomes',(A,B,C),('A1','B1','C1'),('A2','B2','C2'),('A3','B3','C3')),
    ('recurrence',(A,B,C),('A1','B1','C1'),(),('A2','A3','B2','B3','C2','C3')),
    ('non_start',(A,B),('A1','B1'),('O1',),('A2','A3','B2','B3','C1','C2','C3','O2','O3')),
])
def test_issued_literal_status_populations(question,selected,target,comparison,excluded):
    """Task acceptance vectors, resolved statuses only, not claimed as market observations."""
    from leonardo.analysis.pattern_refinement import _granular_assign, evaluate_granular_predicates
    from leonardo.analysis.refinement_models import ResolvedFilterValue as V
    common=P('column','raw_value','native',column='common',profile_id='literal',offset=-1,minimum=1)
    outcome=P('column','raw_value','native',column='outcome',profile_id='literal',offset=-1,minimum=1)
    definition=D(common=(G(conditions=(common,)),),outcome=(G(conditions=(outcome,)),))
    scope=_gr05_resolve_selection(FamilyScope('selected',selected),source_selection=None,universe=[A,B,C],direction='UP',comparison=question)
    vectors=(('A1',A,True,1,1,True),('A2',A,True,1,0,True),('A3',A,True,0,1,False),
        ('B1',B,True,1,1,False),('B2',B,True,1,0,True),('B3',B,True,1,None,True),
        ('C1',C,True,1,1,True),('C2',C,True,1,0,False),('C3',C,False,1,1,True))
    if question=='non_start':vectors+=(('O1',None,True,1,None,True),('O2',None,True,0,None,False),('O3',None,True,None,None,False))
    result={k:[] for k in ('target','comparison','excluded')};matches={}
    for identity,family,mandatory,c,o,match in vectors:
        ordinary=family is None;same=ordinary or family in scope['selected_families'];cohort='excluded'
        if mandatory and (same or question=='other_families'):
            defined=D(common=definition.common) if ordinary else definition
            values={p.measurement_key:V(v) if v is not None else V(unavailable_reason='literal_unavailable') for p,v in ((common,c),(outcome,o))}
            report=evaluate_granular_predicates(defined,values)
            cohort,_=_granular_assign(question,ordinary,same,report)
        result[cohort].append(identity);matches[identity]=match
    assert result==dict(target=list(target),comparison=list(comparison),excluded=list(excluded))
    assert sum(matches[i] for i in target)==(2 if len(selected)==3 else 1)
    assert sum(matches[i] for i in comparison)==(2 if question=='other_outcomes' else 0 if question=='recurrence' else 1)


@pytest.mark.parametrize('mirror',(False,True))
def test_tolerant_pool_aliases_and_all_selected_rule_denominators(tmp_path,mirror):
    from tests.analysis_test.test_trend_start_enrichment import bundle_for
    from leonardo.analysis.trend_start_patterns import build_catalogue
    parent,cat,axis,request,store,manifest,bundle=planted_fixture(tmp_path,sequences=CASES+(ENDED,)*4,mirror=mirror,radius=1)
    # Repeat original exported records, preserving their calculated events.
    analysis=next(iter(bundle.to_dict()['reports'].values()))
    aliases=[('one',analysis,axis[0],axis[-1]),('alias',analysis,axis[0],axis[-1]),('one',analysis,axis[0],axis[-1])]
    aliased=build_catalogue(parent,bundle_for(parent,aliases),axis)
    assert {e['event_id'] for e in cat.instance('logical')['events']}=={e['event_id'] for e in aliased.instance('logical')['events']}
    cat=aliased
    universe=_gr05_family_universe(cat.instance('logical')['events'],event_kind=request.event_kind,start_ms=request.start_ms,end_ms=request.end_ms)
    request=replace(request,family=None,comparison='recurrence',min_matches=1,
        refinement=PatternRefinement(family_scope=FamilyScope('all')))
    study=run_study(parent,cat,request,axis);frozen=pin_patterns(parent,cat,study,study.frame('patterns').pattern_id[:8])
    result=evaluate_granular_patterns(frozen,D(family_scope=FamilyScope('all')))
    count_oracle(result,frozen)
    assert any(len(t.allowed)>1 for p in frozen.patterns for t in p.terms)
    assert len(result._data['samples'])==len({s['event_id'] for s in result._data['samples']})
    zero=evaluate_granular_patterns(frozen,D(outcome=(G(conditions=(P('column','raw_value','native',
        column='delta',profile_id=frozen._root['columns']['delta']['profile_id'],offset=-1,minimum=9999),)),)))
    assert tuple(zero.frame('patterns').pattern_id)==tuple(p.pattern_id for p in frozen.patterns)
    assert not zero.frame('patterns').matched.any()
    count_oracle(zero,frozen)


@pytest.mark.parametrize('fault',('context','selected','source_request','sample','assignment','table'))
def test_scope_membership_binding_rejects_detached_edits(tmp_path,fault):
    parent,cat,_,_,study,universe=multi_case(tmp_path)
    bad=deepcopy(study)
    if fault=='context':
        value=json.loads(bad.context);value.pop('family_scope');bad=replace(bad,context=json.dumps(value))
    elif fault=='selected':bad._data['_gr05_scope']['selected_families']=[universe[-1]]
    elif fault=='source_request':bad=replace(bad,request=replace(bad.request,refinement=PatternRefinement(family_scope=FamilyScope('exact',[universe[0]]))))
    elif fault=='sample':bad._data['samples'][0]['cohort']='comparison'
    elif fault=='assignment':
        bad=replace(bad,_tables=tuple((n,f.assign(cohort='excluded') if n=='cohort_assignments' else f) for n,f in bad._tables))
    else:bad=replace(bad,_tables=tuple((n,f.iloc[:0] if n=='family_population' else f) for n,f in bad._tables))
    with pytest.raises(ValueError):pin_patterns(parent,cat,bad,bad.frame('patterns').pattern_id[:1])


@pytest.mark.parametrize('mirror',(False,True))
def test_two_saved_versions_keep_the_existing_provider_authority(tmp_path,mirror):
    from tests.analysis_test.test_granular_evidence import append_case, quantity, spec
    frozen,parent,cat,axis,request=append_case(tmp_path,mirror=mirror)[1]
    selected=FamilyScope('exact',[request.family])
    original=resolve_granular_population(frozen,spec(quantity(basis='formation')))
    definition=replace(spec(quantity(basis='formation')),family_scope=selected)
    scoped=resolve_granular_population(frozen,definition)
    expected=deepcopy(original['records'])
    for row in expected:
        if row['predicate_report'] is not None:
            assert row['predicate_report']['definition_id']==spec(quantity(basis='formation')).identity
            row['predicate_report']['definition_id']=definition.identity
    assert expected==scoped['records']
    assert original['samples']==scoped['samples']
