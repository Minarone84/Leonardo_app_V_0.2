"""Read-only trace helpers for process and connection runtime families.

The helpers in this module expose existing Core process, connection, and
WebSocket channel read models through shared traceability and Object Map report
contracts. They produce reports only and do not change lifecycle state, emit
audit events, construct clients, or wire Runtime Manager.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from leonardo.contracts.connections import (
    ConnectionDefinition,
    ConnectionRuntimeState,
    WebSocketChannelDefinition,
    WebSocketChannelRuntimeState,
)
from leonardo.contracts.object_family_legends import object_family_legend_by_id
from leonardo.contracts.object_map import ObjectMapProviderDescriptor, ObjectMapSection
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.processes import ProcessRuntimeState
from leonardo.contracts.runtime import RuntimeSnapshot
from leonardo.contracts.traceable_object import (
    ObjectInterrogationReport,
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.process_manager import ProcessManager
from leonardo.core.state_store import StateStore


PROCESS_CONNECTION_TRACE_PROVIDER_ID = "core.process_connection.trace"
PROCESS_CONNECTION_TRACE_SECTION_ID = "core.process_connection_websocket"
PROCESS_CONNECTION_TRACE_OWNER_DOMAIN = "core"
PROCESS_CONNECTION_TRACE_OWNER_COMPONENT = (
    "ProcessManager / ConnectionRegistry trace helper"
)
PROCESS_CONNECTION_TRACE_RUNTIME_KIND = "runtime"
PROCESS_CONNECTION_TRACE_DOC = (
    "docs/core_docs/PROCESS_CONNECTION_WEBSOCKET_FAMILY_TRACE.md"
)
PROCESS_CONNECTION_TRACE_TEST = (
    "tests/core_test/test_process_connection_websocket_family_trace.py"
)

_TRACE_FAMILY_IDS = ("process", "connection", "websocket_channel")
_TRACE_RELATIONSHIP_TYPES = (
    "references",
    "owns_channel",
    "uses_connection",
    "records_audit",
)
_TRACE_CONTRACTS = (
    "leonardo.contracts.processes.ProcessRuntimeState",
    "leonardo.contracts.connections.ConnectionRuntimeState",
    "leonardo.contracts.connections.WebSocketChannelRuntimeState",
    "leonardo.contracts.connections.WebSocketChannelDefinition",
    "leonardo.contracts.traceable_object.TraceableObjectRef",
    "leonardo.contracts.traceable_object.TraceableObjectSummary",
    "leonardo.contracts.traceable_object.TraceableRelationshipRef",
    "leonardo.contracts.object_map.ObjectMapProviderDescriptor",
    "leonardo.contracts.object_map.ObjectMapSection",
)
_TRACE_DOCS = (
    "docs/contracts_docs/TRACEABLE_OBJECTS.md",
    "docs/contracts_docs/OBJECT_FAMILY_LEGENDS.md",
    "docs/contracts_docs/OBJECT_RELATIONSHIPS.md",
    "docs/contracts_docs/OBJECT_MAP_PROTOCOL.md",
    PROCESS_CONNECTION_TRACE_DOC,
)


def build_process_connection_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Return the read-only provider descriptor for process and connection trace."""

    return ObjectMapProviderDescriptor(
        provider_id=PROCESS_CONNECTION_TRACE_PROVIDER_ID,
        provider_name="Core Process / Connection / WebSocket Trace",
        owner_domain=PROCESS_CONNECTION_TRACE_OWNER_DOMAIN,
        owner_component=PROCESS_CONNECTION_TRACE_OWNER_COMPONENT,
        object_kinds=_TRACE_FAMILY_IDS,
        family_ids=_TRACE_FAMILY_IDS,
        relationship_types=_TRACE_RELATIONSHIP_TYPES,
        supports_summary_listing=True,
        supports_interrogation=True,
        supports_relationship_listing=True,
        runtime_or_persistent=PROCESS_CONNECTION_TRACE_RUNTIME_KIND,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=_TRACE_CONTRACTS,
        related_docs=_TRACE_DOCS,
        related_tests=(PROCESS_CONNECTION_TRACE_TEST,),
        metadata={
            "process_source": "ProcessManager.active_processes()",
            "connection_source": "ConnectionRegistry.connection_states()",
            "websocket_channel_source": (
                "ConnectionRegistry.websocket_channel_states()"
            ),
            "snapshot_source": "StateStore.runtime_snapshot()",
        },
        extra={
            "forbidden_behavior": (
                "process_lifecycle_changes",
                "connection_lifecycle_changes",
                "channel_lifecycle_changes",
                "client_object_construction",
                "audit_emission",
                "runtime_manager_wiring",
                "object_map_service_registration",
            )
        },
    )


