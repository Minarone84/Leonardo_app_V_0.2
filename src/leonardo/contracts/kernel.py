"""Contract-kernel value objects for Leonardo V2.

The kernel defines the small set of importable contract models used by Core to
register, inspect, validate, and compare contracts. It does not load contracts
from disk, discover plugins, import domain systems, or own application runtime
behavior.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Literal

IssueSeverity = Literal["warning", "error", "blocker"]

_BLOCKING_SEVERITIES = frozenset({"error", "blocker"})
_VALID_SEVERITIES = frozenset({"warning", "error", "blocker"})


class ContractStatus(str, Enum):
    """Lifecycle status for a registered contract descriptor."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class ContractOwner(str, Enum):
    """Owning subsystem category for a contract descriptor."""

    CORE = "core"
    RUNTIME = "runtime"
    DOMAIN = "domain"
    GUI = "gui"
    INTEGRATION = "integration"
    EXTERNAL = "external"


class ContractSchemaKind(str, Enum):
    """Supported schema categories for the initial contract kernel."""

    FIELD_SET = "field_set"
    JSON_OBJECT = "json_object"
    PYTHON_MAPPING = "python_mapping"


class ContractCompatibilityStatus(str, Enum):
    """Compatibility result for comparing a candidate descriptor with a base."""

    COMPATIBLE = "compatible"
    BACKWARD_COMPATIBLE = "backward_compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContractDescriptor:
    """
    Describe the identity, ownership, lifecycle, and field surface of a contract.

    Contract identity is the pair of ``contract_id`` and ``version``. Required
    and optional fields are stored as ordered tuples to keep descriptors stable
    and deterministic when listed or documented.
    """

    contract_id: str
    version: str
    owner: ContractOwner
    status: ContractStatus
    schema_kind: ContractSchemaKind
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not self.contract_id or not self.contract_id.strip():
            raise ValueError("contract_id must be a non-empty string")
        if not self.version or not self.version.strip():
            raise ValueError("version must be a non-empty string")
        if not isinstance(self.owner, ContractOwner):
            raise TypeError("owner must be a ContractOwner")
        if not isinstance(self.status, ContractStatus):
            raise TypeError("status must be a ContractStatus")
        if not isinstance(self.schema_kind, ContractSchemaKind):
            raise TypeError("schema_kind must be a ContractSchemaKind")

        required_fields = _normalize_fields(self.required_fields, "required_fields")
        optional_fields = _normalize_fields(self.optional_fields, "optional_fields")
        overlap = set(required_fields).intersection(optional_fields)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"Fields cannot be both required and optional: {names}")

        object.__setattr__(self, "required_fields", required_fields)
        object.__setattr__(self, "optional_fields", optional_fields)

    @property
    def identity(self) -> tuple[str, str]:
        """Return the stable registry key for this descriptor."""

        return (self.contract_id, self.version)

    @property
    def known_fields(self) -> tuple[str, ...]:
        """Return required and optional fields in contract declaration order."""

        return self.required_fields + self.optional_fields


@dataclass(frozen=True)
class ContractValidationIssue:
    """
    Describe one validation problem or warning for a contract payload.

    Blocking severities are ``error`` and ``blocker``. Warnings are structured
    but do not make a validation report invalid.
    """

    code: str
    message: str
    severity: IssueSeverity = "error"
    field_name: str | None = None

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("code must be a non-empty string")
        if not self.message or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if self.severity not in _VALID_SEVERITIES:
            allowed = ", ".join(sorted(_VALID_SEVERITIES))
            raise ValueError(f"severity must be one of: {allowed}")

    @property
    def blocks_validation(self) -> bool:
        """Return whether the issue makes its validation report invalid."""

        return self.severity in _BLOCKING_SEVERITIES


@dataclass(frozen=True)
class ContractValidationReport:
    """
    Structured validation result for one contract payload.

    Reports expose a computed ``valid`` property instead of relying on callers to
    keep a boolean synchronized with the issue list.
    """

    contract_id: str
    version: str | None
    issues: tuple[ContractValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        if not self.contract_id or not self.contract_id.strip():
            raise ValueError("contract_id must be a non-empty string")
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def valid(self) -> bool:
        """Return true when the report contains no blocking issues."""

        return not any(issue.blocks_validation for issue in self.issues)


@dataclass(frozen=True)
class ContractCompatibilityReport:
    """
    Structured compatibility result for a candidate contract descriptor.

    The report compares a candidate descriptor to a registered base descriptor.
    The ``messages`` field carries the concrete reasons for non-compatible or
    backward-compatible outcomes.
    """

    contract_id: str
    base_version: str | None
    candidate_version: str
    status: ContractCompatibilityStatus
    messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.contract_id or not self.contract_id.strip():
            raise ValueError("contract_id must be a non-empty string")
        if not self.candidate_version or not self.candidate_version.strip():
            raise ValueError("candidate_version must be a non-empty string")
        if not isinstance(self.status, ContractCompatibilityStatus):
            raise TypeError("status must be a ContractCompatibilityStatus")
        object.__setattr__(self, "messages", tuple(self.messages))

    @property
    def compatible(self) -> bool:
        """Return whether the candidate is compatible with the base descriptor."""

        return self.status in {
            ContractCompatibilityStatus.COMPATIBLE,
            ContractCompatibilityStatus.BACKWARD_COMPATIBLE,
        }


def _normalize_fields(fields: Iterable[str], field_group: str) -> tuple[str, ...]:
    if isinstance(fields, str):
        raise TypeError(f"{field_group} must be an iterable of field-name strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for field_name in fields:
        if not isinstance(field_name, str):
            raise TypeError(f"{field_group} entries must be strings")
        if not field_name or not field_name.strip():
            raise ValueError(f"{field_group} entries must be non-empty strings")
        if field_name in seen:
            raise ValueError(f"Duplicate field in {field_group}: {field_name}")
        seen.add(field_name)
        normalized.append(field_name)
    return tuple(normalized)
