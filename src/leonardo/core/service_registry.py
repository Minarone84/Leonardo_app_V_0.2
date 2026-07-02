"""Service registry base for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from dataclasses import dataclass

from leonardo.contracts.services import ServiceDescriptor, ServiceKind


@dataclass(frozen=True)
class RegisteredService:
    """Store a service descriptor and its runtime object."""

    descriptor: ServiceDescriptor
    service_object: object


class ServiceRegistry:
    """
    Register and inspect Core runtime services.

    The registry does not start, stop, or construct services in this phase.
    """

    def __init__(self) -> None:
        self._services: dict[str, RegisteredService] = {}

    def register_service(
        self,
        descriptor: ServiceDescriptor,
        service_object: object,
    ) -> RegisteredService:
        """Register a service object by descriptor."""

        if not isinstance(descriptor, ServiceDescriptor):
            raise TypeError("descriptor must be a ServiceDescriptor")
        if descriptor.service_id in self._services:
            raise ValueError(f"Service already registered: {descriptor.service_id}")

        registered = RegisteredService(
            descriptor=descriptor,
            service_object=service_object,
        )
        self._services[descriptor.service_id] = registered
        return registered

    def get_service(self, service_id: str) -> RegisteredService | None:
        """Return a registered service by service identifier, if present."""

        return self._services.get(service_id)

    def list_services(
        self,
        *,
        kind: ServiceKind | None = None,
    ) -> tuple[RegisteredService, ...]:
        """Return registered services in deterministic service-id order."""

        if kind is not None and not isinstance(kind, ServiceKind):
            raise TypeError("kind must be a ServiceKind")
        services = self._services.values()
        if kind is not None:
            services = (
                registered
                for registered in services
                if registered.descriptor.kind is kind
            )
        return tuple(
            sorted(
                services,
                key=lambda registered: registered.descriptor.service_id,
            )
        )
