"""Task1083 date drafts and real Core publication; no persistent display settings."""
from dataclasses import replace
from threading import Event
from time import monotonic
import json

import pytest
from PySide6.QtCore import QCoreApplication, QDateTime, QPoint, QRect, Qt
from PySide6.QtWidgets import QMessageBox
from leonardo.analysis.refinement_models import AnchorDateRange as Range, GranularRefinement as D, GranularGroup as G
from leonardo.analysis.pattern_models import FamilyScope
from leonardo.gui.analysis.refinement_filter_editor import GranularFilterEditor
from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
from tests.gui_test.test_family_scope_workflow import family_gui, _gr05_pin_gui
from tests.gui_test.test_trend_start_patterns_tab import qapp, select_event
from tests.gui_test.test_refinement_filter_editor import installed_theme_font, activate
from tests.gui_test.test_pattern_refinement_workflow import _r2_history_popup, _r2_spies, _r2_same_saved
from tests.gui_test.test_analysis_execution_presenter import until
from tests.gui_test.test_pre_event_pattern_controls import dispose
from tests.analysis_test.test_family_scope_refinement import multi_case
from tests.analysis_test.test_refinement_outcomes import horizon
from leonardo.analysis.pattern_refinement import pin_patterns


@pytest.fixture(autouse=True)
def session_zone(qapp):
    previous=qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'UTC')
    yield
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,previous)


@pytest.fixture(scope='module')
def root_context(tmp_path_factory):
    parent,cat,_,_,study,_=multi_case(tmp_path_factory.mktemp('date_editor'),comparison='recurrence')
    return pin_patterns(parent,cat,study,study.frame('patterns').pattern_id.tolist()[:2]).filter_context()


def wait_operation(p,kind):
    started=monotonic();until(lambda:not p.presenter._busy,timeout=60000)
    print('GRDATE_WAIT '+json.dumps(dict(operation=kind,elapsed_seconds=monotonic()-started,limit_seconds=60)),flush=True)


def set_ms(editor,value):editor.setDateTime(QDateTime.fromMSecsSinceEpoch(value,editor.timeZone()))


def test_bound_dates_exact_signals_restoration_and_context(root_context,qapp):
    editor=GranularFilterEditor();signals=[];editor.changed.connect(lambda:signals.append(1))
    try:
        editor.set_context(root_context);request=root_context['original_request'];control=editor.anchor_range
        assert editor.value().anchor_range is None and not control.start.isEnabled()
        assert control.start.dateTime().toMSecsSinceEpoch()==request.start_ms
        assert control.end.dateTime().toMSecsSinceEpoch()==request.end_ms
        assert not signals
        control.enabled.click();assert len(signals)==1
        set_ms(control.start,request.start_ms+123);assert len(signals)==2
        set_ms(control.end,request.end_ms-123);assert len(signals)==3
        assert editor.value().anchor_range==Range(request.start_ms+123,request.end_ms-123)
        saved=editor.value();editor.set_value(saved);editor.set_context(root_context);editor.refresh_display_time()
        assert len(signals)==3 and editor.value()==saved
        control.enabled.click();pair=(control.start.dateTime(),control.end.dateTime())
        assert editor.value().anchor_range is None
        control.enabled.click();assert (control.start.dateTime(),control.end.dateTime())==pair
        editor.set_value(D());assert control.start.dateTime().toMSecsSinceEpoch()==request.start_ms
    finally:dispose(editor)


