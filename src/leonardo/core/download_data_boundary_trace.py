"""Read-only Object Map trace helpers for Download Data boundary read models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import TypeVar

from leonardo.contracts.download_data_boundary import (
    DOWNLOAD_DATA_ARTIFACT_ID,
    DownloadDataBoundaryDescriptor,
    DownloadDataCompletionItem,
    DownloadDataCompletionSummary,
    DownloadDataItemStatus,
    DownloadDataOutputRef,
    DownloadDataPartialPersistenceSummary,
    DownloadDataPreflightItem,
    DownloadDataPreflightMode,
    DownloadDataPreflightSummary,
    DownloadDataProgressItem,
    DownloadDataProgressSummary,
    DownloadDataSelectionDraft,
    DownloadDataSelectionSummary,
    DownloadDataStorageTargetRef,
    DownloadDataWorkflowDescriptor,
)
from leonardo.contracts.object_map import (
    ObjectMapProviderDescriptor,
    ObjectMapSection,
)
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.traceable_object import (
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID = "core.download_data_boundary.trace"
DOWNLOAD_DATA_BOUNDARY_TRACE_SECTION_ID = "core.download_data_boundary"

DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND = "download_data_boundary"
DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND = "download_data_workflow"
DOWNLOAD_DATA_SELECTION_OBJECT_KIND = "download_data_selection"
DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND = "download_data_preflight"
DOWNLOAD_DATA_PREFLIGHT_ITEM_OBJECT_KIND = "download_data_preflight_item"
DOWNLOAD_DATA_PROGRESS_OBJECT_KIND = "download_data_progress"
DOWNLOAD_DATA_PROGRESS_ITEM_OBJECT_KIND = "download_data_progress_item"
DOWNLOAD_DATA_COMPLETION_OBJECT_KIND = "download_data_completion"
DOWNLOAD_DATA_COMPLETION_ITEM_OBJECT_KIND = "download_data_completion_item"
DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND = "download_data_storage_target"
DOWNLOAD_DATA_OUTPUT_OBJECT_KIND = "download_data_output"
DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND = "download_data_partial_persistence"
PROVIDER_CAPABILITY_OBJECT_KIND = "provider_capability"
STORAGE_POLICY_OBJECT_KIND = "storage_policy"
OPERATION_OBJECT_KIND = "operation"
TASK_OBJECT_KIND = "task"
PERMISSION_OBJECT_KIND = "permission"
OBJECT_FAMILY_OBJECT_KIND = "object_family"

_DESCRIPTOR_OBJECT_KINDS = (
    DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND,
    DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND,
    DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
    DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND,
    DOWNLOAD_DATA_PREFLIGHT_ITEM_OBJECT_KIND,
    DOWNLOAD_DATA_PROGRESS_OBJECT_KIND,
    DOWNLOAD_DATA_PROGRESS_ITEM_OBJECT_KIND,
    DOWNLOAD_DATA_COMPLETION_OBJECT_KIND,
    DOWNLOAD_DATA_COMPLETION_ITEM_OBJECT_KIND,
    DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND,
    DOWNLOAD_DATA_OUTPUT_OBJECT_KIND,
    DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND,
    PROVIDER_CAPABILITY_OBJECT_KIND,
    STORAGE_POLICY_OBJECT_KIND,
    OPERATION_OBJECT_KIND,
    TASK_OBJECT_KIND,
    PERMISSION_OBJECT_KIND,
    OBJECT_FAMILY_OBJECT_KIND,
)
_RELATED_DOC = "docs/core_docs/DOWNLOAD_DATA_OBJECT_MAP_PATTERN.md"
_RELATED_CONTRACT_DOC = "docs/contracts_docs/DOWNLOAD_DATA_BOUNDARY.md"
_RELATED_TEST = "tests/core_test/test_download_data_boundary_object_map_pattern.py"

_T = TypeVar("_T")


def build_download_data_boundary_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Build the read-only provider descriptor for Download Data read models."""

    return ObjectMapProviderDescriptor(
        provider_id=DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID,
        provider_name="Download Data Boundary Trace",
        owner_domain="core",
        owner_component="DownloadDataBoundaryTrace",
        object_kinds=_DESCRIPTOR_OBJECT_KINDS,
        family_ids=_DESCRIPTOR_OBJECT_KINDS,
        relationship_types=("references", "has_permission"),
        supports_summary_listing=True,
        supports_interrogation=False,
        supports_relationship_listing=True,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=(
            "leonardo.contracts.download_data_boundary.DownloadDataBoundaryDescriptor",
            "leonardo.contracts.download_data_boundary.DownloadDataWorkflowDescriptor",
            "leonardo.contracts.download_data_boundary.DownloadDataSelectionDraft",
            "leonardo.contracts.download_data_boundary.DownloadDataSelectionSummary",
            "leonardo.contracts.download_data_boundary.DownloadDataPreflightSummary",
            "leonardo.contracts.download_data_boundary.DownloadDataProgressSummary",
            "leonardo.contracts.download_data_boundary.DownloadDataCompletionSummary",
            "leonardo.contracts.download_data_boundary.DownloadDataStorageTargetRef",
            "leonardo.contracts.download_data_boundary.DownloadDataOutputRef",
            "leonardo.contracts.download_data_boundary.DownloadDataPartialPersistenceSummary",
        ),
        related_docs=(_RELATED_CONTRACT_DOC, _RELATED_DOC),
        related_tests=(_RELATED_TEST,),
        metadata={
            "descriptor_source": "explicit_descriptor_inputs",
            "runtime_binding": "not_implemented",
            "storage_truth_owner": "storage_data_layer",
        },
        extra={"read_only": True, "mutation_forbidden": True},
    )


