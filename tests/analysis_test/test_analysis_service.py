"""Store-backed Analysis integration and independent backend parity."""
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import StringIO
import json

import numpy as np
import pandas as pd
import pytest

from leonardo.analysis.models import AnalysisRequest, ColumnRequest, DatabaseReference
from leonardo.analysis.service import AnalysisService, AVAILABILITY
from leonardo.artifacts import ArtifactService
from leonardo.data_manager import DataManagerCreationStore
from leonardo.data_manager.creation_models import DatabaseDefinitionV1, database_revision_from_dict, deterministic_hash
from leonardo.financial_tools import (
    BinningPolicy, DirectionalBinningPolicy, VariationContext,
    fit_directional_binning, classify_directional_binning, fit_dynamic_binning, classify_dynamic_binning,
)
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset

AS_OF = 1_900_000_000_000


def make_database(tmp_path, columns=None, *, tool_key="fixture_numeric", store=None, name="Analysis fixture"):
    """Publish actual validated database bytes under a disposable store root."""
    columns = columns if columns is not None else {"delta": [-4., -2., -1., 0., 0.2, 0.4, 0.6, np.nan]}
    size = len(next(iter(columns.values()))) if columns else 8
    market, base = _accepted_dataset(tmp_path / "historical", rows=size)
    fingerprint = ArtifactService(tmp_path / "historical").capture_accepted_source(market)
    store = store or DataManagerCreationStore(tmp_path / "databases")
    identity, seed = store.new_database_id(), store.new_seed_id()
    definition = DatabaseDefinitionV1(identity, name, "Disposable analysis test fixture", market, seed, datetime.now(UTC))
    frame = base[["ts_ms", "close"]].copy()
    for key, values in columns.items():
        frame[key] = values
    values = frame.to_csv(index=False, lineterminator="\n").encode()
    logical, physical, recipe = (sha256((identity + value).encode()).hexdigest() for value in ("logical", "physical", "recipe"))
    members = [] if not columns else [{"logical_artifact_id": logical, "artifact_id": physical,
        "portable_recipe_id": recipe, "tool_key": tool_key, "kind": "construct", "output_names": list(columns), "values_sha256": sha256(values).hexdigest()}]
    payload = dict(schema_version="3.0", object_type="database_revision", database_id=identity,
        display_name=name, description=definition.description, seed_id=seed, market_id=definition.to_dict()["market_id"],
        source_ohlcv=fingerprint.to_dict(), members=members, dependency_edges=[],
        selected_outputs=[dict(logical_artifact_id=logical, output_name=c, column_name=c) for c in columns],
        collection_sources=[], column_mapping={c:c for c in frame}, first_timestamp_ms=int(frame.ts_ms.iloc[0]),
        last_timestamp_ms=int(frame.ts_ms.iloc[-1]), row_count=size, column_count=len(frame.columns),
        values_sha256=sha256(values).hexdigest(), previous_revision_id=None, created_at_utc=definition.to_dict()["created_at_utc"],
        selection_sources=[] if not columns else [dict(source_kind="artifact", source_id=logical, source_revision_id=None, column_names=sorted(columns))])
    payload["revision_id"] = deterministic_hash(payload)
    manifest = database_revision_from_dict(payload)
    store.publish_database_revision(definition, manifest, values, expected_head_revision_id=None)
    return store, manifest, frame


def reference(manifest):
    return DatabaseReference(manifest.database_id, manifest.revision_id, manifest.values_sha256)


def request(manifest, *names, measurement="directional_intensity", positive_bins=10, negative_bins=10, minimum=2):
    policy = DirectionalBinningPolicy(positive_bins, negative_bins, minimum) if measurement == "directional_intensity" else BinningPolicy(min_reference_count=minimum)
    return AnalysisRequest(reference(manifest), tuple(ColumnRequest(name, measurement, policy) for name in names))


