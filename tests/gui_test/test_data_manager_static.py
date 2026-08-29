from __future__ import annotations

from pathlib import Path


def test_gui_uses_no_filesystem_or_area_authority() -> None:
    for relative in (
        "src/leonardo/gui/windows/data_manager_suite_window.py",
        "src/leonardo/gui/windows/data_manager_dataset_selector_dialog.py",
        "src/leonardo/gui/windows/data_manager_preview_dialog.py",
        "src/leonardo/gui/windows/data_manager_artifact_creation_dialog.py",
        "src/leonardo/gui/windows/data_manager_construct_batch_dialog.py",
        "src/leonardo/gui/windows/data_manager_recipe_derivation_dialog.py",
        "src/leonardo/gui/presenters/data_manager_presenter.py",
        "src/leonardo/gui/data_manager/catalogs.py",
        "src/leonardo/gui/data_manager/creation.py",
        "src/leonardo/gui/data_manager/update.py",
        "src/leonardo/gui/data_manager/operations.py",
        "src/leonardo/gui/data_manager/table_presentation.py",
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


def test_data_manager_catalog_layout_uses_responsive_upper_and_bottom_regions() -> None:
    suite = Path(
        "src/leonardo/gui/windows/data_manager_suite_window.py"
    ).read_text(encoding="utf-8")
    catalogs = Path("src/leonardo/gui/data_manager/catalogs.py").read_text(
        encoding="utf-8"
    )
    presenter = Path(
        "src/leonardo/gui/presenters/data_manager_presenter.py"
    ).read_text(encoding="utf-8")

    assert '"Recipes"' in catalogs
    assert '"Artifacts"' in catalogs
    assert '"Portable Recipes"' not in catalogs
    assert '"Managed Artifacts"' not in catalogs
    assert 'family == "Recipes"' in presenter
    assert 'family == "Artifacts"' in presenter

    assert '"data_manager.splitter.body"' not in suite
    assert '"data_manager.panel.right_rail"' not in suite
    assert "upper_layout.addWidget(tabs)" in suite
    assert "upper_layout.addWidget(operation)" in suite
    assert "upper_layout.setStretch(0, 3)" in suite
    assert "upper_layout.setStretch(1, 1)" in suite
    assert "details_layout.addWidget(self._catalog_workspace.inspector_panel())" in suite
    assert "details_layout.addWidget(self._catalog_workspace.history_panel())" in suite
    assert "details_layout.setStretch(0, 1)" in suite
    assert "details_layout.setStretch(1, 1)" in suite
    assert "body_layout.setStretch(0, 7)" in suite
    assert "body_layout.setStretch(1, 3)" in suite
    assert "setFixedWidth(190)" not in catalogs
    assert "objects.addWidget" not in suite
    assert "def _table_panel(" not in suite
    for obsolete_button in (
        "data_manager.button.preview_artifact",
        "data_manager.button.validate_artifact",
        "data_manager.button.delete_artifact",
        "data_manager.button.delete_recipe",
    ):
        assert obsolete_button not in suite


def test_create_artifact_action_belongs_only_to_artifacts_catalog_context() -> None:
    suite = Path(
        "src/leonardo/gui/windows/data_manager_suite_window.py"
    ).read_text(encoding="utf-8")
    catalogs = Path("src/leonardo/gui/data_manager/catalogs.py").read_text(
        encoding="utf-8"
    )
    assert 'QPushButton("Create Artifact...", center)' in catalogs
    assert 'QPushButton("Batch Constructs...", center)' in catalogs
    assert 'self.current_family == "Artifacts"' in catalogs
    assert "center_layout.addWidget(self.table, 1)" in catalogs
    assert 'QToolBar("Create Artifact' not in suite
    assert 'addAction("Create Artifact' not in suite
    assert 'addAction("Batch Constructs' not in suite


def test_construct_batch_tables_use_shared_data_manager_sizing_authority() -> None:
    source = Path(
        "src/leonardo/gui/windows/data_manager_construct_batch_dialog.py"
    ).read_text(encoding="utf-8")
    for authority in (
        "DATA_MANAGER_DATASET_COLUMNS",
        "data_manager_dataset_row",
        "data_manager_dataset_details",
        "resize_data_manager_table",
        "configure_table",
    ):
        assert authority in source
    assert "DataManagerDatasetEntry" in source
    assert 'object_id="data_manager.construct_batch.dataset_table"' in source
    for old_field in ("exchange", "market_type", "asset", "timeframe"):
        assert f'"data_manager.construct_batch.dataset.{old_field}"' not in source
    assert "resize_data_manager_table(self.dataset_table)" in source
    assert "resize_data_manager_table(self.combination_table)" in source
    assert "resize_data_manager_table(self.preview_table)" in source
