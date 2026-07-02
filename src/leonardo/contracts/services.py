"""Service descriptor contracts for the Leonardo V2 Core foundation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ServiceKind(str, Enum):
    """Supported service categories for the initial registry."""

    LIFECYCLE = "lifecycle"
    CAPABILITY = "capability"


@dataclass(frozen=True)
class ServiceDescriptor:
    """Describe a service registered with the Core service registry."""

    service_id: str
    kind: ServiceKind
    display_name: str = ""
    description: str = ""
    contract_id: str | None = None
    contract_version: str | None = None
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.service_id or not self.service_id.strip():
            raise ValueError("service_id must be a non-empty string")
        if not isinstance(self.kind, ServiceKind):
            raise TypeError("kind must be a ServiceKind")
        object.__setattr__(
            self,
            "dependencies",
            _normalize_dependencies(self.dependencies),
        )


def _normalize_dependencies(dependencies: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise TypeError("dependencies entries must be strings")
        if not dependency or not dependency.strip():
            raise ValueError("dependencies entries must be non-empty strings")
        if dependency in seen:
            raise ValueError(f"Duplicate dependency: {dependency}")
        seen.add(dependency)
        normalized.append(dependency)
    return tuple(normalized)
