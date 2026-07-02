from datetime import UTC, datetime

import pytest

from leonardo.contracts.inspection import (
    AuditEventPreview,
    AuditSinkFailurePreview,
    ContractRegistrySummary,
    RuntimeHealthStatus,
    RuntimeManagerSnapshot,
    RuntimeSectionStatus,
    RuntimeSectionSummary,
)


def _section(
    section_id: str,
    status: RuntimeSectionStatus = RuntimeSectionStatus.OK,
) -> RuntimeSectionSummary:
    return RuntimeSectionSummary(section_id=section_id, status=status)


def test_runtime_section_summary_is_serialization_friendly() -> None:
    summary = RuntimeSectionSummary(
        section_id="tasks",
        status=RuntimeSectionStatus.OK,
        count=2,
        message="2 active tasks",
        metadata={"task_ids": ("task-1", "task-2")},
    )

    assert summary.metadata["task_ids"] == ("task-1", "task-2")
    assert summary.to_dict() == {
        "section_id": "tasks",
        "status": "ok",
        "count": 2,
        "message": "2 active tasks",
        "metadata": {"task_ids": ["task-1", "task-2"]},
    }


def test_runtime_section_summary_rejects_invalid_count() -> None:
    with pytest.raises(ValueError, match="count"):
        RuntimeSectionSummary(
            section_id="tasks",
            status=RuntimeSectionStatus.OK,
            count=-1,
        )


def test_audit_previews_and_contract_summary_are_serialization_friendly() -> None:
    timestamp = datetime(2026, 7, 2, 12, tzinfo=UTC)
    event = AuditEventPreview(
        event_id="event-1",
        timestamp_utc=timestamp,
        severity="info",
        category="runtime",
        event_type="runtime.checked",
        message="Runtime checked",
        actor_id="admin-dev",
    )
    failure = AuditSinkFailurePreview(
        sink_name="FailingSink",
        operation="emit",
        exception_type="RuntimeError",
        message="failed",
        event_id="event-1",
    )
    contracts = ContractRegistrySummary(total_contracts=3, active_contracts=3)

    assert event.to_dict()["timestamp_utc"] == timestamp.isoformat()
    assert failure.to_dict()["sink_name"] == "FailingSink"
    assert contracts.to_dict()["active_contracts"] == 3


def test_runtime_manager_snapshot_derives_health_from_sections() -> None:
    snapshot = RuntimeManagerSnapshot(
        generated_at_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
        app_status="running",
        session_id="session-admin-dev",
        user_id="admin-dev",
        username="Administrator",
        app_summary=_section("app"),
        session_summary=_section("session"),
        services_summary=_section("services"),
        tasks_summary=_section("tasks"),
        windows_summary=_section("windows"),
        actions_summary=_section("actions"),
        operations_summary=_section("operations"),
        audit_summary=_section("audit", RuntimeSectionStatus.DEGRADED),
        contracts_summary=_section("contracts"),
        contract_registry=ContractRegistrySummary(total_contracts=1),
    )

    assert snapshot.health is RuntimeHealthStatus.DEGRADED
    assert [section.section_id for section in snapshot.sections] == [
        "app",
        "session",
        "services",
        "tasks",
        "windows",
        "actions",
        "operations",
        "audit",
        "contracts",
    ]
    assert snapshot.to_dict()["health"] == "degraded"
