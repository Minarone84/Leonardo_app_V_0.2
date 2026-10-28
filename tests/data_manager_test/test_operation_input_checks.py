from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.data_manager import DataManagerArtifactMaterializationRequest, BatchArtifactRequest, BatchArtifactBranchRequest
from leonardo.data_manager.construct_batch import visible_output_names
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactRequest, DataManagerDirectArtifactSource
from tests.data_manager_test.test_update_workflow import MARKET, _domain, _materialize, _sma, _derivative, _append


def _reads(monkeypatch):
    counts = Counter()
    original = Path.open

    def opened(path, mode="r", *args, **kwargs):
        if path.name in {"values.csv", "analysis.json", "candles.csv"} and "r" in mode:
            counts[str(path)] += 1
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    return counts


def _artifact_reads(counts):
    return {Path(path).parent.name: count for path, count in counts.items()
            if Path(path).name == "values.csv" and "artifacts" in Path(path).parts}


def _graph(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    leaf = _sma(3)
    recipes.save_recipe(leaf)
    result = _materialize(service, recipes, _derivative(leaf))
    unrelated = _materialize(service, recipes, _sma(9))
    return service, artifacts, recipes, historical, result, unrelated


def test_direct_and_recipe_discovery_do_not_check_unrelated_values(tmp_path, monkeypatch):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    counts = _reads(monkeypatch)
    catalog = service.build_direct_artifact_catalog(MARKET)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(MARKET, (recipes.list_recipe_summaries()[0].recipe_id,))
    )
    service.plan_artifact_collection_selection(MARKET, result.root_logical_artifact_ids)
    assert catalog.construct_options and plan.nodes
    assert not counts


@pytest.mark.parametrize("route", ("direct", "recipe"))
def test_materialization_checks_only_consumed_inputs_once(tmp_path, monkeypatch, route):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    if route == "recipe":
        recipe = _sma(7)
        recipes.save_recipe(recipe)
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(MARKET, (recipe.recipe_id,))
        )
        work = lambda: service.execute_artifact_materialization(plan)
        expected = set()
    else:
        entry = next(item for item in result.managed_artifacts if item.tool_key == "sma")
        request = DataManagerDirectArtifactRequest(
            MARKET, artifacts.source_metadata(MARKET), "derivative", {"order": 2},
            (DataManagerDirectArtifactSource("source", entry.logical_artifact_id, entry.artifact_id, entry.output_names[0]),),
        )
        work = lambda: service.create_direct_artifact(request)
        expected = {entry.artifact_id}
    counts = _reads(monkeypatch)
    work()
    assert _artifact_reads(counts) == {identity: 1 for identity in expected}


def test_fresh_collection_reuses_verified_outputs_and_reports_real_reuse(tmp_path, monkeypatch):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    assert len(result.verified_artifact_metadata) == 2
    counts = _reads(monkeypatch)
    events = []
    with service._operation_checks(progress=lambda *event: events.append(event)):
        revision = service.create_artifact_collection(result, "Fresh")
    assert len(revision.members) == 2
    assert not counts
    assert len(events) == 2
    assert all("Reusing completed check" in event[2] for event in events)


def test_existing_collection_checks_exact_members_once_and_can_cancel(tmp_path, monkeypatch):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    plan = service.plan_artifact_collection_selection(MARKET, result.root_logical_artifact_ids)
    counts = _reads(monkeypatch)
    events = []
    with service._operation_checks(progress=lambda *event: events.append(event)):
        service.create_artifact_collection_from_selection(plan, "Existing")
    assert _artifact_reads(counts) == {entry.artifact_id: 1 for entry in result.managed_artifacts}
    assert [event[:2] for event in events] == [(1, 2), (2, 2)]


def test_bad_selected_artifact_names_failure_and_prevents_collection(tmp_path):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    plan = service.plan_artifact_collection_selection(MARKET, result.root_logical_artifact_ids)
    identity = result.managed_artifacts[0].artifact_id
    path = next(path for path in historical.rglob("values.csv") if path.parent.name == identity)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match=identity):
        service.create_artifact_collection_from_selection(plan, "Broken")
    assert service.list_artifact_collections() == ()


