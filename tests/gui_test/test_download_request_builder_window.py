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

from leonardo.gui.metadata import GuiMetadataResolver, load_metadata_document  # noqa: E402
from leonardo.gui.windows.download_request_builder_window import (  # noqa: E402
    DOWNLOAD_DATA_WORKFLOW_MODE,
    DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID,
    DOWNLOAD_REQUEST_BUILDER_METADATA_ID,
    DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    OHLCV_POLICY_DEFERRED_MESSAGE,
    OHLCV_SUBMIT_DEFERRED_MESSAGE,
    DownloadRequestBuilderOptions,
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
_BUILDER_METADATA = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "download_request_builder.window.toml"
)
_BYBIT_TIMEFRAMES = (
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "12h",
    "1d",
    "1w",
)
_BUILDER_OPTIONS = DownloadRequestBuilderOptions(
    exchanges=("Bybit",),
    markets=("spot", "linear", "inverse"),
    timeframes=_BYBIT_TIMEFRAMES,
    default_limit=200,
    max_limit=1000,
)
_VISIBLE_FIELD_LABELS = (
    "Exchange",
    "Market Type",
    "Symbol",
    "Timeframes",
    "Start",
    "End",
    "Limit",
)
_BACKEND_LABELS = (
    "Source / Provider",
    "Timeframe Mode",
    "Range Mode",
    "Conflict Policy",
    "Priority",
    "Connection Ref",
    "WebSocket Required",
    "Tags",
    "Metadata",
)


def test_builder_metadata_keeps_identity_and_visible_actions() -> None:
    result = load_metadata_document(_BUILDER_METADATA)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == DOWNLOAD_REQUEST_BUILDER_METADATA_ID
    assert result.document.metadata["window_id"] == DOWNLOAD_REQUEST_BUILDER_METADATA_ID
    assert result.document.metadata["object_name"] == "download_request_builder_window"
    assert result.document.metadata["instance_policy"] == "singleton"
    assert tuple(action.action_id for action in result.document.actions) == (
        "download_request_builder.draft_summary",
        "download_request_builder.preview_preflight",
        DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID,
        DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID,
    )
    assert tuple(action.label for action in result.document.actions) == (
        "Draft Summary",
        "Preview Preflight",
        "Start",
        "Close",
    )

    profile = GuiMetadataResolver().resolve(result.document)
    assert profile.values["metadata"]["window_id"] == DOWNLOAD_REQUEST_BUILDER_METADATA_ID


def test_builder_metadata_aligns_to_download_data_boundary() -> None:
    document = _load_builder_document()
    workflow = document.metadata["download_data_workflow"]

    assert document.metadata["boundary_id"] == "download_data_boundary"
    assert document.metadata["workflow_id"] == DOWNLOAD_DATA_WORKFLOW_MODE
    assert document.metadata["object_kind"] == "download_data_selection_shell"
    assert workflow["boundary_id"] == "download_data_boundary"
    assert workflow["workflow_id"] == DOWNLOAD_DATA_WORKFLOW_MODE
    assert workflow["current_shell_stage"] == "selection_draft"
    assert workflow["current_contract_bridge"] == "DownloadRequestDraft -> DownloadRequest"
    assert workflow["accepted_sequence"] == (
        "selection",
        "selection_recap",
        "preflight",
        "process_confirmation",
        "progress",
        "final_recap",
    )
    assert {
        "selection_recap",
        "visible_preflight",
        "process_confirmation",
        "progress",
        "final_recap",
    }.issubset(set(workflow["not_implemented_stages"]))
    assert {
        "DownloadDataSelectionDraft",
        "DownloadDataSelectionSummary",
        "DownloadDataPreflightSummary",
        "DownloadDataProgressSummary",
        "DownloadDataCompletionSummary",
    }.issubset(set(workflow["future_contracts"]))


