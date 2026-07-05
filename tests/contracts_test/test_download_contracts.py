from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.downloads import (
    DownloadConflictPolicy,
    DownloadPreflight,
    DownloadPriority,
    DownloadProgress,
    DownloadRangeMode,
    DownloadRequest,
    DownloadRequestItem,
    DownloadResult,
    DownloadStatus,
    DownloadSummary,
    DownloadTimeframeMode,
    DownloadValidationIssue,
    DownloadValidationSeverity,
    DownloadWorkflowKind,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOWNLOADS_CONTRACT = _REPO_ROOT / "src" / "leonardo" / "contracts" / "downloads.py"


def test_download_enum_values() -> None:
    assert DownloadWorkflowKind.DOWNLOAD_DATA.value == "download_data"
    assert DownloadWorkflowKind.OHLCV_MAINTENANCE.value == "ohlcv_maintenance"
    assert DownloadStatus.REQUESTED.value == "requested"
    assert DownloadStatus.PARTIALLY_COMPLETED.value == "partially_completed"
    assert DownloadTimeframeMode.EXPLICIT.value == "explicit"
    assert DownloadTimeframeMode.ALL.value == "all"
    assert DownloadRangeMode.MISSING_ONLY.value == "missing_only"
    assert DownloadRangeMode.FULL_HISTORY.value == "full_history"
    assert DownloadConflictPolicy.REPAIR_GAPS.value == "repair_gaps"
    assert DownloadPriority.HIGH.value == "high"
    assert DownloadValidationSeverity.ERROR.value == "error"


def test_valid_explicit_multi_timeframe_request() -> None:
    request = DownloadRequest(
        request_id="request-1",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        batch_id="batch-1",
        source="binance",
        market="spot",
        symbols=("BTCUSDT",),
        timeframe_mode=DownloadTimeframeMode.EXPLICIT,
        timeframes=("1m", "5m", "1h"),
        range_mode=DownloadRangeMode.EXPLICIT,
        start="2026-01-01T00:00:00Z",
        end="2026-01-02T00:00:00Z",
        conflict_policy=DownloadConflictPolicy.MERGE,
        priority=DownloadPriority.HIGH,
        requested_by="admin-dev",
        correlation_id="corr-1",
        connection_ref="connection-binance",
        websocket_required=True,
        preflight_required=True,
        tags=("batch", "crypto"),
        metadata={"labels": ["initial", "audit"]},
    )

    assert request.timeframe_mode is DownloadTimeframeMode.EXPLICIT
    assert request.timeframes == ("1m", "5m", "1h")
    assert request.symbols == ("BTCUSDT",)
    assert request.metadata["labels"] == ("initial", "audit")


def test_valid_all_timeframe_request_allows_empty_timeframes() -> None:
    request = DownloadRequest(
        request_id="request-all",
        workflow_kind=DownloadWorkflowKind.OHLCV_MAINTENANCE,
        source="binance",
        symbols=("ETHUSDT",),
        timeframe_mode=DownloadTimeframeMode.ALL,
        timeframes=(),
        range_mode=DownloadRangeMode.FULL_HISTORY,
        conflict_policy=DownloadConflictPolicy.REPAIR_GAPS,
    )

    assert request.timeframe_mode is DownloadTimeframeMode.ALL
    assert request.timeframes == ()


def test_explicit_timeframe_request_rejects_empty_timeframes() -> None:
    with pytest.raises(ValueError, match="timeframes"):
        DownloadRequest(
            request_id="request-empty-timeframes",
            workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
            symbols=("BTCUSDT",),
            timeframe_mode=DownloadTimeframeMode.EXPLICIT,
            timeframes=(),
        )


def test_valid_multi_symbol_request() -> None:
    request = DownloadRequest(
        request_id="request-symbols",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        timeframe_mode=DownloadTimeframeMode.SUPPORTED,
        range_mode=DownloadRangeMode.MISSING_ONLY,
        conflict_policy=DownloadConflictPolicy.APPEND,
    )

    assert request.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert request.timeframes == ()


def test_request_rejects_empty_symbols() -> None:
    with pytest.raises(ValueError, match="symbols"):
        DownloadRequest(
            request_id="request-no-symbols",
            workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
            symbols=(),
        )


def test_valid_preflight_with_missing_connection_issue() -> None:
    issue = DownloadValidationIssue(
        code="missing_connection",
        severity=DownloadValidationSeverity.ERROR,
        message="Required market-data connection is unavailable.",
        field="connection_ref",
        metadata={"connection_ref": "connection-binance"},
    )
    preflight = DownloadPreflight(
        request_id="request-1",
        status=DownloadStatus.VALIDATED,
        can_run=False,
        required_connections=("connection-binance",),
        missing_connections=("connection-binance",),
        websocket_required=True,
        websocket_available=False,
        estimated_items=6,
        estimated_symbols=2,
        estimated_timeframes=3,
        issues=(issue,),
    )

    assert preflight.can_run is False
    assert preflight.issues == (issue,)
    assert preflight.websocket_available is False


def test_valid_progress_with_current_item_symbol_and_timeframe() -> None:
    progress = DownloadProgress(
        total_items=10,
        completed_items=4,
        failed_items=1,
        skipped_items=1,
        running_items=2,
        percent=60,
        current_item_id="item-7",
        current_symbol="BTCUSDT",
        current_timeframe="1m",
        message="Downloading BTCUSDT 1m",
        bytes_downloaded=1024,
        rows_downloaded=500,
        candles_downloaded=500,
        started_at_utc="2026-01-01T00:00:00Z",
        updated_at_utc="2026-01-01T00:01:00Z",
    )

    assert progress.percent == 60.0
    assert progress.current_item_id == "item-7"
    assert progress.current_symbol == "BTCUSDT"
    assert progress.current_timeframe == "1m"


def test_invalid_progress_percent_is_rejected() -> None:
    with pytest.raises(ValueError, match="percent"):
        DownloadProgress(percent=101)


def test_progress_rejects_negative_counts_and_overflow() -> None:
    with pytest.raises(ValueError, match="failed_items"):
        DownloadProgress(failed_items=-1)
    with pytest.raises(ValueError, match="exceed total_items"):
        DownloadProgress(
            total_items=2,
            completed_items=1,
            failed_items=1,
            running_items=1,
        )


def test_valid_per_item_status_with_connection_and_channel_refs() -> None:
    item = DownloadRequestItem(
        item_id="item-1",
        request_id="request-1",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        source="binance",
        market="spot",
        symbol="BTCUSDT",
        timeframe="1m",
        status=DownloadStatus.RUNNING,
        operation_id="operation-1",
        task_id="task-1",
        process_id="process-1",
        connection_id="connection-binance",
        channel_id="channel-btcusdt-1m",
        progress=DownloadProgress(total_items=1, running_items=1, percent=50),
        validation_issues=(),
        created_at_utc="2026-01-01T00:00:00Z",
        updated_at_utc="2026-01-01T00:00:30Z",
    )

    assert item.connection_id == "connection-binance"
    assert item.channel_id == "channel-btcusdt-1m"
    assert item.progress is not None
    assert item.progress.percent == 50.0


def test_valid_partial_result() -> None:
    result = DownloadResult(
        request_id="request-1",
        status=DownloadStatus.PARTIALLY_COMPLETED,
        output_refs=("dataset://binance/BTCUSDT/1m",),
        completed_count=1,
        failed_count=1,
        skipped_count=2,
        error="Some symbols failed.",
        metadata={"failed_symbols": ("ETHUSDT",)},
    )

    assert result.status is DownloadStatus.PARTIALLY_COMPLETED
    assert result.output_refs == ("dataset://binance/BTCUSDT/1m",)
    assert result.failed_count == 1


def test_valid_rich_summary() -> None:
    summary = DownloadSummary(
        total_requests=4,
        total_items=12,
        requested_count=1,
        validated_count=1,
        queued_count=2,
        running_count=3,
        completed_count=5,
        failed_count=1,
        cancelled_count=0,
        skipped_count=1,
        partially_completed_count=1,
        active_request_ids=("request-running",),
        queued_request_ids=("request-queued",),
        failed_request_ids=("request-failed",),
        active_item_ids=("item-running",),
        failed_item_ids=("item-failed",),
        websocket_required_count=2,
        connection_blocked_count=1,
        preflight_failed_count=1,
        metadata={"owner": "download-manager"},
    )

    assert summary.total_requests == 4
    assert summary.active_request_ids == ("request-running",)
    assert summary.connection_blocked_count == 1


def test_summary_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="total_items"):
        DownloadSummary(total_items=-1)


def test_frozen_contracts_and_readonly_metadata() -> None:
    metadata = {"nested": {"values": ["a", "b"]}}
    request = DownloadRequest(
        request_id="request-immutable",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        symbols=("BTCUSDT",),
        metadata=metadata,
    )
    metadata["nested"] = {"values": ["changed"]}

    assert request.metadata["nested"]["values"] == ("a", "b")
    with pytest.raises(TypeError):
        request.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        request.request_id = "changed"  # type: ignore[misc]


def test_download_contracts_do_not_import_core_or_gui() -> None:
    source = _DOWNLOADS_CONTRACT.read_text(encoding="utf-8")

    assert "leonardo.core" not in source
    assert "leonardo.gui" not in source
    assert "subprocess" not in source
    assert "import requests" not in source
    assert "from requests" not in source
    assert "import aiohttp" not in source
    assert "from aiohttp" not in source
    assert "import websockets" not in source
    assert "from websockets" not in source
