import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from leonardo.contracts.inspection import (
    AuditEventPreview,
    AuditSinkFailurePreview,
    ContractRegistrySummary,
    DownloadDataRuntimeSummary,
    DownloadDataRuntimeSummaryStatus,
    ProviderRuntimeSummary,
    ProviderRuntimeSummaryStatus,
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


def test_provider_runtime_summary_is_frozen_and_serialization_friendly() -> None:
    summary = ProviderRuntimeSummary(
        provider_id="bybit",
        display_name="Bybit",
        status="ok",
        provider_kind="exchange",
        capability_count=2,
        session_count=1,
        active_session_count=1,
        connected_session_count=1,
        subscription_count=2,
        active_subscription_count=1,
        message_trace_count=3,
        object_map_section_count=1,
        warnings=("metadata only",),
        metadata={"environment": "testnet"},
        docs_refs=["docs/core_docs/PROVIDER_RUNTIME_SUMMARY.md"],
    )

    assert summary.status is ProviderRuntimeSummaryStatus.OK
    assert summary.warnings == ("metadata only",)
    assert summary.docs_refs == ("docs/core_docs/PROVIDER_RUNTIME_SUMMARY.md",)
    assert summary.metadata["environment"] == "testnet"
    assert summary.to_dict()["status"] == "ok"
    assert summary.to_dict()["warnings"] == ["metadata only"]
    with pytest.raises(FrozenInstanceError):
        summary.display_name = "changed"
    with pytest.raises(TypeError):
        summary.metadata["environment"] = "changed"


def test_provider_runtime_summary_rejects_blank_required_ids() -> None:
    with pytest.raises(ValueError, match="provider_id"):
        ProviderRuntimeSummary(
            provider_id=" ",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
        )
    with pytest.raises(ValueError, match="display_name"):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name=" ",
            status=ProviderRuntimeSummaryStatus.OK,
        )


def test_provider_runtime_summary_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="capability_count"):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
            capability_count=-1,
        )


def test_provider_runtime_summary_normalizes_tuples_and_rejects_plain_strings() -> None:
    summary = ProviderRuntimeSummary(
        provider_id="bybit",
        display_name="Bybit",
        status=ProviderRuntimeSummaryStatus.DEGRADED,
        warnings=["rate limited"],  # type: ignore[arg-type]
        errors=["summary unavailable"],  # type: ignore[arg-type]
        docs_refs=["docs/core_docs/PROVIDER_RUNTIME_SUMMARY.md"],  # type: ignore[arg-type]
        test_refs=["tests/contracts_test/test_runtime_inspection_contracts.py"],  # type: ignore[arg-type]
    )

    assert summary.status is ProviderRuntimeSummaryStatus.DEGRADED
    assert summary.warnings == ("rate limited",)
    assert summary.errors == ("summary unavailable",)
    assert summary.docs_refs == ("docs/core_docs/PROVIDER_RUNTIME_SUMMARY.md",)
    with pytest.raises(TypeError, match="warnings"):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
            warnings="rate limited",  # type: ignore[arg-type]
        )


def test_provider_runtime_summary_rejects_sensitive_metadata_keys() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
            metadata={"api_key": "never-store"},
        )
    with pytest.raises(ValueError, match="sensitive"):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
            metadata={"raw_payload_summary": "blocked"},
        )


@pytest.mark.parametrize(
    "metadata",
    (
        {"safe": {"token": "x"}},
        {"safe": [{"secret": "x"}]},
        {"safe": {"nested": {"raw_payload": "x"}}},
        {"level": {"one": {"two": {"authorization": "Bearer x"}}}},
    ),
)
def test_provider_runtime_summary_rejects_nested_sensitive_metadata_keys(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
            metadata=metadata,
        )


