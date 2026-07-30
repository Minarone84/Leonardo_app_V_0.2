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
        study_id, study_id, "sma", "SMA", "calculation",
        saved, True, pane_id,
        "Price" if pane_id == "price" else "Non-visual", (),
        "SMA 14",
        "period=14",
        "Period: 14",
        "OHLCV: CLOSE",
        "OHLCV inputs: close",
        "Calculated",
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
    assert widget.table.columnCount() == 8
    assert tuple(
        widget.table.horizontalHeaderItem(column).text()
        for column in range(8)
    ) == (
        "Visible",
        "Study",
        "Tool",
        "Parameters",
        "Sources",
        "Origin",
        "Saved",
        "Pane",
    )
    assert tuple(
        widget.table.item(0, column).text() for column in range(1, 8)
    ) == (
        "SMA 14",
        "SMA",
        "period=14",
        "OHLCV: CLOSE",
        "Calculated",
        "No",
        "Price",
    )
    assert widget.table.item(0, 1).toolTip() == "Original Study name: visual"
    assert widget.table.item(0, 3).toolTip() == "Period: 14"
    assert widget.table.item(0, 4).toolTip() == "OHLCV inputs: close"
    assert (
        widget.table.item(0, 5).toolTip()
        == "Calculated in the current Research workflow."
    )
    assert (
        widget.table.item(0, 6).toolTip()
        == "In-session Study not yet saved."
    )
    assert widget.table.item(0, 7).toolTip() == "Price chart pane."
    assert tuple(item.study_id for item in widget.entries) == ("visual", "nonvisual")
    widget.select_study("visual")
    save = widget.findChild(QPushButton, "research.study_manager.button.save")
    style = widget.findChild(QPushButton, "research.study_manager.button.style")
    assert save.isEnabled() and style.isEnabled()

    visibility = []
    saves = []
    styles = []
    resets = []
    removals = []
    widget.visibility_requested.connect(lambda study_id, visible: visibility.append((study_id, visible)))
    widget.save_requested.connect(saves.append)
    widget.style_requested.connect(styles.append)
    widget.reset_style_requested.connect(resets.append)
    widget.remove_requested.connect(removals.append)
    widget.table.item(0, 0).setCheckState(Qt.Unchecked)
    style.click()
    widget.findChild(
        QPushButton, "research.study_manager.button.reset_style"
    ).click()
    widget.findChild(QPushButton, "research.study_manager.button.remove").click()
    save.click()
    assert visibility == [("visual", False)]
    assert saves == ["visual"]
    assert styles == ["visual"]
    assert resets == ["visual"]
    assert removals == ["visual"]

    widget.select_study("nonvisual")
    assert not save.isEnabled()
    assert not style.isEnabled()
    assert (
        widget.table.item(1, 6).toolTip()
        == "Saved Study with canonical Recipe and Artifact."
    )
    assert widget.table.item(1, 7).toolTip() == "Non-visual Study."
    widget.close()
    app.processEvents()
