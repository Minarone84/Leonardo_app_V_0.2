"""Read-only Object Map trace helpers for suite boundary descriptors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum

from leonardo.contracts.object_map import (
    ObjectMapProviderDescriptor,
    ObjectMapSection,
)
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.suite_boundary import (
    AreaDescriptor,
    SuiteCommandDescriptor,
    SuiteDescriptor,
    SuiteModuleDescriptor,
    SuiteQueryDescriptor,
)
from leonardo.contracts.traceable_object import (
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


SUITE_BOUNDARY_TRACE_PROVIDER_ID = "core.suite_boundary.trace"
SUITE_BOUNDARY_TRACE_SECTION_ID = "core.suite_boundary"

AREA_OBJECT_KIND = "area"
SUITE_OBJECT_KIND = "suite"
SUITE_MODULE_OBJECT_KIND = "suite_module"
SUITE_COMMAND_OBJECT_KIND = "suite_command"
SUITE_QUERY_OBJECT_KIND = "suite_query"
PERMISSION_OBJECT_KIND = "permission"
OBJECT_FAMILY_OBJECT_KIND = "object_family"
ACTION_OBJECT_KIND = "action"

_DESCRIPTOR_OBJECT_KINDS = (
    AREA_OBJECT_KIND,
    SUITE_OBJECT_KIND,
    SUITE_MODULE_OBJECT_KIND,
    SUITE_COMMAND_OBJECT_KIND,
    SUITE_QUERY_OBJECT_KIND,
)
_RELATED_DOC = "docs/core_docs/SUITE_OBJECT_MAP_PATTERN.md"
_RELATED_CONTRACT_DOC = "docs/contracts_docs/SUITE_BOUNDARY.md"
_RELATED_TEST = "tests/core_test/test_suite_boundary_object_map_pattern.py"
_FAMILY_LEGEND_WARNING = (
    "Formal ObjectFamilyLegend descriptors for area, suite, suite_module, "
    "suite_command, and suite_query are future work."
)


def build_suite_boundary_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Build the read-only provider descriptor for suite boundary descriptors."""

    return ObjectMapProviderDescriptor(
        provider_id=SUITE_BOUNDARY_TRACE_PROVIDER_ID,
        provider_name="Suite Boundary Trace",
        owner_domain="core",
        owner_component="SuiteBoundaryTrace",
        object_kinds=_DESCRIPTOR_OBJECT_KINDS,
        family_ids=_DESCRIPTOR_OBJECT_KINDS,
        relationship_types=("references", "has_permission"),
        supports_summary_listing=True,
        supports_interrogation=False,
        supports_relationship_listing=True,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=(
            "leonardo.contracts.suite_boundary.AreaDescriptor",
            "leonardo.contracts.suite_boundary.SuiteDescriptor",
            "leonardo.contracts.suite_boundary.SuiteModuleDescriptor",
            "leonardo.contracts.suite_boundary.SuiteCommandDescriptor",
            "leonardo.contracts.suite_boundary.SuiteQueryDescriptor",
        ),
        related_docs=(_RELATED_CONTRACT_DOC, _RELATED_DOC),
        related_tests=(_RELATED_TEST,),
        metadata={
            "descriptor_source": "explicit_descriptor_inputs",
            "object_family_legend_promotion": "future",
        },
        extra={"read_only": True, "mutation_forbidden": True},
    )


def area_trace_ref_from_descriptor(area: AreaDescriptor) -> TraceableObjectRef:
    """Build a traceable object reference for an area descriptor."""

    _require_type(area, AreaDescriptor, "area")
    return TraceableObjectRef(
        object_id=area.area_id,
        object_kind=AREA_OBJECT_KIND,
        owner_domain=area.owner_domain,
        owner_component=area.owner_component,
        schema_version=area.version,
        label=area.display_name,
        metadata={"family_id": AREA_OBJECT_KIND, "descriptor_type": "AreaDescriptor"},
    )


