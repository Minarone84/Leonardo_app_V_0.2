"""R05: named validation at the real Style Apply/OK boundary."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog
from leonardo.gui.windows.study_style_dialog import StudyStyleDialog
from leonardo.research import (
    StudyFillStyle, StudyLineStyle, StudyPresentation, StudyPresentationValidationError,
)


def _receipt(request, value):
    root = os.environ.get("R02_OBSERVATIONS")
    if root:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
        (path / (key + ".json")).write_text(
            json.dumps({"node": request.node.nodeid, **value}, indent=2) + "\n", encoding="utf-8")


def _presentation():
    return StudyPresentation("bb", True, "price", {
        "upper": StudyLineStyle("upper", "#60A5FA"),
        "lower": StudyLineStyle("lower", "#60A5FA"),
    }, {"band": StudyFillStyle("band", "upper", "lower", "#60A5FA")})


@pytest.fixture
def dialog():
    app = QApplication.instance() or QApplication([])
    value = StudyStyleDialog(_presentation())
    value.show()
    app.processEvents()
    yield app, value
    value.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_actual_invalid_apply_callback(dialog, request):
    """PRE lane: guard must record old escaped StudyPresentationValidationError."""
    app, window = dialog
    patches = []
    window.patch_applied.connect(patches.append)
    original = window._presentation
    window._line_controls["upper"][0].setEditText("not-a-color")
    window.apply_button.click()
    app.processEvents()
    # These supported-old-source assertions do not depend on the new label.
    _receipt(request, {"patch_count": len(patches), "visible": window.isVisible(),
        "entered": window._line_controls["upper"][0].currentText(),
        "original_preserved": window._presentation is original})
    assert patches == [] and window.isVisible()
    assert window._presentation is original
    assert window._line_controls["upper"][0].currentText() == "not-a-color"


@pytest.mark.parametrize("action", ["apply", "ok"])
@pytest.mark.parametrize("invalid", ["line", "fill", "early_valid_late_invalid"])
def test_invalid_then_correct_same_dialog(dialog, request, action, invalid):
    app, window = dialog
    original = window._presentation
    patches = []
    window.patch_applied.connect(patches.append)
    if invalid == "early_valid_late_invalid":
        window._line_controls["upper"][0].setEditText("#FFFFFF")
    color = window._line_controls["lower"][0] if invalid == "line" else window._fill_controls["band"][0]
    color.setEditText("bad-color")
    button = window.apply_button if action == "apply" else window.ok_button
    button.click()
    app.processEvents()
    assert patches == [] and window.isVisible()
    assert window.result() == QDialog.DialogCode.Rejected
    assert window._presentation is original and color.currentText() == "bad-color"
    assert window._validation.isVisible()
    assert window._validation.text().startswith("Style not applied: ")
    assert "#RRGGBB" in window._validation.text()
    feedback = window._validation.text()
    color.setEditText("#22D3EE")
    expected = window.build_patch()
    button.click()
    app.processEvents()
    assert patches == [expected]
    assert not window._validation.isVisible() and window._validation.text() == ""
    assert window._presentation is original
    assert window.isVisible() is (action == "apply")
    assert window.result() == (QDialog.DialogCode.Rejected if action == "apply" else QDialog.DialogCode.Accepted)
    _receipt(request, {"feedback": feedback, "patch": repr(expected), "patch_count": len(patches),
        "action": action, "visible_after_correction": window.isVisible(), "original_preserved": True})


def test_direct_build_strict_unrelated_error_propagates(dialog, monkeypatch):
    _, window = dialog
    window._line_controls["upper"][0].setEditText("bad-color")
    with pytest.raises(StudyPresentationValidationError, match="#RRGGBB"):
        window.build_patch()
    def unrelated():
        raise RuntimeError("unrelated sentinel")
    monkeypatch.setattr(window, "build_patch", unrelated)
    with pytest.raises(RuntimeError, match="unrelated sentinel"):
        window.apply_patch()


def test_valid_patch_controls_and_presentation_reuse(dialog):
    app, window = dialog
    patches = []
    window.patch_applied.connect(patches.append)
    color, width, pattern, visible = window._line_controls["upper"]
    presets = tuple(color.itemData(i) for i in range(color.count()))
    assert len(presets) == 18 and "#FFFFFF" in presets
    color.setEditText("bad-color")
    window.apply_button.click()
    assert window._validation.text()
    replacement = replace(_presentation(), revision=2)
    window.set_presentation(replacement)
    assert not window._validation.isVisible() and window._validation.text() == ""
    assert window._presentation is replacement
    color.setEditText("#FFFFFF")
    width.setValue(2.0)
    pattern.setCurrentText("dashed")
    visible.setChecked(False)
    fill_color, opacity, fill_visible = window._fill_controls["band"]
    fill_color.setEditText("#F59E0B")
    opacity.setValue(0.35)
    fill_visible.setChecked(False)
    expected = window.build_patch()
    result = window.apply_patch()
    assert result == expected and patches == [expected]
    line = next(item for item in result.signal_styles if item.output_name == "upper")
    assert (line.color, line.line_width, line.line_pattern, line.visible) == ("#FFFFFF", 2.0, "dashed", False)
    assert result.fill_styles[0].color == "#F59E0B"
    assert result.fill_styles[0].opacity == pytest.approx(0.35)
    assert result.fill_styles[0].visible is False
    app.processEvents()
    assert window.isVisible()


@pytest.mark.parametrize("action", ["cancel", "reset"])
def test_cancel_reset_keep_original_semantics(dialog, action):
    _, window = dialog
    patches, resets = [], []
    window.patch_applied.connect(patches.append)
    window.reset_requested.connect(resets.append)
    window._line_controls["upper"][0].setEditText("bad-color")
    (window.cancel_button if action == "cancel" else window.reset_button).click()
    assert patches == [] and not window.isVisible()
    assert resets == ([] if action == "cancel" else ["bb"])
    if action == "reset":
        assert not window.apply_button.isEnabled() and not window.ok_button.isEnabled()