def publish_next(store, manifest, frame):
    values = frame.to_csv(index=False, lineterminator="\n").encode()
    payload = manifest.to_dict()
    payload.pop("revision_id")
    payload["previous_revision_id"] = manifest.revision_id
    payload["values_sha256"] = sha256(values).hexdigest()
    payload["revision_id"] = deterministic_hash(payload)
    updated = database_revision_from_dict(payload)
    store.publish_database_revision(store.load_database_definition(manifest.database_id), updated, values, expected_head_revision_id=manifest.revision_id)
    return updated


def files(root):
    return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode', ['directional_intensity', 'value', 'magnitude'])
def test_fit_progress_is_indeterminate_and_completed_columns_keep_real_counts(tmp_path, mode):
    store, manifest, _ = make_database(tmp_path, {'first': [-2., -1., 0., 1.], 'second': [-3., 0., 1., 2.]})
    events = []
    def progress(message, current=None, total=None):
        events.append((message, current, total))
    result = AnalysisService(store, clock_ms=lambda: AS_OF).run(
        request(manifest, 'first', 'second', measurement=mode), progress=progress)
    assert [event for event in events if event[0].startswith('Fitting')] == [
        ('Fitting first (1/2)', None, None), ('Fitting second (2/2)', None, None)]
    assert [event for event in events if event[0].startswith('Completed')] == [
        ('Completed first', 1, 2), ('Completed second', 2, 2)]
    assert [column.outcome for column in result.columns] == ['completed', 'completed']


@pytest.mark.parametrize("mode", ("directional_intensity", "value", "magnitude"))
@pytest.mark.parametrize("values", (
    [-9., -3., -3., -1., 0., .1, .2, .2, .9, np.nan],
    [np.nan, 1., 2., 2., 4., 8., np.nan, 3., 7., np.nan],
    [-1., -2., -2., -4., -8., -3., -5., -9., -7., -6.],
    [0.] * 10, [-2.] * 10, [2.] * 10,
))
def test_exact_backend_parity_and_preserved_rows(tmp_path, mode, values):
    store, manifest, frame = make_database(tmp_path, {"delta": values})
    service = AnalysisService(store, clock_ms=lambda: AS_OF, classification_chunk_size=3)
    before = files(store.root_dir)
    req = request(manifest, "delta", measurement=mode)
    result = service.run(req)
    actual = result.columns[0]
    profile = actual.profile
    data = frame[["ts_ms", "delta"]].copy()
    data["available_at_ms"] = AS_OF
    args = dict(profile_id=profile.profile_id, calibration_as_of_ms=AS_OF, provenance=profile.provenance, policy=req.columns[0].policy)
    if mode == "directional_intensity":
        expected_profile = fit_directional_binning(data, profile.context, **args)
        expected = classify_directional_binning(data, expected_profile, context=profile.context, mode="retrospective").to_frame()
        assert len(actual.to_frame().columns) == 35
    else:
        expected_profile = fit_dynamic_binning(data, profile.context, measurement=mode, **args)
        expected = classify_dynamic_binning(data, expected_profile, context=profile.context, mode="retrospective").to_frame()
        assert len(actual.bins) == 7
    pd.testing.assert_frame_equal(actual.to_frame(), expected)
    assert profile.to_dict() == expected_profile.to_dict()
    assert len(actual.to_frame()) == len(values)
    assert actual.to_frame().raw_value.isna().tolist() == pd.isna(values).tolist()
    assert actual.to_frame().available_at_ms.eq(AS_OF).all()
    assert f"availability:{AVAILABILITY}" in profile.provenance
    assert files(store.root_dir) == before


