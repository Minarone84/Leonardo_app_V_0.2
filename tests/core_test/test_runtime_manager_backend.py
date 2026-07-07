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
from leonardo.contracts.download_execution import (
    DownloadPreflightLayer,
    DownloadPreflightLayerStatus,
)
from leonardo.contracts.gui import ActionDefinition, ActionKind, WindowDefinition
from leonardo.contracts.inspection import (
    DownloadDataRuntimeSummary,
    DownloadDataRuntimeSummaryStatus,
    ProviderRuntimeSummary,
    ProviderRuntimeSummaryStatus,
    RuntimeHealthStatus,
    RuntimeSectionStatus,
    SuiteRuntimeSummary,
    SuiteRuntimeSummaryStatus,
)
from leonardo.contracts.object_map import (
    ObjectMapProviderDescriptor,
    ObjectMapSection,
    ObjectMapSnapshot,
)
from leonardo.contracts.operations import OperationKind
from leonardo.contracts.processes import ProcessKind, ProcessLaunchRequest
from leonardo.contracts.runtime import AppLifecycleStatus
from leonardo.contracts.services import ServiceDescriptor, ServiceKind
from leonardo.contracts.traceable_object import (
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
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
    assert snapshot.tasks_summary.metadata["operation_ids"] == (None,)
    assert snapshot.tasks_summary.metadata["correlation_ids"] == (None,)


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
    app.operation_registry.mark_running(operation.operation_id, task_id="task-1")

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
    assert snapshot.operations_summary.metadata["task_ids"] == ("task-1",)


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

    assert snapshot.contract_registry.total_contracts == 28
    assert snapshot.contract_registry.active_contracts == 28
    assert snapshot.contracts_summary.count == 28
    assert app.contract_registry.get_contract(
        "leonardo.core_runtime.command",
        "1.0",
    ) is not None


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


def test_runtime_manager_snapshot_includes_unavailable_object_map_summary() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.object_map_summary.section_id == "object_map"
    assert snapshot.object_map_summary.status is RuntimeSectionStatus.OK
    assert snapshot.object_map_summary.count == 0
    assert snapshot.object_map_summary.metadata["available"] is False
    assert snapshot.object_map_summary.metadata["provider_count"] == 0
    assert snapshot.object_map_summary.metadata["section_count"] == 0
    assert snapshot.object_map_summary.metadata["degraded"] is False
    assert "object_map" in tuple(section.section_id for section in snapshot.sections)


def test_runtime_manager_snapshot_includes_unavailable_suite_runtime_summary() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.suite_runtime_summary.section_id == "suite_runtime"
    assert snapshot.suite_runtime_summary.status is RuntimeSectionStatus.OK
    assert snapshot.suite_runtime_summary.count == 0
    assert snapshot.suite_runtime_summary.metadata["available"] is False
    assert snapshot.suite_runtime_summary.metadata["summary_count"] == 0
    assert snapshot.suite_runtime_summary.metadata["suite_count"] == 0
    assert snapshot.suite_runtime_summary.metadata["area_count"] == 0
    assert snapshot.suite_runtime_summary.metadata["degraded"] is False
    assert "suite_runtime" in tuple(section.section_id for section in snapshot.sections)


def test_runtime_manager_summarizes_injected_suite_runtime_summaries_read_only() -> None:
    app = LeonardoApp()
    suite_summary = SuiteRuntimeSummary(
        suite_id="data_manager",
        area_id=None,
        display_name="Data Manager",
        status=SuiteRuntimeSummaryStatus.OK,
        module_count=2,
        active_operation_count=1,
        active_task_count=3,
        object_map_section_count=1,
        warning_count=1,
        warnings=("Suite summary is incomplete.",),
        last_activity_at="2026-07-07T10:00:00+00:00",
    )
    area_summary = SuiteRuntimeSummary(
        suite_id=None,
        area_id="provider_connection",
        display_name="Provider Connection",
        status=SuiteRuntimeSummaryStatus.UNAVAILABLE,
        module_count=1,
        object_map_section_count=2,
        error_count=1,
        errors=("provider token=tok-123 is unavailable",),
        degraded=True,
        unavailable_reason="credential password=hunter2 missing",
        last_activity_at="2026-07-07T11:00:00+00:00",
    )
    summaries = (suite_summary, area_summary)
    before = tuple(summary.to_dict() for summary in summaries)
    backend = _runtime_manager_backend(
        app,
        suite_runtime_summary_provider=lambda: summaries,
    )

    snapshot = backend.snapshot()
    metadata = snapshot.suite_runtime_summary.metadata

    assert tuple(summary.to_dict() for summary in summaries) == before
    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.suite_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.suite_runtime_summary.count == 2
    assert snapshot.suite_runtime_summary.message == "2 suite runtime summaries"
    assert metadata["available"] is True
    assert metadata["summary_count"] == 2
    assert metadata["suite_count"] == 1
    assert metadata["area_count"] == 1
    assert metadata["module_count"] == 3
    assert metadata["active_operation_count"] == 1
    assert metadata["active_task_count"] == 3
    assert metadata["object_map_section_count"] == 3
    assert metadata["warning_count"] == 1
    assert metadata["error_count"] == 1
    assert metadata["degraded_count"] == 1
    assert metadata["unavailable_count"] == 1
    assert metadata["suite_ids"] == ("data_manager",)
    assert metadata["area_ids"] == ("provider_connection",)
    assert metadata["warnings"] == ("Suite summary is incomplete.",)
    assert metadata["last_activity_at"] == "2026-07-07T11:00:00+00:00"
    assert metadata["provider_failed"] is False
    displayed = " ".join(
        (
            *metadata["errors"],
            *metadata["unavailable_reasons"],
            *(row["unavailable_reason"] or "" for row in metadata["summary_rows"]),
        )
    )
    assert "[redacted]" in displayed
    assert "tok-123" not in displayed
    assert "hunter2" not in displayed


def test_runtime_manager_handles_suite_runtime_summary_provider_failure_safely() -> None:
    app = LeonardoApp()
    long_secret = (
        "password=hunter2 token=tok-123 "
        "authorization=Bearer abc-456 "
        + ("x" * 500)
    )

    def fail() -> tuple[SuiteRuntimeSummary, ...]:
        raise RuntimeError(long_secret)

    backend = _runtime_manager_backend(app, suite_runtime_summary_provider=fail)

    snapshot = backend.snapshot()
    error = snapshot.suite_runtime_summary.metadata["errors"][0]

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.suite_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.suite_runtime_summary.metadata["available"] is False
    assert snapshot.suite_runtime_summary.metadata["provider_failed"] is True
    assert "RuntimeError" in error
    assert "[redacted]" in error
    assert "hunter2" not in error
    assert "tok-123" not in error
    assert "abc-456" not in error
    assert "x" * 200 not in error
    assert "Traceback" not in error


def test_runtime_manager_handles_invalid_suite_runtime_summary_provider_output_safely() -> None:
    app = LeonardoApp()
    backend = _runtime_manager_backend(
        app,
        suite_runtime_summary_provider=lambda: object(),
    )

    snapshot = backend.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.suite_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.suite_runtime_summary.metadata["available"] is False
    assert snapshot.suite_runtime_summary.metadata["provider_failed"] is True
    assert snapshot.suite_runtime_summary.metadata["error_count"] == 1
    assert snapshot.suite_runtime_summary.metadata["errors"] == (
        "Suite runtime summary provider returned invalid output",
    )


def test_runtime_manager_snapshot_includes_unavailable_download_data_runtime_summary() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.download_data_runtime_summary.section_id == "download_data_runtime"
    assert snapshot.download_data_runtime_summary.status is RuntimeSectionStatus.OK
    assert snapshot.download_data_runtime_summary.count == 0
    assert snapshot.download_data_runtime_summary.message == (
        "Download Data runtime summaries unavailable"
    )
    assert snapshot.download_data_runtime_summary.metadata["available"] is False
    assert snapshot.download_data_runtime_summary.metadata["summary_count"] == 0
    assert snapshot.download_data_runtime_summary.metadata["workflow_count"] == 0
    assert snapshot.download_data_runtime_summary.metadata["degraded"] is False
    assert "download_data_runtime" in tuple(
        section.section_id for section in snapshot.sections
    )


def test_runtime_manager_summarizes_injected_download_data_runtime_summaries_read_only() -> None:
    app = LeonardoApp()
    complete_summary = DownloadDataRuntimeSummary(
        workflow_id="download_data",
        display_name="Download Data",
        status=DownloadDataRuntimeSummaryStatus.OK,
        selection_count=1,
        preflight_count=2,
        ready_preflight_count=1,
        blocked_preflight_count=1,
        running_progress_count=1,
        completed_progress_count=1,
        completion_count=1,
        partial_count=1,
        failed_count=1,
        cancelled_count=1,
        output_ref_count=2,
        storage_target_count=2,
        partial_persistence_count=1,
        expected_total_bars=100,
        expected_total_steps=10,
        completed_steps=5,
        downloaded_bars=50,
        warning_count=1,
        warnings=("Partial output requires maintenance.",),
        last_activity_at="2026-07-07T10:00:00+00:00",
    )
    unavailable_summary = DownloadDataRuntimeSummary(
        workflow_id="download_data_archive",
        display_name="Download Data Archive",
        status=DownloadDataRuntimeSummaryStatus.UNAVAILABLE,
        selection_count=1,
        preflight_count=1,
        error_count=1,
        errors=("download token=tok-123 failed",),
        degraded=True,
        unavailable_reason="credential password=hunter2 missing",
        last_activity_at="2026-07-07T11:00:00+00:00",
    )
    summaries = (unavailable_summary, complete_summary)
    before = tuple(summary.to_dict() for summary in summaries)
    backend = _runtime_manager_backend(
        app,
        download_data_runtime_summary_provider=lambda: summaries,
    )

    snapshot = backend.snapshot()
    metadata = snapshot.download_data_runtime_summary.metadata

    assert tuple(summary.to_dict() for summary in summaries) == before
    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.download_data_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.download_data_runtime_summary.count == 2
    assert snapshot.download_data_runtime_summary.message == (
        "2 Download Data runtime summaries"
    )
    assert metadata["available"] is True
    assert metadata["summary_count"] == 2
    assert metadata["workflow_count"] == 2
    assert metadata["workflow_ids"] == ("download_data", "download_data_archive")
    assert metadata["selection_count"] == 2
    assert metadata["preflight_count"] == 3
    assert metadata["ready_preflight_count"] == 1
    assert metadata["blocked_preflight_count"] == 1
    assert metadata["running_progress_count"] == 1
    assert metadata["completed_progress_count"] == 1
    assert metadata["completion_count"] == 1
    assert metadata["partial_count"] == 1
    assert metadata["failed_count"] == 1
    assert metadata["cancelled_count"] == 1
    assert metadata["output_ref_count"] == 2
    assert metadata["storage_target_count"] == 2
    assert metadata["partial_persistence_count"] == 1
    assert metadata["expected_total_bars"] == 100
    assert metadata["expected_total_steps"] == 10
    assert metadata["completed_steps"] == 5
    assert metadata["downloaded_bars"] == 50
    assert metadata["warning_count"] == 1
    assert metadata["error_count"] == 1
    assert metadata["degraded_count"] == 1
    assert metadata["unavailable_count"] == 1
    assert metadata["last_activity_at"] == "2026-07-07T11:00:00+00:00"
    assert metadata["download_data_failed"] is False
    displayed = " ".join(
        (
            *metadata["errors"],
            *metadata["unavailable_reasons"],
            *(row["unavailable_reason"] or "" for row in metadata["summary_rows"]),
        )
    )
    assert "[redacted]" in displayed
    assert "tok-123" not in displayed
    assert "hunter2" not in displayed


def test_runtime_manager_handles_download_data_runtime_summary_provider_failure_safely() -> None:
    app = LeonardoApp()
    long_secret = (
        "password=hunter2 token=tok-123 "
        "authorization=Bearer abc-456 "
        + ("x" * 500)
    )

    def fail() -> tuple[DownloadDataRuntimeSummary, ...]:
        raise RuntimeError(long_secret)

    backend = _runtime_manager_backend(
        app,
        download_data_runtime_summary_provider=fail,
    )

    snapshot = backend.snapshot()
    error = snapshot.download_data_runtime_summary.metadata["errors"][0]

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.download_data_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.download_data_runtime_summary.metadata["available"] is False
    assert snapshot.download_data_runtime_summary.metadata["download_data_failed"] is True
    assert "RuntimeError" in error
    assert "[redacted]" in error
    assert "hunter2" not in error
    assert "tok-123" not in error
    assert "abc-456" not in error
    assert "x" * 200 not in error
    assert "Traceback" not in error


def test_runtime_manager_handles_invalid_download_data_runtime_summary_provider_output_safely() -> None:
    app = LeonardoApp()
    backend = _runtime_manager_backend(
        app,
        download_data_runtime_summary_provider=lambda: object(),
    )

    snapshot = backend.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.download_data_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.download_data_runtime_summary.metadata["available"] is False
    assert snapshot.download_data_runtime_summary.metadata["download_data_failed"] is True
    assert snapshot.download_data_runtime_summary.metadata["error_count"] == 1
    assert snapshot.download_data_runtime_summary.metadata["errors"] == (
        "Download Data runtime summary provider returned invalid output",
    )


def test_runtime_manager_download_data_summary_does_not_import_download_data_machinery() -> None:
    source = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("src", "leonardo", "core", "runtime_manager.py")
        .read_text(encoding="utf-8")
    )

    blocked_tokens = (
        "download_data_boundary_trace",
        "DownloadDataBoundaryDescriptor",
        "DownloadDataWorkflowDescriptor",
        "DownloadDataSelectionDraft",
        "DownloadDataPreflightSummary",
        "DownloadDataProgressSummary",
        "DownloadDataCompletionSummary",
        "ProviderRegistry",
        "register_provider",
        "discover",
        "pkgutil",
        "importlib",
        "os.walk",
        "Path.rglob",
        "globals()",
        "websockets",
        "import requests",
        "requests.",
        "aiohttp",
        "socket.",
        "shell=True",
    )
    for token in blocked_tokens:
        assert token not in source


