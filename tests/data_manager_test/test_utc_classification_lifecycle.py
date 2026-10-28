"""UTC metadata follows copied values, never a live Artifact dependency."""
from hashlib import sha256
import json

import pytest

from leonardo.data_manager import ArtifactCollectionOutputV1, DataManagerCreationError
from leonardo.data_manager.creation_models import canonical_json_bytes, database_revision_from_dict, deterministic_hash
from leonardo.data_manager.utc_classification_snapshot import _decode_snapshot
from tests.data_manager_test.test_update_workflow import _domain, _append, MARKET
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.test_artifact_materialization import _utc_recipe
from tests.data_manager_test.test_database_content_management import _seed_database


def utc_database(tmp_path, *, collection=False, windows=(5,)):
    service, artifacts, recipes, historical = _domain(tmp_path)
    pt = _leaf("peaks_troughs", {})
    recipes.save_recipe(pt)
    roots = tuple(_utc_recipe(pt, trend_window=w, roles=("trend_peak", "trend_trough", "range_peak", "range_trough")) for w in windows)
    materialization = _materialize(service, recipes, *roots)
    if collection:
        selected = service.create_artifact_collection(materialization, "UTC")
        seed = service.create_database_seed(MARKET, "UTC database")
        manifest = service.build_database_revision(seed.seed_id, selected.collection_id)
    else:
        _, base = _seed_database(service, start_index=0)
        selections = tuple(ArtifactCollectionOutputV1(identity, "uptrend", f"up_{i}")
                           for i, identity in enumerate(materialization.root_logical_artifact_ids))
        plan = service.plan_database_content_edit(base.database_id, artifact_additions=selections)
        assert not plan.blocked, plan.blockers
        manifest = service.execute_database_content_edit(plan)
    return service, artifacts, historical, materialization, manifest


@pytest.mark.parametrize("collection", (False, True))
def test_copy_roundtrip_and_independence_from_sources(tmp_path, monkeypatch, collection):
    service, artifacts, _, materialization, manifest = utc_database(tmp_path, collection=collection)
    loaded = service.load_database_revision(manifest.database_id)
    assert manifest.to_dict()["schema_version"] == "6.0"
    payload = _decode_snapshot(loaded.utc_classification, manifest)
    assert len(payload["reports"]) == 1
    report = next(iter(payload["reports"].values()))["utc_classification"]
    assert report["availability_status"] == "known"
    assert report["context"]["stream_id"].startswith("bybit/linear/BTCUSDT/1m/")
    assert report["episodes"]
    assert len(report["timestamps_ms"]) == manifest.row_count
    assert set(a["artifact_id"] for a in payload["associations"]) == {
        m.artifact_id for m in materialization.managed_artifacts if m.tool_key == "universal_trend_classifier"}
    monkeypatch.setattr(artifacts, "load_artifact_by_id", lambda *a, **kw: pytest.fail("copied snapshot consulted Artifact"))
    assert service.load_database_revision(manifest.database_id).utc_classification == loaded.utc_classification
    assert service._creation.store.load_database_manifest(manifest.database_id, manifest.revision_id) == manifest


def test_multiple_instances_alias_removal_and_last_removal(tmp_path, monkeypatch):
    service, artifacts, _, _, manifest = utc_database(tmp_path, windows=(5, 7))
    original = service.load_database_revision(manifest.database_id)
    payload = _decode_snapshot(original.utc_classification, manifest)
    assert len(payload["reports"]) == 2
    assert {a["column_name"] for a in payload["associations"]} == {"up_0", "up_1"}
    monkeypatch.setattr(artifacts, "load_artifact_by_id", lambda *a, **kw: pytest.fail("retained snapshot consulted Artifact"))
    edited = service.execute_database_content_edit(service.plan_database_content_edit(manifest.database_id, remove_columns=("up_0",)))
    remaining = service.load_database_revision(manifest.database_id)
    assert len(_decode_snapshot(remaining.utc_classification, edited)["reports"]) == 1
    final = service.execute_database_content_edit(service.plan_database_content_edit(manifest.database_id, remove_columns=("up_1",)))
    assert service.load_database_revision(final.database_id).utc_classification is None
    assert service.load_database_revision(manifest.database_id, manifest.revision_id).utc_classification == original.utc_classification


