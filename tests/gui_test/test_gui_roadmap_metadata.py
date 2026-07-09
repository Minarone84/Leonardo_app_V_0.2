from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import re
from types import MappingProxyType

import pytest

from leonardo.gui.action_observer import TRACKED_GUI_ACTION_DEFINITIONS
from leonardo.gui.metadata.gui_roadmap import (
    GUI_ROADMAP_METADATA_PATH,
    GUI_ROADMAP_SCHEMA_PATH,
    load_gui_roadmap,
    load_gui_roadmap_schema,
    validate_gui_roadmap,
)
from leonardo.gui.metadata.loader import load_metadata_document


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUI_METADATA_WINDOWS_DIR = _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata" / "windows"
_ROADMAP_PATH = _REPO_ROOT / GUI_ROADMAP_METADATA_PATH
_SCHEMA_PATH = _REPO_ROOT / GUI_ROADMAP_SCHEMA_PATH
_ACTIVE_WINDOW_STATUSES = {"implemented", "shell_only"}
_STATUS_TAXONOMY = {
    "implemented",
    "shell_only",
    "planned_shell",
    "future_domain",
    "legacy_reference_only",
    "removed_do_not_resurrect",
    "explicitly_out_of_scope",
}
_AI_AGENT_FIELDS = {
    "visible_to_ai",
    "agent_can_reference",
    "agent_can_request_open",
    "agent_can_request_click",
    "agent_can_read_status",
    "agent_can_mutate_directly",
    "requires_human_confirmation",
    "interaction_channel",
    "notes",
}
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
_GUI_ROADMAP_STABLE_SOURCE_FILES = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "main_window.py",
    _REPO_ROOT / "src" / "leonardo" / "gui" / "widgets" / "suite_navigation_donut.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "historical_download_manager_window.py",
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "runtime_manager_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "ohlcv_download_preflight_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "ohlcv_download_task_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "settings_inspector_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "connection_suite_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "research_suite_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "data_manager_suite_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "analysis_suite_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "trading_suite_window.py",
)
_EXCLUDED_STABLE_GUI_SOURCE_IDS = frozenset(
    {
        # Test-only dummy fixture internals are not scanned by this test. Future
        # intentional exclusions must be listed here with a reason.
    }
)
_EXPECTED_IMPLEMENTED_GUI_SOURCE_IDS = frozenset(
    {
        "main_window.label.title",
        "main_window.label.placeholder",
        "main_window.label.username",
        "main_window.label.version",
        "main_window.layout.central",
        "main_window.layout.suite_navigation",
        "main_window.widget.suite_navigation_donut",
        "main_window.donut.segment.connection_suite",
        "main_window.donut.segment.research_suite",
        "main_window.donut.segment.data_manager",
        "main_window.donut.segment.analysis_suite",
        "main_window.donut.segment.trading_suite",
        "main_window.panel.suite_navigation_utilities",
        "main_window.layout.suite_navigation_utilities",
        "main_window.utility_button.runtime_manager",
        "main_window.utility_button.settings",
        "historical_download_manager.title",
        "historical_download_manager.label.timeframes",
        "historical_download_manager.layout.root",
        "historical_download_manager.layout.selection_form",
        "historical_download_manager.layout.timeframes",
        "historical_download_manager.layout.timeframe_buttons",
        "historical_download_manager.layout.action_buttons",
        "historical_download_manager.select_all_timeframes",
        "historical_download_manager.clear_timeframes",
        "historical_download_manager.start",
        "historical_download_manager.stop",
        "historical_download_manager.ohlcv_maintenance",
        "historical_download_manager.label.exchange",
        "historical_download_manager.label.market_type",
        "historical_download_manager.label.symbol",
        "historical_download_manager.label.start_ms",
        "historical_download_manager.label.end_ms",
        "historical_download_manager.label.limit",
        "historical_download_manager.start_ms",
        "historical_download_manager.end_ms",
        "historical_download_manager.limit",
        "runtime_manager.layout.root",
        "runtime_manager.layout.header",
        "runtime_manager.layout.toolbar",
        "runtime_manager.layout.body",
        "runtime_manager.layout.footer",
        "runtime_manager.panel.header",
        "runtime_manager.panel.footer",
        "runtime_manager.panel.overview",
        "runtime_manager.subtitle_label",
        "runtime_manager.theme_status_label",
        "runtime_manager.layout.overview",
        "runtime_manager.card.health",
        "runtime_manager.card.generated_at",
        "runtime_manager.card.summary_rows",
        "runtime_manager.card.audit_preview_rows",
        "runtime_manager.title_label",
        "runtime_manager.summary_table",
        "runtime_manager.services_table",
        "runtime_manager.tasks_table",
        "runtime_manager.processes_table",
        "runtime_manager.connections_table",
        "runtime_manager.windows_table",
        "runtime_manager.actions_table",
        "runtime_manager.operations_table",
        "runtime_manager.audit_preview_table",
        "ohlcv_download_preflight_window",
        "ohlcv_download_preflight.layout.root",
        "ohlcv_download_preflight.layout.actions",
        "ohlcv_download_task_window",
        "ohlcv_download_task.header",
        "ohlcv_download_task.label.overall_progress",
        "ohlcv_download_task.label.current_timeframe_progress",
        "ohlcv_download_task.label.progress_log",
        "ohlcv_download_task.label.final_recap",
        "ohlcv_download_task.layout.root",
        "ohlcv_download_task.layout.summary",
        "ohlcv_download_task.layout.actions",
        "settings_inspector.close",
        "settings_inspector.label.source_status",
        "settings_inspector.label.theme_status",
        "settings_inspector.label.title",
        "settings_inspector.label.value",
        "settings_inspector.panel.controls",
        "settings_inspector.panel.diagnostics",
        "settings_inspector.panel.editor",
        "settings_inspector.panel.header",
        "settings_inspector.panel.settings",
        "settings_inspector.reset_field",
        "settings_inspector.reset_profile",
        "settings_inspector.reset_section",
        "settings_inspector_window",
        "research_suite.combo.study_environment_dummy",
        "research_suite.label.chart_placeholder.message",
        "research_suite.label.chart_placeholder.title",
        "research_suite.label.status",
        "research_suite.label.study_environment",
        "research_suite.label.title",
        "research_suite.layout.chart_placeholder.primary",
        "research_suite.layout.header",
        "research_suite.layout.root",
        "research_suite.layout.status_log",
        "research_suite.layout.study_sidebar",
        "research_suite.layout.toolbar",
        "research_suite.layout.workspace_objects",
        "research_suite.panel.chart_placeholder.primary",
        "research_suite.panel.header",
        "research_suite.panel.status_log",
        "research_suite.panel.study_sidebar",
        "research_suite.panel.workspace_objects",
        "research_suite.splitter.workspace",
        "research_suite.tabs.workspace",
        "data_manager.label.database_build_dummy",
        "data_manager.label.status",
        "data_manager.label.title",
        "data_manager.layout.artifact_recipe_dummy",
        "data_manager.layout.database_build_dummy",
        "data_manager.layout.dataset_catalog_dummy",
        "data_manager.layout.header",
        "data_manager.layout.metadata_status_dummy",
        "data_manager.layout.root",
        "data_manager.layout.toolbar",
        "data_manager.panel.artifact_recipe_dummy",
        "data_manager.panel.database_build_dummy",
        "data_manager.panel.header",
        "data_manager.panel.metadata_status_dummy",
        "data_manager.splitter.catalogs",
        "data_manager.text.metadata_status_dummy",
        "analysis_suite.label.status",
        "analysis_suite.label.target_plan_dummy",
        "analysis_suite.label.title",
        "analysis_suite.layout.diagnostics_report_dummy",
        "analysis_suite.layout.header",
        "analysis_suite.layout.readiness_dummy",
        "analysis_suite.layout.root",
        "analysis_suite.layout.status_log",
        "analysis_suite.layout.target_feature_dummy",
        "analysis_suite.layout.toolbar",
        "analysis_suite.panel.header",
        "analysis_suite.panel.readiness_dummy",
        "analysis_suite.panel.status_log",
        "analysis_suite.panel.target_feature_dummy",
        "analysis_suite.splitter.workspace",
        "trading_suite.label.kill_switch_visual_placeholder",
        "trading_suite.label.status",
        "trading_suite.label.title",
        "trading_suite.layout.account_risk_dummy",
        "trading_suite.layout.header",
        "trading_suite.layout.kill_switch_visual_placeholder",
        "trading_suite.layout.order_position_dummy",
        "trading_suite.layout.root",
        "trading_suite.layout.status_log",
        "trading_suite.layout.toolbar",
        "trading_suite.panel.account_risk_dummy",
        "trading_suite.panel.header",
        "trading_suite.panel.order_position_dummy",
        "trading_suite.panel.status_log",
    }
)


