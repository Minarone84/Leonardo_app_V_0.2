from datetime import UTC, datetime
from pathlib import Path

from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionDirection,
    ConnectionEndpoint,
    ConnectionKind,
    ConnectionLifecycleStatus,
    ConnectionProtocol,
    WebSocketChannelDefinition,
)
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.processes import ProcessKind, ProcessLaunchRequest
from leonardo.contracts.traceable_object import TraceableObjectSummary
from leonardo.core.audit_log import AuditLog
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.process_connection_trace import (
    PROCESS_CONNECTION_TRACE_PROVIDER_ID,
    build_process_connection_trace_provider_descriptor,
    build_process_connection_trace_section,
    connection_trace_summary_from_state,
    interrogate_process_connection_trace,
    process_connection_relationships_from_state,
    process_trace_summary_from_state,
    websocket_channel_trace_summary_from_state,
)
from leonardo.core.process_manager import ProcessManager
from leonardo.core.state_store import StateStore


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "process_connection_trace.py"
_RUNTIME_MANAGER_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "runtime_manager.py"


class FakeHandle:
    def __init__(self, pid: int = 1001) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        raise AssertionError("trace helpers must not terminate processes")

    def kill(self) -> None:
        raise AssertionError("trace helpers must not kill processes")

    def wait(self, timeout: float | None = None) -> int:
        raise AssertionError("trace helpers must not wait for processes")


class FakeLauncher:
    def __init__(self) -> None:
        self.requests: list[ProcessLaunchRequest] = []

    def start(self, request: ProcessLaunchRequest) -> FakeHandle:
        self.requests.append(request)
        return FakeHandle()


def test_process_connection_trace_provider_descriptor_is_read_only() -> None:
    descriptor = build_process_connection_trace_provider_descriptor()

    assert descriptor.provider_id == PROCESS_CONNECTION_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.object_kinds == ("process", "connection", "websocket_channel")
    assert descriptor.family_ids == descriptor.object_kinds
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_interrogation is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert "references" in descriptor.relationship_types
    assert "owns_channel" in descriptor.relationship_types
    assert "uses_connection" in descriptor.relationship_types


def test_process_summary_uses_safe_public_runtime_state() -> None:
    runtime = _runtime_with_process()
    process_state = runtime.process_manager.active_processes()[0]

    summary = process_trace_summary_from_state(process_state)
    targets = {
        relationship.target_ref.object_kind: relationship.target_ref.object_id
        for relationship in summary.relationship_refs
    }

    assert isinstance(summary, TraceableObjectSummary)
    assert summary.object_ref.object_id == "process-1"
    assert summary.object_ref.object_kind == "process"
    assert summary.object_ref.owner_component == "ProcessManager"
    assert summary.display_name == "Inspect runtime"
    assert summary.lifecycle_status == "running"
    assert summary.metadata["process_id"] == "process-1"
    assert summary.metadata["label"] == "Inspect runtime"
    assert summary.metadata["kind"] == "utility"
    assert summary.metadata["status"] == "running"
    assert summary.metadata["pid"] == 1001
    assert summary.metadata["command_preview"] == "python (5 args)"
    assert summary.metadata["command_token_count"] == 5
    assert "command" not in summary.metadata
    assert "secret-token" not in str(summary.metadata)
    assert targets["operation"] == "operation-1"
    assert targets["task"] == "task-1"
    assert summary.operation_refs == ("operation-1",)
    assert summary.task_refs == ("task-1",)
    assert summary.correlation_refs == ("corr-1",)


def test_connection_summary_uses_safe_public_runtime_state_and_definitions() -> None:
    runtime = _runtime_with_connection()
    connection_state = runtime.connection_registry.connection_states()[0]
    channel_states = runtime.connection_registry.websocket_channel_states()
    definition = runtime.connection_registry.list_connections()[0]

    summary = connection_trace_summary_from_state(
        connection_state,
        channel_states=channel_states,
        definition=definition,
    )

    assert summary.object_ref.object_id == "connection-1"
    assert summary.object_ref.object_kind == "connection"
    assert summary.object_ref.owner_component == "ConnectionRegistry"
    assert summary.lifecycle_status == "degraded"
    assert summary.metadata["connection_id"] == "connection-1"
    assert summary.metadata["kind"] == "market_data"
    assert summary.metadata["protocol"] == "websocket"
    assert summary.metadata["direction"] == "outbound"
    assert summary.metadata["last_error_message"] == "Heartbeat late"
    assert summary.metadata["channel_count"] == 1
    assert summary.metadata["channel_ids"] == ("channel-1",)
    assert summary.metadata["endpoint_label"] == "Bybit public stream"
    assert summary.metadata["endpoint_protocol"] == "websocket"
    assert summary.metadata["endpoint_address_redacted"] is True
    assert "stream.example.test" not in str(summary.metadata)
    assert summary.operation_refs == ("operation-1",)
    assert summary.task_refs == ("task-1",)
    assert summary.correlation_refs == ("corr-1",)
    assert summary.relationship_refs[0].relationship_type == "owns_channel"
    assert summary.relationship_refs[0].target_ref.object_id == "channel-1"


