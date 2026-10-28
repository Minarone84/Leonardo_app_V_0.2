"""GR06 independent counts, arithmetic, source and explicit omission evidence."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, getcontext, localcontext, Overflow
from fractions import Fraction
import json
from types import SimpleNamespace

import pytest

from leonardo.analysis.combination_explanations import (numeric_summary,inspect_combination,
    refinement_sensitivity,plan_filter_omissions,_block,_evaluation_digest)
from leonardo.analysis.refinement_models import (InspectionOptions,FilterOmission,GranularPredicate as P,
    GranularGroup as G,GranularRefinement as D,AnchorDateRange)
from leonardo.analysis.pattern_models import FamilyScope,PatternRefinement
from leonardo.analysis.pattern_refinement import pin_patterns,evaluate_patterns,evaluate_granular_patterns,search_granular_patterns
from tests.analysis_test.test_family_scope_refinement import multi_case
from tests.analysis_test.test_family_scope_application import revision_case


def rational_round(value, precision=50):
    """Independent integer rounding to significant digits, ties to even."""
    value=Fraction(value)
    if not value:return Decimal(0)
    sign=value<0;value=abs(value);n,d=value.numerator,value.denominator
    exponent=len(str(n))-len(str(d))
    power=Fraction(10**exponent) if exponent>=0 else Fraction(1,10**(-exponent))
    if value<power:exponent-=1
    shift=precision-1-exponent
    scaled=value*(10**shift) if shift>=0 else value/Fraction(10**(-shift))
    quotient,remainder=divmod(scaled.numerator,scaled.denominator)
    if 2*remainder>scaled.denominator or 2*remainder==scaled.denominator and quotient%2:quotient+=1
    return Decimal((int(sign),tuple(int(c) for c in str(quotient)),-shift))


def oracle_quantiles(values):
    ordered=sorted(Fraction(Decimal(v)) for v in values)
    if not ordered:return [None]*5
    result=[min(Decimal(v) for v in values)]
    for numerator in (1,2,3):
        i,r=divmod((len(ordered)-1)*numerator,4)
        if not r:result.append(sorted(Decimal(v) for v in values)[i])
        else:
            left=rational_round(ordered[i]*Fraction(4-r,4));right=rational_round(ordered[i+1]*Fraction(r,4))
            result.append(rational_round(Fraction(left)+Fraction(right)))
    return [*result,max(Decimal(v) for v in values)]


@pytest.mark.parametrize('values',[[],['7'],['0','10'],['1','2','4','8'],['-10','0','0','10','20'],
    ['-1e308','1e308'],['1e-300','2e-300','5e-300','9e-300'],['1.25','2.5','2.5','3.75'],
    ['-1e300','-3e-200','0','4e-200','1e300'],['1234567890123456789012345678901234567890123456789012345','2e55']])
def test_independent_stagewise_numeric_oracle(values):
    expected=oracle_quantiles(values)
    report=numeric_summary(values)
    assert report['available_count']==len(values)
    assert [None if report[k] is None else Decimal(report[k]) for k in ('min','q1','median','q3','max')]==expected
    assert report['precision']=='50-significant-digit interpolation'


def test_unavailable_values_and_caller_decimal_context_are_preserved():
    with localcontext() as context:
        context.prec=3;context.Emax=9;context.traps[Overflow]=True;context.clear_flags()
        before=context.copy()
        report=numeric_summary([True,None,'bad','NaN','Infinity',float('nan'),'1e300','-1e300'])
        assert report['available_count']==2 and report['unavailable_count']==6
        assert Decimal(report['median'])==0
        assert context.prec==before.prec and context.Emax==before.Emax and context.flags==before.flags and context.traps==before.traps


@pytest.mark.parametrize('bounds',[(100,109),(2**63-10,2**63-1),(0,0),(100,101),(100,102)])
def test_fixed_blocks_integer_oracle_and_empty_intervals(bounds):
    start,end=bounds;span=end-start+1
    groups=[(start+(i*span+3)//4,start+((i+1)*span+3)//4-1) for i in range(4)]
    for t in range(start,end+1):
        expected=next(i for i,(lo,hi) in enumerate(groups) if lo<=t<=hi)
        assert _block(t,start,end)==expected
    assert len(groups)==4


@pytest.fixture(scope='module',params=[(mode,mirror) for mode in ('directional_intensity','value','magnitude') for mirror in (False,True)])
def report_source(request,tmp_path_factory):
    mode,mirror=request.param
    parent,cat,axis,req,study,families=multi_case(tmp_path_factory.mktemp('gr06_labels'),mode=mode,mirror=mirror)
    ids=study.frame('patterns').pattern_id.tolist()
    assert ids
    frozen=pin_patterns(parent,cat,study,ids)
    return SimpleNamespace(parent=parent,cat=cat,axis=axis,request=req,study=study,frozen=frozen,families=families)


def direct_observations(result,rule):
    """Literal token/path oracle, independent of observe, masks, stats and report code."""
    data=result._data;rows={}
    for s in data['samples']:
        tokens=[];valid=True;ready=True
        for t in rule.terms:
            p=s['anchor']+t.offset
            if not 0<=p<len(data['timestamps']):valid=False;break
            lo,hi=sorted((p,s['anchor']))
            if not all(data['coverage'][lo:hi+1]) or data['breaks'][lo]!=data['breaks'][hi]:valid=False;break
            if s['ordinary'] and data['control_uncovered'][hi+1]!=data['control_uncovered'][lo]:valid=False;break
            token=data['columns'][t.column]['tokens'][p]
            if token is None:valid=False;break
            tokens.append(token);ready=ready and data['columns'][t.column]['ready'][p]
        matched=valid and all(x in t.allowed for x,t in zip(tokens,rule.terms,strict=True))
        exact=valid and all(x==t.center for x,t in zip(tokens,rule.terms,strict=True))
        rows[s['event_id']]=dict(cohort=s['cohort'],partition=s['partition'],assessable=valid,matched=matched,
            exact_matched=exact,added_by_tolerance=matched and not exact,ready_assessable=valid and ready and s['timing'],
            ready_matched=matched and ready and s['timing'])
    return rows


def support_ids(report,side,link):
    ids=[];offset=0
    while True:
        frame=report.ledger(dict(side=side,link=link),offset=offset)
        ids+=frame.row_id.tolist()
        if offset+50>=frame.attrs['support_set_total']:break
        offset+=50
    assert len(ids)==len(set(ids))
    return set(ids)


def test_every_pinned_rule_exact_counts_support_sets_and_no_mutation(report_source,monkeypatch):
    p=report_source
    from leonardo.analysis import pre_event_patterns as mining
    monkeypatch.setattr(mining,'mine',lambda *a,**k:pytest.fail('inspection must not mine'))
    before=_evaluation_digest(p.study)
    for rule in p.frozen.patterns:
        report=inspect_combination(p.frozen,p.study,p.study,None,rule.pattern_id,InspectionOptions())
        expected=direct_observations(p.study,rule)
        for row in report.frame('counts').to_dict('records'):
            if row['side']!='current':continue
            group={k:v for k,v in expected.items() if v['cohort']==row['cohort'] and
                (v['partition'] in ('discovery','later') if row['period']=='eligible_combined' else v['partition']==row['period'])}
            assert row['total']==len(group)
            assert support_ids(report,'current',row['total_rows'])==set(group)
            for field in ('assessable','matched','exact_matched','added_by_tolerance','ready_assessable','ready_matched'):
                ids={k for k,v in group.items() if v[field]}
                assert row[field]==len(ids)
                assert support_ids(report,'current',row[field+'_rows'])==ids
        assert report.header['rule']==[json.loads(json.dumps(t.to_dict())) for t in rule.terms]
        assert len(report.frame('rules'))==len(p.frozen.patterns)
    assert _evaluation_digest(p.study)==before


def test_actual_parent_zero_rules_retention_and_immutable_views(report_source):
    p=report_source
    first=evaluate_patterns(p.frozen,PatternRefinement())
    second=evaluate_granular_patterns(p.frozen,D(common=(G(conditions=(P('column','raw_value','native',
        column=p.request.columns[0],profile_id=p.frozen._root['columns'][p.request.columns[0]]['profile_id'],offset=-1,minimum=1000000),)),)),parent=first)
    rule=p.frozen.patterns[0]
    report=inspect_combination(p.frozen,p.study,second,first,rule.pattern_id,InspectionOptions())
    assert report.header['actual_parent_id']==first.evaluation_id
    assert report.frame('counts').query("side == 'current'").matched.eq(0).all()
    assert report.frame('retention').query("cohort == 'all'").retained_share.fillna(0).eq(0).all()
    copy=report.header;copy.clear();assert report.header['pattern_id']==rule.pattern_id
    frame=report.frame('counts');frame.iloc[0,0]='changed';assert report.frame('counts').iloc[0,0]!='changed'
    with pytest.raises(ValueError,match='parent'):inspect_combination(p.frozen,p.study,second,None,rule.pattern_id,InspectionOptions())
    with pytest.raises(ValueError,match='retained'):inspect_combination(p.frozen,p.study,second,first,'alien',InspectionOptions())


@pytest.mark.parametrize('bad',[True,None,'wrong',(),{'side':'alien'},{'period':'future'},{'block':4},{'ready_only':1},{'metric_status':'known'}])
def test_strict_ledger_selectors(report_source,bad):
    p=report_source;rule=p.frozen.patterns[0]
    report=inspect_combination(p.frozen,p.study,p.study,None,rule.pattern_id,InspectionOptions())
    with pytest.raises((ValueError,TypeError)):report.ledger(bad)


@pytest.mark.parametrize('option',[
    lambda:P('column','raw_value','native',column='foreign',offset=-1),
    lambda:P('column','raw_value','native',column='delta',profile_id='foreign',offset=-1),
    lambda:P('duration','observed_elapsed','bars',basis='formation')])
def test_invalid_extra_context_does_not_mutate_source(report_source,option):
    p=report_source;before=_evaluation_digest(p.study)
    with pytest.raises(ValueError):inspect_combination(p.frozen,p.study,p.study,None,p.frozen.patterns[0].pattern_id,InspectionOptions((option(),)))
    assert _evaluation_digest(p.study)==before


def test_measurement_only_denominators_and_budget(report_source):
    p=report_source;rule=p.frozen.patterns[0]
    before=_evaluation_digest(p.study)
    extra=P('horizon','terminal_directional','pct',horizon_bars=1000)
    report=inspect_combination(p.frozen,p.study,p.study,None,rule.pattern_id,InspectionOptions((extra,)))
    rows=report.frame('distributions')
    assert len(rows) and rows.values_summarized.eq(0).all()
    assert rows.base_selected.sum()>0 and rows.source_coherence_unavailable.sum()>0
    assert _evaluation_digest(p.study)==before
    with pytest.raises(ValueError,match='budget|limit|allowance'):
        inspect_combination(p.frozen,p.study,p.study,None,rule.pattern_id,InspectionOptions(),memory_limit_bytes=1)


@pytest.fixture(scope='module')
def calculated(tmp_path_factory):
    p=revision_case(tmp_path_factory.mktemp('gr06_actual'))
    rows=p.study.frame('patterns')
    candidates=[]
    for row in rows.to_dict('records'):
        terms=p.study._data['patterns'][row['pattern_id']]['terms']
        if len({t.column for t in terms})>1 and len({t.offset for t in terms})>1:candidates.append(row['pattern_id'])
    assert candidates
    ids=tuple(dict.fromkeys([candidates[0],*rows.pattern_id.tolist()[:5]]))
    p.frozen=pin_patterns(p.parent,p.catalogue,p.study,ids)
    p.rule=next(r for r in p.frozen.patterns if r.pattern_id==candidates[0])
    column=p.request.columns[0];profile=p.frozen._root['columns'][column]['profile_id']
    p.definition=D(common=(G('ANY',(P('column','raw_value','native',column=column,profile_id=profile,offset=-1,minimum=995),
        P('column','raw_value','native',column=column,profile_id=profile,offset=-1,maximum=985))),),
        outcome=(G(conditions=(P('horizon','terminal_directional','pct',horizon_bars=6,minimum=0),)),))
    p.current=evaluate_granular_patterns(p.frozen,p.definition)
    return p


def test_genuine_four_way_and_extra_timing_counts(calculated):
    p=calculated
    samples=p.current._data['samples']
    assert any(s['cohort']=='target' for s in samples) and any(s['cohort']=='comparison' for s in samples)
    before=_evaluation_digest(p.current)
    extra=P('horizon','terminal_signed','pct',horizon_bars=1000)
    report=inspect_combination(p.frozen,p.study,p.current,None,p.rule.pattern_id,InspectionOptions((extra,)))
    literal=direct_observations(p.current,p.rule)
    for row in report.frame('comparison').to_dict('records'):
        if row['side']!='current':continue
        selected={k:v for k,v in literal.items() if v['assessable'] and (not row['ready_only'] or v['ready_assessable'])
            and (v['partition'] in ('discovery','later') if row['period']=='eligible_combined' else v['partition']==row['period'])}
        matched='exact_matched' if row['matching']=='representative exact center' else 'matched'
        for name,cohort,hit in (('a','target',True),('b','target',False),('c','comparison',True),('d','comparison',False)):
            ids={k for k,v in selected.items() if v['cohort']==cohort and v[matched]==hit}
            assert row[name]==len(ids) and support_ids(report,'current',row[name+'_rows'])==ids
    metrics=report.frame('distributions')
    subset=metrics[metrics.measurement_key==extra.measurement_key]
    assert subset.source_coherence_unavailable.sum()>0
    assert _evaluation_digest(p.current)==before


def test_sensitivity_any_narrows_and_last_outcome_invalid_with_no_mining(calculated,monkeypatch):
    source=calculated
    source_before=_evaluation_digest(source.current)
    p=SimpleNamespace(**vars(source))
    group=p.definition.common[0]
    # Dedicated populated branches; the shared four-way fixture remains unchanged.
    p.definition=replace(p.definition,common=(replace(group,conditions=(
        replace(group.conditions[0],minimum=900),replace(group.conditions[1],maximum=850))),))
    from leonardo.analysis import pre_event_patterns as mining
    from leonardo.analysis.service import AnalysisService
    monkeypatch.setattr(mining,'mine',lambda *a,**k:pytest.fail('sensitivity must not mine'))
    p.current=evaluate_granular_patterns(p.frozen,p.definition)
    column=p.definition.common[0].conditions[0].column
    raw=p.current._data['columns'][column]['frame']
    values={s['event_id']:Decimal(str(raw.iloc[s['anchor']-1]['raw_value'])) for s in p.current._data['samples']}
    high_ids={key for key,value in values.items() if value>=Decimal(900)}
    low_ids={key for key,value in values.items() if value<=Decimal(850)}
    before_ids=set(values)
    assert high_ids and low_ids and high_ids.isdisjoint(low_ids)
    assert before_ids==high_ids|low_ids
    calls=[];original=AnalysisService.evaluate_pattern_set
    def capture(self,*a,**kw):calls.append((a,kw));return original(self,*a,**kw)
    monkeypatch.setattr(AnalysisService,'evaluate_pattern_set',capture)
    before=_evaluation_digest(p.current)
    report=refinement_sensitivity(p.frozen,p.current,(FilterOmission('condition','common',0,0),FilterOmission('condition','outcome',0,0)))
    assert len(calls)==1 and len(report.evaluations)==1
    assert report.plan[1]['status']=='not_evaluated_invalid_definition'
    variant=report.variant('common/0/0')
    assert variant.granular_definition.common[0].operator=='ANY'
    assert variant.parent_id==p.current.evaluation_id
    assert tuple(variant.frame('patterns').pattern_id)==tuple(r.pattern_id for r in p.frozen.patterns)
    after_ids={s['event_id'] for s in variant._data['samples']}
    assert after_ids==low_ids
    assert before_ids-after_ids==high_ids
    assert after_ids<before_ids
    assert _evaluation_digest(p.current)==before
    assert _evaluation_digest(source.current)==source_before


@pytest.mark.parametrize('omissions',[(FilterOmission('condition','common',0,99),),
    (FilterOmission('condition','common',0,0),)*2,tuple(FilterOmission('condition','common',0,i) for i in range(9)),
    (FilterOmission('anchor_range'),),()])
def test_omission_preflight_rejects_invalid_selection(calculated,omissions):
    p=calculated;context=p.frozen.filter_context()
    with pytest.raises(ValueError):plan_filter_omissions(p.definition,omissions,source_request=p.request,
        column_profiles={n:c['profile_id'] for n,c in context['columns'].items()},horizon_source=context['horizon_source'],
        family_universe=p.families)


@pytest.mark.parametrize('comparison',('non_start','recurrence','other_families','other_outcomes'))
def test_comparison_meanings_ordinary_identity_and_chronology(tmp_path,comparison):
    parent,cat,axis,req,study,families=multi_case(tmp_path,comparison=comparison,chronological=True,
        scope=FamilyScope('all') if comparison=='other_outcomes' else None)
    if comparison=='other_outcomes':
        from leonardo.analysis.trend_start_patterns import run_study
        # The completed-outcome examples occur after the helper's midpoint split.
        # Place this test's explicit split between complete evidence windows before pinning.
        available=sorted(study._data['samples'],key=lambda s:s['anchor'])
        assert len(available)==4
        left=available[1]['evidence_end_ms'];right=available[2]['feature_start_ms']
        split=(left+right)//2
        assert left<split<right
        req=replace(req,pre_event=replace(req.pre_event,split_ms=split))
        study=run_study(parent,cat,req,axis)
        assert req.pre_event.chronological and json.loads(study.context)['split_ms']==split
        assert sum(s['partition']=='discovery' for s in study._data['samples'])==2
        assert sum(s['partition']=='later' for s in study._data['samples'])==2
        assert {s['event_id'] for s in study._data['samples']}=={s['event_id'] for s in available}
    assert not study.frame('patterns').empty
    ids=study.frame('patterns').pattern_id.tolist()
    assert ids
    frozen=pin_patterns(parent,cat,study,ids[:2])
    extra=P('column','raw_value','native',column=req.columns[0],profile_id=frozen._root['columns'][req.columns[0]]['profile_id'],offset=-1)
    report=inspect_combination(frozen,study,study,None,ids[0],InspectionOptions((extra,)))
    frame=report.frame('comparison')
    assert not frame.period.eq('excluded').any()
    if comparison!='other_outcomes':assert 'historical_desired_outcome_share' not in frame and 'a' not in frame
    if comparison=='recurrence':assert 'comparison_frequency' not in frame
    records=json.loads(report.payload)['records']['current']
    if comparison=='non_start':
        ordinary=[r for r in records.values() if r['ordinary']]
        assert ordinary
        for row in ordinary:
            assert row['family'] is None and row['event_evidence']['role']=='ordinary_timestamp'
            assert not any(k in row['event_evidence'] for k in ('episode','start','formation','endpoint','observation'))
    eligible={k for k,r in records.items() if r['cohort'] in ('target','comparison') and r['partition'] in ('discovery','later')}
    actual=report.ledger(dict(period='eligible_combined'))
    assert actual.attrs['support_set_total']==len(eligible)
    assert all(r['block'] in range(4) for r in records.values())


def test_simpler_and_alias_support_uses_combination_assessability(calculated):
    p=calculated;report=inspect_combination(p.frozen,p.study,p.current,None,p.rule.pattern_id,InspectionOptions())
    literal=direct_observations(p.current,p.rule)
    selected={k for k,r in literal.items() if r['cohort']=='target' and r['partition'] in ('discovery','later') and r['assessable']}
    for row in report.frame('simpler').to_dict('records'):
        if row['side']=='current' and row['period']=='eligible_combined':
            assert support_ids(report,'current',row['assessable_rows'])==selected
            assert support_ids(report,'current',row['matched_rows'])<=selected
    aliases=report.frame('centers')
    assert len(aliases.query("side == 'current' and period == 'eligible_combined'"))==__import__('math').prod(len(t.centers) for t in p.rule.terms)


def test_repin_granular_source_preserves_upstream_population_identity(calculated):
    p=calculated
    searched=search_granular_patterns(p.frozen,p.parent,p.catalogue,p.definition,parent_id=p.current.evaluation_id)
    ids=searched.frame('patterns').pattern_id.tolist()
    assert ids
    repinned=pin_patterns(p.parent,p.catalogue,searched,ids[:2])
    assert searched.population_report()['set_id']!=repinned.set_id
    report=inspect_combination(repinned,searched,searched,None,repinned.patterns[0].pattern_id,InspectionOptions())
    assert report.header['set_id']==repinned.set_id
    assert report.header['source_provenance']['source']['granular_population_digest']


@pytest.mark.parametrize('fault',('definition','source_stamp','profile','count'))
def test_tampered_source_is_rejected_without_alternate_source(calculated,fault):
    p=calculated;source=deepcopy(p.study)
    if fault=='definition':source._data['_gr03_definition']={}
    elif fault=='source_stamp':source._data['_pin_source_binding']='wrong'
    elif fault=='profile':source._data['columns'][p.rule.terms[0].column]['profile_id']='wrong'
    else:
        table=next(f for n,f in source._tables if n=='patterns');table.loc[table.index[0],'matched']+=1
    with pytest.raises((ValueError,TypeError)):
        inspect_combination(p.frozen,source,source,None,p.rule.pattern_id,InspectionOptions())


@pytest.mark.parametrize('bad',[
    lambda:InspectionOptions((P('horizon','terminal_signed','pct',horizon_bars=1,minimum=0),)),
    lambda:InspectionOptions((P('horizon','terminal_signed','pct',horizon_bars=1),)*2),
    lambda:InspectionOptions(tuple(P('horizon','terminal_signed','pct',horizon_bars=i) for i in range(1,10))),
    lambda:FilterOmission('condition','common',True,0),
    lambda:FilterOmission('family_scope','common',0,0),
    lambda:FilterOmission('unknown')])
def test_finite_descriptor_and_omission_limits(bad):
    with pytest.raises((ValueError,TypeError)):bad()


def test_each_omission_derives_from_same_base_with_date_and_family(calculated):
    p=calculated
    definition=replace(p.definition,anchor_range=AnchorDateRange(p.request.start_ms,p.request.end_ms),family_scope=FamilyScope('selected',p.families[:2]))
    context=p.frozen.filter_context()
    plan=plan_filter_omissions(definition,(FilterOmission('condition','common',0,0),FilterOmission('anchor_range'),FilterOmission('family_scope')),
        source_request=p.request,column_profiles={n:c['profile_id'] for n,c in context['columns'].items()},
        horizon_source=context['horizon_source'],family_universe=p.families)
    assert len({row['before_id'] for row in plan})==1
    assert plan[0]['after']['anchor_range']==definition.to_dict()['anchor_range']
    assert plan[1]['after']['family_scope']==definition.to_dict()['family_scope']
    assert plan[2]['after']['common']==definition.to_dict()['common']
    assert 'anchor_range' not in plan[1]['after']
    assert D.from_dict(plan[1]['after']).anchor_range is None
    assert plan[2]['after']['family_scope'] is None
    group=definition.common[0]
    expected=(
        replace(definition,common=(replace(group,conditions=group.conditions[1:]),)),
        replace(definition,anchor_range=None),
        replace(definition,family_scope=None),
    )
    for row,derived in zip(plan,expected,strict=True):
        assert row['before']==definition.to_dict() and row['before_id']==definition.identity
        assert row['after']==derived.to_dict() and row['after_id']==derived.identity
        assert D.from_dict(row['after'])==derived


def test_report_slice_summaries_and_links_match_direct_values(calculated):
    p=calculated;report=inspect_combination(p.frozen,p.study,p.current,None,p.rule.pattern_id,InspectionOptions())
    records=json.loads(report.payload)['records']['current']
    distributions=report.frame('distributions')
    checked=0
    for row in distributions.to_dict('records'):
        if row['side']!='current' or row['period']!='eligible_combined' or not row['values_summarized']:continue
        ids=support_ids(report,'current',row['summarized_rows'])
        values=[records[k]['metrics'][row['measurement_key']]['value'] for k in ids]
        expected=oracle_quantiles(values)
        assert len(ids)==row['values_summarized']
        assert [Decimal(row[k]) for k in ('min','q1','median','q3','max')]==expected
        checked+=1
    assert checked>0