@pytest.mark.parametrize("positive,negative", ((1,1),(10,10),(1000,1000),(3,17)))
def test_bin_resolution_empty_bins_and_column_isolation(tmp_path, positive, negative):
    store, manifest, _ = make_database(tmp_path, {"delta": [-8., -2., -1., 0., .1, .2, .2, .7], "unrelated": [900., 850., 34., 4., 4., 45., 99., 2.]})
    service = AnalysisService(store, clock_ms=lambda: AS_OF)
    alone = service.run(request(manifest, "delta", positive_bins=positive, negative_bins=negative)).columns[0]
    together = service.run(request(manifest, "delta", "unrelated", positive_bins=positive, negative_bins=negative))
    first, other = together.columns
    assert alone.profile.analysis.to_dict() == first.profile.analysis.to_dict()
    pd.testing.assert_frame_equal(alone.to_frame().drop(columns="profile_id"), first.to_frame().drop(columns="profile_id"))
    assert first.profile.profile_id != other.profile.profile_id != alone.profile.profile_id
    assert len(first.bins) == positive + negative
    assert sum(b.count for b in first.bins) == 7
    assert len(other.bins) == positive + negative
    assert first.profile.analysis.negative.values != first.profile.analysis.positive.values


def test_mixed_modes_overrides_and_all_missing_outcome(tmp_path):
    store, manifest, _ = make_database(tmp_path, {"directional": [-2, -1, 0, 1], "signed": [-9, 1, 2, 3], "absolute": [-8, 1, 2, 4], "missing": [np.nan]*4})
    req = AnalysisRequest(reference(manifest), (
        ColumnRequest("directional", "directional_intensity", DirectionalBinningPolicy(3, 7, 2)),
        ColumnRequest("signed", "value", BinningPolicy(min_reference_count=2), True),
        ColumnRequest("absolute", "magnitude", BinningPolicy(min_reference_count=2), True),
        ColumnRequest("missing", "directional_intensity", DirectionalBinningPolicy()),
    ))
    result = AnalysisService(store, clock_ms=lambda: AS_OF).run(req)
    assert result.has_issues and len(result.columns) == 4
    missing = result.columns[-1]
    assert missing.profile is None and missing.outcome == "insufficient_reference"
    assert missing.bins == () and len(missing.to_frame()) == 4
    assert missing.to_frame().status.eq("missing_value").all()
    assert [c.request.override for c in result.columns] == [False,True,True,False]
    assert len(result.columns[0].bins) == 10
    assert len(result.columns[1].bins) == len(result.columns[2].bins) == 7


def test_pinned_revision_survives_head_change(tmp_path):
    store, manifest, original = make_database(tmp_path)
    service = AnalysisService(store, clock_ms=lambda: AS_OF)
    catalog_reference = service.catalog().entries[0].reference
    changed = original.copy()
    changed["delta"] = np.arange(len(changed)) * 100.0
    head = publish_next(store, manifest, changed)
    assert service.load_columns(catalog_reference).entry.reference == reference(manifest)
    result = service.run(request(manifest, "delta"))
    assert result.entry.reference == reference(manifest)
    np.testing.assert_equal(result.columns[0].to_frame().raw_value.to_numpy(dtype=float, na_value=np.nan), original.delta.to_numpy())
    assert service.catalog().entries[0].reference == reference(head)


@pytest.mark.parametrize("failure", ("hash", "removed", "manifest", "shape", "timestamp", "utf8"))
def test_corrupt_or_removed_revision_fails_without_result(tmp_path, failure):
    store, manifest, _ = make_database(tmp_path)
    folder = store.root_dir/'databases'/manifest.database_id/'revisions'/manifest.revision_id
    values = folder/'values.csv'
    if failure == "removed":
        values.unlink()
    elif failure == "manifest":
        (folder/'manifest.json').write_text('{}')
    else:
        raw = values.read_bytes()
        if failure == "shape": raw = raw.replace(b'ts_ms,close,delta', b'ts_ms,close')
        elif failure == "timestamp":
            lines = raw.splitlines(); lines[2] = lines[1]; raw = b'\n'.join(lines)+b'\n'
        elif failure == "utf8": raw = b'\xff'+raw[1:]
        else: raw += b'corrupted'
        values.write_bytes(raw)
    before = files(store.root_dir)
    with pytest.raises((ValueError, OSError)):
        AnalysisService(store).run(request(manifest, "delta"))
    assert files(store.root_dir) == before