def test_collection_add_remove_does_not_rescan_retained_or_removed_values(tmp_path, monkeypatch):
    service, artifacts, recipes, historical = _domain(tmp_path)
    first = _materialize(service, recipes, _sma(3))
    second = _materialize(service, recipes, _sma(5))
    collection = service.create_artifact_collection(first, "Membership")
    plan = service.plan_artifact_collection_selection(
        MARKET, (*first.root_logical_artifact_ids, *second.root_logical_artifact_ids)
    )
    counts = _reads(monkeypatch)
    changed = service.edit_artifact_collection_from_selection(
        collection.collection_id, plan, expected_revision_id=collection.revision_id
    )
    assert _artifact_reads(counts) == {second.managed_artifacts[0].artifact_id: 1}
    counts.clear()
    removed = service.revise_artifact_collection(
        changed.collection_id, remove_root_logical_artifact_ids=second.root_logical_artifact_ids
    )
    assert removed.root_logical_artifact_ids == first.root_logical_artifact_ids
    assert not counts


def test_seed_to_database_uses_trusted_snapshot_without_live_source(tmp_path, monkeypatch):
    service, artifacts, recipes, historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "Old Seed")
    _append(historical)
    def forbidden(*args, **kwargs):
        raise AssertionError("trusted snapshot invoked live/strict validation")
    monkeypatch.setattr(artifacts, "capture_accepted_source", forbidden)
    monkeypatch.setattr(service.creation_store, "load_seed", forbidden)
    plan = service.plan_seed_only_database_creation(seed.seed_id, "Snapshot")
    database = service.execute_seed_only_database_creation(plan)
    assert database.source_ohlcv == seed.source_ohlcv
    assert database.row_count == seed.row_count


def test_collection_edit_checks_retained_required_support_not_unrelated_member(tmp_path, monkeypatch):
    service, artifacts, recipes, historical = _domain(tmp_path)
    base = _sma(3)
    old = _materialize(service, recipes, base, _sma(5))
    collection = service.create_artifact_collection(old, "Original")
    branch = _materialize(service, recipes, _derivative(base))
    plan = service.plan_artifact_collection_selection(
        MARKET, (*old.root_logical_artifact_ids, *branch.root_logical_artifact_ids)
    )
    counts = _reads(monkeypatch)
    edited = service.edit_artifact_collection_from_selection(
        collection.collection_id, plan, expected_revision_id=collection.revision_id
    )
    assert _artifact_reads(counts) == {item.artifact_id: 1 for item in branch.managed_artifacts}
    counts.clear()
    removal = service.plan_artifact_collection_selection(MARKET, old.root_logical_artifact_ids)
    service.edit_artifact_collection_from_selection(
        collection.collection_id, removal, expected_revision_id=edited.revision_id
    )
    assert not counts


def test_database_import_and_remove_trust_snapshot_and_check_only_imports(tmp_path, monkeypatch):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    seed = service.create_database_seed(MARKET, "Seed")
    database = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Database")
    )
    def forbidden(*args, **kwargs):
        raise AssertionError("internal snapshot use called strict loader")
    monkeypatch.setattr(service.creation_store, "load_database_revision", forbidden)
    plan = service.plan_database_artifact_addition(database.database_id, result.root_logical_artifact_ids)
    counts = _reads(monkeypatch)
    imported = service.execute_database_content_edit(plan)
    assert _artifact_reads(counts) == {item.artifact_id: 1 for item in result.managed_artifacts}
    counts.clear()
    plan = service.plan_database_content_edit(
        database.database_id,
        remove_outputs=tuple((item.logical_artifact_id, item.output_name) for item in imported.selected_outputs),
    )
    service.execute_database_content_edit(plan)
    assert not _artifact_reads(counts)


def test_legacy_materialization_without_runtime_evidence_still_checks(tmp_path, monkeypatch):
    service, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    counts = _reads(monkeypatch)
    service.create_artifact_collection(replace(result, verified_artifact_metadata=()), "Compatibility")
    assert _artifact_reads(counts) == {item.artifact_id: 1 for item in result.managed_artifacts}


