from __future__ import annotations

import ast
from pathlib import Path
import re

from leonardo.gui.metadata import load_metadata_document


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUI_ROOT = _REPO_ROOT / "src" / "leonardo" / "gui"
_METADATA_DIR = _GUI_ROOT / "metadata" / "windows"
_NEW_SHELL_METADATA = {
    "connection_suite.window.toml": {
        "window_id": "connection_suite.home.window",
        "target_area_id": "connection",
        "target_suite_id": "connection_suite",
        "required_widgets": {
            "connection_suite.button.refresh_dummy_status",
            "connection_suite.button.clear_dummy_log",
            "connection_suite.button.view_historical_download_manager",
            "connection_suite.panel.provider_status",
            "connection_suite.panel.websocket_status",
            "connection_suite.panel.download_overview",
            "connection_suite.text.activity_log",
        },
        "required_actions": {
            "connection_suite.action.refresh_dummy_status",
            "connection_suite.action.clear_dummy_log",
            "connection_suite.action.view_historical_download_manager",
        },
    },
    "research_suite.window.toml": {
        "window_id": "research_suite.window",
        "target_area_id": "research",
        "target_suite_id": "research_suite",
        "required_widgets": {
            "research_suite.button.load_dummy_workspace",
            "research_suite.label.boundary_notice",
            "research_suite.panel.chart_placeholder.primary",
            "research_suite.panel.chart_controls",
            "research_suite.panel.workspace_overview",
            "research_suite.table.chart_controls_dummy",
            "research_suite.table.market_context_dummy",
            "research_suite.table.overview_dummy",
            "research_suite.table.study_sidebar_dummy",
            "research_suite.table.workspace_dummy",
        },
        "required_actions": {
            "research_suite.action.load_dummy_workspace",
            "research_suite.action.reset_dummy_workspace",
            "research_suite.action.add_chart_placeholder",
        },
    },
    "data_manager_suite.window.toml": {
        "window_id": "data_manager_suite.window",
        "target_area_id": "data_manager",
        "target_suite_id": "data_manager_suite",
        "required_widgets": {
            "data_manager.button.load_dummy_catalogs",
            "data_manager.button.preview_dummy_artifact",
            "data_manager.button.preview_dummy_recipe",
            "data_manager.table.dataset_catalog_dummy",
            "data_manager.table.artifact_catalog_dummy",
            "data_manager.table.recipe_catalog_dummy",
            "data_manager.progress.database_build_dummy",
        },
        "required_actions": {
            "data_manager.action.load_dummy_catalogs",
            "data_manager.action.preview_dummy_dataset",
            "data_manager.action.preview_dummy_artifact",
            "data_manager.action.preview_dummy_recipe",
            "data_manager.action.plan_dummy_database",
        },
    },
    "analysis_suite.window.toml": {
        "window_id": "analysis_suite.window",
        "target_area_id": "analysis",
        "target_suite_id": "analysis_suite",
        "required_widgets": {
            "analysis_suite.button.load_dummy_state",
            "analysis_suite.button.reset_dummy_plan",
            "analysis_suite.label.boundary_notice",
            "analysis_suite.panel.overview",
            "analysis_suite.panel.queue_status_dummy",
            "analysis_suite.table.diagnostics_dummy",
            "analysis_suite.table.overview_dummy",
            "analysis_suite.table.queue_status_dummy",
            "analysis_suite.table.readiness_dummy",
            "analysis_suite.table.feature_plan_dummy",
            "analysis_suite.table.result_summary_dummy",
            "analysis_suite.text.diagnostics_report_dummy",
        },
        "required_actions": {
            "analysis_suite.action.load_dummy_state",
            "analysis_suite.action.preview_target_plan",
            "analysis_suite.action.preview_diagnostics",
            "analysis_suite.action.reset_dummy_plan",
        },
    },
    "trading_suite.window.toml": {
        "window_id": "trading_suite.window",
        "target_area_id": "trading",
        "target_suite_id": "trading_suite",
        "required_widgets": {
            "trading_suite.button.load_dummy_trading_state",
            "trading_suite.button.kill_switch_visual",
            "trading_suite.table.account_risk_dummy",
            "trading_suite.table.order_position_dummy",
            "trading_suite.panel.kill_switch_visual_placeholder",
        },
        "required_actions": {
            "trading_suite.action.load_dummy_trading_state",
            "trading_suite.action.preview_paper_shell",
            "trading_suite.action.kill_switch_placeholder",
        },
    },
}
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
_FORBIDDEN_STATIC_TOKENS = (
    "from leonardo.core",
    "import leonardo.core",
    "from leonardo.connection",
    "import leonardo.connection",
    "from leonardo.data",
    "import leonardo.data",
    "from leonardo.analysis",
    "import leonardo.analysis",
    "from leonardo.trading",
    "import leonardo.trading",
    "requests.",
    "httpx.",
    "aiohttp.",
    "websockets",
    "socket.",
    "subprocess",
    "QChart",
    "matplotlib",
    "mplfinance",
    "plotly",
    "place_order",
    "submit_order",
    "broker_client",
    "storage_writer",
    "materialize_dataset",
    "AnalysisEngine",
    "DownloadExecutionManager",
    "DownloadRequestBuilderWindow",
)