def download_data_boundary_trace_ref_from_descriptor(
    boundary: DownloadDataBoundaryDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data boundary descriptor."""

    _require_type(boundary, DownloadDataBoundaryDescriptor, "boundary")
    return TraceableObjectRef(
        object_id=boundary.boundary_id,
        object_kind=DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataBoundaryDescriptor",
        label=boundary.display_name,
        metadata={
            "family_id": DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND,
            "descriptor_type": "DownloadDataBoundaryDescriptor",
        },
    )


def download_data_workflow_trace_ref_from_descriptor(
    workflow: DownloadDataWorkflowDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data workflow descriptor."""

    _require_type(workflow, DownloadDataWorkflowDescriptor, "workflow")
    return TraceableObjectRef(
        object_id=workflow.workflow_id,
        object_kind=DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataWorkflowDescriptor",
        label=workflow.display_name,
        metadata={
            "family_id": DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND,
            "descriptor_type": "DownloadDataWorkflowDescriptor",
        },
    )


def download_data_selection_trace_ref_from_draft(
    draft: DownloadDataSelectionDraft,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data selection draft."""

    _require_type(draft, DownloadDataSelectionDraft, "draft")
    return TraceableObjectRef(
        object_id=_selection_draft_object_id(draft),
        object_kind=DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
        owner_domain="gui.selection",
        owner_component="DownloadDataSelectionDraft",
        label=_selection_label(
            draft.exchange_id,
            draft.market_type,
            draft.symbol,
            draft.selected_timeframes,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
            "descriptor_type": "DownloadDataSelectionDraft",
            "selection_kind": "draft",
            "workflow_id": _metadata_string(draft.metadata, "workflow_id"),
        },
    )


def download_data_preflight_trace_ref_from_summary(
    summary: DownloadDataPreflightSummary,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data preflight summary."""

    _require_type(summary, DownloadDataPreflightSummary, "summary")
    return TraceableObjectRef(
        object_id=_preflight_summary_object_id(summary),
        object_kind=DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataPreflightSummary",
        label=f"{summary.workflow_id} preflight",
        metadata={
            "family_id": DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND,
            "descriptor_type": "DownloadDataPreflightSummary",
            "workflow_id": summary.workflow_id,
        },
    )


def download_data_progress_trace_ref_from_summary(
    summary: DownloadDataProgressSummary,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data progress summary."""

    _require_type(summary, DownloadDataProgressSummary, "summary")
    return TraceableObjectRef(
        object_id=_progress_summary_object_id(summary),
        object_kind=DOWNLOAD_DATA_PROGRESS_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataProgressSummary",
        label=f"{summary.workflow_id} progress",
        metadata={
            "family_id": DOWNLOAD_DATA_PROGRESS_OBJECT_KIND,
            "descriptor_type": "DownloadDataProgressSummary",
            "workflow_id": summary.workflow_id,
            "operation_id": summary.operation_id,
            "task_id": summary.task_id,
        },
    )


def download_data_completion_trace_ref_from_summary(
    summary: DownloadDataCompletionSummary,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data completion summary."""

    _require_type(summary, DownloadDataCompletionSummary, "summary")
    return TraceableObjectRef(
        object_id=_completion_summary_object_id(summary),
        object_kind=DOWNLOAD_DATA_COMPLETION_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataCompletionSummary",
        label=f"{summary.workflow_id} completion",
        metadata={
            "family_id": DOWNLOAD_DATA_COMPLETION_OBJECT_KIND,
            "descriptor_type": "DownloadDataCompletionSummary",
            "workflow_id": summary.workflow_id,
        },
    )


def download_data_storage_target_trace_ref(
    storage_target: DownloadDataStorageTargetRef,
) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data storage target."""

    _require_type(storage_target, DownloadDataStorageTargetRef, "storage_target")
    return _storage_target_ref_from_identity(
        exchange_id=storage_target.exchange_id,
        market_type=storage_target.market_type,
        symbol=storage_target.symbol,
        timeframe=storage_target.timeframe,
        csv_path=storage_target.csv_path,
        metadata_path=storage_target.metadata_path,
        storage_root_ref=storage_target.storage_root_ref,
        path_policy_name=storage_target.path_policy_name,
        reference_only=False,
    )


def download_data_output_trace_ref(output_ref: DownloadDataOutputRef) -> TraceableObjectRef:
    """Build a traceable object reference for a Download Data output reference."""

    _require_type(output_ref, DownloadDataOutputRef, "output_ref")
    return TraceableObjectRef(
        object_id=_output_object_id(output_ref),
        object_kind=DOWNLOAD_DATA_OUTPUT_OBJECT_KIND,
        owner_domain="storage.data",
        owner_component="DownloadDataOutputRef",
        label=_storage_label(
            output_ref.exchange_id,
            output_ref.market_type,
            output_ref.symbol,
            output_ref.timeframe,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_OUTPUT_OBJECT_KIND,
            "descriptor_type": "DownloadDataOutputRef",
            "artifact_id": output_ref.artifact_id,
            "csv_path": output_ref.csv_path,
            "metadata_path": output_ref.metadata_path,
        },
    )


def download_data_partial_persistence_trace_ref(
    partial: DownloadDataPartialPersistenceSummary,
) -> TraceableObjectRef:
    """Build a traceable object reference for partial Download Data persistence."""

    _require_type(partial, DownloadDataPartialPersistenceSummary, "partial")
    return TraceableObjectRef(
        object_id=_partial_persistence_object_id(partial),
        object_kind=DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND,
        owner_domain="storage.data",
        owner_component="DownloadDataPartialPersistenceSummary",
        label=_storage_label(
            partial.exchange_id,
            partial.market_type,
            partial.symbol,
            partial.timeframe,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND,
            "descriptor_type": "DownloadDataPartialPersistenceSummary",
            "csv_path": partial.csv_path,
            "metadata_path": partial.metadata_path,
        },
    )


def download_data_boundary_trace_summary_from_descriptor(
    boundary: DownloadDataBoundaryDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data boundary."""

    ref = download_data_boundary_trace_ref_from_descriptor(boundary)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="declared",
        runtime_or_persistent="static_metadata",
        display_name=boundary.display_name,
        metadata={
            "family_id": DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND,
            "boundary_id": boundary.boundary_id,
            "workflow_ids": boundary.workflow_ids,
            "docs_refs": boundary.docs_refs,
            "test_refs": boundary.test_refs,
            "warnings": boundary.warnings,
            "blockers": boundary.blockers,
            "safe_metadata": boundary.metadata,
            "read_only": True,
        },
        source_refs=("DownloadDataBoundaryDescriptor",),
        extra={
            "descriptor_type": "DownloadDataBoundaryDescriptor",
            "mutation_forbidden": True,
        },
    )


def download_data_workflow_trace_summary_from_descriptor(
    workflow: DownloadDataWorkflowDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data workflow."""

    ref = download_data_workflow_trace_ref_from_descriptor(workflow)
    permission_refs = (
        (workflow.required_permission,)
        if workflow.required_permission is not None
        else ()
    )
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(workflow.status),
        runtime_or_persistent="static_metadata",
        display_name=workflow.display_name,
        metadata={
            "family_id": DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND,
            "workflow_id": workflow.workflow_id,
            "status": _value(workflow.status),
            "required_permission": workflow.required_permission,
            "provider_capability_refs": workflow.provider_capability_refs,
            "storage_policy_refs": workflow.storage_policy_refs,
            "docs_refs": workflow.docs_refs,
            "test_refs": workflow.test_refs,
            "warnings": workflow.warnings,
            "blockers": workflow.blockers,
            "safe_metadata": workflow.metadata,
            "read_only": True,
        },
        permission_refs=permission_refs,
        source_refs=("DownloadDataWorkflowDescriptor",),
        extra={
            "descriptor_type": "DownloadDataWorkflowDescriptor",
            "mutation_forbidden": True,
        },
    )


def download_data_selection_trace_summary_from_draft(
    draft: DownloadDataSelectionDraft,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data selection draft."""

    ref = download_data_selection_trace_ref_from_draft(draft)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="complete" if draft.selection_complete else "draft",
        runtime_or_persistent="intent_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
            "selection_kind": "draft",
            "exchange_id": draft.exchange_id,
            "market_type": draft.market_type,
            "symbol": draft.symbol,
            "selected_timeframes": draft.selected_timeframes,
            "selection_complete": draft.selection_complete,
            "workflow_id": _metadata_string(draft.metadata, "workflow_id"),
            "warnings": draft.warnings,
            "blockers": draft.blockers,
            "safe_metadata": draft.metadata,
            "read_only": True,
        },
        source_refs=("DownloadDataSelectionDraft",),
        extra={
            "descriptor_type": "DownloadDataSelectionDraft",
            "mutation_forbidden": True,
        },
    )


def download_data_preflight_trace_summary_from_summary(
    summary: DownloadDataPreflightSummary,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data preflight recap."""

    ref = download_data_preflight_trace_ref_from_summary(summary)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="blocked" if summary.blocked_items else "ready",
        runtime_or_persistent="runtime_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND,
            "workflow_id": summary.workflow_id,
            "exchange_id": summary.selection_summary.exchange_id,
            "market_type": summary.selection_summary.market_type,
            "symbol": summary.selection_summary.symbol,
            "selected_timeframes": summary.selection_summary.selected_timeframes,
            "total_items": summary.total_items,
            "ready_items": summary.ready_items,
            "blocked_items": summary.blocked_items,
            "new_file_items": summary.new_file_items,
            "update_items": summary.update_items,
            "already_current_items": summary.already_current_items,
            "blocked_mode_items": _count_preflight_mode(
                summary.items,
                DownloadDataPreflightMode.BLOCKED,
            ),
            "unknown_mode_items": _count_preflight_mode(
                summary.items,
                DownloadDataPreflightMode.UNKNOWN,
            ),
            "expected_total_bars": summary.expected_total_bars,
            "expected_total_steps": summary.expected_total_steps,
            "warnings": summary.warnings,
            "blockers": summary.blockers,
            "safe_metadata": summary.metadata,
            "read_only": True,
        },
        source_refs=("DownloadDataPreflightSummary",),
        extra={
            "descriptor_type": "DownloadDataPreflightSummary",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def download_data_progress_trace_summary_from_summary(
    summary: DownloadDataProgressSummary,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data progress recap."""

    ref = download_data_progress_trace_ref_from_summary(summary)
    operation_refs = (summary.operation_id,) if summary.operation_id is not None else ()
    task_refs = (summary.task_id,) if summary.task_id is not None else ()
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(summary.status),
        runtime_or_persistent="runtime_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_PROGRESS_OBJECT_KIND,
            "workflow_id": summary.workflow_id,
            "operation_id": summary.operation_id,
            "task_id": summary.task_id,
            "status": _value(summary.status),
            "total_items": summary.total_items,
            "completed_items": summary.completed_items,
            "failed_items": summary.failed_items,
            "cancelled_items": summary.cancelled_items,
            "total_steps": summary.total_steps,
            "completed_steps": summary.completed_steps,
            "message_count": len(summary.messages),
            "warnings": summary.warnings,
            "errors": summary.errors,
            "read_only": True,
        },
        operation_refs=operation_refs,
        task_refs=task_refs,
        source_refs=("DownloadDataProgressSummary",),
        extra={
            "descriptor_type": "DownloadDataProgressSummary",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def download_data_completion_trace_summary_from_summary(
    summary: DownloadDataCompletionSummary,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data completion recap."""

    ref = download_data_completion_trace_ref_from_summary(summary)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(summary.status),
        runtime_or_persistent="runtime_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_COMPLETION_OBJECT_KIND,
            "workflow_id": summary.workflow_id,
            "status": _value(summary.status),
            "total_items": summary.total_items,
            "completed_items": summary.completed_items,
            "partial_items": summary.partial_items,
            "failed_items": summary.failed_items,
            "cancelled_items": summary.cancelled_items,
            "output_ref_count": len(summary.output_refs),
            "warnings": summary.warnings,
            "errors": summary.errors,
            "safe_metadata": summary.metadata,
            "read_only": True,
        },
        source_refs=("DownloadDataCompletionSummary",),
        extra={
            "descriptor_type": "DownloadDataCompletionSummary",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def download_data_storage_target_trace_summary(
    storage_target: DownloadDataStorageTargetRef,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data storage target."""

    ref = download_data_storage_target_trace_ref(storage_target)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="declared",
        runtime_or_persistent="storage_reference",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND,
            "exchange_id": storage_target.exchange_id,
            "market_type": storage_target.market_type,
            "symbol": storage_target.symbol,
            "timeframe": storage_target.timeframe,
            "artifact_id": storage_target.artifact_id,
            "csv_path": storage_target.csv_path,
            "metadata_path": storage_target.metadata_path,
            "storage_root_ref": storage_target.storage_root_ref,
            "path_policy_name": storage_target.path_policy_name,
            "warnings": storage_target.warnings,
            "blockers": storage_target.blockers,
            "read_only": True,
        },
        source_refs=("DownloadDataStorageTargetRef",),
        extra={
            "descriptor_type": "DownloadDataStorageTargetRef",
            "mutation_forbidden": True,
            "write_authority": "not_granted",
        },
    )


def download_data_output_trace_summary(
    output_ref: DownloadDataOutputRef,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a Download Data output reference."""

    ref = download_data_output_trace_ref(output_ref)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(output_ref.persistence_status),
        runtime_or_persistent="storage_reference",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_OUTPUT_OBJECT_KIND,
            "exchange_id": output_ref.exchange_id,
            "market_type": output_ref.market_type,
            "symbol": output_ref.symbol,
            "timeframe": output_ref.timeframe,
            "artifact_id": output_ref.artifact_id,
            "csv_path": output_ref.csv_path,
            "metadata_path": output_ref.metadata_path,
            "bars_written": output_ref.bars_written,
            "first_timestamp_ms": output_ref.first_timestamp_ms,
            "last_timestamp_ms": output_ref.last_timestamp_ms,
            "first_timestamp_utc": output_ref.first_timestamp_utc,
            "last_timestamp_utc": output_ref.last_timestamp_utc,
            "persistence_status": _value(output_ref.persistence_status),
            "validation_status": _value(output_ref.validation_status),
            "loadable": output_ref.loadable,
            "accepted": output_ref.accepted,
            "warnings": output_ref.warnings,
            "errors": output_ref.errors,
            "read_only": True,
        },
        source_refs=("DownloadDataOutputRef",),
        extra={
            "descriptor_type": "DownloadDataOutputRef",
            "mutation_forbidden": True,
            "write_authority": "not_granted",
        },
    )


def download_data_partial_persistence_trace_summary(
    partial: DownloadDataPartialPersistenceSummary,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for partial Download Data persistence."""

    ref = download_data_partial_persistence_trace_ref(partial)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(partial.persistence_status),
        runtime_or_persistent="storage_reference",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND,
            "exchange_id": partial.exchange_id,
            "market_type": partial.market_type,
            "symbol": partial.symbol,
            "timeframe": partial.timeframe,
            "csv_path": partial.csv_path,
            "metadata_path": partial.metadata_path,
            "partial": partial.partial,
            "persistence_status": _value(partial.persistence_status),
            "bars_persisted": partial.bars_persisted,
            "first_timestamp_ms": partial.first_timestamp_ms,
            "last_timestamp_ms": partial.last_timestamp_ms,
            "first_timestamp_utc": partial.first_timestamp_utc,
            "last_timestamp_utc": partial.last_timestamp_utc,
            "resumable": partial.resumable,
            "maintenance_required": partial.maintenance_required,
            "accepted": False,
            "loadable": False,
            "validated": False,
            "warnings": partial.warnings,
            "errors": partial.errors,
            "read_only": True,
        },
        source_refs=("DownloadDataPartialPersistenceSummary",),
        extra={
            "descriptor_type": "DownloadDataPartialPersistenceSummary",
            "mutation_forbidden": True,
            "accepted": False,
            "loadable": False,
            "validated": False,
            "write_authority": "not_granted",
        },
    )