def test_leonardo_app_constructs_runtime_manager_without_download_data_provider() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert isinstance(app.runtime_manager, RuntimeManagerBackend)
    assert snapshot.download_data_runtime_summary.section_id == "download_data_runtime"
    assert snapshot.download_data_runtime_summary.metadata["available"] is False


def test_runtime_manager_snapshot_includes_unavailable_provider_runtime_summary() -> None:
    app = LeonardoApp()

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.provider_runtime_summary.section_id == "provider_runtime"
    assert snapshot.provider_runtime_summary.status is RuntimeSectionStatus.OK
    assert snapshot.provider_runtime_summary.count == 0
    assert snapshot.provider_runtime_summary.message == (
        "Provider runtime summaries unavailable"
    )
    assert snapshot.provider_runtime_summary.metadata["available"] is False
    assert snapshot.provider_runtime_summary.metadata["summary_count"] == 0
    assert snapshot.provider_runtime_summary.metadata["provider_count"] == 0
    assert snapshot.provider_runtime_summary.metadata["degraded"] is False
    assert "provider_runtime" in tuple(
        section.section_id for section in snapshot.sections
    )


def test_runtime_manager_summarizes_injected_provider_runtime_summaries_read_only() -> None:
    app = LeonardoApp()
    bybit_summary = ProviderRuntimeSummary(
        provider_id="bybit",
        display_name="Bybit",
        status=ProviderRuntimeSummaryStatus.OK,
        provider_kind="exchange",
        capability_count=2,
        session_count=2,
        active_session_count=1,
        connected_session_count=1,
        subscription_count=3,
        active_subscription_count=2,
        message_trace_count=5,
        object_map_section_count=1,
        warning_count=1,
        warnings=("Provider summary is partial.",),
        last_activity_at="2026-07-07T10:00:00+00:00",
    )
    local_summary = ProviderRuntimeSummary(
        provider_id="local",
        display_name="Local Provider",
        status=ProviderRuntimeSummaryStatus.UNAVAILABLE,
        provider_kind="local",
        capability_count=1,
        session_count=1,
        subscription_count=1,
        message_trace_count=1,
        object_map_section_count=2,
        error_count=1,
        errors=("provider token=tok-123 is unavailable",),
        degraded=True,
        unavailable_reason="credential password=hunter2 missing",
        last_activity_at="2026-07-07T11:00:00+00:00",
    )
    summaries = (local_summary, bybit_summary)
    before = tuple(summary.to_dict() for summary in summaries)
    backend = _runtime_manager_backend(
        app,
        provider_runtime_summary_provider=lambda: summaries,
    )

    snapshot = backend.snapshot()
    metadata = snapshot.provider_runtime_summary.metadata

    assert tuple(summary.to_dict() for summary in summaries) == before
    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.provider_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.provider_runtime_summary.count == 2
    assert snapshot.provider_runtime_summary.message == (
        "2 provider runtime summaries"
    )
    assert metadata["available"] is True
    assert metadata["summary_count"] == 2
    assert metadata["provider_count"] == 2
    assert metadata["provider_ids"] == ("bybit", "local")
    assert metadata["capability_count"] == 3
    assert metadata["session_count"] == 3
    assert metadata["active_session_count"] == 1
    assert metadata["connected_session_count"] == 1
    assert metadata["subscription_count"] == 4
    assert metadata["active_subscription_count"] == 2
    assert metadata["message_trace_count"] == 6
    assert metadata["object_map_section_count"] == 3
    assert metadata["warning_count"] == 1
    assert metadata["error_count"] == 1
    assert metadata["degraded_count"] == 1
    assert metadata["unavailable_count"] == 1
    assert metadata["warnings"] == ("Provider summary is partial.",)
    assert metadata["last_activity_at"] == "2026-07-07T11:00:00+00:00"
    assert metadata["provider_failed"] is False
    assert tuple(row["provider_id"] for row in metadata["summary_rows"]) == (
        "local",
        "bybit",
    )
    displayed = " ".join(
        (
            *metadata["errors"],
            *metadata["unavailable_reasons"],
            *(row["unavailable_reason"] or "" for row in metadata["summary_rows"]),
        )
    )
    assert "[redacted]" in displayed
    assert "tok-123" not in displayed
    assert "hunter2" not in displayed


