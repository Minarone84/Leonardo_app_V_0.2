"""Read-only trace helpers for GUI action metadata.

The helpers in this module expose static GUI action metadata through the shared
traceability and Object Map report contracts. They read metadata documents and
static action definition records only. They do not instantiate Qt widgets, open
windows, execute actions, dispatch callbacks, submit Core commands, register
providers, wire Runtime Manager, mutate metadata, or own runtime action state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from leonardo.contracts.gui import ActionDefinition
from leonardo.contracts.object_family_legends import object_family_legend_by_id
from leonardo.contracts.object_map import ObjectMapProviderDescriptor, ObjectMapSection
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.traceable_object import (
    ObjectInterrogationReport,
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
from leonardo.gui.action_observer import TRACKED_GUI_ACTION_DEFINITIONS
from leonardo.gui.metadata.loader import load_metadata_document
from leonardo.gui.metadata.models import (
    GuiMetadataDocument,
    GuiMetadataIssueSeverity,
    GuiMetadataKind,
)
from leonardo.gui.metadata.window_trace import default_window_metadata_paths


ACTION_TRACE_PROVIDER_ID = "gui.action.trace"
ACTION_TRACE_SECTION_ID = "gui.actions"
ACTION_TRACE_OWNER_DOMAIN = "gui"
ACTION_TRACE_OWNER_COMPONENT = "GUI metadata action trace helper"
ACTION_TRACE_RUNTIME_KIND = "static_metadata"
ACTION_TRACE_DOC = "docs/contracts_docs/ACTION_FAMILY_TRACE.md"
ACTION_TRACE_TEST = "tests/gui_test/test_action_family_trace.py"

_TRACE_CONTRACTS = (
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
    "docs/contracts_docs/WINDOW_FAMILY_TRACE.md",
    ACTION_TRACE_DOC,
)


@dataclass(frozen=True)
class _ActionTraceSource:
    action_id: str
    label: str
    window_id: str | None = None
    metadata_id: str | None = None
    metadata_ref: str | None = None
    action_kind: str | None = None
    required_permissions: tuple[str, ...] = ()
    is_placeholder: bool | None = None
    sources: tuple[str, ...] = ()


def default_action_metadata_paths() -> tuple[Path, ...]:
    """Return the static window metadata files that declare GUI actions."""

    return default_window_metadata_paths()


def build_action_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Return the static read-only Object Map provider descriptor for actions."""

    return ObjectMapProviderDescriptor(
        provider_id=ACTION_TRACE_PROVIDER_ID,
        provider_name="GUI Action Trace",
        owner_domain=ACTION_TRACE_OWNER_DOMAIN,
        owner_component=ACTION_TRACE_OWNER_COMPONENT,
        object_kinds=("action",),
        family_ids=("action",),
        relationship_types=("contains_action", "has_permission", "triggers"),
        supports_summary_listing=True,
        supports_interrogation=True,
        supports_relationship_listing=True,
        runtime_or_persistent=ACTION_TRACE_RUNTIME_KIND,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=_TRACE_CONTRACTS,
        related_docs=_TRACE_DOCS,
        related_tests=(ACTION_TRACE_TEST,),
        metadata={
            "metadata_source": "src/leonardo/gui/metadata/windows",
            "definition_source": "leonardo.gui.action_observer.TRACKED_GUI_ACTION_DEFINITIONS",
        },
        extra={
            "forbidden_behavior": (
                "qt_widget_construction",
                "window_opening",
                "action_execution",
                "callback_dispatch",
                "core_command_submission",
                "metadata_mutation",
                "runtime_action_state_ownership",
            )
        },
    )


def action_trace_summaries_from_document(
    document: GuiMetadataDocument,
    *,
    metadata_path: str | Path | None = None,
    definitions: Sequence[ActionDefinition] = TRACKED_GUI_ACTION_DEFINITIONS,
) -> tuple[TraceableObjectSummary, ...]:
    """Build action summaries for actions declared by one window metadata document."""

    _validate_window_document(document)
    definitions_by_id = _definitions_by_id(definitions)
    metadata_ref = _metadata_ref_for(document, metadata_path)
    return tuple(
        _summary_from_source(
            _source_from_metadata_action(
                document=document,
                action_id=action.action_id,
                label=action.label,
                metadata_ref=metadata_ref,
                definition=definitions_by_id.get(action.action_id),
            )
        )
        for action in document.actions
    )