def download_data_boundary_relationships_from_descriptors(
    *,
    boundary_descriptors: Iterable[DownloadDataBoundaryDescriptor] = (),
    workflow_descriptors: Iterable[DownloadDataWorkflowDescriptor] = (),
    selection_drafts: Iterable[DownloadDataSelectionDraft] = (),
    selection_summaries: Iterable[DownloadDataSelectionSummary] = (),
    preflight_summaries: Iterable[DownloadDataPreflightSummary] = (),
    progress_summaries: Iterable[DownloadDataProgressSummary] = (),
    completion_summaries: Iterable[DownloadDataCompletionSummary] = (),
    storage_targets: Iterable[DownloadDataStorageTargetRef] = (),
    output_refs: Iterable[DownloadDataOutputRef] = (),
    partial_persistence_summaries: Iterable[
        DownloadDataPartialPersistenceSummary
    ] = (),
) -> tuple[TraceableRelationshipRef, ...]:
    """Build relationships from explicit Download Data boundary inputs."""

    normalized = _normalize_inputs(
        boundary_descriptors=boundary_descriptors,
        workflow_descriptors=workflow_descriptors,
        selection_drafts=selection_drafts,
        selection_summaries=selection_summaries,
        preflight_summaries=preflight_summaries,
        progress_summaries=progress_summaries,
        completion_summaries=completion_summaries,
        storage_targets=storage_targets,
        output_refs=output_refs,
        partial_persistence_summaries=partial_persistence_summaries,
    )
    relationships: list[TraceableRelationshipRef] = []

    for boundary in normalized.boundary_descriptors:
        boundary_ref = download_data_boundary_trace_ref_from_descriptor(boundary)
        for workflow_id in boundary.workflow_ids:
            workflow = normalized.workflow_by_id.get(workflow_id)
            if workflow is not None:
                _append_reference(
                    relationships,
                    boundary_ref,
                    download_data_workflow_trace_ref_from_descriptor(workflow),
                )

    for workflow in normalized.workflow_descriptors:
        workflow_ref = download_data_workflow_trace_ref_from_descriptor(workflow)
        for capability_ref in workflow.provider_capability_refs:
            _append_reference(
                relationships,
                workflow_ref,
                _provider_capability_ref(capability_ref),
            )
        for storage_policy_ref in workflow.storage_policy_refs:
            _append_reference(
                relationships,
                workflow_ref,
                _storage_policy_ref(storage_policy_ref),
            )
        if workflow.required_permission is not None:
            _append_permission_relationship(
                relationships,
                workflow_ref,
                workflow.required_permission,
            )

    for draft in normalized.selection_drafts:
        workflow_id = _metadata_string(draft.metadata, "workflow_id")
        if workflow_id is not None and workflow_id in normalized.workflow_by_id:
            _append_reference(
                relationships,
                download_data_selection_trace_ref_from_draft(draft),
                download_data_workflow_trace_ref_from_descriptor(
                    normalized.workflow_by_id[workflow_id],
                ),
            )

    for selection in normalized.selection_summaries:
        draft = normalized.selection_draft_by_identity.get(_selection_identity(selection))
        if draft is not None:
            _append_reference(
                relationships,
                _selection_trace_ref_from_summary(selection),
                download_data_selection_trace_ref_from_draft(draft),
            )

    for preflight in normalized.preflight_summaries:
        preflight_ref = download_data_preflight_trace_ref_from_summary(preflight)
        selection = normalized.selection_summary_by_identity.get(
            _selection_identity(preflight.selection_summary),
        )
        if selection is not None:
            _append_reference(
                relationships,
                preflight_ref,
                _selection_trace_ref_from_summary(selection),
            )
        for item in preflight.items:
            item_ref = _preflight_item_trace_ref(preflight.workflow_id, item)
            _append_reference(relationships, preflight_ref, item_ref)
            _append_reference(
                relationships,
                item_ref,
                download_data_storage_target_trace_ref(item.storage_target),
            )

    for progress in normalized.progress_summaries:
        progress_ref = download_data_progress_trace_ref_from_summary(progress)
        if progress.operation_id is not None:
            _append_reference(relationships, progress_ref, _operation_ref(progress.operation_id))
        if progress.task_id is not None:
            _append_reference(relationships, progress_ref, _task_ref(progress.task_id))
        for item in progress.items:
            _append_reference(
                relationships,
                progress_ref,
                _progress_item_trace_ref(progress, item),
            )

    for completion in normalized.completion_summaries:
        completion_ref = download_data_completion_trace_ref_from_summary(completion)
        for output_ref in completion.output_refs:
            output_trace_ref = download_data_output_trace_ref(output_ref)
            _append_reference(relationships, completion_ref, output_trace_ref)
            _append_output_storage_reference(relationships, output_trace_ref, output_ref)
        for item in completion.items:
            item_ref = _completion_item_trace_ref(completion.workflow_id, item)
            _append_reference(relationships, completion_ref, item_ref)
            _append_reference(
                relationships,
                item_ref,
                download_data_output_trace_ref(item.output_ref),
            )

    for output_ref in normalized.output_refs:
        output_trace_ref = download_data_output_trace_ref(output_ref)
        _append_output_storage_reference(relationships, output_trace_ref, output_ref)

    for partial in normalized.partial_persistence_summaries:
        partial_ref = download_data_partial_persistence_trace_ref(partial)
        output_ref = normalized.output_by_storage_identity.get(_storage_identity(partial))
        if output_ref is not None:
            _append_reference(
                relationships,
                partial_ref,
                download_data_output_trace_ref(output_ref),
            )
        else:
            _append_reference(
                relationships,
                partial_ref,
                _storage_target_ref_from_identity(
                    exchange_id=partial.exchange_id,
                    market_type=partial.market_type,
                    symbol=partial.symbol,
                    timeframe=partial.timeframe,
                    csv_path=partial.csv_path,
                    metadata_path=partial.metadata_path,
                    storage_root_ref=None,
                    path_policy_name=None,
                    reference_only=True,
                ),
            )

    return _dedupe_relationships(relationships)


