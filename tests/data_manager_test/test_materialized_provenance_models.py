from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionMemberV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionRevisionV2,
    DatabaseContentEditPlan,
    DatabaseDefinitionV1,
    DatabaseRevisionManifest,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DatabaseRevisionManifestV3,
    DatabaseRevisionManifestV4,
    DataManagerCreationError,
    DataManagerCreationStore,
    artifact_collection_revision_from_dict,
    database_collection_references,
    database_revision_from_dict,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
STEP = 3_600_000
READERS = {"collection": artifact_collection_revision_from_dict, "database": database_revision_from_dict}


def _canonical(payload):
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _signed(payload):
    result = deepcopy(payload)
    result.pop("revision_id", None)
    result["revision_id"] = sha256(_canonical(result)).hexdigest()
    return result


def _member(logical, physical, recipe, output):
    return ArtifactCollectionMemberV1(
        ManagedArtifactVersionKey(logical * 64, physical * 64),
        recipe * 64, "sma" if logical == "a" else "derivative",
        "indicator" if logical == "a" else "construct", (output,), physical * 64,
    ).to_dict()


def _payload(kind, *, legacy=False):
    # The selected basis uses physical 2; slope actually consumed physical 1.
    older = _member("a", "1", "c", "sma")
    newer = _member("a", "2", "c", "sma")
    dependent = _member("b", "3", "d", "d1")
    outputs = [
        {"logical_artifact_id": "a" * 64, "output_name": "sma", "column_name": "basis"},
        {"logical_artifact_id": "b" * 64, "output_name": "d1", "column_name": "slope"},
    ]
    source = OHLCVSourceFingerprintV1(MARKET, "4" * 64, "5" * 64, 3, 0, 2 * STEP, "committed", "ok", "1.0")
    payload = {
        "display_name": "Physical provenance", "description": "",
        "market_id": source.to_dict()["market_id"], "source_ohlcv": source.to_dict(),
        "members": [newer, dependent],
        "dependency_edges": [{"dependency_logical_artifact_id": "a" * 64,
            "dependent_logical_artifact_id": "b" * 64, "role": "source", "output_name": "sma"}],
        "selected_outputs": outputs, "first_timestamp_ms": 0, "last_timestamp_ms": 2 * STEP,
        "previous_revision_id": None, "created_at_utc": "2026-10-04T12:00:00Z",
    }
    if kind == "collection":
        payload.update(
            schema_version="1.0" if legacy else "2.0", object_type="artifact_collection_revision",
            collection_id="ac_" + "a" * 32, root_logical_artifact_ids=["a" * 64, "b" * 64],
            support_logical_artifact_ids=[], presentation_order=["basis", "slope"],
            source_portable_recipe_ids=["c" * 64, "d" * 64], source_recipe_collection_id=None,
            source_recipe_collection_revision_id=None, validation_state="valid", database_ready=True,
            revised_at_utc="2026-10-04T12:00:00Z",
        )
    else:
        payload.update(
            schema_version="3.0" if legacy else "4.0", object_type="database_revision",
            database_id="db_" + "b" * 32, seed_id="seed_" + "c" * 32,
            collection_sources=[], column_mapping={name: name for name in ("ts_ms", "close", "basis", "slope")},
            row_count=3, column_count=4, values_sha256="6" * 64,
            selection_sources=[{"source_kind": "artifact", "source_id": output["logical_artifact_id"],
                "source_revision_id": None, "column_names": [output["column_name"]]} for output in outputs],
        )
    if not legacy:
        payload["value_provenance"] = {
            "members": [older, newer, dependent],
            "dependency_edges": [{"dependency_artifact_id": "1" * 64,
                "dependent_artifact_id": "3" * 64, "role": "source", "output_name": "sma"}],
            "outputs": [{**output, "artifact_id": physical * 64,
                "first_timestamp_ms": 0, "last_timestamp_ms": 2 * STEP}
                for output, physical in zip(outputs, ("2", "3"), strict=True)],
        }
    return _signed(payload)


