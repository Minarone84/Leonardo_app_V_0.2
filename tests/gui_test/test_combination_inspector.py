"""Production-composed GR06 views, exact row links and report-only actions."""
from dataclasses import replace
import json
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QPoint

from leonardo.analysis.refinement_models import GranularRefinement as D, GranularGroup as G, GranularPredicate as P
from tests.gui_test.test_family_scope_workflow import family_gui, _gr05_pin_gui
from tests.gui_test.test_trend_start_patterns_tab import qapp, select_event
from tests.gui_test.test_refinement_filter_editor import installed_theme_font, activate
from tests.gui_test.test_pattern_refinement_workflow import _r2_history_popup, _r2_spies
from tests.gui_test.test_analysis_execution_presenter import until


def wait(p):
    started=monotonic();until(lambda:not p.presenter._busy,timeout=60000)
    assert monotonic()-started<60


def start(p,granular=True):
    rows=p.study.frame('patterns');selected=[]
    for identity in rows.pattern_id:
        terms=p.study._data['patterns'][identity]['terms']
        if len({t.column for t in terms})>1 and len({t.offset for t in terms})>1:selected.append(identity)
    assert selected,'genuine fixture must have a multi-column/multi-offset retained combination'
    identity=selected[0];ids=tuple(dict.fromkeys([identity,*rows.pattern_id[:5]]))
    page=_gr05_pin_gui(p,pattern_ids=ids)
    if granular:
        name=p.case.request.columns[0];profile=page._snapshot['filter_context']['columns'][name]['profile_id']
        definition=D(common=(G('ANY',(P('column','raw_value','native',column=name,profile_id=profile,offset=-1,minimum=995),
            P('column','raw_value','native',column=name,profile_id=profile,offset=-1,maximum=985))),),
            outcome=(G(conditions=(P('horizon','terminal_directional','pct',horizon_bars=6,minimum=0),)),))
        activate(page,definition);page.actions['evaluate'].click();wait(p)
        assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
        assert page._result.granular_definition==definition
    page.inspector.select_rule(identity)
    assert page.inspector.rule_selector.currentData()==identity
    return page,identity


def inspect(p,page):
    before=p.service.refinement_snapshot(p.presenter.session)
    page.inspector.inspect_button.click();wait(p)
    report=page.inspector._report
    assert report is not None,p.view.log.toPlainText()
    after=p.service.refinement_snapshot(p.presenter.session)
    assert after['history']==before['history'] and after['active_checkpoint_id']==before['active_checkpoint_id']
    return report


def test_production_complete_inspector_subviews_and_exact_links(family_gui):
    p=family_gui;page,identity=start(p);view=page.inspector;report=inspect(p,page)
    assert view.views.count()==7 and report.header['pattern_id']==identity
    assert len({t['column'] for t in report.header['rule']})>1 and len({t['offset'] for t in report.header['rule']})>1
    records=json.loads(report.payload)['records']['current']
    assert {r['cohort'] for r in records.values()}>={'target','comparison'}
    row=next(r for r in report.frame('comparison').to_dict('records') if r['side']=='current' and r['period']=='eligible_combined' and not r['ready_only'] and r['matching']=='original allowed sets')
    for cell in 'abcd':
        view._support_selected('comparison',row)
        view.link_choices.setCurrentIndex(view.link_choices.findData(row[cell+'_rows']));view.open_link.click()
        assert view.ledger.receipt['support_set_total']==row[cell]
        assert view.ledger.receipt['retained_total']==len(records)
        if len(view.ledger.model.frame):
            view.ledger.table.selectRow(0)
            detail=json.loads(view.details.toPlainText())
            assert detail['row_id'] in records and all('raw_value' in term for term in detail['terms'])
    for title in view.pages:
        view.views.setCurrentWidget(view.pages[title]);QCoreApplication.processEvents()
        assert view.views.currentWidget() is view.pages[title]


