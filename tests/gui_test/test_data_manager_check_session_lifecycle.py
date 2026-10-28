from dataclasses import replace
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtCore import QEventLoop, QMetaObject, QTimer, Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from leonardo.core.core_runner import TaskResult
from leonardo.core.window_registry import WindowRegistry
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_presenter import _ControlledApplication
from tests.gui_test.test_data_manager_presenter import (
    MARKET_SNAPSHOT,
    _product_catalog,
    _projected_artifact_collection,
    _settle_initial_warmup,
)
from tests.gui_test.test_data_manager_concurrency import _Controlled
from tests.data_manager_test.test_update_workflow import MARKET, _domain


_QAPP = QApplication.instance() or QApplication([])


def _close(view, presenter):
    presenter.dispose()
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(view, QEvent.Type.DeferredDelete)


def test_controlled_adapters_without_domain_keep_supported_lifecycle():
    for application in (_Controlled(), _ControlledApplication(), _ControlledApplication(product_catalogs=True)):
        view = DataManagerSuiteWindow()
        presenter = DataManagerSuitePresenter(view, application)
        try:
            application.invalidate_source(MARKET)
        finally:
            _close(view, presenter)


def test_presenter_starts_and_disposes_real_session_but_hiding_keeps_it(tmp_path):
    domain, artifacts, recipes, historical = _domain(tmp_path)
    application = _ControlledApplication()
    application._service = domain
    domain.inspect_market(MARKET)
    view = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(view, application)
    try:
        assert not domain._source_evidence
        domain.inspect_market(MARKET)
        epoch = domain._session_generation
        view.show()
        view.hide()
        view.show()
        assert domain._session_generation == epoch
        assert MARKET in domain._source_evidence
        presenter.dispose()
        assert not domain._source_evidence
        assert domain._session_generation == epoch + 1
        presenter.dispose()
        assert domain._session_generation == epoch + 1
    finally:
        _close(view, presenter)


def test_presenter_notifications_invalidate_real_evidence(tmp_path):
    domain, artifacts, recipes, historical = _domain(tmp_path)
    application = _ControlledApplication()
    application._service = domain
    view = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(view, application)
    try:
        domain.inspect_market(MARKET)
        presenter.notify_external_ohlcv_change(MARKET)
        assert MARKET not in domain._source_evidence
        domain.inspect_market(MARKET)
        presenter.notify_ohlcv_validation_accepted(MARKET)
        assert MARKET not in domain._source_evidence
    finally:
        _close(view, presenter)


@pytest.mark.parametrize("route", ("selector", "view_select_market", "presenter"))
@pytest.mark.parametrize("selected_row", (False, True))
def test_dataset_selection_with_catalog_row_does_not_steal_market_inspection(
    route, selected_row,
):
    class Controlled(_ControlledApplication):
        def submit_list_artifact_collection_revisions(self, collection_id, **values):
            return self._submit(
                ("collection_history", collection_id), values["result_callback"],
            )

    market = MARKET_SNAPSHOT.market_id
    revision = _projected_artifact_collection(
        "ac_" + "a" * 32, "1" * 64, "Selection regression",
    )
    snapshot = replace(_product_catalog("a"), artifact_collections=(revision,))
    view = DataManagerSuiteWindow()
    service = Controlled(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service, snapshot=snapshot)
        workspace = view._catalog_workspace
        workspace.select_family("Artifact Collections")
        workspace.dataset_scope.setCurrentIndex(workspace.dataset_scope.findData("all"))
        assert workspace.table.rowCount() == 1
        if selected_row:
            workspace.table.selectRow(0)
            initial = service.calls[-1]
            assert initial[0] == ("collection_history", revision.collection_id)
            initial[2](TaskResult(initial[1], "completed", (revision,)))
        assert presenter._active_task_id is None

        start = len(service.calls)
        if route == "selector":
            view._on_dataset_selector_selected(market)
        elif route == "view_select_market":
            assert view.select_market(market)
        else:
            presenter._on_market_selected(market)
        triggered = service.calls[start:]
        assert [call[0] for call in triggered] == [("inspect", market)]
        assert view._selected_market == presenter.selected_market_id == market
        inspection = triggered[0]
        inspection[2](TaskResult(inspection[1], "completed", MARKET_SNAPSHOT))
        assert presenter._market_snapshot is MARKET_SNAPSHOT
        assert view._selected_market == presenter.selected_market_id == market
        assert presenter._active_task_id is None

        before_create = len(service.calls)
        presenter._open_direct_artifact_creation()
        assert [call[0] for call in service.calls[before_create:]] == [
            ("direct_catalog", market),
        ]
    finally:
        _close(view, presenter)


