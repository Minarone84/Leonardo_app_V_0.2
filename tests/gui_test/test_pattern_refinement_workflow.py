"""GR-02 Qt drafts, explicit pin selection and real composition workflow."""
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QWidget

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.pattern_models import PatternRefinement, NumericCondition, PrecedingContextFilter, PullbackFilter
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.trend_start_patterns import run_study
from leonardo.gui.analysis.pattern_refinement_controls import PatternRefinementControls
from leonardo.gui.analysis.trend_start_patterns_tab import TrendStartPatternsTab, RefinementControls
from leonardo.gui.analysis.trend_start_results import StudyTableModel
from leonardo.gui.analysis.presenter import AnalysisSuitePresenter
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow
from tests.analysis_test.test_pattern_refinement_application import InlineRunner, execute
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture, TOLERANT
from tests.analysis_test.test_trend_start_enrichment import movement
from tests.gui_test.test_trend_start_patterns_tab import qapp, seed_tab, select_event
from tests.gui_test.test_pre_event_pattern_controls import configured_tab, dispose
from tests.gui_test.test_analysis_execution_presenter import until, choose_database, select_columns


@pytest.fixture
def prepared_gui(qapp, tmp_path):
    parent, catalogue, axis, req, store, *_ = planted_fixture(tmp_path, planted=TOLERANT, radius=1)
    study = run_study(parent,catalogue,req,axis)
    service = AnalysisApplicationService(InlineRunner(), AnalysisService(store))
    view = AnalysisSuiteWindow()
    presenter = AnalysisSuitePresenter(view,service)
    seed_tab(view.pattern_tab,parent,catalogue)
    presenter._binning_result = parent
    presenter._study_result = study
    view.pattern_tab.results.set_result(study)
    yield SimpleNamespace(view=view,presenter=presenter,service=service,parent=parent,catalogue=catalogue,study=study)
    view.close(); dispose(view)


def pin_gui(p):
    ids=tuple(p.study.frame('patterns').pattern_id[:4])
    p.presenter.pin_patterns(ids)
    until(lambda:not p.presenter._busy)
    assert p.service.refinement_snapshot(p.presenter.session)['workspace_present'], p.view.log.toPlainText()
    return p.view.pattern_tab.post_refinement


@pytest.mark.parametrize('basis', ('completed','formation','observed'))
@pytest.mark.parametrize('enabled', (False,True))
def test_filter_roundtrip_exact_values_and_ids(qapp,basis,enabled):
    editor=RefinementControls(identity_prefix='post_refinement.filters')
    value=PatternRefinement(basis=basis,preceding=PrecedingContextFilter(enabled=enabled,up=False,down=True,range=False,
        previous_direction='DOWN',previous_family='DOWN/PTPT/3,1,2,0'),movement_enabled=enabled,
        movement=(NumericCondition('directional_move','pct',Decimal('1.23E-12'),Decimal('1E9')),
                  NumericCondition('signed_move','points',0,None)),duration_enabled=enabled,
        duration=(NumericCondition('structural','minutes',Decimal('1.25'),2),
                  NumericCondition('confirmation_delay','seconds',Decimal('.001'),None)),
        pullbacks=PullbackFilter(enabled=enabled,cohort='formation_recovered' if basis=='formation' else 'currently_pending',
            conditions=(NumericCondition('depth','pct',0,Decimal('20.125'),'mean'),)))
    signals=[];editor.changed.connect(lambda:signals.append(True))
    try:
        editor.set_value(value)
        assert editor.value()==value and len(signals)==1
        assert editor.previous_family.currentData()==value.preceding.previous_family
        assert editor.duration.rows[0].unit.currentData()=='ms'
        assert editor.duration.rows[1].minimum.text()=='1'
        editor.set_value(value)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        names=[w.objectName() for w in editor.findChildren(QWidget) if w.objectName().startswith('analysis_suite.patterns.post_refinement.')]
        assert len(names)==len(set(names))
        assert all('.post_refinement.filters.' in name for name in names)
    finally: dispose(editor)


def test_legacy_disabled_invalid_values_remain_ignored(qapp):
    editor=RefinementControls()
    try:
        editor.movement.rows[0].minimum.setText('NaN')
        assert editor.value()==PatternRefinement()
    finally: dispose(editor)