def test_gui_roadmap_and_schema_are_valid_json() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    schema = _load_json(_SCHEMA_PATH)

    assert roadmap["roadmap_id"] == "leonardo_v2.gui.roadmap"
    assert schema["title"] == "Leonardo V2 GUI Roadmap Metadata"


def test_gui_roadmap_json_uses_lf_line_endings() -> None:
    raw = _ROADMAP_PATH.read_bytes()

    assert b"\r\n" not in raw
    assert b"\r" not in raw


def test_gui_roadmap_loader_returns_read_only_metadata() -> None:
    roadmap = load_gui_roadmap(_ROADMAP_PATH)
    schema = load_gui_roadmap_schema(_SCHEMA_PATH)

    assert roadmap.roadmap_id == "leonardo_v2.gui.roadmap"
    assert roadmap.schema_version == "1"
    assert isinstance(roadmap.data, MappingProxyType)
    assert isinstance(schema, MappingProxyType)
    with pytest.raises(TypeError):
        roadmap.data["roadmap_id"] = "changed"  # type: ignore[index]
    assert roadmap.window_by_id("main_window.window")["display_name"] == "Main Window"
    assert roadmap.action_by_id("main_window.download_data")["status"] == "shell_only"
    assert roadmap.object_by_id("main_window.menu.connection")["object_type"] == "menu"
    assert roadmap.suite_by_id("connection_suite")["target_area_id"] == "connection"