def test_runtime_manager_handles_provider_runtime_summary_provider_failure_safely() -> None:
    app = LeonardoApp()
    long_secret = (
        "password=hunter2 token=tok-123 "
        "authorization=Bearer abc-456 "
        + ("x" * 500)
    )

    def fail() -> tuple[ProviderRuntimeSummary, ...]:
        raise RuntimeError(long_secret)

    backend = _runtime_manager_backend(app, provider_runtime_summary_provider=fail)

    snapshot = backend.snapshot()
    error = snapshot.provider_runtime_summary.metadata["errors"][0]

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.provider_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.provider_runtime_summary.metadata["available"] is False
    assert snapshot.provider_runtime_summary.metadata["provider_failed"] is True
    assert "RuntimeError" in error
    assert "[redacted]" in error
    assert "hunter2" not in error
    assert "tok-123" not in error
    assert "abc-456" not in error
    assert "x" * 200 not in error
    assert "Traceback" not in error


def test_runtime_manager_handles_invalid_provider_runtime_summary_provider_output_safely() -> None:
    app = LeonardoApp()
    backend = _runtime_manager_backend(
        app,
        provider_runtime_summary_provider=lambda: object(),
    )

    snapshot = backend.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.provider_runtime_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.provider_runtime_summary.metadata["available"] is False
    assert snapshot.provider_runtime_summary.metadata["provider_failed"] is True
    assert snapshot.provider_runtime_summary.metadata["error_count"] == 1
    assert snapshot.provider_runtime_summary.metadata["errors"] == (
        "Provider runtime summary provider returned invalid output",
    )


