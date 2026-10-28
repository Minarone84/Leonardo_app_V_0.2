"""Connected P/T studies, invalidation and native-window session lifetime."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from threading import Event, get_ident
from types import SimpleNamespace
import shutil

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication

from leonardo.analysis import AnalysisApplicationService
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.gui.analysis.presenter import AnalysisSuitePresenter
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow
from tests.analysis_test.test_trend_start_application import real_study
from tests.gui_test.test_analysis_execution_presenter import until, choose_database, select_columns, DelayedService
from tests.gui_test.test_trend_start_patterns_tab import select_event

_APP = None


@pytest.fixture(scope="module")
def qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def connected(qapp, tmp_path):
    domain, parent, catalogue, req, dms = real_study(tmp_path)
    runner = CoreRunner(TaskManager())
    runner.start()
    service = AnalysisApplicationService(runner, domain)
    window = AnalysisSuiteWindow()
    presenter = AnalysisSuitePresenter(window, service)
    window.show()
    presenter.start()
    until(lambda: not presenter._busy)
    choose_database(window, parent.entry.reference.database_id)
    until(lambda: not presenter._busy and presenter._loaded is not None)
    select_columns(window.variation_tab, "close")
    window.variation_tab.run_button.click()
    until(lambda: not presenter._busy)
    yield SimpleNamespace(domain=domain, service=service, runner=runner, window=window,
        presenter=presenter, dms=dms)
    window.close()
    service.cancel_all_pending()
    runner.shutdown()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def prepare(connected, kind="T"):
    tab = connected.window.pattern_tab
    tab.load_button.click()
    until(lambda: not connected.presenter._busy)
    select_event(tab, kind)
    assert tab.family.count() > 2
    tab.family.setCurrentIndex(2)
    tab.before.setValue(1)
    tab.after.setValue(1)
    return tab


def test_real_gui_runs_both_directions_and_locates_matching_starts(connected, monkeypatch):
    tab = prepare(connected)
    parent = connected.presenter._binning_result
    threads = []
    original = tab.results.set_result
    monkeypatch.setattr(tab.results, "set_result", lambda value: (threads.append(get_ident()), original(value)))
    for kind in ("T", "P"):
        tab.event.setCurrentIndex(tab.event.findData(kind))
        tab.family.setCurrentIndex(2)
        tab.run_button.click()
        until(lambda: not connected.presenter._busy)
        study = connected.presenter._study_result
        assert study is tab.results._result and study.request.event_kind == kind
        assert set(study.frame("events").event_kind) == {kind}
        assert connected.presenter._binning_result is parent
        tab.results.patterns.table.selectRow(0)
        tab.results.target_matches.click()
        until(lambda: not connected.presenter._busy)
        assert tab.results.views.currentIndex() == 3
        assert not tab.results.events.model.frame.empty
        tab.results.events.table.selectRow(0)
        assert not tab.results.window.model.frame.empty
        assert '"formation"' in tab.results.evidence_text.toPlainText()
    assert threads == [get_ident(), get_ident()]


def change_refinement(tab, group):
    controls = tab.refinement
    if group == "preceding":
        controls.preceding.setChecked(True)
        controls.memberships["down"].setCurrentIndex(1)
    else:
        target = getattr(controls, group)
        target.setChecked(True)
        target.rows[0].minimum.setText("0")


@pytest.mark.parametrize("change", ("family", "origin", "date", "binning", "uncheck", "remove", "reload", "close",
                                    "preceding", "movement", "duration", "pullbacks"))
def test_dependent_invalidation_keeps_only_the_valid_parent(connected, change):
    tab = prepare(connected)
    tab.run_button.click()
    until(lambda: not connected.presenter._busy)
    parent = connected.presenter._binning_result
    assert connected.presenter._study_result is not None
    if change == "family":
        tab.family.setCurrentIndex(1)
    elif change == "origin":
        tab.origin.setCurrentIndex(1)
    elif change == "date":
        tab.start.setDateTime(tab.start.dateTime().addSecs(60))
    elif change == "binning":
        connected.window.variation_tab.defaults.positive_bins.setValue(7)
    elif change == "uncheck":
        connected.window.selected_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    elif change == "remove":
        connected.window.remove_database(parent.entry.reference.database_id)
    elif change == "reload":
        connected.window.variation_tab.reload_button.click()
        until(lambda: not connected.presenter._busy)
    elif change in ("preceding", "movement", "duration", "pullbacks"):
        change_refinement(tab, change)
    else:
        connected.window.close()
    assert tab.results._result is None and connected.presenter._study_result is None
    assert (connected.presenter._binning_result is parent) == (change in
        ("family", "origin", "date", "preceding", "movement", "duration", "pullbacks"))


@pytest.mark.parametrize("operation", ("catalogue", "study", "matches"))
def test_cancel_and_failure_are_visible_and_remain_retryable(connected, monkeypatch, operation):
    tab = prepare(connected)
    tab.run_button.click()
    until(lambda: not connected.presenter._busy)
    if operation == "matches":
        tab.results.patterns.table.selectRow(0)
    method = {"catalogue": "load_pattern_catalogue", "study": "run_patterns", "matches": "pattern_matches"}[operation]
    action = {"catalogue": tab.load_button, "study": tab.run_button, "matches": tab.results.target_matches}[operation]
    actual = getattr(connected.domain, method)
    started, release = Event(), Event()
    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return actual(*args, **kwargs)
    monkeypatch.setattr(connected.domain, method, blocked)
    ticks = []
    timer = QTimer(connected.window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        action.click()
        until(started.is_set)
        until(lambda: len(ticks) >= 4)
        connected.window.cancel_button.click()
        assert connected.presenter._busy and not tab.run_button.isEnabled()
        assert connected.window.operation_labels["state"].text() == "Cancelling"
        release.set()
        until(lambda: not connected.presenter._busy)
        assert connected.window.operation_labels["state"].text() == "Cancelled"
        if operation != "matches":
            assert tab.results._result is None
        if operation == "catalogue":
            assert tab._catalogue is None and tab.load_button.isEnabled()
        else:
            assert connected.presenter._binning_result is not None
        def failure(*args, **kwargs):
            raise ValueError("fixture study failure")
        monkeypatch.setattr(connected.domain, method, failure)
        action.click()
        until(lambda: not connected.presenter._busy)
        assert connected.window.operation_labels["state"].text() == "Failed"
        assert "fixture study failure" in connected.window.status_log_text()
    finally:
        release.set()
        timer.stop()


def test_unchanged_refresh_keeps_results_changed_revision_invalidates(connected):
    tab = prepare(connected)
    tab.run_button.click()
    until(lambda: not connected.presenter._busy)
    study = tab.results._result
    connected.presenter.refresh()
    until(lambda: not connected.presenter._busy)
    assert tab.results._result is study
    identity = study.request.reference.database_id
    plan = connected.dms.plan_database_content_edit(identity, remove_columns=("up_0",))
    connected.dms.execute_database_content_edit(plan)
    connected.presenter.refresh()
    until(lambda: not connected.presenter._busy)
    assert tab.results._result is None and connected.presenter._binning_result is None
    assert connected.presenter._loaded.entry.reference.revision_id != study.request.reference.revision_id


class DelayedPatterns(DelayedService):
    def submit_pattern_catalogue(self, session, result, **callbacks):
        return self._submit("utc_catalogue", result, callbacks)
    def submit_patterns(self, session, result, request, **callbacks):
        return self._submit("patterns", request, callbacks)


@pytest.mark.parametrize("change", ("event", "source", "close", "preceding", "movement", "duration", "pullbacks"))
def test_old_success_cannot_repopulate_an_invalidated_study(qapp, tmp_path, change):
    domain, parent, catalogue, req, _ = real_study(tmp_path)
    fake = DelayedPatterns()
    window = AnalysisSuiteWindow()
    presenter = AnalysisSuitePresenter(window, fake)
    try:
        presenter._analysis_completed(parent)
        window.pattern_tab.set_catalogue(catalogue)
        select_event(window.pattern_tab)
        presenter.run_patterns()
        study = domain.run_patterns(parent, fake.calls[0][1])
        if change == "event":
            window.pattern_tab.event.setCurrentIndex(2)
        elif change == "source":
            presenter._source_changed(None)
        elif change in ("preceding", "movement", "duration", "pullbacks"):
            change_refinement(window.pattern_tab, change)
        else:
            window.close()
        fake.complete(0, study)
        assert presenter._study_result is None and window.pattern_tab.results._result is None
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_production_window_reopens_with_fresh_study_session(qapp, tmp_path):
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import load_default_config, AuditConfig
    from leonardo.gui.composition import GuiCompositionRoot
    domain, parent, _, _, _ = real_study(tmp_path/"fixture")
    (tmp_path/"runtime").mkdir()
    app = LeonardoApp(replace(load_default_config(tmp_path/"runtime"), audit=AuditConfig(enabled=False)))
    shutil.copytree(domain._store.root_dir, app.data_manager_creation_store.root_dir, dirs_exist_ok=True)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    main.show()
    try:
        main.action_for_id("main_window.open_analysis_suite").trigger()
        window, presenter = composition.analysis_suite_window, composition.analysis_suite_presenter
        until(lambda: not presenter._busy)
        choose_database(window, parent.entry.reference.database_id)
        until(lambda: not presenter._busy and presenter._loaded is not None)
        select_columns(window.variation_tab, "close")
        window.variation_tab.run_button.click()
        until(lambda: not presenter._busy)
        tab = prepare(SimpleNamespace(window=window, presenter=presenter))
        tab.run_button.click()
        until(lambda: not presenter._busy)
        assert presenter._study_result is not None
        window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        main.action_for_id("main_window.open_analysis_suite").trigger()
        fresh = composition.analysis_suite_presenter
        until(lambda: not fresh._busy)
        assert fresh.session != presenter.session
        assert fresh._binning_result is None and fresh._study_result is None
        assert not composition.analysis_suite_window.pattern_tab.run_button.isEnabled()
    finally:
        main.close()
        app.shutdown()
        main.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