def build_download_data_boundary_trace_section(
    *,
    boundary_descriptors: Iterable[DownloadDataBoundaryDescriptor] = (),
    workflow_descriptors: Iterable[DownloadDataWorkflowDescriptor] = (),
    selection_drafts: Iterable[DownloadDataSelectionDraft] = (),
    selection_summaries: Iterable[DownloadDataSelectionSummary] = (),
    preflight_summaries: Iterable[DownloadDataPreflightSummary] = (),
    progress_summaries: Iterable[DownloadDataProgressSummary] = (),
    completion_summaries: Iterable[DownloadDataCompletionSummary] = (),
    storage_targets: Iterable[DownloadDataStorageTargetRef] = (),
    output_refs: Iterable[DownloadDataOutputRef] = (),
    partial_persistence_summaries: Iterable[
        DownloadDataPartialPersistenceSummary
    ] = (),
) -> ObjectMapSection:
    """Build a read-only Object Map section from explicit Download Data inputs."""

    normalized = _normalize_inputs(
        boundary_descriptors=boundary_descriptors,
        workflow_descriptors=workflow_descriptors,
        selection_drafts=selection_drafts,
        selection_summaries=selection_summaries,
        preflight_summaries=preflight_summaries,
        progress_summaries=progress_summaries,
        completion_summaries=completion_summaries,
        storage_targets=storage_targets,
        output_refs=output_refs,
        partial_persistence_summaries=partial_persistence_summaries,
    )
    summaries = _all_summaries(normalized)
    relationships = download_data_boundary_relationships_from_descriptors(
        boundary_descriptors=normalized.boundary_descriptors,
        workflow_descriptors=normalized.workflow_descriptors,
        selection_drafts=normalized.selection_drafts,
        selection_summaries=normalized.selection_summaries,
        preflight_summaries=normalized.preflight_summaries,
        progress_summaries=normalized.progress_summaries,
        completion_summaries=normalized.completion_summaries,
        storage_targets=normalized.storage_targets,
        output_refs=normalized.output_refs,
        partial_persistence_summaries=normalized.partial_persistence_summaries,
    )
    definitions = (
        *object_relationship_definitions_by_type("references"),
        *object_relationship_definitions_by_type("has_permission"),
    )
    return ObjectMapSection(
        section_id=DOWNLOAD_DATA_BOUNDARY_TRACE_SECTION_ID,
        provider_id=DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID,
        owner_domain="core",
        title="Download Data Boundary Read Models",
        summaries=summaries,
        relationships=relationships,
        relationship_definitions=definitions,
        warnings=_summary_warnings(summaries),
        blockers=_summary_blockers(summaries),
        errors=_summary_errors(summaries),
        metadata={
            "boundary_count": len(normalized.boundary_descriptors),
            "workflow_count": len(normalized.workflow_descriptors),
            "selection_draft_count": len(normalized.selection_drafts),
            "selection_summary_count": len(normalized.selection_summaries),
            "preflight_summary_count": len(normalized.preflight_summaries),
            "progress_summary_count": len(normalized.progress_summaries),
            "completion_summary_count": len(normalized.completion_summaries),
            "storage_target_count": len(normalized.storage_targets),
            "output_ref_count": len(normalized.output_refs),
            "partial_persistence_count": len(
                normalized.partial_persistence_summaries,
            ),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
            "descriptor_source": "explicit_descriptor_inputs",
            "read_only": True,
        },
        extra={
            "mutation_forbidden": True,
            "interrogation": "future",
            "execution": "not_implemented",
            "runtime_summary": "not_implemented",
        },
    )


