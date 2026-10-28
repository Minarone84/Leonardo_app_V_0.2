"""Real Core/DMS ordinary-root long-path publication and source refusal.

Fixture routing and optional receipts use the documented R02 runner parameters
in the companion new regression module; no test patches persistence or results.
"""
from __future__ import annotations

from dataclasses import replace
from threading import Event

import pandas as pd
import pytest

from leonardo.artifacts import ArtifactService
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data_manager import DataManagerArtifactMaterializationRequest, DataManagerCreationStore, DataManagerService
from leonardo.data_manager.application import DataManagerApplicationService
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactRequest
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.ohlcv.store import OHLCVStore
from leonardo.recipes import PortableRecipeGraphPlanner, PortableRecipeStore, build_portable_recipe
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader, StudyEnvironmentStore
from tests.artifacts_test.test_xrepair_r02_path_reads import MARKET, accepted, case_root, deep_root, disk, io, receipt


def domain(base, depth):
    historical = base / "h" if depth == "short" else deep_root(base, 270)
    frame = accepted(historical, rows=12)
    catalog = AcceptedDatasetCatalog(historical)
    artifacts = ArtifactService(historical)
    recipes = PortableRecipeStore(base / "r")
    service = DataManagerService(catalog, HistoricalDatasetLoader(catalog), artifacts,
        StudyEnvironmentStore(base / "e"), recipes, PortableRecipeGraphPlanner(recipes), DataManagerCreationStore(base / "dm"))
    return historical, frame, artifacts, recipes, service


def submit(service, artifacts, recipes, route, period=3):
    source = artifacts.capture_accepted_source(MARKET)
    request = DataManagerDirectArtifactRequest(MARKET, source, "sma", {"period":period}, ())
    parameters = dict(resolve_parameters("sma", {"period":period}))
    recipe = build_portable_recipe(tool_key="sma", kind="indicator", parameters=parameters, output_names=resolve_output_names("sma", parameters))
    if route == "recipe":
        recipes.save_recipe(recipe)
        plan = service.plan_artifact_materialization(DataManagerArtifactMaterializationRequest(MARKET, (recipe.recipe_id,)))
        assert not plan.blocked
    done, results = Event(), []
    runner = CoreRunner(TaskManager())
    app = DataManagerApplicationService(runner, service)
    runner.start()
    try:
        callback = lambda result: (results.append(result), done.set())
        if route == "direct":
            app.submit_create_direct_artifact(request, result_callback=callback)
        else:
            app.submit_execute_artifact_materialization(plan, result_callback=callback)
        assert done.wait(5), "real Core/DMS publication did not settle"
    finally:
        runner.shutdown()
    assert len(results) == 1
    return results[0]


@pytest.mark.parametrize("depth", ("short", "payload"))
@pytest.mark.parametrize("route", ("direct", "recipe"))
def test_core_publication_has_truthful_terminal_and_durable_identity(tmp_path, request, depth, route):
    historical, frame, artifacts, recipes, service = domain(case_root(tmp_path, request), depth)
    source_before = disk(historical)
    result = submit(service, artifacts, recipes, route)
    # Inspect disk even when the original PRE terminal result reports failure.
    persisted = disk(historical)
    control = ArtifactService(io(historical))
    summaries = control.list_managed_artifacts_metadata(MARKET)
    details = []
    for summary in summaries:
        head = control.load_artifact_head(MARKET, summary.logical_artifact_id)
        loaded = control.load_artifact_by_id(MARKET, head.artifact_id)
        versions = control.list_artifact_versions(MARKET, summary.logical_artifact_id)
        values = loaded.frame["sma_3"]
        assert values.iloc[:2].isna().all()
        assert values.iloc[2:].tolist() == [101.0 + i for i in range(10)]
        pd.testing.assert_series_equal(values.reset_index(drop=True), frame.close.rolling(3).mean().astype("float32").rename("sma_3"), check_exact=True)
        assert head.artifact_id == summary.artifact_id == loaded.metadata.artifact_id
        assert len(versions) == 1 and versions[0].artifact_id == head.artifact_id
        directory = historical / "bybit/linear/BTCUSDT/1m/artifacts/indicator/sma" / head.artifact_id
        details.append({"logical_id":summary.logical_artifact_id, "artifact_id":head.artifact_id, "recipe_id":loaded.metadata.recipe.recipe_id, "version":versions[0].to_dict(), "head":head.to_dict(), "directory_length":len(str(directory)), "metadata_length":len(str(directory/"artifact.meta.json")), "ordinary_metadata_file":(directory/"artifact.meta.json").is_file(), "extended_metadata_file":io(directory/"artifact.meta.json").is_file(), "values":[None if pd.isna(v) else float(v) for v in values]})
    receipt(request.node.nodeid, "terminal", {"route":route, "historical":str(historical), "ordinary_root":True, "root_length":len(str(historical)), "status":result.status, "error_type":result.error_type, "error":result.error_message, "before":source_before, "after":persisted, "saved":details, "longest_path":max(len(str(historical / rel)) for rel in persisted), "clocks":"Production timestamps retained; only same-tree bytes compared, not independent-root IDs"})
    assert len(details) == 1, (result, details)
    assert {k:persisted[k] for k in source_before} == source_before
    if depth == "payload":
        assert details[0]["metadata_length"] == 270
    assert result.status == "completed", (result.error_type, result.error_message)
    materialization = result.value.materialization if route == "direct" else result.value
    assert materialization.created_artifact_ids == (details[0]["artifact_id"],)
    assert materialization.root_logical_artifact_ids == (details[0]["logical_id"],)
    assert tuple(x.artifact_id for x in materialization.managed_artifacts) == materialization.created_artifact_ids
    assert all(x.valid and x.artifact_id for x in artifacts.list_managed_artifacts_metadata(MARKET))


