import pytest

from leonardo.contracts.kernel import (
    ContractCompatibilityStatus,
    ContractDescriptor,
    ContractOwner,
    ContractSchemaKind,
    ContractStatus,
)
from leonardo.core.contract_registry import ContractRegistry


def _descriptor(
    *,
    version: str = "1.0",
    required_fields: tuple[str, ...] = ("session_id",),
    optional_fields: tuple[str, ...] = ("user_id",),
) -> ContractDescriptor:
    return ContractDescriptor(
        contract_id="core.session",
        version=version,
        owner=ContractOwner.CORE,
        status=ContractStatus.ACTIVE,
        schema_kind=ContractSchemaKind.FIELD_SET,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )


def test_register_get_and_list_contracts() -> None:
    registry = ContractRegistry()
    descriptor = _descriptor()

    registered = registry.register_contract(descriptor)

    assert registry.get_contract("core.session", "1.0") == registered
    assert registry.list_contracts() == (registered,)


def test_duplicate_registration_is_rejected() -> None:
    registry = ContractRegistry()
    descriptor = _descriptor()

    registry.register_contract(descriptor)

    with pytest.raises(ValueError, match="already registered"):
        registry.register_contract(descriptor)


def test_validate_payload_reports_missing_required_fields() -> None:
    registry = ContractRegistry()
    registry.register_contract(_descriptor())

    report = registry.validate_payload(
        "core.session",
        "1.0",
        {"user_id": "user-1"},
    )

    assert report.valid is False
    assert [issue.code for issue in report.issues] == ["missing_required_field"]
    assert report.issues[0].field_name == "session_id"


def test_validate_payload_reports_unknown_contract_as_blocker() -> None:
    registry = ContractRegistry()

    report = registry.validate_payload(
        "core.missing",
        "1.0",
        {"session_id": "session-1"},
    )

    assert report.valid is False
    assert report.issues[0].code == "unknown_contract"
    assert report.issues[0].severity == "blocker"


def test_validate_payload_reports_unknown_fields_as_warnings() -> None:
    registry = ContractRegistry()
    registry.register_contract(_descriptor())

    report = registry.validate_payload(
        "core.session",
        "1.0",
        {
            "session_id": "session-1",
            "user_id": "user-1",
            "extra": True,
        },
    )

    assert report.valid is True
    assert report.issues[0].code == "unknown_field"
    assert report.issues[0].severity == "warning"


def test_compatibility_report_allows_optional_field_addition() -> None:
    registry = ContractRegistry()
    registry.register_contract(_descriptor(optional_fields=("user_id",)))
    candidate = _descriptor(version="1.1", optional_fields=("user_id", "trace_id"))

    report = registry.compatibility_report("core.session", "1.0", candidate)

    assert report.status is ContractCompatibilityStatus.BACKWARD_COMPATIBLE
    assert report.compatible is True


def test_compatibility_report_rejects_required_field_changes() -> None:
    registry = ContractRegistry()
    registry.register_contract(_descriptor(required_fields=("session_id",)))
    candidate = _descriptor(
        version="2.0",
        required_fields=("session_id", "user_id"),
        optional_fields=(),
    )

    report = registry.compatibility_report("core.session", "1.0", candidate)

    assert report.status is ContractCompatibilityStatus.INCOMPATIBLE
    assert report.compatible is False


def test_compatibility_report_marks_unknown_base_contract() -> None:
    registry = ContractRegistry()

    report = registry.compatibility_report("core.session", "1.0", _descriptor())

    assert report.status is ContractCompatibilityStatus.UNKNOWN
    assert report.compatible is False