def test_builder_metadata_documents_action_descriptors() -> None:
    document = _load_builder_document()
    descriptors = {
        descriptor["action_id"]: descriptor
        for descriptor in document.metadata["action_descriptors"]
    }

    assert {
        "download_request_builder.draft_summary",
        "download_request_builder.preview_preflight",
        DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID,
        DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID,
    } == set(descriptors)
    assert descriptors["download_request_builder.draft_summary"]["visibility"] == (
        "internal_not_visible"
    )
    assert descriptors["download_request_builder.preview_preflight"]["visibility"] == (
        "internal_not_visible"
    )
    assert descriptors[DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID]["visibility"] == (
        "visible_button"
    )
    assert descriptors[DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID]["permission_ref"] == (
        "download:submit"
    )


def test_builder_metadata_documents_current_to_future_field_mapping() -> None:
    document = _load_builder_document()
    descriptors = {
        descriptor["current_field"]: descriptor
        for descriptor in document.metadata["field_descriptors"]
    }

    assert descriptors["source_provider"]["canonical_download_data_field"] == (
        "exchange_id"
    )
    assert descriptors["source_provider"]["user_label"] == "Exchange"
    assert descriptors["source_provider"]["current_default_behavior"] == (
        "existing_shell_default"
    )
    assert descriptors["source_provider"]["future_alignment"] == "empty_by_default"
    assert descriptors["market"]["canonical_download_data_field"] == "market_type"
    assert descriptors["market"]["user_label"] == "Market Type"
    assert descriptors["symbols"]["canonical_download_data_field"] == "symbol"
    assert descriptors["symbols"]["user_label"] == "Asset / Symbol"
    assert descriptors["symbols"]["current_default_behavior"] == "empty"


def test_builder_metadata_declares_non_execution_boundaries() -> None:
    document = _load_builder_document()
    guarantees = document.metadata["boundary_guarantees"]

    assert guarantees["no_downloader_execution"] is True
    assert guarantees["no_provider_api_call"] is True
    assert guarantees["no_storage_write"] is True
    assert guarantees["no_cancellation_behavior"] is True
    assert guarantees["no_data_manager_integration"] is True
    assert guarantees["no_runtime_manager_control"] is True
    assert guarantees["no_object_map_service_mutation"] is True
    assert guarantees["no_ai_helper_implementation"] is True
    assert {
        "downloader_execution",
        "provider_api_call",
        "storage_write",
        "cancellation_behavior",
        "data_manager_integration",
        "runtime_manager_control",
        "object_map_service_mutation",
        "ai_helper_implementation",
    } == set(guarantees["forbidden_behavior"])


def test_builder_metadata_is_ai_helper_inspectable_without_implementation() -> None:
    document = _load_builder_document()
    inspection = document.metadata["ai_inspection"]

    assert inspection["inspectable"] is True
    assert "normal GUI action observation" in inspection["allowed_path"]
    assert "Future AI helper work" in inspection["notes"][0]
    assert document.metadata["documentation"]["docs_refs"]
    assert document.metadata["documentation"]["test_refs"]


def test_builder_opens_in_download_data_mode(qapplication: QApplication) -> None:
    window = _builder()

    assert window.workflow_mode == "download_data"
    assert window.workflow_label == "Download Data"
    assert window.windowTitle() == "Download Data"
    assert window.findChild(QLabel, "download_request_builder.title_label").text() == (
        "Download Data"
    )
    assert window.findChild(
        QLabel,
        "download_request_builder.ohlcv_policy_note",
    ).isHidden()

    _dispose(qapplication, window)


def test_builder_opens_in_ohlcv_maintenance_mode(qapplication: QApplication) -> None:
    window = _builder(OHLCV_MAINTENANCE_WORKFLOW_MODE)
    window.show()
    qapplication.processEvents()
    note = window.findChild(QLabel, "download_request_builder.ohlcv_policy_note")

    assert window.workflow_mode == "ohlcv_maintenance"
    assert window.workflow_label == "OHLCV Maintenance"
    assert window.windowTitle() == "OHLCV Maintenance"
    assert note.text() == OHLCV_POLICY_DEFERRED_MESSAGE
    assert note.isVisible() is True

    _dispose(qapplication, window)


