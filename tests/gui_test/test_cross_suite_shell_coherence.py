from __future__ import annotations

from collections.abc import Callable
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.gui.windows.analysis_suite_window import (  # noqa: E402
    ANALYSIS_SUITE_METADATA_ID,
    AnalysisSuiteWindow,
)
from leonardo.gui.windows.connection_suite_window import (  # noqa: E402
    CONNECTION_SUITE_METADATA_ID,
    ConnectionSuiteWindow,
)
from leonardo.gui.windows.data_manager_suite_window import (  # noqa: E402
    DATA_MANAGER_SUITE_METADATA_ID,
    DataManagerSuiteWindow,
)
from leonardo.gui.windows.historical_download_manager_window import (  # noqa: E402
    HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
    HistoricalDownloadManagerWindow,
)
from leonardo.gui.windows.ohlcv_download_preflight_window import (  # noqa: E402
    OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID,
    OhlcvDownloadPreflightWindow,
)
from leonardo.gui.windows.ohlcv_download_task_window import (  # noqa: E402
    OHLCV_DOWNLOAD_TASK_METADATA_ID,
    OhlcvDownloadTaskWindow,
)
from leonardo.gui.windows.research_suite_window import (  # noqa: E402
    RESEARCH_SUITE_METADATA_ID,
    ResearchSuiteWindow,
)
from leonardo.gui.windows.trading_suite_window import (  # noqa: E402
    TRADING_SUITE_METADATA_ID,
    TradingSuiteWindow,
)


_ShellFactory = Callable[[], QWidget]
_ACTIVE_SHELL_WINDOWS: tuple[tuple[_ShellFactory, str, str], ...] = (
    (ConnectionSuiteWindow, CONNECTION_SUITE_METADATA_ID, "connection_suite_window"),
    (
        HistoricalDownloadManagerWindow,
        HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
        "historical_download_manager_window",
    ),
    (
        OhlcvDownloadPreflightWindow,
        OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID,
        "ohlcv_download_preflight_window",
    ),
    (
        OhlcvDownloadTaskWindow,
        OHLCV_DOWNLOAD_TASK_METADATA_ID,
        "ohlcv_download_task_window",
    ),
    (ResearchSuiteWindow, RESEARCH_SUITE_METADATA_ID, "research_suite_window"),
    (
        DataManagerSuiteWindow,
        DATA_MANAGER_SUITE_METADATA_ID,
        "data_manager_suite_window",
    ),
    (AnalysisSuiteWindow, ANALYSIS_SUITE_METADATA_ID, "analysis_suite_window"),
    (TradingSuiteWindow, TRADING_SUITE_METADATA_ID, "trading_suite_window"),
)


@pytest.mark.parametrize(
    ("factory", "metadata_id", "object_name"),
    _ACTIVE_SHELL_WINDOWS,
)
def test_active_shell_windows_share_theme_and_top_level_trace(
    factory: _ShellFactory,
    metadata_id: str,
    object_name: str,
) -> None:
    qapplication = _qapplication()
    window = factory()

    try:
        assert window.objectName() == object_name
        assert window.property("object_id") == metadata_id
        assert "QWidget" in window.styleSheet()
        assert "QPushButton" in window.styleSheet()
        assert "QTableWidget" in window.styleSheet()
    finally:
        _dispose(qapplication, window)


@pytest.mark.parametrize(
    ("factory", "status_accessor"),
    (
        (ConnectionSuiteWindow, lambda window: window.status_text()),
        (
            HistoricalDownloadManagerWindow,
            lambda window: window.status_log().toPlainText(),
        ),
        (OhlcvDownloadPreflightWindow, lambda window: window.status_text()),
        (OhlcvDownloadTaskWindow, lambda window: window.status_text()),
        (ResearchSuiteWindow, lambda window: window.status_text()),
        (DataManagerSuiteWindow, lambda window: window.status_text()),
        (AnalysisSuiteWindow, lambda window: window.status_text()),
        (TradingSuiteWindow, lambda window: window.status_text()),
    ),
)
def test_active_shell_windows_render_dummy_boundary_status(
    factory: _ShellFactory,
    status_accessor: Callable[[object], str],
) -> None:
    qapplication = _qapplication()
    window = factory()

    try:
        status_text = status_accessor(window)

        assert "dummy" in status_text.lower()
    finally:
        _dispose(qapplication, window)


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _dispose(qapplication: QApplication, *widgets: QWidget) -> None:
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    qapplication.processEvents()
