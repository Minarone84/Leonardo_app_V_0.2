import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QWidget  # noqa: E402

from leonardo.gui.metadata import load_metadata_document  # noqa: E402
from leonardo.gui.windows.analysis_suite_window import (  # noqa: E402
    ANALYSIS_SUITE_METADATA_ID,
    AnalysisSuiteWindow,
)
from leonardo.gui.windows.research_suite_window import (  # noqa: E402
    RESEARCH_SUITE_METADATA_ID,
    ResearchSuiteWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "research_suite.window.toml"
)
_ANALYSIS_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "analysis_suite.window.toml"
)
_SHELL_SOURCES = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "research_suite_window.py",
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "analysis_suite_window.py",
)


@pytest.fixture
def qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_research_suite_shell_renders_dummy_cockpit_panels(
    qapplication: QApplication,
) -> None:
    window = ResearchSuiteWindow()

    try:
        assert isinstance(window, QWidget)
        assert window.objectName() == "research_suite_window"
        assert window.property("object_id") == RESEARCH_SUITE_METADATA_ID
        assert "QPushButton" in window.styleSheet()
        assert "DUMMY workspace loaded" in window.status_text()

        expected_rows = {
            "research_suite.table.overview_dummy": 3,
            "research_suite.table.study_sidebar_dummy": 2,
            "research_suite.table.market_context_dummy": 3,
            "research_suite.table.workspace_dummy": 2,
            "research_suite.table.chart_controls_dummy": 3,
        }
        for table_id, row_count in expected_rows.items():
            table = window.table_for_id(table_id)
            assert isinstance(table, QTableWidget)
            assert table.rowCount() == row_count

        assert window.table_for_id("research_suite.table.overview_dummy").item(0, 1).text() == (
            "Research Lab / dummy"
        )
        assert window.table_for_id(
            "research_suite.table.market_context_dummy"
        ).item(1, 2).text() == "no provider/API call"
        assert window.table_for_id(
            "research_suite.table.chart_controls_dummy"
        ).item(2, 2).text() == "no calculation"

        for button_id in (
            "research_suite.button.load_dummy_workspace",
            "research_suite.button.reset_dummy_workspace",
            "research_suite.button.add_chart_placeholder",
        ):
            assert isinstance(window.button_for_id(button_id), QPushButton)
    finally:
        _dispose(qapplication, window)


def test_research_suite_shell_actions_are_local_and_dummy_only(
    qapplication: QApplication,
) -> None:
    observer = _RecordingObserver()
    window = ResearchSuiteWindow(action_observer=observer)

    try:
        window.button_for_id("research_suite.button.add_chart_placeholder").click()

        assert observer.calls == [
            ("research_suite.action.add_chart_placeholder", RESEARCH_SUITE_METADATA_ID)
        ]
        assert "GUI shell-only dummy behavior" in window.status_text()
        assert "no chart logic executed" in window.status_log_text()
    finally:
        _dispose(qapplication, window)


def test_analysis_suite_shell_renders_dummy_cockpit_panels(
    qapplication: QApplication,
) -> None:
    window = AnalysisSuiteWindow()

    try:
        assert isinstance(window, QWidget)
        assert window.objectName() == "analysis_suite_window"
        assert window.property("object_id") == ANALYSIS_SUITE_METADATA_ID
        assert "QPushButton" in window.styleSheet()
        assert "DUMMY analysis shell loaded" in window.status_text()

        expected_rows = {
            "analysis_suite.table.overview_dummy": 3,
            "analysis_suite.table.readiness_dummy": 2,
            "analysis_suite.table.feature_plan_dummy": 2,
            "analysis_suite.table.result_summary_dummy": 3,
            "analysis_suite.table.diagnostics_dummy": 3,
            "analysis_suite.table.queue_status_dummy": 2,
        }
        for table_id, row_count in expected_rows.items():
            table = window.table_for_id(table_id)
            assert isinstance(table, QTableWidget)
            assert table.rowCount() == row_count

        assert window.table_for_id("analysis_suite.table.overview_dummy").item(0, 1).text() == (
            "offline placeholder"
        )
        assert window.table_for_id(
            "analysis_suite.table.result_summary_dummy"
        ).item(2, 2).text() == "writes forbidden"
        assert window.table_for_id(
            "analysis_suite.table.queue_status_dummy"
        ).item(0, 2).text() == "No queued execution tasks."
        assert "No analysis engine ran" in window.report_text()
    finally:
        _dispose(qapplication, window)


def test_analysis_suite_shell_actions_are_local_and_dummy_only(
    qapplication: QApplication,
) -> None:
    observer = _RecordingObserver()
    window = AnalysisSuiteWindow(action_observer=observer)

    try:
        window.button_for_id("analysis_suite.button.preview_diagnostics").click()

        assert observer.calls == [
            ("analysis_suite.action.preview_diagnostics", ANALYSIS_SUITE_METADATA_ID)
        ]
        assert "GUI shell-only dummy behavior" in window.status_text()
        assert "no Analysis Suite engine ran" in window.status_log_text()
    finally:
        _dispose(qapplication, window)


@pytest.mark.parametrize(
    ("metadata_id", "metadata_path", "target_area_id", "expected_tables", "guarantee_keys"),
    (
        (
            RESEARCH_SUITE_METADATA_ID,
            _RESEARCH_METADATA_PATH,
            "research",
            {
                "research_suite.table.overview_dummy",
                "research_suite.table.study_sidebar_dummy",
                "research_suite.table.market_context_dummy",
                "research_suite.table.workspace_dummy",
                "research_suite.table.chart_controls_dummy",
            },
            {
                "no_chart_renderer",
                "no_study_execution",
                "no_indicator_calculation",
                "no_dataset_loading",
            },
        ),
        (
            ANALYSIS_SUITE_METADATA_ID,
            _ANALYSIS_METADATA_PATH,
            "analysis",
            {
                "analysis_suite.table.overview_dummy",
                "analysis_suite.table.readiness_dummy",
                "analysis_suite.table.feature_plan_dummy",
                "analysis_suite.table.result_summary_dummy",
                "analysis_suite.table.diagnostics_dummy",
                "analysis_suite.table.queue_status_dummy",
            },
            {
                "no_analysis_engine",
                "no_analysis_execution",
                "no_dataset_loading",
                "no_report_generation",
                "no_calculation",
            },
        ),
    ),
)
def test_research_analysis_shell_metadata_is_gui_owned_and_dummy_only(
    metadata_id: str,
    metadata_path: Path,
    target_area_id: str,
    expected_tables: set[str],
    guarantee_keys: set[str],
) -> None:
    result = load_metadata_document(metadata_path)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == metadata_id
    assert result.document.metadata["owner_area"] == "gui"
    assert result.document.metadata["target_area_id"] == target_area_id
    assert result.document.metadata["status"] == "shell_only"
    assert result.document.metadata["dummy_data_status"] == "local_in_memory_gui_dummy_only"

    table_ids = {table.table_id for table in result.document.tables}
    assert expected_tables <= table_ids

    guarantees = result.document.metadata["boundary_guarantees"]
    assert guarantees["gui_presentation_only"] is True
    assert guarantees["no_provider_api_call"] is True
    assert guarantees["no_storage_write"] is True
    for key in guarantee_keys:
        assert guarantees[key] is True


def test_research_analysis_shell_sources_do_not_import_domain_execution_layers() -> None:
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
        "QChart",
        "matplotlib",
        "plotly",
        "AnalysisEngine",
        "storage_writer",
    )

    for source_path in _SHELL_SOURCES:
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{source_path.name} contains {token!r}"


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
