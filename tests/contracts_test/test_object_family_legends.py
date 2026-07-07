from pathlib import Path

import pytest

from leonardo.contracts.object_family_legends import (
    CURRENT_V2_FAMILY_IDS,
    FUTURE_PLACEHOLDER_FAMILY_IDS,
    OBJECT_FAMILY_LEGENDS,
    all_object_family_legends,
    object_family_legend_by_id,
    object_family_legend_by_kind,
)
from leonardo.contracts.traceable_object import ObjectFamilyLegend


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGENDS_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "object_family_legends.py"
)


def test_current_v2_mandatory_family_legends_exist() -> None:
    legend_ids = {legend.family_id for legend in all_object_family_legends()}

    assert set(CURRENT_V2_FAMILY_IDS) <= legend_ids
    assert {
        "app_runtime",
        "session",
        "service",
        "task",
        "operation",
        "process",
        "connection",
        "websocket_channel",
        "window",
        "action",
        "contract_descriptor",
        "audit_event",
        "error_report",
        "download_request",
        "download_preflight",
        "download_item",
        "download_execution_snapshot",
        "download_capability",
    } <= legend_ids


def test_each_legend_has_required_identity_and_owner_fields() -> None:
    for legend in all_object_family_legends():
        assert legend.family_id
        assert legend.object_kind
        assert legend.owner_domain
        assert legend.owner_component
        assert legend.mutation_owner
        assert legend.read_provider
        assert legend.required_identity_fields


def test_window_legend_declares_window_identity_fields() -> None:
    legend = _legend("window")

    assert legend.owner_domain == "gui"
    assert legend.owner_component == "GUI metadata and WindowRegistry"
    assert {"window_id", "metadata_id", "object_name"} <= set(
        legend.required_identity_fields
    )
    assert "affected_by_settings" in legend.relationships_out
    assert "domain_execution" in legend.extra["forbidden_behavior"]


def test_action_legend_declares_action_identity_and_permissions() -> None:
    legend = _legend("action")

    assert legend.owner_component == "ActionRegistry and GuiActionObserver"
    assert {"action_id", "window_id"} <= set(legend.required_identity_fields)
    assert "triggers" in legend.relationships_out
    assert "creates_operation" in legend.relationships_out
    assert "runtime:view" in legend.permission_refs


def test_operation_legend_references_operation_registry_and_identity() -> None:
    legend = _legend("operation")

    assert legend.owner_component == "OperationRegistry"
    assert legend.required_identity_fields == ("operation_id",)
    assert "schedules_task" in legend.relationships_out


def test_task_legend_references_task_manager_and_identity() -> None:
    legend = _legend("task")

    assert legend.owner_component == "TaskManager"
    assert legend.required_identity_fields == ("task_id",)
    assert "active" in legend.lifecycle_statuses
    assert "cancelled" in legend.lifecycle_statuses


def test_connection_legend_references_connection_registry_and_identity() -> None:
    legend = _legend("connection")

    assert legend.owner_component == "ConnectionRegistry"
    assert legend.required_identity_fields == ("connection_id",)
    assert "owns_channel" in legend.relationships_out
    assert "provider_client_implementation" in legend.extra["forbidden_behavior"]


def test_websocket_channel_legend_references_channel_and_connection_identity() -> None:
    legend = _legend("websocket_channel")

    assert legend.owner_component == "ConnectionRegistry"
    assert {"channel_id", "connection_id"} <= set(legend.required_identity_fields)
    assert "owns_channel" in legend.relationships_in
    assert "message_transport" in legend.extra["forbidden_behavior"]


def test_download_family_legends_are_read_model_only() -> None:
    for family_id in (
        "download_request",
        "download_preflight",
        "download_item",
        "download_execution_snapshot",
        "download_capability",
    ):
        legend = _legend(family_id)
        assert legend.owner_domain == "download.core"
        assert legend.extra["read_model_only"] is True
        assert "execution" in legend.extra["forbidden_behavior"]
        assert "adapters" in legend.extra["forbidden_behavior"]
        assert "storage_writers" in legend.extra["forbidden_behavior"]