@pytest.mark.parametrize("route", ("direct", "recipe"))
def test_long_root_rejects_changed_source_without_touching_prior_managed_objects(tmp_path, request, route):
    historical, _, artifacts, recipes, service = domain(case_root(tmp_path, request), "payload")
    old = submit(service, artifacts, recipes, route)
    assert old.status == "completed"
    service.begin_session()
    service.inspect_market(MARKET)
    sentinel = historical / "sentinel.txt"
    sentinel.write_bytes(b"unrelated")
    before = disk(historical)
    store = OHLCVStore(historical)
    rows = store.read(MARKET)
    rows[-1] = replace(rows[-1], volume=rows[-1].volume + 1)
    store.write(MARKET, rows, source="R02 changed unvalidated", persistence_status="committed")
    # No queued GUI invalidation is delivered. The accepted R01 authority refuses.
    from leonardo.artifacts import ArtifactLineageError

    with service._operation_checks():
        with pytest.raises(ArtifactLineageError, match="validation_status must be ok"):
            artifacts.capture_accepted_source(MARKET)
    after = disk(historical)
    owned = lambda files: {k:v for k,v in files.items() if "/artifacts/" in k or "/artifact_versions/" in k or k=="sentinel.txt"}
    assert owned(after) == owned(before)
    assert MARKET not in service._source_evidence
    assert all(item.artifact_id and item.valid for item in artifacts.list_managed_artifacts_metadata(MARKET))
    receipt(request.node.nodeid, "source_refusal", {"route":route, "historical":str(historical), "before":before, "after":after, "prior_owned_bytes_preserved":True, "gui_invalidation":False})


def _e2_prepare_submission(service, artifacts, recipes, route, period):
    source = artifacts.capture_accepted_source(MARKET)
    if route == "direct":
        from leonardo.data_manager.direct_artifact import _build_direct_portable_recipe

        request = DataManagerDirectArtifactRequest(MARKET, source, "sma", {"period": period}, ())
        candidate = _build_direct_portable_recipe(request, {})
        # Persist the independent portable input before taking the rollback baseline.
        service._publish_portable_recipe_candidates((candidate,))
        return request
    parameters = dict(resolve_parameters("sma", {"period": period}))
    recipe = build_portable_recipe(tool_key="sma", kind="indicator", parameters=parameters,
        output_names=resolve_output_names("sma", parameters))
    recipes.save_recipe(recipe)
    plan = service.plan_artifact_materialization(DataManagerArtifactMaterializationRequest(MARKET, (recipe.recipe_id,)))
    assert not plan.blocked
    return plan


def _e2_submit_prepared(service, route, prepared):
    done, results = Event(), []
    runner = CoreRunner(TaskManager())
    application = DataManagerApplicationService(runner, service)
    runner.start()
    try:
        callback = lambda result: (results.append(result), done.set())
        if route == "direct":
            application.submit_create_direct_artifact(prepared, result_callback=callback)
        else:
            application.submit_execute_artifact_materialization(prepared, result_callback=callback)
        assert done.wait(5), "E2 real Core task did not settle"
    finally:
        runner.shutdown()
    assert len(results) == 1
    return results[0]


