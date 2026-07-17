from pathlib import Path


def test_snapshot_layers_preserve_frozen_boundaries():
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
    assert "PySide6" not in pure
    for forbidden in ("pathlib", "ArtifactService", "HistoricalDatasetLoader", "CoreRunner"):
        assert forbidden not in gui
    assert "notebook" not in (pure + gui).lower()
    assert "annotation_id" not in (pure + gui).lower()
