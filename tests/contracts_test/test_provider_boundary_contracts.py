import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.identity import Permission
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


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_BOUNDARY_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "provider_boundary.py"
)


def test_provider_descriptor_constructs_with_normalized_tuples() -> None:
    descriptor = ProviderDescriptor(
        provider_id="bybit",
        display_name="Bybit",
        description="Static provider boundary descriptor.",
        provider_kind="exchange",
        owner_domain="provider",
        owner_component="ProviderBoundary",
        lifecycle_status="available",
        supported_capability_ids=["market_data:historical_download"],  # type: ignore[arg-type]
        supported_connection_kinds=[ProviderConnectionKind.REST, "websocket"],  # type: ignore[list-item]
        supports_websocket=True,
        supports_polling=True,
        supports_batch=True,
        required_permissions=(Permission.CONNECTION_VIEW, "download:view"),
        object_family_ids=["provider", "provider_capability"],  # type: ignore[arg-type]
        docs_refs=["docs/contracts_docs/PROVIDER_BOUNDARY.md"],  # type: ignore[arg-type]
        test_refs=["tests/contracts_test/test_provider_boundary_contracts.py"],  # type: ignore[arg-type]
        metadata_refs=["src/leonardo/connection/exchange/metadata/bybit.exchange.json"],  # type: ignore[arg-type]
        warnings=["read-only"],  # type: ignore[arg-type]
    )

    assert descriptor.provider_kind is ProviderKind.EXCHANGE
    assert descriptor.lifecycle_status is ProviderLifecycleStatus.AVAILABLE
    assert descriptor.supported_capability_ids == (
        "market_data:historical_download",
    )
    assert descriptor.supported_connection_kinds == ("rest", "websocket")
    assert descriptor.required_permissions == ("connection:view", "download:view")
    assert descriptor.object_family_ids == ("provider", "provider_capability")
    assert descriptor.docs_refs == ("docs/contracts_docs/PROVIDER_BOUNDARY.md",)
    assert descriptor.warnings == ("read-only",)
    assert not hasattr(descriptor, "register")
    assert not hasattr(descriptor, "discover")


def test_provider_capability_descriptor_constructs_with_normalized_tuples() -> None:
    descriptor = ProviderCapabilityDescriptor(
        capability_id="market_data:historical_download",
        provider_id="bybit",
        capability_kind="historical_data",
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
        audit_policy="summary",
        object_family_ids=["provider_capability"],  # type: ignore[arg-type]
        docs_refs=["docs/contracts_docs/PROVIDER_BOUNDARY.md"],  # type: ignore[arg-type]
        warnings=["static facts only"],  # type: ignore[arg-type]
    )

    assert descriptor.capability_kind is ProviderCapabilityKind.HISTORICAL_DATA
    assert descriptor.required_permission == "download:view"
    assert descriptor.connection_required is True
    assert descriptor.supports_batch is True
    assert descriptor.object_family_ids == ("provider_capability",)
    assert not hasattr(descriptor, "execute")
    assert not hasattr(descriptor, "start")
    assert not hasattr(descriptor, "submit")


