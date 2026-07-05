import ast
from pathlib import Path

import pytest

from leonardo.contracts.downloads import (
    DownloadConflictPolicy,
    DownloadPriority,
    DownloadRangeMode,
    DownloadRequest,
    DownloadStatus,
    DownloadTimeframeMode,
    DownloadWorkflowKind,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.download_manager import DownloadManager


def _request(
    *,
    request_id: str = "req-explicit",
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    timeframe_mode: DownloadTimeframeMode = DownloadTimeframeMode.EXPLICIT,
    timeframes: tuple[str, ...] = ("1m", "5m"),
    connection_ref: str | None = "binance-spot",
    websocket_required: bool = False,
) -> DownloadRequest:
    return DownloadRequest(
        request_id=request_id,
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        batch_id="batch-1",
        source="binance",
        market="spot",
        symbols=symbols,
        timeframe_mode=timeframe_mode,
        timeframes=timeframes,
        range_mode=DownloadRangeMode.LATEST,
        conflict_policy=DownloadConflictPolicy.SKIP_EXISTING,
        priority=DownloadPriority.NORMAL,
        requested_by="admin-dev",
        correlation_id=f"corr-{request_id}",
        connection_ref=connection_ref,
        websocket_required=websocket_required,
        tags=("dev",),
        metadata={"profile": "default", "nested": {"symbols": ["BTCUSDT"]}},
    )


def _explicit_request_without_timeframes() -> DownloadRequest:
    request = _request(
        request_id="req-invalid",
        timeframe_mode=DownloadTimeframeMode.DEFAULT,
        timeframes=(),
    )
    object.__setattr__(request, "timeframe_mode", DownloadTimeframeMode.EXPLICIT)
    return request


def _request_without_symbols() -> DownloadRequest:
    request = _request(request_id="req-no-symbols")
    object.__setattr__(request, "symbols", ())
    return request


def _manager_state(manager: DownloadManager) -> tuple[object, ...]:
    return (
        manager.list_requests(),
        manager.list_preflights(),
        manager.list_items(),
        manager.get_summary(),
    )


def test_preview_explicit_request_returns_preflight_without_storing_state() -> None:
    manager = DownloadManager()
    request = _request()
    before_state = _manager_state(manager)

    preflight = manager.preview_request(request)

    assert preflight.status is DownloadStatus.VALIDATED
    assert preflight.can_run is True
    assert preflight.required_connections == ("binance-spot",)
    assert preflight.estimated_items == 4
    assert preflight.estimated_symbols == 2
    assert preflight.estimated_timeframes == 2
    assert preflight.issues == ()
    assert _manager_state(manager) == before_state


def test_preview_all_timeframe_request_returns_unresolved_estimates_only() -> None:
    manager = DownloadManager()
    request = _request(
        request_id="req-all",
        timeframe_mode=DownloadTimeframeMode.ALL,
        timeframes=(),
    )
    before_state = _manager_state(manager)

    preflight = manager.preview_request(request)

    assert preflight.status is DownloadStatus.VALIDATED
    assert preflight.can_run is True
    assert preflight.estimated_symbols == 2
    assert preflight.estimated_items is None
    assert preflight.estimated_timeframes is None
    assert manager.list_items("req-all") == ()
    assert _manager_state(manager) == before_state


def test_preview_invalid_explicit_request_reports_issues_without_storing_state() -> None:
    manager = DownloadManager()
    request = _explicit_request_without_timeframes()
    before_state = _manager_state(manager)

    preflight = manager.preview_request(request)

    assert preflight.status is DownloadStatus.FAILED
    assert preflight.can_run is False
    assert preflight.estimated_items == 0
    assert [issue.code for issue in preflight.issues] == ["missing_timeframes"]
    assert _manager_state(manager) == before_state


def test_preview_duplicate_request_id_reports_issue_without_mutating_state() -> None:
    manager = DownloadManager()
    original = _request()
    duplicate = _request(symbols=("SOLUSDT",), timeframes=("15m",))
    manager.submit_request(original)
    before_state = _manager_state(manager)

    preflight = manager.preview_request(duplicate)

    assert preflight.status is DownloadStatus.FAILED
    assert preflight.can_run is False
    assert [issue.code for issue in preflight.issues] == ["duplicate_request_id"]
    assert preflight.issues[0].field == "request_id"
    assert manager.get_request("req-explicit") is original
    assert _manager_state(manager) == before_state


def test_preview_request_emits_no_audit_events() -> None:
    audit_log = AuditLog()
    manager = DownloadManager(audit_log)
    before_events = audit_log.snapshot()

    preflight = manager.preview_request(_request())

    assert preflight.status is DownloadStatus.VALIDATED
    assert audit_log.snapshot() == before_events


def test_submit_explicit_request_creates_preflight_and_items() -> None:
    manager = DownloadManager()
    request = _request()

    preflight = manager.submit_request(request)

    assert preflight.status is DownloadStatus.VALIDATED
    assert preflight.can_run is True
    assert preflight.required_connections == ("binance-spot",)
    assert preflight.estimated_items == 4
    assert preflight.estimated_symbols == 2
    assert preflight.estimated_timeframes == 2
    assert manager.get_request("req-explicit") is request

    items = manager.list_items("req-explicit")
    assert [item.item_id for item in items] == [
        "req-explicit:BTCUSDT:1m",
        "req-explicit:BTCUSDT:5m",
        "req-explicit:ETHUSDT:1m",
        "req-explicit:ETHUSDT:5m",
    ]
    assert all(item.status is DownloadStatus.VALIDATED for item in items)
    assert items[0].source == "binance"
    assert items[0].market == "spot"
    assert items[0].connection_id == "binance-spot"
    assert items[0].metadata["workflow_kind"] == "download_data"
    assert items[0].metadata["symbol"] == "BTCUSDT"
    assert items[0].metadata["timeframe"] == "1m"


def test_all_timeframe_request_creates_no_fake_items() -> None:
    manager = DownloadManager()
    request = _request(
        request_id="req-all",
        timeframe_mode=DownloadTimeframeMode.ALL,
        timeframes=(),
    )

    preflight = manager.submit_request(request)

    assert preflight.status is DownloadStatus.VALIDATED
    assert preflight.can_run is True
    assert preflight.estimated_items is None
    assert preflight.estimated_timeframes is None
    assert manager.get_request("req-all") is request
    assert manager.list_items("req-all") == ()


@pytest.mark.parametrize(
    "timeframe_mode",
    (DownloadTimeframeMode.DEFAULT, DownloadTimeframeMode.SUPPORTED),
)
def test_unresolved_timeframe_modes_create_no_fake_items(
    timeframe_mode: DownloadTimeframeMode,
) -> None:
    manager = DownloadManager()
    request = _request(
        request_id=f"req-{timeframe_mode.value}",
        timeframe_mode=timeframe_mode,
        timeframes=(),
    )

    preflight = manager.submit_request(request)

    assert preflight.status is DownloadStatus.VALIDATED
    assert preflight.can_run is True
    assert preflight.estimated_items is None
    assert manager.list_items(request.request_id) == ()


def test_invalid_explicit_request_is_stored_with_failed_preflight() -> None:
    manager = DownloadManager()
    request = _explicit_request_without_timeframes()

    preflight = manager.submit_request(request)

    assert preflight.status is DownloadStatus.FAILED
    assert preflight.can_run is False
    assert preflight.estimated_items == 0
    assert [issue.code for issue in preflight.issues] == ["missing_timeframes"]
    assert manager.get_request("req-invalid") is request
    assert manager.get_preflight("req-invalid") is preflight
    assert manager.list_items("req-invalid") == ()


def test_invalid_request_without_symbols_is_stored_with_failed_preflight() -> None:
    manager = DownloadManager()
    request = _request_without_symbols()

    preflight = manager.submit_request(request)

    assert preflight.status is DownloadStatus.FAILED
    assert preflight.can_run is False
    assert preflight.estimated_symbols == 0
    assert [issue.code for issue in preflight.issues] == ["missing_symbols"]
    assert manager.get_request("req-no-symbols") is request
    assert manager.list_items("req-no-symbols") == ()


def test_duplicate_request_id_is_rejected_without_state_overwrite() -> None:
    manager = DownloadManager()
    original = _request()
    duplicate = _request(symbols=("SOLUSDT",), timeframes=("15m",))

    manager.submit_request(original)
    with pytest.raises(ValueError, match="already submitted"):
        manager.submit_request(duplicate)

    assert manager.get_request("req-explicit") is original
    assert len(manager.list_items("req-explicit")) == 4


def test_get_and_list_request_and_preflight_state() -> None:
    manager = DownloadManager()
    request_b = _request(request_id="req-b")
    request_a = _request(request_id="req-a")

    preflight_b = manager.submit_request(request_b)
    preflight_a = manager.submit_request(request_a)

    assert manager.get_request("missing") is None
    assert manager.get_preflight("missing") is None
    assert manager.list_requests() == (request_a, request_b)
    assert manager.list_preflights() == (preflight_a, preflight_b)


def test_list_items_globally_and_by_request() -> None:
    manager = DownloadManager()
    request_a = _request(request_id="req-a", symbols=("BTCUSDT",))
    request_b = _request(request_id="req-b", symbols=("ETHUSDT",))
    request_all = _request(
        request_id="req-all",
        timeframe_mode=DownloadTimeframeMode.ALL,
        timeframes=(),
    )

    manager.submit_request(request_a)
    manager.submit_request(request_b)
    manager.submit_request(request_all)

    assert [item.item_id for item in manager.list_items("req-a")] == [
        "req-a:BTCUSDT:1m",
        "req-a:BTCUSDT:5m",
    ]
    assert [item.item_id for item in manager.list_items("req-all")] == []
    assert [item.item_id for item in manager.list_items()] == [
        "req-a:BTCUSDT:1m",
        "req-a:BTCUSDT:5m",
        "req-b:ETHUSDT:1m",
        "req-b:ETHUSDT:5m",
    ]


def test_summary_counts_valid_failed_and_unresolved_preflight_state() -> None:
    manager = DownloadManager()
    manager.submit_request(_request(request_id="req-explicit"))
    manager.submit_request(_explicit_request_without_timeframes())
    manager.submit_request(
        _request(
            request_id="req-all",
            timeframe_mode=DownloadTimeframeMode.ALL,
            timeframes=(),
            websocket_required=True,
        )
    )

    summary = manager.get_summary()

    assert summary.total_requests == 3
    assert summary.total_items == 4
    assert summary.validated_count == 6
    assert summary.failed_count == 1
    assert summary.active_request_ids == ("req-all", "req-explicit")
    assert summary.failed_request_ids == ("req-invalid",)
    assert summary.queued_request_ids == ()
    assert summary.active_item_ids == (
        "req-explicit:BTCUSDT:1m",
        "req-explicit:BTCUSDT:5m",
        "req-explicit:ETHUSDT:1m",
        "req-explicit:ETHUSDT:5m",
    )
    assert summary.failed_item_ids == ()
    assert summary.preflight_failed_count == 1
    assert summary.websocket_required_count == 1
    assert summary.connection_blocked_count == 0


def test_metadata_is_preserved_and_traceable() -> None:
    manager = DownloadManager()
    request = _request()

    manager.submit_request(request)
    stored = manager.get_request("req-explicit")
    item = manager.list_items("req-explicit")[0]

    assert stored is request
    assert stored.metadata["profile"] == "default"
    assert stored.metadata["nested"]["symbols"] == ("BTCUSDT",)
    assert item.metadata["request_id"] == "req-explicit"
    assert item.metadata["batch_id"] == "batch-1"
    assert item.metadata["source"] == "binance"
    assert item.metadata["market"] == "spot"
    assert item.metadata["connection_ref"] == "binance-spot"
    assert item.metadata["websocket_required"] is False


def test_audit_events_are_emitted_when_audit_log_is_injected() -> None:
    audit_log = AuditLog()
    manager = DownloadManager(audit_log)

    preflight = manager.submit_request(_request())

    events = audit_log.snapshot()
    assert [event.event_type for event in events] == [
        "download.request.submitted",
        "download.preflight.completed",
    ]
    assert events[0].actor_id == "admin-dev"
    assert events[0].connection_id == "binance-spot"
    assert events[0].payload["request_id"] == "req-explicit"
    assert events[1].payload["status"] == preflight.status.value
    assert events[1].payload["can_run"] is True


def test_download_manager_has_no_execution_or_gui_imports() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "leonardo"
        / "core"
        / "download_manager.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")

    blocked_imports = (
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket",
        "sub" + "process",
        "leonardo.gui",
        "leonardo.data",
        "adapter",
    )
    assert all(
        blocked not in imported_module
        for blocked in blocked_imports
        for imported_module in modules
    )
    assert "write_text(" not in source
    assert "open(" not in source
