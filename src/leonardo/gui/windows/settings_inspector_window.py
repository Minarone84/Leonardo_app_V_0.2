"""Qt settings inspector dialog backed by the GUI settings viewmodel."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.metadata import EffectiveGuiMetadataProfile
from leonardo.gui.settings_inspector import (
    GuiSettingsInspectorDiagnostic,
    GuiSettingsInspectorResult,
    GuiSettingsInspectorRow,
    GuiSettingsInspectorViewModel,
)


SettingsApplyCallback = Callable[[str, EffectiveGuiMetadataProfile], None]


class SettingsInspectorWindow(QDialog):
    """
    Inspect and edit metadata-declared GUI settings through a viewmodel.

    The dialog is generic for one metadata profile and receives all persistence
    behavior through an injected `GuiSettingsInspectorViewModel`. It does not
    construct Core services, resolve production paths, create application
    startup state, or duplicate metadata resolver/override-store logic.
    """

    def __init__(
        self,
        viewmodel: GuiSettingsInspectorViewModel,
        *,
        parent: QWidget | None = None,
        on_apply: SettingsApplyCallback | None = None,
        action_observer: GuiActionObserver | None = None,
    ) -> None:
        if not isinstance(viewmodel, GuiSettingsInspectorViewModel):
            raise TypeError("viewmodel must be a GuiSettingsInspectorViewModel")
        if on_apply is not None and not callable(on_apply):
            raise TypeError("on_apply must be callable or None")
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        super().__init__(parent)
        self.setObjectName("settings_inspector_window")
        self.setWindowTitle(f"Settings Inspector - {viewmodel.metadata_id}")

        self._viewmodel = viewmodel
        self._on_apply = on_apply
        self._action_observer = action_observer
        self._operation_diagnostics: tuple[GuiSettingsInspectorDiagnostic, ...] = ()
        self._saved_profile_pending_apply: EffectiveGuiMetadataProfile | None = None

        self.settings_table = QTableWidget(0, 9)
        self.settings_table.setObjectName("settings_inspector.settings_table")
        self.settings_table.setHorizontalHeaderLabels(
            (
                "Path",
                "Label",
                "Type",
                "Description",
                "Effective",
                "Override",
                "Source",
                "Dirty",
                "Diagnostics",
            )
        )
        self.settings_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.settings_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.settings_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.settings_table.currentCellChanged.connect(self._handle_current_cell_changed)

        self.value_editor = QLineEdit()
        self.value_editor.setObjectName("settings_inspector.value_editor")
        self.value_editor.editingFinished.connect(self.apply_selected_edit)

        self.diagnostics_view = QTextEdit()
        self.diagnostics_view.setObjectName("settings_inspector.diagnostics")
        self.diagnostics_view.setReadOnly(True)

        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("settings_inspector.save")
        self.save_button.clicked.connect(self._handle_save_action)

        self.apply_button = QPushButton("Apply Changes")
        self.apply_button.setObjectName("settings_inspector.apply_changes")
        self.apply_button.clicked.connect(self._handle_apply_changes_action)

        self.reset_field_button = QPushButton("Reset Field")
        self.reset_field_button.setObjectName("settings_inspector.reset_field")
        self.reset_field_button.clicked.connect(self.reset_selected_field)

        self.reset_section_button = QPushButton("Reset Section")
        self.reset_section_button.setObjectName("settings_inspector.reset_section")
        self.reset_section_button.clicked.connect(self.reset_selected_section)

        self.reset_profile_button = QPushButton("Reset Profile")
        self.reset_profile_button.setObjectName("settings_inspector.reset_profile")
        self.reset_profile_button.clicked.connect(self.reset_profile)

        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("settings_inspector.close")
        self.close_button.clicked.connect(self.close)

        self._build_layout()
        self._refresh_rows()

    @property
    def viewmodel(self) -> GuiSettingsInspectorViewModel:
        """Return the injected settings inspector viewmodel."""

        return self._viewmodel

    def exposed_setting_paths(self) -> tuple[str, ...]:
        """Return metadata-declared setting paths from the viewmodel."""

        return self._viewmodel.exposed_paths()

    def selected_path(self) -> str | None:
        """Return the currently selected metadata setting path, if any."""

        row_index = self.settings_table.currentRow()
        rows = self._rows()
        if row_index < 0 or row_index >= len(rows):
            return None
        return rows[row_index].path

    def select_setting(self, path: str) -> None:
        """Select one metadata-declared setting row."""

        for row_index, row in enumerate(self._rows()):
            if row.path == path:
                self.settings_table.selectRow(row_index)
                self._copy_row_value_to_editor(row)
                self._refresh_diagnostics(row)
                return
        raise ValueError(f"Setting path is not exposed by metadata: {path}")

    def set_editor_value(self, path: str, value: object) -> bool:
        """Select a setting, update the editor, and stage the local edit."""

        self.select_setting(path)
        self.value_editor.setText(_display_value(value))
        return self.apply_selected_edit()

    def apply_selected_edit(self) -> bool:
        """
        Stage the current editor value through the injected viewmodel.

        The method does not write override files. Persistence is limited to the
        explicit save/reset methods exposed by the viewmodel.
        """

        path = self.selected_path()
        if path is None:
            self._operation_diagnostics = (
                GuiSettingsInspectorDiagnostic(
                    code="no_selection",
                    message="No setting selected",
                ),
            )
            self._refresh_diagnostics()
            return False

        result = self._viewmodel.edit_value(path, self.value_editor.text())
        self._operation_diagnostics = result.diagnostics
        self._refresh_rows(selected_path=path, preserve_editor_text=not result.ok)
        return result.ok

    def save_settings(self) -> bool:
        """Apply the selected editor value and persist changed-only overrides."""

        if not self.apply_selected_edit():
            return False
        result = self._viewmodel.save()
        return self._handle_persistence_result(result)

    def apply_changes(self) -> bool:
        """
        Persist pending settings and apply the saved effective profile.

        The method does not apply invalid or unsaved dirty edits. The apply
        callback is invoked only after the viewmodel save succeeds.
        """

        if not self.save_settings():
            return False
        return self._apply_saved_profile_if_pending()

    def reset_selected_field(self) -> bool:
        """Reset the selected field through the injected viewmodel."""

        path = self.selected_path()
        if path is None:
            self._operation_diagnostics = (
                GuiSettingsInspectorDiagnostic(
                    code="no_selection",
                    message="No setting selected",
                ),
            )
            self._refresh_diagnostics()
            return False
        result = self._viewmodel.reset_field(path)
        return self._handle_persistence_result(result, selected_path=path)

    def reset_selected_section(self) -> bool:
        """Reset the selected row's profile section through the viewmodel."""

        path = self.selected_path()
        if path is None:
            self._operation_diagnostics = (
                GuiSettingsInspectorDiagnostic(
                    code="no_selection",
                    message="No setting selected",
                ),
            )
            self._refresh_diagnostics()
            return False
        result = self._viewmodel.reset_section(_section_path_for(path))
        return self._handle_persistence_result(result, selected_path=path)

    def reset_profile(self) -> bool:
        """Reset all persisted overrides for the inspected metadata profile."""

        result = self._viewmodel.reset_profile()
        return self._handle_persistence_result(result)

    def row_snapshot(self, path: str) -> Mapping[str, str]:
        """Return current table text for one displayed settings row."""

        for row_index, row in enumerate(self._rows()):
            if row.path == path:
                return {
                    "path": self._table_text(row_index, 0),
                    "label": self._table_text(row_index, 1),
                    "value_type": self._table_text(row_index, 2),
                    "description": self._table_text(row_index, 3),
                    "effective_value": self._table_text(row_index, 4),
                    "override_value": self._table_text(row_index, 5),
                    "source": self._table_text(row_index, 6),
                    "dirty": self._table_text(row_index, 7),
                    "diagnostics": self._table_text(row_index, 8),
                }
        raise ValueError(f"Setting path is not exposed by metadata: {path}")

    def diagnostics_text(self) -> str:
        """Return the current diagnostic report text."""

        return self.diagnostics_view.toPlainText()

    def close(self) -> bool:
        """Apply saved-but-not-applied settings before closing the dialog."""

        self._apply_saved_profile_if_pending()
        return bool(super().close())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Apply saved-but-not-applied settings for non-button close paths."""

        self._apply_saved_profile_if_pending()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self.settings_table)

        root.addWidget(QLabel("Value"))
        root.addWidget(self.value_editor)

        controls = QHBoxLayout()
        controls.addWidget(self.save_button)
        controls.addWidget(self.apply_button)
        controls.addWidget(self.reset_field_button)
        controls.addWidget(self.reset_section_button)
        controls.addWidget(self.reset_profile_button)
        controls.addWidget(self.close_button)
        root.addLayout(controls)

        root.addWidget(QLabel("Diagnostics"))
        root.addWidget(self.diagnostics_view)

    def _handle_current_cell_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        rows = self._rows()
        if current_row < 0 or current_row >= len(rows):
            return
        row = rows[current_row]
        self._copy_row_value_to_editor(row)
        self._refresh_diagnostics(row)

    def _handle_save_action(self) -> None:
        self._record_action("settings_inspector.save")
        self.save_settings()

    def _handle_apply_changes_action(self) -> None:
        self._record_action("settings_inspector.apply_changes")
        self.apply_changes()

    def _handle_operation_result(
        self,
        result: GuiSettingsInspectorResult,
        *,
        selected_path: str | None = None,
    ) -> bool:
        self._operation_diagnostics = result.diagnostics
        self._refresh_rows(selected_path=selected_path, preserve_editor_text=not result.ok)
        return result.ok

    def _handle_persistence_result(
        self,
        result: GuiSettingsInspectorResult,
        *,
        selected_path: str | None = None,
    ) -> bool:
        ok = self._handle_operation_result(result, selected_path=selected_path)
        if ok:
            self._record_saved_profile_for_apply()
        return ok

    def _record_saved_profile_for_apply(self) -> None:
        if self._on_apply is None:
            self._saved_profile_pending_apply = None
            return
        self._saved_profile_pending_apply = self._viewmodel.effective_profile

    def _apply_saved_profile_if_pending(self) -> bool:
        if self._on_apply is None:
            self._saved_profile_pending_apply = None
            return True
        if self._saved_profile_pending_apply is None:
            return True

        profile = self._saved_profile_pending_apply
        self._on_apply(self._viewmodel.metadata_id, profile)
        self._saved_profile_pending_apply = None
        return True

    def _refresh_rows(
        self,
        *,
        selected_path: str | None = None,
        preserve_editor_text: bool = False,
    ) -> None:
        rows = self._rows()
        previous_editor_text = self.value_editor.text()
        selected_row = _row_index_for_path(rows, selected_path)
        if selected_row is None and rows:
            selected_row = 0

        self.settings_table.blockSignals(True)
        self.settings_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.path,
                row.label,
                row.value_type,
                row.description,
                _display_value(row.effective_value),
                _display_value(row.override_value),
                row.source.value,
                "yes" if row.dirty else "no",
                _diagnostics_text(row.diagnostics),
            )
            for column, value in enumerate(values):
                self.settings_table.setItem(row_index, column, QTableWidgetItem(value))

        if selected_row is not None:
            self.settings_table.selectRow(selected_row)
        self.settings_table.blockSignals(False)

        if selected_row is None:
            self.value_editor.clear()
            self._refresh_diagnostics()
            self._set_buttons_enabled(False)
            return

        selected = rows[selected_row]
        if preserve_editor_text:
            self.value_editor.setText(previous_editor_text)
        else:
            self._copy_row_value_to_editor(selected)
        self._refresh_diagnostics(selected)
        self._set_buttons_enabled(True)

    def _refresh_diagnostics(self, selected_row: GuiSettingsInspectorRow | None = None) -> None:
        diagnostics: list[GuiSettingsInspectorDiagnostic] = []
        diagnostics.extend(self._operation_diagnostics)
        diagnostics.extend(self._viewmodel.diagnostics)
        if selected_row is not None:
            diagnostics.extend(selected_row.diagnostics)

        text = _diagnostics_text(tuple(diagnostics))
        self.diagnostics_view.setPlainText(text)

    def _copy_row_value_to_editor(self, row: GuiSettingsInspectorRow) -> None:
        value = row.override_value
        if value is None:
            value = row.effective_value
        self.value_editor.setText(_display_value(value))

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.save_button.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        self.reset_field_button.setEnabled(enabled)
        self.reset_section_button.setEnabled(enabled)
        self.reset_profile_button.setEnabled(enabled)

    def _rows(self) -> tuple[GuiSettingsInspectorRow, ...]:
        return self._viewmodel.rows

    def _record_action(self, action_id: str) -> None:
        if self._action_observer is None:
            return
        self._action_observer.record_action(
            action_id,
            metadata={"target_metadata_id": self._viewmodel.metadata_id},
        )

    def _table_text(self, row: int, column: int) -> str:
        item = self.settings_table.item(row, column)
        if item is None:
            return ""
        return item.text()


def _row_index_for_path(
    rows: tuple[GuiSettingsInspectorRow, ...],
    path: str | None,
) -> int | None:
    if path is None:
        return None
    for index, row in enumerate(rows):
        if row.path == path:
            return index
    return None


def _section_path_for(path: str) -> str:
    if "." not in path:
        return path
    return path.rsplit(".", 1)[0]


def _display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _diagnostics_text(
    diagnostics: tuple[GuiSettingsInspectorDiagnostic, ...],
) -> str:
    if not diagnostics:
        return ""
    lines: list[str] = []
    for diagnostic in diagnostics:
        path = f"[{diagnostic.path}]" if diagnostic.path else ""
        lines.append(f"{diagnostic.code}{path}: {diagnostic.message}")
    return "\n".join(lines)
