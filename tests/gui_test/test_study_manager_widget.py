from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from leonardo.gui.widgets.study_manager_widget import StudyManagerWidget
from leonardo.research import StudyManagerEntry


def _entry(study_id: str, *, saved: bool, pane_id: str | None):
    return StudyManagerEntry(
        study_id, study_id, "sma", "Simple Moving Average", "calculation",
        saved, True, pane_id,
        "Price" if pane_id == "price" else "Non-visual", (),
    )


def test_manager_exact_ids_order_states_and_typed_signals() -> None:
    app = QApplication.instance() or QApplication([])
    widget = StudyManagerWidget()
    assert widget.objectName() == "research.study_manager"
    assert widget.table.objectName() == "research.study_manager.table"
    for object_name in (
        "research.study_manager.button.style",
        "research.study_manager.button.reset_style",
        "research.study_manager.button.save",
        "research.study_manager.button.remove",
    ):
        assert widget.findChild(QPushButton, object_name) is not None
    assert widget.entries == ()

    entries = (_entry("visual", saved=False, pane_id="price"), _entry("nonvisual", saved=True, pane_id=None))
    widget.set_entries(entries)
    assert tuple(item.study_id for item in widget.entries) == ("visual", "nonvisual")
    widget.select_study("visual")
    save = widget.findChild(QPushButton, "research.study_manager.button.save")
    style = widget.findChild(QPushButton, "research.study_manager.button.style")
    assert save.isEnabled() and style.isEnabled()

    visibility = []
    saves = []
    widget.visibility_requested.connect(lambda study_id, visible: visibility.append((study_id, visible)))
    widget.save_requested.connect(saves.append)
    widget.table.item(0, 0).setCheckState(Qt.Unchecked)
    save.click()
    assert visibility == [("visual", False)]
    assert saves == ["visual"]

    widget.select_study("nonvisual")
    assert not save.isEnabled()
    assert not style.isEnabled()
    widget.close()
    app.processEvents()
