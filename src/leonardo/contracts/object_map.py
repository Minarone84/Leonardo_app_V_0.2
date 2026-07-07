"""Read-only Object Map protocol contracts for Leonardo V2.

The contracts in this module define report, query, and provider descriptor
shapes for a future Object Map. They are data contracts only. They do not
implement a live Object Map service, register providers, discover objects, query
runtime services, mutate state, or call domain services.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from leonardo.contracts.object_relationships import ObjectRelationshipDefinition
from leonardo.contracts.traceable_object import (
    ObjectFamilyLegend,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


@dataclass(frozen=True)
class ObjectMapProviderDescriptor:
    """
    Static descriptor for a future read-only Object Map provider.

    The descriptor identifies which owner may later expose object summaries,
    legends, relationship references, and relationship definitions. It is not a
    provider implementation and does not grant mutation authority.
    """

    provider_id: str
    owner_domain: str
    owner_component: str
    provider_name: str | None = None
    object_kinds: tuple[str, ...] = ()
    family_ids: tuple[str, ...] = ()
    relationship_types: tuple[str, ...] = ()
    supports_summary_listing: bool = True
    supports_interrogation: bool = True
    supports_relationship_listing: bool = True
    runtime_or_persistent: str = "runtime"
    read_only: bool = True
    mutation_forbidden: bool = True
    related_contracts: tuple[str, ...] = ()
    related_docs: tuple[str, ...] = ()
    related_tests: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.provider_id, "provider_id")
        _validate_non_empty_string(self.owner_domain, "owner_domain")
        _validate_non_empty_string(self.owner_component, "owner_component")
        _optional_string(self.provider_name, "provider_name")
        _validate_non_empty_string(self.runtime_or_persistent, "runtime_or_persistent")
        for field_name in (
            "object_kinds",
            "family_ids",
            "relationship_types",
            "related_contracts",
            "related_docs",
            "related_tests",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        if not self.object_kinds and not self.family_ids:
            raise ValueError("object_kinds or family_ids must identify provider scope")
        for field_name in (
            "supports_summary_listing",
            "supports_interrogation",
            "supports_relationship_listing",
            "read_only",
            "mutation_forbidden",
        ):
            _validate_bool(getattr(self, field_name), field_name)
        if self.read_only is not True:
            raise ValueError("read_only must be True for Object Map descriptors")
        if self.mutation_forbidden is not True:
            raise ValueError(
                "mutation_forbidden must be True for Object Map descriptors"
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_mapping(self.metadata, "metadata"),
        )
        object.__setattr__(self, "extra", _readonly_mapping(self.extra, "extra"))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this provider descriptor."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "owner_domain": self.owner_domain,
            "owner_component": self.owner_component,
            "object_kinds": list(self.object_kinds),
            "family_ids": list(self.family_ids),
            "relationship_types": list(self.relationship_types),
            "supports_summary_listing": self.supports_summary_listing,
            "supports_interrogation": self.supports_interrogation,
            "supports_relationship_listing": self.supports_relationship_listing,
            "runtime_or_persistent": self.runtime_or_persistent,
            "read_only": self.read_only,
            "mutation_forbidden": self.mutation_forbidden,
            "related_contracts": list(self.related_contracts),
            "related_docs": list(self.related_docs),
            "related_tests": list(self.related_tests),
            "metadata": _plain_value(self.metadata),
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectMapProviderDescriptor:
        """Build a provider descriptor from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            provider_id=_required_string(data, "provider_id"),
            provider_name=_optional_string(data.get("provider_name"), "provider_name"),
            owner_domain=_required_string(data, "owner_domain"),
            owner_component=_required_string(data, "owner_component"),
            object_kinds=_string_tuple_from_data(data.get("object_kinds"), "object_kinds"),
            family_ids=_string_tuple_from_data(data.get("family_ids"), "family_ids"),
            relationship_types=_string_tuple_from_data(
                data.get("relationship_types"),
                "relationship_types",
            ),
            supports_summary_listing=_bool_from_data(
                data,
                "supports_summary_listing",
                True,
            ),
            supports_interrogation=_bool_from_data(
                data,
                "supports_interrogation",
                True,
            ),
            supports_relationship_listing=_bool_from_data(
                data,
                "supports_relationship_listing",
                True,
            ),
            runtime_or_persistent=_optional_string(
                data.get("runtime_or_persistent"),
                "runtime_or_persistent",
            )
            or "runtime",
            read_only=_bool_from_data(data, "read_only", True),
            mutation_forbidden=_bool_from_data(data, "mutation_forbidden", True),
            related_contracts=_string_tuple_from_data(
                data.get("related_contracts"),
                "related_contracts",
            ),
            related_docs=_string_tuple_from_data(data.get("related_docs"), "related_docs"),
            related_tests=_string_tuple_from_data(
                data.get("related_tests"),
                "related_tests",
            ),
            metadata=_mapping_or_empty(data.get("metadata"), "metadata"),
            extra=_mapping_or_empty(data.get("extra"), "extra"),
        )


