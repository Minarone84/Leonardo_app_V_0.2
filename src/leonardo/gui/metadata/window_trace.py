"""Read-only trace helpers for GUI window metadata.

The helpers in this module expose static GUI window metadata through the shared
traceability and Object Map report contracts. They read metadata documents only.
They do not instantiate Qt widgets, open windows, execute actions, register
providers, wire Runtime Manager, mutate metadata, or own runtime window state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

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
from leonardo.gui.metadata.loader import load_metadata_document
from leonardo.gui.metadata.models import (
    GuiMetadataDocument,
    GuiMetadataIssueSeverity,
    GuiMetadataKind,
)


WINDOW_TRACE_PROVIDER_ID = "gui.window.trace"
WINDOW_TRACE_SECTION_ID = "gui.windows"
WINDOW_TRACE_OWNER_DOMAIN = "gui"
WINDOW_TRACE_OWNER_COMPONENT = "GUI metadata window trace helper"
WINDOW_TRACE_RUNTIME_KIND = "static_metadata"
WINDOW_TRACE_DOC = "docs/contracts_docs/WINDOW_FAMILY_TRACE.md"
WINDOW_TRACE_TEST = "tests/gui_test/test_window_family_trace.py"

_WINDOW_METADATA_DIR = Path(__file__).with_name("windows")
_DEFAULT_WINDOW_METADATA_FILENAMES: tuple[str, ...] = (
    "main_window.window.toml",
    "runtime_manager.window.toml",
    "connection_suite.window.toml",
    "historical_download_manager.window.toml",
    "research_suite.window.toml",
    "data_manager_suite.window.toml",
    "analysis_suite.window.toml",
    "trading_suite.window.toml",
    "dummy_metadata_test.window.toml",
)
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
    WINDOW_TRACE_DOC,
)


def default_window_metadata_paths() -> tuple[Path, ...]:
    """Return the static window metadata files known to the V2 GUI shell."""

    return tuple(_WINDOW_METADATA_DIR / name for name in _DEFAULT_WINDOW_METADATA_FILENAMES)


def build_window_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Return the static read-only Object Map provider descriptor for windows."""

    return ObjectMapProviderDescriptor(
        provider_id=WINDOW_TRACE_PROVIDER_ID,
        provider_name="GUI Window Trace",
        owner_domain=WINDOW_TRACE_OWNER_DOMAIN,
        owner_component=WINDOW_TRACE_OWNER_COMPONENT,
        object_kinds=("window",),
        family_ids=("window",),
        relationship_types=("contains_action", "opens_window"),
        supports_summary_listing=True,
        supports_interrogation=True,
        supports_relationship_listing=True,
        runtime_or_persistent=WINDOW_TRACE_RUNTIME_KIND,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=_TRACE_CONTRACTS,
        related_docs=_TRACE_DOCS,
        related_tests=(WINDOW_TRACE_TEST,),
        metadata={
            "metadata_source": "src/leonardo/gui/metadata/windows",
            "known_metadata_files": _DEFAULT_WINDOW_METADATA_FILENAMES,
        },
        extra={
            "forbidden_behavior": (
                "qt_widget_construction",
                "window_opening",
                "action_execution",
                "metadata_mutation",
                "runtime_window_state_ownership",
            )
        },
    )


def window_trace_ref_from_document(
    document: GuiMetadataDocument,
    *,
    metadata_path: str | Path | None = None,
) -> TraceableObjectRef:
    """Build a traceable window object reference from one metadata document."""

    _validate_window_document(document)
    window_id = _window_id_for(document)
    return TraceableObjectRef(
        object_id=window_id,
        object_kind="window",
        owner_domain=WINDOW_TRACE_OWNER_DOMAIN,
        owner_component=WINDOW_TRACE_OWNER_COMPONENT,
        schema_version=document.schema_version,
        label=document.label or document.title,
        metadata=_window_ref_metadata(document, metadata_path=metadata_path),
    )