def test_compact_layout_shows_only_user_facing_field_labels(
    qapplication: QApplication,
) -> None:
    window = _builder()
    visible_labels = {
        label.text()
        for label in window.findChildren(QLabel)
        if label.objectName().startswith("download_request_builder.")
    }

    assert set(_VISIBLE_FIELD_LABELS) <= visible_labels
    for backend_label in _BACKEND_LABELS:
        assert backend_label not in visible_labels

    _dispose(qapplication, window)


def test_catalog_options_populate_exchange_market_and_timeframes(
    qapplication: QApplication,
) -> None:
    window = _builder()

    assert window.field_labels() == _VISIBLE_FIELD_LABELS
    assert window.option_values_for_id("exchange") == ("Bybit",)
    assert window.option_values_for_id("source_provider") == ("Bybit",)
    assert window.option_values_for_id("market") == ("spot", "linear", "inverse")
    assert "options" not in window.option_values_for_id("market")
    assert tuple(
        checkbox.text()
        for checkbox in window.findChildren(QCheckBox)
        if checkbox.objectName().startswith("download_request_builder.timeframe.")
    ) == _BYBIT_TIMEFRAMES
    assert window.findChild(QCheckBox, "download_request_builder.timeframe.1M") is None

    _dispose(qapplication, window)


def test_timeframe_checkboxes_are_arranged_in_three_columns(
    qapplication: QApplication,
) -> None:
    window = _builder()
    grid = window.field_widget_for_id("timeframes").layout()
    assert grid is not None

    assert grid.columnCount() == 3
    assert grid.rowCount() == 4

    _dispose(qapplication, window)


def test_no_unapproved_visible_buttons_or_controls(qapplication: QApplication) -> None:
    window = _builder()
    buttons = {
        button.objectName(): button.text()
        for button in window.findChildren(QPushButton)
        if button.objectName().startswith("download_request_builder.")
    }

    assert buttons == {
        "download_request_builder.submit_button": "Start",
        "download_request_builder.close": "Close",
    }
    assert window.findChild(QPushButton, "download_request_builder.select_all") is None
    assert window.findChild(QPushButton, "download_request_builder.clear") is None
    assert window.findChild(QPushButton, "download_request_builder.stop") is None
    assert (
        window.findChild(QPushButton, "download_request_builder.ohlcv_maintenance")
        is None
    )
    assert window.findChild(QPushButton, "download_request_builder.preflight") is None

    _dispose(qapplication, window)


def test_status_area_is_read_only(qapplication: QApplication) -> None:
    window = _builder()
    status = _status_area(window)

    assert status.isReadOnly() is True

    _dispose(qapplication, window)


def test_visible_fields_map_to_explicit_draft_with_hidden_defaults(
    qapplication: QApplication,
) -> None:
    window = _builder()
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")
    _set_text_field(window, "start", "2026-01-01")
    _set_text_field(window, "end", "2026-01-02")

    draft = window.current_draft()

    assert draft.source_provider == "Bybit"
    assert draft.market == "spot"
    assert draft.symbols == ("BTCUSDT",)
    assert draft.timeframe_mode == "explicit"
    assert draft.timeframes == ("1m",)
    assert draft.range_mode == "explicit"
    assert draft.start == "2026-01-01"
    assert draft.end == "2026-01-02"
    assert draft.conflict_policy == "skip_existing"
    assert draft.priority == "normal"
    assert draft.connection_ref == ""
    assert draft.websocket_required is False
    assert draft.tags == ()
    assert dict(draft.metadata) == {"limit": 200}

    _dispose(qapplication, window)