@pytest.mark.parametrize("track_windows", (False, True))
@pytest.mark.parametrize("route", ("dms_then_main", "main_with_dms", "reopen"))
def test_dms_owner_retires_closed_window_and_preserves_new_session(
    tmp_path, capfd, track_windows, route,
):
    domain, _, _, _ = _domain(tmp_path)
    application = _ControlledApplication()
    application._service = domain
    context = SimpleNamespace(
        runtime_manager=SimpleNamespace(snapshot=lambda: None),
        window_registry=WindowRegistry(),
        data_manager_service=application,
    )
    composition = GuiCompositionRoot(context, track_windows=track_windows)
    main = composition.create_main_window()
    owned = []
    main.show()
    try:
        composition._open_data_manager_suite(main)
        window = composition.data_manager_suite_window
        presenter = composition.data_manager_suite_presenter
        owned.append((window, presenter))
        domain.inspect_market(MARKET)
        epoch = domain._session_generation
        assert MARKET in domain._source_evidence
        if route == "main_with_dms":
            main.close()
        else:
            window.close()
            QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
            assert not isValid(window)
            if route == "dms_then_main":
                composition._close_suite_shells()
                main.close()
        assert presenter.is_disposed
        assert not domain._source_evidence
        assert domain._session_generation == epoch + 1
        assert composition.data_manager_suite_window is None
        assert composition.data_manager_suite_presenter is None
        assert composition.tracker_for("data_manager_suite.window") is None
        if track_windows:
            row = next(item for item in context.window_registry.list_windows()
                       if item.window_id == "data_manager_suite.window")
            assert row.status == "closed"
        if route == "reopen":
            composition._open_data_manager_suite(main)
            replacement = composition.data_manager_suite_window
            replacement_presenter = composition.data_manager_suite_presenter
            owned.append((replacement, replacement_presenter))
            assert replacement is not window
            assert replacement_presenter is not presenter
            assert not replacement_presenter.is_disposed
            assert not domain._source_evidence
            assert domain._session_generation == epoch + 2
            replacement_tracker = composition.tracker_for("data_manager_suite.window")
            for stale_pair in ((window, presenter), (replacement, presenter),
                               (window, replacement_presenter)):
                composition._retire_data_manager_suite(*stale_pair)
                assert composition.data_manager_suite_window is replacement
                assert composition.data_manager_suite_presenter is replacement_presenter
                assert composition.tracker_for("data_manager_suite.window") is replacement_tracker
            domain.inspect_market(MARKET)
            assert MARKET in domain._source_evidence
            main.close()
            assert not domain._source_evidence
            assert domain._session_generation == epoch + 3
            assert composition.data_manager_suite_window is None
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert all(not isValid(item[0]) for item in owned)
        assert "Error calling Python override" not in capfd.readouterr().err
    finally:
        for view, owner in owned:
            owner.dispose()
            if isValid(view):
                view.close()
                QCoreApplication.sendPostedEvents(view, QEvent.Type.DeferredDelete)
        composition._data_manager_suite_window = None
        composition._data_manager_suite_presenter = None
        main.close()
        main.deleteLater()
        QCoreApplication.sendPostedEvents(main, QEvent.Type.DeferredDelete)


def test_dms_shutdown_error_guard_captures_native_qt_callback_failure(capfd):
    def injected_failure():
        raise RuntimeError("deliberate test-only shutdown error")

    context = SimpleNamespace(runtime_manager=SimpleNamespace(snapshot=lambda: None))
    composition = GuiCompositionRoot(context, track_windows=False)
    composition._close_suite_shells = injected_failure
    main = composition.create_main_window()
    try:
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        assert QMetaObject.invokeMethod(main, "close", Qt.ConnectionType.QueuedConnection)
        loop.exec()
        error = capfd.readouterr().err
        assert "Error calling Python override" in error
        assert "deliberate test-only shutdown error" in error
    finally:
        main._on_close_requested = lambda: None
        main.close()
        main.deleteLater()
        QCoreApplication.sendPostedEvents(main, QEvent.Type.DeferredDelete)