def synthetic_many(study, count=501):
    """Display-only >50/500 boundary fixture; never submitted to the backend."""
    row=study.frame('patterns').iloc[0].to_dict()
    rows=[dict(row,pattern_id=f'synthetic-{i:04}',condition=f'SYNTHETIC VIEW ROW {i}',
               kind='combination' if i%2==0 else 'single baseline',rank_eligible=i%3==0) for i in range(count)]
    return replace(study,_tables=tuple((key,pd.DataFrame(rows,dtype=object) if key=='patterns' else frame)
                                     for key,frame in study._tables))


def test_cross_page_hidden_selection_original_order_and_500_limit(prepared_gui):
    p=prepared_gui;result=p.view.pattern_tab.results
    study=synthetic_many(p.study)
    result.set_result(study)
    result.pattern_kind.setCurrentIndex(2)
    result.patterns.table.selectRow(0)
    assert result.pin_selection()==('synthetic-0000',)
    model=result.patterns.model
    for page,index in ((2,3),(0,2)):
        result.patterns.page.setValue(page+1)
        assert model.setData(model.index(index,0),Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    assert result.pin_selection()==('synthetic-0002','synthetic-0103')
    result.pattern_kind.setCurrentIndex(0)
    assert '1 hidden' in result.pin_count.text()
    result.ranked.setChecked(True)
    assert result.pin_selection()==('synthetic-0002','synthetic-0103')
    result.clear_pin_selection()
    for identity in study.frame('patterns').pattern_id[:500]: assert result._check_pin(identity,True)
    assert not result._check_pin('synthetic-0500',True)
    assert len(result.pin_selection())==500 and 'Maximum 500' in result.pin_count.text()
    result.set_result(p.study)
    assert not result._pin_ids


def test_pin_evaluate_compare_zero_reset_and_legacy_independence(prepared_gui):
    p=prepared_gui;page=pin_gui(p)
    tab=p.view.pattern_tab
    assert tab.results.views.count()==7 and tab.results.views.tabText(6)=='Pinned refinement'
    original=p.service.refinement_snapshot(p.presenter.session)
    page.editor.set_value(movement('formation',minimum=10000))
    assert 'Draft changed' in page.draft_status.text()
    page.actions['evaluate'].click()
    until(lambda:not p.presenter._busy)
    assert len(page.results.model.frame)==4 and page.results.model.frame.matched.eq(0).all()
    column=page.results.model.frame.columns.get_loc('difference_pp')
    assert page.results.model.data(page.results.model.index(0,column))=='—'
    page.actions['compare_parent'].click()
    assert len(page.comparison.model.frame)==4 and page.comparison.model.frame.delta_difference_pp.isna().all()
    page.actions['reset_discovery'].click()
    assert page.editor.value()==original['active_refinement']
    assert page.results.model.frame.matched.gt(0).any()
    tab.before.setValue(4)
    assert tab.results._result is None
    assert p.service.refinement_snapshot(p.presenter.session)['set_id']==original['set_id']
    assert page._result is p.study
    p.presenter._configuration_changed()
    assert not p.service.refinement_snapshot(p.presenter.session)['workspace_present']
    assert page._result is None


def test_replacement_requires_confirmation_and_failed_pin_reaches_log(prepared_gui,monkeypatch):
    p=prepared_gui;pin_gui(p)
    previous=p.service.refinement_snapshot(p.presenter.session)
    prompts=[]
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda text:prompts.append(text) or False)
    p.presenter.pin_patterns(tuple(p.study.frame('patterns').pattern_id[4:6]))
    assert len(prompts)==1 and 'Replace the current pinned workspace' in prompts[0]
    assert p.service.refinement_snapshot(p.presenter.session)['set_id']==previous['set_id']
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda text:True)
    p.presenter._study_result=replace(p.study,_data={k:v for k,v in p.study._data.items() if k!='_pin_source_binding'})
    p.presenter.pin_patterns(tuple(p.study.frame('patterns').pattern_id[4:6]))
    until(lambda:not p.presenter._busy)
    assert 'source_discovery_binding_missing' in p.view.log.toPlainText()
    assert p.service.refinement_snapshot(p.presenter.session)['set_id']==previous['set_id']