@pytest.mark.parametrize("destination", ("new_collection", "collection_revision"))
def test_batch_collection_check_cancellation_preserves_collection_head(tmp_path, monkeypatch, destination):
    service, artifacts, recipes, historical = _domain(tmp_path)
    base = _materialize(service, recipes, _sma(3))
    unrelated = _materialize(service, recipes, _sma(9))
    collection = service.create_artifact_collection(base, "Existing")
    entry = base.managed_artifacts[0]
    source = DataManagerDirectArtifactSource(
        "source", entry.logical_artifact_id, entry.artifact_id, entry.output_names[0]
    )
    branch = BatchArtifactBranchRequest(
        "derivative", {"order": 1}, (source,),
        visible_output_names("derivative", {"order": 1}, (source,)),
    )
    plan = service.plan_batch_artifacts(BatchArtifactRequest(
        MARKET, base.source_ohlcv, (branch,), destination,
        collection.collection_id if destination == "collection_revision" else None,
    ))
    counts = _reads(monkeypatch)
    cancelled = False
    checks = []

    def progress(current, total, message):
        nonlocal cancelled
        if "Reusing completed check" in message:
            checks.append((current, total, message))
            cancelled = True

    with pytest.raises(ValueError, match="cancelled"):
        service.execute_batch_artifacts(
            plan, progress=progress, cancellation_requested=lambda: cancelled
        )
    assert checks
    assert service.list_artifact_collections() == (collection,)
    assert _artifact_reads(counts) == {entry.artifact_id: 1}
    # Artifacts independently published before the Collection check are retained.
    assert len(artifacts.list_managed_artifacts_metadata(MARKET)) == 3


def test_missing_csv_blocks_requested_updates_without_invalidating_owned_snapshot(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _sma(3))
    seed = service.create_database_seed(MARKET, "Seed")
    database = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Owned snapshot")
    )
    artifacts._ohlcv_store.csv_path(MARKET).unlink()
    service.invalidate_source(MARKET)
    assert service.plan_artifact_update(MARKET, result.root_logical_artifact_ids).blocked
    assert service.plan_database_update(database.database_id).status == "SOURCE_INVALID"
    assert service.load_database_revision(database.database_id).manifest == database


def _am8_renew_validation(artifacts):
    import hashlib

    store = artifacts._ohlcv_store
    csv_path = store.csv_path(MARKET)
    sidecar_path = store.sidecar_path(MARKET)
    candles = store.read(MARKET)
    before_csv = csv_path.read_bytes()
    before_source = artifacts.source_metadata(MARKET)
    store.publish_validation(
        MARKET,
        expected_csv_size=csv_path.stat().st_size,
        expected_csv_mtime_ns=csv_path.stat().st_mtime_ns,
        expected_csv_sha256=hashlib.sha256(before_csv).hexdigest(),
        expected_sidecar_size=sidecar_path.stat().st_size,
        expected_sidecar_mtime_ns=sidecar_path.stat().st_mtime_ns,
        expected_sidecar_sha256=hashlib.sha256(sidecar_path.read_bytes()).hexdigest(),
        status="ok", row_count=len(candles),
        first_timestamp_ms=candles[0].ts_ms,
        last_timestamp_ms=candles[-1].ts_ms,
        warnings=(), issue_codes=(), error_count=0, warning_count=0,
        validator="am8-renewed-validation",
    )
    assert csv_path.read_bytes() == before_csv
    after_source = artifacts.source_metadata(MARKET)
    assert before_source != after_source
    assert replace(after_source, sidecar_sha256=before_source.sidecar_sha256) == before_source


