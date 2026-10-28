"""GR-03B population algebra, chronology, isolation and report boundaries."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json

import pandas as pd
import pytest

from leonardo.analysis.pattern_models import PatternRefinement
from leonardo.analysis.refinement_models import GranularPredicate as Predicate,GranularGroup as Group,GranularRefinement as Definition,ResolvedFilterValue
from leonardo.analysis.pattern_refinement import resolve_granular_population,evaluate_granular_predicates,evaluate_patterns,_granular_assign
from leonardo.analysis.trend_start_patterns import _json,_hash
from leonardo.analysis.pre_event_cohorts import partition_sample
from tests.analysis_test.test_granular_evidence import make_case,append_case,quantity,spec,ledger
from tests.analysis_test.test_trend_start_enrichment import movement


POPULATION=(('E1',4,20,'target','target'),('E2',3,40,'target','common_mismatch'),
    ('E3',-1,18,'comparison','comparison'),('E4',1.5,22,'comparison','comparison'),
    ('E5',4,20,'target','target'),('E6',.2,16,'comparison','comparison'),
    ('E7',1,70,'comparison','common_mismatch'),('E8',-2,25,'comparison','comparison'),('E9',None,20,'unavailable','unavailable'))
CHRONOLOGY=((100,300,120,999,'discovery'),(100,300,120,1000,'excluded'),
    (1000,1100,1000,1200,'later'),(999,1100,1000,1200,'excluded'),(100,300,120,None,'excluded'))


def hand_vectors():
    outcome=quantity(unit='pct',minimum=3);common=quantity('duration','structural','bars',minimum=12,maximum=30)
    definitions=(spec(outcome),spec(outcome,common=(Group(conditions=(common,)),)))
    rows=[]
    for identity,move,bars,parent,child in POPULATION:
        values={outcome.measurement_key:ResolvedFilterValue(move) if move is not None else ResolvedFilterValue(unavailable_reason='saved_metric_missing'),
                common.measurement_key:ResolvedFilterValue(bars)}
        for stage,definition,expected in zip(('parent','child'),definitions,(parent,child)):
            report=evaluate_granular_predicates(definition,values)
            cohort,reason=_granular_assign('other_outcomes',False,True,report)
            actual='unavailable' if reason=='unavailable_requested_evidence' else 'common_mismatch' if reason=='common_condition_mismatch' else cohort
            rows.append(dict(id=identity,stage=stage,expected=expected,actual=actual,purposes=report['purposes']))
    return rows


@pytest.mark.parametrize('identity',[r[0] for r in POPULATION])
def test_hand_counted_assignment_literals(identity):
    rows=[r for r in hand_vectors() if r['id']==identity]
    assert len(rows)==2 and all(r['actual']==r['expected'] for r in rows)


def test_acceptance_population_counts_reset_and_additional_unavailable_case():
    from collections import Counter
    rows=hand_vectors()
    assert Counter(r['actual'] for r in rows if r['stage']=='parent')=={'target':3,'comparison':5,'unavailable':1}
    assert Counter(r['actual'] for r in rows if r['stage']=='child')=={'target':2,'comparison':4,'common_mismatch':2,'unavailable':1}
    assert hand_vectors()==rows
    outcome=quantity(unit='pct',minimum=3)
    common=quantity('duration','structural','bars',minimum=12,maximum=30)
    definition=spec(outcome,common=(Group(conditions=(common,)),))
    result=evaluate_granular_predicates(definition,{outcome.measurement_key:ResolvedFilterValue(unavailable_reason='saved_metric_missing'),
                                                  common.measurement_key:ResolvedFilterValue(70)})
    assert result['purposes']=={'common':'mismatch','outcome':'unavailable'}
    assert result['status']=='unavailable'
    assert _granular_assign('other_outcomes',False,True,result)==('excluded','unavailable_requested_evidence')


@pytest.fixture(scope='module',params=('other_families','other_outcomes','non_start'))
def population(request,tmp_path_factory):
    return make_case(tmp_path_factory.mktemp(request.param),comparison=request.param)


def assert_schema(report):
    assert set(report)=={'kind','report_id','root_id','set_id','source_discovery_id','source_request','legacy_filters_applied',
        'definition_id','definition','comparison','resolved_split_ms','records','samples','summary','accounting','scope'}
    assert report['kind']=='gr03-population-report-v1'
    assert report['scope']=='frozen_sources_and_population_only_not_rule_matching'
    assert not report['legacy_filters_applied']
    expected={'row_id','ordinary','anchor','anchor_ts_ms','family','scope_selected','mandatory_eligible','evaluation_scope',
        'predicate_report','scalar_ledger','source_resolution','cohort','reason','partition','partition_reason',
        'feature_start_ms','cutoff_ms','evidence_start_ms','evidence_end_ms'}
    for row in report['records']:
        assert set(row)==expected
        source=row['source_resolution']
        assert set(source)=={'status','compatible_providers','chosen_provider','rejected_witnesses','formation_bridge','temporal_rejections'}
        assert set(source['formation_bridge'])=={'used','carrier','formation_witnesses'}
        if source['chosen_provider']:assert set(source['chosen_provider'])=={'artifact_id','report_sha256','episode_id'}
        assert [v['measurement_key'] for v in row['scalar_ledger']]==sorted(v['measurement_key'] for v in row['scalar_ledger'])
        for value in row['scalar_ledger']:
            assert set(value)=={'measurement_key','selectors','known','value','unavailable_reason','source'}
            assert set(value['selectors'])=={'domain','field','unit','basis','cohort','statistic','column','profile_id','offset'}
            assert set(value['source'])==({'kind','artifact_id','report_sha256','episode_id','basis','cohort','projection_reason','support_reason',
                'required_start_ms','required_end_ms','recognition_ms','available_at_ms','clock_basis','formation_bridge'} if value['source']['kind']=='utc_projection'
                else {'kind','column','profile_id','offset','row','ts_ms','measurement','ready_reference','available_at_ms','clock_basis','path_valid','support_reason'})
    for sample in report['samples']:
        assert set(sample)=={'event_id','anchor','cohort','ordinary','timing','evidence_start_ms','evidence_end_ms',
            'feature_start_ms','cutoff_ms','partition','partition_reason'}
    summary=report['summary']
    assert set(summary)=={'records_total','event_records','control_records','scope_excluded','mandatory_excluded','unavailable_requested',
        'known_filter_mismatch','target_total','comparison_total','cohort_excluded','by_cohort_partition'}
    assert summary['records_total']==len(report['records'])==summary['event_records']+summary['control_records']
    assert summary['cohort_excluded']==sum(summary[k] for k in ('scope_excluded','mandatory_excluded','unavailable_requested','known_filter_mismatch'))
    assert summary['target_total']+summary['comparison_total']+summary['cohort_excluded']==summary['records_total']
    assert len(summary['by_cohort_partition'])==6
    assert sum(r['count'] for r in summary['by_cohort_partition'])==len(report['samples'])
    assert len({r['row_id'] for r in report['records']})==len(report['records'])
    assert report['records']==sorted(report['records'],key=lambda r:(r['anchor_ts_ms'],r['row_id']))
    assert json.loads(json.dumps(report))==report


def test_real_population_assignment_common_symmetry_and_reset(population):
    frozen=population[0];comparison=frozen.original_request.comparison
    p=quantity(minimum=15 if comparison=='other_outcomes' else 10)
    definition=spec(p)
    original=resolve_granular_population(frozen,definition);assert_schema(original)
    assert original['summary']['target_total']>0 and original['summary']['comparison_total']>0
    column=frozen._root['columns']['delta']
    common=Predicate('column','raw_value','native',column='delta',profile_id=column['profile_id'],offset=-4,minimum=3,maximum=7)
    child=resolve_granular_population(frozen,spec(p,common=(Group(conditions=(common,)),)))
    assert_schema(child)
    for row,value in ledger(child,'column'):
        if row['cohort']!='excluded':assert value['known'] and Decimal(3)<=Decimal(value['value'])<=Decimal(7)
    restored=resolve_granular_population(frozen,definition)
    assert restored==original and child['report_id']!=original['report_id']
    if comparison=='non_start':
        controls=[r for r in child['records'] if r['ordinary']]
        assert controls and all(r['family'] is None and r['source_resolution']['status']=='not_applicable' for r in controls)
        assert all(r['evaluation_scope']=='common_only_for_ordinary_control' for r in controls)
        common_id=Definition(common=(Group(conditions=(common,)),)).identity
        assert all(r['predicate_report']['definition_id']==common_id and r['predicate_report']['purposes']['outcome']=='inactive' for r in controls)
        starts={e['anchor_ts_ms'] for e in json.loads(frozen._root['instance'])['events']}
        assert not starts&{r['anchor_ts_ms'] for r in controls}
        assert all(v['selectors']['domain']=='column' for r in controls for v in r['scalar_ledger'])
    if comparison=='other_outcomes':
        assert any(r['reason']=='fails_outcome_definition' for r in original['records'])
        assert any(r['reason']=='unavailable_requested_evidence' for r in original['records'])
        assert all(r['predicate_report'] is None for r in original['records'] if not r['scope_selected'])


def test_legacy_filters_are_provenance_and_all_candidates_restore(tmp_path):
    frozen,*_=make_case(tmp_path,comparison='other_outcomes',legacy=movement(minimum=35))
    permissive=resolve_granular_population(frozen,spec(quantity(minimum=0)))
    strict=resolve_granular_population(frozen,spec(quantity(minimum=35)))
    assert permissive['summary']['target_total']>strict['summary']['target_total']
    assert permissive['source_request']['refinement']==frozen.original_request.refinement.to_dict()
    assert resolve_granular_population(frozen,spec(quantity(minimum=0)))==permissive
    assert frozen.original_request.refinement==movement(minimum=35)


@pytest.mark.parametrize('operator',('ALL','ANY'))
def test_unknown_outcome_survives_common_mismatch_and_pass_branch(tmp_path,operator):
    frozen,*_=make_case(tmp_path,comparison='other_outcomes')
    profile=frozen._root['columns']['delta']['profile_id']
    common=Predicate('column','raw_value','native',column='delta',profile_id=profile,offset=-1,minimum=999)
    known_pass=replace(common,minimum=0)
    definition=Definition(common=(Group(conditions=(common,)),),outcome=(Group(operator,(quantity(),known_pass)),))
    result=resolve_granular_population(frozen,definition)
    unknown=[r for r in result['records'] if r['predicate_report'] and r['predicate_report']['purposes']['outcome']=='unavailable']
    assert unknown
    for row in unknown:
        assert row['predicate_report']['purposes']['common']=='mismatch'
        assert row['cohort']=='excluded' and row['reason']=='unavailable_requested_evidence'
        assert len(row['predicate_report']['predicates'])==3


@pytest.mark.parametrize('domain',('movement','duration','pullbacks','context','outcome_context'))
def test_nonstart_rejects_unsupported_requirements_before_source(tmp_path,domain,monkeypatch):
    frozen,*_=make_case(tmp_path,comparison='non_start')
    p={'movement':quantity(),'duration':quantity('duration','structural','bars'),
       'pullbacks':quantity('pullbacks','count','count',cohort='internal_recovered'),
       'context':Predicate('context','up','boolean',allowed=(True,)),
       'outcome_context':Predicate('context','up','boolean',allowed=(False,))}[domain]
    definition=spec(p) if domain=='outcome_context' else Definition(common=(Group(conditions=(p,)),))
    import leonardo.analysis.pattern_refinement as engine
    monkeypatch.setattr(engine,'build_cohorts',lambda *a,**k:pytest.fail('unsupported condition reached source work'))
    with pytest.raises(ValueError,match='non_start'):resolve_granular_population(frozen,definition)


@pytest.mark.parametrize('vector',CHRONOLOGY)
def test_literal_chronology_boundaries(vector):
    from types import SimpleNamespace
    start,cutoff,evidence_start,evidence_end,expected=vector
    request=SimpleNamespace(pre_event=SimpleNamespace(offsets=(-2,-1),lead=1,chronological=True))
    sample=dict(anchor=2,evidence_start_ms=evidence_start,evidence_end_ms=evidence_end)
    partition_sample(sample,dict(timestamps=(start,cutoff,cutoff+1)),request,1000)
    assert sample['partition']==expected


def test_added_stored_column_clock_extends_actual_interval_across_split(tmp_path):
    frozen,*_=append_case(tmp_path,chronological=True)[1]
    baseline=resolve_granular_population(frozen,spec(quantity()))
    column=frozen._root['columns']['delta']
    predicate=Predicate('column','raw_value','native',column='delta',profile_id=column['profile_id'],offset=-1,minimum=0)
    child=resolve_granular_population(frozen,spec(quantity(),predicate))
    a=next(r for r in baseline['records'] if r['anchor']==7);b=next(r for r in child['records'] if r['anchor']==7)
    assert a['partition']=='discovery' and a['evidence_end_ms']<frozen.resolved_split
    assert b['cohort']=='target' and b['partition']=='excluded'
    assert b['evidence_end_ms']==int(column['frame'].iloc[6].available_at_ms)>frozen.resolved_split
    assert b['partition_reason']=='feature_or_evidence_crosses_split'


def test_context_uses_same_carrier_snapshot_without_fabricated_anchor_clock(tmp_path):
    frozen,*_=append_case(tmp_path,chronological=True)[0]
    definition=spec(quantity(),Predicate('context','previous_direction','category',allowed=('NONE',)))
    report=resolve_granular_population(frozen,definition)
    row=next(r for r in report['records'] if r['anchor']==7)
    context=next(v for v in row['scalar_ledger'] if v['selectors']['domain']=='context')
    assert context['known'] and context['value']=='NONE'
    assert context['source']['artifact_id']==row['source_resolution']['chosen_provider']['artifact_id']
    assert row['evidence_end_ms']==context['source']['available_at_ms']>frozen.resolved_split
    assert row['partition']=='excluded'


@pytest.mark.parametrize('limit',(0,-1,True,1.5,'100',134217729))
def test_invalid_memory_limits(population,limit):
    with pytest.raises(ValueError,match='memory limit'):resolve_granular_population(population[0],spec(quantity()),memory_limit_bytes=limit)


def test_exact_payload_limit_and_report_detachment(population):
    frozen=population[0];definition=spec(quantity());report=resolve_granular_population(frozen,definition)
    size=len(_json({k:v for k,v in report.items() if k!='accounting'}).encode('utf-8'))
    assert report['accounting']['retained_payload_bytes']==size
    exact=resolve_granular_population(frozen,definition,memory_limit_bytes=size)
    assert exact['report_id']==report['report_id'] and exact['accounting']['retained_payload_bytes']==size
    with pytest.raises(ValueError,match='granular_payload_limit'):resolve_granular_population(frozen,definition,memory_limit_bytes=size-1)
    saved=deepcopy(report);report['records'][0]['source_resolution']['compatible_providers'].clear();report['definition'].clear();report['samples'].clear()
    assert resolve_granular_population(frozen,definition)==saved
    assert saved['report_id']==_hash(('gr03-population-v1',frozen.set_id,definition.identity))


@pytest.mark.parametrize('where',('entry','copy','axis','field','return'))
def test_cancellation_has_no_partial_publication_and_retry(tmp_path,where):
    frozen,*_=make_case(tmp_path,comparison='non_start');definition=spec(quantity())
    before=frozen.metadata();source=frozen._root['instance'];frames={n:c['frame'].copy(deep=True) for n,c in frozen._root['columns'].items()}
    calls=[];expected=resolve_granular_population(frozen,definition,checkpoint=lambda:calls.append(True))
    target={'entry':1,'copy':3,'axis':5,'field':len(calls)//2,'return':len(calls)}[where]
    count=0;published=[]
    class Stop(Exception):pass
    def checkpoint():
        nonlocal count
        count+=1
        if count==target:raise Stop('cancel')
    with pytest.raises(Stop):published.append(resolve_granular_population(frozen,definition,checkpoint=checkpoint))
    assert not published and frozen.metadata()==before and frozen._root['instance']==source
    for n,frame in frames.items():pd.testing.assert_frame_equal(frozen._root['columns'][n]['frame'],frame,check_exact=True)
    assert resolve_granular_population(frozen,definition)==expected


def test_no_mining_calculation_persistence_or_live_submission(population,monkeypatch):
    import leonardo.analysis.pattern_refinement as engine
    import leonardo.analysis.pre_event_patterns as mining
    import leonardo.analysis.service as service
    import leonardo.financial_tools as financial
    from leonardo.data_manager.creation_store import DataManagerCreationStore
    from leonardo.analysis.application import AnalysisApplicationService
    def forbidden(*a,**k):pytest.fail('source-to-population crossed a forbidden workflow boundary')
    for module,names in ((engine,('pin_patterns','evaluate_patterns','observe','_counts_for_masks')),(mining,('mine',)),
        (service,('fit_directional_binning','classify_directional_binning','fit_dynamic_binning','classify_dynamic_binning')),
        (financial,('calculate_financial_tool',)),(DataManagerCreationStore,('load_database_revision','publish_database_revision'))):
        for name in names:monkeypatch.setattr(module,name,forbidden)
    for name in dir(AnalysisApplicationService):
        if name.startswith('submit'):monkeypatch.setattr(AnalysisApplicationService,name,forbidden)
    for name in ('run','load_columns','load_utc_classification','load_pattern_catalogue','run_patterns','pattern_matches',
                 'pin_pattern_set','evaluate_pattern_set'):
        monkeypatch.setattr(service.AnalysisService,name,forbidden)
    from PySide6.QtWidgets import QWidget
    for name in ('show','setVisible'):
        monkeypatch.setattr(QWidget,name,forbidden)
    original=engine.build_cohorts;calls=[]
    def build(*a,**k):calls.append(True);return original(*a,**k)
    monkeypatch.setattr(engine,'build_cohorts',build)
    report=resolve_granular_population(population[0],spec(quantity()))
    assert calls==[True] and report['records']


def test_wrong_types_legacy_api_and_progress_errors(population):
    frozen=population[0]
    for first,second in ((None,Definition()),(frozen,{}),(frozen,PatternRefinement())):
        with pytest.raises(TypeError):resolve_granular_population(first,second)
    with pytest.raises(TypeError):evaluate_patterns(frozen,Definition())
    class Stop(Exception):pass
    def progress(*args):raise Stop('progress callback')
    with pytest.raises(Stop):resolve_granular_population(frozen,spec(quantity()),progress=progress)
    if frozen.original_request.comparison=='other_outcomes':
        with pytest.raises(ValueError,match='active outcome'):resolve_granular_population(frozen,Definition())
    inactive=spec(replace(quantity(),enabled=False))
    if frozen.original_request.comparison!='other_outcomes':
        report=resolve_granular_population(frozen,inactive)
        assert all(not r['scalar_ledger'] for r in report['records'])


@pytest.mark.parametrize('phase',('carrier','field','axis128'))
def test_cancellation_at_actual_source_traversal_points(population,phase):
    import sys
    frozen=population[0];definition=spec(quantity());expected=resolve_granular_population(frozen,definition)
    hit=[]
    class Stop(Exception):pass
    def checkpoint():
        caller=sys._getframe(1)
        function=caller.f_code.co_name
        should_stop=(phase=='carrier' and function=='_refinement_resolve_saved' and 'witness' in caller.f_locals
            or phase=='field' and function=='resolve_granular_population' and 'key' in caller.f_locals
            or phase=='axis128' and function=='resolve_granular_population' and caller.f_locals.get('index')==128)
        if should_stop:hit.append(function);raise Stop(phase)
    with pytest.raises(Stop):resolve_granular_population(frozen,definition,checkpoint=checkpoint)
    assert len(hit)==1 and resolve_granular_population(frozen,definition)==expected