def test_real_qt_queued_draft_change_keeps_previous_checkpoint(prepared_gui):
    p=prepared_gui;page=pin_gui(p)
    previous=p.service.refinement_snapshot(p.presenter.session)
    page.actions['evaluate'].click()
    # Inline worker has finished, but the real Qt dispatcher has not delivered.
    assert p.presenter._busy and p.service.is_busy(p.presenter.session)
    assert page.editor.isEnabled()
    page.editor.movement.setChecked(True)
    page.editor.movement.rows[0].minimum.setText('999')
    assert 'cancelling prior evaluation' in page.draft_status.text()
    assert page._result is p.study and not page.actions['evaluate'].isEnabled()
    until(lambda:not p.presenter._busy)
    state=p.service.refinement_snapshot(p.presenter.session)
    assert state['evaluation_count']==0 and state['active_checkpoint_id']==previous['active_checkpoint_id']
    assert page.editor.movement.rows[0].minimum.text()=='999'


def test_occurrence_views_are_detached_real_counts_and_evidence(prepared_gui):
    p=prepared_gui;page=pin_gui(p)
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    page.results.table.selectRow(0)
    row=page.results.current_row()
    for cohort,button in (('target',page.target_matches),('comparison',page.comparison_matches)):
        button.click();until(lambda:not p.presenter._busy)
        actual=page._result.pattern_matches(row['pattern_id'],cohort)
        pd.testing.assert_frame_equal(page._occurrences,actual)
        for kind in ('matched','exact_match','added_by_tolerance','assessable','unavailable','all'):
            page.occurrence_kind.setCurrentIndex(page.occurrence_kind.findData(kind))
            if not page.occurrences.model.frame.empty:
                page.occurrences.table.selectRow(0)
                assert not page.event_window.model.frame.empty
                assert page.event_details.toPlainText()
    page._occurrences.iloc[0,0]='display-only'
    assert page._result.pattern_matches(row['pattern_id'],'comparison').iloc[0,0]!='display-only'


