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
    QProgressBar,
    QPushButton,
    QTextEdit,
    QWidget,
)

from leonardo.gui.metadata import GuiMetadataResolver, load_metadata_document  # noqa: E402
from leonardo.gui.windows.download_request_builder_window import (  # noqa: E402
    DOWNLOAD_DATA_WORKFLOW_MODE,
    DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID,
    DOWNLOAD_REQUEST_BUILDER_METADATA_ID,
    DOWNLOAD_REQUEST_BUILDER_PREVIEW_PREFLIGHT_ACTION_ID,
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
    assert workflow["current_shell_stage"] == "sandbox_execution"
    assert workflow["current_contract_bridge"] == "DownloadRequestDraft -> DownloadRequest"
    assert workflow["accepted_sequence"] == (
        "selection",
        "selection_recap",
        "preflight",
        "process_confirmation",
        "progress",
        "final_recap",
    )
    assert "selection_recap" not in workflow["not_implemented_stages"]
    assert "visible_preflight" not in workflow["not_implemented_stages"]
    assert "storage_aware_preflight" not in workflow["not_implemented_stages"]
    assert "progress" not in workflow["not_implemented_stages"]
    assert "real_execution" not in workflow["not_implemented_stages"]
    assert "final_recap" not in workflow["not_implemented_stages"]
    assert {
        "provider_range_discovery",
        "process_confirmation",
        "production_storage_root",
        "default_live_execution",
        "cancellation",
        "data_manager_integration",
        "ohlcv_maintenance_acceptance",
        "ai_helper",
    }.issubset(set(workflow["not_implemented_stages"]))
    assert any(
        "passive read-only selection recap" in note
        for note in workflow["implemented_stage_notes"]
    )
    assert any(
        "visible Preview Preflight control" in note
        for note in workflow["implemented_stage_notes"]
    )
    assert any(
        "displays sandbox progress" in note
        for note in workflow["implemented_stage_notes"]
    )
    assert any(
        "sandbox smoke execution" in note
        for note in workflow["implemented_stage_notes"]
    )
    assert any(
        "passive final recap" in note
        for note in workflow["implemented_stage_notes"]
    )
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
        "visible_button"
    )
    assert descriptors["download_request_builder.preview_preflight"]["permission_ref"] == (
        "download:preview"
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
    assert descriptors["source_provider"]["current_default_behavior"] == "empty"
    assert descriptors["source_provider"]["future_alignment"] == "empty_by_default"
    assert descriptors["market"]["canonical_download_data_field"] == "market_type"
    assert descriptors["market"]["user_label"] == "Market Type"
    assert descriptors["market"]["current_default_behavior"] == "empty"
    assert descriptors["symbols"]["canonical_download_data_field"] == "symbol"
    assert descriptors["symbols"]["user_label"] == "Asset / Symbol"
    assert descriptors["symbols"]["current_default_behavior"] == "empty"


def test_builder_metadata_declares_sandbox_execution_boundaries() -> None:
    document = _load_builder_document()
    guarantees = document.metadata["boundary_guarantees"]

    assert guarantees["sandbox_execution_only"] is True
    assert guarantees["fixture_backed_default_execution"] is True
    assert guarantees["live_bybit_opt_in_only"] is True
    assert guarantees["no_default_live_api"] is True
    assert guarantees["no_default_provider_api_call"] is True
    assert guarantees["no_production_storage_write"] is True
    assert guarantees["no_direct_provider_api_call"] is True
    assert guarantees["no_direct_storage_write"] is True
    assert guarantees["no_cancellation_behavior"] is True
    assert guarantees["no_data_manager_integration"] is True
    assert guarantees["no_ohlcv_maintenance_acceptance"] is True
    assert guarantees["no_runtime_manager_control"] is True
    assert guarantees["no_object_map_service_mutation"] is True
    assert guarantees["no_ai_helper_implementation"] is True
    assert {
        "default_live_api",
        "production_storage_write",
        "cancellation_behavior",
        "data_manager_integration",
        "ohlcv_maintenance_acceptance",
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
    recap = document.metadata["selection_recap_surface"]
    assert recap["surface_id"] == "download_request_builder.selection_recap"
    assert recap["read_only"] is True
    assert recap["passive_display"] is True
    assert recap["data_source"] == "current_draft / Download Data selection adapter"
    assert recap["no_execution"] is True
    assert recap["no_core_call"] is True
    assert recap["no_provider_api_call"] is True
    assert recap["no_storage_access"] is True
    assert recap["no_ai_helper_implementation"] is True
    preflight = document.metadata["preflight_preview_surface"]
    assert preflight["surface_id"] == "download_request_builder.status_summary"
    assert preflight["control_id"] == (
        "download_request_builder.preview_preflight_button"
    )
    assert preflight["read_only"] is True
    assert preflight["structural_preview_only"] is True
    assert preflight["no_execution"] is True
    assert preflight["no_provider_api_call"] is True
    assert preflight["no_storage_access"] is True
    assert preflight["no_update_or_new_file_detection"] is True
    assert "Provider range checks" in preflight["wording_guard"]
    assert "sandbox storage inspection" in preflight["storage_aware_preflight_scope"]
    progress = document.metadata["progress_shell_surface"]
    assert progress["surface_id"] == "download_request_builder.progress_shell"
    assert progress["total_progress_id"] == "download_request_builder.progress.total"
    assert progress["non_executing_shell"] is True
    assert progress["updates_from_submit_result"] is True
    assert progress["initial_total_progress"] == 0
    assert progress["initial_timeframe_progress"] == 0
    assert progress["completion_total_progress"] == 100
    assert progress["no_auto_run"] is True
    assert progress["no_fake_progress"] is True
    assert progress["no_timers"] is True
    assert progress["no_core_task_call"] is True
    final_recap = document.metadata["final_recap_surface"]
    assert final_recap["surface_id"] == "download_request_builder.status_summary"
    assert final_recap["read_only"] is True
    assert final_recap["passive_display"] is True
    assert final_recap["shows_mode"] is True
    assert final_recap["shows_csv_path"] is True
    assert final_recap["shows_metadata_path"] is True
    assert final_recap["shows_accepted_loadable_validated"] is True
    assert final_recap["shows_sandbox_notice"] is True
    assert final_recap["accepted"] is False
    assert final_recap["loadable"] is False
    assert final_recap["validated"] is False
    assert "download_request_builder.selection_recap" in {
        region.region_id for region in document.regions
    }
    assert "download_request_builder.progress_shell" in {
        region.region_id for region in document.regions
    }
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
    assert _combo_current_text(window, "exchange") == ""
    assert _combo_current_text(window, "source_provider") == ""
    assert _combo_current_text(window, "market") == ""
    assert "options" not in window.option_values_for_id("market")
    assert tuple(
        checkbox.text()
        for checkbox in window.findChildren(QCheckBox)
        if checkbox.objectName().startswith("download_request_builder.timeframe.")
    ) == _BYBIT_TIMEFRAMES
    assert window.findChild(QCheckBox, "download_request_builder.timeframe.1M") is None

    _dispose(qapplication, window)


def test_builder_initializes_with_empty_download_data_selection(
    qapplication: QApplication,
) -> None:
    window = _builder()

    draft = window.current_draft()

    assert draft.source_provider == ""
    assert draft.market == ""
    assert draft.symbols == ()
    assert draft.timeframes == ()
    assert dict(draft.metadata) == {"limit": 200}

    _dispose(qapplication, window)


def test_selection_recap_is_visible_and_empty_on_initial_creation(
    qapplication: QApplication,
) -> None:
    window = _builder()
    window.show()
    qapplication.processEvents()

    recap = window.findChild(QWidget, "download_request_builder.selection_recap")

    assert recap is not None
    assert recap.isVisible() is True
    assert _recap_value(window, "exchange") == "missing"
    assert _recap_value(window, "market_type") == "missing"
    assert _recap_value(window, "symbols") == "missing"
    assert _recap_value(window, "timeframes") == "none selected"
    assert _recap_value(window, "limit") == "200"
    assert _recap_value(window, "state") == "Selection incomplete"
    assert "exchange_id is required for Download Data selection." in _recap_value(
        window,
        "blockers",
    )
    assert "market_type is required for Download Data selection." in _recap_value(
        window,
        "blockers",
    )
    assert "symbol is required for Download Data selection." in _recap_value(
        window,
        "blockers",
    )
    assert (
        "selected_timeframes is required for Download Data selection."
        in _recap_value(window, "blockers")
    )

    _dispose(qapplication, window)


def test_selecting_exchange_does_not_auto_select_market_or_other_fields(
    qapplication: QApplication,
) -> None:
    window = _builder()

    _select_combo(window, "exchange", "Bybit")
    draft = window.current_draft()

    assert draft.source_provider == "Bybit"
    assert draft.market == ""
    assert draft.symbols == ()
    assert draft.timeframes == ()
    assert window.option_values_for_id("market") == ("spot", "linear", "inverse")
    assert _recap_value(window, "exchange") == "Bybit"
    assert _recap_value(window, "market_type") == "missing"
    assert _recap_value(window, "symbols") == "missing"
    assert _recap_value(window, "timeframes") == "none selected"
    assert _recap_value(window, "state") == "Selection incomplete"

    _dispose(qapplication, window)


def test_selecting_market_does_not_invent_symbol_or_timeframes(
    qapplication: QApplication,
) -> None:
    window = _builder()

    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    draft = window.current_draft()

    assert draft.source_provider == "Bybit"
    assert draft.market == "spot"
    assert draft.symbols == ()
    assert draft.timeframes == ()
    assert _recap_value(window, "exchange") == "Bybit"
    assert _recap_value(window, "market_type") == "spot"
    assert _recap_value(window, "symbols") == "missing"
    assert _recap_value(window, "timeframes") == "none selected"
    assert _recap_value(window, "state") == "Selection incomplete"

    _dispose(qapplication, window)


def test_selection_recap_updates_symbol_timeframes_and_limit(
    qapplication: QApplication,
) -> None:
    window = _builder()

    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m", "5m")
    _set_text_field(window, "limit", "500")

    assert _recap_value(window, "symbols") == "BTCUSDT"
    assert _recap_value(window, "timeframes") == "2 (1m, 5m)"
    assert _recap_value(window, "limit") == "500"

    _dispose(qapplication, window)


def test_complete_selection_recap_shows_ready_state_and_item_count(
    qapplication: QApplication,
) -> None:
    window = _builder()

    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m", "5m")

    assert _recap_value(window, "state") == (
        "Selection complete - ready for preflight (2 items)"
    )
    assert _recap_value(window, "warnings") == "none"
    assert _recap_value(window, "blockers") == "none"

    _dispose(qapplication, window)


def test_selection_recap_reports_limit_blocker_without_exception(
    qapplication: QApplication,
) -> None:
    window = _builder()

    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")
    _set_text_field(window, "limit", "invalid")

    assert _recap_value(window, "limit") == "unresolved"
    assert _recap_value(window, "state") == "Selection incomplete"
    assert "Limit must be a positive integer." in _recap_value(window, "blockers")

    _dispose(qapplication, window)


def test_selection_recap_updates_do_not_trigger_preview_or_submit_callbacks(
    qapplication: QApplication,
) -> None:
    preview_calls = 0
    submit_calls = 0

    def preview_callback(draft: object) -> object:
        nonlocal preview_calls
        preview_calls += 1
        return object()

    def submit_callback(draft: object) -> object:
        nonlocal submit_calls
        submit_calls += 1
        return _submit_view()

    window = _builder(
        on_preview_requested=preview_callback,
        on_submit_intent=submit_callback,
    )

    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")
    _set_text_field(window, "limit", "500")

    assert preview_calls == 0
    assert submit_calls == 0
    assert _status_area(window).toPlainText() == ""

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
        "download_request_builder.preview_preflight_button": "Preview Preflight",
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
    assert (
        window.findChild(QPushButton, "download_request_builder.process_download")
        is None
    )

    _dispose(qapplication, window)


def test_status_area_is_read_only(qapplication: QApplication) -> None:
    window = _builder()
    status = _status_area(window)

    assert status.isReadOnly() is True

    _dispose(qapplication, window)


def test_preview_preflight_incomplete_selection_shows_local_validation_only(
    qapplication: QApplication,
) -> None:
    preview_calls = 0
    submit_calls = 0

    def preview_callback(draft: object) -> object:
        nonlocal preview_calls
        preview_calls += 1
        return _preview_view()

    def submit_callback(draft: object) -> object:
        nonlocal submit_calls
        submit_calls += 1
        return _submit_view()

    window = _builder(
        on_preview_requested=preview_callback,
        on_submit_intent=submit_callback,
    )
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")

    result = _render_preview(window)

    assert preview_calls == 0
    assert submit_calls == 0
    assert "Preflight preview blocked by local validation issues:" in result
    assert "ERROR timeframes: Explicit timeframe mode requires at least one timeframe." in (
        result
    )

    _dispose(qapplication, window)


def test_preview_preflight_complete_selection_calls_preview_without_submit(
    qapplication: QApplication,
) -> None:
    preview_calls: list[object] = []
    submit_calls = 0

    def preview_callback(draft: object) -> object:
        preview_calls.append(draft)
        return _preview_view()

    def submit_callback(draft: object) -> object:
        nonlocal submit_calls
        submit_calls += 1
        return _submit_view()

    window = _builder(
        on_preview_requested=preview_callback,
        on_submit_intent=submit_callback,
    )
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_preview(window)

    assert len(preview_calls) == 1
    assert preview_calls[0].symbols == ("BTCUSDT",)
    assert preview_calls[0].timeframes == ("1m",)
    assert submit_calls == 0
    assert result.startswith("Preflight preview result:")
    assert (
        "Structural preflight preview only. Provider range checks, storage "
        "checks, update/new-file detection, and execution are not performed "
        "in this shell yet."
    ) in result
    assert "Message: Preflight preview passed." in result
    assert "Request ID: preview-test" in result
    assert "Provider range checks completed" not in result
    assert "Storage checks completed" not in result
    assert "Update/new-file mode determined" not in result
    assert "Execution started" not in result
    assert "Files written" not in result

    _dispose(qapplication, window)


def test_preview_preflight_action_records_through_observer(
    qapplication: QApplication,
) -> None:
    observer = _RecordingActionObserver()
    window = _builder(
        on_preview_requested=lambda draft: _preview_view(),
        action_observer=observer,
    )
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    _render_preview(window)

    assert tuple(call.action_id for call in observer.calls) == (
        DOWNLOAD_REQUEST_BUILDER_PREVIEW_PREFLIGHT_ACTION_ID,
    )
    assert observer.calls[0].window_id == DOWNLOAD_REQUEST_BUILDER_METADATA_ID
    assert observer.calls[0].metadata == {"workflow_mode": DOWNLOAD_DATA_WORKFLOW_MODE}

    _dispose(qapplication, window)


def test_progress_shell_initializes_as_non_running_empty_state(
    qapplication: QApplication,
) -> None:
    window = _builder()

    progress = window.findChild(QWidget, "download_request_builder.progress_shell")
    total = window.findChild(QProgressBar, "download_request_builder.progress.total")
    empty = window.findChild(
        QLabel,
        "download_request_builder.progress.timeframes.empty",
    )
    messages = window.findChild(
        QTextEdit,
        "download_request_builder.progress.messages",
    )

    assert progress is not None
    assert total is not None
    assert total.value() == 0
    assert empty is not None
    assert empty.text() == "No timeframes selected."
    assert messages is not None
    assert messages.isReadOnly() is True
    assert messages.toPlainText() == (
        "No download running.\nExecution is not implemented yet."
    )

    _dispose(qapplication, window)


def test_progress_shell_shows_zeroed_per_timeframe_rows_without_autorun(
    qapplication: QApplication,
) -> None:
    window = _builder()
    _check_timeframes(window, "1m", "5m")
    qapplication.processEvents()

    total = window.findChild(QProgressBar, "download_request_builder.progress.total")
    one_minute = window.findChild(
        QProgressBar,
        "download_request_builder.progress.timeframe.1m",
    )
    five_minutes = window.findChild(
        QProgressBar,
        "download_request_builder.progress.timeframe.5m",
    )
    empty = window.findChild(
        QLabel,
        "download_request_builder.progress.timeframes.empty",
    )
    messages = window.findChild(
        QTextEdit,
        "download_request_builder.progress.messages",
    )

    assert total is not None
    assert total.value() == 0
    assert one_minute is not None
    assert one_minute.value() == 0
    assert five_minutes is not None
    assert five_minutes.value() == 0
    assert empty is None
    assert messages is not None
    assert messages.toPlainText() == (
        "No download running.\nExecution is not implemented yet."
    )

    qapplication.processEvents()

    assert total.value() == 0
    assert one_minute.value() == 0
    assert five_minutes.value() == 0

    _dispose(qapplication, window)


def test_visible_fields_map_to_explicit_draft_with_hidden_defaults(
    qapplication: QApplication,
) -> None:
    window = _builder()
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")

    result = _render_start(window)

    assert calls == 0
    assert "Download start blocked by local validation issues:" in result
    assert "ERROR timeframes: Explicit timeframe mode requires at least one timeframe." in (
        result
    )

    _dispose(qapplication, window)


def test_empty_exchange_blocks_local_start_validation(
    qapplication: QApplication,
) -> None:
    calls = 0

    def callback(draft: object) -> object:
        nonlocal calls
        calls += 1
        return _submit_view()

    window = _builder(on_submit_intent=callback)
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)

    assert calls == 0
    assert "Download start blocked by local validation issues:" in result
    assert "ERROR source_provider: Exchange is required." in result

    _dispose(qapplication, window)


def test_empty_market_blocks_local_start_validation(
    qapplication: QApplication,
) -> None:
    calls = 0

    def callback(draft: object) -> object:
        nonlocal calls
        calls += 1
        return _submit_view()

    window = _builder(on_submit_intent=callback)
    _select_combo(window, "exchange", "Bybit")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)

    assert calls == 0
    assert "Download start blocked by local validation issues:" in result
    assert "ERROR market: Market Type is required." in result

    _dispose(qapplication, window)


