from pathlib import Path

import pytest

from leonardo.contracts.downloads import CONNECTION_DOWNLOAD_MANAGER_OWNER_DOMAIN
from leonardo.contracts.object_family_legends import (
    CURRENT_V2_FAMILY_IDS,
    FUTURE_PLACEHOLDER_FAMILY_IDS,
)
from leonardo.contracts.object_relationships import (
    CURRENT_RELATIONSHIP_TYPES,
    FUTURE_PLACEHOLDER_RELATIONSHIP_TYPES,
    OBJECT_RELATIONSHIP_DEFINITIONS,
    ObjectRelationshipDefinition,
    all_object_relationship_definitions,
    object_relationship_definitions_by_type,
    object_relationship_definitions_for_source,
    object_relationship_definitions_for_target,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_RELATIONSHIPS_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "object_relationships.py"
)


def test_relationship_definition_requires_type_source_and_target() -> None:
    with pytest.raises(ValueError, match="relationship_type"):
        ObjectRelationshipDefinition(
            relationship_type="",
            source_object_kind="action",
            target_object_kind="operation",
            owner_domain="core.runtime",
            owner_component="OperationRegistry",
        )

    with pytest.raises(ValueError, match="source_object_kind"):
        ObjectRelationshipDefinition(
            relationship_type="triggers",
            source_object_kind=" ",
            target_object_kind="operation",
            owner_domain="core.runtime",
            owner_component="OperationRegistry",
        )

    with pytest.raises(ValueError, match="target_object_kind"):
        ObjectRelationshipDefinition(
            relationship_type="triggers",
            source_object_kind="action",
            target_object_kind="",
            owner_domain="core.runtime",
            owner_component="OperationRegistry",
        )


def test_relationship_definition_rejects_unknown_direction_status_or_family() -> None:
    with pytest.raises(ValueError, match="direction"):
        _definition(direction="sideways")

    with pytest.raises(ValueError, match="status"):
        _definition(status="experimental")

    with pytest.raises(ValueError, match="source_family_id"):
        _definition(source_family_id="missing_family")


def test_relationship_definition_round_trips_to_dict() -> None:
    definition = ObjectRelationshipDefinition(
        relationship_type="custom_link",
        source_object_kind="action",
        target_object_kind="operation",
        owner_domain="core.runtime",
        owner_component="OperationRegistry",
        source_family_id="action",
        target_family_id="operation",
        direction="causal",
        lifecycle_statuses=("active", "completed"),
        required_metadata_fields=("operation_id",),
        optional_metadata_fields=("action_id",),
        read_provider="RuntimeManagerBackend snapshots",
        mutation_owner="OperationRegistry",
        audit_event_types=("operation.created",),
        permission_refs=("runtime:view",),
        related_contracts=("contract.module.Type",),
        related_docs=("docs/contracts_docs/example.md",),
        related_tests=("tests/contracts_test/test_example.py",),
        extra={"nested": {"value": "kept"}, "flags": ["a", "b"]},
    )

    loaded = ObjectRelationshipDefinition.from_dict(definition.to_dict())

    assert loaded == definition
    assert loaded.extra["nested"]["value"] == "kept"
    assert loaded.extra["flags"] == ("a", "b")


def test_current_core_runtime_relationship_descriptors_exist() -> None:
    expected = {
        "triggers",
        "creates_operation",
        "schedules_task",
        "reports_progress",
        "produces_result",
        "fails_with",
        "cancelled_by",
        "records_audit",
        "described_by_contract",
        "has_permission",
    }

    assert expected <= _relationship_types()
    assert set(CURRENT_RELATIONSHIP_TYPES) <= _relationship_types()


def test_connection_and_window_relationship_descriptors_exist() -> None:
    expected = {
        "uses_connection",
        "owns_channel",
        "owns_subscription",
        "records_message",
        "opens_window",
        "contains_action",
    }

    assert expected <= _relationship_types()
    assert _single("owns_channel").source_object_kind == "connection"
    assert _single("opens_window").source_object_kind == "action"
    assert _single("contains_action").source_object_kind == "window"


def test_download_read_model_relationships_are_non_executing() -> None:
    for relationship_type in (
        "creates_item",
        "creates_plan",
        "classified_by",
        "requires_capability",
    ):
        definitions = object_relationship_definitions_by_type(relationship_type)
        assert definitions
        for definition in definitions:
            assert definition.owner_domain == CONNECTION_DOWNLOAD_MANAGER_OWNER_DOMAIN
            assert definition.owner_domain not in {"gui", "core", "download.core"}
            assert definition.extra["read_model_only"] is True
            assert "execution" in definition.extra["forbidden_behavior"]
            assert "adapters" in definition.extra["forbidden_behavior"]
            assert "storage_writers" in definition.extra["forbidden_behavior"]


