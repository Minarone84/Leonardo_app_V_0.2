from pathlib import Path

import pytest

from leonardo.contracts.download_data_boundary import (
    DownloadDataSelectionDraft,
    DownloadDataSelectionSummary,
)
from leonardo.contracts.downloads import (
    DownloadPreflight,
    DownloadStatus,
    DownloadTimeframeMode,
    DownloadValidationIssue,
    DownloadValidationSeverity,
    DownloadWorkflowKind,
)
from leonardo.gui.download_request_mapper import (
    DownloadPreflightPreviewView,
    DownloadSubmitResultView,
    build_download_request_for_submit,
    build_download_request_from_draft,
    build_preflight_preview_view,
    build_submit_error_view,
    build_submit_result_view,
    download_data_selection_drafts_from_request_draft,
    download_data_selection_summaries_from_request_draft,
    download_data_selection_summary_from_selection_draft,
)
from leonardo.gui.windows.download_request_builder_window import (
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    DownloadRequestDraft,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAPPER_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "download_request_mapper.py"


def test_mapper_builds_download_data_request_from_draft() -> None:
    draft = _draft()

    request = build_download_request_from_draft(draft)

    assert request.request_id.startswith("preview-")
    assert request.workflow_kind is DownloadWorkflowKind.DOWNLOAD_DATA
    assert request.source == "binance"
    assert request.market == "spot"
    assert request.symbols == ("BTCUSDT", "ETHUSDT")
    assert request.timeframe_mode is DownloadTimeframeMode.EXPLICIT
    assert request.timeframes == ("1m", "5m")
    assert request.connection_ref == "binance-spot"
    assert request.metadata["profile"] == "manual"


def test_mapper_builds_ohlcv_maintenance_request_from_draft() -> None:
    draft = _draft(workflow_mode=OHLCV_MAINTENANCE_WORKFLOW_MODE)

    request = build_download_request_from_draft(draft)

    assert request.workflow_kind is DownloadWorkflowKind.OHLCV_MAINTENANCE
    assert request.request_id.startswith("preview-")


def test_mapper_generates_deterministic_preview_ids() -> None:
    first = build_download_request_from_draft(_draft())
    second = build_download_request_from_draft(_draft())
    changed = build_download_request_from_draft(_draft(symbols=("SOLUSDT",)))

    assert first.request_id == second.request_id
    assert first.request_id != changed.request_id


def test_mapper_generates_submit_ids_with_request_prefix() -> None:
    request = build_download_request_for_submit(_draft())

    assert request.request_id.startswith("request-")
    assert not request.request_id.startswith("preview-")


def test_mapper_generates_deterministic_submit_ids() -> None:
    first = build_download_request_for_submit(_draft())
    second = build_download_request_for_submit(_draft())
    changed = build_download_request_for_submit(_draft(symbols=("SOLUSDT",)))

    assert first.request_id == second.request_id
    assert first.request_id != changed.request_id


def test_mapper_builds_submit_request_from_download_data_draft() -> None:
    draft = _draft()

    request = build_download_request_for_submit(draft)

    assert request.workflow_kind is DownloadWorkflowKind.DOWNLOAD_DATA
    assert request.source == "binance"
    assert request.market == "spot"
    assert request.symbols == ("BTCUSDT", "ETHUSDT")
    assert request.timeframe_mode is DownloadTimeframeMode.EXPLICIT
    assert request.timeframes == ("1m", "5m")
    assert request.connection_ref == "binance-spot"
    assert request.websocket_required is True
    assert request.tags == ("preview",)
    assert request.metadata["profile"] == "manual"


def test_mapper_builds_download_data_selection_draft_from_single_symbol_draft() -> None:
    draft = _draft(symbols=("BTCUSDT",))

    selections = download_data_selection_drafts_from_request_draft(draft)

    assert len(selections) == 1
    selection = selections[0]
    assert isinstance(selection, DownloadDataSelectionDraft)
    assert selection.exchange_id == "binance"
    assert selection.market_type == "spot"
    assert selection.symbol == "BTCUSDT"
    assert selection.selected_timeframes == ("1m", "5m")
    assert selection.selection_complete is True
    assert selection.warnings == ()
    assert selection.blockers == ()


def test_mapper_splits_multi_symbol_draft_into_download_data_selections() -> None:
    selections = download_data_selection_drafts_from_request_draft(_draft())

    assert tuple(selection.symbol for selection in selections) == (
        "BTCUSDT",
        "ETHUSDT",
    )
    assert all(selection.exchange_id == "binance" for selection in selections)
    assert all(selection.market_type == "spot" for selection in selections)
    assert all(selection.selected_timeframes == ("1m", "5m") for selection in selections)
    assert all(selection.selection_complete is True for selection in selections)
    assert all(
        selection.warnings
        == ("Multiple symbols were split into one Download Data selection per symbol.",)
        for selection in selections
    )


def test_mapper_represents_zero_symbol_draft_as_incomplete_selection() -> None:
    selections = download_data_selection_drafts_from_request_draft(_draft(symbols=()))

    assert len(selections) == 1
    selection = selections[0]
    assert selection.exchange_id == "binance"
    assert selection.market_type == "spot"
    assert selection.symbol is None
    assert selection.selected_timeframes == ("1m", "5m")
    assert selection.selection_complete is False
    assert selection.blockers == ("symbol is required for Download Data selection.",)


def test_mapper_supports_empty_exchange_without_inventing_exchange_id() -> None:
    selections = download_data_selection_drafts_from_request_draft(
        _draft(symbols=("BTCUSDT",), source_provider=""),
    )

    selection = selections[0]
    assert selection.exchange_id is None
    assert selection.market_type == "spot"
    assert selection.symbol == "BTCUSDT"
    assert selection.selection_complete is False
    assert "exchange_id is required for Download Data selection." in selection.blockers


def test_mapper_supports_empty_market_without_inventing_market_type() -> None:
    selections = download_data_selection_drafts_from_request_draft(
        _draft(symbols=("BTCUSDT",), market=""),
    )

    selection = selections[0]
    assert selection.exchange_id == "binance"
    assert selection.market_type is None
    assert selection.symbol == "BTCUSDT"
    assert selection.selection_complete is False
    assert "market_type is required for Download Data selection." in selection.blockers


def test_mapper_represents_empty_timeframes_as_incomplete_selection() -> None:
    selections = download_data_selection_drafts_from_request_draft(
        _draft(symbols=("BTCUSDT",), timeframes=()),
    )

    selection = selections[0]
    assert selection.selected_timeframes == ()
    assert selection.selection_complete is False
    assert (
        "selected_timeframes is required for Download Data selection."
        in selection.blockers
    )


def test_mapper_does_not_select_timeframes_for_unresolved_modes() -> None:
    selections = download_data_selection_drafts_from_request_draft(
        _draft(
            symbols=("BTCUSDT",),
            timeframe_mode="all",
            timeframes=("1m", "5m"),
        ),
    )

    selection = selections[0]
    assert selection.selected_timeframes == ()
    assert selection.selection_complete is False
    assert (
        "Only explicit timeframes map to Download Data selected_timeframes."
        in selection.warnings
    )
    assert (
        "selected_timeframes is required for Download Data selection."
        in selection.blockers
    )


def test_mapper_preserves_download_data_selection_timeframe_order() -> None:
    selections = download_data_selection_drafts_from_request_draft(
        _draft(symbols=("BTCUSDT",), timeframes=(" 5m ", "1m", "")),
    )

    assert selections[0].selected_timeframes == ("5m", "1m")


def test_mapper_converts_complete_selection_draft_to_summary() -> None:
    selection = download_data_selection_drafts_from_request_draft(
        _draft(symbols=("BTCUSDT",)),
    )[0]

    summary = download_data_selection_summary_from_selection_draft(selection)

    assert isinstance(summary, DownloadDataSelectionSummary)
    assert summary.exchange_id == "binance"
    assert summary.market_type == "spot"
    assert summary.symbol == "BTCUSDT"
    assert summary.selected_timeframes == ("1m", "5m")
    assert summary.item_count == 2
    assert summary.warnings == ()
    assert summary.blockers == ()


def test_mapper_rejects_incomplete_selection_summary_conversion() -> None:
    selection = DownloadDataSelectionDraft(
        exchange_id="binance",
        market_type="spot",
        selected_timeframes=("1m",),
    )

    with pytest.raises(ValueError, match="symbol"):
        download_data_selection_summary_from_selection_draft(selection)


def test_mapper_builds_selection_summaries_from_multi_symbol_draft() -> None:
    summaries = download_data_selection_summaries_from_request_draft(_draft())

    assert tuple(summary.symbol for summary in summaries) == (
        "BTCUSDT",
        "ETHUSDT",
    )
    assert all(summary.selected_timeframes == ("1m", "5m") for summary in summaries)
    assert all(summary.item_count == 2 for summary in summaries)
    assert all(
        summary.warnings
        == ("Multiple symbols were split into one Download Data selection per symbol.",)
        for summary in summaries
    )


def test_mapper_selection_adapter_does_not_mutate_source_draft() -> None:
    draft = _draft(
        symbols=(" BTCUSDT ", ""),
        timeframes=("1m", ""),
        source_provider=" binance ",
        market=" spot ",
    )
    original = (
        draft.source_provider,
        draft.market,
        draft.symbols,
        draft.timeframes,
        dict(draft.metadata),
    )

    selections = download_data_selection_drafts_from_request_draft(draft)

    assert selections[0].exchange_id == "binance"
    assert selections[0].market_type == "spot"
    assert selections[0].symbol == "BTCUSDT"
    assert (
        draft.source_provider,
        draft.market,
        draft.symbols,
        draft.timeframes,
        dict(draft.metadata),
    ) == original


@pytest.mark.parametrize(
    "timeframe_mode",
    ("all", "default", "supported"),
)
def test_mapper_does_not_create_fake_timeframes_for_unresolved_modes(
    timeframe_mode: str,
) -> None:
    draft = _draft(timeframe_mode=timeframe_mode, timeframes=("1m", "5m"))

    request = build_download_request_from_draft(draft)

    assert request.timeframe_mode is DownloadTimeframeMode(timeframe_mode)
    assert request.timeframes == ()


def test_mapper_converts_preflight_to_preview_view() -> None:
    issue = DownloadValidationIssue(
        code="missing_timeframes",
        severity=DownloadValidationSeverity.ERROR,
        message="Explicit timeframe mode requires at least one timeframe.",
        field="timeframes",
    )
    preflight = DownloadPreflight(
        request_id="preview-test",
        status=DownloadStatus.FAILED,
        can_run=False,
        required_connections=("binance-spot",),
        websocket_required=True,
        estimated_symbols=2,
        estimated_timeframes=0,
        estimated_items=0,
        issues=(issue,),
    )

    view = build_preflight_preview_view(preflight)

    assert isinstance(view, DownloadPreflightPreviewView)
    assert view.request_id == "preview-test"
    assert view.status == "failed"
    assert view.can_run is False
    assert view.required_connections == ("binance-spot",)
    assert view.websocket_required is True
    assert view.issues == (
        "ERROR timeframes: Explicit timeframe mode requires at least one timeframe.",
    )
    assert view.message == "Preflight preview blocked."


def test_mapper_converts_submit_result_to_gui_view() -> None:
    request = build_download_request_for_submit(_draft())
    preflight = DownloadPreflight(
        request_id=request.request_id,
        status=DownloadStatus.VALIDATED,
        can_run=True,
        estimated_items=4,
        estimated_symbols=2,
        estimated_timeframes=2,
    )

    view = build_submit_result_view(request, preflight, item_count=4)

    assert isinstance(view, DownloadSubmitResultView)
    assert view.request_id == request.request_id
    assert view.accepted is True
    assert view.status == "validated"
    assert view.can_run is True
    assert view.item_count == 4
    assert view.estimated_items == 4
    assert view.issues == ()
    assert view.message == "Download request submitted."
    assert view.runtime_visible is True
    assert view.execution_plan_id is None
    assert view.execution_plan_created is False
    assert view.execution_plan_message == "Execution plan was not created."
    assert view.execution_plan_phase is None
    assert view.execution_plan_ready is False
    assert view.execution_plan_blocked is False


def test_mapper_converts_submit_result_with_execution_plan_fields() -> None:
    request = build_download_request_for_submit(_draft())
    preflight = DownloadPreflight(
        request_id=request.request_id,
        status=DownloadStatus.VALIDATED,
        can_run=True,
        estimated_items=4,
        estimated_symbols=2,
        estimated_timeframes=2,
    )

    view = build_submit_result_view(
        request,
        preflight,
        item_count=4,
        execution_plan_id="execution-plan-request-test",
        execution_plan_created=True,
        execution_plan_message="Download execution plan classified as ready.",
        execution_plan_phase="ready",
        execution_plan_ready=True,
        execution_plan_blocked=False,
    )

    assert isinstance(view, DownloadSubmitResultView)
    assert view.execution_plan_id == "execution-plan-request-test"
    assert view.execution_plan_created is True
    assert view.execution_plan_message == "Download execution plan classified as ready."
    assert view.execution_plan_phase == "ready"
    assert view.execution_plan_ready is True
    assert view.execution_plan_blocked is False


def test_mapper_builds_safe_rejected_submit_result() -> None:
    view = build_submit_error_view(
        "request-test",
        "Download request submit rejected.",
        ("ValueError: duplicate",),
    )

    assert isinstance(view, DownloadSubmitResultView)
    assert view.request_id == "request-test"
    assert view.accepted is False
    assert view.status == "rejected"
    assert view.can_run is False
    assert view.item_count == 0
    assert view.estimated_items is None
    assert view.issues == ("ValueError: duplicate",)
    assert view.message == "Download request submit rejected."
    assert view.runtime_visible is False
    assert view.execution_plan_id is None
    assert view.execution_plan_created is False
    assert view.execution_plan_message == (
        "Execution plan was not created because submit was rejected."
    )
    assert view.execution_plan_phase is None
    assert view.execution_plan_ready is False
    assert view.execution_plan_blocked is False


def test_mapper_imports_contracts_but_no_core_or_qt() -> None:
    source = _MAPPER_SOURCE.read_text(encoding="utf-8")

    assert "leonardo.contracts.download_data_boundary" in source
    assert "leonardo.contracts.downloads" in source
    assert "leonardo.core" not in source
    assert "PySide6" not in source
    assert "Qt" not in source
    assert "DownloadManager" not in source
    assert "LeonardoApp" not in source
    assert "RuntimeManager" not in source


def test_mapper_does_not_add_later_download_data_stage_adapters() -> None:
    source = _MAPPER_SOURCE.read_text(encoding="utf-8")

    assert "DownloadDataPreflightSummary" not in source
    assert "DownloadDataProgressSummary" not in source
    assert "DownloadDataCompletionSummary" not in source
    assert "DownloadDataOutputRef" not in source
    assert "DownloadDataPartialPersistenceSummary" not in source


def _draft(
    *,
    workflow_mode: str = DOWNLOAD_DATA_WORKFLOW_MODE,
    source_provider: str = "binance",
    market: str = "spot",
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    timeframe_mode: str = "explicit",
    timeframes: tuple[str, ...] = ("1m", "5m"),
) -> DownloadRequestDraft:
    return DownloadRequestDraft(
        workflow_mode=workflow_mode,
        source_provider=source_provider,
        market=market,
        symbols=symbols,
        timeframe_mode=timeframe_mode,
        timeframes=timeframes,
        range_mode="latest",
        start="2026-01-01",
        end="2026-01-02",
        conflict_policy="skip_existing",
        priority="normal",
        connection_ref="binance-spot",
        websocket_required=True,
        tags=("preview",),
        metadata={"profile": "manual"},
        metadata_parse_error=None,
    )