class _Inputs:
    def __init__(
        self,
        *,
        boundary_descriptors: tuple[DownloadDataBoundaryDescriptor, ...],
        workflow_descriptors: tuple[DownloadDataWorkflowDescriptor, ...],
        selection_drafts: tuple[DownloadDataSelectionDraft, ...],
        selection_summaries: tuple[DownloadDataSelectionSummary, ...],
        preflight_summaries: tuple[DownloadDataPreflightSummary, ...],
        progress_summaries: tuple[DownloadDataProgressSummary, ...],
        completion_summaries: tuple[DownloadDataCompletionSummary, ...],
        storage_targets: tuple[DownloadDataStorageTargetRef, ...],
        output_refs: tuple[DownloadDataOutputRef, ...],
        partial_persistence_summaries: tuple[
            DownloadDataPartialPersistenceSummary,
            ...,
        ],
    ) -> None:
        self.boundary_descriptors = boundary_descriptors
        self.workflow_descriptors = workflow_descriptors
        self.selection_drafts = selection_drafts
        self.selection_summaries = selection_summaries
        self.preflight_summaries = preflight_summaries
        self.progress_summaries = progress_summaries
        self.completion_summaries = completion_summaries
        self.storage_targets = storage_targets
        self.output_refs = output_refs
        self.partial_persistence_summaries = partial_persistence_summaries
        self.workflow_by_id = {
            workflow.workflow_id: workflow
            for workflow in workflow_descriptors
        }
        self.selection_draft_by_identity = {
            _selection_identity(draft): draft
            for draft in selection_drafts
            if _has_selection_identity(draft)
        }
        self.selection_summary_by_identity = {
            _selection_identity(summary): summary
            for summary in selection_summaries
        }
        self.storage_target_by_identity = {
            _storage_identity(target): target
            for target in storage_targets
        }
        self.output_by_storage_identity = {
            _storage_identity(output_ref): output_ref
            for output_ref in output_refs
        }


def _normalize_inputs(
    *,
    boundary_descriptors: Iterable[DownloadDataBoundaryDescriptor],
    workflow_descriptors: Iterable[DownloadDataWorkflowDescriptor],
    selection_drafts: Iterable[DownloadDataSelectionDraft],
    selection_summaries: Iterable[DownloadDataSelectionSummary],
    preflight_summaries: Iterable[DownloadDataPreflightSummary],
    progress_summaries: Iterable[DownloadDataProgressSummary],
    completion_summaries: Iterable[DownloadDataCompletionSummary],
    storage_targets: Iterable[DownloadDataStorageTargetRef],
    output_refs: Iterable[DownloadDataOutputRef],
    partial_persistence_summaries: Iterable[DownloadDataPartialPersistenceSummary],
) -> _Inputs:
    normalized_boundary_descriptors = _sort_by_object_id(
        _normalize_tuple(
            boundary_descriptors,
            DownloadDataBoundaryDescriptor,
            "boundary_descriptors",
        ),
        download_data_boundary_trace_ref_from_descriptor,
    )
    normalized_workflow_descriptors = _sort_by_object_id(
        _normalize_tuple(
            workflow_descriptors,
            DownloadDataWorkflowDescriptor,
            "workflow_descriptors",
        ),
        download_data_workflow_trace_ref_from_descriptor,
    )
    normalized_selection_drafts = _sort_by_object_id(
        _normalize_tuple(
            selection_drafts,
            DownloadDataSelectionDraft,
            "selection_drafts",
        ),
        download_data_selection_trace_ref_from_draft,
    )
    normalized_selection_summaries = _sort_by_object_id(
        _normalize_tuple(
            selection_summaries,
            DownloadDataSelectionSummary,
            "selection_summaries",
        ),
        _selection_trace_ref_from_summary,
    )
    normalized_preflight_summaries = _sort_by_object_id(
        _normalize_tuple(
            preflight_summaries,
            DownloadDataPreflightSummary,
            "preflight_summaries",
        ),
        download_data_preflight_trace_ref_from_summary,
    )
    normalized_progress_summaries = _sort_by_object_id(
        _normalize_tuple(
            progress_summaries,
            DownloadDataProgressSummary,
            "progress_summaries",
        ),
        download_data_progress_trace_ref_from_summary,
    )
    normalized_completion_summaries = _sort_by_object_id(
        _normalize_tuple(
            completion_summaries,
            DownloadDataCompletionSummary,
            "completion_summaries",
        ),
        download_data_completion_trace_ref_from_summary,
    )
    normalized_storage_targets = _sort_by_object_id(
        _normalize_tuple(
            storage_targets,
            DownloadDataStorageTargetRef,
            "storage_targets",
        ),
        download_data_storage_target_trace_ref,
    )
    normalized_output_refs = _sort_by_object_id(
        _normalize_tuple(output_refs, DownloadDataOutputRef, "output_refs"),
        download_data_output_trace_ref,
    )
    normalized_partial_persistence_summaries = _sort_by_object_id(
        _normalize_tuple(
            partial_persistence_summaries,
            DownloadDataPartialPersistenceSummary,
            "partial_persistence_summaries",
        ),
        download_data_partial_persistence_trace_ref,
    )
    return _Inputs(
        boundary_descriptors=normalized_boundary_descriptors,
        workflow_descriptors=normalized_workflow_descriptors,
        selection_drafts=normalized_selection_drafts,
        selection_summaries=normalized_selection_summaries,
        preflight_summaries=normalized_preflight_summaries,
        progress_summaries=normalized_progress_summaries,
        completion_summaries=normalized_completion_summaries,
        storage_targets=normalized_storage_targets,
        output_refs=normalized_output_refs,
        partial_persistence_summaries=normalized_partial_persistence_summaries,
    )


