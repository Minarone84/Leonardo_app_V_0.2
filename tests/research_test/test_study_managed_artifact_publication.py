from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactLineageError,
    ArtifactSourceRefV1,
    compute_logical_artifact_id,
)
from leonardo.artifacts._stores import _io_path
from leonardo.data_manager import DataManagerService
from leonardo.recipes import PortableRecipeGraphPlanner, PortableRecipeStore
from leonardo.research import (
    AcceptedDatasetCatalog,
    HistoricalDatasetLoader,
    ResearchStudyService,
    StudyEnvironmentStore,
    StudyInputSource,
    StudyOperationCancelled,
    StudySavedLink,
    StudyValidationError,
)
from tests.research_test.test_study_artifact_apply_save import (
    _changed_frame,
    _save_attempt,
)
from tests.research_test.test_study_execution import (
    accepted_context,
    prepare,
    publish_accepted_frame,
)


def _domain(root):
    dataset, artifacts, frame = accepted_context(root / "h")
    recipes = PortableRecipeStore(root / "data_manager")
    service = ResearchStudyService(artifacts, recipes)
    catalog = AcceptedDatasetCatalog(root / "h")
    dms = DataManagerService(
        catalog,
        HistoricalDatasetLoader(catalog),
        artifacts,
        StudyEnvironmentStore(root / "study_environments"),
        recipes,
        PortableRecipeGraphPlanner(recipes),
    )
    return dataset, artifacts, frame, recipes, service, dms


def _bytes(root):
    root = _io_path(root)
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _payload(artifacts, dataset, metadata):
    return artifacts._store.artifact_dir(
        dataset.market_id,
        metadata.recipe.kind,
        metadata.recipe.tool_key,
        metadata.artifact_id,
    )


def _canonical(artifacts, dataset, study, refs=()):
    saved = artifacts.save_calculation(
        dataset.market_id,
        study.result,
        source_artifacts=refs,
        display_name=study.display_name,
    )
    metadata = saved.metadata
    link = StudySavedLink(
        metadata.recipe.kind,
        metadata.recipe.tool_key,
        metadata.recipe.recipe_id,
        metadata.artifact_id,
    )
    return replace(study, saved_link=link), metadata


def _assert_unmanaged(artifacts, dataset, root):
    assert artifacts.list_managed_artifacts(dataset.market_id) == ()
    assert not any("/artifact_versions/" in path for path in _bytes(root))


