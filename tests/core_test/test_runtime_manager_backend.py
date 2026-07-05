from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionDirection,
    ConnectionKind,
    ConnectionProtocol,
    WebSocketChannelDefinition,
)
from leonardo.contracts.downloads import (
    DownloadRangeMode,
    DownloadRequest,
    DownloadTimeframeMode,
    DownloadWorkflowKind,
)
from leonardo.contracts.gui import ActionDefinition, ActionKind, WindowDefinition
from leonardo.contracts.inspection import RuntimeHealthStatus, RuntimeSectionStatus
from leonardo.contracts.operations import OperationKind
from leonardo.contracts.processes import ProcessKind, ProcessLaunchRequest
from leonardo.contracts.runtime import AppLifecycleStatus
from leonardo.contracts.services import ServiceDescriptor, ServiceKind
from leonardo.core.app import LeonardoApp
from leonardo.core.audit_log import AuditLog, CompositeAuditSink, InMemoryAuditSink
from leonardo.core.runtime_manager import RuntimeManagerBackend


def test_runtime_manager_snapshot_includes_app_and_session_state() -> None:
    app = LeonardoApp()
    app.startup()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.app_status == AppLifecycleStatus.RUNNING.value
    assert snapshot.app_summary.status is RuntimeSectionStatus.OK
    assert snapshot.session_id == "session-admin-dev"
    assert snapshot.user_id == "admin-dev"
    assert snapshot.username == "Administrator"
    assert snapshot.session_summary.metadata["username"] == "Administrator"


def test_runtime_manager_snapshot_includes_service_summary() -> None:
    app = LeonardoApp()
    app.service_registry.register_service(
        ServiceDescriptor(
            service_id="runtime-inspector",
            kind=ServiceKind.CAPABILITY,
        ),
        object(),
    )

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.services_summary.count == 1
    assert snapshot.services_summary.metadata["service_ids"] == (
        "runtime-inspector",
    )


def test_runtime_manager_snapshot_includes_active_task_without_starting_tasks() -> None:
    app = LeonardoApp()
    app.state_store.task_started(
        task_id="task-1",
        task_name="inspect-runtime",
        metadata={"source": "test"},
    )
    before = app.task_manager.active_tasks()

    snapshot = app.runtime_manager.snapshot()

    assert app.task_manager.active_tasks() == before
    assert snapshot.tasks_summary.count == 1
    assert snapshot.tasks_summary.metadata["task_ids"] == ("task-1",)
    assert snapshot.tasks_summary.metadata["task_names"] == ("inspect-runtime",)


def test_runtime_manager_snapshot_includes_windows_actions_and_operations() -> None:
    app = LeonardoApp()
    app.window_registry.register_window(
        WindowDefinition(
            window_id="runtime-manager",
            title="Runtime Manager",
            window_type="tool",
        )
    )
    app.window_registry.open_window("runtime-manager")
    app.action_registry.register_action(
        ActionDefinition(
            action_id="runtime.refresh",
            label="Refresh",
            kind=ActionKind.BUTTON,
            window_id="runtime-manager",
        )
    )
    app.action_registry.record_trigger(
        "runtime.refresh",
        window_id="runtime-manager",
        actor_id="admin-dev",
        session_id="session-admin-dev",
    )
    operation = app.operation_registry.request_operation(
        operation_kind=OperationKind.USER_WORKFLOW,
        label="Inspect runtime",
        actor_id="admin-dev",
        session_id="session-admin-dev",
        window_id="runtime-manager",
        action_id="runtime.refresh",
    )

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.windows_summary.count == 1
    assert snapshot.windows_summary.metadata["open_window_ids"] == (
        "runtime-manager",
    )
    assert snapshot.actions_summary.count == 1
    assert snapshot.actions_summary.metadata["recent_action_ids"] == (
        "runtime.refresh",
    )
    assert snapshot.operations_summary.count == 1
    assert snapshot.operations_summary.metadata["operation_ids"] == (
        operation.operation_id,
    )


