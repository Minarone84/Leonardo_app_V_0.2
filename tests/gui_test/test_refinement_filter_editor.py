"""Task 1080 granular input and production-composed refinement interactions."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget,QPushButton,QMessageBox

from leonardo.analysis.refinement_models import GranularPredicate as P,GranularGroup as G,GranularRefinement as D
from leonardo.analysis.refinement_models import convert_legacy_refinement
from leonardo.analysis.pattern_models import PatternRefinement
from leonardo.analysis.pattern_refinement import pin_patterns
from leonardo.gui.analysis.refinement_filter_editor import GranularFilterEditor
from tests.analysis_test.test_granular_evidence import make_case,quantity,spec
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture,TOLERANT
from tests.analysis_test.test_trend_start_enrichment import movement
from tests.gui_test.test_trend_start_patterns_tab import qapp,seed_tab
from tests.gui_test.test_pre_event_pattern_controls import dispose
from tests.gui_test.test_analysis_execution_presenter import until
from tests.gui_test.test_pattern_refinement_workflow import prepared_gui,pin_gui,_r2_history_popup,_r2_spies,_r2_same_saved


@pytest.fixture(scope='module')
def context(tmp_path_factory):return make_case(tmp_path_factory.mktemp('editor'))[0].filter_context()


def mixed_definition(context):
    pid=context['columns']['delta']['profile_id']
    return D(common=(G(conditions=(quantity('duration','structural','bars',basis='formation',minimum=0,maximum=80),)),
        G('ANY',(P('context','down','boolean',allowed=(False,)),P('context','previous_direction','category',allowed=('NONE',))))),
        outcome=(G('ANY',(quantity(basis='completed',minimum=0),quantity('pullbacks','count','count',basis='observed',cohort='internal_recovered',minimum=0))),
            G(conditions=(P('column','raw_value','native',column='delta',profile_id=pid,offset=-1,minimum=Decimal('1e-23'),upper_inclusive=False),))))


def activate(page,definition):
    page.granular_editor.set_value(definition)
    page.mode.setCurrentIndex(page.mode.findData('granular'))
    page._draft_changed()


@pytest.mark.parametrize('value',('0','-0.00000000000000000001','1.23456789e-16','1e50'))
def test_exact_keyboard_values_and_single_change(qapp,context,value):
    editor=GranularFilterEditor();editor.set_context(context);editor.set_value(spec(quantity()))
    signals=[];editor.changed.connect(lambda:signals.append(True))
    try:
        editor.show();row=editor.groups['outcome'][0].rows[0];row.minimum.selectAll()
        QTest.keyClicks(row.minimum,value)
        assert editor.value().outcome[0].conditions[0].minimum==Decimal(value)
        assert signals
        signals.clear();row.enabled.show();QCoreApplication.processEvents()
        QTest.mouseClick(row.enabled,Qt.MouseButton.LeftButton)
        assert not editor.value().outcome[0].conditions[0].enabled and len(signals)==1
        before=len(signals);editor.set_value(editor.value());editor.set_context(context);assert len(signals)==before
    finally:dispose(editor)


def test_group_row_order_limits_strict_intervals_and_unavailable_choices(qapp,context):
    editor=GranularFilterEditor();editor.set_context(context);editor.set_value(mixed_definition(context))
    try:
        original=editor.value();assert D.from_dict(original.to_dict())==original
        row=editor.groups['outcome'][1].rows[0];row.minimum.setText('0');row.maximum.setText('0')
        with pytest.raises(ValueError,match='empty'):editor.value()
        row.upper_inclusive.setChecked(True);assert editor.value().outcome[1].conditions[0].maximum==0
        row.maximum.clear();row.minimum.setText('NaN')
        with pytest.raises(ValueError,match='finite'):editor.value()
        assert row.minimum.text()=='NaN'
        editor.set_value(original);group=editor.groups['outcome'][0];group.move_row(group.rows[0],1)
        assert editor.value().outcome[0].conditions==tuple(reversed(original.outcome[0].conditions))
        editor.move_group(editor.groups['outcome'][0],1);assert editor.value().outcome[1].operator=='ANY'
        foreign=P('column','raw_value','native',column='not_here',profile_id='old-profile',offset=-199,minimum=1,enabled=False)
        editor.set_value(D(common=(G(conditions=(foreign,)),)))
        restored=editor.groups['common'][0].rows[0]
        assert editor.value().common[0].conditions[0]==foreign
        assert 'unavailable' in restored.column.currentText() and restored.profile.text()=='old-profile'
        restored.enabled.setChecked(True)
        with pytest.raises(ValueError,match='context'):editor.value()
        editor.set_value(D())
        for _ in range(9):editor.add_group('common')
        assert len(editor.groups['common'])==8 and not editor.add_buttons['outcome'].isEnabled()
        for i in range(34):
            editor.groups['common'][0].add_row(quantity(minimum=i))
        assert len(editor.groups['common'][0].rows)==32 and editor.value().active_count==32
        editor.groups['common'][1].add_row(quantity(minimum=100))
        with pytest.raises(ValueError,match='32 active'):editor.value()
        assert len(editor.groups['common'][0].rows)==32
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        names=[w.objectName() for w in editor.findChildren(QWidget) if w.objectName().startswith('analysis_suite.patterns.post_refinement.')]
        assert len(names)==len(set(names))
    finally:dispose(editor)


def test_domain_confirmation_and_field_changes_retain_raw_bounds(qapp,context,monkeypatch):
    editor=GranularFilterEditor();editor.set_context(context);editor.set_value(spec(quantity(minimum=Decimal('1.25'))))
    try:
        row=editor.groups['outcome'][0].rows[0]
        question=Mock(return_value=QMessageBox.StandardButton.No);monkeypatch.setattr(QMessageBox,'question',question)
        row.domain.setCurrentIndex(row.domain.findData('context'))
        assert row.domain.currentData()=='movement' and row.minimum.text()=='1.25'
        assert question.call_args.args[-1]==QMessageBox.StandardButton.No
        question.return_value=QMessageBox.StandardButton.Yes;row.domain.setCurrentIndex(row.domain.findData('duration'))
        assert row.minimum.text()=='' and editor.value().outcome[0].conditions[0].minimum is None
        row.minimum.setText('1.25')
        with pytest.raises(ValueError,match='integer'):editor.value()
        assert row.minimum.text()=='1.25'
        row.unit.setCurrentIndex(row.unit.findData('seconds'))
        assert editor.value().outcome[0].conditions[0].minimum==1250
        row.field.setCurrentIndex(row.field.findData('confirmation_delay'))
        assert row.minimum.text()=='1.25'
    finally:dispose(editor)


def test_modes_conversion_overwrite_and_invalid_completed_counts(prepared_gui,monkeypatch):
    p=prepared_gui;page=pin_gui(p);old=page.editor;frame=page.results.model.frame.copy(deep=True)
    assert page.mode.currentData()=='simple'
    page.editor.set_value(movement('formation',minimum=0))
    page.mode.setCurrentIndex(1)
    assert page.granular_editor.value()==D() and page.editor is old
    assert page.results.model.frame.equals(frame)
    page.convert_granular.click()
    expected=convert_legacy_refinement(movement('formation',minimum=0),comparison=p.study.request.comparison)
    assert page.draft()==expected
    row=page.granular_editor.groups['outcome'][0].rows[0];row.minimum.setText('invalid')
    assert not page.actions['evaluate'].isEnabled() and not page.actions['search_new'].isEnabled()
    assert 'Invalid draft' in page.draft_status.text() and page.results.model.frame.equals(frame)
    question=Mock(return_value=QMessageBox.StandardButton.No);monkeypatch.setattr(QMessageBox,'question',question)
    page.convert_granular.click();assert row.minimum.text()=='invalid'
    assert question.call_args.args[-1]==QMessageBox.StandardButton.No
    page.mode.setCurrentIndex(0);assert page.draft()==movement('formation',minimum=0)
    page.mode.setCurrentIndex(1);assert row.minimum.text()=='invalid'
    question.return_value=QMessageBox.StandardButton.Yes;page.convert_granular.click();assert page.draft()==expected


@pytest.mark.parametrize('keyboard',(False,True))
def test_current_granular_history_real_popup_restores_invalid_once(prepared_gui,monkeypatch,keyboard):
    p=prepared_gui;page=pin_gui(p);activate(page,spec(quantity(basis='formation',minimum=0)))
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;frame=page.results.model.frame.copy(deep=True)
    spies=_r2_spies(p,page,monkeypatch)
    page.granular_editor.groups['outcome'][0].rows[0].minimum.setText('invalid')
    before=p.service.refinement_snapshot(p.presenter.session)
    _r2_history_popup(p,page,before['active_checkpoint_id'],keyboard=keyboard)
    _r2_same_saved(p,page,before,result,frame)
    assert spies.selection.call_count==1 and not spies.worker.called
    assert page.mode.currentData()=='granular'
    _r2_history_popup(p,page,before['source_discovery_id'])
    assert page.mode.currentData()=='simple' and spies.selection.call_count==2


def test_population_presentation_and_actual_parent_zero_rule(prepared_gui):
    p=prepared_gui;page=pin_gui(p)
    activate(page,spec(quantity(basis='formation',minimum=9999)))
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    assert page.results.model.frame.matched.eq(0).all()
    page.actions['compare_parent'].click();assert page.views.currentIndex()==1
    assert page.comparison.model.frame.parent_id.eq(page._snapshot['source_discovery_id']).all()
    page.views.setCurrentIndex(4);before=page._result;count=page._snapshot['evaluation_count']
    page.population_cohort.setCurrentIndex(page.population_cohort.findData('excluded'))
    assert page.population.model.frame.cohort.eq('excluded').all()
    page.population.table.selectRow(0)
    record=json.loads(page.population_json.toPlainText())
    assert record['row_id']==page.population.current_row()['event_id'] and not page.condition_evidence.model.frame.empty
    page.population_partition.setCurrentIndex(page.population_partition.findData('excluded'))
    assert page._result is before and page._snapshot['evaluation_count']==count
    assert [page.views.tabText(i) for i in range(5)]==['Results','Compare','Population changes','Occurrences','Population evidence']
    page.actions['reset_discovery'].click();assert page.mode.currentData()=='simple'
    assert 'No granular' in page.population_status.text()


def test_explicit_new_search_and_confirmed_refused_failed_repin(prepared_gui,monkeypatch):
    p=prepared_gui;page=pin_gui(p);activate(page,spec(quantity(basis='formation',minimum=0)))
    before=p.service.refinement_snapshot(p.presenter.session)
    page.actions['search_new'].click();until(lambda:not p.presenter._busy)
    candidate=p.presenter._study_result
    assert candidate.granular_definition==page.draft(),p.view.log.toPlainText()
    result=p.view.pattern_tab.results;assert 'NEW DISCOVERY' in result.context.text()
    assert p.service.refinement_snapshot(p.presenter.session)['set_id']==before['set_id']
    selected=tuple(candidate.frame('patterns').pattern_id[:3]);assert selected
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:False)
    p.presenter.pin_patterns(selected);assert p.service.refinement_snapshot(p.presenter.session)['set_id']==before['set_id']
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:True)
    stamp=candidate._data.pop('_gr03_discovery_binding')
    p.presenter.pin_patterns(selected);until(lambda:not p.presenter._busy)
    assert p.service.refinement_snapshot(p.presenter.session)['set_id']==before['set_id']
    candidate._data['_gr03_discovery_binding']=stamp
    p.presenter.pin_patterns(selected);until(lambda:not p.presenter._busy)
    assert page._snapshot['set_id']!=before['set_id'] and page.mode.currentData()=='granular'
    old=page.results.model.frame.set_index('pattern_id')
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    new=page.results.model.frame.set_index('pattern_id');shared=[k for k in new if k in old]
    pd.testing.assert_frame_equal(new[shared],old[shared])


@pytest.fixture
def composed_gui(qapp,tmp_path,installed_theme_font):
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import load_default_config,AuditConfig
    from leonardo.gui.composition import GuiCompositionRoot
    frozen,parent,catalogue,axis,request=make_case(tmp_path/'synthetic',comparison='other_outcomes')
    app=LeonardoApp(replace(load_default_config(tmp_path/'runtime'),audit=AuditConfig(enabled=False)))
    app.startup();app.start_core_runtime();composition=GuiCompositionRoot(app.context);main=composition.create_main_window();main.show()
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        view=composition.analysis_suite_window;presenter=composition.analysis_suite_presenter
        until(lambda:not presenter._busy)
        from leonardo.analysis.trend_start_patterns import run_study
        study=run_study(parent,catalogue,request,axis)
        seed_tab(view.pattern_tab,parent,catalogue);presenter._binning_result=parent;presenter._study_result=study
        view.pattern_tab.results.set_result(study)
        yield SimpleNamespace(view=view,presenter=presenter,service=app.analysis_service,parent=parent,catalogue=catalogue,study=study,app=app)
    finally:
        main.close();app.shutdown();main.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.fixture
def installed_theme_font(qapp):
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    fonts=[]
    try:
        for name in ('segoeui.ttf','segoeuib.ttf'):
            path=Path('C:/Windows/Fonts')/name
            if path.is_file():
                identity=QFontDatabase.addApplicationFont(str(path));assert identity>=0
                fonts.append(identity)
        yield
    finally:
        for identity in fonts:QFontDatabase.removeApplicationFont(identity)


@pytest.mark.parametrize('size',((1280,820),(1000,700)))
def test_production_composition_granular_editor_evaluate_evidence_search(qapp,composed_gui,size,installed_theme_font):
    p=composed_gui;page=pin_gui(p);tab=p.view.pattern_tab
    p.view.resize(*size);p.view.show();p.view.analysis_tabs.setCurrentWidget(tab);tab.results.views.setCurrentWidget(page)
    definition=mixed_definition(page._snapshot['filter_context']);activate(page,definition)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);QCoreApplication.processEvents()
    assert page.draft()==definition
    for groups in page.granular_editor.groups.values():
        for group in groups:
            for row in group.rows:
                for label in row._labels.values():
                    if label.isVisibleTo(row) and label.text():
                        assert label.width()>0 and label.height()>0, label.text()
    for widget in (page.mode,page.convert_granular,page.granular_editor.groups['outcome'][1].rows[0].minimum,page.actions['evaluate']):
        tab.scroll.ensureWidgetVisible(widget);QCoreApplication.processEvents()
        assert widget.isVisibleTo(page) and widget.parentWidget().rect().contains(widget.geometry())
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    report=page._result.population_report()
    for reason in ('unavailable_requested_evidence','fails_outcome_definition'):
        matching=[i for i,r in enumerate(report['records']) if r['reason']==reason]
        if matching:
            page.views.setCurrentIndex(4);page.population.table.selectRow(matching[0]);assert page.population_json.toPlainText()
    page.results.table.selectRow(0);page.target_matches.click();until(lambda:not p.presenter._busy)
    assert page._occurrences is not None
    page.actions['search_new'].click();until(lambda:not p.presenter._busy)
    assert p.presenter._study_result.granular_definition==definition,p.view.log.toPlainText()
    assert page._snapshot['evaluation_count']==1
    assert p.view.width()==size[0]
    tab.results.views.setCurrentWidget(page)
    p.view.workspace_splitter.setSizes([320,size[0]-580,240])
    for _ in range(3):QCoreApplication.processEvents()
    assert tab.scroll.horizontalScrollBar().maximum()==0, [
        (w.objectName(),w.metaObject().className(),w.minimumSizeHint().width())
        for w in tab.scroll.widget().findChildren(QWidget)
        if w.isVisibleTo(tab.scroll.widget()) and w.minimumSizeHint().width()>tab.scroll.viewport().width()]
    context=json.loads(p.presenter._study_result.context)
    assert context['definition_summary'] in tab.results.context.text().replace('\u200b','')
    assert context['search_parent']['checkpoint_id'] in tab.results.context.toolTip()
    names=[w.objectName() for w in page.findChildren(QWidget) if w.objectName().startswith('analysis_suite.patterns.post_refinement.')]
    assert len(names)==len(set(names))


@pytest.mark.parametrize('operation',('evaluate','matches'))
def test_granular_current_reselection_cancels_held_terminal_and_retries(prepared_gui,monkeypatch,operation):
    p=prepared_gui;page=pin_gui(p);activate(page,spec(quantity(basis='formation')))
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    saved=p.service.refinement_snapshot(p.presenter.session);result=page._result;frame=page.results.model.frame.copy(deep=True)
    held=[];monkeypatch.setattr(p.presenter._dispatcher,'dispatch',held.append)
    if operation=='evaluate':
        page.granular_editor.groups['outcome'][0].rows[0].minimum.setText('9999');page.actions['evaluate'].click()
    else:page.results.table.selectRow(0);page.target_matches.click()
    assert held and p.presenter._busy
    if operation=='evaluate':page.granular_editor.groups['outcome'][0].rows[0].minimum.setText('invalid')
    _r2_history_popup(p,page,saved['active_checkpoint_id'])
    for callback in tuple(held):callback();callback()
    held.clear()
    _r2_same_saved(p,page,saved,result,frame,idle=False)
    assert page._occurrences is None
    page.actions['evaluate'].click()
    for callback in tuple(held):callback();callback()
    assert page._snapshot['evaluation_count']==saved['evaluation_count']+1
    assert page._result.parent_id==saved['active_checkpoint_id']


def test_empty_granular_search_remains_inspectable_and_unpinnable(prepared_gui):
    p=prepared_gui;page=pin_gui(p);activate(page,spec(quantity(basis='formation',minimum=99999)))
    before=page._snapshot['set_id'];page.actions['search_new'].click();until(lambda:not p.presenter._busy)
    result=p.view.pattern_tab.results
    assert p.presenter._study_result.granular_definition is not None,p.view.log.toPlainText()
    assert result._result.frame('patterns').empty and not result.pin_selected.isEnabled()
    assert not result.events.model.frame.empty and 'NEW DISCOVERY' in result.context.text()
    assert p.service.refinement_snapshot(p.presenter.session)['set_id']==before


# Task 1080 R2: typed profile identities remain separate from display text.
def _r2_identity_transform(token):
    def transform(parent,cat,axis,request,store,manifest,bundle):
        from leonardo.analysis.trend_start_patterns import build_catalogue as _r2_build,analysis_key as _r2_key
        columns=[]
        for column in parent.columns:
            if column.request.source=='delta':
                frame=column.to_frame();frame['profile_id']=token
                column=replace(column,profile=replace(column.profile,profile_id=token),_frame=frame)
            columns.append(column)
        parent=replace(parent,columns=tuple(columns))
        return parent,_r2_build(parent,bundle,axis),axis,replace(request,run_key=_r2_key(parent))
    return transform


@pytest.mark.parametrize('token',('None','none','NONE','0','das_literal','  literal  '))
@pytest.mark.parametrize('field',('raw_value','label'))
def test_r2_typed_profile_roundtrip_on_genuinely_pinned_source(qapp,tmp_path,token,field):
    from leonardo.analysis.pattern_refinement import evaluate_granular_patterns as _r2_evaluate
    frozen,*_=make_case(tmp_path,transform=_r2_identity_transform(token))
    condition=P('column',field,'native' if field=='raw_value' else 'label',column='delta',profile_id=token,offset=-1,
        minimum=0 if field=='raw_value' else None,allowed=() if field=='raw_value' else ('P01',))
    definition=D(common=(G(conditions=(condition,)),))
    expected=_r2_evaluate(frozen,definition)
    editor=GranularFilterEditor();signals=[];editor.changed.connect(lambda:signals.append(True))
    try:
        editor.set_context(frozen.filter_context());editor.set_value(definition)
        row=editor.groups['common'][0].rows[0]
        assert row.value()==condition and editor.value()==definition
        assert type(row.value().profile_id) is str and D.from_dict(editor.value().to_dict())==definition
        row.profile.setText('display text is not identity')
        assert row.value().profile_id==token
        editor.set_context(frozen.filter_context())
        assert row.profile.text()==token and editor.value()==definition and signals==[]
        actual=_r2_evaluate(frozen,editor.value())
        assert actual.evaluation_id==expected.evaluation_id and actual.population_report()==expected.population_report()
        pd.testing.assert_frame_equal(actual.frame('patterns'),expected.frame('patterns'))
    finally:dispose(editor)


def test_r2_actual_none_raw_profile_is_genuine_and_label_none_stays_invalid(qapp,tmp_path):
    from leonardo.analysis.pattern_refinement import evaluate_granular_patterns as _r2_evaluate
    def _r2_profileless(parent,cat,axis,request,store,manifest,bundle):
        from leonardo.analysis.trend_start_patterns import build_catalogue as _r2_build,analysis_key as _r2_key
        columns=[]
        for item in parent.columns:
            if item.request.source=='delta':
                frame=item.to_frame();frame['profile_id']=None;frame['bin_label']=None
                item=replace(item,profile=None,bins=(),_frame=frame)
            columns.append(item)
        parent=replace(parent,columns=tuple(columns))
        return parent,_r2_build(parent,bundle,axis),axis,replace(request,run_key=_r2_key(parent),columns=('volume_change',))
    frozen,*_=make_case(tmp_path,transform=_r2_profileless)
    context=frozen.filter_context()
    column=next(name for name,value in context['columns'].items() if value['profile_id'] is None)
    condition=P('column','raw_value','native',column=column,profile_id=None,offset=-1,minimum=0)
    definition=D(common=(G(conditions=(condition,)),))
    editor=GranularFilterEditor();editor.set_context(context);editor.set_value(definition)
    try:
        assert editor.value()==definition and editor.value().common[0].conditions[0].profile_id is None
        editor.set_context(context);assert editor.value()==definition
        assert _r2_evaluate(frozen,editor.value()).population_report()['records']
        with pytest.raises(ValueError,match='missing label profile'):replace(condition,field='label',unit='label',minimum=None,allowed=('P01',))
    finally:dispose(editor)


def test_r2_refresh_preserves_foreign_identity_and_explicit_selection_updates_it(qapp,context):
    original=context['columns']['delta']['profile_id']
    condition=P('column','raw_value','native',column='delta',profile_id=original,offset=-1,minimum=0)
    editor=GranularFilterEditor();editor.set_context(context);editor.set_value(D(common=(G(conditions=(condition,)),)))
    signals=[];editor.changed.connect(lambda:signals.append(True))
    try:
        changed=deepcopy(context);changed['columns']['delta']['profile_id']='None'
        changed['columns']['new_explicit']=deepcopy(changed['columns']['delta']);changed['columns']['new_explicit']['profile_id']='0'
        editor.set_context(changed);row=editor.groups['common'][0].rows[0]
        assert row.value().profile_id==original and signals==[]
        with pytest.raises(ValueError,match='profile'):editor.value()
        row.column.setCurrentIndex(row.column.findData('new_explicit'))
        assert row.value().profile_id=='0' and len(signals)==1
        assert editor.value().common[0].conditions[0].profile_id=='0'
        foreign=replace(condition,column='foreign',profile_id='None',enabled=False)
        editor.set_value(D(common=(G(conditions=(foreign,)),)));editor.set_context(changed)
        assert editor.value().common[0].conditions[0]==foreign
        editor.groups['common'][0].rows[0].enabled.setChecked(True)
        with pytest.raises(ValueError,match='context'):editor.value()
    finally:dispose(editor)


@pytest.fixture
def _r2_identity_composed_gui(qapp,tmp_path,installed_theme_font):
    from leonardo.core.app import LeonardoApp as _r2_App
    from leonardo.core.config import load_default_config as _r2_config,AuditConfig as _r2_Audit
    from leonardo.gui.composition import GuiCompositionRoot as _r2_Composition
    from leonardo.analysis.trend_start_patterns import run_study as _r2_run
    frozen,parent,catalogue,axis,request=make_case(tmp_path/'synthetic',comparison='non_start',transform=_r2_identity_transform('None'))
    app=_r2_App(replace(_r2_config(tmp_path/'runtime'),audit=_r2_Audit(enabled=False)))
    app.startup();app.start_core_runtime();composition=_r2_Composition(app.context);main=composition.create_main_window();main.show()
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        view=composition.analysis_suite_window;presenter=composition.analysis_suite_presenter
        until(lambda:not presenter._busy)
        study=_r2_run(parent,catalogue,request,axis)
        seed_tab(view.pattern_tab,parent,catalogue);presenter._binning_result=parent;presenter._study_result=study
        view.pattern_tab.results.set_result(study)
        yield SimpleNamespace(view=view,presenter=presenter,service=app.analysis_service,parent=parent,catalogue=catalogue,study=study,app=app)
    finally:
        main.close();app.shutdown();main.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('keyboard',(False,True),ids=('mouse','keyboard'))
def test_r2_literal_profile_composed_history_restores_once(_r2_identity_composed_gui,monkeypatch,keyboard):
    p=_r2_identity_composed_gui;page=pin_gui(p)
    condition=P('column','raw_value','native',column='delta',profile_id='None',offset=-1,minimum=0)
    definition=D(common=(G(conditions=(condition,)),));activate(page,definition)
    assert page.actions['evaluate'].isEnabled()
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;frame=page.results.model.frame.copy(deep=True)
    spies=_r2_spies(p,page,monkeypatch)
    page.granular_editor.groups['common'][0].rows[0].minimum.setText('invalid')
    assert not page.actions['evaluate'].isEnabled()
    before=p.service.refinement_snapshot(p.presenter.session)
    _r2_history_popup(p,page,before['active_checkpoint_id'],keyboard=keyboard)
    _r2_same_saved(p,page,before,result,frame)
    assert page.draft()==definition and type(page.draft().common[0].conditions[0].profile_id) is str
    assert spies.selection.call_count==1 and not spies.worker.called
