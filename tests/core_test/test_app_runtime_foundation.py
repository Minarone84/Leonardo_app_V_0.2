import asyncio
import json
from dataclasses import replace
from threading import Event

import pytest

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionDirection,
    ConnectionKind,
    ConnectionLifecycleStatus,
    ConnectionProtocol,
    WebSocketChannelDefinition,
)
from leonardo.contracts.core_runtime import (
    CoreRuntimeCommand,
    CoreRuntimeMetadata,
    CoreRuntimeResult,
    CoreRuntimeResultStatus,
)
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
from leonardo.contracts.processes import (
    ProcessKind,
    ProcessLaunchRequest,
    ProcessLifecycleStatus,
)
from leonardo.contracts.runtime import AppLifecycleStatus
from leonardo.contracts.runtime import ServiceLifecycleStatus
from leonardo.contracts.services import ServiceDescriptor, ServiceKind
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


def test_leonardo_app_shutdown_cancels_runtime_work_and_rejects_submissions() -> None:
    app = LeonardoApp()
    started = Event()
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, _progress):
        started.set()
        await asyncio.Event().wait()

    def record_result(result: CoreRuntimeResult) -> None:
        results.append(result)
        received.set()

    context = app.startup()
    context.core_runtime_bridge.start()
    submission = context.core_runtime_bridge.submit_command(
        _core_command("shutdown-command-1"),
        handler,
        result_callback=record_result,
    )
    assert started.wait(2)

    app.shutdown(timeout=1.0, reason="test shutdown")

    assert received.wait(2)
    assert results[0].status is CoreRuntimeResultStatus.CANCELLED
    assert results[0].metadata.operation_id == submission.metadata.operation_id
    assert app.state_store.get_app_status() is AppLifecycleStatus.STOPPED
    assert app.core_runtime_bridge.is_accepting_submissions is False
    assert app.core_runner.is_running is False
    event_types = [event.event_type for event in app.audit_log.snapshot()]
    assert "task.lifecycle.cancelled" in event_types
    assert "operation.lifecycle.cancelled" in event_types
    assert event_types[-1] == "app.lifecycle.changed"

    with pytest.raises(RuntimeError, match="not accepting submissions"):
        app.core_runtime_bridge.submit_command(
            _core_command("after-shutdown-command-1"),
            lambda _command, _progress: None,
        )


def test_leonardo_app_shutdown_preserves_failed_startup_state() -> None:
    class FailingApp(LeonardoApp):
        def _register_runtime_contracts(self) -> None:
            raise RuntimeError("contract registration failed")

    app = FailingApp()

    with pytest.raises(RuntimeError, match="contract registration failed"):
        app.startup()

    app.shutdown()

    assert app.state_store.get_app_status() is AppLifecycleStatus.FAILED


def test_leonardo_app_shutdown_reports_structured_runtime_shutdown_failure() -> None:
    app = LeonardoApp()
    app.startup()

    def fail_shutdown(*, timeout: float) -> None:
        raise TimeoutError("task settlement timed out")

    app.core_runtime_bridge.shutdown = fail_shutdown  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="Application shutdown failed"):
        app.shutdown(timeout=0.1, reason="timeout test")

    assert app.state_store.get_app_status() is AppLifecycleStatus.FAILED
    assert any(
        event.category is AuditCategory.ERROR
        and event.event_type == "error.reported"
        and event.message == "Application shutdown step failed: core_runtime"
        for event in app.audit_log.snapshot()
    )
    assert any(
        event.category is AuditCategory.ERROR
        and event.event_type == "error.reported"
        and event.message == "Application shutdown failed"
        for event in app.audit_log.snapshot()
    )


def test_leonardo_app_shutdown_invokes_process_manager_cleanup() -> None:
    handle = _FakeHandle()
    app = LeonardoApp()
    app.process_manager._launcher = _FakeLauncher(handle)  # type: ignore[attr-defined]
    app.startup()
    app.process_manager.launch_process(_process_request())

    app.shutdown()

    assert handle.terminated is True
    process_state = app.state_store.processes_state()[0]
    assert process_state.status is ProcessLifecycleStatus.STOP_REQUESTED


def test_leonardo_app_shutdown_marks_connection_tracking_stopped_only() -> None:
    app = LeonardoApp()
    app.startup()
    app.connection_registry.register_connection(_connection_definition())
    app.connection_registry.register_websocket_channel(_channel_definition())
    app.connection_registry.mark_connection_connected("connection-1")

    app.shutdown()

    assert app.connection_registry.connection_states()[0].status is (
        ConnectionLifecycleStatus.DISCONNECTED
    )
    assert app.connection_registry.websocket_channel_states()[0].status is (
        ConnectionLifecycleStatus.DISCONNECTED
    )
    assert any(
        event.event_type == "connection.lifecycle.disconnected"
        for event in app.audit_log.snapshot()
    )


