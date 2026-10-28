"""Real composed fixed-horizon editor, checkpoints and source evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from leonardo.analysis.refinement_models import GranularPredicate as P,GranularGroup as G,GranularRefinement as D
from leonardo.gui.analysis.refinement_filter_editor import GranularFilterEditor
from tests.analysis_test.test_refinement_outcomes import priced_case,horizon,spec
from tests.gui_test.test_trend_start_patterns_tab import qapp,seed_tab
from tests.gui_test.test_refinement_filter_editor import installed_theme_font,activate
from tests.gui_test.test_pattern_refinement_workflow import pin_gui,_r2_history_popup,_r2_spies,_r2_same_saved
from tests.gui_test.test_analysis_execution_presenter import until
from tests.gui_test.test_pre_event_pattern_controls import dispose


@pytest.fixture
def horizon_gui(qapp,tmp_path,installed_theme_font):
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import load_default_config,AuditConfig
    from leonardo.gui.composition import GuiCompositionRoot
    case=priced_case(tmp_path/'prices',direction='DOWN')
    app=LeonardoApp(replace(load_default_config(tmp_path/'runtime'),audit=AuditConfig(enabled=False)))
    app.startup();app.start_core_runtime();composition=GuiCompositionRoot(app.context);main=composition.create_main_window();main.show()
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        view=composition.analysis_suite_window;presenter=composition.analysis_suite_presenter
        until(lambda:not presenter._busy)
        seed_tab(view.pattern_tab,case.parent,case.catalogue);presenter._binning_result=case.parent;presenter._study_result=case.study
        view.pattern_tab.results.set_result(case.study)
        yield SimpleNamespace(view=view,presenter=presenter,service=app.analysis_service,parent=case.parent,
            catalogue=case.catalogue,study=case.study,case=case,app=app)
    finally:
        main.close();app.shutdown();main.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('text',('', '0','-1','1.5','1001','１２','+6','1e1'))
def test_invalid_horizon_text_retained_through_context_refresh(qapp,tmp_path,text):
    case=priced_case(tmp_path);editor=GranularFilterEditor();context=case.frozen.filter_context()
    editor.set_context(context);editor.set_value(spec(horizon()));signals=[];editor.changed.connect(lambda:signals.append(1))
    try:
        row=editor.groups['outcome'][0].rows[0];row.horizon_bars.setText(text)
        assert len(signals)==1
        with pytest.raises(ValueError,match='Next bars'):editor.value()
        editor.set_context(context);assert row.horizon_bars.text()==text and len(signals)==1
        editor.set_value(spec(horizon(n=12)));assert editor.value()==spec(horizon(n=12)) and len(signals)==1
    finally:dispose(editor)


def test_fresh_domain_defaults_and_default_no_confirmation(qapp,tmp_path,monkeypatch):
    case=priced_case(tmp_path);editor=GranularFilterEditor();editor.set_context(case.frozen.filter_context())
    from tests.analysis_test.test_granular_evidence import quantity
    editor.set_value(spec(quantity()));row=editor.groups['outcome'][0].rows[0];calls=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a: calls.append(a) or QMessageBox.StandardButton.No)
    try:
        row.domain.setCurrentIndex(row.domain.findData('horizon'));assert row.domain.currentData()=='movement'
        assert calls[0][-1]==QMessageBox.StandardButton.No
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
        row.domain.setCurrentIndex(row.domain.findData('horizon'))
        value=row.value();assert (value.field,value.unit,value.horizon_bars)==('terminal_directional','pct',6)
        assert value.minimum is None and value.basis is None and value.column is None
        assert row.horizon_reference.objectName().endswith('.horizon_reference')
    finally:dispose(editor)


@pytest.mark.parametrize('keyboard',(False,True),ids=('mouse','keyboard'))
@pytest.mark.parametrize('invalid',('horizon_bars','minimum'))
def test_composed_current_history_restores_once(horizon_gui,monkeypatch,keyboard,invalid):
    p=horizon_gui;page=pin_gui(p);definition=spec(horizon(n=12,minimum=-1000));activate(page,definition)
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;frame=page.results.model.frame.copy(deep=True)
    getattr(page.granular_editor.groups['outcome'][0].rows[0],invalid).setText('invalid')
    assert not page.actions['evaluate'].isEnabled()
    saved=p.service.refinement_snapshot(p.presenter.session);calls=_r2_spies(p,page,monkeypatch)
    _r2_history_popup(p,page,saved['active_checkpoint_id'],keyboard=keyboard)
    _r2_same_saved(p,page,saved,result,frame)
    assert page.granular_editor.value()==definition and page.actions['evaluate'].isEnabled()
    assert calls.selection.call_count==1 and calls.worker.call_count==0


def test_composed_evaluate_evidence_compare_search_and_repin(horizon_gui,monkeypatch):
    p=horizon_gui;page=pin_gui(p)
    definition=spec(horizon(n=6,minimum=-1000),horizon('favorable_excursion',12,minimum=0))
    activate(page,definition);page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;report=result.population_report()
    selected=next(i for i,r in enumerate(report['records']) if r.get('horizon_windows'))
    page.views.setCurrentIndex(4);page.population.table.selectRow(selected)
    assert 'fixed_horizon_price' in page.population_json.toPlainText()
    page.actions['compare_parent'].click();assert len(page.comparison.model.frame)==len(p.case.frozen.patterns)
    previous=page._snapshot['set_id'];page.actions['search_new'].click();until(lambda:not p.presenter._busy)
    candidate=p.presenter._study_result;assert candidate.granular_definition==definition,p.view.log.toPlainText()
    assert candidate._data['_gr04_prices'] is p.study._data['_gr04_prices']
    ids=tuple(candidate.frame('patterns').pattern_id[:2]);assert ids
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:False)
    p.presenter.pin_patterns(ids);assert page._snapshot['set_id']==previous
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:True)
    p.presenter.pin_patterns(ids);until(lambda:not p.presenter._busy)
    assert page._snapshot['set_id']!=previous and page.granular_editor.value()==definition
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._result.population_report()['horizon_source']==report['horizon_source']


def test_missing_capability_and_inactive_row_preserve_completed_result(horizon_gui):
    p=horizon_gui;page=pin_gui(p);activate(page,spec(horizon(minimum=-1000)))
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy);result=page._result
    context=deepcopy(page._snapshot['filter_context']);context['horizon_source']['roles']['high']=dict(status='unavailable',reason='canonical_price_column_missing')
    page.granular_editor.set_context(context);activate(page,spec(horizon('adverse_excursion')))
    assert not page.actions['evaluate'].isEnabled() and page._result is result
    row=page.granular_editor.groups['outcome'][0].rows[0]
    assert not row.field.model().item(row.field.findData('adverse_excursion')).isEnabled()
    activate(page,D(outcome=(G(conditions=(horizon('adverse_excursion',enabled=False),horizon(minimum=-1000))),)))
    assert page.granular_editor.value().active_count==1


@pytest.mark.parametrize('size',((1280,820),(1000,700)))
def test_horizon_geometry_and_stable_ids(horizon_gui,size):
    p=horizon_gui;page=pin_gui(p);tab=p.view.pattern_tab
    p.view.resize(*size);p.view.show();p.view.analysis_tabs.setCurrentWidget(tab);tab.results.views.setCurrentWidget(page)
    activate(page,spec(horizon(n=6,minimum=-1000),horizon('favorable_excursion',12,minimum=0)))
    p.view.workspace_splitter.setSizes([320,size[0]-580,240])
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);QCoreApplication.processEvents()
    for row in page.granular_editor.groups['outcome'][0].rows:
        tab.scroll.ensureWidgetVisible(row.horizon_bars);QCoreApplication.processEvents()
        assert row.horizon_bars.isVisibleTo(page) and row.horizon_bars.objectName().endswith('.horizon_bars')
    assert tab.scroll.horizontalScrollBar().maximum()==0
    assert '2 / 8 active horizons' in page.granular_editor.status.text()


def test_mixed_horizon_keeps_literal_and_absent_profile_types(qapp,tmp_path):
    case=priced_case(tmp_path);context=case.frozen.filter_context()
    context['columns']['literal']=dict(profile_id='None',measurement='directional_intensity',labels=('P01',))
    context['columns']['absent']=dict(profile_id=None,measurement='value',labels=())
    rows=(P('column','raw_value','native',column='literal',profile_id='None',offset=-1,minimum=0),
          P('column','raw_value','native',column='absent',profile_id=None,offset=-1,minimum=0),horizon())
    definition=spec(*rows);editor=GranularFilterEditor();editor.set_context(context);signals=[];editor.changed.connect(lambda:signals.append(1))
    try:
        editor.set_value(definition);editor.set_context(context)
        assert editor.value()==definition and not signals
        a,b,c=editor.groups['outcome'][0].rows
        assert a.value().profile_id=='None' and b.value().profile_id is None
        c.horizon_bars.setText(' 000006 ');assert editor.value()==definition and len(signals)==1
        editor.set_context(context);assert c.horizon_bars.text()==' 000006 ' and len(signals)==1
    finally:dispose(editor)