def test_websocket_channel_summary_uses_state_counters_and_definition_topic() -> None:
    runtime = _runtime_with_connection()
    channel_state = runtime.connection_registry.websocket_channel_states()[0]
    definition = runtime.connection_registry.list_websocket_channels()[0]

    summary = websocket_channel_trace_summary_from_state(
        channel_state,
        definition=definition,
    )

    assert summary.object_ref.object_id == "channel-1"
    assert summary.object_ref.object_kind == "websocket_channel"
    assert summary.object_ref.owner_component == "ConnectionRegistry"
    assert summary.lifecycle_status == "degraded"
    assert summary.metadata["channel_id"] == "channel-1"
    assert summary.metadata["connection_id"] == "connection-1"
    assert summary.metadata["topic"] == "runtime.events"
    assert summary.metadata["received_count"] == 2
    assert summary.metadata["sent_count"] == 3
    assert summary.metadata["error_count"] == 1
    assert summary.metadata["last_message_at_utc"] == datetime(2026, 7, 2, 12, tzinfo=UTC)
    assert summary.relationship_refs[0].relationship_type == "references"
    assert summary.relationship_refs[0].target_ref.object_id == "connection-1"


def test_process_connection_relationships_include_only_known_safe_links() -> None:
    runtime = _runtime_with_process_and_connection()
    process_state = runtime.process_manager.active_processes()[0]
    connection_state = runtime.connection_registry.connection_states()[0]
    channel_state = runtime.connection_registry.websocket_channel_states()[0]

    relationships = process_connection_relationships_from_state(
        process_states=(process_state,),
        connection_states=(connection_state,),
        websocket_channel_states=(channel_state,),
    )
    relationship_ids = {relationship.relationship_id for relationship in relationships}
    relationship_types = {relationship.relationship_type for relationship in relationships}

    assert "references" in relationship_types
    assert "owns_channel" in relationship_types
    assert "process-1.references_operation.operation-1" in relationship_ids
    assert "process-1.references_task.task-1" in relationship_ids
    assert "connection-1.owns_channel.channel-1" in relationship_ids
    assert "channel-1.references_connection.connection-1" in relationship_ids


def test_missing_optional_ids_do_not_create_fake_relationships() -> None:
    runtime = _runtime()
    request = ProcessLaunchRequest(
        process_id="process-without-links",
        label="No links",
        command=("python", "-m", "tool"),
        kind=ProcessKind.UTILITY,
    )
    process_state = runtime.process_manager.launch_process(request)
    connection_state = runtime.connection_registry.register_connection(
        ConnectionDefinition(
            connection_id="connection-without-channel",
            label="No channel",
            kind=ConnectionKind.INTERNAL_SERVICE,
            protocol=ConnectionProtocol.INTERNAL,
            direction=ConnectionDirection.INTERNAL,
        )
    )
    connection_runtime_state = runtime.connection_registry.connection_states()[0]

    relationships = process_connection_relationships_from_state(
        process_states=(process_state,),
        connection_states=(connection_runtime_state,),
    )

    assert connection_state.connection_id == "connection-without-channel"
    assert relationships == ()


def test_object_map_section_includes_summaries_legends_and_definitions() -> None:
    runtime = _runtime_with_process_and_connection()

    section = build_process_connection_trace_section(
        process_manager=runtime.process_manager,
        connection_registry=runtime.connection_registry,
    )
    summary_kinds = {summary.object_ref.object_kind for summary in section.summaries}
    family_ids = {legend.family_id for legend in section.legends}
    relationship_types = {
        definition.relationship_type
        for definition in section.relationship_definitions
    }

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "core.process_connection_websocket"
    assert section.provider_id == PROCESS_CONNECTION_TRACE_PROVIDER_ID
    assert summary_kinds == {"process", "connection", "websocket_channel"}
    assert family_ids == {"process", "connection", "websocket_channel"}
    assert "references" in relationship_types
    assert "owns_channel" in relationship_types
    assert "uses_connection" in relationship_types
    assert "records_audit" in relationship_types
    assert section.metadata["process_count"] == 1
    assert section.metadata["connection_count"] == 1
    assert section.metadata["websocket_channel_count"] == 1
    assert section.errors == ()