def test_all_gui_window_metadata_is_gui_owned() -> None:
    for path in sorted(_METADATA_DIR.glob("*.window.toml")):
        document = _load(path)
        assert document.metadata["owner_area"] == "gui", path.name


def test_new_shell_metadata_is_traceable_and_dummy_only() -> None:
    for filename, expected in _NEW_SHELL_METADATA.items():
        document = _load(_METADATA_DIR / filename)
        metadata = document.metadata
        assert metadata["window_id"] == expected["window_id"]
        assert metadata["status"] == "shell_only"
        assert metadata["ownership_scope"] == "presentation_shell_only"
        assert metadata["target_area_id"] == expected["target_area_id"]
        assert metadata["target_suite_id"] == expected["target_suite_id"]
        assert metadata["dummy_data_status"] == "local_in_memory_gui_dummy_only"
        assert metadata["traceability"]["no_anonymous_widgets"] is True
        assert metadata["dummy_data"]["deterministic"] is True
        assert metadata["dummy_data"]["local_in_memory"] is True
        assert metadata["dummy_data"]["network_calls"] is False
        assert metadata["dummy_data"]["storage_writes"] is False
        assert metadata["boundary_guarantees"]["gui_presentation_only"] is True
        assert metadata["boundary_guarantees"]["no_provider_api_call"] is True
        assert metadata["boundary_guarantees"]["no_storage_write"] is True

        action_ids = {action.action_id for action in document.actions}
        widget_ids = {widget.widget_id for widget in document.widgets}
        table_ids = {table.table_id for table in document.tables}
        assert expected["required_actions"] <= action_ids
        assert expected["required_widgets"] <= widget_ids | table_ids


def test_traceable_ids_are_unique_and_deterministic_in_new_shells() -> None:
    for filename in _NEW_SHELL_METADATA:
        document = _load(_METADATA_DIR / filename)
        ids = [
            document.metadata["window_id"],
            *(region.region_id for region in document.regions),
            *(action.action_id for action in document.actions),
            *(widget.widget_id for widget in document.widgets),
            *(table.table_id for table in document.tables),
        ]
        assert len(ids) == len(set(ids)), filename
        assert all(_ID_PATTERN.match(object_id) for object_id in ids), filename


def test_main_window_launch_surfaces_target_shell_windows_only() -> None:
    document = _load(_METADATA_DIR / "main_window.window.toml")
    launch_surfaces = document.metadata["launch_surfaces"]
    expected = {
        "download_data": "connection_suite.home.window",
        "ohlcv_maintenance": "historical_download_manager.window",
        "research_suite": "research_suite.window",
        "data_manager_suite": "data_manager_suite.window",
        "analysis_suite": "analysis_suite.window",
        "trading_suite": "trading_suite.window",
        "runtime_manager": "runtime_manager.window",
    }
    for launch_id, target_window_id in expected.items():
        launch = launch_surfaces[launch_id]
        assert launch["target_window_id"] == target_window_id
        assert launch["ownership_scope"] == "launch_surface_only"
        assert launch["execution_owner"] == "none_shell_only"
        assert launch["storage_owner"] in {
            "none_shell_only",
            "metadata_override_store_when_enabled",
        }


def test_static_window_trace_defaults_include_new_suite_shells() -> None:
    source = (_GUI_ROOT / "metadata" / "window_trace.py").read_text(encoding="utf-8")
    for filename in _NEW_SHELL_METADATA:
        assert filename in source


def test_dummy_data_provider_is_local_in_memory_only() -> None:
    source_path = _GUI_ROOT / "dummy_data.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    from_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imports == set()
    assert from_imports <= {"__future__", "collections.abc"}
    assert "open(" not in source
    assert ".write(" not in source
    assert "Path(" not in source
    assert "requests" not in source
    assert "httpx" not in source
    assert "import socket" not in source
    assert "socket." not in source
    assert "socket(" not in source


def test_new_gui_shell_sources_do_not_import_domain_execution_layers() -> None:
    source_paths = (
        _GUI_ROOT / "windows" / "connection_suite_window.py",
        _GUI_ROOT / "windows" / "research_suite_window.py",
        _GUI_ROOT / "windows" / "data_manager_suite_window.py",
        _GUI_ROOT / "windows" / "analysis_suite_window.py",
        _GUI_ROOT / "windows" / "trading_suite_window.py",
        _GUI_ROOT / "windows" / "traceable_shell_widgets.py",
        _GUI_ROOT / "widgets" / "suite_navigation_donut.py",
        _GUI_ROOT / "dummy_data.py",
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        for token in _FORBIDDEN_STATIC_TOKENS:
            assert token not in source, f"{path.name} contains forbidden token {token}"


def test_removed_download_data_symbols_are_absent_from_active_source() -> None:
    active_sources = list((_REPO_ROOT / "src" / "leonardo").rglob("*.py"))
    blocked = (
        "leonardo.download_data",
        "DownloadRequestBuilderWindow",
        "download_request_builder",
        "download_request_mapper",
        "DownloadExecutionManager",
        "composition_core_download_manager",
    )
    for path in active_sources:
        source = path.read_text(encoding="utf-8")
        for token in blocked:
            assert token not in source, f"{path.relative_to(_REPO_ROOT)} contains {token}"


def _load(path: Path):
    result = load_metadata_document(path)
    assert result.document is not None, path.name
    assert result.report.has_errors is False, [issue.message for issue in result.report.issues]
    return result.document
