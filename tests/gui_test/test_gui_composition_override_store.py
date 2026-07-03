import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.contracts.gui import WindowDefinition  # noqa: E402
from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import (  # noqa: E402
    GuiMetadataOverrideDocument,
    GuiMetadataOverrideStore,
    OVERRIDE_FILE_SCHEMA_VERSION,
)
from leonardo.gui.windows.main_window import LeonardoMainWindow  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402


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


class FakeRuntimeManager:
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
    def __init__(self) -> None:
        self.definitions: dict[str, WindowDefinition] = {}
        self.open_ids: set[str] = set()
        self.calls: list[str] = []
        self.widgets_seen = 0

    def get_window_definition(self, window_id: str) -> WindowDefinition | None:
        self._reject_widget(window_id)
        self.calls.append("get_window_definition")
        return self.definitions.get(window_id)

    def register_window(self, definition: WindowDefinition) -> WindowDefinition:
        self._reject_widget(definition)
        self.calls.append("register_window")
        self.definitions[definition.window_id] = definition
        return definition

    def open_windows(self) -> tuple[object, ...]:
        self.calls.append("open_windows")
        return tuple(SimpleNamespace(window_id=window_id) for window_id in self.open_ids)

    def open_window(
        self,
        window_id: str,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> object:
        self._reject_widget(window_id, owner_action_id, current_operation_id, metadata)
        self.calls.append("open_window")
        self.open_ids.add(window_id)
        return SimpleNamespace(window_id=window_id)

    def focus_window(self, window_id: str) -> object:
        self._reject_widget(window_id)
        self.calls.append("focus_window")
        return SimpleNamespace(window_id=window_id)

    def request_window_close(self, window_id: str) -> object:
        self._reject_widget(window_id)
        self.calls.append("request_window_close")
        return SimpleNamespace(window_id=window_id)

    def close_window(self, window_id: str) -> object:
        self._reject_widget(window_id)
        self.calls.append("close_window")
        self.open_ids.discard(window_id)
        return SimpleNamespace(window_id=window_id)

    def _reject_widget(self, *values: object) -> None:
        for value in values:
            if isinstance(value, QWidget):
                self.widgets_seen += 1
                raise AssertionError("registry received QWidget")
            if isinstance(value, dict):
                self._reject_widget(*value.values())


class FakeContext:
    def __init__(self, *, runs_dir: Path | None = None) -> None:
        self.runtime_manager = FakeRuntimeManager()
        self.window_registry = FakeRegistry()
        self.config = SimpleNamespace(
            paths=SimpleNamespace(runs_dir=runs_dir),
        )


def test_composition_works_without_override_store(
    qapplication: QApplication,
) -> None:
    context = FakeContext()
    root = GuiCompositionRoot(context)

    window = root.create_main_window()

    assert isinstance(window, LeonardoMainWindow)
    assert window.profile.values["style"]["font_size"] == 14
    assert window.font().pointSize() == 14
    assert root.override_load_results == {}

    window.deleteLater()
    qapplication.processEvents()


def test_composition_applies_main_window_persisted_override(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
    )
    root = GuiCompositionRoot(FakeContext(), override_store=store)

    window = root.create_main_window()

    assert window.profile.values["style"]["font_size"] == 18
    assert window.font().pointSize() == 18
    assert root.override_load_results["main_window.window"].ok is True

    window.deleteLater()
    qapplication.processEvents()


def test_composition_applies_runtime_manager_persisted_override(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(
        tmp_path,
        "runtime_manager.window",
        {"style.font_size": 16},
    )
    root = GuiCompositionRoot(FakeContext(), override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert runtime_window.profile.values["style"]["font_size"] == 16
    assert runtime_window.font().pointSize() == 16
    assert root.override_load_results["runtime_manager.window"].ok is True

    runtime_window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()


def test_runtime_snapshot_provider_remains_lazy_with_overrides(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context = FakeContext()
    store = _store_with_override(
        tmp_path,
        "runtime_manager.window",
        {"style.font_size": 16},
    )
    root = GuiCompositionRoot(context, override_store=store)
    window = root.create_main_window()

    assert context.runtime_manager.calls == 0

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert context.runtime_manager.calls == 0

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert context.runtime_manager.calls == 1

    runtime_window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()


def test_corrupt_main_window_override_falls_back_with_diagnostics(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    _write_corrupt_override(store, "main_window.window")
    root = GuiCompositionRoot(FakeContext(), override_store=store)

    window = root.create_main_window()
    result = root.override_load_results["main_window.window"]

    assert window.profile.values["style"]["font_size"] == 14
    assert window.font().pointSize() == 14
    assert result.ok is False
    assert result.errors[0].code == "corrupt_json"

    window.deleteLater()
    qapplication.processEvents()


def test_corrupt_runtime_manager_override_falls_back_with_diagnostics(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    _write_corrupt_override(store, "runtime_manager.window")
    root = GuiCompositionRoot(FakeContext(), override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window
    result = root.override_load_results["runtime_manager.window"]

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert runtime_window.profile.values["style"]["font_size"] == 14
    assert runtime_window.font().pointSize() == 14
    assert result.ok is False
    assert result.errors[0].code == "corrupt_json"

    runtime_window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()


def test_metadata_toml_files_are_not_modified(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    before_main = _MAIN_METADATA_PATH.read_text(encoding="utf-8")
    before_runtime = _RUNTIME_METADATA_PATH.read_text(encoding="utf-8")
    store = _store_with_override(
        tmp_path,
        "runtime_manager.window",
        {"style.font_size": 16},
    )
    root = GuiCompositionRoot(FakeContext(), override_store=store)

    window = root.create_main_window()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert _MAIN_METADATA_PATH.read_text(encoding="utf-8") == before_main
    assert _RUNTIME_METADATA_PATH.read_text(encoding="utf-8") == before_runtime

    if runtime_window is not None:
        runtime_window.close()
        runtime_window.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_override_store_root_is_injected_not_derived_from_context(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context_runs_dir = tmp_path / "context_runs"
    override_root = tmp_path / "explicit_override_root"
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
        root=override_root,
    )

    window = GuiCompositionRoot(
        FakeContext(runs_dir=context_runs_dir),
        override_store=store,
    ).create_main_window()

    assert window.font().pointSize() == 18
    assert store.root == override_root
    assert context_runs_dir.exists() is False

    window.deleteLater()
    qapplication.processEvents()


def test_no_production_override_files_are_written_outside_tmp_path(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
    )

    window = GuiCompositionRoot(FakeContext(), override_store=store).create_main_window()

    assert _path_is_relative_to(store.path_for("main_window.window"), tmp_path)
    assert list((_REPO_ROOT / "src").rglob("*.override.json")) == []

    window.deleteLater()
    qapplication.processEvents()


def test_no_app_startup_is_required(qapplication: QApplication, tmp_path: Path) -> None:
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
    )
    source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")

    window = GuiCompositionRoot(FakeContext(), override_store=store).create_main_window()

    assert window.font().pointSize() == 18
    assert ".startup(" not in source
    assert ".shutdown(" not in source

    window.deleteLater()
    qapplication.processEvents()


def test_no_qapplication_startup_is_created(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    app_instance = QApplication.instance()
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
    )

    window = GuiCompositionRoot(FakeContext(), override_store=store).create_main_window()

    assert QApplication.instance() is app_instance
    assert "QApplication" not in _COMPOSITION_SOURCE.read_text(encoding="utf-8")

    window.deleteLater()
    qapplication.processEvents()


def test_no_core_mutation_is_introduced(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context = FakeContext()
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
    )

    window = GuiCompositionRoot(context, override_store=store).create_main_window()

    assert context.runtime_manager.calls == 0
    assert context.window_registry.calls == []

    window.deleteLater()
    qapplication.processEvents()


def test_existing_window_tracking_remains_intact_with_overrides(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context = FakeContext()
    store = _store_with_override(
        tmp_path,
        "main_window.window",
        {"style.font_size": 18},
    )
    root = GuiCompositionRoot(context, override_store=store)
    window = root.create_main_window()

    window.show()
    qapplication.processEvents()
    window.close()
    qapplication.processEvents()

    assert root.tracker_for("main_window.window") is not None
    assert "register_window" in context.window_registry.calls
    assert "open_window" in context.window_registry.calls
    assert "request_window_close" in context.window_registry.calls
    assert "close_window" in context.window_registry.calls
    assert context.window_registry.widgets_seen == 0

    window.deleteLater()
    qapplication.processEvents()


def _store_with_override(
    tmp_path: Path,
    metadata_id: str,
    values: dict[str, object],
    *,
    root: Path | None = None,
) -> GuiMetadataOverrideStore:
    store = GuiMetadataOverrideStore(root or tmp_path / "overrides")
    result = store.save(
        GuiMetadataOverrideDocument(
            metadata_id=metadata_id,
            values=values,
        )
    )
    assert result.ok is True
    return store


def _write_corrupt_override(
    store: GuiMetadataOverrideStore,
    metadata_id: str,
) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    store.path_for(metadata_id).write_text("{not json", encoding="utf-8")


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