def test_limit_default_and_max_validation(qapplication: QApplication) -> None:
    window = _builder()
    limit = window.field_widget_for_id("limit")
    assert isinstance(limit, QLineEdit)

    assert limit.text() == "200"
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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


def test_start_completed_sandbox_execution_updates_status_and_progress(
    qapplication: QApplication,
) -> None:
    window = _builder(on_submit_intent=lambda draft: _submit_view_with_sandbox())
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)
    total = window.findChild(QProgressBar, "download_request_builder.progress.total")
    one_minute = window.findChild(
        QProgressBar,
        "download_request_builder.progress.timeframe.1m",
    )
    messages = window.findChild(
        QTextEdit,
        "download_request_builder.progress.messages",
    )

    assert "Sandbox execution:" in result
    assert "Status: completed" in result
    assert "Bars written: 3" in result
    assert "CSV path: C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv" in (
        result
    )
    assert "Metadata path: C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json" in (
        result
    )
    assert "First timestamp: 1700000000000" in result
    assert "Last timestamp: 1700000120000" in result
    assert "Accepted: no" in result
    assert "Loadable: no" in result
    assert "Validated: no" in result
    assert "Final recap:" in result
    assert "exchange=bybit" in result
    assert "market_type=spot" in result
    assert "symbol=BTCUSDT" in result
    assert "timeframe=1m" in result
    assert "mode=new_file" in result
    assert "status=completed" in result
    assert "accepted=false" in result
    assert "loadable=false" in result
    assert "validated=false" in result
    assert "Sandbox root notice: output is confined to the configured sandbox root." in (
        result
    )
    assert total is not None
    assert total.value() == 100
    assert one_minute is not None
    assert one_minute.value() == 100
    assert messages is not None
    assert "Sandbox smoke execution completed." in messages.toPlainText()
    assert "Bars written: 3" in messages.toPlainText()
    assert "mode=new_file" in messages.toPlainText()

    _dispose(qapplication, window)