@pytest.mark.parametrize('fault',('outside','reversed','singleton','between','unbound','unrepresentable'))
def test_invalid_or_empty_dates_are_not_clamped(root_context,qapp,fault):
    editor=GranularFilterEditor()
    try:
        editor.set_context(root_context);request=root_context['original_request'];control=editor.anchor_range
        if fault=='unbound':editor.set_context({});control.enabled.click()
        elif fault=='unrepresentable':editor.set_value(D(anchor_range=Range(2**63-2,2**63-1)))
        else:
            control.enabled.click()
            start=request.start_ms-1 if fault=='outside' else request.start_ms+123
            end=start if fault=='singleton' else start+1 if fault=='between' else start-1 if fault=='reversed' else request.end_ms
            set_ms(control.start,start);set_ms(control.end,end)
            assert control.start.dateTime().toMSecsSinceEpoch()==start and control.end.dateTime().toMSecsSinceEpoch()==end
        if fault in ('singleton','between'):assert editor.value().anchor_range==Range(start,end)
        else:
            with pytest.raises((ValueError,TypeError)):editor.value()
            assert 'Invalid' in editor.status.text() or 'Invalid' in control.status.text()
        if fault=='unrepresentable':assert str(2**63-1) in control.status.text()
    finally:dispose(editor)


def test_timezone_dst_exact_and_invalid_text_is_not_repaired(root_context,qapp):
    editor=GranularFilterEditor();signals=[];editor.changed.connect(lambda:signals.append(1))
    try:
        # 2024-03-31 spans Europe's DST jump, with exact nonzero milliseconds.
        context=dict(root_context);context['original_request']=replace(context['original_request'],start_ms=1711836000123,end_ms=1711846800789)
        editor.set_context(context);definition=D(anchor_range=Range(1711845000456,1711846800789));editor.set_value(definition)
        control=editor.anchor_range
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'Europe/Rome');editor.refresh_display_time()
        assert editor.value()==definition and 'Europe/Rome' in control.zone.text() and not signals
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'UTC');editor.refresh_display_time()
        assert editor.value().identity==definition.identity and not signals
        control.start.clear()
        assert not control.start.hasAcceptableInput()
        raw=control.start.lineEdit().text();qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'Europe/Rome');editor.refresh_display_time()
        assert control.start.lineEdit().text()==raw
        with pytest.raises(ValueError):editor.value()
        assert not signals
    finally:dispose(editor)


def definition_for(p):
    request=p.study.request
    return D(outcome=(G(conditions=(horizon(n=6,minimum=-1000),)),),
        family_scope=FamilyScope('selected',p.case.families[:2]),
        anchor_range=Range(request.start_ms+12_000_123,request.end_ms-12_000_123))


@pytest.mark.parametrize('keyboard',(False,True),ids=('mouse','keyboard'))
def test_actual_core_history_invalid_draft_and_compact_full_form(family_gui,monkeypatch,keyboard):
    p=family_gui;page=_gr05_pin_gui(p);definition=definition_for(p);activate(page,definition)
    page.actions['evaluate'].click();wait_operation(p,'evaluate')
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;frame=page.results.model.frame.copy(deep=True);saved=p.service.refinement_snapshot(p.presenter.session)
    control=page.granular_editor.anchor_range
    set_ms(control.start,p.study.request.start_ms-1)
    assert not page.actions['evaluate'].isEnabled() and not page.actions['search_new'].isEnabled()
    assert page._result is result and page.results.model.frame.equals(frame)
    assert 'COMPLETED' in page.context.text() and 'Invalid' in page.draft_status.text()
    restore_before=p.service.refinement_snapshot(p.presenter.session)
    assert restore_before['generation']==saved['generation']+1
    assert {k:v for k,v in restore_before.items() if k!='generation'}=={k:v for k,v in saved.items() if k!='generation'}
    calls=_r2_spies(p,page,monkeypatch)
    _r2_history_popup(p,page,saved['active_checkpoint_id'],keyboard=keyboard)
    _r2_same_saved(p,page,restore_before,result,frame)
    assert calls.selection.call_count==1 and calls.worker.call_count==0 and page.draft()==definition
    tab=p.view.pattern_tab;select_event(tab,p.study.request.event_kind,None);tab.mode.setCurrentIndex(tab.mode.findData('pre_event'))
    p.view.resize(1000,700);p.view.workspace_splitter.setSizes([140,720,140]);QCoreApplication.processEvents()
    assert (p.view.width(),p.view.height())==(1000,700) and tab.pre_event_controls.isVisibleTo(tab.scroll.widget())
    for widget in (page.history,control.enabled,control.start,control.end,page.granular_editor.family_scope.members,
                   page.granular_editor.groups['outcome'][0].rows[0].horizon_bars,page.actions['evaluate']):
        tab.scroll.ensureWidgetVisible(widget);QCoreApplication.processEvents()
        rect=QRect(widget.mapTo(tab.scroll.viewport(),QPoint(0,0)),widget.size())
        assert tab.scroll.viewport().rect().contains(rect),(widget.objectName(),rect)
        assert tab.scroll.horizontalScrollBar().maximum()==0
    assert page._result is result and page.draft()==definition
    page.actions['compare_parent'].click();assert len(page.comparison.model.frame)==saved['pinned_count']
    page.results.table.selectRow(0);page.target_matches.click();wait_operation(p,'matches')
    assert page._occurrences is not None


