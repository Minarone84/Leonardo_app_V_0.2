import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.contracts.gui import WindowDefinition  # noqa: E402
from leonardo.gui.composition import (  # noqa: E402
    GuiCompositionRoot,
    create_main_window_for_context,
)
from leonardo.gui.windows.download_request_builder_window import (  # noqa: E402
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    DownloadRequestBuilderWindow,
)
from leonardo.gui.windows.main_window import LeonardoMainWindow  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSITION_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "composition.py"


class FakeRuntimeManager:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {
            "health": "ok",
            "sections": (
                {
                    "section_id": "services",
                    "status": "ok",
                    "count": 1,
                    "message": "1 service visible",
                    "metadata": {"service_ids": ("runtime-service",)},
                },
            ),
            "recent_audit_events": (),
        }


class FakeWindowRegistry:
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


class FakeDownloadManager:
    def __init__(self) -> None:
        self.submit_calls = 0

    def submit_request(self, request: object) -> object:
        self.submit_calls += 1
        raise AssertionError("composition must not submit download requests")


class FakeCoreContext:
    def __init__(self) -> None:
        self.runtime_manager = FakeRuntimeManager()
        self.window_registry = FakeWindowRegistry()
        self.download_manager = FakeDownloadManager()


def test_composition_creates_main_window_from_context_without_startup(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    app_instance = QApplication.instance()
    root = GuiCompositionRoot(context)

    window = root.create_main_window()

    assert isinstance(window, LeonardoMainWindow)
    assert QApplication.instance() is app_instance
    assert context.runtime_manager.calls == 0
    assert context.window_registry.calls == []
    assert root.tracker_for("main_window.window") is not None

    window.deleteLater()
    qapplication.processEvents()


def test_function_helper_uses_gui_composition_root(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()

    window = create_main_window_for_context(context)

    assert isinstance(window, LeonardoMainWindow)
    assert context.runtime_manager.calls == 0

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_factory_is_injected_and_uses_snapshot_provider_lazily(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert context.runtime_manager.calls == 0
    assert root.tracker_for("runtime_manager.window") is not None

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert context.runtime_manager.calls == 1
    assert runtime_window.last_rendered_snapshot_summary["status"] == "rendered"

    runtime_window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()


def test_composition_injects_inert_download_placeholder_callbacks(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window

    assert isinstance(builder, DownloadRequestBuilderWindow)
    assert builder.workflow_mode == DOWNLOAD_DATA_WORKFLOW_MODE
    assert builder.isVisible() is True
    assert window.statusBar().currentMessage() == "Download Data request builder opened."
    assert context.download_manager.submit_calls == 0

    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    qapplication.processEvents()

    assert root.download_request_builder_window is builder
    assert builder.workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE
    assert window.statusBar().currentMessage() == (
        "OHLCV Maintenance request builder opened."
    )
    assert context.download_manager.submit_calls == 0

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_window_tracking_reports_lifecycle_only_after_window_events(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    assert context.window_registry.calls == []

    window.show()
    qapplication.processEvents()
    window.close()
    qapplication.processEvents()

    assert "register_window" in context.window_registry.calls
    assert "open_window" in context.window_registry.calls
    assert "request_window_close" in context.window_registry.calls
    assert "close_window" in context.window_registry.calls
    assert context.window_registry.widgets_seen == 0

    window.deleteLater()
    qapplication.processEvents()


def test_composition_can_disable_window_tracking(qapplication: QApplication) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context, track_windows=False)

    window = root.create_main_window()
    window.show()
    qapplication.processEvents()

    assert root.window_trackers == {}
    assert context.window_registry.calls == []

    window.close()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_source_does_not_construct_app_or_qapplication() -> None:
    source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")

    assert "LeonardoApp" not in source
    assert "QApplication" not in source
    assert ".startup(" not in source
    assert ".shutdown(" not in source
    assert "DownloadRequest(" not in source
    assert "leonardo.contracts.downloads" not in source
    assert ".submit_request(" not in source


def test_composed_windows_destroy_cleanly(qapplication: QApplication) -> None:
    context = FakeCoreContext()
    window = GuiCompositionRoot(context).create_main_window()

    window.show()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert runtime_window is not None
    window.close()
    window.deleteLater()
    runtime_window.deleteLater()
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