def test_runtime_manager_snapshot_includes_recent_audit_event_previews() -> None:
    app = LeonardoApp()
    app.audit_log.emit(
        AuditEvent(
            event_type="runtime.checked",
            message="Runtime checked",
            severity=AuditSeverity.INFO,
            category=AuditCategory.RUNTIME,
            actor_id="admin-dev",
            session_id="session-admin-dev",
        )
    )

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.audit_summary.count == len(snapshot.recent_audit_events)
    assert snapshot.recent_audit_events[-1].event_type == "runtime.checked"
    assert snapshot.recent_audit_events[-1].actor_id == "admin-dev"


def test_runtime_manager_snapshot_includes_audit_sink_failure_previews() -> None:
    class FailingSink:
        def emit(self, event: AuditEvent) -> AuditEvent:
            raise RuntimeError("sink failed")

    audit_log = AuditLog(
        CompositeAuditSink(
            (
                FailingSink(),
                InMemoryAuditSink(),
            )
        )
    )
    app = LeonardoApp()
    backend = RuntimeManagerBackend(
        state_store=app.state_store,
        session_manager=app.session_manager,
        service_registry=app.service_registry,
        task_manager=app.task_manager,
        process_manager=app.process_manager,
        connection_registry=app.connection_registry,
        window_registry=app.window_registry,
        action_registry=app.action_registry,
        operation_registry=app.operation_registry,
        audit_log=audit_log,
        contract_registry=app.contract_registry,
    )
    audit_log.emit(
        AuditEvent(
            event_type="runtime.checked",
            message="Runtime checked",
            severity=AuditSeverity.INFO,
            category=AuditCategory.RUNTIME,
        )
    )

    snapshot = backend.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.audit_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.audit_sink_failures[0].sink_name == "FailingSink"
    assert snapshot.audit_sink_failures[0].operation == "emit"


def test_runtime_manager_snapshot_includes_contract_registry_summary() -> None:
    app = LeonardoApp()
    app.startup()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.contract_registry.total_contracts == 20
    assert snapshot.contract_registry.active_contracts == 20
    assert snapshot.contracts_summary.count == 20


def test_runtime_manager_snapshot_includes_process_summary() -> None:
    app = LeonardoApp()
    app.state_store.process_starting(
        ProcessLaunchRequest(
            process_id="process-1",
            label="Inspect runtime",
            command=("python", "-c", "print('ok')"),
            kind=ProcessKind.UTILITY,
        )
    )
    app.state_store.process_running("process-1", pid=123)

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.processes_summary.count == 1
    assert snapshot.processes_summary.metadata["process_ids"] == ("process-1",)
    assert snapshot.processes_summary.metadata["process_labels"] == (
        "Inspect runtime",
    )


def test_runtime_manager_snapshot_includes_connection_summary() -> None:
    app = LeonardoApp()
    app.connection_registry.register_connection(
        ConnectionDefinition(
            connection_id="connection-1",
            label="Runtime feed",
            kind=ConnectionKind.EXTERNAL_SERVICE,
            protocol=ConnectionProtocol.WEBSOCKET,
            direction=ConnectionDirection.OUTBOUND,
        )
    )
    app.connection_registry.register_websocket_channel(
        WebSocketChannelDefinition(
            channel_id="channel-1",
            connection_id="connection-1",
            label="Runtime channel",
        )
    )
    app.connection_registry.mark_connection_connected("connection-1")
    app.connection_registry.record_channel_received("channel-1", count=2)

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.connections_summary.count == 1
    assert snapshot.connections_summary.status is RuntimeSectionStatus.OK
    assert snapshot.connections_summary.metadata["connection_ids"] == (
        "connection-1",
    )
    assert snapshot.connections_summary.metadata["connected_count"] == 1
    assert snapshot.connections_summary.metadata["websocket_channel_count"] == 1
    assert snapshot.connections_summary.metadata["channel_received_count"] == 2


