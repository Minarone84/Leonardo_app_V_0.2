from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from leonardo.gui.windows.study_style_dialog import StudyStyleDialog, StudyStylePatch
from leonardo.research import StudyFillStyle, StudyLineStyle, StudyPresentation


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
    color.setText("#FFFFFF")
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
    color.setText("#FFFFFF")

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
