"""GR-03A supplied-scalar predicates: independent truth and boundary oracles."""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext, getcontext, ROUND_UP, ROUND_DOWN
from itertools import product
import json
import os
import subprocess
import sys

import pytest

from leonardo.analysis.refinement_models import (
    GranularPredicate, GranularGroup, GranularRefinement, ResolvedFilterValue,
)
from leonardo.analysis.pattern_refinement import validate_granular_context, evaluate_granular_predicates
from leonardo.analysis.pattern_models import NumericCondition, MEASUREMENT_BASES, MOVEMENT_FIELDS, DURATION_FIELDS, PULLBACK_COHORTS
from leonardo.analysis.trend_start_patterns import _bounded, _hash


# Literal hand vectors from the approved acceptance card. No external-file dependency.
TRUTH = (
    ('PPP','pass','pass'), ('PPM','mismatch','pass'), ('PPU','unavailable','unavailable'),
    ('PMP','mismatch','pass'), ('PMM','mismatch','pass'), ('PMU','unavailable','unavailable'),
    ('PUP','unavailable','unavailable'), ('PUM','unavailable','unavailable'), ('PUU','unavailable','unavailable'),
    ('MPP','mismatch','pass'), ('MPM','mismatch','pass'), ('MPU','unavailable','unavailable'),
    ('MMP','mismatch','pass'), ('MMM','mismatch','mismatch'), ('MMU','unavailable','unavailable'),
    ('MUP','unavailable','unavailable'), ('MUM','unavailable','unavailable'), ('MUU','unavailable','unavailable'),
    ('UPP','unavailable','unavailable'), ('UPM','unavailable','unavailable'), ('UPU','unavailable','unavailable'),
    ('UMP','unavailable','unavailable'), ('UMM','unavailable','unavailable'), ('UMU','unavailable','unavailable'),
    ('UUP','unavailable','unavailable'), ('UUM','unavailable','unavailable'), ('UUU','unavailable','unavailable'),
)
STRICT = (
    (False,False,('mismatch','mismatch','pass','pass','mismatch','mismatch')),
    (False,True, ('mismatch','mismatch','pass','pass','pass','mismatch')),
    (True,False, ('mismatch','pass','pass','pass','mismatch','mismatch')),
    (True,True,  ('mismatch','pass','pass','pass','pass','mismatch')),
)
STRICT_VALUES = ('-1','0','1E-12','1','2','3')
CANONICAL = (('1','1e0'),('1.0','1e0'),('1E0','1e0'),('-0.00','0'),('1.25','125e-2'),('75000','75e3'),('1.23E-12','123e-14'))
POPULATION = (
    ('E1',True,'4',20,'pass','pass','pass'),
    ('E2',True,'3',40,'pass','mismatch','mismatch'),
    ('E3',True,'-1',18,'mismatch','pass','mismatch'),
    ('E4',True,'1.5',22,'mismatch','pass','mismatch'),
    ('E5',False,'4',20,'pass','pass','pass'),
    ('E6',False,'0.2',16,'mismatch','pass','mismatch'),
    ('E7',False,'1',70,'mismatch','mismatch','mismatch'),
    ('E8',False,'-2',25,'mismatch','pass','mismatch'),
    ('E9',True,None,20,'unavailable','pass','unavailable'),
)


def numeric(**kwargs):
    settings = dict(domain='movement', field='directional_move', unit='pct', basis='completed', minimum=0)
    return GranularPredicate(**(settings | kwargs))


def definition(*predicates, operator='ALL'):
    return GranularRefinement(outcome=(GranularGroup(operator, predicates),))


def fact(value):
    return ResolvedFilterValue(unavailable_reason='fixture_unavailable') if value is None else ResolvedFilterValue(value)


def one(predicate, value):
    return evaluate_granular_predicates(definition(predicate), {predicate.measurement_key:fact(value)})


def truth_oracle_rows():
    rows=[]
    predicates=tuple(numeric(field=f) for f in ('directional_move','signed_move','pivot_span'))
    for operator in ('ALL','ANY'):
        for code,all_expected,any_expected in TRUTH:
            expected=all_expected if operator=='ALL' else any_expected
            # Independent mathematical enumeration, not the production aggregation helper.
            mathematical=('unavailable' if 'U' in code else
                'pass' if (all(c=='P' for c in code) if operator=='ALL' else any(c=='P' for c in code)) else 'mismatch')
            assert expected==mathematical
            values={p.measurement_key:fact({'P':1,'M':-1,'U':None}[c]) for p,c in zip(predicates,code)}
            report=evaluate_granular_predicates(definition(*predicates,operator=operator),values)
            rows.append(dict(operator=operator,leaves=code,expected=expected,actual=report['status'],
                leaf_statuses=[r['status'] for r in report['predicates']],known=report['all_required_known']))
    return rows


