"""Read-only trace helpers for Core task and operation runtime state.

The helpers in this module expose active TaskManager and OperationRegistry read
models through the shared traceability and Object Map report contracts. They do
not schedule tasks, cancel tasks, submit commands, register Object Map
providers, wire Runtime Manager, mutate StateStore, or emit audit events.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from leonardo.contracts.object_family_legends import object_family_legend_by_id
from leonardo.contracts.object_map import ObjectMapProviderDescriptor, ObjectMapSection
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.operations import (
    OperationBlocker,
    OperationLifecycleStatus,
    OperationRuntimeState,
    OperationWarning,
)
from leonardo.contracts.runtime import (
    RuntimeSnapshot,
    TaskLifecycleStatus,
    TaskRuntimeState,
)
from leonardo.contracts.traceable_object import (
    ObjectInterrogationReport,
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager


TASK_OPERATION_TRACE_PROVIDER_ID = "core.task_operation.trace"
TASK_OPERATION_TRACE_SECTION_ID = "core.tasks_operations"
TASK_OPERATION_TRACE_OWNER_DOMAIN = "core"
TASK_OPERATION_TRACE_OWNER_COMPONENT = (
    "TaskManager / OperationRegistry trace helper"
)
TASK_OPERATION_TRACE_RUNTIME_KIND = "runtime"
TASK_OPERATION_TRACE_DOC = "docs/core_docs/TASK_OPERATION_FAMILY_TRACE.md"
TASK_OPERATION_TRACE_TEST = "tests/core_test/test_task_operation_family_trace.py"

_TRACE_CONTRACTS = (
    "leonardo.contracts.runtime.TaskRuntimeState",
    "leonardo.contracts.operations.OperationRuntimeState",
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
    TASK_OPERATION_TRACE_DOC,
)


def build_task_operation_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Return the read-only Object Map provider descriptor for tasks/operations."""

    return ObjectMapProviderDescriptor(
        provider_id=TASK_OPERATION_TRACE_PROVIDER_ID,
        provider_name="Core Task / Operation Trace",
        owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
        owner_component=TASK_OPERATION_TRACE_OWNER_COMPONENT,
        object_kinds=("task", "operation"),
        family_ids=("task", "operation"),
        relationship_types=("schedules_task", "references"),
        supports_summary_listing=True,
        supports_interrogation=True,
        supports_relationship_listing=True,
        runtime_or_persistent=TASK_OPERATION_TRACE_RUNTIME_KIND,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=_TRACE_CONTRACTS,
        related_docs=_TRACE_DOCS,
        related_tests=(TASK_OPERATION_TRACE_TEST,),
        metadata={
            "task_source": "TaskManager.active_tasks()",
            "operation_source": "OperationRegistry.active_operations()",
        },
        extra={
            "forbidden_behavior": (
                "task_scheduling",
                "task_cancellation",
                "command_submission",
                "operation_transition",
                "runtime_state_mutation",
                "audit_emission",
                "runtime_manager_wiring",
                "object_map_service_registration",
            )
        },
    )


def task_trace_ref_from_state(state: TaskRuntimeState) -> TraceableObjectRef:
    """Build a traceable object reference for one active task state."""

    _validate_task_state(state)
    return TraceableObjectRef(
        object_id=state.task_id,
        object_kind="task",
        owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
        owner_component="TaskManager",
        label=state.task_name,
        metadata={
            "task_id": state.task_id,
            "task_name": state.task_name,
            "operation_id": state.operation_id,
            "service_id": state.service_id,
            "correlation_id": state.correlation_id,
        },
    )


def operation_trace_ref_from_state(
    state: OperationRuntimeState,
) -> TraceableObjectRef:
    """Build a traceable object reference for one active operation state."""

    _validate_operation_state(state)
    return TraceableObjectRef(
        object_id=state.operation_id,
        object_kind="operation",
        owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
        owner_component="OperationRegistry",
        label=state.label or state.operation_kind.value,
        metadata={
            "operation_id": state.operation_id,
            "operation_kind": state.operation_kind.value,
            "label": state.label,
            "task_id": state.task_id,
            "action_id": state.action_id,
            "window_id": state.window_id,
            "session_id": state.session_id,
            "correlation_id": state.correlation_id,
        },
    )