def _legacy_provenance_payload():
    payload = _payload("database")
    legacy = _payload("database", legacy=True)
    payload["value_provenance"] = {
        "members": [], "dependency_edges": [], "legacy_revisions": [legacy],
        "outputs": [{**output, "legacy_revision_id": legacy["revision_id"],
                     "first_timestamp_ms": 0, "last_timestamp_ms": 2 * STEP}
                    for output in legacy["selected_outputs"]],
    }
    return _signed(payload)


def test_legacy_provenance_is_explicit_canonical_and_immutable():
    payload = _legacy_provenance_payload()
    model = database_revision_from_dict(payload)
    assert model.to_dict() == payload
    assert model.canonical_json_bytes() == _canonical(payload)
    assert model.value_provenance["members"] == ()
    assert all("artifact_id" not in segment for segment in model.value_provenance["outputs"])
    with pytest.raises(TypeError):
        model.value_provenance["legacy_revisions"][0]["schema_version"] = "4.0"


@pytest.mark.parametrize("case", ("missing_legacy", "unknown_revision", "duplicate", "wrong_database", "wrong_market",
                                 "wrong_output", "bad_hash", "noncanonical_timestamp", "nonlegacy", "physical_and_legacy", "uncovered_range"))
def test_invalid_legacy_provenance_is_rejected(case):
    payload = _legacy_provenance_payload()
    provenance = payload["value_provenance"]
    record = provenance["legacy_revisions"][0]
    if case == "missing_legacy":
        provenance.pop("legacy_revisions")
    elif case == "unknown_revision":
        provenance["outputs"][0]["legacy_revision_id"] = "e" * 64
    elif case == "duplicate":
        provenance["legacy_revisions"].append(deepcopy(record))
    elif case in {"wrong_database", "wrong_market"}:
        if case == "wrong_database":
            record["database_id"] = "db_" + "d" * 32
        else:
            record["market_id"]["symbol"] = "ETHUSDT"
            record["source_ohlcv"]["market_id"]["symbol"] = "ETHUSDT"
        provenance["legacy_revisions"][0] = _signed(record)
        for segment in provenance["outputs"]:
            segment["legacy_revision_id"] = provenance["legacy_revisions"][0]["revision_id"]
    elif case == "wrong_output":
        provenance["outputs"][0]["output_name"] = "other"
    elif case == "bad_hash":
        record["description"] = "tampered"
    elif case == "noncanonical_timestamp":
        record["created_at_utc"] = record["created_at_utc"].replace("Z", "+00:00")
    elif case == "nonlegacy":
        provenance["legacy_revisions"][0] = _payload("database")
    elif case == "physical_and_legacy":
        provenance["outputs"][0]["artifact_id"] = "2" * 64
    else:
        payload["last_timestamp_ms"] += STEP
        payload["row_count"] += 1
        for segment in provenance["outputs"]:
            segment["last_timestamp_ms"] += STEP
    with pytest.raises(DataManagerCreationError):
        database_revision_from_dict(_signed(payload))


def test_collection_cannot_claim_legacy_database_provenance():
    payload = _payload("collection")
    payload["value_provenance"] = _legacy_provenance_payload()["value_provenance"]
    with pytest.raises(DataManagerCreationError):
        artifact_collection_revision_from_dict(_signed(payload))


@pytest.mark.parametrize("kind,new_type,parent_type", [
    ("collection", ArtifactCollectionRevisionV2, ArtifactCollectionRevisionV1),
    ("database", DatabaseRevisionManifestV4, DatabaseRevisionManifestV3),
])
def test_mixed_physical_versions_of_one_logical_artifact_round_trip(kind, new_type, parent_type):
    payload = _payload(kind)
    encoded = _canonical(payload)
    model = READERS[kind](json.loads(encoded))
    assert type(model) is new_type
    assert isinstance(model, parent_type)
    assert model.canonical_json_bytes() == encoded
    assert new_type.from_dict(model.to_dict()) == model
    assert len(model.members) == 2
    assert len(model.value_provenance["members"]) == 3
    assert model.value_provenance["dependency_edges"][0]["dependency_artifact_id"] == "1" * 64
    assert model.members[0].version_key.artifact_id == "2" * 64
    if kind == "database":
        assert isinstance(model, DatabaseRevisionManifest)
        assert database_collection_references(model) == ()


