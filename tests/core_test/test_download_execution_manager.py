import ast
from pathlib import Path

import pytest

from leonardo.contracts.download_execution import (
    DownloadExecutionPhase,
    DownloadPreflightLayer,
    DownloadPreflightLayerStatus,
)
from leonardo.contracts.downloads import (
    DownloadConflictPolicy,
    DownloadPriority,
    DownloadRangeMode,
    DownloadRequest,
    DownloadTimeframeMode,
    DownloadWorkflowKind,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.download_execution_manager import DownloadExecutionManager
from leonardo.core.download_manager import DownloadManager


_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXECUTION_MANAGER_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "core" / "download_execution_manager.py"
)


def test_create_plan_from_submitted_explicit_download_request() -> None:
    download_manager = DownloadManager()
    request = _request()
    download_manager.submit_request(request)
    manager = DownloadExecutionManager(download_manager)

    snapshot = manager.create_plan("req-explicit")

    assert snapshot.plan.plan_id == "execution-plan-req-explicit"
    assert snapshot.plan.request_id == "req-explicit"
    assert snapshot.plan.workflow_kind == "download_data"
    assert snapshot.plan.phase is DownloadExecutionPhase.PLANNED
    assert snapshot.plan.operation_id is None
    assert snapshot.plan.task_id is None
    assert snapshot.plan.connection_refs == ("binance-spot",)
    assert snapshot.plan.item_ids == (
        "req-explicit:BTCUSDT:1m",
        "req-explicit:BTCUSDT:5m",
        "req-explicit:ETHUSDT:1m",
        "req-explicit:ETHUSDT:5m",
    )
    assert snapshot.estimate is not None
    assert snapshot.estimate.estimated_items == 4
    assert snapshot.progress is not None
    assert snapshot.progress.request_id == "req-explicit"
    assert snapshot.progress.phase is DownloadExecutionPhase.PLANNED
    assert snapshot.outputs == ()
    assert snapshot.errors == ()
    assert manager.get_snapshot(snapshot.plan.plan_id) is snapshot
    assert manager.get_snapshot_for_request("req-explicit") is snapshot
    assert manager.list_snapshots() == (snapshot,)


def test_create_plan_does_not_execute_or_mutate_download_manager_state() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager)

    snapshot = manager.create_plan("req-explicit")

    assert _download_manager_state(download_manager) == before_state
    assert snapshot.outputs == ()
    assert snapshot.errors == ()
    assert snapshot.progress is not None
    assert snapshot.progress.completed_items == 0
    assert snapshot.progress.running_items == 0
    assert snapshot.progress.rows_downloaded is None
    assert snapshot.progress.candles_downloaded is None
    assert snapshot.progress.pages_fetched is None


def test_missing_request_raises_key_error_without_creating_plan() -> None:
    manager = DownloadExecutionManager(DownloadManager())

    with pytest.raises(KeyError, match="Download request is not submitted"):
        manager.create_plan("missing-request")

    assert manager.list_snapshots() == ()
    assert manager.get_snapshot_for_request("missing-request") is None


def test_duplicate_create_plan_returns_existing_snapshot() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)

    first = manager.create_plan("req-explicit")
    second = manager.create_plan("req-explicit")

    assert second is first
    assert manager.list_snapshots() == (first,)


def test_failed_submitted_request_creates_failed_structural_layer() -> None:
    download_manager = DownloadManager()
    request = _request(
        request_id="req-invalid",
        timeframe_mode=DownloadTimeframeMode.DEFAULT,
        timeframes=(),
    )
    object.__setattr__(request, "timeframe_mode", DownloadTimeframeMode.EXPLICIT)
    preflight = download_manager.submit_request(request)
    manager = DownloadExecutionManager(download_manager)

    snapshot = manager.create_plan("req-invalid")

    assert preflight.can_run is False
    assert snapshot.plan.phase is DownloadExecutionPhase.PLANNED
    assert snapshot.plan.item_ids == ()
    assert snapshot.estimate is not None
    assert snapshot.estimate.estimated_items == 0
    assert len(snapshot.preflight_layers) == 1
    layer = snapshot.preflight_layers[0]
    assert layer.layer is DownloadPreflightLayer.STRUCTURAL
    assert layer.status is DownloadPreflightLayerStatus.FAILED
    assert layer.can_continue is False
    assert layer.issues == ("Explicit timeframe mode requires at least one timeframe.",)
    assert layer.metadata["issue_codes"] == ("missing_timeframes",)


def test_unresolved_all_timeframe_request_creates_plan_without_fake_items() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(
        _request(
            request_id="req-all",
            timeframe_mode=DownloadTimeframeMode.ALL,
            timeframes=(),
        )
    )
    manager = DownloadExecutionManager(download_manager)

    snapshot = manager.create_plan("req-all")

    assert snapshot.plan.item_ids == ()
    assert snapshot.estimate is not None
    assert snapshot.estimate.estimated_items is None
    assert snapshot.progress is not None
    assert snapshot.progress.total_items is None


def test_plan_creation_emits_optional_audit_event_only_when_injected() -> None:
    audit_log = AuditLog()
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    before_events = audit_log.snapshot()
    manager = DownloadExecutionManager(download_manager, audit_log)

    snapshot = manager.create_plan("req-explicit")

    events = audit_log.snapshot()
    assert len(events) == len(before_events) + 1
    assert events[-1].event_type == "download.execution.plan.created"
    assert events[-1].payload["plan_id"] == snapshot.plan.plan_id
    assert events[-1].payload["request_id"] == "req-explicit"
    assert events[-1].payload["phase"] == "planned"


def test_plan_creation_without_audit_log_keeps_audit_out_of_band() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)

    snapshot = manager.create_plan("req-explicit")

    assert snapshot.plan.request_id == "req-explicit"


def test_manager_constructor_requires_download_manager() -> None:
    with pytest.raises(TypeError, match="download_manager"):
        DownloadExecutionManager(object())  # type: ignore[arg-type]


def test_core_execution_manager_imports_no_gui_or_runtime_execution_owners() -> None:
    source = _EXECUTION_MANAGER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")

    blocked_imports = (
        "leonardo.gui",
        "leonardo.core.task_manager",
        "leonardo.core.operation_registry",
        "leonardo.core.process_manager",
        "leonardo.core.connection_registry",
        "leonardo.core.runtime_manager",
        "leonardo.data",
        "adapter",
    )
    assert all(
        blocked not in imported_module
        for blocked in blocked_imports
        for imported_module in modules
    )


def test_core_execution_manager_has_no_process_network_or_file_behavior() -> None:
    source = _EXECUTION_MANAGER_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket.",
        "sub" + "process",
        "shell" + "=True",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
        "to" + "_csv",
        "to" + "_parquet",
    )

    for token in blocked_tokens:
        assert token not in source


def _request(
    *,
    request_id: str = "req-explicit",
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    timeframe_mode: DownloadTimeframeMode = DownloadTimeframeMode.EXPLICIT,
    timeframes: tuple[str, ...] = ("1m", "5m"),
    connection_ref: str | None = "binance-spot",
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
        metadata={"profile": "default"},
    )


def _download_manager_state(manager: DownloadManager) -> tuple[object, ...]:
    return (
        manager.list_requests(),
        manager.list_preflights(),
        manager.list_items(),
        manager.get_summary(),
    )