def test_selection_identity_and_policy_are_validated_before_fit(tmp_path):
    store, manifest, _ = make_database(tmp_path)
    service = AnalysisService(store)
    with pytest.raises(ValueError, match="selected reference"):
        service.load_columns(replace(reference(manifest), values_sha256="0"*64))
    with pytest.raises(ValueError, match="unavailable or ineligible"):
        service.run(request(manifest, "alien"))
    with pytest.raises(ValueError, match="unique"):
        request(manifest, "delta", "delta")
    with pytest.raises(ValueError):
        AnalysisRequest.from_configuration(reference(manifest), {"database_id":"foreign", "reference":"full_history", "columns":()})
    with pytest.raises(ValueError):
        ColumnRequest("delta", "directional_intensity", BinningPolicy())
    with pytest.raises(ValueError, match="canonical"):
        DatabaseReference(manifest.database_id, "../../outside", manifest.values_sha256)


@pytest.mark.parametrize("values,reason", ((["bad","2"], "nonnumeric"), (["1e999","2"], "nonfinite"), (["True","False"], "nonnumeric")))
def test_invalid_column_tokens_are_not_coerced_to_missing(tmp_path, values, reason):
    store, manifest, _ = make_database(tmp_path, {"bad": values})
    service = AnalysisService(store)
    column = next(c for c in service.load_columns(reference(manifest)).columns if c.name == "bad")
    assert not column.eligible and reason in column.reason
    with pytest.raises(ValueError, match="ineligible"):
        service.run(request(manifest, "bad"))


def test_known_categorical_and_reserved_columns_are_excluded(tmp_path):
    store, manifest, _ = make_database(tmp_path, {"state":[1.,2.], "width":[.1,.2], "compression":[.01,.02]}, tool_key="braids")
    columns = {c.name:c for c in AnalysisService(store).load_columns(reference(manifest)).columns}
    assert not columns["ts_ms"].eligible
    assert not columns["state"].eligible and "categorical" in columns["state"].reason
    assert columns["width"].eligible and columns["compression"].eligible


def test_future_time_and_catalog_failures_are_explicit(tmp_path, monkeypatch):
    store, manifest, _ = make_database(tmp_path)
    with pytest.raises(ValueError, match="future timestamps"):
        AnalysisService(store, clock_ms=lambda: manifest.first_timestamp_ms - 1).run(request(manifest,"delta"))
    (store.root_dir/'databases'/manifest.database_id/'head.json').write_text('{}')
    catalog = AnalysisService(store).catalog()
    assert not catalog.entries and len(catalog.issues) == 1
    monkeypatch.setattr(store, 'list_database_ids', lambda: (_ for _ in ()).throw(OSError('scan failed')))
    with pytest.raises(OSError, match="scan failed"):
        AnalysisService(store).catalog()


def test_metadata_is_explicitly_snapshot_only_and_chart_reduction_is_display_only(tmp_path):
    values = np.linspace(-10., 100., 2200)
    store, manifest, _ = make_database(tmp_path, {"percent_named_but_untyped": values})
    outcome = AnalysisService(store).run(request(manifest,"percent_named_but_untyped")).columns[0]
    assert outcome.column.unit == "unspecified_database_native_unit"
    assert not outcome.column.type_known
    definition = json.loads(outcome.profile.context.parameter_definition)
    assert definition['formula'] == definition['unit'] == 'not_recorded'
    assert definition['revision_id'] == manifest.revision_id
    assert outcome.distribution.reduced and len(outcome.distribution.points) == 2000
    assert outcome.distribution.points[0][0] == values[0] and outcome.distribution.points[-1] == (values[-1],1.)
    assert outcome.profile.analysis.valid_count == len(values) == len(outcome.to_frame())