def strict_oracle_rows():
    rows=[]
    for lower,upper,expected in STRICT:
        p=numeric(minimum=0,maximum=2,lower_inclusive=lower,upper_inclusive=upper)
        for text,status in zip(STRICT_VALUES,expected):
            rows.append(dict(lower_inclusive=lower,upper_inclusive=upper,value=text,expected=status,actual=one(p,Decimal(text))['status']))
    return rows


def population_oracle_rows():
    outcome=numeric(minimum=3)
    common=numeric(domain='duration',field='structural',unit='bars',minimum=12,maximum=30)
    parent=definition(outcome);child=replace(parent,common=(GranularGroup(conditions=(common,)),))
    rows=[]
    for identity,rule_matches,move,bars,parent_status,common_status,child_status in POPULATION:
        values={outcome.measurement_key:fact(None if move is None else Decimal(move)),common.measurement_key:fact(bars)}
        for stage,spec,expected_common,expected_overall in (('parent',parent,'inactive',parent_status),('child',child,common_status,child_status)):
            result=evaluate_granular_predicates(spec,values)
            rows.append(dict(id=identity,stage=stage,rule_matches=rule_matches,
                expected=dict(common=expected_common,outcome=parent_status,status=expected_overall),
                actual=dict(**result['purposes'],status=result['status'])))
    return rows


def key_oracle_rows():
    rows=[]
    for value,unit,expected in (('1.25','minutes',75000),('0.001','seconds',1)):
        a=numeric(domain='duration',field='structural',unit=unit,minimum=Decimal(value))
        b=replace(a,unit='ms',minimum=expected)
        rows.append(dict(input=value,unit=unit,expected_ms=expected,actual_ms=a.minimum,
            equivalent_measurement_key=a.measurement_key==b.measurement_key,equivalent_predicate_key=a.predicate_key==b.predicate_key))
    for value,expected in CANONICAL:
        p=numeric(minimum=Decimal(value))
        rows.append(dict(input=value,expected=expected,actual=p.to_dict()['minimum']))
    return rows


@pytest.mark.parametrize('operator',('ALL','ANY'))
@pytest.mark.parametrize('code,all_expected,any_expected',TRUTH)
def test_three_leaf_truth_table(operator,code,all_expected,any_expected):
    row=next(r for r in truth_oracle_rows() if (r['operator'],r['leaves'])==(operator,code))
    assert row['actual']==row['expected']
    assert row['leaf_statuses']==[{'P':'pass','M':'mismatch','U':'unavailable'}[c] for c in code]
    assert row['known']==('U' not in code)


@pytest.mark.parametrize('lower,upper,expected',STRICT)
@pytest.mark.parametrize('value_index',range(6))
def test_strict_endpoint_oracle(lower,upper,expected,value_index):
    p=numeric(minimum=0,maximum=2,lower_inclusive=lower,upper_inclusive=upper)
    result=one(p,Decimal(STRICT_VALUES[value_index]))
    assert result['status']==expected[value_index]
    assert result['predicates'][0]['reason']==('outside_bounds' if expected[value_index]=='mismatch' else '')


@pytest.mark.parametrize('row',POPULATION,ids=[r[0] for r in POPULATION])
def test_hand_counted_population_purpose_statuses(row):
    results=[r for r in population_oracle_rows() if r['id']==row[0]]
    assert len(results)==2 and all(r['actual']==r['expected'] for r in results)


def test_hand_counted_groups_are_test_only_and_ignore_rule_match():
    rows=population_oracle_rows()
    def groups(stage):
        result={'target':[],'comparison':[],'unavailable':[]}
        if stage=='child':result['common_excluded']=[]
        for row in rows:
            if row['stage']!=stage:continue
            value=row['actual']
            name=('unavailable' if value['status']=='unavailable' else 'common_excluded' if value['common']=='mismatch'
                  else 'target' if value['outcome']=='pass' else 'comparison')
            result[name].append(row['id'])
        return result
    assert groups('parent')==dict(target=['E1','E2','E5'],comparison=['E3','E4','E6','E7','E8'],unavailable=['E9'])
    assert groups('child')==dict(target=['E1','E5'],comparison=['E3','E4','E6','E8'],common_excluded=['E2','E7'],unavailable=['E9'])


