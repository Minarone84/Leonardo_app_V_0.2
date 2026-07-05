import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
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
    assert (
        window.findChild(
            QPushButton,
            "download_request_builder.draft_summary_button",
        )
        is not None
    )
    assert (
        window.findChild(
            QPushButton,
            "download_request_builder.preview_preflight_button",
        )
        is not None
    )
    assert window.findChild(QPushButton, "download_request_builder.submit") is None
    assert window.findChild(QPushButton, "download_request_builder.preflight") is None

    window.deleteLater()
    qapplication.processEvents()


def test_builder_summary_text_area_is_read_only(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()
    summary_text = window.findChild(QTextEdit, "download_request_builder.summary_text")

    assert summary_text is not None
    assert summary_text.isReadOnly() is True

    window.deleteLater()
    qapplication.processEvents()


def test_builder_preview_result_text_area_is_read_only(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    preview_result = window.findChild(
        QTextEdit,
        "download_request_builder.preview_result_text",
    )

    assert preview_result is not None
    assert preview_result.isReadOnly() is True

    window.deleteLater()
    qapplication.processEvents()


def test_builder_exposes_current_draft(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT, ETHUSDT")
    _set_text_field(window, "timeframes", "1m\n5m")
    _set_text_field(window, "tags", "preview, smoke")
    _set_metadata(window, '{"profile": "manual"}')

    draft = window.current_draft()

    assert draft.workflow_mode == DOWNLOAD_DATA_WORKFLOW_MODE
    assert draft.symbols == ("BTCUSDT", "ETHUSDT")
    assert draft.timeframes == ("1m", "5m")
    assert draft.tags == ("preview", "smoke")
    assert draft.metadata["profile"] == "manual"

    window.deleteLater()
    qapplication.processEvents()


def test_preview_local_validation_errors_block_callback(
    qapplication: QApplication,
) -> None:
    calls = 0

    def callback(draft: object) -> object:
        nonlocal calls
        calls += 1
        return _preview_view()

    window = DownloadRequestBuilderWindow(on_preview_requested=callback)

    result = _render_preview(window)

    assert calls == 0
    assert "Preflight preview blocked by local validation issues:" in result
    assert "ERROR symbols: At least one symbol is required." in result
    assert (
        "ERROR timeframes: Explicit timeframe mode requires at least one timeframe."
        in result
    )

    window.deleteLater()
    qapplication.processEvents()


def test_preview_valid_draft_calls_callback_once(qapplication: QApplication) -> None:
    calls: list[object] = []

    def callback(draft: object) -> object:
        calls.append(draft)
        return _preview_view()

    window = DownloadRequestBuilderWindow(on_preview_requested=callback)
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")

    result = _render_preview(window)

    assert len(calls) == 1
    assert result.startswith("Preflight preview result:")
    assert "Message: Preflight preview passed." in result
    assert "Request ID: preview-test" in result
    assert "Status: validated" in result
    assert "Core preview issues:\n- none" in result

    window.deleteLater()
    qapplication.processEvents()


def test_preview_absent_callback_renders_unavailable_message(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")

    result = _render_preview(window)

    assert result == "Preflight preview is unavailable."

    window.deleteLater()
    qapplication.processEvents()


def test_preview_callback_exception_renders_safe_error(
    qapplication: QApplication,
) -> None:
    def callback(draft: object) -> object:
        raise RuntimeError("preview failed")

    window = DownloadRequestBuilderWindow(on_preview_requested=callback)
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")

    result = _render_preview(window)

    assert result == "Preflight preview failed: RuntimeError: preview failed"

    window.deleteLater()
    qapplication.processEvents()


def test_draft_summary_parses_comma_separated_symbols(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT, ETHUSDT")
    _set_text_field(window, "timeframes", "1m")

    summary = _render_summary(window)

    assert "Symbols: 2 (BTCUSDT, ETHUSDT)" in summary

    window.deleteLater()
    qapplication.processEvents()


def test_draft_summary_parses_newline_separated_symbols(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT\nETHUSDT")
    _set_text_field(window, "timeframes", "1m")

    summary = _render_summary(window)

    assert "Symbols: 2 (BTCUSDT, ETHUSDT)" in summary

    window.deleteLater()
    qapplication.processEvents()


def test_draft_summary_parses_timeframes_only_for_explicit_mode(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m\n5m")

    explicit_summary = _render_summary(window)
    _select_combo_value(window, "timeframe_mode", "all")
    all_summary = _render_summary(window)

    assert "Explicit timeframes: 2 (1m, 5m)" in explicit_summary
    assert "Explicit timeframes: 0 (none)" in all_summary

    window.deleteLater()
    qapplication.processEvents()


def test_explicit_timeframe_mode_with_empty_timeframes_reports_local_issue(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")

    summary = _render_summary(window)

    assert (
        "- ERROR timeframes: Explicit timeframe mode requires at least one timeframe."
        in summary
    )

    window.deleteLater()
    qapplication.processEvents()


@pytest.mark.parametrize("timeframe_mode", ("all", "default", "supported"))
def test_non_explicit_timeframe_modes_do_not_require_timeframes(
    qapplication: QApplication,
    timeframe_mode: str,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _select_combo_value(window, "timeframe_mode", timeframe_mode)

    summary = _render_summary(window)

    assert "Local validation issues:\n- none" in summary

    window.deleteLater()
    qapplication.processEvents()


def test_draft_summary_parses_tags_from_commas_and_newlines(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")
    _set_text_field(window, "tags", "alpha, beta\ngamma")

    summary = _render_summary(window)

    assert "Tags: 3 (alpha, beta, gamma)" in summary

    window.deleteLater()
    qapplication.processEvents()


def test_empty_metadata_is_valid(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")

    summary = _render_summary(window)

    assert "Metadata: valid JSON object {}" in summary
    assert "metadata:" not in summary

    window.deleteLater()
    qapplication.processEvents()


def test_json_object_metadata_parses_and_appears_in_summary(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")
    _set_metadata(window, '{"note": "daily", "source": "manual"}')

    summary = _render_summary(window)

    assert 'Metadata: valid JSON object {"note": "daily", "source": "manual"}' in summary

    window.deleteLater()
    qapplication.processEvents()


def test_invalid_metadata_reports_local_issue(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")
    _set_metadata(window, "{bad")

    summary = _render_summary(window)

    assert "- ERROR metadata: Invalid metadata JSON:" in summary

    window.deleteLater()
    qapplication.processEvents()


@pytest.mark.parametrize("metadata", ('["tag"]', '"text"', "3"))
def test_non_object_metadata_reports_local_issue(
    qapplication: QApplication,
    metadata: str,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")
    _set_metadata(window, metadata)

    summary = _render_summary(window)

    assert "- ERROR metadata: Metadata must be a JSON object." in summary

    window.deleteLater()
    qapplication.processEvents()


def test_parseable_start_and_end_are_accepted(qapplication: QApplication) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")
    _set_text_field(window, "start", "2026-01-01")
    _set_text_field(window, "end", "2026-01-02")

    summary = _render_summary(window)

    assert "Start: 2026-01-01" in summary
    assert "End: 2026-01-02" in summary
    assert "Local validation issues:\n- none" in summary

    window.deleteLater()
    qapplication.processEvents()


def test_reversed_start_and_end_report_local_issue(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow()
    _set_text_field(window, "symbols", "BTCUSDT")
    _set_text_field(window, "timeframes", "1m")
    _set_text_field(window, "start", "2026-01-02")
    _set_text_field(window, "end", "2026-01-01")

    summary = _render_summary(window)

    assert "- ERROR end: End must be greater than or equal to start." in summary

    window.deleteLater()
    qapplication.processEvents()


def test_ohlcv_draft_summary_includes_deferred_policy_warning(
    qapplication: QApplication,
) -> None:
    window = DownloadRequestBuilderWindow(OHLCV_MAINTENANCE_WORKFLOW_MODE)

    summary = _render_summary(window)

    assert (
        "OHLCV naming/storage/maintenance policy is not implemented here. "
        "This is a local draft only."
    ) in summary

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


def _set_text_field(
    window: DownloadRequestBuilderWindow,
    field_id: str,
    value: str,
) -> None:
    widget = window.field_widget_for_id(field_id)
    assert isinstance(widget, QLineEdit)
    widget.setText(value)


def _set_metadata(window: DownloadRequestBuilderWindow, value: str) -> None:
    widget = window.field_widget_for_id("metadata")
    assert isinstance(widget, QTextEdit)
    widget.setPlainText(value)


def _select_combo_value(
    window: DownloadRequestBuilderWindow,
    field_id: str,
    value: str,
) -> None:
    widget = window.field_widget_for_id(field_id)
    assert isinstance(widget, QComboBox)
    index = widget.findText(value)
    assert index >= 0
    widget.setCurrentIndex(index)


def _render_summary(window: DownloadRequestBuilderWindow) -> str:
    button = window.findChild(
        QPushButton,
        "download_request_builder.draft_summary_button",
    )
    summary_text = window.findChild(QTextEdit, "download_request_builder.summary_text")
    assert button is not None
    assert summary_text is not None

    button.click()
    return summary_text.toPlainText()


def _render_preview(window: DownloadRequestBuilderWindow) -> str:
    button = window.findChild(
        QPushButton,
        "download_request_builder.preview_preflight_button",
    )
    preview_text = window.findChild(
        QTextEdit,
        "download_request_builder.preview_result_text",
    )
    assert button is not None
    assert preview_text is not None

    button.click()
    return preview_text.toPlainText()


def _preview_view() -> SimpleNamespace:
    return SimpleNamespace(
        request_id="preview-test",
        status="validated",
        can_run=True,
        estimated_symbols=1,
        estimated_timeframes=1,
        estimated_items=1,
        required_connections=(),
        websocket_required=False,
        issues=(),
        message="Preflight preview passed.",
    )