def test_leonardo_app_shutdown_stops_lifecycle_services_not_capabilities() -> None:
    app = LeonardoApp()
    app.startup()
    app.service_registry.register_service(
        ServiceDescriptor(
            service_id="lifecycle-service",
            kind=ServiceKind.LIFECYCLE,
        ),
        object(),
    )
    app.service_registry.register_service(
        ServiceDescriptor(
            service_id="capability-provider",
            kind=ServiceKind.CAPABILITY,
        ),
        object(),
    )
    app.state_store.register_service_runtime_state(
        "lifecycle-service",
        status=ServiceLifecycleStatus.RUNNING,
    )
    app.state_store.register_service_runtime_state(
        "capability-provider",
        status=ServiceLifecycleStatus.RUNNING,
    )

    app.shutdown()

    service_states = {
        state.service_id: state
        for state in app.state_store.runtime_snapshot().service_states
    }
    assert service_states["lifecycle-service"].status is ServiceLifecycleStatus.STOPPED
    assert service_states["capability-provider"].status is (
        ServiceLifecycleStatus.RUNNING
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


def test_leonardo_app_exposes_populated_download_capability_catalog_without_service_registration() -> None:
    app = LeonardoApp()

    context = app.startup()
    providers = context.download_capability_catalog.list_providers()

    assert isinstance(app.download_capability_catalog, DownloadCapabilityCatalog)
    assert context.download_capability_catalog is app.download_capability_catalog
    assert (
        app.download_execution_manager._capability_catalog  # type: ignore[attr-defined]
        is app.download_capability_catalog
    )
    assert tuple(provider.provider for provider in providers) == ("bybit",)
    assert context.download_capability_catalog.supported_timeframes(
        "bybit",
        "spot",
    ) == (
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
    assert context.service_registry.list_services() == ()


def test_default_app_catalog_blocks_unknown_download_provider_readiness() -> None:
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


def test_default_app_catalog_classifies_valid_bybit_download_ready() -> None:
    app = LeonardoApp()
    context = app.startup()
    context.download_manager.submit_request(
        _download_request(
            source="bybit",
            connection_ref="bybit-spot",
        )
    )

    snapshot = context.download_execution_manager.create_plan("req-app-download")
    updated = context.download_execution_manager.classify_readiness(
        snapshot.plan.plan_id,
    )

    layer = _capability_layer(updated)
    assert updated.plan.phase is DownloadExecutionPhase.READY
    assert layer.status is DownloadPreflightLayerStatus.PASSED
    assert layer.metadata["provider"] == "bybit"
    assert layer.metadata["market"] == "spot"
    assert dict(layer.metadata["provider_intervals"]) == {
        "1m": "1",
        "5m": "5",
    }


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


def _core_command(command_id: str) -> CoreRuntimeCommand:
    return CoreRuntimeCommand(
        command_id=command_id,
        command_type="test.shutdown",
        metadata=CoreRuntimeMetadata(
            action_id="shutdown.test",
            window_id="runtime-test",
            actor_id="admin-dev",
            session_id="session-admin-dev",
            source="unit_test",
            correlation_id="shutdown-corr-1",
        ),
    )


class _FakeHandle:
    def __init__(self) -> None:
        self.pid = 1001
        self.terminated = False

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0


class _FakeLauncher:
    def __init__(self, handle: _FakeHandle) -> None:
        self._handle = handle

    def start(self, _request: ProcessLaunchRequest) -> _FakeHandle:
        return self._handle


def _process_request() -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        process_id="process-1",
        label="Shutdown process",
        command=("python", "-c", "print('ok')"),
        kind=ProcessKind.UTILITY,
    )


def _connection_definition() -> ConnectionDefinition:
    return ConnectionDefinition(
        connection_id="connection-1",
        label="Shutdown connection",
        kind=ConnectionKind.EXTERNAL_SERVICE,
        protocol=ConnectionProtocol.WEBSOCKET,
        direction=ConnectionDirection.OUTBOUND,
    )


def _channel_definition() -> WebSocketChannelDefinition:
    return WebSocketChannelDefinition(
        channel_id="channel-1",
        connection_id="connection-1",
        label="Shutdown channel",
    )


def _download_request(
    *,
    source: str = "binance",
    market: str = "spot",
    timeframes: tuple[str, ...] = ("1m", "5m"),
    connection_ref: str = "binance-spot",
) -> DownloadRequest:
    return DownloadRequest(
        request_id="req-app-download",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        source=source,
        market=market,
        symbols=("BTCUSDT",),
        timeframe_mode=DownloadTimeframeMode.EXPLICIT,
        timeframes=timeframes,
        range_mode=DownloadRangeMode.LATEST,
        requested_by="admin-dev",
        connection_ref=connection_ref,
    )


def _capability_layer(snapshot: object) -> object:
    layers = tuple(
        layer
        for layer in snapshot.preflight_layers
        if layer.layer is DownloadPreflightLayer.CAPABILITY
    )
    assert len(layers) == 1
    return layers[0]
