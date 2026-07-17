from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from leonardo.data import MarketId
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
)
from leonardo.research.notebook import ResearchNotebookSummary


def _summary(valid: bool) -> ResearchNotebookSummary:
    return ResearchNotebookSummary(
        notebook_id="notebook_one" if valid else "Invalid Name",
        display_name="Valid" if valid else "Invalid",
        description="description",
        created_at_utc=None,
        updated_at_utc=None,
        page_count=1 if valid else 0,
        note_count=0,
        potential_trade_count=0,
        point_of_interest_count=0,
        page_market_ids=(
            (MarketId("bybit", "linear", "BTCUSDT", "1h"),) if valid else ()
        ),
        valid=valid,
        rejection_reason=None if valid else "invalid JSON",
        path=Path("notebook.json"),
    )


def test_manager_valid_and_invalid_selection_enablement() -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog((_summary(True), _summary(False)))
    open_button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.open"
    )
    delete_button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.delete"
    )
    assert open_button.isEnabled()
    assert delete_button.isEnabled()
    dialog.findChild(
        __import__("PySide6.QtWidgets", fromlist=["QListWidget"]).QListWidget,
        "research.notebook_manager_dialog.list.notebooks",
    ).setCurrentRow(1)
    assert not open_button.isEnabled()
    assert delete_button.isEnabled()


def test_manager_delete_requires_explicit_confirmation(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog((_summary(True),))
    emitted: list[str] = []
    dialog.delete_requested.connect(emitted.append)
    delete_button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.delete"
    )
    answers = iter((QMessageBox.No, QMessageBox.Yes))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )

    delete_button.click()
    delete_button.click()

    assert emitted == ["notebook_one"]
