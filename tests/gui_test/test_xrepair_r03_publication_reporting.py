"""R03 typed publication evidence, real Core results and rendered table contents."""
from dataclasses import replace

import numpy as np
import pytest

from leonardo.core.core_runner import TaskResult
from leonardo.data_manager import (
    BatchArtifactBranchRequest, BatchArtifactRequest,
    DataManagerArtifactMaterializationRequest,
)
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactRequest, DataManagerDirectArtifactSource
from leonardo.financial_tools import resolve_output_names
from leonardo.gui.presenters.data_manager_presenter import _operation_details
from tests.artifacts_test.test_artifact_service_roundtrip import _frame
from tests.data_manager_test.test_artifact_materialization import _domain, _leaf
from tests.data_manager_test.test_xrepair_r03_reviewed_derivation import (
    _inventory, _plain, _receipt, _setup,
)
from tests.gui_test.test_xrepair_r03_derivation_workflow import _gui, _rows
from tests.gui_test.test_data_manager_recipe_artifact_materialization_vertical import _settle


MISSING = (
    "execute_recipe_artifact_materialization", "execute_construct_batch",
    "create_artifact_collection_from_materialization", "create_recipe_collection_from_catalog",
    "update_recipe_collection_from_catalog", "edit_artifact_collection_from_selection",
)
SCOPED = MISSING + ("persist_recipe_derivation", "create_direct_artifact",
                    "materialize_base_artifacts", "execute_batch_artifacts")


def _execute(window, presenter, operation, submit, *args, **kwargs):
    results = []
    generation = (presenter._catalog_generation if operation in {
        "persist_recipe_derivation", "create_recipe_collection_from_catalog",
        "update_recipe_collection_from_catalog", "edit_artifact_collection_from_selection",
    } else presenter._market_generation)
    presenter._submit(operation, generation,
        lambda progress, result: submit(*args, progress_callback=progress,
            result_callback=result, callback_dispatcher=presenter._dispatcher.dispatch, **kwargs),
        results.append)
    _settle(presenter)
    rows = _rows(window)
    _receipt(operation, rows=rows, terminal_count=len(results),
             result=repr(results[0]) if results else None)
    assert len(results) == 1 and results[0].status == "completed", rows
    assert dict(rows)["State"] == "completed" and dict(rows)["Task ID"] == results[0].task_id
    return results[0].value, dict(rows)


def _materialize_setup(tmp_path):
    market, service, artifacts, recipes, historical, environments = _domain(tmp_path / "d")
    recipe = _leaf("sma", {"period": 3})
    recipes.save_recipe(recipe)
    request = DataManagerArtifactMaterializationRequest(market, (recipe.recipe_id,))
    return market, service, artifacts, recipes, historical, recipe, request


@pytest.mark.parametrize("operation", ["execute_recipe_artifact_materialization", "materialize_base_artifacts"])
def test_real_materialization_operation_table_new_and_reuse(tmp_path, operation):
    market, service, artifacts, recipes, historical, recipe, request = _materialize_setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        before = _inventory(historical)
        first, first_rows = _execute(window, presenter, operation,
            app.submit_execute_artifact_materialization, service.plan_artifact_materialization(request))
        after = _inventory(historical)
        values = []
        for managed in first.managed_artifacts:
            head = artifacts.load_artifact_head(market, managed.logical_artifact_id)
            version = artifacts.load_artifact_version(market, managed.logical_artifact_id, managed.artifact_id)
            loaded = artifacts.load_artifact_by_id(market, managed.artifact_id)
            assert head.artifact_id == version.artifact_id == managed.artifact_id
            expected = _frame().close.rolling(3).mean().to_numpy()
            np.testing.assert_allclose(loaded.frame[recipe.output_names[0]], expected, equal_nan=True)
            values.append(loaded.frame.to_dict(orient="list"))
        _receipt("fresh_materialization_disk_ui", before=before, after=after,
                 result=_plain(first), rows=first_rows, actual_values=values)
        assert first.created_artifact_ids and first.created_version_keys and first.advanced_logical_artifact_ids
        assert first_rows["Published"] == "yes"
        second, rows = _execute(window, presenter, operation,
            app.submit_execute_artifact_materialization, service.plan_artifact_materialization(request))
        reused_disk = _inventory(historical)
        _receipt("reuse_materialization_disk_ui", before=after, after=reused_disk,
                 result=_plain(second), rows=rows)
        assert not second.created_artifact_ids and second.reused_artifact_ids
        assert rows["Published"] == "no"
        assert "Existing outputs reused; no new Artifact/version/head reported" in rows["Publication evidence"]
        assert reused_disk == after