def test_runtime_manager_provider_summary_does_not_import_provider_machinery() -> None:
    source = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("src", "leonardo", "core", "runtime_manager.py")
        .read_text(encoding="utf-8")
    )

    blocked_tokens = (
        "provider_boundary_trace",
        "ProviderDescriptor",
        "ProviderCapabilityDescriptor",
        "ProviderSessionDescriptor",
        "ProviderSubscriptionDescriptor",
        "ProviderMessageTraceDescriptor",
        "ProviderRegistry",
        "register_provider",
        "discover",
        "pkgutil",
        "importlib",
        "os.walk",
        "Path.rglob",
        "globals()",
        "websockets",
        "import requests",
        "requests.",
        "aiohttp",
        "socket.",
        "shell=True",
    )
    for token in blocked_tokens:
        assert token not in source


def test_runtime_manager_suite_summary_does_not_import_suite_trace_or_registries() -> None:
    source = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("src", "leonardo", "core", "runtime_manager.py")
        .read_text(encoding="utf-8")
    )

    blocked_tokens = (
        "suite_boundary_trace",
        "SuiteRegistry",
        "register_suite",
        "pkgutil",
        "importlib",
        "os.walk",
        "Path.rglob",
        "globals()",
        "ObjectMapProviderEntry",
        "build_section",
        "register_provider",
    )
    for token in blocked_tokens:
        assert token not in source