def suite_trace_ref_from_descriptor(suite: SuiteDescriptor) -> TraceableObjectRef:
    """Build a traceable object reference for a suite descriptor."""

    _require_type(suite, SuiteDescriptor, "suite")
    return TraceableObjectRef(
        object_id=suite.suite_id,
        object_kind=SUITE_OBJECT_KIND,
        owner_domain=suite.owner_domain,
        owner_component=suite.owner_component,
        schema_version=suite.version,
        label=suite.display_name,
        metadata={"family_id": SUITE_OBJECT_KIND, "descriptor_type": "SuiteDescriptor"},
    )


def suite_module_trace_ref_from_descriptor(
    module: SuiteModuleDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a suite module descriptor."""

    _require_type(module, SuiteModuleDescriptor, "module")
    return TraceableObjectRef(
        object_id=module.module_id,
        object_kind=SUITE_MODULE_OBJECT_KIND,
        owner_domain=module.owner_domain,
        owner_component=module.owner_component,
        label=module.display_name,
        metadata={
            "family_id": SUITE_MODULE_OBJECT_KIND,
            "descriptor_type": "SuiteModuleDescriptor",
        },
    )


def suite_command_trace_ref_from_descriptor(
    command: SuiteCommandDescriptor,
    *,
    areas: Iterable[AreaDescriptor] = (),
    suites: Iterable[SuiteDescriptor] = (),
    modules: Iterable[SuiteModuleDescriptor] = (),
) -> TraceableObjectRef:
    """Build a traceable object reference for a suite command descriptor."""

    _require_type(command, SuiteCommandDescriptor, "command")
    owner = _resolve_command_query_owner(
        suite_id=command.suite_id,
        area_id=command.area_id,
        module_id=command.module_id,
        areas=areas,
        suites=suites,
        modules=modules,
        fallback_component="SuiteCommandDescriptor",
    )
    return TraceableObjectRef(
        object_id=command.command_id,
        object_kind=SUITE_COMMAND_OBJECT_KIND,
        owner_domain=owner.owner_domain,
        owner_component=owner.owner_component,
        label=command.label,
        metadata={
            "family_id": SUITE_COMMAND_OBJECT_KIND,
            "descriptor_type": "SuiteCommandDescriptor",
        },
    )


def suite_query_trace_ref_from_descriptor(
    query: SuiteQueryDescriptor,
    *,
    areas: Iterable[AreaDescriptor] = (),
    suites: Iterable[SuiteDescriptor] = (),
    modules: Iterable[SuiteModuleDescriptor] = (),
) -> TraceableObjectRef:
    """Build a traceable object reference for a suite query descriptor."""

    _require_type(query, SuiteQueryDescriptor, "query")
    owner = _resolve_command_query_owner(
        suite_id=query.suite_id,
        area_id=query.area_id,
        module_id=query.module_id,
        areas=areas,
        suites=suites,
        modules=modules,
        fallback_component="SuiteQueryDescriptor",
    )
    return TraceableObjectRef(
        object_id=query.query_id,
        object_kind=SUITE_QUERY_OBJECT_KIND,
        owner_domain=owner.owner_domain,
        owner_component=owner.owner_component,
        label=query.label,
        metadata={
            "family_id": SUITE_QUERY_OBJECT_KIND,
            "descriptor_type": "SuiteQueryDescriptor",
        },
    )


def area_trace_summary_from_descriptor(area: AreaDescriptor) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for an area descriptor."""

    ref = area_trace_ref_from_descriptor(area)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(area.lifecycle_status),
        runtime_or_persistent="static_metadata",
        display_name=area.display_name,
        metadata={
            "family_id": AREA_OBJECT_KIND,
            "area_id": area.area_id,
            "area_kind": _value(area.area_kind),
            "lifecycle_status": _value(area.lifecycle_status),
            "version": area.version,
            "suite_id": area.suite_id,
            "module_ids": area.module_ids,
            "command_ids": area.command_ids,
            "query_ids": area.query_ids,
            "object_family_ids": area.object_family_ids,
            "required_permissions": area.required_permissions,
            "audit_categories": area.audit_categories,
            "object_map_provider_id": area.object_map_provider_id,
            "runtime_summary_kind": area.runtime_summary_kind,
            "docs_refs": area.docs_refs,
            "test_refs": area.test_refs,
            "warnings": area.warnings,
            "blockers": area.blockers,
            "read_only": True,
        },
        permission_refs=area.required_permissions,
        source_refs=(area.owner_component,),
        extra={"descriptor_type": "AreaDescriptor", "mutation_forbidden": True},
    )