def build_action_trace_section(
    *,
    metadata_paths: Iterable[str | Path] | None = None,
    definitions: Sequence[ActionDefinition] = TRACKED_GUI_ACTION_DEFINITIONS,
) -> ObjectMapSection:
    """Build a read-only Object Map section for static GUI actions."""

    sources, warnings, errors = _collect_action_sources(
        metadata_paths=metadata_paths,
        definitions=definitions,
    )
    summaries = tuple(_summary_from_source(source) for source in sources)
    relationships = tuple(
        relationship
        for summary in summaries
        for relationship in summary.relationship_refs
    )

    legend = object_family_legend_by_id("action")
    legends = (legend,) if legend is not None else ()
    if legend is None:
        warnings = (*warnings, "Missing object family legend for action")

    paths = tuple(Path(path) for path in (metadata_paths or default_action_metadata_paths()))
    return ObjectMapSection(
        section_id=ACTION_TRACE_SECTION_ID,
        provider_id=ACTION_TRACE_PROVIDER_ID,
        owner_domain=ACTION_TRACE_OWNER_DOMAIN,
        object_kind="action",
        family_id="action",
        title="GUI Actions",
        summaries=summaries,
        relationships=relationships,
        legends=legends,
        relationship_definitions=_action_relationship_definitions(),
        warnings=warnings,
        errors=errors,
        metadata={
            "metadata_paths": tuple(_path_text(path) for path in paths),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
            "definition_count": len(definitions),
        },
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "static_gui_metadata_and_action_definitions",
        },
    )


def interrogate_action_trace(
    action_id: str,
    *,
    metadata_paths: Iterable[str | Path] | None = None,
    definitions: Sequence[ActionDefinition] = TRACKED_GUI_ACTION_DEFINITIONS,
) -> ObjectInterrogationReport:
    """Return a read-only interrogation report for one static GUI action."""

    _validate_non_empty_string(action_id, "action_id")
    section = build_action_trace_section(
        metadata_paths=metadata_paths,
        definitions=definitions,
    )
    summary = _find_summary(section.summaries, action_id)
    target_ref = (
        summary.object_ref
        if summary is not None
        else TraceableObjectRef(
            object_id=action_id,
            object_kind="action",
            owner_domain=ACTION_TRACE_OWNER_DOMAIN,
            owner_component=ACTION_TRACE_OWNER_COMPONENT,
        )
    )
    family_legend = section.legends[0] if section.legends else None
    blockers = () if summary is not None else (f"Action metadata not found: {action_id}",)

    return ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=family_legend,
        relationships=summary.relationship_refs if summary is not None else (),
        permissions=summary.permission_refs if summary is not None else (),
        docs=_TRACE_DOCS,
        tests=(ACTION_TRACE_TEST,),
        warnings=section.warnings,
        blockers=(*blockers, *section.blockers),
        errors=section.errors,
        metadata={
            "provider_id": ACTION_TRACE_PROVIDER_ID,
            "section_id": ACTION_TRACE_SECTION_ID,
            "action_id": action_id,
            "read_only": True,
        },
    )


def _collect_action_sources(
    *,
    metadata_paths: Iterable[str | Path] | None,
    definitions: Sequence[ActionDefinition],
) -> tuple[tuple[_ActionTraceSource, ...], tuple[str, ...], tuple[str, ...]]:
    records: dict[str, _ActionTraceSource] = {}
    warnings: list[str] = []
    errors: list[str] = []
    definitions_by_id = _definitions_by_id(definitions)
    paths = tuple(Path(path) for path in (metadata_paths or default_action_metadata_paths()))

    for path in paths:
        result = load_metadata_document(path)
        warnings.extend(_issue_messages(path, result.report.issues, warning=True))
        errors.extend(_issue_messages(path, result.report.issues, warning=False))
        document = result.document
        if document is None:
            continue
        if document.kind is not GuiMetadataKind.WINDOW:
            warnings.append(f"{_path_text(path)}: skipped non-window metadata document")
            continue
        metadata_ref = _metadata_ref_for(document, path)
        for action in document.actions:
            records[action.action_id] = _merge_source(
                records.get(action.action_id),
                _source_from_metadata_action(
                    document=document,
                    action_id=action.action_id,
                    label=action.label,
                    metadata_ref=metadata_ref,
                    definition=definitions_by_id.get(action.action_id),
                ),
            )

    for definition in definitions:
        records[definition.action_id] = _merge_source(
            records.get(definition.action_id),
            _source_from_definition(definition),
        )

    return (
        tuple(records[action_id] for action_id in sorted(records)),
        tuple(warnings),
        tuple(errors),
    )