def test_runtime_manager_summarizes_injected_object_map_snapshot_read_only() -> None:
    app = LeonardoApp()
    object_map_snapshot = _object_map_snapshot()
    before = object_map_snapshot.to_dict()
    backend = _runtime_manager_backend(
        app,
        object_map_snapshot_provider=lambda: object_map_snapshot,
    )

    snapshot = backend.snapshot()

    assert object_map_snapshot.to_dict() == before
    assert snapshot.object_map_summary.status is RuntimeSectionStatus.OK
    assert snapshot.object_map_summary.count == 2
    assert snapshot.object_map_summary.message == (
        "2 Object Map objects, 1 section"
    )
    assert snapshot.object_map_summary.metadata["available"] is True
    assert snapshot.object_map_summary.metadata["provider_count"] == 1
    assert snapshot.object_map_summary.metadata["section_count"] == 1
    assert snapshot.object_map_summary.metadata["object_count"] == 2
    assert snapshot.object_map_summary.metadata["relationship_count"] == 1
    assert snapshot.object_map_summary.metadata["family_ids"] == (
        "operation",
        "task",
    )
    assert snapshot.object_map_summary.metadata["object_kinds"] == (
        "operation",
        "task",
    )
    assert snapshot.object_map_summary.metadata["provider_ids"] == (
        "core.test.object_map",
    )
    assert snapshot.object_map_summary.metadata["section_ids"] == (
        "core.test.object_map.section",
    )


