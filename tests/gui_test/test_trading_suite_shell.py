import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QWidget  # noqa: E402

from leonardo.gui.metadata import load_metadata_document  # noqa: E402
from leonardo.gui.windows.trading_suite_window import (  # noqa: E402
    TRADING_SUITE_METADATA_ID,
    TradingSuiteWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRADING_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "trading_suite.window.toml"
)
_SHELL_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "trading_suite_window.py"
)
_DUMMY_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "dummy_data.py"


def test_trading_suite_shell_renders_dummy_trading_surfaces() -> None:
    qapplication = _qapplication()
    window = TradingSuiteWindow()

    try:
        assert isinstance(window, QWidget)
        assert window.objectName() == "trading_suite_window"
        assert window.property("object_id") == TRADING_SUITE_METADATA_ID
        assert "QPushButton" in window.styleSheet()
        assert "DUMMY trading shell loaded" in window.status_text()

        expected_rows = {
            "trading_suite.table.overview_dummy": 3,
            "trading_suite.table.account_risk_dummy": 2,
            "trading_suite.table.broker_account_dummy": 3,
            "trading_suite.table.risk_summary_dummy": 3,
            "trading_suite.table.order_position_dummy": 2,
            "trading_suite.table.strategy_status_dummy": 3,
            "trading_suite.table.execution_controls_dummy": 3,
        }
        for table_id, row_count in expected_rows.items():
            table = window.table_for_id(table_id)
            assert isinstance(table, QTableWidget)
            assert table.rowCount() == row_count

        assert window.table_for_id("trading_suite.table.overview_dummy").item(2, 1).text() == (
            "locked"
        )
        assert window.table_for_id("trading_suite.table.broker_account_dummy").item(0, 1).text() == (
            "disconnected"
        )
        assert window.table_for_id(
            "trading_suite.table.execution_controls_dummy"
        ).item(2, 1).text() == "forbidden"

        for button_id in (
            "trading_suite.button.load_dummy_trading_state",
            "trading_suite.button.preview_paper_shell",
            "trading_suite.button.kill_switch_visual",
        ):
            button = window.button_for_id(button_id)
            assert isinstance(button, QPushButton)
            assert "Place Order" not in button.text()
            assert "Cancel Order" not in button.text()
    finally:
        _dispose(qapplication, window)


def test_trading_suite_shell_actions_are_local_and_dummy_only() -> None:
    qapplication = _qapplication()
    observer = _RecordingObserver()
    window = TradingSuiteWindow(action_observer=observer)

    try:
        window.button_for_id("trading_suite.button.preview_paper_shell").click()
        window.button_for_id("trading_suite.button.kill_switch_visual").click()

        assert observer.calls == [
            ("trading_suite.action.preview_paper_shell", TRADING_SUITE_METADATA_ID),
            ("trading_suite.action.kill_switch_placeholder", TRADING_SUITE_METADATA_ID),
        ]
        assert "GUI shell-only dummy behavior" in window.status_text()
        assert "no broker, order, or trading behavior ran" in window.status_log_text()
    finally:
        _dispose(qapplication, window)


def test_trading_suite_metadata_is_gui_owned_and_dummy_only() -> None:
    result = load_metadata_document(_TRADING_METADATA_PATH)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == TRADING_SUITE_METADATA_ID
    assert result.document.metadata["owner_area"] == "gui"
    assert result.document.metadata["target_area_id"] == "trading"
    assert result.document.metadata["status"] == "shell_only"
    assert result.document.metadata["dummy_data_status"] == "local_in_memory_gui_dummy_only"

    table_ids = {table.table_id for table in result.document.tables}
    assert {
        "trading_suite.table.overview_dummy",
        "trading_suite.table.account_risk_dummy",
        "trading_suite.table.broker_account_dummy",
        "trading_suite.table.risk_summary_dummy",
        "trading_suite.table.order_position_dummy",
        "trading_suite.table.strategy_status_dummy",
        "trading_suite.table.execution_controls_dummy",
    } <= table_ids

    widget_ids = {widget.widget_id for widget in result.document.widgets}
    assert {
        "trading_suite.panel.overview",
        "trading_suite.label.boundary_notice",
        "trading_suite.button.load_dummy_trading_state",
        "trading_suite.button.preview_paper_shell",
        "trading_suite.button.kill_switch_visual",
        "trading_suite.panel.kill_switch_visual_placeholder",
    } <= widget_ids

    guarantees = result.document.metadata["boundary_guarantees"]
    for key in (
        "gui_presentation_only",
        "no_provider_api_call",
        "no_storage_write",
        "no_trading_behavior",
        "no_broker_connection",
        "no_account_sync",
        "no_order_placement",
        "no_order_cancellation",
        "no_order_routing",
        "no_risk_engine",
        "no_strategy_execution",
        "no_market_data_" + "subscription",
    ):
        assert guarantees[key] is True


def test_trading_shell_sources_do_not_import_domain_execution_layers() -> None:
    forbidden_tokens = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "from leonardo." + "data",
        "import leonardo." + "data",
        "from leonardo." + "trading",
        "import leonardo." + "trading",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "socket.",
        "subprocess",
        "DownloadRequestBuilderWindow",
        "download_request_mapper",
        "broker_client",
        "place_" + "order",
        "submit_" + "order",
        "cancel_" + "order",
    )

    for source_path in (_SHELL_SOURCE, _DUMMY_SOURCE):
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{source_path.name} contains {token!r}"


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


class _RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: object | None = None,
    ):
        self.calls.append((action_id, window_id))
        return type("Decision", (), {"allowed": True})()
