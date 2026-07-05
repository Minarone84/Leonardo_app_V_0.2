import json
from dataclasses import replace

import pytest

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.downloads import (
    DownloadRangeMode,
    DownloadRequest,
    DownloadStatus,
    DownloadTimeframeMode,
    DownloadWorkflowKind,
)
from leonardo.contracts.download_execution import (
    DownloadExecutionPhase,
    DownloadPreflightLayer,
    DownloadPreflightLayerStatus,
)
from leonardo.contracts.runtime import AppLifecycleStatus
from leonardo.core.app import LeonardoApp
from leonardo.core.config import load_default_config
from leonardo.core.download_capability_catalog import DownloadCapabilityCatalog
from leonardo.core.download_execution_manager import DownloadExecutionManager
from leonardo.core.download_manager import DownloadManager


def test_default_config_resolves_runtime_paths_without_creating_directories(tmp_path) -> None:
    config = load_default_config(tmp_path)

    assert config.paths.repo_root == tmp_path.resolve()
    assert config.paths.runs_dir == tmp_path / "runs"
    assert config.paths.historical_data_dir == tmp_path / "historical_data"
    assert config.paths.tmp_dir == tmp_path / "tmp"
    assert config.audit.jsonl_path == tmp_path / "runs" / "audit.jsonl"
    assert not config.paths.runs_dir.exists()


def test_default_config_keeps_durable_audit_disabled(tmp_path) -> None:
    config = load_default_config(tmp_path)
    app = LeonardoApp(config)
    event = _audit_event("runtime.memory_only_checked")

    app.audit_log.emit(event)
    app.shutdown()

    assert event in app.audit_log.snapshot()
    assert config.audit.jsonl_path is not None
    assert not config.audit.jsonl_path.exists()
    assert not config.paths.runs_dir.exists()