def test_runtime_manager_degrades_when_object_map_snapshot_reports_errors() -> None:
    app = LeonardoApp()
    object_map_snapshot = _object_map_snapshot(
        warnings=("duplicate section",),
        errors=("provider failed",),
        blockers=("blocked provider",),
    )
    backend = _runtime_manager_backend(
        app,
        object_map_snapshot_provider=lambda: object_map_snapshot,
    )

    snapshot = backend.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.object_map_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.object_map_summary.metadata["warning_count"] == 1
    assert snapshot.object_map_summary.metadata["error_count"] == 1
    assert snapshot.object_map_summary.metadata["blocker_count"] == 1
    assert snapshot.object_map_summary.metadata["warnings"] == ("duplicate section",)
    assert snapshot.object_map_summary.metadata["errors"] == ("provider failed",)
    assert snapshot.object_map_summary.metadata["blockers"] == ("blocked provider",)
    assert snapshot.object_map_summary.metadata["degraded"] is True


def test_runtime_manager_counts_full_object_map_diagnostics_but_bounds_display() -> None:
    app = LeonardoApp()
    object_map_snapshot = _object_map_snapshot(
        warnings=_diagnostics("warning", 12),
        errors=_diagnostics("error", 13),
        blockers=_diagnostics("blocker", 14),
    )
    backend = _runtime_manager_backend(
        app,
        object_map_snapshot_provider=lambda: object_map_snapshot,
    )

    snapshot = backend.snapshot()
    metadata = snapshot.object_map_summary.metadata

    assert snapshot.object_map_summary.status is RuntimeSectionStatus.DEGRADED
    assert metadata["warning_count"] == 12
    assert metadata["error_count"] == 13
    assert metadata["blocker_count"] == 14
    assert len(metadata["warnings"]) == 10
    assert len(metadata["errors"]) == 10
    assert len(metadata["blockers"]) == 10
    assert metadata["degraded"] is True


def test_runtime_manager_redacts_and_bounds_snapshot_diagnostics() -> None:
    app = LeonardoApp()
    long_tail = "x" * 500
    object_map_snapshot = _object_map_snapshot(
        warnings=(f"warning password=hunter2 token=tok-123 {long_tail}",),
        errors=(
            f"error api_key=api-456 authorization=Bearer auth-789 {long_tail}",
        ),
        blockers=(
            f"blocker credential=cred-000 secret=secret-111 "
            f"passwd=pass-222 {long_tail}",
        ),
    )
    backend = _runtime_manager_backend(
        app,
        object_map_snapshot_provider=lambda: object_map_snapshot,
    )

    snapshot = backend.snapshot()
    metadata = snapshot.object_map_summary.metadata
    displayed = (
        *metadata["warnings"],
        *metadata["errors"],
        *metadata["blockers"],
    )
    joined = " ".join(displayed)

    assert metadata["warning_count"] == 1
    assert metadata["error_count"] == 1
    assert metadata["blocker_count"] == 1
    assert all(len(diagnostic) <= 160 for diagnostic in displayed)
    assert "[redacted]" in joined
    for sensitive_value in (
        "hunter2",
        "tok-123",
        "api-456",
        "auth-789",
        "cred-000",
        "secret-111",
        "pass-222",
    ):
        assert sensitive_value not in joined
    assert "x" * 200 not in joined