INVALID_PREDICATES = [
    {'domain':'horizon'}, {'domain':None}, {'domain':1}, {'field':'future_return'}, {'field':[]},
    {'unit':'dollars'}, {'unit':False}, {'basis':None}, {'basis':'future'}, {'basis':False},
    {'cohort':'internal_recovered'}, {'column':'delta'}, {'profile_id':'p'}, {'offset':-1}, {'statistic':'mean'},
    {'enabled':1}, {'enabled':'false'}, {'lower_inclusive':0}, {'upper_inclusive':None},
    {'minimum':True}, {'maximum':False}, {'minimum':'1'}, {'maximum':'NaN'},
    {'minimum':float('nan')}, {'maximum':float('inf')}, {'minimum':Decimal('sNaN')},
    {'minimum':3,'maximum':2}, {'minimum':0,'maximum':0,'lower_inclusive':False},
    {'minimum':0,'maximum':0,'upper_inclusive':False}, {'allowed':('P0',)},
    {'domain':'duration','field':'structural','unit':'bars','minimum':.5},
    {'domain':'duration','field':'confirmation_delay','unit':'bars'},
    {'domain':'duration','field':'structural','unit':'seconds','minimum':Decimal('.0001')},
    {'domain':'duration','field':'structural','unit':'seconds','minimum':Decimal('1000000000000000000000000000.0001')},
    {'domain':'duration','field':'directional_move','unit':'pct'},
    {'domain':'pullbacks','field':'count','unit':'count','cohort':'internal_recovered','minimum':1.5},
    {'domain':'pullbacks','field':'count','unit':'count','cohort':'invalid'},
    {'domain':'pullbacks','field':'count','unit':'count','cohort':'internal_recovered','statistic':'mean'},
    {'domain':'pullbacks','field':'depth','unit':'pct','cohort':'internal_recovered'},
    {'domain':'pullbacks','field':'recovered_duration','unit':'bars','cohort':'internal_recovered','statistic':'maximum','minimum':.5},
    {'domain':'context','field':'up','unit':'boolean','basis':None,'minimum':None,'allowed':(1,)},
    {'domain':'context','field':'up','unit':'boolean','basis':None,'minimum':None,'allowed':(True,False)},
    {'domain':'context','field':'up','unit':'boolean','basis':None,'minimum':None,'allowed':(True,True)},
    {'domain':'context','field':'up','unit':'boolean','basis':None,'minimum':0,'allowed':(True,)},
    {'domain':'context','field':'up','unit':'boolean','basis':None,'minimum':None,'lower_inclusive':False},
    {'domain':'context','field':'up','unit':'boolean','minimum':None},
    {'domain':'context','field':'previous_direction','unit':'category','basis':None,'minimum':None,'allowed':('RANGE',)},
    {'domain':'context','field':'previous_direction','unit':'category','basis':None,'minimum':None,'allowed':('UP','UP')},
    {'domain':'context','field':'previous_family','unit':'category','basis':None,'minimum':None,'allowed':('UP/PTP/0,1,2',)},
    {'domain':'context','field':'previous_family','unit':'category','basis':None,'minimum':None,'allowed':('UP/TPT/0,1',)},
    {'domain':'column','field':'label','unit':'label','basis':None,'minimum':None,'column':'x','offset':-1,'allowed':('P0',)},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'','offset':-1},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':' \t','offset':-1},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'x\0','offset':-1},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'x','offset':0},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'x','offset':True},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'x','offset':-200},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'x','offset':-1,'profile_id':' '},
    {'domain':'column','field':'raw_value','unit':'native','basis':None,'column':'x','offset':-1,'minimum':'2'},
]


@pytest.mark.parametrize('kwargs',INVALID_PREDICATES)
def test_invalid_predicate_selectors_and_numbers_remain_strict_when_disabled(kwargs):
    for enabled in (True,False):
        with pytest.raises((TypeError,ValueError)):
            numeric(**({'enabled':enabled}|kwargs))


@pytest.mark.parametrize('bad',('x',b'x',{},set(),iter(()),None))
def test_sequence_boundaries_reject_non_list_tuple(bad):
    for constructor in (lambda: numeric(allowed=bad), lambda:GranularGroup(conditions=bad),
                        lambda:GranularRefinement(common=bad), lambda:GranularRefinement(outcome=bad)):
        with pytest.raises((TypeError,ValueError)):constructor()


@pytest.mark.parametrize('operator,enabled',(('all',True),('AND',True),(True,True),(None,True),('ALL',1),('ANY','false')))
def test_invalid_group_flags(operator,enabled):
    with pytest.raises((TypeError,ValueError)):GranularGroup(operator=operator,enabled=enabled)