def test_save_catalog_exact_payload_and_idempotence(tmp_path: Path, monkeypatch):
    dataset, artifacts, _frame, recipes, service, dms = _domain(tmp_path)
    study = prepare(service, dataset, "sma", parameters={"period": 3})
    assert dms.scan_managed_artifacts().artifacts == ()
    saved_payloads = []
    original_save = artifacts.save_calculation

    def capture_save(*args, **kwargs):
        saved = original_save(*args, **kwargs)
        saved_payloads.append(_bytes(_payload(artifacts, dataset, saved.metadata)))
        return saved

    def no_calculation(*args, **kwargs):
        raise AssertionError("Save must use the stored calculation")

    monkeypatch.setattr(artifacts, "save_calculation", capture_save)
    monkeypatch.setattr(
        "leonardo.research.study_execution.calculate_financial_tool", no_calculation
    )
    outcome = service.save_study(
        _save_attempt(study), dataset, study, (study,), description="RSS handoff"
    )
    loaded = artifacts.load_artifact_by_id(dataset.market_id, outcome.saved_link.artifact_id)
    payload_dir = _payload(artifacts, dataset, loaded.metadata)
    assert _bytes(payload_dir) == saved_payloads[0]
    assert loaded.frame.equals(study.result.to_frame().reset_index(drop=True))
    assert tuple(loaded.frame.ts_ms) == dataset.ts_ms
    assert loaded.frame["sma_3"].isna().iloc[:2].all()
    assert loaded.frame["sma_3"].notna().iloc[2:].all()
    assert loaded.metadata.recipe.display_name == study.display_name
    assert loaded.metadata.recipe.description == "RSS handoff"
    assert loaded.metadata.recipe.recipe_id == outcome.saved_link.recipe_id
    dms.reconcile_update_status()
    catalog = dms.scan_product_catalogs().managed_artifacts.artifacts
    assert len(catalog) == 1
    entry = catalog[0]
    portable = recipes.list_recipe_summaries()[0]
    assert entry.valid and entry.rejection_reason == ""
    assert entry.artifact_id == outcome.saved_link.artifact_id
    assert entry.portable_recipe_id == portable.recipe_id
    assert entry.logical_artifact_id == compute_logical_artifact_id(
        dataset.market_id, portable.recipe_id
    )
    assert entry.row_count == dataset.row_count
    versions = artifacts.list_artifact_versions(dataset.market_id, entry.logical_artifact_id)
    assert len(versions) == 1 and versions[0].previous_artifact_id is None
    assert versions[0].artifact_id == entry.artifact_id
    assert versions[0].created_at_utc == loaded.metadata.created_at_utc
    persistence = recipes.load_persistence_metadata(portable.recipe_id)
    assert tuple(origin.origin_kind for origin in persistence.origins) == ("research_save",)
    before = _bytes(tmp_path / "h")
    linked = replace(study, saved_link=outcome.saved_link)
    for candidate in (linked, study, linked, study):
        try:
            repeated = service.save_study(
                _save_attempt(candidate), dataset, candidate, (candidate,),
                description="RSS handoff",
            )
        except ArtifactAlreadyExistsError:
            assert candidate.saved_link is None
        else:
            assert repeated.saved_link == outcome.saved_link
            if candidate.saved_link is not None:
                assert repeated.created is False
        assert _bytes(tmp_path / "h") == before
        assert artifacts.list_artifact_versions(dataset.market_id, entry.logical_artifact_id) == versions
    assert len(recipes.list_recipe_summaries()) == 1
    assert recipes.load_persistence_metadata(portable.recipe_id) == persistence


def test_dependent_study_manages_unmanaged_durable_graph(tmp_path: Path, monkeypatch):
    dataset, artifacts, _frame, recipes, service, dms = _domain(tmp_path)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    linked_sma, sma_metadata = _canonical(artifacts, dataset, sma)
    derivative = prepare(
        service, dataset, "derivative", parameters={"order": 1},
        sources=(StudyInputSource("source", "study", study_id=sma.study_id, output_name="sma_3"),),
        studies=(linked_sma,),
    )
    derivative_refs = (ArtifactSourceRefV1("source", sma_metadata.artifact_id, "sma_3"),)
    linked_derivative, derivative_metadata = _canonical(artifacts, dataset, derivative, derivative_refs)
    root = prepare(
        service, dataset, "angle_momentum", parameters={"n": 3},
        sources=(StudyInputSource("source_1", "study", study_id=derivative.study_id,
                                 output_name=derivative.result.output_names[0]),),
        studies=(linked_sma, linked_derivative),
    )
    dependency_bytes = {
        metadata.artifact_id: _bytes(_payload(artifacts, dataset, metadata))
        for metadata in (sma_metadata, derivative_metadata)
    }
    _assert_unmanaged(artifacts, dataset, tmp_path / "h")
    calls = []
    original = artifacts.publish_managed_artifact_graph

    def capture(prepared, *, expected_source):
        calls.append(tuple(prepared))
        assert all(item.metadata.source_ohlcv == expected_source for item in prepared)
        assert all(item.previous_artifact_id is None for item in prepared)
        return original(prepared, expected_source=expected_source)

    monkeypatch.setattr(artifacts, "publish_managed_artifact_graph", capture)
    saved = service.save_study(
        _save_attempt(root), dataset, root, (linked_sma, linked_derivative, root)
    )
    assert len(calls) == 1
    graph = calls[0]
    assert tuple(item.metadata.artifact_id for item in graph) == (
        sma_metadata.artifact_id, derivative_metadata.artifact_id, saved.saved_link.artifact_id
    )
    assert graph[0].metadata.recipe.source_artifacts == ()
    assert graph[1].metadata.recipe.source_artifacts == derivative_refs
    assert graph[2].metadata.recipe.source_artifacts == (
        ArtifactSourceRefV1("source_1", derivative_metadata.artifact_id, derivative.result.output_names[0]),
    )
    for item in graph:
        portable = recipes.load_recipe(item.portable_recipe_id)
        assert portable.tool_key == item.metadata.recipe.tool_key
        versions = artifacts.list_artifact_versions(dataset.market_id, item.logical_artifact_id)
        assert len(versions) == 1 and versions[0].artifact_id == item.metadata.artifact_id
        loaded = artifacts.load_artifact_by_id(dataset.market_id, item.metadata.artifact_id)
        assert tuple(loaded.frame.ts_ms) == dataset.ts_ms
    for metadata in (sma_metadata, derivative_metadata):
        assert _bytes(_payload(artifacts, dataset, metadata)) == dependency_bytes[metadata.artifact_id]
    assert {entry.artifact_id for entry in dms.scan_managed_artifacts().artifacts if entry.valid} == {
        item.metadata.artifact_id for item in graph
    }