def suite_trace_summary_from_descriptor(
    suite: SuiteDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a suite descriptor."""

    ref = suite_trace_ref_from_descriptor(suite)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(suite.lifecycle_status),
        runtime_or_persistent="static_metadata",
        display_name=suite.display_name,
        metadata={
            "family_id": SUITE_OBJECT_KIND,
            "suite_id": suite.suite_id,
            "lifecycle_status": _value(suite.lifecycle_status),
            "version": suite.version,
            "area_ids": suite.area_ids,
            "module_ids": suite.module_ids,
            "supported_command_ids": suite.supported_command_ids,
            "supported_query_ids": suite.supported_query_ids,
            "object_family_ids": suite.object_family_ids,
            "required_permissions": suite.required_permissions,
            "audit_categories": suite.audit_categories,
            "object_map_provider_id": suite.object_map_provider_id,
            "runtime_summary_kind": suite.runtime_summary_kind,
            "docs_refs": suite.docs_refs,
            "test_refs": suite.test_refs,
            "warnings": suite.warnings,
            "blockers": suite.blockers,
            "read_only": True,
        },
        permission_refs=suite.required_permissions,
        source_refs=(suite.owner_component,),
        extra={"descriptor_type": "SuiteDescriptor", "mutation_forbidden": True},
    )


def suite_module_trace_summary_from_descriptor(
    module: SuiteModuleDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a suite module descriptor."""

    ref = suite_module_trace_ref_from_descriptor(module)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(module.lifecycle_status),
        runtime_or_persistent="static_metadata",
        display_name=module.display_name,
        metadata={
            "family_id": SUITE_MODULE_OBJECT_KIND,
            "module_id": module.module_id,
            "suite_id": module.suite_id,
            "area_id": module.area_id,
            "lifecycle_status": _value(module.lifecycle_status),
            "object_family_ids": module.object_family_ids,
            "command_ids": module.command_ids,
            "query_ids": module.query_ids,
            "required_permissions": module.required_permissions,
            "audit_categories": module.audit_categories,
            "object_map_section_id": module.object_map_section_id,
            "docs_refs": module.docs_refs,
            "test_refs": module.test_refs,
            "warnings": module.warnings,
            "blockers": module.blockers,
            "read_only": True,
        },
        permission_refs=module.required_permissions,
        source_refs=(module.owner_component,),
        extra={"descriptor_type": "SuiteModuleDescriptor", "mutation_forbidden": True},
    )


def suite_command_trace_summary_from_descriptor(
    command: SuiteCommandDescriptor,
    *,
    areas: Iterable[AreaDescriptor] = (),
    suites: Iterable[SuiteDescriptor] = (),
    modules: Iterable[SuiteModuleDescriptor] = (),
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a command descriptor."""

    ref = suite_command_trace_ref_from_descriptor(
        command,
        areas=areas,
        suites=suites,
        modules=modules,
    )
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="declared",
        runtime_or_persistent="static_metadata",
        display_name=command.label,
        metadata={
            "family_id": SUITE_COMMAND_OBJECT_KIND,
            "command_id": command.command_id,
            "suite_id": command.suite_id,
            "area_id": command.area_id,
            "module_id": command.module_id,
            "command_kind": _value(command.command_kind),
            "required_permission": command.required_permission,
            "creates_operation": command.creates_operation,
            "expected_task_behavior": _value(command.expected_task_behavior),
            "cancellable": command.cancellable,
            "audit_category": command.audit_category,
            "runtime_policy": _value(command.runtime_policy),
            "input_schema_ref": command.input_schema_ref,
            "result_schema_ref": command.result_schema_ref,
            "progress_schema_ref": command.progress_schema_ref,
            "related_action_ids": command.related_action_ids,
            "object_family_ids": command.object_family_ids,
            "allowed_callers": command.allowed_callers,
            "docs_refs": command.docs_refs,
            "test_refs": command.test_refs,
            "warnings": command.warnings,
            "blockers": command.blockers,
            "read_only": True,
        },
        permission_refs=(command.required_permission,),
        source_refs=(ref.owner_component or "SuiteCommandDescriptor",),
        extra={"descriptor_type": "SuiteCommandDescriptor", "mutation_forbidden": True},
    )


def suite_query_trace_summary_from_descriptor(
    query: SuiteQueryDescriptor,
    *,
    areas: Iterable[AreaDescriptor] = (),
    suites: Iterable[SuiteDescriptor] = (),
    modules: Iterable[SuiteModuleDescriptor] = (),
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a query descriptor."""

    ref = suite_query_trace_ref_from_descriptor(
        query,
        areas=areas,
        suites=suites,
        modules=modules,
    )
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="declared",
        runtime_or_persistent="static_metadata",
        display_name=query.label,
        metadata={
            "family_id": SUITE_QUERY_OBJECT_KIND,
            "query_id": query.query_id,
            "suite_id": query.suite_id,
            "area_id": query.area_id,
            "module_id": query.module_id,
            "query_kind": _value(query.query_kind),
            "required_permission": query.required_permission,
            "read_model_kind": query.read_model_kind,
            "input_schema_ref": query.input_schema_ref,
            "result_schema_ref": query.result_schema_ref,
            "object_family_ids": query.object_family_ids,
            "cache_policy": _value(query.cache_policy),
            "audit_policy": _value(query.audit_policy),
            "allowed_callers": query.allowed_callers,
            "docs_refs": query.docs_refs,
            "test_refs": query.test_refs,
            "warnings": query.warnings,
            "blockers": query.blockers,
            "read_only": True,
        },
        permission_refs=(query.required_permission,),
        source_refs=(ref.owner_component or "SuiteQueryDescriptor",),
        extra={"descriptor_type": "SuiteQueryDescriptor", "mutation_forbidden": True},
    )


