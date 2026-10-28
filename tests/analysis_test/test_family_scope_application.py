"""Fixed-scope publication, retained-source search and Core lifecycle evidence."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.pattern_models import FamilyScope, PatternRefinement, PreEventSpec
from leonardo.analysis.refinement_models import GranularRefinement as D, GranularPredicate as P, GranularGroup as G
from leonardo.analysis.pattern_refinement import pin_patterns, evaluate_granular_patterns
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_pattern_refinement_application import InlineRunner, execute, pin, evaluate
from tests.analysis_test.test_granular_application import search
from tests.analysis_test.test_family_scope_refinement import multi_case, count_oracle
from tests.analysis_test.test_analysis_application import wait_until
from tests.analysis_test.test_analysis_service import request as bin_request
from tests.analysis_test.test_trend_start_catalogue import study_request
from tests.analysis_test.test_refinement_outcomes import horizon


def revision_case(tmp_path, direction='UP', comparison='other_outcomes'):
    """Real OHLCV -> canonical P/T -> UTC -> immutable database, never patched events."""
    from leonardo.ohlcv.store import OHLCVStore, Candle
    from leonardo.data_manager import ArtifactCollectionOutputV1
    from tests.data_manager_test.test_update_workflow import _domain, MARKET
    from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
    from tests.data_manager_test.test_artifact_materialization import _utc_recipe
    from tests.analysis_test.test_trend_start_enrichment import movement
    domain,_,recipes,historical=_domain(tmp_path,initialize=False)
    rng=np.random.default_rng(731)
    close=1000+np.cumsum(rng.integers(-5,6,1200))
    high=close+rng.integers(1,9,len(close));low=close-rng.integers(1,9,len(close))
    candles=[Candle(1700000000000+i*60_000,float(c),float(h),float(l),float(c),1000.) for i,(c,h,l) in enumerate(zip(close,high,low))]
    owned=OHLCVStore(historical);owned.write(MARKET,candles,source='gr05-disposable',persistence_status='committed')
    csvpath,sidepath=owned.csv_path(MARKET),owned.sidecar_path(MARKET)
    owned.publish_validation(MARKET,expected_csv_size=csvpath.stat().st_size,expected_csv_mtime_ns=csvpath.stat().st_mtime_ns,
        expected_csv_sha256=sha256(csvpath.read_bytes()).hexdigest(),expected_sidecar_size=sidepath.stat().st_size,
        expected_sidecar_mtime_ns=sidepath.stat().st_mtime_ns,expected_sidecar_sha256=sha256(sidepath.read_bytes()).hexdigest(),
        status='ok',row_count=len(candles),first_timestamp_ms=candles[0].ts_ms,last_timestamp_ms=candles[-1].ts_ms,
        warnings=(),issue_codes=(),error_count=0,warning_count=0,validator='gr05-disposable')
    pt=_leaf('peaks_troughs',{});recipes.save_recipe(pt)
    utc=_utc_recipe(pt,trend_window=5,roles=('trend_peak','trend_trough','range_peak','range_trough'))
    materialized=_materialize(domain,recipes,utc)
    collection=domain.create_artifact_collection(materialized,'GR05 calculated UTC')
    seed=domain.create_database_seed(MARKET,'GR05 disposable multi-family')
    manifest=domain.build_database_revision(seed.seed_id,collection.collection_id)
    for period,name in ((3,'signal'),(30,'slow_signal')):
        recipe=_leaf('sma',{'period':period});materialized=_materialize(domain,recipes,recipe)
        addition=ArtifactCollectionOutputV1(materialized.root_logical_artifact_ids[0],recipe.output_names[0],name)
        plan=domain.plan_database_content_edit(manifest.database_id,artifact_additions=(addition,));assert not plan.blocked
        manifest=domain.execute_database_content_edit(plan)
    store=domain._creation.store;service=AnalysisService(store,clock_ms=lambda:1900000000000)
    parent=service.run(bin_request(manifest,'signal','slow_signal',minimum=2))
    catalogue=service.load_pattern_catalogue(parent);instance=catalogue.to_dict()['instances'][0]
    kind='T' if direction=='UP' else 'P'
    families=tuple(sorted(row['family'] for row in catalogue.families(instance['instance_id'],kind)))
    assert len(families)>=3
    ref=movement(minimum=0) if comparison=='other_outcomes' else PatternRefinement()
    scope=FamilyScope('all') if comparison!='other_families' else FamilyScope('selected',families[:2])
    req=replace(study_request(parent,catalogue,kind=kind,before=4,after=2,min_target=1,min_comparison=1,min_matches=1,
        pre_event=PreEventSpec(history=3,max_terms=2)),instance_id=instance['instance_id'],comparison=comparison,
        refinement=replace(ref,family_scope=scope))
    study=service.run_patterns(parent,req)
    assert not study.frame('patterns').empty
    frozen=pin_patterns(parent,catalogue,study,study.frame('patterns').pattern_id.tolist()[:6])
    return SimpleNamespace(domain=domain,store=store,service=service,parent=parent,catalogue=catalogue,study=study,frozen=frozen,
        request=req,manifest=manifest,families=families,
        loaded=store.load_database_revision(manifest.database_id,manifest.revision_id))


@pytest.fixture
def prepared(tmp_path):
    parent,cat,_,request,study,families=multi_case(tmp_path)
    from leonardo.data_manager.creation_store import DataManagerCreationStore
    domain=AnalysisService(DataManagerCreationStore(tmp_path/'empty_store'));app=AnalysisApplicationService(InlineRunner(),domain);session=app.begin_session()
    p=SimpleNamespace(parent=parent,catalogue=cat,study=study,domain=domain,app=app,session=session,
        ids=tuple(study.frame('patterns').pattern_id[:5]),families=families)
    yield p
    app.end_session(session)


def test_applied_and_original_scopes_history_search_and_repin(prepared,monkeypatch):
    p=prepared;frozen=pin(p);source_scope=frozen.original_request.refinement.family_scope
    narrowed=D(family_scope=FamilyScope('exact',[p.families[0]]))
    one=evaluate(p,narrowed);wide=evaluate(p,D(family_scope=FamilyScope('selected',p.families[:-1])))
    assert wide.parent_id==one.evaluation_id
    p.app.select_refinement_checkpoint(p.session,frozen.set_id,one.evaluation_id)
    assert evaluate(p,wide.granular_definition) is wide
    assert p.app.refinement_snapshot(p.session)['evaluation_count']==2
    inherited=evaluate(p,D())
    assert json.loads(inherited.context)['family_scope']['selected_families']==list(source_scope.families)
    monkeypatch.setattr(p.domain,'run_patterns',lambda *a,**k:pytest.fail('scoped search cannot read current store'))
    simple=search(p,PatternRefinement(family_scope=FamilyScope('exact',[p.families[0]])))
    assert 'family_search_parent' in json.loads(simple.context) and simple.granular_definition is None
    candidate=search(p,narrowed)
    with pytest.raises(ValueError,match='confirm replacement'):
        execute(lambda **cb:p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,candidate,candidate.frame('patterns').pattern_id[:2],**cb))
    repin=execute(lambda **cb:p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,candidate,candidate.frame('patterns').pattern_id[:2],replace_workspace=True,**cb))
    snapshot=p.app.refinement_snapshot(p.session)
    assert snapshot['active_refinement']==narrowed
    assert snapshot['source_family_scope']['selected_families']==list(narrowed.family_scope.families)
    assert snapshot['filter_context']['family_scope_context']['source_selection']==source_scope.to_dict()
    again=evaluate(p,D())
    assert json.loads(again.context)['family_scope']['selected_families']==list(source_scope.families)


@pytest.mark.parametrize('fault',('scope','table','summary','stamp','source'))
def test_bad_scoped_outputs_never_publish(prepared,monkeypatch,fault):
    p=prepared;frozen=pin(p);real=p.domain.search_family_patterns
    def bad(*a,**k):
        result=deepcopy(real(*a,**k));context=json.loads(result.context)
        if fault=='scope':context['family_scope']['selected_families']=[]
        elif fault=='table':result=replace(result,_tables=tuple((n,f.iloc[:0] if n=='family_population' else f) for n,f in result._tables))
        elif fault=='summary':context['family_population'][0]['candidate_rows']+=1
        elif fault=='stamp':result._data.pop('_gr05_discovery_binding')
        else:result._data['_pin_source_binding']='different source'
        return replace(result,context=json.dumps(context))
    monkeypatch.setattr(p.domain,'search_family_patterns',bad)
    with pytest.raises(AssertionError):search(p,PatternRefinement())
    state=p.app.refinement_snapshot(p.session)
    assert state['evaluation_count']==0 and state['active_checkpoint_id']==frozen.source_discovery_id
    assert p.app._refinements[p.session].candidate is None


@pytest.mark.parametrize('operation',('evaluate','search'))
@pytest.mark.parametrize('ending',('draft','checkpoint','source','cancel','close'))
def test_scope_late_duplicate_callbacks(prepared,operation,ending):
    p=prepared;frozen=pin(p);state=p.app.refinement_snapshot(p.session);queued=[];results=[]
    submit=p.app.submit_evaluate_pinned if operation=='evaluate' else p.app.submit_refinement_search
    submit(p.session,frozen.set_id,state['active_checkpoint_id'],state['generation'],D(family_scope=FamilyScope('exact',[p.families[0]])),
        result_callback=results.append,callback_dispatcher=queued.append)
    assert queued and p.app.is_busy(p.session)
    if ending=='draft':p.app.invalidate_refinement_draft(p.session)
    elif ending=='checkpoint':p.app.select_refinement_checkpoint(p.session,frozen.set_id,frozen.source_discovery_id)
    elif ending=='source':p.app.clear_refinement_workspace(p.session)
    elif ending=='cancel':p.app.cancel(p.session)
    else:p.app.end_session(p.session)
    for callback in reversed(queued):callback();callback()
    assert not p.app.is_busy(p.session)
    if ending=='close':assert not results
    else:
        assert len(results)==1 and results[0].status=='cancelled'
        assert p.app.refinement_snapshot(p.session)['evaluation_count']==0


@pytest.mark.parametrize('queued',(False,True))
def test_real_core_scope_cancel_retry(prepared,monkeypatch,queued):
    p=prepared;frozen=pin(p);runner=CoreRunner(TaskManager(),max_worker_threads=1);runner.start();p.app._runner=runner
    entered=Event();release=Event();finished=Event();results=[];real=p.domain.evaluate_pattern_set;calls=[]
    def held(*a,checkpoint,**kw):
        calls.append(1);entered.set();assert release.wait(10);checkpoint();return real(*a,checkpoint=checkpoint,**kw)
    try:
        if queued:
            runner.submit_blocking_job(lambda reporter:(entered.set(),release.wait(10)),task_name='occupied')
            assert entered.wait(5)
        else:monkeypatch.setattr(p.domain,'evaluate_pattern_set',held)
        state=p.app.refinement_snapshot(p.session)
        p.app.submit_evaluate_pinned(p.session,frozen.set_id,frozen.source_discovery_id,state['generation'],D(family_scope=FamilyScope('exact',[p.families[0]])),
            result_callback=lambda r:(results.append(r),finished.set()),callback_dispatcher=lambda cb:cb())
        assert entered.wait(5);assert p.app.cancel(p.session);release.set()
        assert finished.wait(10) and results[0].status=='cancelled'
        assert p.app.refinement_snapshot(p.session)['evaluation_count']==0
        if queued:assert not calls
        wait_until(lambda:not p.app.has_draining_workers)
        monkeypatch.setattr(p.domain,'evaluate_pattern_set',real)
        done=Event();retried=[];state=p.app.refinement_snapshot(p.session)
        p.app.submit_evaluate_pinned(p.session,frozen.set_id,frozen.source_discovery_id,state['generation'],D(),
            result_callback=lambda r:(retried.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert done.wait(10) and retried[0].status=='completed'
    finally:release.set();runner.shutdown()


@pytest.mark.parametrize('direction',('UP','DOWN'))
def test_real_revision_pooled_horizons_and_frozen_read_route(tmp_path,monkeypatch,direction):
    case=revision_case(tmp_path,direction)
    definition=D(outcome=(G(conditions=(horizon(n=6,minimum=0),)),),family_scope=FamilyScope('all'))
    result=evaluate_granular_patterns(case.frozen,definition)
    assert result.population_report()['horizon_source']['price_snapshot_id']==case.frozen._root['_gr04_price_binding']
    assert len(result.frame('family_population'))>=3
    count_oracle(result,case.frozen)
    from io import StringIO
    import pandas as pd
    from tests.analysis_test.test_refinement_outcomes import publish_variant
    from leonardo.analysis.pattern_refinement import search_granular_patterns
    frame=pd.read_csv(StringIO(case.loaded.values_csv.decode()));frame['close']+=1
    successor=publish_variant(case,frame);assert successor.revision_id!=case.manifest.revision_id
    def forbidden(*a,**k):pytest.fail('frozen scope operation attempted a fresh source read')
    monkeypatch.setattr(case.store,'load_database_revision',forbidden)
    monkeypatch.setattr(case.service,'run_patterns',forbidden)
    monkeypatch.setattr(case.service,'_clock_ms',forbidden)
    assert evaluate_granular_patterns(case.frozen,definition).population_report()==result.population_report()
    new=case.service.search_family_patterns(case.frozen,case.parent,case.catalogue,
        replace(case.request.refinement,family_scope=FamilyScope('selected',case.families[:2])),parent_id=result.evaluation_id)
    assert new._data['_gr04_prices'] is case.frozen._root['_gr04_prices']
    pinned=pin_patterns(case.parent,case.catalogue,new,new.frame('patterns').pattern_id[:3])
    assert pinned._root['_gr04_prices']==case.frozen._root['_gr04_prices']
    granular=search_granular_patterns(case.frozen,case.parent,case.catalogue,definition,parent_id=result.evaluation_id)
    assert granular._data['_gr04_prices'] is case.frozen._root['_gr04_prices']


def test_scoped_history_capacity_budget_duplicate_and_leaf(prepared,monkeypatch):
    p=prepared;frozen=pin(p);limits=[];original=p.domain.evaluate_pattern_set
    def capture(*a,**k):limits.append(k['memory_limit_bytes']);return original(*a,**k)
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',capture)
    definitions=[D(family_scope=FamilyScope('selected',p.families[:2+i%7])) for i in range(20)]
    results=[evaluate(p,d) for d in definitions]
    assert p.app.refinement_snapshot(p.session)['evaluation_count']==20 and len(limits)==20
    assert all(b<a for a,b in zip(limits,limits[1:]))
    with pytest.raises(ValueError,match='20 evaluation'):evaluate(p,D(family_scope=FamilyScope('exact',[p.families[0]])))
    p.app.select_refinement_checkpoint(p.session,frozen.set_id,frozen.source_discovery_id)
    assert evaluate(p,definitions[0]) is results[0] and len(limits)==20
    with pytest.raises(ValueError,match='leaf'):p.app.discard_refinement_checkpoint(p.session,frozen.set_id,results[0].evaluation_id)
    p.app.select_refinement_checkpoint(p.session,frozen.set_id,results[-1].evaluation_id)
    state=p.app.discard_refinement_checkpoint(p.session,frozen.set_id,results[-1].evaluation_id)
    assert state['evaluation_count']==19 and state['active_checkpoint_id']==results[-2].evaluation_id
