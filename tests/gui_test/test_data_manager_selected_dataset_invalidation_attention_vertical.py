from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton
from shiboken6 import isValid

from leonardo.core.core_runner import TaskResult
from leonardo.data_manager import DataManagerPreview
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_catalogs import associated_product_snapshot
from tests.gui_test.test_data_manager_dataset_selector_dialog import _assert_dataset_attention_typography
from tests.gui_test.test_data_manager_suite_window import _selected_dataset_values, _assert_selected_dataset_typography, _assert_selector_normal
from tests.gui_test.test_data_manager_presenter import (
    CATALOG_BOTH, MARKET, MARKET_B, MARKET_SNAPSHOT, MARKET_SNAPSHOT_B,
    _ControlledApplication, _direct_catalog, _reconciliation, _settle_initial_warmup,
)


def test_selected_dataset_invalidation_attention_real_gui_lifecycle():
    recovery_market = MARKET_B
    app = QApplication.instance() or QApplication([])
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    snapshot = replace(
        associated_product_snapshot(), catalog=CATALOG_BOTH,
        latest_reconciliation=_reconciliation("a"),
    )
    try:
        view.show()
        normal_operation = view._operation_surface.styleSheet()
        normal_status = view._operation_surface._status.styleSheet()
        normal_selected_table = view._selected_dataset_table.styleSheet()
        _settle_initial_warmup(service, snapshot=snapshot)
        view._show_dataset_selector()
        selector = view.dataset_selector_dialog()
        selector._table.cellWidget(0, 0).findChild(QCheckBox).click()
        selector.button_for_id("data_manager.dataset_selector.button.select").click()
        inspect = service.calls[-1]
        assert inspect[0] == ("inspect", MARKET)
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        workspace = view._catalog_workspace
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isEnabled()
        workspace.create_artifact_button.click()
        create_catalog = service.calls[-1]
        create_catalog[2](TaskResult(create_catalog[1], "completed", _direct_catalog()))
        child = view.artifact_creation_dialog()
        assert child.isVisible()
        preview = DataManagerPreview(
            "Dataset preview", MARKET, "dataset", None,
            ("close",), (("1",),), 1, False, {},
        )
        presenter._settle_preview(TaskResult("preview", "completed", preview), expected_market=MARKET)
        preview_dialog = next(iter(presenter._preview_dialogs))
        presenter._show_reuse_result("Reuse result", ("Existing result",))
        reuse_dialog = next(iter(presenter._reuse_result_dialogs))
        view._show_dataset_selector()
        selector._show_search_help()
        assert selector.isVisible()

        # Exact identity is required: another timeframe of the same symbol is also unrelated.
        from leonardo.data import MarketId
        for other in (MARKET_B, MarketId("bybit", "linear", "BTCUSDT", "4h")):
            presenter.notify_external_ohlcv_change(other)
            assert not view.dataset_context_suspended
            assert child.isVisible() and preview_dialog.isVisible() and reuse_dialog.isVisible()
            assert not selector._dataset_evidence_attention
            assert view._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Stopped
            assert view._operation_surface._status.styleSheet() == normal_status
            assert workspace.create_artifact_button.isEnabled()
            reconcile = service.calls[-1]
            reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("a")))
            scan = service.calls[-1]
            assert scan[0] == "scan_product_catalogs"
            scan[2](TaskResult(scan[1], "completed", snapshot))

        workspace.select_family("Recipes")
        workspace.table.selectRow(0)
        recipe_inspection = service.calls[-1]
        recipe_inspection[2](TaskResult(
            recipe_inspection[1], "completed", snapshot.portable_recipes.recipes[0]
        ))
        original_values = _selected_dataset_values(view)
        before = len(service.calls)
        presenter.notify_external_ohlcv_change(MARKET)
        assert [call[0] for call in service.calls[before:]] == ["reconcile_status"]
        assert presenter._active_task_id is None
        assert view.dataset_context_suspended
        surface = view._operation_surface
        assert surface._attention_animation.state() == QAbstractAnimation.State.Running
        assert surface._status.objectName() == "data_manager.operation.status"
        assert "#142b45" in surface._status.styleSheet()
        assert surface.styleSheet() == normal_operation
        table_animation = view._selected_dataset_attention_animation
        assert table_animation.state() == QAbstractAnimation.State.Running
        assert "#142b45" in view._selected_dataset_table.styleSheet()
        assert not child.isVisible()
        create_catalog[2](TaskResult(create_catalog[1], "completed", _direct_catalog()))
        assert not child.isVisible()
        assert not preview_dialog.isVisible()
        assert not isValid(reuse_dialog) or not reuse_dialog.isVisible()
        assert presenter._preview_dialogs == set()
        assert presenter._reuse_result_dialogs == set()
        assert not selector.isVisible()
        assert _selected_dataset_values(view) == original_values
        _assert_selected_dataset_typography(view, True)
        for animation in (surface._attention_animation, table_animation, selector._attention_animation):
            assert animation.duration() == 4000
            assert animation.loopCount() == -1
            assert [(key, color.name()) for key, color in animation.keyValues()] == [
                (0.0, "#142b45"), (0.5, "#315f8a"), (1.0, "#142b45")
            ]
        assert selector.selected_market_id() is None
        assert not selector._search_help_dialog.isVisible()
        assert view._selected_dataset_table.rowCount() == 1
        assert not any(button.isEnabled() for button in workspace.findChildren(QPushButton))
        assert not any(button.isEnabled() for button in view._update_workspace.buttons.values())
        for family in ("Study Environments", "Recipes", "Recipe Collections",
                       "Artifacts", "Artifact Collections", "Database Seeds", "Databases"):
            workspace.select_family(family)
            assert not any(button.isEnabled() for button in workspace.findChildren(QPushButton))
        assert not workspace.create_database_seed_button.isEnabled()
        assert not workspace.create_seed_only_database_button.isEnabled()
        for name in ("refresh", "select_dataset"):
            assert view.button_for_id(f"data_manager.button.{name}").isEnabled()
        assert not surface.clear_button.isEnabled()
        assert not surface.cancel_button.isEnabled()
        assert view._workspace_tabs.isEnabled()
        assert workspace.table.isEnabled() and workspace.inspector_panel().isEnabled()

        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        scan = service.calls[-1]
        scan[2](TaskResult(scan[1], "completed", replace(snapshot, latest_reconciliation=_reconciliation("b"))))
        assert view.dataset_context_suspended
        view.button_for_id("data_manager.button.refresh").click()
        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        scan = service.calls[-1]
        assert scan[0] == "scan_product_catalogs"
        scan[2](TaskResult(scan[1], "completed", replace(snapshot, latest_reconciliation=_reconciliation("b"))))
        assert view.dataset_context_suspended and not selector.isVisible()
        assert table_animation.state() == QAbstractAnimation.State.Running
        assert surface._attention_animation.state() == QAbstractAnimation.State.Running

        # Programmatic focus and its completed inspection cannot recover user context.
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        assert inspect[0] == ("inspect", MARKET)
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        assert view.dataset_context_suspended
        assert not selector.isVisible()
        assert _selected_dataset_values(view) == original_values
        workspace.select_family("Recipes")
        workspace.table.clearSelection()
        workspace.table.selectRow(0)
        inspect_recipe = service.calls[-1]
        assert inspect_recipe[0][0] == "inspect_recipe"
        assert workspace.table.isEnabled()
        assert workspace.inspector_panel().isEnabled()
        assert not surface.cancel_button.isEnabled()
        inspect_recipe[2](TaskResult(inspect_recipe[1], "completed", snapshot.portable_recipes.recipes[0]))
        assert view.dataset_context_suspended
        assert "OHLCV evidence changed" in view.status_text()

        collection_entry = snapshot.recipe_collections.collections[0]
        view.set_catalog_history(collection_entry.collection_id, (collection_entry,))
        before_history = len(service.calls)
        workspace.history.selectRow(0)
        assert workspace.inspector.rowCount() > 0
        assert len(service.calls) == before_history
        assert view.dataset_context_suspended

        assert _selected_dataset_values(view) == original_values
        view._show_dataset_selector()
        selector._table.cellWidget(0, 0).findChild(QCheckBox).click()
        selector.button_for_id("data_manager.dataset_selector.button.select").click()
        assert view.dataset_context_suspended
        assert _selected_dataset_values(view) == original_values
        _assert_selected_dataset_typography(view, True)
        view._show_dataset_selector()
        row = 1
        selector._table.cellWidget(row, 0).findChild(QCheckBox).click()
        assert selector.selected_market_id() == recovery_market
        selector.button_for_id("data_manager.dataset_selector.button.select").click()
        assert not view.dataset_context_suspended
        assert not selector._dataset_evidence_attention
        _assert_dataset_attention_typography(selector, False)
        assert surface._attention_animation.state() == QAbstractAnimation.State.Stopped
        assert table_animation.state() == QAbstractAnimation.State.Stopped
        assert view._selected_dataset_table.styleSheet() == normal_selected_table
        assert surface._status.styleSheet() == normal_status
        assert surface.styleSheet() == normal_operation
        inspect = service.calls[-1]
        assert inspect[0] == ("inspect", recovery_market)
        market_snapshot = MARKET_SNAPSHOT if recovery_market == MARKET else MARKET_SNAPSHOT_B
        inspect[2](TaskResult(inspect[1], "completed", market_snapshot))
        assert presenter.selected_market_id == recovery_market
        assert view.status_text() == "Market inspection ready"
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isEnabled()
        assert not child.isVisible()
        assert presenter._preview_dialogs == set() and presenter._reuse_result_dialogs == set()
        assert service.cancelled == []
        assert not any(
            "execute" in str(call[0]) or "direct_create" in str(call[0])
            for call in service.calls
        )
        app.processEvents()
    finally:
        view.close()