def suite_boundary_relationships_from_descriptors(
    *,
    areas: Iterable[AreaDescriptor] = (),
    suites: Iterable[SuiteDescriptor] = (),
    modules: Iterable[SuiteModuleDescriptor] = (),
    commands: Iterable[SuiteCommandDescriptor] = (),
    queries: Iterable[SuiteQueryDescriptor] = (),
) -> tuple[TraceableRelationshipRef, ...]:
    """Build descriptor relationships from explicit suite boundary descriptors."""

    normalized = _normalize_inputs(
        areas=areas,
        suites=suites,
        modules=modules,
        commands=commands,
        queries=queries,
    )
    relationships: list[TraceableRelationshipRef] = []

    for suite in normalized.suites:
        suite_ref = suite_trace_ref_from_descriptor(suite)
        for area_id in suite.area_ids:
            area = normalized.area_by_id.get(area_id)
            if area is not None:
                _append_reference(
                    relationships,
                    suite_ref,
                    area_trace_ref_from_descriptor(area),
                )
        for module_id in suite.module_ids:
            module = normalized.module_by_id.get(module_id)
            if module is not None:
                _append_reference(
                    relationships,
                    suite_ref,
                    suite_module_trace_ref_from_descriptor(module),
                )
        for command_id in suite.supported_command_ids:
            command = normalized.command_by_id.get(command_id)
            if command is not None:
                _append_reference(
                    relationships,
                    suite_ref,
                    suite_command_trace_ref_from_descriptor(
                        command,
                        areas=normalized.areas,
                        suites=normalized.suites,
                        modules=normalized.modules,
                    ),
                )
        for query_id in suite.supported_query_ids:
            query = normalized.query_by_id.get(query_id)
            if query is not None:
                _append_reference(
                    relationships,
                    suite_ref,
                    suite_query_trace_ref_from_descriptor(
                        query,
                        areas=normalized.areas,
                        suites=normalized.suites,
                        modules=normalized.modules,
                    ),
                )
        _append_descriptor_permission_relationships(
            relationships,
            suite_ref,
            suite.required_permissions,
        )
        _append_object_family_relationships(
            relationships,
            suite_ref,
            suite.object_family_ids,
        )

    for area in normalized.areas:
        area_ref = area_trace_ref_from_descriptor(area)
        if area.suite_id is not None:
            suite = normalized.suite_by_id.get(area.suite_id)
            if suite is not None:
                _append_reference(
                    relationships,
                    area_ref,
                    suite_trace_ref_from_descriptor(suite),
                )
        for module_id in area.module_ids:
            module = normalized.module_by_id.get(module_id)
            if module is not None:
                _append_reference(
                    relationships,
                    area_ref,
                    suite_module_trace_ref_from_descriptor(module),
                )
        for command_id in area.command_ids:
            command = normalized.command_by_id.get(command_id)
            if command is not None:
                _append_reference(
                    relationships,
                    area_ref,
                    suite_command_trace_ref_from_descriptor(
                        command,
                        areas=normalized.areas,
                        suites=normalized.suites,
                        modules=normalized.modules,
                    ),
                )
        for query_id in area.query_ids:
            query = normalized.query_by_id.get(query_id)
            if query is not None:
                _append_reference(
                    relationships,
                    area_ref,
                    suite_query_trace_ref_from_descriptor(
                        query,
                        areas=normalized.areas,
                        suites=normalized.suites,
                        modules=normalized.modules,
                    ),
                )
        _append_descriptor_permission_relationships(
            relationships,
            area_ref,
            area.required_permissions,
        )
        _append_object_family_relationships(
            relationships,
            area_ref,
            area.object_family_ids,
        )

    for module in normalized.modules:
        module_ref = suite_module_trace_ref_from_descriptor(module)
        if module.suite_id is not None:
            suite = normalized.suite_by_id.get(module.suite_id)
            if suite is not None:
                _append_reference(
                    relationships,
                    module_ref,
                    suite_trace_ref_from_descriptor(suite),
                )
        if module.area_id is not None:
            area = normalized.area_by_id.get(module.area_id)
            if area is not None:
                _append_reference(
                    relationships,
                    module_ref,
                    area_trace_ref_from_descriptor(area),
                )
        for command_id in module.command_ids:
            command = normalized.command_by_id.get(command_id)
            if command is not None:
                _append_reference(
                    relationships,
                    module_ref,
                    suite_command_trace_ref_from_descriptor(
                        command,
                        areas=normalized.areas,
                        suites=normalized.suites,
                        modules=normalized.modules,
                    ),
                )
        for query_id in module.query_ids:
            query = normalized.query_by_id.get(query_id)
            if query is not None:
                _append_reference(
                    relationships,
                    module_ref,
                    suite_query_trace_ref_from_descriptor(
                        query,
                        areas=normalized.areas,
                        suites=normalized.suites,
                        modules=normalized.modules,
                    ),
                )
        _append_descriptor_permission_relationships(
            relationships,
            module_ref,
            module.required_permissions,
        )
        _append_object_family_relationships(
            relationships,
            module_ref,
            module.object_family_ids,
        )

    for command in normalized.commands:
        command_ref = suite_command_trace_ref_from_descriptor(
            command,
            areas=normalized.areas,
            suites=normalized.suites,
            modules=normalized.modules,
        )
        _append_owner_references(
            relationships,
            command_ref,
            suite_id=command.suite_id,
            area_id=command.area_id,
            module_id=command.module_id,
            normalized=normalized,
        )
        _append_descriptor_permission_relationships(
            relationships,
            command_ref,
            (command.required_permission,),
        )
        _append_object_family_relationships(
            relationships,
            command_ref,
            command.object_family_ids,
        )
        for action_id in command.related_action_ids:
            _append_reference(
                relationships,
                command_ref,
                TraceableObjectRef(
                    object_id=action_id,
                    object_kind=ACTION_OBJECT_KIND,
                    owner_domain="gui",
                    owner_component="ActionRegistry",
                    label=action_id,
                    metadata={"family_id": ACTION_OBJECT_KIND},
                ),
            )

    for query in normalized.queries:
        query_ref = suite_query_trace_ref_from_descriptor(
            query,
            areas=normalized.areas,
            suites=normalized.suites,
            modules=normalized.modules,
        )
        _append_owner_references(
            relationships,
            query_ref,
            suite_id=query.suite_id,
            area_id=query.area_id,
            module_id=query.module_id,
            normalized=normalized,
        )
        _append_descriptor_permission_relationships(
            relationships,
            query_ref,
            (query.required_permission,),
        )
        _append_object_family_relationships(
            relationships,
            query_ref,
            query.object_family_ids,
        )

    return _dedupe_relationships(relationships)