def test_runtime_manager_handles_object_map_snapshot_provider_failure_safely() -> None:
    app = LeonardoApp()
    long_secret = (
        "password=hunter2 token=tok-123 "
        "authorization=Bearer abc-456 "
        + ("x" * 500)
    )

    def fail() -> ObjectMapSnapshot:
        raise RuntimeError(long_secret)

    backend = _runtime_manager_backend(app, object_map_snapshot_provider=fail)

    snapshot = backend.snapshot()
    error = snapshot.object_map_summary.metadata["errors"][0]

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.object_map_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.object_map_summary.metadata["available"] is False
    assert snapshot.object_map_summary.metadata["provider_failed"] is True
    assert "RuntimeError" in error
    assert "[redacted]" in error
    assert "hunter2" not in error
    assert "tok-123" not in error
    assert "abc-456" not in error
    assert "x" * 200 not in error
    assert "Traceback" not in error


def test_runtime_manager_handles_invalid_object_map_snapshot_provider_output_safely() -> None:
    app = LeonardoApp()
    backend = _runtime_manager_backend(
        app,
        object_map_snapshot_provider=lambda: object(),
    )

    snapshot = backend.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.object_map_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.object_map_summary.metadata["available"] is False
    assert snapshot.object_map_summary.metadata["provider_failed"] is True
    assert snapshot.object_map_summary.metadata["error_count"] == 1
    assert snapshot.object_map_summary.metadata["errors"] == (
        "Object Map snapshot provider returned invalid output",
    )


def test_runtime_manager_object_map_summary_does_not_import_trace_providers() -> None:
    source = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("src", "leonardo", "core", "runtime_manager.py")
        .read_text(encoding="utf-8")
    )

    blocked_tokens = (
        "task_operation_trace",
        "runtime_registry_trace",
        "process_connection_trace",
        "audit_event_trace",
        "window_trace",
        "action_trace",
        "ObjectMapProviderEntry",
        "build_section",
        "register_provider",
    )
    for token in blocked_tokens:
        assert token not in source


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


def test_runtime_manager_snapshot_reflects_download_execution_ready_phase() -> None:
    app = LeonardoApp()
    app.download_manager.submit_request(_download_request())
    execution_snapshot = app.download_execution_manager.create_plan("req-download")
    updated = app.download_execution_manager.mark_ready(
        execution_snapshot.plan.plan_id,
    )
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
    assert snapshot.download_execution_summary.metadata["active_plan_ids"] == (
        updated.plan.plan_id,
    )
    assert snapshot.download_execution_summary.metadata["running_plan_ids"] == (
        updated.plan.plan_id,
    )
    assert snapshot.download_execution_summary.metadata["blocked_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["plan_rows"][0]["phase"] == (
        "ready"
    )
    assert snapshot.download_execution_summary.metadata["plan_rows"][0]["details"] == (
        "connection_refs=binance-spot; "
        "message=Download execution plan is ready for future execution."
    )