def test_simple_checkpoint_metrics_do_not_convert_or_edit_draft(family_gui):
    p=family_gui;page,_=start(p,granular=False);view=page.inspector
    report=inspect(p,page);before=p.service.refinement_snapshot(p.presenter.session)
    assert not view.compare_button.isEnabled() and 'Convert/Evaluate' in view.omission_status.text()
    selector=view.metric_selector;selector.domain.setCurrentIndex(selector.domain.findData('horizon'))
    selector.horizon.setText('bad');view.add_metric.click()
    assert not view._extras and 'integer' in view.metric_note.text()
    selector.horizon.setText('1000');view.add_metric.click()
    assert len(view._extras)==1 and page._result.granular_definition is None
    assert view._report is report
    second=inspect(p,page)
    after=p.service.refinement_snapshot(p.presenter.session)
    assert before['history']==after['history'] and before['active_refinement']==after['active_refinement']
    table=second.frame('distributions');assert table.base_selected.sum()>0 and table.source_coherence_unavailable.sum()>0


def test_explicit_sensitivity_and_variant_do_not_insert_history(family_gui):
    p=family_gui;page,identity=start(p);view=page.inspector
    before=p.service.refinement_snapshot(p.presenter.session)
    for index in range(view.omissions.count()):
        item=view.omissions.item(index)
        if item.data(Qt.ItemDataRole.UserRole).key in ('common/0/0','outcome/0/0'):item.setCheckState(Qt.CheckState.Checked)
    assert len(view._planned)==2 and view.compare_button.isEnabled()
    assert view._planned[1]['status']=='not_evaluated_invalid_definition'
    view.compare_button.click();wait(p)
    report=view._sensitivity;assert report is not None,p.view.log.toPlainText()
    assert len(report.evaluations)==1
    assert tuple(report.variant('common/0/0').frame('patterns').pattern_id)==before['pinned_ids']
    assert p.service.refinement_snapshot(p.presenter.session)['history']==before['history']
    view.inspect_variant.click();wait(p)
    assert view._report.header['variant_key']=='common/0/0'
    assert 'not a checkpoint' in view.context.text()
    assert p.service.refinement_snapshot(p.presenter.session)['history']==before['history']


def test_full_ledger_is_filtered_before_paging_and_view_changes_submit_nothing(family_gui,monkeypatch):
    from leonardo.analysis.pattern_models import PatternRefinement
    p=family_gui
    # A bounded initial non-start study supplies genuine timestamp controls, not duplicated rows.
    request=replace(p.case.request,comparison='non_start',
        end_ms=p.case.request.start_ms+(p.case.request.end_ms-p.case.request.start_ms)//4,
        refinement=PatternRefinement(family_scope=p.case.request.refinement.family_scope))
    p.study=p.case.service.run_patterns(p.parent,request)
    p.presenter._study_result=p.study
    p.view.pattern_tab.results.set_result(p.study)
    page,_=start(p,granular=False);view=page.inspector;report=inspect(p,page)
    all_rows=report.ledger(dict(side='current'))
    assert all_rows.attrs['retained_total']>50,'genuine calculated source must exercise hidden pages'
    calls=[]
    monkeypatch.setattr(p.service,'submit_combination_inspection',lambda *a,**kw:calls.append(1))
    view.ledger.load(report,dict(side='current'));first=set(view.ledger.model.frame.row_id)
    view.ledger.next.click();second=set(view.ledger.model.frame.row_id)
    assert first.isdisjoint(second) and view.ledger.page.value()==2
    records=json.loads(report.payload)['records']['current']
    hidden=next(key for key in view.ledger.model.frame.row_id if records[key]['cohort'] in ('target','comparison') and records[key]['partition'] in ('discovery','later'))
    family='ordinary' if records[hidden]['ordinary'] else records[hidden]['family']
    view.family.setCurrentIndex(view.family.findData(family))
    view.period.setCurrentIndex(view.period.findData('eligible_combined'))
    expected={k for k,r in records.items() if ('ordinary' if r['ordinary'] else r['family'])==family and r['cohort'] in ('target','comparison') and r['partition'] in ('discovery','later')}
    assert hidden in expected
    assert view.ledger.receipt['support_set_total']==len(expected)
    view.rule_sort.setCurrentIndex(view.rule_sort.findData('matched'))
    view.rule_min.setText('0');view.rule_min.clear()
    assert calls==[]