@pytest.mark.parametrize("collection", [False, True])
def test_real_derivation_receipts(tmp_path, collection):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        first, rows = _execute(window, presenter, "persist_recipe_derivation",
            app.submit_persist_recipe_derivation, env.environment_id, roots,
            create_collection=collection, collection_display_name="R03",
            expected_environment_content_hash=plan.environment_content_hash)
        assert rows["Published"] == "yes" and first.created_recipe_ids and first.new_provenance_ids
        before = _inventory(recipes.root_dir)
        second, rows = _execute(window, presenter, "persist_recipe_derivation",
            app.submit_persist_recipe_derivation, env.environment_id, roots,
            create_collection=collection, collection_display_name="R03",
            expected_environment_content_hash=plan.environment_content_hash)
        assert rows["Published"] == "no" and second.existing_provenance_ids
        assert "reused" in rows["Publication evidence"]
        assert before == _inventory(recipes.root_dir)
        _receipt("derivation_disk_ui", first=_plain(first), second=_plain(second), rows=rows,
                 before=before, after=_inventory(recipes.root_dir))


@pytest.mark.parametrize("destination", ["individual", "new_collection"])
@pytest.mark.parametrize("operation", ["execute_construct_batch", "execute_batch_artifacts"])
def test_real_derivation_and_construct_batch_receipts(tmp_path, destination, operation):
    market, service, artifacts, recipes, historical, recipe, request = _materialize_setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        base, _ = _execute(window, presenter, "materialize_base_artifacts",
            app.submit_execute_artifact_materialization, service.plan_artifact_materialization(request))
        root = base.managed_artifacts[0]
        source_output = root.output_names[0]
        batch_request = BatchArtifactRequest(market, base.source_ohlcv,
            (BatchArtifactBranchRequest(tool_key="derivative", parameters={"order": 1},
                sources=(DataManagerDirectArtifactSource("source", root.logical_artifact_id,
                    root.artifact_id, source_output),),
                requested_outputs=resolve_output_names("derivative", {"order": 1, "source": source_output})),),
            destination=destination)
        first, rows = _execute(window, presenter, operation, app.submit_execute_batch_artifacts,
            service.plan_batch_artifacts(batch_request))
        assert isinstance(first, tuple) and len(first) == 2 and rows["Published"] == "yes"
        before = _inventory(historical)
        second, rows = _execute(window, presenter, operation, app.submit_execute_batch_artifacts,
            service.plan_batch_artifacts(batch_request))
        assert not second[0].created_artifact_ids and second[0].reused_artifact_ids
        assert rows["Published"] == ("no" if destination == "individual" else "unknown")
        if destination != "individual":
            assert second[1] is not None
            assert "Stored Collection revision returned; new/reused not reported" in rows["Publication evidence"]
        _receipt("construct_disk_ui", before=before, after=_inventory(historical),
                 first=repr(first), second=repr(second), rows=rows)


@pytest.mark.parametrize("family", ["recipe", "artifact"])
def test_real_collection_results_report_unknown_newness(tmp_path, family):
    market, service, artifacts, recipes, historical, recipe, request = _materialize_setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        if family == "recipe":
            operation = "create_recipe_collection_from_catalog"
            submit = app.submit_create_recipe_collection
            args = ("Stored roots", "", (recipe.recipe_id,))
        else:
            materialization, _ = _execute(window, presenter, "materialize_base_artifacts",
                app.submit_execute_artifact_materialization, service.plan_artifact_materialization(request))
            operation = "create_artifact_collection_from_materialization"
            submit = app.submit_create_artifact_collection
            args = (materialization, "Stored graph")
        first, rows = _execute(window, presenter, operation, submit, *args)
        second, reused_rows = _execute(window, presenter, operation, submit, *args)
        collection = first.collection if family == "recipe" else first
        reused = second.collection if family == "recipe" else second
        assert collection.collection_id == reused.collection_id and collection.revision_id == reused.revision_id
        for displayed in (rows, reused_rows):
            assert displayed["Published"] == "unknown"
            assert "Stored Collection revision returned; new/reused not reported" in displayed["Publication evidence"]
            assert collection.collection_id in displayed.values() and collection.revision_id in displayed.values()
        if family == "recipe":
            edited, edit_rows = _execute(window, presenter, "update_recipe_collection_from_catalog",
                app.submit_update_recipe_collection, collection.collection_id, "Renamed roots", "",
                (recipe.recipe_id,), expected_revision_id=collection.revision_id)
        else:
            selection = service.plan_artifact_collection_selection(market,
                materialization.root_logical_artifact_ids, collection_id=collection.collection_id,
                expected_revision_id=collection.revision_id)
            edited, edit_rows = _execute(window, presenter, "edit_artifact_collection_from_selection",
                app.submit_edit_artifact_collection_from_selection, collection.collection_id, selection,
                display_name="Renamed graph", expected_revision_id=collection.revision_id)
        assert edit_rows["Published"] == "unknown"
        _receipt("real_collection_results", new=repr(first), reused=repr(second), edited=repr(edited),
                 new_rows=rows, reuse_rows=reused_rows, edit_rows=edit_rows,
                 recipes=_inventory(recipes.root_dir), historical=_inventory(historical))