def test_runtime_manager_snapshot_reflects_download_execution_blocked_phase() -> None:
    app = LeonardoApp()
    app.download_manager.submit_request(_download_request())
    execution_snapshot = app.download_execution_manager.create_plan("req-download")
    updated = app.download_execution_manager.mark_blocked(
        execution_snapshot.plan.plan_id,
        "Storage policy is unresolved.",
    )

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert snapshot.download_execution_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.download_execution_summary.metadata["active_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["running_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["blocked_plan_ids"] == (
        updated.plan.plan_id,
    )
    assert snapshot.download_execution_summary.metadata["plan_rows"][0]["phase"] == (
        "blocked"
    )
    assert snapshot.download_execution_summary.metadata["plan_rows"][0]["details"] == (
        "connection_refs=binance-spot; message=Storage policy is unresolved."
    )


def test_runtime_manager_snapshot_reflects_capability_blocked_execution() -> None:
    app = LeonardoApp()
    app.download_manager.submit_request(_download_request())
    execution_snapshot = app.download_execution_manager.create_plan("req-download")
    updated = app.download_execution_manager.classify_readiness(
        execution_snapshot.plan.plan_id,
    )
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
    capability_layers = tuple(
        layer
        for layer in updated.preflight_layers
        if layer.layer is DownloadPreflightLayer.CAPABILITY
    )

    assert after_state == before_state
    assert capability_layers[0].status is DownloadPreflightLayerStatus.BLOCKED
    assert capability_layers[0].issues == ("Unknown provider: binance.",)
    assert snapshot.download_execution_summary.status is RuntimeSectionStatus.DEGRADED
    assert snapshot.download_execution_summary.metadata["blocked_plan_ids"] == (
        updated.plan.plan_id,
    )
    assert snapshot.download_execution_summary.metadata["plan_rows"][0][
        "preflight_layer_count"
    ] == 2
    assert snapshot.download_execution_summary.metadata["plan_rows"][0]["details"] == (
        "connection_refs=binance-spot; message=Unknown provider: binance."
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


def _runtime_manager_backend(
    app: LeonardoApp,
    *,
    object_map_snapshot_provider: object | None = None,
    provider_runtime_summary_provider: object | None = None,
    suite_runtime_summary_provider: object | None = None,
    download_data_runtime_summary_provider: object | None = None,
) -> RuntimeManagerBackend:
    return RuntimeManagerBackend(
        state_store=app.state_store,
        session_manager=app.session_manager,
        service_registry=app.service_registry,
        task_manager=app.task_manager,
        process_manager=app.process_manager,
        connection_registry=app.connection_registry,
        window_registry=app.window_registry,
        action_registry=app.action_registry,
        operation_registry=app.operation_registry,
        audit_log=app.audit_log,
        contract_registry=app.contract_registry,
        download_manager=app.download_manager,
        download_execution_manager=app.download_execution_manager,
        object_map_snapshot_provider=object_map_snapshot_provider,
        provider_runtime_summary_provider=provider_runtime_summary_provider,
        suite_runtime_summary_provider=suite_runtime_summary_provider,
        download_data_runtime_summary_provider=download_data_runtime_summary_provider,
    )


def _object_map_snapshot(
    *,
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
) -> ObjectMapSnapshot:
    operation_ref = TraceableObjectRef(
        object_id="operation-1",
        object_kind="operation",
        owner_domain="core",
        owner_component="OperationRegistry",
    )
    task_ref = TraceableObjectRef(
        object_id="task-1",
        object_kind="task",
        owner_domain="core",
        owner_component="TaskManager",
    )
    relationship = TraceableRelationshipRef(
        relationship_id="operation-1.schedules_task.task-1",
        relationship_type="schedules_task",
        source_ref=operation_ref,
        target_ref=task_ref,
        lifecycle_status="active",
    )
    return ObjectMapSnapshot(
        snapshot_id="test.object_map.snapshot",
        sections=(
            ObjectMapSection(
                section_id="core.test.object_map.section",
                provider_id="core.test.object_map",
                owner_domain="core",
                object_kind=None,
                family_id=None,
                summaries=(
                    TraceableObjectSummary(
                        object_ref=operation_ref,
                        lifecycle_status="running",
                        runtime_or_persistent="runtime",
                        relationship_refs=(relationship,),
                    ),
                    TraceableObjectSummary(
                        object_ref=task_ref,
                        lifecycle_status="running",
                        runtime_or_persistent="runtime",
                    ),
                ),
                relationships=(relationship,),
            ),
        ),
        provider_descriptors=(
            ObjectMapProviderDescriptor(
                provider_id="core.test.object_map",
                owner_domain="core",
                owner_component="test",
                object_kinds=("operation", "task"),
                family_ids=("operation", "task"),
                relationship_types=("schedules_task",),
            ),
        ),
        warnings=warnings,
        errors=errors,
        blockers=blockers,
    )


def _diagnostics(prefix: str, count: int) -> tuple[str, ...]:
    return tuple(f"{prefix}-{index}" for index in range(count))
