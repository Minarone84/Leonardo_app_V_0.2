import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QWidget,
)

from leonardo.gui.metadata import load_metadata_document  # noqa: E402
from leonardo.gui.windows.historical_download_manager_window import (  # noqa: E402
    HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
    HistoricalDownloadManagerWindow,
)
from leonardo.gui.windows.ohlcv_download_preflight_window import (  # noqa: E402
    OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID,
    OHLCV_PREFLIGHT_COLUMNS,
    OhlcvDownloadPlanRow,
    OhlcvDownloadPreflightWindow,
)
from leonardo.gui.windows.ohlcv_download_task_window import (  # noqa: E402
    OHLCV_DOWNLOAD_TASK_METADATA_ID,
    OhlcvDownloadTaskWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUI_WINDOW_SOURCES = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "historical_download_manager_window.py",
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "ohlcv_download_preflight_window.py",
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "ohlcv_download_task_window.py",
)
_METADATA_SOURCES = {
    HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID: (
        _REPO_ROOT
        / "src"
        / "leonardo"
        / "gui"
        / "metadata"
        / "windows"
        / "historical_download_manager.window.toml"
    ),
    OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID: (
        _REPO_ROOT
        / "src"
        / "leonardo"
        / "gui"
        / "metadata"
        / "windows"
        / "ohlcv_download_preflight.window.toml"
    ),
    OHLCV_DOWNLOAD_TASK_METADATA_ID: (
        _REPO_ROOT
        / "src"
        / "leonardo"
        / "gui"
        / "metadata"
        / "windows"
        / "ohlcv_download_task.window.toml"
    ),
}


@pytest.fixture
def qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_historical_download_manager_has_expected_fields_and_buttons(
    qapplication: QApplication,
) -> None:
    window = HistoricalDownloadManagerWindow()

    try:
        assert isinstance(window, QWidget)
        assert window.objectName() == "historical_download_manager_window"
        assert window.windowTitle() == "Historical Download Manager"
        assert isinstance(window.field_widget_for_id("exchange"), QComboBox)
        assert isinstance(window.field_widget_for_id("market_type"), QComboBox)
        assert isinstance(window.field_widget_for_id("symbol"), QLineEdit)
        assert isinstance(window.field_widget_for_id("start_ms"), QLineEdit)
        assert isinstance(window.field_widget_for_id("end_ms"), QLineEdit)
        assert isinstance(window.field_widget_for_id("limit"), QLineEdit)
        assert window.field_widget_for_id("limit").text() == "200"
        assert isinstance(window.button_for_id("select_all_timeframes"), QPushButton)
        assert window.button_for_id("select_all_timeframes").text() == "Select All Timeframes"
        assert isinstance(window.button_for_id("clear_timeframes"), QPushButton)
        assert window.button_for_id("clear_timeframes").text() == (
            "Clear/Deselect All Timeframes"
        )
        assert isinstance(window.button_for_id("start"), QPushButton)
        assert isinstance(window.button_for_id("stop"), QPushButton)
        assert window.button_for_id("stop").isEnabled() is False
        assert isinstance(window.button_for_id("ohlcv_maintenance"), QPushButton)
        assert isinstance(window.status_log(), QTextEdit)
        assert window.status_log().isReadOnly() is True
    finally:
        _dispose(qapplication, window)


def test_historical_download_manager_timeframes_are_supplied_externally(
    qapplication: QApplication,
) -> None:
    window = HistoricalDownloadManagerWindow()

    try:
        assert window.available_timeframes() == ()

        window.set_available_timeframes(["1m", "5m", "1h"])

        assert window.available_timeframes() == ("1m", "5m", "1h")
        assert isinstance(window.timeframe_checkbox_for_value("1m"), QCheckBox)
        window.button_for_id("select_all_timeframes").click()
        assert window.selected_timeframes() == ("1m", "5m", "1h")

        window.button_for_id("clear_timeframes").click()
        assert window.selected_timeframes() == ()
    finally:
        _dispose(qapplication, window)


def test_historical_download_manager_empty_timeframes_invents_none(
    qapplication: QApplication,
) -> None:
    window = HistoricalDownloadManagerWindow()

    try:
        window.set_available_timeframes([])

        assert window.available_timeframes() == ()
        assert window.selected_timeframes() == ()
    finally:
        _dispose(qapplication, window)