@pytest.mark.parametrize("change", ("metadata", "newer_ohlcv"))
def test_am8_reviewed_root_removal_survives_live_source_change(tmp_path, monkeypatch, change):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _sma(3), _sma(5))
    collection = service.create_artifact_collection(result, "Removal")
    roots = collection.root_logical_artifact_ids[:1]
    plan = service.plan_artifact_collection_selection(MARKET, roots)
    if change == "metadata":
        _am8_renew_validation(artifacts)
    else:
        _append(historical)
    counts = _reads(monkeypatch)
    revised = service.edit_artifact_collection_from_selection(
        collection.collection_id, plan, expected_revision_id=collection.revision_id,
    )
    assert revised.root_logical_artifact_ids == roots
    assert revised.source_ohlcv == collection.source_ohlcv
    assert revised.members == tuple(
        item for item in collection.members if item.version_key.logical_artifact_id in roots
    )
    assert revised.previous_revision_id == collection.revision_id
    assert not counts


@pytest.mark.parametrize("change", ("metadata", "newer_ohlcv", "missing_ohlcv"))
def test_am8_removal_preview_preserves_saved_dependencies_and_mappings(tmp_path, monkeypatch, change):
    from leonardo.data_manager import ArtifactCollectionOutputV1

    service, artifacts, recipes, historical = _domain(tmp_path)
    base = _sma(3)
    recipes.save_recipe(base)
    branch = _derivative(base)
    result = _materialize(service, recipes, base, branch, _sma(9))
    collection = service.create_artifact_collection(
        result, "Mapped removal", selected_outputs=tuple(
            ArtifactCollectionOutputV1(item.logical_artifact_id, output, f"mapped_{index}")
            for index, item in enumerate(result.managed_artifacts)
            for output in item.output_names
        ),
    )
    retained = next(item for item in result.managed_artifacts if item.tool_key == "derivative")
    roots = (retained.logical_artifact_id,)
    if change == "metadata":
        _am8_renew_validation(artifacts)
    elif change == "newer_ohlcv":
        _append(historical)
    else:
        artifacts._ohlcv_store.csv_path(MARKET).unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("removal consulted live OHLCV or Artifact payloads")

    monkeypatch.setattr(artifacts, "capture_accepted_source", forbidden)
    monkeypatch.setattr(artifacts, "source_metadata", forbidden)
    monkeypatch.setattr(artifacts, "load_artifact_by_id", forbidden)
    counts = _reads(monkeypatch)
    plan = service.plan_artifact_collection_selection(
        MARKET, roots, collection_id=collection.collection_id,
        expected_revision_id=collection.revision_id,
    )
    required = service._creation._required_members(roots, collection.dependency_edges)
    expected_members = tuple(
        item for item in collection.members if item.version_key.logical_artifact_id in required
    )
    assert plan.members == expected_members
    assert len(plan.members) == 2
    assert plan.support_logical_artifact_ids == tuple(
        item.version_key.logical_artifact_id for item in expected_members
        if item.version_key.logical_artifact_id not in roots
    )
    assert plan.dependency_edges == collection.dependency_edges
    assert plan.execution_stages == (plan.support_logical_artifact_ids, roots)
    revised = service.edit_artifact_collection_from_selection(
        collection.collection_id, plan, expected_revision_id=collection.revision_id,
    )
    assert revised.members == plan.members
    assert revised.source_ohlcv == collection.source_ohlcv
    assert revised.first_timestamp_ms == collection.first_timestamp_ms
    assert revised.last_timestamp_ms == collection.last_timestamp_ms
    assert revised.selected_outputs == tuple(
        item for item in collection.selected_outputs if item.logical_artifact_id in required
    )
    assert revised.presentation_order == tuple(
        item for item in collection.presentation_order
        if item in {output.column_name for output in revised.selected_outputs}
    )
    assert service.load_artifact_collection(collection.collection_id, collection.revision_id) == collection
    assert not counts


