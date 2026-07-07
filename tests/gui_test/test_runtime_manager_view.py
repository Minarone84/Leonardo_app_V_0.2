import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget  # noqa: E402

from leonardo.contracts.inspection import (  # noqa: E402
    AuditEventPreview,
    ContractRegistrySummary,
    RuntimeManagerSnapshot,
    RuntimeSectionStatus,
    RuntimeSectionSummary,
)
from leonardo.gui.windows.runtime_manager_window import (  # noqa: E402
    RuntimeManagerWindow,
    load_runtime_manager_profile,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_MANAGER_WINDOW_SOURCE = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "runtime_manager_window.py"
)
_METADATA_PACKAGE_PATH = _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata"


class FakeSnapshotProvider:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> dict[str, object]:
        self.calls += 1
        return _fake_snapshot()


class FakeRuntimeBackend:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return _fake_snapshot()


def test_runtime_manager_effective_profile_loads() -> None:
    profile = load_runtime_manager_profile()

    assert profile.metadata_id == "runtime_manager.window"
    assert profile.values["identity"]["title"] == "Runtime Manager"
    assert profile.report.has_errors is False


def test_runtime_manager_window_constructs_without_leonardo_app(
    qapplication: QApplication,
) -> None:
    profile = load_runtime_manager_profile()
    window = RuntimeManagerWindow(profile)

    assert window.profile is profile
    assert window.windowTitle() == "Runtime Manager"
    assert window.objectName() == "runtime_manager_window"
    assert window.findChild(QLabel, "runtime_manager.title_label").text() == (
        "Runtime Manager"
    )

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_action_labels_come_from_metadata(
    qapplication: QApplication,
) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())

    assert window.action_labels() == {
        "runtime_manager.refresh_snapshot": "Refresh Snapshot",
        "runtime_manager.copy_snapshot_summary": "Copy Snapshot Summary",
        "runtime_manager.export_snapshot": "Export Snapshot",
        "runtime_manager.open_details": "Open Details",
        "runtime_manager.close": "Close",
    }
    for action_id, label in window.action_labels().items():
        button = window.findChild(QPushButton, action_id)
        assert button is not None
        assert button.text() == label

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_metadata_table_ids_are_present(
    qapplication: QApplication,
) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())

    assert set(window.table_ids()) == {
        "runtime_manager.summary_table",
        "runtime_manager.services_table",
        "runtime_manager.tasks_table",
        "runtime_manager.processes_table",
        "runtime_manager.connections_table",
        "runtime_manager.windows_table",
        "runtime_manager.actions_table",
        "runtime_manager.operations_table",
        "runtime_manager.downloads_table",
        "runtime_manager.download_execution_table",
        "runtime_manager.audit_preview_table",
    }

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_table_headers_come_from_metadata(
    qapplication: QApplication,
) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())

    assert window.table_headers("runtime_manager.summary_table") == (
        "Section",
        "Status",
        "Count",
        "Details",
    )
    assert window.table_headers("runtime_manager.audit_preview_table") == (
        "Timestamp",
        "Severity",
        "Event Type",
        "Message",
        "Event ID",
        "Category",
        "Actor ID",
        "Session ID",
        "Window ID",
        "Action ID",
        "Operation ID",
        "Task ID",
        "Correlation ID",
    )
    assert window.table_headers("runtime_manager.downloads_table") == (
        "Metric",
        "Value",
        "Details",
    )
    assert window.table_headers("runtime_manager.download_execution_table") == (
        "Plan ID",
        "Request ID",
        "Phase",
        "Operation ID",
        "Task ID",
        "Items",
        "Preflight Layers",
        "Progress %",
        "Outputs",
        "Errors",
        "Details",
    )

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_fake_snapshot_provider_can_be_injected(
    qapplication: QApplication,
) -> None:
    provider = FakeSnapshotProvider()
    window = RuntimeManagerWindow(
        load_runtime_manager_profile(),
        snapshot_provider=provider,
    )

    assert provider.calls == 0
    assert window.refresh_called is False

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_refresh_calls_provider_and_updates_local_state(
    qapplication: QApplication,
) -> None:
    provider = FakeSnapshotProvider()
    window = RuntimeManagerWindow(
        load_runtime_manager_profile(),
        snapshot_provider=provider,
    )

    window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    summary = window.last_rendered_snapshot_summary
    services_table = window.table_for_id("runtime_manager.services_table")
    tasks_table = window.table_for_id("runtime_manager.tasks_table")
    audit_table = window.table_for_id("runtime_manager.audit_preview_table")

    assert provider.calls == 1
    assert window.refresh_called is True
    assert summary["status"] == "rendered"
    assert summary["health"] == "ok"
    assert summary["service_rows"] == 2
    assert summary["task_rows"] == 1
    assert services_table.item(0, 0).text() == "runtime-service"
    assert services_table.item(1, 0).text() == "audit-service"
    assert tasks_table.item(0, 0).text() == "Inspect runtime"
    assert audit_table.item(0, 2).text() == "runtime.checked"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_backend_snapshot_method_can_be_injected(
    qapplication: QApplication,
) -> None:
    backend = FakeRuntimeBackend()
    window = RuntimeManagerWindow(load_runtime_manager_profile(), backend=backend)

    window.refresh_snapshot()
    qapplication.processEvents()

    assert backend.calls == 1
    assert window.last_rendered_snapshot_summary["status"] == "rendered"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_renders_runtime_snapshot_contract(
    qapplication: QApplication,
) -> None:
    snapshot = RuntimeManagerSnapshot(
        generated_at_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
        app_status="running",
        session_id="session-admin-dev",
        user_id="admin-dev",
        username="Administrator",
        app_summary=_section("app", "Application running"),
        session_summary=_section("session", "Session active"),
        services_summary=_section(
            "services",
            "1 service visible",
            count=1,
            metadata={"service_ids": ("contract-service",)},
        ),
        tasks_summary=_section(
            "tasks",
            "1 active task",
            count=1,
            metadata={
                "task_ids": ("task-1",),
                "task_names": ("Contract task",),
            },
        ),
        processes_summary=_section("processes", "No active processes"),
        connections_summary=_section("connections", "No connections"),
        windows_summary=_section("windows", "No windows"),
        actions_summary=_section("actions", "No actions"),
        operations_summary=_section("operations", "No operations"),
        audit_summary=_section("audit", "1 retained audit event", count=1),
        contracts_summary=_section("contracts", "1 contract", count=1),
        recent_audit_events=(
            AuditEventPreview(
                event_id="event-1",
                timestamp_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
                severity="info",
                category="runtime",
                event_type="runtime.checked",
                message="Runtime checked",
            ),
        ),
        contract_registry=ContractRegistrySummary(total_contracts=1),
    )
    window = RuntimeManagerWindow(load_runtime_manager_profile(), snapshot=snapshot)

    assert window.last_rendered_snapshot_summary["health"] == "ok"
    summary_table = window.table_for_id("runtime_manager.summary_table")
    assert summary_table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
    assert window.last_rendered_snapshot_summary["summary_rows"] == 14
    assert summary_table.rowCount() == 14
    assert summary_table.item(11, 0).text() == "object_map"
    assert summary_table.item(11, 1).text() == "ok"
    assert summary_table.item(11, 2).text() == "0"
    assert summary_table.item(11, 3).text() == "Object Map unavailable"
    assert window.table_for_id("runtime_manager.services_table").item(0, 0).text() == (
        "contract-service"
    )
    assert window.table_for_id("runtime_manager.tasks_table").item(0, 0).text() == (
        "Contract task"
    )
    assert window.table_for_id("runtime_manager.audit_preview_table").item(0, 2).text() == (
        "runtime.checked"
    )
    downloads_table = window.table_for_id("runtime_manager.downloads_table")
    assert downloads_table.rowCount() == 14
    assert downloads_table.item(0, 0).text() == "Total Requests"
    assert downloads_table.item(0, 1).text() == "0"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_audit_preview_renders_existing_context_fields(
    qapplication: QApplication,
) -> None:
    snapshot = RuntimeManagerSnapshot(
        generated_at_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
        app_status="running",
        session_id="session-admin-dev",
        user_id="admin-dev",
        username="Administrator",
        app_summary=_section("app", "Application running"),
        session_summary=_section("session", "Session active"),
        services_summary=_section("services", "No services"),
        tasks_summary=_section("tasks", "No tasks"),
        processes_summary=_section("processes", "No active processes"),
        connections_summary=_section("connections", "No connections"),
        windows_summary=_section("windows", "No windows"),
        actions_summary=_section("actions", "No actions"),
        operations_summary=_section("operations", "No operations"),
        audit_summary=_section("audit", "1 retained audit event", count=1),
        contracts_summary=_section("contracts", "No contracts"),
        recent_audit_events=(
            AuditEventPreview(
                event_id="event-1",
                timestamp_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
                severity="info",
                category="runtime",
                event_type="runtime.checked",
                message="Runtime checked",
                actor_id="admin-dev",
                session_id="session-admin-dev",
                window_id="runtime-manager",
                action_id="runtime.refresh",
                operation_id="operation-1",
                task_id="task-1",
                correlation_id="correlation-1",
            ),
        ),
    )
    window = RuntimeManagerWindow(load_runtime_manager_profile(), snapshot=snapshot)
    table = window.table_for_id("runtime_manager.audit_preview_table")

    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "2026-07-02T12:00:00+00:00"
    assert table.item(0, 1).text() == "info"
    assert table.item(0, 2).text() == "runtime.checked"
    assert table.item(0, 3).text() == "Runtime checked"
    assert table.item(0, 4).text() == "event-1"
    assert table.item(0, 5).text() == "runtime"
    assert table.item(0, 6).text() == "admin-dev"
    assert table.item(0, 7).text() == "session-admin-dev"
    assert table.item(0, 8).text() == "runtime-manager"
    assert table.item(0, 9).text() == "runtime.refresh"
    assert table.item(0, 10).text() == "operation-1"
    assert table.item(0, 11).text() == "task-1"
    assert table.item(0, 12).text() == "correlation-1"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_renders_all_detail_tabs_from_snapshot_summary_metadata(
    qapplication: QApplication,
) -> None:
    snapshot = RuntimeManagerSnapshot(
        generated_at_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
        app_status="running",
        session_id="session-admin-dev",
        user_id="admin-dev",
        username="Administrator",
        app_summary=_section("app", "Application running"),
        session_summary=_section("session", "Session active"),
        services_summary=_section("services", "No services"),
        tasks_summary=_section("tasks", "No tasks"),
        processes_summary=_section(
            "processes",
            "1 active process",
            count=1,
            metadata={
                "process_ids": ("process-1",),
                "process_labels": ("Inspect runtime process",),
            },
        ),
        connections_summary=_section(
            "connections",
            "1 connection visible",
            count=1,
            metadata={
                "connection_ids": ("connection-1",),
                "connection_labels": ("Runtime feed",),
            },
        ),
        windows_summary=_section(
            "windows",
            "1 open window",
            count=1,
            metadata={"open_window_ids": ("runtime-manager",)},
        ),
        actions_summary=_section(
            "actions",
            "1 recent action trigger",
            count=1,
            metadata={"recent_action_ids": ("runtime.refresh",)},
        ),
        operations_summary=_section(
            "operations",
            "1 active operation",
            count=1,
            metadata={
                "operation_ids": ("operation-1",),
                "operation_labels": ("Inspect runtime operation",),
            },
        ),
        audit_summary=_section("audit", "No retained audit events"),
        contracts_summary=_section("contracts", "No contracts"),
    )
    window = RuntimeManagerWindow(load_runtime_manager_profile(), snapshot=snapshot)

    processes = window.table_for_id("runtime_manager.processes_table")
    connections = window.table_for_id("runtime_manager.connections_table")
    windows = window.table_for_id("runtime_manager.windows_table")
    actions = window.table_for_id("runtime_manager.actions_table")
    operations = window.table_for_id("runtime_manager.operations_table")

    assert processes.rowCount() == 1
    assert processes.item(0, 0).text() == "Inspect runtime process"
    assert processes.item(0, 1).text() == "ok"
    assert processes.item(0, 2).text() == ""
    assert processes.item(0, 3).text() == "1 active process"

    assert connections.rowCount() == 1
    assert connections.item(0, 0).text() == "Runtime feed"
    assert connections.item(0, 1).text() == "ok"
    assert connections.item(0, 2).text() == "1 connection visible"

    assert windows.rowCount() == 1
    assert windows.item(0, 0).text() == "runtime-manager"
    assert windows.item(0, 1).text() == "ok"
    assert windows.item(0, 2).text() == "1 open window"

    assert actions.rowCount() == 1
    assert actions.item(0, 0).text() == "runtime.refresh"
    assert actions.item(0, 1).text() == "ok"
    assert actions.item(0, 2).text() == "1 recent action trigger"

    assert operations.rowCount() == 1
    assert operations.item(0, 0).text() == "Inspect runtime operation"
    assert operations.item(0, 1).text() == "ok"
    assert operations.item(0, 2).text() == "1 active operation"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_renders_download_summary_rows(
    qapplication: QApplication,
) -> None:
    snapshot = RuntimeManagerSnapshot(
        generated_at_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
        app_status="running",
        session_id="session-admin-dev",
        user_id="admin-dev",
        username="Administrator",
        app_summary=_section("app", "Application running"),
        session_summary=_section("session", "Session active"),
        services_summary=_section("services", "No services"),
        tasks_summary=_section("tasks", "No tasks"),
        processes_summary=_section("processes", "No active processes"),
        connections_summary=_section("connections", "No connections"),
        windows_summary=_section("windows", "No windows"),
        actions_summary=_section("actions", "No actions"),
        operations_summary=_section("operations", "No operations"),
        downloads_summary=_section(
            "downloads",
            "1 download request, 2 items",
            count=1,
            metadata={
                "total_requests": 1,
                "total_items": 2,
                "requested_count": 0,
                "validated_count": 3,
                "queued_count": 0,
                "running_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "cancelled_count": 0,
                "skipped_count": 0,
                "partially_completed_count": 0,
                "preflight_failed_count": 0,
                "websocket_required_count": 1,
                "connection_blocked_count": 0,
                "active_request_ids": ("req-download",),
                "queued_request_ids": (),
                "failed_request_ids": (),
                "active_item_ids": (
                    "req-download:BTCUSDT:1m",
                    "req-download:BTCUSDT:5m",
                ),
                "failed_item_ids": (),
            },
        ),
        audit_summary=_section("audit", "No retained audit events"),
        contracts_summary=_section("contracts", "No contracts"),
    )
    window = RuntimeManagerWindow(load_runtime_manager_profile(), snapshot=snapshot)
    table = window.table_for_id("runtime_manager.downloads_table")

    assert table.rowCount() == 14
    assert table.item(0, 0).text() == "Total Requests"
    assert table.item(0, 1).text() == "1"
    assert table.item(0, 2).text() == "active_request_ids=req-download"
    assert table.item(1, 0).text() == "Total Items"
    assert table.item(1, 1).text() == "2"
    assert table.item(1, 2).text() == (
        "active_item_ids=req-download:BTCUSDT:1m, req-download:BTCUSDT:5m"
    )
    assert table.item(3, 0).text() == "Validated"
    assert table.item(3, 1).text() == "3"
    assert table.item(12, 0).text() == "WebSocket Required"
    assert table.item(12, 1).text() == "1"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_renders_download_execution_rows_read_only(
    qapplication: QApplication,
) -> None:
    snapshot = RuntimeManagerSnapshot(
        generated_at_utc=datetime(2026, 7, 2, 12, tzinfo=UTC),
        app_status="running",
        session_id="session-admin-dev",
        user_id="admin-dev",
        username="Administrator",
        app_summary=_section("app", "Application running"),
        session_summary=_section("session", "Session active"),
        services_summary=_section("services", "No services"),
        tasks_summary=_section("tasks", "No tasks"),
        processes_summary=_section("processes", "No active processes"),
        connections_summary=_section("connections", "No connections"),
        windows_summary=_section("windows", "No windows"),
        actions_summary=_section("actions", "No actions"),
        operations_summary=_section("operations", "No operations"),
        download_execution_summary=_section(
            "download_execution",
            "1 download execution plan",
            count=1,
            metadata={
                "total_plans": 1,
                "active_plan_ids": ("execution-plan-req-download",),
                "failed_plan_ids": (),
                "completed_plan_ids": (),
                "running_plan_ids": (),
                "blocked_plan_ids": (),
                "plan_rows": (
                    {
                        "plan_id": "execution-plan-req-download",
                        "request_id": "req-download",
                        "phase": "planned",
                        "operation_id": "",
                        "task_id": "",
                        "item_count": 2,
                        "preflight_layer_count": 1,
                        "progress_percent": None,
                        "output_count": 0,
                        "error_count": 0,
                        "details": "connection_refs=binance-spot",
                    },
                ),
            },
        ),
        audit_summary=_section("audit", "No retained audit events"),
        contracts_summary=_section("contracts", "No contracts"),
    )
    window = RuntimeManagerWindow(load_runtime_manager_profile(), snapshot=snapshot)
    table = window.table_for_id("runtime_manager.download_execution_table")

    assert table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
    assert window.last_rendered_snapshot_summary["download_execution_rows"] == 1
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "execution-plan-req-download"
    assert table.item(0, 1).text() == "req-download"
    assert table.item(0, 2).text() == "planned"
    assert table.item(0, 3).text() == ""
    assert table.item(0, 4).text() == ""
    assert table.item(0, 5).text() == "2"
    assert table.item(0, 6).text() == "1"
    assert table.item(0, 7).text() == ""
    assert table.item(0, 8).text() == "0"
    assert table.item(0, 9).text() == "0"
    assert table.item(0, 10).text() == "connection_refs=binance-spot"

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_empty_snapshot_does_not_crash(
    qapplication: QApplication,
) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())

    assert window.last_rendered_snapshot_summary["status"] == "empty"
    assert window.table_for_id("runtime_manager.summary_table").rowCount() == 0

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_requires_no_core_mutation_services() -> None:
    source = _RUNTIME_MANAGER_WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "StateStore" not in source
    assert "WindowRegistry" not in source
    assert "ActionRegistry" not in source
    assert "OperationRegistry" not in source
    assert "LeonardoApp" not in source


