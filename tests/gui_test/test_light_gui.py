from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.window_tracking import GuiWindowTracker
from leonardo.gui.windows import (
    AnalysisSuiteWindow,
    ConnectionSuiteWindow,
    DataManagerSuiteWindow,
    HistoricalDownloadManagerWindow,
    LeonardoMainWindow,
    OhlcvDownloadPreflightWindow,
    OhlcvDownloadTaskWindow,
    OhlcvMaintenanceWindow,
    ResearchSuiteWindow,
    RuntimeManagerWindow,
    TradingSuiteWindow,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _config(tmp_path: Path):
    config = load_default_config(tmp_path)
    return replace(config, audit=AuditConfig(enabled=False))


def test_shell_windows_construct_in_honest_empty_state(qapp: QApplication) -> None:
    connection = ConnectionSuiteWindow()
    research = ResearchSuiteWindow()
    data_manager = DataManagerSuiteWindow()
    analysis = AnalysisSuiteWindow()
    trading = TradingSuiteWindow()
    manager = HistoricalDownloadManagerWindow()
    preflight = OhlcvDownloadPreflightWindow()
    task = OhlcvDownloadTaskWindow()
    maintenance = OhlcvMaintenanceWindow()
    windows = (
        connection,
        research,
        data_manager,
        analysis,
        trading,
        manager,
        preflight,
        task,
        maintenance,
    )
    try:
        for window in windows:
            assert window.objectName()
            visible_text = " ".join(
                child.text()
                for child in window.findChildren(QWidget)
                if callable(getattr(child, "text", None))
            ).lower()
            assert "dummy" not in visible_text

        assert connection.status_text() == "Connection services are not configured"
        assert manager.status_log().toPlainText() == ""
        assert preflight.status_text() == "No request loaded"
        assert task.status_text() == "No task running"
        assert maintenance.status_text() == "Ready"
    finally:
        for window in windows:
            window.close()


def test_preflight_accepts_presenter_tuple_rows(qapp: QApplication) -> None:
    preflight = OhlcvDownloadPreflightWindow()
    try:
        preflight.set_request_summary((("Exchange", "bybit", "selected"),))
        preflight.set_validation_checklist((("1m", "ready", "No blockers"),))
        preflight.set_workload_estimate(
            (("Expected pages", 1, "Provider page limits applied"),)
        )

        request_table = preflight.table_for_id(
            "ohlcv_download_preflight.request_summary_table"
        )
        validation_table = preflight.table_for_id(
            "ohlcv_download_preflight.validation_checklist_table"
        )
        workload_table = preflight.table_for_id(
            "ohlcv_download_preflight.workload_estimate_table"
        )

        assert request_table.item(0, 0).text() == "Exchange"
        assert request_table.item(0, 1).text() == "bybit"
        assert request_table.item(0, 2).text() == "selected"
        assert validation_table.item(0, 0).text() == "1m"
        assert validation_table.item(0, 1).text() == "ready"
        assert workload_table.item(0, 0).text() == "Expected pages"
        assert workload_table.item(0, 1).text() == "1"
    finally:
        preflight.close()


def test_composition_opens_and_tracks_windows(qapp: QApplication, tmp_path: Path) -> None:
    app = LeonardoApp(_config(tmp_path))
    app.startup()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    try:
        main.show()
        QCoreApplication.processEvents()
        main.action_for_id("main_window.download_data").trigger()
        QCoreApplication.processEvents()
        assert composition.connection_suite_window is not None
        assert composition.connection_suite_window.isVisible()

        main.action_for_id("main_window.ohlcv_maintenance").trigger()
        QCoreApplication.processEvents()
        assert composition.ohlcv_maintenance_window is not None
        assert composition.ohlcv_maintenance_window.isVisible()

        main.action_for_id("main_window.open_research_suite").trigger()
        QCoreApplication.processEvents()
        assert composition.research_suite_window is not None
        assert composition.research_suite_window.isVisible()

        main.action_for_id("main_window.open_runtime_manager").trigger()
        QCoreApplication.processEvents()
        assert main.runtime_manager_window is not None
        assert main.runtime_manager_window.isVisible()

        open_ids = {item.window_id for item in app.window_registry.open_windows()}
        assert "main_window.window" in open_ids
        assert "connection_suite.home.window" in open_ids
        assert "ohlcv_maintenance.window" in open_ids
        assert "research_suite.window" in open_ids
        assert "runtime_manager.window" in open_ids
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_composition_routes_ohlcv_change_only_to_existing_data_manager(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    app = LeonardoApp(_config(tmp_path))
    app.startup()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    received = []
    try:
        main.action_for_id("main_window.ohlcv_maintenance").trigger()
        QCoreApplication.processEvents()
        maintenance = composition.ohlcv_maintenance_presenter
        assert maintenance is not None
        callback = maintenance._on_canonical_ohlcv_evidence_changed
        assert callback is not None

        callback(market)
        assert composition.data_manager_suite_presenter is None

        data_manager = SimpleNamespace(
            is_disposed=False,
            notify_external_ohlcv_change=received.append,
        )
        composition._data_manager_suite_presenter = data_manager
        callback(market)
        assert received == [market]

        data_manager.is_disposed = True
        callback(market)
        assert received == [market]
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_runtime_manager_renders_direct_snapshot(qapp: QApplication, tmp_path: Path) -> None:
    app = LeonardoApp(_config(tmp_path))
    app.startup()
    app.window_registry.register_window("main.window", title="Leonardo")
    app.window_registry.open_window("main.window")
    window = RuntimeManagerWindow(snapshot_provider=app.runtime_manager.snapshot)
    try:
        snapshot = window.refresh_snapshot()
        assert snapshot is not None
        assert "app=running" in window.last_rendered_snapshot_summary
        assert set(window.table_ids()) == {
            "runtime_manager.table.tasks",
            "runtime_manager.table.processes",
            "runtime_manager.table.connections",
            "runtime_manager.table.windows",
            "runtime_manager.table.actions",
            "runtime_manager.table.audit",
        }
    finally:
        window.close()
        app.shutdown()


def test_window_tracker_updates_canonical_registry(qapp: QApplication) -> None:
    from leonardo.core.window_registry import WindowRegistry

    registry = WindowRegistry()
    window = QWidget()
    tracker = GuiWindowTracker(
        window,
        window_id="test.window",
        title="Test",
        window_type="test",
        registry=registry,
    )
    assert tracker.window_id == "test.window"
    window.show()
    QCoreApplication.processEvents()
    assert registry.open_windows()[0].window_id == "test.window"
    window.close()
    QCoreApplication.processEvents()
    assert registry.open_windows() == ()


def test_theme_loads_and_applies(qapp: QApplication) -> None:
    theme = load_default_theme()
    assert theme.identity.theme_id == "leonardo_jarvish_cockpit"
    apply_theme_stylesheet(qapp, theme)
    assert qapp.styleSheet()


@pytest.mark.parametrize(
    ("result", "changed", "expected_calls", "expected_status"),
    (
        (QDialog.DialogCode.Rejected, False, 0, "Settings cancelled."),
        (QDialog.DialogCode.Accepted, False, 0, "Settings unchanged."),
        (QDialog.DialogCode.Accepted, True, 1, "Display time zone updated."),
    ),
)
def test_settings_action_uses_injected_dialog_and_exact_change_callback(
    qapp: QApplication,
    result: QDialog.DialogCode,
    changed: bool,
    expected_calls: int,
    expected_status: str,
) -> None:
    created: list[QDialog] = []
    callbacks: list[bool] = []

    class InjectedSettingsDialog(QDialog):
        @property
        def display_time_zone_changed(self) -> bool:
            return changed

        def exec(self) -> int:
            return int(result)

    def factory(parent: QWidget) -> InjectedSettingsDialog:
        dialog = InjectedSettingsDialog(parent)
        created.append(dialog)
        return dialog

    window = LeonardoMainWindow(
        settings_dialog_factory=factory,
        on_display_time_zone_changed=lambda: callbacks.append(True),
    )
    try:
        window.action_for_id("main_window.open_settings_inspector").trigger()
        assert len(created) == 1
        assert callbacks == [True] * expected_calls
        assert window.statusBar().currentMessage() == expected_status
    finally:
        window.close()


def test_settings_dependencies_require_callables(qapp: QApplication) -> None:
    with pytest.raises(TypeError, match="settings_dialog_factory must be callable"):
        LeonardoMainWindow(settings_dialog_factory=object())
    with pytest.raises(
        TypeError, match="on_display_time_zone_changed must be callable"
    ):
        LeonardoMainWindow(on_display_time_zone_changed=object())


def test_composition_display_time_change_refreshes_only_live_data_manager(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    app = LeonardoApp(_config(tmp_path))
    composition = GuiCompositionRoot(app.context)
    composition._on_display_time_zone_changed()

    refreshes: list[bool] = []
    composition._data_manager_suite_presenter = SimpleNamespace(
        is_disposed=False,
        refresh=lambda: refreshes.append(True),
    )
    composition._on_display_time_zone_changed()
    assert refreshes == [True]

    composition._data_manager_suite_presenter.is_disposed = True
    composition._on_display_time_zone_changed()
    assert refreshes == [True]
