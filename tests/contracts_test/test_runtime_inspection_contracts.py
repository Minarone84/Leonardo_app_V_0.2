from dataclasses import FrozenInstanceError
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
    SuiteRuntimeSummary,
    SuiteRuntimeSummaryStatus,
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


def test_suite_runtime_summary_is_frozen_and_serialization_friendly() -> None:
    summary = SuiteRuntimeSummary(
        suite_id="data_manager",
        area_id=None,
        display_name="Data Manager",
        status="ok",
        module_count=2,
        active_operation_count=1,
        active_task_count=3,
        object_map_section_count=1,
        warnings=("slow provider",),
        metadata={"source": "test"},
        docs_refs=["docs/core_docs/SUITE_RUNTIME_SUMMARY.md"],
    )

    assert summary.status is SuiteRuntimeSummaryStatus.OK
    assert summary.warnings == ("slow provider",)
    assert summary.docs_refs == ("docs/core_docs/SUITE_RUNTIME_SUMMARY.md",)
    assert summary.metadata["source"] == "test"
    assert summary.to_dict()["status"] == "ok"
    assert summary.to_dict()["warnings"] == ["slow provider"]
    with pytest.raises(FrozenInstanceError):
        summary.display_name = "changed"
    with pytest.raises(TypeError):
        summary.metadata["source"] = "changed"


def test_suite_runtime_summary_requires_suite_or_area_id() -> None:
    with pytest.raises(ValueError, match="suite_id or area_id"):
        SuiteRuntimeSummary(
            suite_id=None,
            area_id=None,
            display_name="Missing Owner",
            status=SuiteRuntimeSummaryStatus.OK,
        )


def test_suite_runtime_summary_rejects_blank_ids() -> None:
    with pytest.raises(ValueError, match="suite_id"):
        SuiteRuntimeSummary(
            suite_id=" ",
            area_id=None,
            display_name="Blank Suite",
            status=SuiteRuntimeSummaryStatus.OK,
        )


def test_suite_runtime_summary_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="module_count"):
        SuiteRuntimeSummary(
            suite_id="data_manager",
            area_id=None,
            display_name="Data Manager",
            status=SuiteRuntimeSummaryStatus.OK,
            module_count=-1,
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
        processes_summary=_section("processes"),
        connections_summary=_section("connections"),
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
        "processes",
        "connections",
        "windows",
        "actions",
        "operations",
        "downloads",
        "download_execution",
        "object_map",
        "suite_runtime",
        "audit",
        "contracts",
    ]
    assert snapshot.download_execution_summary.section_id == "download_execution"
    assert snapshot.download_execution_summary.metadata["available"] is False
    assert snapshot.object_map_summary.section_id == "object_map"
    assert snapshot.object_map_summary.metadata["available"] is False
    assert snapshot.suite_runtime_summary.section_id == "suite_runtime"
    assert snapshot.suite_runtime_summary.metadata["available"] is False
    assert snapshot.to_dict()["health"] == "degraded"
