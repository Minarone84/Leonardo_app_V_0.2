"""GR-03B genuine pinned-source resolution and extraction parity."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.pattern_models import PatternRefinement,PreEventSpec,PrecedingContextFilter,NumericCondition
from leonardo.analysis.refinement_models import GranularPredicate as Predicate,GranularGroup as Group,GranularRefinement as Definition
from leonardo.analysis.pattern_refinement import pin_patterns,resolve_granular_population
from leonardo.analysis.trend_start_patterns import build_catalogue,run_study,analysis_key,refine_event,_refinement_resolve_saved,_refinement_scalar
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture
from tests.analysis_test.test_trend_start_enrichment import ENDED,STANDARD,enriched_fixture,saved_analysis,bundle_for,movement,first_event
from tests.analysis_test.test_pre_event_pattern_stability import _reviewed_append_fixture
from tests.financial_tools_test.test_utc_classification import CASES


def quantity(domain='movement',field='directional_move',unit='points',basis='completed',minimum=0,**kwargs):
    return Predicate(domain,field,unit,basis=basis,minimum=minimum,**kwargs)


def spec(*predicates,common=(),operator='ALL'):
    return Definition(common=tuple(common),outcome=(Group(operator,tuple(predicates)),) if predicates else ())


def pin_inputs(parent,catalogue,axis,request):
    request=replace(request,run_key=catalogue.run_key,min_matches=1)
    study=run_study(parent,catalogue,request,axis)
    assert not study.frame('patterns').empty
    frozen=pin_patterns(parent,catalogue,study,study.frame('patterns').pattern_id.tolist()[:4])
    return frozen,parent,catalogue,axis,request


def make_case(tmp_path,*,comparison='other_families',mirror=False,mode='directional_intensity',known=True,
              legacy=None,chronological=False,transform=None):
    alternate=CASES[2]+(('T',108),('P',112),('T',104),('P',120))
    sequences=(ENDED,tuple((k,100+(v-100)*2) for k,v in ENDED),tuple((k,100+(v-100)*.5) for k,v in ENDED),STANDARD,alternate,alternate)
    parent,cat,axis,request,store,manifest,bundle=planted_fixture(tmp_path,sequences=sequences,mirror=mirror,known=known,measurement=mode)
    request=replace(request,comparison=comparison,refinement=legacy or (movement() if comparison=='other_outcomes' else PatternRefinement()),
        pre_event=replace(request.pre_event,chronological=chronological,split_ms=axis[30] if chronological else None))
    if transform is not None:parent,cat,axis,request=transform(parent,cat,axis,request,store,manifest,bundle)
    return pin_inputs(parent,cat,axis,request)


def append_case(tmp_path,mirror=False,fault=None,chronological=False):
    parent,catalogues,axis,request=_reviewed_append_fixture(tmp_path,mirror=mirror,fault=fault)
    request=replace(request,refinement=PatternRefinement(),pre_event=replace(request.pre_event,
        chronological=chronological,split_ms=request.pre_event.split_ms if chronological else None))
    return [pin_inputs(parent,c,axis,request) for c in catalogues]


@pytest.fixture(scope='module')
def genuine(tmp_path_factory):
    return make_case(tmp_path_factory.mktemp('gr03b_source'))


def ledger(report,domain=None):
    return [(r,v) for r in report['records'] for v in r['scalar_ledger'] if domain is None or v['selectors']['domain']==domain]


@pytest.mark.parametrize('basis',('completed','formation','observed'))
def test_saved_values_all_fields_and_scalar_support(genuine,basis):
    frozen,_,catalogue,_,_=genuine
    predicates=[quantity(basis=basis),quantity(field='signed_move',basis=basis),quantity('duration','structural','bars',basis),
        quantity('pullbacks','count','count',basis,cohort='internal_recovered'),
        quantity('pullbacks','depth','points',basis,cohort='internal_recovered',statistic='mean'),
        quantity('pullbacks','recovered_duration','bars',basis,cohort='internal_recovered',statistic='mean')]
    report=resolve_granular_population(frozen,spec(*predicates))
    events={e['event_id']:e for e in catalogue.instance('logical')['events']}
    checked=0
    for row,value in ledger(report):
        if not value['known']:continue
        source=value['source'];w=next(w for w in events[row['row_id']]['witnesses'] if w['artifact_id']==source['artifact_id'])
        projection=w['measurement_projections'][basis]['projection'];selectors=value['selectors']
        if selectors['domain']=='movement':expected=projection['structural']['movement'][selectors['field']+'_'+selectors['unit']]
        elif selectors['domain']=='duration':expected=projection['structural']['duration']['bars']
        else:
            summary=projection['pullback_summary']['internal_recovered'];field=selectors['field']
            expected=summary['count'] if field=='count' else summary[field+'_'+selectors['unit']][selectors['statistic']]
        assert Decimal(value['value'])==Decimal(str(expected));checked+=1
    assert checked>=18


def test_threshold_and_cross_purpose_placement_cannot_choose_provider(genuine,monkeypatch):
    frozen=genuine[0];a=quantity(basis='formation');b=quantity()
    first=resolve_granular_population(frozen,spec(b,common=(Group(conditions=(a,)),)))
    second=resolve_granular_population(frozen,spec(replace(b,minimum=999),common=(Group(conditions=(a,)),)))
    assert [r['source_resolution'] for r in first['records']]==[r['source_resolution'] for r in second['records']]
    import leonardo.analysis.trend_start_patterns as trend
    original=trend._refinement_scalar;calls=[]
    def read_once(*args,**kwargs):calls.append(kwargs);return original(*args,**kwargs)
    monkeypatch.setattr(trend,'_refinement_scalar',read_once)
    repeated=spec(b,replace(b,minimum=1),common=(Group(conditions=(b,)),))
    report=resolve_granular_population(frozen,repeated)
    assert len(calls)==sum(bool(r['scalar_ledger']) and r['source_resolution']['status']=='resolved' for r in report['records'])
    assert all(r['predicate_report']['cross_purpose_predicates']==[b.predicate_key] for r in report['records'] if r['predicate_report'])


@pytest.mark.parametrize('mirror',(False,True),ids=('UP','DOWN'))
def test_reviewed_prefix_mixed_basis_bridge_matches_full_provider(tmp_path,mirror):
    cases=append_case(tmp_path,mirror=mirror)
    definition=spec(quantity(basis='formation'),quantity())
    reports=[resolve_granular_population(c[0],definition) for c in cases]
    rows=[next(r for r in report['records'] if r['anchor']==7) for report in reports]
    assert all(r['cohort']=='target' and r['source_resolution']['status']=='resolved' for r in rows)
    assert [(r['evidence_start_ms'],r['evidence_end_ms']) for r in rows]==[(1700000420000,1700001320000)]*2
    assert [v['value'] for v in rows[0]['scalar_ledger']]==[v['value'] for v in rows[1]['scalar_ledger']]
    bridge=rows[1]['source_resolution']['formation_bridge']
    assert bridge['used'] and bridge['carrier']['artifact_id']=='new'
    assert [w['artifact_id'] for w in bridge['formation_witnesses']]==['old']
    formation=next(v for v in rows[1]['scalar_ledger'] if v['selectors']['basis']=='formation')
    assert formation['source']['projection_reason']=='decision_outside_provider_coverage'
    assert formation['source']['clock_basis']=='formation_via_verified_completed_prefix'
    event=next(e for e in cases[1][2].instance('logical')['events'] if e['anchor_ts_ms']==1700000420000)
    legacy=refine_event(event,movement('formation'))
    assert [p['artifact_id'] for p in legacy['providers']]==['old']


@pytest.mark.parametrize('fault',('missing_formation_row','missing_outcome_row','unknown_formation','unknown_outcome','incomplete_prefix','conflicting_prefix'))
def test_real_append_faults_cannot_use_bridge(tmp_path,fault):
    case=append_case(tmp_path,fault=fault)[1]
    report=resolve_granular_population(case[0],spec(quantity(basis='formation'),quantity()))
    row=next(r for r in report['records'] if r['anchor_ts_ms']==1700000420000)
    assert not row['source_resolution']['formation_bridge']['used']
    assert row['cohort']=='excluded' or row['evidence_end_ms'] is None


@pytest.mark.parametrize('mode',('directional_intensity','value','magnitude'))
def test_columns_read_exact_absolute_rows_in_all_modes(tmp_path,mode):
    frozen,*_=make_case(tmp_path,mode=mode)
    column=frozen._root['columns']['delta'];p=Predicate('column','raw_value','native',column='delta',profile_id=column['profile_id'],offset=-4,minimum=0)
    token=next(t for t in column['tokens'] if t is not None)
    label=replace(p,field='label',unit='label',minimum=None,allowed=(token,))
    result=resolve_granular_population(frozen,spec(p,label))
    for row,value in ledger(result,'column'):
        position=row['anchor']-4;source=value['source']
        assert source['row']==position and source['ts_ms']==frozen._root['timestamps'][position]
        if value['selectors']['field']=='raw_value':assert Decimal(value['value'])==Decimal(str(column['frame'].iloc[position].raw_value))
        else:assert value['value']==column['tokens'][position]
        assert source['clock_basis']=='stored_observation'
        assert source['available_at_ms']==int(column['frame'].iloc[position].available_at_ms)


def test_extra_analyzed_column_raw_without_profile_and_exact_zero(tmp_path):
    from leonardo.analysis.service import AnalysisService
    from tests.analysis_test.test_analysis_service import request as bin_request
    def transform(parent,cat,axis,request,store,manifest,bundle):
        parent=AnalysisService(store).run(bin_request(manifest,'delta','volume_change','close'))
        extra=replace(parent.columns[-1],profile=None)
        frames=[]
        for c in parent.columns[:2]:
            frame=c.to_frame();frame.loc[3,'raw_value']=0.;frame.loc[3,'status']='zero_value'
            frame.loc[3,'bin_label']=None;frames.append(replace(c,_frame=frame))
        parent=replace(parent,columns=(*frames,extra))
        return parent,build_catalogue(parent,bundle,axis),axis,replace(request,run_key=analysis_key(parent))
    frozen,*_=make_case(tmp_path,transform=transform)
    assert 'close' not in frozen.original_request.columns and frozen._root['columns']['close']['profile_id'] is None
    raw=Predicate('column','raw_value','native',column='close',offset=-1,minimum=0)
    label=Predicate('column','label','label',column='delta',profile_id=frozen._root['columns']['delta']['profile_id'],offset=-4,allowed=('Zero',))
    report=resolve_granular_population(frozen,spec(raw,label))
    first=next(r for r in report['records'] if r['anchor']==7)
    assert next(v for v in first['scalar_ledger'] if v['selectors']['field']=='label')['value']=='Zero'
    assert next(v for v in first['scalar_ledger'] if v['selectors']['column']=='close')['known']


@pytest.mark.parametrize('fault',('nan','inf','missing_label','snapshot','unknown_clock'))
def test_stored_column_absence_and_clock_provenance(tmp_path,fault):
    def transform(parent,cat,axis,request,store,manifest,bundle):
        columns=[]
        for column in parent.columns:
            frame=column.to_frame()
            if column.request.source=='delta':
                if fault in ('nan','inf'):frame.loc[3,'raw_value']=np.nan if fault=='nan' else np.inf
                if fault=='missing_label':frame.loc[3,'bin_label']=None
                if fault in ('snapshot','unknown_clock'):frame['available_at_ms']=None
            columns.append(replace(column,_frame=frame))
        parent=replace(parent,columns=tuple(columns),snapshot_read_ms=None if fault=='unknown_clock' else parent.snapshot_read_ms)
        return parent,build_catalogue(parent,bundle,axis),axis,replace(request,run_key=analysis_key(parent))
    frozen,*_=make_case(tmp_path,transform=transform)
    p=Predicate('column','raw_value','native',column='delta',profile_id=frozen._root['columns']['delta']['profile_id'],offset=-4,minimum=0)
    if fault=='missing_label':p=replace(p,field='label',unit='label',minimum=None,allowed=('P01',))
    row=next(r for r in resolve_granular_population(frozen,spec(p))['records'] if r['anchor']==7)
    value=row['scalar_ledger'][0]
    if fault in ('nan','inf','missing_label'):assert not value['known'] and row['cohort']=='excluded'
    else:
        assert value['known']
        assert value['source']['clock_basis']==('unknown' if fault=='unknown_clock' else 'snapshot_read_only')
        if fault=='unknown_clock':assert row['evidence_end_ms'] is None


@pytest.mark.parametrize('fault',('profile','offset','column'))
def test_context_binding_rejects_before_source_work(genuine,fault,monkeypatch):
    p=Predicate('column','raw_value','native',column='delta',profile_id=genuine[0]._root['columns']['delta']['profile_id'],offset=-1,minimum=0)
    p=replace(p,**{'profile':{'profile_id':'foreign'},'offset':{'offset':-199},'column':{'column':'foreign'}}[fault])
    import leonardo.analysis.pattern_refinement as engine
    monkeypatch.setattr(engine,'build_cohorts',lambda *a,**k:pytest.fail('source iteration before context rejection'))
    with pytest.raises(ValueError):resolve_granular_population(genuine[0],spec(p))


@pytest.mark.parametrize('fault',('ambiguous','joint','legacy_prefix','context_excluded'))
def test_genuine_tuple_compatibility_before_bounds(tmp_path,fault):
    parent,_,axis,full,frame=enriched_fixture(tmp_path,ENDED)
    earlier=frame.iloc[:12].copy()
    if fault=='joint':
        # A real quiet interval allows the older observed projection to be
        # available before the later break; the old outcome is still open.
        frame.loc[17,'trough_fractal_5']=frame.loc[13,'trough_fractal_5']
        frame.loc[13,'trough_fractal_5']=np.nan
        frame.loc[19,'peak_fractal_5']=frame.loc[15,'peak_fractal_5']
        frame.loc[15,'peak_fractal_5']=np.nan
        full=saved_analysis(frame);earlier=frame.iloc[:17].copy()
    if fault=='context_excluded':earlier.loc[0,'high']=201
    old=saved_analysis(earlier)
    rows=[('old',old,axis[0],axis[len(earlier)-1]),('new',full,axis[0],axis[-1])]
    if fault=='ambiguous':
        changed=frame.copy();changed.loc[4,'high']=201
        rows=[('old',saved_analysis(changed),axis[0],axis[-1]),rows[1]]
    if fault=='legacy_prefix':rows=[('old',{'utc_classification':old['utc_classification']},axis[0],axis[11]),('new',full,axis[12],axis[-1])]
    if fault=='context_excluded':rows=[('old',old,axis[1],axis[11]),rows[1]]
    event=first_event(build_catalogue(parent,bundle_for(parent,rows),axis))
    bases=('completed','observed') if fault=='joint' else ('completed','formation') if fault=='legacy_prefix' else ('completed',)
    result=_refinement_resolve_saved(event,bases=bases,membership=fault=='context_excluded',lineage=False,positions={t:i for i,t in enumerate(axis)})
    if fault=='ambiguous':assert result['resolution']=='ambiguous_saved_measurements'
    elif fault=='legacy_prefix':assert result['resolution']=='unavailable'
    else:
        assert result['resolution']=='resolved' and [p['artifact_id'] for p in result['providers']]==['new']
        if fault=='joint':assert _refinement_resolve_saved(event,bases=('observed',),membership=False,lineage=False)['resolution']=='ambiguous_saved_measurements'


@pytest.mark.parametrize('sequence,field,cohort,statistic,expected_reason',(
    ((('T',-10),('P',0),('T',-5),('P',5),('T',0),('P',10)),'depth','all_observed','mean','partial_pullback_statistic_support'),
    ((('T',100),('P',110),('P',115)),'depth','internal_recovered','mean','empty_or_unavailable_pullback_statistic'),
))
def test_saved_scalar_support_does_not_recompute(tmp_path,sequence,field,cohort,statistic,expected_reason):
    _,catalogue,_,_,_=enriched_fixture(tmp_path,sequence)
    event=first_event(catalogue);resolved=_refinement_resolve_saved(event,bases=('observed',),membership=True,lineage=True)
    selected,_,witness,_=resolved['candidates'][0]
    value,reason=_refinement_scalar(selected,witness,domain='pullbacks',field=field,unit='pct',basis='observed',cohort=cohort,statistic=statistic)
    assert value is None and reason==expected_reason
    value,reason=_refinement_scalar(selected,witness,domain='context',field='previous_direction',unit='category')
    assert value=='NONE' and not reason
    count,_=_refinement_scalar(selected,witness,domain='pullbacks',field='count',unit='count',basis='observed',cohort='internal_recovered')
    if len(sequence)==3:assert count==0
    else:
        assert _refinement_scalar(selected,witness,domain='movement',field='directional_move',unit='points',basis='observed')==(20.0,'')
        value,reason=_refinement_scalar(selected,witness,domain='movement',field='directional_move',unit='pct',basis='observed')
        assert value is None and reason=='nonpositive_reference_price'


@pytest.mark.parametrize('first',('trend_start_patterns','pattern_refinement'))
def test_cold_imports_and_frozen_root_exports(first,tmp_path):
    second='pattern_refinement' if first=='trend_start_patterns' else 'trend_start_patterns'
    code=f'import importlib; importlib.import_module("leonardo.analysis.{first}"); importlib.import_module("leonardo.analysis.{second}"); import leonardo.analysis as root; assert not hasattr(root,"resolve_granular_population")'
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=tmp_path,env=os.environ.copy(),capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('fault',('gap','history_and_segment','ordinary_coverage'))
def test_column_paths_never_cross_actual_missing_coverage(tmp_path,fault):
    def transform(parent,cat,axis,request,store,manifest,bundle):
        if fault=='gap':
            missing=axis[3];axis=tuple(t for t in axis if t!=missing)
            parent=replace(parent,columns=tuple(replace(c,_frame=c.to_frame().loc[lambda f:f.ts_ms!=missing].reset_index(drop=True)) for c in parent.columns))
            cat=build_catalogue(parent,bundle,axis)
        elif fault=='history_and_segment':request=replace(request,pre_event=replace(request.pre_event,history=10))
        else:
            analysis=next(iter(bundle.to_dict()['reports'].values()))
            from tests.financial_tools_test.test_utc_classification import _frame
            unknown=saved_analysis(_frame((),tail=3),known=False)
            inputs=[('unknown_prefix',unknown,axis[0],axis[2]),('one',analysis,axis[3],axis[-1])]
            cat=build_catalogue(parent,bundle_for(parent,inputs),axis)
        return parent,cat,axis,replace(request,run_key=analysis_key(parent))
    frozen,*_=make_case(tmp_path,comparison='non_start' if fault=='ordinary_coverage' else 'other_families',transform=transform)
    offset={'gap':-4,'history_and_segment':-9,'ordinary_coverage':-1}[fault]
    predicate=Predicate('column','raw_value','native',column='delta',profile_id=frozen._root['columns']['delta']['profile_id'],offset=offset,minimum=0)
    report=resolve_granular_population(frozen,Definition(common=(Group(conditions=(predicate,)),)))
    anchor={'gap':6,'history_and_segment':7,'ordinary_coverage':3}[fault]
    row=next(r for r in report['records'] if r['anchor']==anchor)
    assert row['cohort']=='excluded' and row['reason']=='unavailable_requested_evidence'
    value=row['scalar_ledger'][0]
    assert not value['known'] and not value['source']['path_valid']
    if fault=='ordinary_coverage':assert value['unavailable_reason']=='ordinary_control_path_unavailable'
    if fault=='history_and_segment':
        assert value['source']['row'] is None
        segment=next(r for r in report['records'] if r['anchor']==37)
        assert segment['scalar_ledger'][0]['source']['row']==28
        assert segment['scalar_ledger'][0]['unavailable_reason']=='column_path_unavailable'


def test_repeated_imported_aliases_do_not_duplicate_events(tmp_path):
    def transform(parent,cat,axis,request,store,manifest,bundle):
        analysis=next(iter(bundle.to_dict()['reports'].values()))
        rows=[('one',analysis,axis[0],axis[-1]),('alias',analysis,axis[0],axis[-1]),('one',analysis,axis[0],axis[-1])]
        return parent,build_catalogue(parent,bundle_for(parent,rows),axis),axis,request
    frozen,_,catalogue,*_=make_case(tmp_path,transform=transform)
    report=resolve_granular_population(frozen,spec(quantity(basis='formation')))
    assert len(report['records'])==len([e for e in catalogue.instance('logical')['events'] if e['direction']=='UP'])
    assert len({r['row_id'] for r in report['records']})==len(report['records'])
    assert all(len(r['source_resolution']['compatible_providers'])==2 for r in report['records'] if r['predicate_report'])


def test_fractional_saved_mean_and_boolean_false_are_known(tmp_path):
    sequence=(('T',100),('P',110),('T',105),('P',120),('T',112),('P',118),('T',114),('P',125))
    parent,_,axis,_,frame=enriched_fixture(tmp_path,sequence)
    frame.loc[16,'peak_fractal_5']=frame.loc[15,'peak_fractal_5'];frame.loc[15,'peak_fractal_5']=np.nan
    analysis=saved_analysis(frame)
    event=first_event(build_catalogue(parent,bundle_for(parent,[('one',analysis,axis[0],axis[-1])]),axis))
    result=_refinement_resolve_saved(event,bases=('observed',),membership=True,lineage=True)
    selected,_,witness,_=result['candidates'][0]
    value,reason=_refinement_scalar(selected,witness,domain='pullbacks',field='recovered_duration',unit='bars',basis='observed',cohort='internal_recovered',statistic='mean')
    assert value==6.5 and not reason
    assert value==selected['measurements']['observed']['pullback_summary']['internal_recovered']['recovered_duration_bars']['mean']
    assert _refinement_scalar(selected,witness,domain='context',field='up',unit='boolean')==(False,'')
    assert _refinement_scalar(selected,witness,domain='context',field='previous_family',unit='category')==('NONE','')


def test_missing_saved_context_is_not_none_lineage(tmp_path):
    parent,_,axis,analysis,_=enriched_fixture(tmp_path,ENDED)
    catalogue=build_catalogue(parent,bundle_for(parent,[('one',analysis,axis[7],axis[-1])]),axis)
    event=next(e for e in catalogue.instance('logical')['events'] if e['direction']=='DOWN')
    result=_refinement_resolve_saved(event,bases=(),membership=True,lineage=True)
    selected,_,witness,_=result['candidates'][0]
    for field,unit in (('up','boolean'),('previous_direction','category')):
        value,reason=_refinement_scalar(selected,witness,domain='context',field=field,unit=unit)
        assert value is None and reason


def test_unknown_column_clock_preserves_scalar_but_excludes_chronology(tmp_path):
    def transform(parent,cat,axis,request,store,manifest,bundle):
        columns=[]
        for column in parent.columns:
            frame=column.to_frame();frame['available_at_ms']=None
            columns.append(replace(column,_frame=frame))
        parent=replace(parent,columns=tuple(columns),snapshot_read_ms=None)
        return parent,build_catalogue(parent,bundle,axis),axis,replace(request,run_key=analysis_key(parent))
    frozen,*_=make_case(tmp_path,chronological=True,transform=transform)
    p=Predicate('column','raw_value','native',column='delta',profile_id=frozen._root['columns']['delta']['profile_id'],offset=-1,minimum=0)
    report=resolve_granular_population(frozen,spec(p))
    rows=[r for r in report['records'] if r['predicate_report']]
    assert rows and all(r['scalar_ledger'][0]['known'] for r in rows)
    assert all(r['cohort']!='excluded' and r['partition']=='excluded' and r['partition_reason']=='unknown_feature_or_evidence_boundary' for r in rows)


@pytest.mark.parametrize('fault',('no_qualified_donor','different_formation'))
def test_bridge_cannot_repair_missing_donor_or_different_frozen_formation(tmp_path,fault):
    parent,_,axis,full,frame=enriched_fixture(tmp_path,ENDED)
    earlier=frame.iloc[:12].copy()
    if fault=='different_formation':earlier.loc[5,'trough_fractal_5']=104
    old=saved_analysis(earlier)
    inputs=[('old',old,axis[0],axis[8] if fault=='no_qualified_donor' else axis[11]),('new',full,axis[12],axis[-1])]
    if fault=='different_formation':
        with pytest.raises(ValueError,match='Conflicting frozen UTC formation'):build_catalogue(parent,bundle_for(parent,inputs),axis)
    else:
        from leonardo.analysis.trend_start_patterns import _refinement_formation_bridge
        event=first_event(build_catalogue(parent,bundle_for(parent,inputs),axis))
        assert not event['eligible']
        assert all(not _refinement_formation_bridge(event,w,('completed','formation'),{t:i for i,t in enumerate(axis)}) for w in event['witnesses'])


def test_frozen_pending_cohort_is_not_a_recovered_duration(tmp_path):
    sequence=(('T',100),('P',110),('T',120),('P',115),('P',122))
    _,catalogue,*_=enriched_fixture(tmp_path,sequence)
    result=_refinement_resolve_saved(first_event(catalogue),bases=('observed',),membership=False,lineage=False)
    selected,_,witness,_=result['candidates'][0]
    assert _refinement_scalar(selected,witness,domain='pullbacks',field='count',unit='count',basis='observed',cohort='formation_pending_at_boundary')==(1,'')
    value,reason=_refinement_scalar(selected,witness,domain='pullbacks',field='recovered_duration',unit='bars',basis='observed',cohort='formation_pending_at_boundary',statistic='mean')
    assert value is None and reason=='empty_or_unavailable_pullback_statistic'
