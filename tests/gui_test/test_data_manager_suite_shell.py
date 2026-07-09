import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QWidget  # noqa: E402

from leonardo.gui.metadata import load_metadata_document  # noqa: E402
from leonardo.gui.windows.data_manager_suite_window import (  # noqa: E402
    DATA_MANAGER_SUITE_METADATA_ID,
    DataManagerSuiteWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_MANAGER_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "data_manager_suite.window.toml"
)
_SHELL_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "data_manager_suite_window.py"
)
_DUMMY_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "dummy_data.py"


def test_data_manager_suite_shell_renders_dummy_cockpit_panels() -> None:
    qapplication = _qapplication()
    window = DataManagerSuiteWindow()

    try:
        assert isinstance(window, QWidget)
        assert window.objectName() == "data_manager_suite_window"
        assert window.property("object_id") == DATA_MANAGER_SUITE_METADATA_ID
        assert "QPushButton" in window.styleSheet()
        assert "DUMMY catalogs loaded" in window.status_text()

        expected_rows = {
            "data_manager.table.overview_dummy": 3,
            "data_manager.table.dataset_catalog_dummy": 2,
            "data_manager.table.artifact_catalog_dummy": 2,
            "data_manager.table.recipe_catalog_dummy": 2,
            "data_manager.table.storage_readiness_dummy": 3,
            "data_manager.table.import_export_controls_dummy": 3,
            "data_manager.table.processing_queue_dummy": 3,
        }
        for table_id, row_count in expected_rows.items():
            table = window.table_for_id(table_id)
            assert isinstance(table, QTableWidget)
            assert table.rowCount() == row_count

        assert window.table_for_id("data_manager.table.overview_dummy").item(2, 1).text() == (
            "offline placeholder"
        )
        assert window.table_for_id(
            "data_manager.table.import_export_controls_dummy"
        ).item(0, 2).text() == "No file picker, parser, or storage write."
        assert window.table_for_id(
            "data_manager.table.processing_queue_dummy"
        ).item(2, 2).text() == "storage disabled"

        for button_id in (
            "data_manager.button.load_dummy_catalogs",
            "data_manager.button.preview_dummy_dataset",
            "data_manager.button.preview_dummy_artifact",
            "data_manager.button.preview_dummy_recipe",
            "data_manager.button.plan_dummy_database",
        ):
            assert isinstance(window.button_for_id(button_id), QPushButton)
    finally:
        _dispose(qapplication, window)


def test_data_manager_suite_shell_actions_are_local_and_dummy_only() -> None:
    qapplication = _qapplication()
    observer = _RecordingObserver()
    window = DataManagerSuiteWindow(action_observer=observer)

    try:
        window.button_for_id("data_manager.button.preview_dummy_dataset").click()

        assert observer.calls == [
            ("data_manager.action.preview_dummy_dataset", DATA_MANAGER_SUITE_METADATA_ID)
        ]
        assert "GUI shell-only dummy behavior" in window.status_text()
        assert "no Data Manager backend ran" in window.status_log_text()
    finally:
        _dispose(qapplication, window)


def test_data_manager_suite_metadata_is_gui_owned_and_dummy_only() -> None:
    result = load_metadata_document(_DATA_MANAGER_METADATA_PATH)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == DATA_MANAGER_SUITE_METADATA_ID
    assert result.document.metadata["owner_area"] == "gui"
    assert result.document.metadata["target_area_id"] == "data_manager"
    assert result.document.metadata["status"] == "shell_only"
    assert result.document.metadata["dummy_data_status"] == "local_in_memory_gui_dummy_only"

    table_ids = {table.table_id for table in result.document.tables}
    assert {
        "data_manager.table.overview_dummy",
        "data_manager.table.dataset_catalog_dummy",
        "data_manager.table.artifact_catalog_dummy",
        "data_manager.table.recipe_catalog_dummy",
        "data_manager.table.storage_readiness_dummy",
        "data_manager.table.import_export_controls_dummy",
        "data_manager.table.processing_queue_dummy",
    } <= table_ids

    widget_ids = {widget.widget_id for widget in result.document.widgets}
    assert {
        "data_manager.label.boundary_notice",
        "data_manager.panel.overview",
        "data_manager.panel.dataset_catalog_dummy",
        "data_manager.panel.artifact_catalog_dummy",
        "data_manager.panel.recipe_catalog_dummy",
        "data_manager.panel.processing_queue_dummy",
    } <= widget_ids

    guarantees = result.document.metadata["boundary_guarantees"]
    for key in (
        "gui_presentation_only",
        "no_provider_api_call",
        "no_storage_write",
        "no_backend_materialization",
        "no_dataset_loading",
        "no_import_execution",
        "no_export_execution",
        "no_database_mutation",
        "no_artifact_execution",
        "no_recipe_execution",
    ):
        assert guarantees[key] is True


def test_data_manager_shell_sources_do_not_import_domain_execution_layers() -> None:
    forbidden_tokens = (
        "from leonardo.core",
        "import leonardo.core",
        "from leonardo.data",
        "import leonardo.data",
        "from leonardo.trading",
        "import leonardo.trading",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "socket.",
        "subprocess",
        "DownloadRequestBuilderWindow",
        "download_request_mapper",
        "storage_writer",
        "materialize_dataset",
        "RecipeExecutor",
    )

    for source_path in (_SHELL_SOURCE, _DUMMY_SOURCE):
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{source_path.name} contains {token!r}"


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _dispose(qapplication: QApplication, *widgets: QWidget) -> None:
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    qapplication.processEvents()


class _RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: object | None = None,
    ):
        self.calls.append((action_id, window_id))
        return type("Decision", (), {"allowed": True})()
