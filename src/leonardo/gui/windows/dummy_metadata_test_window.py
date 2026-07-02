"""Dummy PySide6 window that consumes the GUI metadata effective profile."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
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

from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
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


def load_dummy_metadata_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the dummy metadata test window profile."""

    result = load_metadata_document(_DUMMY_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid dummy metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class DummyMetadataTestWindow(QWidget):
    """Test-only PySide6 window driven by an effective metadata profile.

    The window consumes static metadata values for labels, action buttons, and
    table headers. Button behavior is local dummy behavior implemented in
    Python; metadata does not define callbacks or executable behavior.
    """

    def __init__(self, profile: EffectiveGuiMetadataProfile | None = None) -> None:
        super().__init__()
        self.profile = profile if profile is not None else load_dummy_metadata_profile()
        if self.profile.metadata_id != DUMMY_METADATA_ID:
            raise ValueError("profile must describe dummy_metadata_test.window")
        self.close_requested_locally = False
        self.action_buttons: dict[str, QPushButton] = {}
        self._status_label: QLabel | None = None
        self._notes_text: QTextEdit | None = None
        self._diagnostics_text: QTextEdit | None = None
        self.settings_inspector: QWidget | None = None

        self._apply_window_metadata()
        self._build_window()
        self.apply_effective_profile(self.profile)

    @property
    def results_table(self) -> QTableWidget:
        """Return the dummy results table widget."""

        table = self.findChild(QTableWidget, "dummy_metadata_test.results_table")
        if table is None:
            raise RuntimeError("dummy results table was not created")
        return table

    def closeEvent(self, event: QCloseEvent) -> None:
        """Record that the dummy close path stayed local to the widget."""

        self.close_requested_locally = True
        super().closeEvent(event)

    def apply_effective_profile(self, profile: EffectiveGuiMetadataProfile) -> None:
        """Apply safe local presentation values from an effective profile."""

        if profile.metadata_id != DUMMY_METADATA_ID:
            raise ValueError("profile must describe dummy_metadata_test.window")
        self.profile = profile
        values = self.profile.values
        style = _mapping_at(values, "style")
        geometry = _mapping_at(values, "geometry")
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)
        for child in self.findChildren(QWidget):
            child.setFont(font)
        self.resize(
            _int_value(geometry, "width", self.width()),
            _int_value(geometry, "height", self.height()),
        )

    def _apply_window_metadata(self) -> None:
        values = self.profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        self.setWindowTitle(_string_value(identity, "title", "Dummy Metadata Test Window"))
        self.setObjectName(_string_value(metadata, "object_name", DUMMY_METADATA_ID))
        width = _int_value(geometry, "width", 1120)
        height = _int_value(geometry, "height", 720)
        self.resize(width, height)

    def _build_window(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        values = self.profile.values
        identity = _mapping_at(values, "identity")
        title = QLabel(_string_value(identity, "title", "Dummy Metadata Test Window"))
        title.setObjectName("dummy_metadata_test.title_label")

        header = QGroupBox(_region_label(values, "header", "Header"))
        layout = QVBoxLayout(header)
        layout.addWidget(title)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox(_region_label(self.profile.values, "toolbar", "Toolbar"))
        layout = QHBoxLayout(toolbar)
        for action_id, action in _sorted_metadata_items(_mapping_at(self.profile.values, "actions")):
            button = QPushButton(_string_value(action, "label", action_id))
            button.setObjectName(action_id)
            button.clicked.connect(partial(self._handle_dummy_action, action_id))
            self.action_buttons[action_id] = button
            layout.addWidget(button)
        return toolbar

    def _build_body(self) -> QWidget:
        body = QGroupBox(_region_label(self.profile.values, "body", "Body"))
        layout = QHBoxLayout(body)
        layout.addWidget(self._build_left_panel())
        layout.addWidget(self._build_center_panel(), stretch=1)
        layout.addWidget(self._build_right_panel())
        return body

    def _build_left_panel(self) -> QWidget:
        left_panel = QGroupBox(_region_label(self.profile.values, "left_panel", "Left Panel"))
        layout = QVBoxLayout(left_panel)

        enabled = QCheckBox(_widget_label(self.profile.values, "dummy_metadata_test.enabled_checkbox"))
        enabled.setObjectName("dummy_metadata_test.enabled_checkbox")
        layout.addWidget(enabled)

        name_input = QLineEdit()
        name_input.setObjectName("dummy_metadata_test.name_input")
        name_input.setPlaceholderText(_widget_label(self.profile.values, "dummy_metadata_test.name_input"))
        layout.addWidget(name_input)

        mode_combo = QComboBox()
        mode_combo.setObjectName("dummy_metadata_test.mode_combo")
        mode_combo.addItems(("Preview", "Review", "Diagnostics"))
        layout.addWidget(mode_combo)

        return left_panel

    def _build_center_panel(self) -> QWidget:
        center = QGroupBox("Table Area")
        layout = QVBoxLayout(center)
        layout.addWidget(self._build_results_table())
        layout.addWidget(self._build_report_area())
        return center

    def _build_results_table(self) -> QTableWidget:
        table_metadata = _mapping_at(
            _mapping_at(self.profile.values, "tables"),
            "dummy_metadata_test.results_table",
        )
        columns = _sorted_columns(_mapping_at(table_metadata, "columns"))
        table = QTableWidget(2, len(columns))
        table.setObjectName("dummy_metadata_test.results_table")
        table.setHorizontalHeaderLabels(
            [_string_value(column, "label", column_id) for column_id, column in columns]
        )
        table.setItem(0, 0, QTableWidgetItem("alpha"))
        table.setItem(0, 1, QTableWidgetItem("ready"))
        table.setItem(0, 2, QTableWidgetItem("42"))
        table.setItem(0, 3, QTableWidgetItem("static dummy row"))
        table.setItem(1, 0, QTableWidgetItem("beta"))
        table.setItem(1, 1, QTableWidgetItem("idle"))
        table.setItem(1, 2, QTableWidgetItem("7"))
        table.setItem(1, 3, QTableWidgetItem("static dummy row"))
        return table

    def _build_report_area(self) -> QWidget:
        reports = _mapping_at(self.profile.values, "reports")
        report = _mapping_at(reports, "dummy_metadata_test.structured_report")
        report_area = QGroupBox(_string_value(report, "label", "Structured Report"))
        layout = QVBoxLayout(report_area)
        report_view = QTextEdit()
        report_view.setObjectName("dummy_metadata_test.report_view")
        report_view.setReadOnly(True)
        report_view.setPlainText("Dummy report summary\nWarnings: none\nResults: static")
        layout.addWidget(report_view)
        return report_area

    def _build_right_panel(self) -> QWidget:
        right_panel = QGroupBox(_region_label(self.profile.values, "right_panel", "Right Panel"))
        layout = QVBoxLayout(right_panel)

        notes = QTextEdit()
        notes.setObjectName("dummy_metadata_test.notes_text")
        notes.setPlaceholderText(_widget_label(self.profile.values, "dummy_metadata_test.notes_text"))
        self._notes_text = notes
        layout.addWidget(notes)

        diagnostics = QTextEdit()
        diagnostics.setObjectName("dummy_metadata_test.diagnostics_view")
        diagnostics.setReadOnly(True)
        diagnostics.setPlainText("No dummy actions triggered.")
        self._diagnostics_text = diagnostics
        layout.addWidget(diagnostics)

        return right_panel

    def _build_footer(self) -> QWidget:
        footer = QGroupBox(_region_label(self.profile.values, "footer", "Footer"))
        layout = QHBoxLayout(footer)
        status = QLabel("Ready")
        status.setObjectName("dummy_metadata_test.status_label")
        self._status_label = status
        layout.addWidget(status)
        return footer

    def _handle_dummy_action(self, action_id: str) -> None:
        if action_id == "dummy_metadata_test.close":
            self.close()
            return
        if action_id == "dummy_metadata_test.reset_mock":
            self._set_status("Dummy display reset.")
            if self._notes_text is not None:
                self._notes_text.clear()
            if self._diagnostics_text is not None:
                self._diagnostics_text.setPlainText("Dummy display reset.")
            return
        if action_id == "dummy_metadata_test.refresh":
            self._set_status("Dummy refresh complete.")
            return
        if action_id == "dummy_metadata_test.apply_mock":
            self._set_status("Dummy mock applied.")
            if self._notes_text is not None:
                self._notes_text.append("Applied local dummy mock.")
            return
        if action_id == "dummy_metadata_test.open_settings":
            self._open_settings_inspector()
            return
        self._set_status(f"Unhandled dummy action: {action_id}")

    def _set_status(self, value: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(value)

    def _open_settings_inspector(self) -> None:
        from leonardo.gui.windows.dummy_metadata_settings_inspector import (
            DummyMetadataSettingsInspector,
        )

        if self.settings_inspector is None:
            self.settings_inspector = DummyMetadataSettingsInspector(
                self.profile,
                target_window=self,
                parent=self,
            )
        self.settings_inspector.show()
        self._set_status("Dummy settings inspector opened locally.")
        if self._diagnostics_text is not None:
            self._diagnostics_text.append("Opened local dummy settings inspector.")


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


def _region_label(values: Mapping[str, object], region_id: str, fallback: str) -> str:
    region = _mapping_at(_mapping_at(values, "regions"), region_id)
    return _string_value(region, "label", fallback)


def _widget_label(values: Mapping[str, object], widget_id: str) -> str:
    widget = _mapping_at(_mapping_at(values, "widgets"), widget_id)
    return _string_value(widget, "label", widget_id)


def _sorted_metadata_items(values: Mapping[str, object]) -> tuple[tuple[str, Mapping[str, object]], ...]:
    return tuple(
        (key, item)
        for key, item in sorted(values.items(), key=lambda entry: entry[0])
        if isinstance(key, str) and isinstance(item, Mapping)
    )


def _sorted_columns(values: Mapping[str, object]) -> tuple[tuple[str, Mapping[str, object]], ...]:
    return tuple(
        (key, item)
        for key, item in sorted(
            values.items(),
            key=lambda entry: _int_value(entry[1], "order", 0)
            if isinstance(entry[1], Mapping)
            else 0,
        )
        if isinstance(key, str) and isinstance(item, Mapping)
    )
