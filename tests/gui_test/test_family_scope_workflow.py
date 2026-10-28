"""Actual scope widgets and production-composed retained-family workflows."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from leonardo.analysis.pattern_models import FamilyScope, PatternRefinement
from leonardo.analysis.refinement_models import GranularRefinement as D, GranularGroup as G
from leonardo.gui.analysis.family_scope_controls import FamilyScopeControls
from leonardo.gui.analysis.trend_start_patterns_tab import TrendStartPatternsTab
from tests.analysis_test.test_family_scope_application import revision_case
from tests.analysis_test.test_family_scope_refinement import multi_case, A, B, C
from tests.analysis_test.test_refinement_outcomes import horizon
from tests.gui_test.test_trend_start_patterns_tab import qapp, seed_tab, select_event
from tests.gui_test.test_refinement_filter_editor import installed_theme_font, activate
from tests.gui_test.test_pattern_refinement_workflow import pin_gui, _r2_history_popup, _r2_spies, _r2_same_saved
from tests.gui_test.test_analysis_execution_presenter import until
from tests.gui_test.test_pre_event_pattern_controls import dispose


def context():
    return dict(families=[A,B,C],direction='UP',comparison='recurrence',source_selection=None)


def test_scope_signals_keyboard_hidden_selection_and_saved_foreign(qapp):
    widget=FamilyScopeControls(identity_prefix='test.scope');signals=[];widget.changed.connect(lambda:signals.append(1))
    try:
        data=context();widget.set_context(data);widget.set_value(FamilyScope('selected',[A,B]));data['families'].clear()
        assert widget.value().families==(A,B) and not signals
        widget.show();widget.members.setCurrentRow(0);widget.members.setFocus();QTest.keyClick(widget.members,Qt.Key.Key_Space)
        assert widget.value().families==(B,) and len(signals)==1
        widget.search.setText('no visible rows');assert len(signals)==1
        widget.select_all.click();assert widget.value().families==(A,B,C) and len(signals)==2
        widget.deselect_all.click();assert len(signals)==3
        with pytest.raises(ValueError):widget.value()
        widget.set_value(FamilyScope('selected',[A,B]));small=context();small['families']=[A,C];widget.set_context(small)
        assert B in widget._gr05_checked() and any('unavailable' in widget.members.item(i).text() for i in range(widget.members.count()))
        with pytest.raises(ValueError):widget.value()
        assert len(signals)==3
        widget.set_context({});widget.set_value(None);assert widget.value() is None
    finally:dispose(widget)


def test_initial_exact_is_the_existing_selector_and_questions_are_fixed(qapp):
    widget=FamilyScopeControls(identity_prefix='test.initial',initial=True)
    try:
        widget.set_context(context())
        with pytest.raises(ValueError,match='existing family selector'):widget.set_value(FamilyScope('exact',[A]))
        widget.set_value(FamilyScope('all'));assert widget.value()==FamilyScope('all')
        data=context();data['comparison']='other_families';widget.set_context(data)
        with pytest.raises(ValueError):widget.value()
        assert widget.mode.currentData()=='all' and 'Invalid' in widget.status.text()
        widget.set_value(FamilyScope('selected',[A,B,C]))
        with pytest.raises(ValueError):widget.value()
        widget.set_value(FamilyScope('selected',[A]));assert widget.value().families==(A,)
    finally:dispose(widget)


@pytest.mark.parametrize('mirror',(False,True))
def test_initial_pool_overview_context_reset_and_origin_zero(qapp,tmp_path,mirror):
    parent,cat,_,request,_,families=multi_case(tmp_path,mirror=mirror)
    tab=TrendStartPatternsTab()
    try:
        seed_tab(tab,parent,cat);select_event(tab,request.event_kind,families[0]);tab.mode.setCurrentIndex(tab.mode.findData('pre_event'))
        assert tab.request().family==families[0] and tab.request().refinement.family_scope is None
        tab.family.setCurrentIndex(tab.family.findData(None));assert tab.request().family is None
        assert 'separate overview' in tab.context.text()
        selected=FamilyScope('selected',families[:2]);tab.family_scope.set_value(selected);tab._sync()
        assert tab.request().family is None and tab.request().refinement.family_scope==selected
        assert not tab.family.isEnabled() and 'separate overview' not in tab.context.text()
        tab._choices_changed(reset=False);assert tab.family_scope.value()==selected
        tab.origin.setCurrentIndex(tab.origin.findData('candidate_restart'));assert tuple(tab.family_scope._context['families'])==families
        tab.event.setCurrentIndex(tab.event.findData('T' if mirror else 'P'));assert tab.family_scope.mode.currentData() is None
        assert not tab.family_scope._gr05_checked()
        tab.clear_source();assert tab.family_scope.value() is None
    finally:dispose(tab)


@pytest.fixture(params=('UP','DOWN'))
def family_gui(request,qapp,tmp_path,installed_theme_font):
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import load_default_config, AuditConfig
    from leonardo.gui.composition import GuiCompositionRoot
    case=revision_case(tmp_path/'prices',direction=request.param)
    app=LeonardoApp(replace(load_default_config(tmp_path/'runtime'),audit=AuditConfig(enabled=False)))
    app.startup();app.start_core_runtime();composition=GuiCompositionRoot(app.context);main=composition.create_main_window();main.show()
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        view=composition.analysis_suite_window;presenter=composition.analysis_suite_presenter;until(lambda:not presenter._busy)
        seed_tab(view.pattern_tab,case.parent,case.catalogue);presenter._binning_result=case.parent;presenter._study_result=case.study
        view.pattern_tab.results.set_result(case.study)
        yield SimpleNamespace(view=view,presenter=presenter,service=app.analysis_service,parent=case.parent,
            catalogue=case.catalogue,study=case.study,case=case,app=app)
    finally:
        main.close();app.shutdown();main.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def pooled_definition(p):
    return D(outcome=(G(conditions=(horizon(n=6,minimum=-1000),)),),family_scope=FamilyScope('selected',p.case.families[:2]))


@pytest.mark.parametrize('keyboard',(False,True),ids=('mouse','keyboard'))
def test_current_history_restores_scope_and_numeric_draft_once(family_gui,monkeypatch,keyboard):
    p=family_gui;page=_gr05_pin_gui(p);definition=pooled_definition(p);activate(page,definition)
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;frame=page.results.model.frame.copy(deep=True)
    page.granular_editor.family_scope.deselect_all.click()
    page.granular_editor.groups['outcome'][0].rows[0].horizon_bars.setText('invalid')
    assert not page.actions['evaluate'].isEnabled() and page._result is result
    saved=p.service.refinement_snapshot(p.presenter.session);calls=_r2_spies(p,page,monkeypatch)
    _r2_history_popup(p,page,saved['active_checkpoint_id'],keyboard=keyboard)
    _r2_same_saved(p,page,saved,result,frame)
    assert page.granular_editor.value()==definition and calls.selection.call_count==1 and calls.worker.call_count==0
    p.view.resize(1000,700);p.view.workspace_splitter.setSizes([320,420,240]);QCoreApplication.processEvents()
    p.view.pattern_tab.scroll.ensureWidgetVisible(page.granular_editor.family_scope.members);QCoreApplication.processEvents()
    assert p.view.pattern_tab.scroll.horizontalScrollBar().maximum()==0


def test_composed_pool_occurrences_compare_search_and_repin(family_gui,monkeypatch):
    p=family_gui;page=_gr05_pin_gui(p);original_ids=page._snapshot['pinned_ids'];definition=pooled_definition(p);activate(page,definition)
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1,p.view.log.toPlainText()
    result=page._result;assert page._snapshot['pinned_ids']==original_ids
    assert len(page.family_population.model.frame)==len(p.case.families)
    page.results.table.selectRow(0);page.target_matches.click();until(lambda:not p.presenter._busy)
    assert not page.family_breakdown.model.frame.empty and 'same retained rule masks' in page.family_breakdown_status.text()
    page.results.table.selectRow(1);assert page.family_breakdown.model.frame.empty
    page.actions['compare_parent'].click();assert len(page.comparison.model.frame)==len(original_ids)
    previous=page._snapshot['set_id'];page.actions['search_new'].click();until(lambda:not p.presenter._busy)
    candidate=p.presenter._study_result;assert candidate.granular_definition==definition,p.view.log.toPlainText()
    assert candidate._data['_gr04_prices'] is p.study._data['_gr04_prices']
    ids=tuple(candidate.frame('patterns').pattern_id[:2]);assert ids
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:False);p.presenter.pin_patterns(ids)
    assert page._snapshot['set_id']==previous and page._result is result
    monkeypatch.setattr(p.presenter,'_confirm_refinement',lambda message:True);_gr05_pin_gui(p, pattern_ids=ids)
    assert page._snapshot['set_id']!=previous and page.granular_editor.value()==definition
    page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._result.population_report()['horizon_source']==result.population_report()['horizon_source']


def test_simple_conversion_and_separate_drafts(family_gui,monkeypatch):
    p=family_gui;page=_gr05_pin_gui(p);simple=replace(p.study.request.refinement,family_scope=FamilyScope('selected',p.case.families[:2]))
    page.editor.set_value(simple);page._draft_changed();page.actions['evaluate'].click();until(lambda:not p.presenter._busy)
    assert page._snapshot['evaluation_count']==1
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    page.convert_granular.click();assert page.granular_editor.value().family_scope==simple.family_scope
    page.granular_editor.family_scope.set_value(FamilyScope('all'));page._draft_changed()
    page.mode.setCurrentIndex(page.mode.findData('simple'));assert page.editor.value()==simple
    page.mode.setCurrentIndex(page.mode.findData('granular'));assert page.granular_editor.value().family_scope==FamilyScope('all')
    page.granular_editor.family_scope.deselect_all.click()
    page.granular_editor.family_scope.mode.setCurrentIndex(page.granular_editor.family_scope.mode.findData('selected'))
    assert not page.actions['evaluate'].isEnabled() and page._snapshot['evaluation_count']==1


# Task 1082 R2: the complete visible pre-event form must fit after history restore.
@pytest.mark.parametrize('keyboard', (False, True), ids=('mouse', 'keyboard'))
def test_r2_compact_full_pre_event_form_after_history_restore(family_gui, monkeypatch, keyboard):
    from PySide6.QtCore import QPoint, QRect
    p = family_gui
    tab = p.view.pattern_tab
    p.view.resize(1280, 820)
    p.view.show()
    p.view.analysis_tabs.setCurrentWidget(tab)
    p.view.workspace_splitter.setSizes([180, 920, 180])
    select_event(tab, p.study.request.event_kind, None)
    tab.mode.setCurrentIndex(tab.mode.findData('pre_event'))
    tab.family_scope.set_value(FamilyScope('selected', p.case.families[:2]))
    tab._sync()
    assert tab.request().refinement.family_scope == FamilyScope('selected', p.case.families[:2])
    assert tab.pre_event_controls.isVisibleTo(tab.scroll.widget())
    # Reattach the genuine completed study after deliberately configuring the independent discovery form.
    p.presenter._study_result = p.study
    tab.results.set_result(p.study)
    p.presenter.pin_patterns(tuple(p.study.frame('patterns').pattern_id[:4]))
    until(lambda: not p.presenter._busy, timeout=60000)
    page = tab.post_refinement
    assert page._snapshot is not None, p.view.log.toPlainText()
    tab.results.views.setCurrentWidget(page)
    definition = pooled_definition(p)
    activate(page, definition)
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy, timeout=60000)
    assert page._result.granular_definition == definition, p.view.log.toPlainText()
    page.results.table.selectRow(0)
    page.target_matches.click()
    until(lambda: not p.presenter._busy, timeout=60000)
    assert not page.family_breakdown.model.frame.empty
    page.views.setCurrentIndex(0)
    result = page._result
    frame = page.results.model.frame.copy(deep=True)
    page.granular_editor.family_scope.deselect_all.click()
    assert not page.actions['evaluate'].isEnabled() and page._result is result
    saved = p.service.refinement_snapshot(p.presenter.session)
    calls = _r2_spies(p, page, monkeypatch)
    _r2_history_popup(p, page, saved['active_checkpoint_id'], keyboard=keyboard)
    _r2_same_saved(p, page, saved, result, frame)
    assert page.granular_editor.value() == definition and page.actions['evaluate'].isEnabled()
    assert calls.selection.call_count == 1 and calls.worker.call_count == 0
    for width, height, sizes in ((1000, 700, [140, 720, 140]),
                                  (1280, 820, [180, 920, 180]),
                                  (1000, 700, [140, 720, 140])):
        p.view.resize(width, height)
        p.view.workspace_splitter.setSizes(sizes)
        QCoreApplication.processEvents()
        assert (p.view.width(), p.view.height()) == (width, height)
        assert tab.mode.currentData() == 'pre_event'
        assert tab.pre_event_controls.isVisibleTo(tab.scroll.widget())
        assert tab.scroll.horizontalScrollBar().maximum() == 0
        controls = (tab.after_label, tab.pre_event_controls.custom_split, tab.family_scope.mode,
                    page.history, page.granular_editor.family_scope.mode,
                    page.granular_editor.family_scope.members,
                    page.granular_editor.groups['outcome'][0].rows[0].horizon_bars,
                    page.actions['evaluate'])
        for control in controls:
            assert control.isVisibleTo(tab.scroll.widget())
            tab.scroll.ensureWidgetVisible(control)
            QCoreApplication.processEvents()
            rectangle = QRect(control.mapTo(tab.scroll.viewport(), QPoint(0, 0)), control.size())
            assert tab.scroll.viewport().rect().contains(rectangle), (control.objectName(), rectangle)
            assert tab.scroll.horizontalScrollBar().maximum() == 0
    assert calls.selection.call_count == 1 and calls.worker.call_count == 0
    assert page._result is result and page.granular_editor.value() == definition
    assert p.service.refinement_snapshot(p.presenter.session)['evaluation_count'] == saved['evaluation_count']


# Task 1082 R3: initial legacy delegation and a bounded GR-05 fixture Pin wait.
def _gr05_pin_gui(p, *, pattern_ids=None):
    from time import monotonic
    ids = tuple(p.study.frame('patterns').pattern_id[:4]) if pattern_ids is None else tuple(pattern_ids)
    started = monotonic()
    p.presenter.pin_patterns(ids)
    until(lambda: not p.presenter._busy, timeout=60000)
    snapshot = p.service.refinement_snapshot(p.presenter.session)
    assert snapshot['workspace_present'], p.view.log.toPlainText()
    print('GR05_PIN_WAIT ' + json.dumps(dict(elapsed_seconds=monotonic()-started,
        wait_limit_ms=60000, requested_rules=len(ids), workspace_present=True,
        phase='initial' if pattern_ids is None else 'confirmed_repin')), flush=True)
    return p.view.pattern_tab.post_refinement


@pytest.mark.parametrize('mirror', (False, True), ids=('UP', 'DOWN'))
@pytest.mark.parametrize('selection', ('exact', 'overview'))
@pytest.mark.parametrize('interval', ('other_families_remain', 'empty'))
def test_r3_initial_legacy_date_narrowing(qapp, tmp_path, mirror, selection, interval):
    from collections import defaultdict
    from leonardo.analysis.trend_start_patterns import run_study
    from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture
    from tests.analysis_test.test_trend_start_enrichment import ENDED
    from tests.financial_tools_test.test_utc_classification import CASES
    parent, catalogue, axis, base, *_ = planted_fixture(
        tmp_path, sequences=CASES+(ENDED,)*4, mirror=mirror)
    events = [e for e in catalogue.instance(base.instance_id)['events']
              if e['event_kind'] == base.event_kind]
    grouped = defaultdict(list)
    for event in events:
        grouped[event['family']].append(event['anchor_ts_ms'])
    last = max(e['anchor_ts_ms'] for e in events)
    family = next(f for f, times in grouped.items() if max(times) < last)
    chosen = family if selection == 'exact' else None
    start = max(grouped[family])+1 if interval == 'other_families_remain' else axis[-1]
    remaining = [e for e in events if start <= e['anchor_ts_ms'] <= axis[-1]]
    assert bool(remaining) == (interval == 'other_families_remain')
    assert all(e['family'] != family for e in remaining)
    tab = TrendStartPatternsTab()
    try:
        seed_tab(tab, parent, catalogue)
        select_event(tab, base.event_kind, chosen)
        tab.mode.setCurrentIndex(tab.mode.findData('pre_event'))
        original_start = tab.start.dateTime()
        assert tab.request().family == chosen
        tab.start.setDateTime(original_start.addMSecs(start-original_start.toMSecsSinceEpoch()))
        qapp.processEvents()
        assert tab.family.currentData() == chosen
        assert tab.family_scope.mode.currentData() is None
        assert tab.family_scope.value() is None
        request = tab.request()
        assert request.family == chosen and request.start_ms == start
        assert request.refinement.family_scope is None and tab.run_button.isEnabled()
        assert 'Invalid family selection' not in tab.family_scope.status.text()
        study = run_study(parent, catalogue, request, axis)
        assert study.frame('patterns').empty
        if interval == 'empty':
            assert study.frame('events').empty and not study._data['samples']
        elif selection == 'exact':
            assert study.frame('events').empty and study._data['samples']
            assert all(s['cohort'] == 'comparison' for s in study._data['samples'])
        else:
            assert not study.frame('events').empty and study._data['samples']
            assert all(s['cohort'] == 'target' for s in study._data['samples'])
        tab.start.setDateTime(original_start)
        qapp.processEvents()
        assert tab.request().family == chosen
        assert tab.request().refinement.family_scope is None and tab.run_button.isEnabled()
    finally:
        dispose(tab)


@pytest.mark.parametrize('kind', ('empty_context', 'empty_universe', 'foreign_exact', 'partial_context'))
def test_r3_initial_none_does_not_invoke_scope_membership(qapp, monkeypatch, kind):
    import leonardo.gui.analysis.family_scope_controls as module
    data = dict(families=[A, B], direction='UP', comparison='other_families',
                source_selection=FamilyScope('exact', (C,)).to_dict())
    if kind == 'empty_context':
        data = {}
    elif kind == 'empty_universe':
        data['families'] = []
    elif kind == 'partial_context':
        data.pop('comparison')
    widget = FamilyScopeControls(identity_prefix='r3.initial', initial=True)
    signals = []
    widget.changed.connect(lambda: signals.append(True))
    try:
        widget.set_context(data)
        widget.set_value(None)
        def forbidden(*args, **kwargs):
            pytest.fail('inactive initial scope must delegate to the existing selector')
        monkeypatch.setattr(module, '_gr05_resolve_selection', forbidden)
        assert widget.value() is None
        widget.set_context(data)
        widget.set_value(None)
        assert widget.value() is None and not signals
    finally:
        dispose(widget)


@pytest.mark.parametrize('initial', (False, True), ids=('pinned', 'initial'))
@pytest.mark.parametrize('case', ('foreign', 'opposite', 'empty', 'missing_context', 'all_other'))
def test_r3_explicit_scope_validation_remains_strict(qapp, initial, case):
    widget = FamilyScopeControls(identity_prefix='r3.explicit', initial=initial)
    data = dict(families=[A, B], direction='UP', comparison='recurrence', source_selection=None)
    if case == 'all_other':
        data['comparison'] = 'other_families'
    try:
        widget.set_context({} if case == 'missing_context' else data)
        value = (FamilyScope('all') if case == 'all_other' else
                 FamilyScope('selected', (C if case == 'foreign' else
                     'DOWN/PTPT/3,1,2,0' if case == 'opposite' else A,)))
        widget.set_value(value)
        if case == 'empty':
            widget.deselect_all.click()
        with pytest.raises(ValueError):
            widget.value()
        assert widget.mode.currentData() == value.mode
        assert 'Invalid family selection' in widget.status.text()
    finally:
        dispose(widget)


@pytest.mark.parametrize('case', ('valid', 'foreign', 'all_other'))
def test_r3_pinned_none_keeps_inherited_explicit_validation(qapp, case):
    source = FamilyScope('all') if case == 'all_other' else FamilyScope('selected', (C if case == 'foreign' else A,))
    data = dict(families=[A, B], direction='UP', comparison='other_families' if case == 'all_other' else 'recurrence',
                source_selection=source.to_dict())
    widget = FamilyScopeControls(identity_prefix='r3.inherited', initial=False)
    try:
        widget.set_context(data)
        widget.set_value(None)
        if case == 'valid':
            assert widget.value() is None
        else:
            with pytest.raises(ValueError):
                widget.value()
        assert widget.mode.currentData() is None
    finally:
        dispose(widget)


@pytest.mark.parametrize('explicit', (False, True), ids=('initial', 'confirmed_repin'))
@pytest.mark.parametrize('completed', (False, True), ids=('wait_failure', 'completed'))
def test_r3_local_pin_helper_is_bounded_and_does_not_retry(monkeypatch, completed, explicit):
    import sys
    from unittest.mock import Mock
    module = sys.modules[__name__]
    page = object()
    presenter = SimpleNamespace(_busy=True, session='fixture-session', pin_patterns=Mock())
    snapshot = Mock(return_value={'workspace_present': True})
    p = SimpleNamespace(study=SimpleNamespace(frame=lambda name: SimpleNamespace(pattern_id=('a', 'b', 'c', 'd', 'e'))),
        presenter=presenter, service=SimpleNamespace(refinement_snapshot=snapshot),
        view=SimpleNamespace(log=SimpleNamespace(toPlainText=lambda: ''),
                             pattern_tab=SimpleNamespace(post_refinement=page)))
    waits = []
    def bounded(predicate, timeout):
        waits.append(timeout)
        assert not predicate()
        if not completed:
            raise AssertionError('deliberate bounded Pin wait failure')
        presenter._busy = False
        assert predicate()
    monkeypatch.setattr(module, 'until', bounded)
    if completed:
        assert _gr05_pin_gui(p, pattern_ids=('d', 'e') if explicit else None) is page
        snapshot.assert_called_once_with('fixture-session')
    else:
        with pytest.raises(AssertionError, match='deliberate bounded Pin wait failure'):
            _gr05_pin_gui(p, pattern_ids=('d', 'e') if explicit else None)
        snapshot.assert_not_called()
    presenter.pin_patterns.assert_called_once_with(('d', 'e') if explicit else ('a', 'b', 'c', 'd'))
    assert waits == [60000]


# Task 1082 R4: empty discoveries are displayable and never supply pin IDs.
import pandas as _r4_pd
from tests.gui_test.test_pattern_refinement_workflow import prepared_gui


def _r4_empty_studies(tmp_path, mirror, variant):
    from collections import defaultdict
    from decimal import Decimal
    from leonardo.analysis.pattern_models import NumericCondition
    from leonardo.analysis.refinement_models import GranularPredicate
    from leonardo.analysis.pattern_refinement import pin_patterns, search_granular_patterns
    from leonardo.analysis.trend_start_patterns import run_study
    from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture
    from tests.analysis_test.test_trend_start_enrichment import ENDED
    from tests.financial_tools_test.test_utc_classification import CASES
    parent, catalogue, axis, request, *_ = planted_fixture(
        tmp_path, sequences=CASES + (ENDED,) * 4, mirror=mirror)
    populated = run_study(parent, catalogue, request, axis)
    assert not populated.frame('patterns').empty
    events = [e for e in catalogue.instance(request.instance_id)['events']
              if e['event_kind'] == request.event_kind]
    if variant == 'dates':
        grouped = defaultdict(list)
        for event in events:
            grouped[event['family']].append(event['anchor_ts_ms'])
        last = max(event['anchor_ts_ms'] for event in events)
        family = next(f for f in sorted(grouped) if max(grouped[f]) < last)
        changed = replace(request, family=family, start_ms=max(grouped[family]) + 1,
                          refinement=PatternRefinement(), comparison='other_families')
        empty = run_study(parent, catalogue, changed, axis)
        assert empty.frame('events').empty and empty._data['samples']
        assert all(s['cohort'] == 'comparison' for s in empty._data['samples'])
    elif variant == 'pooled':
        families = tuple(sorted({event['family'] for event in events}))
        assert len(families) >= 3
        definition = PatternRefinement(basis='formation', movement_enabled=True,
            movement=(NumericCondition('directional_move', 'points', Decimal('1e100')),),
            family_scope=FamilyScope('selected', families[:2]))
        empty = run_study(parent, catalogue, replace(request, family=None,
                          refinement=definition, comparison='other_families'), axis)
        assert json.loads(empty.context)['family_scope']['selected_families'] == list(families[:2])
    elif variant == 'overview':
        empty = run_study(parent, catalogue, replace(request, family=None,
                          refinement=PatternRefinement()), axis)
        assert 'family_scope' not in json.loads(empty.context)
    else:
        assert variant == 'granular'
        frozen = pin_patterns(parent, catalogue, populated,
                              tuple(populated.frame('patterns').pattern_id[:3]))
        column = next(c for c in parent.columns if c.request.source == request.columns[0])
        predicate = GranularPredicate('column', 'raw_value', 'native',
            column=column.request.source, profile_id=column.profile.profile_id,
            offset=request.pre_event.offsets[-1], minimum=Decimal('1e100'))
        definition = D(outcome=(G(conditions=(predicate,)),))
        empty = search_granular_patterns(frozen, parent, catalogue, definition,
                                        parent_id=frozen.source_discovery_id)
        assert empty.granular_definition == definition
        assert 'pattern_id' in empty.frame('patterns').columns
    assert empty.frame('patterns').empty
    return populated, empty


@pytest.mark.parametrize('mirror', (False, True), ids=('UP', 'DOWN'))
@pytest.mark.parametrize('variant', ('dates', 'pooled', 'overview', 'granular'))
def test_r4_empty_discovery_display_filters_clear_and_recovery(qapp, tmp_path, mirror, variant):
    from leonardo.gui.analysis.trend_start_results import TrendStartResults
    populated, empty = _r4_empty_studies(tmp_path, mirror, variant)
    before = empty.frame('patterns')
    source_context = empty.context
    widget = TrendStartResults()
    pins = []
    matches = []
    widget.pin_requested.connect(pins.append)
    widget.matches_requested.connect(lambda *args: matches.append(args))
    try:
        widget.set_result(populated)
        widget.pattern_kind.setCurrentIndex(widget.pattern_kind.findData(None))
        ids = tuple(populated.frame('patterns').pattern_id)
        assert len(ids) >= 2
        assert widget._check_pin(ids[-1], True) and widget._check_pin(ids[0], True)
        assert widget.pin_selection() == (ids[0], ids[-1])
        widget.set_result(empty)
        assert widget._result is empty and widget.pin_selection() == ()
        assert not widget._pin_ids and widget.patterns.model.rowCount() == 0
        assert widget.pattern_note.text() and not widget.pin_selected.isEnabled()
        for ranked in (True, False):
            widget.ranked.setChecked(ranked)
            for index in range(widget.pattern_kind.count()):
                widget.pattern_kind.setCurrentIndex(index)
                assert widget.pin_selection() == ()
                assert not widget.pin_selected.isEnabled()
                assert not widget.target_matches.isEnabled() and not widget.comparison_matches.isEnabled()
        widget.set_busy(True)
        widget.set_busy(False)
        widget.clear_pin_selection()
        widget.refresh_display_time()
        widget.all_events.click()
        widget.pin_selected.click()
        widget.target_matches.click()
        widget.comparison_matches.click()
        assert not pins and not matches
        assert not widget.pattern_detail.toPlainText()
        assert widget.family_breakdown.model.frame.empty
        assert widget.diagnostics.model.rowCount() > 0
        _r4_pd.testing.assert_frame_equal(empty.frame('patterns'), before, check_exact=True)
        assert empty.context == source_context
        widget.clear()
        assert widget.pin_selection() == ()
        widget.set_result(populated)
        widget.ranked.setChecked(False)
        widget.pattern_kind.setCurrentIndex(widget.pattern_kind.findData(None))
        widget.patterns.table.selectRow(0)
        assert widget.pin_selection() == (ids[0],) and widget.pin_selected.isEnabled()
        widget.pin_selected.click()
        assert pins == [(ids[0],)]
    finally:
        dispose(widget)


@pytest.mark.parametrize('schema', ('columnless', 'typed'))
@pytest.mark.parametrize('stale_selection', (False, True))
def test_r4_zero_row_pin_selection_does_not_invent_a_schema(qapp, schema, stale_selection):
    from leonardo.gui.analysis.trend_start_results import TrendStartResults
    frame = _r4_pd.DataFrame() if schema == 'columnless' else _r4_pd.DataFrame(columns=('pattern_id', 'condition'))
    expected = frame.copy(deep=True)
    widget = TrendStartResults()
    try:
        widget._result = SimpleNamespace(request=SimpleNamespace(pre_event=object()), frame=lambda name: frame)
        if stale_selection:
            widget._pin_ids.add('old-unrelated-id')
        assert widget.pin_selection() == ()
        _r4_pd.testing.assert_frame_equal(frame, expected, check_exact=True)
    finally:
        dispose(widget)


@pytest.mark.parametrize('schema', ('other_column', 'index_only'))
def test_r4_nonempty_missing_id_is_not_silently_accepted(qapp, schema):
    from leonardo.gui.analysis.trend_start_results import TrendStartResults
    frame = _r4_pd.DataFrame({'condition': ['malformed supplied row']}) if schema == 'other_column' else _r4_pd.DataFrame(index=[0])
    widget = TrendStartResults()
    try:
        widget._result = SimpleNamespace(request=SimpleNamespace(pre_event=object()), frame=lambda name: frame)
        with pytest.raises(AttributeError, match='pattern_id'):
            widget.pin_selection()
    finally:
        dispose(widget)


def test_r4_empty_discovery_callback_keeps_existing_pinned_workspace(prepared_gui):
    from leonardo.analysis.trend_start_patterns import run_study
    from tests.analysis_test.test_trend_start_enrichment import movement
    p = prepared_gui
    page = pin_gui(p)
    before = p.service.refinement_snapshot(p.presenter.session)
    result = page._result
    request = replace(p.study.request, refinement=movement('formation', minimum=1e100))
    empty = run_study(p.parent, p.catalogue, request, tuple(p.study._data['timestamps']))
    assert empty.frame('patterns').empty
    p.presenter._patterns_completed(empty)
    assert p.view.pattern_tab.results._result is empty
    assert p.view.pattern_tab.results.pin_selection() == ()
    assert not p.view.pattern_tab.results.pin_selected.isEnabled()
    assert page._result is result
    assert p.service.refinement_snapshot(p.presenter.session) == before
    page.actions['evaluate'].click()
    until(lambda: not p.presenter._busy)
    assert page._snapshot['evaluation_count'] == before['evaluation_count'] + 1
    assert page._snapshot['pinned_ids'] == before['pinned_ids']