def test_no_nested_groups_and_immutable_detached_sequences():
    p=numeric();items=[p];g=GranularGroup(conditions=items);groups=[g];s=GranularRefinement(common=groups)
    items.clear();groups.clear()
    assert s.common==(g,) and g.conditions==(p,)
    for value,field,new in ((p,'minimum',2),(g,'enabled',False),(s,'outcome',()),(ResolvedFilterValue(1),'value',2)):
        assert not hasattr(value,'__dict__')
        with pytest.raises(FrozenInstanceError):setattr(value,field,new)
    with pytest.raises((TypeError,ValueError)):GranularGroup(conditions=(g,))
    with pytest.raises((TypeError,ValueError)):GranularRefinement(common=(p,))


PARITY = [(d,f,u,stat) for d,f,u,stat in (
    ('movement','directional_move','pct',None),('movement','signed_move','points',None),
    ('movement','pivot_favorable','pct',None),('movement','pivot_adverse','points',None),('movement','pivot_span','points',None),
    ('duration','structural','bars',None),('duration','endpoint_extension','ms',None),
    ('duration','observed_elapsed','ms',None),('duration','confirmation_delay','ms',None),
    ('pullbacks','count','count',None),('pullbacks','depth','pct','mean'),('pullbacks','depth','points','maximum'),
    ('pullbacks','recovered_duration','bars','mean'),('pullbacks','recovered_duration','ms','maximum'))]


@pytest.mark.parametrize('domain,field,unit,statistic',PARITY)
def test_inclusive_truth_matches_existing_bounded(domain,field,unit,statistic):
    for minimum,maximum in ((0,None),(None,2),(0,2),(1,1)):
        p=numeric(domain=domain,field=field,unit=unit,statistic=statistic,cohort='internal_recovered' if domain=='pullbacks' else None,
                  minimum=minimum,maximum=maximum)
        old=NumericCondition(field,unit,minimum,maximum,statistic)
        for value in (None,0,1,2,3):
            assert one(p,value)['status']==_bounded(value,old)['status']
    blank=replace(p,minimum=None,maximum=None)
    assert not blank.active and one(blank,None)['status']=='pass'


@pytest.mark.parametrize('value,unit,expected',(('1.25','minutes',75000),('.001','seconds',1),('0.00001','hours',36)))
def test_exact_units_and_normalized_keys(value,unit,expected):
    a=numeric(domain='duration',field='structural',unit=unit,minimum=Decimal(value))
    b=replace(a,unit='ms',minimum=expected)
    assert (a.unit,a.minimum)==('ms',expected)
    assert a.predicate_key==b.predicate_key and a.measurement_key==b.measurement_key
    assert one(a,expected)['status']=='pass'
    with pytest.raises(ValueError):GranularGroup(conditions=(a,b))


@pytest.mark.parametrize('text,expected',CANONICAL)
def test_canonical_decimal_literals(text,expected):
    p=numeric(minimum=Decimal(text))
    assert p.to_dict()['minimum']==expected
    assert one(p,Decimal(text))['predicates'][0]['value']==expected


@pytest.mark.parametrize('rounding',(ROUND_UP,ROUND_DOWN))
def test_round_trip_exactness_under_low_decimal_context(rounding):
    p=numeric(minimum=Decimal('123456789012345678901234567890.123456789'),maximum=Decimal('1E1000'))
    duration=numeric(domain='duration',field='structural',unit='minutes',minimum=Decimal('1.25'))
    s=definition(p,duration)
    expected=s.to_dict();identity=s.identity;key=p.predicate_key
    with localcontext() as ctx:
        ctx.prec=2;ctx.rounding=rounding;ctx.clear_flags()
        original=(ctx.prec,ctx.rounding,dict(ctx.flags),dict(ctx.traps))
        actual=GranularRefinement.from_dict(json.loads(json.dumps(expected)))
        assert actual==s and actual.identity==identity and actual.outcome[0].conditions[0].predicate_key==key
        assert one(p,Decimal('123456789012345678901234567890.123456788'))['status']=='mismatch'
        assert one(p,Decimal('123456789012345678901234567890.123456789'))['status']=='pass'
        assert (ctx.prec,ctx.rounding,dict(ctx.flags),dict(ctx.traps))==original
    assert numeric(minimum=1).predicate_key==numeric(minimum=1.0).predicate_key==numeric(minimum=Decimal('1.000')).predicate_key


@pytest.mark.parametrize('text',(' 1','1 ','1_0','NaN','Infinity','-Infinity','1+2','', '\t2', '1e','0x1'))
def test_parser_rejects_bad_numeric_strings(text):
    payload=definition(numeric()).to_dict();payload['outcome'][0]['conditions'][0]['minimum']=text
    with pytest.raises((TypeError,ValueError)):GranularRefinement.from_dict(payload)


