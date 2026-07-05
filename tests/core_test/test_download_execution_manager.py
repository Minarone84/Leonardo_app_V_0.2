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


def test_mark_ready_updates_retained_snapshot_immutably() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager)
    original = manager.create_plan("req-explicit")

    updated = manager.mark_ready(original.plan.plan_id)

    assert updated is not original
    assert original.plan.phase is DownloadExecutionPhase.PLANNED
    assert original.progress is not None
    assert original.progress.phase is DownloadExecutionPhase.PLANNED
    assert updated.plan.phase is DownloadExecutionPhase.READY
    assert updated.progress is not None
    assert updated.progress.phase is DownloadExecutionPhase.READY
    assert updated.progress.message == (
        "Download execution plan is ready for future execution."
    )
    assert updated.plan.plan_id == original.plan.plan_id
    assert updated.plan.request_id == original.plan.request_id
    assert updated.plan.item_ids == original.plan.item_ids
    assert updated.estimate == original.estimate
    assert updated.outputs == ()
    assert updated.errors == ()
    assert updated.plan.operation_id is None
    assert updated.plan.task_id is None
    assert manager.get_snapshot(original.plan.plan_id) is updated
    assert manager.get_snapshot_for_request("req-explicit") is updated
    assert _download_manager_state(download_manager) == before_state


def test_mark_blocked_updates_snapshot_with_reason() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager)
    original = manager.create_plan("req-explicit")

    updated = manager.mark_blocked(
        original.plan.plan_id,
        "Storage policy is unresolved.",
    )

    assert updated is not original
    assert original.plan.phase is DownloadExecutionPhase.PLANNED
    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress.message == "Storage policy is unresolved."
    assert updated.metadata["lifecycle_reason"] == "Storage policy is unresolved."
    assert updated.metadata["blocked_reason"] == "Storage policy is unresolved."
    assert updated.plan.item_ids == original.plan.item_ids
    assert updated.estimate == original.estimate
    assert updated.outputs == ()
    assert updated.errors == ()
    assert updated.plan.operation_id is None
    assert updated.plan.task_id is None
    assert _download_manager_state(download_manager) == before_state


def test_mark_lifecycle_unknown_plan_fails_clearly() -> None:
    manager = DownloadExecutionManager(DownloadManager())

    with pytest.raises(KeyError, match="Download execution plan is not retained"):
        manager.mark_ready("execution-plan-missing")


def test_mark_lifecycle_rejects_non_planned_transitions() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")

    manager.mark_ready(snapshot.plan.plan_id)
    with pytest.raises(ValueError, match="only planned plans can transition"):
        manager.mark_blocked(snapshot.plan.plan_id, "Late blocker.")

    download_manager.submit_request(_request(request_id="req-blocked"))
    blocked = manager.create_plan("req-blocked")
    manager.mark_blocked(blocked.plan.plan_id, "Missing storage policy.")
    with pytest.raises(ValueError, match="only planned plans can transition"):
        manager.mark_ready(blocked.plan.plan_id)


def test_mark_blocked_rejects_empty_reason() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")

    with pytest.raises(ValueError, match="reason"):
        manager.mark_blocked(snapshot.plan.plan_id, " ")


@pytest.mark.parametrize(
    "timeframe_mode",
    (
        DownloadTimeframeMode.ALL,
        DownloadTimeframeMode.DEFAULT,
        DownloadTimeframeMode.SUPPORTED,
    ),
)
def test_unresolved_timeframe_plan_can_be_marked_blocked_without_fake_items(
    timeframe_mode: DownloadTimeframeMode,
) -> None:
    request_id = f"req-{timeframe_mode.value}"
    download_manager = DownloadManager()
    download_manager.submit_request(
        _request(
            request_id=request_id,
            timeframe_mode=timeframe_mode,
            timeframes=(),
        )
    )
    manager = DownloadExecutionManager(download_manager)
    original = manager.create_plan(request_id)

    updated = manager.mark_blocked(
        original.plan.plan_id,
        "Timeframe expansion is unresolved.",
    )

    assert original.plan.phase is DownloadExecutionPhase.PLANNED
    assert original.plan.item_ids == ()
    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.plan.item_ids == ()
    assert updated.estimate is not None
    assert updated.estimate.estimated_items is None
    assert updated.progress is not None
    assert updated.progress.total_items is None
    assert download_manager.list_items(request_id) == ()