def test_runtime_manager_requires_no_main_window_wiring() -> None:
    source = _RUNTIME_MANAGER_WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "LeonardoMainWindow" not in source
    assert "main_window" not in source


def test_runtime_manager_non_refresh_actions_are_local_and_read_only(
    qapplication: QApplication,
) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())
    status = window.findChild(QLabel, "runtime_manager.status_label")

    window.action_button_for_id("runtime_manager.open_details").click()
    qapplication.processEvents()

    assert status is not None
    assert status.text() == (
        "runtime_manager.open_details is read-only metadata-only behavior in this phase."
    )
    assert window.refresh_called is False

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_close_action_closes_locally(qapplication: QApplication) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())
    close_button = window.action_button_for_id("runtime_manager.close")
    window.show()
    qapplication.processEvents()

    close_button.click()
    qapplication.processEvents()

    assert window.close_requested_locally is True
    assert window.isVisible() is False

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_window_can_be_destroyed_cleanly(
    qapplication: QApplication,
) -> None:
    window = RuntimeManagerWindow(load_runtime_manager_profile())
    window.show()
    qapplication.processEvents()

    window.close()
    window.deleteLater()
    qapplication.processEvents()

    assert window.close_requested_locally is True


def test_metadata_runtime_package_still_has_no_qt_imports() -> None:
    metadata_sources = [
        path
        for path in _METADATA_PACKAGE_PATH.rglob("*.py")
        if path.is_file()
    ]

    assert metadata_sources
    for source_path in metadata_sources:
        source = source_path.read_text(encoding="utf-8")
        assert "PySide6" not in source
        assert "PyQt6" not in source
        assert "QtWidgets" not in source
        assert "QtCore" not in source
        assert "QtGui" not in source