def task_trace_summary_from_state(
    state: TaskRuntimeState,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one active task state."""

    _validate_task_state(state)
    object_ref = task_trace_ref_from_state(state)
    relationships = _task_relationships_from_state(state, object_ref)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=state.status.value,
        runtime_or_persistent=TASK_OPERATION_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(state.started_at_utc),
        updated_at_utc=_datetime_text(state.updated_at_utc),
        display_name=state.task_name,
        metadata=_task_summary_metadata(state),
        relationship_refs=relationships,
        audit_refs=(),
        operation_refs=_optional_ref_tuple(state.operation_id),
        task_refs=(state.task_id,),
        correlation_refs=_optional_ref_tuple(state.correlation_id),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "TaskManager.active_tasks",
            "audit_reference_policy": "AuditLog remains historical truth",
        },
    )


def operation_trace_summary_from_state(
    state: OperationRuntimeState,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one active operation state."""

    _validate_operation_state(state)
    object_ref = operation_trace_ref_from_state(state)
    relationships = _operation_relationships_from_state(state, object_ref)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=state.status.value,
        runtime_or_persistent=TASK_OPERATION_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(state.requested_at_utc),
        updated_at_utc=_datetime_text(state.updated_at_utc),
        display_name=state.label,
        metadata=_operation_summary_metadata(state),
        relationship_refs=relationships,
        permission_refs=(),
        audit_refs=(),
        operation_refs=(state.operation_id,),
        task_refs=_optional_ref_tuple(state.task_id),
        correlation_refs=_optional_ref_tuple(state.correlation_id),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "OperationRegistry.active_operations",
            "audit_reference_policy": "AuditLog remains historical truth",
        },
    )


def task_operation_relationships_from_state(
    *,
    task_states: Iterable[TaskRuntimeState] = (),
    operation_states: Iterable[OperationRuntimeState] = (),
) -> tuple[TraceableRelationshipRef, ...]:
    """Build read-only relationship refs from active task/operation states."""

    relationships: list[TraceableRelationshipRef] = []
    for state in _normalize_task_states(task_states):
        relationships.extend(
            _task_relationships_from_state(state, task_trace_ref_from_state(state))
        )
    for state in _normalize_operation_states(operation_states):
        relationships.extend(
            _operation_relationships_from_state(
                state,
                operation_trace_ref_from_state(state),
            )
        )
    return _dedupe_relationships(relationships)


def build_task_operation_trace_section(
    *,
    task_manager: TaskManager | None = None,
    operation_registry: OperationRegistry | None = None,
    state_store: StateStore | None = None,
    runtime_snapshot: RuntimeSnapshot | None = None,
    task_states: Iterable[TaskRuntimeState] | None = None,
    operation_states: Iterable[OperationRuntimeState] | None = None,
) -> ObjectMapSection:
    """Build a read-only Object Map section for active tasks and operations."""

    tasks, task_errors = _resolve_task_states(
        task_manager=task_manager,
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
        task_states=task_states,
    )
    operations, operation_errors = _resolve_operation_states(
        operation_registry=operation_registry,
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
        operation_states=operation_states,
    )

    summaries: list[TraceableObjectSummary] = []
    errors = [*task_errors, *operation_errors]
    for state in tasks:
        try:
            summaries.append(task_trace_summary_from_state(state))
        except (TypeError, ValueError) as error:
            errors.append(f"Task trace skipped for {state!r}: {error}")
    for state in operations:
        try:
            summaries.append(operation_trace_summary_from_state(state))
        except (TypeError, ValueError) as error:
            errors.append(f"Operation trace skipped for {state!r}: {error}")

    relationships = _dedupe_relationships(
        relationship
        for summary in summaries
        for relationship in summary.relationship_refs
    )
    legends, legend_warnings = _task_operation_legends()

    return ObjectMapSection(
        section_id=TASK_OPERATION_TRACE_SECTION_ID,
        provider_id=TASK_OPERATION_TRACE_PROVIDER_ID,
        owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
        object_kind="task_operation",
        family_id="task_operation",
        title="Core Tasks And Operations",
        summaries=tuple(summaries),
        relationships=relationships,
        legends=legends,
        relationship_definitions=_task_operation_relationship_definitions(),
        warnings=legend_warnings,
        errors=tuple(errors),
        metadata={
            "task_count": len(tasks),
            "operation_count": len(operations),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
            "task_ids": tuple(state.task_id for state in tasks),
            "operation_ids": tuple(state.operation_id for state in operations),
        },
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "active_task_and_operation_read_models",
        },
    )


