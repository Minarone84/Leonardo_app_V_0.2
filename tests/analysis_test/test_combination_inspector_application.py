"""GR06 report ownership, real Core cancellation and guarded delivery."""
from dataclasses import replace
import asyncio
import json
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.combination_explanations import inspect_combination, _evaluation_digest
from leonardo.analysis.refinement_models import InspectionOptions, CombinationInspection, FilterOmission
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_pattern_refinement_application import prepared, pin, evaluate, execute, select_source, InlineRunner
from tests.analysis_test.test_combination_explanations import calculated


def inspection(p, **extra):
    state=p.app.refinement_snapshot(p.session)
    return execute(lambda **cb:p.app.submit_combination_inspection(p.session,state['set_id'],
        state['active_checkpoint_id'],state['generation'],p.ids[0],InspectionOptions(),**extra,**cb))


def unchanged_history(before,after):
    for key in ('history','active_checkpoint_id','evaluation_count','pinned_ids','active_refinement'):
        assert before[key]==after[key],key


def test_reports_are_opt_in_charged_defensive_and_clear_does_not_reset_history(prepared):
    p=prepared;frozen=pin(p);before=p.app.refinement_snapshot(p.session)
    assert 'inspection_report' not in before and 'sensitivity_report' not in before
    assert p.app.refinement_inspection_result(p.session,frozen.set_id) is None
    first=inspection(p);after=p.app.refinement_snapshot(p.session)
    unchanged_history(before,after)
    assert after['retained_report_bytes']==first.retained_bytes
    assert after['retained_total_bytes']==before['retained_total_bytes']+first.retained_bytes
    assert p.app.refinement_inspection_result(p.session,frozen.set_id) is first
    payload=first.record('current',next(iter(json.loads(first.payload)['records']['current'])))
    payload.clear();assert first.header['root_id']==frozen.root_id
    p.app.clear_refinement_reports(p.session,frozen.set_id)
    cleared=p.app.refinement_snapshot(p.session);unchanged_history(before,cleared)
    assert 'inspection_report' not in cleared and cleared['retained_total_bytes']==before['retained_total_bytes']


def test_stale_cache_keeps_charge_and_source_restoration_reuses_saved_report(prepared):
    p=prepared;frozen=pin(p);report=inspection(p)
    evaluation=evaluate(p)
    state=p.app.refinement_snapshot(p.session)
    assert state['inspection_report']['status']=='stale'
    assert state['retained_report_bytes']==report.retained_bytes
    assert p.app.refinement_inspection_result(p.session,frozen.set_id) is None
    select_source(p)
    assert p.app.refinement_inspection_result(p.session,frozen.set_id) is report
    assert evaluation.evaluation_id in p.app._refinements[p.session].evaluations


@pytest.mark.parametrize('stage',('draft','checkpoint','clear_reports','clear_workspace','cancel','close'))
def test_queued_duplicate_callback_is_fenced_without_checkpoint_publication(prepared,stage):
    p=prepared;frozen=pin(p);old=inspection(p);state=p.app.refinement_snapshot(p.session)
    callbacks=[];results=[]
    p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,state['generation'],
        p.ids[1],InspectionOptions(),result_callback=results.append,callback_dispatcher=callbacks.append)
    assert len(callbacks)==1 and p.app.is_busy(p.session)
    if stage=='draft':p.app.invalidate_refinement_draft(p.session)
    elif stage=='checkpoint':select_source(p)
    elif stage=='clear_reports':p.app.clear_refinement_reports(p.session,frozen.set_id)
    elif stage=='clear_workspace':p.app.clear_refinement_workspace(p.session)
    elif stage=='cancel':p.app.cancel(p.session)
    else:p.app.end_session(p.session)
    callbacks[0]();callbacks[0]()
    assert not p.app.is_busy(p.session)
    if stage=='close':assert results==[]
    else:
        assert len(results)==1 and results[0].status=='cancelled'
        state=p.app.refinement_snapshot(p.session);assert state['evaluation_count']==0
        if stage not in ('clear_reports','clear_workspace'):
            assert p.app.refinement_inspection_result(p.session,frozen.set_id) is old


@pytest.mark.parametrize('fault',('root_id','set_id','source_discovery_id','checkpoint_id','actual_parent_id','pattern_id','options_id','definition_id','digest','row_membership','wrong_type'))
def test_invalid_delivery_leaves_previous_report_and_history(prepared,monkeypatch,fault):
    p=prepared;frozen=pin(p);old=inspection(p);before=p.app.refinement_snapshot(p.session)
    content=json.loads(old.payload)
    if fault=='wrong_type':bad=object()
    elif fault=='digest':
        bad=CombinationInspection(old.payload);object.__setattr__(bad,'report_id','bad')
    elif fault=='row_membership':
        key=next(iter(content['records']['current']))
        content['records']['current'][key]['row_id']='not-a-root-candidate'
        bad=CombinationInspection(json.dumps(content))
    else:
        content['header'][fault]='alien';bad=CombinationInspection(json.dumps(content))
    monkeypatch.setattr(p.domain,'inspect_combination',lambda *a,**kw:bad)
    results=[]
    p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,before['generation'],
        p.ids[0],InspectionOptions(),result_callback=results.append,callback_dispatcher=lambda cb:cb())
    assert len(results)==1 and results[0].status=='failed'
    assert p.app.refinement_inspection_result(p.session,frozen.set_id) is old
    unchanged_history(before,p.app.refinement_snapshot(p.session))


