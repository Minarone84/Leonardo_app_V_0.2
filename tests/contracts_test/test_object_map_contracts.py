from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.object_family_legends import object_family_legend_by_id
from leonardo.contracts.object_map import (
    ObjectMapProviderDescriptor,
    ObjectMapQuery,
    ObjectMapQueryReport,
    ObjectMapSection,
    ObjectMapSnapshot,
)
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.traceable_object import (
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OBJECT_MAP_CONTRACT = _REPO_ROOT / "src" / "leonardo" / "contracts" / "object_map.py"


def test_provider_descriptor_validates_provider_id_and_owner_domain() -> None:
    with pytest.raises(ValueError, match="provider_id"):
        _provider(provider_id="")

    with pytest.raises(ValueError, match="owner_domain"):
        _provider(owner_domain=" ")

    with pytest.raises(ValueError, match="object_kinds or family_ids"):
        ObjectMapProviderDescriptor(
            provider_id="empty-scope",
            owner_domain="core.runtime",
            owner_component="RuntimeManagerBackend",
        )


def test_provider_descriptor_defaults_to_read_only_and_mutation_forbidden() -> None:
    descriptor = _provider()

    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True

    with pytest.raises(ValueError, match="read_only"):
        _provider(read_only=False)
    with pytest.raises(ValueError, match="mutation_forbidden"):
        _provider(mutation_forbidden=False)


def test_provider_descriptor_round_trips_to_dict() -> None:
    descriptor = _provider(
        provider_name="Core Runtime",
        relationship_types=("triggers", "creates_operation"),
        metadata={"nested": {"scope": "runtime"}},
        extra={"flags": ["read", "only"]},
    )

    loaded = ObjectMapProviderDescriptor.from_dict(descriptor.to_dict())

    assert loaded == descriptor
    assert loaded.metadata["nested"]["scope"] == "runtime"
    assert loaded.extra["flags"] == ("read", "only")


def test_section_validates_section_id_and_provider_id() -> None:
    with pytest.raises(ValueError, match="section_id"):
        _section(section_id="")

    with pytest.raises(ValueError, match="provider_id"):
        _section(provider_id=" ")


def test_section_normalizes_summaries_from_mappings_or_instances() -> None:
    summary = _summary()
    section = _section(summaries=(summary, summary.to_dict()))

    assert section.summaries == (summary, summary)


def test_section_normalizes_relationships_from_mappings_or_instances() -> None:
    relationship = _relationship()
    section = _section(relationships=(relationship, relationship.to_dict()))

    assert section.relationships == (relationship, relationship)


def test_section_normalizes_legends_from_mappings_or_instances() -> None:
    legend = _legend()
    section = _section(legends=(legend, legend.to_dict()))

    assert section.legends == (legend, legend)


def test_section_normalizes_relationship_definitions_from_mappings_or_instances() -> None:
    definition = _relationship_definition()
    section = _section(
        relationship_definitions=(definition, definition.to_dict()),
    )

    assert section.relationship_definitions == (definition, definition)


def test_snapshot_validates_snapshot_id() -> None:
    with pytest.raises(ValueError, match="snapshot_id"):
        ObjectMapSnapshot(snapshot_id="")


def test_snapshot_normalizes_sections_and_provider_descriptors() -> None:
    section = _section()
    descriptor = _provider()
    snapshot = ObjectMapSnapshot(
        snapshot_id="snapshot-1",
        sections=(section, section.to_dict()),
        provider_descriptors=(descriptor, descriptor.to_dict()),
        metadata={"source": ["test"]},
    )

    assert snapshot.sections == (section, section)
    assert snapshot.provider_descriptors == (descriptor, descriptor)
    assert snapshot.metadata["source"] == ("test",)
    assert ObjectMapSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_query_supports_broad_read_only_queries_without_mutation_fields() -> None:
    query = ObjectMapQuery()

    assert query.object_kind is None
    assert query.include_summaries is True
    assert query.include_relationships is True
    assert query.include_legends is True
    assert query.include_relationship_definitions is True
    assert query.include_provider_descriptors is True
    assert set(query.to_dict()) == {
        "object_kind",
        "family_id",
        "object_id",
        "owner_domain",
        "provider_id",
        "relationship_type",
        "include_summaries",
        "include_relationships",
        "include_legends",
        "include_relationship_definitions",
        "include_provider_descriptors",
        "include_docs",
        "include_tests",
        "metadata",
    }
    assert ObjectMapQuery.from_dict(query.to_dict()) == query


def test_query_report_carries_all_read_only_sections_and_descriptors() -> None:
    query = ObjectMapQuery(object_kind="action")
    section = _section()
    summary = _summary()
    relationship = _relationship()
    legend = _legend()
    definition = _relationship_definition()
    descriptor = _provider()
    report = ObjectMapQueryReport(
        query=query,
        sections=(section, section.to_dict()),
        summaries=(summary, summary.to_dict()),
        relationships=(relationship, relationship.to_dict()),
        legends=(legend, legend.to_dict()),
        relationship_definitions=(definition, definition.to_dict()),
        provider_descriptors=(descriptor, descriptor.to_dict()),
        warnings=("read-only",),
        blockers=("provider-not-implemented",),
        errors=("none",),
        metadata={"query": {"kind": "action"}},
        extra={"flags": ["contract"]},
    )

    assert report.query == query
    assert report.sections == (section, section)
    assert report.summaries == (summary, summary)
    assert report.relationships == (relationship, relationship)
    assert report.legends == (legend, legend)
    assert report.relationship_definitions == (definition, definition)
    assert report.provider_descriptors == (descriptor, descriptor)
    assert report.metadata["query"]["kind"] == "action"
    assert report.extra["flags"] == ("contract",)
    assert ObjectMapQueryReport.from_dict(report.to_dict()) == report


def test_metadata_and_extra_fields_are_preserved_immutably() -> None:
    section = _section(
        metadata={"nested": {"value": "kept"}},
        extra={"items": ["a", "b"]},
    )

    assert section.metadata["nested"]["value"] == "kept"
    assert section.extra["items"] == ("a", "b")
    with pytest.raises(TypeError):
        section.metadata["new"] = "blocked"
    with pytest.raises(TypeError):
        section.extra["items"][0] = "blocked"


def test_contracts_are_frozen_read_only_and_generic() -> None:
    descriptor = _provider()

    with pytest.raises(FrozenInstanceError):
        descriptor.provider_id = "changed"
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert not hasattr(descriptor, "start")
    assert not hasattr(descriptor, "stop")
    assert not hasattr(descriptor, "execute")


def test_object_map_module_does_not_implement_live_provider_or_wiring() -> None:
    source = _OBJECT_MAP_CONTRACT.read_text(encoding="utf-8")
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
    blocked_tokens = (
        "ObjectMapReadOnlyProvider",
        "class ObjectMapService",
        "class ObjectMapRegistry",
        "register_provider",
        "def discover",
        ".discover",
        "discover(",
        "def provider_descriptor",
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

    for blocked_import in blocked_imports:
        assert blocked_import not in source
    for token in blocked_tokens:
        assert token not in source


def _provider(
    *,
    provider_id: str = "core-runtime-provider",
    provider_name: str | None = None,
    owner_domain: str = "core.runtime",
    owner_component: str = "RuntimeManagerBackend",
    object_kinds: tuple[str, ...] = ("action", "operation"),
    family_ids: tuple[str, ...] = ("action", "operation"),
    relationship_types: tuple[str, ...] = ("triggers",),
    read_only: bool = True,
    mutation_forbidden: bool = True,
    metadata: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
) -> ObjectMapProviderDescriptor:
    return ObjectMapProviderDescriptor(
        provider_id=provider_id,
        provider_name=provider_name,
        owner_domain=owner_domain,
        owner_component=owner_component,
        object_kinds=object_kinds,
        family_ids=family_ids,
        relationship_types=relationship_types,
        read_only=read_only,
        mutation_forbidden=mutation_forbidden,
        related_contracts=("leonardo.contracts.traceable_object.TraceableObjectSummary",),
        related_docs=("docs/contracts_docs/OBJECT_MAP_PROTOCOL.md",),
        related_tests=("tests/contracts_test/test_object_map_contracts.py",),
        metadata=metadata or {},
        extra=extra or {},
    )


def _section(
    *,
    section_id: str = "core-runtime-section",
    provider_id: str = "core-runtime-provider",
    summaries=(),
    relationships=(),
    legends=(),
    relationship_definitions=(),
    metadata: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
) -> ObjectMapSection:
    return ObjectMapSection(
        section_id=section_id,
        provider_id=provider_id,
        owner_domain="core.runtime",
        object_kind="action",
        family_id="action",
        title="Actions",
        summaries=summaries,
        relationships=relationships,
        legends=legends,
        relationship_definitions=relationship_definitions,
        warnings=("descriptor-only",),
        blockers=("provider-not-implemented",),
        metadata=metadata or {},
        extra=extra or {},
    )


def _summary() -> TraceableObjectSummary:
    return TraceableObjectSummary(
        object_ref=TraceableObjectRef(
            object_id="action-1",
            object_kind="action",
            owner_domain="gui",
            owner_component="ActionRegistry",
        ),
        lifecycle_status="registered",
        runtime_or_persistent="runtime",
        display_name="Action 1",
    )


def _relationship() -> TraceableRelationshipRef:
    return TraceableRelationshipRef(
        relationship_type="triggers",
        source_ref=TraceableObjectRef(
            object_id="action-1",
            object_kind="action",
            owner_domain="gui",
        ),
        target_ref=TraceableObjectRef(
            object_id="operation-1",
            object_kind="operation",
            owner_domain="core.runtime",
        ),
        direction="outbound",
    )


def _legend():
    legend = object_family_legend_by_id("action")
    assert legend is not None
    return legend


def _relationship_definition():
    definitions = object_relationship_definitions_by_type("triggers")
    assert definitions
    return definitions[0]