def test_gui_roadmap_top_level_contract_is_complete() -> None:
    roadmap = _load_json(_ROADMAP_PATH)

    assert validate_gui_roadmap(roadmap) == ()
    assert {
        "roadmap_id",
        "schema_version",
        "status",
        "nsrr_policy",
        "status_taxonomy",
        "ownership_policy",
        "id_conventions",
        "areas",
        "suites",
        "windows",
        "objects",
        "actions",
        "ai_agent_usage",
    } <= set(roadmap)
    assert _STATUS_TAXONOMY == {item["status"] for item in roadmap["status_taxonomy"]}


def test_gui_roadmap_schema_requires_object_owner_and_target_fields() -> None:
    schema = _load_json(_SCHEMA_PATH)
    object_schema = schema["$defs"]["object"]
    required_fields = set(object_schema["required"])
    properties = object_schema["properties"]

    assert {
        "owner_area",
        "target_area_id",
        "target_suite_id",
        "target_module_id",
    } <= required_fields
    assert properties["owner_area"]["type"] == "string"
    for field_name in ("target_area_id", "target_suite_id", "target_module_id"):
        assert properties[field_name]["type"] == ["string", "null"]


def test_gui_roadmap_ids_are_stable_and_unique_by_category() -> None:
    roadmap = _load_json(_ROADMAP_PATH)

    _assert_unique_ids(roadmap["areas"], "area_id")
    _assert_unique_ids(roadmap["suites"], "suite_id")
    _assert_unique_ids(roadmap["windows"], "window_id")
    _assert_unique_ids(roadmap["actions"], "action_id")
    _assert_unique_ids(roadmap["objects"], "object_id")

    for section, field_name in (
        ("areas", "area_id"),
        ("suites", "suite_id"),
        ("windows", "window_id"),
        ("actions", "action_id"),
        ("objects", "object_id"),
    ):
        for item in roadmap[section]:
            assert _ID_PATTERN.fullmatch(item[field_name]), item[field_name]