def test_report_charge_reduces_evaluate_and_search_allowance(prepared,monkeypatch):
    p=prepared;frozen=pin(p);report=inspection(p);limits=[]
    original=p.domain.evaluate_pattern_set
    def capture(*a,**kw):limits.append(kw['memory_limit_bytes']);return original(*a,**kw)
    monkeypatch.setattr(p.domain,'evaluate_pattern_set',capture)
    before=p.app.refinement_snapshot(p.session);evaluate(p)
    assert limits==[134217728-before['retained_total_bytes']]
    # The exact protected search method must charge reports in both its preflight and acceptance.
    import inspect
    source=inspect.getsource(type(p.app).submit_refinement_search)
    assert source.count('retained_report_bytes')==2
    assert report.retained_bytes>0


def wait_call(submit):
    results=[];done=Event();started=monotonic()
    submit(result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
    assert done.wait(60),f'Core wait exceeded 60s after {monotonic()-started:.3f}s'
    assert len(results)==1 and results[0].status=='completed',results
    return results[0].value


@pytest.mark.parametrize('stage',('measurement','ledger'))
@pytest.mark.parametrize('ending',('cancel','clear_reports','close'))
def test_real_core_cancellation_drains_without_replacing_saved_report(prepared,monkeypatch,stage,ending):
    p=prepared;runner=CoreRunner(TaskManager());runner.start()
    p.app=AnalysisApplicationService(runner,p.domain);p.session=p.app.begin_session()
    entered,release,done=Event(),Event(),Event();results=[]
    try:
        frozen=wait_call(lambda **cb:p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,p.study,p.ids,**cb))
        state=p.app.refinement_snapshot(p.session)
        old=wait_call(lambda **cb:p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,
            state['generation'],p.ids[0],InspectionOptions(),**cb))
        import leonardo.analysis.combination_explanations as reports
        import leonardo.analysis.pattern_refinement as resolution
        owner,name=(resolution,'resolve_inspection_measurements') if stage=='measurement' else (reports,'_side_records')
        original=getattr(owner,name)
        def blocked(*a,**kw):
            entered.set();assert release.wait(60)
            checkpoint=kw.get('checkpoint',a[5] if stage=='ledger' else None)
            checkpoint()
            return original(*a,**kw)
        monkeypatch.setattr(owner,name,blocked)
        state=p.app.refinement_snapshot(p.session)
        p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,state['generation'],
            p.ids[1],InspectionOptions(),result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert entered.wait(60)
        if ending=='cancel':p.app.cancel(p.session)
        elif ending=='clear_reports':p.app.clear_refinement_reports(p.session,frozen.set_id)
        else:p.app.end_session(p.session)
        release.set()
        if ending!='close':
            assert done.wait(60) and results[0].status=='cancelled'
            assert p.app.refinement_snapshot(p.session)['evaluation_count']==0
            assert p.app.refinement_inspection_result(p.session,frozen.set_id) is (None if ending=='clear_reports' else old)
    finally:
        release.set();p.app.end_session(p.session);runner.shutdown()


def test_sensitivity_full_set_is_transient_and_variant_binding_is_exact(calculated):
    p=calculated
    app=AnalysisApplicationService(InlineRunner(),p.service);session=app.begin_session()
    try:
        frozen=execute(lambda **cb:app.submit_pin_patterns(session,p.parent,p.catalogue,p.study,
            tuple(r.pattern_id for r in p.frozen.patterns),**cb))
        state=app.refinement_snapshot(session)
        current=execute(lambda **cb:app.submit_evaluate_pinned(session,frozen.set_id,frozen.source_discovery_id,
            state['generation'],p.definition,**cb))
        state=app.refinement_snapshot(session)
        report=execute(lambda **cb:app.submit_refinement_sensitivity(session,frozen.set_id,current.evaluation_id,
            state['generation'],(FilterOmission('condition','common',0,0),FilterOmission('condition','outcome',0,0)),**cb))
        after=app.refinement_snapshot(session);unchanged_history(state,after)
        assert len(report.evaluations)==1 and len(report.plan)==2
        variant=report.variant('common/0/0')
        assert tuple(variant.frame('patterns').pattern_id)==after['pinned_ids']
        inspected=execute(lambda **cb:app.submit_combination_inspection(session,frozen.set_id,current.evaluation_id,
            after['generation'],p.rule.pattern_id,InspectionOptions(),variant_key='common/0/0',**cb))
        assert inspected.header['sensitivity_report_id']==report.report_id
        assert inspected.header['variant_evaluation_id']==variant.evaluation_id
        assert inspected.header['checkpoint_id']==current.evaluation_id
        unchanged_history(state,app.refinement_snapshot(session))
        assert variant.evaluation_id not in app._refinements[session].evaluations
    finally:app.end_session(session)