def window_action_relationships_from_document(
    document: GuiMetadataDocument,
    *,
    metadata_path: str | Path | None = None,
) -> tuple[TraceableRelationshipRef, ...]:
    """Build static window-to-action relationship refs from metadata actions."""

    _validate_window_document(document)
    window_ref = window_trace_ref_from_document(
        document,
        metadata_path=metadata_path,
    )
    window_id = window_ref.object_id
    return tuple(
        TraceableRelationshipRef(
            relationship_id=f"{window_id}.contains_action.{action.action_id}",
            relationship_type="contains_action",
            source_ref=window_ref,
            target_ref=TraceableObjectRef(
                object_id=action.action_id,
                object_kind="action",
                owner_domain=WINDOW_TRACE_OWNER_DOMAIN,
                owner_component="GUI metadata action reference",
                label=action.label,
                metadata={
                    "metadata_id": document.metadata_id,
                    "window_id": window_id,
                    "action_id": action.action_id,
                    "action_label": action.label,
                },
            ),
            direction="outbound",
            lifecycle_status="defined",
            metadata={
                "metadata_id": document.metadata_id,
                "window_id": window_id,
                "action_id": action.action_id,
                "action_label": action.label,
            },
        )
        for action in document.actions
    )


def window_trace_summary_from_document(
    document: GuiMetadataDocument,
    *,
    metadata_path: str | Path | None = None,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary from one window metadata document."""

    _validate_window_document(document)
    object_ref = window_trace_ref_from_document(
        document,
        metadata_path=metadata_path,
    )
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status="defined",
        runtime_or_persistent=WINDOW_TRACE_RUNTIME_KIND,
        schema_version=document.schema_version,
        display_name=document.label or document.title,
        metadata_ref=_metadata_ref_for(document, metadata_path),
        metadata=_window_summary_metadata(document, metadata_path=metadata_path),
        relationship_refs=window_action_relationships_from_document(
            document,
            metadata_path=metadata_path,
        ),
        permission_refs=(),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "static_gui_metadata",
        },
    )


def build_window_trace_section(
    *,
    metadata_paths: Iterable[str | Path] | None = None,
) -> ObjectMapSection:
    """Build a read-only Object Map section from static window metadata."""

    paths = tuple(Path(path) for path in (metadata_paths or default_window_metadata_paths()))
    summaries: list[TraceableObjectSummary] = []
    relationships: list[TraceableRelationshipRef] = []
    warnings: list[str] = []
    errors: list[str] = []

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
        try:
            summary = window_trace_summary_from_document(
                document,
                metadata_path=path,
            )
        except (TypeError, ValueError) as error:
            errors.append(f"{_path_text(path)}: {error}")
            continue
        summaries.append(summary)
        relationships.extend(summary.relationship_refs)

    legend = object_family_legend_by_id("window")
    legends = (legend,) if legend is not None else ()
    if legend is None:
        warnings.append("Missing object family legend for window")

    return ObjectMapSection(
        section_id=WINDOW_TRACE_SECTION_ID,
        provider_id=WINDOW_TRACE_PROVIDER_ID,
        owner_domain=WINDOW_TRACE_OWNER_DOMAIN,
        object_kind="window",
        family_id="window",
        title="GUI Windows",
        summaries=tuple(summaries),
        relationships=tuple(relationships),
        legends=legends,
        relationship_definitions=_window_relationship_definitions(),
        warnings=tuple(warnings),
        errors=tuple(errors),
        metadata={
            "metadata_paths": tuple(_path_text(path) for path in paths),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
        },
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "static_gui_metadata",
        },
    )


def interrogate_window_trace(
    object_id: str,
    *,
    metadata_paths: Iterable[str | Path] | None = None,
) -> ObjectInterrogationReport:
    """Return a read-only interrogation report for one static window object."""

    _validate_non_empty_string(object_id, "object_id")
    section = build_window_trace_section(metadata_paths=metadata_paths)
    summary = _find_summary(section.summaries, object_id)
    target_ref = (
        summary.object_ref
        if summary is not None
        else TraceableObjectRef(
            object_id=object_id,
            object_kind="window",
            owner_domain=WINDOW_TRACE_OWNER_DOMAIN,
            owner_component=WINDOW_TRACE_OWNER_COMPONENT,
        )
    )
    family_legend = section.legends[0] if section.legends else None
    blockers = () if summary is not None else (f"Window metadata not found: {object_id}",)

    return ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=family_legend,
        relationships=summary.relationship_refs if summary is not None else (),
        permissions=summary.permission_refs if summary is not None else (),
        docs=_TRACE_DOCS,
        tests=(WINDOW_TRACE_TEST,),
        warnings=section.warnings,
        blockers=(*blockers, *section.blockers),
        errors=section.errors,
        metadata={
            "provider_id": WINDOW_TRACE_PROVIDER_ID,
            "section_id": WINDOW_TRACE_SECTION_ID,
            "object_id": object_id,
            "read_only": True,
        },
    )


def _validate_window_document(document: GuiMetadataDocument) -> None:
    if not isinstance(document, GuiMetadataDocument):
        raise TypeError("document must be a GuiMetadataDocument")
    if document.kind is not GuiMetadataKind.WINDOW:
        raise ValueError("document kind must be window")


def _window_id_for(document: GuiMetadataDocument) -> str:
    value = _metadata_string(document.metadata, "window_id")
    return value or document.metadata_id


def _window_ref_metadata(
    document: GuiMetadataDocument,
    *,
    metadata_path: str | Path | None,
) -> Mapping[str, object]:
    return {
        "metadata_id": document.metadata_id,
        "window_id": _window_id_for(document),
        "object_name": _metadata_string(document.metadata, "object_name"),
        "metadata_ref": _metadata_ref_for(document, metadata_path),
    }


def _window_summary_metadata(
    document: GuiMetadataDocument,
    *,
    metadata_path: str | Path | None,
) -> Mapping[str, object]:
    return {
        "metadata_id": document.metadata_id,
        "window_id": _window_id_for(document),
        "object_name": _metadata_string(document.metadata, "object_name"),
        "title": document.title,
        "label": document.label or document.title,
        "owner_area": _metadata_string(document.metadata, "owner_area"),
        "instance_policy": _metadata_string(document.metadata, "instance_policy"),
        "settings_present": bool(document.settings),
        "action_ids": tuple(action.action_id for action in document.actions),
        "region_ids": tuple(region.region_id for region in document.regions),
        "table_ids": tuple(table.table_id for table in document.tables),
        "report_ids": tuple(report.report_id for report in document.reports),
        "metadata_ref": _metadata_ref_for(document, metadata_path),
    }


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


def _window_relationship_definitions() -> tuple[object, ...]:
    return (
        *object_relationship_definitions_by_type("contains_action"),
        *object_relationship_definitions_by_type("opens_window"),
    )


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
    object_id: str,
) -> TraceableObjectSummary | None:
    for summary in summaries:
        metadata_id = summary.metadata.get("metadata_id")
        window_id = summary.metadata.get("window_id")
        if object_id in (summary.object_ref.object_id, metadata_id, window_id):
            return summary
    return None


def _path_text(path: Path) -> str:
    return path.as_posix()


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


__all__ = [
    "WINDOW_TRACE_OWNER_COMPONENT",
    "WINDOW_TRACE_OWNER_DOMAIN",
    "WINDOW_TRACE_PROVIDER_ID",
    "WINDOW_TRACE_SECTION_ID",
    "WINDOW_TRACE_RUNTIME_KIND",
    "build_window_trace_provider_descriptor",
    "build_window_trace_section",
    "default_window_metadata_paths",
    "interrogate_window_trace",
    "window_action_relationships_from_document",
    "window_trace_ref_from_document",
    "window_trace_summary_from_document",
]
