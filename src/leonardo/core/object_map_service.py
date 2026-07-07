"""Read-only Object Map aggregation service.

This module aggregates explicitly supplied Object Map provider outputs into
snapshot and query report contracts. It does not discover providers, inspect
source managers directly, mutate runtime state, register global providers, or
wire Runtime Manager.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import re

from leonardo.contracts.object_map import (
    ObjectMapProviderDescriptor,
    ObjectMapQuery,
    ObjectMapQueryReport,
    ObjectMapSection,
    ObjectMapSnapshot,
)
from leonardo.contracts.traceable_object import (
    ObjectFamilyLegend,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


DEFAULT_OBJECT_MAP_SNAPSHOT_ID = "core.object_map.snapshot"

ObjectMapSectionBuilder = Callable[[], ObjectMapSection | Mapping[str, object]]

_MAX_PROVIDER_FAILURE_MESSAGE_LENGTH = 160
_REDACTED_VALUE = "[redacted]"
_REDACTED_PATH = "[path]"
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    r"(?i)((?:['\"])?\b"
    r"(?:token|secret|password|passwd|api_key|apikey|authorization|bearer|credential)"
    r"\b(?:['\"])?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_BEARER_VALUE_PATTERN = re.compile(
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"
)
_WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:\\[^\s,;]+")
_POSIX_PATH_PATTERN = re.compile(r"(?<!\w)/(?:[^/\s,;]+/)+[^\s,;]+")


@dataclass(frozen=True)
class ObjectMapProviderEntry:
    """
    Explicit read-only Object Map provider input.

    The entry binds one immutable provider descriptor to a callable that emits a
    read-only `ObjectMapSection`. Construction is local to the service caller;
    no global registration, discovery, or source-manager access is performed by
    this module.
    """

    descriptor: ObjectMapProviderDescriptor | Mapping[str, object]
    build_section: ObjectMapSectionBuilder

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "descriptor",
            _normalize_provider_descriptor(self.descriptor),
        )
        if not callable(self.build_section):
            raise TypeError("build_section must be callable")


@dataclass(frozen=True)
class _ProviderBuildResult:
    sections: tuple[ObjectMapSection, ...]
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    errors: tuple[str, ...]


class ReadOnlyObjectMapService:
    """
    Aggregate explicit read-only Object Map provider outputs.

    The service owns only the provider entry list passed at construction time
    and the query logic over provider-emitted sections. It does not own the
    source objects represented by summaries or relationships, and it does not
    call source managers directly.
    """

    def __init__(self, providers: Iterable[ObjectMapProviderEntry] = ()) -> None:
        entries = tuple(_normalize_provider_entry(provider) for provider in providers)
        _validate_unique_provider_ids(entries)
        self._providers = tuple(
            sorted(entries, key=lambda provider: provider.descriptor.provider_id)
        )

    def get_provider_descriptors(self) -> tuple[ObjectMapProviderDescriptor, ...]:
        """Return provider descriptors in deterministic provider ID order."""

        return tuple(provider.descriptor for provider in self._providers)

    def build_snapshot(
        self,
        *,
        snapshot_id: str = DEFAULT_OBJECT_MAP_SNAPSHOT_ID,
        generated_at_utc: str | None = None,
    ) -> ObjectMapSnapshot:
        """
        Build an Object Map snapshot from explicit provider entries.

        Provider callable failures are reported in the snapshot errors and do
        not prevent other providers from contributing sections.
        """

        build_result = self._build_sections()
        return ObjectMapSnapshot(
            snapshot_id=snapshot_id,
            generated_at_utc=generated_at_utc or _utc_now_text(),
            sections=build_result.sections,
            provider_descriptors=self.get_provider_descriptors(),
            warnings=build_result.warnings,
            blockers=build_result.blockers,
            errors=build_result.errors,
            metadata=_snapshot_metadata(build_result.sections, self._providers),
            extra={
                "read_only": True,
                "mutation_forbidden": True,
                "source": "explicit_object_map_provider_entries",
            },
        )

    def list_sections(self) -> tuple[ObjectMapSection, ...]:
        """Return sections from a freshly built read-only snapshot."""

        return self.build_snapshot().sections

    def query(
        self,
        query: ObjectMapQuery | Mapping[str, object] | None = None,
        *,
        snapshot_id: str = DEFAULT_OBJECT_MAP_SNAPSHOT_ID,
        generated_at_utc: str | None = None,
    ) -> ObjectMapQueryReport:
        """
        Execute an Object Map query over a freshly built read-only snapshot.

        Filtering is limited to fields already present on `ObjectMapQuery`:
        object kind, family ID, object ID, owner domain, provider ID, and
        relationship type. Source/target-specific filters require a future
        contract extension.
        """

        normalized_query = _normalize_query(query)
        snapshot = self.build_snapshot(
            snapshot_id=snapshot_id,
            generated_at_utc=generated_at_utc,
        )
        descriptors = _filter_provider_descriptors(
            snapshot.provider_descriptors,
            normalized_query,
        )
        sections = tuple(
            section
            for section in (
                _filter_section(section, normalized_query)
                for section in snapshot.sections
                if _provider_matches(section.provider_id, normalized_query)
            )
            if section is not None
        )
        summaries = tuple(
            summary
            for section in sections
            for summary in section.summaries
        )
        relationships = tuple(
            relationship
            for section in sections
            for relationship in section.relationships
        )
        legends = tuple(
            legend
            for section in sections
            for legend in section.legends
        )
        definitions = tuple(
            definition
            for section in sections
            for definition in section.relationship_definitions
        )
        return ObjectMapQueryReport(
            query=normalized_query,
            sections=sections,
            summaries=summaries,
            relationships=relationships,
            legends=legends,
            relationship_definitions=definitions,
            provider_descriptors=descriptors,
            warnings=snapshot.warnings,
            blockers=snapshot.blockers,
            errors=snapshot.errors,
            metadata={
                "snapshot_id": snapshot.snapshot_id,
                "section_count": len(sections),
                "summary_count": len(summaries),
                "relationship_count": len(relationships),
                "legend_count": len(legends),
                "relationship_definition_count": len(definitions),
                "provider_descriptor_count": len(descriptors),
                "read_only": True,
            },
            extra={
                "mutation_forbidden": True,
                "query_source": "fresh_object_map_snapshot",
            },
        )

    def _build_sections(self) -> _ProviderBuildResult:
        sections: list[ObjectMapSection] = []
        errors: list[str] = []
        for provider in self._providers:
            provider_id = provider.descriptor.provider_id
            try:
                section = _normalize_section(provider.build_section())
            except Exception as error:  # noqa: BLE001 - boundary-level report.
                errors.append(
                    "Object Map provider failed "
                    f"{provider_id}: {_format_provider_failure(error)}"
                )
                continue
            if section.provider_id != provider_id:
                errors.append(
                    "Object Map provider "
                    f"{provider_id} emitted section {section.section_id} "
                    f"for provider_id {section.provider_id}"
                )
                continue
            sections.append(section)

        normalized_sections = tuple(sections)
        warnings = [
            *(
                f"Object Map section {section.section_id} warning: {warning}"
                for section in normalized_sections
                for warning in section.warnings
            ),
            *_duplicate_section_warnings(normalized_sections),
            *_duplicate_object_warnings(normalized_sections),
        ]
        blockers = tuple(
            f"Object Map section {section.section_id} blocker: {blocker}"
            for section in normalized_sections
            for blocker in section.blockers
        )
        collected_errors = [
            *errors,
            *(
                f"Object Map section {section.section_id} error: {error}"
                for section in normalized_sections
                for error in section.errors
            ),
        ]
        return _ProviderBuildResult(
            sections=normalized_sections,
            warnings=tuple(warnings),
            blockers=blockers,
            errors=tuple(collected_errors),
        )


def _normalize_provider_entry(provider: ObjectMapProviderEntry) -> ObjectMapProviderEntry:
    if not isinstance(provider, ObjectMapProviderEntry):
        raise TypeError("providers must contain ObjectMapProviderEntry values")
    return provider


def _normalize_provider_descriptor(
    descriptor: ObjectMapProviderDescriptor | Mapping[str, object],
) -> ObjectMapProviderDescriptor:
    if isinstance(descriptor, ObjectMapProviderDescriptor):
        return descriptor
    if isinstance(descriptor, Mapping):
        return ObjectMapProviderDescriptor.from_dict(descriptor)
    raise TypeError("descriptor must be an ObjectMapProviderDescriptor or mapping")


def _normalize_section(
    section: ObjectMapSection | Mapping[str, object],
) -> ObjectMapSection:
    if isinstance(section, ObjectMapSection):
        return section
    if isinstance(section, Mapping):
        return ObjectMapSection.from_dict(section)
    raise TypeError("provider build_section must return an ObjectMapSection or mapping")


def _normalize_query(
    query: ObjectMapQuery | Mapping[str, object] | None,
) -> ObjectMapQuery:
    if query is None:
        return ObjectMapQuery()
    if isinstance(query, ObjectMapQuery):
        return query
    if isinstance(query, Mapping):
        return ObjectMapQuery.from_dict(query)
    raise TypeError("query must be an ObjectMapQuery, mapping, or None")


def _validate_unique_provider_ids(providers: tuple[ObjectMapProviderEntry, ...]) -> None:
    counts = Counter(provider.descriptor.provider_id for provider in providers)
    duplicates = sorted(provider_id for provider_id, count in counts.items() if count > 1)
    if duplicates:
        joined = ", ".join(duplicates)
        raise ValueError(f"Duplicate Object Map provider_id values: {joined}")


def _format_provider_failure(
    error: BaseException,
    *,
    max_message_length: int = _MAX_PROVIDER_FAILURE_MESSAGE_LENGTH,
) -> str:
    error_type = _safe_exception_type_name(error)
    message = _bounded_text(
        _sanitize_provider_failure_message(_exception_message_text(error)),
        max_length=max_message_length,
    )
    return f"{error_type}: {message}"


def _safe_exception_type_name(error: BaseException) -> str:
    name = type(error).__name__
    return name if name.isidentifier() else "Exception"


def _exception_message_text(error: BaseException) -> str:
    args = getattr(error, "args", ())
    if not args:
        return "<no message>"
    return " ".join(_argument_text(arg) for arg in args)


def _argument_text(value: object) -> str:
    text = str(value)
    return text if text.strip() else "<blank message>"


def _sanitize_provider_failure_message(message: str) -> str:
    collapsed = " ".join(message.split())
    redacted = _BEARER_VALUE_PATTERN.sub(f"Bearer {_REDACTED_VALUE}", collapsed)
    redacted = _SENSITIVE_KEY_VALUE_PATTERN.sub(
        lambda match: f"{match.group(1)}{_REDACTED_VALUE}",
        redacted,
    )
    redacted = _WINDOWS_PATH_PATTERN.sub(_REDACTED_PATH, redacted)
    redacted = _POSIX_PATH_PATTERN.sub(_REDACTED_PATH, redacted)
    return redacted


def _bounded_text(message: str, *, max_length: int) -> str:
    if len(message) <= max_length:
        return message
    suffix = "..."
    return f"{message[: max_length - len(suffix)].rstrip()}{suffix}"


def _snapshot_metadata(
    sections: tuple[ObjectMapSection, ...],
    providers: tuple[ObjectMapProviderEntry, ...],
) -> Mapping[str, object]:
    summaries = tuple(summary for section in sections for summary in section.summaries)
    relationships = tuple(
        relationship for section in sections for relationship in section.relationships
    )
    return {
        "provider_count": len(providers),
        "section_count": len(sections),
        "summary_count": len(summaries),
        "relationship_count": len(relationships),
        "section_ids": tuple(section.section_id for section in sections),
        "provider_ids": tuple(provider.descriptor.provider_id for provider in providers),
        "read_only": True,
    }


def _filter_provider_descriptors(
    descriptors: tuple[ObjectMapProviderDescriptor, ...],
    query: ObjectMapQuery,
) -> tuple[ObjectMapProviderDescriptor, ...]:
    if not query.include_provider_descriptors:
        return ()
    return tuple(
        _descriptor_with_requested_refs(descriptor, query)
        for descriptor in descriptors
        if _provider_descriptor_matches(descriptor, query)
    )


def _provider_descriptor_matches(
    descriptor: ObjectMapProviderDescriptor,
    query: ObjectMapQuery,
) -> bool:
    if query.provider_id is not None and descriptor.provider_id != query.provider_id:
        return False
    if query.owner_domain is not None and descriptor.owner_domain != query.owner_domain:
        return False
    if query.object_kind is not None and query.object_kind not in descriptor.object_kinds:
        return False
    if query.family_id is not None and query.family_id not in descriptor.family_ids:
        return False
    if (
        query.relationship_type is not None
        and query.relationship_type not in descriptor.relationship_types
    ):
        return False
    return True


def _descriptor_with_requested_refs(
    descriptor: ObjectMapProviderDescriptor,
    query: ObjectMapQuery,
) -> ObjectMapProviderDescriptor:
    if query.include_docs and query.include_tests:
        return descriptor
    data = descriptor.to_dict()
    if not query.include_docs:
        data["related_docs"] = []
    if not query.include_tests:
        data["related_tests"] = []
    return ObjectMapProviderDescriptor.from_dict(data)


def _filter_section(
    section: ObjectMapSection,
    query: ObjectMapQuery,
) -> ObjectMapSection | None:
    summaries = (
        tuple(
            summary
            for summary in section.summaries
            if _summary_matches(summary, section, query)
        )
        if query.include_summaries
        else ()
    )
    relationships = (
        tuple(
            relationship
            for relationship in section.relationships
            if _relationship_matches(relationship, section, query)
        )
        if query.include_relationships
        else ()
    )
    legends = (
        tuple(
            legend
            for legend in section.legends
            if _legend_matches(legend, section, query)
        )
        if query.include_legends
        else ()
    )
    definitions = (
        tuple(
            definition
            for definition in section.relationship_definitions
            if _definition_matches(definition, section, query)
        )
        if query.include_relationship_definitions
        else ()
    )

    if not _filtered_section_has_match(
        section,
        query,
        summaries=summaries,
        relationships=relationships,
        legends=legends,
        definitions=definitions,
    ):
        return None

    return ObjectMapSection(
        section_id=section.section_id,
        provider_id=section.provider_id,
        owner_domain=section.owner_domain,
        object_kind=section.object_kind,
        family_id=section.family_id,
        title=section.title,
        summaries=summaries,
        relationships=relationships,
        legends=legends,
        relationship_definitions=definitions,
        warnings=section.warnings,
        blockers=section.blockers,
        errors=section.errors,
        metadata={
            **dict(section.metadata),
            "query_filtered": True,
        },
        extra=section.extra,
    )


def _filtered_section_has_match(
    section: ObjectMapSection,
    query: ObjectMapQuery,
    *,
    summaries: tuple[TraceableObjectSummary, ...],
    relationships: tuple[TraceableRelationshipRef, ...],
    legends: tuple[ObjectFamilyLegend, ...],
    definitions: tuple[object, ...],
) -> bool:
    if not _provider_matches(section.provider_id, query):
        return False
    has_content_filter = any(
        (
            query.object_id,
            query.object_kind,
            query.family_id,
            query.relationship_type,
        )
    )
    if query.owner_domain is not None and section.owner_domain == query.owner_domain:
        return not has_content_filter or any(
            (summaries, relationships, legends, definitions)
        )
    if not has_content_filter and query.owner_domain is None:
        return True
    return any((summaries, relationships, legends, definitions))


def _provider_matches(provider_id: str, query: ObjectMapQuery) -> bool:
    return query.provider_id is None or provider_id == query.provider_id


def _summary_matches(
    summary: TraceableObjectSummary,
    section: ObjectMapSection,
    query: ObjectMapQuery,
) -> bool:
    object_ref = summary.object_ref
    if query.object_id is not None and object_ref.object_id != query.object_id:
        return False
    if query.object_kind is not None and object_ref.object_kind != query.object_kind:
        return False
    if query.family_id is not None and not _summary_matches_family(
        summary,
        section,
        query,
    ):
        return False
    if query.owner_domain is not None and not _owner_domain_matches(
        query.owner_domain,
        section.owner_domain,
        object_ref.owner_domain,
    ):
        return False
    return True


def _summary_matches_family(
    summary: TraceableObjectSummary,
    section: ObjectMapSection,
    query: ObjectMapQuery,
) -> bool:
    family_id = query.family_id
    if family_id is None:
        return True
    return family_id in {
        summary.object_ref.object_kind,
        section.family_id,
        _metadata_string(summary.object_ref.metadata, "family_id"),
        _metadata_string(summary.metadata, "family_id"),
    }


def _relationship_matches(
    relationship: TraceableRelationshipRef,
    section: ObjectMapSection,
    query: ObjectMapQuery,
) -> bool:
    if (
        query.relationship_type is not None
        and relationship.relationship_type != query.relationship_type
    ):
        return False
    if query.object_id is not None and query.object_id not in {
        relationship.source_ref.object_id,
        relationship.target_ref.object_id,
    }:
        return False
    if query.object_kind is not None and query.object_kind not in {
        relationship.source_ref.object_kind,
        relationship.target_ref.object_kind,
    }:
        return False
    if query.family_id is not None and query.family_id not in {
        relationship.source_ref.object_kind,
        relationship.target_ref.object_kind,
    }:
        return False
    if query.owner_domain is not None and not _owner_domain_matches(
        query.owner_domain,
        section.owner_domain,
        relationship.source_ref.owner_domain,
        relationship.target_ref.owner_domain,
    ):
        return False
    return True


def _legend_matches(
    legend: ObjectFamilyLegend,
    section: ObjectMapSection,
    query: ObjectMapQuery,
) -> bool:
    if query.object_id is not None:
        return False
    if query.object_kind is not None and legend.object_kind != query.object_kind:
        return False
    if query.family_id is not None and legend.family_id != query.family_id:
        return False
    if query.relationship_type is not None and query.relationship_type not in {
        *legend.relationships_in,
        *legend.relationships_out,
    }:
        return False
    if query.owner_domain is not None and not _owner_domain_matches(
        query.owner_domain,
        section.owner_domain,
        legend.owner_domain,
    ):
        return False
    return True


def _definition_matches(
    definition: object,
    section: ObjectMapSection,
    query: ObjectMapQuery,
) -> bool:
    relationship_type = getattr(definition, "relationship_type", None)
    if query.object_id is not None:
        return False
    if (
        query.relationship_type is not None
        and relationship_type != query.relationship_type
    ):
        return False
    if query.object_kind is not None and query.object_kind not in {
        getattr(definition, "source_object_kind", None),
        getattr(definition, "target_object_kind", None),
    }:
        return False
    if query.family_id is not None and query.family_id not in {
        getattr(definition, "source_family_id", None),
        getattr(definition, "target_family_id", None),
    }:
        return False
    if query.owner_domain is not None and not _owner_domain_matches(
        query.owner_domain,
        section.owner_domain,
        getattr(definition, "owner_domain", None),
    ):
        return False
    return True


def _owner_domain_matches(query_owner: str, *owners: object) -> bool:
    return any(owner == query_owner for owner in owners if isinstance(owner, str))


def _metadata_string(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _duplicate_section_warnings(
    sections: tuple[ObjectMapSection, ...],
) -> tuple[str, ...]:
    counts = Counter(section.section_id for section in sections)
    return tuple(
        f"Duplicate Object Map section_id emitted: {section_id}"
        for section_id, count in sorted(counts.items())
        if count > 1
    )


def _duplicate_object_warnings(
    sections: tuple[ObjectMapSection, ...],
) -> tuple[str, ...]:
    counts = Counter(
        summary.object_ref.object_id
        for section in sections
        for summary in section.summaries
    )
    return tuple(
        f"Duplicate Object Map object_id emitted: {object_id}"
        for object_id, count in sorted(counts.items())
        if count > 1
    )


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "DEFAULT_OBJECT_MAP_SNAPSHOT_ID",
    "ObjectMapProviderEntry",
    "ObjectMapSectionBuilder",
    "ReadOnlyObjectMapService",
]
