import pytest

from leonardo.contracts.kernel import (
    ContractCompatibilityReport,
    ContractCompatibilityStatus,
    ContractDescriptor,
    ContractOwner,
    ContractSchemaKind,
    ContractStatus,
    ContractValidationIssue,
    ContractValidationReport,
)


def test_contract_descriptor_preserves_identity_and_declared_fields() -> None:
    descriptor = ContractDescriptor(
        contract_id="core.session",
        version="1.0",
        owner=ContractOwner.CORE,
        status=ContractStatus.ACTIVE,
        schema_kind=ContractSchemaKind.FIELD_SET,
        required_fields=("session_id",),
        optional_fields=("user_id",),
    )

    assert descriptor.identity == ("core.session", "1.0")
    assert descriptor.known_fields == ("session_id", "user_id")


def test_contract_descriptor_rejects_missing_identity() -> None:
    with pytest.raises(ValueError, match="contract_id"):
        ContractDescriptor(
            contract_id="",
            version="1.0",
            owner=ContractOwner.CORE,
            status=ContractStatus.ACTIVE,
            schema_kind=ContractSchemaKind.FIELD_SET,
        )


def test_contract_descriptor_rejects_overlapping_fields() -> None:
    with pytest.raises(ValueError, match="both required and optional"):
        ContractDescriptor(
            contract_id="core.session",
            version="1.0",
            owner=ContractOwner.CORE,
            status=ContractStatus.ACTIVE,
            schema_kind=ContractSchemaKind.FIELD_SET,
            required_fields=("session_id",),
            optional_fields=("session_id",),
        )


def test_validation_report_computes_valid_from_blocking_issues() -> None:
    report = ContractValidationReport(
        contract_id="core.session",
        version="1.0",
        issues=(
            ContractValidationIssue(
                code="missing_required_field",
                message="Missing required field: session_id",
                severity="error",
                field_name="session_id",
            ),
        ),
    )

    assert report.valid is False
    assert report.issues[0].blocks_validation is True


def test_validation_report_allows_structured_warnings() -> None:
    report = ContractValidationReport(
        contract_id="core.session",
        version="1.0",
        issues=(
            ContractValidationIssue(
                code="unknown_field",
                message="Payload field is not declared by the contract: extra",
                severity="warning",
                field_name="extra",
            ),
        ),
    )

    assert report.valid is True


def test_compatibility_report_exposes_compatible_property() -> None:
    report = ContractCompatibilityReport(
        contract_id="core.session",
        base_version="1.0",
        candidate_version="1.1",
        status=ContractCompatibilityStatus.BACKWARD_COMPATIBLE,
        messages=("Candidate adds optional fields: user_id",),
    )

    assert report.compatible is True