@pytest.mark.parametrize('first',('pattern_refinement_controls','trend_start_patterns_tab'))
def test_cold_import_both_orders_and_window(first,tmp_path):
    second='trend_start_patterns_tab' if first=='pattern_refinement_controls' else 'pattern_refinement_controls'
    script=f'''import importlib
importlib.import_module("leonardo.gui.analysis.{first}")
importlib.import_module("leonardo.gui.analysis.{second}")
from PySide6.QtWidgets import QApplication
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow
app=QApplication([])
w=AnalysisSuiteWindow()
assert w.pattern_tab.results.views.count()==7
w.close()
'''
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=tmp_path,env=os.environ.copy(),capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('kind,direction',(('T','UP'),('P','DOWN')))
def test_production_composition_two_columns_real_import_and_reopen(qapp,tmp_path,monkeypatch,kind,direction):
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import load_default_config,AuditConfig
    from leonardo.gui.composition import GuiCompositionRoot
    from tests.analysis_test.test_trend_start_application import bidirectional_database
    domain,_,historical,_,manifest=bidirectional_database(tmp_path/'imported')
    from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
    from leonardo.data_manager import ArtifactCollectionOutputV1
    materialized = _materialize(domain, domain._portable_recipes, _leaf('sma', {'period':3}))
    plan = domain.plan_database_content_edit(manifest.database_id, artifact_additions=(
        ArtifactCollectionOutputV1(materialized.root_logical_artifact_ids[0], 'sma_3', 'moving_average'),))
    assert not plan.blocked
    manifest = domain.execute_database_content_edit(plan)
    config=load_default_config(tmp_path/'runtime')
    config=replace(config,paths=replace(config.paths,data_manager_dir=domain._creation.store.root_dir,
        historical_data_dir=historical),audit=AuditConfig(enabled=False))
    app=LeonardoApp(config);app.startup();app.start_core_runtime()
    composition=GuiCompositionRoot(app.context);main=composition.create_main_window();main.show()
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        view=composition.analysis_suite_window;presenter=composition.analysis_suite_presenter
        until(lambda:not presenter._busy)
        choose_database(view,manifest.database_id);until(lambda:presenter._loaded is not None and not presenter._busy)
        select_columns(view.variation_tab,'close','moving_average')
        view.variation_tab.defaults.minimum_count.setValue(2)
        view.variation_tab.run_button.click();until(lambda:not presenter._busy)
        assert len(presenter._binning_result.columns)==2
        tab=view.pattern_tab;tab.load_button.click();until(lambda:not presenter._busy)
        select_event(tab,kind)
        tab.family.setCurrentIndex(2)
        tab.mode.setCurrentIndex(tab.mode.findData('pre_event'))
        tab.min_target.setValue(1);tab.min_comparison.setValue(1);tab.min_matches.setValue(1)
        tab.pre_event_controls.max_terms.setValue(2)
        tab.pre_event_controls.history.setValue(3)
        tab.run_button.click();until(lambda:not presenter._busy)
        study=presenter._study_result
        assert study is not None,view.log.toPlainText()
        rules=study.frame('patterns')
        selected=rules[rules.kind=='combination'].pattern_id.tolist()[:3]
        assert len(selected)>=2 and rules.matched.gt(0).any()
        assert study.request.trend_direction==direction
        presenter.pin_patterns(selected);until(lambda:not presenter._busy)
        page=tab.post_refinement
        assert len(page.results.model.frame)==len(selected)
        page.editor.set_value(movement('formation',100000))
        page.actions['evaluate'].click();until(lambda:not presenter._busy)
        assert page.results.model.frame.matched.eq(0).all()
        assert page.results.model.frame.difference_pp.isna().all()
        page.actions['reset_discovery'].click()
        page.results.table.selectRow(0);page.target_matches.click();until(lambda:not presenter._busy)
        assert not page.occurrences.model.frame.empty
        page.occurrences.table.selectRow(0)
        assert not page.event_window.model.frame.empty
        import leonardo.analysis.pre_event_patterns as miner_module
        import leonardo.analysis.service as service_module
        mine_calls, reads = [], []
        original_mine = miner_module.mine
        original_read = app.data_manager_creation_store.load_database_revision
        def mine(*args, **kwargs):
            mine_calls.append(True)
            return original_mine(*args, **kwargs)
        def read(database_id, revision_id=None):
            reads.append((database_id, revision_id))
            assert (database_id, revision_id) == (study.request.reference.database_id, study.request.reference.revision_id)
            return original_read(database_id, revision_id)
        monkeypatch.setattr(miner_module, 'mine', mine)
        monkeypatch.setattr(app.data_manager_creation_store, 'load_database_revision', read)
        monkeypatch.setattr(service_module, 'fit_directional_binning', lambda *a, **kw: pytest.fail('new search refitted bins'))
        before = app.analysis_service.refinement_snapshot(presenter.session)
        profiles = tuple(c.profile.to_dict() for c in presenter._binning_result.columns)
        tab.before.setValue(8)
        page.editor.set_value(movement('formation', 0))
        page.actions['search_new'].click(); until(lambda:not presenter._busy)
        candidate = presenter._study_result
        assert candidate is not None, view.log.toPlainText()
        assert candidate.request == replace(study.request, refinement=page.editor.value())
        assert len(mine_calls) == 1 and reads
        after = app.analysis_service.refinement_snapshot(presenter.session)
        assert (after['active_checkpoint_id'], after['evaluation_count']) == (before['active_checkpoint_id'], before['evaluation_count'])
        assert profiles == tuple(c.profile.to_dict() for c in presenter._binning_result.columns)
        assert 'New discovery from pinned checkpoint' in tab.results.context.text()
        old_session=presenter.session
        view.close();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        main.action_for_id('main_window.open_analysis_suite').trigger()
        new=composition.analysis_suite_presenter;until(lambda:not new._busy)
        assert new.session!=old_session
        assert not app.analysis_service.refinement_snapshot(new.session)['workspace_present']
    finally:
        main.close();app.shutdown();dispose(main)


def test_roundtrip_explicit_blank_conditions_and_inactive_basis_cohort(qapp):
    editor=RefinementControls(identity_prefix='post_refinement.filters')
    value=PatternRefinement(basis='formation',movement=(NumericCondition('signed_move','pct'),),
        duration=(NumericCondition('endpoint_extension','bars'),),
        pullbacks=PullbackFilter(cohort='currently_pending',conditions=(NumericCondition('depth','pct',statistic='maximum'),)))
    try:
        editor.set_value(value)
        assert editor.value()==value
        assert editor.movement.rows[0].minimum.text()==''
    finally:dispose(editor)


@pytest.mark.parametrize('action',('source','checkpoint','cancel','rule','dispose'))
def test_queued_matches_never_replace_newer_selection(prepared_gui,action):
    p=prepared_gui;page=pin_gui(p)
    page.results.table.selectRow(0)
    page.target_matches.click()
    assert p.presenter._busy
    if action=='source':p.presenter._configuration_changed()
    elif action=='checkpoint':p.presenter.select_refinement_checkpoint(page._snapshot['source_discovery_id'])
    elif action=='cancel':p.presenter.cancel()
    elif action=='rule':page.results.table.selectRow(1)
    else:p.presenter.dispose()
    QCoreApplication.processEvents()
    assert page._occurrences is None
    if action!='dispose':assert not p.presenter._busy