def _normalize_tuple(
    values: Iterable[object],
    expected_type: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an iterable of {expected_type.__name__}")
    normalized = tuple(values)
    for value in normalized:
        _require_type(value, expected_type, f"{field_name} entry")
    return normalized


def _sort_by_object_id(
    values: tuple[_T, ...],
    ref_builder: object,
) -> tuple[_T, ...]:
    return tuple(
        sorted(
            values,
            key=lambda value: ref_builder(value).object_id,  # type: ignore[operator]
        )
    )


def _require_type(value: object, expected_type: type[object], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be a {expected_type.__name__}")


def _selection_trace_ref_from_summary(
    summary: DownloadDataSelectionSummary,
) -> TraceableObjectRef:
    _require_type(summary, DownloadDataSelectionSummary, "summary")
    return TraceableObjectRef(
        object_id=_selection_summary_object_id(summary),
        object_kind=DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
        owner_domain="gui.selection",
        owner_component="DownloadDataSelectionSummary",
        label=_selection_label(
            summary.exchange_id,
            summary.market_type,
            summary.symbol,
            summary.selected_timeframes,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
            "descriptor_type": "DownloadDataSelectionSummary",
            "selection_kind": "summary",
        },
    )


def _selection_trace_summary_from_summary(
    summary: DownloadDataSelectionSummary,
) -> TraceableObjectSummary:
    ref = _selection_trace_ref_from_summary(summary)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="selected",
        runtime_or_persistent="intent_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
            "selection_kind": "summary",
            "exchange_id": summary.exchange_id,
            "market_type": summary.market_type,
            "symbol": summary.symbol,
            "selected_timeframes": summary.selected_timeframes,
            "item_count": summary.item_count,
            "warnings": summary.warnings,
            "blockers": summary.blockers,
            "read_only": True,
        },
        source_refs=("DownloadDataSelectionSummary",),
        extra={
            "descriptor_type": "DownloadDataSelectionSummary",
            "mutation_forbidden": True,
        },
    )


def _preflight_item_trace_ref(
    workflow_id: str,
    item: DownloadDataPreflightItem,
) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=_preflight_item_object_id(workflow_id, item),
        object_kind=DOWNLOAD_DATA_PREFLIGHT_ITEM_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataPreflightItem",
        label=_storage_label(
            item.exchange_id,
            item.market_type,
            item.symbol,
            item.timeframe,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_PREFLIGHT_ITEM_OBJECT_KIND,
            "workflow_id": workflow_id,
            "descriptor_type": "DownloadDataPreflightItem",
        },
    )


def _preflight_item_trace_summary(
    workflow_id: str,
    item: DownloadDataPreflightItem,
) -> TraceableObjectSummary:
    ref = _preflight_item_trace_ref(workflow_id, item)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(item.status),
        runtime_or_persistent="runtime_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_PREFLIGHT_ITEM_OBJECT_KIND,
            "workflow_id": workflow_id,
            "exchange_id": item.exchange_id,
            "market_type": item.market_type,
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "mode": _value(item.mode),
            "status": _value(item.status),
            "local_dataset_exists": item.local_dataset_state.exists,
            "local_dataset_row_count": item.local_dataset_state.row_count,
            "local_persistence_status": _value(
                item.local_dataset_state.persistence_status,
            ),
            "local_validation_status": _value(
                item.local_dataset_state.validation_status,
            ),
            "local_loadable": item.local_dataset_state.loadable,
            "local_accepted": item.local_dataset_state.accepted,
            "exchange_first_available_timestamp_ms": (
                item.exchange_range_summary.first_available_timestamp_ms
            ),
            "exchange_last_available_timestamp_ms": (
                item.exchange_range_summary.last_available_timestamp_ms
            ),
            "exchange_page_limit": item.exchange_range_summary.page_limit,
            "exchange_source": item.exchange_range_summary.source,
            "expected_bars": item.workload_estimate.expected_bars,
            "expected_steps": item.workload_estimate.expected_steps,
            "bars_per_step": item.workload_estimate.bars_per_step,
            "storage_target_id": download_data_storage_target_trace_ref(
                item.storage_target,
            ).object_id,
            "warnings": item.warnings,
            "blockers": item.blockers,
            "read_only": True,
        },
        source_refs=("DownloadDataPreflightItem",),
        extra={
            "descriptor_type": "DownloadDataPreflightItem",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def _progress_item_trace_ref(
    progress: DownloadDataProgressSummary,
    item: DownloadDataProgressItem,
) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=_progress_item_object_id(progress, item),
        object_kind=DOWNLOAD_DATA_PROGRESS_ITEM_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataProgressItem",
        label=_storage_label(
            item.exchange_id,
            item.market_type,
            item.symbol,
            item.timeframe,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_PROGRESS_ITEM_OBJECT_KIND,
            "workflow_id": progress.workflow_id,
            "descriptor_type": "DownloadDataProgressItem",
        },
    )


def _progress_item_trace_summary(
    progress: DownloadDataProgressSummary,
    item: DownloadDataProgressItem,
) -> TraceableObjectSummary:
    ref = _progress_item_trace_ref(progress, item)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(item.status),
        runtime_or_persistent="runtime_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_PROGRESS_ITEM_OBJECT_KIND,
            "workflow_id": progress.workflow_id,
            "exchange_id": item.exchange_id,
            "market_type": item.market_type,
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "status": _value(item.status),
            "mode": _value(item.mode),
            "completed_steps": item.completed_steps,
            "total_steps": item.total_steps,
            "downloaded_bars": item.downloaded_bars,
            "first_timestamp_ms": item.first_timestamp_ms,
            "last_timestamp_ms": item.last_timestamp_ms,
            "first_timestamp_utc": item.first_timestamp_utc,
            "last_timestamp_utc": item.last_timestamp_utc,
            "warnings": item.warnings,
            "errors": item.errors,
            "read_only": True,
        },
        source_refs=("DownloadDataProgressItem",),
        extra={
            "descriptor_type": "DownloadDataProgressItem",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def _completion_item_trace_ref(
    workflow_id: str,
    item: DownloadDataCompletionItem,
) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=_completion_item_object_id(workflow_id, item),
        object_kind=DOWNLOAD_DATA_COMPLETION_ITEM_OBJECT_KIND,
        owner_domain="download_data",
        owner_component="DownloadDataCompletionItem",
        label=_storage_label(
            item.exchange_id,
            item.market_type,
            item.symbol,
            item.timeframe,
        ),
        metadata={
            "family_id": DOWNLOAD_DATA_COMPLETION_ITEM_OBJECT_KIND,
            "workflow_id": workflow_id,
            "descriptor_type": "DownloadDataCompletionItem",
        },
    )


