from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionDependencyV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    DatabaseCollectionReferenceV2,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DatabaseRevisionManifestV3,
    DataManagerCreationError,
    database_collection_references,
    database_revision_from_dict,
)
from leonardo.data_manager.creation_models import deterministic_hash


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
NOW = datetime(2026, 9, 7, 10, 30, tzinfo=UTC)


def _source() -> OHLCVSourceFingerprintV1:
    return OHLCVSourceFingerprintV1(
        MARKET, "1" * 64, "2" * 64, 3, 1, 3, "committed", "ok", "1.0"
    )


def _member(
    logical: str, artifact: str, recipe: str, tool: str, output: str
) -> ArtifactCollectionMemberV1:
    return ArtifactCollectionMemberV1(
        ManagedArtifactVersionKey(logical * 64, artifact * 64),
        recipe * 64,
        tool,
        "construct" if tool == "derivative" else "indicator",
        (output,),
        artifact * 64,
    )


def _manifest(
    *,
    members: tuple[ArtifactCollectionMemberV1, ...] = (),
    edges: tuple[ArtifactCollectionDependencyV1, ...] = (),
    outputs: tuple[ArtifactCollectionOutputV1, ...] = (),
    references: tuple[DatabaseCollectionReferenceV2, ...] = (),
) -> DatabaseRevisionManifestV2:
    columns = ("ts_ms", "close", *(item.column_name for item in outputs))
    payload = {
        "schema_version": "2.0",
        "object_type": "database_revision",
        "database_id": "db_" + "a" * 32,
        "display_name": "Seed database",
        "description": "",
        "seed_id": "seed_" + "b" * 32,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": _source().to_dict(),
        "members": [item.to_dict() for item in members],
        "dependency_edges": [item.to_dict() for item in edges],
        "selected_outputs": [item.to_dict() for item in outputs],
        "collection_sources": [
            item.to_dict()
            for item in sorted(
                references,
                key=lambda item: (item.collection_id, item.revision_id),
            )
        ],
        "column_mapping": {item: item for item in columns},
        "first_timestamp_ms": 1,
        "last_timestamp_ms": 3,
        "row_count": 3,
        "column_count": len(columns),
        "values_sha256": "3" * 64,
        "previous_revision_id": None,
        "created_at_utc": "2026-09-07T10:30:00Z",
    }
    payload["revision_id"] = deterministic_hash(payload)
    return DatabaseRevisionManifestV2.from_dict(payload)


def _member_bearing_parts():
    support = _member("a", "b", "c", "sma", "sma_14")
    root = _member("d", "e", "f", "derivative", "research_source__d1")
    edge = ArtifactCollectionDependencyV1(
        support.version_key.logical_artifact_id,
        root.version_key.logical_artifact_id,
        "source",
        "sma_14",
    )
    output = ArtifactCollectionOutputV1(
        root.version_key.logical_artifact_id,
        "research_source__d1",
        "angle_momentum",
    )
    references = (
        DatabaseCollectionReferenceV2("ac_" + "1" * 32, "1" * 64),
        DatabaseCollectionReferenceV2("ac_" + "2" * 32, "2" * 64),
    )
    return support, root, edge, output, references


def test_base_only_and_member_bearing_v2_round_trip() -> None:
    base = _manifest()
    assert database_revision_from_dict(base.to_dict()) == base
    assert database_collection_references(base) == ()

    support, root, edge, output, references = _member_bearing_parts()
    member_bearing = _manifest(
        members=(support, root),
        edges=(edge,),
        outputs=(output,),
        references=tuple(reversed(references)),
    )
    assert database_revision_from_dict(member_bearing.to_dict()) == member_bearing
    assert member_bearing.collection_sources == references
    assert member_bearing.artifact_version_keys == (
        support.version_key,
        root.version_key,
    )
    assert member_bearing.artifact_payload_hashes == (
        support.values_sha256,
        root.values_sha256,
    )
    assert member_bearing.portable_recipe_ids == (
        support.portable_recipe_id,
        root.portable_recipe_id,
    )