def test_stale_duplicate_presenter_callback_cannot_release_new_operation(prepared_gui,monkeypatch):
    p=prepared_gui;pin_gui(p)
    queued=[]
    monkeypatch.setattr(p.presenter._dispatcher,'dispatch',queued.append)
    page=p.view.pattern_tab.post_refinement
    page.actions['evaluate'].click()
    old=queued.pop()
    old()
    assert not p.presenter._busy
    page.actions['evaluate'].click()
    assert p.presenter._busy
    token=p.presenter._operation_token
    old()
    assert p.presenter._busy and p.presenter._operation_token is token
    queued.pop()()
    assert not p.presenter._busy and p.service.refinement_snapshot(p.presenter.session)['evaluation_count']==2


@pytest.mark.parametrize('outcome',('failure','cancel'))
def test_explicit_search_failure_preserves_legacy_and_pinned_results(prepared_gui,monkeypatch,outcome):
    p=prepared_gui;page=pin_gui(p)
    before=p.service.refinement_snapshot(p.presenter.session)
    def fail(*args,**kwargs):raise ValueError('deliberate new search failure')
    monkeypatch.setattr(p.service._service,'run_patterns',fail)
    page.actions['search_new'].click()
    assert not page.editor.isEnabled() and not page.history.isEnabled()
    if outcome=='cancel':p.presenter.cancel()
    until(lambda:not p.presenter._busy)
    assert p.view.pattern_tab.results._result is p.study and page._result is p.study
    after=p.service.refinement_snapshot(p.presenter.session)
    assert after['active_checkpoint_id']==before['active_checkpoint_id'] and after['evaluation_count']==0


def test_gui_discard_clear_confirmations_and_unique_live_ids(prepared_gui,monkeypatch):
    p=prepared_gui;page=pin_gui(p)
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    snapshot=p.service.refinement_snapshot(p.presenter.session)
    parent=snapshot['history'][1]['checkpoint_id']
    p.presenter.select_refinement_checkpoint(parent)
    assert not page.actions['discard'].isEnabled()
    p.presenter.select_refinement_checkpoint(snapshot['active_checkpoint_id'])
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda text:False)
    page.actions['discard'].click()
    assert p.service.refinement_snapshot(p.presenter.session)['evaluation_count']==2
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda text:True)
    page.actions['discard'].click()
    assert p.service.refinement_snapshot(p.presenter.session)['active_checkpoint_id']==parent
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    names=[w.objectName() for w in p.view.findChildren(QWidget) if w.objectName().startswith(
        ('analysis_suite.patterns.post_refinement.','analysis_suite.patterns.pin_'))]
    assert len(names)==len(set(names))
    page.actions['clear_workspace'].click()
    assert not p.service.refinement_snapshot(p.presenter.session)['workspace_present']
    assert p.view.pattern_tab.results._result is p.study


@pytest.mark.parametrize('size',((1280,820),(1024,768)))
def test_dark_page_layout_actions_are_reachable(prepared_gui,size):
    from PySide6.QtWidgets import QPushButton
    p=prepared_gui;page=pin_gui(p);tab=p.view.pattern_tab
    p.view.resize(*size);p.view.show()
    p.view.analysis_tabs.setCurrentWidget(tab)
    # The same nested page is inspected in the production scroll area.
    tab.results.views.setCurrentWidget(page)
    page.editor.movement.setChecked(True)
    page.editor.movement.rows[0].minimum.setText('0')
    second=page.editor.movement.add_row()
    second.field.setCurrentIndex(second.field.findData('signed_move'))
    second.minimum.setText('-1')
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
    assert p.view.width()==size[0]
    for button in page.findChildren(QPushButton):
        if button.isVisibleTo(page):
            assert button.parentWidget().rect().contains(button.geometry()),button.objectName()
    assert page.minimumSizeHint().width()<600, sorted((w.minimumSizeHint().width(), w.objectName(), type(w).__name__)
        for w in page.findChildren(QWidget))[-8:]