def test_window_action_references_are_declared_actions() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    action_ids = set(_by_id(roadmap["actions"], "action_id"))

    for window in roadmap["windows"]:
        for action_id in window["action_ids"]:
            assert action_id in action_ids, (window["window_id"], action_id)


def test_action_source_objects_exist_in_object_graph() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    object_ids = _object_or_window_ids(roadmap)

    for action in roadmap["actions"]:
        assert action["source_object_id"] in object_ids, action["action_id"]


def test_settings_inspector_button_actions_are_declared_and_linked() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    actions = _by_id(roadmap["actions"], "action_id")
    objects = _by_id(roadmap["objects"], "object_id")
    window = _by_id(roadmap["windows"], "window_id")["settings_inspector.window"]
    expected_action_ids = {
        "settings_inspector.save",
        "settings_inspector.apply_changes",
        "settings_inspector.reset_field",
        "settings_inspector.reset_section",
        "settings_inspector.reset_profile",
        "settings_inspector.close",
    }

    for action_id in expected_action_ids:
        action = actions[action_id]
        object_record = objects[action_id]

        assert action_id in window["action_ids"]
        assert action["owner_area"] == "gui"
        assert action["target_area_id"] == "gui"
        assert action["target_suite_id"] == "gui_service"
        assert action["target_module_id"] == "gui.settings"
        assert action["status"] == "implemented"
        assert action["source_object_id"] == action_id
        assert object_record["linked_action_id"] == action_id
        assert object_record["ai_agent"]["agent_can_request_click"] is True
        assert object_record["ai_agent"]["agent_can_mutate_directly"] is False
        assert object_record["ai_agent"]["interaction_channel"] == "gui_action_observer"

    for action_id in (
        "settings_inspector.reset_field",
        "settings_inspector.reset_section",
        "settings_inspector.reset_profile",
    ):
        assert actions[action_id]["requires_human_confirmation"] is True
        assert objects[action_id]["ai_agent"]["requires_human_confirmation"] is True


def test_window_child_objects_exist_in_object_graph() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    object_ids = _object_or_window_ids(roadmap)

    for window in roadmap["windows"]:
        for object_id in window["child_object_ids"]:
            assert object_id in object_ids, (window["window_id"], object_id)


def test_object_parent_references_resolve_to_objects_or_windows() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    object_ids = _object_or_window_ids(roadmap)

    for object_record in roadmap["objects"]:
        parent_object_id = object_record["parent_object_id"]
        if parent_object_id is not None:
            assert parent_object_id in object_ids, object_record["object_id"]


def test_every_object_has_explicit_gui_owner_and_target_fields() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    suite_ids = {suite["suite_id"] for suite in roadmap["suites"]}

    for object_record in roadmap["objects"]:
        assert object_record["owner_area"] == "gui"
        assert object_record["owner_area"] not in suite_ids
        assert "target_area_id" in object_record
        assert "target_suite_id" in object_record
        assert "target_module_id" in object_record
        assert object_record["target_area_id"] is None or isinstance(
            object_record["target_area_id"], str
        )
        assert object_record["target_suite_id"] is None or isinstance(
            object_record["target_suite_id"], str
        )
        assert object_record["target_module_id"] is None or isinstance(
            object_record["target_module_id"], str
        )


def test_object_targets_are_consistent_with_windows_or_linked_actions() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    windows = _by_id(roadmap["windows"], "window_id")
    actions = _by_id(roadmap["actions"], "action_id")

    for object_record in roadmap["objects"]:
        linked_action_ids = _linked_action_ids(object_record)
        if linked_action_ids:
            linked_actions = [actions[action_id] for action_id in linked_action_ids]
            areas = {action["target_area_id"] for action in linked_actions}
            suites = {action["target_suite_id"] for action in linked_actions}
            modules = {action["target_module_id"] for action in linked_actions}
            if len(areas) == 1:
                assert object_record["target_area_id"] == next(iter(areas))
            if len(suites) == 1:
                assert object_record["target_suite_id"] == next(iter(suites))
            if len(modules) == 1:
                assert object_record["target_module_id"] == next(iter(modules))
            else:
                assert object_record["target_module_id"] is None
            continue

        window = windows[object_record["window_id"]]
        assert object_record["target_area_id"] == window["target_area_id"]
        assert object_record["target_suite_id"] == window["target_suite_id"]
        assert object_record["target_module_id"] == window["target_module_id"]