def test_historical_download_manager_deduplicates_supplied_timeframes(
    qapplication: QApplication,
) -> None:
    window = HistoricalDownloadManagerWindow()

    try:
        window.set_available_timeframes(["1m", "5m", "1m", "1h", "5m"])

        assert window.available_timeframes() == ("1m", "5m", "1h")
        window.button_for_id("select_all_timeframes").click()
        assert window.selected_timeframes() == ("1m", "5m", "1h")

        window.button_for_id("clear_timeframes").click()
        assert window.selected_timeframes() == ()
    finally:
        _dispose(qapplication, window)


def test_historical_download_manager_buttons_emit_local_signals_only(
    qapplication: QApplication,
) -> None:
    window = HistoricalDownloadManagerWindow()
    signals: list[str] = []

    try:
        window.start_requested.connect(lambda: signals.append("start"))
        window.maintenance_requested.connect(lambda: signals.append("maintenance"))

        window.button_for_id("start").click()
        window.button_for_id("ohlcv_maintenance").click()

        assert signals == ["start", "maintenance"]
    finally:
        _dispose(qapplication, window)


def test_ohlcv_download_preflight_is_standalone_table_dialog(
    qapplication: QApplication,
) -> None:
    window = OhlcvDownloadPreflightWindow()

    try:
        assert isinstance(window, QDialog)
        assert window.windowTitle() == "Confirm OHLCV Download"
        assert bool(window.windowFlags() & Qt.WindowType.Window)
        assert isinstance(window.table(), QTableWidget)
        assert window.table().columnCount() == len(OHLCV_PREFLIGHT_COLUMNS)
        assert _horizontal_header_labels(window.table()) == OHLCV_PREFLIGHT_COLUMNS
        assert isinstance(window.button_for_id("cancel"), QPushButton)
        assert isinstance(window.button_for_id("start_download"), QPushButton)
    finally:
        _dispose(qapplication, window)


def test_ohlcv_download_preflight_displays_file_state_and_mode(
    qapplication: QApplication,
) -> None:
    window = OhlcvDownloadPreflightWindow()
    signals: list[str] = []

    try:
        window.start_download_requested.connect(lambda: signals.append("start"))
        window.set_work_plan(
            [
                OhlcvDownloadPlanRow(
                    timeframe="1m",
                    local_file_exists=False,
                    update_existing=False,
                    local_rows=0,
                    local_range="-",
                    planned_range="1000-2000",
                    expected_bars=100,
                    pages=1,
                    page_limit=200,
                    status="Ready",
                ),
                {
                    "timeframe": "5m",
                    "local_file_exists": True,
                    "update_existing": True,
                    "local_rows": 240,
                    "local_range": "1000-1600",
                    "planned_range": "1600-2200",
                    "expected_bars": 120,
                    "pages": 1,
                    "page_limit": 200,
                    "status": "Update planned",
                },
            ]
        )

        assert window.table().rowCount() == 2
        assert window.table().item(0, 0).text() == "1m"
        assert window.table().item(0, 1).text() == "Missing local file"
        assert window.table().item(0, 2).text() == "New download"
        assert window.table().item(1, 0).text() == "5m"
        assert window.table().item(1, 1).text() == "Existing local file"
        assert window.table().item(1, 2).text() == "Update existing"

        window.button_for_id("start_download").click()
        assert signals == ["start"]
    finally:
        _dispose(qapplication, window)


def test_ohlcv_download_task_is_standalone_progress_dialog(
    qapplication: QApplication,
) -> None:
    window = OhlcvDownloadTaskWindow()

    try:
        assert isinstance(window, QDialog)
        assert window.windowTitle() == "OHLCV Download Task"
        assert bool(window.windowFlags() & Qt.WindowType.Window)
        assert isinstance(window.overall_progress_bar(), QProgressBar)
        assert isinstance(window.current_timeframe_progress_bar(), QProgressBar)
        assert isinstance(window.progress_log(), QTextEdit)
        assert window.progress_log().isReadOnly() is True
        assert isinstance(window.final_recap(), QTextEdit)
        assert window.final_recap().isReadOnly() is True
        assert isinstance(window.button_for_id("stop"), QPushButton)
        assert window.button_for_id("stop").isEnabled() is False
        assert isinstance(window.button_for_id("ok"), QPushButton)
    finally:
        _dispose(qapplication, window)