@dataclass(frozen=True)
class ObjectMapSection:
    """
    Read-only report section emitted by a future object-family owner.

    Sections aggregate owner-emitted summaries and descriptor references. They
    are display/query output and do not own object truth.
    """

    section_id: str
    provider_id: str
    owner_domain: str
    object_kind: str | None = None
    family_id: str | None = None
    title: str | None = None
    summaries: tuple[TraceableObjectSummary | Mapping[str, object], ...] = ()
    relationships: tuple[TraceableRelationshipRef | Mapping[str, object], ...] = ()
    legends: tuple[ObjectFamilyLegend | Mapping[str, object], ...] = ()
    relationship_definitions: tuple[
        ObjectRelationshipDefinition | Mapping[str, object],
        ...,
    ] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.section_id, "section_id")
        _validate_non_empty_string(self.provider_id, "provider_id")
        _validate_non_empty_string(self.owner_domain, "owner_domain")
        for field_name in ("object_kind", "family_id", "title"):
            _optional_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "summaries",
            _normalize_summary_tuple(self.summaries, "summaries"),
        )
        object.__setattr__(
            self,
            "relationships",
            _normalize_relationship_tuple(self.relationships, "relationships"),
        )
        object.__setattr__(
            self,
            "legends",
            _normalize_legend_tuple(self.legends, "legends"),
        )
        object.__setattr__(
            self,
            "relationship_definitions",
            _normalize_definition_tuple(
                self.relationship_definitions,
                "relationship_definitions",
            ),
        )
        for field_name in ("warnings", "blockers", "errors"):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_mapping(self.metadata, "metadata"),
        )
        object.__setattr__(self, "extra", _readonly_mapping(self.extra, "extra"))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this Object Map section."""

        return {
            "section_id": self.section_id,
            "provider_id": self.provider_id,
            "owner_domain": self.owner_domain,
            "object_kind": self.object_kind,
            "family_id": self.family_id,
            "title": self.title,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
            "legends": [legend.to_dict() for legend in self.legends],
            "relationship_definitions": [
                definition.to_dict()
                for definition in self.relationship_definitions
            ],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
            "metadata": _plain_value(self.metadata),
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectMapSection:
        """Build an Object Map section from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            section_id=_required_string(data, "section_id"),
            provider_id=_required_string(data, "provider_id"),
            owner_domain=_required_string(data, "owner_domain"),
            object_kind=_optional_string(data.get("object_kind"), "object_kind"),
            family_id=_optional_string(data.get("family_id"), "family_id"),
            title=_optional_string(data.get("title"), "title"),
            summaries=_summary_tuple_from_data(data.get("summaries"), "summaries"),
            relationships=_relationship_tuple_from_data(
                data.get("relationships"),
                "relationships",
            ),
            legends=_legend_tuple_from_data(data.get("legends"), "legends"),
            relationship_definitions=_definition_tuple_from_data(
                data.get("relationship_definitions"),
                "relationship_definitions",
            ),
            warnings=_string_tuple_from_data(data.get("warnings"), "warnings"),
            blockers=_string_tuple_from_data(data.get("blockers"), "blockers"),
            errors=_string_tuple_from_data(data.get("errors"), "errors"),
            metadata=_mapping_or_empty(data.get("metadata"), "metadata"),
            extra=_mapping_or_empty(data.get("extra"), "extra"),
        )


