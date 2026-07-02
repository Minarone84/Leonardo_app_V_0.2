import pytest

from leonardo.contracts.services import ServiceDescriptor, ServiceKind
from leonardo.core.service_registry import ServiceRegistry


def test_service_registry_registers_and_lists_services_by_kind() -> None:
    registry = ServiceRegistry()
    lifecycle = object()
    capability = object()

    registry.register_service(
        ServiceDescriptor(
            service_id="state-store",
            kind=ServiceKind.LIFECYCLE,
        ),
        lifecycle,
    )
    registry.register_service(
        ServiceDescriptor(
            service_id="runtime-inspector",
            kind=ServiceKind.CAPABILITY,
        ),
        capability,
    )

    assert registry.get_service("state-store").service_object is lifecycle
    assert [
        service.descriptor.service_id
        for service in registry.list_services(kind=ServiceKind.LIFECYCLE)
    ] == ["state-store"]


def test_service_registry_rejects_duplicate_service_ids() -> None:
    registry = ServiceRegistry()
    descriptor = ServiceDescriptor(
        service_id="state-store",
        kind=ServiceKind.LIFECYCLE,
    )

    registry.register_service(descriptor, object())

    with pytest.raises(ValueError, match="already registered"):
        registry.register_service(descriptor, object())