def _completion_item_trace_summary(
    workflow_id: str,
    item: DownloadDataCompletionItem,
) -> TraceableObjectSummary:
    ref = _completion_item_trace_ref(workflow_id, item)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(item.status),
        runtime_or_persistent="runtime_read_model",
        display_name=ref.label,
        metadata={
            "family_id": DOWNLOAD_DATA_COMPLETION_ITEM_OBJECT_KIND,
            "workflow_id": workflow_id,
            "exchange_id": item.exchange_id,
            "market_type": item.market_type,
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "mode": _value(item.mode),
            "status": _value(item.status),
            "output_ref_id": download_data_output_trace_ref(item.output_ref).object_id,
            "bars_downloaded": item.bars_downloaded,
            "first_timestamp_ms": item.first_timestamp_ms,
            "last_timestamp_ms": item.last_timestamp_ms,
            "first_timestamp_utc": item.first_timestamp_utc,
            "last_timestamp_utc": item.last_timestamp_utc,
            "warnings": item.warnings,
            "errors": item.errors,
            "read_only": True,
        },
        source_refs=("DownloadDataCompletionItem",),
        extra={
            "descriptor_type": "DownloadDataCompletionItem",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def _all_summaries(normalized: _Inputs) -> tuple[TraceableObjectSummary, ...]:
    summaries = (
        *(
            download_data_boundary_trace_summary_from_descriptor(boundary)
            for boundary in normalized.boundary_descriptors
        ),
        *(
            download_data_workflow_trace_summary_from_descriptor(workflow)
            for workflow in normalized.workflow_descriptors
        ),
        *(
            download_data_selection_trace_summary_from_draft(draft)
            for draft in normalized.selection_drafts
        ),
        *(
            _selection_trace_summary_from_summary(summary)
            for summary in normalized.selection_summaries
        ),
        *(
            download_data_preflight_trace_summary_from_summary(summary)
            for summary in normalized.preflight_summaries
        ),
        *(
            _preflight_item_trace_summary(summary.workflow_id, item)
            for summary in normalized.preflight_summaries
            for item in summary.items
        ),
        *(
            download_data_progress_trace_summary_from_summary(summary)
            for summary in normalized.progress_summaries
        ),
        *(
            _progress_item_trace_summary(summary, item)
            for summary in normalized.progress_summaries
            for item in summary.items
        ),
        *(
            download_data_completion_trace_summary_from_summary(summary)
            for summary in normalized.completion_summaries
        ),
        *(
            _completion_item_trace_summary(summary.workflow_id, item)
            for summary in normalized.completion_summaries
            for item in summary.items
        ),
        *(
            download_data_storage_target_trace_summary(target)
            for target in normalized.storage_targets
        ),
        *(
            download_data_output_trace_summary(output_ref)
            for output_ref in _all_output_refs(normalized)
        ),
        *(
            download_data_partial_persistence_trace_summary(partial)
            for partial in normalized.partial_persistence_summaries
        ),
    )
    return _dedupe_summaries(summaries)


def _all_output_refs(normalized: _Inputs) -> tuple[DownloadDataOutputRef, ...]:
    output_refs = (
        *normalized.output_refs,
        *(
            output_ref
            for completion in normalized.completion_summaries
            for output_ref in completion.output_refs
        ),
        *(
            item.output_ref
            for completion in normalized.completion_summaries
            for item in completion.items
        ),
    )
    deduped: dict[str, DownloadDataOutputRef] = {}
    for output_ref in output_refs:
        deduped.setdefault(download_data_output_trace_ref(output_ref).object_id, output_ref)
    return tuple(deduped[key] for key in sorted(deduped))


def _append_permission_relationship(
    relationships: list[TraceableRelationshipRef],
    source_ref: TraceableObjectRef,
    permission: str,
) -> None:
    relationships.append(
        _relationship(
            "has_permission",
            source_ref,
            TraceableObjectRef(
                object_id=permission,
                object_kind=PERMISSION_OBJECT_KIND,
                owner_domain="core.policy",
                owner_component="UserPolicy",
                label=permission,
                metadata={"permission_ref": permission},
            ),
            metadata={"permission_ref": permission},
        )
    )


def _append_output_storage_reference(
    relationships: list[TraceableRelationshipRef],
    output_trace_ref: TraceableObjectRef,
    output_ref: DownloadDataOutputRef,
) -> None:
    _append_reference(
        relationships,
        output_trace_ref,
        _storage_target_ref_from_identity(
            exchange_id=output_ref.exchange_id,
            market_type=output_ref.market_type,
            symbol=output_ref.symbol,
            timeframe=output_ref.timeframe,
            csv_path=output_ref.csv_path,
            metadata_path=output_ref.metadata_path,
            storage_root_ref=None,
            path_policy_name=None,
            reference_only=True,
        ),
    )


def _append_reference(
    relationships: list[TraceableRelationshipRef],
    source_ref: TraceableObjectRef,
    target_ref: TraceableObjectRef,
) -> None:
    relationships.append(_relationship("references", source_ref, target_ref))


def _relationship(
    relationship_type: str,
    source_ref: TraceableObjectRef,
    target_ref: TraceableObjectRef,
    *,
    metadata: Mapping[str, object] | None = None,
) -> TraceableRelationshipRef:
    return TraceableRelationshipRef(
        relationship_id=(
            f"{source_ref.object_kind}:{source_ref.object_id}."
            f"{relationship_type}."
            f"{target_ref.object_kind}:{target_ref.object_id}"
        ),
        relationship_type=relationship_type,
        source_ref=source_ref,
        target_ref=target_ref,
        direction="outbound",
        lifecycle_status="declared",
        metadata=metadata or {},
    )


def _dedupe_relationships(
    relationships: list[TraceableRelationshipRef],
) -> tuple[TraceableRelationshipRef, ...]:
    deduped: dict[str, TraceableRelationshipRef] = {}
    for relationship in relationships:
        key = relationship.relationship_id
        if key is None:
            key = (
                f"{relationship.source_ref.object_kind}:{relationship.source_ref.object_id}."
                f"{relationship.relationship_type}."
                f"{relationship.target_ref.object_kind}:{relationship.target_ref.object_id}"
            )
        deduped.setdefault(key, relationship)
    return tuple(deduped[key] for key in sorted(deduped))


def _dedupe_summaries(
    summaries: tuple[TraceableObjectSummary, ...],
) -> tuple[TraceableObjectSummary, ...]:
    deduped: dict[str, TraceableObjectSummary] = {}
    for summary in summaries:
        key = f"{summary.object_ref.object_kind}:{summary.object_ref.object_id}"
        deduped.setdefault(key, summary)
    return tuple(deduped[key] for key in sorted(deduped))


def _summary_warnings(
    summaries: tuple[TraceableObjectSummary, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{summary.object_ref.object_kind} {summary.object_ref.object_id}: {warning}"
        for summary in summaries
        for warning in _string_tuple(summary.metadata.get("warnings"))
    )


def _summary_blockers(
    summaries: tuple[TraceableObjectSummary, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{summary.object_ref.object_kind} {summary.object_ref.object_id}: {blocker}"
        for summary in summaries
        for blocker in _string_tuple(summary.metadata.get("blockers"))
    )


def _summary_errors(
    summaries: tuple[TraceableObjectSummary, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{summary.object_ref.object_kind} {summary.object_ref.object_id}: {error}"
        for summary in summaries
        for error in _string_tuple(summary.metadata.get("errors"))
    )


def _provider_capability_ref(capability_ref: str) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=capability_ref,
        object_kind=PROVIDER_CAPABILITY_OBJECT_KIND,
        owner_domain="provider.boundary",
        owner_component="ProviderCapabilityDescriptor",
        label=capability_ref,
        metadata={"ownership": "reference_only"},
    )


def _storage_policy_ref(storage_policy_ref: str) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=storage_policy_ref,
        object_kind=STORAGE_POLICY_OBJECT_KIND,
        owner_domain="storage.data",
        owner_component="StoragePolicy",
        label=storage_policy_ref,
        metadata={"ownership": "reference_only"},
    )


def _operation_ref(operation_id: str) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=operation_id,
        object_kind=OPERATION_OBJECT_KIND,
        owner_domain="core.operation",
        owner_component="operation_tracking",
        label=operation_id,
        metadata={"ownership": "reference_only"},
    )


def _task_ref(task_id: str) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=task_id,
        object_kind=TASK_OBJECT_KIND,
        owner_domain="core.task",
        owner_component="task_tracking",
        label=task_id,
        metadata={"ownership": "reference_only"},
    )


def _storage_target_ref_from_identity(
    *,
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
    csv_path: str | None,
    metadata_path: str | None,
    storage_root_ref: str | None,
    path_policy_name: str | None,
    reference_only: bool,
) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=_storage_object_id(
            DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND,
            exchange_id,
            market_type,
            symbol,
            timeframe,
            DOWNLOAD_DATA_ARTIFACT_ID,
        ),
        object_kind=DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND,
        owner_domain="storage.data",
        owner_component="DownloadDataStorageTargetRef",
        label=_storage_label(exchange_id, market_type, symbol, timeframe),
        metadata={
            "family_id": DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND,
            "artifact_id": DOWNLOAD_DATA_ARTIFACT_ID,
            "csv_path": csv_path,
            "metadata_path": metadata_path,
            "storage_root_ref": storage_root_ref,
            "path_policy_name": path_policy_name,
            "ownership": "reference_only" if reference_only else "explicit_input",
        },
    )


