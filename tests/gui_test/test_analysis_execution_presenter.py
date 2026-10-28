"""Connected Analysis GUI, queued delivery and stale-callback protection."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
from threading import Event, get_ident
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from leonardo.analysis import AnalysisService, AnalysisApplicationService
from leonardo.core.core_runner import CoreRunner, TaskResult, TaskProgress, TaskSubmission
from leonardo.core.task_manager import TaskManager
from leonardo.gui.analysis.presenter import AnalysisSuitePresenter
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow
from tests.analysis_test.test_analysis_service import make_database, publish_next, reference, request

_APP = None


@pytest.fixture(scope='module')
def qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def until(predicate, timeout=7000):
    limit = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < limit:
        QTest.qWait(5)
    assert predicate()


def choose_database(window, identity):
    window.open_database_selector()
    for row in range(window._selector.table.rowCount()):
        item = window._selector.table.item(row,0)
        if item.data(Qt.ItemDataRole.UserRole) == identity:
            item.setCheckState(Qt.CheckState.Checked)
    window._selector.add_button.click()
    tab = window.variation_tab
    tab.database_choice.setCurrentIndex(tab.database_choice.findData(identity))


def select_columns(tab, *names):
    for row in range(tab.columns.rowCount()):
        item = tab.columns.item(row,0)
        item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in names else Qt.CheckState.Unchecked)


@pytest.fixture
def connected(qapp, tmp_path):
    store, manifest, frame = make_database(tmp_path)
    domain = AnalysisService(store)
    runner = CoreRunner(TaskManager())
    runner.start()
    service = AnalysisApplicationService(runner, domain)
    window = AnalysisSuiteWindow()
    presenter = AnalysisSuitePresenter(window, service)
    window.show()
    presenter.start()
    until(lambda: not presenter._busy)
    yield SimpleNamespace(window=window, presenter=presenter, service=service, domain=domain,
                          runner=runner, store=store, manifest=manifest, frame=frame)
    window.close()
    service.cancel_all_pending()
    runner.shutdown()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def load(connected):
    choose_database(connected.window, connected.manifest.database_id)
    until(lambda: connected.presenter._loaded is not None and not connected.presenter._busy)
    select_columns(connected.window.variation_tab, 'delta')


def inspector_fields(window):
    return {window.inspector.item(row, 0).text(): window.inspector.item(row, 1).text()
            for row in range(window.inspector.rowCount())}


def assert_pinned_details(window, manifest):
    fields = inspector_fields(window)
    assert fields['Active analysis database'] == f'{manifest.display_name} [{manifest.database_id}]'
    assert fields['Pinned revision'] == manifest.revision_id
    assert fields['Values SHA-256'] == manifest.values_sha256
    for row in range(window.inspector.rowCount()):
        item = window.inspector.item(row, 1)
        assert item.toolTip() == item.text()


def test_inspector_refresh_row_and_timezone_preserve_active_source_and_results(connected, qapp, tmp_path):
    from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
    _, other, _ = make_database(tmp_path/'other', store=connected.store, name='Other fixture')
    connected.presenter.refresh()
    until(lambda: not connected.presenter._busy)
    choose_database(connected.window, other.database_id)
    until(lambda: not connected.presenter._busy)
    load(connected)
    view, tab = connected.window, connected.window.variation_tab
    override = tab.column_override('delta')
    override.override.setChecked(True)
    override.editor.positive_bins.setValue(7)
    configuration = tab.configuration()
    tab.run_button.click()
    until(lambda: not connected.presenter._busy)
    result = tab.results._result
    assert result is not None
    connected.presenter.refresh()
    until(lambda: not connected.presenter._busy)
    assert_pinned_details(view, connected.manifest)
    # The highlighted workspace row is independent of the active analysis source.
    for row in range(view.selected_table.rowCount()):
        if view.selected_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == other.database_id:
            view.selected_table.selectRow(row)
    assert inspector_fields(view)['Database ID'] == other.database_id
    assert_pinned_details(view, connected.manifest)
    previous_zone = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, 'UTC')
        connected.presenter.refresh_display_time()
        assert_pinned_details(view, connected.manifest)
        assert connected.presenter._loaded.entry.reference == reference(connected.manifest)
        assert tab.configuration() == configuration
        assert tab.results._result is result
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, previous_zone)


@pytest.mark.parametrize('action', ['clear', 'uncheck', 'remove', 'reload_failure', 'close'])
def test_invalidated_source_clears_inspector_provenance(connected, action):
    load(connected)
    view, tab = connected.window, connected.window.variation_tab
    assert_pinned_details(view, connected.manifest)
    if action == 'clear':
        tab.database_choice.setCurrentIndex(0)
    elif action == 'uncheck':
        view.selected_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    elif action == 'remove':
        view.remove_database(connected.manifest.database_id)
    elif action == 'close':
        view.close()
    else:
        path = connected.store.root_dir/'databases'/connected.manifest.database_id/'revisions'/connected.manifest.revision_id/'values.csv'
        path.write_bytes(path.read_bytes() + b'bad')
        tab.reload_button.click()
        assert 'Pinned revision' not in inspector_fields(view)
        until(lambda: not connected.presenter._busy)
        assert view.operation_labels['state'].text() == 'Failed'
    assert connected.presenter._loaded is None
    assert not {'Active analysis database', 'Pinned revision', 'Values SHA-256'} & inspector_fields(view).keys()


def test_catalogue_cancellation_retains_loaded_state_and_allows_retry(connected, monkeypatch):
    load(connected)
    view, tab = connected.window, connected.window.variation_tab
    tab.run_button.click()
    until(lambda: not connected.presenter._busy)
    result, configuration = tab.results._result, tab.configuration()
    expected_catalog = view._catalog
    view.open_database_selector()
    started, release = Event(), Event()
    original = connected.domain.catalog
    def blocked(**kwargs):
        started.set()
        assert release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(connected.domain, 'catalog', blocked)
    try:
        connected.presenter.refresh()
        until(started.is_set)
        view.cancel_button.click()
        assert connected.presenter._busy
        assert not view._selector.refresh_button.isEnabled()
        release.set()
        until(lambda: not connected.presenter._busy)
        message = view.catalog_label.text()
        assert 'cancelled' in message.lower() and 'Previous catalogue retained' in message
        assert 'Refresh Databases' in message
        assert view._selector.source_label.text() == message == view._source_label
        assert view._catalog == expected_catalog
        assert view._selector.refresh_button.isEnabled()
        assert tab.configuration() == configuration and tab.results._result is result
        assert_pinned_details(view, connected.manifest)
        view._selector.refresh_button.click()
        until(lambda: not connected.presenter._busy)
        assert view.catalog_label.text() == '1 saved databases available.'
        assert view._selector.source_label.text() == view.catalog_label.text()
        assert tab.results._result is result
    finally:
        release.set()


def test_blocked_fitting_indicator_is_indeterminate_until_completion(connected, monkeypatch):
    import leonardo.analysis.service as module
    load(connected)
    started, release = Event(), Event()
    original = module.fit_directional_binning
    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'fit_directional_binning', blocked)
    view, tab = connected.window, connected.window.variation_tab
    try:
        tab.run_button.click()
        until(lambda: started.is_set() and view.operation_labels['status'].text().startswith('Fitting'))
        assert view.operation_labels['status'].text() == 'Fitting delta (1/1)'
        assert view.progress.minimum() == view.progress.maximum() == 0
        assert view.progress.isEnabled() and not tab.run_button.isEnabled()
        release.set()
        until(lambda: not connected.presenter._busy)
        assert view.progress.maximum() == view.progress.value() == 1
        assert tab.results._result is not None and tab.run_button.isEnabled()
    finally:
        release.set()
        until(lambda: not connected.presenter._busy)


def test_database_columns_run_and_results_use_real_queued_path(connected, monkeypatch):
    load(connected)
    window, tab = connected.window, connected.window.variation_tab
    assert tab.run_button.isEnabled()
    assert 'Revision' in tab.column_source.text()
    assert 'ts_ms' in tab.column_issues.text()
    threads = []
    original = tab.results.set_result
    monkeypatch.setattr(tab.results, 'set_result', lambda value: (threads.append(get_ident()), original(value)))
    tab.run_button.click()
    assert not tab.run_button.isEnabled() and not tab.columns.isEnabled()
    until(lambda: tab.results._result is not None)
    assert threads == [get_ident()]
    assert tab.results.column.count() == 1
    assert len(tab.results.model.frame.columns) == 35
    assert len(tab.results.model.frame) == len(connected.frame)
    assert tab.results.bins.rowCount() == 20
    assert tab.run_button.isEnabled()


def test_failed_analysis_replaces_running_placeholder(connected, monkeypatch):
    load(connected)
    def fail(*args, **kwargs):
        raise ValueError("Fixture revision validation failure")
    monkeypatch.setattr(connected.domain, "run", fail)
    connected.window.variation_tab.run_button.click()
    until(lambda: not connected.presenter._busy)
    tab = connected.window.variation_tab
    assert tab.results._result is None
    assert "Analysis failed" in tab.results.source.text()
    assert connected.window.operation_labels["state"].text() == "Failed"
    assert "Fixture revision validation failure" in connected.window.status_log_text()
    assert tab.run_button.isEnabled()


def test_gui_remains_responsive_duplicate_start_and_cancellation_drain(connected, monkeypatch):
    load(connected)
    started, release = Event(), Event()
    actual = connected.domain.run
    calls = []
    def blocked(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return actual(*args, **kwargs)
    monkeypatch.setattr(connected.domain, 'run', blocked)
    ticks = []
    timer = QTimer(connected.window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    tab = connected.window.variation_tab
    try:
        tab.run_button.click()
        until(started.is_set)
        connected.presenter.run()
        until(lambda: len(ticks) > 4)
        connected.window.cancel_button.click()
        assert connected.presenter._busy and not tab.run_button.isEnabled()
        assert 'Cancelling' in connected.window.operation_labels['state'].text()
        assert tab.results._result is None and len(calls) == 1
        release.set()
        until(lambda: not connected.presenter._busy)
        assert tab.results._result is None and tab.run_button.isEnabled()
        assert connected.window.operation_labels['state'].text() == 'Cancelled'
        assert 'Analysis cancelled' in tab.results.source.text()
    finally:
        release.set()
        timer.stop()


def test_configuration_change_clears_results_and_rejects_running_output(connected, monkeypatch):
    load(connected)
    tab = connected.window.variation_tab
    tab.run_button.click()
    until(lambda: tab.results._result is not None)
    tab.defaults.positive_bins.setValue(13)
    assert tab.results._result is None
    started, release = Event(), Event()
    original = connected.domain.run
    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(connected.domain, 'run', blocked)
    try:
        tab.run_button.click()
        until(started.is_set)
        tab.defaults.negative_bins.setValue(7)
        release.set()
        until(lambda: not connected.presenter._busy)
        assert tab.results._result is None
    finally:
        release.set()


def test_refresh_pins_new_revision_and_unchanged_refresh_keeps_settings(connected):
    load(connected)
    tab = connected.window.variation_tab
    tab.defaults.positive_bins.setValue(15)
    connected.presenter.refresh()
    until(lambda: not connected.presenter._busy)
    assert tab.selected_column_names() == ('delta',)
    changed = connected.frame.copy()
    changed['delta'] = changed['delta'] * 3
    head = publish_next(connected.store, connected.manifest, changed)
    assert connected.presenter._loaded.entry.reference == reference(connected.manifest)
    connected.presenter.refresh()
    until(lambda: connected.presenter._loaded is not None and connected.presenter._loaded.entry.reference == reference(head) and not connected.presenter._busy)
    assert tab.selected_column_names() == ()
    assert tab.defaults.positive_bins.value() == 15
    assert_pinned_details(connected.window, head)
    assert tab.results._result is None
    select_columns(tab, 'delta')
    tab.reload_button.click()
    until(lambda: not connected.presenter._busy)
    assert tab.selected_column_names() == ()


def test_failed_load_retry_and_removed_database(connected):
    path = connected.store.root_dir/'databases'/connected.manifest.database_id/'revisions'/connected.manifest.revision_id/'values.csv'
    original = path.read_bytes()
    path.write_bytes(original+b'bad')
    choose_database(connected.window, connected.manifest.database_id)
    until(lambda: not connected.presenter._busy)
    assert connected.presenter._loaded is None
    assert not connected.window.variation_tab.run_button.isEnabled()
    assert 'hash' in connected.window.status_log_text()
    path.write_bytes(original)
    connected.window.variation_tab.reload_button.click()
    until(lambda: connected.presenter._loaded is not None and not connected.presenter._busy)
    connected.window.remove_database(connected.manifest.database_id)
    assert connected.presenter._loaded is None and connected.window.variation_tab.active_database_id() is None


class DelayedService:
    has_draining_workers = False
    def __init__(self):
        self.calls = []
        self.cancelled = 0
    def begin_session(self): return 'test-session'
    def end_session(self, session): self.cancelled += 1
    def cancel(self, session): self.cancelled += 1; return True
    def _submit(self, kind, payload, callbacks):
        self.calls.append((kind, payload, callbacks))
        return TaskSubmission(str(len(self.calls)), kind)
    def submit_catalog(self, session, **callbacks): return self._submit('catalog', None, callbacks)
    def submit_columns(self, session, reference, **callbacks): return self._submit('columns', reference, callbacks)
    def submit_analysis(self, session, request, **callbacks): return self._submit('analysis', request, callbacks)
    def complete(self, index, value=None, status='completed'):
        self.calls[index][2]['result_callback'](TaskResult(str(index+1), status, value, error_message='old failure'))


@pytest.mark.parametrize('prior', ['none', 'empty', 'warnings'])
@pytest.mark.parametrize('waiting_for_drain', [False, True])
def test_cancelled_catalogue_distinguishes_first_load_from_retained_catalogue(qapp, tmp_path, prior, waiting_for_drain):
    store, _, _ = make_database(tmp_path)
    domain, fake = AnalysisService(store), DelayedService()
    view = AnalysisSuiteWindow()
    presenter = AnalysisSuitePresenter(view, fake)
    try:
        if prior != 'none':
            presenter.start()
            catalog = domain.catalog()
            catalog = replace(catalog, entries=() if prior == 'empty' else catalog.entries,
                              issues=('Fixture warning',) if prior == 'warnings' else ())
            fake.complete(0, catalog)
        expected_catalog = view._catalog
        fake.has_draining_workers = waiting_for_drain
        presenter.refresh()
        view.open_database_selector()
        view.cancel_button.click()
        if waiting_for_drain:
            assert not presenter._retry.isActive()
            assert len(fake.calls) == (0 if prior == 'none' else 1)
        else:
            fake.complete(len(fake.calls) - 1, status='cancelled')
        message = view.catalog_label.text()
        assert view.operation_labels['state'].text() == 'Cancelled'
        assert not presenter._busy and not presenter._waiting_refresh
        assert 'loading' not in message.lower() and 'cancelled' in message.lower()
        assert 'Refresh Databases' in message
        assert view._selector.source_label.text() == view._source_label == message
        assert view._catalog == expected_catalog
        assert view._selector.refresh_button.isEnabled()
        if prior == 'none':
            assert 'No catalogue loaded' in message
        else:
            assert 'Previous catalogue retained' in message
            assert ('0 saved databases' if prior == 'empty' else '1 database(s) unavailable') in message
    finally:
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('late_status', ['completed','failed'])
def test_old_source_result_progress_and_failure_cannot_update_new_selection(qapp, tmp_path, late_status):
    store, first, _ = make_database(tmp_path/'a')
    _, second, _ = make_database(tmp_path/'b', store=store)
    domain, fake = AnalysisService(store), DelayedService()
    view = AnalysisSuiteWindow()
    presenter = AnalysisSuitePresenter(view, fake)
    try:
        presenter.start()
        fake.complete(0, domain.catalog())
        view.open_database_selector()
        for row in range(view._selector.table.rowCount()):
            view._selector.table.item(row,0).setCheckState(Qt.CheckState.Checked)
        view._selector.add_button.click()
        tab = view.variation_tab
        tab.database_choice.setCurrentIndex(tab.database_choice.findData(first.database_id))
        old = fake.calls[1][2]
        # Programmatic changes must be fenced even while user controls are locked.
        tab.database_choice.setCurrentIndex(tab.database_choice.findData(second.database_id))
        assert 'Pinned revision' not in inspector_fields(view)
        old['progress_callback'](TaskProgress('2','OUTDATED PROGRESS'))
        assert 'OUTDATED' not in view.status_text()
        fake.complete(1, domain.load_columns(reference(first)), late_status)
        assert fake.calls[-1][1] == reference(second)
        fake.complete(2, domain.load_columns(reference(second)))
        assert presenter._loaded.entry.reference == reference(second)
        assert_pinned_details(view, second)
        assert 'old failure' not in view.status_log_text()
        assert view.variation_tab.selected_column_names() == ()
        view.close()
        old['progress_callback'](TaskProgress('2','AFTER CLOSE'))
        old['result_callback'](TaskResult('2','completed',None))
    finally:
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_action_rejection_prevents_execution_and_refresh(qapp, tmp_path):
    fake = DelayedService()
    view = AnalysisSuiteWindow(action_observer=SimpleNamespace(record_action=lambda *a,**kw: SimpleNamespace(allowed=False)))
    presenter = AnalysisSuitePresenter(view, fake)
    presenter.refresh()
    presenter.run()
    presenter.reload()
    assert fake.calls == []
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