def test_start_completed_sandbox_update_execution_shows_update_recap(
    qapplication: QApplication,
) -> None:
    window = _builder(
        on_submit_intent=lambda draft: _submit_view_with_sandbox(
            mode="update_existing",
            message="Sandbox smoke execution completed with update_existing output.",
        )
    )
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)
    messages = window.findChild(
        QTextEdit,
        "download_request_builder.progress.messages",
    )

    assert "Sandbox execution:" in result
    assert "Status: completed" in result
    assert "Message: Sandbox smoke execution completed with update_existing output." in (
        result
    )
    assert "Final recap:" in result
    assert "mode=update_existing" in result
    assert "status=completed" in result
    assert "csv_path=C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv" in (
        result
    )
    assert "metadata_path=C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json" in (
        result
    )
    assert "accepted=false" in result
    assert "loadable=false" in result
    assert "validated=false" in result
    assert messages is not None
    assert "mode=update_existing" in messages.toPlainText()

    _dispose(qapplication, window)


def test_start_action_records_through_observer(qapplication: QApplication) -> None:
    observer = _RecordingActionObserver()
    window = _builder(action_observer=observer)
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
    _set_text_field(window, "symbol", "BTCUSDT")
    _check_timeframes(window, "1m")

    result = _render_start(window)

    assert calls == 0
    assert result == OHLCV_SUBMIT_DEFERRED_MESSAGE

    _dispose(qapplication, window)