def test_symbol_input_maps_to_one_item_tuple(qapplication: QApplication) -> None:
    window = _builder()
    _set_text_field(window, "symbol", "BTCUSDT, ETHUSDT")

    draft = window.current_draft()

    assert draft.symbols == ("BTCUSDT, ETHUSDT",)

    _dispose(qapplication, window)


def test_no_selected_timeframes_block_local_start_validation(
    qapplication: QApplication,
) -> None:
    calls = 0

    def callback(draft: object) -> object:
        nonlocal calls
        calls += 1
        return _submit_view()

    window = _builder(on_submit_intent=callback)
    _set_text_field(window, "symbol", "BTCUSDT")

    result = _render_start(window)

    assert calls == 0
    assert "Download start blocked by local validation issues:" in result
    assert "ERROR timeframes: Explicit timeframe mode requires at least one timeframe." in (
        result
    )

    _dispose(qapplication, window)


def test_limit_default_and_max_validation(qapplication: QApplication) -> None:
    window = _builder()
    limit = window.field_widget_for_id("limit")
    assert isinstance(limit, QLineEdit)

    assert limit.text() == "200"
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")
    _set_text_field(window, "limit", "1001")

    result = _render_start(window)

    assert "ERROR limit: Limit must be less than or equal to 1000." in result

    _dispose(qapplication, window)


def test_start_valid_download_data_draft_calls_callback_once(
    qapplication: QApplication,
) -> None:
    calls: list[object] = []

    def callback(draft: object) -> object:
        calls.append(draft)
        return _submit_view()

    window = _builder(on_submit_intent=callback)
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)

    assert len(calls) == 1
    assert calls[0].symbols == ("BTCUSDT",)
    assert calls[0].timeframes == ("1m",)
    assert dict(calls[0].metadata) == {"limit": 200}
    assert result.startswith("Download start result:")
    assert "Message: Download request submitted." in result
    assert "Accepted: True" in result
    assert "Request ID: request-test" in result
    assert "Execution plan created: yes" in result

    _dispose(qapplication, window)


def test_start_action_records_through_observer(qapplication: QApplication) -> None:
    observer = _RecordingActionObserver()
    window = _builder(action_observer=observer)
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    _render_start(window)
    window.findChild(QPushButton, "download_request_builder.close").click()

    assert tuple(call.action_id for call in observer.calls) == (
        DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID,
        DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID,
    )
    assert all(
        call.window_id == DOWNLOAD_REQUEST_BUILDER_METADATA_ID
        for call in observer.calls
    )
    assert all(
        call.metadata == {"workflow_mode": DOWNLOAD_DATA_WORKFLOW_MODE}
        for call in observer.calls
    )

    _dispose(qapplication, window)


def test_denied_start_action_does_not_run_callback(
    qapplication: QApplication,
) -> None:
    calls = 0

    def callback(draft: object) -> object:
        nonlocal calls
        calls += 1
        return _submit_view()

    observer = _RecordingActionObserver(
        denied_action_ids=(DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID,)
    )
    window = _builder(on_submit_intent=callback, action_observer=observer)
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)

    assert calls == 0
    assert result == ""
    assert observer.calls[-1].action_id == DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID

    _dispose(qapplication, window)


def test_start_ohlcv_mode_blocks_callback_and_shows_deferred_message(
    qapplication: QApplication,
) -> None:
    calls = 0

    def callback(draft: object) -> object:
        nonlocal calls
        calls += 1
        return _submit_view()

    window = _builder(OHLCV_MAINTENANCE_WORKFLOW_MODE, on_submit_intent=callback)
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)

    assert calls == 0
    assert result == OHLCV_SUBMIT_DEFERRED_MESSAGE

    _dispose(qapplication, window)


def test_parseable_start_and_end_are_accepted(qapplication: QApplication) -> None:
    window = _builder()
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")
    _set_text_field(window, "start", "2026-01-01")
    _set_text_field(window, "end", "2026-01-02")

    summary = _render_summary(window)

    assert "Start: 2026-01-01" in summary
    assert "End: 2026-01-02" in summary
    assert "Local validation issues:\n- none" in summary

    _dispose(qapplication, window)