def test_append_retains_physical_provider_coverage_and_old_bytes(tmp_path):
    service, _, historical, materialization, original = utc_database(tmp_path, collection=True)
    before = service.load_database_revision(original.database_id)
    _append(historical)
    waiting = service.plan_database_update(original.database_id)
    assert waiting.mode == "BLOCKED"
    service.execute_artifact_update(service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids))
    ready = service.plan_database_update(original.database_id)
    assert ready.mode == "APPEND", ready
    appended = service.execute_database_append(ready).database_revision
    after = service.load_database_revision(original.database_id)
    assert after.values_csv.startswith(before.values_csv)
    assert service.load_database_revision(original.database_id, original.revision_id) == before
    payload = _decode_snapshot(after.utc_classification, appended)
    assert len(payload["reports"]) == 2
    assert {a["first_timestamp_ms"] for a in payload["associations"]} == {
        original.first_timestamp_ms, original.last_timestamp_ms + 60_000}


@pytest.mark.parametrize("fault", ("missing", "bytes", "extra"))
def test_corrupt_or_wrong_file_set_is_rejected(tmp_path, fault):
    service, _, _, _, manifest = utc_database(tmp_path)
    root = service._creation.store.root_dir
    sidecar = next(root.rglob("utc_classification.json"))
    if fault == "missing":
        sidecar.unlink()
    elif fault == "bytes":
        sidecar.write_bytes(b"{}")
    else:
        (sidecar.parent / "unowned.json").write_bytes(b"{}")
    with pytest.raises(DataManagerCreationError):
        service.load_database_revision(manifest.database_id)


def test_association_tamper_rejected_even_with_rehashed_file(tmp_path):
    service, _, _, _, manifest = utc_database(tmp_path)
    loaded = service.load_database_revision(manifest.database_id)
    payload = json.loads(loaded.utc_classification)
    payload["associations"][0]["column_name"] = "invented"
    data = canonical_json_bytes(payload)
    value = manifest.to_dict(include_revision_id=False)
    value["utc_classification"]["sha256"] = sha256(data).hexdigest()
    value["revision_id"] = deterministic_hash(value)
    with pytest.raises(DataManagerCreationError, match="provenance"):
        _decode_snapshot(data, database_revision_from_dict(value))


@pytest.mark.parametrize("fault", ("flush", "gate", "head"))
def test_sidecar_publication_failure_rolls_back_all_owned_files(tmp_path, monkeypatch, fault):
    service, _, _, _, manifest = utc_database(tmp_path, windows=(5, 7))
    store = service._creation.store
    before = {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()}
    plan = service.plan_database_content_edit(manifest.database_id, remove_columns=("up_0",))
    def fail(): raise RuntimeError("injected UTC publication failure")
    if fault == "flush":
        original = store._flush_file
        def flush(path):
            if path.name == "utc_classification.json": fail()
            return original(path)
        monkeypatch.setattr(store, "_flush_file", flush)
    elif fault == "head":
        original = store._write_atomic
        def write(path, data):
            if path.name == "head.json": fail()
            return original(path, data)
        monkeypatch.setattr(store, "_write_atomic", write)
    else:
        original = store.publish_database_revision
        def publish(*args, **kwargs):
            kwargs["before_publish"] = fail
            return original(*args, **kwargs)
        monkeypatch.setattr(store, "publish_database_revision", publish)
    with pytest.raises(RuntimeError, match="injected UTC"):
        service.execute_database_content_edit(plan)
    assert {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()} == before
    assert not list(store.root_dir.rglob(".tmp-*"))


def test_deleted_artifact_does_not_invalidate_copy_and_database_delete_owns_sidecar(tmp_path):
    service, artifacts, _, materialization, manifest = utc_database(tmp_path)
    before = service.load_database_revision(manifest.database_id)
    identity = materialization.root_logical_artifact_ids[0]
    artifacts.delete_managed_artifact(MARKET, identity)
    assert service.load_database_revision(manifest.database_id) == before
    sidecar = next(service._creation.store.root_dir.rglob("utc_classification.json"))
    service.delete_database(manifest.database_id)
    assert not sidecar.exists()


def test_retained_legacy_provider_remains_unavailable_without_live_source(tmp_path, monkeypatch):
    from leonardo.data_manager import DataManagerCreationStore
    from leonardo.data_manager.creation_models import LoadedDatabaseRevision
    from leonardo.data_manager.utc_classification_snapshot import _capture_snapshot
    service, artifacts, _, _, manifest = utc_database(tmp_path)
    loaded = service.load_database_revision(manifest.database_id)
    value = manifest.to_dict(include_revision_id=False)
    value.pop("utc_classification")
    value["schema_version"] = "4.0"
    value["previous_revision_id"] = None
    value["revision_id"] = deterministic_hash(value)
    legacy = database_revision_from_dict(value)
    store = DataManagerCreationStore(tmp_path / "legacy")
    definition = service._creation.store.load_database_definition(manifest.database_id)
    store.publish_database_revision(definition, legacy, loaded.values_csv, expected_head_revision_id=None)
    previous = store.load_database_revision(legacy.database_id)
    assert previous.utc_classification is None
    monkeypatch.setattr(artifacts, "load_artifact_by_id", lambda *a: pytest.fail("legacy evidence was guessed from live Artifact"))
    captured, data = _capture_snapshot(legacy, artifacts, previous)
    payload = _decode_snapshot(data, captured)
    assert list(payload["reports"].values()) == [{}]
    assert store.load_database_revision(legacy.database_id) == previous


