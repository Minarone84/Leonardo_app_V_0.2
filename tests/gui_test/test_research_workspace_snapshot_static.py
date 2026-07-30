from pathlib import Path


def _snapshot_sources():
    pure = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/leonardo/research/workspace_snapshot.py",
            "src/leonardo/research/workspace_snapshot_store.py",
            "src/leonardo/research/workspace_snapshot_service.py",
        )
    )
    gui = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/leonardo/gui/windows/workspace_snapshot_save_dialog.py",
            "src/leonardo/gui/windows/workspace_snapshot_manager_dialog.py",
            "src/leonardo/gui/windows/workspace_snapshot_preflight_dialog.py",
        )
    )
    return pure, gui


def test_snapshot_layers_preserve_frozen_boundaries():
    pure, gui = _snapshot_sources()
    assert "PySide6" not in pure
    for forbidden in ("pathlib", "ArtifactService", "HistoricalDatasetLoader", "CoreRunner"):
        assert forbidden not in gui
    assert "annotation_id" not in (pure + gui).lower()


def test_snapshot_pure_layer_owns_only_notebook_identity_and_linkage():
    pure, _gui = _snapshot_sources()
    assert "notebook_id" in pure
    assert "ResearchWorkspaceNotebookLinkService" in pure
    for forbidden in (
        "notebook_display_name",
        "ResearchNotebookStore",
        "ResearchNotebookV1",
        "ResearchNotebookSummary",
    ):
        assert forbidden not in pure


def test_snapshot_dialogs_remain_notebook_service_and_persistence_free():
    _pure, gui = _snapshot_sources()
    for forbidden in (
        "notebook_id",
        "ResearchWorkspaceNotebookLinkService",
        "ResearchNotebookStore",
        "ResearchNotebookService",
    ):
        assert forbidden not in gui