def interrogate_task_operation_trace(
    object_id: str,
    *,
    object_kind: str | None = None,
    task_manager: TaskManager | None = None,
    operation_registry: OperationRegistry | None = None,
    state_store: StateStore | None = None,
    runtime_snapshot: RuntimeSnapshot | None = None,
    task_states: Iterable[TaskRuntimeState] | None = None,
    operation_states: Iterable[OperationRuntimeState] | None = None,
) -> ObjectInterrogationReport:
    """Return a read-only interrogation report for one task or operation."""

    _validate_non_empty_string(object_id, "object_id")
    if object_kind is not None and object_kind not in {"task", "operation"}:
        raise ValueError("object_kind must be task, operation, or None")
    section = build_task_operation_trace_section(
        task_manager=task_manager,
        operation_registry=operation_registry,
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
        task_states=task_states,
        operation_states=operation_states,
    )
    summary = _find_summary(section.summaries, object_id, object_kind=object_kind)
    inferred_kind = object_kind or _kind_from_summary(summary) or "task_operation"
    target_ref = (
        summary.object_ref
        if summary is not None
        else TraceableObjectRef(
            object_id=object_id,
            object_kind=inferred_kind,
            owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
            owner_component=TASK_OPERATION_TRACE_OWNER_COMPONENT,
        )
    )
    family_legend = _legend_for_kind(target_ref.object_kind)
    blockers = () if summary is not None else (f"Task/operation not found: {object_id}",)

    return ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=family_legend,
        relationships=summary.relationship_refs if summary is not None else (),
        permissions=summary.permission_refs if summary is not None else (),
        audit_refs=summary.audit_refs if summary is not None else (),
        runtime_refs=(object_id,),
        docs=_TRACE_DOCS,
        tests=(TASK_OPERATION_TRACE_TEST,),
        warnings=section.warnings,
        blockers=(*blockers, *section.blockers),
        errors=section.errors,
        metadata={
            "provider_id": TASK_OPERATION_TRACE_PROVIDER_ID,
            "section_id": TASK_OPERATION_TRACE_SECTION_ID,
            "object_id": object_id,
            "object_kind": target_ref.object_kind,
            "read_only": True,
        },
    )