def test_phase_change_emits_optional_audit_event_only_when_injected() -> None:
    audit_log = AuditLog()
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager, audit_log)
    snapshot = manager.create_plan("req-explicit")
    before_events = audit_log.snapshot()

    updated = manager.mark_ready(snapshot.plan.plan_id)

    events = audit_log.snapshot()
    assert len(events) == len(before_events) + 1
    assert events[-1].event_type == "download.execution.phase.changed"
    assert events[-1].payload["plan_id"] == updated.plan.plan_id
    assert events[-1].payload["request_id"] == "req-explicit"
    assert events[-1].payload["old_phase"] == "planned"
    assert events[-1].payload["new_phase"] == "ready"
    assert events[-1].payload["reason"] == (
        "Download execution plan is ready for future execution."
    )


def test_phase_change_without_audit_log_keeps_audit_out_of_band() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")

    updated = manager.mark_ready(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.READY


def test_classify_readiness_marks_valid_explicit_plan_ready_with_audit() -> None:
    audit_log = AuditLog()
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager, audit_log)
    snapshot = manager.create_plan("req-explicit")
    before_events = audit_log.snapshot()

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.READY
    assert updated.progress is not None
    assert updated.progress.phase is DownloadExecutionPhase.READY
    assert updated.progress.message == (
        "Download execution plan is ready for future execution."
    )
    assert updated.plan.item_ids == snapshot.plan.item_ids
    assert updated.outputs == ()
    assert updated.errors == ()
    assert updated.plan.operation_id is None
    assert updated.plan.task_id is None
    assert manager.get_snapshot(snapshot.plan.plan_id) is updated
    assert _download_manager_state(download_manager) == before_state

    events = audit_log.snapshot()
    assert len(events) == len(before_events) + 1
    assert events[-1].event_type == "download.execution.phase.changed"
    assert events[-1].payload["plan_id"] == updated.plan.plan_id
    assert events[-1].payload["request_id"] == "req-explicit"
    assert events[-1].payload["old_phase"] == "planned"
    assert events[-1].payload["new_phase"] == "ready"


def test_classify_readiness_blocks_failed_structural_preflight() -> None:
    download_manager = DownloadManager()
    request = _request(
        request_id="req-invalid",
        timeframe_mode=DownloadTimeframeMode.DEFAULT,
        timeframes=(),
    )
    object.__setattr__(request, "timeframe_mode", DownloadTimeframeMode.EXPLICIT)
    download_manager.submit_request(request)
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-invalid")

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress.message == "Structural preflight failed."
    assert updated.metadata["blocked_reason"] == "Structural preflight failed."
    assert updated.preflight_layers == snapshot.preflight_layers
    assert _download_manager_state(download_manager) == before_state


def test_classify_readiness_blocks_explicit_mode_without_stored_items() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")
    download_manager._item_by_id.clear()  # type: ignore[attr-defined]
    before_state = _download_manager_state(download_manager)

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Explicit timeframe mode has no stored items."
    assert updated.plan.item_ids == snapshot.plan.item_ids
    assert download_manager.list_items("req-explicit") == ()
    assert _download_manager_state(download_manager) == before_state


def test_classify_readiness_blocks_inconsistent_item_state() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")
    download_manager._item_by_id.pop(  # type: ignore[attr-defined]
        "req-explicit:BTCUSDT:1m"
    )
    before_state = _download_manager_state(download_manager)

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Download plan/item state is inconsistent."
    assert updated.plan.item_ids == snapshot.plan.item_ids
    assert _download_manager_state(download_manager) == before_state