@pytest.mark.parametrize(
    "metadata",
    (
        {"safe": object()},
        {"safe": lambda: None},
        {"safe": b"bytes"},
        {"safe": bytearray(b"bytes")},
        {"safe": memoryview(b"bytes")},
        {"safe": {"values"}},
        {"safe": frozenset({"values"})},
        {1: "not a string key"},
        {"safe": float("nan")},
        {"safe": float("inf")},
        {"safe": float("-inf")},
    ),
)
def test_provider_runtime_summary_rejects_unsafe_metadata_values(
    metadata: dict[object, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ProviderRuntimeSummary(
            provider_id="bybit",
            display_name="Bybit",
            status=ProviderRuntimeSummaryStatus.OK,
            metadata=metadata,  # type: ignore[arg-type]
        )


def test_provider_runtime_summary_accepts_nested_json_like_metadata_read_only() -> None:
    metadata = {
        "level": "summary",
        "counts": {"sessions": 2, "active": 1},
        "flags": [True, False],
        "notes": None,
    }

    summary = ProviderRuntimeSummary(
        provider_id="bybit",
        display_name="Bybit",
        status=ProviderRuntimeSummaryStatus.OK,
        metadata=metadata,
    )

    assert summary.metadata["level"] == "summary"
    assert summary.metadata["counts"]["sessions"] == 2  # type: ignore[index]
    assert summary.metadata["flags"] == (True, False)
    with pytest.raises(TypeError):
        summary.metadata["level"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        summary.metadata["counts"]["sessions"] = 3  # type: ignore[index]


def test_provider_runtime_summary_metadata_does_not_mutate_caller_values() -> None:
    metadata = {
        "counts": {"sessions": 2},
        "flags": [True],
    }

    summary = ProviderRuntimeSummary(
        provider_id="bybit",
        display_name="Bybit",
        status=ProviderRuntimeSummaryStatus.OK,
        metadata=metadata,
    )
    metadata["counts"]["sessions"] = 99  # type: ignore[index]
    metadata["flags"].append(False)  # type: ignore[attr-defined]

    assert summary.metadata["counts"]["sessions"] == 2  # type: ignore[index]
    assert summary.metadata["flags"] == (True,)


def test_provider_runtime_summary_to_dict_has_json_compatible_nested_metadata() -> None:
    summary = ProviderRuntimeSummary(
        provider_id="bybit",
        display_name="Bybit",
        status=ProviderRuntimeSummaryStatus.OK,
        metadata={
            "level": "summary",
            "counts": {"sessions": 2, "active": 1},
            "flags": [True, False],
            "ratio": 0.5,
            "notes": None,
        },
    )

    serialized = summary.to_dict()

    assert serialized["metadata"] == {
        "level": "summary",
        "counts": {"sessions": 2, "active": 1},
        "flags": [True, False],
        "ratio": 0.5,
        "notes": None,
    }
    json.dumps(serialized)


def test_download_data_runtime_summary_is_frozen_and_serialization_friendly() -> None:
    summary = DownloadDataRuntimeSummary(
        workflow_id="download_data",
        display_name="Download Data",
        status="ok",
        selection_count=1,
        preflight_count=2,
        ready_preflight_count=1,
        blocked_preflight_count=1,
        running_progress_count=1,
        completed_progress_count=1,
        completion_count=1,
        partial_count=1,
        failed_count=1,
        cancelled_count=1,
        output_ref_count=2,
        storage_target_count=2,
        partial_persistence_count=1,
        expected_total_bars=100,
        expected_total_steps=10,
        completed_steps=5,
        downloaded_bars=50,
        warning_count=1,
        error_count=1,
        warnings=("partial data",),
        errors=("one item failed",),
        metadata={"counts": {"selected": 1}, "flags": [True, False]},
        docs_refs=["docs/core_docs/DOWNLOAD_DATA_RUNTIME_SUMMARY.md"],
    )

    assert summary.status is DownloadDataRuntimeSummaryStatus.OK
    assert summary.warnings == ("partial data",)
    assert summary.docs_refs == ("docs/core_docs/DOWNLOAD_DATA_RUNTIME_SUMMARY.md",)
    assert summary.metadata["counts"]["selected"] == 1  # type: ignore[index]
    assert summary.metadata["flags"] == (True, False)
    serialized = summary.to_dict()
    assert serialized["status"] == "ok"
    assert serialized["warnings"] == ["partial data"]
    assert serialized["metadata"] == {
        "counts": {"selected": 1},
        "flags": [True, False],
    }
    json.dumps(serialized)
    with pytest.raises(FrozenInstanceError):
        summary.display_name = "changed"
    with pytest.raises(TypeError):
        summary.metadata["counts"]["selected"] = 2  # type: ignore[index]


def test_download_data_runtime_summary_rejects_blank_required_fields() -> None:
    with pytest.raises(ValueError, match="workflow_id"):
        DownloadDataRuntimeSummary(
            workflow_id=" ",
            display_name="Download Data",
            status=DownloadDataRuntimeSummaryStatus.OK,
        )
    with pytest.raises(ValueError, match="display_name"):
        DownloadDataRuntimeSummary(
            workflow_id="download_data",
            display_name=" ",
            status=DownloadDataRuntimeSummaryStatus.OK,
        )


def test_download_data_runtime_summary_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="partial_persistence_count"):
        DownloadDataRuntimeSummary(
            workflow_id="download_data",
            display_name="Download Data",
            status=DownloadDataRuntimeSummaryStatus.OK,
            partial_persistence_count=-1,
        )


def test_download_data_runtime_summary_normalizes_tuples_and_rejects_plain_strings() -> None:
    summary = DownloadDataRuntimeSummary(
        workflow_id="download_data",
        display_name="Download Data",
        status="degraded",
        warnings=["partial"],  # type: ignore[arg-type]
        errors=["failed"],  # type: ignore[arg-type]
        docs_refs=["docs/core_docs/DOWNLOAD_DATA_RUNTIME_SUMMARY.md"],  # type: ignore[arg-type]
        test_refs=["tests/contracts_test/test_runtime_inspection_contracts.py"],  # type: ignore[arg-type]
    )

    assert summary.status is DownloadDataRuntimeSummaryStatus.DEGRADED
    assert summary.warnings == ("partial",)
    assert summary.errors == ("failed",)
    assert summary.docs_refs == ("docs/core_docs/DOWNLOAD_DATA_RUNTIME_SUMMARY.md",)
    with pytest.raises(TypeError, match="warnings"):
        DownloadDataRuntimeSummary(
            workflow_id="download_data",
            display_name="Download Data",
            status=DownloadDataRuntimeSummaryStatus.OK,
            warnings="partial",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "metadata",
    (
        {"provider_ref": "blocked"},
        {"safe": {"token": "x"}},
        {"safe": [{"adapter": "x"}]},
        {"safe": {"nested": {"storage_writer": "x"}}},
        {"level": {"one": {"two": {"authorization": "Bearer x"}}}},
    ),
)
def test_download_data_runtime_summary_rejects_sensitive_metadata_keys(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        DownloadDataRuntimeSummary(
            workflow_id="download_data",
            display_name="Download Data",
            status=DownloadDataRuntimeSummaryStatus.OK,
            metadata=metadata,
        )


@pytest.mark.parametrize(
    "metadata",
    (
        {"safe": object()},
        {"safe": lambda: None},
        {"safe": b"bytes"},
        {"safe": bytearray(b"bytes")},
        {"safe": memoryview(b"bytes")},
        {"safe": {"values"}},
        {"safe": frozenset({"values"})},
        {1: "not a string key"},
        {"safe": float("nan")},
        {"safe": float("inf")},
        {"safe": float("-inf")},
    ),
)
def test_download_data_runtime_summary_rejects_unsafe_metadata_values(
    metadata: dict[object, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        DownloadDataRuntimeSummary(
            workflow_id="download_data",
            display_name="Download Data",
            status=DownloadDataRuntimeSummaryStatus.OK,
            metadata=metadata,  # type: ignore[arg-type]
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
        "provider_runtime",
        "suite_runtime",
        "download_data_runtime",
        "audit",
        "contracts",
    ]
    assert snapshot.download_execution_summary.section_id == "download_execution"
    assert snapshot.download_execution_summary.metadata["available"] is False
    assert snapshot.object_map_summary.section_id == "object_map"
    assert snapshot.object_map_summary.metadata["available"] is False
    assert snapshot.provider_runtime_summary.section_id == "provider_runtime"
    assert snapshot.provider_runtime_summary.metadata["available"] is False
    assert snapshot.suite_runtime_summary.section_id == "suite_runtime"
    assert snapshot.suite_runtime_summary.metadata["available"] is False
    assert snapshot.download_data_runtime_summary.section_id == "download_data_runtime"
    assert snapshot.download_data_runtime_summary.metadata["available"] is False
    assert snapshot.to_dict()["health"] == "degraded"
