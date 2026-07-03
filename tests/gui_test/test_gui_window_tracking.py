import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.contracts.gui import WindowDefinition  # noqa: E402
from leonardo.gui.window_tracking import (  # noqa: E402
    GuiWindowIdentity,
    GuiWindowTracker,
    identity_from_profile,
)
from leonardo.gui.windows.main_window import load_main_window_profile  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOW_TRACKING_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "window_tracking.py"


class FakeWindowRegistry:
    def __init__(self) -> None:
        self.definitions: dict[str, WindowDefinition] = {}
        self.open_ids: set[str] = set()
        self.calls: list[tuple[str, object]] = []
        self.widgets_seen = 0

    def get_window_definition(self, window_id: str) -> WindowDefinition | None:
        self._reject_widgets(window_id)
        self.calls.append(("get_window_definition", window_id))
        return self.definitions.get(window_id)

    def register_window(self, definition: WindowDefinition) -> WindowDefinition:
        self._reject_widgets(definition)
        self.calls.append(("register_window", definition))
        if definition.window_id in self.definitions:
            raise ValueError(f"Window already registered: {definition.window_id}")
        self.definitions[definition.window_id] = definition
        return definition

    def open_windows(self) -> tuple[object, ...]:
        self.calls.append(("open_windows", None))
        return tuple(SimpleNamespace(window_id=window_id) for window_id in self.open_ids)

    def open_window(
        self,
        window_id: str,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> object:
        self._reject_widgets(window_id, owner_action_id, current_operation_id, metadata)
        self.calls.append(("open_window", window_id))
        self.open_ids.add(window_id)
        return SimpleNamespace(window_id=window_id)

    def focus_window(self, window_id: str) -> object:
        self._reject_widgets(window_id)
        self.calls.append(("focus_window", window_id))
        return SimpleNamespace(window_id=window_id)

    def request_window_close(self, window_id: str) -> object:
        self._reject_widgets(window_id)
        self.calls.append(("request_window_close", window_id))
        return SimpleNamespace(window_id=window_id)

    def close_window(self, window_id: str) -> object:
        self._reject_widgets(window_id)
        self.calls.append(("close_window", window_id))
        self.open_ids.discard(window_id)
        return SimpleNamespace(window_id=window_id)

    def _reject_widgets(self, *values: object) -> None:
        for value in values:
            if isinstance(value, QWidget):
                self.widgets_seen += 1
                raise AssertionError("registry received QWidget")
            if isinstance(value, dict):
                self._reject_widgets(*value.values())


def test_tracker_constructs_without_core_application() -> None:
    registry = FakeWindowRegistry()
    tracker = GuiWindowTracker(registry, _identity())

    assert tracker.window_id == "main_window.window"
    assert registry.calls == []


def test_tracker_registers_window_definition_without_widget_payload() -> None:
    registry = FakeWindowRegistry()
    tracker = GuiWindowTracker(registry, _identity())

    definition = tracker.ensure_registered()

    assert definition.window_id == "main_window.window"
    assert definition.title == "Leonardo"
    assert registry.widgets_seen == 0
    assert [call[0] for call in registry.calls] == [
        "get_window_definition",
        "register_window",
    ]


def test_tracker_records_lifecycle_through_registry_public_methods() -> None:
    registry = FakeWindowRegistry()
    tracker = GuiWindowTracker(registry, _identity())

    tracker.mark_opened(owner_action_id="main_window.open_runtime_manager")
    tracker.mark_focused()
    tracker.mark_close_requested()
    tracker.mark_closed()

    assert _call_names(registry) == [
        "get_window_definition",
        "register_window",
        "open_windows",
        "open_window",
        "focus_window",
        "request_window_close",
        "close_window",
    ]
    assert registry.widgets_seen == 0


def test_duplicate_registration_is_handled_safely() -> None:
    registry = FakeWindowRegistry()
    identity = _identity()
    registry.definitions[identity.window_id] = identity.to_definition()
    tracker = GuiWindowTracker(registry, identity)

    definition = tracker.ensure_registered()

    assert definition.window_id == identity.window_id
    assert "register_window" not in _call_names(registry)


def test_duplicate_open_records_are_avoided() -> None:
    registry = FakeWindowRegistry()
    tracker = GuiWindowTracker(registry, _identity())

    tracker.mark_opened()
    tracker.mark_opened()

    assert _call_names(registry).count("open_window") == 1


def test_only_explicit_top_level_windows_are_tracked(qapplication: QApplication) -> None:
    registry = FakeWindowRegistry()
    tracker = GuiWindowTracker(registry, _identity())
    top_level = QWidget()
    embedded = QWidget(top_level)

    assert tracker.track(embedded) is False
    assert tracker.track(top_level) is True
    assert registry.calls == []

    top_level.deleteLater()
    embedded.deleteLater()
    qapplication.processEvents()


def test_qt_event_filter_reports_open_and_close(qapplication: QApplication) -> None:
    registry = FakeWindowRegistry()
    tracker = GuiWindowTracker(registry, _identity())
    window = QWidget()

    assert tracker.track(window) is True
    window.show()
    qapplication.processEvents()
    window.close()
    qapplication.processEvents()

    call_names = _call_names(registry)
    assert "open_window" in call_names
    assert "request_window_close" in call_names
    assert "close_window" in call_names
    assert registry.widgets_seen == 0

    window.deleteLater()
    qapplication.processEvents()


def test_identity_can_be_derived_from_metadata_profile() -> None:
    identity = identity_from_profile(load_main_window_profile())

    assert identity.window_id == "main_window.window"
    assert identity.metadata_id == "main_window.window"
    assert identity.object_name == "main_window"
    assert identity.window_type == "main_application_shell"
    assert identity.registry_metadata()["metadata_id"] == "main_window.window"


def test_tracker_source_has_no_app_or_other_runtime_registry_requirements() -> None:
    source = _WINDOW_TRACKING_SOURCE.read_text(encoding="utf-8")

    assert "LeonardoApp" not in source
    assert "StateStore" not in source
    assert "ActionRegistry" not in source
    assert "OperationRegistry" not in source
    assert "TaskManager" not in source
    assert "ProcessManager" not in source
    assert "ConnectionRegistry" not in source


def _identity() -> GuiWindowIdentity:
    return GuiWindowIdentity(
        window_id="main_window.window",
        metadata_id="main_window.window",
        title="Leonardo",
        window_type="main_application_shell",
        object_name="main_window",
        metadata={"metadata_id": "main_window.window"},
    )


def _call_names(registry: FakeWindowRegistry) -> list[str]:
    return [name for name, _payload in registry.calls]


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
