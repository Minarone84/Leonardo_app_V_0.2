import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from leonardo.core.app import LeonardoApp  # noqa: E402
from leonardo.gui.composition import (  # noqa: E402
    GuiCompositionRoot,
    create_main_window_for_context,
)
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow  # noqa: E402
from leonardo.gui.windows.connection_suite_window import ConnectionSuiteWindow  # noqa: E402
from leonardo.gui.windows.data_manager_suite_window import (  # noqa: E402
    DataManagerSuiteWindow,
)
from leonardo.gui.windows.historical_download_manager_window import (  # noqa: E402
    HistoricalDownloadManagerWindow,
)
from leonardo.gui.windows.main_window import LeonardoMainWindow  # noqa: E402
from leonardo.gui.windows.research_suite_window import ResearchSuiteWindow  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402
from leonardo.gui.windows.trading_suite_window import TradingSuiteWindow  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSITION_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "composition.py"
_OLD_GUI_FILES = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "download_request_builder_window.py",
    _REPO_ROOT / "src" / "leonardo" / "gui" / "download_request_mapper.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "download_request_builder.window.toml",
)


def test_composition_creates_main_window_from_context_without_startup(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    app_instance = QApplication.instance()
    root = GuiCompositionRoot(app.context)

    window = root.create_main_window()

    assert isinstance(window, LeonardoMainWindow)
    assert QApplication.instance() is app_instance
    assert root.tracker_for("main_window.window") is not None
    assert root.connection_suite_window is None
    assert window.runtime_manager_window is None
    assert root.historical_download_manager_window is None
    assert root.research_suite_window is None
    assert root.data_manager_suite_window is None
    assert root.analysis_suite_window is None
    assert root.trading_suite_window is None

    _dispose(qapplication, window)
    app.shutdown()


def test_function_helper_uses_gui_composition_root(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()

    window = create_main_window_for_context(app.context)

    assert isinstance(window, LeonardoMainWindow)
    assert window.runtime_manager_window is None

    _dispose(qapplication, window)
    app.shutdown()


def test_runtime_manager_factory_is_injected_and_uses_snapshot_provider_lazily(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert root.tracker_for("runtime_manager.window") is not None

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert runtime_window.last_rendered_snapshot_summary["status"] == "rendered"

    _dispose(qapplication, window, runtime_window)
    app.shutdown()


def test_download_data_menu_opens_gui_only_connection_suite_shell(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context)
    window = root.create_main_window()
    before_events = app.audit_log.snapshot()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    shell = root.connection_suite_window

    assert isinstance(shell, ConnectionSuiteWindow)
    assert shell.isVisible() is True
    assert shell.table_for_id("connection_suite.table.provider_status_dummy").rowCount() == 5
    assert root.tracker_for("connection_suite.home.window") is not None
    assert (
        app.window_registry.get_window_definition("connection_suite.home.window")
        is not None
    )
    assert "connection_suite.home.window" in _open_window_ids(app)
    assert window.statusBar().currentMessage() == "Connection Suite shell opened."
    assert _download_event_types(app.audit_log.snapshot()) == _download_event_types(
        before_events
    )

    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    qapplication.processEvents()
    historical_shell = root.historical_download_manager_window

    assert isinstance(historical_shell, HistoricalDownloadManagerWindow)
    assert historical_shell.isVisible() is True
    assert window.statusBar().currentMessage() == (
        "Historical Download Manager shell opened."
    )
    assert _download_event_types(app.audit_log.snapshot()) == _download_event_types(
        before_events
    )

    shell.close()
    historical_shell.close()
    qapplication.processEvents()

    assert "connection_suite.home.window" not in _open_window_ids(app)
    assert "historical_download_manager.window" not in _open_window_ids(app)

    _dispose(qapplication, window, shell, historical_shell)
    app.shutdown()


def test_main_window_suite_actions_open_gui_only_dummy_shells(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context)
    window = root.create_main_window()
    before_events = app.audit_log.snapshot()

    for action_id, attr_name, window_type, message, tracker_id in (
        (
            "main_window.download_data",
            "connection_suite_window",
            ConnectionSuiteWindow,
            "Connection Suite shell opened.",
            "connection_suite.home.window",
        ),
        (
            "main_window.open_research_suite",
            "research_suite_window",
            ResearchSuiteWindow,
            "Research Suite shell opened.",
            "research_suite.window",
        ),
        (
            "main_window.open_data_manager_suite",
            "data_manager_suite_window",
            DataManagerSuiteWindow,
            "Data Manager Suite shell opened.",
            "data_manager_suite.window",
        ),
        (
            "main_window.open_analysis_suite",
            "analysis_suite_window",
            AnalysisSuiteWindow,
            "Analysis Suite shell opened.",
            "analysis_suite.window",
        ),
        (
            "main_window.open_trading_suite",
            "trading_suite_window",
            TradingSuiteWindow,
            "Trading Suite shell opened.",
            "trading_suite.window",
        ),
    ):
        window.action_for_id(action_id).trigger()
        qapplication.processEvents()
        shell = getattr(root, attr_name)

        assert isinstance(shell, window_type)
        assert shell.isVisible() is True
        assert root.tracker_for(tracker_id) is not None
        assert app.window_registry.get_window_definition(tracker_id) is not None
        assert tracker_id in _open_window_ids(app)
        assert window.statusBar().currentMessage() == message

    assert _download_event_types(app.audit_log.snapshot()) == _download_event_types(
        before_events
    )

    _dispose(
        qapplication,
        window,
        root.connection_suite_window,
        root.research_suite_window,
        root.data_manager_suite_window,
        root.analysis_suite_window,
        root.trading_suite_window,
    )
    app.shutdown()


def test_closing_main_window_releases_suite_shells_and_registry_state(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context)
    window = root.create_main_window()

    window.show()
    for action_id in (
        "main_window.download_data",
        "main_window.open_research_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_analysis_suite",
        "main_window.open_trading_suite",
    ):
        window.action_for_id(action_id).trigger()
        qapplication.processEvents()

    suite_window_ids = (
        "research_suite.window",
        "data_manager_suite.window",
        "analysis_suite.window",
        "trading_suite.window",
        "connection_suite.home.window",
    )
    assert set(suite_window_ids) <= set(_open_window_ids(app))
    assert root.connection_suite_window is not None
    assert root.research_suite_window is not None
    assert root.data_manager_suite_window is not None
    assert root.analysis_suite_window is not None
    assert root.trading_suite_window is not None

    window.close()
    qapplication.processEvents()

    assert root.connection_suite_window is None
    assert root.research_suite_window is None
    assert root.data_manager_suite_window is None
    assert root.analysis_suite_window is None
    assert root.trading_suite_window is None
    assert not set(suite_window_ids) & set(_open_window_ids(app))
    for window_id in suite_window_ids:
        tracker = root.tracker_for(window_id)
        assert tracker is not None
        assert tracker.is_open is False

    _dispose(qapplication, window)
    app.shutdown()


def test_composition_can_disable_window_tracking(qapplication: QApplication) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)

    window = root.create_main_window()
    window.show()
    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()

    assert root.window_trackers == {}
    assert root.connection_suite_window is not None
    assert root.connection_suite_window.isVisible() is True
    assert app.window_registry.open_windows() == ()

    _dispose(qapplication, window, root.connection_suite_window)
    app.shutdown()


def test_composition_source_does_not_construct_app_or_qapplication() -> None:
    source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")

    assert "LeonardoApp" not in source
    assert "QApplication" not in source
    assert ".startup(" not in source
    assert ".shutdown(" not in source


def test_composition_source_has_no_download_backend_execution_path() -> None:
    source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "download_request_builder",
        "DownloadRequestBuilderWindow",
        "download_request_mapper",
        "DownloadRequest(",
        "leonardo.contracts.downloads",
        "core.download_manager",
        "DownloadManager(",
        "DownloadExecutionManager",
        "leonardo.download_data",
        ".submit_request(",
        ".create_plan(",
        ".classify_readiness(",
        "run_sandbox_smoke",
        "run_bybit_ohlcv_smoke_slice",
        ".write(",
    )

    for token in blocked_tokens:
        assert token not in source


def test_old_download_request_builder_files_are_not_active_gui_files() -> None:
    for path in _OLD_GUI_FILES:
        assert not path.exists(), f"Legacy GUI file still exists: {path}"


def test_composed_windows_destroy_cleanly(qapplication: QApplication) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context)
    window = root.create_main_window()

    window.show()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    window.action_for_id("main_window.download_data").trigger()
    window.action_for_id("main_window.open_research_suite").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert runtime_window is not None
    assert root.connection_suite_window is not None
    assert window.runtime_manager_window is not None
    assert window.isVisible() is True
    window.close()
    _dispose(qapplication, window, runtime_window, root.connection_suite_window)
    app.shutdown()

    assert window.close_requested_locally is True


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()


def _download_event_types(events: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(
        event.event_type
        for event in events
        if getattr(event, "event_type", "").startswith("download.")
    )


def _open_window_ids(app: LeonardoApp) -> tuple[str, ...]:
    return tuple(state.window_id for state in app.window_registry.open_windows())


def _dispose(qapplication: QApplication, *widgets: object) -> None:
    for widget in widgets:
        if widget is not None:
            widget.close()
            widget.deleteLater()
    qapplication.processEvents()