def test_download_relationships_use_connection_owned_component_names() -> None:
    deleted_components = {"DownloadManager", "DownloadExecutionManager"}

    for relationship_type in (
        "creates_item",
        "creates_plan",
        "classified_by",
        "requires_capability",
    ):
        for definition in object_relationship_definitions_by_type(relationship_type):
            assert definition.owner_component not in deleted_components
            assert definition.mutation_owner == "ConnectionDownloadManager"
            assert "ConnectionDownload" in definition.owner_component


def test_future_relationship_descriptors_are_planned_placeholders() -> None:
    for relationship_type in FUTURE_PLACEHOLDER_RELATIONSHIP_TYPES:
        definitions = object_relationship_definitions_by_type(relationship_type)
        assert definitions
        for definition in definitions:
            assert definition.status == "planned"
            assert definition.extra["placeholder"] is True
            assert definition.extra["implementation_not_started"] is True


def test_helpers_are_read_only_and_deterministic() -> None:
    definitions = all_object_relationship_definitions()

    assert definitions is OBJECT_RELATIONSHIP_DEFINITIONS
    assert object_relationship_definitions_by_type("missing") == ()
    assert object_relationship_definitions_for_source("missing") == ()
    assert object_relationship_definitions_for_target("missing") == ()
    assert object_relationship_definitions_by_type("triggers")[0] is _single("triggers")
    assert _single("triggers") in object_relationship_definitions_for_source("action")
    assert _single("triggers") in object_relationship_definitions_for_target("operation")
    assert tuple(dict.fromkeys(definition.relationship_type for definition in definitions))

    with pytest.raises(ValueError, match="relationship_type"):
        object_relationship_definitions_by_type("")
    with pytest.raises(ValueError, match="object_kind"):
        object_relationship_definitions_for_source(" ")
    with pytest.raises(ValueError, match="object_kind"):
        object_relationship_definitions_for_target("")


def test_definitions_reference_existing_family_ids_where_declared() -> None:
    family_ids = set(CURRENT_V2_FAMILY_IDS + FUTURE_PLACEHOLDER_FAMILY_IDS)

    for definition in all_object_relationship_definitions():
        if definition.source_family_id is not None:
            assert definition.source_family_id in family_ids
        if definition.target_family_id is not None:
            assert definition.target_family_id in family_ids


def test_all_definitions_round_trip_through_dicts() -> None:
    for definition in all_object_relationship_definitions():
        loaded = ObjectRelationshipDefinition.from_dict(definition.to_dict())
        assert loaded == definition


def test_relationship_module_imports_no_gui_runtime_or_domain_services() -> None:
    source = _RELATIONSHIPS_CONTRACT.read_text(encoding="utf-8")
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
        "from leonardo." + "data",
        "from leonardo." + "adapters",
    )

    for blocked_import in blocked_imports:
        assert blocked_import not in source


def test_relationship_module_is_static_descriptor_only() -> None:
    source = _RELATIONSHIPS_CONTRACT.read_text(encoding="utf-8")
    blocked_tokens = (
        "ObjectMapProvider",
        "class ObjectMap",
        "register_provider",
        "def discover",
        ".discover",
        "discover(",
        "StateStore(",
        "AuditLog(",
        "RuntimeManagerBackend(",
        "DownloadManager(",
        "DownloadExecutionManager(",
        "QApplication",
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


def test_relationship_module_does_not_implement_object_map_provider() -> None:
    source = _RELATIONSHIPS_CONTRACT.read_text(encoding="utf-8")

    assert "ObjectMapProvider" not in source
    assert "class ObjectMap" not in source
    assert "object_map_provider" not in source


def _definition(
    *,
    direction: str = "forward",
    status: str = "current",
    source_family_id: str | None = "action",
) -> ObjectRelationshipDefinition:
    return ObjectRelationshipDefinition(
        relationship_type="triggers",
        source_object_kind="action",
        target_object_kind="operation",
        owner_domain="core.runtime",
        owner_component="OperationRegistry",
        direction=direction,
        source_family_id=source_family_id,
        status=status,
    )


def _relationship_types() -> set[str]:
    return {
        definition.relationship_type
        for definition in all_object_relationship_definitions()
    }


def _single(relationship_type: str) -> ObjectRelationshipDefinition:
    definitions = object_relationship_definitions_by_type(relationship_type)
    assert definitions
    return definitions[0]