def test_report_clear_preserves_invalid_draft_and_completed_checkpoint(family_gui):
    p=family_gui;page,_=start(p);view=page.inspector;inspect(p,page)
    before=p.service.refinement_snapshot(p.presenter.session)
    edit=page.granular_editor.groups['outcome'][0].rows[0].horizon_bars
    edit.setText('invalid')
    assert not page.actions['evaluate'].isEnabled() and view._report is not None
    view.clear_reports.click();wait(p)
    after=p.service.refinement_snapshot(p.presenter.session)
    assert edit.text()=='invalid' and after['history']==before['history']
    assert 'inspection_report' not in after and view._report is None


@pytest.mark.parametrize('width,height',((1000,700),(1280,820)))
def test_current_history_and_complete_form_geometry(family_gui,monkeypatch,width,height):
    p=family_gui;page,_=start(p);view=page.inspector;report=inspect(p,page)
    tab=p.view.pattern_tab
    p.view.analysis_tabs.setCurrentWidget(tab)
    select_event(tab,p.study.request.event_kind,None)
    tab.mode.setCurrentIndex(tab.mode.findData('pre_event'))
    assert tab.pre_event_controls.isVisibleTo(tab.scroll.widget())
    # The independent initial form must remain visible; no layout-label hiding.
    page.granular_editor.groups['outcome'][0].rows[0].horizon_bars.setText('invalid')
    saved=p.service.refinement_snapshot(p.presenter.session);calls=_r2_spies(p,page,monkeypatch)
    _r2_history_popup(p,page,saved['active_checkpoint_id'],keyboard=False)
    assert calls.selection.call_count==1 and calls.worker.call_count==0
    assert page._snapshot['evaluation_count']==saved['evaluation_count']
    assert view._report is report
    for size in ((width,height),(1280,820),(1000,700)):
        p.view.resize(*size);p.view.workspace_splitter.setSizes([180,max(420,size[0]-360),180]);QCoreApplication.processEvents()
        assert tab.scroll.horizontalScrollBar().maximum()==0
    page.views.setCurrentWidget(view)
    for title,control in (('Overview',view.inspect_button),('Distributions',view.add_metric),
            ('Examples and evidence',view.ledger.page),('Sensitivity',view.compare_button)):
        view.views.setCurrentWidget(view.pages[title]);tab.scroll.ensureWidgetVisible(control);QCoreApplication.processEvents()
        assert control.isVisibleTo(tab.scroll.widget())
        position=control.mapTo(tab.scroll.viewport(),QPoint(0,0))
        assert position.y()<tab.scroll.viewport().height() and position.y()+control.height()>0


@pytest.mark.parametrize('ending',('options','rule','draft'))
def test_blocked_report_intent_is_fenced_without_stale_repaint(family_gui,monkeypatch,ending):
    p=family_gui;page,_=start(p);view=page.inspector;old=inspect(p,page)
    entered,release=Event(),Event()
    original=p.app.analysis_domain_service.inspect_combination if hasattr(p.app,'analysis_domain_service') else None
    domain=p.service._service
    original=domain.inspect_combination
    def blocked(*a,**kw):
        entered.set();assert release.wait(60);kw['checkpoint']();return original(*a,**kw)
    monkeypatch.setattr(domain,'inspect_combination',blocked)
    try:
        view.inspect_button.click();until(entered.is_set,timeout=60000)
        if ending=='options':view.metric_selector.horizon.setText('7')
        elif ending=='rule':view.rule_selector.setCurrentIndex((view.rule_selector.currentIndex()+1)%view.rule_selector.count())
        else:page.granular_editor.groups['outcome'][0].rows[0].horizon_bars.setText('invalid')
        release.set();wait(p)
        assert view._report is old and page._snapshot['evaluation_count']==1
    finally:release.set()
