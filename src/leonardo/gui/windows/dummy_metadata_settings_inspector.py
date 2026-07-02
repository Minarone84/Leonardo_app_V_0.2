"""Dummy-only settings inspector for the metadata test window."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataDocument,
    GuiMetadataIssueCode,
    GuiMetadataOverrideDocument,
    GuiMetadataResolver,
    load_metadata_document,
)


DUMMY_METADATA_ID = "dummy_metadata_test.window"
_DUMMY_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "dummy_metadata_test.window.toml"
)


class DummyMetadataSettingsInspector(QDialog):
    """Inspect and edit dummy-window settings exposure in memory only."""

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        target_window: QWidget | None = None,
        overrides: GuiMetadataOverrideDocument | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dummy_metadata_settings_inspector")
        self.setWindowTitle("Dummy Metadata Settings")
        self._document = _load_dummy_metadata_document()
        self._resolver = GuiMetadataResolver()
        self._overrides = overrides or GuiMetadataOverrideDocument(
            metadata_id=self._document.metadata_id,
            values={},
        )
        self._profile = profile or self._resolver.resolve(self._document, self._overrides)
        if self._profile.metadata_id != DUMMY_METADATA_ID:
            raise ValueError("profile must describe dummy_metadata_test.window")
        self._target_window = target_window
        self.last_error = ""

        self.settings_table = QTableWidget(0, 6)
        self.settings_table.setObjectName("dummy_metadata_settings_table")
        self.settings_table.setHorizontalHeaderLabels(
            ("Setting", "Path", "Default", "Current", "Override", "Apply Mode")
        )
        self.value_editor = QLineEdit()
        self.value_editor.setObjectName("dummy_metadata_settings_value_editor")
        self.status_label = QLabel("")
        self.status_label.setObjectName("dummy_metadata_settings_status")

        self._build_layout()
        self._refresh_table()

    @property
    def current_override_document(self) -> GuiMetadataOverrideDocument:
        """Return the current changed-only in-memory override document."""

        return self._overrides

    @property
    def effective_profile(self) -> EffectiveGuiMetadataProfile:
        """Return the current effective profile."""

        return self._profile

    def exposed_setting_paths(self) -> tuple[str, ...]:
        """Return safe metadata-exposed setting paths in declaration order."""

        return tuple(setting.path for setting in self._document.settings)

    def setting_snapshot(self, path: str) -> Mapping[str, object]:
        """Return display state for one exposed setting path."""

        self._require_exposed_path(path)
        trace = self._profile.trace_for(path)
        return {
            "path": path,
            "label": self._setting_label(path),
            "default": trace.default_value,
            "current": trace.effective_value,
            "has_override": path in self._overrides.values,
            "apply_mode": self._apply_mode_for(path),
            "source": trace.source,
        }

    def select_setting(self, path: str) -> None:
        """Select one exposed setting and copy its current value into the editor."""

        row = self._row_for_path(path)
        self.settings_table.selectRow(row)
        current = self.setting_snapshot(path)["current"]
        self.value_editor.setText(_display_value(current))

    def set_editor_value(self, path: str, value: object) -> None:
        """Select a setting and stage a textual editor value."""

        self.select_setting(path)
        self.value_editor.setText(_display_value(value))

    def preview_selected_setting(self) -> bool:
        """Apply the edited value to the target dummy window without saving."""

        path = self._selected_path()
        if path is None:
            self._set_error("No setting selected")
            return False
        parsed = self._parse_editor_value(path)
        if parsed is _INVALID_VALUE:
            return False
        candidate = self._candidate_override(path, parsed)
        profile = self._resolver.resolve(self._document, candidate)
        if self._profile_has_invalid_path(profile, path):
            self._set_error(f"Invalid value for {path}")
            return False
        self._apply_to_target_window(profile)
        self._set_status(f"Previewed {path}")
        return True

    def save_selected_setting(self) -> bool:
        """Save the edited value into the in-memory override document."""

        path = self._selected_path()
        if path is None:
            self._set_error("No setting selected")
            return False
        parsed = self._parse_editor_value(path)
        if parsed is _INVALID_VALUE:
            return False
        candidate = self._candidate_override(path, parsed)
        profile = self._resolver.resolve(self._document, candidate)
        if self._profile_has_invalid_path(profile, path):
            self._set_error(f"Invalid value for {path}")
            return False
        self._overrides = candidate
        self._profile = profile
        self._refresh_table()
        self.select_setting(path)
        self._apply_to_target_window(profile)
        self._set_status(f"Saved {path}")
        return True

    def reset_selected_setting(self) -> bool:
        """Remove one selected override entry in memory."""

        path = self._selected_path()
        if path is None:
            self._set_error("No setting selected")
            return False
        self._overrides = self._resolver.reset_field(self._overrides, path)
        self._profile = self._resolver.resolve(self._document, self._overrides)
        self._refresh_table()
        self.select_setting(path)
        self._apply_to_target_window(self._profile)
        self._set_status(f"Reset {path}")
        return True

    def reset_all_settings(self) -> None:
        """Remove all dummy setting overrides in memory."""

        self._overrides = self._resolver.reset_profile(self._overrides)
        self._profile = self._resolver.resolve(self._document, self._overrides)
        self._refresh_table()
        self._apply_to_target_window(self._profile)
        self._set_status("Reset all settings")

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self.settings_table)
        root.addWidget(QLabel("Value"))
        root.addWidget(self.value_editor)

        controls = QHBoxLayout()
        buttons = (
            ("Preview", "dummy_metadata_settings_preview", self.preview_selected_setting),
            ("Save", "dummy_metadata_settings_save", self.save_selected_setting),
            ("Reset Selected", "dummy_metadata_settings_reset_selected", self.reset_selected_setting),
            ("Reset All", "dummy_metadata_settings_reset_all", self.reset_all_settings),
            ("Close", "dummy_metadata_settings_close", self.close),
        )
        for label, object_name, handler in buttons:
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(handler)
            controls.addWidget(button)
        root.addLayout(controls)
        root.addWidget(self.status_label)

    def _refresh_table(self) -> None:
        self.settings_table.setRowCount(len(self._document.settings))
        for row, setting in enumerate(self._document.settings):
            snapshot = self.setting_snapshot(setting.path)
            values = (
                str(snapshot["label"]),
                str(snapshot["path"]),
                _display_value(snapshot["default"]),
                _display_value(snapshot["current"]),
                "yes" if snapshot["has_override"] else "no",
                str(snapshot["apply_mode"]),
            )
            for column, value in enumerate(values):
                self.settings_table.setItem(row, column, QTableWidgetItem(value))
        if self.settings_table.rowCount() > 0 and not self.settings_table.selectedItems():
            self.settings_table.selectRow(0)
            first_path = self._document.settings[0].path
            self.value_editor.setText(_display_value(self.setting_snapshot(first_path)["current"]))

    def _selected_path(self) -> str | None:
        row = self.settings_table.currentRow()
        if row < 0 or row >= len(self._document.settings):
            return None
        return self._document.settings[row].path

    def _row_for_path(self, path: str) -> int:
        self._require_exposed_path(path)
        for row, setting in enumerate(self._document.settings):
            if setting.path == path:
                return row
        raise ValueError(f"Unknown setting path: {path}")

    def _setting_label(self, path: str) -> str:
        for setting in self._document.settings:
            if setting.path == path:
                return setting.label
        return path

    def _setting_value_type(self, path: str) -> str:
        for setting in self._document.settings:
            if setting.path == path:
                return setting.value_type
        return "string"

    def _require_exposed_path(self, path: str) -> None:
        if path not in self.exposed_setting_paths():
            raise ValueError(f"Setting path is not exposed: {path}")

    def _parse_editor_value(self, path: str) -> object:
        value_type = self._setting_value_type(path)
        text = self.value_editor.text()
        if value_type == "integer":
            try:
                return int(text)
            except ValueError:
                self._set_error(f"Expected integer for {path}")
                return _INVALID_VALUE
        if value_type == "boolean":
            normalized = text.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
            self._set_error(f"Expected boolean for {path}")
            return _INVALID_VALUE
        return text

    def _candidate_override(
        self,
        path: str,
        value: object,
    ) -> GuiMetadataOverrideDocument:
        candidate_values = dict(self._overrides.values)
        candidate_values[path] = value
        return GuiMetadataOverrideDocument(
            metadata_id=self._document.metadata_id,
            values=candidate_values,
        )

    def _profile_has_invalid_path(
        self,
        profile: EffectiveGuiMetadataProfile,
        path: str,
    ) -> bool:
        for issue in profile.report.issues_by_code(GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE):
            if issue.path == path:
                return True
        for issue in profile.report.issues_by_code(GuiMetadataIssueCode.STALE_OVERRIDE_PATH):
            if issue.path == path:
                return True
        return False

    def _apply_to_target_window(self, profile: EffectiveGuiMetadataProfile) -> None:
        if self._target_window is None:
            return
        apply_profile = getattr(self._target_window, "apply_effective_profile", None)
        if callable(apply_profile):
            apply_profile(profile)

    def _apply_mode_for(self, path: str) -> str:
        if path == "style.font_size":
            return "live-local"
        if path.startswith("geometry."):
            return "profile-local"
        return "profile-only"

    def _set_error(self, message: str) -> None:
        self.last_error = message
        self.status_label.setText(message)

    def _set_status(self, message: str) -> None:
        self.last_error = ""
        self.status_label.setText(message)


class _InvalidValue:
    pass


_INVALID_VALUE = _InvalidValue()


def _load_dummy_metadata_document() -> GuiMetadataDocument:
    result = load_metadata_document(_DUMMY_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid dummy metadata document: {messages}")
    return result.document


def _display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