def test_current_window_metadata_files_are_represented_and_gui_owned() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    windows_by_id = _by_id(roadmap["windows"], "window_id")

    for metadata_path in sorted(_GUI_METADATA_WINDOWS_DIR.glob("*.window.toml")):
        result = load_metadata_document(metadata_path)
        assert result.report.has_errors is False
        assert result.document is not None
        document = result.document
        assert document.metadata["owner_area"] == "gui"
        assert document.metadata_id in windows_by_id
        if document.metadata_id == "dummy_metadata_test.window":
            assert windows_by_id[document.metadata_id]["status"] == "explicitly_out_of_scope"
            assert windows_by_id[document.metadata_id]["test_fixture"] is True
        else:
            assert windows_by_id[document.metadata_id]["status"] in _ACTIVE_WINDOW_STATUSES


def test_active_window_toml_actions_widgets_and_tables_are_roadmap_represented() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    windows_by_id = _by_id(roadmap["windows"], "window_id")
    action_ids = set(_by_id(roadmap["actions"], "action_id"))
    represented_object_ids = _object_or_window_ids(roadmap)
    missing: list[str] = []

    for metadata_path in sorted(_GUI_METADATA_WINDOWS_DIR.glob("*.window.toml")):
        result = load_metadata_document(metadata_path)
        assert result.report.has_errors is False
        assert result.document is not None
        document = result.document
        roadmap_window = windows_by_id[document.metadata_id]
        if roadmap_window["status"] not in _ACTIVE_WINDOW_STATUSES:
            continue

        for action in document.actions:
            if action.action_id not in action_ids:
                missing.append(f"{document.metadata_id} action {action.action_id}")
            elif action.action_id not in roadmap_window["action_ids"]:
                missing.append(
                    f"{document.metadata_id} window action {action.action_id}"
                )
        for widget in document.widgets:
            if widget.widget_id not in represented_object_ids:
                missing.append(f"{document.metadata_id} widget {widget.widget_id}")
        for table in document.tables:
            if table.table_id not in represented_object_ids:
                missing.append(f"{document.metadata_id} table {table.table_id}")

    assert missing == []


def test_gui_windows_remain_gui_owned_and_domain_suites_are_targets_only() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    suite_ids = {suite["suite_id"] for suite in roadmap["suites"]}

    for window in roadmap["windows"]:
        assert window["owner_area"] == "gui"
        assert window["owner_area"] not in suite_ids
    for action in roadmap["actions"]:
        assert action["owner_area"] == "gui"
        assert action["owner_area"] not in suite_ids
    for object_record in roadmap["objects"]:
        assert object_record["owner_area"] == "gui"
        assert object_record["owner_area"] not in suite_ids

    ownership_policy = roadmap["ownership_policy"]
    assert ownership_policy["domain_suites_are_targets"] is True
    assert ownership_policy["metadata_does_not_transfer_ownership"] is True
    assert any("must not bypass GUI boundaries" in rule for rule in ownership_policy["ai_agent_rules"])


def test_active_windows_do_not_point_to_missing_metadata_files() -> None:
    roadmap = _load_json(_ROADMAP_PATH)

    for window in roadmap["windows"]:
        metadata_file = window["metadata_file"]
        if window["status"] in _ACTIVE_WINDOW_STATUSES and metadata_file is not None:
            assert (_REPO_ROOT / metadata_file).is_file(), window["window_id"]