def test_dev_config_writes_jsonl_audit_under_runs_dir(tmp_path) -> None:
    default_config = load_default_config(tmp_path)
    config = replace(
        default_config,
        audit=replace(default_config.audit, jsonl_enabled=True),
    )

    assert config.audit.jsonl_path == config.paths.runs_dir / "audit.jsonl"
    assert not config.paths.runs_dir.exists()

    app = LeonardoApp(config)
    event = _audit_event("runtime.dev_jsonl_checked")

    app.audit_log.emit(event)
    app.shutdown()

    assert event in app.audit_log.snapshot()
    assert config.audit.jsonl_path is not None
    payloads = [
        json.loads(line)
        for line in config.audit.jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(payload["event_id"] == event.event_id for payload in payloads)
    assert any(payload["event_type"] == event.event_type for payload in payloads)


def test_durable_audit_requires_explicit_jsonl_path(tmp_path) -> None:
    default_config = load_default_config(tmp_path)
    config = replace(
        default_config,
        audit=replace(
            default_config.audit,
            jsonl_enabled=True,
            jsonl_path=None,
        ),
    )

    with pytest.raises(
        ValueError,
        match="audit.jsonl_path must be configured when JSONL audit is enabled",
    ):
        LeonardoApp(config)


def test_leonardo_app_startup_and_shutdown_transition_state() -> None:
    app = LeonardoApp()

    context = app.startup()

    assert context is app.context
    assert app.state_store.get_app_status() is AppLifecycleStatus.RUNNING
    assert app.contract_registry.get_contract(
        "leonardo.runtime.app_state",
        "1.0",
    ) is not None
    assert app.contract_registry.get_contract(
        "leonardo.runtime.task_state",
        "1.0",
    ) is not None
    assert app.contract_registry.get_contract(
        "leonardo.processes.runtime_state",
        "1.0",
    ) is not None
    assert app.contract_registry.get_contract(
        "leonardo.connections.runtime_state",
        "1.0",
    ) is not None
    assert app.contract_registry.get_contract(
        "leonardo.gui.window_definition",
        "1.0",
    ) is not None
    assert app.contract_registry.get_contract(
        "leonardo.operations.operation_state",
        "1.0",
    ) is not None
    assert context.task_manager is app.task_manager
    assert context.process_manager is app.process_manager
    assert context.connection_registry is app.connection_registry
    assert context.window_registry is app.window_registry
    assert context.action_registry is app.action_registry
    assert context.operation_registry is app.operation_registry
    assert context.download_capability_catalog is app.download_capability_catalog
    assert context.download_manager is app.download_manager
    assert context.download_execution_manager is app.download_execution_manager
    assert context.runtime_manager is app.runtime_manager
    assert app.process_manager.active_processes() == ()
    assert app.connection_registry.connection_states() == ()
    assert app.connection_registry.websocket_channel_states() == ()

    app.shutdown()
    app.shutdown()

    assert app.state_store.get_app_status() is AppLifecycleStatus.STOPPED


def test_leonardo_app_startup_failure_sets_failed_state_and_routes_error() -> None:
    class FailingApp(LeonardoApp):
        def _register_runtime_contracts(self) -> None:
            raise RuntimeError("contract registration failed")

    app = FailingApp()

    with pytest.raises(RuntimeError, match="contract registration failed"):
        app.startup()

    assert app.state_store.get_app_status() is AppLifecycleStatus.FAILED
    assert any(
        event.category is AuditCategory.ERROR
        and event.event_type == "error.reported"
        for event in app.audit_log.snapshot()
    )


def test_leonardo_app_exposes_download_manager_without_service_registration() -> None:
    app = LeonardoApp()

    context = app.startup()

    assert isinstance(app.download_manager, DownloadManager)
    assert context.download_manager is app.download_manager
    assert context.download_manager.get_summary().total_requests == 0
    assert context.service_registry.list_services() == ()


def test_leonardo_app_exposes_download_execution_manager_without_service_registration() -> None:
    app = LeonardoApp()

    context = app.startup()

    assert isinstance(app.download_execution_manager, DownloadExecutionManager)
    assert context.download_execution_manager is app.download_execution_manager
    assert context.download_execution_manager.list_snapshots() == ()
    assert context.service_registry.list_services() == ()


def test_leonardo_app_exposes_empty_download_capability_catalog_without_service_registration() -> None:
    app = LeonardoApp()

    context = app.startup()

    assert isinstance(app.download_capability_catalog, DownloadCapabilityCatalog)
    assert context.download_capability_catalog is app.download_capability_catalog
    assert (
        app.download_execution_manager._capability_catalog  # type: ignore[attr-defined]
        is app.download_capability_catalog
    )
    assert context.download_capability_catalog.list_providers() == ()
    assert context.service_registry.list_services() == ()


def test_default_empty_app_catalog_blocks_download_execution_readiness() -> None:
    app = LeonardoApp()
    context = app.startup()
    context.download_manager.submit_request(_download_request())
    before_items = context.download_manager.list_items("req-app-download")

    snapshot = context.download_execution_manager.create_plan("req-app-download")
    updated = context.download_execution_manager.classify_readiness(
        snapshot.plan.plan_id,
    )

    layer = _capability_layer(updated)
    assert updated.plan.phase is DownloadExecutionPhase.BLOCKED
    assert updated.progress is not None
    assert updated.progress.message == "Unknown provider: binance."
    assert layer.status is DownloadPreflightLayerStatus.BLOCKED
    assert layer.issues == ("Unknown provider: binance.",)
    assert context.download_manager.list_items("req-app-download") == before_items
    assert context.service_registry.list_services() == ()


def test_download_manager_can_be_used_through_app_context_without_gui(tmp_path) -> None:
    config = load_default_config(tmp_path)
    app = LeonardoApp(config)

    context = app.startup()
    preflight = context.download_manager.submit_request(_download_request())
    app.shutdown()

    assert preflight.status is DownloadStatus.VALIDATED
    assert preflight.can_run is True
    assert context.download_manager.list_requests() == (_download_request(),)
    assert len(context.download_manager.list_items("req-app-download")) == 2
    assert not config.paths.runs_dir.exists()
    assert not config.paths.historical_data_dir.exists()
    assert not config.paths.tmp_dir.exists()
    assert config.audit.jsonl_path is not None
    assert not config.audit.jsonl_path.exists()


def test_download_execution_manager_uses_app_owned_download_manager() -> None:
    app = LeonardoApp()
    context = app.startup()

    preflight = app.download_manager.submit_request(_download_request())
    snapshot = context.download_execution_manager.create_plan("req-app-download")

    assert preflight.can_run is True
    assert snapshot.plan.request_id == "req-app-download"
    assert snapshot.plan.item_ids == (
        "req-app-download:BTCUSDT:1m",
        "req-app-download:BTCUSDT:5m",
    )
    assert snapshot.estimate is not None
    assert snapshot.estimate.estimated_items == 2
    assert app.download_execution_manager.get_snapshot(
        "execution-plan-req-app-download",
    ) is snapshot


def test_app_injected_audit_log_receives_download_manager_events() -> None:
    app = LeonardoApp()
    context = app.startup()

    context.download_manager.submit_request(_download_request())

    event_types = [event.event_type for event in app.audit_log.snapshot()]
    assert "download.request.submitted" in event_types
    assert "download.preflight.completed" in event_types


def test_app_injected_audit_log_receives_download_execution_plan_event() -> None:
    app = LeonardoApp()
    context = app.startup()

    context.download_manager.submit_request(_download_request())
    context.download_execution_manager.create_plan("req-app-download")

    event_types = [event.event_type for event in app.audit_log.snapshot()]
    assert "download.execution.plan.created" in event_types


def _audit_event(event_type: str) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        message="Runtime audit checked",
        severity=AuditSeverity.INFO,
        category=AuditCategory.RUNTIME,
    )


def _download_request() -> DownloadRequest:
    return DownloadRequest(
        request_id="req-app-download",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        source="binance",
        market="spot",
        symbols=("BTCUSDT",),
        timeframe_mode=DownloadTimeframeMode.EXPLICIT,
        timeframes=("1m", "5m"),
        range_mode=DownloadRangeMode.LATEST,
        requested_by="admin-dev",
        connection_ref="binance-spot",
    )


def _capability_layer(snapshot: object) -> object:
    layers = tuple(
        layer
        for layer in snapshot.preflight_layers
        if layer.layer is DownloadPreflightLayer.CAPABILITY
    )
    assert len(layers) == 1
    return layers[0]
