"""Minimal Main Window shell that consumes GUI metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow


MAIN_WINDOW_METADATA_ID = "main_window.window"
_MAIN_WINDOW_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "main_window.window.toml"
)
RuntimeManagerWindowFactory = Callable[[], QWidget]
RuntimeSnapshotProvider = Callable[[], object]
SettingsInspectorFactory = Callable[[], QWidget]


def load_main_window_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Main Window shell metadata profile."""

    result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Main Window metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class LeonardoMainWindow(QMainWindow):
    """Minimal metadata-driven Leonardo Main Window shell.

    The shell consumes metadata for title, action labels, and basic presentation
    defaults. Runtime Manager handoff is GUI-local through an injected factory
    or read-only snapshot provider. The class does not call Core services or
    application composition.
    """

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        runtime_manager_window_factory: RuntimeManagerWindowFactory | None = None,
        runtime_snapshot_provider: RuntimeSnapshotProvider | None = None,
        settings_inspector_factory: SettingsInspectorFactory | None = None,
    ) -> None:
        super().__init__()
        self._profile = profile if profile is not None else load_main_window_profile()
        if self._profile.metadata_id != MAIN_WINDOW_METADATA_ID:
            raise ValueError("profile must describe main_window.window")
        if runtime_manager_window_factory is not None and not callable(
            runtime_manager_window_factory
        ):
            raise TypeError("runtime_manager_window_factory must be callable")
        if runtime_snapshot_provider is not None and not callable(runtime_snapshot_provider):
            raise TypeError("runtime_snapshot_provider must be callable")
        if settings_inspector_factory is not None and not callable(
            settings_inspector_factory
        ):
            raise TypeError("settings_inspector_factory must be callable")
        self.close_requested_locally = False
        self._actions: dict[str, QAction] = {}
        self._last_local_action_id = ""
        self._runtime_manager_window_factory = runtime_manager_window_factory
        self._runtime_snapshot_provider = runtime_snapshot_provider
        self._runtime_manager_window: QWidget | None = None
        self._settings_inspector_factory = settings_inspector_factory
        self._settings_inspector_window: QWidget | None = None
        self._apply_profile_metadata()
        self._build_menu_bar()
        self._build_central_placeholder()
        self._build_status_bar()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

    @property
    def metadata_title(self) -> str:
        """Return the metadata-derived shell title."""

        identity = _mapping_at(self._profile.values, "identity")
        return _string_value(identity, "title", "Leonardo")

    @property
    def last_local_action_id(self) -> str:
        """Return the last locally handled shell action ID."""

        return self._last_local_action_id

    @property
    def runtime_manager_window(self) -> QWidget | None:
        """Return the locally retained Runtime Manager window, if created."""

        return self._runtime_manager_window

    @property
    def settings_inspector_window(self) -> QWidget | None:
        """Return the locally retained Settings Inspector dialog, if created."""

        return self._settings_inspector_window

    def action_ids(self) -> tuple[str, ...]:
        """Return metadata action IDs in deterministic order."""

        return tuple(self._actions)

    def action_labels(self) -> Mapping[str, str]:
        """Return metadata action labels by action ID."""

        return {action_id: action.text() for action_id, action in self._actions.items()}

    def action_for_id(self, action_id: str) -> QAction:
        """Return a shell action by stable action ID."""

        try:
            return self._actions[action_id]
        except KeyError as error:
            raise KeyError(f"Unknown Main Window action: {action_id}") from error

    def closeEvent(self, event: QCloseEvent) -> None:
        """Record that the shell close path stayed local."""

        self.close_requested_locally = True
        if self._runtime_manager_window is not None:
            self._runtime_manager_window.close()
        if self._settings_inspector_window is not None:
            self._settings_inspector_window.close()
        super().closeEvent(event)

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")

        self.setWindowTitle(self.metadata_title)
        self.setObjectName(_string_value(metadata, "object_name", "main_window"))
        self.resize(
            _int_value(geometry, "width", 1440),
            _int_value(geometry, "height", 900),
        )

        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_menu_bar(self) -> None:
        menu = self.menuBar().addMenu("Shell")
        menu.setObjectName("main_window.menu_bar")
        for action_id, action_metadata in _sorted_metadata_items(
            _mapping_at(self._profile.values, "actions")
        ):
            action = QAction(_string_value(action_metadata, "label", action_id), self)
            action.setObjectName(action_id)
            action.triggered.connect(partial(self._handle_shell_action, action_id))
            self._actions[action_id] = action
            menu.addAction(action)

    def _build_central_placeholder(self) -> None:
        central = QWidget()
        central.setObjectName("main_window.central")
        layout = QVBoxLayout(central)
        title_label = QLabel(self.metadata_title)
        title_label.setObjectName("main_window.title_label")
        placeholder = QLabel("Leonardo shell metadata pilot")
        placeholder.setObjectName("main_window.placeholder_label")
        layout.addWidget(title_label)
        layout.addWidget(placeholder)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> None:
        self.statusBar().setObjectName("main_window.status_bar")
        self.statusBar().showMessage("Ready")

    def _handle_shell_action(self, action_id: str) -> None:
        self._last_local_action_id = action_id
        if action_id == "main_window.exit":
            self.statusBar().showMessage("Exit requested locally.")
            self.close()
            return
        if action_id == "main_window.open_dummy_metadata_test":
            self.statusBar().showMessage("Dummy metadata test action is local/inert.")
            return
        if action_id == "main_window.open_settings_inspector":
            self._open_settings_inspector_window()
            return
        if action_id == "main_window.open_runtime_manager":
            self._open_runtime_manager_window()
            return
        self.statusBar().showMessage(f"Unhandled local shell action: {action_id}")

    def _open_runtime_manager_window(self) -> None:
        created = False
        if self._runtime_manager_window is None:
            self._runtime_manager_window = self._create_runtime_manager_window()
            created = True

        self._runtime_manager_window.show()
        self._runtime_manager_window.raise_()
        self._runtime_manager_window.activateWindow()
        if created:
            self.statusBar().showMessage("Runtime Manager opened locally.")
            return
        self.statusBar().showMessage("Runtime Manager raised locally.")

    def _create_runtime_manager_window(self) -> QWidget:
        if self._runtime_manager_window_factory is not None:
            window = self._runtime_manager_window_factory()
        else:
            window = RuntimeManagerWindow(
                snapshot_provider=self._runtime_snapshot_provider,
            )
        if not isinstance(window, QWidget):
            raise TypeError("Runtime Manager window factory must return a QWidget")
        return window

    def _open_settings_inspector_window(self) -> None:
        if self._settings_inspector_factory is None:
            self.statusBar().showMessage("Settings inspector action is local/inert.")
            return

        created = False
        if self._settings_inspector_window is None:
            self._settings_inspector_window = self._create_settings_inspector_window()
            created = True

        self._settings_inspector_window.show()
        self._settings_inspector_window.raise_()
        self._settings_inspector_window.activateWindow()
        if created:
            self.statusBar().showMessage("Settings inspector opened locally.")
            return
        self.statusBar().showMessage("Settings inspector raised locally.")

    def _create_settings_inspector_window(self) -> QWidget:
        if self._settings_inspector_factory is None:
            raise RuntimeError("settings_inspector_factory is not configured")
        window = self._settings_inspector_factory()
        if not isinstance(window, QWidget):
            raise TypeError("Settings Inspector factory must return a QWidget")
        return window


def _mapping_at(values: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(values: Mapping[str, object], key: str, fallback: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _int_value(values: Mapping[str, object], key: str, fallback: int) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


def _sorted_metadata_items(values: Mapping[str, object]) -> tuple[tuple[str, Mapping[str, object]], ...]:
    return tuple(
        (key, item)
        for key, item in sorted(values.items(), key=lambda entry: entry[0])
        if isinstance(key, str) and isinstance(item, Mapping)
    )