# Task 1077 R2: user activation restores saved history without new computation.
from unittest.mock import Mock
from PySide6.QtCore import QSignalBlocker
from PySide6.QtTest import QTest


def _r2_state(p):
    return p.service.refinement_snapshot(p.presenter.session)


def _r2_history_popup(p, page, checkpoint, *, keyboard=False):
    """Exercise the real popup, including same-index user acceptance."""
    p.view.resize(1280, 820)
    p.view.show()
    p.view.analysis_tabs.setCurrentWidget(p.view.pattern_tab)
    p.view.pattern_tab.results.views.setCurrentWidget(page)
    p.view.pattern_tab.scroll.ensureWidgetVisible(page.history)
    QCoreApplication.processEvents()
    index = page.history.findData(checkpoint)
    assert index >= 0 and page.history.isEnabled()
    page.history.showPopup()
    QCoreApplication.processEvents()
    popup = page.history.view()
    model_index = page.history.model().index(index, 0)
    popup.scrollTo(model_index)
    QCoreApplication.processEvents()
    rect = popup.visualRect(model_index)
    assert popup.isVisible() and rect.isValid()
    visible_rect = rect.intersected(popup.viewport().rect())
    assert visible_rect.isValid() and visible_rect.height() == rect.height()
    assert popup.viewport().rect().contains(visible_rect)
    if keyboard:
        assert page.history.currentIndex() == index
        assert popup.currentIndex() == model_index
        QTest.keyClick(popup, Qt.Key.Key_Return)
    else:
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, visible_rect.center())
    QCoreApplication.processEvents()
    assert not popup.isVisible()


def _r2_spies(p, page, monkeypatch):
    selection = Mock(wraps=p.service.select_refinement_checkpoint)
    monkeypatch.setattr(p.service, 'select_refinement_checkpoint', selection)
    submitted = {}
    terminals = []
    for name in ('submit_pin_patterns', 'submit_evaluate_pinned',
                 'submit_refinement_search', 'submit_refinement_matches'):
        original = getattr(p.service, name)
        def submit(*args, _original=original, **kwargs):
            callback = kwargs['result_callback']
            def received(value):
                terminals.append(value)
                callback(value)
            kwargs['result_callback'] = received
            return _original(*args, **kwargs)
        submitted[name] = Mock(side_effect=submit)
        monkeypatch.setattr(p.service, name, submitted[name])
    worker = Mock(wraps=p.service._runner.submit_blocking_job)
    monkeypatch.setattr(p.service._runner, 'submit_blocking_job', worker)
    requested, activated, changed = [], [], []
    page.checkpoint_requested.connect(requested.append)
    page.history.activated.connect(activated.append)
    page.history.currentIndexChanged.connect(changed.append)
    return SimpleNamespace(selection=selection, submitted=submitted, worker=worker,
        terminals=terminals, requested=requested, activated=activated, changed=changed)


def _r2_same_saved(p, page, before, result, frame, *, idle=True):
    after = _r2_state(p)
    for key in ('root_id', 'set_id', 'source_discovery_id', 'active_checkpoint_id',
                'evaluation_count', 'retained_match_bytes', 'pinned_ids', 'history'):
        assert after[key] == before[key], key
    assert page.draft() == before['active_refinement'] == after['active_refinement']
    assert page._result is result
    pd.testing.assert_frame_equal(page.results.model.frame, frame)
    assert page.history.count() == len(before['history'])
    assert page.draft_status.text().startswith('Showing saved settings and completed counts.')
    if idle:
        assert after['generation'] == before['generation'] + 1
    return after