@pytest.mark.parametrize("version", ["collection1", "database1", "database2", "database3"])
def test_legacy_shapes_and_canonical_bytes_are_unchanged(version):
    kind = "collection" if version == "collection1" else "database"
    payload = _payload(kind, legacy=True)
    if version in {"database1", "database2"}:
        payload["schema_version"] = version[-1] + ".0"
        del payload["selection_sources"]
    if version == "database1":
        payload.update(collection_id="ac_" + "a" * 32, collection_revision_id="7" * 64,
            collection_manifest_hash="7" * 64,
            artifact_version_keys=[{"logical_artifact_id": item["logical_artifact_id"], "artifact_id": item["artifact_id"]} for item in payload["members"]],
            artifact_payload_hashes=[item["values_sha256"] for item in payload["members"]],
            portable_recipe_ids=[item["portable_recipe_id"] for item in payload["members"]])
        for name in ("members", "dependency_edges", "selected_outputs", "collection_sources"):
            del payload[name]
    payload = _signed(payload)
    encoded = _canonical(payload)
    model = READERS[kind](json.loads(encoded))
    expected = {"collection1": ArtifactCollectionRevisionV1, "database1": DatabaseRevisionManifestV1,
        "database2": DatabaseRevisionManifestV2, "database3": DatabaseRevisionManifestV3}[version]
    assert type(model) is expected
    assert model.canonical_json_bytes() == encoded
    assert "value_provenance" not in model.to_dict()
    with pytest.raises(DataManagerCreationError, match="fields"):
        READERS[kind](_signed({**payload, "value_provenance": {"members": [], "dependency_edges": [], "outputs": []}}))


@pytest.mark.parametrize("kind", READERS)
def test_provenance_is_deeply_frozen_and_detached(kind):
    payload = _payload(kind)
    model = READERS[kind](payload)
    with pytest.raises(FrozenInstanceError):
        model.value_provenance = {}
    with pytest.raises(TypeError):
        model.value_provenance["outputs"][0]["artifact_id"] = "1" * 64
    with pytest.raises(TypeError):
        model.value_provenance["members"][0]["output_names"][0] = "bad"
    payload["value_provenance"]["members"][0]["output_names"].append("extra")
    detached = model.to_dict()
    detached["value_provenance"]["dependency_edges"][0]["role"] = "changed"
    assert model.value_provenance["members"][0]["output_names"] == ("sma",)
    assert model.value_provenance["dependency_edges"][0]["role"] == "source"


