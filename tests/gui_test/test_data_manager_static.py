from __future__ import annotations

from pathlib import Path


def test_gui_uses_no_filesystem_or_area_authority() -> None:
    for relative in (
        "src/leonardo/gui/windows/data_manager_suite_window.py",
        "src/leonardo/gui/windows/data_manager_preview_dialog.py",
        "src/leonardo/gui/presenters/data_manager_presenter.py",
    ):
        source = Path(relative).read_text(encoding="utf-8")
        assert "pathlib" not in source
        assert "DataFrame" not in source
        assert "ArtifactService" not in source
        assert "HistoricalDatasetLoader" not in source
        assert "AcceptedDatasetCatalog" not in source
        assert "open(" not in source


def test_exact_task_boundary_contains_no_database_or_collection_behavior() -> None:
    source = Path("src/leonardo/data_manager/service.py").read_text(encoding="utf-8")
    assert "database" not in source.lower()
    assert "list_collections" not in source
    assert "create_collection" not in source
    assert "delete_dataset" not in source