def test_v1_round_trip_bytes_remain_unchanged() -> None:
    payload = {
        "schema_version": "1.0",
        "object_type": "database_revision",
        "database_id": "db_" + "a" * 32,
        "display_name": "Legacy database",
        "description": "V1 remains exact",
        "seed_id": "seed_" + "b" * 32,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": _source().to_dict(),
        "collection_id": "ac_" + "c" * 32,
        "collection_revision_id": "4" * 64,
        "collection_manifest_hash": "4" * 64,
        "artifact_version_keys": [{
            "logical_artifact_id": "5" * 64,
            "artifact_id": "6" * 64,
        }],
        "artifact_payload_hashes": ["7" * 64],
        "portable_recipe_ids": ["8" * 64],
        "column_mapping": {"ts_ms": "ts_ms", "close": "close"},
        "first_timestamp_ms": 1,
        "last_timestamp_ms": 3,
        "row_count": 3,
        "column_count": 2,
        "values_sha256": "9" * 64,
        "previous_revision_id": None,
        "created_at_utc": "2026-09-07T10:30:00Z",
    }
    payload["revision_id"] = deterministic_hash(payload)
    manifest = DatabaseRevisionManifestV1.from_dict(payload)
    original_bytes = manifest.canonical_json_bytes()

    loaded = database_revision_from_dict(json.loads(original_bytes))

    assert isinstance(loaded, DatabaseRevisionManifestV1)
    assert loaded == manifest
    assert loaded.canonical_json_bytes() == original_bytes
    assert database_collection_references(loaded) == (
        DatabaseCollectionReferenceV2(
            manifest.collection_id,
            manifest.collection_revision_id,
        ),
    )


def test_v2_decoder_rejects_unknown_fields_versions_and_tampering() -> None:
    payload = _manifest().to_dict()
    with pytest.raises(DataManagerCreationError, match="unsupported"):
        database_revision_from_dict({**payload, "schema_version": "4.0"})
    with pytest.raises(DataManagerCreationError, match="fields"):
        database_revision_from_dict({**payload, "unexpected": True})
    with pytest.raises(DataManagerCreationError, match="revision_id"):
        database_revision_from_dict({**payload, "display_name": "Tampered"})


@pytest.mark.parametrize("case", ("duplicate", "orphan", "cycle", "output"))
def test_v2_rejects_invalid_content_graphs(case: str) -> None:
    support, root, edge, output, references = _member_bearing_parts()
    members = (support, root)
    edges = (edge,)
    outputs = (output,)
    if case == "duplicate":
        members = (support, support, root)
    elif case == "orphan":
        members = (*members, _member("9", "8", "7", "ema", "ema_14"))
    elif case == "cycle":
        edges = (*edges, ArtifactCollectionDependencyV1(
            root.version_key.logical_artifact_id,
            support.version_key.logical_artifact_id,
            "source",
            "research_source__d1",
        ))
    else:
        outputs = (ArtifactCollectionOutputV1(
            root.version_key.logical_artifact_id,
            "missing",
            "angle_momentum",
        ),)
    with pytest.raises(DataManagerCreationError):
        _manifest(
            members=members,
            edges=edges,
            outputs=outputs,
            references=references,
        )


def _v3_manifest(
    *,
    sources: tuple[dict[str, object], ...] | None = None,
) -> DatabaseRevisionManifestV3:
    support, root, edge, output, references = _member_bearing_parts()
    if sources is None:
        sources = (
            {
                "source_kind": "collection",
                "source_id": references[0].collection_id,
                "source_revision_id": references[0].revision_id,
                "column_names": [output.column_name],
            },
        )
        references = references[:1]
    else:
        collection_keys = {
            (source["source_id"], source["source_revision_id"])
            for source in sources
            if source.get("source_kind") == "collection"
        }
        references = tuple(
            DatabaseCollectionReferenceV2(identity, revision)
            for identity, revision in sorted(collection_keys)
        )
    canonical_sources = sorted(
        (
            {
                "source_kind": source["source_kind"],
                "source_id": source["source_id"],
                "source_revision_id": source["source_revision_id"],
                "column_names": sorted(source["column_names"]),
            }
            for source in sources
        ),
        key=lambda source: (
            source["source_kind"],
            source["source_id"],
            source["source_revision_id"] or "",
        ),
    )
    columns = ("ts_ms", "close", output.column_name)
    payload = {
        "schema_version": "3.0",
        "object_type": "database_revision",
        "database_id": "db_" + "a" * 32,
        "display_name": "V3 database",
        "description": "",
        "seed_id": "seed_" + "b" * 32,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": _source().to_dict(),
        "members": [support.to_dict(), root.to_dict()],
        "dependency_edges": [edge.to_dict()],
        "selected_outputs": [output.to_dict()],
        "collection_sources": [item.to_dict() for item in references],
        "selection_sources": canonical_sources,
        "column_mapping": {item: item for item in columns},
        "first_timestamp_ms": 1,
        "last_timestamp_ms": 3,
        "row_count": 3,
        "column_count": len(columns),
        "values_sha256": "3" * 64,
        "previous_revision_id": None,
        "created_at_utc": "2026-09-07T10:30:00Z",
    }
    payload["revision_id"] = deterministic_hash(payload)
    return DatabaseRevisionManifestV3.from_dict(payload)


def _rehash(payload: dict[str, object]) -> dict[str, object]:
    result = dict(payload)
    result.pop("revision_id", None)
    result["revision_id"] = deterministic_hash(result)
    return result