def _task_relationships_from_state(
    state: TaskRuntimeState,
    task_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    if state.operation_id is None:
        return ()
    return (
        TraceableRelationshipRef(
            relationship_id=f"{state.task_id}.references_operation.{state.operation_id}",
            relationship_type="references",
            source_ref=task_ref,
            target_ref=TraceableObjectRef(
                object_id=state.operation_id,
                object_kind="operation",
                owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
                owner_component="OperationRegistry",
                metadata={"operation_id": state.operation_id},
            ),
            direction="outbound",
            lifecycle_status=state.status.value,
            operation_id=state.operation_id,
            task_id=state.task_id,
            correlation_id=state.correlation_id,
            created_at_utc=_datetime_text(state.started_at_utc),
            updated_at_utc=_datetime_text(state.updated_at_utc),
            metadata={
                "relationship_semantics": "task_runtime_state_links_operation",
                "task_id": state.task_id,
                "operation_id": state.operation_id,
            },
        ),
    )


def _operation_relationships_from_state(
    state: OperationRuntimeState,
    operation_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    if state.task_id is not None:
        relationships.append(
            TraceableRelationshipRef(
                relationship_id=f"{state.operation_id}.schedules_task.{state.task_id}",
                relationship_type="schedules_task",
                source_ref=operation_ref,
                target_ref=TraceableObjectRef(
                    object_id=state.task_id,
                    object_kind="task",
                    owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
                    owner_component="TaskManager",
                    metadata={"task_id": state.task_id},
                ),
                direction="outbound",
                lifecycle_status=state.status.value,
                operation_id=state.operation_id,
                task_id=state.task_id,
                correlation_id=state.correlation_id,
                created_at_utc=_datetime_text(state.started_at_utc or state.requested_at_utc),
                updated_at_utc=_datetime_text(state.updated_at_utc),
                metadata={
                    "relationship_semantics": "operation_registry_links_task",
                    "operation_id": state.operation_id,
                    "task_id": state.task_id,
                },
            )
        )
    relationships.extend(
        _operation_reference_relationships(
            state,
            operation_ref,
            object_id=state.action_id,
            object_kind="action",
            owner_domain="gui.core",
            owner_component="ActionRegistry",
            metadata_key="action_id",
        )
    )
    relationships.extend(
        _operation_reference_relationships(
            state,
            operation_ref,
            object_id=state.window_id,
            object_kind="window",
            owner_domain="gui",
            owner_component="WindowRegistry",
            metadata_key="window_id",
        )
    )
    relationships.extend(
        _operation_reference_relationships(
            state,
            operation_ref,
            object_id=state.session_id,
            object_kind="session",
            owner_domain=TASK_OPERATION_TRACE_OWNER_DOMAIN,
            owner_component="SessionManager",
            metadata_key="session_id",
        )
    )
    return tuple(relationships)


def _operation_reference_relationships(
    state: OperationRuntimeState,
    operation_ref: TraceableObjectRef,
    *,
    object_id: str | None,
    object_kind: str,
    owner_domain: str,
    owner_component: str,
    metadata_key: str,
) -> tuple[TraceableRelationshipRef, ...]:
    if object_id is None:
        return ()
    return (
        TraceableRelationshipRef(
            relationship_id=f"{state.operation_id}.references_{object_kind}.{object_id}",
            relationship_type="references",
            source_ref=operation_ref,
            target_ref=TraceableObjectRef(
                object_id=object_id,
                object_kind=object_kind,
                owner_domain=owner_domain,
                owner_component=owner_component,
                metadata={metadata_key: object_id},
            ),
            direction="outbound",
            lifecycle_status=state.status.value,
            operation_id=state.operation_id,
            task_id=state.task_id,
            correlation_id=state.correlation_id,
            created_at_utc=_datetime_text(state.requested_at_utc),
            updated_at_utc=_datetime_text(state.updated_at_utc),
            metadata={
                "relationship_semantics": "operation_runtime_state_reference",
                "operation_id": state.operation_id,
                metadata_key: object_id,
            },
        ),
    )


def _task_summary_metadata(state: TaskRuntimeState) -> Mapping[str, object]:
    terminal = state.status in {
        TaskLifecycleStatus.COMPLETED,
        TaskLifecycleStatus.FAILED,
        TaskLifecycleStatus.CANCELLED,
    }
    return {
        "task_id": state.task_id,
        "task_name": state.task_name,
        "status": state.status.value,
        "operation_id": state.operation_id,
        "service_id": state.service_id,
        "correlation_id": state.correlation_id,
        "cancellable": not terminal,
        "cancel_requested": state.status is TaskLifecycleStatus.CANCEL_REQUESTED,
        "started_at_utc": state.started_at_utc,
        "updated_at_utc": state.updated_at_utc,
        "completed_at_utc": state.completed_at_utc,
        "error_message": state.error_message,
        "metadata": dict(state.metadata),
    }


def _operation_summary_metadata(state: OperationRuntimeState) -> Mapping[str, object]:
    return {
        "operation_id": state.operation_id,
        "operation_kind": state.operation_kind.value,
        "label": state.label,
        "status": state.status.value,
        "actor_id": state.actor_id,
        "session_id": state.session_id,
        "origin": state.origin.value if state.origin is not None else None,
        "window_id": state.window_id,
        "action_id": state.action_id,
        "task_id": state.task_id,
        "correlation_id": state.correlation_id,
        "blockers": tuple(_blocker_metadata(blocker) for blocker in state.blockers),
        "warnings": tuple(_warning_metadata(warning) for warning in state.warnings),
        "error_message": state.error_message,
        "requested_at_utc": state.requested_at_utc,
        "started_at_utc": state.started_at_utc,
        "updated_at_utc": state.updated_at_utc,
        "completed_at_utc": state.completed_at_utc,
        "cancel_requested": state.status is OperationLifecycleStatus.CANCEL_REQUESTED,
        "terminal": state.is_terminal,
        "metadata": dict(state.metadata),
    }


def _blocker_metadata(blocker: OperationBlocker) -> Mapping[str, object]:
    return {
        "code": blocker.code,
        "message": blocker.message,
        "metadata": dict(blocker.metadata),
    }


def _warning_metadata(warning: OperationWarning) -> Mapping[str, object]:
    return {
        "code": warning.code,
        "message": warning.message,
        "metadata": dict(warning.metadata),
    }


def _resolve_task_states(
    *,
    task_manager: TaskManager | None,
    state_store: StateStore | None,
    runtime_snapshot: RuntimeSnapshot | None,
    task_states: Iterable[TaskRuntimeState] | None,
) -> tuple[tuple[TaskRuntimeState, ...], tuple[str, ...]]:
    if task_states is not None:
        return _checked_task_states(task_states)
    if task_manager is not None:
        if not isinstance(task_manager, TaskManager):
            return (), ("task_manager must be a TaskManager",)
        return _checked_task_states(task_manager.active_tasks())
    if runtime_snapshot is not None:
        if not isinstance(runtime_snapshot, RuntimeSnapshot):
            return (), ("runtime_snapshot must be a RuntimeSnapshot",)
        return _checked_task_states(runtime_snapshot.task_states)
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return (), ("state_store must be a StateStore",)
        return _checked_task_states(state_store.tasks_state())
    return (), ()


def _resolve_operation_states(
    *,
    operation_registry: OperationRegistry | None,
    state_store: StateStore | None,
    runtime_snapshot: RuntimeSnapshot | None,
    operation_states: Iterable[OperationRuntimeState] | None,
) -> tuple[tuple[OperationRuntimeState, ...], tuple[str, ...]]:
    if operation_states is not None:
        return _checked_operation_states(operation_states)
    if operation_registry is not None:
        if not isinstance(operation_registry, OperationRegistry):
            return (), ("operation_registry must be an OperationRegistry",)
        return _checked_operation_states(operation_registry.active_operations())
    if runtime_snapshot is not None:
        if not isinstance(runtime_snapshot, RuntimeSnapshot):
            return (), ("runtime_snapshot must be a RuntimeSnapshot",)
        return _checked_operation_states(runtime_snapshot.operation_states)
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return (), ("state_store must be a StateStore",)
        return _checked_operation_states(state_store.operations_state())
    return (), ()


def _checked_task_states(
    values: Iterable[TaskRuntimeState],
) -> tuple[tuple[TaskRuntimeState, ...], tuple[str, ...]]:
    states: list[TaskRuntimeState] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, TaskRuntimeState):
            errors.append("task_states entries must be TaskRuntimeState")
            continue
        states.append(value)
    return tuple(states), tuple(errors)


def _checked_operation_states(
    values: Iterable[OperationRuntimeState],
) -> tuple[tuple[OperationRuntimeState, ...], tuple[str, ...]]:
    states: list[OperationRuntimeState] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, OperationRuntimeState):
            errors.append("operation_states entries must be OperationRuntimeState")
            continue
        states.append(value)
    return tuple(states), tuple(errors)