def test_trace_section_can_read_from_state_store_or_runtime_snapshot() -> None:
    runtime = _runtime_with_process_and_connection()

    state_store_section = build_process_connection_trace_section(
        state_store=runtime.state_store
    )
    snapshot_section = build_process_connection_trace_section(
        runtime_snapshot=runtime.state_store.runtime_snapshot(),
    )

    assert state_store_section.metadata["process_ids"] == ("process-1",)
    assert state_store_section.metadata["connection_ids"] == ("connection-1",)
    assert state_store_section.metadata["websocket_channel_ids"] == ("channel-1",)
    assert snapshot_section.metadata["process_ids"] == ("process-1",)
    assert snapshot_section.metadata["connection_ids"] == ("connection-1",)
    assert snapshot_section.metadata["websocket_channel_ids"] == ("channel-1",)


def test_interrogate_process_connection_trace_returns_read_only_reports() -> None:
    runtime = _runtime_with_process_and_connection()

    process_report = interrogate_process_connection_trace(
        "process-1",
        object_kind="process",
        process_manager=runtime.process_manager,
        connection_registry=runtime.connection_registry,
    )
    connection_report = interrogate_process_connection_trace(
        "connection-1",
        object_kind="connection",
        process_manager=runtime.process_manager,
        connection_registry=runtime.connection_registry,
    )
    channel_report = interrogate_process_connection_trace(
        "channel-1",
        object_kind="websocket_channel",
        process_manager=runtime.process_manager,
        connection_registry=runtime.connection_registry,
    )

    assert process_report.summary is not None
    assert process_report.target_ref.object_kind == "process"
    assert process_report.family_legend is not None
    assert process_report.family_legend.family_id == "process"
    assert process_report.metadata["read_only"] is True
    assert process_report.blockers == ()
    assert any(
        relationship.target_ref.object_id == "operation-1"
        for relationship in process_report.relationships
    )
    assert connection_report.summary is not None
    assert connection_report.family_legend is not None
    assert any(
        relationship.target_ref.object_id == "channel-1"
        for relationship in connection_report.relationships
    )
    assert channel_report.summary is not None
    assert channel_report.family_legend is not None
    assert any(
        relationship.target_ref.object_id == "connection-1"
        for relationship in channel_report.relationships
    )


def test_interrogate_missing_process_connection_object_reports_blocker() -> None:
    report = interrogate_process_connection_trace(
        "missing-process",
        object_kind="process",
    )

    assert report.summary is None
    assert report.target_ref.object_id == "missing-process"
    assert report.target_ref.object_kind == "process"
    assert report.blockers == ("Process/connection object not found: missing-process",)
    assert report.errors == ()


def test_trace_helpers_do_not_mutate_managers_state_or_audit_log() -> None:
    runtime = _runtime_with_process_and_connection()
    before = (
        runtime.process_manager.active_processes(),
        runtime.connection_registry.connection_states(),
        runtime.connection_registry.websocket_channel_states(),
        runtime.state_store.runtime_snapshot().process_states,
        runtime.state_store.runtime_snapshot().connection_states,
        runtime.state_store.runtime_snapshot().websocket_channel_states,
        runtime.audit_log.snapshot(),
    )

    build_process_connection_trace_section(
        process_manager=runtime.process_manager,
        connection_registry=runtime.connection_registry,
    )
    interrogate_process_connection_trace(
        "connection-1",
        object_kind="connection",
        process_manager=runtime.process_manager,
        connection_registry=runtime.connection_registry,
    )
    after = (
        runtime.process_manager.active_processes(),
        runtime.connection_registry.connection_states(),
        runtime.connection_registry.websocket_channel_states(),
        runtime.state_store.runtime_snapshot().process_states,
        runtime.state_store.runtime_snapshot().connection_states,
        runtime.state_store.runtime_snapshot().websocket_channel_states,
        runtime.audit_log.snapshot(),
    )

    assert after == before


def test_malformed_explicit_sources_are_reported_without_mutation() -> None:
    section = build_process_connection_trace_section(
        process_states=(object(),),
        connection_states=(object(),),
        websocket_channel_states=(object(),),
        connection_definitions=(object(),),
        websocket_channel_definitions=(object(),),
    )

    assert section.summaries == ()
    assert "process_states entries must be ProcessRuntimeState" in section.errors
    assert "connection_states entries must be ConnectionRuntimeState" in section.errors
    assert (
        "websocket_channel_states entries must be WebSocketChannelRuntimeState"
        in section.errors
    )
    assert (
        "connection_definitions entries must be ConnectionDefinition"
        in section.errors
    )
    assert (
        "websocket_channel_definitions entries must be WebSocketChannelDefinition"
        in section.errors
    )