def test_v3_round_trip_canonicalizes_selection_sources_and_allows_overlap() -> None:
    _support, root, _edge, output, references = _member_bearing_parts()
    manifest = _v3_manifest(
        sources=(
            {
                "source_kind": "collection",
                "source_id": references[0].collection_id,
                "source_revision_id": references[0].revision_id,
                "column_names": [output.column_name],
            },
            {
                "source_kind": "artifact",
                "source_id": root.version_key.logical_artifact_id,
                "source_revision_id": None,
                "column_names": [output.column_name],
            },
        )
    )

    loaded = database_revision_from_dict(manifest.to_dict())

    assert loaded == manifest
    assert isinstance(loaded, DatabaseRevisionManifestV3)
    assert tuple(source["source_kind"] for source in loaded.selection_sources) == (
        "artifact",
        "collection",
    )
    assert all(
        source["column_names"] == (output.column_name,)
        for source in loaded.selection_sources
    )
    assert database_collection_references(loaded) == (references[0],)


@pytest.mark.parametrize(
    "mutation,match",
    (
        ("duplicate_source", "duplicate selection source key"),
        ("missing_owner", "every selected output requires an owner"),
        ("wrong_direct_owner", "direct source owns another Artifact output"),
        ("direct_revision", "direct Artifact source revision must be null"),
        ("unknown_column", "selection source column is not a selected output"),
        ("string_columns", "column_names must be a nonempty sequence"),
        ("empty_columns", "column_names must be a nonempty sequence"),
        ("duplicate_columns", "column_names must be unique"),
        ("collection_mismatch", "Collection provenance disagrees"),
    ),
)
def test_v3_rejects_invalid_selection_source_ownership(
    mutation: str, match: str
) -> None:
    manifest = _v3_manifest()
    payload = manifest.to_dict()
    sources = [dict(item) for item in payload["selection_sources"]]
    source = sources[0]
    if mutation == "duplicate_source":
        sources.append(dict(source))
    elif mutation == "missing_owner":
        sources = []
        payload["collection_sources"] = []
    elif mutation == "wrong_direct_owner":
        source["source_kind"] = "artifact"
        source["source_id"] = "9" * 64
        source["source_revision_id"] = None
        payload["collection_sources"] = []
    elif mutation == "direct_revision":
        source["source_kind"] = "artifact"
        source["source_id"] = payload["selected_outputs"][0]["logical_artifact_id"]
        source["source_revision_id"] = "8" * 64
        payload["collection_sources"] = []
    elif mutation == "unknown_column":
        source["column_names"] = ["missing"]
    elif mutation == "string_columns":
        source["column_names"] = payload["selected_outputs"][0]["column_name"]
    elif mutation == "empty_columns":
        source["column_names"] = []
    elif mutation == "duplicate_columns":
        column = payload["selected_outputs"][0]["column_name"]
        source["column_names"] = [column, column]
    else:
        payload["collection_sources"] = []
    payload["selection_sources"] = sources

    with pytest.raises(DataManagerCreationError, match=match):
        database_revision_from_dict(_rehash(payload))


def test_v3_selection_sources_participate_in_revision_identity() -> None:
    manifest = _v3_manifest()
    payload = manifest.to_dict()
    source = dict(payload["selection_sources"][0])
    _support, root, _edge, output, _references = _member_bearing_parts()
    payload["selection_sources"] = [
        {
            "source_kind": "artifact",
            "source_id": root.version_key.logical_artifact_id,
            "source_revision_id": None,
            "column_names": [output.column_name],
        }
    ]
    payload["collection_sources"] = []
    direct = database_revision_from_dict(_rehash(payload))

    assert direct.revision_id != manifest.revision_id
    assert source["source_kind"] == "collection"


def test_v3_treats_distinct_captured_collection_revisions_as_distinct_sources() -> None:
    _support, _root, _edge, output, references = _member_bearing_parts()
    collection_id = references[0].collection_id
    manifest = _v3_manifest(
        sources=(
            {
                "source_kind": "collection",
                "source_id": collection_id,
                "source_revision_id": "1" * 64,
                "column_names": [output.column_name],
            },
            {
                "source_kind": "collection",
                "source_id": collection_id,
                "source_revision_id": "2" * 64,
                "column_names": [output.column_name],
            },
        )
    )

    assert tuple(
        (source["source_id"], source["source_revision_id"])
        for source in manifest.selection_sources
    ) == (
        (collection_id, "1" * 64),
        (collection_id, "2" * 64),
    )
    assert manifest.collection_sources == (
        DatabaseCollectionReferenceV2(collection_id, "1" * 64),
        DatabaseCollectionReferenceV2(collection_id, "2" * 64),
    )
