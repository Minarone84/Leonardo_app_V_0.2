from pathlib import Path

import pytest

from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.operations import OperationKind, OperationLifecycleStatus
from leonardo.contracts.traceable_object import TraceableObjectSummary
from leonardo.core.audit_log import AuditLog
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager
from leonardo.core.task_operation_trace import (
    TASK_OPERATION_TRACE_PROVIDER_ID,
    TASK_OPERATION_TRACE_RUNTIME_KIND,
    build_task_operation_trace_provider_descriptor,
    build_task_operation_trace_section,
    interrogate_task_operation_trace,
    operation_trace_summary_from_state,
    task_operation_relationships_from_state,
    task_trace_summary_from_state,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "task_operation_trace.py"
_RUNTIME_MANAGER_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "runtime_manager.py"


def test_task_operation_trace_provider_descriptor_is_read_only() -> None:
    descriptor = build_task_operation_trace_provider_descriptor()

    assert descriptor.provider_id == TASK_OPERATION_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.object_kinds == ("task", "operation")
    assert descriptor.family_ids == ("task", "operation")
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_interrogation is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert "schedules_task" in descriptor.relationship_types
    assert "references" in descriptor.relationship_types


def test_active_task_state_produces_trace_summary() -> None:
    task_manager, operation_registry, state_store, _audit_log = _runtime()
    task_state, operation_state = _linked_task_and_operation(
        operation_registry,
        state_store,
    )

    summary = task_trace_summary_from_state(task_state)

    assert isinstance(summary, TraceableObjectSummary)
    assert summary.object_ref.object_id == "task-1"
    assert summary.object_ref.object_kind == "task"
    assert summary.object_ref.owner_domain == "core"
    assert summary.object_ref.owner_component == "TaskManager"
    assert summary.display_name == "download-preview"
    assert summary.lifecycle_status == "running"
    assert summary.runtime_or_persistent == TASK_OPERATION_TRACE_RUNTIME_KIND
    assert summary.metadata["task_id"] == "task-1"
    assert summary.metadata["task_name"] == "download-preview"
    assert summary.metadata["operation_id"] == operation_state.operation_id
    assert summary.metadata["service_id"] == "service-1"
    assert summary.metadata["correlation_id"] == "corr-1"
    assert summary.metadata["status"] == "running"
    assert summary.metadata["cancellable"] is True
    assert summary.metadata["cancel_requested"] is False
    assert summary.operation_refs == (operation_state.operation_id,)
    assert summary.task_refs == ("task-1",)
    assert summary.correlation_refs == ("corr-1",)
    assert summary.relationship_refs[0].relationship_type == "references"
    assert summary.relationship_refs[0].target_ref.object_id == operation_state.operation_id
    assert task_manager.active_tasks() == (task_state,)


def test_active_operation_state_produces_trace_summary() -> None:
    _task_manager, operation_registry, state_store, _audit_log = _runtime()
    _task_state, operation_state = _linked_task_and_operation(
        operation_registry,
        state_store,
    )

    summary = operation_trace_summary_from_state(operation_state)
    relationship_targets = {
        relationship.target_ref.object_kind: relationship.target_ref.object_id
        for relationship in summary.relationship_refs
    }

    assert summary.object_ref.object_id == operation_state.operation_id
    assert summary.object_ref.object_kind == "operation"
    assert summary.object_ref.owner_component == "OperationRegistry"
    assert summary.display_name == "Download preview"
    assert summary.lifecycle_status == "running"
    assert summary.metadata["operation_id"] == operation_state.operation_id
    assert summary.metadata["operation_kind"] == "user_workflow"
    assert summary.metadata["label"] == "Download preview"
    assert summary.metadata["status"] == "running"
    assert summary.metadata["actor_id"] == "admin-dev"
    assert summary.metadata["session_id"] == "session-admin-dev"
    assert summary.metadata["origin"] == "development"
    assert summary.metadata["window_id"] == "main_window.window"
    assert summary.metadata["action_id"] == "main_window.download_data"
    assert summary.metadata["task_id"] == "task-1"
    assert summary.metadata["correlation_id"] == "corr-1"
    assert summary.metadata["cancel_requested"] is False
    assert summary.metadata["terminal"] is False
    assert relationship_targets["task"] == "task-1"
    assert relationship_targets["action"] == "main_window.download_data"
    assert relationship_targets["window"] == "main_window.window"
    assert relationship_targets["session"] == "session-admin-dev"


def test_task_operation_relationships_include_linked_task_and_operation_refs() -> None:
    _task_manager, operation_registry, state_store, _audit_log = _runtime()
    task_state, operation_state = _linked_task_and_operation(
        operation_registry,
        state_store,
    )

    relationships = task_operation_relationships_from_state(
        task_states=(task_state,),
        operation_states=(operation_state,),
    )
    relationship_types = {relationship.relationship_type for relationship in relationships}
    relationship_ids = {relationship.relationship_id for relationship in relationships}

    assert "schedules_task" in relationship_types
    assert "references" in relationship_types
    assert f"{operation_state.operation_id}.schedules_task.task-1" in relationship_ids
    assert f"task-1.references_operation.{operation_state.operation_id}" in relationship_ids


def test_missing_optional_ids_do_not_create_fake_relationships() -> None:
    _task_manager, operation_registry, state_store, _audit_log = _runtime()
    task_state = state_store.task_started(
        task_id="task-without-operation",
        task_name="orphan-task",
    )
    operation_state = operation_registry.request_operation(
        operation_kind=OperationKind.SYSTEM_WORKFLOW,
        label="Operation without links",
    )

    relationships = task_operation_relationships_from_state(
        task_states=(task_state,),
        operation_states=(operation_state,),
    )

    assert relationships == ()


def test_object_map_section_includes_task_operation_summaries_legends_and_defs() -> None:
    task_manager, operation_registry, state_store, _audit_log = _runtime()
    _linked_task_and_operation(operation_registry, state_store)

    section = build_task_operation_trace_section(
        task_manager=task_manager,
        operation_registry=operation_registry,
    )
    summary_kinds = {summary.object_ref.object_kind for summary in section.summaries}
    family_ids = {legend.family_id for legend in section.legends}
    relationship_types = {
        definition.relationship_type
        for definition in section.relationship_definitions
    }

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "core.tasks_operations"
    assert section.provider_id == TASK_OPERATION_TRACE_PROVIDER_ID
    assert section.owner_domain == "core"
    assert summary_kinds == {"task", "operation"}
    assert family_ids == {"task", "operation"}
    assert "schedules_task" in relationship_types
    assert "references" in relationship_types
    assert "records_audit" in relationship_types
    assert "creates_operation" in relationship_types
    assert section.metadata["task_count"] == 1
    assert section.metadata["operation_count"] == 1
    assert section.errors == ()


def test_trace_section_can_read_from_state_store_or_runtime_snapshot() -> None:
    _task_manager, operation_registry, state_store, _audit_log = _runtime()
    task_state, operation_state = _linked_task_and_operation(
        operation_registry,
        state_store,
    )

    state_store_section = build_task_operation_trace_section(state_store=state_store)
    snapshot_section = build_task_operation_trace_section(
        runtime_snapshot=state_store.runtime_snapshot(),
    )

    assert state_store_section.metadata["task_ids"] == ("task-1",)
    assert state_store_section.metadata["operation_ids"] == (
        operation_state.operation_id,
    )
    assert snapshot_section.metadata["task_ids"] == (task_state.task_id,)
    assert snapshot_section.metadata["operation_ids"] == (operation_state.operation_id,)


def test_interrogate_task_and_operation_trace_returns_read_only_reports() -> None:
    task_manager, operation_registry, state_store, _audit_log = _runtime()
    _task_state, operation_state = _linked_task_and_operation(
        operation_registry,
        state_store,
    )

    task_report = interrogate_task_operation_trace(
        "task-1",
        object_kind="task",
        task_manager=task_manager,
        operation_registry=operation_registry,
    )
    operation_report = interrogate_task_operation_trace(
        operation_state.operation_id,
        object_kind="operation",
        task_manager=task_manager,
        operation_registry=operation_registry,
    )

    assert task_report.target_ref.object_kind == "task"
    assert task_report.summary is not None
    assert task_report.family_legend is not None
    assert task_report.family_legend.family_id == "task"
    assert task_report.blockers == ()
    assert task_report.metadata["read_only"] is True
    assert operation_report.target_ref.object_kind == "operation"
    assert operation_report.summary is not None
    assert operation_report.family_legend is not None
    assert operation_report.family_legend.family_id == "operation"
    assert any(
        relationship.relationship_type == "schedules_task"
        for relationship in operation_report.relationships
    )


def test_interrogate_missing_task_operation_reports_blocker() -> None:
    report = interrogate_task_operation_trace("missing-operation", object_kind="operation")

    assert report.summary is None
    assert report.target_ref.object_id == "missing-operation"
    assert report.target_ref.object_kind == "operation"
    assert report.blockers == ("Task/operation not found: missing-operation",)
    assert report.errors == ()


def test_trace_helpers_do_not_mutate_runtime_state_or_audit_log() -> None:
    task_manager, operation_registry, state_store, audit_log = _runtime()
    _linked_task_and_operation(operation_registry, state_store)
    before = (
        task_manager.active_tasks(),
        operation_registry.active_operations(),
        state_store.tasks_state(),
        state_store.operations_state(),
        audit_log.snapshot(),
    )

    build_task_operation_trace_section(
        task_manager=task_manager,
        operation_registry=operation_registry,
    )
    interrogate_task_operation_trace(
        "task-1",
        object_kind="task",
        task_manager=task_manager,
        operation_registry=operation_registry,
    )
    after = (
        task_manager.active_tasks(),
        operation_registry.active_operations(),
        state_store.tasks_state(),
        state_store.operations_state(),
        audit_log.snapshot(),
    )

    assert after == before


def test_malformed_explicit_states_are_reported_without_mutation() -> None:
    section = build_task_operation_trace_section(
        task_states=(object(),),
        operation_states=(object(),),
    )

    assert section.summaries == ()
    assert "task_states entries must be TaskRuntimeState" in section.errors
    assert "operation_states entries must be OperationRuntimeState" in section.errors


def test_task_operation_trace_has_no_runner_runtime_manager_or_domain_wiring() -> None:
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
        "discover(",
        "submit_command",
        "cancel_task",
        "cancel_operation",
        "DownloadManager",
        "DownloadExecutionManager",
        "DownloadRequestBuilderWindow",
        "PySide6",
        "PyQt6",
        "QtWidgets",
        "QApplication",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "sub" + "process",
        "shell" + "=True",
        "requests",
        "aio" + "http",
        "web" + "sockets",
    )

    for token in blocked_tokens:
        assert token not in source