@pytest.mark.parametrize("kind", READERS)
@pytest.mark.parametrize("case", [
    "missing_provenance", "extra_top_field", "extra_provenance_field", "missing_provenance_field",
    "members_not_sequence", "edges_not_sequence", "outputs_not_sequence", "provenance_not_mapping",
    "extra_member_field", "missing_member_field", "member_output_string", "bad_member_hash", "bad_artifact_id",
    "duplicate_physical_member", "extra_edge_field", "missing_edge_field", "bad_edge_id",
    "missing_dependency", "missing_dependent", "missing_edge_output", "duplicate_edge", "conflicting_role",
    "cycle", "self_cycle", "extra_segment_field", "missing_segment_field", "missing_provider",
    "wrong_logical_provider", "missing_provider_output", "wrong_binding", "unknown_column",
    "bool_timestamp", "float_timestamp", "reversed_range", "outside_range", "incomplete_start",
    "incomplete_end", "missing_column", "bad_segment_id",
])
def test_invalid_physical_evidence_is_rejected_even_with_recomputed_hash(kind, case):
    payload = _payload(kind)
    provenance = payload["value_provenance"]
    member, edge, segment = provenance["members"][0], provenance["dependency_edges"][0], provenance["outputs"][0]
    if case == "missing_provenance":
        del payload["value_provenance"]
    elif case == "extra_top_field":
        payload["unexpected"] = True
    elif case == "extra_provenance_field":
        provenance["unexpected"] = []
    elif case == "missing_provenance_field":
        del provenance["dependency_edges"]
    elif case.endswith("_not_sequence"):
        provenance[case.removesuffix("_not_sequence").replace("edges", "dependency_edges")] = {}
    elif case == "provenance_not_mapping":
        payload["value_provenance"] = []
    elif case == "extra_member_field":
        member["unexpected"] = True
    elif case == "missing_member_field":
        del member["kind"]
    elif case == "member_output_string":
        member["output_names"] = "sma"
    elif case == "bad_member_hash":
        member["values_sha256"] = "invalid"
    elif case == "bad_artifact_id":
        member["artifact_id"] = "invalid"
    elif case == "duplicate_physical_member":
        provenance["members"].append(dict(member))
    elif case == "extra_edge_field":
        edge["unexpected"] = True
    elif case == "missing_edge_field":
        del edge["role"]
    elif case == "bad_edge_id":
        edge["dependent_artifact_id"] = "invalid"
    elif case == "missing_dependency":
        edge["dependency_artifact_id"] = "9" * 64
    elif case == "missing_dependent":
        edge["dependent_artifact_id"] = "9" * 64
    elif case == "missing_edge_output":
        edge["output_name"] = "missing"
    elif case in {"duplicate_edge", "conflicting_role"}:
        provenance["dependency_edges"].append({**edge,
            "dependency_artifact_id": ("1" if case == "duplicate_edge" else "2") * 64})
    elif case == "cycle":
        provenance["dependency_edges"].append({"dependency_artifact_id": "3" * 64,
            "dependent_artifact_id": "1" * 64, "role": "source", "output_name": "d1"})
    elif case == "self_cycle":
        edge["dependent_artifact_id"] = "1" * 64
    elif case == "extra_segment_field":
        segment["unexpected"] = True
    elif case == "missing_segment_field":
        del segment["output_name"]
    elif case == "missing_provider":
        segment["artifact_id"] = "9" * 64
    elif case == "wrong_logical_provider":
        segment["logical_artifact_id"] = "b" * 64
    elif case == "missing_provider_output":
        segment["output_name"] = "missing"
    elif case == "wrong_binding":
        segment.update(logical_artifact_id="b" * 64, artifact_id="3" * 64, output_name="d1")
    elif case == "unknown_column":
        segment["column_name"] = "unknown"
    elif case == "bool_timestamp":
        segment["first_timestamp_ms"] = False
    elif case == "float_timestamp":
        segment["last_timestamp_ms"] = float(2 * STEP)
    elif case == "reversed_range":
        segment.update(first_timestamp_ms=STEP, last_timestamp_ms=0)
    elif case == "outside_range":
        segment["last_timestamp_ms"] = 3 * STEP
    elif case == "incomplete_start":
        segment["first_timestamp_ms"] = STEP
    elif case == "incomplete_end":
        segment["last_timestamp_ms"] = STEP
    elif case == "missing_column":
        provenance["outputs"].pop()
    elif case == "bad_segment_id":
        segment["artifact_id"] = "INVALID"
    with pytest.raises(ValueError):
        READERS[kind](_signed(payload))


@pytest.mark.parametrize("kind", READERS)
@pytest.mark.parametrize("section,key,value", [
    ("members", "values_sha256", "9" * 64),
    ("dependency_edges", "role", "other_role"),
    ("outputs", "artifact_id", "1" * 64),
])
def test_every_provenance_section_participates_in_revision_hash(kind, section, key, value):
    payload = _payload(kind)
    original = payload["revision_id"]
    payload["value_provenance"][section][0][key] = value
    with pytest.raises(DataManagerCreationError, match="revision_id"):
        READERS[kind](payload)
    model = READERS[kind](_signed(payload))
    assert model.revision_id != original


def _append_payload(kind):
    payload = _payload(kind)
    outputs = payload["value_provenance"]["outputs"]
    prefix = {**outputs[0], "artifact_id": "1" * 64, "last_timestamp_ms": STEP}
    suffix = {**outputs[0], "first_timestamp_ms": 2 * STEP}
    # Interleaving another column does not change per-column segment ordering.
    payload["value_provenance"]["outputs"] = [prefix, outputs[1], suffix]
    return _signed(payload)


