from __future__ import annotations

from dataclasses import replace
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog

from leonardo.gui.windows.study_style_dialog import StudyStyleDialog, StudyStylePatch
from leonardo.research import StudyFillStyle, StudyLineStyle, StudyPresentation


_EXPECTED_PRESETS = (
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


def _presentation() -> StudyPresentation:
    return StudyPresentation(
        "bb", True, "price",
        {
            "upper": StudyLineStyle("upper", "#60A5FA"),
            "lower": StudyLineStyle("lower", "#60A5FA"),
        },
        {"band": StudyFillStyle("band", "upper", "lower", "#60A5FA")},
    )


def test_dialog_apply_ok_and_cancel_emit_immutable_intentions() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = StudyStyleDialog(_presentation())
    patches: list[StudyStylePatch] = []
    dialog.patch_applied.connect(patches.append)
    color, width, pattern, visible = dialog._line_controls["upper"]
    color.setEditText("#FFFFFF")
    width.setValue(2.0)
    pattern.setCurrentText("dashed")
    visible.setChecked(False)
    patch = dialog.apply_patch()
    assert patch == patches[-1]
    assert patch.signal_styles[0].color == "#FFFFFF"
    assert patch.signal_styles[0].line_width == 2.0
    assert patch.signal_styles[0].line_pattern == "dashed"
    assert patch.signal_styles[0].visible is False
    assert dialog.result() == 0

    dialog._apply_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(patches) == 2

    cancelled = StudyStyleDialog(_presentation())
    cancelled_patches = []
    cancelled.patch_applied.connect(cancelled_patches.append)
    cancelled.reject()
    assert cancelled_patches == []
    cancelled.close()
    dialog.close()
    app.processEvents()


def test_reset_closes_without_allowing_stale_patch_reapplication() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = StudyStyleDialog(_presentation())
    patches: list[StudyStylePatch] = []
    resets: list[str] = []
    dialog.patch_applied.connect(patches.append)
    dialog.reset_requested.connect(resets.append)
    color, _, _, _ = dialog._line_controls["upper"]
    color.setEditText("#FFFFFF")

    dialog.reset_button.click()

    assert resets == ["bb"]
    assert patches == []
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.apply_button.isEnabled() is False
    assert dialog.ok_button.isEnabled() is False
    dialog.ok_button.click()
    dialog.apply_button.click()
    assert patches == []
    dialog.close()
    app.processEvents()


def test_line_and_fill_color_selectors_preserve_hex_patch_values() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = StudyStyleDialog(_presentation())
    try:
        line_color = dialog._line_controls["upper"][0]
        fill_color = dialog._fill_controls["band"][0]
        assert all(
            isinstance(controls[0], QComboBox) and controls[0].isEditable()
            for controls in dialog._line_controls.values()
        )
        assert all(
            isinstance(controls[0], QComboBox) and controls[0].isEditable()
            for controls in dialog._fill_controls.values()
        )
        assert line_color.objectName() == "research.study_style.color.line.upper"
        assert fill_color.objectName() == "research.study_style.color.fill.band"
        assert tuple(
            (line_color.itemText(index), line_color.itemData(index))
            for index in range(line_color.count())
        ) == tuple(
            (f"{name} — {color}", color) for name, color in _EXPECTED_PRESETS
        )
        assert tuple(
            (fill_color.itemText(index), fill_color.itemData(index))
            for index in range(fill_color.count())
        ) == tuple(
            (f"{name} — {color}", color) for name, color in _EXPECTED_PRESETS
        )

        cyan_index = line_color.findData("#22D3EE")
        line_color.setCurrentIndex(cyan_index)
        line_color.activated.emit(cyan_index)
        fill_color.setEditText("#123456")
        patch = dialog.build_patch()
        assert patch.signal_styles[0].color == "#22D3EE"
        assert patch.fill_styles[0].color == "#123456"

        refreshed = replace(
            _presentation(),
            signal_styles={
                "upper": StudyLineStyle("upper", "#F59E0B"),
                "lower": StudyLineStyle("lower", "#60A5FA"),
            },
            fill_styles={
                "band": StudyFillStyle(
                    "band", "upper", "lower", "#14B8A6"
                )
            },
        )
        dialog.set_presentation(refreshed)
        assert line_color.currentText() == "#F59E0B"
        assert fill_color.currentText() == "#14B8A6"
        assert dialog.build_patch().signal_styles[0].color == "#F59E0B"
    finally:
        dialog.close()
        app.processEvents()


def test_tdirsi_fill_uses_generic_controls_and_emits_exact_patch() -> None:
    app = QApplication.instance() or QApplication([])
    upper = "tdirsi_up_14_34_2_7_ema_rma"
    lower = "tdirsi_dn_14_34_2_7_ema_rma"
    presentation = StudyPresentation(
        "tdirsi",
        True,
        "oscillator:tdirsi",
        {
            upper: StudyLineStyle(upper, "#60A5FA", line_pattern="dashed"),
            lower: StudyLineStyle(lower, "#60A5FA", line_pattern="dashed"),
        },
        {
            "tdirsi_band": StudyFillStyle(
                "tdirsi_band", upper, lower, "#60A5FA", 0.10, True
            )
        },
        tool_key="tdirsi",
    )
    dialog = StudyStyleDialog(presentation)
    try:
        assert tuple(dialog._fill_controls) == ("tdirsi_band",)
        color, opacity, visible = dialog._fill_controls["tdirsi_band"]
        color.setEditText("#123456")
        opacity.setValue(0.35)
        visible.setChecked(False)

        patch = dialog.build_patch()

        assert patch.fill_styles == (
            StudyFillStyle(
                "tdirsi_band",
                upper,
                lower,
                "#123456",
                0.35,
                False,
            ),
        )
    finally:
        dialog.close()
        app.processEvents()


def test_initial_size_is_clamped_resizable_and_applied_only_once() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = StudyStyleDialog(_presentation())
    try:
        natural = dialog._natural_size
        screen = dialog.screen() or app.primaryScreen()
        available = screen.availableGeometry()
        expected_width = min(
            round(natural.width() * 1.5), round(available.width() * 0.9)
        )
        expected_height = min(
            round(natural.height() * 1.5), round(available.height() * 0.9)
        )
        assert abs(dialog.width() - expected_width) <= 1
        assert abs(dialog.height() - expected_height) <= 1
        assert dialog.width() <= round(available.width() * 0.9)
        assert dialog.height() <= round(available.height() * 0.9)

        dialog.show()
        app.processEvents()
        dialog.resize(dialog.width() + 17, dialog.height() + 11)
        app.processEvents()
        resized = dialog.size()
        dialog.show()
        app.processEvents()
        assert dialog.size() == resized
    finally:
        dialog.close()
        app.processEvents()
