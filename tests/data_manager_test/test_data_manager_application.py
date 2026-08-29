from __future__ import annotations

from pathlib import Path
from threading import Event
import time
from types import SimpleNamespace

import pytest

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.data import MarketId
from leonardo.data_manager import DataManagerApplicationService, DataManagerService
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.recipes import PortableRecipeGraphPlanner, PortableRecipeStore
from leonardo.research import (
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    HistoricalDataset,
    StudyEnvironmentStore,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")


class _Catalog:
    def scan(self):
        return DatasetCatalogReport(
            (
                AcceptedDatasetSummary(
                    MARKET,
                    Path("candles.csv"),
                    Path("candles.meta.json"),
                    "a" * 64,
                    1,
                    0,
                    0,
                    "test",
                    "committed",
                    "ok",
                    (),
                ),
            ),
            (),
        )


class _BlockingCatalog(_Catalog):
    def __init__(self) -> None:
        self.scan_entered = Event()
        self.release_scan = Event()

    def scan(self):
        self.scan_entered.set()
        if not self.release_scan.wait(3.0):
            raise RuntimeError("catalog scan release timed out")
        return super().scan()


class _Loader:
    def __init__(self, *, block_until_cancelled: bool = False) -> None:
        self.block_until_cancelled = block_until_cancelled

    def load(self, market_id, *, progress=None, cancellation_requested=None):
        if self.block_until_cancelled:
            while not cancellation_requested():
                time.sleep(0.005)
            raise RuntimeError("cancelled loader")
        if progress is not None:
            progress(1, 1)
        return HistoricalDataset(
            MARKET,
            Path("candles.csv"),
            "a" * 64,
            1,
            0,
            0,
            (0,),
            (1.0,),
            (2.0,),
            (0.5,),
            (1.5,),
            (10.0,),
        )


class _Artifacts:
    def __init__(self) -> None:
        self.artifact_deletion_started = Event()
        self.recipe_deletion_started = Event()
        self.release_artifact_deletion = Event()
        self.release_recipe_deletion = Event()
        self.artifact_delete_calls = 0
        self.recipe_delete_calls = 0

    def list_recipes(self, market_id):
        return ()

    def list_artifacts(self, market_id):
        return ()

    def load_artifact(self, *args):
        raise AssertionError("not used")

    def validate_artifact_current(self, *args):
        raise AssertionError("not used")

    def delete_artifact(self, *args):
        self.artifact_delete_calls += 1
        self.artifact_deletion_started.set()
        self.release_artifact_deletion.wait(3.0)
        return None

    def delete_recipe(self, *args):
        self.recipe_delete_calls += 1
        self.recipe_deletion_started.set()
        self.release_recipe_deletion.wait(3.0)
        return None


class _TrackingService(DataManagerService):
    def __init__(self, catalog, loader, artifacts) -> None:
        recipes = PortableRecipeStore(Path("__unused_data_manager_application_recipes__"))
        super().__init__(
            catalog,
            loader,
            artifacts,
            StudyEnvironmentStore(Path("__unused_data_manager_application_environments__")),
            recipes,
            PortableRecipeGraphPlanner(recipes),
        )
        self.artifact_worker_finished = Event()
        self.recipe_worker_finished = Event()

    def _delete_artifact(self, *args, **kwargs):
        try:
            return super()._delete_artifact(*args, **kwargs)
        finally:
            self.artifact_worker_finished.set()

    def _delete_recipe(self, *args, **kwargs):
        try:
            return super()._delete_recipe(*args, **kwargs)
        finally:
            self.recipe_worker_finished.set()


class _PortableOperationsService(_TrackingService):
    def plan_artifact_collection_selection(self, market_id, root_ids):
        if not hasattr(self, "selection_plan"):
            self.selection_plan = SimpleNamespace(
                market_id=market_id,
                root_logical_artifact_ids=tuple(root_ids),
                plan_id="c" * 64,
            )
        return self.selection_plan

    def _create_artifact_collection_from_selection(
        self, plan, display_name, *, before_publish=None, **_kwargs
    ):
        self.selection_create_fenced = before_publish is not None
        if before_publish is not None:
            before_publish()
        return ("selection-create", plan.plan_id, display_name)

    def _edit_artifact_collection_from_selection(
        self,
        collection_id,
        plan,
        *,
        before_publish=None,
        expected_revision_id,
        **_kwargs,
    ):
        self.selection_edit_fenced = before_publish is not None
        if before_publish is not None:
            before_publish()
        return (
            "selection-edit",
            collection_id,
            plan.plan_id,
            expected_revision_id,
        )

    def scan_study_environments(self, **_kwargs):
        return "environments"

    def plan_recipe_derivation(self, *_args):
        return "plan"

    def persist_recipe_derivation(self, *_args, **_kwargs):
        return "persist"

    def _persist_recipe_derivation(self, *_args, before_publish=None, **_kwargs):
        if before_publish is not None:
            before_publish()
        return "persist"

    def scan_portable_recipes(self, **_kwargs):
        return "recipes"

    def create_recipe_collection(self, *_args):
        return "create"

    def plan_recipe_collection(self, root_recipe_ids):
        return ("collection-plan", root_recipe_ids)

    def _create_recipe_collection(self, *_args, before_publish=None):
        if before_publish is not None:
            before_publish()
        return "create"

    def update_recipe_collection(self, *_args):
        return "update"

    def _update_recipe_collection(
        self, *_args, before_publish=None, expected_revision_id=None
    ):
        if before_publish is not None:
            before_publish()
        return ("update", expected_revision_id)

    def list_recipe_collections(self):
        return "collections"

    def inspect_recipe_collection(self, *_args):
        return "inspect"


class _ControlledPublicationService(_PortableOperationsService):
    def __init__(self) -> None:
        super().__init__(_Catalog(), _Loader(), _Artifacts())
        self.preflight_entered = Event()
        self.release_preflight = Event()
        self.publication_started = Event()
        self.release_publication = Event()
        self.published: list[str] = []

    def _run_publication(self, operation: str, before_publish):
        self.preflight_entered.set()
        if not self.release_preflight.wait(3.0):
            raise RuntimeError("publication preflight release timed out")
        if before_publish is not None:
            before_publish()
        self.publication_started.set()
        if not self.release_publication.wait(3.0):
            raise RuntimeError("publication release timed out")
        self.published.append(operation)
        return operation

    def _persist_recipe_derivation(self, *_args, before_publish=None, **_kwargs):
        return self._run_publication("persist", before_publish)

    def _create_recipe_collection(self, *_args, before_publish=None):
        return self._run_publication("create", before_publish)

    def _update_recipe_collection(
        self, *_args, before_publish=None, expected_revision_id=None
    ):
        return self._run_publication("update", before_publish)


class _ControlledCatalogDeletionService(_PortableOperationsService):
    def __init__(self) -> None:
        super().__init__(_Catalog(), _Loader(), _Artifacts())
        self.preflight_entered = Event()
        self.release_preflight = Event()
        self.deletion_started = Event()
        self.release_deletion = Event()
        self.deleted: list[str] = []

    def _run_deletion(self, operation: str, before_delete):
        self.preflight_entered.set()
        if not self.release_preflight.wait(3.0):
            raise RuntimeError("deletion preflight release timed out")
        if before_delete is not None:
            before_delete()
        self.deletion_started.set()
        if not self.release_deletion.wait(3.0):
            raise RuntimeError("deletion release timed out")
        self.deleted.append(operation)
        return operation

    def _delete_portable_recipe(self, *_args, before_delete=None):
        return self._run_deletion("portable_recipe", before_delete)

    def _delete_recipe_collection(self, *_args, before_delete=None):
        return self._run_deletion("recipe_collection", before_delete)

    def _delete_managed_artifact(self, *_args, before_delete=None):
        return self._run_deletion("managed_artifact", before_delete)

    def _delete_artifact_collection(self, *_args, before_delete=None):
        return self._run_deletion("artifact_collection", before_delete)


class _UpdateOperationsService(_PortableOperationsService):
    def __init__(self, catalog, loader, artifacts) -> None:
        super().__init__(catalog, loader, artifacts)
        self.reconciliation_cancellation_requested = None

    def reconcile_update_status(self, *, force=False, cancellation_requested=None):
        self.reconciliation_cancellation_requested = cancellation_requested
        return ("reconcile", force)

    def latest_update_status(self):
        return "latest"

    def plan_artifact_collection_update(self, collection_id):
        return ("artifact-plan", collection_id)

    def execute_artifact_collection_update(
        self, plan, *, cancellation_requested=None, before_publish=None
    ):
        assert cancellation_requested() is False
        before_publish()
        return ("artifact-execute", plan.plan_id)

    def plan_database_update(self, database_id):
        return ("database-plan", database_id)

    def execute_database_append(
        self, plan, *, cancellation_requested=None, before_publish=None
    ):
        assert cancellation_requested() is False
        before_publish()
        return ("append", plan.plan_id)

    def execute_database_rebuild(
        self, plan, *, cancellation_requested=None, before_publish=None
    ):
        assert cancellation_requested() is False
        before_publish()
        return ("rebuild", plan.plan_id)


class _ProductReadOperationsService(_TrackingService):
    def inspect_study_environment(self, environment_id):
        return ("environment", environment_id)

    def inspect_portable_recipe(self, recipe_id):
        return ("recipe", recipe_id)

    def list_recipe_collection_revisions(self, collection_id):
        return ("revisions", collection_id)

    def scan_managed_artifacts(self):
        return "managed-artifacts"

    def scan_product_catalogs(self):
        return "product-catalogs"


def _application(loader=None, artifacts=None, catalog=None, service=None):
    manager = TaskManager()
    runner = CoreRunner(manager)
    recipes = PortableRecipeStore(Path("__unused_data_manager_application_recipes__"))
    domain = service or DataManagerService(
        catalog or _Catalog(),
        loader or _Loader(),
        artifacts or _Artifacts(),
        StudyEnvironmentStore(Path("__unused_data_manager_application_environments__")),
        recipes,
        PortableRecipeGraphPlanner(recipes),
    )
    return manager, runner, DataManagerApplicationService(runner, domain)


def _submit_publication(application, operation: str, result_callback):
    if operation == "persist":
        return application.submit_persist_recipe_derivation(
            "env_one",
            ("entry_one",),
            create_collection=False,
            result_callback=result_callback,
        )
    if operation == "create":
        return application.submit_create_recipe_collection(
            "Collection", "", ("a" * 64,), result_callback=result_callback
        )
    return application.submit_update_recipe_collection(
        "prc_" + "b" * 32,
        "Collection",
        "",
        ("a" * 64,),
        result_callback=result_callback,
    )


def test_application_runs_catalog_through_core_and_tracks_operation() -> None:
    manager, runner, application = _application()
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        application.submit_scan_catalog(
            result_callback=lambda result: (results.append(result), ready.set())
        )
        assert ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value.accepted_count == 1
        assert any(
            item.metadata.get("operation") == "data_manager.scan_catalog"
            for item in manager.snapshots()
        )
    finally:
        runner.shutdown()


def test_update_operations_use_exact_core_metadata_and_direct_latest_read() -> None:
    service = _UpdateOperationsService(_Catalog(), _Loader(), _Artifacts())
    manager, runner, application = _application(service=service)
    completed = Event()
    results: list[TaskResult] = []

    def receive(result: TaskResult) -> None:
        results.append(result)
        if len(results) == 6:
            completed.set()

    artifact_plan = SimpleNamespace(collection_id="col_one", plan_id="a" * 64)
    database_plan = SimpleNamespace(database_id="db_one", plan_id="b" * 64)
    runner.start()
    try:
        application.submit_reconcile_status(force=True, result_callback=receive)
        application.submit_plan_artifact_collection_update(
            "col_one", result_callback=receive
        )
        application.submit_execute_artifact_collection_update(
            artifact_plan, result_callback=receive
        )
        application.submit_plan_database_update("db_one", result_callback=receive)
        application.submit_execute_database_append(database_plan, result_callback=receive)
        application.submit_execute_database_rebuild(database_plan, result_callback=receive)
        assert completed.wait(3.0)
        assert all(item.status == "completed" for item in results)
        assert callable(service.reconciliation_cancellation_requested)
        assert service.reconciliation_cancellation_requested() is False
        assert {
            item.metadata.get("operation") for item in manager.snapshots()
        } >= {
            "data_manager.reconcile_status",
            "data_manager.plan_artifact_collection_update",
            "data_manager.execute_artifact_collection_update",
            "data_manager.plan_database_update",
            "data_manager.execute_database_append",
            "data_manager.execute_database_rebuild",
        }
        assert application.latest_reconciliation_snapshot() == "latest"
    finally:
        runner.shutdown()


def test_artifact_collection_selection_operations_use_exact_core_metadata_and_fence(
) -> None:
    service = _PortableOperationsService(_Catalog(), _Loader(), _Artifacts())
    manager, runner, application = _application(service=service)
    completed = Event()
    results: list[TaskResult] = []

    def receive(result: TaskResult) -> None:
        results.append(result)
        if len(results) == 3:
            completed.set()

    plan = service.plan_artifact_collection_selection(MARKET, ("a" * 64,))
    runner.start()
    try:
        application.submit_plan_artifact_collection_selection(
            MARKET, ("a" * 64,), result_callback=receive
        )
        application.submit_create_artifact_collection_from_selection(
            plan, "Selection", result_callback=receive
        )
        application.submit_edit_artifact_collection_from_selection(
            "ac_" + "b" * 32,
            plan,
            expected_revision_id="d" * 64,
            result_callback=receive,
        )
        assert completed.wait(3.0)
        assert all(item.status == "completed" for item in results)
        assert any(item.value is plan for item in results)
        assert service.selection_create_fenced
        assert service.selection_edit_fenced
        assert any(
            item.value
            == (
                "selection-edit",
                "ac_" + "b" * 32,
                "c" * 64,
                "d" * 64,
            )
            for item in results
        )
        assert {
            item.metadata.get("operation") for item in manager.snapshots()
        } >= {
            "data_manager.plan_artifact_collection_selection",
            "data_manager.create_artifact_collection_from_selection",
            "data_manager.edit_artifact_collection_from_selection",
        }
    finally:
        runner.shutdown()


def test_product_catalog_read_operations_use_exact_core_metadata() -> None:
    service = _ProductReadOperationsService(_Catalog(), _Loader(), _Artifacts())
    manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []

    def receive(result: TaskResult) -> None:
        results.append(result)
        if len(results) == 5:
            ready.set()

    runner.start()
    try:
        application.submit_inspect_study_environment("env_one", result_callback=receive)
        application.submit_inspect_portable_recipe("a" * 64, result_callback=receive)
        application.submit_list_recipe_collection_revisions(
            "prc_" + "b" * 32, result_callback=receive
        )
        application.submit_scan_managed_artifacts(result_callback=receive)
        application.submit_scan_product_catalogs(result_callback=receive)
        assert ready.wait(3.0)
        assert all(item.status == "completed" for item in results)
        operations = {
            item.metadata.get("operation") for item in manager.snapshots()
        }
        assert {
            "data_manager.inspect_study_environment",
            "data_manager.inspect_portable_recipe",
            "data_manager.list_recipe_collection_revisions",
            "data_manager.scan_managed_artifacts",
            "data_manager.scan_product_catalogs",
        }.issubset(operations)
    finally:
        runner.shutdown()


def test_portable_recipe_operations_use_exact_core_metadata() -> None:
    service = _PortableOperationsService(_Catalog(), _Loader(), _Artifacts())
    manager, runner, application = _application(service=service)
    completed = Event()
    results: list[TaskResult] = []

    def receive(result: TaskResult) -> None:
        results.append(result)
        if len(results) == 9:
            completed.set()

    runner.start()
    try:
        application.submit_scan_study_environments(result_callback=receive)
        application.submit_plan_recipe_derivation(
            "env_one", ("entry_one",), result_callback=receive
        )
        application.submit_persist_recipe_derivation(
            "env_one", ("entry_one",), create_collection=False,
            result_callback=receive,
        )
        application.submit_scan_portable_recipes(result_callback=receive)
        application.submit_create_recipe_collection(
            "Collection", "", ("a" * 64,), result_callback=receive
        )
        application.submit_plan_recipe_collection(
            ("a" * 64,), result_callback=receive
        )
        application.submit_update_recipe_collection(
            "prc_" + "b" * 32, "Collection", "", ("a" * 64,),
            expected_revision_id="c" * 64,
            result_callback=receive,
        )
        application.submit_list_recipe_collections(result_callback=receive)
        application.submit_inspect_recipe_collection(
            "prc_" + "b" * 32, result_callback=receive
        )
        assert completed.wait(3.0)
        assert all(item.status == "completed" for item in results)
        operations = {
            item.metadata.get("operation") for item in manager.snapshots()
        }
        assert {
            "data_manager.scan_study_environments",
            "data_manager.plan_recipe_derivation",
            "data_manager.persist_recipe_derivation",
            "data_manager.scan_portable_recipes",
            "data_manager.create_recipe_collection",
            "data_manager.plan_recipe_collection",
            "data_manager.update_recipe_collection",
            "data_manager.list_recipe_collections",
            "data_manager.inspect_recipe_collection",
        }.issubset(operations)
        plan_result = next(
            item for item in results if item.value == ("collection-plan", ("a" * 64,))
        )
        assert plan_result.status == "completed"
        update_result = next(
            item for item in results if item.value == ("update", "c" * 64)
        )
        assert update_result.status == "completed"
    finally:
        runner.shutdown()


def test_preview_cancellation_is_cooperative_before_publication() -> None:
    manager, runner, application = _application(loader=_Loader(block_until_cancelled=True))
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = application.submit_preview_dataset(
            MARKET,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        assert application.cancel(submission.task_id)
        assert ready.wait(3.0)
        assert results[0].status == "cancelled"
    finally:
        runner.shutdown()


@pytest.mark.parametrize("operation", ("persist", "create", "update"))
def test_recipe_persistence_cancellation_is_accepted_before_publication(
    operation: str,
) -> None:
    service = _ControlledPublicationService()
    _manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = _submit_publication(
            application,
            operation,
            lambda result: (results.append(result), ready.set()),
        )
        assert service.preflight_entered.wait(3.0)
        assert application.cancel(submission.task_id) is True
        service.release_preflight.set()
        assert ready.wait(3.0)
        assert results[0].status == "cancelled"
        assert not service.publication_started.is_set()
        assert service.published == []
    finally:
        service.release_preflight.set()
        service.release_publication.set()
        runner.shutdown()


@pytest.mark.parametrize("operation", ("persist", "create", "update"))
def test_recipe_persistence_cancellation_is_refused_after_publication_begins(
    operation: str,
) -> None:
    service = _ControlledPublicationService()
    service.release_preflight.set()
    _manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = _submit_publication(
            application,
            operation,
            lambda result: (results.append(result), ready.set()),
        )
        assert service.publication_started.wait(3.0)
        assert application.cancel(submission.task_id) is False
        service.release_publication.set()
        assert ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value == operation
        assert service.published == [operation]
    finally:
        service.release_preflight.set()
        service.release_publication.set()
        runner.shutdown()


@pytest.mark.parametrize("object_kind", ("artifact", "recipe"))
def test_pre_delete_cancellation_prevents_worker_publication(object_kind) -> None:
    catalog = _BlockingCatalog()
    artifacts = _Artifacts()
    service = _TrackingService(catalog, _Loader(), artifacts)
    _manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submit = (
            application.submit_delete_artifact
            if object_kind == "artifact"
            else application.submit_delete_recipe
        )
        submission = submit(
            MARKET,
            "indicator",
            "sma",
            ("a" if object_kind == "artifact" else "r") * 64,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        assert catalog.scan_entered.wait(3.0)
        assert application.cancel(submission.task_id) is True
        assert artifacts.artifact_delete_calls == 0
        assert artifacts.recipe_delete_calls == 0
        catalog.release_scan.set()
        worker_finished = (
            service.artifact_worker_finished
            if object_kind == "artifact"
            else service.recipe_worker_finished
        )
        assert worker_finished.wait(3.0)
        assert ready.wait(3.0)
        assert results[0].status == "cancelled"
        assert artifacts.artifact_delete_calls == 0
        assert artifacts.recipe_delete_calls == 0
    finally:
        catalog.release_scan.set()
        runner.shutdown()


@pytest.mark.parametrize("object_kind", ("artifact", "recipe"))
def test_cancellation_is_refused_after_canonical_deletion_starts(object_kind) -> None:
    artifacts = _Artifacts()
    _manager, runner, application = _application(artifacts=artifacts)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submit = (
            application.submit_delete_artifact
            if object_kind == "artifact"
            else application.submit_delete_recipe
        )
        object_id = ("a" if object_kind == "artifact" else "r") * 64
        submission = submit(
            MARKET,
            "indicator",
            "sma",
            object_id,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        deletion_started = (
            artifacts.artifact_deletion_started
            if object_kind == "artifact"
            else artifacts.recipe_deletion_started
        )
        assert deletion_started.wait(3.0)
        assert application.cancel(submission.task_id) is False
        if object_kind == "artifact":
            artifacts.release_artifact_deletion.set()
        else:
            artifacts.release_recipe_deletion.set()
        assert ready.wait(3.0)
        assert results[0].value == DataManagerDeletionResult(
            MARKET, object_kind, "indicator", "sma", object_id
        )
        assert artifacts.artifact_delete_calls == (object_kind == "artifact")
        assert artifacts.recipe_delete_calls == (object_kind == "recipe")
    finally:
        artifacts.release_artifact_deletion.set()
        artifacts.release_recipe_deletion.set()
        runner.shutdown()


def _submit_catalog_deletion(application, operation: str, callback):
    if operation == "portable_recipe":
        return application.submit_delete_portable_recipe(
            "a" * 64, result_callback=callback
        )
    if operation == "recipe_collection":
        return application.submit_delete_recipe_collection(
            "prc_" + "b" * 32, result_callback=callback
        )
    if operation == "managed_artifact":
        return application.submit_delete_managed_artifact(
            MARKET, "c" * 64, result_callback=callback
        )
    return application.submit_delete_artifact_collection(
        "ac_" + "d" * 32, result_callback=callback
    )


@pytest.mark.parametrize(
    ("operation", "operation_id"),
    (
        ("portable_recipe", "data_manager.delete_portable_recipe"),
        ("recipe_collection", "data_manager.delete_recipe_collection"),
        ("managed_artifact", "data_manager.delete_managed_artifact"),
        ("artifact_collection", "data_manager.delete_artifact_collection"),
    ),
)
def test_catalog_deletion_uses_core_and_cancels_before_destructive_gate(
    operation, operation_id
) -> None:
    service = _ControlledCatalogDeletionService()
    manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = _submit_catalog_deletion(
            application,
            operation,
            lambda result: (results.append(result), ready.set()),
        )
        assert service.preflight_entered.wait(3.0)
        assert application.cancel(submission.task_id) is True
        service.release_preflight.set()
        assert ready.wait(3.0)
        assert results[0].status == "cancelled"
        assert service.deleted == []
        assert any(
            item.metadata.get("operation") == operation_id
            for item in manager.snapshots()
        )
    finally:
        service.release_preflight.set()
        service.release_deletion.set()
        runner.shutdown()


@pytest.mark.parametrize(
    "operation",
    ("portable_recipe", "recipe_collection", "managed_artifact", "artifact_collection"),
)
def test_catalog_deletion_refuses_cancellation_after_destructive_gate(operation) -> None:
    service = _ControlledCatalogDeletionService()
    _manager, runner, application = _application(service=service)
    ready = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = _submit_catalog_deletion(
            application,
            operation,
            lambda result: (results.append(result), ready.set()),
        )
        assert service.preflight_entered.wait(3.0)
        service.release_preflight.set()
        assert service.deletion_started.wait(3.0)
        assert application.cancel(submission.task_id) is False
        service.release_deletion.set()
        assert ready.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value == operation
        assert service.deleted == [operation]
    finally:
        service.release_preflight.set()
        service.release_deletion.set()
        runner.shutdown()