@pytest.mark.parametrize("kind", ["database"])
def test_append_keeps_prefix_and_records_new_provider(kind):
    payload = _append_payload(kind)
    model = READERS[kind](payload)
    assert model.canonical_json_bytes() == _canonical(payload)
    assert [s["artifact_id"] for s in model.value_provenance["outputs"] if s["column_name"] == "basis"] == ["1" * 64, "2" * 64]


def test_collection_does_not_stitch_providers_within_one_output():
    with pytest.raises(DataManagerCreationError, match="one full-range"):
        READERS["collection"](_append_payload("collection"))


@pytest.mark.parametrize("kind", READERS)
@pytest.mark.parametrize("case", ["overlap", "duplicate", "unordered", "gap"])
def test_append_rejects_overlap_reordering_and_nonadjacent_segments(kind, case):
    payload = _append_payload(kind)
    outputs = payload["value_provenance"]["outputs"]
    if case == "overlap":
        outputs[2]["first_timestamp_ms"] = STEP
    elif case == "duplicate":
        outputs.insert(1, deepcopy(outputs[0]))
    elif case == "unordered":
        outputs.reverse()
    else:
        outputs[0]["last_timestamp_ms"] = 0
    with pytest.raises(DataManagerCreationError):
        READERS[kind](_signed(payload))


@pytest.mark.parametrize("gap", [False, True])
def test_monthly_adjacency_uses_existing_calendar_authority(gap):
    payload = _append_payload("database")
    january, february, march = [int(datetime(2026, month, day, tzinfo=UTC).timestamp() * 1000)
        for month, day in ((1, 31), (2, 28), (3, 31))]
    market = MarketId("bybit", "linear", "BTCUSDT", "1M")
    source = OHLCVSourceFingerprintV1(market, "4" * 64, "5" * 64, 3, january, march, "committed", "ok", "1.0")
    payload.update(market_id=source.to_dict()["market_id"], source_ohlcv=source.to_dict(),
        first_timestamp_ms=january, last_timestamp_ms=march)
    prefix, other, suffix = payload["value_provenance"]["outputs"]
    prefix.update(first_timestamp_ms=january, last_timestamp_ms=january)
    other.update(first_timestamp_ms=january, last_timestamp_ms=march)
    suffix.update(first_timestamp_ms=march if gap else february, last_timestamp_ms=march)
    if gap:
        with pytest.raises(DataManagerCreationError, match="contiguous"):
            database_revision_from_dict(_signed(payload))
    else:
        assert database_revision_from_dict(_signed(payload)).market_id == market


def _empty_database_payload():
    payload = _payload("database")
    for name in ("members", "dependency_edges", "selected_outputs", "selection_sources"):
        payload[name] = []
    payload.update(column_mapping={"ts_ms": "ts_ms", "close": "close"}, column_count=2,
        value_provenance={"members": [], "dependency_edges": [], "outputs": []})
    return _signed(payload)


def test_empty_base_database_requires_all_provenance_tuples_empty():
    payload = _empty_database_payload()
    model = database_revision_from_dict(payload)
    assert all(value == () for value in model.value_provenance.values())
    assert model.canonical_json_bytes() == _canonical(payload)
    payload["value_provenance"]["members"] = [_member("a", "1", "c", "sma")]
    with pytest.raises(DataManagerCreationError, match="empty structural tuples"):
        database_revision_from_dict(_signed(payload))


def test_content_edit_plan_adds_only_last_optional_frozen_evidence_field():
    model = database_revision_from_dict(_payload("database"))
    plan = DatabaseContentEditPlan("7" * 64, model.database_id, model.revision_id, MARKET,
        model.source_ohlcv, (), (), (), (), (), model.members, model.dependency_edges,
        model.selected_outputs, model.selection_sources, b"ts_ms,close\n0,1\n", ("ts_ms", "close"), (), (), False)
    assert tuple(f.name for f in fields(plan)[-2:]) == ("value_provenance", "remove_columns")
    assert plan.remove_columns == ()
    assert plan.value_provenance is None
    evidence = model.to_dict()["value_provenance"]
    reviewed = replace(plan, value_provenance=evidence)
    evidence["outputs"][0]["artifact_id"] = "9" * 64
    assert reviewed.value_provenance["outputs"][0]["artifact_id"] == "2" * 64
    with pytest.raises(TypeError):
        reviewed.value_provenance["outputs"][0]["artifact_id"] = "9" * 64
    with pytest.raises(DataManagerCreationError, match="mapping"):
        replace(plan, value_provenance=[])


