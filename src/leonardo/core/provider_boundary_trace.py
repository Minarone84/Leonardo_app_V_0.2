"""Read-only Object Map trace helpers for provider boundary descriptors."""

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
from leonardo.contracts.provider_boundary import (
    ProviderCapabilityDescriptor,
    ProviderDescriptor,
    ProviderMessageTraceDescriptor,
    ProviderSessionDescriptor,
    ProviderSubscriptionDescriptor,
)
from leonardo.contracts.traceable_object import (
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


PROVIDER_BOUNDARY_TRACE_PROVIDER_ID = "core.provider_boundary.trace"
PROVIDER_BOUNDARY_TRACE_SECTION_ID = "core.provider_boundary"

PROVIDER_OBJECT_KIND = "provider"
PROVIDER_CAPABILITY_OBJECT_KIND = "provider_capability"
PROVIDER_SESSION_OBJECT_KIND = "provider_session"
PROVIDER_SUBSCRIPTION_OBJECT_KIND = "provider_subscription"
PROVIDER_MESSAGE_TRACE_OBJECT_KIND = "provider_message_trace"
PERMISSION_OBJECT_KIND = "permission"
OBJECT_FAMILY_OBJECT_KIND = "object_family"
CONNECTION_OBJECT_KIND = "connection"

_DESCRIPTOR_OBJECT_KINDS = (
    PROVIDER_OBJECT_KIND,
    PROVIDER_CAPABILITY_OBJECT_KIND,
    PROVIDER_SESSION_OBJECT_KIND,
    PROVIDER_SUBSCRIPTION_OBJECT_KIND,
    PROVIDER_MESSAGE_TRACE_OBJECT_KIND,
)
_RELATED_DOC = "docs/core_docs/PROVIDER_OBJECT_MAP_PATTERN.md"
_RELATED_CONTRACT_DOC = "docs/contracts_docs/PROVIDER_BOUNDARY.md"
_RELATED_TEST = "tests/core_test/test_provider_boundary_object_map_pattern.py"


def build_provider_boundary_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Build the read-only provider descriptor for provider boundary descriptors."""

    return ObjectMapProviderDescriptor(
        provider_id=PROVIDER_BOUNDARY_TRACE_PROVIDER_ID,
        provider_name="Provider Boundary Trace",
        owner_domain="core",
        owner_component="ProviderBoundaryTrace",
        object_kinds=_DESCRIPTOR_OBJECT_KINDS,
        family_ids=_DESCRIPTOR_OBJECT_KINDS,
        relationship_types=("references", "has_permission"),
        supports_summary_listing=True,
        supports_interrogation=False,
        supports_relationship_listing=True,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=(
            "leonardo.contracts.provider_boundary.ProviderDescriptor",
            "leonardo.contracts.provider_boundary.ProviderCapabilityDescriptor",
            "leonardo.contracts.provider_boundary.ProviderSessionDescriptor",
            "leonardo.contracts.provider_boundary.ProviderSubscriptionDescriptor",
            "leonardo.contracts.provider_boundary.ProviderMessageTraceDescriptor",
        ),
        related_docs=(_RELATED_CONTRACT_DOC, _RELATED_DOC),
        related_tests=(_RELATED_TEST,),
        metadata={
            "descriptor_source": "explicit_descriptor_inputs",
            "runtime_binding": "not_implemented",
        },
        extra={"read_only": True, "mutation_forbidden": True},
    )


def provider_trace_ref_from_descriptor(
    provider: ProviderDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a provider descriptor."""

    _require_type(provider, ProviderDescriptor, "provider")
    return TraceableObjectRef(
        object_id=provider.provider_id,
        object_kind=PROVIDER_OBJECT_KIND,
        owner_domain=provider.owner_domain,
        owner_component=provider.owner_component,
        schema_version=provider.version,
        label=provider.display_name,
        metadata={
            "family_id": PROVIDER_OBJECT_KIND,
            "descriptor_type": "ProviderDescriptor",
        },
    )


def provider_capability_trace_ref_from_descriptor(
    capability: ProviderCapabilityDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a provider capability descriptor."""

    _require_type(capability, ProviderCapabilityDescriptor, "capability")
    return TraceableObjectRef(
        object_id=capability.capability_id,
        object_kind=PROVIDER_CAPABILITY_OBJECT_KIND,
        owner_domain="provider_boundary",
        owner_component="ProviderCapabilityDescriptor",
        label=capability.label,
        metadata={
            "family_id": PROVIDER_CAPABILITY_OBJECT_KIND,
            "descriptor_type": "ProviderCapabilityDescriptor",
            "provider_id": capability.provider_id,
            "required_permission": capability.required_permission,
        },
    )


def provider_session_trace_ref_from_descriptor(
    session: ProviderSessionDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a provider session descriptor."""

    _require_type(session, ProviderSessionDescriptor, "session")
    return TraceableObjectRef(
        object_id=session.provider_session_id,
        object_kind=PROVIDER_SESSION_OBJECT_KIND,
        owner_domain="provider_boundary",
        owner_component="ProviderSessionDescriptor",
        label=session.provider_session_id,
        metadata={
            "family_id": PROVIDER_SESSION_OBJECT_KIND,
            "descriptor_type": "ProviderSessionDescriptor",
            "provider_id": session.provider_id,
            "connection_id": session.connection_id,
        },
    )


def provider_subscription_trace_ref_from_descriptor(
    subscription: ProviderSubscriptionDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a provider subscription descriptor."""

    _require_type(subscription, ProviderSubscriptionDescriptor, "subscription")
    return TraceableObjectRef(
        object_id=subscription.subscription_id,
        object_kind=PROVIDER_SUBSCRIPTION_OBJECT_KIND,
        owner_domain="provider_boundary",
        owner_component="ProviderSubscriptionDescriptor",
        label=subscription.subscription_id,
        metadata={
            "family_id": PROVIDER_SUBSCRIPTION_OBJECT_KIND,
            "descriptor_type": "ProviderSubscriptionDescriptor",
            "provider_id": subscription.provider_id,
            "provider_session_id": subscription.provider_session_id,
            "capability_id": subscription.capability_id,
            "connection_id": subscription.connection_id,
        },
    )


def provider_message_trace_ref_from_descriptor(
    message_trace: ProviderMessageTraceDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for a provider message trace descriptor."""

    _require_type(message_trace, ProviderMessageTraceDescriptor, "message_trace")
    return TraceableObjectRef(
        object_id=message_trace.message_trace_id,
        object_kind=PROVIDER_MESSAGE_TRACE_OBJECT_KIND,
        owner_domain="provider_boundary",
        owner_component="ProviderMessageTraceDescriptor",
        label=message_trace.message_trace_id,
        metadata={
            "family_id": PROVIDER_MESSAGE_TRACE_OBJECT_KIND,
            "descriptor_type": "ProviderMessageTraceDescriptor",
            "provider_id": message_trace.provider_id,
            "provider_session_id": message_trace.provider_session_id,
            "subscription_id": message_trace.subscription_id,
            "connection_id": message_trace.connection_id,
        },
    )


def provider_trace_summary_from_descriptor(
    provider: ProviderDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a provider descriptor."""

    ref = provider_trace_ref_from_descriptor(provider)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(provider.lifecycle_status),
        runtime_or_persistent="static_metadata",
        display_name=provider.display_name,
        metadata={
            "family_id": PROVIDER_OBJECT_KIND,
            "provider_id": provider.provider_id,
            "description": provider.description,
            "provider_kind": _value(provider.provider_kind),
            "lifecycle_status": _value(provider.lifecycle_status),
            "version": provider.version,
            "supported_capability_ids": provider.supported_capability_ids,
            "supported_connection_kinds": provider.supported_connection_kinds,
            "supports_websocket": provider.supports_websocket,
            "supports_polling": provider.supports_polling,
            "supports_batch": provider.supports_batch,
            "required_permissions": provider.required_permissions,
            "object_family_ids": provider.object_family_ids,
            "docs_refs": provider.docs_refs,
            "test_refs": provider.test_refs,
            "metadata_refs": provider.metadata_refs,
            "warnings": provider.warnings,
            "blockers": provider.blockers,
            "read_only": True,
        },
        permission_refs=provider.required_permissions,
        source_refs=(provider.owner_component,),
        extra={"descriptor_type": "ProviderDescriptor", "mutation_forbidden": True},
    )


def provider_capability_trace_summary_from_descriptor(
    capability: ProviderCapabilityDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a provider capability descriptor."""

    ref = provider_capability_trace_ref_from_descriptor(capability)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="declared",
        runtime_or_persistent="static_metadata",
        display_name=capability.label,
        metadata={
            "family_id": PROVIDER_CAPABILITY_OBJECT_KIND,
            "capability_id": capability.capability_id,
            "provider_id": capability.provider_id,
            "capability_kind": _value(capability.capability_kind),
            "description": capability.description,
            "required_permission": capability.required_permission,
            "connection_required": capability.connection_required,
            "websocket_required": capability.websocket_required,
            "supports_streaming": capability.supports_streaming,
            "supports_batch": capability.supports_batch,
            "input_schema_ref": capability.input_schema_ref,
            "result_schema_ref": capability.result_schema_ref,
            "rate_limit_ref": capability.rate_limit_ref,
            "audit_category": capability.audit_category,
            "audit_policy": _value(capability.audit_policy),
            "object_family_ids": capability.object_family_ids,
            "docs_refs": capability.docs_refs,
            "test_refs": capability.test_refs,
            "warnings": capability.warnings,
            "blockers": capability.blockers,
            "read_only": True,
        },
        permission_refs=(capability.required_permission,),
        source_refs=("ProviderCapabilityDescriptor",),
        extra={
            "descriptor_type": "ProviderCapabilityDescriptor",
            "mutation_forbidden": True,
        },
    )


def provider_session_trace_summary_from_descriptor(
    session: ProviderSessionDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a provider session descriptor."""

    ref = provider_session_trace_ref_from_descriptor(session)
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(session.status),
        runtime_or_persistent="runtime_read_model",
        display_name=session.provider_session_id,
        metadata={
            "family_id": PROVIDER_SESSION_OBJECT_KIND,
            "provider_session_id": session.provider_session_id,
            "provider_id": session.provider_id,
            "connection_id": session.connection_id,
            "actor_id": session.actor_id,
            "session_id": session.session_id,
            "status": _value(session.status),
            "authentication_mode": _value(session.authentication_mode),
            "started_at": session.started_at,
            "last_heartbeat_at": session.last_heartbeat_at,
            "active_capability_ids": session.active_capability_ids,
            "warning_count": session.warning_count,
            "error_count": session.error_count,
            "safe_metadata": session.metadata,
            "docs_refs": session.docs_refs,
            "test_refs": session.test_refs,
            "warnings": session.warnings,
            "errors": session.errors,
            "read_only": True,
        },
        source_refs=("ProviderSessionDescriptor",),
        extra={"descriptor_type": "ProviderSessionDescriptor", "mutation_forbidden": True},
    )


def provider_subscription_trace_summary_from_descriptor(
    subscription: ProviderSubscriptionDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for a provider subscription descriptor."""

    ref = provider_subscription_trace_ref_from_descriptor(subscription)
    permission_refs = (
        (subscription.required_permission,)
        if subscription.required_permission is not None
        else ()
    )
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status=_value(subscription.status),
        runtime_or_persistent="runtime_read_model",
        display_name=subscription.subscription_id,
        metadata={
            "family_id": PROVIDER_SUBSCRIPTION_OBJECT_KIND,
            "subscription_id": subscription.subscription_id,
            "provider_id": subscription.provider_id,
            "provider_session_id": subscription.provider_session_id,
            "capability_id": subscription.capability_id,
            "connection_id": subscription.connection_id,
            "websocket_channel_id": subscription.websocket_channel_id,
            "topic": subscription.topic,
            "subscription_kind": _value(subscription.subscription_kind),
            "status": _value(subscription.status),
            "created_at": subscription.created_at,
            "updated_at": subscription.updated_at,
            "last_message_at": subscription.last_message_at,
            "message_count": subscription.message_count,
            "error_count": subscription.error_count,
            "required_permission": subscription.required_permission,
            "object_family_ids": subscription.object_family_ids,
            "docs_refs": subscription.docs_refs,
            "test_refs": subscription.test_refs,
            "warnings": subscription.warnings,
            "errors": subscription.errors,
            "read_only": True,
        },
        permission_refs=permission_refs,
        source_refs=("ProviderSubscriptionDescriptor",),
        extra={
            "descriptor_type": "ProviderSubscriptionDescriptor",
            "mutation_forbidden": True,
            "execution": "not_implemented",
        },
    )


def provider_message_trace_summary_from_descriptor(
    message_trace: ProviderMessageTraceDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only Object Map summary for bounded message trace metadata."""

    ref = provider_message_trace_ref_from_descriptor(message_trace)
    correlation_refs = (
        (message_trace.correlation_id,)
        if message_trace.correlation_id is not None
        else ()
    )
    return TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="observed",
        runtime_or_persistent="runtime_read_model",
        display_name=message_trace.message_trace_id,
        metadata={
            "family_id": PROVIDER_MESSAGE_TRACE_OBJECT_KIND,
            "message_trace_id": message_trace.message_trace_id,
            "provider_id": message_trace.provider_id,
            "provider_session_id": message_trace.provider_session_id,
            "subscription_id": message_trace.subscription_id,
            "connection_id": message_trace.connection_id,
            "websocket_channel_id": message_trace.websocket_channel_id,
            "direction": _value(message_trace.direction),
            "message_kind": _value(message_trace.message_kind),
            "observed_at": message_trace.observed_at,
            "payload_kind": message_trace.payload_kind,
            "payload_size_bytes": message_trace.payload_size_bytes,
            "payload_key_count": message_trace.payload_key_count,
            "payload_keys": message_trace.payload_keys,
            "warning_count": message_trace.warning_count,
            "error_count": message_trace.error_count,
            "docs_refs": message_trace.docs_refs,
            "test_refs": message_trace.test_refs,
            "warnings": message_trace.warnings,
            "errors": message_trace.errors,
            "read_only": True,
        },
        source_refs=("ProviderMessageTraceDescriptor",),
        correlation_refs=correlation_refs,
        extra={
            "descriptor_type": "ProviderMessageTraceDescriptor",
            "mutation_forbidden": True,
            "raw_message_body": "not_included",
        },
    )


def provider_boundary_relationships_from_descriptors(
    *,
    providers: Iterable[ProviderDescriptor] = (),
    capabilities: Iterable[ProviderCapabilityDescriptor] = (),
    sessions: Iterable[ProviderSessionDescriptor] = (),
    subscriptions: Iterable[ProviderSubscriptionDescriptor] = (),
    message_traces: Iterable[ProviderMessageTraceDescriptor] = (),
) -> tuple[TraceableRelationshipRef, ...]:
    """Build descriptor relationships from explicit provider boundary descriptors."""

    normalized = _normalize_inputs(
        providers=providers,
        capabilities=capabilities,
        sessions=sessions,
        subscriptions=subscriptions,
        message_traces=message_traces,
    )
    relationships: list[TraceableRelationshipRef] = []

    for provider in normalized.providers:
        provider_ref = provider_trace_ref_from_descriptor(provider)
        for capability_id in provider.supported_capability_ids:
            capability = normalized.capability_by_id.get(capability_id)
            if capability is not None:
                _append_reference(
                    relationships,
                    provider_ref,
                    provider_capability_trace_ref_from_descriptor(capability),
                )
        _append_descriptor_permission_relationships(
            relationships,
            provider_ref,
            provider.required_permissions,
        )
        _append_object_family_relationships(
            relationships,
            provider_ref,
            provider.object_family_ids,
        )

    for capability in normalized.capabilities:
        capability_ref = provider_capability_trace_ref_from_descriptor(capability)
        provider = normalized.provider_by_id.get(capability.provider_id)
        if provider is not None:
            _append_reference(
                relationships,
                capability_ref,
                provider_trace_ref_from_descriptor(provider),
            )
        _append_descriptor_permission_relationships(
            relationships,
            capability_ref,
            (capability.required_permission,),
        )
        _append_object_family_relationships(
            relationships,
            capability_ref,
            capability.object_family_ids,
        )

    for session in normalized.sessions:
        session_ref = provider_session_trace_ref_from_descriptor(session)
        provider = normalized.provider_by_id.get(session.provider_id)
        if provider is not None:
            _append_reference(
                relationships,
                session_ref,
                provider_trace_ref_from_descriptor(provider),
            )
        for capability_id in session.active_capability_ids:
            capability = normalized.capability_by_id.get(capability_id)
            if capability is not None:
                _append_reference(
                    relationships,
                    session_ref,
                    provider_capability_trace_ref_from_descriptor(capability),
                )
        if session.connection_id is not None:
            _append_connection_reference(relationships, session_ref, session.connection_id)

    for subscription in normalized.subscriptions:
        subscription_ref = provider_subscription_trace_ref_from_descriptor(subscription)
        provider = normalized.provider_by_id.get(subscription.provider_id)
        if provider is not None:
            _append_reference(
                relationships,
                subscription_ref,
                provider_trace_ref_from_descriptor(provider),
            )
        if subscription.provider_session_id is not None:
            session = normalized.session_by_id.get(subscription.provider_session_id)
            if session is not None:
                _append_reference(
                    relationships,
                    subscription_ref,
                    provider_session_trace_ref_from_descriptor(session),
                )
        if subscription.capability_id is not None:
            capability = normalized.capability_by_id.get(subscription.capability_id)
            if capability is not None:
                _append_reference(
                    relationships,
                    subscription_ref,
                    provider_capability_trace_ref_from_descriptor(capability),
                )
        if subscription.connection_id is not None:
            _append_connection_reference(
                relationships,
                subscription_ref,
                subscription.connection_id,
            )
        if subscription.required_permission is not None:
            _append_descriptor_permission_relationships(
                relationships,
                subscription_ref,
                (subscription.required_permission,),
            )
        _append_object_family_relationships(
            relationships,
            subscription_ref,
            subscription.object_family_ids,
        )

    for message_trace in normalized.message_traces:
        message_ref = provider_message_trace_ref_from_descriptor(message_trace)
        provider = normalized.provider_by_id.get(message_trace.provider_id)
        if provider is not None:
            _append_reference(
                relationships,
                message_ref,
                provider_trace_ref_from_descriptor(provider),
            )
        if message_trace.provider_session_id is not None:
            session = normalized.session_by_id.get(message_trace.provider_session_id)
            if session is not None:
                _append_reference(
                    relationships,
                    message_ref,
                    provider_session_trace_ref_from_descriptor(session),
                )
        if message_trace.subscription_id is not None:
            subscription = normalized.subscription_by_id.get(
                message_trace.subscription_id
            )
            if subscription is not None:
                _append_reference(
                    relationships,
                    message_ref,
                    provider_subscription_trace_ref_from_descriptor(subscription),
                )
        if message_trace.connection_id is not None:
            _append_connection_reference(
                relationships,
                message_ref,
                message_trace.connection_id,
            )

    return _dedupe_relationships(relationships)


def build_provider_boundary_trace_section(
    *,
    providers: Iterable[ProviderDescriptor] = (),
    capabilities: Iterable[ProviderCapabilityDescriptor] = (),
    sessions: Iterable[ProviderSessionDescriptor] = (),
    subscriptions: Iterable[ProviderSubscriptionDescriptor] = (),
    message_traces: Iterable[ProviderMessageTraceDescriptor] = (),
) -> ObjectMapSection:
    """Build a read-only Object Map section from explicit provider descriptors."""

    normalized = _normalize_inputs(
        providers=providers,
        capabilities=capabilities,
        sessions=sessions,
        subscriptions=subscriptions,
        message_traces=message_traces,
    )
    summaries = _all_descriptor_summaries(normalized)
    relationships = provider_boundary_relationships_from_descriptors(
        providers=normalized.providers,
        capabilities=normalized.capabilities,
        sessions=normalized.sessions,
        subscriptions=normalized.subscriptions,
        message_traces=normalized.message_traces,
    )
    definitions = (
        *object_relationship_definitions_by_type("references"),
        *object_relationship_definitions_by_type("has_permission"),
    )
    return ObjectMapSection(
        section_id=PROVIDER_BOUNDARY_TRACE_SECTION_ID,
        provider_id=PROVIDER_BOUNDARY_TRACE_PROVIDER_ID,
        owner_domain="core",
        title="Provider Boundary Descriptors",
        summaries=summaries,
        relationships=relationships,
        relationship_definitions=definitions,
        warnings=_descriptor_warnings(normalized),
        blockers=_descriptor_blockers(normalized),
        errors=_descriptor_errors(normalized),
        metadata={
            "provider_count": len(normalized.providers),
            "capability_count": len(normalized.capabilities),
            "session_count": len(normalized.sessions),
            "subscription_count": len(normalized.subscriptions),
            "message_trace_count": len(normalized.message_traces),
            "relationship_count": len(relationships),
            "descriptor_source": "explicit_descriptor_inputs",
            "read_only": True,
        },
        extra={
            "mutation_forbidden": True,
            "interrogation": "future",
            "runtime_summary": "not_implemented",
        },
    )


class _Inputs:
    def __init__(
        self,
        *,
        providers: tuple[ProviderDescriptor, ...],
        capabilities: tuple[ProviderCapabilityDescriptor, ...],
        sessions: tuple[ProviderSessionDescriptor, ...],
        subscriptions: tuple[ProviderSubscriptionDescriptor, ...],
        message_traces: tuple[ProviderMessageTraceDescriptor, ...],
    ) -> None:
        self.providers = providers
        self.capabilities = capabilities
        self.sessions = sessions
        self.subscriptions = subscriptions
        self.message_traces = message_traces
        self.provider_by_id = {provider.provider_id: provider for provider in providers}
        self.capability_by_id = {
            capability.capability_id: capability for capability in capabilities
        }
        self.session_by_id = {
            session.provider_session_id: session for session in sessions
        }
        self.subscription_by_id = {
            subscription.subscription_id: subscription
            for subscription in subscriptions
        }


def _normalize_inputs(
    *,
    providers: Iterable[ProviderDescriptor],
    capabilities: Iterable[ProviderCapabilityDescriptor],
    sessions: Iterable[ProviderSessionDescriptor],
    subscriptions: Iterable[ProviderSubscriptionDescriptor],
    message_traces: Iterable[ProviderMessageTraceDescriptor],
) -> _Inputs:
    normalized_providers = _normalize_tuple(providers, ProviderDescriptor, "providers")
    normalized_capabilities = _normalize_tuple(
        capabilities,
        ProviderCapabilityDescriptor,
        "capabilities",
    )
    normalized_sessions = _normalize_tuple(
        sessions,
        ProviderSessionDescriptor,
        "sessions",
    )
    normalized_subscriptions = _normalize_tuple(
        subscriptions,
        ProviderSubscriptionDescriptor,
        "subscriptions",
    )
    normalized_message_traces = _normalize_tuple(
        message_traces,
        ProviderMessageTraceDescriptor,
        "message_traces",
    )
    return _Inputs(
        providers=_sort_by_id(normalized_providers, "provider_id"),
        capabilities=_sort_by_id(normalized_capabilities, "capability_id"),
        sessions=_sort_by_id(normalized_sessions, "provider_session_id"),
        subscriptions=_sort_by_id(normalized_subscriptions, "subscription_id"),
        message_traces=_sort_by_id(normalized_message_traces, "message_trace_id"),
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


def _sort_by_id(values: tuple[object, ...], field_name: str) -> tuple[object, ...]:
    return tuple(sorted(values, key=lambda value: getattr(value, field_name)))


def _require_type(value: object, expected_type: type[object], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be a {expected_type.__name__}")


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


def _append_connection_reference(
    relationships: list[TraceableRelationshipRef],
    source_ref: TraceableObjectRef,
    connection_id: str,
) -> None:
    _append_reference(
        relationships,
        source_ref,
        TraceableObjectRef(
            object_id=connection_id,
            object_kind=CONNECTION_OBJECT_KIND,
            owner_domain="core.connection",
            owner_component="connection_tracking",
            label=connection_id,
            metadata={"connection_id": connection_id, "ownership": "reference_only"},
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


def _descriptor_errors(normalized: _Inputs) -> tuple[str, ...]:
    return tuple(
        f"{summary.object_ref.object_kind} {summary.object_ref.object_id}: {error}"
        for summary in _all_descriptor_summaries(normalized)
        for error in _string_tuple(summary.metadata.get("errors"))
    )


def _all_descriptor_summaries(normalized: _Inputs) -> tuple[TraceableObjectSummary, ...]:
    return (
        *(provider_trace_summary_from_descriptor(provider) for provider in normalized.providers),
        *(
            provider_capability_trace_summary_from_descriptor(capability)
            for capability in normalized.capabilities
        ),
        *(
            provider_session_trace_summary_from_descriptor(session)
            for session in normalized.sessions
        ),
        *(
            provider_subscription_trace_summary_from_descriptor(subscription)
            for subscription in normalized.subscriptions
        ),
        *(
            provider_message_trace_summary_from_descriptor(message_trace)
            for message_trace in normalized.message_traces
        ),
    )


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
    "CONNECTION_OBJECT_KIND",
    "OBJECT_FAMILY_OBJECT_KIND",
    "PERMISSION_OBJECT_KIND",
    "PROVIDER_BOUNDARY_TRACE_PROVIDER_ID",
    "PROVIDER_BOUNDARY_TRACE_SECTION_ID",
    "PROVIDER_CAPABILITY_OBJECT_KIND",
    "PROVIDER_MESSAGE_TRACE_OBJECT_KIND",
    "PROVIDER_OBJECT_KIND",
    "PROVIDER_SESSION_OBJECT_KIND",
    "PROVIDER_SUBSCRIPTION_OBJECT_KIND",
    "build_provider_boundary_trace_provider_descriptor",
    "build_provider_boundary_trace_section",
    "provider_boundary_relationships_from_descriptors",
    "provider_capability_trace_ref_from_descriptor",
    "provider_capability_trace_summary_from_descriptor",
    "provider_message_trace_ref_from_descriptor",
    "provider_message_trace_summary_from_descriptor",
    "provider_session_trace_ref_from_descriptor",
    "provider_session_trace_summary_from_descriptor",
    "provider_subscription_trace_ref_from_descriptor",
    "provider_subscription_trace_summary_from_descriptor",
    "provider_trace_ref_from_descriptor",
    "provider_trace_summary_from_descriptor",
]
