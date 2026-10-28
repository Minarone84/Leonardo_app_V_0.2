"""Task 1080 mixed history, retained payload accounting and guarded Core publication."""
from copy import deepcopy
from dataclasses import replace
import json
from threading import Event

import pytest

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.pattern_models import PatternRefinement
from leonardo.analysis.refinement_models import GranularRefinement as D
from leonardo.analysis.pattern_refinement import evaluate_granular_patterns, _gr03_charge
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_granular_evidence import quantity, spec
from tests.analysis_test.test_pattern_refinement_application import prepared, pin, evaluate, execute, select_source
from tests.analysis_test.test_analysis_application import wait_until


def search(p,definition):
    s=p.app.refinement_snapshot(p.session)
    return execute(lambda **cb:p.app.submit_refinement_search(p.session,s['set_id'],s['active_checkpoint_id'],s['generation'],definition,**cb))


def test_mixed_history_actual_parent_duplicates_and_capacity(prepared):
    p=prepared;frozen=pin(p)
    simple=evaluate(p,PatternRefinement())
    granular=evaluate(p,D())
    assert granular.parent_id==simple.evaluation_id
    after=p.app.refinement_snapshot(p.session)
    assert after['active_filter_kind']=='granular' and after['source_filter_kind']=='simple'
    assert [r['filter_kind'] for r in after['history']]==['simple','simple','granular']
    p.app.select_refinement_checkpoint(p.session,frozen.set_id,simple.evaluation_id)
    assert evaluate(p,D()) is granular
    assert p.app.refinement_snapshot(p.session)['evaluation_count']==2
    prior=granular
    for i in range(18):prior=evaluate(p,spec(quantity(basis='formation',minimum=i)))
    assert p.app.refinement_snapshot(p.session)['evaluation_count']==20
    with pytest.raises(ValueError,match='20 evaluation'):evaluate(p,D())
    p.app.select_refinement_checkpoint(p.session,frozen.set_id,prior.parent_id)
    assert evaluate(p,prior.granular_definition) is prior
    p.app.discard_refinement_checkpoint(p.session,frozen.set_id,prior.evaluation_id)
    assert p.app.refinement_snapshot(p.session)['evaluation_count']==19
    assert evaluate(p,D()).parent_id==prior.parent_id
    select_source(p)
    state=p.app.refinement_snapshot(p.session)
    state['filter_context']['columns'].clear();state['history'].clear()
    assert p.app.refinement_snapshot(p.session)['filter_context']['columns']
    assert p.app.refinement_snapshot(p.session)['active_refinement']==PatternRefinement()


@pytest.mark.parametrize('fault',('definition','definition_id','root','set','parent','request','identity','charge','total','samples','accounting_shape','context_shape'))
def test_foreign_or_malformed_granular_output_not_inserted(prepared,monkeypatch,fault):
    p=prepared;frozen=pin(p);actual=p.domain.evaluate_pattern_set
    def bad(*a,**kw):
        result=deepcopy(actual(*a,**kw));context=json.loads(result.context)
        if fault=='definition':result._data['_gr03_definition']=spec(quantity())
        elif fault=='definition_id':context['definition_id']='bad'
        elif fault in ('root','set','parent'):result=replace(result,**{fault+'_id':'bad'})
        elif fault=='request':result=replace(result,request=replace(result.request,after=result.request.after+1))
        elif fault=='identity':result=replace(result,evaluation_id='bad')
        elif fault=='charge':result._data['_gr03_population']['accounting']['retained_payload_bytes']+=1
        elif fault=='total':context['retained_total_bytes']+=1
        elif fault=='samples':result._data['samples']=[]
        elif fault=='accounting_shape':result._data['_gr03_population']['accounting']=None
        elif fault=='context_shape':context=[]
        return replace(result,context=json.dumps(context))
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',bad)
    s=p.app.refinement_snapshot(p.session);out=[]
    p.app.submit_evaluate_pinned(p.session,frozen.set_id,frozen.source_discovery_id,s['generation'],D(),
        result_callback=out.append,callback_dispatcher=lambda cb:cb())
    assert out[0].status=='failed' and p.app.refinement_snapshot(p.session)['evaluation_count']==0


