"""REC-02 original service publication/accounting integration regressions."""
import json
from tests.analysis_test.test_pattern_refinement_application import prepared, pin
from tests.analysis_test.test_combination_inspector_application import inspection, unchanged_history

def test_compact_service_report_is_charged_and_replacement_keeps_history(prepared):
    p = prepared
    frozen = pin(p)
    before = p.app.refinement_snapshot(p.session)
    first = inspection(p)
    assert "window_store" in json.loads(first.payload)
    second = inspection(p)
    after = p.app.refinement_snapshot(p.session)
    assert after["retained_report_bytes"] == second.retained_bytes
    assert after["retained_total_bytes"] == before["retained_total_bytes"] + second.retained_bytes
    unchanged_history(before, after)
    assert p.app.refinement_inspection_result(p.session, frozen.set_id) is second


from threading import Event
from time import monotonic
import pytest
from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.refinement_models import InspectionOptions
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_combination_inspector_application import wait_call

@pytest.mark.parametrize('stage',('capture','late_records','accounting','chunk_encoding','model_boundary'))
def test_real_core_cancels_new_storage_boundaries_and_preserves_prior_report(prepared,monkeypatch,stage,record_property):
    from leonardo.analysis import combination_explanations as ce
    from leonardo.analysis.refinement_models import CombinationInspection
    p=prepared;runner=CoreRunner(TaskManager());runner.start()
    p.app=AnalysisApplicationService(runner,p.domain);p.session=p.app.begin_session()
    entered,release,done=Event(),Event(),Event();results=[];observed=[]
    try:
        frozen=wait_call(lambda **cb:p.app.submit_pin_patterns(p.session,p.parent,p.catalogue,p.study,p.ids,**cb))
        state=p.app.refinement_snapshot(p.session)
        old=wait_call(lambda **cb:p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,
            state['generation'],p.ids[0],InspectionOptions(),**cb))
        before=p.app.refinement_snapshot(p.session)
        def pause(checkpoint):
            if entered.is_set():return
            observed.append(('entered',monotonic()));entered.set()
            assert release.wait(60)
            observed.append(('checkpoint',monotonic()));checkpoint()
        if stage=='capture':
            original=ce._inspection_window_source
            def capture(result,store,account):
                pause(account.checkpoint);return original(result,store,account)
            monkeypatch.setattr(ce,'_inspection_window_source',capture)
        elif stage=='late_records':
            original=ce._side_records
            def records(*a,**kw):
                result=original(*a,**kw);pause(a[5]);return result
            monkeypatch.setattr(ce,'_side_records',records)
        elif stage=='accounting':
            original=ce._InspectionAccounting.scalar_size
            def charge(self,value):
                pause(self.checkpoint);return original(self,value)
            monkeypatch.setattr(ce._InspectionAccounting,'scalar_size',charge)
        elif stage=='chunk_encoding':
            original=ce._inspection_encode
            def encode(value,checkpoint):
                if isinstance(value,dict) and 'window_store' in value:pause(checkpoint)
                return original(value,checkpoint)
            monkeypatch.setattr(ce,'_inspection_encode',encode)
        else:
            original=CombinationInspection._build
            def model(cls,payload,checkpoint):
                result=original(payload,checkpoint);pause(checkpoint);return result
            monkeypatch.setattr(CombinationInspection,'_build',classmethod(model))
        p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,before['generation'],
            p.ids[1],InspectionOptions(),result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert entered.wait(60)
        observed.append(('request',monotonic()));p.app.cancel(p.session)
        release.set()
        assert done.wait(60) and len(results)==1 and results[0].status=='cancelled'
        observed.append(('terminal',monotonic()))
        assert not p.app.is_busy(p.session)
        assert p.app.refinement_inspection_result(p.session,frozen.set_id) is old
        after=p.app.refinement_snapshot(p.session);unchanged_history(before,after)
        assert after['retained_report_bytes']==before['retained_report_bytes']
        record_property('cancellation_receipt',json.dumps(dict(stage=stage,events=observed,status=results[0].status,
            old_report_id=old.report_id,history_preserved=True)))
    finally:
        release.set();p.app.end_session(p.session);runner.shutdown()

def test_failed_compact_replacement_keeps_old_charge_and_publication(prepared,monkeypatch):
    p=prepared;frozen=pin(p);old=inspection(p);before=p.app.refinement_snapshot(p.session);limits=[]
    original=p.domain.inspect_combination
    def limited(*a,**kw):
        limits.append(kw['memory_limit_bytes']);kw['memory_limit_bytes']=32
        return original(*a,**kw)
    monkeypatch.setattr(p.domain,'inspect_combination',limited)
    results=[]
    p.app.submit_combination_inspection(p.session,frozen.set_id,frozen.source_discovery_id,before['generation'],
        p.ids[1],InspectionOptions(),result_callback=results.append,callback_dispatcher=lambda f:f())
    assert len(results)==1 and results[0].status=='failed' and 'report_budget_exceeded' in results[0].error_message
    assert limits==[134217728-before['retained_total_bytes']]
    assert p.app.refinement_inspection_result(p.session,frozen.set_id) is old
    after=p.app.refinement_snapshot(p.session);unchanged_history(before,after)
    assert after['retained_total_bytes']==before['retained_total_bytes']