def test_repeated_dependency_roles_have_one_metadata_owner(tmp_path: Path, monkeypatch):
    dataset, artifacts, _frame, _recipes, service, _dms = _domain(tmp_path)
    peaks = prepare(service, dataset, "peaks_troughs")
    _linked, metadata = _canonical(artifacts, dataset, peaks)
    sources = tuple(
        StudyInputSource(role, "artifact", artifact_kind="indicator",
                         artifact_tool_key="peaks_troughs", artifact_id=metadata.artifact_id,
                         output_name=output)
        for role, output in (("trend_peak", "peak_fractal_5"), ("trend_trough", "trough_fractal_5"),
                             ("range_peak", "peak_fractal_3"), ("range_trough", "trough_fractal_3"))
    )
    study = prepare(service, dataset, "universal_trend_classifier", sources=sources)
    calls = []
    original = artifacts.prepare_managed_calculation

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(artifacts, "prepare_managed_calculation", capture)
    service.save_study(_save_attempt(study), dataset, study, (study,))
    assert len(calls) == 2
    assert calls[0]["source_metadata"] == ()
    assert len(calls[1]["source_artifacts"]) == 4
    assert calls[1]["source_metadata"] == (metadata,)
    assert len(artifacts.list_managed_artifacts(dataset.market_id)) == 2


def test_linked_canonical_only_save_preserves_payload(tmp_path: Path):
    dataset, artifacts, _frame, _recipes, service, dms = _domain(tmp_path)
    study = prepare(service, dataset, "sma", parameters={"period": 3})
    linked, metadata = _canonical(artifacts, dataset, study)
    before = _bytes(_payload(artifacts, dataset, metadata))
    assert dms.scan_managed_artifacts().artifacts == ()
    outcome = service.save_study(_save_attempt(linked), dataset, linked, (linked,))
    assert outcome.created is False and outcome.saved_link == linked.saved_link
    assert _bytes(_payload(artifacts, dataset, metadata)) == before
    entries = dms.scan_managed_artifacts().artifacts
    assert len(entries) == 1 and entries[0].valid
    assert entries[0].artifact_id == metadata.artifact_id


@pytest.mark.parametrize("linked", (False, True))
@pytest.mark.parametrize("at_gate", (False, True))
def test_cancel_before_persistence_has_no_writes(tmp_path: Path, linked, at_gate):
    dataset, artifacts, _frame, _recipes, service, _dms = _domain(tmp_path)
    study = prepare(service, dataset, "sma", parameters={"period": 3})
    if linked:
        study, _metadata = _canonical(artifacts, dataset, study)
    before = _bytes(tmp_path)
    options = {"_begin_persistence": lambda: False} if at_gate else {"cancellation_requested": lambda: True}
    with pytest.raises(StudyOperationCancelled):
        service.save_study(_save_attempt(study), dataset, study, (study,), **options)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("root_state", ("new", "linked"))