@pytest.mark.parametrize("version", ("1.0","2.0","3.0","4.0","5.0"))
def test_real_persisted_manifest_versions_including_legacy_outputs(tmp_path, version):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    from tests.data_manager_test.test_update_workflow import _domain
    domain, _artifacts, recipes, _historical = _domain(tmp_path)
    manifest, _collection, _roots, _values = _a2_snapshot(domain, recipes, "1.0" if version == "5.0" else version)
    if version == "5.0":
        plan = domain.plan_database_content_edit(manifest.database_id)
        manifest = domain.execute_database_content_edit(domain.plan_database_content_edit(manifest.database_id, remove_columns=(plan.selected_outputs[0].column_name,)))
    assert manifest.schema_version == version
    service = AnalysisService(domain.creation_store)
    before = files(domain.creation_store.root_dir)
    columns = service.load_columns(reference(manifest))
    selected = [c.name for c in columns.columns if c.eligible]
    assert selected
    result = service.run(request(manifest, *selected))
    assert len(result.columns) == len(selected)
    assert all(len(c.to_frame()) == manifest.row_count for c in result.columns)
    assert files(domain.creation_store.root_dir) == before


def test_seed_only_snapshot_needs_no_upstream_runtime_objects(tmp_path):
    from tests.data_manager_test.test_update_workflow import _domain, MARKET
    domain, _artifacts, _recipes, _historical = _domain(tmp_path)
    seed = domain.create_database_seed(MARKET, "Seed")
    manifest = domain.execute_seed_only_database_creation(domain.plan_seed_only_database_creation(seed.seed_id, "Base only"))
    service = AnalysisService(domain.creation_store)
    assert service.run(request(manifest,"close")).columns[0].outcome == 'completed'


@pytest.mark.parametrize('failure', ('header', 'row_width', 'row_count', 'timestamp', 'utf8'))
def test_structure_is_validated_even_when_payload_hash_matches(tmp_path, failure):
    store, manifest, _ = make_database(tmp_path)
    raw = store.load_database_revision(manifest.database_id).values_csv
    lines = raw.splitlines()
    if failure == 'header': lines[0] = b'ts_ms,close,close'
    elif failure == 'row_width': lines[1] += b',extra'
    elif failure == 'row_count': lines.pop()
    elif failure == 'timestamp': lines[2] = lines[1]
    else: lines[1] = b'\xff' + lines[1]
    raw = b'\n'.join(lines) + b'\n'
    payload = manifest.to_dict()
    payload.pop('revision_id')
    payload['values_sha256'] = sha256(raw).hexdigest()
    payload['revision_id'] = deterministic_hash(payload)
    candidate = database_revision_from_dict(payload)
    folder = store.root_dir/'databases'/candidate.database_id/'revisions'/candidate.revision_id
    folder.mkdir()
    (folder/'values.csv').write_bytes(raw)
    (folder/'manifest.json').write_bytes(candidate.canonical_json_bytes())
    with pytest.raises(ValueError) as error:
        AnalysisService(store).run(request(candidate,'delta'))
    assert 'hash does not match' not in str(error.value)


def test_unexpected_backend_failure_aborts_run_without_partial_result(tmp_path,monkeypatch):
    import leonardo.analysis.service as module
    store,manifest,_=make_database(tmp_path,{'first':[-2,-1,0,1], 'second':[-3,0,1,2]})
    original=module.fit_directional_binning
    calls=[]
    def fit(data,context,**kw):
        calls.append(context.source)
        if context.source=='second':
            raise RuntimeError('unexpected engine failure')
        return original(data,context,**kw)
    monkeypatch.setattr(module,'fit_directional_binning',fit)
    with pytest.raises(RuntimeError,match='unexpected engine failure'):
        AnalysisService(store).run(request(manifest,'first','second'))
    assert calls==['first','second']