def test_download_request_builder_is_not_an_active_v2_window() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    active_windows = [
        window
        for window in roadmap["windows"]
        if window["status"] in _ACTIVE_WINDOW_STATUSES | {"planned_shell", "future_domain"}
    ]

    for window in active_windows:
        assert window.get("class_name") != "DownloadRequestBuilderWindow"
        assert "download_request_builder" not in window["window_id"]
        assert "DownloadRequestBuilderWindow" not in window["display_name"]

    legacy_matches = [
        item
        for item in roadmap["legacy_references"]
        if item["object_id"] == "DownloadRequestBuilderWindow"
    ]
    assert len(legacy_matches) == 1
    assert legacy_matches[0]["status"] == "removed_do_not_resurrect"
    assert legacy_matches[0]["active_v2_object"] is False


def test_ohlcv_maintenance_is_connection_suite_only() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    roadmap_windows = _by_id(roadmap["windows"], "window_id")
    roadmap_actions = _by_id(roadmap["actions"], "action_id")

    ohlcv_window = roadmap_windows["connection.ohlcv_maintenance.window"]
    assert ohlcv_window["target_area_id"] == "connection"
    assert ohlcv_window["target_suite_id"] == "connection_suite"
    assert ohlcv_window["target_module_id"] == "connection.ohlcv_maintenance"

    launch_action = roadmap_actions["main_window.ohlcv_maintenance"]
    assert launch_action["target_area_id"] == "connection"
    assert launch_action["target_suite_id"] == "connection_suite"
    assert launch_action["target_module_id"] == "connection.ohlcv_maintenance"

    ohlcv_targets = [
        item
        for item in (*roadmap["windows"], *roadmap["actions"])
        if item.get("target_module_id") == "connection.ohlcv_maintenance"
    ]
    assert ohlcv_targets
    assert {item["target_suite_id"] for item in ohlcv_targets} == {"connection_suite"}

    for object_record in roadmap["objects"]:
        if object_record["object_id"].startswith("ohlcv_download_"):
            assert object_record["target_area_id"] == "connection"
            assert object_record["target_suite_id"] == "connection_suite"
            assert object_record["target_module_id"] == "connection.ohlcv_maintenance"


def test_ai_agent_metadata_exists_and_defaults_to_no_direct_mutation() -> None:
    roadmap = _load_json(_ROADMAP_PATH)

    for window in roadmap["windows"]:
        if window["status"] in _ACTIVE_WINDOW_STATUSES:
            _assert_ai_agent_metadata(window["ai_agent"])
    for action in roadmap["actions"]:
        if action["status"] in _ACTIVE_WINDOW_STATUSES:
            _assert_ai_agent_metadata(action["ai_agent"])
    for object_record in roadmap["objects"]:
        _assert_ai_agent_metadata(object_record["ai_agent"])

    default_ai_agent = roadmap["ai_agent_usage"]["default_ai_agent"]
    _assert_ai_agent_metadata(default_ai_agent)
    assert default_ai_agent["agent_can_request_open"] is False
    assert default_ai_agent["agent_can_request_click"] is False


def test_ai_agent_direct_mutation_is_denied_for_all_records() -> None:
    roadmap = _load_json(_ROADMAP_PATH)

    for section in ("windows", "actions", "objects"):
        for item in roadmap[section]:
            _assert_ai_agent_metadata(item["ai_agent"])


def test_ai_agent_metadata_distinguishes_shell_only_and_planned_surfaces() -> None:
    roadmap = _load_json(_ROADMAP_PATH)

    for action in roadmap["actions"]:
        if action["status"] == "shell_only":
            assert action["ai_agent"]["agent_can_mutate_directly"] is False
            assert action["runtime_observed"] in {True, False}
            assert action["forbidden_behaviors"]

    for window in roadmap["windows"]:
        if window["status"] in {"planned_shell", "future_domain"}:
            assert window["class_name"] is None
            assert window["ai_agent"]["agent_can_mutate_directly"] is False
            assert window["ai_agent"]["agent_can_request_open"] is False

    for object_record in roadmap["objects"]:
        if object_record["status"] in {"planned_shell", "future_domain"}:
            assert object_record["ai_agent"]["agent_can_mutate_directly"] is False
            assert object_record["ai_agent"]["agent_can_request_click"] is False


