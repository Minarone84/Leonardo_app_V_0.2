"""The production DAS entry point owns one presenter and retires it safely."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from dataclasses import replace
from threading import Event, Timer

import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import load_default_config, AuditConfig
from leonardo.gui.composition import GuiCompositionRoot
from tests.analysis_test.test_analysis_service import make_database
from tests.gui_test.test_analysis_execution_presenter import choose_database, select_columns, until

_APP=None


@pytest.fixture(scope='module')
def qapp():
    global _APP
    _APP=QApplication.instance() or QApplication([])
    return _APP


def test_main_application_executes_retires_and_reopens_analysis(qapp,tmp_path):
    (tmp_path/'runtime').mkdir()
    app=LeonardoApp(replace(load_default_config(tmp_path/'runtime'),audit=AuditConfig(enabled=False)))
    store,manifest,_=make_database(tmp_path/'fixture',store=app.data_manager_creation_store)
    context=app.startup()
    app.start_core_runtime()
    composition=GuiCompositionRoot(context)
    main=composition.create_main_window()
    main.show()
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        window=composition.analysis_suite_window
        presenter=composition.analysis_suite_presenter
        until(lambda:not presenter._busy)
        choose_database(window,manifest.database_id)
        until(lambda:presenter._loaded is not None and not presenter._busy)
        select_columns(window.variation_tab,'delta')
        window.variation_tab.run_button.click()
        until(lambda:window.variation_tab.results._result is not None)
        assert any(t.metadata.get('area')=='analysis' for t in app.task_manager.snapshots())
        main.action_for_id('main_window.open_analysis_suite').trigger()
        assert composition.analysis_suite_window is window
        window.open_database_selector()
        window.close()
        assert presenter.is_disposed
        assert composition.analysis_suite_window is None and composition.analysis_suite_presenter is None
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        main.action_for_id('main_window.open_analysis_suite').trigger()
        reopened=composition.analysis_suite_window
        fresh=composition.analysis_suite_presenter
        until(lambda:not fresh._busy)
        assert fresh.session!=presenter.session
        assert reopened.selected_databases()==()
        assert reopened.variation_tab.results._result is None
        assert next(w for w in app.window_registry.list_windows() if w.window_id=='analysis_suite.window').status=='open'
        main.close()
        assert composition.analysis_suite_window is None
    finally:
        main.close()
        app.shutdown()
        main.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_close_while_running_then_reopen_waits_for_old_worker(qapp,tmp_path,monkeypatch):
    (tmp_path/'runtime').mkdir()
    app=LeonardoApp(replace(load_default_config(tmp_path/'runtime'),audit=AuditConfig(enabled=False)))
    _store,manifest,_=make_database(tmp_path/'fixture',store=app.data_manager_creation_store)
    app.startup();app.start_core_runtime()
    composition=GuiCompositionRoot(app.context)
    main=composition.create_main_window()
    main.show()
    started,release=Event(),Event()
    original=app.analysis_domain.run
    def blocked(*args,**kw):
        started.set()
        assert release.wait(5)
        return original(*args,**kw)
    monkeypatch.setattr(app.analysis_domain,'run',blocked)
    try:
        main.action_for_id('main_window.open_analysis_suite').trigger()
        view=composition.analysis_suite_window; presenter=composition.analysis_suite_presenter
        until(lambda:not presenter._busy)
        choose_database(view,manifest.database_id)
        until(lambda:presenter._loaded is not None and not presenter._busy)
        select_columns(view.variation_tab,'delta')
        view.variation_tab.run_button.click()
        until(started.is_set)
        view.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        main.action_for_id('main_window.open_analysis_suite').trigger()
        fresh=composition.analysis_suite_presenter
        assert fresh._waiting_refresh
        release.set()
        until(lambda:not fresh._waiting_refresh and not fresh._busy)
        assert composition.analysis_suite_window.variation_tab.results._result is None
        assert not app.analysis_service.has_draining_workers
    finally:
        release.set();main.close();app.shutdown();main.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