def _fake_snapshot() -> dict[str, object]:
    return {
        "generated_at_utc": "2026-07-02T12:00:00+00:00",
        "health": "ok",
        "app_status": "running",
        "sections": (
            {
                "section_id": "services",
                "status": "ok",
                "count": 2,
                "message": "2 services visible",
                "metadata": {
                    "service_ids": ("runtime-service", "audit-service"),
                },
            },
            {
                "section_id": "tasks",
                "status": "ok",
                "count": 1,
                "message": "1 active task",
                "metadata": {
                    "task_ids": ("task-1",),
                    "task_names": ("Inspect runtime",),
                },
            },
            {
                "section_id": "audit",
                "status": "ok",
                "count": 1,
                "message": "1 retained audit event",
                "metadata": {},
            },
        ),
        "recent_audit_events": (
            {
                "timestamp_utc": "2026-07-02T12:00:00+00:00",
                "severity": "info",
                "event_type": "runtime.checked",
                "message": "Runtime checked",
            },
        ),
    }


def _section(
    section_id: str,
    message: str,
    *,
    count: int = 0,
    metadata: dict[str, object] | None = None,
) -> RuntimeSectionSummary:
    return RuntimeSectionSummary(
        section_id=section_id,
        status=RuntimeSectionStatus.OK,
        count=count,
        message=message,
        metadata=metadata or {},
    )


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