def process_trace_ref_from_state(state: ProcessRuntimeState) -> TraceableObjectRef:
    """Build a traceable object reference for one active process state."""

    _validate_process_state(state)
    return TraceableObjectRef(
        object_id=state.process_id,
        object_kind="process",
        owner_domain=PROCESS_CONNECTION_TRACE_OWNER_DOMAIN,
        owner_component="ProcessManager",
        label=state.label,
        metadata={
            "process_id": state.process_id,
            "label": state.label,
            "kind": state.kind.value,
            "status": state.status.value,
            "operation_id": state.operation_id,
            "task_id": state.task_id,
            "correlation_id": state.correlation_id,
        },
    )


def process_trace_summary_from_state(
    state: ProcessRuntimeState,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one active process state."""

    _validate_process_state(state)
    object_ref = process_trace_ref_from_state(state)
    relationships = _process_relationships_from_state(state, object_ref)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=state.status.value,
        runtime_or_persistent=PROCESS_CONNECTION_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(state.started_at_utc),
        updated_at_utc=_datetime_text(state.updated_at_utc),
        display_name=state.label,
        metadata=_process_summary_metadata(state),
        relationship_refs=relationships,
        audit_refs=(),
        operation_refs=_optional_ref_tuple(state.operation_id),
        task_refs=_optional_ref_tuple(state.task_id),
        correlation_refs=_optional_ref_tuple(state.correlation_id),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "ProcessManager active process read models",
            "command_policy": "Only command token count and first token are exposed.",
            "audit_reference_policy": "AuditLog remains historical truth.",
        },
    )


def connection_trace_ref_from_state(
    state: ConnectionRuntimeState,
) -> TraceableObjectRef:
    """Build a traceable object reference for one connection runtime state."""

    _validate_connection_state(state)
    return TraceableObjectRef(
        object_id=state.connection_id,
        object_kind="connection",
        owner_domain="core.connection",
        owner_component="ConnectionRegistry",
        label=state.label,
        metadata={
            "connection_id": state.connection_id,
            "label": state.label,
            "kind": state.kind.value,
            "protocol": state.protocol.value,
            "direction": state.direction.value,
            "status": state.status.value,
        },
    )


def connection_trace_summary_from_state(
    state: ConnectionRuntimeState,
    *,
    channel_states: Iterable[WebSocketChannelRuntimeState] = (),
    definition: ConnectionDefinition | None = None,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one connection runtime state."""

    _validate_connection_state(state)
    _validate_optional_connection_definition(definition)
    channels = tuple(
        channel
        for channel in _normalize_channel_states(channel_states)
        if channel.connection_id == state.connection_id
    )
    object_ref = connection_trace_ref_from_state(state)
    relationships = _connection_relationships_from_state(
        state,
        object_ref,
        channel_states=channels,
    )
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=state.status.value,
        runtime_or_persistent=PROCESS_CONNECTION_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(state.registered_at_utc),
        updated_at_utc=_datetime_text(state.updated_at_utc),
        display_name=state.label,
        metadata=_connection_summary_metadata(
            state,
            channel_states=channels,
            definition=definition,
        ),
        relationship_refs=relationships,
        audit_refs=(),
        operation_refs=_optional_ref_tuple(state.operation_id),
        task_refs=_optional_ref_tuple(state.task_id),
        correlation_refs=_optional_ref_tuple(state.correlation_id),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "ConnectionRegistry connection read models",
            "endpoint_policy": "Endpoint address fields are not exposed.",
            "audit_reference_policy": "AuditLog remains historical truth.",
        },
    )


def websocket_channel_trace_ref_from_state(
    state: WebSocketChannelRuntimeState,
) -> TraceableObjectRef:
    """Build a traceable object reference for one WebSocket channel state."""

    _validate_channel_state(state)
    return TraceableObjectRef(
        object_id=state.channel_id,
        object_kind="websocket_channel",
        owner_domain="core.connection",
        owner_component="ConnectionRegistry",
        label=state.label,
        metadata={
            "channel_id": state.channel_id,
            "connection_id": state.connection_id,
            "label": state.label,
            "status": state.status.value,
        },
    )