@pytest.mark.parametrize('checkpoint_kind', ('source', 'evaluation'))
@pytest.mark.parametrize('dirty', ('9999', 'not-a-number'), ids=('valid', 'invalid'))
def test_r2_history_current_popup_restores_full_saved_state(prepared_gui, monkeypatch, checkpoint_kind, dirty):
    p = prepared_gui
    page = pin_gui(p)
    if checkpoint_kind == 'evaluation':
        # Multiple saved groups check restoration of the full value, not just the edited minimum.
        saved = movement('formation', 0, duration_enabled=True,
            duration=(NumericCondition('structural', 'bars', 0, 9999),),
            pullbacks=PullbackFilter(enabled=False, cohort='formation_recovered',
                conditions=(NumericCondition('depth', 'pct', 0, 99, 'maximum'),)))
        page.editor.set_value(saved)
        page.actions['evaluate'].click()
        until(lambda: not p.presenter._busy)
        assert _r2_state(p)['evaluation_count'] == 1, p.view.log.toPlainText()
    spies = _r2_spies(p, page, monkeypatch)
    result, frame = page._result, page.results.model.frame.copy(deep=True)
    page.editor.movement.setChecked(True)
    page.editor.movement.rows[0].minimum.setText(dirty)
    assert ('Invalid draft' if dirty == 'not-a-number' else 'Draft changed') in page.draft_status.text()
    before = _r2_state(p)
    index = page.history.currentIndex()
    _r2_history_popup(p, page, before['active_checkpoint_id'])
    _r2_same_saved(p, page, before, result, frame)
    spies.selection.assert_called_once_with(p.presenter.session, before['set_id'], before['active_checkpoint_id'])
    assert spies.requested == [before['active_checkpoint_id']] and spies.activated == [index]
    assert not spies.changed and not spies.worker.called
    assert not any(s.called for s in spies.submitted.values())


def test_r2_history_different_popup_switches_exactly_once(prepared_gui, monkeypatch):
    p = prepared_gui
    page = pin_gui(p)
    source = _r2_state(p)
    source_result = page._result
    page.editor.set_value(movement('formation', 0))
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy)
    evaluation = _r2_state(p)
    evaluation_result = page._result
    spies = _r2_spies(p, page, monkeypatch)
    for number, saved, result in ((1, source, source_result), (2, evaluation, evaluation_result)):
        page.editor.movement.setChecked(True)
        page.editor.movement.rows[0].minimum.setText('9999')
        before = _r2_state(p)
        index = page.history.findData(saved['active_checkpoint_id'])
        _r2_history_popup(p, page, saved['active_checkpoint_id'])
        after = _r2_state(p)
        assert spies.selection.call_count == number and len(spies.requested) == number
        spies.selection.assert_called_with(p.presenter.session, saved['set_id'], saved['active_checkpoint_id'])
        assert spies.activated[-1] == index and spies.changed[-1] == index
        assert after['generation'] == before['generation'] + 1
        assert after['active_checkpoint_id'] == saved['active_checkpoint_id']
        assert page.draft() == saved['active_refinement'] and page._result is result
        assert after['evaluation_count'] == evaluation['evaluation_count']
        assert after['retained_match_bytes'] == evaluation['retained_match_bytes']
    assert len(spies.changed) == len(spies.activated) == 2
    assert not spies.worker.called and not any(s.called for s in spies.submitted.values())


def test_r2_history_repeated_same_popup_restores_once_each(prepared_gui, monkeypatch):
    p = prepared_gui
    page = pin_gui(p)
    page.editor.set_value(movement('formation', 0))
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy)
    spies = _r2_spies(p, page, monkeypatch)
    result, frame = page._result, page.results.model.frame.copy(deep=True)
    for number in range(1, 4):
        page.editor.movement.rows[0].minimum.setText(str(9000 + number))
        before = _r2_state(p)
        _r2_history_popup(p, page, before['active_checkpoint_id'])
        _r2_same_saved(p, page, before, result, frame)
        assert spies.selection.call_count == number
        assert spies.requested == [before['active_checkpoint_id']] * number
        assert spies.activated == [page.history.currentIndex()] * number
    assert not spies.changed and not spies.worker.called
    assert not any(s.called for s in spies.submitted.values())


def test_r2_history_keyboard_current_popup_acceptance(prepared_gui, monkeypatch):
    p = prepared_gui
    page = pin_gui(p)
    page.editor.set_value(movement('formation', 0))
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy)
    spies = _r2_spies(p, page, monkeypatch)
    result, frame = page._result, page.results.model.frame.copy(deep=True)
    page.editor.movement.rows[0].minimum.setText('not-a-number')
    before = _r2_state(p)
    _r2_history_popup(p, page, before['active_checkpoint_id'], keyboard=True)
    _r2_same_saved(p, page, before, result, frame)
    spies.selection.assert_called_once_with(p.presenter.session, before['set_id'], before['active_checkpoint_id'])
    assert spies.requested == [before['active_checkpoint_id']]
    assert spies.activated == [page.history.currentIndex()] and not spies.changed
    assert not spies.worker.called and not any(s.called for s in spies.submitted.values())


