from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.gui.data_manager.catalogs import DataManagerCatalogWorkspace


@dataclass(frozen=True)
class _Revision:
    collection_id: str
    revision_id: str
    display_name: str
    created_at_utc: str


def test_exact_revision_history_remains_separate_from_current_inspection() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    workspace = DataManagerCatalogWorkspace()
    try:
        workspace.set_inspection(
            (("collection_id", "ac_123"), ("revision_id", "current")),
            (
                ("revision-1", "2026-08-01T00:00:00+00:00", "superseded"),
                ("revision-2", "2026-08-02T00:00:00+00:00", "current"),
            ),
        )
        assert workspace.inspector.rowCount() == 2
        assert workspace.history.rowCount() == 2
        assert workspace.history.item(0, 0).text() == "revision-1"
        assert workspace.history.item(1, 2).text() == "current"
    finally:
        workspace.close()


def test_history_selection_emits_exact_identity_and_replaces_only_inspector() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    workspace = DataManagerCatalogWorkspace()
    observed: list[tuple[str, str, object]] = []
    workspace.history_selected.connect(
        lambda family, identity, value: observed.append(
            (family, identity, value)
        )
    )
    try:
        workspace.select_family("Artifact Collections")
        workspace.set_inspection(
            (("collection_id", "ac_123"), ("revision_id", "current"))
        )
        revisions = (
            _Revision("ac_123", "revision-1", "Original", "2026-08-01"),
            _Revision("ac_123", "revision-2", "Current", "2026-08-02"),
        )
        workspace.set_history_items("ac_123", revisions)
        assert workspace.inspector.item(1, 1).text() == "current"
        assert workspace.history.rowCount() == 2

        workspace.history.selectRow(0)
        assert observed[-1] == (
            "Artifact Collections",
            "ac_123",
            revisions[0],
        )
        fields = {
            workspace.inspector.item(row, 0).text(): workspace.inspector.item(
                row, 1
            ).text()
            for row in range(workspace.inspector.rowCount())
        }
        assert fields["revision_id"] == "revision-1"
        assert workspace.history.rowCount() == 2

        workspace.history.selectRow(1)
        assert observed[-1][2] == revisions[1]
        workspace.select_family("Databases")
        assert workspace.history.rowCount() == 0
    finally:
        workspace.close()