@pytest.mark.parametrize(
    "timeframe_mode",
    (
        DownloadTimeframeMode.ALL,
        DownloadTimeframeMode.DEFAULT,
        DownloadTimeframeMode.SUPPORTED,
    ),
)
def test_classify_readiness_blocks_unresolved_timeframe_modes_without_fake_items(
    timeframe_mode: DownloadTimeframeMode,
) -> None:
    request_id = f"req-classify-{timeframe_mode.value}"
    download_manager = DownloadManager()
    download_manager.submit_request(
        _request(
            request_id=request_id,
            timeframe_mode=timeframe_mode,
            timeframes=(),
        )
    )
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan(request_id)

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert snapshot.plan.phase is DownloadExecutionPhase.PLANNED
    assert snapshot.plan.item_ids == ()
    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Timeframe expansion is unresolved."
    assert updated.plan.item_ids == ()
    assert updated.estimate is not None
    assert updated.estimate.estimated_items is None
    assert download_manager.list_items(request_id) == ()
    assert _download_manager_state(download_manager) == before_state


def test_classify_readiness_blocks_unsupported_ohlcv_workflow() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(
        _request(
            request_id="req-ohlcv",
            workflow_kind=DownloadWorkflowKind.OHLCV_MAINTENANCE,
        )
    )
    before_state = _download_manager_state(download_manager)
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-ohlcv")

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Unsupported workflow kind: ohlcv_maintenance."
    assert updated.metadata["blocked_reason"] == (
        "Unsupported workflow kind: ohlcv_maintenance."
    )
    assert updated.outputs == ()
    assert updated.errors == ()
    assert _download_manager_state(download_manager) == before_state


def test_classify_readiness_blocks_missing_request_state() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")
    download_manager._request_by_id.pop("req-explicit")  # type: ignore[attr-defined]
    before_state = _download_manager_state(download_manager)

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Stored download request is unavailable."
    assert _download_manager_state(download_manager) == before_state


def test_classify_readiness_blocks_missing_preflight_state() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    snapshot = manager.create_plan("req-explicit")
    download_manager._preflight_by_request_id.pop(  # type: ignore[attr-defined]
        "req-explicit"
    )
    before_state = _download_manager_state(download_manager)

    updated = manager.classify_readiness(snapshot.plan.plan_id)

    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Stored structural preflight is unavailable."
    assert _download_manager_state(download_manager) == before_state


def test_classify_readiness_rejects_unknown_plan_id() -> None:
    manager = DownloadExecutionManager(DownloadManager())

    with pytest.raises(KeyError, match="Download execution plan is not retained"):
        manager.classify_readiness("execution-plan-missing")


def test_classify_readiness_rejects_non_planned_plan() -> None:
    download_manager = DownloadManager()
    download_manager.submit_request(_request())
    manager = DownloadExecutionManager(download_manager)
    ready = manager.mark_ready(manager.create_plan("req-explicit").plan.plan_id)

    with pytest.raises(ValueError, match="only planned plans can be classified"):
        manager.classify_readiness(ready.plan.plan_id)

    download_manager.submit_request(_request(request_id="req-blocked"))
    blocked = manager.mark_blocked(
        manager.create_plan("req-blocked").plan.plan_id,
        "Missing storage policy.",
    )

    with pytest.raises(ValueError, match="only planned plans can be classified"):
        manager.classify_readiness(blocked.plan.plan_id)


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
    workflow_kind: DownloadWorkflowKind = DownloadWorkflowKind.DOWNLOAD_DATA,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    timeframe_mode: DownloadTimeframeMode = DownloadTimeframeMode.EXPLICIT,
    timeframes: tuple[str, ...] = ("1m", "5m"),
    connection_ref: str | None = "binance-spot",
) -> DownloadRequest:
    return DownloadRequest(
        request_id=request_id,
        workflow_kind=workflow_kind,
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
