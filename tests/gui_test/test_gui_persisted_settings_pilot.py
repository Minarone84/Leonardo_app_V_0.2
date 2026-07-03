import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import (  # noqa: E402
    GuiMetadataOverrideDocument,
    GuiMetadataOverrideStore,
    GuiMetadataSessionState,
    OVERRIDE_FILE_SCHEMA_VERSION,
)
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSITION_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "composition.py"
_MAIN_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "main_window.window.toml"
)
_RUNTIME_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "runtime_manager.window.toml"
)


class FakeRuntimeSnapshotSource:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {
            "health": "ok",
            "sections": (),
            "recent_audit_events": (),
        }


class FakeRegistry:
    def get_window_definition(self, window_id: str) -> None:
        return None

    def register_window(self, definition: object) -> object:
        return definition

    def open_windows(self) -> tuple[object, ...]:
        return ()

    def open_window(
        self,
        window_id: str,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> object:
        return _WindowHandle(window_id)

    def focus_window(self, window_id: str) -> object:
        return _WindowHandle(window_id)

    def request_window_close(self, window_id: str) -> object:
        return _WindowHandle(window_id)

    def close_window(self, window_id: str) -> object:
        return _WindowHandle(window_id)


class FakeGuiContext:
    def __init__(self) -> None:
        self.runtime_manager = FakeRuntimeSnapshotSource()
        self.window_registry = FakeRegistry()


class _WindowHandle:
    def __init__(self, window_id: str) -> None:
        self.window_id = window_id


def test_main_window_persisted_font_size_is_applied_after_composition_construction(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})
    root = GuiCompositionRoot(FakeGuiContext(), override_store=store)

    window = root.create_main_window()

    assert window.profile.values["style"]["font_size"] == 18
    assert window.font().pointSize() == 18
    assert root.override_load_results["main_window.window"].ok is True

    _dispose_windows(qapplication, window)


def test_runtime_manager_persisted_font_size_is_applied_through_main_window_handoff(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(
        tmp_path,
        "runtime_manager.window",
        {"style.font_size": 16},
    )
    root = GuiCompositionRoot(FakeGuiContext(), override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert runtime_window.profile.values["style"]["font_size"] == 16
    assert runtime_window.font().pointSize() == 16
    assert root.override_load_results["runtime_manager.window"].ok is True

    _dispose_windows(qapplication, window, runtime_window)


def test_reset_field_removes_persisted_override_and_reload_restores_source_default(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})
    first_window = GuiCompositionRoot(
        FakeGuiContext(),
        override_store=store,
    ).create_main_window()

    reset_result = store.reset_field("main_window.window", "style.font_size")
    second_window = GuiCompositionRoot(
        FakeGuiContext(),
        override_store=store,
    ).create_main_window()

    assert first_window.font().pointSize() == 18
    assert reset_result.ok is True
    assert store.path_for("main_window.window").exists() is False
    assert second_window.profile.values["style"]["font_size"] == 14
    assert second_window.font().pointSize() == 14

    _dispose_windows(qapplication, first_window, second_window)


def test_reset_profile_deletes_override_file_and_reload_restores_source_default(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(
        tmp_path,
        "runtime_manager.window",
        {"style.font_size": 16},
    )
    path = store.path_for("runtime_manager.window")
    assert path.exists()

    reset_result = store.reset_profile("runtime_manager.window")
    root = GuiCompositionRoot(FakeGuiContext(), override_store=store)
    window = root.create_main_window()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert reset_result.ok is True
    assert path.exists() is False
    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert runtime_window.profile.values["style"]["font_size"] == 14
    assert runtime_window.font().pointSize() == 14

    _dispose_windows(qapplication, window, runtime_window)


def test_source_toml_files_remain_unchanged_before_after_save_reset_reload(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    before_main = _MAIN_METADATA_PATH.read_text(encoding="utf-8")
    before_runtime = _RUNTIME_METADATA_PATH.read_text(encoding="utf-8")
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})
    runtime_save_result = store.save(
        GuiMetadataOverrideDocument(
            metadata_id="runtime_manager.window",
            values={"style.font_size": 16},
        )
    )
    root = GuiCompositionRoot(FakeGuiContext(), override_store=store)

    window = root.create_main_window()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window
    field_reset_result = store.reset_field("main_window.window", "style.font_size")
    profile_reset_result = store.reset_profile("runtime_manager.window")
    reload_window = GuiCompositionRoot(
        FakeGuiContext(),
        override_store=store,
    ).create_main_window()

    assert runtime_save_result.ok is True
    assert field_reset_result.ok is True
    assert profile_reset_result.ok is True
    assert _MAIN_METADATA_PATH.read_text(encoding="utf-8") == before_main
    assert _RUNTIME_METADATA_PATH.read_text(encoding="utf-8") == before_runtime

    _dispose_windows(qapplication, window, runtime_window, reload_window)


def test_session_state_values_are_not_saved_in_override_files(tmp_path: Path) -> None:
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})
    session_state = GuiMetadataSessionState(
        metadata_id="main_window.window",
        values={"style.font_size": 22},
    )

    payload = _load_json(store.path_for("main_window.window"))

    assert session_state.values == {"style.font_size": 22}
    assert set(payload) == {
        "schema_version",
        "metadata_id",
        "updated_at_ms",
        "overrides",
    }
    assert payload["schema_version"] == OVERRIDE_FILE_SCHEMA_VERSION
    assert payload["overrides"] == {"style.font_size": 18}
    assert "session_state" not in payload
    assert "session" not in payload
    assert session_state.values["style.font_size"] not in payload["overrides"].values()


