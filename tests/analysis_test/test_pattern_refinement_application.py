"""GR-02 owner, real backend and deterministic Core/queued-delivery checks."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import json
from queue import Queue
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.pattern_models import PatternRefinement
from leonardo.analysis.pattern_refinement import pin_patterns, evaluate_patterns
from leonardo.analysis.trend_start_patterns import run_study
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture, TOLERANT
from tests.analysis_test.test_trend_start_enrichment import movement


class InlineRunner:
    """Unit-only executor; production execution is covered separately below."""
    def __init__(self):
        self.number = 0
        self.metadata = []
    def submit_blocking_job(self, job, **kwargs):
        self.number += 1
        identity = str(self.number)
        self.metadata.append(kwargs['metadata'])
        try:
            value = job(SimpleNamespace(report=lambda *a, **k: None))
            result = TaskResult(identity, 'completed', value)
        except asyncio.CancelledError:
            result = TaskResult(identity, 'cancelled')
        except Exception as exc:
            result = TaskResult(identity, 'failed', error_type=type(exc).__name__, error_message=str(exc))
        kwargs['result_callback'](result)
        return SimpleNamespace(task_id=identity)
    def cancel(self, task_id):
        return True


@pytest.fixture
def prepared(tmp_path):
    parent, catalogue, axis, req, store, *_ = planted_fixture(tmp_path, planted=TOLERANT, radius=1)
    study = run_study(parent, catalogue, req, axis)
    domain = AnalysisService(store)
    app = AnalysisApplicationService(InlineRunner(), domain)
    session = app.begin_session()
    return SimpleNamespace(parent=parent, catalogue=catalogue, study=study, domain=domain, app=app,
                           session=session, ids=tuple(study.frame('patterns').pattern_id[:4]))


def execute(submit):
    results = []
    submit(result_callback=results.append, callback_dispatcher=lambda callback: callback())
    assert len(results) == 1
    assert results[0].status == 'completed', results[0].error_message
    return results[0].value


def pin(p, **kwargs):
    return execute(lambda **cb: p.app.submit_pin_patterns(p.session, p.parent, p.catalogue,
                    p.study, p.ids, **kwargs, **cb))


def evaluate(p, refinement=None):
    snapshot = p.app.refinement_snapshot(p.session)
    return execute(lambda **cb: p.app.submit_evaluate_pinned(p.session, snapshot['set_id'],
        snapshot['active_checkpoint_id'], snapshot['generation'], refinement or PatternRefinement(), **cb))


def select_source(p):
    s = p.app.refinement_snapshot(p.session)
    return p.app.select_refinement_checkpoint(p.session, s['set_id'], s['source_discovery_id'])


@pytest.mark.parametrize('count,reverse', ((1,False),(4,False),(4,True)))
def test_pin_original_order_and_detached_snapshot(prepared, count, reverse):
    p = prepared
    original = p.ids[:count]
    p.ids = tuple(reversed(original)) if reverse else original
    frozen = pin(p)
    snapshot = p.app.refinement_snapshot(p.session)
    assert snapshot['pinned_ids'] == original
    assert snapshot['evaluation_count'] == 0 and snapshot['evaluation_limit'] == 20
    assert snapshot['active_checkpoint_id'] == frozen.source_discovery_id
    snapshot['history'][0]['active'] = False
    snapshot['history'].clear()
    assert len(p.app.refinement_snapshot(p.session)['history']) == 1
    other = p.app.begin_session()
    for action in (lambda: p.app.refinement_result(other, frozen.set_id, frozen.source_discovery_id),
                   lambda: p.app.select_refinement_checkpoint(other, frozen.set_id, frozen.source_discovery_id)):
        with pytest.raises(ValueError): action()
    p.app.end_session(other)
    with pytest.raises(RuntimeError): p.app.refinement_snapshot(other)


def test_parity_zero_reset_lineage_comparison_and_occurrences(prepared):
    p = prepared
    frozen = pin(p)
    same = evaluate(p)
    before = frozen.original_patterns().set_index('pattern_id')
    after = same.frame('patterns').set_index('pattern_id')
    shared = [name for name in after if name in before]
    pd.testing.assert_frame_equal(after[shared], before.loc[after.index, shared])
    zero = evaluate(p, movement('formation', minimum=10000))
    assert tuple(zero.frame('patterns').pattern_id) == p.ids
    assert zero.frame('patterns').matched.eq(0).all()
    assert zero.frame('patterns').assessable.eq(0).all()
    assert zero.frame('patterns').difference_pp.isna().all()
    comparison = p.app.refinement_comparison(p.session, frozen.set_id, zero.evaluation_id)
    assert comparison.parent_id.eq(same.evaluation_id).all()
    assert comparison.delta_difference_pp.isna().all()
    with pytest.raises(ValueError): p.domain.compare_pattern_evaluation(frozen, zero)
    for cohort in ('target','comparison'):
        actual = execute(lambda **kw: p.app.submit_refinement_matches(p.session, frozen.set_id,
            zero.evaluation_id, p.ids[0], cohort, **kw))
        assert actual.empty and len(actual.columns) == 15
    restored = select_source(p)
    assert restored['active_refinement'] == p.study.request.refinement
    assert p.app.refinement_result(p.session, frozen.set_id, frozen.source_discovery_id) is p.study
    with pytest.raises(ValueError, match='no parent'): p.app.refinement_comparison(p.session, frozen.set_id, frozen.source_discovery_id)
    repeated = evaluate(p)
    assert repeated is same and p.app.refinement_snapshot(p.session)['evaluation_count'] == 2


@pytest.mark.parametrize('fault', ('missing_stamp','catalogue_same_id','profile_same_id'))
def test_real_r2_errors_preserve_previous_workspace(prepared, fault):
    p = prepared
    frozen = pin(p)
    parent, catalogue, study = p.parent, p.catalogue, p.study
    if fault == 'missing_stamp':
        study = replace(study, _data={k:v for k,v in study._data.items() if k != '_pin_source_binding'})
    elif fault == 'catalogue_same_id':
        payload = catalogue.to_dict()
        payload['instances'][0]['events'][0]['origin'] = 'changed-evidence'
        catalogue = replace(catalogue, _json=json.dumps(payload))
    else:
        columns = list(parent.columns)
        profile = columns[0].profile
        changed = replace(profile, context=replace(profile.context, unit='same-id-different-unit'))
        columns[0] = replace(columns[0], profile=changed)
        parent = replace(parent, columns=tuple(columns))
    results = []
    p.app.submit_pin_patterns(p.session, parent, catalogue, study, p.ids, replace_workspace=True,
        result_callback=results.append, callback_dispatcher=lambda cb: cb())
    assert results[0].status == 'failed' and 'binding' in results[0].error_message
    assert p.app.refinement_snapshot(p.session)['set_id'] == frozen.set_id


def test_history_capacity_duplicate_leaf_ancestor_and_remaining_budget(prepared, monkeypatch):
    p = prepared
    frozen = pin(p)
    limits = []
    original = p.domain.evaluate_pattern_set
    def capture(*args, **kwargs):
        limits.append(kwargs['memory_limit_bytes'])
        return original(*args, **kwargs)
    monkeypatch.setattr(p.domain, 'evaluate_pattern_set', capture)
    first = evaluate(p)
    second = evaluate(p)
    assert first.evaluation_id != second.evaluation_id and second.parent_id == first.evaluation_id
    with pytest.raises(ValueError, match='leaf'): p.app.discard_refinement_checkpoint(p.session, frozen.set_id, first.evaluation_id)
    with pytest.raises(ValueError, match='source'): p.app.discard_refinement_checkpoint(p.session, frozen.set_id, frozen.source_discovery_id)
    for n in range(18): evaluate(p, movement('formation', minimum=n))
    state = p.app.refinement_snapshot(p.session)
    assert state['evaluation_count'] == 20 and len(limits) == 20
    assert limits[0] == 134217728 and all(b < a for a,b in zip(limits, limits[1:]))
    with pytest.raises(ValueError, match='20 evaluation'): evaluate(p, movement('formation', 9000))
    select_source(p)
    assert evaluate(p) is first and len(limits) == 20
    leaf = state['active_checkpoint_id']
    p.app.select_refinement_checkpoint(p.session, frozen.set_id, leaf)
    state = p.app.discard_refinement_checkpoint(p.session, frozen.set_id, leaf)
    assert state['evaluation_count'] == 19 and state['active_checkpoint_id'] != leaf
    assert state['retained_match_bytes'] == sum(json.loads(e.context)['estimated_retained_match_state_bytes']
        for e in p.app._refinements[p.session].evaluations.values())


@pytest.mark.parametrize('stage', ('draft','checkpoint','clear','cancel','close'))
def test_after_worker_before_dispatch_has_no_stale_commit(prepared, stage):
    p = prepared
    frozen = pin(p)
    snapshot = p.app.refinement_snapshot(p.session)
    queued, results = [], []
    p.app.submit_evaluate_pinned(p.session, frozen.set_id, frozen.source_discovery_id, snapshot['generation'],
        PatternRefinement(), result_callback=results.append, callback_dispatcher=queued.append)
    assert p.app.is_busy(p.session) and p.app.refinement_snapshot(p.session)['evaluation_count'] == 0
    with pytest.raises(RuntimeError, match='running'):
        p.app.submit_refinement_matches(p.session, frozen.set_id, frozen.source_discovery_id, p.ids[0], 'target',
            result_callback=results.append, callback_dispatcher=queued.append)
    if stage == 'draft': p.app.invalidate_refinement_draft(p.session)
    elif stage == 'checkpoint': select_source(p)
    elif stage == 'clear': p.app.clear_refinement_workspace(p.session)
    elif stage == 'cancel': p.app.cancel(p.session)
    else: p.app.end_session(p.session)
    for callback in reversed(queued): callback(); callback()
    assert not p.app.is_busy(p.session)
    if stage == 'close': assert results == []
    else:
        assert len(results) == 1 and results[0].status == 'cancelled' and results[0].value is None
        assert p.app.refinement_snapshot(p.session)['evaluation_count'] == 0


@pytest.mark.parametrize('operation', ('pin','evaluate','matches','search'))
@pytest.mark.parametrize('ending', ('cancel','close'))
def test_real_core_blocked_work_drains_and_keeps_completed_state(prepared, monkeypatch, operation, ending):
    p = prepared
    runner = CoreRunner(TaskManager())
    runner.start()
    p.app = AnalysisApplicationService(runner, p.domain)
    p.session = p.app.begin_session()
    results, done, entered, release = [], Event(), Event(), Event()
    def await_call(submit):
        out, completed = [], Event()
        submit(result_callback=lambda r: (out.append(r),completed.set()), callback_dispatcher=lambda cb: cb())
        assert completed.wait(10) and out[0].status == 'completed', out
        return out[0].value
    try:
        frozen = await_call(lambda **kw: p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,p.study,p.ids,**kw))
        snapshot = p.app.refinement_snapshot(p.session)
        method = {'pin':'pin_pattern_set','evaluate':'evaluate_pattern_set','matches':'pattern_matches','search':'run_patterns'}[operation]
        actual = getattr(p.domain, method)
        def blocked(*args, checkpoint, **kwargs):
            entered.set()
            assert release.wait(10)
            checkpoint()
            return actual(*args, checkpoint=checkpoint, **kwargs)
        monkeypatch.setattr(p.domain, method, blocked)
        cb = dict(result_callback=lambda r: (results.append(r), done.set()), callback_dispatcher=lambda f:f())
        if operation == 'pin': submission = p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,p.study,p.ids,replace_workspace=True,**cb)
        elif operation == 'evaluate': submission = p.app.submit_evaluate_pinned(p.session,frozen.set_id,frozen.source_discovery_id,snapshot['generation'],PatternRefinement(),**cb)
        elif operation == 'matches': submission = p.app.submit_refinement_matches(p.session,frozen.set_id,frozen.source_discovery_id,p.ids[0],'target',**cb)
        else: submission = p.app.submit_refinement_search(p.session,frozen.set_id,frozen.source_discovery_id,snapshot['generation'],PatternRefinement(),**cb)
        assert entered.wait(5)
        assert runner._task_manager.get_snapshot(submission.task_id).metadata['operation'] == 'refinement_'+operation
        responsive = Event()
        async def quick(): responsive.set()
        runner.submit_coroutine(quick(),task_name='responsive')
        assert responsive.wait(2)
        if ending == 'close': p.app.end_session(p.session)
        else: assert p.app.cancel(p.session)
        assert p.app.has_draining_workers
        another = p.app.begin_session()
        with pytest.raises(RuntimeError): p.app.submit_catalog(another, **cb)
        p.app.end_session(another)
        release.set()
        if ending == 'cancel':
            assert done.wait(5) and results[0].status == 'cancelled'
            assert p.app.refinement_snapshot(p.session)['active_checkpoint_id'] == frozen.source_discovery_id
        else:
            from tests.analysis_test.test_analysis_application import wait_until
            wait_until(lambda:not p.app.is_busy(p.session))
            assert results == []
    finally:
        release.set(); p.app.end_session(p.session); runner.shutdown()


def test_hand_counted_projection_and_unavailable(prepared):
    p = prepared
    frozen = pin(p)
    real = evaluate_patterns(frozen, PatternRefinement())
    patterns = frozen.patterns[:2]
    old, new = [], []
    for index, pattern in enumerate(patterns):
        base = dict(pattern_id=pattern.pattern_id,condition=f'R_{index}',matched=3,assessable=6,
            comparison_matched=1,comparison_assessable=4,difference_pp=25,rank_eligible=True)
        old.append(replace(pattern, original_row=json.dumps(base)))
        new.append(dict(base, matched=1 if index == 0 else 0,assessable=2 if index == 0 else 0,
            comparison_matched=0,comparison_assessable=2,difference_pp=50 if index == 0 else None,support_eligible=index==0))
    selected = replace(frozen, patterns=tuple(old))
    child = replace(real, _tables=(('patterns',pd.DataFrame(new,dtype=object)),))
    report = p.domain.compare_pattern_evaluation(selected,child)
    assert report.iloc[0][['delta_matched','delta_assessable','delta_comparison_matched',
                         'delta_comparison_assessable','delta_difference_pp']].tolist() == [-2,-4,-1,-2,25]
    assert report.iloc[1].delta_difference_pp is None
    assert len(report) == 2 and report.parent_support.str.startswith('Source original').all()


def test_no_mining_fitting_or_reads_on_fixed_workflow(prepared, monkeypatch):
    p = prepared
    import sys
    def forbidden(*a, **kw): pytest.fail('fixed refinement recomputed or read persistence')
    names = []
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith('leonardo.') or module is None: continue
        for name, value in tuple(vars(module).items()):
            if callable(value) and (name in ('mine','terms_for_column','run_study','run_pre_event','calculate_financial_tool')
                    or name.startswith(('fit_','classify_','analyze_directional','analyze_variation','measure_utc','get_utc'))):
                monkeypatch.setattr(module,name,forbidden); names.append(module_name+'.'+name)
    monkeypatch.setattr(p.domain,'_load',forbidden)
    monkeypatch.setattr(p.domain,'load_pattern_catalogue',forbidden)
    frozen = pin(p)
    current = evaluate(p)
    p.app.refinement_comparison(p.session,frozen.set_id,current.evaluation_id)
    for cohort in ('target','comparison'):
        actual = execute(lambda **kw:p.app.submit_refinement_matches(p.session,frozen.set_id,current.evaluation_id,p.ids[0],cohort,**kw))
        pd.testing.assert_frame_equal(actual,current.pattern_matches(p.ids[0],cohort))
    select_source(p)
    assert any(name.endswith('pre_event_patterns.mine') for name in names)


@pytest.mark.parametrize('fault', ('budget','failure'))
def test_failed_evaluation_does_not_consume_history(prepared, monkeypatch, fault):
    p = prepared
    frozen = pin(p)
    original = p.domain.evaluate_pattern_set
    def bad(*args, **kw):
        if fault == 'failure': raise ValueError('explicit fixture failure')
        return original(*args, **dict(kw,memory_limit_bytes=1))
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',bad)
    state = p.app.refinement_snapshot(p.session)
    results=[]
    p.app.submit_evaluate_pinned(p.session,frozen.set_id,frozen.source_discovery_id,state['generation'],
        PatternRefinement(),result_callback=results.append,callback_dispatcher=lambda cb:cb())
    assert results[0].status == 'failed'
    assert p.app.refinement_snapshot(p.session)['evaluation_count'] == 0


def test_cancel_before_executor_entry_and_queued_progress(prepared, monkeypatch):
    p=prepared
    runner=CoreRunner(TaskManager(),max_worker_threads=1)
    runner.start();p.app=AnalysisApplicationService(runner,p.domain);p.session=p.app.begin_session()
    entered,release,done=Event(),Event(),Event();results=[];calls=[]
    def occupy(reporter):
        entered.set();assert release.wait(10)
    runner.submit_blocking_job(occupy,task_name='occupied')
    assert entered.wait(3)
    monkeypatch.setattr(p.domain,'pin_pattern_set',lambda *a,**kw:calls.append(True))
    try:
        p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,p.study,p.ids,
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        p.app.cancel(p.session)
        assert done.wait(5) and results[0].status=='cancelled' and not calls
        assert not p.app.refinement_snapshot(p.session)['workspace_present']
    finally:
        release.set();p.app.end_session(p.session);runner.shutdown()


def test_queued_progress_is_guarded_on_delivery(prepared):
    p=prepared;pin(p)
    class ReportingRunner(InlineRunner):
        def submit_blocking_job(self,job,**kw):
            kw['progress_callback'](SimpleNamespace(message='queued progress'))
            return super().submit_blocking_job(job,**kw)
    p.app._runner=ReportingRunner()
    state=p.app.refinement_snapshot(p.session)
    queued,progress,results=[],[],[]
    p.app.submit_evaluate_pinned(p.session,state['set_id'],state['active_checkpoint_id'],state['generation'],
        PatternRefinement(),result_callback=results.append,progress_callback=progress.append,callback_dispatcher=queued.append)
    p.app.invalidate_refinement_draft(p.session)
    for callback in queued: callback()
    assert not progress and results[0].status=='cancelled'


def test_exact_aggregate_budget_no_eviction_and_reuse(prepared,monkeypatch):
    p=prepared;frozen=pin(p)
    actual=p.domain.evaluate_pattern_set
    def consume(*args,**kw):
        result=actual(*args,**kw)
        return replace(result,context=json.dumps(dict(json.loads(result.context),estimated_retained_match_state_bytes=134217728)))
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',consume)
    first=evaluate(p)
    state=p.app.refinement_snapshot(p.session)
    assert state['retained_match_bytes']==134217728
    with pytest.raises(ValueError,match='budget exhausted'): evaluate(p)
    select_source(p)
    assert evaluate(p) is first
    p.app.discard_refinement_checkpoint(p.session,frozen.set_id,first.evaluation_id)
    assert p.app.refinement_snapshot(p.session)['retained_match_bytes']==0


@pytest.mark.parametrize('operation',('evaluate','matches','search'))
def test_identity_guards_fail_before_work(prepared,operation):
    p=prepared;frozen=pin(p);s=p.app.refinement_snapshot(p.session)
    callbacks=dict(result_callback=lambda r:None,callback_dispatcher=lambda cb:cb())
    with pytest.raises(ValueError):
        if operation=='evaluate': p.app.submit_evaluate_pinned(p.session,'foreign',s['active_checkpoint_id'],s['generation'],PatternRefinement(),**callbacks)
        elif operation=='matches': p.app.submit_refinement_matches(p.session,s['set_id'],s['active_checkpoint_id'],'foreign','target',**callbacks)
        else: p.app.submit_refinement_search(p.session,s['set_id'],s['active_checkpoint_id'],s['generation']-1,PatternRefinement(),**callbacks)
    assert not p.app.is_busy(p.session) and p.app.refinement_snapshot(p.session)['evaluation_count']==0


@pytest.mark.parametrize('chronological', (False,True))
@pytest.mark.parametrize('comparison', ('other_families','non_start'))
def test_real_ledger_partitions_controls_and_incomplete_search(tmp_path,chronological,comparison):
    parent,catalogue,axis,req,store,*_=planted_fixture(tmp_path,radius=1,planted=TOLERANT)
    req=replace(req,comparison=comparison,pre_event=replace(req.pre_event,chronological=chronological,candidate_limit=12))
    study=run_study(parent,catalogue,req,axis)
    p=SimpleNamespace(parent=parent,catalogue=catalogue,study=study,domain=AnalysisService(store),
        ids=tuple(study.frame('patterns').pattern_id[:3]))
    assert p.ids and not json.loads(study.context)['search']['complete']
    p.app=AnalysisApplicationService(InlineRunner(),p.domain);p.session=p.app.begin_session()
    frozen=pin(p);result=evaluate(p)
    assert tuple(result.frame('patterns').pattern_id)==p.ids
    for cohort in ('target','comparison'):
        ledger=execute(lambda **kw:p.app.submit_refinement_matches(p.session,frozen.set_id,result.evaluation_id,p.ids[0],cohort,**kw))
        assert ledger.attrs['pattern_detail']==result.pattern_matches(p.ids[0],cohort).attrs['pattern_detail']
        assert set(ledger.partition)<= {'discovery','later','excluded'}
        if cohort=='comparison' and comparison=='non_start':
            assert not ledger.empty
            evidence=result.evidence(ledger.iloc[0].event_id)
            assert evidence.get('facts') is None
            assert not result.event_window(ledger.iloc[0].event_id).empty