def websocket_channel_trace_summary_from_state(
    state: WebSocketChannelRuntimeState,
    *,
    definition: WebSocketChannelDefinition | None = None,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one WebSocket channel state."""

    _validate_channel_state(state)
    _validate_optional_channel_definition(definition)
    object_ref = websocket_channel_trace_ref_from_state(state)
    relationships = _channel_relationships_from_state(state, object_ref)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=state.status.value,
        runtime_or_persistent=PROCESS_CONNECTION_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(state.registered_at_utc),
        updated_at_utc=_datetime_text(state.updated_at_utc),
        display_name=state.label,
        metadata=_channel_summary_metadata(state, definition=definition),
        relationship_refs=relationships,
        audit_refs=(),
        correlation_refs=(),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "ConnectionRegistry WebSocket channel read models",
            "payload_policy": "Raw WebSocket payloads are not represented.",
            "audit_reference_policy": "AuditLog remains historical truth.",
        },
    )


def process_connection_relationships_from_state(
    *,
    process_states: Iterable[ProcessRuntimeState] = (),
    connection_states: Iterable[ConnectionRuntimeState] = (),
    websocket_channel_states: Iterable[WebSocketChannelRuntimeState] = (),
) -> tuple[TraceableRelationshipRef, ...]:
    """Build read-only relationships from explicit process and connection states."""

    relationships: list[TraceableRelationshipRef] = []
    processes = _normalize_process_states(process_states)
    connections = _normalize_connection_states(connection_states)
    channels = _normalize_channel_states(websocket_channel_states)
    for state in processes:
        relationships.extend(
            _process_relationships_from_state(state, process_trace_ref_from_state(state))
        )
    for state in connections:
        relationships.extend(
            _connection_relationships_from_state(
                state,
                connection_trace_ref_from_state(state),
                channel_states=(
                    channel
                    for channel in channels
                    if channel.connection_id == state.connection_id
                ),
            )
        )
    for state in channels:
        relationships.extend(
            _channel_relationships_from_state(
                state,
                websocket_channel_trace_ref_from_state(state),
            )
        )
    return _dedupe_relationships(relationships)


def build_process_connection_trace_section(
    *,
    process_manager: ProcessManager | None = None,
    connection_registry: ConnectionRegistry | None = None,
    state_store: StateStore | None = None,
    runtime_snapshot: RuntimeSnapshot | None = None,
    process_states: Iterable[ProcessRuntimeState] | None = None,
    connection_states: Iterable[ConnectionRuntimeState] | None = None,
    websocket_channel_states: Iterable[WebSocketChannelRuntimeState] | None = None,
    connection_definitions: Iterable[ConnectionDefinition] | None = None,
    websocket_channel_definitions: Iterable[WebSocketChannelDefinition] | None = None,
) -> ObjectMapSection:
    """Build a read-only Object Map section for process and connection families."""

    snapshot, snapshot_errors = _resolve_runtime_snapshot(
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
    )
    processes, process_errors = _resolve_process_states(
        process_manager=process_manager,
        runtime_snapshot=snapshot,
        state_store=state_store,
        process_states=process_states,
    )
    connections, connection_errors = _resolve_connection_states(
        connection_registry=connection_registry,
        runtime_snapshot=snapshot,
        state_store=state_store,
        connection_states=connection_states,
    )
    channels, channel_errors = _resolve_channel_states(
        connection_registry=connection_registry,
        runtime_snapshot=snapshot,
        state_store=state_store,
        websocket_channel_states=websocket_channel_states,
    )
    connection_defs, connection_def_errors = _resolve_connection_definitions(
        connection_registry=connection_registry,
        connection_definitions=connection_definitions,
    )
    channel_defs, channel_def_errors = _resolve_channel_definitions(
        connection_registry=connection_registry,
        websocket_channel_definitions=websocket_channel_definitions,
    )
    connection_def_by_id = {
        definition.connection_id: definition for definition in connection_defs
    }
    channel_def_by_id = {
        definition.channel_id: definition for definition in channel_defs
    }

    summaries: list[TraceableObjectSummary] = []
    errors = [
        *snapshot_errors,
        *process_errors,
        *connection_errors,
        *channel_errors,
        *connection_def_errors,
        *channel_def_errors,
    ]
    for state in processes:
        try:
            summaries.append(process_trace_summary_from_state(state))
        except (TypeError, ValueError) as error:
            errors.append(f"Process trace skipped for {state!r}: {error}")
    for state in connections:
        try:
            summaries.append(
                connection_trace_summary_from_state(
                    state,
                    channel_states=channels,
                    definition=connection_def_by_id.get(state.connection_id),
                )
            )
        except (TypeError, ValueError) as error:
            errors.append(f"Connection trace skipped for {state!r}: {error}")
    for state in channels:
        try:
            summaries.append(
                websocket_channel_trace_summary_from_state(
                    state,
                    definition=channel_def_by_id.get(state.channel_id),
                )
            )
        except (TypeError, ValueError) as error:
            errors.append(f"WebSocket channel trace skipped for {state!r}: {error}")

    relationships = _relationships_from_summaries(summaries)
    legends, legend_warnings = _process_connection_legends()

    return ObjectMapSection(
        section_id=PROCESS_CONNECTION_TRACE_SECTION_ID,
        provider_id=PROCESS_CONNECTION_TRACE_PROVIDER_ID,
        owner_domain=PROCESS_CONNECTION_TRACE_OWNER_DOMAIN,
        object_kind=None,
        family_id=None,
        title="Core Processes And Connections",
        summaries=tuple(summaries),
        relationships=relationships,
        legends=legends,
        relationship_definitions=_process_connection_relationship_definitions(),
        warnings=legend_warnings,
        errors=tuple(errors),
        metadata={
            "process_count": len(processes),
            "connection_count": len(connections),
            "websocket_channel_count": len(channels),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
            "process_ids": tuple(state.process_id for state in processes),
            "connection_ids": tuple(state.connection_id for state in connections),
            "websocket_channel_ids": tuple(state.channel_id for state in channels),
        },
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "process_connection_websocket_read_models",
        },
    )


def interrogate_process_connection_trace(
    object_id: str,
    *,
    object_kind: str | None = None,
    process_manager: ProcessManager | None = None,
    connection_registry: ConnectionRegistry | None = None,
    state_store: StateStore | None = None,
    runtime_snapshot: RuntimeSnapshot | None = None,
    process_states: Iterable[ProcessRuntimeState] | None = None,
    connection_states: Iterable[ConnectionRuntimeState] | None = None,
    websocket_channel_states: Iterable[WebSocketChannelRuntimeState] | None = None,
    connection_definitions: Iterable[ConnectionDefinition] | None = None,
    websocket_channel_definitions: Iterable[WebSocketChannelDefinition] | None = None,
) -> ObjectInterrogationReport:
    """Return a read-only interrogation report for one process or connection object."""

    _validate_non_empty_string(object_id, "object_id")
    if object_kind is not None and object_kind not in _TRACE_FAMILY_IDS:
        allowed = ", ".join(_TRACE_FAMILY_IDS)
        raise ValueError(f"object_kind must be one of: {allowed}")
    section = build_process_connection_trace_section(
        process_manager=process_manager,
        connection_registry=connection_registry,
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
        process_states=process_states,
        connection_states=connection_states,
        websocket_channel_states=websocket_channel_states,
        connection_definitions=connection_definitions,
        websocket_channel_definitions=websocket_channel_definitions,
    )
    summary = _find_summary(section.summaries, object_id, object_kind=object_kind)
    inferred_kind = object_kind or _kind_from_summary(summary) or "process_connection"
    target_ref = (
        summary.object_ref
        if summary is not None
        else TraceableObjectRef(
            object_id=object_id,
            object_kind=inferred_kind,
            owner_domain=PROCESS_CONNECTION_TRACE_OWNER_DOMAIN,
            owner_component=PROCESS_CONNECTION_TRACE_OWNER_COMPONENT,
        )
    )
    blockers = (
        ()
        if summary is not None
        else (f"Process/connection object not found: {object_id}",)
    )
    relationships = (
        _relationships_for_summary(summary, section.relationships)
        if summary is not None
        else ()
    )
    return ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=_legend_for_kind(target_ref.object_kind),
        relationships=relationships,
        permissions=summary.permission_refs if summary is not None else (),
        audit_refs=summary.audit_refs if summary is not None else (),
        runtime_refs=(object_id,),
        docs=_TRACE_DOCS,
        tests=(PROCESS_CONNECTION_TRACE_TEST,),
        warnings=section.warnings,
        blockers=(*blockers, *section.blockers),
        errors=section.errors,
        metadata={
            "provider_id": PROCESS_CONNECTION_TRACE_PROVIDER_ID,
            "section_id": PROCESS_CONNECTION_TRACE_SECTION_ID,
            "object_id": object_id,
            "object_kind": target_ref.object_kind,
            "read_only": True,
        },
    )


def _process_relationships_from_state(
    state: ProcessRuntimeState,
    process_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    relationships.extend(
        _reference_relationship(
            process_ref,
            object_id=state.operation_id,
            object_kind="operation",
            owner_domain=PROCESS_CONNECTION_TRACE_OWNER_DOMAIN,
            owner_component="OperationRegistry",
            metadata_key="operation_id",
            relationship_suffix="operation",
            lifecycle_status=state.status.value,
            operation_id=state.operation_id,
            task_id=state.task_id,
            correlation_id=state.correlation_id,
        )
    )
    relationships.extend(
        _reference_relationship(
            process_ref,
            object_id=state.task_id,
            object_kind="task",
            owner_domain=PROCESS_CONNECTION_TRACE_OWNER_DOMAIN,
            owner_component="TaskManager",
            metadata_key="task_id",
            relationship_suffix="task",
            lifecycle_status=state.status.value,
            operation_id=state.operation_id,
            task_id=state.task_id,
            correlation_id=state.correlation_id,
        )
    )
    return tuple(relationships)


def _connection_relationships_from_state(
    state: ConnectionRuntimeState,
    connection_ref: TraceableObjectRef,
    *,
    channel_states: Iterable[WebSocketChannelRuntimeState],
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    for channel in tuple(channel_states):
        relationships.append(
            TraceableRelationshipRef(
                relationship_id=(
                    f"{state.connection_id}.owns_channel.{channel.channel_id}"
                ),
                relationship_type="owns_channel",
                source_ref=connection_ref,
                target_ref=websocket_channel_trace_ref_from_state(channel),
                direction="outbound",
                lifecycle_status=state.status.value,
                operation_id=state.operation_id,
                task_id=state.task_id,
                correlation_id=state.correlation_id,
                created_at_utc=_datetime_text(channel.registered_at_utc),
                updated_at_utc=_datetime_text(channel.updated_at_utc),
                metadata={
                    "relationship_semantics": "connection_owns_channel",
                    "connection_id": state.connection_id,
                    "channel_id": channel.channel_id,
                },
            )
        )
    return tuple(relationships)


def _channel_relationships_from_state(
    state: WebSocketChannelRuntimeState,
    channel_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    return (
        TraceableRelationshipRef(
            relationship_id=f"{state.channel_id}.references_connection.{state.connection_id}",
            relationship_type="references",
            source_ref=channel_ref,
            target_ref=TraceableObjectRef(
                object_id=state.connection_id,
                object_kind="connection",
                owner_domain="core.connection",
                owner_component="ConnectionRegistry",
                metadata={"connection_id": state.connection_id},
            ),
            direction="outbound",
            lifecycle_status=state.status.value,
            created_at_utc=_datetime_text(state.registered_at_utc),
            updated_at_utc=_datetime_text(state.updated_at_utc),
            metadata={
                "relationship_semantics": "channel_references_connection",
                "channel_id": state.channel_id,
                "connection_id": state.connection_id,
            },
        ),
    )


def _reference_relationship(
    source_ref: TraceableObjectRef,
    *,
    object_id: str | None,
    object_kind: str,
    owner_domain: str,
    owner_component: str,
    metadata_key: str,
    relationship_suffix: str,
    lifecycle_status: str,
    operation_id: str | None,
    task_id: str | None,
    correlation_id: str | None,
) -> tuple[TraceableRelationshipRef, ...]:
    if object_id is None:
        return ()
    return (
        TraceableRelationshipRef(
            relationship_id=(
                f"{source_ref.object_id}.references_{relationship_suffix}."
                f"{object_id}"
            ),
            relationship_type="references",
            source_ref=source_ref,
            target_ref=TraceableObjectRef(
                object_id=object_id,
                object_kind=object_kind,
                owner_domain=owner_domain,
                owner_component=owner_component,
                metadata={metadata_key: object_id},
            ),
            direction="outbound",
            lifecycle_status=lifecycle_status,
            operation_id=operation_id,
            task_id=task_id,
            correlation_id=correlation_id,
            metadata={
                "relationship_semantics": "runtime_state_reference",
                metadata_key: object_id,
            },
        ),
    )


def _process_summary_metadata(state: ProcessRuntimeState) -> Mapping[str, object]:
    return {
        "process_id": state.process_id,
        "label": state.label,
        "kind": state.kind.value,
        "status": state.status.value,
        "pid": state.pid,
        "command_preview": _command_preview(state.command),
        "command_token_count": len(state.command),
        "operation_id": state.operation_id,
        "task_id": state.task_id,
        "service_id": state.service_id,
        "correlation_id": state.correlation_id,
        "started_at_utc": state.started_at_utc,
        "updated_at_utc": state.updated_at_utc,
        "completed_at_utc": state.completed_at_utc,
        "exit_code": state.exit_code,
        "error_message": state.error_message,
        "metadata": dict(state.metadata),
    }


def _connection_summary_metadata(
    state: ConnectionRuntimeState,
    *,
    channel_states: tuple[WebSocketChannelRuntimeState, ...],
    definition: ConnectionDefinition | None,
) -> Mapping[str, object]:
    endpoint = definition.endpoint if definition is not None else None
    return {
        "connection_id": state.connection_id,
        "label": state.label,
        "kind": state.kind.value,
        "protocol": state.protocol.value,
        "direction": state.direction.value,
        "status": state.status.value,
        "registered_at_utc": state.registered_at_utc,
        "updated_at_utc": state.updated_at_utc,
        "connected_at_utc": state.connected_at_utc,
        "disconnected_at_utc": state.disconnected_at_utc,
        "last_heartbeat_at_utc": state.last_heartbeat_at_utc,
        "last_error_message": state.last_error_message,
        "service_id": state.service_id,
        "process_id": state.process_id,
        "operation_id": state.operation_id,
        "task_id": state.task_id,
        "correlation_id": state.correlation_id,
        "channel_count": len(channel_states),
        "channel_ids": tuple(channel.channel_id for channel in channel_states),
        "endpoint_label": endpoint.label if endpoint is not None else None,
        "endpoint_protocol": (
            endpoint.protocol.value if endpoint is not None else None
        ),
        "endpoint_address_redacted": endpoint is not None,
        "metadata": dict(state.metadata),
    }


def _channel_summary_metadata(
    state: WebSocketChannelRuntimeState,
    *,
    definition: WebSocketChannelDefinition | None,
) -> Mapping[str, object]:
    return {
        "channel_id": state.channel_id,
        "connection_id": state.connection_id,
        "label": state.label,
        "topic": definition.topic if definition is not None else None,
        "status": state.status.value,
        "registered_at_utc": state.registered_at_utc,
        "updated_at_utc": state.updated_at_utc,
        "last_message_at_utc": state.last_message_at_utc,
        "received_count": state.received_count,
        "sent_count": state.sent_count,
        "error_count": state.error_count,
        "metadata": dict(state.metadata),
    }


def _resolve_runtime_snapshot(
    *,
    state_store: StateStore | None,
    runtime_snapshot: RuntimeSnapshot | None,
) -> tuple[RuntimeSnapshot | None, tuple[str, ...]]:
    if runtime_snapshot is not None:
        if not isinstance(runtime_snapshot, RuntimeSnapshot):
            return None, ("runtime_snapshot must be a RuntimeSnapshot",)
        return runtime_snapshot, ()
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return None, ("state_store must be a StateStore",)
        return state_store.runtime_snapshot(), ()
    return None, ()


def _resolve_process_states(
    *,
    process_manager: ProcessManager | None,
    runtime_snapshot: RuntimeSnapshot | None,
    state_store: StateStore | None,
    process_states: Iterable[ProcessRuntimeState] | None,
) -> tuple[tuple[ProcessRuntimeState, ...], tuple[str, ...]]:
    if process_states is not None:
        return _checked_process_states(process_states)
    if process_manager is not None:
        if not isinstance(process_manager, ProcessManager):
            return (), ("process_manager must be a ProcessManager",)
        return _checked_process_states(process_manager.active_processes())
    if runtime_snapshot is not None:
        return _checked_process_states(runtime_snapshot.process_states)
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return (), ("state_store must be a StateStore",)
        return _checked_process_states(state_store.processes_state())
    return (), ()


def _resolve_connection_states(
    *,
    connection_registry: ConnectionRegistry | None,
    runtime_snapshot: RuntimeSnapshot | None,
    state_store: StateStore | None,
    connection_states: Iterable[ConnectionRuntimeState] | None,
) -> tuple[tuple[ConnectionRuntimeState, ...], tuple[str, ...]]:
    if connection_states is not None:
        return _checked_connection_states(connection_states)
    if connection_registry is not None:
        if not isinstance(connection_registry, ConnectionRegistry):
            return (), ("connection_registry must be a ConnectionRegistry",)
        return _checked_connection_states(connection_registry.connection_states())
    if runtime_snapshot is not None:
        return _checked_connection_states(runtime_snapshot.connection_states)
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return (), ("state_store must be a StateStore",)
        return _checked_connection_states(state_store.connection_states())
    return (), ()


def _resolve_channel_states(
    *,
    connection_registry: ConnectionRegistry | None,
    runtime_snapshot: RuntimeSnapshot | None,
    state_store: StateStore | None,
    websocket_channel_states: Iterable[WebSocketChannelRuntimeState] | None,
) -> tuple[tuple[WebSocketChannelRuntimeState, ...], tuple[str, ...]]:
    if websocket_channel_states is not None:
        return _checked_channel_states(websocket_channel_states)
    if connection_registry is not None:
        if not isinstance(connection_registry, ConnectionRegistry):
            return (), ("connection_registry must be a ConnectionRegistry",)
        return _checked_channel_states(connection_registry.websocket_channel_states())
    if runtime_snapshot is not None:
        return _checked_channel_states(runtime_snapshot.websocket_channel_states)
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return (), ("state_store must be a StateStore",)
        return _checked_channel_states(state_store.websocket_channel_states())
    return (), ()


def _resolve_connection_definitions(
    *,
    connection_registry: ConnectionRegistry | None,
    connection_definitions: Iterable[ConnectionDefinition] | None,
) -> tuple[tuple[ConnectionDefinition, ...], tuple[str, ...]]:
    if connection_definitions is not None:
        return _checked_connection_definitions(connection_definitions)
    if connection_registry is not None:
        if not isinstance(connection_registry, ConnectionRegistry):
            return (), ("connection_registry must be a ConnectionRegistry",)
        return _checked_connection_definitions(connection_registry.list_connections())
    return (), ()


def _resolve_channel_definitions(
    *,
    connection_registry: ConnectionRegistry | None,
    websocket_channel_definitions: Iterable[WebSocketChannelDefinition] | None,
) -> tuple[tuple[WebSocketChannelDefinition, ...], tuple[str, ...]]:
    if websocket_channel_definitions is not None:
        return _checked_channel_definitions(websocket_channel_definitions)
    if connection_registry is not None:
        if not isinstance(connection_registry, ConnectionRegistry):
            return (), ("connection_registry must be a ConnectionRegistry",)
        return _checked_channel_definitions(
            connection_registry.list_websocket_channels()
        )
    return (), ()


def _checked_process_states(
    values: Iterable[ProcessRuntimeState],
) -> tuple[tuple[ProcessRuntimeState, ...], tuple[str, ...]]:
    states: list[ProcessRuntimeState] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, ProcessRuntimeState):
            errors.append("process_states entries must be ProcessRuntimeState")
            continue
        states.append(value)
    return tuple(states), tuple(errors)


def _checked_connection_states(
    values: Iterable[ConnectionRuntimeState],
) -> tuple[tuple[ConnectionRuntimeState, ...], tuple[str, ...]]:
    states: list[ConnectionRuntimeState] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, ConnectionRuntimeState):
            errors.append("connection_states entries must be ConnectionRuntimeState")
            continue
        states.append(value)
    return tuple(states), tuple(errors)


def _checked_channel_states(
    values: Iterable[WebSocketChannelRuntimeState],
) -> tuple[tuple[WebSocketChannelRuntimeState, ...], tuple[str, ...]]:
    states: list[WebSocketChannelRuntimeState] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, WebSocketChannelRuntimeState):
            errors.append(
                "websocket_channel_states entries must be WebSocketChannelRuntimeState"
            )
            continue
        states.append(value)
    return tuple(states), tuple(errors)


def _checked_connection_definitions(
    values: Iterable[ConnectionDefinition],
) -> tuple[tuple[ConnectionDefinition, ...], tuple[str, ...]]:
    definitions: list[ConnectionDefinition] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, ConnectionDefinition):
            errors.append(
                "connection_definitions entries must be ConnectionDefinition"
            )
            continue
        definitions.append(value)
    return tuple(definitions), tuple(errors)


def _checked_channel_definitions(
    values: Iterable[WebSocketChannelDefinition],
) -> tuple[tuple[WebSocketChannelDefinition, ...], tuple[str, ...]]:
    definitions: list[WebSocketChannelDefinition] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, WebSocketChannelDefinition):
            errors.append(
                "websocket_channel_definitions entries must be "
                "WebSocketChannelDefinition"
            )
            continue
        definitions.append(value)
    return tuple(definitions), tuple(errors)


def _normalize_process_states(
    values: Iterable[ProcessRuntimeState],
) -> tuple[ProcessRuntimeState, ...]:
    states, errors = _checked_process_states(values)
    if errors:
        raise TypeError(errors[0])
    return states


def _normalize_connection_states(
    values: Iterable[ConnectionRuntimeState],
) -> tuple[ConnectionRuntimeState, ...]:
    states, errors = _checked_connection_states(values)
    if errors:
        raise TypeError(errors[0])
    return states


def _normalize_channel_states(
    values: Iterable[WebSocketChannelRuntimeState],
) -> tuple[WebSocketChannelRuntimeState, ...]:
    states, errors = _checked_channel_states(values)
    if errors:
        raise TypeError(errors[0])
    return states


def _relationships_from_summaries(
    summaries: Iterable[TraceableObjectSummary],
) -> tuple[TraceableRelationshipRef, ...]:
    return _dedupe_relationships(
        relationship
        for summary in summaries
        for relationship in summary.relationship_refs
    )


def _relationships_for_summary(
    summary: TraceableObjectSummary,
    relationships: Iterable[TraceableRelationshipRef],
) -> tuple[TraceableRelationshipRef, ...]:
    object_id = summary.object_ref.object_id
    object_kind = summary.object_ref.object_kind
    return tuple(
        relationship
        for relationship in relationships
        if (
            relationship.source_ref.object_id == object_id
            and relationship.source_ref.object_kind == object_kind
        )
        or (
            relationship.target_ref.object_id == object_id
            and relationship.target_ref.object_kind == object_kind
        )
    )


def _process_connection_legends() -> tuple[tuple[object, ...], tuple[str, ...]]:
    warnings: list[str] = []
    legends = []
    for family_id in _TRACE_FAMILY_IDS:
        legend = object_family_legend_by_id(family_id)
        if legend is None:
            warnings.append(f"Missing object family legend for {family_id}")
            continue
        legends.append(legend)
    return tuple(legends), tuple(warnings)


def _process_connection_relationship_definitions() -> tuple[object, ...]:
    definitions: list[object] = []
    for relationship_type in _TRACE_RELATIONSHIP_TYPES:
        definitions.extend(object_relationship_definitions_by_type(relationship_type))
    return tuple(definitions)


def _dedupe_relationships(
    relationships: Iterable[TraceableRelationshipRef],
) -> tuple[TraceableRelationshipRef, ...]:
    records: dict[str, TraceableRelationshipRef] = {}
    for relationship in relationships:
        relationship_id = relationship.relationship_id or (
            f"{relationship.source_ref.object_id}."
            f"{relationship.relationship_type}."
            f"{relationship.target_ref.object_id}"
        )
        records.setdefault(relationship_id, relationship)
    return tuple(records[key] for key in sorted(records))


def _find_summary(
    summaries: tuple[TraceableObjectSummary, ...],
    object_id: str,
    *,
    object_kind: str | None,
) -> TraceableObjectSummary | None:
    for summary in summaries:
        if object_kind is not None and summary.object_ref.object_kind != object_kind:
            continue
        if object_id == summary.object_ref.object_id:
            return summary
        for key in ("process_id", "connection_id", "channel_id"):
            if object_id == summary.metadata.get(key):
                return summary
    return None


def _kind_from_summary(summary: TraceableObjectSummary | None) -> str | None:
    if summary is None:
        return None
    return summary.object_ref.object_kind


def _legend_for_kind(object_kind: str) -> object | None:
    if object_kind in _TRACE_FAMILY_IDS:
        return object_family_legend_by_id(object_kind)
    return None


def _command_preview(command: tuple[str, ...]) -> str:
    first_token = command[0] if command else "<empty>"
    return f"{first_token} ({len(command)} args)"


def _optional_ref_tuple(value: str | None) -> tuple[str, ...]:
    return (value,) if value is not None else ()


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_process_state(value: ProcessRuntimeState) -> None:
    if not isinstance(value, ProcessRuntimeState):
        raise TypeError("state must be a ProcessRuntimeState")


def _validate_connection_state(value: ConnectionRuntimeState) -> None:
    if not isinstance(value, ConnectionRuntimeState):
        raise TypeError("state must be a ConnectionRuntimeState")


def _validate_channel_state(value: WebSocketChannelRuntimeState) -> None:
    if not isinstance(value, WebSocketChannelRuntimeState):
        raise TypeError("state must be a WebSocketChannelRuntimeState")


def _validate_optional_connection_definition(
    value: ConnectionDefinition | None,
) -> None:
    if value is not None and not isinstance(value, ConnectionDefinition):
        raise TypeError("definition must be a ConnectionDefinition or None")


def _validate_optional_channel_definition(
    value: WebSocketChannelDefinition | None,
) -> None:
    if value is not None and not isinstance(value, WebSocketChannelDefinition):
        raise TypeError("definition must be a WebSocketChannelDefinition or None")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


__all__ = [
    "PROCESS_CONNECTION_TRACE_OWNER_COMPONENT",
    "PROCESS_CONNECTION_TRACE_OWNER_DOMAIN",
    "PROCESS_CONNECTION_TRACE_PROVIDER_ID",
    "PROCESS_CONNECTION_TRACE_RUNTIME_KIND",
    "PROCESS_CONNECTION_TRACE_SECTION_ID",
    "build_process_connection_trace_provider_descriptor",
    "build_process_connection_trace_section",
    "connection_trace_ref_from_state",
    "connection_trace_summary_from_state",
    "interrogate_process_connection_trace",
    "process_connection_relationships_from_state",
    "process_trace_ref_from_state",
    "process_trace_summary_from_state",
    "websocket_channel_trace_ref_from_state",
    "websocket_channel_trace_summary_from_state",
]