def test_historical_download_validation_recovers_selected_flag_and_rejects_invalid_validation(tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QWidget
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import AuditConfig, load_default_config
    from leonardo.data import canonicalize_market_id
    from leonardo.gui.composition import GuiCompositionRoot
    from leonardo.ohlcv import DownloadProgressEvent
    from tests.gui_test.test_data_manager_catalogs import EXPECTED_FAMILIES
    from tests.gui_test.test_download_maintenance_research_workflow import (
        _UpdatingWorkflowProvider, _prepare_workflow_download, _wait_until,
    )

    qapp = QApplication.instance() or QApplication([])
    runtime = LeonardoApp(replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False)))
    provider = _UpdatingWorkflowProvider()
    runtime.provider_registry.register("workflow", lambda: provider)
    runtime.startup()
    runtime.start_core_runtime()
    composition = GuiCompositionRoot(runtime.context)
    main = composition.create_main_window()
    market_a = canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")
    market_b = canonicalize_market_id("workflow", "linear", "ETHUSDT", "1m")
    try:
        main.action_for_id("main_window.download_data").trigger()
        composition.connection_suite_window.button_for_id(
            "connection_suite.button.view_historical_download_manager"
        ).click()
        for symbol in ("BTCUSDT", "ETHUSDT"):
            download = _prepare_workflow_download(composition, symbol=symbol, start="60000", end="180000")
            download.preflight_window.button_for_id("start_download").click()
            _wait_until(lambda: download.task_window.status_text() == "Completed")
        composition.historical_download_manager_window.button_for_id("ohlcv_maintenance").click()
        maintenance = composition.ohlcv_maintenance_window
        maintenance_presenter = composition.ohlcv_maintenance_presenter
        _wait_until(lambda: maintenance.table_for_id("datasets").rowCount() == 2)
        for row in range(2):
            maintenance.select_dataset_index(row)
            maintenance.button_for_id("validate").click()
            _wait_until(lambda: maintenance_presenter.active_task_id is None)
        assert runtime.ohlcv_store.read_sidecar(market_a).validation_status == "ok"
        assert runtime.ohlcv_store.read_sidecar(market_b).validation_status == "ok"
        main.action_for_id("main_window.open_data_manager_suite").trigger()
        view = composition.data_manager_suite_window
        presenter = composition.data_manager_suite_presenter
        _wait_until(lambda: presenter._initial_warmup_complete)

        def choose(market):
            view.button_for_id("data_manager.button.select_dataset").click()
            selector = view.dataset_selector_dialog()
            _assert_selector_normal(selector)
            row = next(i for i, entry in enumerate(selector._visible_entries)
                       if entry.market_id == market and entry.accepted)
            selector._table.cellWidget(row, 0).findChild(QCheckBox).click()
            assert selector.selected_market_id() == market
            selector.button_for_id("data_manager.dataset_selector.button.select").click()
            return selector

        choose(market_a)
        _wait_until(lambda: presenter._active_task_id is None)
        original = _selected_dataset_values(view)
        original_entry = view._selected_dataset_entry
        surface = view._operation_surface
        normal_palette, normal_font = surface._status.palette(), surface._status.font()
        workspace = view._catalog_workspace
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isEnabled()
        workspace.create_artifact_button.click()
        _wait_until(lambda: presenter._active_task_id is None and view.artifact_creation_dialog() is not None)
        child = view.artifact_creation_dialog()
        presenter._show_reuse_result("Existing result", ("Read-only result",))
        view._show_dataset_selector()
        selector = view.dataset_selector_dialog()
        selector._show_search_help()
        children = [widget for widget in view.findChildren(QWidget) if widget.isWindow() and widget.isVisible()]
        assert selector in children and child in children and len(children) >= 4
        first_page = []
        original_progress = download._on_task_progress

        def observe(progress):
            original_progress(progress)
            event = (progress.details or {}).get("download_event")
            if isinstance(event, DownloadProgressEvent) and event.kind == "page_persisted" and not first_page:
                assert view.dataset_context_suspended
                assert view._selected_market == market_a
                assert view._selected_dataset_entry is original_entry
                assert _selected_dataset_values(view) == original
                _assert_selected_dataset_typography(view, True)
                assert surface._status.palette().color(QPalette.ColorRole.WindowText).name() == "#ff3b4d"
                assert surface._status.font().bold()
                assert "border: 2px solid #FF3B4D" in surface._status.styleSheet()
                assert "border: 2px solid #FF3B4D" in view._selected_dataset_table.styleSheet()
                assert surface._attention_animation.state() == QAbstractAnimation.State.Running
                assert view._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Running
                assert all(not isValid(widget) or not widget.isVisible() for widget in children)
                assert not any(widget.isVisible() for widget in view.findChildren(QWidget) if widget.isWindow())
                assert len(runtime.ohlcv_store.read(market_a)) > 3
                first_page.append(True)

        monkeypatch.setattr(download, "_on_task_progress", observe)
        provider.now_ms = 360_000
        _prepare_workflow_download(composition, symbol="BTCUSDT", limit="1")
        download.preflight_window.button_for_id("start_download").click()
        _wait_until(lambda: download.task_window.status_text() == "Completed")
        assert first_page == [True]
        for family in EXPECTED_FAMILIES:
            workspace.select_family(family)
            if workspace.table.rowCount():
                workspace.table.selectRow(0)
            assert not any(button.isEnabled() for button in workspace.findChildren(QPushButton))
            assert workspace.table.isEnabled() and workspace.inspector_panel().isEnabled()
            assert workspace.history_panel().isEnabled()
        assert view._workspace_tabs.isEnabled()
        for name in ("refresh", "select_dataset"):
            assert view.button_for_id(f"data_manager.button.{name}").isEnabled()
        view.button_for_id("data_manager.button.refresh").click()
        _wait_until(lambda: presenter._background_refresh_task_id is None)
        assert view.dataset_context_suspended and _selected_dataset_values(view) == original
        view._show_dataset_selector()
        assert selector.isVisible()
        _assert_selector_normal(selector)
        selector.close()
        # Hold GUI delivery of real product-scan results: validation itself must
        # recover synchronously before any fresh product scan can settle.
        held_product_results = []
        original_settle = presenter._settle_background_product_scan
        hold_product_results = True

        def settle_product(*args):
            if hold_product_results:
                held_product_results.append(args)
            else:
                original_settle(*args)

        monkeypatch.setattr(presenter, "_settle_background_product_scan", settle_product)
        maintenance.select_dataset_index(0)
        maintenance.button_for_id("validate").click()
        _wait_until(lambda: maintenance_presenter.active_task_id is None)
        assert runtime.ohlcv_store.read_sidecar(market_a).validation_status == "ok"
        assert not view.dataset_context_suspended
        assert view._selected_market == market_a and presenter.selected_market_id == market_a
        assert view._selected_dataset_table.rowCount() == 1
        assert _selected_dataset_values(view) == original
        _assert_selected_dataset_typography(view, False)
        assert surface._attention_animation.state() == QAbstractAnimation.State.Stopped
        assert view._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Stopped
        assert surface._status.palette() == normal_palette and surface._status.font() == normal_font
        assert "#FF3B4D" not in surface._status.styleSheet()
        assert "#FF3B4D" not in view._selected_dataset_table.styleSheet()
        assert "operations restored" in view.status_text()
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isEnabled()
        hold_product_results = False
        for args in held_product_results:
            original_settle(*args)
        _wait_until(lambda: presenter._background_refresh_task_id is None and not view.dataset_context_suspended)
        assert view._selected_market == market_a and presenter.selected_market_id == market_a
        assert "operations restored" in view.status_text()
        assert view._selected_dataset_table.rowCount() == 1
        assert view._selected_dataset_entry is not None
        assert view._selected_dataset_entry.row_count == 5
        _assert_selected_dataset_typography(view, False)
        assert surface._attention_animation.state() == QAbstractAnimation.State.Stopped
        assert view._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Stopped
        assert surface._status.palette() == normal_palette and surface._status.font() == normal_font
        assert "#FF3B4D" not in surface._status.styleSheet()
        assert "#FF3B4D" not in view._selected_dataset_table.styleSheet()
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isEnabled()
        assert all(not isValid(widget) or not widget.isVisible() for widget in children)

        # A second real download persists invalid provider evidence. Validation must
        # leave the flag set; no direct view recovery or synthetic notification is used.
        from leonardo.connection import ProviderCandle
        async def invalid_provider_page(*, start_ms=None, end_ms=None, limit=None, **_kwargs):
            rows = tuple(ProviderCandle(i * 60_000, 1.0, 2.0, 0.5, 1.5, 10.0) for i in range(1, 6))
            rows += (ProviderCandle(360_000, 1.0, 0.25, 0.5, 1.5, 10.0),)
            lower = 0 if start_ms is None else start_ms
            upper = 360_000 if end_ms is None else min(end_ms, 360_000)
            rows = tuple(row for row in rows if lower <= row.ts_ms <= upper)
            return rows[-limit:] if limit else rows
        monkeypatch.setattr(provider, "fetch_ohlcv_historical", invalid_provider_page)
        provider.now_ms = 420_000
        before_second = _selected_dataset_values(view)
        _prepare_workflow_download(composition, symbol="BTCUSDT", limit="1")
        download.preflight_window.button_for_id("start_download").click()
        _wait_until(lambda: download.task_window.status_text() == "Completed")
        assert len(runtime.ohlcv_store.read(market_a)) == 6
        assert view.dataset_context_suspended and _selected_dataset_values(view) == before_second
        maintenance.select_dataset_index(0)
        maintenance.button_for_id("validate").click()
        _wait_until(lambda: maintenance_presenter.active_task_id is None)
        assert runtime.ohlcv_store.read_sidecar(market_a).validation_status != "ok"
        assert view.dataset_context_suspended
        _assert_selected_dataset_typography(view, True)
        assert surface._attention_animation.state() == QAbstractAnimation.State.Running
        assert view._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Running
        assert not any(button.isEnabled() for button in workspace.findChildren(QPushButton))
        maintenance.select_dataset_index(1)
        maintenance.button_for_id("validate").click()
        _wait_until(lambda: maintenance_presenter.active_task_id is None)
        assert runtime.ohlcv_store.read_sidecar(market_b).validation_status == "ok"
        assert view.dataset_context_suspended
        choose(market_b)
        _wait_until(lambda: presenter._active_task_id is None)
        assert not view.dataset_context_suspended
        assert view._selected_market == market_b and presenter.selected_market_id == market_b
        assert _selected_dataset_values(view) != original
        _assert_selected_dataset_typography(view, False)
        assert surface._attention_animation.state() == QAbstractAnimation.State.Stopped
        assert view._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Stopped
        assert surface._status.palette() == normal_palette and surface._status.font() == normal_font
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isEnabled()
        assert all(not isValid(widget) or not widget.isVisible() for widget in children)
        assert view.status_text() == "Market inspection ready"
    finally:
        main.close()
        QCoreApplication.processEvents()
        runtime.shutdown()
        main.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
