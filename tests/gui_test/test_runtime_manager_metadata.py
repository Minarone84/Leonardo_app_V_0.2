from collections.abc import Mapping
from pathlib import Path
import tomllib

from leonardo.gui.metadata import (
    FORBIDDEN_EXECUTABLE_FIELD_NAMES,
    GuiMetadataOverrideDocument,
    GuiMetadataResolver,
    ResolvedValueSource,
    load_metadata_document,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_MANAGER_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "runtime_manager.window.toml"
)
_REQUIRED_REGIONS = {"header", "toolbar", "body", "status_area", "footer"}
_REQUIRED_ACTIONS = {
    "runtime_manager.refresh_snapshot",
    "runtime_manager.copy_snapshot_summary",
    "runtime_manager.close",
}
_REQUIRED_TABLES = {
    "runtime_manager.summary_table",
    "runtime_manager.services_table",
    "runtime_manager.tasks_table",
    "runtime_manager.processes_table",
    "runtime_manager.connections_table",
    "runtime_manager.windows_table",
    "runtime_manager.actions_table",
    "runtime_manager.operations_table",
    "runtime_manager.downloads_table",
    "runtime_manager.audit_preview_table",
}
_REQUIRED_TABLE_COLUMNS = {
    "runtime_manager.summary_table": {"section", "status", "count", "details"},
    "runtime_manager.services_table": {"service", "status", "details"},
    "runtime_manager.tasks_table": {"task", "status", "started_at", "details"},
    "runtime_manager.downloads_table": {"metric", "value", "details"},
    "runtime_manager.audit_preview_table": {
        "timestamp",
        "severity",
        "event_type",
        "message",
        "event_id",
        "category",
        "actor_id",
        "session_id",
        "window_id",
        "action_id",
        "operation_id",
        "task_id",
        "correlation_id",
    },
}
_UNSAFE_SETTING_PATH_PREFIXES = (
    "identity.",
    "metadata.",
    "actions.",
    "regions.",
    "widgets.",
    "tables.",
    "reports.",
)
_UNSAFE_SETTING_PATH_PARTS = {
    "service_id",
    "task_id",
    "process_id",
    "connection_id",
    "action_id",
    "widget_id",
    "table_id",
    "schema_version",
}


def test_runtime_manager_metadata_loads_and_validates() -> None:
    result = load_metadata_document(_RUNTIME_MANAGER_METADATA_PATH)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == "runtime_manager.window"
    assert result.document.kind.value == "window"
    assert result.document.title == "Runtime Manager"


def test_runtime_manager_metadata_resolves_effective_profile() -> None:
    document = _load_runtime_manager_document()
    profile = GuiMetadataResolver().resolve(document)

    assert profile.report.has_errors is False
    assert profile.metadata_id == "runtime_manager.window"
    assert profile.values["identity"]["title"] == "Runtime Manager"
    assert profile.values["geometry"]["width"] == 1440
    assert profile.values["style"]["font_size"] == 14


def test_runtime_manager_identity_is_discoverable() -> None:
    document = _load_runtime_manager_document()

    assert document.metadata["contract_id"] == "runtime_manager.window"
    assert document.metadata["logical_kind"] == "read_only_runtime_inspection"
    assert document.metadata["owner_area"] == "runtime"
    assert document.metadata["window_id"] == "runtime_manager.window"
    assert document.metadata["instance_policy"] == "singleton"
    assert document.metadata["geometry_policy"]["start_mode"] == "maximized"
    assert document.metadata["style_tokens"]["theme_role"] == "diagnostic"


def test_runtime_manager_required_regions_exist() -> None:
    document = _load_runtime_manager_document()

    assert _REQUIRED_REGIONS == {region.region_id for region in document.regions}


def test_runtime_manager_required_actions_exist() -> None:
    document = _load_runtime_manager_document()
    action_ids = {action.action_id for action in document.actions}

    assert _REQUIRED_ACTIONS <= action_ids
    assert "runtime_manager.export_snapshot" in action_ids
    assert "runtime_manager.open_details" in action_ids


def test_runtime_manager_required_tables_and_columns_exist() -> None:
    document = _load_runtime_manager_document()
    tables = {table.table_id: table for table in document.tables}

    assert _REQUIRED_TABLES == set(tables)
    for table_id, required_columns in _REQUIRED_TABLE_COLUMNS.items():
        assert required_columns == {
            column.column_id
            for column in tables[table_id].columns
        }


def test_runtime_manager_snapshot_report_exists() -> None:
    document = _load_runtime_manager_document()
    reports = {report.report_id: report for report in document.reports}
    report = reports["runtime_manager.snapshot_report"]

    assert {
        "summary",
        "services",
        "tasks",
        "downloads",
        "audit_preview",
        "diagnostics",
    } == {section.section_id for section in report.sections}


def test_runtime_manager_settings_exposure_contains_only_safe_paths() -> None:
    document = _load_runtime_manager_document()
    profile = GuiMetadataResolver().resolve(document)
    setting_paths = {setting.path for setting in document.settings}

    assert setting_paths == {"style.font_size", "style.density"}
    for path in setting_paths:
        assert profile.trace_for(path).source is ResolvedValueSource.METADATA_DEFAULT
        assert not path.startswith(_UNSAFE_SETTING_PATH_PREFIXES)
        assert not set(path.split(".")) & _UNSAFE_SETTING_PATH_PARTS


def test_runtime_manager_runtime_state_fields_are_not_exposed() -> None:
    document = _load_runtime_manager_document()
    setting_paths = {setting.path for setting in document.settings}
    forbidden_fragments = {
        "service",
        "task",
        "process",
        "connection",
        "action",
        "widget",
        "table",
        "schema_version",
    }

    for path in setting_paths:
        assert not set(path.split(".")) & forbidden_fragments


def test_runtime_manager_override_merge_and_reset_for_exposed_setting() -> None:
    document = _load_runtime_manager_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 12},
    )

    overridden = resolver.resolve(document, overrides)
    reset = resolver.reset_field(overrides, "style.font_size")
    restored = resolver.resolve(document, reset)

    assert overridden.values["style"]["font_size"] == 12
    assert resolver.explain(overridden, "style.font_size").source is (
        ResolvedValueSource.USER_OVERRIDE
    )
    assert "style.font_size" not in reset.values
    assert restored.values["style"]["font_size"] == 14
    assert resolver.explain(restored, "style.font_size").source is (
        ResolvedValueSource.METADATA_DEFAULT
    )


def test_runtime_manager_metadata_has_no_executable_metadata_fields() -> None:
    raw_data = _load_raw_metadata()

    assert _forbidden_keys_in(raw_data) == set()


def test_runtime_manager_metadata_loading_uses_no_view_runtime() -> None:
    result = load_metadata_document(_RUNTIME_MANAGER_METADATA_PATH)
    assert result.document is not None

    profile = GuiMetadataResolver().resolve(result.document)

    assert profile.report.has_errors is False
    assert profile.values["identity"]["metadata_id"] == "runtime_manager.window"


def _load_runtime_manager_document():
    result = load_metadata_document(_RUNTIME_MANAGER_METADATA_PATH)
    assert result.document is not None
    assert result.report.has_errors is False
    return result.document


def _load_raw_metadata() -> Mapping[str, object]:
    with _RUNTIME_MANAGER_METADATA_PATH.open("rb") as source_file:
        return tomllib.load(source_file)


def _forbidden_keys_in(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in FORBIDDEN_EXECUTABLE_FIELD_NAMES:
                found.add(key_text)
            found.update(_forbidden_keys_in(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys_in(item))
    return found