def test_provider_session_descriptor_uses_safe_read_only_metadata() -> None:
    descriptor = ProviderSessionDescriptor(
        provider_session_id="provider-session-1",
        provider_id="bybit",
        connection_id="connection-1",
        actor_id="admin-dev",
        session_id="session-admin-dev",
        status="connected",
        authentication_mode=ProviderAuthenticationMode.EXTERNAL,
        started_at="2026-07-07T10:00:00+00:00",
        last_heartbeat_at="2026-07-07T10:01:00+00:00",
        active_capability_ids=["market_data:historical_download"],  # type: ignore[arg-type]
        warning_count=1,
        warnings=["degraded mode not active"],  # type: ignore[arg-type]
        metadata={"environment": "testnet", "limits": {"requests": 120}},
    )

    assert descriptor.status is ProviderSessionStatus.CONNECTED
    assert descriptor.authentication_mode is ProviderAuthenticationMode.EXTERNAL
    assert descriptor.active_capability_ids == ("market_data:historical_download",)
    assert descriptor.metadata["environment"] == "testnet"
    assert descriptor.metadata["limits"]["requests"] == 120  # type: ignore[index]
    with pytest.raises(TypeError):
        descriptor.metadata["other"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        descriptor.metadata["limits"]["other"] = 1  # type: ignore[index]
    assert not hasattr(descriptor, "connect")
    assert not hasattr(descriptor, "disconnect")


def test_provider_subscription_descriptor_constructs_reference_only_binding() -> None:
    descriptor = ProviderSubscriptionDescriptor(
        subscription_id="subscription-1",
        provider_id="bybit",
        provider_session_id="provider-session-1",
        capability_id="market_data:live_stream",
        connection_id="connection-1",
        websocket_channel_id="channel-1",
        topic="kline.1.BTCUSDT",
        subscription_kind=ProviderCapabilityKind.WEBSOCKET_SUBSCRIBE,
        status="active",
        created_at="2026-07-07T10:00:00+00:00",
        updated_at="2026-07-07T10:01:00+00:00",
        last_message_at="2026-07-07T10:02:00+00:00",
        message_count=3,
        required_permission=Permission.CONNECTION_SUBSCRIBE,
        object_family_ids=["provider_subscription", "websocket_channel"],  # type: ignore[arg-type]
        warnings=["summary only"],  # type: ignore[arg-type]
    )

    assert descriptor.status is ProviderSubscriptionStatus.ACTIVE
    assert descriptor.subscription_kind is ProviderCapabilityKind.WEBSOCKET_SUBSCRIBE
    assert descriptor.websocket_channel_id == "channel-1"
    assert descriptor.required_permission == "connection:subscribe"
    assert descriptor.object_family_ids == (
        "provider_subscription",
        "websocket_channel",
    )
    assert not hasattr(descriptor, "subscribe")
    assert not hasattr(descriptor, "unsubscribe")
    assert not hasattr(descriptor, "reconnect")


def test_provider_message_trace_descriptor_records_payload_metadata_only() -> None:
    descriptor = ProviderMessageTraceDescriptor(
        message_trace_id="message-trace-1",
        provider_id="bybit",
        provider_session_id="provider-session-1",
        subscription_id="subscription-1",
        connection_id="connection-1",
        websocket_channel_id="channel-1",
        direction="inbound",
        message_kind="data",
        observed_at="2026-07-07T10:02:00+00:00",
        payload_kind="json_object",
        payload_size_bytes=512,
        payload_key_count=3,
        payload_keys=["topic", "type", "data"],  # type: ignore[arg-type]
        correlation_id="corr-1",
    )

    assert descriptor.direction is ProviderMessageDirection.INBOUND
    assert descriptor.message_kind is ProviderMessageTraceKind.DATA
    assert descriptor.payload_size_bytes == 512
    assert descriptor.payload_key_count == 3
    assert descriptor.payload_keys == ("topic", "type", "data")
    assert not hasattr(descriptor, "payload")
    assert not hasattr(descriptor, "body")
    assert not hasattr(descriptor, "response")


def test_required_ids_reject_empty_or_blank_strings() -> None:
    with pytest.raises(ValueError, match="provider_id"):
        ProviderDescriptor(
            provider_id=" ",
            display_name="Bybit",
            description="Provider.",
            provider_kind=ProviderKind.EXCHANGE,
            owner_domain="provider",
            owner_component="Boundary",
        )
    with pytest.raises(ValueError, match="capability_id"):
        ProviderCapabilityDescriptor(
            capability_id="",
            provider_id="bybit",
            capability_kind=ProviderCapabilityKind.HISTORICAL_DATA,
            label="Historical",
            description="Capability.",
            required_permission="download:view",
        )
    with pytest.raises(ValueError, match="provider_session_id"):
        ProviderSessionDescriptor(provider_session_id="", provider_id="bybit")
    with pytest.raises(ValueError, match="subscription_id"):
        ProviderSubscriptionDescriptor(subscription_id="", provider_id="bybit")
    with pytest.raises(ValueError, match="message_trace_id"):
        ProviderMessageTraceDescriptor(message_trace_id="", provider_id="bybit")


def test_optional_ids_reject_blank_strings_when_present() -> None:
    with pytest.raises(ValueError, match="connection_id"):
        ProviderSessionDescriptor(
            provider_session_id="provider-session-1",
            provider_id="bybit",
            connection_id=" ",
        )
    with pytest.raises(ValueError, match="websocket_channel_id"):
        ProviderSubscriptionDescriptor(
            subscription_id="subscription-1",
            provider_id="bybit",
            websocket_channel_id=" ",
        )
    with pytest.raises(ValueError, match="subscription_id"):
        ProviderMessageTraceDescriptor(
            message_trace_id="message-trace-1",
            provider_id="bybit",
            subscription_id=" ",
        )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: ProviderSessionDescriptor(
            provider_session_id="provider-session-1",
            provider_id="bybit",
            warning_count=-1,
        ),
        lambda: ProviderSubscriptionDescriptor(
            subscription_id="subscription-1",
            provider_id="bybit",
            message_count=-1,
        ),
        lambda: ProviderMessageTraceDescriptor(
            message_trace_id="message-trace-1",
            provider_id="bybit",
            payload_size_bytes=-1,
        ),
        lambda: ProviderMessageTraceDescriptor(
            message_trace_id="message-trace-1",
            provider_id="bybit",
            payload_key_count=-1,
        ),
    ),
)
def test_negative_counts_are_rejected(factory: object) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        factory()