def test_corrupt_persisted_setting_falls_back_to_default_and_exposes_diagnostics(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    _write_corrupt_override(store, "main_window.window")
    root = GuiCompositionRoot(FakeGuiContext(), override_store=store)

    window = root.create_main_window()
    result = root.override_load_results["main_window.window"]

    assert window.profile.values["style"]["font_size"] == 14
    assert window.font().pointSize() == 14
    assert result.ok is False
    assert result.errors[0].code == "corrupt_json"

    _dispose_windows(qapplication, window)


def test_runtime_manager_snapshot_provider_remains_lazy_during_persisted_settings_load(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context = FakeGuiContext()
    store = _store_with_override(
        tmp_path,
        "runtime_manager.window",
        {"style.font_size": 16},
    )
    root = GuiCompositionRoot(context, override_store=store)

    window = root.create_main_window()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert context.runtime_manager.calls == 0

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert context.runtime_manager.calls == 1

    _dispose_windows(qapplication, window, runtime_window)


def test_no_production_override_files_are_written_outside_tmp_path(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})

    window = GuiCompositionRoot(FakeGuiContext(), override_store=store).create_main_window()

    store.path_for("main_window.window").resolve(strict=False).relative_to(
        tmp_path.resolve(strict=False)
    )
    assert list((_REPO_ROOT / "src").rglob("*.override.json")) == []

    _dispose_windows(qapplication, window)


def test_settings_inspector_action_opens_dialog_without_runtime_manager(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})
    window = GuiCompositionRoot(FakeGuiContext(), override_store=store).create_main_window()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.open_settings_inspector"
    assert window.runtime_manager_window is None
    assert isinstance(window.settings_inspector_window, SettingsInspectorWindow)
    assert window.settings_inspector_window.isVisible() is True
    assert window.settings_inspector_window.viewmodel.metadata_id == "main_window.window"

    _dispose_windows(qapplication, window, window.settings_inspector_window)


def test_no_application_or_qapplication_startup_is_required(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    app_instance = QApplication.instance()
    store = _store_with_override(tmp_path, "main_window.window", {"style.font_size": 18})
    source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")

    window = GuiCompositionRoot(FakeGuiContext(), override_store=store).create_main_window()

    assert window.font().pointSize() == 18
    assert QApplication.instance() is app_instance
    assert "QApplication" not in source
    assert ".startup(" not in source
    assert ".shutdown(" not in source

    _dispose_windows(qapplication, window)


def _store_with_override(
    tmp_path: Path,
    metadata_id: str,
    values: dict[str, object],
) -> GuiMetadataOverrideStore:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    result = store.save(
        GuiMetadataOverrideDocument(
            metadata_id=metadata_id,
            values=values,
        )
    )
    assert result.ok is True
    return store


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_corrupt_override(store: GuiMetadataOverrideStore, metadata_id: str) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    store.path_for(metadata_id).write_text("{not json", encoding="utf-8")


def _dispose_windows(qapplication: QApplication, *windows: object) -> None:
    for window in windows:
        if window is None:
            continue
        close = getattr(window, "close", None)
        if callable(close):
            close()
        delete_later = getattr(window, "deleteLater", None)
        if callable(delete_later):
            delete_later()
    qapplication.processEvents()


@pytest.fixture
def qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