@pytest.mark.parametrize('level',('root','group','predicate'))
@pytest.mark.parametrize('change',('missing','extra','wrong_container'))
def test_strict_schema_keys_at_every_level(level,change):
    payload=definition(numeric()).to_dict()
    target=payload if level=='root' else payload['outcome'][0] if level=='group' else payload['outcome'][0]['conditions'][0]
    if change=='missing':target.pop(next(iter(target)))
    elif change=='extra':target['unexpected']=True
    elif level=='root':payload=[]
    elif level=='group':payload['outcome'][0]=[]
    else:payload['outcome'][0]['conditions'][0]=[]
    with pytest.raises((TypeError,ValueError)):GranularRefinement.from_dict(payload)


def test_parser_kind_types_and_detached_serialization():
    s=definition(numeric());payload=s.to_dict()
    for bad in (None,1,'gr03-filter-spec-v2'):
        with pytest.raises(ValueError):GranularRefinement.from_dict(payload|{'kind':bad})
    payload['outcome'][0]['conditions'][0]['minimum']=True
    with pytest.raises((TypeError,ValueError)):GranularRefinement.from_dict(payload)
    payload['outcome'].clear();assert s.active_count==1
    assert numeric(minimum=None,lower_inclusive=False).to_dict()['lower_inclusive'] is False
    empty=definition(numeric(minimum=None,lower_inclusive=False))
    assert GranularRefinement.from_dict(empty.to_dict())==empty


def test_exact_keys_selectors_and_threshold_distinction():
    a=numeric();b=replace(a,minimum=1)
    assert a.measurement_key==b.measurement_key and a.predicate_key!=b.predicate_key
    assert definition(a).identity!=definition(b).identity
    selectors={k:a.to_dict()[k] for k in ('domain','field','unit','basis','cohort','statistic','column','profile_id','offset')}
    assert a.measurement_key==_hash(('gr03-measure-v1',selectors))
    payload=a.to_dict();payload.pop('enabled');assert a.predicate_key==_hash(('gr03-predicate-v1',payload))
    assert definition(a).identity==_hash(definition(a).to_dict())
    assert replace(a,enabled=False).predicate_key==a.predicate_key
    assert len({replace(a,basis=basis).measurement_key for basis in MEASUREMENT_BASES})==3
    p=numeric(domain='pullbacks',field='depth',cohort='internal_recovered',statistic='mean')
    variations=(p,replace(p,cohort='all_observed'),replace(p,statistic='maximum'),replace(p,unit='points'))
    assert len({v.measurement_key for v in variations})==4
    raw=GranularPredicate('column','raw_value','native',column=' literal column ',profile_id='p1',offset=-1,minimum=0)
    variations=(raw,replace(raw,column='literal column'),replace(raw,profile_id='p2'),replace(raw,profile_id=None),replace(raw,offset=-2))
    assert len({v.measurement_key for v in variations})==5 and raw.column==' literal column '


class CountingValues(Mapping):
    def __init__(self,items):self.items=dict(items);self.reads=[]
    def __getitem__(self,key):self.reads.append(key);return self.items[key]
    def __iter__(self):raise AssertionError('evaluator must not inspect unrequested entries')
    def __len__(self):return len(self.items)


def test_repeated_measures_groups_roles_and_no_hidden_short_circuit():
    a=numeric();b=replace(a,minimum=2);c=replace(a,minimum=3)
    with pytest.raises(ValueError):GranularGroup(conditions=(a,replace(a,enabled=False)))
    g1=GranularGroup('ANY',(a,b));g2=GranularGroup('ANY',(a,c))
    s=GranularRefinement(common=(g1,g2),outcome=(GranularGroup(conditions=(a,)),))
    values=CountingValues({a.measurement_key:fact(1),'unrequested':object()})
    result=evaluate_granular_predicates(s,values)
    assert result['status']=='pass' and result['active_count']==5
    assert values.reads==[a.measurement_key] and result['required_measurements']==[a.measurement_key]
    assert result['cross_purpose_predicates']==[a.predicate_key]
    reordered=replace(s,common=(replace(g2,conditions=tuple(reversed(g2.conditions))),g1))
    other=evaluate_granular_predicates(reordered,{a.measurement_key:fact(1)})
    assert other['status']==result['status'] and other['required_measurements']==result['required_measurements']
    assert other['definition_id']!=result['definition_id']


