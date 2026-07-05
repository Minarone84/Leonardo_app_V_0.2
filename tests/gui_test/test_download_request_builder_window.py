import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QTextEdit,
)

from leonardo.gui.windows.download_request_builder_window import (  # noqa: E402
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    OHLCV_POLICY_DEFERRED_MESSAGE,
    DownloadRequestBuilderWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILDER_SOURCE = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "download_request_builder_window.py"
)
_EXPECTED_FIELD_LABELS = (
    "Source / Provider",
    "Market",
    "Symbols",
    "Timeframe Mode",
    "Timeframes",
    "Range Mode",
    "Start",
    "End",
    "Conflict Policy",
    "Priority",
    "Connection Ref",
    "WebSocket Required",
    "Tags",
    "Metadata",
)


def test_builder_opens_in_download_data_mode(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow(DOWNLOAD_DATA_WORKFLOW_MODE)

    assert window.workflow_mode == "download_data"
    assert window.workflow_label == "Download Data"
    assert window.windowTitle() == "Download Data Request Builder"
    assert window.findChild(QLabel, "download_request_builder.title_label").text() == (
        "Download Data Request Builder"
    )
    assert window.findChild(
        QLabel,
        "download_request_builder.workflow_mode_label",
    ).text() == "Workflow mode: download_data"
    assert window.findChild(
        QLabel,
        "download_request_builder.ohlcv_policy_note",
    ).isHidden()

    window.deleteLater()
    qapplication.processEvents()


def test_builder_opens_in_ohlcv_maintenance_mode(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow(OHLCV_MAINTENANCE_WORKFLOW_MODE)
    window.show()
    qapplication.processEvents()
    note = window.findChild(QLabel, "download_request_builder.ohlcv_policy_note")

    assert window.workflow_mode == "ohlcv_maintenance"
    assert window.workflow_label == "OHLCV Maintenance"
    assert window.windowTitle() == "OHLCV Maintenance Request Builder"
    assert note.text() == OHLCV_POLICY_DEFERRED_MESSAGE
    assert note.isVisible() is True

    window.deleteLater()
    qapplication.processEvents()


def test_builder_displays_common_placeholder_fields(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()

    assert window.field_labels() == _EXPECTED_FIELD_LABELS
    assert isinstance(window.field_widget_for_id("source_provider"), QComboBox)
    assert isinstance(window.field_widget_for_id("market"), QComboBox)
    assert isinstance(window.field_widget_for_id("timeframe_mode"), QComboBox)
    assert isinstance(window.field_widget_for_id("range_mode"), QComboBox)
    assert isinstance(window.field_widget_for_id("conflict_policy"), QComboBox)
    assert isinstance(window.field_widget_for_id("priority"), QComboBox)
    assert isinstance(window.field_widget_for_id("connection_ref"), QComboBox)
    assert isinstance(window.field_widget_for_id("websocket_required"), QCheckBox)
    assert isinstance(window.field_widget_for_id("metadata"), QTextEdit)

    assert window.option_values_for_id("timeframe_mode") == (
        "explicit",
        "all",
        "default",
        "supported",
    )
    assert window.option_values_for_id("range_mode") == (
        "explicit",
        "latest",
        "missing_only",
        "full_history",
    )

    window.deleteLater()
    qapplication.processEvents()


def test_builder_has_only_local_close_button(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()

    assert window.findChild(QPushButton, "download_request_builder.close") is not None
    assert window.findChild(QPushButton, "download_request_builder.submit") is None
    assert window.findChild(QPushButton, "download_request_builder.preflight") is None

    window.deleteLater()
    qapplication.processEvents()


def test_builder_rejects_unknown_workflow_mode(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()

    with pytest.raises(ValueError, match="Unsupported"):
        window.set_workflow_mode("unknown")

    window.deleteLater()
    qapplication.processEvents()


def test_builder_source_has_no_core_or_contract_dependencies() -> None:
    source = _BUILDER_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "leonardo.core",
        "leonardo.contracts",
        "Download" + "Manager",
        "Download" + "Request(",
        "submit_" + "request",
        "LeonardoApp",
        "RuntimeManagerBackend",
        "AuditLog",
        "UserPolicy",
        "SessionManager",
    )

    for token in blocked_tokens:
        assert token not in source


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
