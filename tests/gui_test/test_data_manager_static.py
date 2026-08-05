from __future__ import annotations

from pathlib import Path


def test_gui_uses_no_filesystem_or_area_authority() -> None:
    for relative in (
        "src/leonardo/gui/windows/data_manager_suite_window.py",
        "src/leonardo/gui/windows/data_manager_dataset_selector_dialog.py",
        "src/leonardo/gui/windows/data_manager_preview_dialog.py",
        "src/leonardo/gui/presenters/data_manager_presenter.py",
        "src/leonardo/gui/data_manager/catalogs.py",
        "src/leonardo/gui/data_manager/creation.py",
        "src/leonardo/gui/data_manager/update.py",
        "src/leonardo/gui/data_manager/operations.py",
        "src/leonardo/gui/data_manager/reconciliation.py",
    ):
        source = Path(relative).read_text(encoding="utf-8")
        assert "pathlib" not in source
        assert "DataFrame" not in source
        assert "ArtifactService" not in source
        assert "ArtifactService(" not in source
        assert "PortableRecipeStore(" not in source
        assert "DataManagerCreationStore(" not in source
        assert "CoreRunner(" not in source
        assert "TaskManager(" not in source
        assert "HistoricalDatasetLoader" not in source
        assert "AcceptedDatasetCatalog" not in source
        assert "open(" not in source


def test_task_1059_creation_behavior_uses_one_data_manager_authority() -> None:
    source = Path("src/leonardo/data_manager/service.py").read_text(encoding="utf-8")
    creation = Path(
        "src/leonardo/data_manager/creation_service.py"
    ).read_text(encoding="utf-8")
    assert "DataManagerCreationWorkflow" in source
    assert "DataManagerCreationStore" in source
    assert "create_artifact_collection" in source
    assert "build_database_revision" in source
    assert "ArtifactService(" not in creation
    assert "PortableRecipeStore(" not in creation
    assert "CoreRunner(" not in creation
    assert "TaskManager(" not in creation
    assert "delete_dataset" not in source