def _source_from_metadata_action(
    *,
    document: GuiMetadataDocument,
    action_id: str,
    label: str,
    metadata_ref: str,
    definition: ActionDefinition | None,
) -> _ActionTraceSource:
    window_id = _window_id_for(document)
    required_permissions = (
        _permission_values(definition.required_permissions)
        if definition is not None
        else ()
    )
    return _ActionTraceSource(
        action_id=action_id,
        label=label,
        window_id=window_id,
        metadata_id=document.metadata_id,
        metadata_ref=metadata_ref,
        action_kind=definition.kind.value if definition is not None else None,
        required_permissions=required_permissions,
        is_placeholder=definition.is_placeholder if definition is not None else None,
        sources=("window_metadata",),
    )


def _source_from_definition(definition: ActionDefinition) -> _ActionTraceSource:
    if not isinstance(definition, ActionDefinition):
        raise TypeError("definitions entries must be ActionDefinition")
    return _ActionTraceSource(
        action_id=definition.action_id,
        label=definition.label,
        window_id=definition.window_id,
        action_kind=definition.kind.value,
        required_permissions=_permission_values(definition.required_permissions),
        is_placeholder=definition.is_placeholder,
        sources=("action_observer_definition",),
    )


def _merge_source(
    existing: _ActionTraceSource | None,
    incoming: _ActionTraceSource,
) -> _ActionTraceSource:
    if existing is None:
        return incoming
    return _ActionTraceSource(
        action_id=existing.action_id,
        label=existing.label or incoming.label,
        window_id=existing.window_id or incoming.window_id,
        metadata_id=existing.metadata_id or incoming.metadata_id,
        metadata_ref=existing.metadata_ref or incoming.metadata_ref,
        action_kind=existing.action_kind or incoming.action_kind,
        required_permissions=existing.required_permissions or incoming.required_permissions,
        is_placeholder=(
            existing.is_placeholder
            if existing.is_placeholder is not None
            else incoming.is_placeholder
        ),
        sources=tuple(dict.fromkeys((*existing.sources, *incoming.sources))),
    )


def _summary_from_source(source: _ActionTraceSource) -> TraceableObjectSummary:
    object_ref = _action_ref(source)
    relationships = (
        *_window_relationships_for(source, object_ref),
        *_permission_relationships_for(source, object_ref),
    )
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status="defined",
        runtime_or_persistent=ACTION_TRACE_RUNTIME_KIND,
        display_name=source.label,
        metadata_ref=source.metadata_ref or source.action_id,
        metadata=_action_summary_metadata(source),
        relationship_refs=relationships,
        permission_refs=source.required_permissions,
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "static_gui_metadata_and_action_definitions",
        },
    )


def _action_ref(source: _ActionTraceSource) -> TraceableObjectRef:
    return TraceableObjectRef(
        object_id=source.action_id,
        object_kind="action",
        owner_domain=ACTION_TRACE_OWNER_DOMAIN,
        owner_component=ACTION_TRACE_OWNER_COMPONENT,
        label=source.label,
        metadata={
            "action_id": source.action_id,
            "window_id": source.window_id,
            "metadata_id": source.metadata_id,
            "metadata_ref": source.metadata_ref,
        },
    )