def test_collection_store_reads_legacy_and_new_revisions_without_rewriting(tmp_path):
    store = DataManagerCreationStore(tmp_path / "data_manager", clock=lambda: NOW)
    store.set_collection_semantic_key_resolver(
        lambda market, roots, outputs: (market, tuple(roots), tuple(outputs))
    )
    legacy = artifact_collection_revision_from_dict(_payload("collection", legacy=True))
    store.save_collection_revision(legacy, expected_head_revision_id=None)
    payload = _payload("collection")
    payload["previous_revision_id"] = legacy.revision_id
    current = artifact_collection_revision_from_dict(_signed(payload))
    store.save_collection_revision(current, expected_head_revision_id=legacy.revision_id)
    assert type(store.load_collection(current.collection_id)) is ArtifactCollectionRevisionV2
    assert store.load_collection(current.collection_id) == current
    assert store.load_collection(legacy.collection_id, legacy.revision_id).canonical_json_bytes() == legacy.canonical_json_bytes()
    assert {type(item) for item in store.list_collection_revisions(current.collection_id)} == {ArtifactCollectionRevisionV1, ArtifactCollectionRevisionV2}
    saved = list((tmp_path / "data_manager").rglob(legacy.revision_id + ".json"))
    assert len(saved) == 1 and saved[0].read_bytes() == legacy.canonical_json_bytes()


@pytest.mark.parametrize("empty", [False, True])
def test_database_store_publishes_and_reads_physical_provenance(tmp_path, empty):
    payload = _empty_database_payload() if empty else _append_payload("database")
    values = (b"ts_ms,close\n0,10\n3600000,11\n7200000,12\n" if empty
        else b"ts_ms,close,basis,slope\n0,10,1,\n3600000,11,2,1\n7200000,12,3,1\n")
    payload["values_sha256"] = sha256(values).hexdigest()
    model = database_revision_from_dict(_signed(payload))
    definition = DatabaseDefinitionV1(model.database_id, model.display_name, model.description, MARKET, model.seed_id, NOW)
    store = DataManagerCreationStore(tmp_path / "data_manager", clock=lambda: NOW)
    assert store.publish_database_revision(definition, model, values, expected_head_revision_id=None) == model
    loaded = store.load_database_revision(model.database_id)
    assert type(loaded.manifest) is DatabaseRevisionManifestV4
    assert loaded.manifest.canonical_json_bytes() == model.canonical_json_bytes()
    assert loaded.values_csv == values
    assert store.load_database_manifest(model.database_id) == model
    assert store.list_database_revisions(model.database_id) == (model,)


@pytest.mark.parametrize("kind", READERS)
def test_dispatch_rejects_unknown_versions_and_nonmappings(kind):
    with pytest.raises(DataManagerCreationError, match="unsupported"):
        READERS[kind](_signed({**_payload(kind), "schema_version": "99.0"}))
    with pytest.raises(DataManagerCreationError, match="mapping"):
        READERS[kind]([])



def _a2_v5_payload():
    original = _payload("database", legacy=True)
    legacy = deepcopy(original)
    legacy.update(schema_version="1.0", collection_id="ac_" + "a" * 32,
                  collection_revision_id="7" * 64, collection_manifest_hash="7" * 64,
                  artifact_version_keys=[{"logical_artifact_id": m["logical_artifact_id"],
                                         "artifact_id": m["artifact_id"]} for m in legacy["members"]],
                  artifact_payload_hashes=[m["values_sha256"] for m in legacy["members"]],
                  portable_recipe_ids=[m["portable_recipe_id"] for m in legacy["members"]],
                  column_mapping={"ts_ms": "ts_ms", "close": "close", "sma": "basis", "d1": "slope"})
    for key in ("members", "dependency_edges", "selected_outputs", "collection_sources", "selection_sources"):
        legacy.pop(key)
    legacy = _signed(legacy)
    outputs = [{"column_name": o["column_name"], "output_name": o["output_name"],
                "legacy_revision_id": legacy["revision_id"]} for o in original["selected_outputs"]]
    original.update(schema_version="5.0", members=[], dependency_edges=[], selected_outputs=outputs,
                    selection_sources=[{"source_kind": "legacy_snapshot", "source_id": original["database_id"],
                                        "source_revision_id": legacy["revision_id"], "column_names": ["basis", "slope"]}],
                    value_provenance={"members": [], "dependency_edges": [], "legacy_revisions": [legacy],
                                      "outputs": [{**o, "first_timestamp_ms": 0, "last_timestamp_ms": 2 * STEP}
                                                  for o in outputs]})
    return _signed(original)