def test_date_only_conversion_requires_confirmation_and_separate_drafts(family_gui,monkeypatch):
    p=family_gui;page=_gr05_pin_gui(p)
    page.convert_granular.click();assert page.mode.currentData()=='granular'
    request=p.study.request;date=Range(request.start_ms+1,request.end_ms-1)
    # An active outcome is required by this root; date-only refers to replacement guard, before validation.
    page.granular_editor.set_value(D(anchor_range=date));page._granular_edited=False;page._draft_changed()
    calls=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *args:(calls.append(args),QMessageBox.StandardButton.No)[1])
    page.convert_granular.click();assert len(calls)==1 and page.granular_editor.anchor_range.value()==date
    set_ms(page.granular_editor.anchor_range.start,request.start_ms-1)
    page.convert_granular.click();assert len(calls)==2
    simple=page.editor.value();page.mode.setCurrentIndex(page.mode.findData('simple'));assert page.draft()==simple
    page.mode.setCurrentIndex(page.mode.findData('granular'))
    assert page.granular_editor.anchor_range.start.dateTime().toMSecsSinceEpoch()==request.start_ms-1
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
    page.convert_granular.click();assert page.granular_editor.value().anchor_range is None


def test_empty_search_retains_fixed_rules_then_clear_and_explicit_repin(family_gui,monkeypatch):
    p=family_gui;page=_gr05_pin_gui(p);definition=definition_for(p);request=p.study.request
    full_definition=replace(definition,anchor_range=None);activate(page,full_definition)
    page.actions['evaluate'].click();wait_operation(p,'undated baseline evaluate')
    assert page._result.granular_definition==full_definition
    full_patterns=page._result.frame('patterns');full_population=page._result.population_report()
    assert full_population['samples']
    empty=replace(definition,anchor_range=Range(request.start_ms+1,request.start_ms+2));activate(page,empty)
    page.actions['evaluate'].click();wait_operation(p,'empty evaluate')
    result=page._result;assert result.granular_definition==empty,p.view.log.toPlainText()
    assert result.frame('patterns').matched.eq(0).all() and len(result.frame('patterns'))==page._snapshot['pinned_count']
    saved=p.service.refinement_snapshot(p.presenter.session)
    page.actions['search_new'].click();wait_operation(p,'empty search')
    candidate=p.presenter._study_result
    assert candidate.frame('patterns').empty and p.view.pattern_tab.results.pin_selection()==()
    assert not p.view.pattern_tab.results.pin_selected.isEnabled()
    assert page._result is result and p.service.refinement_snapshot(p.presenter.session)['history']==saved['history']
    page.granular_editor.anchor_range.enabled.click();page.actions['evaluate'].click();wait_operation(p,'clear date evaluate')
    assert page._result.granular_definition==full_definition
    assert page._result.frame('patterns').equals(full_patterns)
    restored_population=page._result.population_report()
    for key in ('report_id','definition','definition_id','source_request','resolved_split_ms',
                'records','samples','summary','family_scope','family_population','horizon_source'):
        assert restored_population[key]==full_population[key],key
    page.actions['search_new'].click();wait_operation(p,'full search')
    candidate=p.presenter._study_result;ids=tuple(candidate.frame('patterns').pattern_id[:2]);assert ids
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:True)
    _gr05_pin_gui(p,pattern_ids=ids)
    assert page.draft().anchor_range is None and page._snapshot['original_request'].start_ms==request.start_ms


