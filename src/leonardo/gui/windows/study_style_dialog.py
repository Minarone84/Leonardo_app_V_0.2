"""Chart-local Study style editor emitting immutable presentation patches."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from leonardo.research import StudyFillStyle, StudyLineStyle, StudyPresentation


_COLOR_PRESETS = (
    ("Cyan", "#22D3EE"),
    ("Orange", "#F59E0B"),
    ("Yellow", "#FACC15"),
    ("Grey", "#94A3B8"),
    ("Red", "#EF4444"),
    ("Green", "#22C55E"),
    ("Blue", "#3B82F6"),
    ("Light Blue", "#60A5FA"),
    ("Navy", "#1D4ED8"),
    ("Purple", "#A855F7"),
    ("Violet", "#8B5CF6"),
    ("Magenta", "#D946EF"),
    ("Pink", "#EC4899"),
    ("Lime", "#84CC16"),
    ("Teal", "#14B8A6"),
    ("Amber", "#FBBF24"),
    ("White", "#FFFFFF"),
    ("Black", "#000000"),
)


class _ColorComboBox(QComboBox):
    def setText(self, value: str) -> None:  # noqa: N802 - retained Qt-style API
        self.setEditText(value)


@dataclass(frozen=True, slots=True)
class StudyStylePatch:
    study_id: str
    visible: bool
    signal_styles: tuple[StudyLineStyle, ...]
    fill_styles: tuple[StudyFillStyle, ...]


class StudyStyleDialog(QDialog):
    """Edit only the Task 1018 chart-local mutable style fields."""

    patch_applied = Signal(object)
    reset_requested = Signal(str)

    def __init__(
        self, presentation: StudyPresentation, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        if not isinstance(presentation, StudyPresentation):
            raise TypeError("presentation must be a StudyPresentation")
        self._presentation = presentation
        self.setObjectName("research.study_style_dialog")
        self.setWindowTitle("Study Style")
        self._study_visible = QCheckBox("Visible", self)
        self._study_visible.setChecked(presentation.visible)
        self._line_controls: dict[str, tuple[QComboBox, QDoubleSpinBox, QComboBox, QCheckBox]] = {}
        self._fill_controls: dict[str, tuple[QComboBox, QDoubleSpinBox, QCheckBox]] = {}

        tabs = QTabWidget(self)
        for name, style in presentation.signal_styles.items():
            page = QWidget(tabs)
            form = QFormLayout(page)
            color = _color_selector(
                style.color,
                f"research.study_style.color.line.{_object_suffix(name)}",
                page,
            )
            width = QDoubleSpinBox(page)
            width.setRange(0.5, 5.0)
            width.setSingleStep(0.5)
            width.setValue(style.line_width)
            pattern = QComboBox(page)
            pattern.addItems(("solid", "dashed", "dotted"))
            pattern.setCurrentText(style.line_pattern)
            visible = QCheckBox(page)
            visible.setChecked(style.visible)
            form.addRow("Output", QLabel(name, page))
            form.addRow("Color", color)
            form.addRow("Width", width)
            form.addRow("Pattern", pattern)
            form.addRow("Visible", visible)
            tabs.addTab(page, name)
            self._line_controls[name] = (color, width, pattern, visible)
        for fill_id, style in presentation.fill_styles.items():
            page = QWidget(tabs)
            form = QFormLayout(page)
            color = _color_selector(
                style.color,
                f"research.study_style.color.fill.{_object_suffix(fill_id)}",
                page,
            )
            opacity = QDoubleSpinBox(page)
            opacity.setRange(0.0, 1.0)
            opacity.setSingleStep(0.05)
            opacity.setValue(style.opacity)
            visible = QCheckBox(page)
            visible.setChecked(style.visible)
            form.addRow("Fill", QLabel(fill_id, page))
            form.addRow("Color", color)
            form.addRow("Opacity", opacity)
            form.addRow("Visible", visible)
            tabs.addTab(page, fill_id)
            self._fill_controls[fill_id] = (color, opacity, visible)

        self.apply_button = QPushButton("Apply", self)
        self.ok_button = QPushButton("OK", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.reset_button = QPushButton("Reset to Defaults", self)
        self.apply_button.setObjectName("research.study_style.button.apply")
        self.ok_button.setObjectName("research.study_style.button.ok")
        self.cancel_button.setObjectName("research.study_style.button.cancel")
        self.reset_button.setObjectName("research.study_style.button.reset")
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self._study_visible)
        layout.addWidget(tabs)
        layout.addLayout(buttons)
        self.apply_button.clicked.connect(self.apply_patch)
        self.ok_button.clicked.connect(self._apply_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self._reset_and_close)
        layout.activate()
        self._natural_size = self.sizeHint()
        screen = self.screen()
        if screen is None and parent is not None:
            screen = parent.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        target_width = round(self._natural_size.width() * 1.5)
        target_height = round(self._natural_size.height() * 1.5)
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(target_width, round(available.width() * 0.9))
            target_height = min(target_height, round(available.height() * 0.9))
        self.resize(target_width, target_height)

    @property
    def presentation(self) -> StudyPresentation:
        return self._presentation

    def set_presentation(self, presentation: StudyPresentation) -> None:
        self._presentation = presentation
        self._study_visible.setChecked(presentation.visible)
        for name, style in presentation.signal_styles.items():
            color, width, pattern, visible = self._line_controls[name]
            color.setEditText(style.color)
            width.setValue(style.line_width)
            pattern.setCurrentText(style.line_pattern)
            visible.setChecked(style.visible)
        for fill_id, style in presentation.fill_styles.items():
            color, opacity, visible = self._fill_controls[fill_id]
            color.setEditText(style.color)
            opacity.setValue(style.opacity)
            visible.setChecked(style.visible)

    def build_patch(self) -> StudyStylePatch:
        lines = []
        for name, current in self._presentation.signal_styles.items():
            color, width, pattern, visible = self._line_controls[name]
            lines.append(
                replace(
                    current,
                    color=color.currentText(),
                    line_width=width.value(),
                    line_pattern=pattern.currentText(),
                    visible=visible.isChecked(),
                )
            )
        fills = []
        for fill_id, current in self._presentation.fill_styles.items():
            color, opacity, visible = self._fill_controls[fill_id]
            fills.append(
                replace(
                    current,
                    color=color.currentText(),
                    opacity=opacity.value(),
                    visible=visible.isChecked(),
                )
            )
        return StudyStylePatch(
            self._presentation.study_id,
            self._study_visible.isChecked(),
            tuple(lines),
            tuple(fills),
        )

    def apply_patch(self) -> StudyStylePatch:
        patch = self.build_patch()
        self.patch_applied.emit(patch)
        return patch

    def _apply_and_accept(self) -> None:
        self.apply_patch()
        self.accept()

    def _reset_and_close(self) -> None:
        self.reset_requested.emit(self._presentation.study_id)
        self.apply_button.setEnabled(False)
        self.ok_button.setEnabled(False)
        self.reject()


def _color_selector(value: str, object_name: str, parent: QWidget) -> QComboBox:
    selector = _ColorComboBox(parent)
    selector.setEditable(True)
    selector.setObjectName(object_name)
    for name, color in _COLOR_PRESETS:
        selector.addItem(f"{name} — {color}", color)
    selector.activated.connect(
        lambda index, current=selector: current.setEditText(
            str(current.itemData(index))
        )
    )
    selector.setEditText(value)
    return selector


def _object_suffix(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)