def test_runtime_manager_snapshot_includes_empty_download_summary() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.downloads_summary.section_id == "downloads"
    assert snapshot.downloads_summary.status is RuntimeSectionStatus.OK
    assert snapshot.downloads_summary.count == 0
    assert snapshot.downloads_summary.metadata["available"] is True
    assert snapshot.downloads_summary.metadata["total_requests"] == 0
    assert snapshot.downloads_summary.metadata["total_items"] == 0
    assert "downloads" in tuple(
        section.section_id for section in snapshot.sections
    )


def test_runtime_manager_snapshot_includes_empty_download_execution_summary() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.download_execution_summary.section_id == "download_execution"
    assert snapshot.download_execution_summary.status is RuntimeSectionStatus.OK
    assert snapshot.download_execution_summary.count == 0
    assert snapshot.download_execution_summary.message == (
        "0 download execution plans"
    )
    assert snapshot.download_execution_summary.metadata["available"] is True
    assert snapshot.download_execution_summary.metadata["total_plans"] == 0
    assert snapshot.download_execution_summary.metadata["active_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["plan_rows"] == ()
    assert "download_execution" in tuple(
        section.section_id for section in snapshot.sections
    )


def test_runtime_manager_snapshot_reflects_download_manager_state_read_only() -> None:
    app = LeonardoApp()
    app.download_manager.submit_request(
        _download_request(
            symbols=("BTCUSDT", "ETHUSDT"),
            timeframes=("1m", "5m"),
        )
    )
    before_state = (
        app.download_manager.list_requests(),
        app.download_manager.list_preflights(),
        app.download_manager.list_items(),
        app.download_manager.get_summary(),
        app.audit_log.snapshot(),
    )

    snapshot = app.runtime_manager.snapshot()
    after_state = (
        app.download_manager.list_requests(),
        app.download_manager.list_preflights(),
        app.download_manager.list_items(),
        app.download_manager.get_summary(),
        app.audit_log.snapshot(),
    )

    assert after_state == before_state
    assert snapshot.downloads_summary.status is RuntimeSectionStatus.OK
    assert snapshot.downloads_summary.count == 1
    assert snapshot.downloads_summary.message == "1 download request, 4 items"
    assert snapshot.downloads_summary.metadata["total_requests"] == 1
    assert snapshot.downloads_summary.metadata["total_items"] == 4
    assert snapshot.downloads_summary.metadata["validated_count"] == 5
    assert snapshot.downloads_summary.metadata["active_request_ids"] == (
        "req-download",
    )
    assert snapshot.downloads_summary.metadata["active_item_ids"] == (
        "req-download:BTCUSDT:1m",
        "req-download:BTCUSDT:5m",
        "req-download:ETHUSDT:1m",
        "req-download:ETHUSDT:5m",
    )


def test_runtime_manager_snapshot_marks_download_failures_degraded() -> None:
    app = LeonardoApp()
    request = _download_request(
        timeframe_mode=DownloadTimeframeMode.DEFAULT,
        timeframes=(),
    )
    object.__setattr__(request, "timeframe_mode", DownloadTimeframeMode.EXPLICIT)

    app.download_manager.submit_request(request)
    snapshot = app.runtime_manager.snapshot()

    assert snapshot.downloads_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.downloads_summary.metadata["failed_count"] == 1
    assert snapshot.downloads_summary.metadata["preflight_failed_count"] == 1
    assert snapshot.downloads_summary.metadata["failed_request_ids"] == (
        "req-download",
    )


def test_runtime_manager_snapshot_reflects_download_execution_state_read_only() -> None:
    app = LeonardoApp()
    app.download_manager.submit_request(
        _download_request(
            symbols=("BTCUSDT", "ETHUSDT"),
            timeframes=("1m",),
        )
    )
    execution_snapshot = app.download_execution_manager.create_plan("req-download")
    before_state = (
        app.download_execution_manager.list_snapshots(),
        app.download_manager.list_requests(),
        app.download_manager.list_preflights(),
        app.download_manager.list_items(),
        app.audit_log.snapshot(),
    )

    snapshot = app.runtime_manager.snapshot()
    after_state = (
        app.download_execution_manager.list_snapshots(),
        app.download_manager.list_requests(),
        app.download_manager.list_preflights(),
        app.download_manager.list_items(),
        app.audit_log.snapshot(),
    )

    assert after_state == before_state
    assert snapshot.download_execution_summary.status is RuntimeSectionStatus.OK
    assert snapshot.download_execution_summary.count == 1
    assert snapshot.download_execution_summary.metadata["total_plans"] == 1
    assert snapshot.download_execution_summary.metadata["active_plan_ids"] == (
        execution_snapshot.plan.plan_id,
    )
    assert snapshot.download_execution_summary.metadata["failed_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["completed_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["running_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["blocked_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["plan_rows"] == (
        {
            "plan_id": "execution-plan-req-download",
            "request_id": "req-download",
            "phase": "planned",
            "operation_id": None,
            "task_id": None,
            "item_count": 2,
            "preflight_layer_count": 1,
            "progress_percent": None,
            "output_count": 0,
            "error_count": 0,
            "details": "connection_refs=binance-spot",
            "estimated_items": 2,
        },
    )


def test_runtime_manager_snapshot_does_not_create_download_execution_plans() -> None:
    app = LeonardoApp()
    app.download_manager.submit_request(_download_request())
    before_state = (
        app.download_execution_manager.list_snapshots(),
        app.audit_log.snapshot(),
    )

    snapshot = app.runtime_manager.snapshot()
    after_state = (
        app.download_execution_manager.list_snapshots(),
        app.audit_log.snapshot(),
    )

    assert before_state == ((), app.audit_log.snapshot())
    assert after_state == before_state
    assert snapshot.download_execution_summary.count == 0
    assert snapshot.download_execution_summary.metadata["plan_rows"] == ()


def test_runtime_manager_snapshot_degrades_when_connection_degraded() -> None:
    app = LeonardoApp()
    app.connection_registry.register_connection(
        ConnectionDefinition(
            connection_id="connection-1",
            label="Runtime feed",
            kind=ConnectionKind.EXTERNAL_SERVICE,
            protocol=ConnectionProtocol.WEBSOCKET,
            direction=ConnectionDirection.OUTBOUND,
        )
    )
    app.connection_registry.mark_connection_degraded(
        "connection-1",
        last_error_message="Heartbeat late",
    )

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.connections_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.connections_summary.metadata["degraded_count"] == 1


def test_runtime_manager_snapshot_degrades_when_app_failed() -> None:
    app = LeonardoApp()
    app.state_store.set_app_lifecycle_status(AppLifecycleStatus.FAILED)

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.health is RuntimeHealthStatus.ERROR
    assert snapshot.app_summary.status is RuntimeSectionStatus.ERROR


def test_runtime_manager_snapshot_is_defensive_and_read_only() -> None:
    app = LeonardoApp()
    app.window_registry.register_window(
        WindowDefinition(
            window_id="runtime-manager",
            title="Runtime Manager",
            window_type="tool",
        )
    )
    before_events = app.audit_log.snapshot()

    snapshot = app.runtime_manager.snapshot()
    after_snapshot_read_events = app.audit_log.snapshot()
    app.window_registry.open_window("runtime-manager")
    after_snapshot = app.runtime_manager.snapshot()

    assert after_snapshot_read_events == before_events
    assert snapshot.windows_summary.count == 0
    assert after_snapshot.windows_summary.count == 1


def test_leonardo_app_exposes_runtime_manager_backend() -> None:
    app = LeonardoApp()

    assert isinstance(app.runtime_manager, RuntimeManagerBackend)
    assert app.context.runtime_manager is app.runtime_manager


def _download_request(
    *,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    timeframe_mode: DownloadTimeframeMode = DownloadTimeframeMode.EXPLICIT,
    timeframes: tuple[str, ...] = ("1m",),
) -> DownloadRequest:
    return DownloadRequest(
        request_id="req-download",
        workflow_kind=DownloadWorkflowKind.DOWNLOAD_DATA,
        source="binance",
        market="spot",
        symbols=symbols,
        timeframe_mode=timeframe_mode,
        timeframes=timeframes,
        range_mode=DownloadRangeMode.LATEST,
        requested_by="admin-dev",
        connection_ref="binance-spot",
    )