@pytest.mark.parametrize('operation',('evaluate','search'))
@pytest.mark.parametrize('queued',(False,True),ids=('running','queued_delivery'))
def test_real_core_date_edit_cancels_and_explicit_retry(family_gui,monkeypatch,operation,queued):
    p=family_gui;page=_gr05_pin_gui(p);definition=definition_for(p);activate(page,definition)
    initial=page._result;saved=p.service.refinement_snapshot(p.presenter.session)
    entered=Event();release=Event();computed=Event();held=[]
    method='evaluate_pattern_set' if operation=='evaluate' else 'search_granular_patterns'
    original=getattr(p.service._service,method)
    dispatch=p.presenter._dispatcher.dispatch
    def controlled(*args,checkpoint,**kwargs):
        entered.set()
        if not queued:
            assert release.wait(60)
            checkpoint()
        result=original(*args,checkpoint=checkpoint,**kwargs);computed.set();return result
    monkeypatch.setattr(p.service._service,method,controlled)
    if queued:monkeypatch.setattr(p.presenter._dispatcher,'dispatch',held.append)
    try:
        page.actions['evaluate' if operation=='evaluate' else 'search_new'].click()
        until(entered.is_set,timeout=60000)
        if queued:until(lambda:computed.is_set() and bool(held) and not p.service.has_draining_workers,timeout=60000)
        set_ms(page.granular_editor.anchor_range.start,definition.anchor_range.start_ms+1)
        release.set()
        if queued:
            for callback in tuple(held):callback();callback()
        wait_operation(p,'cancelled '+operation)
        assert page._result is initial and p.service.refinement_snapshot(p.presenter.session)['evaluation_count']==saved['evaluation_count']
        monkeypatch.setattr(p.service._service,method,original)
        monkeypatch.setattr(p.presenter._dispatcher,'dispatch',dispatch)
        page.actions['evaluate' if operation=='evaluate' else 'search_new'].click();wait_operation(p,'explicit retry '+operation)
        if operation=='evaluate':assert page._snapshot['evaluation_count']==saved['evaluation_count']+1
        else:assert p.presenter._study_result.granular_definition.anchor_range.start_ms==definition.anchor_range.start_ms+1
    finally:release.set()


