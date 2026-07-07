"""Traceable object vocabulary contracts for Leonardo V2.

The contracts in this module define shared identity, relationship, summary,
legend, and interrogation shapes for future traceable object read models. They
do not own runtime state, register providers, implement Object Map behavior, or
mutate domain objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from math import isfinite
from types import MappingProxyType


@dataclass(frozen=True)
class TraceableObjectRef:
    """
    Compact reference to one traceable object.

    The reference identifies an object and its owning domain without requiring a
    universal domain schema. Family-specific fields belong in metadata or in the
    owning family's legend.
    """

    object_id: str
    object_kind: str
    owner_domain: str
    owner_component: str | None = None
    schema_version: str | None = None
    label: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.object_id, "object_id")
        _validate_non_empty_string(self.object_kind, "object_kind")
        _validate_non_empty_string(self.owner_domain, "owner_domain")
        for field_name in ("owner_component", "schema_version", "label"):
            _optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this object reference."""

        return {
            "object_id": self.object_id,
            "object_kind": self.object_kind,
            "owner_domain": self.owner_domain,
            "owner_component": self.owner_component,
            "schema_version": self.schema_version,
            "label": self.label,
            "metadata": _plain_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TraceableObjectRef:
        """Build an object reference from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            object_id=_required_string(data, "object_id"),
            object_kind=_required_string(data, "object_kind"),
            owner_domain=_required_string(data, "owner_domain"),
            owner_component=_optional_string(data.get("owner_component"), "owner_component"),
            schema_version=_optional_string(data.get("schema_version"), "schema_version"),
            label=_optional_string(data.get("label"), "label"),
            metadata=_mapping_or_empty(data.get("metadata")),
        )


@dataclass(frozen=True)
class TraceableRelationshipRef:
    """
    Compact directed relationship between two traceable objects.

    Relationship references are read models. They describe lineage or runtime
    associations but do not imply ownership transfer or mutation authority.
    """

    relationship_type: str
    source_ref: TraceableObjectRef | Mapping[str, object]
    target_ref: TraceableObjectRef | Mapping[str, object]
    direction: str = "outbound"
    schema_version: str = "1.0"
    relationship_id: str | None = None
    lifecycle_status: str | None = None
    created_at_utc: str | None = None
    updated_at_utc: str | None = None
    operation_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.relationship_type, "relationship_type")
        object.__setattr__(
            self,
            "source_ref",
            _normalize_object_ref(self.source_ref, "source_ref"),
        )
        object.__setattr__(
            self,
            "target_ref",
            _normalize_object_ref(self.target_ref, "target_ref"),
        )
        _validate_non_empty_string(self.direction, "direction")
        _validate_non_empty_string(self.schema_version, "schema_version")
        for field_name in (
            "relationship_id",
            "lifecycle_status",
            "created_at_utc",
            "updated_at_utc",
            "operation_id",
            "task_id",
            "correlation_id",
        ):
            _optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this relationship reference."""

        return {
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type,
            "source_ref": self.source_ref.to_dict(),
            "target_ref": self.target_ref.to_dict(),
            "direction": self.direction,
            "schema_version": self.schema_version,
            "lifecycle_status": self.lifecycle_status,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "metadata": _plain_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TraceableRelationshipRef:
        """Build a relationship reference from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            relationship_id=_optional_string(data.get("relationship_id"), "relationship_id"),
            relationship_type=_required_string(data, "relationship_type"),
            source_ref=_required_mapping(data, "source_ref"),
            target_ref=_required_mapping(data, "target_ref"),
            direction=_optional_string(data.get("direction"), "direction") or "outbound",
            schema_version=_optional_string(data.get("schema_version"), "schema_version")
            or "1.0",
            lifecycle_status=_optional_string(data.get("lifecycle_status"), "lifecycle_status"),
            created_at_utc=_optional_string(data.get("created_at_utc"), "created_at_utc"),
            updated_at_utc=_optional_string(data.get("updated_at_utc"), "updated_at_utc"),
            operation_id=_optional_string(data.get("operation_id"), "operation_id"),
            task_id=_optional_string(data.get("task_id"), "task_id"),
            correlation_id=_optional_string(data.get("correlation_id"), "correlation_id"),
            metadata=_mapping_or_empty(data.get("metadata")),
        )


@dataclass(frozen=True)
class TraceableObjectSummary:
    """
    Common trace envelope emitted by the owner of one object.

    Object summaries describe identity, lifecycle, relationships, permissions,
    audit references, and correlation references. They are read models and must
    not be treated as mutation authority.
    """

    object_ref: TraceableObjectRef | Mapping[str, object]
    lifecycle_status: str
    runtime_or_persistent: str
    schema_version: str = "1.0"
    created_or_registered_at_utc: str | None = None
    updated_at_utc: str | None = None
    display_name: str | None = None
    metadata_ref: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    relationship_refs: tuple[TraceableRelationshipRef | Mapping[str, object], ...] = ()
    permission_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    operation_refs: tuple[str, ...] = ()
    task_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "object_ref",
            _normalize_object_ref(self.object_ref, "object_ref"),
        )
        _validate_non_empty_string(self.lifecycle_status, "lifecycle_status")
        _validate_non_empty_string(self.runtime_or_persistent, "runtime_or_persistent")
        _validate_non_empty_string(self.schema_version, "schema_version")
        for field_name in (
            "created_or_registered_at_utc",
            "updated_at_utc",
            "display_name",
            "metadata_ref",
        ):
            _optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))
        object.__setattr__(
            self,
            "relationship_refs",
            _normalize_relationship_tuple(
                self.relationship_refs,
                "relationship_refs",
            ),
        )
        for field_name in (
            "permission_refs",
            "audit_refs",
            "operation_refs",
            "task_refs",
            "source_refs",
            "correlation_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "extra", _readonly_mapping(self.extra))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this object summary."""

        return {
            "object_ref": self.object_ref.to_dict(),
            "lifecycle_status": self.lifecycle_status,
            "runtime_or_persistent": self.runtime_or_persistent,
            "schema_version": self.schema_version,
            "created_or_registered_at_utc": self.created_or_registered_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "display_name": self.display_name,
            "metadata_ref": self.metadata_ref,
            "metadata": _plain_value(self.metadata),
            "relationship_refs": [
                relationship.to_dict() for relationship in self.relationship_refs
            ],
            "permission_refs": list(self.permission_refs),
            "audit_refs": list(self.audit_refs),
            "operation_refs": list(self.operation_refs),
            "task_refs": list(self.task_refs),
            "source_refs": list(self.source_refs),
            "correlation_refs": list(self.correlation_refs),
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TraceableObjectSummary:
        """Build an object summary from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            object_ref=_required_mapping(data, "object_ref"),
            lifecycle_status=_required_string(data, "lifecycle_status"),
            runtime_or_persistent=_required_string(data, "runtime_or_persistent"),
            schema_version=_optional_string(data.get("schema_version"), "schema_version")
            or "1.0",
            created_or_registered_at_utc=_optional_string(
                data.get("created_or_registered_at_utc"),
                "created_or_registered_at_utc",
            ),
            updated_at_utc=_optional_string(data.get("updated_at_utc"), "updated_at_utc"),
            display_name=_optional_string(data.get("display_name"), "display_name"),
            metadata_ref=_optional_string(data.get("metadata_ref"), "metadata_ref"),
            metadata=_mapping_or_empty(data.get("metadata")),
            relationship_refs=_relationship_tuple_from_data(
                data.get("relationship_refs"),
                "relationship_refs",
            ),
            permission_refs=_string_tuple_from_data(data.get("permission_refs"), "permission_refs"),
            audit_refs=_string_tuple_from_data(data.get("audit_refs"), "audit_refs"),
            operation_refs=_string_tuple_from_data(data.get("operation_refs"), "operation_refs"),
            task_refs=_string_tuple_from_data(data.get("task_refs"), "task_refs"),
            source_refs=_string_tuple_from_data(data.get("source_refs"), "source_refs"),
            correlation_refs=_string_tuple_from_data(
                data.get("correlation_refs"),
                "correlation_refs",
            ),
            extra=_mapping_or_empty(data.get("extra")),
        )


@dataclass(frozen=True)
class ObjectFamilyLegend:
    """
    Ownership and interrogation contract for one object family.

    Legends define who mutates a family, who may read it, where truth lives, and
    which relationships, permissions, contracts, docs, and tests describe it.
    They do not define the full domain schema for the family.
    """

    family_id: str
    object_kind: str
    owner_domain: str
    owner_component: str
    mutation_owner: str
    read_provider: str
    runtime_or_persistent: str
    truth_source: str
    schema_version: str = "1.0"
    required_identity_fields: tuple[str, ...] = ()
    optional_identity_fields: tuple[str, ...] = ()
    metadata_fields: tuple[str, ...] = ()
    lifecycle_statuses: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    permission_refs: tuple[str, ...] = ()
    audit_event_types: tuple[str, ...] = ()
    relationships_in: tuple[str, ...] = ()
    relationships_out: tuple[str, ...] = ()
    related_contracts: tuple[str, ...] = ()
    related_docs: tuple[str, ...] = ()
    related_tests: tuple[str, ...] = ()
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "family_id",
            "object_kind",
            "owner_domain",
            "owner_component",
            "mutation_owner",
            "read_provider",
            "runtime_or_persistent",
            "truth_source",
            "schema_version",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "required_identity_fields",
            "optional_identity_fields",
            "metadata_fields",
            "lifecycle_statuses",
            "allowed_actions",
            "permission_refs",
            "audit_event_types",
            "relationships_in",
            "relationships_out",
            "related_contracts",
            "related_docs",
            "related_tests",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "extra", _readonly_mapping(self.extra))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this object family legend."""

        return {
            "family_id": self.family_id,
            "object_kind": self.object_kind,
            "owner_domain": self.owner_domain,
            "owner_component": self.owner_component,
            "mutation_owner": self.mutation_owner,
            "read_provider": self.read_provider,
            "runtime_or_persistent": self.runtime_or_persistent,
            "truth_source": self.truth_source,
            "schema_version": self.schema_version,
            "required_identity_fields": list(self.required_identity_fields),
            "optional_identity_fields": list(self.optional_identity_fields),
            "metadata_fields": list(self.metadata_fields),
            "lifecycle_statuses": list(self.lifecycle_statuses),
            "allowed_actions": list(self.allowed_actions),
            "permission_refs": list(self.permission_refs),
            "audit_event_types": list(self.audit_event_types),
            "relationships_in": list(self.relationships_in),
            "relationships_out": list(self.relationships_out),
            "related_contracts": list(self.related_contracts),
            "related_docs": list(self.related_docs),
            "related_tests": list(self.related_tests),
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectFamilyLegend:
        """Build an object family legend from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            family_id=_required_string(data, "family_id"),
            object_kind=_required_string(data, "object_kind"),
            owner_domain=_required_string(data, "owner_domain"),
            owner_component=_required_string(data, "owner_component"),
            mutation_owner=_required_string(data, "mutation_owner"),
            read_provider=_required_string(data, "read_provider"),
            runtime_or_persistent=_required_string(data, "runtime_or_persistent"),
            truth_source=_required_string(data, "truth_source"),
            schema_version=_optional_string(data.get("schema_version"), "schema_version")
            or "1.0",
            required_identity_fields=_string_tuple_from_data(
                data.get("required_identity_fields"),
                "required_identity_fields",
            ),
            optional_identity_fields=_string_tuple_from_data(
                data.get("optional_identity_fields"),
                "optional_identity_fields",
            ),
            metadata_fields=_string_tuple_from_data(data.get("metadata_fields"), "metadata_fields"),
            lifecycle_statuses=_string_tuple_from_data(
                data.get("lifecycle_statuses"),
                "lifecycle_statuses",
            ),
            allowed_actions=_string_tuple_from_data(data.get("allowed_actions"), "allowed_actions"),
            permission_refs=_string_tuple_from_data(data.get("permission_refs"), "permission_refs"),
            audit_event_types=_string_tuple_from_data(
                data.get("audit_event_types"),
                "audit_event_types",
            ),
            relationships_in=_string_tuple_from_data(
                data.get("relationships_in"),
                "relationships_in",
            ),
            relationships_out=_string_tuple_from_data(
                data.get("relationships_out"),
                "relationships_out",
            ),
            related_contracts=_string_tuple_from_data(
                data.get("related_contracts"),
                "related_contracts",
            ),
            related_docs=_string_tuple_from_data(data.get("related_docs"), "related_docs"),
            related_tests=_string_tuple_from_data(data.get("related_tests"), "related_tests"),
            extra=_mapping_or_empty(data.get("extra")),
        )


@dataclass(frozen=True)
class ObjectInterrogationRequest:
    """
    Read-only request shape for future object interrogation.

    The request selects which read-model sections a future Object Map provider
    may include. It carries requester identity but performs no authorization.
    """

    target_ref: TraceableObjectRef | Mapping[str, object]
    schema_version: str = "1.0"
    include_metadata: bool = True
    include_relationships: bool = True
    include_permissions: bool = True
    include_audit_refs: bool = True
    include_runtime_state: bool = True
    include_docs: bool = True
    include_tests: bool = True
    requester_actor_id: str | None = None
    requester_session_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_ref",
            _normalize_object_ref(self.target_ref, "target_ref"),
        )
        _validate_non_empty_string(self.schema_version, "schema_version")
        for field_name in (
            "include_metadata",
            "include_relationships",
            "include_permissions",
            "include_audit_refs",
            "include_runtime_state",
            "include_docs",
            "include_tests",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be a bool")
        for field_name in ("requester_actor_id", "requester_session_id"):
            _optional_string(getattr(self, field_name), field_name)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this interrogation request."""

        return {
            "target_ref": self.target_ref.to_dict(),
            "schema_version": self.schema_version,
            "include_metadata": self.include_metadata,
            "include_relationships": self.include_relationships,
            "include_permissions": self.include_permissions,
            "include_audit_refs": self.include_audit_refs,
            "include_runtime_state": self.include_runtime_state,
            "include_docs": self.include_docs,
            "include_tests": self.include_tests,
            "requester_actor_id": self.requester_actor_id,
            "requester_session_id": self.requester_session_id,
            "metadata": _plain_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectInterrogationRequest:
        """Build an interrogation request from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            target_ref=_required_mapping(data, "target_ref"),
            schema_version=_optional_string(data.get("schema_version"), "schema_version")
            or "1.0",
            include_metadata=_bool_from_data(data, "include_metadata", True),
            include_relationships=_bool_from_data(data, "include_relationships", True),
            include_permissions=_bool_from_data(data, "include_permissions", True),
            include_audit_refs=_bool_from_data(data, "include_audit_refs", True),
            include_runtime_state=_bool_from_data(data, "include_runtime_state", True),
            include_docs=_bool_from_data(data, "include_docs", True),
            include_tests=_bool_from_data(data, "include_tests", True),
            requester_actor_id=_optional_string(
                data.get("requester_actor_id"),
                "requester_actor_id",
            ),
            requester_session_id=_optional_string(
                data.get("requester_session_id"),
                "requester_session_id",
            ),
            metadata=_mapping_or_empty(data.get("metadata")),
        )


@dataclass(frozen=True)
class ObjectInterrogationReport:
    """
    Read-only response shape for future object interrogation.

    Reports collect owner-emitted summaries, family legends, references, and
    diagnostics. They are not controllers and do not repair or mutate objects.
    """

    target_ref: TraceableObjectRef | Mapping[str, object]
    schema_version: str = "1.0"
    summary: TraceableObjectSummary | Mapping[str, object] | None = None
    family_legend: ObjectFamilyLegend | Mapping[str, object] | None = None
    relationships: tuple[TraceableRelationshipRef | Mapping[str, object], ...] = ()
    permissions: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    runtime_refs: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_ref",
            _normalize_object_ref(self.target_ref, "target_ref"),
        )
        _validate_non_empty_string(self.schema_version, "schema_version")
        object.__setattr__(
            self,
            "summary",
            _normalize_optional_summary(self.summary, "summary"),
        )
        object.__setattr__(
            self,
            "family_legend",
            _normalize_optional_legend(self.family_legend, "family_legend"),
        )
        object.__setattr__(
            self,
            "relationships",
            _normalize_relationship_tuple(self.relationships, "relationships"),
        )
        for field_name in (
            "permissions",
            "audit_refs",
            "runtime_refs",
            "docs",
            "tests",
            "warnings",
            "blockers",
            "errors",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible mapping for this interrogation report."""

        return {
            "target_ref": self.target_ref.to_dict(),
            "schema_version": self.schema_version,
            "summary": self.summary.to_dict() if self.summary is not None else None,
            "family_legend": (
                self.family_legend.to_dict()
                if self.family_legend is not None
                else None
            ),
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
            "permissions": list(self.permissions),
            "audit_refs": list(self.audit_refs),
            "runtime_refs": list(self.runtime_refs),
            "docs": list(self.docs),
            "tests": list(self.tests),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
            "metadata": _plain_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObjectInterrogationReport:
        """Build an interrogation report from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            target_ref=_required_mapping(data, "target_ref"),
            schema_version=_optional_string(data.get("schema_version"), "schema_version")
            or "1.0",
            summary=_optional_mapping(data.get("summary"), "summary"),
            family_legend=_optional_mapping(data.get("family_legend"), "family_legend"),
            relationships=_relationship_tuple_from_data(
                data.get("relationships"),
                "relationships",
            ),
            permissions=_string_tuple_from_data(data.get("permissions"), "permissions"),
            audit_refs=_string_tuple_from_data(data.get("audit_refs"), "audit_refs"),
            runtime_refs=_string_tuple_from_data(data.get("runtime_refs"), "runtime_refs"),
            docs=_string_tuple_from_data(data.get("docs"), "docs"),
            tests=_string_tuple_from_data(data.get("tests"), "tests"),
            warnings=_string_tuple_from_data(data.get("warnings"), "warnings"),
            blockers=_string_tuple_from_data(data.get("blockers"), "blockers"),
            errors=_string_tuple_from_data(data.get("errors"), "errors"),
            metadata=_mapping_or_empty(data.get("metadata")),
        )


def _normalize_object_ref(
    value: TraceableObjectRef | Mapping[str, object],
    field_name: str,
) -> TraceableObjectRef:
    if isinstance(value, TraceableObjectRef):
        return value
    if isinstance(value, Mapping):
        return TraceableObjectRef.from_dict(value)
    raise TypeError(f"{field_name} must be a TraceableObjectRef or mapping")


def _normalize_relationship_tuple(
    values: tuple[TraceableRelationshipRef | Mapping[str, object], ...],
    field_name: str,
) -> tuple[TraceableRelationshipRef, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of relationship refs")
    normalized = tuple(values)
    return tuple(
        value
        if isinstance(value, TraceableRelationshipRef)
        else TraceableRelationshipRef.from_dict(_validate_mapping(value, field_name))
        for value in normalized
    )


def _normalize_optional_summary(
    value: TraceableObjectSummary | Mapping[str, object] | None,
    field_name: str,
) -> TraceableObjectSummary | None:
    if value is None:
        return None
    if isinstance(value, TraceableObjectSummary):
        return value
    if isinstance(value, Mapping):
        return TraceableObjectSummary.from_dict(value)
    raise TypeError(f"{field_name} must be a TraceableObjectSummary, mapping, or None")


def _normalize_optional_legend(
    value: ObjectFamilyLegend | Mapping[str, object] | None,
    field_name: str,
) -> ObjectFamilyLegend | None:
    if value is None:
        return None
    if isinstance(value, ObjectFamilyLegend):
        return value
    if isinstance(value, Mapping):
        return ObjectFamilyLegend.from_dict(value)
    raise TypeError(f"{field_name} must be an ObjectFamilyLegend, mapping, or None")


def _relationship_tuple_from_data(
    value: object,
    field_name: str,
) -> tuple[TraceableRelationshipRef | Mapping[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a tuple of relationship refs")
    if not isinstance(value, tuple | list):
        raise TypeError(f"{field_name} must be a tuple of relationship refs")
    return tuple(
        item
        if isinstance(item, TraceableRelationshipRef)
        else _validate_mapping(item, field_name)
        for item in value
    )


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


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    _validate_mapping(value, "metadata")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        normalized[key] = _readonly_value(item)
    return MappingProxyType(normalized)


def _readonly_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _readonly_mapping(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_value(item) for item in value)
    return value


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("float metadata values must be finite")
        return value
    return value


def _required_string(data: Mapping[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _bool_from_data(data: Mapping[str, object], field_name: str, default: bool) -> bool:
    value = data.get(field_name, default)
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")
    return value


def _required_mapping(data: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    value = data.get(field_name)
    return _validate_mapping(value, field_name)


def _optional_mapping(value: object, field_name: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _validate_mapping(value, field_name)


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    return _validate_mapping(value, "mapping field")


def _validate_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


__all__ = [
    "ObjectFamilyLegend",
    "ObjectInterrogationReport",
    "ObjectInterrogationRequest",
    "TraceableObjectRef",
    "TraceableObjectSummary",
    "TraceableRelationshipRef",
]
