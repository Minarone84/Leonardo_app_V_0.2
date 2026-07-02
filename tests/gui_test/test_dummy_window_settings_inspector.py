import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget  # noqa: E402

from leonardo.gui.metadata import ResolvedValueSource  # noqa: E402
from leonardo.gui.windows.dummy_metadata_settings_inspector import (  # noqa: E402
    DummyMetadataSettingsInspector,
)
from leonardo.gui.windows.dummy_metadata_test_window import (  # noqa: E402
    DummyMetadataTestWindow,
    load_dummy_metadata_profile,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DUMMY_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "dummy_metadata_test.window.toml"
)


def test_inspector_constructs_and_reads_settings_exposure(
    qapplication: QApplication,
) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())

    assert inspector.objectName() == "dummy_metadata_settings_inspector"
    assert inspector.exposed_setting_paths() == (
        "style.font_size",
        "style.density",
        "geometry.width",
        "geometry.height",
    )
    assert inspector.findChild(QTableWidget, "dummy_metadata_settings_table") is not None

    inspector.deleteLater()
    qapplication.processEvents()


def test_inspector_lists_only_exposed_settings(qapplication: QApplication) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())
    paths = inspector.exposed_setting_paths()

    assert "style.font_size" in paths
    assert "metadata.contract_id" not in paths
    assert "action_id" not in paths
    assert "widget_id" not in paths
    assert "table_id" not in paths
    assert "identity.schema_version" not in paths

    inspector.deleteLater()
    qapplication.processEvents()


def test_inspector_exposes_default_current_and_override_status(
    qapplication: QApplication,
) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())

    snapshot = inspector.setting_snapshot("style.font_size")

    assert snapshot["label"] == "Font Size"
    assert snapshot["default"] == 14
    assert snapshot["current"] == 14
    assert snapshot["has_override"] is False
    assert snapshot["source"] is ResolvedValueSource.METADATA_DEFAULT

    inspector.deleteLater()
    qapplication.processEvents()


def test_saving_supported_setting_updates_in_memory_changed_only_override(
    qapplication: QApplication,
) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())

    inspector.set_editor_value("style.font_size", 11)
    assert inspector.save_selected_setting() is True

    assert inspector.current_override_document.values == {"style.font_size": 11}
    assert inspector.effective_profile.values["style"]["font_size"] == 11
    assert inspector.setting_snapshot("style.font_size")["has_override"] is True

    inspector.deleteLater()
    qapplication.processEvents()


def test_reset_selected_removes_only_selected_override(
    qapplication: QApplication,
) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())
    inspector.set_editor_value("style.font_size", 11)
    assert inspector.save_selected_setting() is True
    inspector.set_editor_value("geometry.width", 1000)
    assert inspector.save_selected_setting() is True

    inspector.select_setting("style.font_size")
    assert inspector.reset_selected_setting() is True

    assert inspector.current_override_document.values == {"geometry.width": 1000}
    assert inspector.effective_profile.values["style"]["font_size"] == 14
    assert inspector.effective_profile.values["geometry"]["width"] == 1000

    inspector.deleteLater()
    qapplication.processEvents()


def test_reset_all_removes_all_overrides_and_restores_defaults(
    qapplication: QApplication,
) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())
    inspector.set_editor_value("style.font_size", 11)
    assert inspector.save_selected_setting() is True
    inspector.set_editor_value("geometry.width", 1000)
    assert inspector.save_selected_setting() is True

    inspector.reset_all_settings()

    assert inspector.current_override_document.values == {}
    assert inspector.effective_profile.values["style"]["font_size"] == 14
    assert inspector.effective_profile.values["geometry"]["width"] == 1120
    assert inspector.setting_snapshot("style.font_size")["source"] is (
        ResolvedValueSource.METADATA_DEFAULT
    )

    inspector.deleteLater()
    qapplication.processEvents()


def test_invalid_edit_does_not_update_override(qapplication: QApplication) -> None:
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())

    inspector.set_editor_value("style.font_size", "banana")

    assert inspector.save_selected_setting() is False
    assert inspector.current_override_document.values == {}
    assert "Expected integer" in inspector.last_error

    inspector.deleteLater()
    qapplication.processEvents()


def test_preview_and_save_apply_local_effect_to_dummy_window(
    qapplication: QApplication,
) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    inspector = DummyMetadataSettingsInspector(
        window.profile,
        target_window=window,
        parent=window,
    )

    inspector.set_editor_value("style.font_size", 10)
    assert inspector.preview_selected_setting() is True
    assert window.font().pointSize() == 10
    assert inspector.current_override_document.values == {}

    assert inspector.save_selected_setting() is True
    assert window.profile.values["style"]["font_size"] == 10
    assert inspector.current_override_document.values == {"style.font_size": 10}

    inspector.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_inspector_does_not_write_or_mutate_source_metadata(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    before = _DUMMY_METADATA_PATH.read_text(encoding="utf-8")
    inspector = DummyMetadataSettingsInspector(load_dummy_metadata_profile())

    inspector.set_editor_value("style.font_size", 11)
    assert inspector.save_selected_setting() is True
    inspector.reset_all_settings()

    assert _DUMMY_METADATA_PATH.read_text(encoding="utf-8") == before
    assert list(tmp_path.iterdir()) == []

    inspector.deleteLater()
    qapplication.processEvents()


def test_inspector_and_dummy_window_require_no_core_services(
    qapplication: QApplication,
) -> None:
    window = DummyMetadataTestWindow()
    inspector = DummyMetadataSettingsInspector(target_window=window)

    assert window.profile.metadata_id == "dummy_metadata_test.window"
    assert inspector.effective_profile.metadata_id == "dummy_metadata_test.window"

    inspector.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_opens_inspector_locally(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    open_settings = window.findChild(QPushButton, "dummy_metadata_test.open_settings")

    assert open_settings is not None
    open_settings.click()
    qapplication.processEvents()

    assert window.settings_inspector is not None
    assert window.settings_inspector.objectName() == "dummy_metadata_settings_inspector"
    assert window.findChild(QPushButton, "dummy_metadata_settings_save") is not None

    window.settings_inspector.close()
    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_destroys_cleanly_after_inspector_use(
    qapplication: QApplication,
) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    open_settings = window.findChild(QPushButton, "dummy_metadata_test.open_settings")
    assert open_settings is not None

    open_settings.click()
    qapplication.processEvents()
    window.close()
    window.deleteLater()
    qapplication.processEvents()

    assert window.close_requested_locally is True


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