def _window_relationships_for(
    source: _ActionTraceSource,
    action_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    if source.window_id is None:
        return ()
    return (
        TraceableRelationshipRef(
            relationship_id=f"{source.action_id}.contained_by.{source.window_id}",
            relationship_type="contains_action",
            source_ref=action_ref,
            target_ref=TraceableObjectRef(
                object_id=source.window_id,
                object_kind="window",
                owner_domain=ACTION_TRACE_OWNER_DOMAIN,
                owner_component="GUI metadata window trace helper",
                metadata={
                    "window_id": source.window_id,
                    "metadata_id": source.metadata_id,
                    "metadata_ref": source.metadata_ref,
                },
            ),
            direction="inbound",
            lifecycle_status="defined",
            metadata={
                "action_id": source.action_id,
                "window_id": source.window_id,
                "relationship_semantics": "declared_by_window_metadata",
            },
        ),
    )


def _permission_relationships_for(
    source: _ActionTraceSource,
    action_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    return tuple(
        TraceableRelationshipRef(
            relationship_id=f"{source.action_id}.has_permission.{permission}",
            relationship_type="has_permission",
            source_ref=action_ref,
            target_ref=TraceableObjectRef(
                object_id=permission,
                object_kind="permission",
                owner_domain="core.policy",
                owner_component="UserPolicy",
                label=permission,
                metadata={"permission_ref": permission},
            ),
            direction="outbound",
            lifecycle_status="defined",
            metadata={
                "action_id": source.action_id,
                "permission_ref": permission,
            },
        )
        for permission in source.required_permissions
    )


def _action_summary_metadata(source: _ActionTraceSource) -> Mapping[str, object]:
    is_placeholder = bool(source.is_placeholder) if source.is_placeholder is not None else False
    return {
        "action_id": source.action_id,
        "window_id": source.window_id,
        "metadata_id": source.metadata_id,
        "metadata_ref": source.metadata_ref,
        "action_kind": source.action_kind,
        "label": source.label,
        "required_permissions": source.required_permissions,
        "is_placeholder": is_placeholder,
        "implementation_status": "placeholder" if is_placeholder else "defined",
        "sources": source.sources,
    }


def _action_relationship_definitions() -> tuple[object, ...]:
    return (
        *object_relationship_definitions_by_type("contains_action"),
        *object_relationship_definitions_by_type("has_permission"),
        *object_relationship_definitions_by_type("triggers"),
    )


def _definitions_by_id(
    definitions: Sequence[ActionDefinition],
) -> dict[str, ActionDefinition]:
    result: dict[str, ActionDefinition] = {}
    for definition in definitions:
        if not isinstance(definition, ActionDefinition):
            raise TypeError("definitions entries must be ActionDefinition")
        result[definition.action_id] = definition
    return result


def _validate_window_document(document: GuiMetadataDocument) -> None:
    if not isinstance(document, GuiMetadataDocument):
        raise TypeError("document must be a GuiMetadataDocument")
    if document.kind is not GuiMetadataKind.WINDOW:
        raise ValueError("document kind must be window")


def _window_id_for(document: GuiMetadataDocument) -> str:
    value = _metadata_string(document.metadata, "window_id")
    return value or document.metadata_id


def _metadata_ref_for(
    document: GuiMetadataDocument,
    metadata_path: str | Path | None,
) -> str:
    if metadata_path is None:
        return document.metadata_id
    return _path_text(Path(metadata_path))


def _metadata_string(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _permission_values(values: object) -> tuple[str, ...]:
    return tuple(permission.value for permission in values)


def _issue_messages(
    path: Path,
    issues: object,
    *,
    warning: bool,
) -> tuple[str, ...]:
    expected_severity = (
        GuiMetadataIssueSeverity.WARNING
        if warning
        else GuiMetadataIssueSeverity.ERROR
    )
    return tuple(
        f"{_path_text(path)}: {issue.code.value} {issue.path}: {issue.message}"
        for issue in issues
        if issue.severity is expected_severity
    )


def _find_summary(
    summaries: tuple[TraceableObjectSummary, ...],
    action_id: str,
) -> TraceableObjectSummary | None:
    for summary in summaries:
        if action_id in (summary.object_ref.object_id, summary.metadata.get("action_id")):
            return summary
    return None


def _path_text(path: Path) -> str:
    return path.as_posix()


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


__all__ = [
    "ACTION_TRACE_OWNER_COMPONENT",
    "ACTION_TRACE_OWNER_DOMAIN",
    "ACTION_TRACE_PROVIDER_ID",
    "ACTION_TRACE_RUNTIME_KIND",
    "ACTION_TRACE_SECTION_ID",
    "action_trace_summaries_from_document",
    "build_action_trace_provider_descriptor",
    "build_action_trace_section",
    "default_action_metadata_paths",
    "interrogate_action_trace",
]