@pytest.mark.parametrize('common,outcome',product(('P','M','U','I'),repeat=2))
def test_separate_all_roots_and_unknown_outcome_after_failed_common(common,outcome):
    a=numeric();b=numeric(field='signed_move')
    s=GranularRefinement(common=(GranularGroup(conditions=(replace(a,enabled=common!='I'),)),),
        outcome=(GranularGroup(conditions=(replace(b,enabled=outcome!='I'),)),))
    values={p.measurement_key:fact({'P':1,'M':-1,'U':None,'I':None}[v]) for p,v in ((a,common),(b,outcome))}
    result=evaluate_granular_predicates(s,values)
    assert result['purposes']=={k:{'P':'pass','M':'mismatch','U':'unavailable','I':'inactive'}[v] for k,v in [('common',common),('outcome',outcome)]}
    expected='unavailable' if 'U' in (common,outcome) else 'mismatch' if 'M' in (common,outcome) else 'pass'
    assert result['status']==expected


def test_limits_effective_activity_and_inactive_reason_precedence():
    rows=tuple(numeric(minimum=i) for i in range(32))
    assert definition(*rows).active_count==32
    with pytest.raises(ValueError):GranularGroup(conditions=rows+(numeric(minimum=32),))
    with pytest.raises(ValueError):GranularRefinement(common=(GranularGroup(conditions=rows),GranularGroup(conditions=(numeric(),))))
    eight=(GranularGroup(conditions=rows,enabled=False),)*8
    assert GranularRefinement(common=eight).active_count==0
    with pytest.raises(ValueError):GranularRefinement(common=eight,outcome=(GranularGroup(),))
    a=numeric(enabled=False);empty=numeric(minimum=None)
    s=GranularRefinement(common=(GranularGroup('ANY',(a,empty)),GranularGroup('ANY',(a,empty),False),GranularGroup('ANY')))
    result=evaluate_granular_predicates(s,CountingValues({}))
    assert result['status']=='pass' and result['active_count']==0 and result['all_required_known']
    assert result['required_measurements']==[] and all(g['status']=='inactive' for g in result['groups'])
    assert [p['reason'] for p in result['predicates']]==['predicate_disabled','empty_condition','group_disabled','group_disabled']
    assert all(p['value'] is None for p in result['predicates'])
    assert evaluate_granular_predicates(GranularRefinement(),{})['purposes']==dict(common='inactive',outcome='inactive')


@pytest.mark.parametrize('predicate',(
    numeric(domain='duration',field='endpoint_extension',unit='bars',basis='formation'),
    numeric(domain='duration',field='observed_elapsed',unit='ms',basis='formation'),
    numeric(domain='pullbacks',field='count',unit='count',basis='formation',cohort='currently_pending'),
))
def test_cross_basis_compatibility_only_when_effectively_active(predicate):
    inactive=GranularRefinement(outcome=(GranularGroup(conditions=(predicate,),enabled=False),))
    assert GranularRefinement.from_dict(inactive.to_dict())==inactive
    assert definition(replace(predicate,enabled=False)).active_count==0
    assert definition(replace(predicate,minimum=None)).active_count==0
    with pytest.raises(ValueError):definition(predicate)


@pytest.mark.parametrize('cohort',PULLBACK_COHORTS[:4])
def test_formation_cohort_authority(cohort):
    p=numeric(domain='pullbacks',field='count',unit='count',basis='formation',cohort=cohort)
    assert one(p,0)['status']=='pass'


@pytest.mark.parametrize('args',({}, {'value':None}, {'unavailable_reason':''}, {'unavailable_reason':' '},
    {'value':1,'unavailable_reason':'missing'}, {'value':float('nan')}, {'value':float('inf')},
    {'value':[]}, {'value':{}}, {'value':object()}, {'value':''}, {'value':'x\0'}))
def test_invalid_resolved_values(args):
    with pytest.raises((TypeError,ValueError)):ResolvedFilterValue(**args)


@pytest.mark.parametrize('value',(True,'1',None,{},1))
def test_wrong_requested_record_or_scalar_is_boundary_error(value):
    p=numeric()
    record=ResolvedFilterValue(value) if type(value) in (bool,str) else value
    with pytest.raises((TypeError,ValueError)):evaluate_granular_predicates(definition(p),{p.measurement_key:record})
    inactive=replace(p,enabled=False)
    assert evaluate_granular_predicates(definition(inactive),{p.measurement_key:record})['status']=='pass'