def test_process_connection_trace_has_no_lifecycle_runtime_manager_or_domain_wiring() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "CoreRunner",
        "CoreRuntimeBridge",
        "RuntimeManagerBackend",
        "RuntimeManagerWindow",
        "class ObjectMapService",
        "class ObjectMapRegistry",
        "register_provider",
        "def discover",
        ".discover",
        "submit_command",
        "ProcessLauncher",
        "SubprocessLauncher",
        "sub" + "process",
        "launch_process",
        "poll_process",
        "refresh_process",
        "stop_process",
        "kill_process",
        "stop_all",
        "register_connection",
        "register_websocket_channel",
        "mark_connection",
        "record_heartbeat",
        "record_channel",
        "shutdown_tracking",
        ".emit(",
        "DownloadManager",
        "DownloadExecutionManager",
        "DownloadRequestBuilderWindow",
        "PySide6",
        "PyQt6",
        "QtWidgets",
        "QApplication",
        "socket.",
        "requests",
        "aio" + "http",
        "web" + "sockets",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "shell" + "=True",
    )

    for token in blocked_tokens:
        assert token not in source


def test_runtime_manager_remains_unwired_from_process_connection_trace() -> None:
    source = _RUNTIME_MANAGER_SOURCE.read_text(encoding="utf-8")

    assert "process_connection_trace" not in source
    assert "build_process_connection_trace_section" not in source
    assert "PROCESS_CONNECTION_TRACE_PROVIDER_ID" not in source


class _Runtime:
    def __init__(self) -> None:
        self.audit_log = AuditLog()
        self.state_store = StateStore(self.audit_log)
        self.launcher = FakeLauncher()
        self.process_manager = ProcessManager(
            self.state_store,
            self.audit_log,
            launcher=self.launcher,
        )
        self.connection_registry = ConnectionRegistry(self.state_store)


def _runtime() -> _Runtime:
    return _Runtime()


def _runtime_with_process() -> _Runtime:
    runtime = _runtime()
    runtime.process_manager.launch_process(_process_request())
    return runtime


def _runtime_with_connection() -> _Runtime:
    runtime = _runtime()
    _register_connection(runtime.connection_registry)
    return runtime


def _runtime_with_process_and_connection() -> _Runtime:
    runtime = _runtime_with_process()
    _register_connection(runtime.connection_registry)
    return runtime


def _process_request() -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        process_id="process-1",
        label="Inspect runtime",
        command=("python", "-m", "safe.module", "--token", "secret-token"),
        kind=ProcessKind.UTILITY,
        operation_id="operation-1",
        task_id="task-1",
        service_id="service-1",
        correlation_id="corr-1",
        metadata={"purpose": "trace-test"},
    )


def _connection_definition() -> ConnectionDefinition:
    return ConnectionDefinition(
        connection_id="connection-1",
        label="Runtime feed",
        kind=ConnectionKind.MARKET_DATA,
        protocol=ConnectionProtocol.WEBSOCKET,
        direction=ConnectionDirection.OUTBOUND,
        endpoint=ConnectionEndpoint(
            label="Bybit public stream",
            protocol=ConnectionProtocol.WEBSOCKET,
            host="stream.example.test",
            path="/private",
        ),
        service_id="service-1",
        process_id="process-1",
        metadata={"provider": "bybit"},
    )


def _channel_definition() -> WebSocketChannelDefinition:
    return WebSocketChannelDefinition(
        channel_id="channel-1",
        connection_id="connection-1",
        label="Runtime channel",
        topic="runtime.events",
        metadata={"scope": "runtime"},
    )


def _register_connection(registry: ConnectionRegistry) -> None:
    timestamp = datetime(2026, 7, 2, 12, tzinfo=UTC)
    registry.register_connection(_connection_definition())
    registry.register_websocket_channel(_channel_definition())
    registry.mark_connection_degraded(
        "connection-1",
        last_error_message="Heartbeat late",
        operation_id="operation-1",
        task_id="task-1",
        correlation_id="corr-1",
    )
    registry.record_heartbeat("connection-1", timestamp_utc=timestamp)
    registry.record_channel_received(
        "channel-1",
        count=2,
        timestamp_utc=timestamp,
    )
    registry.record_channel_sent("channel-1", count=3, timestamp_utc=timestamp)
    registry.record_channel_error("channel-1", count=1, timestamp_utc=timestamp)