@pytest.mark.parametrize("depth", ("short", "payload"))
@pytest.mark.parametrize("route", ("direct", "recipe"))
def test_e2_ordinary_post_head_rollback_restores_all_owned_files(tmp_path, request, monkeypatch, depth, route):
    from pathlib import Path
    from leonardo.artifacts import ArtifactLineageError

    base = case_root(tmp_path, request)
    historical, _, artifacts, recipes, service = domain(base, depth)
    assert not str(historical).startswith("\\\\?\\")
    old = submit(service, artifacts, recipes, route, period=2)
    assert old.status == "completed", old.error_message
    service.begin_session()
    service.inspect_market(MARKET)
    assert MARKET in service._source_evidence
    io(historical / "sentinel.bin").write_bytes(b"E2 unrelated historical sentinel")
    # Prepare portable input definitions before the baseline. They are not outputs.
    prepared = _e2_prepare_submission(service, artifacts, recipes, route, 5)
    before = disk(historical)
    global_before = disk(base / "r")
    original = artifacts._store.replace_head
    store = OHLCVStore(historical)
    intermediate = []

    def replace_head(path, payload):
        original(path, payload)
        if not intermediate:
            intermediate.append({"files": disk(historical), "head": str(path), "head_payload": io(path).read_text()})
            store.finalize(MARKET, source="E2 legitimate metadata reset after managed head")
            intermediate[0]["after_metadata_reset"] = disk(historical)

    monkeypatch.setattr(artifacts._store, "replace_head", replace_head)
    result = _e2_submit_prepared(service, route, prepared)
    after = disk(historical)
    global_after = disk(base / "r")
    sidecar = store.sidecar_path(MARKET).relative_to(historical).as_posix()
    content = lambda files: {k: {f: v[f] for f in ("bytes", "sha256")} for k, v in files.items()}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(k for k in set(before) & set(after) if content(before)[k] != content(after)[k])
    new_files = sorted(set(intermediate[0]["files"]) - set(before)) if intermediate else []
    new_payloads = [k for k in new_files if k.endswith("/artifact.meta.json")]
    payload_lengths = [len(str(historical / k)) for k in new_payloads]
    source_rejected = not service._catalog.scan().accepted
    cache_removed = MARKET not in service._source_evidence
    receipt(request.node.nodeid, "e2_post_head_rollback", {
        "route": route, "depth": depth, "historical": str(historical), "ordinary_root": True,
        "status": result.status, "error_type": result.error_type, "error": result.error_message,
        "before": before, "intermediate": intermediate, "after": after,
        "portable_recipe_before": global_before, "portable_recipe_after": global_after,
        "sidecar": sidecar, "added": added, "removed": removed, "modified": modified,
        "new_publication_files": new_files, "metadata_lengths": payload_lengths,
        "cache_removed": cache_removed, "source_rejected": source_rejected,
        "new_head_directory_exists": [io(Path(x["head"]).parent).exists() for x in intermediate],
        "new_artifact_directory_exists": [io((historical / k).parent).exists() for k in new_payloads],
        "gui_invalidation": False,
    })
    assert len(intermediate) == 1
    assert len(new_payloads) == 1
    assert len([k for k in new_files if "/recipes/" in k]) == 1
    assert any("/artifact_versions/" in k and k.endswith("/head.json") for k in new_files)
    assert any("/versions/" in k for k in new_files)
    if depth == "payload":
        assert payload_lengths == [270]
    assert result.status == "failed" and "validation_status must be ok" in result.error_message
    assert "rollback failed" not in result.error_message
    assert cache_removed and source_rejected
    assert not added and not removed and modified == [sidecar]
    assert {k: v for k, v in content(after).items() if k != sidecar} == {k: v for k, v in content(before).items() if k != sidecar}
    assert after[sidecar] == intermediate[0]["after_metadata_reset"][sidecar]
    assert global_after == global_before
    assert all(not io(Path(x["head"]).parent).exists() for x in intermediate)
    assert all(not io((historical / k).parent).exists() for k in new_payloads)
    with service._operation_checks():
        with pytest.raises(ArtifactLineageError, match="validation_status must be ok"):
            artifacts.capture_accepted_source(MARKET)
