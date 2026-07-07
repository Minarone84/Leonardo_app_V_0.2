from pathlib import Path

from leonardo.contracts.identity import Permission
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.provider_boundary import (
    ProviderAuthenticationMode,
    ProviderCapabilityDescriptor,
    ProviderCapabilityKind,
    ProviderConnectionKind,
    ProviderDescriptor,
    ProviderKind,
    ProviderLifecycleStatus,
    ProviderMessageDirection,
    ProviderMessageTraceDescriptor,
    ProviderMessageTraceKind,
    ProviderSessionDescriptor,
    ProviderSessionStatus,
    ProviderSubscriptionDescriptor,
    ProviderSubscriptionStatus,
)
from leonardo.core.object_map_service import (
    ObjectMapProviderEntry,
    ReadOnlyObjectMapService,
)
from leonardo.core.provider_boundary_trace import (
    CONNECTION_OBJECT_KIND,
    PROVIDER_BOUNDARY_TRACE_PROVIDER_ID,
    PROVIDER_CAPABILITY_OBJECT_KIND,
    PROVIDER_MESSAGE_TRACE_OBJECT_KIND,
    PROVIDER_OBJECT_KIND,
    PROVIDER_SESSION_OBJECT_KIND,
    PROVIDER_SUBSCRIPTION_OBJECT_KIND,
    build_provider_boundary_trace_provider_descriptor,
    build_provider_boundary_trace_section,
    provider_boundary_relationships_from_descriptors,
    provider_capability_trace_ref_from_descriptor,
    provider_capability_trace_summary_from_descriptor,
    provider_message_trace_ref_from_descriptor,
    provider_message_trace_summary_from_descriptor,
    provider_session_trace_ref_from_descriptor,
    provider_session_trace_summary_from_descriptor,
    provider_subscription_trace_ref_from_descriptor,
    provider_subscription_trace_summary_from_descriptor,
    provider_trace_ref_from_descriptor,
    provider_trace_summary_from_descriptor,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_HELPER = _REPO_ROOT / "src" / "leonardo" / "core" / "provider_boundary_trace.py"


def test_provider_descriptor_is_read_only_and_mutation_forbidden() -> None:
    descriptor = build_provider_boundary_trace_provider_descriptor()

    assert descriptor.provider_id == PROVIDER_BOUNDARY_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.owner_component == "ProviderBoundaryTrace"
    assert descriptor.object_kinds == (
        "provider",
        "provider_capability",
        "provider_session",
        "provider_subscription",
        "provider_message_trace",
    )
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.supports_interrogation is False
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True


def test_provider_ref_and_summary_preserve_identity_and_owner_fields() -> None:
    provider = _provider()

    ref = provider_trace_ref_from_descriptor(provider)
    summary = provider_trace_summary_from_descriptor(provider)

    assert ref.object_id == "bybit"
    assert ref.object_kind == PROVIDER_OBJECT_KIND
    assert ref.owner_domain == "provider"
    assert ref.owner_component == "BybitProviderBoundary"
    assert ref.schema_version == "1.0"
    assert ref.label == "Bybit"
    assert summary.object_ref == ref
    assert summary.lifecycle_status == "available"
    assert summary.runtime_or_persistent == "static_metadata"
    assert summary.permission_refs == ("connection:view", "download:view")
    assert summary.metadata["supported_capability_ids"] == (
        "bybit.historical_ohlcv",
        "bybit.kline_stream",
    )


def test_capability_ref_and_summary_preserve_provider_and_permission_fields() -> None:
    capability = _historical_capability()

    ref = provider_capability_trace_ref_from_descriptor(capability)
    summary = provider_capability_trace_summary_from_descriptor(capability)

    assert ref.object_id == "bybit.historical_ohlcv"
    assert ref.object_kind == PROVIDER_CAPABILITY_OBJECT_KIND
    assert ref.metadata["provider_id"] == "bybit"
    assert ref.metadata["required_permission"] == "download:view"
    assert summary.metadata["provider_id"] == "bybit"
    assert summary.metadata["required_permission"] == "download:view"
    assert summary.metadata["capability_kind"] == "historical_data"
    assert summary.permission_refs == ("download:view",)


def test_session_summary_contains_safe_metadata_without_sensitive_material() -> None:
    session = _session()

    ref = provider_session_trace_ref_from_descriptor(session)
    summary = provider_session_trace_summary_from_descriptor(session)

    assert ref.object_id == "provider-session-1"
    assert ref.object_kind == PROVIDER_SESSION_OBJECT_KIND
    assert summary.lifecycle_status == "connected"
    assert summary.metadata["authentication_mode"] == "external"
    assert summary.metadata["safe_metadata"]["environment"] == "testnet"  # type: ignore[index]
    summary_text = str(summary.to_dict()).lower()
    assert "secret-value" not in summary_text
    assert "raw-response" not in summary_text


def test_subscription_summary_is_reference_only_without_execution_behavior() -> None:
    subscription = _subscription()

    ref = provider_subscription_trace_ref_from_descriptor(subscription)
    summary = provider_subscription_trace_summary_from_descriptor(subscription)

    assert ref.object_id == "subscription-1"
    assert ref.object_kind == PROVIDER_SUBSCRIPTION_OBJECT_KIND
    assert summary.lifecycle_status == "active"
    assert summary.metadata["provider_session_id"] == "provider-session-1"
    assert summary.metadata["capability_id"] == "bybit.kline_stream"
    assert summary.extra["execution"] == "not_implemented"
    assert not hasattr(summary, "subscribe")
    assert not hasattr(summary, "unsubscribe")


def test_message_summary_contains_bounded_payload_metadata_only() -> None:
    message_trace = _message_trace()

    ref = provider_message_trace_ref_from_descriptor(message_trace)
    summary = provider_message_trace_summary_from_descriptor(message_trace)

    assert ref.object_id == "message-trace-1"
    assert ref.object_kind == PROVIDER_MESSAGE_TRACE_OBJECT_KIND
    assert summary.metadata["payload_kind"] == "json_object"
    assert summary.metadata["payload_size_bytes"] == 512
    assert summary.metadata["payload_key_count"] == 3
    assert summary.metadata["payload_keys"] == ("topic", "type", "data")
    assert "raw_payload" not in summary.metadata
    assert "body" not in summary.metadata
    assert "response" not in summary.metadata


def test_relationships_include_provider_to_declared_capability() -> None:
    relationships = _relationships()
    pairs = _relationship_pairs(relationships)

    assert (
        "references",
        "provider",
        "bybit",
        "provider_capability",
        "bybit.historical_ohlcv",
    ) in pairs
    assert (
        "references",
        "provider",
        "bybit",
        "provider_capability",
        "bybit.kline_stream",
    ) in pairs


def test_relationships_include_permission_links() -> None:
    relationships = _relationships()
    pairs = _relationship_pairs(relationships)

    assert (
        "has_permission",
        "provider",
        "bybit",
        "permission",
        "connection:view",
    ) in pairs
    assert (
        "has_permission",
        "provider_capability",
        "bybit.historical_ohlcv",
        "permission",
        "download:view",
    ) in pairs
    assert (
        "has_permission",
        "provider_subscription",
        "subscription-1",
        "permission",
        "connection:subscribe",
    ) in pairs


def test_missing_optional_ids_do_not_create_fake_descriptor_relationships() -> None:
    session = ProviderSessionDescriptor(
        provider_session_id="provider-session-2",
        provider_id="missing-provider",
        active_capability_ids=("missing-capability",),
    )
    subscription = ProviderSubscriptionDescriptor(
        subscription_id="subscription-2",
        provider_id="missing-provider",
        provider_session_id="missing-session",
        capability_id="missing-capability",
    )

    relationships = provider_boundary_relationships_from_descriptors(
        sessions=(session,),
        subscriptions=(subscription,),
    )

    assert all(
        relationship.target_ref.object_id
        not in {"missing-provider", "missing-capability", "missing-session"}
        for relationship in relationships
    )


def test_connection_refs_are_reference_only_without_connection_owner_import() -> None:
    relationships = _relationships()
    connection_relationships = [
        relationship
        for relationship in relationships
        if relationship.target_ref.object_kind == CONNECTION_OBJECT_KIND
    ]
    source = _TRACE_HELPER.read_text(encoding="utf-8")

    assert connection_relationships
    assert all(
        relationship.target_ref.metadata["ownership"] == "reference_only"
        for relationship in connection_relationships
    )
    assert "Connection" + "Registry" not in source


def test_section_aggregates_explicit_descriptor_inputs_only() -> None:
    section = build_provider_boundary_trace_section(
        providers=(_provider(),),
        capabilities=(_historical_capability(), _stream_capability()),
        sessions=(_session(),),
        subscriptions=(_subscription(),),
        message_traces=(_message_trace(),),
    )

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "core.provider_boundary"
    assert section.provider_id == PROVIDER_BOUNDARY_TRACE_PROVIDER_ID
    assert section.owner_domain == "core"
    assert section.metadata["provider_count"] == 1
    assert section.metadata["capability_count"] == 2
    assert section.metadata["session_count"] == 1
    assert section.metadata["subscription_count"] == 1
    assert section.metadata["message_trace_count"] == 1
    assert [summary.object_ref.object_id for summary in section.summaries] == [
        "bybit",
        "bybit.historical_ohlcv",
        "bybit.kline_stream",
        "provider-session-1",
        "subscription-1",
        "message-trace-1",
    ]


def test_section_warnings_blockers_and_errors_are_derived_from_descriptors() -> None:
    provider = _provider(warnings=("metadata-only",), blockers=("adapter not scoped",))
    session = _session(warnings=(), errors=("heartbeat stale",))

    section = build_provider_boundary_trace_section(
        providers=(provider,),
        sessions=(session,),
    )

    assert section.warnings == ("provider bybit: metadata-only",)
    assert section.blockers == ("provider bybit: adapter not scoped",)
    assert section.errors == ("provider_session provider-session-1: heartbeat stale",)


def test_outputs_are_frozen_and_read_only_through_existing_contracts() -> None:
    section = build_provider_boundary_trace_section(providers=(_provider(),))
    summary = section.summaries[0]

    assert section.extra["mutation_forbidden"] is True
    assert summary.metadata["read_only"] is True
    assert summary.extra["mutation_forbidden"] is True
    try:
        summary.metadata["read_only"] = False  # type: ignore[index]
    except TypeError:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("summary metadata must be immutable")


def test_no_mutable_registry_scanning_or_auto_lookup_behavior() -> None:
    source = _TRACE_HELPER.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo." + "gui",
        "import leonardo." + "gui",
        "PySide6",
        "Task" + "Manager",
        "Operation" + "Registry",
        "State" + "Store",
        "Audit" + "Log",
        "Runtime" + "Manager",
        "Runtime" + "ManagerBackend",
        "ReadOnlyObject" + "MapService",
        "CoreRuntime" + "Bridge",
        "Core" + "Runner",
        "Connection" + "Registry",
        "Provider" + "Registry",
        "register" + "_provider",
        "dis" + "cover(",
        "pkg" + "util",
        "import" + "lib",
        "os." + "walk",
        "Path." + "rglob",
        "glo" + "bals" + "()",
        "sub" + "process",
        "soc" + "ket.",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "shell" + "=True",
    )

    for token in blocked_tokens:
        assert token not in source