def test_ai_clickable_objects_map_to_declared_actions() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    action_ids = set(_by_id(roadmap["actions"], "action_id"))

    for object_record in roadmap["objects"]:
        if not object_record["ai_agent"]["agent_can_request_click"]:
            continue
        linked_action_ids = _linked_action_ids(object_record)
        if not linked_action_ids:
            assert "click_mapping_note" in object_record, object_record["object_id"]
            continue
        assert linked_action_ids <= action_ids, object_record["object_id"]


def test_roadmap_action_ids_align_with_tracked_gui_action_definitions() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    roadmap_actions = _by_id(roadmap["actions"], "action_id")

    for definition in TRACKED_GUI_ACTION_DEFINITIONS:
        assert definition.action_id in roadmap_actions
        roadmap_action = roadmap_actions[definition.action_id]
        assert roadmap_action["display_label"] == definition.label
        if definition.window_id is not None:
            assert roadmap_action["window_id"] == definition.window_id
        assert roadmap_action["runtime_observed"] is True


def test_runtime_manager_roadmap_entry_is_generic_and_read_only() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    windows = _by_id(roadmap["windows"], "window_id")
    actions = _by_id(roadmap["actions"], "action_id")
    runtime_window = windows["runtime_manager.window"]

    assert runtime_window["target_area_id"] == "runtime"
    assert runtime_window["target_suite_id"] == "gui_service"
    assert "runtime_mutation" in runtime_window["forbidden_behaviors"]
    assert "domain_execution" in runtime_window["forbidden_behaviors"]
    assert "object_map_mutation" in runtime_window["forbidden_behaviors"]

    for action_id in runtime_window["action_ids"]:
        action = actions[action_id]
        assert action["target_suite_id"] == "gui_service"
        assert "domain_execution" in action["forbidden_behaviors"]


def test_missing_corrective_dialog_actions_are_shell_only_and_non_executing() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    actions = _by_id(roadmap["actions"], "action_id")
    expected_action_ids = {
        "ohlcv_download_preflight.cancel",
        "ohlcv_download_preflight.start_download",
        "ohlcv_download_task.stop",
        "ohlcv_download_task.ok",
    }

    for action_id in expected_action_ids:
        action = actions[action_id]
        assert action["owner_area"] == "gui"
        assert action["target_area_id"] == "connection"
        assert action["target_suite_id"] == "connection_suite"
        assert action["target_module_id"] == "connection.ohlcv_maintenance"
        assert action["status"] == "shell_only"
        assert action["runtime_observed"] is False
        assert "download_execution" in action["forbidden_behaviors"]
        assert "provider_api_call" in action["forbidden_behaviors"]
        assert "network_call" in action["forbidden_behaviors"]
        assert "storage_write" in action["forbidden_behaviors"]


def test_implemented_gui_source_ids_are_represented_in_roadmap() -> None:
    roadmap = _load_json(_ROADMAP_PATH)
    represented_ids = _object_or_window_ids(roadmap)
    represented_ids.update(_by_id(roadmap["actions"], "action_id"))

    source_ids = _literal_stable_gui_source_ids() - _EXCLUDED_STABLE_GUI_SOURCE_IDS
    required_ids = source_ids | set(_EXPECTED_IMPLEMENTED_GUI_SOURCE_IDS)
    missing_ids = sorted(required_ids - represented_ids)

    assert missing_ids == []


def test_static_forbidden_active_gui_source_scans_pass() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((_REPO_ROOT / "src" / "leonardo" / "gui").rglob("*.py"))
    )

    assert "DownloadRequestBuilderWindow" not in source_text
    assert "leonardo.download_data" not in source_text
    forbidden_import_patterns = (
        r"from leonardo\.download_data\b",
        r"import leonardo\.download_data\b",
        r"from leonardo\.data\b",
        r"import leonardo\.data\b",
        r"from leonardo\.providers?\b",
        r"import leonardo\.providers?\b",
        r"from leonardo\.storage\b",
        r"import leonardo\.storage\b",
        r"from leonardo\.charts?\b",
        r"import leonardo\.charts?\b",
        r"from leonardo\.trading\b",
        r"import leonardo\.trading\b",
        r"from .*DownloadExecutionManager",
        r"import .*DownloadExecutionManager",
    )
    for pattern in forbidden_import_patterns:
        assert re.search(pattern, source_text) is None, pattern