@dataclass(frozen=True)
class ObjectMapSnapshot:
    """
    Read-only aggregate of future Object Map report sections.

    Snapshots combine provider descriptors and provider-emitted sections. A
    snapshot owns no object truth and performs no discovery.
    """

    snapshot_id: str
    schema_version: str = "1.0"
    generated_at_utc: str | None = None
    sections: tuple[ObjectMapSection | Mapping[str, object], ...] = ()
    provider_descriptors: tuple[
        ObjectMapProviderDescriptor | Mapping[str, object],
        ...,
    ] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.snapshot_id, "snapshot_id")
        _validate_non_empty_string(self.schema_version, "schema_version")
        _optional_string(self.generated_at_utc, "generated_at_utc")
        object.__setattr__(
            self,
            "sections",
            _normalize_section_tuple(self.sections, "sections"),
        )
        object.__setattr__(
            self,
            "provider_descriptors",
            _normalize_provider_descriptor_tuple(
                self.provider_descriptors,
                "provider_descriptors",
            ),
        )
        for field_name in ("warnings", "blockers", "errors"):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_mapping(self.metadata, "metadata"),
        )
        object.__setattr__(self, "extra", _readonly_mapping(self.extra, "extra"))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this Object Map snapshot."""

        return {
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "generated_at_utc": self.generated_at_utc,
            "sections": [section.to_dict() for section in self.sections],
            "provider_descriptors": [
                descriptor.to_dict() for descriptor in self.provider_descriptors
            ],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
            "metadata": _plain_value(self.metadata),
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectMapSnapshot:
        """Build an Object Map snapshot from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            snapshot_id=_required_string(data, "snapshot_id"),
            schema_version=_optional_string(data.get("schema_version"), "schema_version")
            or "1.0",
            generated_at_utc=_optional_string(
                data.get("generated_at_utc"),
                "generated_at_utc",
            ),
            sections=_section_tuple_from_data(data.get("sections"), "sections"),
            provider_descriptors=_provider_descriptor_tuple_from_data(
                data.get("provider_descriptors"),
                "provider_descriptors",
            ),
            warnings=_string_tuple_from_data(data.get("warnings"), "warnings"),
            blockers=_string_tuple_from_data(data.get("blockers"), "blockers"),
            errors=_string_tuple_from_data(data.get("errors"), "errors"),
            metadata=_mapping_or_empty(data.get("metadata"), "metadata"),
            extra=_mapping_or_empty(data.get("extra"), "extra"),
        )


