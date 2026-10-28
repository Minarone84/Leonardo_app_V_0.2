from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.data_manager.application import DataManagerApplicationService
from leonardo.gui.presenters.data_manager_presenter import _operation_details
from leonardo.gui.windows.data_manager_artifact_collection_dialog import DataManagerArtifactCollectionDialog
from leonardo.gui.windows.data_manager_recipe_artifact_materialization_dialog import DataManagerRecipeArtifactMaterializationDialog
from leonardo.gui.data_manager.operations import DataManagerOperationSurface
from tests.data_manager_test.test_operation_input_checks import _graph
from tests.data_manager_test.test_update_workflow import MARKET
from tests.gui_test.test_data_manager_artifact_collection_dialog import _snapshot, _plan, _check, ROOT_A, MARKET_A
from tests.gui_test.test_data_manager_recipe_artifact_materialization_dialog import _plan as _recipe_plan, DATASET
from tests.gui_test.test_data_manager_catalogs import associated_product_snapshot


_QAPP = QApplication.instance() or QApplication([])


def _dispose(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)


def test_both_collection_preflights_explain_checks_and_fresh_reuse():
    manual = DataManagerArtifactCollectionDialog(_snapshot(), browsing_market_id=MARKET_A)
    recipe = DataManagerRecipeArtifactMaterializationDialog()
    try:
        _check(manual, ROOT_A)
        plan = _plan((ROOT_A,))
        assert manual.set_plan(plan)
        assert "required dependencies" in manual.preview_summary.text()
        assert manual.set_collection_prediction(plan, None)
        assert "without payload rescans" in manual.preview_summary.text()
        snapshot = associated_product_snapshot()
        recipe.configure_recipe(snapshot.portable_recipes.recipes[0], snapshot, DATASET)
        plan = _recipe_plan()
        assert recipe.set_plan(plan)
        assert "reuses completed checks" in recipe.preview_summary.text()
        assert recipe.set_collection_prediction(plan, None)
        assert "actual input checks" in recipe.preview_summary.text()
    finally:
        _dispose(manual)
        _dispose(recipe)


@pytest.mark.parametrize("fresh", (False, True))
@pytest.mark.parametrize("cancel", (False, True))
def test_core_collection_progress_precedes_publish_and_allows_cancellation(tmp_path, monkeypatch, fresh, cancel):
    domain, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    plan = domain.plan_artifact_collection_selection(MARKET, result.root_logical_artifact_ids)
    runner = CoreRunner(TaskManager())
    application = DataManagerApplicationService(runner, domain)
    runner.start()
    arrived, release, finished = Event(), Event(), Event()
    progress, outcomes, publications = [], [], []
    original = domain.creation_store._publish_collection_revision

    def publish(revision):
        publications.append(tuple(progress))
        return original(revision)

    def report(event):
        if "Checked Artifact" in event.message or "Reusing completed check" in event.message:
            progress.append(event)
            if not arrived.is_set():
                arrived.set()
                assert release.wait(5)

    def completed(value):
        outcomes.append(value)
        finished.set()

    monkeypatch.setattr(domain.creation_store, "_publish_collection_revision", publish)
    try:
        if fresh:
            task = application.submit_create_artifact_collection(
                result, "Progress", progress_callback=report, result_callback=completed
            )
        else:
            task = application.submit_create_artifact_collection_from_selection(
                plan, "Progress", progress_callback=report, result_callback=completed
            )
        assert arrived.wait(5)
        assert not publications
        if cancel:
            assert application.cancel(task.task_id)
        release.set()
        assert finished.wait(5)
        assert task.task_id not in application._cancellations
        if cancel:
            assert not publications
            assert not domain.list_artifact_collections()
            assert outcomes[0].status != "completed"
        else:
            assert outcomes[0].status == "completed"
            assert len(publications) == 1
            assert [(event.current, event.total) for event in publications[0]] == [(1, 2), (2, 2)]
            surface = DataManagerOperationSurface()
            try:
                for event in progress:
                    surface.set_progress(event.current, event.total, event.message)
                assert surface.progress.maximum() == 2
                assert surface.progress.value() == 2
            finally:
                _dispose(surface)
    finally:
        release.set()
        runner.shutdown()


@pytest.mark.parametrize(
    ("status", "published"),
    (("completed", "yes"), ("failed", "no"), ("cancelled", "no")),
)
def test_manual_collection_publication_details(status, published):
    result = TaskResult("manual-collection", status)
    details = dict(_operation_details(
        "create_artifact_collection_from_selection", result.task_id, result,
    ))
    assert details["Published"] == published


@pytest.mark.parametrize(
    ("status", "published"),
    (("completed", "yes"), ("failed", "no"), ("cancelled", "no")),
)
def test_database_content_edit_publication_details(status, published):
    result = TaskResult("database-content-edit", status)
    details = dict(_operation_details(
        "execute_database_content_edit", result.task_id, result,
    ))
    assert details["Published"] == published


@pytest.mark.parametrize("editing", (False, True))
def test_am8_collection_preview_forwards_edit_context_through_core(tmp_path, monkeypatch, editing):
    from types import SimpleNamespace
    from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter

    domain, artifacts, recipes, historical, result, unrelated = _graph(tmp_path)
    runner = CoreRunner(TaskManager())
    application = DataManagerApplicationService(runner, domain)
    runner.start()
    finished = Event()
    calls, outcomes = [], []
    roots = result.root_logical_artifact_ids
    context = {"collection_id": "collection_context", "expected_revision_id": "a" * 64} if editing else {}

    def plan(market_id, selected_roots, **kwargs):
        calls.append((market_id, selected_roots, kwargs))
        return "reviewed"

    def settled(outcome, *args):
        outcomes.append(outcome)
        finished.set()

    dialog = SimpleNamespace(
        isVisible=lambda: True, selection_market_id=MARKET,
        selected_root_logical_artifact_ids=lambda: roots,
        collection_id=context.get("collection_id"),
        expected_revision_id=context.get("expected_revision_id"),
    )
    presenter = SimpleNamespace(
        _disposed=False, _active_task_id=None, _catalog_generation=1,
        _view=SimpleNamespace(artifact_collection_dialog=lambda: dialog),
        _service=application,
        _dispatcher=SimpleNamespace(dispatch=lambda callback: callback()),
        _submit=lambda operation, generation, submit, settle: submit(None, settle),
        _settle_artifact_collection_plan=settled,
    )
    monkeypatch.setattr(domain, "plan_artifact_collection_selection", plan)
    try:
        DataManagerSuitePresenter._preview_artifact_collection(presenter, MARKET, roots)
        assert finished.wait(5)
        assert calls == [(MARKET, roots, context)]
        assert outcomes[0].status == "completed"
        assert outcomes[0].value == "reviewed"
    finally:
        runner.shutdown()