def test_unique_population_candidate_replacement_repin_and_clear(prepared,monkeypatch):
    p=prepared;frozen=pin(p);evaluation=evaluate(p,D());state=p.app.refinement_snapshot(p.session)
    assert state['retained_population_bytes']==_gr03_charge(evaluation._data['_gr03_population'])
    first=search(p,spec(quantity(basis='formation',minimum=0)))
    after=p.app.refinement_snapshot(p.session)
    assert after['active_checkpoint_id']==state['active_checkpoint_id'] and after['evaluation_count']==1
    assert after['retained_population_bytes']==state['retained_population_bytes']+_gr03_charge(first._data['_gr03_population'])
    second=search(p,D())
    expected=state['retained_population_bytes']+_gr03_charge(second._data['_gr03_population'])
    assert p.app.refinement_snapshot(p.session)['retained_population_bytes']==expected
    original=p.domain.search_granular_patterns
    def fail(*a,**kw):raise ValueError('search failure fixture')
    monkeypatch.setattr(p.domain,'search_granular_patterns',fail)
    with pytest.raises(AssertionError,match='search failure'):search(p,D())
    assert p.app._refinements[p.session].candidate['study'] is second
    monkeypatch.setattr(p.domain,'search_granular_patterns',original)
    ids=tuple(second.frame('patterns').pattern_id[:4])
    repin=execute(lambda **cb:p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,second,ids,replace_workspace=True,**cb))
    state=p.app.refinement_snapshot(p.session)
    assert state['evaluation_count']==0 and state['active_filter_kind']=='granular' and state['active_refinement']==D()
    assert repin._root['_gr03_population'] is second._data['_gr03_population']
    assert state['retained_population_bytes']==_gr03_charge(second._data['_gr03_population'])
    p.app.clear_refinement_workspace(p.session)
    assert p.app.refinement_snapshot(p.session)['retained_total_bytes']==0


def test_combined_exact_budget_duplicate_and_leaf_credit(prepared,monkeypatch):
    p=prepared;frozen=pin(p);real=p.domain.evaluate_pattern_set
    required=json.loads(evaluate_granular_patterns(frozen,D()).context)['retained_total_bytes']
    def consume(*args,**kw):
        value=real(*args,**kw)
        return replace(value,context=json.dumps({**json.loads(value.context),'estimated_retained_match_state_bytes':134217728-required}))
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',consume)
    base=evaluate(p,PatternRefinement());select_source(p)
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',real)
    current=evaluate(p,D());state=p.app.refinement_snapshot(p.session)
    assert state['retained_total_bytes']==134217728
    select_source(p);assert evaluate(p,D()) is current
    with pytest.raises(ValueError,match='budget exhausted'):evaluate(p,spec(quantity()))
    p.app.discard_refinement_checkpoint(p.session,frozen.set_id,base.evaluation_id)
    assert evaluate(p,spec(quantity())).parent_id==current.evaluation_id


@pytest.mark.parametrize('operation',('evaluate','search'))
@pytest.mark.parametrize('stage',('draft','checkpoint','clear','cancel','close'))
def test_obsolete_held_terminal_never_publishes(prepared,operation,stage):
    p=prepared;frozen=pin(p);old=search(p,D()) if operation=='search' else None
    before=p.app.refinement_snapshot(p.session);queued=[];results=[];progress=[]
    submit=p.app.submit_evaluate_pinned if operation=='evaluate' else p.app.submit_refinement_search
    submit(p.session,frozen.set_id,before['active_checkpoint_id'],before['generation'],spec(quantity(basis='formation')),
        result_callback=results.append,progress_callback=progress.append,callback_dispatcher=queued.append)
    assert queued and p.app.is_busy(p.session)
    if stage=='draft':p.app.invalidate_refinement_draft(p.session)
    elif stage=='checkpoint':select_source(p)
    elif stage=='clear':p.app.clear_refinement_workspace(p.session)
    elif stage=='cancel':p.app.cancel(p.session)
    else:p.app.end_session(p.session)
    for callback in reversed(queued):callback();callback()
    assert not p.app.is_busy(p.session)
    if stage=='close':assert not results
    else:
        assert len(results)==1 and results[0].status=='cancelled'
        assert p.app.refinement_snapshot(p.session)['evaluation_count']==0
        if old is not None and stage!='clear':assert p.app._refinements[p.session].candidate['study'] is old