def test_runtime_manager_remains_unwired_from_task_operation_trace() -> None:
    source = _RUNTIME_MANAGER_SOURCE.read_text(encoding="utf-8")

    assert "task_operation_trace" not in source
    assert "build_task_operation_trace_section" not in source
    assert "TASK_OPERATION_TRACE_PROVIDER_ID" not in source


def _runtime() -> tuple[TaskManager, OperationRegistry, StateStore, AuditLog]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    task_manager = TaskManager(state_store)
    operation_registry = OperationRegistry(state_store)
    return task_manager, operation_registry, state_store, audit_log


def _linked_task_and_operation(
    operation_registry: OperationRegistry,
    state_store: StateStore,
) -> tuple[object, object]:
    operation = operation_registry.request_operation(
        operation_kind=OperationKind.USER_WORKFLOW,
        label="Download preview",
        actor_id="admin-dev",
        session_id="session-admin-dev",
        origin=ActorOrigin.DEVELOPMENT,
        window_id="main_window.window",
        action_id="main_window.download_data",
        correlation_id="corr-1",
        metadata={"command_id": "command-1", "domain": "download"},
    )
    running = operation_registry.mark_running(operation.operation_id, task_id="task-1")
    task = state_store.task_started(
        task_id="task-1",
        task_name="download-preview",
        operation_id=operation.operation_id,
        service_id="service-1",
        correlation_id="corr-1",
        metadata={"command_id": "command-1"},
    )

    assert running.status is OperationLifecycleStatus.RUNNING
    return task, running