def test_read_only_object_map_service_can_consume_explicit_provider_entry() -> None:
    provider_descriptor = build_provider_boundary_trace_provider_descriptor()
    service = ReadOnlyObjectMapService(
        (
            ObjectMapProviderEntry(
                descriptor=provider_descriptor,
                build_section=lambda: build_provider_boundary_trace_section(
                    providers=(_provider(),),
                    capabilities=(_historical_capability(), _stream_capability()),
                    sessions=(_session(),),
                    subscriptions=(_subscription(),),
                    message_traces=(_message_trace(),),
                ),
            ),
        )
    )

    snapshot = service.build_snapshot(generated_at_utc="2026-01-01T00:00:00+00:00")
    report = service.query()

    assert snapshot.provider_descriptors == (provider_descriptor,)
    assert snapshot.sections[0].provider_id == provider_descriptor.provider_id
    assert snapshot.metadata["summary_count"] == 6
    assert any(
        summary.object_ref.object_kind == "provider_message_trace"
        for summary in report.summaries
    )


def _relationships():
    return provider_boundary_relationships_from_descriptors(
        providers=(_provider(),),
        capabilities=(_historical_capability(), _stream_capability()),
        sessions=(_session(),),
        subscriptions=(_subscription(),),
        message_traces=(_message_trace(),),
    )