def build_suite_boundary_trace_section(
    *,
    areas: Iterable[AreaDescriptor] = (),
    suites: Iterable[SuiteDescriptor] = (),
    modules: Iterable[SuiteModuleDescriptor] = (),
    commands: Iterable[SuiteCommandDescriptor] = (),
    queries: Iterable[SuiteQueryDescriptor] = (),
) -> ObjectMapSection:
    """Build a read-only Object Map section from explicit descriptors."""

    normalized = _normalize_inputs(
        areas=areas,
        suites=suites,
        modules=modules,
        commands=commands,
        queries=queries,
    )
    summaries = (
        *(area_trace_summary_from_descriptor(area) for area in normalized.areas),
        *(suite_trace_summary_from_descriptor(suite) for suite in normalized.suites),
        *(
            suite_module_trace_summary_from_descriptor(module)
            for module in normalized.modules
        ),
        *(
            suite_command_trace_summary_from_descriptor(
                command,
                areas=normalized.areas,
                suites=normalized.suites,
                modules=normalized.modules,
            )
            for command in normalized.commands
        ),
        *(
            suite_query_trace_summary_from_descriptor(
                query,
                areas=normalized.areas,
                suites=normalized.suites,
                modules=normalized.modules,
            )
            for query in normalized.queries
        ),
    )
    relationships = suite_boundary_relationships_from_descriptors(
        areas=normalized.areas,
        suites=normalized.suites,
        modules=normalized.modules,
        commands=normalized.commands,
        queries=normalized.queries,
    )
    warnings = (
        _FAMILY_LEGEND_WARNING,
        *_descriptor_warnings(normalized),
        *_missing_reference_warnings(normalized),
    )
    blockers = _descriptor_blockers(normalized)
    definitions = (
        *object_relationship_definitions_by_type("references"),
        *object_relationship_definitions_by_type("has_permission"),
    )
    return ObjectMapSection(
        section_id=SUITE_BOUNDARY_TRACE_SECTION_ID,
        provider_id=SUITE_BOUNDARY_TRACE_PROVIDER_ID,
        owner_domain="core",
        title="Suite Boundary Descriptors",
        summaries=summaries,
        relationships=relationships,
        relationship_definitions=definitions,
        warnings=warnings,
        blockers=blockers,
        metadata={
            "area_count": len(normalized.areas),
            "suite_count": len(normalized.suites),
            "module_count": len(normalized.modules),
            "command_count": len(normalized.commands),
            "query_count": len(normalized.queries),
            "relationship_count": len(relationships),
            "descriptor_source": "explicit_descriptor_inputs",
            "read_only": True,
        },
        extra={
            "mutation_forbidden": True,
            "interrogation": "future",
            "formal_family_legends": "future",
        },
    )


