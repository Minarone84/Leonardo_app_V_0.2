import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import GuiMetadataOverrideStore, load_metadata_document  # noqa: E402
from leonardo.gui.settings_profiles import (  # noqa: E402
    MAIN_WINDOW_SETTINGS_PROFILE_ID,
    RUNTIME_MANAGER_SETTINGS_PROFILE_ID,
    GuiSettingsProfileProvider,
    GuiSettingsProfileRef,
)
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_PROFILES_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "settings_profiles.py"
)
_COMPOSITION_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "composition.py"
_MAIN_WINDOW_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "main_window.py"
)
_RUNTIME_MANAGER_WINDOW_SOURCE = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "runtime_manager_window.py"
)
_SETTINGS_INSPECTOR_WINDOW_SOURCE = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "settings_inspector_window.py"
)


class FakeRuntimeManager:
    def snapshot(self) -> dict[str, object]:
        return {"health": "ok", "sections": (), "recent_audit_events": ()}


class FakeCoreContext:
    def __init__(self) -> None:
        self.runtime_manager = FakeRuntimeManager()


class RecordingSettingsProfileProvider(GuiSettingsProfileProvider):
    def __init__(self) -> None:
        self.requested_profile_ids: list[str] = []

    def get_profile(self, metadata_id: str) -> GuiSettingsProfileRef:
        self.requested_profile_ids.append(metadata_id)
        return super().get_profile(metadata_id)


def test_settings_profile_provider_exposes_only_allowlisted_profiles() -> None:
    provider = GuiSettingsProfileProvider()

    profile_ids = tuple(profile.metadata_id for profile in provider.list_profiles())

    assert profile_ids == (
        MAIN_WINDOW_SETTINGS_PROFILE_ID,
        RUNTIME_MANAGER_SETTINGS_PROFILE_ID,
    )
    assert "dummy_metadata_test.window" not in profile_ids


def test_settings_profile_provider_returns_main_window_source_reference() -> None:
    provider = GuiSettingsProfileProvider()

    profile = provider.get_profile(MAIN_WINDOW_SETTINGS_PROFILE_ID)

    assert profile.metadata_id == MAIN_WINDOW_SETTINGS_PROFILE_ID
    assert profile.title == "Leonardo"
    assert profile.metadata_path.name == "main_window.window.toml"
    assert profile.metadata_path.exists() is True
    assert profile.owner_area == "gui"
    assert profile.logical_kind == "main_application_shell"


def test_settings_profile_provider_returns_runtime_manager_source_reference() -> None:
    provider = GuiSettingsProfileProvider()

    profile = provider.get_profile(RUNTIME_MANAGER_SETTINGS_PROFILE_ID)
    result = load_metadata_document(profile.metadata_path)

    assert profile.metadata_id == RUNTIME_MANAGER_SETTINGS_PROFILE_ID
    assert profile.title == "Runtime Manager"
    assert profile.metadata_path.name == "runtime_manager.window.toml"
    assert profile.metadata_path.exists() is True
    assert profile.owner_area == "gui"
    assert profile.logical_kind == "read_only_runtime_inspection"
    assert result.document is not None
    assert result.report.has_errors is False
    assert result.document.metadata_id == RUNTIME_MANAGER_SETTINGS_PROFILE_ID
    assert result.document.metadata["owner_area"] == "gui"
    assert result.document.metadata["target_area_id"] == "runtime"
    assert result.document.metadata["logical_kind"] == "read_only_runtime_inspection"
    assert {
        setting.path for setting in result.document.settings
    } >= {"style.font_size", "style.density"}


@pytest.mark.parametrize(
    "metadata_id",
    ("dummy_metadata_test.window", "missing.window"),
)
def test_settings_profile_provider_rejects_unapproved_profiles(
    metadata_id: str,
) -> None:
    provider = GuiSettingsProfileProvider()

    with pytest.raises(KeyError, match=metadata_id):
        provider.get_profile(metadata_id)


def test_settings_profile_provider_does_not_scan_metadata_directory() -> None:
    source = _SETTINGS_PROFILES_SOURCE.read_text(encoding="utf-8")

    assert ".glob(" not in source
    assert ".rglob(" not in source
    assert ".iterdir(" not in source


def test_settings_profile_provider_has_no_qt_or_core_dependency() -> None:
    source = _SETTINGS_PROFILES_SOURCE.read_text(encoding="utf-8")

    assert "PySide6" not in source
    assert "QtWidgets" not in source
    assert "leonardo.core" not in source


def test_runtime_manager_profile_exposure_does_not_wire_user_facing_surfaces() -> None:
    composition_source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")
    main_window_source = _MAIN_WINDOW_SOURCE.read_text(encoding="utf-8")
    runtime_manager_window_source = _RUNTIME_MANAGER_WINDOW_SOURCE.read_text(
        encoding="utf-8"
    )
    settings_inspector_window_source = _SETTINGS_INSPECTOR_WINDOW_SOURCE.read_text(
        encoding="utf-8"
    )

    assert RUNTIME_MANAGER_SETTINGS_PROFILE_ID not in composition_source
    assert "get_profile(RUNTIME_MANAGER_SETTINGS_PROFILE_ID)" not in composition_source
    assert RUNTIME_MANAGER_SETTINGS_PROFILE_ID not in main_window_source
    assert "GuiSettingsProfileProvider" not in runtime_manager_window_source
    assert "SettingsInspector" not in runtime_manager_window_source
    assert "settings_inspector" not in runtime_manager_window_source
    assert "GuiSettingsProfileProvider" not in settings_inspector_window_source
    assert "list_profiles" not in settings_inspector_window_source


def test_composition_uses_provider_for_current_settings_inspector_factory(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    provider = RecordingSettingsProfileProvider()
    root = GuiCompositionRoot(
        FakeCoreContext(),
        track_windows=False,
        override_store=store,
        settings_profile_provider=provider,
    )
    window = root.create_main_window()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    dialog = window.settings_inspector_window
    assert provider.requested_profile_ids == [MAIN_WINDOW_SETTINGS_PROFILE_ID]
    assert isinstance(dialog, SettingsInspectorWindow)
    assert dialog.viewmodel.metadata_id == MAIN_WINDOW_SETTINGS_PROFILE_ID

    _dispose(qapplication, window, dialog)


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