def test_known_false_zero_none_lineage_and_exact_label_membership():
    boolean=GranularPredicate('context','up','boolean',allowed=(False,))
    assert one(boolean,False)['predicates'][0]['value'] is False
    assert one(boolean,True)['status']=='mismatch'
    with pytest.raises((TypeError,ValueError)):one(boolean,0)
    assert one(numeric(),0)['predicates'][0]['value']=='0'
    previous=GranularPredicate('context','previous_direction','category',allowed=('NONE','DOWN'))
    assert previous.allowed==('DOWN','NONE') and one(previous,'NONE')['status']=='pass'
    assert one(previous,None)['status']=='unavailable'
    with pytest.raises(ValueError):one(previous,'RANGE')
    family=GranularPredicate('context','previous_family','category',allowed=('UP/TPT/0,2,1','NONE'))
    assert one(family,'NONE')['status']=='pass' and one(family,'DOWN/PTP/2,0,1')['status']=='mismatch'
    with pytest.raises(ValueError):one(family,'bad-family')
    label=GranularPredicate('column','label','label',column='delta',profile_id='profile',offset=-1,allowed=('P0','P2'))
    assert one(label,'P0')['status']=='pass' and one(label,'P1')['status']=='mismatch'
    assert one(label,'P*')['status']=='mismatch'
    with pytest.raises((TypeError,ValueError)):one(label,0)


@pytest.mark.parametrize('domain,field,unit,statistic',(
    ('duration','structural','bars',None),('duration','structural','ms',None),
    ('pullbacks','count','count',None),('pullbacks','recovered_duration','bars','maximum'),
    ('pullbacks','recovered_duration','ms','maximum'),
))
def test_count_and_individual_duration_facts_nonnegative_integral(domain,field,unit,statistic):
    p=numeric(domain=domain,field=field,unit=unit,statistic=statistic,cohort='internal_recovered' if domain=='pullbacks' else None)
    for value in (-1,Decimal('.5')):
        with pytest.raises(ValueError):one(p,value)
    assert one(p,0)['status']=='pass'


@pytest.mark.parametrize('unit',('bars','ms'))
def test_mean_duration_facts_may_be_fractional(unit):
    p=numeric(domain='pullbacks',field='recovered_duration',unit=unit,cohort='internal_recovered',statistic='mean')
    assert one(p,Decimal('.5'))['status']=='pass'
    with pytest.raises(ValueError):one(p,Decimal('-.5'))
    if unit=='bars':assert replace(p,minimum=Decimal('.25')).minimum==Decimal('.25')


@pytest.mark.parametrize('offsets',([],(),[0],[-1,0],[1],[-1,-1],[-1,-2],[-200],[-1.0],[True],{-1},'[-1]'))
def test_context_rejects_invalid_offset_envelopes(offsets):
    with pytest.raises((TypeError,ValueError)):validate_granular_context(GranularRefinement(),column_profiles={},offsets=offsets)


def test_literal_column_profile_offset_binding_and_inactive_drafts():
    raw=GranularPredicate('column','raw_value','native',column=' raw ',offset=-199,minimum=-1)
    label=GranularPredicate('column','label','label',column='delta',profile_id=' p1 ',offset=-1,allowed=('P0',))
    spec=definition(raw,label);columns={' raw ':None,'delta':' p1 '};saved=dict(columns)
    assert validate_granular_context(spec,column_profiles=columns,offsets=[-199,-1]) is None
    assert columns==saved and one(raw,-1)['status']=='pass'
    for changed in ({'raw':None,'delta':' p1 '},{' raw ':'p','delta':' p1 '},{' raw ':None,'delta':'p1'},{' raw ':None}):
        with pytest.raises(ValueError):validate_granular_context(spec,column_profiles=changed,offsets=(-199,-1))
    with pytest.raises(ValueError):validate_granular_context(spec,column_profiles=columns,offsets=(-2,-1))
    for inactive in (replace(spec,outcome=(replace(spec.outcome[0],enabled=False),)),definition(replace(raw,enabled=False),replace(label,allowed=()))):
        validate_granular_context(inactive,column_profiles={},offsets=(-1,))
        assert evaluate_granular_predicates(inactive,CountingValues({}))['status']=='pass'
    for bad in ([],{'':None},{'x':''},{'x':1},{'x\0':None}):
        with pytest.raises((TypeError,ValueError)):validate_granular_context(GranularRefinement(),column_profiles=bad,offsets=(-1,))