def test_direct_creation_retains_outer_recipe_identity(tmp_path):
    market, service, artifacts, recipes, historical, recipe, request = _materialize_setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        source = service.plan_artifact_materialization(request).source_ohlcv
        direct = DataManagerDirectArtifactRequest(market, source, "ema", {"period": 3})
        for expected in ("yes", "no"):
            result, rows = _execute(window, presenter, "create_direct_artifact",
                app.submit_create_direct_artifact, direct)
            assert rows["Published"] == expected
            assert rows["portable_recipe_id"] == result.portable_recipe_id
            _receipt("direct_" + expected, rows=rows, result=_plain(result), disk=_inventory(historical))


@pytest.mark.parametrize("operation", SCOPED)
@pytest.mark.parametrize("case", ["failed", "cancelled", "none", "wrong", "bad_tuple"])
def test_scoped_operation_failure_cancelled_malformed_table(operation, case):
    from PySide6.QtWidgets import QApplication
    from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
    qapp = QApplication.instance() or QApplication([])
    window = DataManagerSuiteWindow()
    status = case if case in {"failed", "cancelled"} else "completed"
    value = {"none": None, "wrong": "unexpected", "bad_tuple": (None, None)}.get(case)
    result = TaskResult("diagnostic", status, value, error_type="RecordedError" if status != "completed" else None,
                        error_message="Recorded failure; no rollback proof" if status != "completed" else None)
    try:
        window.settle_operation(status, "Projection control", _operation_details(operation, result.task_id, result))
        rows = dict(_rows(window))
        assert rows["Published"] == "unknown" and rows["Publication evidence"]
        assert rows["State"] == status and rows["Error type"] == (result.error_type or "")
        assert rows["Error message"] == (result.error_message or "")
        _receipt("uncertain_projection", rows=rows, synthetic_result_control=True)
    finally:
        window.close()
    assert qapp is not None


@pytest.mark.parametrize("dimension", ["artifact", "version", "head", "none"])
def test_materialization_evidence_dimensions(tmp_path, dimension):
    market, service, artifacts, recipes, historical, recipe, request = _materialize_setup(tmp_path)
    real = service.execute_artifact_materialization(service.plan_artifact_materialization(request))
    # Validated immutable variants isolate each authoritative field in the pure projection.
    value = replace(real,
        created_artifact_ids=real.created_artifact_ids if dimension == "artifact" else (),
        reused_artifact_ids=() if dimension == "artifact" else real.created_artifact_ids,
        created_version_keys=real.created_version_keys if dimension == "version" else (),
        reused_version_keys=() if dimension == "version" else real.created_version_keys,
        advanced_logical_artifact_ids=real.advanced_logical_artifact_ids if dimension == "head" else ())
    rows = dict(_operation_details("execute_recipe_artifact_materialization", "dimensions",
                                  TaskResult("dimensions", "completed", value)))
    assert rows["Published"] == ("no" if dimension == "none" else "yes")


@pytest.mark.parametrize("operation", ["plan_recipe_derivation", "scan_catalog", "inspect_study_environment"])
@pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
def test_unscoped_plan_scan_and_original_error_projection(operation, state):
    result = TaskResult("unscoped", state, error_type="E", error_message="detail")
    rows = _operation_details(operation, "unscoped", result)
    assert rows == (("Operation", operation), ("Task ID", "unscoped"), ("State", state),
                    ("Error type", "E"), ("Error message", "detail"), ("Published", "no"))
