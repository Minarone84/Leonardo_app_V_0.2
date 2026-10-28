"""Deterministic real-Core cancellation at the Analysis lock boundary."""
from dataclasses import replace
import json
from threading import Event, Thread, current_thread, enumerate as all_threads
from time import monotonic
import sys
import traceback

import pytest
from leonardo.analysis.pattern_models import FamilyScope
from leonardo.analysis.refinement_models import GranularRefinement as D
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_family_scope_application import prepared
from tests.analysis_test.test_pattern_refinement_application import pin, evaluate


@pytest.mark.parametrize('action', ('draft', 'clear', 'select', 'discard', 'cancel', 'close'))
def test_terminal_callback_and_cancel_do_not_wait_on_each_others_lock(prepared, monkeypatch, tmp_path, action):
    p=prepared;frozen=pin(p)
    previous=evaluate(p,D())
    before=p.app.refinement_snapshot(p.session)
    runner=CoreRunner(TaskManager(),max_worker_threads=1);runner.start();p.app._runner=runner
    worker_entered=Event();release_worker=Event();terminal_ready=Event();release_terminal=Event()
    callback_entered=Event();callback_done=Event();cancel_done=Event();queued=Event()
    pending=[];deliveries=[];cancel_records=[];stacks=[];thread_errors=[]
    real_evaluate=p.domain.evaluate_pattern_set;real_submit=runner.submit_blocking_job;real_cancel=runner.cancel
    def held_work(*args,**kwargs):
        worker_entered.set()
        assert release_worker.wait(15),'controlled worker was not released'
        return real_evaluate(*args,**kwargs)
    def observed_submit(job,**kwargs):
        original=kwargs['result_callback']
        def held_terminal(value):
            terminal_ready.set()
            assert release_terminal.wait(15),'controlled terminal callback was not released'
            callback_entered.set()
            try:original(value)
            finally:callback_done.set()
        return real_submit(job,**{**kwargs,'result_callback':held_terminal})
    def observed_cancel(task_id,**kwargs):
        record=dict(task_id=task_id,caller=current_thread().name,
                    application_lock_owned=p.app._lock._is_owned(),started=monotonic())
        cancel_records.append(record)
        release_terminal.set()
        assert callback_entered.wait(5),'terminal callback never reached the lock boundary'
        try:
            value=real_cancel(task_id,**kwargs)
            record['core_result']=value
            return value
        finally:
            record['elapsed']=monotonic()-record['started'];cancel_done.set()
    def sample_stacks():
        try:
            if callback_entered.wait(10) and not cancel_done.wait(0.25):
                frames=sys._current_frames()
                for thread in all_threads():
                    if thread.ident in frames and thread.name in ('MainThread','LeonardoCore'):
                        stacks.append(dict(thread=thread.name,stack=traceback.format_stack(frames[thread.ident])))
        except BaseException as exc:thread_errors.append(repr(exc))
    def dispatch(callback):pending.append(callback);queued.set()
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',held_work)
    monkeypatch.setattr(runner,'submit_blocking_job',observed_submit)
    monkeypatch.setattr(runner,'cancel',observed_cancel)
    watcher=Thread(target=sample_stacks,name='CancellationStackObserver',daemon=True)
    error=None;returned=None
    try:
        definition=D(family_scope=FamilyScope('exact',(p.families[0],)))
        p.app.submit_evaluate_pinned(p.session,frozen.set_id,previous.evaluation_id,before['generation'],definition,
            result_callback=deliveries.append,callback_dispatcher=dispatch)
        assert worker_entered.wait(10)
        release_worker.set();assert terminal_ready.wait(10)
        watcher.start()
        try:
            if action=='draft':returned=p.app.invalidate_refinement_draft(p.session)
            elif action=='clear':returned=p.app.clear_refinement_workspace(p.session)
            elif action=='select':returned=p.app.select_refinement_checkpoint(p.session,frozen.set_id,frozen.source_discovery_id)
            elif action=='discard':returned=p.app.discard_refinement_checkpoint(p.session,frozen.set_id,previous.evaluation_id)
            elif action=='cancel':returned=p.app.cancel(p.session)
            else:returned=p.app.end_session(p.session)
        except BaseException as exc:error=exc
        assert callback_done.wait(10)
        if action!='close':assert queued.wait(5)
        for callback in tuple(pending):callback();callback()
        assert not p.app.is_busy(p.session) and not p.app.has_draining_workers
        after=None if action=='close' else p.app.refinement_snapshot(p.session)
        proof=dict(action=action,cancel_records=cancel_records,stacks=stacks,error=None if error is None else type(error).__name__,
            deliveries=[r.status for r in deliveries],before=before['generation'],after=None if after is None else after['generation'])
        (tmp_path/'cancellation_proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
        print('CANCELLATION_LOCK_PROOF '+json.dumps({k:v for k,v in proof.items() if k!='stacks'}),flush=True)
        if error is not None:raise error
        assert len(cancel_records)==1 and not cancel_records[0]['application_lock_owned']
        assert not thread_errors
        if action=='close':assert not deliveries and p.session not in p.app._sessions
        else:
            assert len(deliveries)==1 and deliveries[0].status=='cancelled'
            expected=before['generation']+(2 if action=='cancel' else 3)
            assert after['generation']==expected
            if action=='clear':assert not after['workspace_present']
            elif action=='discard':assert after['evaluation_count']==0 and after['active_checkpoint_id']==frozen.source_discovery_id
            else:
                assert after['evaluation_count']==before['evaluation_count']
                assert after['pinned_ids']==before['pinned_ids']
                assert after['active_checkpoint_id']==(frozen.source_discovery_id if action=='select' else previous.evaluation_id)
        if action=='select':assert returned==after
        if action=='discard':assert returned==after
        if action=='draft':assert returned==after['generation']
        if action=='cancel':assert returned is True
    finally:
        release_worker.set();release_terminal.set();cancel_done.set()
        if watcher.ident is not None:watcher.join(5)
        monkeypatch.setattr(runner,'cancel',real_cancel)
        monkeypatch.setattr(runner,'submit_blocking_job',real_submit)
        monkeypatch.setattr(p.domain,'evaluate_pattern_set',real_evaluate)
        p.app.end_session(p.session)
        runner.shutdown(timeout=10)


def test_idle_invalidation_preserves_exact_generation_and_no_core_call(prepared,monkeypatch):
    p=prepared;frozen=pin(p);first=evaluate(p,D());before=p.app.refinement_snapshot(p.session)
    calls=[]
    monkeypatch.setattr(p.app._runner,'cancel',lambda task_id:calls.append(task_id))
    assert p.app.cancel(p.session) is False
    generation=p.app.invalidate_refinement_draft(p.session)
    assert generation==before['generation']+1
    after=p.app.select_refinement_checkpoint(p.session,frozen.set_id,frozen.source_discovery_id)
    assert after['generation']==generation+1 and after['evaluation_count']==1
    p.app.discard_refinement_checkpoint(p.session,frozen.set_id,first.evaluation_id)
    assert p.app.refinement_snapshot(p.session)['generation']==generation+2
    p.app.clear_refinement_workspace(p.session)
    assert p.app.refinement_snapshot(p.session)['generation']==generation+3
    assert not calls
