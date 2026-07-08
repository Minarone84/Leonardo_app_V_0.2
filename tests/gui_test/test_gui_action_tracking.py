import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from leonardo.contracts.gui import ActionKind  # noqa: E402
from leonardo.contracts.identity import (  # noqa: E402
    ActorOrigin,
    Permission,
    SessionContext,
    UserRef,
    UserRole,
)
from leonardo.core.app import LeonardoApp  # noqa: E402
from leonardo.core.action_registry import ActionRegistry  # noqa: E402
from leonardo.core.audit_log import AuditLog  # noqa: E402
from leonardo.core.session_manager import SessionManager  # noqa: E402
from leonardo.core.state_store import StateStore  # noqa: E402
from leonardo.core.user_policy import UserPolicy  # noqa: E402
from leonardo.gui.action_observer import build_gui_action_observer  # noqa: E402
from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import (  # noqa: E402
    GuiMetadataOverrideStore,
    load_metadata_document,
)
from leonardo.gui.settings_inspector import GuiSettingsInspectorViewModel  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import (  # noqa: E402
    RuntimeManagerWindow,
    load_runtime_manager_profile,
)
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOW_SOURCES = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "main_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "historical_download_manager_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "ohlcv_download_preflight_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "ohlcv_download_task_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "runtime_manager_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "settings_inspector_window.py",
)


def test_composition_registers_first_gui_action_definitions(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)
    window = root.create_main_window()

    registered_action_ids = {
        definition.action_id for definition in app.action_registry.list_actions()
    }
    definitions = {
        definition.action_id: definition
        for definition in app.action_registry.list_actions()
    }

    assert {
        "historical_download_manager.clear_timeframes",
        "historical_download_manager.ohlcv_maintenance",
        "historical_download_manager.select_all_timeframes",
        "historical_download_manager.start",
        "historical_download_manager.stop",
        "main_window.download_data",
        "main_window.ohlcv_maintenance",
        "main_window.open_analysis_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_research_suite",
        "main_window.open_runtime_manager",
        "main_window.open_settings_inspector",
        "main_window.open_trading_suite",
        "settings_inspector.save",
        "settings_inspector.apply_changes",
        "runtime_manager.refresh_snapshot",
        "runtime_manager.close",
    } <= registered_action_ids
    assert definitions[
        "main_window.open_runtime_manager"
    ].required_permissions == (Permission.RUNTIME_VIEW,)
    assert definitions[
        "main_window.open_settings_inspector"
    ].required_permissions == (Permission.GUI_SETTINGS_MANAGE,)
    assert definitions["settings_inspector.save"].required_permissions == (
        Permission.GUI_SETTINGS_MANAGE,
    )
    assert definitions["settings_inspector.apply_changes"].required_permissions == (
        Permission.GUI_SETTINGS_MANAGE,
    )
    assert definitions["runtime_manager.refresh_snapshot"].required_permissions == (
        Permission.RUNTIME_VIEW,
    )
    assert definitions["runtime_manager.close"].required_permissions == ()
    assert definitions["historical_download_manager.start"].label == "Start"
    for action_id in (
        "historical_download_manager.clear_timeframes",
        "historical_download_manager.ohlcv_maintenance",
        "historical_download_manager.select_all_timeframes",
        "historical_download_manager.start",
        "historical_download_manager.stop",
    ):
        assert definitions[action_id].required_permissions == ()
        assert definitions[action_id].is_placeholder is False
        assert definitions[action_id].kind is ActionKind.BUTTON
        assert definitions[action_id].window_id == "historical_download_manager.window"
    for action_id in (
        "main_window.open_analysis_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_research_suite",
        "main_window.open_trading_suite",
    ):
        assert definitions[action_id].required_permissions == ()
        assert definitions[action_id].is_placeholder is True
    for action_id in (
        "main_window.download_data",
        "main_window.ohlcv_maintenance",
    ):
        assert definitions[action_id].required_permissions == ()
        assert definitions[action_id].is_placeholder is False
    assert definitions["main_window.download_data"].kind is ActionKind.MENU
    assert definitions["main_window.ohlcv_maintenance"].kind is ActionKind.MENU
    assert definitions["main_window.open_trading_suite"].kind is ActionKind.BUTTON

    _dispose(qapplication, window)
    app.shutdown()