@dataclass(frozen=True)
class ObjectMapQuery:
    """
    Read-only query shape for a future Object Map.

    The query selects desired report material. It does not execute commands,
    bypass permissions, discover providers, or mutate objects.
    """

    object_kind: str | None = None
    family_id: str | None = None
    object_id: str | None = None
    owner_domain: str | None = None
    provider_id: str | None = None
    relationship_type: str | None = None
    include_summaries: bool = True
    include_relationships: bool = True
    include_legends: bool = True
    include_relationship_definitions: bool = True
    include_provider_descriptors: bool = True
    include_docs: bool = True
    include_tests: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "object_kind",
            "family_id",
            "object_id",
            "owner_domain",
            "provider_id",
            "relationship_type",
        ):
            _optional_string(getattr(self, field_name), field_name)
        for field_name in (
            "include_summaries",
            "include_relationships",
            "include_legends",
            "include_relationship_definitions",
            "include_provider_descriptors",
            "include_docs",
            "include_tests",
        ):
            _validate_bool(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "metadata",
            _readonly_mapping(self.metadata, "metadata"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this Object Map query."""

        return {
            "object_kind": self.object_kind,
            "family_id": self.family_id,
            "object_id": self.object_id,
            "owner_domain": self.owner_domain,
            "provider_id": self.provider_id,
            "relationship_type": self.relationship_type,
            "include_summaries": self.include_summaries,
            "include_relationships": self.include_relationships,
            "include_legends": self.include_legends,
            "include_relationship_definitions": self.include_relationship_definitions,
            "include_provider_descriptors": self.include_provider_descriptors,
            "include_docs": self.include_docs,
            "include_tests": self.include_tests,
            "metadata": _plain_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectMapQuery:
        """Build an Object Map query from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            object_kind=_optional_string(data.get("object_kind"), "object_kind"),
            family_id=_optional_string(data.get("family_id"), "family_id"),
            object_id=_optional_string(data.get("object_id"), "object_id"),
            owner_domain=_optional_string(data.get("owner_domain"), "owner_domain"),
            provider_id=_optional_string(data.get("provider_id"), "provider_id"),
            relationship_type=_optional_string(
                data.get("relationship_type"),
                "relationship_type",
            ),
            include_summaries=_bool_from_data(data, "include_summaries", True),
            include_relationships=_bool_from_data(
                data,
                "include_relationships",
                True,
            ),
            include_legends=_bool_from_data(data, "include_legends", True),
            include_relationship_definitions=_bool_from_data(
                data,
                "include_relationship_definitions",
                True,
            ),
            include_provider_descriptors=_bool_from_data(
                data,
                "include_provider_descriptors",
                True,
            ),
            include_docs=_bool_from_data(data, "include_docs", True),
            include_tests=_bool_from_data(data, "include_tests", True),
            metadata=_mapping_or_empty(data.get("metadata"), "metadata"),
        )


@dataclass(frozen=True)
class ObjectMapQueryReport:
    """
    Read-only result shape for a future Object Map query.

    Query reports collect owner-emitted read models and descriptors. They do not
    become the truth source for any object family.
    """

    query: ObjectMapQuery | Mapping[str, object]
    sections: tuple[ObjectMapSection | Mapping[str, object], ...] = ()
    summaries: tuple[TraceableObjectSummary | Mapping[str, object], ...] = ()
    relationships: tuple[TraceableRelationshipRef | Mapping[str, object], ...] = ()
    legends: tuple[ObjectFamilyLegend | Mapping[str, object], ...] = ()
    relationship_definitions: tuple[
        ObjectRelationshipDefinition | Mapping[str, object],
        ...,
    ] = ()
    provider_descriptors: tuple[
        ObjectMapProviderDescriptor | Mapping[str, object],
        ...,
    ] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _normalize_query(self.query, "query"))
        object.__setattr__(
            self,
            "sections",
            _normalize_section_tuple(self.sections, "sections"),
        )
        object.__setattr__(
            self,
            "summaries",
            _normalize_summary_tuple(self.summaries, "summaries"),
        )
        object.__setattr__(
            self,
            "relationships",
            _normalize_relationship_tuple(self.relationships, "relationships"),
        )
        object.__setattr__(
            self,
            "legends",
            _normalize_legend_tuple(self.legends, "legends"),
        )
        object.__setattr__(
            self,
            "relationship_definitions",
            _normalize_definition_tuple(
                self.relationship_definitions,
                "relationship_definitions",
            ),
        )
        object.__setattr__(
            self,
            "provider_descriptors",
            _normalize_provider_descriptor_tuple(
                self.provider_descriptors,
                "provider_descriptors",
            ),
        )
        for field_name in ("warnings", "blockers", "errors"):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "metadata",
            _readonly_mapping(self.metadata, "metadata"),
        )
        object.__setattr__(self, "extra", _readonly_mapping(self.extra, "extra"))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this Object Map query report."""

        return {
            "query": self.query.to_dict(),
            "sections": [section.to_dict() for section in self.sections],
            "summaries": [summary.to_dict() for summary in self.summaries],
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
            "legends": [legend.to_dict() for legend in self.legends],
            "relationship_definitions": [
                definition.to_dict()
                for definition in self.relationship_definitions
            ],
            "provider_descriptors": [
                descriptor.to_dict() for descriptor in self.provider_descriptors
            ],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
            "metadata": _plain_value(self.metadata),
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectMapQueryReport:
        """Build an Object Map query report from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            query=_required_mapping(data, "query"),
            sections=_section_tuple_from_data(data.get("sections"), "sections"),
            summaries=_summary_tuple_from_data(data.get("summaries"), "summaries"),
            relationships=_relationship_tuple_from_data(
                data.get("relationships"),
                "relationships",
            ),
            legends=_legend_tuple_from_data(data.get("legends"), "legends"),
            relationship_definitions=_definition_tuple_from_data(
                data.get("relationship_definitions"),
                "relationship_definitions",
            ),
            provider_descriptors=_provider_descriptor_tuple_from_data(
                data.get("provider_descriptors"),
                "provider_descriptors",
            ),
            warnings=_string_tuple_from_data(data.get("warnings"), "warnings"),
            blockers=_string_tuple_from_data(data.get("blockers"), "blockers"),
            errors=_string_tuple_from_data(data.get("errors"), "errors"),
            metadata=_mapping_or_empty(data.get("metadata"), "metadata"),
            extra=_mapping_or_empty(data.get("extra"), "extra"),
        )


def _normalize_query(
    value: ObjectMapQuery | Mapping[str, object],
    field_name: str,
) -> ObjectMapQuery:
    if isinstance(value, ObjectMapQuery):
        return value
    if isinstance(value, Mapping):
        return ObjectMapQuery.from_dict(value)
    raise TypeError(f"{field_name} must be an ObjectMapQuery or mapping")