def test_v6_preserves_unbound_legacy_provenance_without_invented_identity():
    from tests.data_manager_test.test_materialized_provenance_models import _a2_v5_payload, _signed
    value = _a2_v5_payload()
    legacy_outputs = value["selected_outputs"]
    legacy_provenance = value["value_provenance"]
    data = canonical_json_bytes({"schema_version": "1.0", "reports": {}, "associations": []})
    value["schema_version"] = "6.0"
    value["utc_classification"] = {"schema_version": "1.0", "filename": "utc_classification.json", "sha256": sha256(data).hexdigest()}
    model = database_revision_from_dict(_signed(value))
    assert model.to_dict()["selected_outputs"] == legacy_outputs
    assert model.to_dict()["value_provenance"] == legacy_provenance
    assert all(o.logical_artifact_id is None for o in model.selected_outputs)
    assert _decode_snapshot(data, model)["associations"] == []


def test_cancelled_and_stale_utc_edit_preserve_whole_revision(tmp_path):
    from leonardo.data_manager import DataManagerOperationError
    service, _, _, _, manifest = utc_database(tmp_path, windows=(5, 7))
    store = service._creation.store
    plan = service.plan_database_content_edit(manifest.database_id, remove_columns=("up_0",))
    before = {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()}
    with pytest.raises((DataManagerCreationError, DataManagerOperationError), match="cancel"):
        service.execute_database_content_edit(plan, cancellation_requested=lambda: True)
    assert {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()} == before
    service.execute_database_content_edit(plan)
    after = {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()}
    with pytest.raises(DataManagerCreationError, match="stale|changed"):
        service.execute_database_content_edit(plan)
    assert {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()} == after


def test_dependency_only_utc_is_not_selected_context(tmp_path):
    from leonardo.financial_tools import resolve_parameters, resolve_output_names
    from leonardo.recipes import build_portable_recipe, PortableRecipeDependencyV1
    service, _, recipes, _ = _domain(tmp_path)
    pt = _leaf("peaks_troughs", {})
    utc = _utc_recipe(pt, roles=("trend_peak", "trend_trough", "range_peak", "range_trough"))
    for recipe in (pt, utc):
        recipes.save_recipe(recipe)
    parameters = dict(resolve_parameters("angle", {}))
    angle = build_portable_recipe(
        tool_key="angle", kind="construct", parameters=parameters,
        output_names=resolve_output_names("angle", {**parameters, "source": "__research_source"}),
        dependencies=(PortableRecipeDependencyV1("source", utc.recipe_id, "hor_upper"),),
    )
    materialization = _materialize(service, recipes, angle)
    collection = service.create_artifact_collection(materialization, "UTC dependency")
    seed = service.create_database_seed(MARKET, "Derived values only")
    manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
    loaded = service.load_database_revision(manifest.database_id)
    assert any(m["tool_key"] == "universal_trend_classifier" for m in manifest.to_dict()["value_provenance"]["members"])
    assert loaded.utc_classification is None
    assert manifest.to_dict()["schema_version"] != "6.0"


def test_append_rejects_changed_confirmed_facts_without_mutating_database(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from leonardo.data_manager.utc_classification_snapshot import _capture_snapshot
    service, artifacts, historical, materialization, original = utc_database(tmp_path, collection=True)
    previous = service.load_database_revision(original.database_id)
    _append(historical)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids))
    appended = service.execute_database_append(service.plan_database_update(original.database_id)).database_revision
    store = service._creation.store
    before = {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()}
    original_load = artifacts.load_artifact_by_id
    def changed_report(*args, **kwargs):
        loaded = original_load(*args, **kwargs)
        analysis = loaded.analysis
        # Keep this original frozen-fact test deliberately V1-only. A stale
        # metrics binding is rejected earlier and is covered independently.
        analysis.pop("utc_episode_metrics", None)
        analysis["utc_classification"]["episodes"][0]["origin"] = "unknown"
        return SimpleNamespace(metadata=loaded.metadata, analysis=analysis)
    monkeypatch.setattr(artifacts, "load_artifact_by_id", changed_report)
    with pytest.raises(DataManagerCreationError, match="confirmed UTC formation changed"):
        _capture_snapshot(appended, artifacts, previous)
    assert {p: p.read_bytes() for p in store.root_dir.rglob("*") if p.is_file()} == before


