from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
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
    windows = (
        connection,
        research,
        data_manager,
        analysis,
        trading,
        manager,
        preflight,
        task,
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
    finally:
        for window in windows:
            window.close()


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
        assert "research_suite.window" in open_ids
        assert "runtime_manager.window" in open_ids
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