def test_report_schema_full_leaf_retention_and_detachment():
    a=numeric();b=numeric(field='signed_move')
    spec=GranularRefinement(common=(GranularGroup(conditions=(a,)),),outcome=(GranularGroup('ANY',(b,)),))
    values={a.measurement_key:fact(-1),b.measurement_key:ResolvedFilterValue(unavailable_reason='missing_saved_clock'),'inspection_only':object()}
    saved=deepcopy(values);report=evaluate_granular_predicates(spec,values)
    assert set(report)=={'kind','definition_id','status','active_count','required_measurements','all_required_known','purposes','groups','predicates','cross_purpose_predicates','scope'}
    assert report['status']=='unavailable' and report['purposes']==dict(common='mismatch',outcome='unavailable')
    assert report['predicates'][1]['reason']=='missing_saved_clock'
    assert [r['path'] for r in report['predicates']]==['common[0].conditions[0]','outcome[0].conditions[0]']
    assert set(report['groups'][0])=={'purpose','group_index','operator','status','active_count'}
    assert set(report['predicates'][0])=={'path','purpose','group_index','predicate_index','measurement_key','predicate_key','status','value','reason'}
    assert report['scope']=='supplied_scalars_only_not_cohort_or_evidence_validation'
    before=json.dumps(report,sort_keys=True);report['predicates'][0]['value']='changed';report['groups'].clear();report['required_measurements'].clear()
    assert json.dumps(evaluate_granular_predicates(spec,values),sort_keys=True)==before
    assert values[a.measurement_key]==saved[a.measurement_key] and values[b.measurement_key]==saved[b.measurement_key]
    missing=evaluate_granular_predicates(definition(a),{})
    assert missing['predicates'][0]['reason']=='required_value_missing'


@pytest.mark.parametrize('where',('entry','middle','return'))
def test_checkpoint_cancellation_propagates_without_partial_publication(where):
    p=numeric();s=definition(p,replace(p,minimum=2));values={p.measurement_key:fact(1)}
    calls=[];expected=evaluate_granular_predicates(s,values,checkpoint=lambda:calls.append(True))
    target={'entry':1,'middle':len(calls)//2,'return':len(calls)}[where]
    class Stop(Exception):pass
    count=0;published=[];before=s.to_dict();old=dict(values)
    def checkpoint():
        nonlocal count
        count+=1
        if count==target:raise Stop('cancel specimen')
    with pytest.raises(Stop):published.append(evaluate_granular_predicates(s,values,checkpoint=checkpoint))
    assert not published and s.to_dict()==before and values==old
    assert evaluate_granular_predicates(s,values)==expected


def test_supplied_real_projection_does_not_recalculate_or_resolve(tmp_path,monkeypatch):
    from tests.analysis_test.test_trend_start_enrichment import enriched_fixture,ENDED,first_event,movement
    from leonardo.analysis import trend_start_patterns as trend, pattern_refinement as refinement, pre_event_patterns as mining, pre_event_cohorts as cohorts, service
    from leonardo import financial_tools
    from leonardo.data_manager.creation_store import DataManagerCreationStore
    parent,catalogue,axis,analysis,frame=enriched_fixture(tmp_path,ENDED)
    event=first_event(catalogue)
    projection=trend.refine_event(event,movement('completed',0))['projection']['measurements']
    amount=projection['structural']['movement']['directional_move_points']
    duration=projection['structural']['duration']['bars']
    assert amount is not None and duration is not None
    before=deepcopy(event)
    def forbidden(*args,**kwargs):pytest.fail('predicate kernel called a forbidden calculation/resolution boundary')
    for module,names in ((refinement,('pin_patterns','evaluate_patterns','build_cohorts','_axis_and_columns','_pin_source_binding')),
        (trend,('refine_event','build_catalogue','run_study')),(mining,('mine',)),(cohorts,('build_cohorts',)),
        (service,('fit_directional_binning','classify_directional_binning','fit_dynamic_binning','classify_dynamic_binning')),
        (financial_tools,('calculate_financial_tool',)),(DataManagerCreationStore,('load_database_revision',))):
        for name in names:monkeypatch.setattr(module,name,forbidden)
    p=numeric(unit='points',minimum=amount,maximum=amount)
    d=numeric(domain='duration',field='structural',unit='bars',minimum=duration,maximum=duration)
    spec=definition(p,d);validate_granular_context(spec,column_profiles={},offsets=(-1,))
    assert evaluate_granular_predicates(spec,{p.measurement_key:fact(amount),d.measurement_key:fact(duration)})['status']=='pass'
    assert event==before


@pytest.mark.parametrize('first',('refinement_models','pattern_refinement'))
def test_cold_import_orders_without_root_exports(first,tmp_path):
    second='pattern_refinement' if first=='refinement_models' else 'refinement_models'
    script=f'''import importlib
importlib.import_module("leonardo.analysis.{first}")
importlib.import_module("leonardo.analysis.{second}")
import leonardo.analysis as root
for name in ("GranularPredicate","GranularGroup","GranularRefinement","ResolvedFilterValue","evaluate_granular_predicates","validate_granular_context"):
    assert not hasattr(root,name) and name not in root.__all__
'''
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=tmp_path,env=os.environ.copy(),capture_output=True,text=True)
    assert result.returncode==0,result.stderr
