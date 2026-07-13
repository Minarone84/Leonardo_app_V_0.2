from leonardo.audit import AuditEventV1
from leonardo.core.app import LeonardoApp


def test_runtime_manager_reads_direct_manager_snapshots() -> None:
    app = LeonardoApp()
    app.startup()
    app.window_registry.register_window("main.window", title="Leonardo")
    app.window_registry.open_window("main.window")
    app.connection_registry.register_connection("provider", label="Provider")
    app.connection_registry.mark_connected("provider")
    app.action_registry.register_action(action_id="runtime.refresh", label="Refresh")
    app.action_registry.record_trigger("runtime.refresh")
    app.audit_log.emit(AuditEventV1(event_type="runtime.checked", message="Checked"))

    snapshot = app.runtime_manager.snapshot()

    assert snapshot.app_status == "running"
    assert snapshot.actor_id == "local-user"
    assert snapshot.connections[0]["connection_id"] == "provider"
    assert snapshot.windows[0]["window_id"] == "main.window"
    assert snapshot.actions[0]["action_id"] == "runtime.refresh"
    assert any(event["event_type"] == "runtime.checked" for event in snapshot.recent_events)
    app.shutdown()