def _normalize_task_states(
    values: Iterable[TaskRuntimeState],
) -> tuple[TaskRuntimeState, ...]:
    states, errors = _checked_task_states(values)
    if errors:
        raise TypeError(errors[0])
    return states


def _normalize_operation_states(
    values: Iterable[OperationRuntimeState],
) -> tuple[OperationRuntimeState, ...]:
    states, errors = _checked_operation_states(values)
    if errors:
        raise TypeError(errors[0])
    return states


def _task_operation_legends() -> tuple[tuple[object, ...], tuple[str, ...]]:
    warnings: list[str] = []
    legends = []
    for family_id in ("task", "operation"):
        legend = object_family_legend_by_id(family_id)
        if legend is None:
            warnings.append(f"Missing object family legend for {family_id}")
            continue
        legends.append(legend)
    return tuple(legends), tuple(warnings)


def _task_operation_relationship_definitions() -> tuple[object, ...]:
    return (
        *object_relationship_definitions_by_type("schedules_task"),
        *object_relationship_definitions_by_type("references"),
        *object_relationship_definitions_by_type("depends_on"),
        *object_relationship_definitions_by_type("records_audit"),
        *object_relationship_definitions_by_type("creates_operation"),
    )


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
        if object_id in (summary.metadata.get("task_id"), summary.metadata.get("operation_id")):
            return summary
    return None


def _kind_from_summary(summary: TraceableObjectSummary | None) -> str | None:
    if summary is None:
        return None
    return summary.object_ref.object_kind


def _legend_for_kind(object_kind: str) -> object | None:
    if object_kind in {"task", "operation"}:
        return object_family_legend_by_id(object_kind)
    return None


def _optional_ref_tuple(value: str | None) -> tuple[str, ...]:
    return (value,) if value is not None else ()


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_task_state(state: TaskRuntimeState) -> None:
    if not isinstance(state, TaskRuntimeState):
        raise TypeError("state must be a TaskRuntimeState")


def _validate_operation_state(state: OperationRuntimeState) -> None:
    if not isinstance(state, OperationRuntimeState):
        raise TypeError("state must be an OperationRuntimeState")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


__all__ = [
    "TASK_OPERATION_TRACE_OWNER_COMPONENT",
    "TASK_OPERATION_TRACE_OWNER_DOMAIN",
    "TASK_OPERATION_TRACE_PROVIDER_ID",
    "TASK_OPERATION_TRACE_RUNTIME_KIND",
    "TASK_OPERATION_TRACE_SECTION_ID",
    "build_task_operation_trace_provider_descriptor",
    "build_task_operation_trace_section",
    "interrogate_task_operation_trace",
    "operation_trace_ref_from_state",
    "operation_trace_summary_from_state",
    "task_operation_relationships_from_state",
    "task_trace_ref_from_state",
    "task_trace_summary_from_state",
]