class _Owner:
    def __init__(self, owner_domain: str, owner_component: str) -> None:
        self.owner_domain = owner_domain
        self.owner_component = owner_component


class _Inputs:
    def __init__(
        self,
        *,
        areas: tuple[AreaDescriptor, ...],
        suites: tuple[SuiteDescriptor, ...],
        modules: tuple[SuiteModuleDescriptor, ...],
        commands: tuple[SuiteCommandDescriptor, ...],
        queries: tuple[SuiteQueryDescriptor, ...],
    ) -> None:
        self.areas = areas
        self.suites = suites
        self.modules = modules
        self.commands = commands
        self.queries = queries
        self.area_by_id = {area.area_id: area for area in areas}
        self.suite_by_id = {suite.suite_id: suite for suite in suites}
        self.module_by_id = {module.module_id: module for module in modules}
        self.command_by_id = {command.command_id: command for command in commands}
        self.query_by_id = {query.query_id: query for query in queries}


def _normalize_inputs(
    *,
    areas: Iterable[AreaDescriptor],
    suites: Iterable[SuiteDescriptor],
    modules: Iterable[SuiteModuleDescriptor],
    commands: Iterable[SuiteCommandDescriptor],
    queries: Iterable[SuiteQueryDescriptor],
) -> _Inputs:
    normalized_areas = _normalize_tuple(areas, AreaDescriptor, "areas")
    normalized_suites = _normalize_tuple(suites, SuiteDescriptor, "suites")
    normalized_modules = _normalize_tuple(modules, SuiteModuleDescriptor, "modules")
    normalized_commands = _normalize_tuple(commands, SuiteCommandDescriptor, "commands")
    normalized_queries = _normalize_tuple(queries, SuiteQueryDescriptor, "queries")
    return _Inputs(
        areas=normalized_areas,
        suites=normalized_suites,
        modules=normalized_modules,
        commands=normalized_commands,
        queries=normalized_queries,
    )