def _relationship_pairs(relationships):
    return {
        (
            relationship.relationship_type,
            relationship.source_ref.object_kind,
            relationship.source_ref.object_id,
            relationship.target_ref.object_kind,
            relationship.target_ref.object_id,
        )
        for relationship in relationships
    }


def _provider(
    *,
    warnings: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id="bybit",
        display_name="Bybit",
        description="Static provider boundary descriptor.",
        provider_kind=ProviderKind.EXCHANGE,
        owner_domain="provider",
        owner_component="BybitProviderBoundary",
        lifecycle_status=ProviderLifecycleStatus.AVAILABLE,
        supported_capability_ids=("bybit.historical_ohlcv", "bybit.kline_stream"),
        supported_connection_kinds=(
            ProviderConnectionKind.REST,
            ProviderConnectionKind.WEBSOCKET,
        ),
        supports_websocket=True,
        supports_polling=True,
        supports_batch=True,
        required_permissions=(Permission.CONNECTION_VIEW, Permission.DOWNLOAD_VIEW),
        object_family_ids=("provider", "provider_capability"),
        docs_refs=("docs/contracts_docs/PROVIDER_BOUNDARY.md",),
        test_refs=("tests/core_test/test_provider_boundary_object_map_pattern.py",),
        metadata_refs=("src/leonardo/provider_metadata/bybit.toml",),
        warnings=warnings,
        blockers=blockers,
    )