def test_artifact_recipe_saved_artifact_and_metadata_are_distinct_placeholders() -> None:
    recipe = _legend("artifact_recipe")
    artifact = _legend("saved_artifact")
    metadata = _legend("artifact_metadata")

    assert recipe.owner_domain == "data_manager"
    assert artifact.owner_domain == "data_manager"
    assert metadata.owner_domain == "data_manager"
    assert recipe.family_id != artifact.family_id != metadata.family_id
    assert recipe.required_identity_fields == ("recipe_id",)
    assert artifact.required_identity_fields == ("artifact_id",)
    assert metadata.required_identity_fields == ("artifact_metadata_id", "artifact_id")
    assert recipe.extra["placeholder"] is True
    assert artifact.extra["implementation_not_started"] is True


def test_study_and_study_environment_are_distinct_future_legends() -> None:
    study = _legend("study")
    environment = _legend("study_environment")

    assert study.owner_domain == "research"
    assert environment.owner_domain == "research"
    assert study.required_identity_fields == ("study_id",)
    assert environment.required_identity_fields == ("study_environment_id",)
    assert "study_refs" in environment.metadata_fields


def test_trading_signal_and_strategy_are_placeholders_only() -> None:
    signal = _legend("trading_signal")
    strategy = _legend("trading_strategy")

    assert signal.owner_domain == "trading"
    assert strategy.owner_domain == "trading"
    assert signal.extra["placeholder"] is True
    assert strategy.extra["implementation_not_started"] is True
    assert signal.permission_refs == ("trading:view",)
    assert strategy.permission_refs == ("trading:view",)


def test_helper_functions_are_read_only_and_deterministic() -> None:
    legends = all_object_family_legends()

    assert legends is OBJECT_FAMILY_LEGENDS
    assert object_family_legend_by_id("window") is _legend("window")
    assert object_family_legend_by_kind("window") is _legend("window")
    assert object_family_legend_by_id("missing") is None
    assert object_family_legend_by_kind("missing") is None
    assert tuple(legend.family_id for legend in legends) == (
        CURRENT_V2_FAMILY_IDS + FUTURE_PLACEHOLDER_FAMILY_IDS
    )
    with pytest.raises(ValueError, match="family_id"):
        object_family_legend_by_id("")
    with pytest.raises(ValueError, match="object_kind"):
        object_family_legend_by_kind(" ")


def test_all_legends_round_trip_through_object_family_legend_dicts() -> None:
    for legend in all_object_family_legends():
        loaded = ObjectFamilyLegend.from_dict(legend.to_dict())
        assert loaded == legend


def test_legend_module_imports_no_gui_core_runtime_or_domain_services() -> None:
    source = _LEGENDS_CONTRACT.read_text(encoding="utf-8")
    blocked_imports = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "from leonardo." + "gui",
        "import leonardo." + "gui",
        "PySide6",
        "PyQt6",
        "QtWidgets",
        "QtCore",
        "QtGui",
    )

    for blocked_import in blocked_imports:
        assert blocked_import not in source


def test_legend_module_is_static_descriptor_only() -> None:
    source = _LEGENDS_CONTRACT.read_text(encoding="utf-8")
    blocked_tokens = (
        "ObjectMapProvider",
        "class ObjectMap",
        "register_provider",
        "def discover",
        ".discover",
        "discover(",
        "StateStore(",
        "AuditLog(",
        "DownloadManager(",
        "RuntimeManagerBackend(",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket.",
        "sub" + "process",
        "shell" + "=True",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
    )

    for token in blocked_tokens:
        assert token not in source


def _legend(family_id: str):
    legend = object_family_legend_by_id(family_id)
    assert legend is not None
    return legend
