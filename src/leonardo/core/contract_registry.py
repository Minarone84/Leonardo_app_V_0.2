"""Core contract registry for Leonardo V2.

The registry owns in-memory registration, lookup, field validation, and
compatibility reporting for contract descriptors. It does not perform dynamic
loading, filesystem discovery, application startup, or domain-specific
validation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from leonardo.contracts.kernel import (
    ContractCompatibilityReport,
    ContractCompatibilityStatus,
    ContractDescriptor,
    ContractStatus,
    ContractValidationIssue,
    ContractValidationReport,
)

PayloadValidator = Callable[
    [Mapping[str, object], ContractDescriptor],
    ContractValidationReport,
]


@dataclass(frozen=True)
class RegisteredContract:
    """
    Store a descriptor and optional payload validator registered with Core.

    The descriptor carries the public contract identity. The validator is an
    optional extension point for contract-specific checks after generic required,
    optional, and unknown-field validation has completed.
    """

    descriptor: ContractDescriptor
    validator: PayloadValidator | None = None


class ContractRegistry:
    """
    Register, inspect, validate, and compare Leonardo V2 contract descriptors.

    The registry is intentionally local and explicit. It has no global instance,
    no import-time registrations, and no filesystem or plugin discovery behavior.
    """

    def __init__(self) -> None:
        self._contracts: dict[tuple[str, str], RegisteredContract] = {}

    def register_contract(
        self,
        descriptor: ContractDescriptor,
        *,
        validator: PayloadValidator | None = None,
    ) -> RegisteredContract:
        """
        Register a contract descriptor.

        Duplicate ``contract_id`` and ``version`` pairs are rejected. Replacement
        mode is intentionally unsupported in this phase.

        Raises
        ------
        ValueError
            Raised when the same contract identity is already registered.
        TypeError
            Raised when the descriptor or validator violates the registry
            contract.
        """

        if not isinstance(descriptor, ContractDescriptor):
            raise TypeError("descriptor must be a ContractDescriptor")
        if validator is not None and not callable(validator):
            raise TypeError("validator must be callable")

        key = descriptor.identity
        if key in self._contracts:
            contract_id, version = key
            raise ValueError(
                f"Contract already registered: {contract_id} version {version}"
            )

        registered = RegisteredContract(descriptor=descriptor, validator=validator)
        self._contracts[key] = registered
        return registered

    def get_contract(
        self,
        contract_id: str,
        version: str,
    ) -> RegisteredContract | None:
        """Return a registered contract by exact identity, if present."""

        return self._contracts.get((contract_id, version))

    def list_contracts(
        self,
        *,
        status: ContractStatus | None = None,
    ) -> tuple[RegisteredContract, ...]:
        """
        Return registered contracts in deterministic identity order.

        Parameters
        ----------
        status:
            Optional lifecycle status filter.
        """

        contracts = self._contracts.values()
        if status is not None:
            contracts = (
                registered
                for registered in contracts
                if registered.descriptor.status is status
            )
        return tuple(
            sorted(
                contracts,
                key=lambda registered: registered.descriptor.identity,
            )
        )

    def validate_payload(
        self,
        contract_id: str,
        version: str,
        payload: Mapping[str, object],
    ) -> ContractValidationReport:
        """
        Validate a payload against a registered contract descriptor.

        Unknown contracts and malformed payloads return structured validation
        reports. Contract-specific validator exceptions are not swallowed because
        they indicate validator implementation failures rather than payload
        validation failures.
        """

        registered = self.get_contract(contract_id, version)
        if registered is None:
            return ContractValidationReport(
                contract_id=contract_id,
                version=version,
                issues=(
                    ContractValidationIssue(
                        code="unknown_contract",
                        message=(
                            f"Contract is not registered: {contract_id} "
                            f"version {version}"
                        ),
                        severity="blocker",
                    ),
                ),
            )

        if not isinstance(payload, Mapping):
            return ContractValidationReport(
                contract_id=contract_id,
                version=version,
                issues=(
                    ContractValidationIssue(
                        code="invalid_payload_type",
                        message="Payload must be a mapping",
                        severity="error",
                    ),
                ),
            )

        descriptor = registered.descriptor
        issues = list(self._validate_field_surface(descriptor, payload))
        if registered.validator is not None and not _has_blocking_issue(issues):
            validator_report = registered.validator(payload, descriptor)
            if not isinstance(validator_report, ContractValidationReport):
                raise TypeError("validator must return ContractValidationReport")
            issues.extend(validator_report.issues)

        return ContractValidationReport(
            contract_id=contract_id,
            version=version,
            issues=tuple(issues),
        )

    def compatibility_report(
        self,
        contract_id: str,
        base_version: str,
        candidate: ContractDescriptor,
    ) -> ContractCompatibilityReport:
        """
        Compare a candidate descriptor with a registered base descriptor.

        The initial compatibility policy is conservative: contract identity,
        schema kind, required fields, and existing optional fields must remain
        stable. Adding optional fields is reported as backward compatible.
        """

        if not isinstance(candidate, ContractDescriptor):
            raise TypeError("candidate must be a ContractDescriptor")

        registered = self.get_contract(contract_id, base_version)
        if registered is None:
            return ContractCompatibilityReport(
                contract_id=contract_id,
                base_version=base_version,
                candidate_version=candidate.version,
                status=ContractCompatibilityStatus.UNKNOWN,
                messages=(
                    f"Base contract is not registered: {contract_id} "
                    f"version {base_version}",
                ),
            )

        base = registered.descriptor
        messages: list[str] = []
        if candidate.contract_id != contract_id:
            messages.append(
                "Candidate contract_id does not match the requested base contract"
            )
        if candidate.schema_kind is not base.schema_kind:
            messages.append("Candidate schema_kind differs from the base contract")
        if set(candidate.required_fields) != set(base.required_fields):
            messages.append("Candidate required_fields differ from the base contract")

        base_optional = set(base.optional_fields)
        candidate_optional = set(candidate.optional_fields)
        removed_optional = base_optional.difference(candidate_optional)
        if removed_optional:
            names = ", ".join(sorted(removed_optional))
            messages.append(f"Candidate removes optional fields: {names}")

        if messages:
            status = ContractCompatibilityStatus.INCOMPATIBLE
        elif candidate_optional.difference(base_optional):
            status = ContractCompatibilityStatus.BACKWARD_COMPATIBLE
            names = ", ".join(sorted(candidate_optional.difference(base_optional)))
            messages.append(f"Candidate adds optional fields: {names}")
        else:
            status = ContractCompatibilityStatus.COMPATIBLE

        return ContractCompatibilityReport(
            contract_id=contract_id,
            base_version=base_version,
            candidate_version=candidate.version,
            status=status,
            messages=tuple(messages),
        )

    def _validate_field_surface(
        self,
        descriptor: ContractDescriptor,
        payload: Mapping[str, object],
    ) -> tuple[ContractValidationIssue, ...]:
        issues: list[ContractValidationIssue] = []
        payload_fields: set[str] = set()

        for field_name in payload:
            if not isinstance(field_name, str):
                issues.append(
                    ContractValidationIssue(
                        code="invalid_field_name",
                        message="Payload field names must be strings",
                        severity="error",
                    )
                )
                continue
            payload_fields.add(field_name)

        for required_field in descriptor.required_fields:
            if required_field not in payload_fields:
                issues.append(
                    ContractValidationIssue(
                        code="missing_required_field",
                        message=f"Missing required field: {required_field}",
                        severity="error",
                        field_name=required_field,
                    )
                )

        known_fields = set(descriptor.known_fields)
        for unknown_field in sorted(payload_fields.difference(known_fields)):
            issues.append(
                ContractValidationIssue(
                    code="unknown_field",
                    message=f"Payload field is not declared by the contract: {unknown_field}",
                    severity="warning",
                    field_name=unknown_field,
                )
            )

        return tuple(issues)


def _has_blocking_issue(issues: list[ContractValidationIssue]) -> bool:
    return any(issue.blocks_validation for issue in issues)