def _normalize_tuple(
    values: Iterable[object],
    expected_type: type[object],
    field_name: str,
) -> tuple[object, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an iterable of {expected_type.__name__}")
    normalized = tuple(values)
    for value in normalized:
        _require_type(value, expected_type, f"{field_name} entry")
    return normalized


def _require_type(value: object, expected_type: type[object], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be a {expected_type.__name__}")


def _resolve_command_query_owner(
    *,
    suite_id: str | None,
    area_id: str | None,
    module_id: str | None,
    areas: Iterable[AreaDescriptor],
    suites: Iterable[SuiteDescriptor],
    modules: Iterable[SuiteModuleDescriptor],
    fallback_component: str,
) -> _Owner:
    module_by_id = {module.module_id: module for module in modules}
    area_by_id = {area.area_id: area for area in areas}
    suite_by_id = {suite.suite_id: suite for suite in suites}
    if module_id is not None and module_id in module_by_id:
        module = module_by_id[module_id]
        return _Owner(module.owner_domain, module.owner_component)
    if area_id is not None and area_id in area_by_id:
        area = area_by_id[area_id]
        return _Owner(area.owner_domain, area.owner_component)
    if suite_id is not None and suite_id in suite_by_id:
        suite = suite_by_id[suite_id]
        return _Owner(suite.owner_domain, suite.owner_component)
    return _Owner("suite_boundary", fallback_component)


def _append_owner_references(
    relationships: list[TraceableRelationshipRef],
    source_ref: TraceableObjectRef,
    *,
    suite_id: str | None,
    area_id: str | None,
    module_id: str | None,
    normalized: _Inputs,
) -> None:
    if module_id is not None and module_id in normalized.module_by_id:
        _append_reference(
            relationships,
            source_ref,
            suite_module_trace_ref_from_descriptor(normalized.module_by_id[module_id]),
        )
    if area_id is not None and area_id in normalized.area_by_id:
        _append_reference(
            relationships,
            source_ref,
            area_trace_ref_from_descriptor(normalized.area_by_id[area_id]),
        )
    if suite_id is not None and suite_id in normalized.suite_by_id:
        _append_reference(
            relationships,
            source_ref,
            suite_trace_ref_from_descriptor(normalized.suite_by_id[suite_id]),
        )


def _append_descriptor_permission_relationships(
    relationships: list[TraceableRelationshipRef],
    source_ref: TraceableObjectRef,
    permissions: tuple[str, ...],
) -> None:
    for permission in permissions:
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


def _append_object_family_relationships(
    relationships: list[TraceableRelationshipRef],
    source_ref: TraceableObjectRef,
    family_ids: tuple[str, ...],
) -> None:
    for family_id in family_ids:
        _append_reference(
            relationships,
            source_ref,
            TraceableObjectRef(
                object_id=family_id,
                object_kind=OBJECT_FAMILY_OBJECT_KIND,
                owner_domain="contracts",
                owner_component="ObjectFamilyLegend",
                label=family_id,
                metadata={"family_id": family_id},
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
    return tuple(deduped.values())


def _descriptor_warnings(normalized: _Inputs) -> tuple[str, ...]:
    return tuple(
        f"{summary.object_ref.object_kind} {summary.object_ref.object_id}: {warning}"
        for summary in _all_descriptor_summaries(normalized)
        for warning in _string_tuple(summary.metadata.get("warnings"))
    )


def _descriptor_blockers(normalized: _Inputs) -> tuple[str, ...]:
    return tuple(
        f"{summary.object_ref.object_kind} {summary.object_ref.object_id}: {blocker}"
        for summary in _all_descriptor_summaries(normalized)
        for blocker in _string_tuple(summary.metadata.get("blockers"))
    )


def _all_descriptor_summaries(normalized: _Inputs) -> tuple[TraceableObjectSummary, ...]:
    return (
        *(area_trace_summary_from_descriptor(area) for area in normalized.areas),
        *(suite_trace_summary_from_descriptor(suite) for suite in normalized.suites),
        *(
            suite_module_trace_summary_from_descriptor(module)
            for module in normalized.modules
        ),
        *(
            suite_command_trace_summary_from_descriptor(
                command,
                areas=normalized.areas,
                suites=normalized.suites,
                modules=normalized.modules,
            )
            for command in normalized.commands
        ),
        *(
            suite_query_trace_summary_from_descriptor(
                query,
                areas=normalized.areas,
                suites=normalized.suites,
                modules=normalized.modules,
            )
            for query in normalized.queries
        ),
    )


def _missing_reference_warnings(normalized: _Inputs) -> tuple[str, ...]:
    warnings: list[str] = []
    for suite in normalized.suites:
        warnings.extend(
            _missing_refs(
                source=f"suite {suite.suite_id}",
                field_name="area_ids",
                ids=suite.area_ids,
                known=normalized.area_by_id,
            )
        )
        warnings.extend(
            _missing_refs(
                source=f"suite {suite.suite_id}",
                field_name="module_ids",
                ids=suite.module_ids,
                known=normalized.module_by_id,
            )
        )
        warnings.extend(
            _missing_refs(
                source=f"suite {suite.suite_id}",
                field_name="supported_command_ids",
                ids=suite.supported_command_ids,
                known=normalized.command_by_id,
            )
        )
        warnings.extend(
            _missing_refs(
                source=f"suite {suite.suite_id}",
                field_name="supported_query_ids",
                ids=suite.supported_query_ids,
                known=normalized.query_by_id,
            )
        )
    for area in normalized.areas:
        warnings.extend(
            _missing_refs(
                source=f"area {area.area_id}",
                field_name="module_ids",
                ids=area.module_ids,
                known=normalized.module_by_id,
            )
        )
        warnings.extend(
            _missing_refs(
                source=f"area {area.area_id}",
                field_name="command_ids",
                ids=area.command_ids,
                known=normalized.command_by_id,
            )
        )
        warnings.extend(
            _missing_refs(
                source=f"area {area.area_id}",
                field_name="query_ids",
                ids=area.query_ids,
                known=normalized.query_by_id,
            )
        )
    for module in normalized.modules:
        warnings.extend(
            _missing_refs(
                source=f"module {module.module_id}",
                field_name="command_ids",
                ids=module.command_ids,
                known=normalized.command_by_id,
            )
        )
        warnings.extend(
            _missing_refs(
                source=f"module {module.module_id}",
                field_name="query_ids",
                ids=module.query_ids,
                known=normalized.query_by_id,
            )
        )
    return tuple(warnings)


def _missing_refs(
    *,
    source: str,
    field_name: str,
    ids: tuple[str, ...],
    known: Mapping[str, object],
) -> tuple[str, ...]:
    return tuple(
        f"{source} references missing {field_name} entry: {value}"
        for value in ids
        if value not in known
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = [
    "AREA_OBJECT_KIND",
    "OBJECT_FAMILY_OBJECT_KIND",
    "PERMISSION_OBJECT_KIND",
    "SUITE_BOUNDARY_TRACE_PROVIDER_ID",
    "SUITE_BOUNDARY_TRACE_SECTION_ID",
    "SUITE_COMMAND_OBJECT_KIND",
    "SUITE_MODULE_OBJECT_KIND",
    "SUITE_OBJECT_KIND",
    "SUITE_QUERY_OBJECT_KIND",
    "area_trace_ref_from_descriptor",
    "area_trace_summary_from_descriptor",
    "build_suite_boundary_trace_provider_descriptor",
    "build_suite_boundary_trace_section",
    "suite_boundary_relationships_from_descriptors",
    "suite_command_trace_ref_from_descriptor",
    "suite_command_trace_summary_from_descriptor",
    "suite_module_trace_ref_from_descriptor",
    "suite_module_trace_summary_from_descriptor",
    "suite_query_trace_ref_from_descriptor",
    "suite_query_trace_summary_from_descriptor",
    "suite_trace_ref_from_descriptor",
    "suite_trace_summary_from_descriptor",
]