def test_parseable_start_and_end_are_accepted(qapplication: QApplication) -> None:
    window = _builder()
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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
    _select_combo(window, "exchange", "Bybit")
    _select_combo(window, "market", "spot")
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
    on_preview_requested=None,
    on_submit_intent=None,
    action_observer=None,
) -> DownloadRequestBuilderWindow:
    return DownloadRequestBuilderWindow(
        workflow_mode,
        on_preview_requested=on_preview_requested,
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


def _select_combo(
    window: DownloadRequestBuilderWindow,
    field_id: str,
    value: str,
) -> None:
    widget = window.field_widget_for_id(field_id)
    assert isinstance(widget, QComboBox)
    index = widget.findText(value)
    assert index >= 0
    widget.setCurrentIndex(index)


def _combo_current_text(
    window: DownloadRequestBuilderWindow,
    field_id: str,
) -> str:
    widget = window.field_widget_for_id(field_id)
    assert isinstance(widget, QComboBox)
    return widget.currentText()


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


def _recap_value(window: DownloadRequestBuilderWindow, field_id: str) -> str:
    label = window.findChild(
        QLabel,
        f"download_request_builder.selection_recap.{field_id}.value",
    )
    assert label is not None
    return label.text()


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


def _render_preview(window: DownloadRequestBuilderWindow) -> str:
    button = window.findChild(
        QPushButton,
        "download_request_builder.preview_preflight_button",
    )
    assert button is not None

    button.click()
    return _status_area(window).toPlainText()


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


def _submit_view_with_sandbox(
    *,
    mode: str = "new_file",
    message: str = "Sandbox smoke execution completed.",
) -> SimpleNamespace:
    view = _submit_view()
    view.sandbox_execution_status = "completed"
    view.sandbox_execution_completed = True
    view.sandbox_execution_message = message
    view.sandbox_root = "C:/tmp/sandbox"
    view.sandbox_csv_paths = (
        "C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv",
    )
    view.sandbox_metadata_paths = (
        "C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json",
    )
    view.sandbox_bars_written = 3
    view.sandbox_first_timestamp_ms = 1_700_000_000_000
    view.sandbox_last_timestamp_ms = 1_700_000_120_000
    view.sandbox_timeframes_completed = ("1m",)
    view.sandbox_result_summaries = (
        "exchange=bybit | market_type=spot | symbol=BTCUSDT | timeframe=1m | "
        f"mode={mode} | status=completed | bars_written=3 | "
        "first_timestamp_ms=1700000000000 | "
        "last_timestamp_ms=1700000120000 | "
        "csv_path=C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv | "
        "metadata_path=C:/tmp/sandbox/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json | "
        "accepted=false | loadable=false | validated=false | sandbox_only=true",
    )
    return view


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