def test_a2_v5_unbound_snapshot_round_trip_and_old_versions_reject_extension():
    from leonardo.data_manager import DatabaseLegacyOutputV1, DatabaseRevisionManifestV5
    payload = _a2_v5_payload()
    model = database_revision_from_dict(payload)
    assert isinstance(model, (DatabaseRevisionManifestV5, DatabaseRevisionManifestV4))
    assert all(isinstance(o, DatabaseLegacyOutputV1) and o.logical_artifact_id is None for o in model.selected_outputs)
    assert model.canonical_json_bytes() == _canonical(payload)
    assert database_revision_from_dict(model.to_dict()) == model
    for version in ("2.0", "3.0", "4.0"):
        with pytest.raises(DataManagerCreationError):
            database_revision_from_dict(_signed({**payload, "schema_version": version}))
    collection = _payload("collection")
    collection["selected_outputs"] = payload["selected_outputs"]
    with pytest.raises(DataManagerCreationError):
        artifact_collection_revision_from_dict(_signed(collection))


@pytest.mark.parametrize("case", ("binding_revision", "binding_column", "invented_logical", "source_database",
                                  "source_revision", "source_column", "gap", "overlap", "duplicate_column",
                                  "unused_capture", "wrong_database", "wrong_market", "tampered_capture"))
def test_a2_v5_rejects_false_or_incomplete_claims(case):
    payload = _a2_v5_payload()
    provenance = payload["value_provenance"]
    if case == "binding_revision":
        payload["selected_outputs"][0]["legacy_revision_id"] = "e" * 64
    elif case == "binding_column":
        payload["selected_outputs"][0]["output_name"] = "not_recorded"
    elif case == "invented_logical":
        provenance["outputs"][0]["logical_artifact_id"] = "a" * 64
    elif case == "source_database":
        payload["selection_sources"][0]["source_id"] = "db_" + "f" * 32
    elif case == "source_revision":
        payload["selection_sources"][0]["source_revision_id"] = "e" * 64
    elif case == "source_column":
        payload["selection_sources"][0]["column_names"].append("close")
    elif case == "gap":
        provenance["outputs"][0]["first_timestamp_ms"] = STEP
    elif case == "overlap":
        provenance["outputs"].append(deepcopy(provenance["outputs"][0]))
    elif case == "duplicate_column":
        payload["selected_outputs"].append(deepcopy(payload["selected_outputs"][0]))
    elif case == "unused_capture":
        extra = deepcopy(provenance["legacy_revisions"][0]); extra["description"] = "unused"
        provenance["legacy_revisions"].append(_signed(extra))
    else:
        captured = provenance["legacy_revisions"][0]
        if case == "wrong_database":
            captured["database_id"] = "db_" + "d" * 32
        elif case == "wrong_market":
            captured["market_id"]["symbol"] = "ETHUSDT"
            captured["source_ohlcv"]["market_id"]["symbol"] = "ETHUSDT"
        else:
            captured["description"] = "tampered"
        if case != "tampered_capture":
            provenance["legacy_revisions"][0] = _signed(captured)
    with pytest.raises(DataManagerCreationError):
        database_revision_from_dict(_signed(payload))