def test_main_window_tracked_actions_are_recorded(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    app = LeonardoApp()
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(app.context, track_windows=False, override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    records = app.action_registry.recent_triggers()
    action_ids = _recent_action_ids(app)
    runtime_record = _last_record(app, "main_window.open_runtime_manager")
    settings_record = _last_record(app, "main_window.open_settings_inspector")

    assert "main_window.open_runtime_manager" in action_ids
    assert "main_window.open_settings_inspector" in action_ids
    assert runtime_record.window_id == "main_window.window"
    assert settings_record.window_id == "main_window.window"
    assert all(record.actor_id == "admin-dev" for record in records)
    assert all(record.session_id == "session-admin-dev" for record in records)

    _dispose(
        qapplication,
        window,
        window.runtime_manager_window,
        window.settings_inspector_window,
    )
    app.shutdown()


def test_main_window_placeholder_actions_are_recorded_without_permissions(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)
    window = root.create_main_window()

    initial_runtime_downloads = app.runtime_manager.snapshot().downloads_summary

    window.action_for_id("main_window.download_data").trigger()
    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    window.placeholder_button_for_id("main_window.open_trading_suite").click()
    window.placeholder_button_for_id("main_window.open_research_suite").click()
    window.placeholder_button_for_id("main_window.open_data_manager_suite").click()
    window.placeholder_button_for_id("main_window.open_analysis_suite").click()
    qapplication.processEvents()

    expected_action_ids = (
        "main_window.download_data",
        "main_window.ohlcv_maintenance",
        "main_window.open_trading_suite",
        "main_window.open_research_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_analysis_suite",
    )
    action_ids = _recent_action_ids(app)
    audit_action_ids = tuple(
        event.action_id
        for event in app.audit_log.snapshot()
        if event.event_type == "gui.action.triggered"
    )
    runtime_downloads = app.runtime_manager.snapshot().downloads_summary
    download_events = tuple(
        event
        for event in app.audit_log.snapshot()
        if event.event_type.startswith("download.")
    )

    for action_id in expected_action_ids:
        record = _last_record(app, action_id)
        assert action_id in action_ids
        assert action_id in audit_action_ids
        assert record.window_id == "main_window.window"
        assert record.actor_id == "admin-dev"
        assert record.session_id == "session-admin-dev"

    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None
    assert root.historical_download_manager_window is not None
    assert root.historical_download_manager_window.isVisible() is True
    assert initial_runtime_downloads.count == 0
    assert initial_runtime_downloads.metadata["total_requests"] == 0
    assert initial_runtime_downloads.metadata["available"] is False
    assert runtime_downloads.count == 0
    assert runtime_downloads.metadata["total_requests"] == 0
    assert runtime_downloads.metadata["total_items"] == 0
    assert runtime_downloads.metadata["available"] is False
    assert download_events == ()

    _dispose(qapplication, window, root.historical_download_manager_window)
    app.shutdown()


def test_historical_download_manager_shell_buttons_remain_local_signals(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)
    window = root.create_main_window()
    signals: list[str] = []

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    shell = root.historical_download_manager_window
    assert shell is not None

    shell.start_requested.connect(lambda: signals.append("start"))
    shell.maintenance_requested.connect(lambda: signals.append("maintenance"))
    shell.button_for_id("start").click()
    shell.button_for_id("ohlcv_maintenance").click()
    qapplication.processEvents()

    assert signals == ["start", "maintenance"]
    assert "historical_download_manager.start" not in _recent_action_ids(app)
    assert "historical_download_manager.ohlcv_maintenance" not in _recent_action_ids(app)
    assert not [
        event
        for event in app.audit_log.snapshot()
        if event.event_type.startswith("download.")
    ]

    _dispose(qapplication, window, shell)
    app.shutdown()


def test_settings_inspector_save_and_apply_actions_are_recorded_without_semantic_change(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    app = LeonardoApp()
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(app.context, track_windows=False, override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()
    dialog = window.settings_inspector_window
    assert isinstance(dialog, SettingsInspectorWindow)

    assert dialog.set_editor_value("style.font_size", "18") is True
    dialog.findChild(QPushButton, "settings_inspector.save").click()
    qapplication.processEvents()

    loaded = store.load("main_window.window")
    assert loaded.document is not None
    assert loaded.document.values == {"style.font_size": 18}
    assert window.font().pointSize() == 14
    assert dict(_last_record(app, "settings_inspector.save").metadata) == {
        "target_metadata_id": "main_window.window",
    }

    assert dialog.set_editor_value("style.font_size", "19") is True
    dialog.findChild(QPushButton, "settings_inspector.apply_changes").click()
    qapplication.processEvents()

    loaded = store.load("main_window.window")
    assert loaded.document is not None
    assert loaded.document.values == {"style.font_size": 19}
    assert window.font().pointSize() == 19
    assert _recent_action_ids(app)[-1] == "settings_inspector.apply_changes"
    assert _recent_action_ids(app).count("settings_inspector.save") == 1
    assert _recent_action_ids(app).count("settings_inspector.apply_changes") == 1

    _dispose(qapplication, window, dialog)
    app.shutdown()


def test_runtime_manager_refresh_and_close_actions_are_recorded_and_visible(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window
    assert isinstance(runtime_window, RuntimeManagerWindow)

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    actions_table = runtime_window.table_for_id("runtime_manager.actions_table")
    visible_action_ids = {
        actions_table.item(row, 0).text() for row in range(actions_table.rowCount())
    }

    assert "runtime_manager.refresh_snapshot" in visible_action_ids
    assert _recent_action_ids(app)[-1] == "runtime_manager.refresh_snapshot"
    assert runtime_window.refresh_called is True

    runtime_window.action_button_for_id("runtime_manager.close").click()
    qapplication.processEvents()

    assert _recent_action_ids(app)[-1] == "runtime_manager.close"
    assert runtime_window.close_requested_locally is True
    assert runtime_window.isVisible() is False

    _dispose(qapplication, window, runtime_window)
    app.shutdown()


def test_restricted_user_without_runtime_view_cannot_open_or_refresh_runtime_manager(
    qapplication: QApplication,
) -> None:
    context = _policy_context(permissions=())
    root = GuiCompositionRoot(context, track_windows=False)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()

    assert window.runtime_manager_window is None
    assert "main_window.open_runtime_manager" not in _recent_action_ids(context)
    denied = _last_audit_event(context, "gui.action.denied")
    assert denied.action_id == "main_window.open_runtime_manager"
    assert denied.window_id == "main_window.window"
    assert denied.actor_id == "restricted-user"
    assert denied.session_id == "session-restricted-user"
    assert denied.payload["required_permissions"] == ("runtime:view",)
    assert denied.payload["reason"] == "missing_permission"

    observer = build_gui_action_observer(context)
    runtime_window = RuntimeManagerWindow(
        load_runtime_manager_profile(),
        snapshot_provider=context.runtime_manager.snapshot,
        action_observer=observer,
    )
    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert context.runtime_manager.calls == 0
    assert runtime_window.refresh_called is False
    assert "runtime_manager.refresh_snapshot" not in _recent_action_ids(context)
    denied = _last_audit_event(context, "gui.action.denied")
    assert denied.action_id == "runtime_manager.refresh_snapshot"
    assert denied.window_id == "runtime_manager.window"
    assert denied.payload["required_permissions"] == ("runtime:view",)

    _dispose(qapplication, window, runtime_window)


def test_restricted_user_without_gui_settings_manage_cannot_open_save_or_apply_settings(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context = _policy_context(permissions=(Permission.RUNTIME_VIEW,))
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(context, track_windows=False, override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert window.settings_inspector_window is None
    assert "main_window.open_settings_inspector" not in _recent_action_ids(context)
    denied = _last_audit_event(context, "gui.action.denied")
    assert denied.action_id == "main_window.open_settings_inspector"
    assert denied.payload["required_permissions"] == ("gui_settings:manage",)
    assert denied.payload["reason"] == "missing_permission"

    dialog = SettingsInspectorWindow(
        GuiSettingsInspectorViewModel(_load_main_window_document(), store),
        on_apply=lambda _metadata_id, _profile: pytest.fail("apply should be denied"),
        action_observer=build_gui_action_observer(context),
    )

    assert dialog.set_editor_value("style.font_size", "18") is True
    dialog.findChild(QPushButton, "settings_inspector.save").click()
    qapplication.processEvents()

    assert store.path_for("main_window.window").exists() is False
    assert "settings_inspector.save" not in _recent_action_ids(context)
    denied = _last_audit_event(context, "gui.action.denied")
    assert denied.action_id == "settings_inspector.save"
    assert denied.payload["required_permissions"] == ("gui_settings:manage",)

    dialog.findChild(QPushButton, "settings_inspector.apply_changes").click()
    qapplication.processEvents()

    assert store.path_for("main_window.window").exists() is False
    assert "settings_inspector.apply_changes" not in _recent_action_ids(context)
    denied = _last_audit_event(context, "gui.action.denied")
    assert denied.action_id == "settings_inspector.apply_changes"
    assert denied.payload["required_permissions"] == ("gui_settings:manage",)

    _dispose(qapplication, window, dialog)


def test_runtime_manager_close_remains_allowed_without_permission(
    qapplication: QApplication,
) -> None:
    context = _policy_context(permissions=())
    runtime_window = RuntimeManagerWindow(
        load_runtime_manager_profile(),
        action_observer=build_gui_action_observer(context),
    )
    runtime_window.show()
    qapplication.processEvents()

    runtime_window.action_button_for_id("runtime_manager.close").click()
    qapplication.processEvents()

    assert _recent_action_ids(context)[-1] == "runtime_manager.close"
    assert runtime_window.close_requested_locally is True
    assert runtime_window.isVisible() is False
    assert not [
        event
        for event in context.audit_log.snapshot()
        if event.event_type == "gui.action.denied"
        and event.action_id == "runtime_manager.close"
    ]

    _dispose(qapplication, runtime_window)


def test_action_tracking_keeps_qt_windows_free_of_core_concrete_imports() -> None:
    for path in _WINDOW_SOURCES:
        source = path.read_text(encoding="utf-8")

        assert "leonardo.core" not in source
        assert "LeonardoApp" not in source
        assert "ActionRegistry" not in source
        assert "WindowRegistry" not in source
        assert "OperationRegistry" not in source


class _RuntimeSnapshotProvider:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {"health": "ok", "sections": (), "recent_audit_events": ()}


def _policy_context(
    *,
    permissions: tuple[Permission, ...],
    is_active: bool = True,
):
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    user = UserRef(
        user_id="restricted-user",
        username="Restricted User",
        roles=(UserRole.USER,),
        permissions=permissions,
        is_active=is_active,
    )
    session = SessionContext(
        session_id="session-restricted-user",
        actor=user,
        origin=ActorOrigin.HUMAN,
        started_at_utc=datetime(2026, 7, 5, 12, tzinfo=UTC),
    )
    return SimpleNamespace(
        audit_log=audit_log,
        state_store=state_store,
        session_manager=SessionManager(
            audit_log=audit_log,
            session_context=session,
        ),
        user_policy=UserPolicy(),
        action_registry=ActionRegistry(state_store),
        runtime_manager=_RuntimeSnapshotProvider(),
    )


def _load_main_window_document():
    result = load_metadata_document(
        _REPO_ROOT
        / "src"
        / "leonardo"
        / "gui"
        / "metadata"
        / "windows"
        / "main_window.window.toml"
    )
    assert result.document is not None
    assert result.report.has_errors is False
    return result.document


def _recent_action_ids(context: object) -> tuple[str, ...]:
    return tuple(
        record.action_id for record in context.action_registry.recent_triggers()
    )


def _last_record(context: object, action_id: str):
    for record in reversed(context.action_registry.recent_triggers()):
        if record.action_id == action_id:
            return record
    raise AssertionError(f"Missing action trigger record: {action_id}")


def _last_audit_event(context: object, event_type: str):
    for event in reversed(context.audit_log.snapshot()):
        if event.event_type == event_type:
            return event
    raise AssertionError(f"Missing audit event: {event_type}")


def _dispose(qapplication: QApplication, *widgets: QWidget | None) -> None:
    for widget in widgets:
        if widget is not None:
            widget.close()
            widget.deleteLater()
    qapplication.processEvents()


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