def test_publication_failure_rolls_back_only_new_root(tmp_path: Path, monkeypatch, root_state):
    dataset, artifacts, _frame, recipes, service, _dms = _domain(tmp_path)
    unrelated = prepare(service, dataset, "ema", parameters={"period": 3})
    service.save_study(_save_attempt(unrelated), dataset, unrelated, (unrelated,))
    managed_before = artifacts.list_managed_artifacts(dataset.market_id)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    linked_sma, source = _canonical(artifacts, dataset, sma)
    root = prepare(
        service, dataset, "derivative", parameters={"order": 1},
        sources=(StudyInputSource("source", "study", study_id=sma.study_id, output_name="sma_3"),),
        studies=(linked_sma,),
    )
    if root_state != "new":
        linked_root, _metadata = _canonical(
            artifacts, dataset, root, (ArtifactSourceRefV1("source", source.artifact_id, "sma_3"),)
        )
        if root_state == "linked":
            root = linked_root
    prior_ids = {item.artifact_id for item in artifacts.list_artifacts(dataset.market_id)}
    before = _bytes(tmp_path / "h")
    original = artifacts._store.replace_head
    writes = []

    def fail_after_second_head(path, payload):
        original(path, payload)
        writes.append(path)
        if len(writes) == 2:
            raise OSError("injected RSS managed publication failure")

    monkeypatch.setattr(artifacts._store, "replace_head", fail_after_second_head)
    with pytest.raises(ArtifactLineageError, match="injected RSS managed publication failure"):
        service.save_study(_save_attempt(root), dataset, root, (linked_sma, root))
    assert len(writes) == 2
    assert artifacts.list_managed_artifacts(dataset.market_id) == managed_before
    assert {item.artifact_id for item in artifacts.list_artifacts(dataset.market_id)} == prior_ids
    after = _bytes(tmp_path / "h")
    assert all(after[path] == content for path, content in before.items())
    assert {path: data for path, data in after.items() if "/artifact_versions/" in path} == {
        path: data for path, data in before.items() if "/artifact_versions/" in path
    }
    assert len(recipes.list_recipe_summaries()) == 3


@pytest.mark.parametrize("linked", (False, True))
@pytest.mark.parametrize("stage", ("after_prepare", "before_publish", "after_head"))
def test_source_change_never_leaves_managed_publication(tmp_path: Path, monkeypatch, linked, stage):
    dataset, artifacts, frame, _recipes, service, _dms = _domain(tmp_path)
    study = prepare(service, dataset, "sma", parameters={"period": 3})
    if linked:
        study, metadata = _canonical(artifacts, dataset, study)
        before_payload = _bytes(_payload(artifacts, dataset, metadata))
    calls = []
    original_publish = artifacts.publish_managed_artifact_graph

    def change_source():
        publish_accepted_frame(tmp_path / "h", _changed_frame(frame), dataset.market_id)

    def publish(prepared, **kwargs):
        calls.append(tuple(prepared))
        if stage == "before_publish":
            change_source()
        return original_publish(prepared, **kwargs)

    monkeypatch.setattr(artifacts, "publish_managed_artifact_graph", publish)
    if stage == "after_prepare":
        original_prepare = service._publish_portable_recipe

        def prepare_then_change(*args, **kwargs):
            result = original_prepare(*args, **kwargs)
            change_source()
            return result

        monkeypatch.setattr(service, "_publish_portable_recipe", prepare_then_change)
    elif stage == "after_head":
        original_head = artifacts._store.replace_head

        def head_then_change(*args, **kwargs):
            original_head(*args, **kwargs)
            change_source()

        monkeypatch.setattr(artifacts._store, "replace_head", head_then_change)
    with pytest.raises((StudyValidationError, ArtifactLineageError)):
        service.save_study(_save_attempt(study), dataset, study, (study,))
    assert len(calls) == (0 if stage == "after_prepare" else 1)
    _assert_unmanaged(artifacts, dataset, tmp_path / "h")
    if linked:
        assert _bytes(_payload(artifacts, dataset, metadata)) == before_payload
    else:
        assert artifacts.list_artifacts(dataset.market_id) == ()