def _selection_draft_object_id(draft: DownloadDataSelectionDraft) -> str:
    return (
        "download_data_selection:draft:"
        f"{_id_part(draft.exchange_id)}:"
        f"{_id_part(draft.market_type)}:"
        f"{_id_part(draft.symbol)}:"
        f"{_timeframe_id_part(draft.selected_timeframes)}"
    )


def _selection_summary_object_id(summary: DownloadDataSelectionSummary) -> str:
    return (
        "download_data_selection:summary:"
        f"{summary.exchange_id}:"
        f"{summary.market_type}:"
        f"{summary.symbol}:"
        f"{_timeframe_id_part(summary.selected_timeframes)}"
    )


def _preflight_summary_object_id(summary: DownloadDataPreflightSummary) -> str:
    return (
        f"download_data_preflight:{summary.workflow_id}:"
        f"{_selection_identity_text(summary.selection_summary)}"
    )


def _preflight_item_object_id(
    workflow_id: str,
    item: DownloadDataPreflightItem,
) -> str:
    return (
        f"download_data_preflight_item:{workflow_id}:"
        f"{item.exchange_id}:{item.market_type}:{item.symbol}:{item.timeframe}"
    )


def _progress_summary_object_id(summary: DownloadDataProgressSummary) -> str:
    owner_id = summary.operation_id or summary.task_id or summary.workflow_id
    return f"download_data_progress:{owner_id}"


def _progress_item_object_id(
    progress: DownloadDataProgressSummary,
    item: DownloadDataProgressItem,
) -> str:
    return (
        f"download_data_progress_item:{_progress_summary_object_id(progress)}:"
        f"{item.exchange_id}:{item.market_type}:{item.symbol}:{item.timeframe}"
    )


def _completion_summary_object_id(summary: DownloadDataCompletionSummary) -> str:
    output_id_part = ".".join(
        sorted(output_ref.timeframe for output_ref in summary.output_refs),
    )
    if not output_id_part:
        output_id_part = "none"
    return f"download_data_completion:{summary.workflow_id}:{_value(summary.status)}:{output_id_part}"


def _completion_item_object_id(
    workflow_id: str,
    item: DownloadDataCompletionItem,
) -> str:
    return (
        f"download_data_completion_item:{workflow_id}:"
        f"{item.exchange_id}:{item.market_type}:{item.symbol}:{item.timeframe}"
    )


def _output_object_id(output_ref: DownloadDataOutputRef) -> str:
    return _storage_object_id(
        DOWNLOAD_DATA_OUTPUT_OBJECT_KIND,
        output_ref.exchange_id,
        output_ref.market_type,
        output_ref.symbol,
        output_ref.timeframe,
        output_ref.artifact_id,
    )


def _partial_persistence_object_id(
    partial: DownloadDataPartialPersistenceSummary,
) -> str:
    return (
        f"download_data_partial_persistence:"
        f"{partial.exchange_id}:{partial.market_type}:{partial.symbol}:{partial.timeframe}"
    )


def _storage_object_id(
    object_kind: str,
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
    artifact_id: str,
) -> str:
    return f"{object_kind}:{exchange_id}:{market_type}:{symbol}:{timeframe}:{artifact_id}"


def _storage_label(
    exchange_id: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> str:
    return f"{exchange_id} {market_type} {symbol} {timeframe}"


def _selection_label(
    exchange_id: str | None,
    market_type: str | None,
    symbol: str | None,
    timeframes: tuple[str, ...],
) -> str:
    return (
        f"{_id_part(exchange_id)} {_id_part(market_type)} "
        f"{_id_part(symbol)} {_timeframe_id_part(timeframes)}"
    )


def _selection_identity(
    value: DownloadDataSelectionDraft | DownloadDataSelectionSummary,
) -> tuple[str, str, str, tuple[str, ...]]:
    return (
        str(value.exchange_id),
        str(value.market_type),
        str(value.symbol),
        tuple(value.selected_timeframes),
    )


def _selection_identity_text(summary: DownloadDataSelectionSummary) -> str:
    return (
        f"{summary.exchange_id}:{summary.market_type}:{summary.symbol}:"
        f"{_timeframe_id_part(summary.selected_timeframes)}"
    )


def _has_selection_identity(value: DownloadDataSelectionDraft) -> bool:
    return (
        value.exchange_id is not None
        and value.market_type is not None
        and value.symbol is not None
        and bool(value.selected_timeframes)
    )


def _storage_identity(
    value: (
        DownloadDataStorageTargetRef
        | DownloadDataOutputRef
        | DownloadDataPartialPersistenceSummary
    ),
) -> tuple[str, str, str, str]:
    return (value.exchange_id, value.market_type, value.symbol, value.timeframe)


def _count_preflight_mode(
    items: tuple[DownloadDataPreflightItem, ...],
    mode: DownloadDataPreflightMode,
) -> int:
    return sum(1 for item in items if item.mode is mode)


def _metadata_string(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _id_part(value: str | None) -> str:
    if value is None:
        return "none"
    return value


def _timeframe_id_part(timeframes: tuple[str, ...]) -> str:
    if not timeframes:
        return "none"
    return ".".join(timeframes)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


__all__ = [
    "DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND",
    "DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID",
    "DOWNLOAD_DATA_BOUNDARY_TRACE_SECTION_ID",
    "DOWNLOAD_DATA_COMPLETION_ITEM_OBJECT_KIND",
    "DOWNLOAD_DATA_COMPLETION_OBJECT_KIND",
    "DOWNLOAD_DATA_OUTPUT_OBJECT_KIND",
    "DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND",
    "DOWNLOAD_DATA_PREFLIGHT_ITEM_OBJECT_KIND",
    "DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND",
    "DOWNLOAD_DATA_PROGRESS_ITEM_OBJECT_KIND",
    "DOWNLOAD_DATA_PROGRESS_OBJECT_KIND",
    "DOWNLOAD_DATA_SELECTION_OBJECT_KIND",
    "DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND",
    "DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND",
    "OBJECT_FAMILY_OBJECT_KIND",
    "OPERATION_OBJECT_KIND",
    "PERMISSION_OBJECT_KIND",
    "PROVIDER_CAPABILITY_OBJECT_KIND",
    "STORAGE_POLICY_OBJECT_KIND",
    "TASK_OBJECT_KIND",
    "build_download_data_boundary_trace_provider_descriptor",
    "build_download_data_boundary_trace_section",
    "download_data_boundary_relationships_from_descriptors",
    "download_data_boundary_trace_ref_from_descriptor",
    "download_data_boundary_trace_summary_from_descriptor",
    "download_data_completion_trace_ref_from_summary",
    "download_data_completion_trace_summary_from_summary",
    "download_data_output_trace_ref",
    "download_data_output_trace_summary",
    "download_data_partial_persistence_trace_ref",
    "download_data_partial_persistence_trace_summary",
    "download_data_preflight_trace_ref_from_summary",
    "download_data_preflight_trace_summary_from_summary",
    "download_data_progress_trace_ref_from_summary",
    "download_data_progress_trace_summary_from_summary",
    "download_data_selection_trace_ref_from_draft",
    "download_data_selection_trace_summary_from_draft",
    "download_data_storage_target_trace_ref",
    "download_data_storage_target_trace_summary",
    "download_data_workflow_trace_ref_from_descriptor",
    "download_data_workflow_trace_summary_from_descriptor",
]
