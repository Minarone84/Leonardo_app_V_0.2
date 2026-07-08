"""Static traceable object relationship descriptors for Leonardo V2.

This module defines canonical relationship definition records for current V2
runtime/read-model relationships and conservative placeholders for future
domains. The descriptors are static contract metadata only. They do not discover
objects, register providers, mutate runtime state, implement Object Map
behavior, or call domain services.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from leonardo.contracts.downloads import CONNECTION_DOWNLOAD_MANAGER_OWNER_DOMAIN
from leonardo.contracts.object_family_legends import (
    CURRENT_V2_FAMILY_IDS,
    FUTURE_PLACEHOLDER_FAMILY_IDS,
)


RELATIONSHIP_DIRECTIONS: tuple[str, ...] = (
    "forward",
    "reverse",
    "bidirectional",
    "derived",
    "causal",
    "ownership",
    "reference",
)

RELATIONSHIP_STATUSES: tuple[str, ...] = ("current", "planned")

_KNOWN_FAMILY_IDS = frozenset(
    CURRENT_V2_FAMILY_IDS + FUTURE_PLACEHOLDER_FAMILY_IDS
)

_RELATIONSHIP_DOC = "docs/contracts_docs/OBJECT_RELATIONSHIPS.md"
_TRACEABLE_DOC = "docs/contracts_docs/TRACEABLE_OBJECTS.md"
_LEGEND_DOC = "docs/contracts_docs/OBJECT_FAMILY_LEGENDS.md"
_RELATIONSHIP_TEST = "tests/contracts_test/test_object_relationships.py"

_READ_MODEL_ONLY = {
    "read_model_only": True,
    "forbidden_behavior": (
        "execution",
        "adapters",
        "network_clients",
        "storage_writers",
        "runtime_mutation",
    ),
}

_FUTURE_PLACEHOLDER = {
    "placeholder": True,
    "implementation_not_started": True,
    "forbidden_behavior": (
        "domain_execution",
        "storage_writers",
        "adapter_calls",
        "runtime_mutation",
    ),
}


@dataclass(frozen=True)
class ObjectRelationshipDefinition:
    """
    Static rule describing one supported traceable relationship shape.

    Relationship definitions describe allowed object-kind pairings, ownership,
    metadata expectations, and related contract references. They are not live
    relationship instances. Actual observed relationships are represented by
    `TraceableRelationshipRef` values emitted by object owners or future
    read-only providers.
    """

    relationship_type: str
    source_object_kind: str
    target_object_kind: str
    owner_domain: str
    owner_component: str
    direction: str = "forward"
    source_family_id: str | None = None
    target_family_id: str | None = None
    lifecycle_statuses: tuple[str, ...] = ()
    required_metadata_fields: tuple[str, ...] = ()
    optional_metadata_fields: tuple[str, ...] = ()
    read_provider: str | None = None
    mutation_owner: str | None = None
    audit_event_types: tuple[str, ...] = ()
    permission_refs: tuple[str, ...] = ()
    related_contracts: tuple[str, ...] = ()
    related_docs: tuple[str, ...] = ()
    related_tests: tuple[str, ...] = ()
    status: str = "current"
    schema_version: str = "1.0"
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.relationship_type, "relationship_type")
        _validate_non_empty_string(self.source_object_kind, "source_object_kind")
        _validate_non_empty_string(self.target_object_kind, "target_object_kind")
        _validate_non_empty_string(self.owner_domain, "owner_domain")
        _validate_non_empty_string(self.owner_component, "owner_component")
        _validate_non_empty_string(self.direction, "direction")
        _validate_non_empty_string(self.status, "status")
        _validate_non_empty_string(self.schema_version, "schema_version")
        if self.direction not in RELATIONSHIP_DIRECTIONS:
            raise ValueError(f"Unsupported relationship direction: {self.direction}")
        if self.status not in RELATIONSHIP_STATUSES:
            raise ValueError(f"Unsupported relationship status: {self.status}")

        for field_name in (
            "source_family_id",
            "target_family_id",
            "read_provider",
            "mutation_owner",
        ):
            _optional_string(getattr(self, field_name), field_name)
        _validate_family_id(self.source_family_id, "source_family_id")
        _validate_family_id(self.target_family_id, "target_family_id")

        for field_name in (
            "lifecycle_statuses",
            "required_metadata_fields",
            "optional_metadata_fields",
            "audit_event_types",
            "permission_refs",
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
        """Return a JSON-compatible mapping for this relationship definition."""

        return {
            "relationship_type": self.relationship_type,
            "source_object_kind": self.source_object_kind,
            "target_object_kind": self.target_object_kind,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
            "direction": self.direction,
            "lifecycle_statuses": list(self.lifecycle_statuses),
            "required_metadata_fields": list(self.required_metadata_fields),
            "optional_metadata_fields": list(self.optional_metadata_fields),
            "owner_domain": self.owner_domain,
            "owner_component": self.owner_component,
            "read_provider": self.read_provider,
            "mutation_owner": self.mutation_owner,
            "audit_event_types": list(self.audit_event_types),
            "permission_refs": list(self.permission_refs),
            "related_contracts": list(self.related_contracts),
            "related_docs": list(self.related_docs),
            "related_tests": list(self.related_tests),
            "status": self.status,
            "schema_version": self.schema_version,
            "extra": _plain_value(self.extra),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
    ) -> ObjectRelationshipDefinition:
        """Build a relationship definition from a serialized mapping."""

        _validate_mapping(data, "data")
        return cls(
            relationship_type=_required_string(data, "relationship_type"),
            source_object_kind=_required_string(data, "source_object_kind"),
            target_object_kind=_required_string(data, "target_object_kind"),
            source_family_id=_optional_string(
                data.get("source_family_id"),
                "source_family_id",
            ),
            target_family_id=_optional_string(
                data.get("target_family_id"),
                "target_family_id",
            ),
            direction=_optional_string(data.get("direction"), "direction")
            or "forward",
            lifecycle_statuses=_string_tuple_from_data(
                data.get("lifecycle_statuses"),
                "lifecycle_statuses",
            ),
            required_metadata_fields=_string_tuple_from_data(
                data.get("required_metadata_fields"),
                "required_metadata_fields",
            ),
            optional_metadata_fields=_string_tuple_from_data(
                data.get("optional_metadata_fields"),
                "optional_metadata_fields",
            ),
            owner_domain=_required_string(data, "owner_domain"),
            owner_component=_required_string(data, "owner_component"),
            read_provider=_optional_string(data.get("read_provider"), "read_provider"),
            mutation_owner=_optional_string(
                data.get("mutation_owner"),
                "mutation_owner",
            ),
            audit_event_types=_string_tuple_from_data(
                data.get("audit_event_types"),
                "audit_event_types",
            ),
            permission_refs=_string_tuple_from_data(
                data.get("permission_refs"),
                "permission_refs",
            ),
            related_contracts=_string_tuple_from_data(
                data.get("related_contracts"),
                "related_contracts",
            ),
            related_docs=_string_tuple_from_data(
                data.get("related_docs"),
                "related_docs",
            ),
            related_tests=_string_tuple_from_data(
                data.get("related_tests"),
                "related_tests",
            ),
            status=_optional_string(data.get("status"), "status") or "current",
            schema_version=_optional_string(
                data.get("schema_version"),
                "schema_version",
            )
            or "1.0",
            extra=_mapping_or_empty(data.get("extra")),
        )


def _validate_lookup_key(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _required_string(data: Mapping[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _validate_family_id(value: str | None, field_name: str) -> None:
    if value is not None and value not in _KNOWN_FAMILY_IDS:
        raise ValueError(f"{field_name} references an unknown object family")


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


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    return _validate_mapping(value, "extra")


def _validate_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    _validate_mapping(value, "extra")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("extra keys must be strings")
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
    return value


CURRENT_RELATIONSHIP_TYPES: tuple[str, ...] = (
    "triggers",
    "creates_operation",
    "schedules_task",
    "reports_progress",
    "produces_result",
    "fails_with",
    "cancelled_by",
    "uses_connection",
    "owns_channel",
    "records_audit",
    "described_by_contract",
    "has_permission",
    "opens_window",
    "contains_action",
    "creates_item",
    "creates_plan",
    "classified_by",
    "requires_capability",
)

FUTURE_PLACEHOLDER_RELATIONSHIP_TYPES: tuple[str, ...] = (
    "derives_from",
    "produces_artifact",
    "has_metadata",
    "groups_artifact",
    "groups_recipe",
    "builds_database",
    "uses_dataset",
    "contains_study",
    "contains_chart_panel",
    "produces_report",
    "packages_report",
    "validates",
    "generates_signal",
    "creates_order_intent",
    "owns_subscription",
    "records_message",
    "supersedes",
    "references",
    "depends_on",
)


def _definition(
    relationship_type: str,
    source_object_kind: str,
    target_object_kind: str,
    *,
    owner_domain: str,
    owner_component: str,
    direction: str = "forward",
    source_family_id: str | None = None,
    target_family_id: str | None = None,
    lifecycle_statuses: tuple[str, ...] = (),
    required_metadata_fields: tuple[str, ...] = (),
    optional_metadata_fields: tuple[str, ...] = (),
    read_provider: str | None = None,
    mutation_owner: str | None = None,
    audit_event_types: tuple[str, ...] = (),
    permission_refs: tuple[str, ...] = (),
    related_contracts: tuple[str, ...] = (),
    related_docs: tuple[str, ...] = (),
    related_tests: tuple[str, ...] = (),
    status: str = "current",
    extra: Mapping[str, object] | None = None,
) -> ObjectRelationshipDefinition:
    return ObjectRelationshipDefinition(
        relationship_type=relationship_type,
        source_object_kind=source_object_kind,
        target_object_kind=target_object_kind,
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        direction=direction,
        lifecycle_statuses=lifecycle_statuses,
        required_metadata_fields=required_metadata_fields,
        optional_metadata_fields=optional_metadata_fields,
        owner_domain=owner_domain,
        owner_component=owner_component,
        read_provider=read_provider,
        mutation_owner=mutation_owner,
        audit_event_types=audit_event_types,
        permission_refs=permission_refs,
        related_contracts=(
            "leonardo.contracts.traceable_object.TraceableRelationshipRef",
            *related_contracts,
        ),
        related_docs=(_TRACEABLE_DOC, _LEGEND_DOC, _RELATIONSHIP_DOC, *related_docs),
        related_tests=(_RELATIONSHIP_TEST, *related_tests),
        status=status,
        extra=dict(extra or {}),
    )


def _core_definition(
    relationship_type: str,
    source_family_id: str,
    target_object_kind: str,
    *,
    target_family_id: str | None = None,
    direction: str = "forward",
    owner_component: str,
    mutation_owner: str,
    required_metadata_fields: tuple[str, ...] = (),
    optional_metadata_fields: tuple[str, ...] = (),
    audit_event_types: tuple[str, ...] = (),
    permission_refs: tuple[str, ...] = (),
    related_contracts: tuple[str, ...] = (),
    extra: Mapping[str, object] | None = None,
) -> ObjectRelationshipDefinition:
    return _definition(
        relationship_type,
        source_family_id,
        target_object_kind,
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        direction=direction,
        owner_domain="core.runtime",
        owner_component=owner_component,
        read_provider="RuntimeManagerBackend snapshots and future read-only Object Map",
        mutation_owner=mutation_owner,
        required_metadata_fields=required_metadata_fields,
        optional_metadata_fields=optional_metadata_fields,
        audit_event_types=audit_event_types,
        permission_refs=permission_refs,
        related_contracts=related_contracts,
        extra=extra,
    )


def _download_definition(
    relationship_type: str,
    source_family_id: str,
    target_family_id: str,
    *,
    owner_component: str = "ConnectionDownloadManager read-model owner",
    direction: str = "forward",
) -> ObjectRelationshipDefinition:
    return _definition(
        relationship_type,
        source_family_id,
        target_family_id,
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        direction=direction,
        owner_domain=CONNECTION_DOWNLOAD_MANAGER_OWNER_DOMAIN,
        owner_component=owner_component,
        read_provider=(
            "ConnectionDownloadManager read model and future read-only Object Map"
        ),
        mutation_owner="ConnectionDownloadManager",
        related_contracts=(
            "leonardo.contracts.download.DownloadRequest",
            "leonardo.contracts.download_execution.DownloadExecutionSnapshot",
        ),
        extra=_READ_MODEL_ONLY,
    )


def _future_definition(
    relationship_type: str,
    source_family_id: str,
    target_object_kind: str,
    *,
    target_family_id: str | None = None,
    owner_domain: str,
    owner_component: str,
    direction: str = "forward",
) -> ObjectRelationshipDefinition:
    return _definition(
        relationship_type,
        source_family_id,
        target_object_kind,
        source_family_id=source_family_id,
        target_family_id=target_family_id,
        direction=direction,
        owner_domain=owner_domain,
        owner_component=owner_component,
        read_provider="future read-only Object Map after domain owner exists",
        mutation_owner=owner_component,
        status="planned",
        extra=_FUTURE_PLACEHOLDER,
    )


OBJECT_RELATIONSHIP_DEFINITIONS: tuple[ObjectRelationshipDefinition, ...] = (
    _core_definition(
        "triggers",
        "action",
        "operation",
        target_family_id="operation",
        direction="causal",
        owner_component="ActionRegistry and OperationRegistry",
        mutation_owner="ActionRegistry and OperationRegistry",
        optional_metadata_fields=("action_id", "operation_id", "command_id"),
        audit_event_types=("action.triggered", "operation.created"),
        permission_refs=("runtime:view",),
    ),
    _core_definition(
        "creates_operation",
        "action",
        "operation",
        target_family_id="operation",
        direction="causal",
        owner_component="OperationRegistry",
        mutation_owner="OperationRegistry",
        optional_metadata_fields=("action_id", "operation_id", "command_id"),
        audit_event_types=("operation.created",),
        permission_refs=("runtime:view",),
    ),
    _definition(
        "creates_operation",
        "command",
        "operation",
        target_family_id="operation",
        direction="causal",
        owner_domain="core.runtime",
        owner_component="OperationRegistry",
        read_provider="RuntimeManagerBackend snapshots and future read-only Object Map",
        mutation_owner="OperationRegistry",
        optional_metadata_fields=("command_id", "operation_id"),
        audit_event_types=("operation.created",),
        permission_refs=("runtime:view",),
    ),
    _core_definition(
        "schedules_task",
        "operation",
        "task",
        target_family_id="task",
        direction="causal",
        owner_component="TaskManager",
        mutation_owner="TaskManager",
        optional_metadata_fields=("operation_id", "task_id"),
        audit_event_types=("task.scheduled",),
    ),
    _core_definition(
        "reports_progress",
        "operation",
        "progress_event",
        direction="causal",
        owner_component="OperationRegistry",
        mutation_owner="OperationRegistry",
        required_metadata_fields=("progress_event_id",),
        optional_metadata_fields=("operation_id", "percent_complete", "message"),
        audit_event_types=("operation.progress",),
    ),
    _core_definition(
        "reports_progress",
        "task",
        "progress_event",
        direction="causal",
        owner_component="TaskManager",
        mutation_owner="TaskManager",
        required_metadata_fields=("progress_event_id",),
        optional_metadata_fields=("task_id", "percent_complete", "message"),
        audit_event_types=("task.progress",),
    ),
    _core_definition(
        "produces_result",
        "operation",
        "result",
        direction="causal",
        owner_component="OperationRegistry",
        mutation_owner="OperationRegistry",
        optional_metadata_fields=("operation_id", "result_id", "summary"),
        audit_event_types=("operation.completed",),
    ),
    _core_definition(
        "produces_result",
        "task",
        "result",
        direction="causal",
        owner_component="TaskManager",
        mutation_owner="TaskManager",
        optional_metadata_fields=("task_id", "result_id", "summary"),
        audit_event_types=("task.completed",),
    ),
    _core_definition(
        "fails_with",
        "operation",
        "error_report",
        target_family_id="error_report",
        direction="causal",
        owner_component="OperationRegistry and ErrorRouter",
        mutation_owner="OperationRegistry and ErrorRouter",
        optional_metadata_fields=("operation_id", "error_id", "severity"),
        audit_event_types=("operation.failed", "error.reported"),
    ),
    _core_definition(
        "fails_with",
        "task",
        "error_report",
        target_family_id="error_report",
        direction="causal",
        owner_component="TaskManager and ErrorRouter",
        mutation_owner="TaskManager and ErrorRouter",
        optional_metadata_fields=("task_id", "error_id", "severity"),
        audit_event_types=("task.failed", "error.reported"),
    ),
    _core_definition(
        "cancelled_by",
        "operation",
        "cancellation_request",
        direction="causal",
        owner_component="OperationRegistry",
        mutation_owner="OperationRegistry",
        optional_metadata_fields=("operation_id", "requested_by", "reason"),
        audit_event_types=("operation.cancelled",),
    ),
    _core_definition(
        "cancelled_by",
        "task",
        "cancellation_request",
        direction="causal",
        owner_component="TaskManager",
        mutation_owner="TaskManager",
        optional_metadata_fields=("task_id", "requested_by", "reason"),
        audit_event_types=("task.cancelled",),
    ),
    _core_definition(
        "uses_connection",
        "operation",
        "connection",
        target_family_id="connection",
        direction="reference",
        owner_component="OperationRegistry and ConnectionRegistry",
        mutation_owner="ConnectionRegistry",
        optional_metadata_fields=("operation_id", "connection_id"),
        audit_event_types=("connection.used",),
    ),
    _core_definition(
        "uses_connection",
        "task",
        "connection",
        target_family_id="connection",
        direction="reference",
        owner_component="TaskManager and ConnectionRegistry",
        mutation_owner="ConnectionRegistry",
        optional_metadata_fields=("task_id", "connection_id"),
        audit_event_types=("connection.used",),
    ),
    _core_definition(
        "owns_channel",
        "connection",
        "websocket_channel",
        target_family_id="websocket_channel",
        direction="ownership",
        owner_component="ConnectionRegistry",
        mutation_owner="ConnectionRegistry",
        required_metadata_fields=("connection_id", "channel_id"),
        audit_event_types=("connection.channel.opened",),
    ),
    _core_definition(
        "records_audit",
        "operation",
        "audit_event",
        target_family_id="audit_event",
        direction="causal",
        owner_component="AuditLog",
        mutation_owner="AuditLog",
        optional_metadata_fields=("operation_id", "audit_event_id"),
        audit_event_types=("operation.audit_recorded",),
    ),
    _core_definition(
        "records_audit",
        "task",
        "audit_event",
        target_family_id="audit_event",
        direction="causal",
        owner_component="AuditLog",
        mutation_owner="AuditLog",
        optional_metadata_fields=("task_id", "audit_event_id"),
        audit_event_types=("task.audit_recorded",),
    ),
    _core_definition(
        "records_audit",
        "action",
        "audit_event",
        target_family_id="audit_event",
        direction="causal",
        owner_component="AuditLog",
        mutation_owner="AuditLog",
        optional_metadata_fields=("action_id", "audit_event_id"),
        audit_event_types=("action.audit_recorded",),
    ),
    _core_definition(
        "records_audit",
        "window",
        "audit_event",
        target_family_id="audit_event",
        direction="causal",
        owner_component="AuditLog",
        mutation_owner="AuditLog",
        optional_metadata_fields=("window_id", "audit_event_id"),
        audit_event_types=("window.audit_recorded",),
    ),
    _core_definition(
        "records_audit",
        "connection",
        "audit_event",
        target_family_id="audit_event",
        direction="causal",
        owner_component="AuditLog",
        mutation_owner="AuditLog",
        optional_metadata_fields=("connection_id", "audit_event_id"),
        audit_event_types=("connection.audit_recorded",),
    ),
    _definition(
        "described_by_contract",
        "object_family",
        "contract_descriptor",
        target_family_id="contract_descriptor",
        direction="reference",
        owner_domain="contracts",
        owner_component="ContractRegistry",
        read_provider="ContractRegistry and future read-only Object Map",
        mutation_owner="ContractRegistry",
        required_metadata_fields=("contract_id",),
        optional_metadata_fields=("family_id", "object_kind", "contract_version"),
        related_contracts=("leonardo.core.contract_registry.ContractRegistry",),
    ),
    _core_definition(
        "has_permission",
        "action",
        "permission",
        direction="reference",
        owner_component="UserPolicy and ActionRegistry",
        mutation_owner="UserPolicy",
        required_metadata_fields=("permission_ref",),
        optional_metadata_fields=("action_id",),
        permission_refs=("runtime:view",),
        related_contracts=("leonardo.core.user_policy.UserPolicy",),
    ),
    _definition(
        "has_permission",
        "object_family",
        "permission",
        direction="reference",
        owner_domain="core.policy",
        owner_component="UserPolicy",
        read_provider="UserPolicy and future read-only Object Map",
        mutation_owner="UserPolicy",
        required_metadata_fields=("permission_ref",),
        optional_metadata_fields=("family_id", "object_kind"),
        permission_refs=("runtime:view",),
        related_contracts=("leonardo.core.user_policy.UserPolicy",),
    ),
    _core_definition(
        "opens_window",
        "action",
        "window",
        target_family_id="window",
        direction="causal",
        owner_component="ActionRegistry and WindowRegistry",
        mutation_owner="WindowRegistry",
        optional_metadata_fields=("action_id", "window_id"),
        audit_event_types=("window.opened",),
        permission_refs=("runtime:view",),
    ),
    _core_definition(
        "contains_action",
        "window",
        "action",
        target_family_id="action",
        direction="ownership",
        owner_component="WindowRegistry and ActionRegistry",
        mutation_owner="ActionRegistry",
        required_metadata_fields=("window_id", "action_id"),
        audit_event_types=("action.registered",),
        permission_refs=("runtime:view",),
    ),
    _download_definition(
        "creates_item",
        "download_request",
        "download_item",
    ),
    _download_definition(
        "creates_plan",
        "download_request",
        "download_execution_snapshot",
        owner_component="ConnectionDownloadExecutionReadModel owner",
    ),
    _download_definition(
        "creates_plan",
        "download_request",
        "download_preflight",
        owner_component="ConnectionDownloadPreflightReadModel owner",
    ),
    _download_definition(
        "classified_by",
        "download_execution_snapshot",
        "download_preflight",
        owner_component="ConnectionDownloadReadinessReadModel owner",
    ),
    _download_definition(
        "requires_capability",
        "download_request",
        "download_capability",
        owner_component="ConnectionDownloadCapabilityCatalog",
    ),
    _download_definition(
        "requires_capability",
        "download_item",
        "download_capability",
        owner_component="ConnectionDownloadCapabilityCatalog",
    ),
    _future_definition(
        "derives_from",
        "saved_artifact",
        "artifact_recipe",
        target_family_id="artifact_recipe",
        owner_domain="data_manager",
        owner_component="future artifact lineage owner",
        direction="derived",
    ),
    _future_definition(
        "produces_artifact",
        "artifact_recipe",
        "saved_artifact",
        target_family_id="saved_artifact",
        owner_domain="data_manager",
        owner_component="future artifact recipe executor",
        direction="causal",
    ),
    _future_definition(
        "has_metadata",
        "saved_artifact",
        "artifact_metadata",
        target_family_id="artifact_metadata",
        owner_domain="data_manager",
        owner_component="future artifact metadata store",
        direction="ownership",
    ),
    _future_definition(
        "groups_artifact",
        "artifact_collection",
        "saved_artifact",
        target_family_id="saved_artifact",
        owner_domain="data_manager",
        owner_component="future artifact collection store",
        direction="ownership",
    ),
    _future_definition(
        "groups_recipe",
        "recipe_collection",
        "artifact_recipe",
        target_family_id="artifact_recipe",
        owner_domain="data_manager",
        owner_component="future recipe collection store",
        direction="ownership",
    ),
    _future_definition(
        "builds_database",
        "artifact_recipe",
        "analysis_database",
        target_family_id="analysis_database",
        owner_domain="analysis",
        owner_component="future analysis database builder",
        direction="causal",
    ),
    _future_definition(
        "uses_dataset",
        "analysis_database",
        "dataset",
        owner_domain="analysis",
        owner_component="future dataset usage owner",
        direction="reference",
    ),
    _future_definition(
        "contains_study",
        "analysis_project",
        "study",
        target_family_id="study",
        owner_domain="analysis",
        owner_component="future analysis project owner",
        direction="ownership",
    ),
    _future_definition(
        "contains_chart_panel",
        "chart_session",
        "chart_panel",
        target_family_id="chart_panel",
        owner_domain="charting",
        owner_component="future chart session owner",
        direction="ownership",
    ),
    _future_definition(
        "produces_report",
        "analysis_run",
        "analysis_report",
        target_family_id="analysis_report",
        owner_domain="analysis",
        owner_component="future analysis run owner",
        direction="causal",
    ),
    _future_definition(
        "packages_report",
        "analysis_report",
        "saved_artifact",
        target_family_id="saved_artifact",
        owner_domain="analysis",
        owner_component="future report package owner",
        direction="causal",
    ),
    _future_definition(
        "validates",
        "validation_scenario",
        "saved_rule_package",
        target_family_id="saved_rule_package",
        owner_domain="analysis",
        owner_component="future validation scenario owner",
        direction="causal",
    ),
    _future_definition(
        "generates_signal",
        "trading_strategy",
        "trading_signal",
        target_family_id="trading_signal",
        owner_domain="trading",
        owner_component="future signal generation owner",
        direction="causal",
    ),
    _future_definition(
        "creates_order_intent",
        "trading_signal",
        "order_intent",
        target_family_id="order_intent",
        owner_domain="trading",
        owner_component="future order intent owner",
        direction="causal",
    ),
    _future_definition(
        "owns_subscription",
        "provider_session",
        "websocket_subscription",
        target_family_id="websocket_subscription",
        owner_domain="connection",
        owner_component="future provider session owner",
        direction="ownership",
    ),
    _future_definition(
        "records_message",
        "websocket_subscription",
        "websocket_message_trace",
        target_family_id="websocket_message_trace",
        owner_domain="connection",
        owner_component="future websocket trace owner",
        direction="causal",
    ),
    _future_definition(
        "supersedes",
        "saved_artifact",
        "saved_artifact",
        target_family_id="saved_artifact",
        owner_domain="data_manager",
        owner_component="future artifact lineage owner",
        direction="reference",
    ),
    _definition(
        "references",
        "traceable_object",
        "traceable_object",
        owner_domain="contracts",
        owner_component="future read-only Object Map",
        read_provider="future read-only Object Map after domain owner exists",
        mutation_owner="future read-only Object Map",
        direction="reference",
        status="planned",
        extra=_FUTURE_PLACEHOLDER,
    ),
    _definition(
        "depends_on",
        "traceable_object",
        "traceable_object",
        owner_domain="contracts",
        owner_component="future read-only Object Map",
        read_provider="future read-only Object Map after domain owner exists",
        mutation_owner="future read-only Object Map",
        direction="reference",
        status="planned",
        extra=_FUTURE_PLACEHOLDER,
    ),
)


def _group_by_field(field_name: str) -> dict[str, tuple[ObjectRelationshipDefinition, ...]]:
    keys = tuple(
        dict.fromkeys(
            getattr(definition, field_name)
            for definition in OBJECT_RELATIONSHIP_DEFINITIONS
        )
    )
    return {
        key: tuple(
            definition
            for definition in OBJECT_RELATIONSHIP_DEFINITIONS
            if getattr(definition, field_name) == key
        )
        for key in keys
    }


_DEFINITIONS_BY_TYPE = MappingProxyType(
    {
        relationship_type: tuple(
            definition
            for definition in OBJECT_RELATIONSHIP_DEFINITIONS
            if definition.relationship_type == relationship_type
        )
        for relationship_type in (
            CURRENT_RELATIONSHIP_TYPES + FUTURE_PLACEHOLDER_RELATIONSHIP_TYPES
        )
    }
)

_DEFINITIONS_BY_SOURCE = MappingProxyType(
    _group_by_field("source_object_kind")
)
_DEFINITIONS_BY_TARGET = MappingProxyType(
    _group_by_field("target_object_kind")
)


def all_object_relationship_definitions() -> tuple[ObjectRelationshipDefinition, ...]:
    """Return all static object relationship definitions in deterministic order."""

    return OBJECT_RELATIONSHIP_DEFINITIONS


def object_relationship_definitions_by_type(
    relationship_type: str,
) -> tuple[ObjectRelationshipDefinition, ...]:
    """Return static relationship definitions for one relationship type."""

    _validate_lookup_key(relationship_type, "relationship_type")
    return _DEFINITIONS_BY_TYPE.get(relationship_type, ())


def object_relationship_definitions_for_source(
    object_kind: str,
) -> tuple[ObjectRelationshipDefinition, ...]:
    """Return static relationship definitions for one source object kind."""

    _validate_lookup_key(object_kind, "object_kind")
    return _DEFINITIONS_BY_SOURCE.get(object_kind, ())


def object_relationship_definitions_for_target(
    object_kind: str,
) -> tuple[ObjectRelationshipDefinition, ...]:
    """Return static relationship definitions for one target object kind."""

    _validate_lookup_key(object_kind, "object_kind")
    return _DEFINITIONS_BY_TARGET.get(object_kind, ())


def _validate_unique_relationship_definitions() -> None:
    expected = set(CURRENT_RELATIONSHIP_TYPES + FUTURE_PLACEHOLDER_RELATIONSHIP_TYPES)
    actual = {
        definition.relationship_type
        for definition in OBJECT_RELATIONSHIP_DEFINITIONS
    }
    missing = expected - actual
    if missing:
        raise ValueError(f"Missing relationship definitions: {sorted(missing)}")


_validate_unique_relationship_definitions()

__all__ = [
    "CURRENT_RELATIONSHIP_TYPES",
    "FUTURE_PLACEHOLDER_RELATIONSHIP_TYPES",
    "OBJECT_RELATIONSHIP_DEFINITIONS",
    "ObjectRelationshipDefinition",
    "RELATIONSHIP_DIRECTIONS",
    "RELATIONSHIP_STATUSES",
    "all_object_relationship_definitions",
    "object_relationship_definitions_by_type",
    "object_relationship_definitions_for_source",
    "object_relationship_definitions_for_target",
]