def test_r2_history_programmatic_population_is_presentation_only(prepared_gui, monkeypatch):
    p = prepared_gui
    page = pin_gui(p)
    source, source_result = _r2_state(p), page._result
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy)
    saved, result = _r2_state(p), page._result
    spies = _r2_spies(p, page, monkeypatch)
    for _ in range(2):
        page.show_checkpoint(source, source_result)
        page.clear()
        page.show_checkpoint(saved, result)
        with QSignalBlocker(page.history):
            page.history.setCurrentIndex(0)
            page.history.setCurrentIndex(page.history.findData(saved['active_checkpoint_id']))
        QCoreApplication.processEvents()
    assert not spies.changed
    page.history.setCurrentIndex(0)
    QCoreApplication.processEvents()
    assert spies.changed == [0]  # A bare display index change is not a user restore request.
    page.show_checkpoint(saved, result)
    page.repaint()
    QCoreApplication.processEvents()
    assert _r2_state(p) == saved and page.draft() == saved['active_refinement']
    assert not spies.selection.called and not spies.requested and not spies.activated
    assert not spies.worker.called and not any(s.called for s in spies.submitted.values())


@pytest.mark.parametrize('operation', ('evaluate', 'matches'))
def test_r2_history_current_popup_cancels_queued_publication_and_allows_retry(prepared_gui, monkeypatch, operation):
    p = prepared_gui
    page = pin_gui(p)
    page.editor.set_value(movement('formation', 0))
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy)
    saved = _r2_state(p)
    result, frame = page._result, page.results.model.frame.copy(deep=True)
    held = []
    # Hold terminal delivery before popup setup, which itself processes Qt events.
    monkeypatch.setattr(p.presenter._dispatcher, 'dispatch', held.append)
    spies = _r2_spies(p, page, monkeypatch)
    if operation == 'evaluate':
        page.editor.movement.rows[0].minimum.setText('9999')
        page.actions['evaluate'].click()
    else:
        page.results.table.selectRow(0)
        page.target_matches.click()
    assert held and p.presenter._busy and p.service.is_busy(p.presenter.session)
    pending = p.service._operations[p.presenter.session]
    assert pending.finished and pending.terminal.status == 'completed' and not pending.delivered
    assert page._result is result and _r2_state(p)['evaluation_count'] == saved['evaluation_count']
    pending_generation = _r2_state(p)['generation']
    _r2_history_popup(p, page, saved['active_checkpoint_id'])
    assert pending.cancelled.is_set()
    assert _r2_state(p)['generation'] > pending_generation
    spies.selection.assert_called_once_with(p.presenter.session, saved['set_id'], saved['active_checkpoint_id'])
    assert spies.requested == [saved['active_checkpoint_id']]
    assert spies.activated == [page.history.currentIndex()] and not spies.changed
    assert spies.worker.call_count == 1
    for callback in tuple(held):
        callback()
        callback()  # Duplicate obsolete terminal delivery must be harmless.
    held.clear()
    assert not p.presenter._busy and not p.service.is_busy(p.presenter.session)
    assert len(spies.terminals) == 1 and spies.terminals[0].status == 'cancelled'
    assert spies.terminals[0].value is None
    _r2_same_saved(p, page, saved, result, frame, idle=False)
    assert page._occurrences is None and page.occurrences.model.frame.empty
    assert page.event_window.model.frame.empty and not page.event_details.toPlainText()
    # Retry explicitly using the restored settings, without editing the draft again.
    assert page.actions['evaluate'].isEnabled()
    page.actions['evaluate'].click()
    assert held and p.presenter._busy
    for callback in tuple(held):
        callback()
        callback()
    assert not p.presenter._busy and not p.service.is_busy(p.presenter.session)
    after = _r2_state(p)
    assert after['evaluation_count'] == saved['evaluation_count'] + 1
    assert after['active_checkpoint_id'] != saved['active_checkpoint_id']
    assert page._result.parent_id == saved['active_checkpoint_id']
    assert page.draft() == saved['active_refinement']
    assert [t.status for t in spies.terminals] == ['cancelled', 'completed']
    assert spies.worker.call_count == 2 and spies.selection.call_count == 1
    assert spies.submitted['submit_evaluate_pinned'].call_count == (2 if operation == 'evaluate' else 1)
    assert spies.submitted['submit_refinement_matches'].call_count == (1 if operation == 'matches' else 0)
    assert not spies.submitted['submit_pin_patterns'].called and not spies.submitted['submit_refinement_search'].called