def _normalize_provider_descriptor_tuple(
    values: tuple[ObjectMapProviderDescriptor | Mapping[str, object], ...],
    field_name: str,
) -> tuple[ObjectMapProviderDescriptor, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of provider descriptors")
    return tuple(
        value
        if isinstance(value, ObjectMapProviderDescriptor)
        else ObjectMapProviderDescriptor.from_dict(_validate_mapping(value, field_name))
        for value in tuple(values)
    )


def _normalize_section_tuple(
    values: tuple[ObjectMapSection | Mapping[str, object], ...],
    field_name: str,
) -> tuple[ObjectMapSection, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of Object Map sections")
    return tuple(
        value
        if isinstance(value, ObjectMapSection)
        else ObjectMapSection.from_dict(_validate_mapping(value, field_name))
        for value in tuple(values)
    )


def _normalize_summary_tuple(
    values: tuple[TraceableObjectSummary | Mapping[str, object], ...],
    field_name: str,
) -> tuple[TraceableObjectSummary, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of object summaries")
    return tuple(
        value
        if isinstance(value, TraceableObjectSummary)
        else TraceableObjectSummary.from_dict(_validate_mapping(value, field_name))
        for value in tuple(values)
    )


def _normalize_relationship_tuple(
    values: tuple[TraceableRelationshipRef | Mapping[str, object], ...],
    field_name: str,
) -> tuple[TraceableRelationshipRef, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of relationship refs")
    return tuple(
        value
        if isinstance(value, TraceableRelationshipRef)
        else TraceableRelationshipRef.from_dict(_validate_mapping(value, field_name))
        for value in tuple(values)
    )


def _normalize_legend_tuple(
    values: tuple[ObjectFamilyLegend | Mapping[str, object], ...],
    field_name: str,
) -> tuple[ObjectFamilyLegend, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of object family legends")
    return tuple(
        value
        if isinstance(value, ObjectFamilyLegend)
        else ObjectFamilyLegend.from_dict(_validate_mapping(value, field_name))
        for value in tuple(values)
    )


def _normalize_definition_tuple(
    values: tuple[ObjectRelationshipDefinition | Mapping[str, object], ...],
    field_name: str,
) -> tuple[ObjectRelationshipDefinition, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of relationship definitions")
    return tuple(
        value
        if isinstance(value, ObjectRelationshipDefinition)
        else ObjectRelationshipDefinition.from_dict(
            _validate_mapping(value, field_name)
        )
        for value in tuple(values)
    )


def _provider_descriptor_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[ObjectMapProviderDescriptor | Mapping[str, object], ...]:
    return _tuple_from_data(value, field_name, "provider descriptors")


def _section_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[ObjectMapSection | Mapping[str, object], ...]:
    return _tuple_from_data(value, field_name, "Object Map sections")


def _summary_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[TraceableObjectSummary | Mapping[str, object], ...]:
    return _tuple_from_data(value, field_name, "object summaries")


def _relationship_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[TraceableRelationshipRef | Mapping[str, object], ...]:
    return _tuple_from_data(value, field_name, "relationship refs")


def _legend_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[ObjectFamilyLegend | Mapping[str, object], ...]:
    return _tuple_from_data(value, field_name, "object family legends")


def _definition_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[ObjectRelationshipDefinition | Mapping[str, object], ...]:
    return _tuple_from_data(value, field_name, "relationship definitions")


def _tuple_from_data(
    value: object,
    field_name: str,
    item_description: str,
) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a tuple of {item_description}")
    if not isinstance(value, tuple | list):
        raise TypeError(f"{field_name} must be a tuple of {item_description}")
    return tuple(value)


def _string_tuple_from_data(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    if not isinstance(value, tuple | list):
        raise TypeError(f"{field_name} must be a tuple of strings")
    return _normalize_string_tuple(tuple(value), field_name)


def _normalize_string_tuple(
    values: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    normalized = tuple(values)
    for item in normalized:
        _validate_non_empty_string(item, f"{field_name} entry")
    return normalized


def _bool_from_data(
    data: Mapping[str, object],
    field_name: str,
    default: bool,
) -> bool:
    value = data.get(field_name, default)
    _validate_bool(value, field_name)
    return value


def _validate_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")


def _required_string(data: Mapping[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _required_mapping(data: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    value = data.get(field_name)
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _mapping_or_empty(value: object, field_name: str) -> Mapping[str, object]:
    if value is None:
        return {}
    return _validate_mapping(value, field_name)


def _validate_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _readonly_mapping(
    value: Mapping[str, object],
    field_name: str,
) -> Mapping[str, object]:
    _validate_mapping(value, field_name)
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        normalized[key] = _readonly_value(item, field_name)
    return MappingProxyType(normalized)


def _readonly_value(value: object, field_name: str) -> object:
    if isinstance(value, Mapping):
        return _readonly_mapping(value, field_name)
    if isinstance(value, tuple | list):
        return tuple(_readonly_value(item, field_name) for item in value)
    return value


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain_value(item) for item in value]
    return value


__all__ = [
    "ObjectMapProviderDescriptor",
    "ObjectMapQuery",
    "ObjectMapQueryReport",
    "ObjectMapSection",
    "ObjectMapSnapshot",
]