def test_provider_capability_descriptor_requires_required_permission() -> None:
    with pytest.raises(ValueError, match="required_permission"):
        ProviderCapabilityDescriptor(
            capability_id="market_data:historical_download",
            provider_id="bybit",
            capability_kind=ProviderCapabilityKind.HISTORICAL_DATA,
            label="Historical",
            description="Capability.",
            required_permission=" ",
        )


def test_session_metadata_rejects_sensitive_keys() -> None:
    with pytest.raises(ValueError, match="sensitive provider metadata"):
        ProviderSessionDescriptor(
            provider_session_id="provider-session-1",
            provider_id="bybit",
            metadata={"api_key": "not allowed"},
        )
    with pytest.raises(ValueError, match="sensitive provider metadata"):
        ProviderSessionDescriptor(
            provider_session_id="provider-session-1",
            provider_id="bybit",
            metadata={"nested": {"access_token": "not allowed"}},
        )


def test_descriptor_objects_are_frozen_read_only() -> None:
    descriptor = ProviderDescriptor(
        provider_id="bybit",
        display_name="Bybit",
        description="Provider.",
        provider_kind=ProviderKind.EXCHANGE,
        owner_domain="provider",
        owner_component="Boundary",
    )

    with pytest.raises(FrozenInstanceError):
        descriptor.provider_id = "changed"  # type: ignore[misc]


def test_provider_connection_is_not_modelled_as_a_suite() -> None:
    descriptor = ProviderDescriptor(
        provider_id="bybit",
        display_name="Bybit",
        description="Provider.",
        provider_kind=ProviderKind.EXCHANGE,
        owner_domain="provider",
        owner_component="Boundary",
        object_family_ids=("provider", "provider_capability"),
    )

    assert descriptor.provider_kind is not None
    assert not hasattr(descriptor, "suite_id")
    assert not hasattr(descriptor, "module_ids")
    assert "suite" not in descriptor.object_family_ids


def test_connection_and_channel_ids_are_references_only() -> None:
    session = ProviderSessionDescriptor(
        provider_session_id="provider-session-1",
        provider_id="bybit",
        connection_id="connection-1",
    )
    subscription = ProviderSubscriptionDescriptor(
        subscription_id="subscription-1",
        provider_id="bybit",
        connection_id="connection-1",
        websocket_channel_id="channel-1",
    )

    assert session.connection_id == "connection-1"
    assert subscription.websocket_channel_id == "channel-1"
    assert not hasattr(session, "connection")
    assert not hasattr(subscription, "websocket_channel")


def test_contract_module_has_no_mutable_registry_or_runtime_behavior() -> None:
    source = _PROVIDER_BOUNDARY_CONTRACT.read_text(encoding="utf-8")

    assert "ProviderRegistry" not in source
    assert "register_provider" not in source
    assert "discover" not in source
    for token in (
        "requests",
        "aiohttp",
        "websockets",
        "subprocess",
        "Path.rglob",
        "pkgutil",
        "importlib",
        "os.walk",
        "globals()",
    ):
        assert token not in source


def test_contract_module_imports_no_core_runtime_gui_or_provider_implementation() -> None:
    source = _PROVIDER_BOUNDARY_CONTRACT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = _imported_modules(tree)
    forbidden_imports = (
        "leonardo.core",
        "leonardo.gui",
        "leonardo.connection",
        "PySide6",
        "PyQt6",
    )
    forbidden_runtime_names = (
        "TaskManager",
        "OperationRegistry",
        "StateStore",
        "AuditLog",
        "RuntimeManager",
        "ReadOnlyObjectMapService",
        "CoreRuntimeBridge",
        "CoreRunner",
        "ConnectionRegistry",
    )

    assert all(
        forbidden not in module
        for forbidden in forbidden_imports
        for module in imported_modules
    )
    assert all(name not in source for name in forbidden_runtime_names)


def test_contract_module_does_not_add_download_data_workflow_behavior() -> None:
    source = _PROVIDER_BOUNDARY_CONTRACT.read_text(encoding="utf-8")

    assert "DownloadManager" not in source
    assert "DownloadExecutionManager" not in source
    assert "Download Data" not in source
    assert "download_data" not in source


def _imported_modules(tree: ast.AST) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return tuple(modules)