def test_ohlcv_download_task_displays_external_progress_and_recap(
    qapplication: QApplication,
) -> None:
    window = OhlcvDownloadTaskWindow()

    try:
        window.set_job_summary(
            exchange="Bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframes=("1m", "5m"),
        )
        window.set_overall_progress(40)
        window.set_current_timeframe_progress(120)
        window.append_log_message("Prepared 1m")
        window.set_final_recap("Downloaded 2 timeframes")

        assert window.summary_text_for_id("exchange") == "Bybit"
        assert window.summary_text_for_id("market_type") == "linear"
        assert window.summary_text_for_id("symbol") == "BTCUSDT"
        assert window.summary_text_for_id("timeframes") == "1m, 5m"
        assert window.overall_progress_bar().value() == 40
        assert window.current_timeframe_progress_bar().value() == 100
        assert "Prepared 1m" in window.progress_log().toPlainText()
        assert window.final_recap().toPlainText() == "Downloaded 2 timeframes"
    finally:
        _dispose(qapplication, window)


@pytest.mark.parametrize(
    ("metadata_id", "title", "object_name"),
    (
        (
            HISTORICAL_DOWNLOAD_MANAGER_METADATA_ID,
            "Historical Download Manager",
            "historical_download_manager_window",
        ),
        (
            OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID,
            "Confirm OHLCV Download",
            "ohlcv_download_preflight_window",
        ),
        (
            OHLCV_DOWNLOAD_TASK_METADATA_ID,
            "OHLCV Download Task",
            "ohlcv_download_task_window",
        ),
    ),
)
def test_connection_download_manager_shell_metadata_is_gui_owned(
    metadata_id: str,
    title: str,
    object_name: str,
) -> None:
    result = load_metadata_document(_METADATA_SOURCES[metadata_id])

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == metadata_id
    assert result.document.title == title
    assert result.document.metadata["owner_area"] == "gui"
    assert result.document.metadata["target_area_id"] == "connection"
    assert result.document.metadata["target_suite_id"] == "connection_suite"
    assert result.document.metadata["target_module_id"] == "connection.download_manager"
    assert result.document.metadata["object_name"] == object_name
    assert "owner_suite_id" not in result.document.metadata

    guarantees = result.document.metadata["boundary_guarantees"]
    assert guarantees["gui_presentation_only"] is True
    assert guarantees["domain_workflow_not_owned_by_gui"] is True
    assert guarantees["no_backend_execution"] is True
    assert guarantees["no_provider_api_call"] is True
    assert guarantees["no_storage_write"] is True
    assert guarantees["no_runtime_manager_control"] is True
    assert guarantees["no_object_map_mutation"] is True
    assert {setting.path for setting in result.document.settings} == {
        "style.font_size",
        "style.density",
        "geometry.width",
        "geometry.height",
    }


def test_preflight_metadata_describes_table_like_work_plan() -> None:
    result = load_metadata_document(_METADATA_SOURCES[OHLCV_DOWNLOAD_PREFLIGHT_METADATA_ID])

    assert result.report.has_errors is False
    assert result.document is not None
    assert tuple(table.table_id for table in result.document.tables) == (
        "ohlcv_download_preflight.work_plan_table",
    )
    assert tuple(column.label for column in result.document.tables[0].columns) == (
        "Timeframe",
        "Local File",
        "Mode",
        "Local Rows",
        "Local Range",
        "Planned Range",
        "Expected Bars",
        "Pages",
        "Page Limit",
        "Status",
    )


def test_connection_download_manager_gui_shells_have_no_backend_imports_or_io_calls() -> None:
    forbidden_tokens = (
        "leonardo.download_data",
        "BybitTransport",
        "bybit_transport",
        "storage_writer",
        "DownloadExecutionManager",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "socket.",
        "subprocess",
        "shell=True",
        "open(",
        ".write(",
        "Path(",
    )

    for source_path in _GUI_WINDOW_SOURCES:
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{source_path} contains forbidden token {token!r}"


def _horizontal_header_labels(table: QTableWidget) -> tuple[str, ...]:
    return tuple(
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    )


def _dispose(qapplication: QApplication, *widgets: QWidget) -> None:
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    qapplication.processEvents()