def test_reversed_start_and_end_report_local_issue(
    qapplication: QApplication,
) -> None:
    window = _builder()
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")
    _set_text_field(window, "start", "2026-01-02")
    _set_text_field(window, "end", "2026-01-01")

    summary = _render_summary(window)

    assert "- ERROR end: End must be greater than or equal to start." in summary

    _dispose(qapplication, window)


def test_builder_rejects_unknown_workflow_mode(qapplication: QApplication) -> None:
    window = _builder()

    with pytest.raises(ValueError, match="Unsupported"):
        window.set_workflow_mode("unknown")

    _dispose(qapplication, window)


def test_builder_source_has_no_core_or_contract_dependencies() -> None:
    source = _BUILDER_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "leonardo.core",
        "leonardo.contracts",
        "Download" + "Manager",
        "Download" + "Request(",
        "LeonardoApp",
        "RuntimeManagerBackend",
        "AuditLog",
        "UserPolicy",
        "SessionManager",
    )

    for token in blocked_tokens:
        assert token not in source


def _load_builder_document():
    result = load_metadata_document(_BUILDER_METADATA)
    assert result.report.has_errors is False
    assert result.document is not None
    return result.document


class _RecordingActionObserver:
    def __init__(self, denied_action_ids: tuple[str, ...] = ()) -> None:
        self._denied_action_ids = set(denied_action_ids)
        self.calls: list[SimpleNamespace] = []

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        call = SimpleNamespace(
            action_id=action_id,
            window_id=window_id,
            metadata=dict(metadata or {}),
        )
        self.calls.append(call)
        return SimpleNamespace(
            action_id=action_id,
            allowed=action_id not in self._denied_action_ids,
        )


def _builder(
    workflow_mode: str = DOWNLOAD_DATA_WORKFLOW_MODE,
    *,
    on_submit_intent=None,
    action_observer=None,
) -> DownloadRequestBuilderWindow:
    return DownloadRequestBuilderWindow(
        workflow_mode,
        on_submit_intent=on_submit_intent,
        action_observer=action_observer,
        options=_BUILDER_OPTIONS,
    )


def _set_text_field(
    window: DownloadRequestBuilderWindow,
    field_id: str,
    value: str,
) -> None:
    widget = window.field_widget_for_id(field_id)
    assert isinstance(widget, QLineEdit)
    widget.setText(value)


def _check_timeframes(
    window: DownloadRequestBuilderWindow,
    *timeframes: str,
) -> None:
    for timeframe in timeframes:
        window.timeframe_checkbox_for_value(timeframe).setChecked(True)


def _status_area(window: DownloadRequestBuilderWindow) -> QTextEdit:
    status = window.findChild(QTextEdit, "download_request_builder.status_summary")
    assert status is not None
    return status


def _render_summary(window: DownloadRequestBuilderWindow) -> str:
    window._show_draft_summary()
    return _status_area(window).toPlainText()


def _render_start(window: DownloadRequestBuilderWindow) -> str:
    button = window.findChild(
        QPushButton,
        "download_request_builder.submit_button",
    )
    assert button is not None

    button.click()
    return _status_area(window).toPlainText()


def _submit_view() -> SimpleNamespace:
    return SimpleNamespace(
        request_id="request-test",
        accepted=True,
        status="validated",
        can_run=True,
        item_count=1,
        estimated_items=1,
        issues=(),
        message="Download request submitted.",
        runtime_visible=True,
        execution_plan_id="execution-plan-request-test",
        execution_plan_created=True,
        execution_plan_message="Download execution plan classified as ready.",
        execution_plan_phase="ready",
        execution_plan_ready=True,
        execution_plan_blocked=False,
    )


def _dispose(qapplication: QApplication, *widgets) -> None:
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    qapplication.processEvents()


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