def _historical_capability() -> ProviderCapabilityDescriptor:
    return ProviderCapabilityDescriptor(
        capability_id="bybit.historical_ohlcv",
        provider_id="bybit",
        capability_kind=ProviderCapabilityKind.HISTORICAL_DATA,
        label="Historical OHLCV",
        description="Declared historical market data capability.",
        required_permission=Permission.DOWNLOAD_VIEW,
        connection_required=True,
        websocket_required=False,
        supports_streaming=False,
        supports_batch=True,
        input_schema_ref="leonardo.downloads.request",
        result_schema_ref="leonardo.downloads.preflight",
        rate_limit_ref="bybit.public.rate_limit",
        audit_category="provider.capability",
        object_family_ids=("provider_capability", "ohlcv_dataset"),
    )


def _stream_capability() -> ProviderCapabilityDescriptor:
    return ProviderCapabilityDescriptor(
        capability_id="bybit.kline_stream",
        provider_id="bybit",
        capability_kind=ProviderCapabilityKind.WEBSOCKET_SUBSCRIBE,
        label="Kline Stream",
        description="Declared kline stream capability.",
        required_permission=Permission.CONNECTION_SUBSCRIBE,
        connection_required=True,
        websocket_required=True,
        supports_streaming=True,
        supports_batch=False,
        audit_category="provider.subscription",
        object_family_ids=("provider_capability", "provider_subscription"),
    )


def _session(
    *,
    warnings: tuple[str, ...] = ("degraded mode not active",),
    errors: tuple[str, ...] = (),
) -> ProviderSessionDescriptor:
    return ProviderSessionDescriptor(
        provider_session_id="provider-session-1",
        provider_id="bybit",
        connection_id="connection-1",
        actor_id="admin-dev",
        session_id="session-admin-dev",
        status=ProviderSessionStatus.CONNECTED,
        authentication_mode=ProviderAuthenticationMode.EXTERNAL,
        started_at="2026-07-07T10:00:00+00:00",
        last_heartbeat_at="2026-07-07T10:01:00+00:00",
        active_capability_ids=("bybit.historical_ohlcv", "bybit.kline_stream"),
        warning_count=1,
        error_count=len(errors),
        warnings=warnings,
        errors=errors,
        metadata={"environment": "testnet", "limits": {"requests": 120}},
    )


def _subscription() -> ProviderSubscriptionDescriptor:
    return ProviderSubscriptionDescriptor(
        subscription_id="subscription-1",
        provider_id="bybit",
        provider_session_id="provider-session-1",
        capability_id="bybit.kline_stream",
        connection_id="connection-1",
        websocket_channel_id="channel-1",
        topic="kline.1.BTCUSDT",
        subscription_kind=ProviderCapabilityKind.WEBSOCKET_SUBSCRIBE,
        status=ProviderSubscriptionStatus.ACTIVE,
        created_at="2026-07-07T10:00:00+00:00",
        updated_at="2026-07-07T10:01:00+00:00",
        last_message_at="2026-07-07T10:02:00+00:00",
        message_count=3,
        required_permission=Permission.CONNECTION_SUBSCRIBE,
        object_family_ids=("provider_subscription",),
    )


def _message_trace() -> ProviderMessageTraceDescriptor:
    return ProviderMessageTraceDescriptor(
        message_trace_id="message-trace-1",
        provider_id="bybit",
        provider_session_id="provider-session-1",
        subscription_id="subscription-1",
        connection_id="connection-1",
        websocket_channel_id="channel-1",
        direction=ProviderMessageDirection.INBOUND,
        message_kind=ProviderMessageTraceKind.DATA,
        observed_at="2026-07-07T10:02:00+00:00",
        payload_kind="json_object",
        payload_size_bytes=512,
        payload_key_count=3,
        payload_keys=("topic", "type", "data"),
        correlation_id="corr-1",
    )