@pytest.mark.parametrize('operation',('evaluate','search'))
@pytest.mark.parametrize('ending',('cancel','close'))
def test_real_core_granular_running_cancellation_and_drain(prepared,monkeypatch,operation,ending):
    p=prepared;runner=CoreRunner(TaskManager());runner.start();p.app=AnalysisApplicationService(runner,p.domain);p.session=p.app.begin_session()
    release=Event();entered=Event();done=Event();results=[]
    def await_call(submit):
        out=[];completed=Event();submit(result_callback=lambda r:(out.append(r),completed.set()),callback_dispatcher=lambda cb:cb())
        assert completed.wait(10) and out[0].status=='completed',out
        return out[0].value
    try:
        frozen=await_call(lambda **cb:p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,p.study,p.ids,**cb))
        method='evaluate_pattern_set' if operation=='evaluate' else 'search_granular_patterns';actual=getattr(p.domain,method)
        def held(*a,checkpoint,**kw):
            entered.set();assert release.wait(10);checkpoint();return actual(*a,checkpoint=checkpoint,**kw)
        monkeypatch.setattr(p.domain,method,held)
        state=p.app.refinement_snapshot(p.session)
        submit=p.app.submit_evaluate_pinned if operation=='evaluate' else p.app.submit_refinement_search
        submit(p.session,frozen.set_id,frozen.source_discovery_id,state['generation'],D(),
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert entered.wait(5)
        if ending=='cancel':assert p.app.cancel(p.session)
        else:p.app.end_session(p.session)
        assert p.app.has_draining_workers;release.set()
        if ending=='cancel':
            assert done.wait(5) and results[0].status=='cancelled'
            assert p.app.refinement_snapshot(p.session)['active_checkpoint_id']==frozen.source_discovery_id
        else:wait_until(lambda:not p.app.is_busy(p.session));assert not results
    finally:release.set();p.app.end_session(p.session);runner.shutdown()


def test_candidate_exclusive_credit_at_combined_boundary(prepared,monkeypatch):
    p=prepared;frozen=pin(p);candidate=search(p,D());charge=_gr03_charge(candidate._data['_gr03_population'])
    original=p.domain.evaluate_pattern_set
    def consume(*a,**kw):
        result=original(*a,**kw)
        return replace(result,context=json.dumps({**json.loads(result.context),'estimated_retained_match_state_bytes':134217728-charge}))
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',consume)
    evaluate(p,PatternRefinement())
    assert p.app.refinement_snapshot(p.session)['retained_total_bytes']==134217728
    replacement=search(p,D())
    assert replacement is not candidate and p.app.refinement_snapshot(p.session)['retained_total_bytes']==134217728
    with pytest.raises(AssertionError,match='limit'):search(p,spec(quantity()))
    assert p.app._refinements[p.session].candidate['study'] is replacement
    assert p.app.refinement_snapshot(p.session)['retained_total_bytes']==134217728


@pytest.mark.parametrize('operation',('evaluate','search'))
def test_cancel_granular_before_core_executor_entry(prepared,monkeypatch,operation):
    p=prepared;frozen=pin(p)
    runner=CoreRunner(TaskManager(),max_worker_threads=1);runner.start();p.app._runner=runner
    entered=Event();release=Event();done=Event();calls=[];results=[]
    def occupy(reporter):entered.set();assert release.wait(10)
    try:
        runner.submit_blocking_job(occupy,task_name='occupied');assert entered.wait(3)
        method='evaluate_pattern_set' if operation=='evaluate' else 'search_granular_patterns'
        monkeypatch.setattr(p.domain,method,lambda *a,**kw:calls.append(True))
        s=p.app.refinement_snapshot(p.session)
        submit=p.app.submit_evaluate_pinned if operation=='evaluate' else p.app.submit_refinement_search
        submit(p.session,frozen.set_id,frozen.source_discovery_id,s['generation'],D(),
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        p.app.cancel(p.session)
        assert done.wait(5) and results[0].status=='cancelled' and not calls
        assert p.app.refinement_snapshot(p.session)['evaluation_count']==0
    finally:release.set();p.app.end_session(p.session);runner.shutdown()