def test_dummy_display_data_remains_gui_local_and_in_memory() -> None:
    dummy_source = (_REPO_ROOT / "src" / "leonardo" / "gui" / "dummy_data.py").read_text(
        encoding="utf-8"
    )

    assert "GUI-only dummy data" in dummy_source
    assert "provider truth" in dummy_source
    assert "Path(" not in dummy_source
    assert "open(" not in dummy_source
    assert "requests" not in dummy_source
    assert "aiohttp" not in dummy_source


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _by_id(items: Iterable[Mapping[str, object]], field_name: str) -> dict[str, Mapping[str, object]]:
    return {str(item[field_name]): item for item in items}


def _object_or_window_ids(roadmap: Mapping[str, object]) -> set[object]:
    windows = roadmap["windows"]
    objects = roadmap["objects"]
    assert isinstance(windows, list)
    assert isinstance(objects, list)
    return {
        item["object_id"]
        for item in (*windows, *objects)
        if isinstance(item, Mapping)
    }


def _linked_action_ids(object_record: Mapping[str, object]) -> set[object]:
    if "linked_action_id" in object_record:
        return {object_record["linked_action_id"]}
    if "linked_action_ids" in object_record:
        linked_action_ids = object_record["linked_action_ids"]
        assert isinstance(linked_action_ids, list)
        return set(linked_action_ids)
    return set()


def _assert_unique_ids(items: Iterable[Mapping[str, object]], field_name: str) -> None:
    values = [item[field_name] for item in items]
    assert len(values) == len(set(values))


def _assert_ai_agent_metadata(ai_agent: Mapping[str, object]) -> None:
    assert _AI_AGENT_FIELDS <= set(ai_agent)
    assert ai_agent["agent_can_mutate_directly"] is False
    assert isinstance(ai_agent["notes"], list)


def _literal_stable_gui_source_ids() -> set[object]:
    source_ids: set[object] = set()
    for path in _GUI_ROADMAP_STABLE_SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            source_ids.update(_stable_ids_from_call(node))
    return source_ids


def _stable_ids_from_call(node: ast.Call) -> set[object]:
    source_ids: set[object] = set()
    function_name = _call_function_name(node)

    if function_name == "setObjectName":
        source_ids.update(_stable_id_from_arg(node, 0))
    elif function_name == "setProperty":
        property_name = _constant_string_arg(node, 0)
        if property_name in {"object_id", "action_id"}:
            source_ids.update(_stable_id_from_arg(node, 1))
    elif function_name == "apply_trace":
        source_ids.update(_stable_id_from_arg(node, 1))
    elif function_name == "configure_table":
        source_ids.update(_stable_id_from_keyword(node, "object_id"))

    for keyword_name in ("object_id", "parent_object_id", "action_id"):
        source_ids.update(_stable_id_from_keyword(node, keyword_name))
    return source_ids


def _call_function_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


def _stable_id_from_arg(node: ast.Call, index: int) -> set[object]:
    if index >= len(node.args):
        return set()
    value = _constant_string(node.args[index])
    return {value} if value is not None and _ID_PATTERN.fullmatch(value) else set()


def _stable_id_from_keyword(node: ast.Call, keyword_name: str) -> set[object]:
    for keyword in node.keywords:
        if keyword.arg != keyword_name:
            continue
        value = _constant_string(keyword.value)
        return {value} if value is not None and _ID_PATTERN.fullmatch(value) else set()
    return set()


def _constant_string_arg(node: ast.Call, index: int) -> str | None:
    if index >= len(node.args):
        return None
    return _constant_string(node.args[index])


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