def test_updated_utc_uses_current_physical_dependencies_in_artifact_and_database(tmp_path):
    service, artifacts, historical, materialization, original = utc_database(tmp_path, collection=True)
    old_database = service.load_database_revision(original.database_id)
    before_ids = {m.tool_key: m.artifact_id for m in materialization.managed_artifacts}
    old_utc = artifacts.load_artifact_by_id(MARKET, before_ids["universal_trend_classifier"])
    _append(historical)
    updated = service.execute_artifact_update(
        service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids))
    after_ids = {m.tool_key: m.artifact_id for m in updated.materialization.managed_artifacts}
    assert after_ids["peaks_troughs"] != before_ids["peaks_troughs"]
    utc = artifacts.load_artifact_by_id(MARKET, after_ids["universal_trend_classifier"])
    expected = sorted({ref.artifact_id for ref in utc.metadata.recipe.source_artifacts})
    assert expected == [after_ids["peaks_troughs"]]
    assert utc.analysis["utc_classification"]["context"]["dependency_ids"] == expected
    appended = service.execute_database_append(service.plan_database_update(original.database_id)).database_revision
    loaded = service.load_database_revision(original.database_id)
    reports = _decode_snapshot(loaded.utc_classification, appended)["reports"]
    assert utc.analysis in reports.values()
    assert old_utc.analysis in reports.values()
    assert all("utc_episode_metrics" in report for report in reports.values())
    assert utc.analysis["utc_episode_metrics"]["classification_sha256"] != old_utc.analysis["utc_episode_metrics"]["classification_sha256"]
    assert service.load_database_revision(original.database_id, original.revision_id) == old_database
    assert artifacts.load_artifact_by_id(MARKET, before_ids["universal_trend_classifier"]).analysis == old_utc.analysis


def _resign_measurement_snapshot(manifest, payload):
    from leonardo.artifacts.serialization import encode_analysis_json
    remapped = {digest: sha256(encode_analysis_json(report)).hexdigest() for digest, report in payload["reports"].items()}
    payload["reports"] = {remapped[digest]: report for digest, report in payload["reports"].items()}
    for association in payload["associations"]:
        association["report_sha256"] = remapped[association["report_sha256"]]
    data = canonical_json_bytes(payload)
    value = manifest.to_dict(include_revision_id=False)
    value["utc_classification"]["sha256"] = sha256(data).hexdigest()
    value["revision_id"] = deterministic_hash(value)
    return database_revision_from_dict(value), data


def test_rehashed_database_snapshot_still_rejects_broken_metrics_binding(tmp_path):
    service, _, _, _, manifest = utc_database(tmp_path)
    loaded = service.load_database_revision(manifest.database_id)
    payload = _decode_snapshot(loaded.utc_classification, manifest)
    next(iter(payload["reports"].values()))["utc_episode_metrics"]["classification_sha256"] = "0"*64
    altered, data = _resign_measurement_snapshot(manifest, payload)
    with pytest.raises(DataManagerCreationError, match="metrics classification binding"):
        _decode_snapshot(data, altered)
    assert service.load_database_revision(manifest.database_id) == loaded


def test_retained_v1_provider_is_not_enriched_from_live_source(tmp_path, monkeypatch):
    from dataclasses import replace
    from leonardo.data_manager.utc_classification_snapshot import _capture_snapshot
    service, artifacts, _, _, manifest = utc_database(tmp_path)
    loaded = service.load_database_revision(manifest.database_id)
    payload = _decode_snapshot(loaded.utc_classification, manifest)
    for report in payload["reports"].values(): report.pop("utc_episode_metrics")
    v1_manifest, v1_data = _resign_measurement_snapshot(manifest, payload)
    previous = replace(loaded, manifest=v1_manifest, utc_classification=v1_data)
    monkeypatch.setattr(artifacts, "load_artifact_by_id", lambda *a, **k: pytest.fail("V1 metrics were invented from live source"))
    captured, data = _capture_snapshot(v1_manifest, artifacts, previous)
    assert all(set(report) == {"utc_classification"} for report in _decode_snapshot(data, captured)["reports"].values())
    assert service.load_database_revision(manifest.database_id) == loaded