@pytest.mark.parametrize("moment", ("preview", "execution"))
def test_am8_removal_rejects_stale_collection_revision(tmp_path, monkeypatch, moment):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _sma(3), _sma(5))
    collection = service.create_artifact_collection(result, "Stale")
    roots = collection.root_logical_artifact_ids[:1]
    if moment == "execution":
        plan = service.plan_artifact_collection_selection(
            MARKET, roots, collection_id=collection.collection_id,
            expected_revision_id=collection.revision_id,
        )
    changed = service.revise_artifact_collection(collection.collection_id, display_name="Changed")

    def forbidden(*args, **kwargs):
        raise AssertionError("stale removal consulted live OHLCV")

    monkeypatch.setattr(artifacts, "capture_accepted_source", forbidden)
    with pytest.raises(ValueError, match="revision changed before Edit"):
        if moment == "preview":
            service.plan_artifact_collection_selection(
                MARKET, roots, collection_id=collection.collection_id,
                expected_revision_id=collection.revision_id,
            )
        else:
            service.edit_artifact_collection_from_selection(
                collection.collection_id, plan, expected_revision_id=collection.revision_id,
            )
    assert service.load_artifact_collection(collection.collection_id) == changed
    assert len(service.list_artifact_collection_revisions(collection.collection_id)) == 2


@pytest.mark.parametrize("route", ("creation", "addition", "same_roots"))
def test_am8_non_removal_checks_source_without_requiring_matching_sidecar_hash(tmp_path, monkeypatch, route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _sma(3), _sma(5))
    collection = service.create_artifact_collection(result, "Strict")
    extra = _materialize(service, recipes, _sma(9))
    _am8_renew_validation(artifacts)
    roots = collection.root_logical_artifact_ids
    context = {"collection_id": collection.collection_id, "expected_revision_id": collection.revision_id}
    if route == "creation":
        roots = roots[:1]
        context = {}
    elif route == "addition":
        roots = (*roots, *extra.root_logical_artifact_ids)
    captured = []
    original = artifacts.capture_accepted_source

    def capture(market):
        captured.append(market)
        return original(market)

    monkeypatch.setattr(artifacts, "capture_accepted_source", capture)
    plan = service.plan_artifact_collection_selection(MARKET, roots, **context)
    assert plan.source_ohlcv.row_count == collection.source_ohlcv.row_count
    assert plan.first_timestamp_ms == collection.first_timestamp_ms
    assert plan.last_timestamp_ms == collection.last_timestamp_ms
    assert captured == [MARKET]
    assert service.load_artifact_collection(collection.collection_id) == collection


@pytest.mark.parametrize("moment", ("preview", "execution"))
def test_am8_replacement_is_not_classified_as_saved_removal(tmp_path, monkeypatch, moment):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _sma(3), _sma(5))
    collection = service.create_artifact_collection(result, "Replacement")
    roots = collection.root_logical_artifact_ids[:1]
    context = {"collection_id": collection.collection_id, "expected_revision_id": collection.revision_id}
    old_plan = service.plan_artifact_collection_selection(MARKET, roots, **context)
    _append(historical)
    update = service.plan_artifact_update(MARKET, roots)
    assert not update.blocked
    service.execute_artifact_update(update)
    strict_plan = service.plan_artifact_collection_selection(MARKET, roots)
    assert strict_plan.members != old_plan.members
    captured = []
    original = artifacts.capture_accepted_source

    def capture(market):
        captured.append(market)
        return original(market)

    monkeypatch.setattr(artifacts, "capture_accepted_source", capture)
    if moment == "preview":
        assert service.plan_artifact_collection_selection(MARKET, roots, **context) == strict_plan
    else:
        with pytest.raises(ValueError, match="selection changed since Preview"):
            service.edit_artifact_collection_from_selection(
                collection.collection_id, old_plan, expected_revision_id=collection.revision_id,
            )
    assert captured == [MARKET]
    assert service.load_artifact_collection(collection.collection_id) == collection


@pytest.mark.parametrize("missing", ("collection_id", "expected_revision_id"))
def test_am8_partial_edit_context_is_rejected(tmp_path, missing):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _sma(3), _sma(5))
    collection = service.create_artifact_collection(result, "Context")
    context = {"collection_id": collection.collection_id, "expected_revision_id": collection.revision_id}
    del context[missing]
    with pytest.raises(ValueError, match="requires collection_id and expected_revision_id"):
        service.plan_artifact_collection_selection(MARKET, collection.root_logical_artifact_ids[:1], **context)