# Task1083 R3: genuine incomplete Qt edits, not rejected arbitrary date strings.
@pytest.mark.parametrize('endpoint',('start','end'))
@pytest.mark.parametrize('initial_zone,next_zone,start_ms,end_ms',(
    ('UTC','Europe/Rome',1711845000456,1711846800789),
    ('Europe/Rome','UTC',1729989000456,1729990800789),
),ids=('spring_forward','autumn_overlap'))
def test_r3_incomplete_keyboard_edit_survives_zone_refresh(root_context,qapp,endpoint,initial_zone,next_zone,start_ms,end_ms):
    from PySide6.QtTest import QTest
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,initial_zone)
    editor=GranularFilterEditor();signals=[];edits=[]
    try:
        context=dict(root_context)
        context['original_request']=replace(context['original_request'],start_ms=start_ms-3600000,end_ms=end_ms+3600000)
        definition=D(anchor_range=Range(start_ms,end_ms))
        editor.set_context(context);editor.set_value(definition)
        control=editor.anchor_range;date=getattr(control,endpoint)
        editor.changed.connect(lambda:signals.append(1));date.lineEdit().textEdited.connect(edits.append)
        original=date.lineEdit().text();other=control.end if endpoint=='start' else control.start
        other_text=other.lineEdit().text();values=(control.start.dateTime().toMSecsSinceEpoch(),control.end.dateTime().toMSecsSinceEpoch())
        assert original.startswith('2024-') and not date.keyboardTracking()
        date.lineEdit().setSelection(3,1)
        QTest.keyClick(date,Qt.Key.Key_Backspace)
        partial=original[:3]+original[4:]
        assert date.lineEdit().text()==partial and not date.hasAcceptableInput()
        assert edits==[partial] and signals==[1]
        assert (control.start.dateTime().toMSecsSinceEpoch(),control.end.dateTime().toMSecsSinceEpoch())==values
        with pytest.raises(ValueError,match='complete valid anchor date'):editor.value()
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,next_zone)
        editor.refresh_display_time()
        editor.set_context(context)
        assert date.lineEdit().text()==partial and not date.hasAcceptableInput()
        assert other.lineEdit().text()==other_text
        assert date.timeZone().id().data().decode()==initial_zone
        assert initial_zone in control.zone.text() and 'Invalid' in control.status.text()
        assert edits==[partial] and signals==[1]
        with pytest.raises(ValueError,match='complete valid anchor date'):editor.value()
        editor.set_value(definition)
        assert editor.value()==definition and editor.value().identity==definition.identity
        assert (control.start.dateTime().toMSecsSinceEpoch(),control.end.dateTime().toMSecsSinceEpoch())==values
        assert control.start.hasAcceptableInput() and control.end.hasAcceptableInput()
        assert next_zone in control.zone.text() and edits==[partial] and signals==[1]
    finally:dispose(editor)


def test_r3_real_incomplete_draft_disables_actions_without_losing_checkpoint(family_gui,monkeypatch,qapp):
    from PySide6.QtTest import QTest
    p=family_gui;page=_gr05_pin_gui(p);definition=definition_for(p);activate(page,definition)
    page.actions['evaluate'].click();wait_operation(p,'R3 completed date evaluation')
    result=page._result;frame=page.results.model.frame.copy(deep=True)
    saved=p.service.refinement_snapshot(p.presenter.session)
    assert result.granular_definition==definition
    control=page.granular_editor.anchor_range;date=control.start
    raw=date.lineEdit().text();edits=[];signals=[]
    date.lineEdit().textEdited.connect(edits.append);page.draft_changed.connect(lambda:signals.append(1))
    date.lineEdit().setSelection(3,1);QTest.keyClick(date,Qt.Key.Key_Backspace)
    partial=raw[:3]+raw[4:]
    assert date.lineEdit().text()==partial and not date.hasAcceptableInput()
    assert edits==[partial] and signals==[1]
    assert not page.actions['evaluate'].isEnabled() and not page.actions['search_new'].isEnabled()
    assert page._result is result and page.results.model.frame.equals(frame)
    assert 'Invalid' in page.draft_status.text()
    invalid_snapshot=p.service.refinement_snapshot(p.presenter.session)
    assert invalid_snapshot['generation']==saved['generation']+1
    assert {k:v for k,v in invalid_snapshot.items() if k!='generation'}=={k:v for k,v in saved.items() if k!='generation'}
    calls=_r2_spies(p,page,monkeypatch)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'Europe/Rome');p.presenter.refresh_display_time()
    assert date.lineEdit().text()==partial and not date.hasAcceptableInput()
    assert signals==[1] and p.service.refinement_snapshot(p.presenter.session)==invalid_snapshot
    assert calls.selection.call_count==0 and calls.worker.call_count==0
    assert not page.actions['evaluate'].isEnabled() and not page.actions['search_new'].isEnabled()
    _r2_history_popup(p,page,saved['active_checkpoint_id'],keyboard=True)
    _r2_same_saved(p,page,invalid_snapshot,result,frame)
    assert calls.selection.call_count==1 and calls.worker.call_count==0
    assert page.draft()==definition and page.actions['evaluate'].isEnabled() and page.actions['search_new'].isEnabled()
    assert date.hasAcceptableInput() and 'Europe/Rome' in control.zone.text()