@pytest.mark.parametrize("rewrite_prefix", ("all", "last_row"))
def test_v5_rejects_relabelling_original_unbound_prefix_as_exact(rewrite_prefix):
    payload = _a2_v5_payload()
    exact = _payload("database")["value_provenance"]
    provenance = payload["value_provenance"]
    provenance["members"] = deepcopy(exact["members"])
    provenance["dependency_edges"] = deepcopy(exact["dependency_edges"])
    if rewrite_prefix == "all":
        provenance["outputs"] = deepcopy(exact["outputs"])
    else:
        for segment in provenance["outputs"]:
            segment["last_timestamp_ms"] = STEP
        for segment in deepcopy(exact["outputs"]):
            segment["first_timestamp_ms"] = 2 * STEP
            provenance["outputs"].append(segment)
        provenance["outputs"].sort(key=lambda s: (s["column_name"], s["first_timestamp_ms"]))
    # All row coverage is still inside the original V1 capture; none is a future suffix.
    with pytest.raises(DataManagerCreationError):
        database_revision_from_dict(_signed(payload))


def test_real_v5_reader_and_store_reject_exact_claim_for_original_last_row(tmp_path):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    from tests.data_manager_test.test_update_workflow import _domain

    service, _artifacts, recipes, _historical = _domain(tmp_path)
    original, _collection, _roots, _values = _a2_snapshot(service, recipes)
    proved_v4 = next(service.load_database_revision(identity).manifest
                     for identity in service.creation_store.list_database_ids()
                     if identity != original.database_id)
    baseline = service.plan_database_content_edit(original.database_id)
    service.execute_database_content_edit(service.plan_database_content_edit(
        original.database_id, remove_columns=(baseline.selected_outputs[-1].column_name,)))
    saved = service.load_database_revision(original.database_id)
    assert saved.manifest.schema_version == "5.0"
    payload = saved.manifest.to_dict()
    payload["previous_revision_id"] = saved.manifest.revision_id
    provenance = payload["value_provenance"]
    exact = proved_v4.to_dict()["value_provenance"]
    provenance["members"] = deepcopy(exact["members"])
    provenance["dependency_edges"] = deepcopy(exact["dependency_edges"])
    columns = {o.column_name for o in saved.manifest.selected_outputs}
    for segment in provenance["outputs"]:
        segment["last_timestamp_ms"] -= 60_000
    for segment in deepcopy(exact["outputs"]):
        if segment["column_name"] in columns:
            segment["first_timestamp_ms"] = original.last_timestamp_ms
            provenance["outputs"].append(segment)
    provenance["outputs"].sort(key=lambda s: (s["column_name"], s["first_timestamp_ms"]))
    try:
        forged = database_revision_from_dict(_signed(payload))
    except DataManagerCreationError:
        return
    service.creation_store.publish_database_revision(
        service.load_database_definition(original.database_id), forged, saved.values_csv,
        expected_head_revision_id=saved.manifest.revision_id,
    )
    loaded = service.creation_store.read_trusted_database_revision(original.database_id)
    assert loaded.manifest == forged and loaded.values_csv == saved.values_csv
    pytest.fail("V5 reader, canonical publication and trusted reader all accepted relabelled legacy cells")



def test_a2_v5_exact_future_suffix_round_trips_without_relabelling_legacy():
    payload = _a2_v5_payload()
    original_segments = deepcopy(payload["value_provenance"]["outputs"])
    exact = _payload("database")["value_provenance"]
    payload.update(row_count=5, last_timestamp_ms=4 * STEP)
    payload["source_ohlcv"].update(row_count=5, last_timestamp_ms=4 * STEP)
    provenance = payload["value_provenance"]
    provenance["members"] = deepcopy(exact["members"])
    provenance["dependency_edges"] = deepcopy(exact["dependency_edges"])
    for segment in deepcopy(exact["outputs"]):
        segment.update(first_timestamp_ms=3 * STEP, last_timestamp_ms=4 * STEP)
        provenance["outputs"].append(segment)
    provenance["outputs"].sort(key=lambda segment: (segment["column_name"], segment["first_timestamp_ms"]))
    payload = _signed(payload)
    model = database_revision_from_dict(payload)
    assert model.canonical_json_bytes() == _canonical(payload)
    assert database_revision_from_dict(model.to_dict()) == model
    assert [segment for segment in model.to_dict()["value_provenance"]["outputs"]
            if "legacy_revision_id" in segment] == original_segments
    assert all(output.logical_artifact_id is None for output in model.selected_outputs)
