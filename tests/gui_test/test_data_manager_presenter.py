from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from leonardo.artifacts import (
    ManagedArtifactSummary,
    ManagedArtifactVersionKey,
    OHLCVSourceFingerprintV1,
)
from leonardo.core.core_runner import TaskProgress, TaskResult, TaskSubmission
from leonardo.data import MarketId
from leonardo.data_manager import (
    BatchArtifactPlan,
    ArtifactCollectionRevisionV1,
    DataManagerApplicationService,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
    DataManagerManagedArtifactCatalog,
    DataManagerPortableRecipeCatalog,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionCatalog,
    DataManagerRecipeCollectionEntry,
    DataManagerReconciliationSnapshot,
    DataManagerRecipeDerivationPlan,
    DataManagerRecipePersistenceResult,
    DataManagerStudyEntryPortability,
    DataManagerStudyEnvironmentCatalog,
    DataManagerStudyEnvironmentEntry,
    DataManagerStudyEnvironmentInspection,
)
from leonardo.data_manager.construct_batch import (
    ConstructBatchExpansionRequest,
    ConstructBatchSourceScope,
    catalog_signals,
    expand_construct_batch,
)
from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
    DataManagerDirectArtifactRequest,
    DataManagerDirectArtifactResult,
)
from leonardo.data_manager.models import (
    DataManagerArtifactMaterializationResult,
    DataManagerArtifactEntry,
    DataManagerDeletionResult,
    DataManagerManagedArtifactEntry,
    DataManagerPortableRecipeEntry,
)
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from leonardo.recipes import (
    PortableRecipeCollectionRevisionV1,
    PortableRecipeOHLCVInputV1,
    build_portable_recipe,
)


_QAPP = QApplication.instance() or QApplication([])


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
MARKET_B = MarketId("bybit", "linear", "ETHUSDT", "4h")
DATASET = DataManagerDatasetEntry(MARKET, True, 1, 0, 0)
DATASET_B = DataManagerDatasetEntry(MARKET_B, True, 1, 0, 0)
CATALOG = DataManagerCatalogSnapshot((DATASET,))
CATALOG_BOTH = DataManagerCatalogSnapshot((DATASET, DATASET_B))
MARKET_SNAPSHOT = DataManagerMarketSnapshot(MARKET, DATASET, (), ())
MARKET_SNAPSHOT_B = DataManagerMarketSnapshot(MARKET_B, DATASET_B, (), ())


class _ControlledApplication(DataManagerApplicationService):
    def __init__(self, *, product_catalogs: bool = False):
        self.calls = []
        self.cancelled = []
        self.reconcile_forces = []
        self.progress_callbacks = {}
        self._counter = 0
        if product_catalogs:
            self._service = object()

    def _submit(self, operation, result_callback, progress_callback=None):
        self._counter += 1
        task_id = f"task-{self._counter}"
        self.calls.append((operation, task_id, result_callback))
        if progress_callback is not None:
            self.progress_callbacks[task_id] = progress_callback
        return TaskSubmission(task_id, operation)

    def submit_scan_catalog(self, **values):
        return self._submit("scan", values["result_callback"])

    def submit_inspect_market(self, market_id, **values):
        return self._submit(("inspect", market_id), values["result_callback"])

    def submit_preview_dataset(self, market_id, **values):
        return self._submit(("preview_dataset", market_id), values["result_callback"])

    def submit_inspect_portable_recipe(self, recipe_id, **values):
        return self._submit(
            ("inspect_recipe", recipe_id), values["result_callback"]
        )

    def submit_inspect_study_environment(self, environment_id, **values):
        return self._submit(
            ("inspect_environment", environment_id), values["result_callback"]
        )

    def submit_plan_recipe_derivation(
        self, environment_id, root_entry_ids, **values
    ):
        return self._submit(
            ("plan_recipe_derivation", environment_id, root_entry_ids),
            values["result_callback"],
        )

    def submit_persist_recipe_derivation(
        self,
        environment_id,
        root_entry_ids,
        *,
        create_collection,
        collection_display_name="",
        collection_description="",
        **values,
    ):
        return self._submit(
            (
                "persist_recipe_derivation",
                environment_id,
                root_entry_ids,
                create_collection,
                collection_display_name,
                collection_description,
            ),
            values["result_callback"],
        )

    def submit_plan_recipe_collection(self, root_recipe_ids, **values):
        return self._submit(
            ("plan_recipe_collection", root_recipe_ids),
            values["result_callback"],
        )

    def submit_create_recipe_collection(
        self, display_name, description, root_recipe_ids, **values
    ):
        return self._submit(
            (
                "create_recipe_collection",
                display_name,
                description,
                root_recipe_ids,
            ),
            values["result_callback"],
        )

    def submit_update_recipe_collection(
        self,
        collection_id,
        display_name,
        description,
        root_recipe_ids,
        *,
        expected_revision_id=None,
        **values,
    ):
        return self._submit(
            (
                "update_recipe_collection",
                collection_id,
                display_name,
                description,
                root_recipe_ids,
                expected_revision_id,
            ),
            values["result_callback"],
        )

    def submit_inspect_recipe_collection(
        self, collection_id, revision_id=None, **values
    ):
        return self._submit(
            ("inspect_recipe_collection", collection_id, revision_id),
            values["result_callback"],
        )

    def submit_plan_artifact_collection_selection(
        self, market_id, root_logical_artifact_ids, **values
    ):
        return self._submit(
            (
                "plan_artifact_collection_selection",
                market_id,
                root_logical_artifact_ids,
            ),
            values["result_callback"],
        )

    def submit_create_artifact_collection_from_selection(
        self,
        plan,
        display_name,
        *,
        description="",
        selected_outputs=None,
        **values,
    ):
        return self._submit(
            (
                "create_artifact_collection_from_selection",
                plan,
                display_name,
                description,
                selected_outputs,
            ),
            values["result_callback"],
        )

    def submit_edit_artifact_collection_from_selection(
        self,
        collection_id,
        plan,
        *,
        display_name=None,
        description=None,
        selected_outputs=None,
        presentation_order=None,
        expected_revision_id,
        **values,
    ):
        return self._submit(
            (
                "edit_artifact_collection_from_selection",
                collection_id,
                plan,
                display_name,
                description,
                selected_outputs,
                presentation_order,
                expected_revision_id,
            ),
            values["result_callback"],
        )

    def submit_inspect_managed_artifact(
        self, market_id, logical_artifact_id, **values
    ):
        return self._submit(
            ("inspect_artifact", market_id, logical_artifact_id),
            values["result_callback"],
        )

    def submit_build_direct_artifact_catalog(self, market_id, **values):
        return self._submit(
            ("direct_catalog", market_id), values["result_callback"]
        )

    def submit_create_direct_artifact(self, request, **values):
        return self._submit(("direct_create", request), values["result_callback"])

    def submit_plan_batch_artifacts(self, request, **values):
        return self._submit(("batch_plan", request), values["result_callback"])

    def submit_execute_batch_artifacts(self, plan, **values):
        return self._submit(("batch_execute", plan), values["result_callback"])

    def submit_scan_creation_foundations(self, **values):
        return self._submit("scan_creation_foundations", values["result_callback"])

    def submit_reconcile_status(self, **values):
        self.reconcile_forces.append(values["force"])
        return self._submit(
            "reconcile_status",
            values["result_callback"],
            values["progress_callback"],
        )

    def submit_scan_product_catalogs(self, **values):
        return self._submit(
            "scan_product_catalogs",
            values["result_callback"],
            values["progress_callback"],
        )

    def submit_delete_portable_recipe(self, recipe_id, **values):
        return self._submit(
            ("delete_portable_recipe", recipe_id), values["result_callback"]
        )

    def submit_delete_recipe_collection(self, collection_id, **values):
        return self._submit(
            ("delete_recipe_collection", collection_id), values["result_callback"]
        )

    def submit_delete_managed_artifact(
        self, market_id, logical_artifact_id, **values
    ):
        return self._submit(
            ("delete_managed_artifact", market_id, logical_artifact_id),
            values["result_callback"],
        )

    def submit_delete_artifact_collection(self, collection_id, **values):
        return self._submit(
            ("delete_artifact_collection", collection_id),
            values["result_callback"],
        )

    def submit_delete_artifact(
        self, market_id, kind, tool_key, artifact_id, **values
    ):
        return self._submit(
            ("delete_artifact", market_id, kind, tool_key, artifact_id),
            values["result_callback"],
        )

    def submit_delete_recipe(
        self, market_id, kind, tool_key, recipe_id, **values
    ):
        return self._submit(
            ("delete_recipe", market_id, kind, tool_key, recipe_id),
            values["result_callback"],
        )

    def cancel(self, task_id):
        self.cancelled.append(task_id)
        return True


def _settle_initial_scan(service: _ControlledApplication) -> None:
    scan = service.calls[0]
    scan[2](TaskResult(scan[1], "completed", CATALOG))


def _fingerprint(market: MarketId = MARKET) -> OHLCVSourceFingerprintV1:
    return OHLCVSourceFingerprintV1(
        market, "1" * 64, "2" * 64, 1, 0, 0, "committed", "ok", "1.0"
    )


def _reconciliation(signature: str) -> DataManagerReconciliationSnapshot:
    return DataManagerReconciliationSnapshot(
        datetime(2026, 8, 15, tzinfo=UTC),
        (),
        (),
        (),
        (),
        (),
        signature * 64,
    )


def _product_catalog(
    signature: str,
    *,
    catalog: DataManagerCatalogSnapshot = CATALOG,
    portable_recipes: DataManagerPortableRecipeCatalog | None = None,
) -> DataManagerProductCatalogSnapshot:
    return DataManagerProductCatalogSnapshot(
        catalog,
        DataManagerStudyEnvironmentCatalog(()),
        portable_recipes or DataManagerPortableRecipeCatalog(()),
        DataManagerRecipeCollectionCatalog(()),
        DataManagerManagedArtifactCatalog(()),
        (),
        (),
        (),
        _reconciliation(signature),
    )


def _settle_initial_warmup(
    service: _ControlledApplication,
    *,
    snapshot: DataManagerProductCatalogSnapshot | None = None,
) -> DataManagerProductCatalogSnapshot:
    snapshot = snapshot or _product_catalog("a")
    reconcile = service.calls[-1]
    assert reconcile[0] == "reconcile_status"
    reconcile[2](
        TaskResult(
            reconcile[1],
            "completed",
            snapshot.latest_reconciliation,
        )
    )
    scan = service.calls[-1]
    assert scan[0] == "scan_product_catalogs"
    scan[2](TaskResult(scan[1], "completed", snapshot))
    return snapshot


def _direct_catalog(market: MarketId = MARKET) -> DataManagerDirectArtifactCatalog:
    return DataManagerDirectArtifactCatalog(market, _fingerprint(market), (), ())


def _derivation_inspection(
    recipe_id: str = "a" * 64,
) -> DataManagerStudyEnvironmentInspection:
    environment = DataManagerStudyEnvironmentEntry(
        "environment_1",
        "Environment",
        "Description",
        MARKET,
        1,
        1,
        0,
        0,
        0,
        0,
        datetime(2026, 8, 17, tzinfo=UTC),
        datetime(2026, 8, 17, tzinfo=UTC),
    )
    entry = DataManagerStudyEntryPortability(
        "entry_1",
        "EMA",
        "calculation",
        "indicator",
        "ema",
        "PORTABLE",
        "",
        (),
        recipe_id,
    )
    return DataManagerStudyEnvironmentInspection(environment, (entry,))


def _derivation_plan(
    *, blockers: tuple[str, ...] = (), recipe_id: str = "a" * 64
) -> DataManagerRecipeDerivationPlan:
    value = object.__new__(DataManagerRecipeDerivationPlan)
    attributes = {
        "environment_id": "environment_1",
        "environment_content_hash": "b" * 64,
        "root_entry_ids": ("entry_1",),
        "support_entry_ids": (),
        "entry_classifications": _derivation_inspection(recipe_id).entries,
        "recipes": (),
        "provenances": (),
        "dependency_edges": (),
        "execution_stages": (),
        "warnings": (),
        "blockers": blockers,
    }
    for name, item in attributes.items():
        object.__setattr__(value, name, item)
    return value


def _open_derivation_dialog(
    view: DataManagerSuiteWindow,
    service: _ControlledApplication,
    *,
    recipe_id: str = "a" * 64,
) -> object:
    inspection = _derivation_inspection(recipe_id)
    view.derive_recipes_requested.emit(inspection.environment)
    call = service.calls[-1]
    assert call[0] == ("inspect_environment", "environment_1")
    call[2](TaskResult(call[1], "completed", inspection))
    dialog = view.recipe_derivation_dialog()
    assert dialog is not None and dialog.isVisible()
    dialog.study_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    return dialog


def _batch_catalog(
    market: MarketId = MARKET,
    *,
    source: OHLCVSourceFingerprintV1 | None = None,
) -> DataManagerDirectArtifactCatalog:
    source = source or _fingerprint(market)
    return DataManagerDirectArtifactCatalog(
        market,
        source,
        (
            DataManagerDirectArtifactOption(
                market,
                "a" * 64,
                "b" * 64,
                "sma",
                "indicator",
                "SMA",
                ("sma_3",),
                source,
            ),
        ),
        (),
    )


def _batch_plan(
    request, *, reuse_current: tuple[bool, ...] | None = None
) -> BatchArtifactPlan:
    reuse_current = reuse_current or (False,) * len(request.branches)
    recipe_ids = tuple(
        f"{index:064x}" for index in range(1, len(request.branches) + 1)
    )
    new_recipe_ids = tuple(
        recipe_id
        for recipe_id, reuse in zip(recipe_ids, reuse_current, strict=True)
        if not reuse
    )
    reusable_recipe_ids = tuple(
        recipe_id
        for recipe_id, reuse in zip(recipe_ids, reuse_current, strict=True)
        if reuse
    )
    return BatchArtifactPlan(
        request=request,
        branch_recipe_ids=recipe_ids,
        branch_reuse_current=reuse_current,
        recipe_ids=recipe_ids,
        dependency_edges=(),
        execution_stages=(recipe_ids,),
        new_recipe_ids=new_recipe_ids,
        reusable_recipe_ids=reusable_recipe_ids,
        new_logical_artifact_ids=tuple(
            f"{index:064x}" for index in range(101, 101 + len(new_recipe_ids))
        ),
        reusable_logical_artifact_ids=tuple(
            f"{index:064x}"
            for index in range(201, 201 + len(reusable_recipe_ids))
        ),
        naming_collisions=(),
        unsupported_combinations=(),
        blockers=(),
    )


def _direct_request(market: MarketId = MARKET) -> DataManagerDirectArtifactRequest:
    return DataManagerDirectArtifactRequest(
        market, _fingerprint(market), "sma", {"period": 3}, ()
    )


def _direct_result(market: MarketId = MARKET) -> DataManagerDirectArtifactResult:
    recipe_id = "f" * 64
    logical_artifact_id = "d" * 64
    artifact_id = "c" * 64
    managed = DataManagerManagedArtifactEntry(
        logical_artifact_id,
        recipe_id,
        market,
        artifact_id,
        None,
        "sma",
        "indicator",
        ("sma_3",),
        1,
        0,
        0,
        datetime(2026, 8, 9, tzinfo=UTC),
    )
    return DataManagerDirectArtifactResult(
        recipe_id,
        DataManagerArtifactMaterializationResult(
            "e" * 64,
            market,
            _fingerprint(market),
            (logical_artifact_id,),
            (),
            (artifact_id,),
            (),
            (ManagedArtifactVersionKey(logical_artifact_id, artifact_id),),
            (),
            (logical_artifact_id,),
            (managed,),
        ),
    )


def _deletion_values():
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("source", "close"),),
    )
    recipe_entry = DataManagerPortableRecipeEntry(
        recipe.recipe_id,
        recipe.tool_key,
        recipe.tool_version,
        recipe.kind,
        recipe.parameters,
        recipe.output_names,
        ("source=OHLCV.close",),
        0,
        1,
        (),
        (),
        (),
        0,
    )
    recipe_collection = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_" + "1" * 32,
        display_name="Portable Recipes",
        description="",
        root_recipe_ids=(recipe.recipe_id,),
        member_recipe_ids=(recipe.recipe_id,),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 17, tzinfo=UTC),
    )
    recipe_collection_entry = DataManagerRecipeCollectionEntry(
        recipe_collection.collection_id,
        recipe_collection.revision_id,
        recipe_collection.display_name,
        recipe_collection.description,
        1,
        1,
        (recipe.recipe_id,),
        0,
        1,
        recipe_collection.created_at_utc,
        recipe_collection.created_at_utc,
    )
    artifact_entry = DataManagerManagedArtifactEntry(
        "2" * 64,
        recipe.recipe_id,
        MARKET,
        "3" * 64,
        None,
        "sma",
        "indicator",
        ("sma_20",),
        1,
        0,
        0,
        datetime(2026, 8, 17, tzinfo=UTC),
    )
    artifact_summary = ManagedArtifactSummary(
        artifact_entry.logical_artifact_id,
        artifact_entry.portable_recipe_id,
        artifact_entry.market_id,
        artifact_entry.artifact_id,
        artifact_entry.previous_artifact_id,
        artifact_entry.tool_key,
        artifact_entry.kind,
        artifact_entry.output_names,
        artifact_entry.row_count,
        artifact_entry.first_timestamp_ms,
        artifact_entry.last_timestamp_ms,
        artifact_entry.created_at_utc,
    )
    artifact_collection = object.__new__(ArtifactCollectionRevisionV1)
    for name, value in {
        "collection_id": "ac_" + "4" * 32,
        "revision_id": "5" * 64,
        "display_name": "Managed Artifacts",
        "description": "",
        "market_id": MARKET,
        "root_logical_artifact_ids": (artifact_entry.logical_artifact_id,),
        "support_logical_artifact_ids": (),
        "members": (object(),),
        "dependency_edges": (),
        "selected_outputs": (object(),),
        "presentation_order": ("sma_20",),
        "source_portable_recipe_ids": (recipe.recipe_id,),
        "source_recipe_collection_id": None,
        "source_recipe_collection_revision_id": None,
        "source_ohlcv": _fingerprint(),
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 0,
        "database_ready": True,
        "validation_state": "valid",
        "previous_revision_id": None,
        "created_at_utc": datetime(2026, 8, 17, tzinfo=UTC),
        "revised_at_utc": datetime(2026, 8, 17, tzinfo=UTC),
        "schema_version": "1.0",
        "object_type": "artifact_collection_revision",
    }.items():
        object.__setattr__(artifact_collection, name, value)
    return (
        recipe,
        recipe_entry,
        recipe_collection,
        recipe_collection_entry,
        artifact_summary,
        artifact_entry,
        artifact_collection,
    )


def _open_both_creation_dialogs(
    view: DataManagerSuiteWindow,
    service: _ControlledApplication,
    presenter: DataManagerSuitePresenter,
):
    scan = service.calls[0]
    scan[2](TaskResult(scan[1], "completed", CATALOG_BOTH))
    presenter.focus_market(MARKET, source="research")
    inspect = service.calls[-1]
    inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))

    view.create_artifact_requested.emit()
    direct_catalog = service.calls[-1]
    direct_catalog[2](
        TaskResult(direct_catalog[1], "completed", _direct_catalog())
    )
    direct_dialog = view.artifact_creation_dialog()

    view.batch_constructs_requested.emit()
    batch_catalog = service.calls[-1]
    batch_catalog[2](TaskResult(batch_catalog[1], "completed", _batch_catalog()))
    batch_dialog = view.construct_batch_dialog()

    assert direct_dialog is not None and direct_dialog.isVisible()
    assert batch_dialog is not None and batch_dialog.isVisible()
    assert direct_dialog.market_id == MARKET
    assert batch_dialog.market_id == MARKET
    return direct_dialog, batch_dialog


def test_presenter_scans_focuses_exact_market_and_ignores_stale_result() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        presenter.focus_market(MARKET, source="research")
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG))
        inspect = service.calls[1]
        assert inspect[0] == ("inspect", MARKET)

        inspect[2](TaskResult("foreign", "completed", MARKET_SNAPSHOT))
        assert view._operation_surface.context_text() == "Loading accepted dataset..."

        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        assert presenter.selected_market_id == MARKET
        assert view.selected_market_id() == MARKET
        assert view._operation_surface.context_text() == (
            "Accepted dataset ready for preview and Database workflows."
        )
        assert view.status_text() == "Market inspection ready"
    finally:
        view.close()


def test_recipe_derivation_preview_persistence_collection_and_refresh_are_exact() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        assert presenter.selected_market_id is None
        dialog = _open_derivation_dialog(view, service)

        dialog.preview_button.click()
        preview = service.calls[-1]
        assert preview[0] == (
            "plan_recipe_derivation",
            "environment_1",
            ("entry_1",),
        )
        preview[2](TaskResult(preview[1], "completed", _derivation_plan()))
        assert dialog.create_button.isEnabled()

        dialog.collection_checkbox.setChecked(True)
        dialog.collection_name.setText("Portable Graph")
        dialog.collection_description.setText("Reviewed Recipes")
        dialog.create_button.click()
        persistence = service.calls[-1]
        assert persistence[0] == (
            "persist_recipe_derivation",
            "environment_1",
            ("entry_1",),
            True,
            "Portable Graph",
            "Reviewed Recipes",
        )
        result = DataManagerRecipePersistenceResult(
            "environment_1",
            ("a" * 64,),
            (),
            "collection_1",
            "c" * 64,
        )
        persistence[2](TaskResult(persistence[1], "completed", result))

        assert view.recipe_derivation_dialog() is dialog
        assert dialog.isVisible()
        assert "Recipes created/reused successfully" in dialog.status_label.text()
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.create_button.isEnabled()
        assert service.calls[-1][0] == "reconcile_status"
        assert presenter.selected_market_id is None

        refreshed_recipe_id = "b" * 64
        refreshed = _product_catalog(
            "b",
            portable_recipes=DataManagerPortableRecipeCatalog(
                (
                    DataManagerPortableRecipeEntry(
                        refreshed_recipe_id,
                        "ema",
                        "1.0",
                        "indicator",
                        {"period": 20},
                        ("ema_20",),
                        ("source=OHLCV.close",),
                        0,
                        1,
                        (),
                        (),
                        (),
                        0,
                    ),
                )
            ),
        )
        reconcile = service.calls[-1]
        reconcile[2](
            TaskResult(
                reconcile[1],
                "completed",
                refreshed.latest_reconciliation,
            )
        )
        product_scan = service.calls[-1]
        assert product_scan[0] == "scan_product_catalogs"
        product_scan[2](TaskResult(product_scan[1], "completed", refreshed))

        assert dialog.set_plan(_derivation_plan(recipe_id=refreshed_recipe_id))
        assert dialog.preview_table.item(0, 5).text() == "Existing"
        assert presenter.selected_market_id is None
    finally:
        view.close()


def test_blocked_and_late_recipe_derivation_results_cannot_execute_or_resurrect() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        dialog = _open_derivation_dialog(view, service)
        dialog.preview_button.click()
        preview = service.calls[-1]
        preview[2](
            TaskResult(
                preview[1],
                "completed",
                _derivation_plan(blockers=("blocked",)),
            )
        )
        assert not dialog.create_button.isEnabled()
        call_count = len(service.calls)
        view.recipe_derivation_create_requested.emit(
            "environment_1", ("entry_1",), False, "", ""
        )
        assert len(service.calls) == call_count

        dialog.invalidate_preview()
        dialog.preview_button.click()
        late_preview = service.calls[-1]
        dialog.close()
        assert view.recipe_derivation_dialog() is None
        late_preview[2](
            TaskResult(late_preview[1], "completed", _derivation_plan())
        )
        assert view.recipe_derivation_dialog() is None
    finally:
        view.close()


def test_late_recipe_persistence_refreshes_without_resurrecting_closed_dialog() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        dialog = _open_derivation_dialog(view, service)
        dialog.preview_button.click()
        preview = service.calls[-1]
        preview[2](TaskResult(preview[1], "completed", _derivation_plan()))
        dialog.create_button.click()
        persistence = service.calls[-1]
        dialog.close()
        assert view.recipe_derivation_dialog() is None

        result = DataManagerRecipePersistenceResult(
            "environment_1", ("a" * 64,), ()
        )
        persistence[2](TaskResult(persistence[1], "completed", result))
        assert view.recipe_derivation_dialog() is None
        assert service.calls[-1][0] == "reconcile_status"
    finally:
        view.close()


def test_dispose_cancels_one_active_task_and_is_idempotent() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        presenter.dispose()
        presenter.dispose()
        assert service.cancelled == ["task-1"]
    finally:
        view.close()


def test_same_market_focus_reinspects_once_without_legacy_object_tables() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        first = service.calls[-1]
        first[2](TaskResult(first[1], "completed", MARKET_SNAPSHOT))
        before = len(service.calls)

        presenter.focus_market(MARKET, source="research")
        view.market_selected.emit(MARKET)

        assert len(service.calls) == before + 1
        inspect = service.calls[-1]
        assert inspect[0] == ("inspect", MARKET)
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        assert presenter.selected_market_id == MARKET
        assert "data_manager.table.artifacts" not in view._tables
        assert "data_manager.table.recipes" not in view._tables
    finally:
        view.close()


@pytest.mark.parametrize("include_rejection", (True, False))
def test_unavailable_focus_clears_prior_market_and_dataset_action(
    include_rejection,
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    unavailable = MarketId("bybit", "linear", "ETHUSDT", "1h")
    rejected_entry = DataManagerDatasetEntry(
        unavailable,
        False,
        rejection_code="hash",
        rejection_reason="source changed",
    )
    catalog = DataManagerCatalogSnapshot(
        (DATASET, rejected_entry) if include_rejection else (DATASET,)
    )
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", catalog))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))

        presenter.focus_market(unavailable, source="research")

        assert presenter.selected_market_id is None
        assert view.selected_market_id() is None
        expected = (
            "hash: source changed"
            if include_rejection
            else "missing from canonical persistence"
        )
        assert expected in view.status_text()
        assert not view.button_for_id("data_manager.button.preview_dataset").isEnabled()
    finally:
        view.close()


def test_market_unavailable_preview_clears_stale_dataset_selection() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))

        view.preview_dataset_requested.emit()
        preview = service.calls[-1]
        message = f"Dataset {MARKET.as_key()} is unavailable: hash: changed"
        preview[2](
            TaskResult(
                preview[1],
                "failed",
                error_type="DataManagerMarketUnavailableError",
                error_message=message,
            )
        )

        assert presenter.selected_market_id is None
        assert view.selected_market_id() is None
        assert view.status_text() == message
        assert not view.button_for_id("data_manager.button.preview_dataset").isEnabled()
    finally:
        view.close()


def test_ordinary_dataset_preview_failure_preserves_current_selection() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))

        view.preview_dataset_requested.emit()
        preview = service.calls[-1]
        preview[2](
            TaskResult(
                preview[1],
                "failed",
                error_type="OSError",
                error_message="ordinary preview failure",
            )
        )

        assert presenter.selected_market_id == MARKET
        assert view.selected_market_id() == MARKET
        assert view.button_for_id("data_manager.button.preview_dataset").isEnabled()
        assert view.status_text() == "Preview failed"
    finally:
        view.close()


def test_presenter_routes_renamed_global_recipe_and_artifact_families() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)

        recipe = SimpleNamespace(recipe_id="r" * 64)
        view.catalog_row_selected.emit("Recipes", recipe)
        recipe_call = service.calls[-1]
        assert recipe_call[0] == ("inspect_recipe", recipe.recipe_id)
        recipe_call[2](
            TaskResult(
                recipe_call[1],
                "completed",
                SimpleNamespace(recipe_id=recipe.recipe_id, tool_key="rsi"),
            )
        )
        assert view._catalog_workspace.inspector.rowCount() == 1

        logical_id = "a" * 64
        artifact = SimpleNamespace(
            market_id=MARKET,
            logical_artifact_id=logical_id,
        )
        view.catalog_row_selected.emit("Artifacts", artifact)
        artifact_call = service.calls[-1]
        assert artifact_call[0] == ("inspect_artifact", MARKET, logical_id)
        version = SimpleNamespace(
            artifact_id="b" * 64,
            created_at_utc="2026-08-06T00:00:00+00:00",
        )
        artifact_call[2](
            TaskResult(
                artifact_call[1],
                "completed",
                SimpleNamespace(versions=(version,), current=artifact),
            )
        )
        assert view._catalog_workspace.history.rowCount() == 1
    finally:
        view.close()


def test_direct_artifact_open_create_success_refresh_and_stale_fencing() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))

        view.create_artifact_requested.emit()
        catalog_call = service.calls[-1]
        assert catalog_call[0] == ("direct_catalog", MARKET)
        catalog_call[2](TaskResult("foreign", "completed", _direct_catalog()))
        assert view.artifact_creation_dialog() is None
        catalog_call[2](
            TaskResult(catalog_call[1], "completed", _direct_catalog())
        )
        dialog = view.artifact_creation_dialog()
        assert dialog is not None
        sma_row = next(
            row
            for row in range(dialog.tool_list.count())
            if dialog.tool_list.item(row).data(Qt.ItemDataRole.UserRole).key
            == "sma"
        )
        dialog.tool_list.setCurrentRow(sma_row)

        request = _direct_request()
        view.calculate_artifact_requested.emit(request)
        create_call = service.calls[-1]
        assert create_call[0] == ("direct_create", request)
        create_call[2](TaskResult(create_call[1], "completed", _direct_result()))
        assert dialog.status_label.text() == f"Root Artifact created: {'d' * 64}"
        refresh_call = service.calls[-1]
        assert refresh_call[0] == ("direct_catalog", MARKET)
        surface = view._operation_surface
        detail_values = {
            surface.details.item(row, 0).text(): surface.details.item(row, 1).text()
            for row in range(surface.details.rowCount())
        }
        assert detail_values["Operation"] == "create_direct_artifact"
        assert detail_values["State"] == "completed"
        assert detail_values["Published"] == "yes"
        operation_report = (
            surface._name.text(),
            surface.state,
            surface._message.text(),
            tuple(
                (
                    surface.details.item(row, 0).text(),
                    surface.details.item(row, 1).text(),
                )
                for row in range(surface.details.rowCount())
            ),
        )
        service._service = object()
        refresh_call[2](
            TaskResult(refresh_call[1], "completed", _direct_catalog())
        )
        assert (
            surface._name.text(),
            surface.state,
            surface._message.text(),
            tuple(
                (
                    surface.details.item(row, 0).text(),
                    surface.details.item(row, 1).text(),
                )
                for row in range(surface.details.rowCount())
            ),
        ) == operation_report
        assert service.calls[-1][0] == "reconcile_status"
        reconciliation = service.calls[-1]
        reconciliation[2](
            TaskResult(reconciliation[1], "completed", _reconciliation("a"))
        )
        assert service.calls[-1][0] == "scan_product_catalogs"
        assert (surface._name.text(), surface.state, surface._message.text()) == (
            operation_report[0],
            operation_report[1],
            operation_report[2],
        )

        service.calls[-1][2](
            TaskResult(service.calls[-1][1], "failed", error_message="stop")
        )
        view.create_artifact_requested.emit()
        stale_call = service.calls[-1]
        presenter._market_generation += 1
        stale_call[2](TaskResult(stale_call[1], "completed", _direct_catalog()))
        assert view.artifact_creation_dialog() is dialog
    finally:
        view.close()


def test_closed_direct_artifact_dialog_stays_closed_during_source_refresh() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.create_artifact_requested.emit()
        catalog_call = service.calls[-1]
        catalog_call[2](TaskResult(catalog_call[1], "completed", _direct_catalog()))
        dialog = view.artifact_creation_dialog()
        assert dialog is not None and dialog.isVisible()

        view.calculate_artifact_requested.emit(_direct_request())
        create_call = service.calls[-1]
        create_call[2](TaskResult(create_call[1], "completed", _direct_result()))
        refresh_call = service.calls[-1]
        assert refresh_call[0] == ("direct_catalog", MARKET)
        surface = view._operation_surface
        operation_report = tuple(
            (
                surface.details.item(row, 0).text(),
                surface.details.item(row, 1).text(),
            )
            for row in range(surface.details.rowCount())
        )
        assert dict(operation_report)["Published"] == "yes"

        dialog.close()
        QApplication.processEvents()
        assert not dialog.isVisible()
        service._service = object()
        refresh_call[2](
            TaskResult(refresh_call[1], "completed", _direct_catalog())
        )

        assert view.artifact_creation_dialog() is dialog
        assert not dialog.isVisible()
        assert service.calls[-1][0] == "reconcile_status"
        assert tuple(
            (
                surface.details.item(row, 0).text(),
                surface.details.item(row, 1).text(),
            )
            for row in range(surface.details.rowCount())
        ) == operation_report
    finally:
        view.close()


def test_direct_artifact_failure_does_not_fake_success() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.create_artifact_requested.emit()
        catalog_call = service.calls[-1]
        catalog_call[2](TaskResult(catalog_call[1], "completed", _direct_catalog()))
        dialog = view.artifact_creation_dialog()
        before = dialog.status_label.text()

        view.calculate_artifact_requested.emit(_direct_request())
        create_call = service.calls[-1]
        create_call[2](
            TaskResult(create_call[1], "failed", error_message="calculation failed")
        )
        assert dialog.status_label.text() == before
        assert "failed" in view.status_text().casefold()
    finally:
        view.close()


def test_construct_batch_preview_execute_and_closed_window_fencing() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))

        view.batch_constructs_requested.emit()
        catalog_call = service.calls[-1]
        assert catalog_call[0] == ("direct_catalog", MARKET)
        catalog = _batch_catalog()
        catalog_call[2](TaskResult(catalog_call[1], "completed", catalog))
        dialog = view.construct_batch_dialog()
        assert dialog is not None and dialog.isVisible()

        signal = catalog_signals(catalog)[0]
        expansion = ConstructBatchExpansionRequest(
            catalog,
            "derivative",
            {},
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(signal,),
        )
        request = expand_construct_batch(expansion)
        view.batch_construct_preview_requested.emit(expansion)
        plan_call = service.calls[-1]
        assert plan_call[0] == ("batch_plan", request)
        plan = _batch_plan(request)
        plan_call[2](TaskResult(plan_call[1], "completed", plan))
        assert dialog.preview_table.rowCount() == 1
        assert dialog.execute_button.isEnabled()

        view.batch_construct_execute_requested.emit()
        execute_call = service.calls[-1]
        assert execute_call[0] == ("batch_execute", plan)
        dialog.close()
        QApplication.processEvents()
        service._service = object()
        execute_call[2](
            TaskResult(
                execute_call[1],
                "completed",
                (_direct_result().materialization, None),
            )
        )
        assert view.construct_batch_dialog() is dialog
        assert not dialog.isVisible()
        assert dialog.execution_report is None
        assert service.calls[-1][0] == "reconcile_status"
    finally:
        view.close()


def test_batch_plan_summary_uses_artifact_counts() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        request = expand_construct_batch(
            ConstructBatchExpansionRequest(
                _batch_catalog(),
                "derivative",
                {},
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(catalog_signals(_batch_catalog())[0],),
            )
        )
        plan = _batch_plan(request)
        presenter._pending_batch_plan_context = object()

        presenter._settle_batch_plan(
            TaskResult("task-batch-plan", "completed", plan)
        )

        assert view._creation_summary.text() == (
            "Batch plan: 1 create/update Artifact(s), 0 reusable, blockers=0"
        )
    finally:
        view.close()


def test_construct_batch_success_reports_reviewed_plan_counts_and_refreshes_once() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.batch_constructs_requested.emit()
        catalog_call = service.calls[-1]
        catalog = _batch_catalog()
        catalog_call[2](TaskResult(catalog_call[1], "completed", catalog))
        dialog = view.construct_batch_dialog()
        assert dialog is not None and dialog.isVisible()

        signal = catalog_signals(catalog)[0]
        expansion = ConstructBatchExpansionRequest(
            catalog,
            "derivative",
            {},
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(signal,),
        )
        single_request = expand_construct_batch(expansion)
        request = replace(
            single_request,
            branches=single_request.branches * 8,
        )
        plan = _batch_plan(
            request,
            reuse_current=(False, False, True, False, True, False, False, False),
        )
        presenter._construct_batch_plan = plan
        presenter._pending_construct_batch_request = request
        dialog.set_plan(plan)
        service._service = object()
        calls_before = len(service.calls)

        presenter._settle_construct_batch_execution(
            TaskResult(
                "task-batch",
                "completed",
                (_direct_result().materialization, None),
            ),
            plan,
        )

        report = dialog.execution_report
        assert report is not None and report.isVisible()
        assert report.summary_label.text() == "8 / 8 branches completed successfully"
        assert report.new_label.text() == "New: 6"
        assert report.reused_label.text() == "Reuse Current: 2"
        assert dialog.reviewed_plan is None
        assert not dialog.execute_button.isEnabled()
        assert view.status_text() == "Construct Batch execution complete"
        assert len(service.calls) == calls_before + 1
        assert service.calls[-1][0] == "reconcile_status"
    finally:
        view.close()


@pytest.mark.parametrize(
    ("status", "error_message", "title", "summary"),
    (
        ("failed", "batch calculation failed", "Batch Execution Failed", "batch calculation failed"),
        ("cancelled", None, "Batch Execution Cancelled", "The batch operation was cancelled."),
    ),
)
def test_visible_construct_batch_reports_terminal_failure_and_cancellation(
    status, error_message, title, summary
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.batch_constructs_requested.emit()
        catalog_call = service.calls[-1]
        catalog = _batch_catalog()
        catalog_call[2](TaskResult(catalog_call[1], "completed", catalog))
        dialog = view.construct_batch_dialog()
        signal = catalog_signals(catalog)[0]
        request = expand_construct_batch(
            ConstructBatchExpansionRequest(
                catalog,
                "derivative",
                {},
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(signal,),
            )
        )
        plan = _batch_plan(request)
        presenter._construct_batch_plan = plan
        presenter._pending_construct_batch_request = request

        presenter._settle_construct_batch_execution(
            TaskResult("task-batch", status, error_message=error_message),
            plan,
        )

        report = dialog.execution_report
        assert report is not None and report.isVisible()
        assert report.windowTitle() == title
        assert report.summary_label.text() == summary
        assert report.new_label.isHidden()
        assert report.reused_label.isHidden()
        assert "Data Manager Operation panel" in report.details_label.text()
        assert view.status_text() == f"Construct Batch execution {status}"
        assert view._operation_surface.notes_text() == (error_message or status)
    finally:
        view.close()


@pytest.mark.parametrize("status", ("failed", "cancelled"))
def test_closed_construct_batch_does_not_show_terminal_failure(status) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.batch_constructs_requested.emit()
        catalog_call = service.calls[-1]
        catalog = _batch_catalog()
        catalog_call[2](TaskResult(catalog_call[1], "completed", catalog))
        dialog = view.construct_batch_dialog()
        signal = catalog_signals(catalog)[0]
        request = expand_construct_batch(
            ConstructBatchExpansionRequest(
                catalog,
                "derivative",
                {},
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(signal,),
            )
        )
        plan = _batch_plan(request)
        presenter._construct_batch_plan = plan
        dialog.close()
        QApplication.processEvents()

        presenter._settle_construct_batch_execution(
            TaskResult("task-batch", status, error_message="terminal result"),
            plan,
        )

        assert not dialog.isVisible()
        assert dialog.execution_report is None
        assert view.status_text() == f"Construct Batch execution {status}"
        assert view._operation_surface.notes_text() == "terminal result"
    finally:
        view.close()


def test_visible_construct_batch_retargets_and_filters_exact_collections() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        scan = service.calls[0]
        scan[2](TaskResult(scan[1], "completed", CATALOG_BOTH))
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.batch_constructs_requested.emit()
        catalog_call = service.calls[-1]
        catalog_call[2](TaskResult(catalog_call[1], "completed", _batch_catalog()))
        dialog = view.construct_batch_dialog()
        assert dialog is not None and dialog.isVisible()

        catalog = _batch_catalog()
        signal = catalog_signals(catalog)[0]
        expansion = ConstructBatchExpansionRequest(
            catalog,
            "derivative",
            {},
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(signal,),
        )
        request = expand_construct_batch(expansion)
        view.batch_construct_preview_requested.emit(expansion)
        plan_call = service.calls[-1]
        plan_call[2](TaskResult(plan_call[1], "completed", _batch_plan(request)))
        assert dialog.execute_button.isEnabled()

        view.market_selected.emit(MARKET_B)
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.execute_button.isEnabled()
        inspect_b = service.calls[-1]
        assert inspect_b[0] == ("inspect", MARKET_B)
        compatible_source = _fingerprint(MARKET_B)
        presenter._product_catalogs = SimpleNamespace(
            artifact_collections=(
                SimpleNamespace(
                    collection_id="compatible",
                    display_name="Compatible",
                    market_id=MARKET_B,
                    source_ohlcv=compatible_source,
                ),
                SimpleNamespace(
                    collection_id="stale",
                    display_name="Stale",
                    market_id=MARKET_B,
                    source_ohlcv=replace(
                        compatible_source, csv_sha256="f" * 64
                    ),
                ),
            )
        )
        inspect_b[2](TaskResult(inspect_b[1], "completed", MARKET_SNAPSHOT_B))
        retarget = service.calls[-1]
        assert retarget[0] == ("direct_catalog", MARKET_B)
        retarget[2](
            TaskResult(retarget[1], "completed", _batch_catalog(MARKET_B))
        )
        assert view.construct_batch_dialog() is dialog
        assert dialog.market_id == MARKET_B
        assert dialog._dataset_fields["asset"].text() == "ETHUSDT"
        assert tuple(
            dialog.collection_combo.itemData(index)
            for index in range(dialog.collection_combo.count())
        ) == ("compatible",)
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.execute_button.isEnabled()

        view.market_selected.emit(MARKET)
        inspect_a = service.calls[-1]
        inspect_a[2](TaskResult(inspect_a[1], "completed", MARKET_SNAPSHOT))
        closed_retarget = service.calls[-1]
        assert closed_retarget[0] == ("direct_catalog", MARKET)
        dialog.close()
        QApplication.processEvents()
        closed_retarget[2](
            TaskResult(closed_retarget[1], "completed", _batch_catalog())
        )
        assert view.construct_batch_dialog() is dialog
        assert not dialog.isVisible()
    finally:
        view.close()


def test_shared_batch_catalog_retargets_both_visible_creation_windows() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct_dialog, batch_dialog = _open_both_creation_dialogs(
            view, service, presenter
        )
        sma_row = next(
            row
            for row in range(direct_dialog.tool_list.count())
            if direct_dialog.tool_list.item(row).data(Qt.ItemDataRole.UserRole).key
            == "sma"
        )
        direct_dialog.tool_list.setCurrentRow(sma_row)
        assert direct_dialog.calculate_button.isEnabled()
        catalog = _batch_catalog()
        signal = catalog_signals(catalog)[0]
        expansion = ConstructBatchExpansionRequest(
            catalog,
            "derivative",
            {},
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(signal,),
        )
        request = expand_construct_batch(expansion)
        view.batch_construct_preview_requested.emit(expansion)
        plan_call = service.calls[-1]
        plan_call[2](TaskResult(plan_call[1], "completed", _batch_plan(request)))
        assert batch_dialog.execute_button.isEnabled()

        view.market_selected.emit(MARKET_B)
        assert not direct_dialog.calculate_button.isEnabled()
        assert not direct_dialog._dataset_fields["asset"].text()
        assert batch_dialog.preview_table.rowCount() == 0
        assert not batch_dialog.execute_button.isEnabled()
        inspect_b = service.calls[-1]
        before_settlement = len(service.calls)
        inspect_b[2](TaskResult(inspect_b[1], "completed", MARKET_SNAPSHOT_B))
        assert len(service.calls) == before_settlement + 1
        shared_catalog = service.calls[-1]
        assert shared_catalog[0] == ("direct_catalog", MARKET_B)
        before_catalog_settlement = len(service.calls)
        shared_catalog[2](
            TaskResult(shared_catalog[1], "completed", _batch_catalog(MARKET_B))
        )

        assert len(service.calls) == before_catalog_settlement
        assert view.artifact_creation_dialog() is direct_dialog
        assert view.construct_batch_dialog() is batch_dialog
        assert direct_dialog.market_id == MARKET_B
        assert batch_dialog.market_id == MARKET_B
        assert not direct_dialog.calculate_button.isEnabled()
        assert batch_dialog.preview_table.rowCount() == 0
        assert not batch_dialog.execute_button.isEnabled()
    finally:
        view.close()


def test_closed_batch_does_not_suppress_shared_direct_retarget() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct_dialog, batch_dialog = _open_both_creation_dialogs(
            view, service, presenter
        )
        view.market_selected.emit(MARKET_B)
        inspect_b = service.calls[-1]
        inspect_b[2](TaskResult(inspect_b[1], "completed", MARKET_SNAPSHOT_B))
        shared_catalog = service.calls[-1]
        batch_dialog.close()
        QApplication.processEvents()
        shared_catalog[2](
            TaskResult(shared_catalog[1], "completed", _batch_catalog(MARKET_B))
        )

        assert view.artifact_creation_dialog() is direct_dialog
        assert direct_dialog.isVisible()
        assert direct_dialog.market_id == MARKET_B
        assert view.construct_batch_dialog() is batch_dialog
        assert not batch_dialog.isVisible()
    finally:
        view.close()


def test_closed_direct_does_not_suppress_shared_batch_retarget() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct_dialog, batch_dialog = _open_both_creation_dialogs(
            view, service, presenter
        )
        view.market_selected.emit(MARKET_B)
        inspect_b = service.calls[-1]
        inspect_b[2](TaskResult(inspect_b[1], "completed", MARKET_SNAPSHOT_B))
        shared_catalog = service.calls[-1]
        direct_dialog.close()
        QApplication.processEvents()
        shared_catalog[2](
            TaskResult(shared_catalog[1], "completed", _batch_catalog(MARKET_B))
        )

        assert view.artifact_creation_dialog() is direct_dialog
        assert not direct_dialog.isVisible()
        assert view.construct_batch_dialog() is batch_dialog
        assert batch_dialog.isVisible()
        assert batch_dialog.market_id == MARKET_B
    finally:
        view.close()


def test_blocked_construct_batch_plan_reports_concrete_failure() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_scan(service)
        presenter.focus_market(MARKET, source="research")
        inspect = service.calls[-1]
        inspect[2](TaskResult(inspect[1], "completed", MARKET_SNAPSHOT))
        view.batch_constructs_requested.emit()
        catalog_call = service.calls[-1]
        catalog = _batch_catalog()
        catalog_call[2](TaskResult(catalog_call[1], "completed", catalog))
        dialog = view.construct_batch_dialog()
        signal = catalog_signals(catalog)[0]
        expansion = ConstructBatchExpansionRequest(
            catalog,
            "derivative",
            {},
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(signal,),
        )
        request = expand_construct_batch(expansion)
        view.batch_construct_preview_requested.emit(expansion)
        plan_call = service.calls[-1]
        blocked = replace(
            _batch_plan(request), naming_collisions=("duplicate_output",)
        )
        plan_call[2](TaskResult(plan_call[1], "completed", blocked))

        assert presenter._construct_batch_plan is None
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.execute_button.isEnabled()
        assert view.status_text() == "Construct Batch planning failed"
        assert "duplicate_output" in view._operation_surface.notes_text()
    finally:
        view.close()


def _changed_selected_catalog() -> DataManagerCatalogSnapshot:
    return DataManagerCatalogSnapshot(
        (DataManagerDatasetEntry(MARKET, True, 2, 0, 1),)
    )


def _settle_background_to_creation_catalog(
    view: DataManagerSuiteWindow,
    service: _ControlledApplication,
    presenter: DataManagerSuitePresenter,
):
    direct_dialog, batch_dialog = _open_both_creation_dialogs(
        view, service, presenter
    )
    service._service = object()
    presenter._product_catalogs = _product_catalog("a")
    presenter._catalog = CATALOG
    presenter._background_evidence_signature = "a" * 64
    presenter._initial_warmup_complete = True
    presenter.refresh()
    reconcile = service.calls[-1]
    reconcile[2](
        TaskResult(reconcile[1], "completed", _reconciliation("b"))
    )
    product_scan = service.calls[-1]
    product_scan[2](
        TaskResult(
            product_scan[1],
            "completed",
            _product_catalog("b", catalog=_changed_selected_catalog()),
        )
    )
    market_scan = service.calls[-1]
    assert market_scan[0] == ("inspect", MARKET)
    market_scan[2](TaskResult(market_scan[1], "completed", MARKET_SNAPSHOT))
    creation_scan = service.calls[-1]
    assert creation_scan[0] == ("direct_catalog", MARKET)
    return direct_dialog, batch_dialog, creation_scan


def test_initial_warmup_uses_foreground_operation_progress_and_catalogs() -> None:
    view = DataManagerSuiteWindow()
    applied = []
    original = view.set_product_catalogs
    view.set_product_catalogs = lambda value: (
        applied.append(value), original(value)
    )[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        reconcile = service.calls[0]
        assert reconcile[0] == "reconcile_status"
        assert service.reconcile_forces == [False]
        assert presenter._active_task_id == reconcile[1]
        assert presenter._background_refresh_task_id is None
        assert not presenter._initial_warmup_complete
        assert view._busy
        assert view._operation_surface._name.text() == "Loading Data Manager"

        service.progress_callbacks[reconcile[1]](
            TaskProgress(reconcile[1], "Reconciling managed state", 2, 5)
        )
        assert view.status_text() == "Reconciling managed state"
        assert view._progress.value() == 2
        assert view._progress.maximum() == 5

        calls_before = len(service.calls)
        presenter._refresh_on_timer()
        presenter.refresh()
        assert len(service.calls) == calls_before

        snapshot = _product_catalog("a")
        reconcile[2](
            TaskResult(
                reconcile[1], "completed", snapshot.latest_reconciliation
            )
        )
        scan = service.calls[-1]
        assert scan[0] == "scan_product_catalogs"
        assert presenter._active_task_id == scan[1]
        assert presenter._background_refresh_task_id is None
        assert view._operation_surface._name.text() == "Loading Data Manager"
        service.progress_callbacks[scan[1]](
            TaskProgress(scan[1], "Loading product catalogs", 1, None)
        )
        assert view.status_text() == "Loading product catalogs"
        assert view._progress.minimum() == 0
        assert view._progress.maximum() == 0

        scan[2](TaskResult(scan[1], "completed", snapshot))
        assert applied == [snapshot]
        assert presenter._product_catalogs is snapshot
        assert presenter._catalog is snapshot.catalog
        assert presenter._initial_warmup_complete
        assert presenter._background_evidence_signature == "a" * 64
        assert presenter._active_task_id is None

        calls_before = len(service.calls)
        presenter._refresh_on_timer()
        background = service.calls[-1]
        assert len(service.calls) == calls_before + 1
        assert presenter._active_task_id is None
        assert presenter._background_refresh_task_id == background[1]
        background[2](
            TaskResult(background[1], "completed", _reconciliation("a"))
        )
        assert len(service.calls) == calls_before + 1
        assert presenter._background_refresh_task_id is None

        presenter._refresh_when_opened()
        reopened_background = service.calls[-1]
        assert presenter._active_task_id is None
        assert presenter._background_refresh_task_id == reopened_background[1]
        assert service.reconcile_forces[-1] is False
        reopened_background[2](
            TaskResult(
                reopened_background[1], "failed", error_message="expected"
            )
        )

        presenter.refresh()
        assert service.reconcile_forces[-1] is True
        assert presenter._background_refresh_task_id == service.calls[-1][1]
    finally:
        view.close()


@pytest.mark.parametrize("failed_stage", ("reconcile", "catalog"))
def test_initial_warmup_failure_is_visible_and_manual_refresh_retries(
    failed_stage,
) -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        reconcile = service.calls[0]
        if failed_stage == "catalog":
            reconcile[2](
                TaskResult(
                    reconcile[1], "completed", _reconciliation("a")
                )
            )
            failed = service.calls[-1]
        else:
            failed = reconcile
        failed[2](
            TaskResult(failed[1], "failed", error_message="warm-up failed")
        )

        assert not presenter._initial_warmup_complete
        assert presenter._active_task_id is None
        assert presenter._background_refresh_task_id is None
        assert view._operation_surface.state == "failed"
        assert view._operation_surface.notes_text() == "warm-up failed"
        expected = (
            "Data Manager catalog loading failed"
            if failed_stage == "catalog"
            else "Data Manager loading/reconciliation failed"
        )
        assert view.status_text() == expected
        if failed_stage == "reconcile":
            assert [call[0] for call in service.calls] == ["reconcile_status"]

        presenter._refresh_on_timer()
        assert service.calls[-1] is failed
        presenter.refresh()
        assert service.calls[-1][0] == "reconcile_status"
        assert service.reconcile_forces[-1] is True
        assert presenter._active_task_id == service.calls[-1][1]
        assert presenter._background_refresh_task_id is None
    finally:
        view.close()


def test_disposal_during_initial_warmup_cancels_and_fences_late_result() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        reconcile = service.calls[0]
        presenter.dispose()
        reconcile[2](
            TaskResult(reconcile[1], "completed", _reconciliation("a"))
        )
        assert service.cancelled == [reconcile[1]]
        assert len(service.calls) == 1
        assert not presenter._initial_warmup_complete
        assert presenter._product_catalogs is None
    finally:
        view.close()


def test_background_a_does_not_own_foreground_task_slot() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        presenter._refresh_on_timer()
        assert presenter._active_task_id is None
        assert presenter._background_refresh_task_id == service.calls[-1][1]
    finally:
        view.close()


def test_background_b_does_not_take_over_foreground_busy_surface() -> None:
    view = DataManagerSuiteWindow()
    busy_calls = []
    operation_calls = []
    progress_calls = []
    original_busy = view.set_busy
    original_operation = view.set_operation_task
    original_progress = view.set_progress
    view.set_busy = lambda *args, **kwargs: (
        busy_calls.append((args, kwargs)), original_busy(*args, **kwargs)
    )[1]
    view.set_operation_task = lambda *args, **kwargs: (
        operation_calls.append((args, kwargs)), original_operation(*args, **kwargs)
    )[1]
    view.set_progress = lambda *args, **kwargs: (
        progress_calls.append((args, kwargs)), original_progress(*args, **kwargs)
    )[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        busy_calls.clear()
        operation_calls.clear()
        progress_calls.clear()
        presenter._refresh_on_timer()
        assert busy_calls == []
        assert operation_calls == []
        assert progress_calls == []
    finally:
        view.close()


def test_background_c_coexists_with_foreground_submission() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        presenter._refresh_on_timer()
        background_id = presenter._background_refresh_task_id
        presenter._submit(
            "scan_catalog",
            presenter._catalog_generation,
            lambda progress, result: service.submit_scan_catalog(
                progress_callback=progress, result_callback=result
            ),
            lambda _result: None,
        )
        assert presenter._active_task_id is not None
        assert presenter._background_refresh_task_id == background_id
        assert len(service.calls) == 4
    finally:
        view.close()


def test_background_d_prevents_self_overlap() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        warmup_reconciles = [call[0] for call in service.calls].count(
            "reconcile_status"
        )
        presenter.refresh()
        presenter._refresh_on_timer()
        assert [call[0] for call in service.calls].count(
            "reconcile_status"
        ) == warmup_reconciles + 1
        reconcile = service.calls[-1]
        reconcile[2](
            TaskResult(reconcile[1], "completed", _reconciliation("b"))
        )
        scan = service.calls[-1]
        scan[2](TaskResult(scan[1], "failed", error_message="expected"))
        assert [call[0] for call in service.calls].count(
            "reconcile_status"
        ) == warmup_reconciles + 2
    finally:
        view.close()


def test_background_e_coalesces_force_for_next_pass() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        presenter._refresh_on_timer()
        presenter.refresh()
        reconcile = service.calls[-1]
        reconcile[2](
            TaskResult(reconcile[1], "failed", error_message="stop")
        )
        assert service.reconcile_forces == [False, False, True]
    finally:
        view.close()


def test_background_f_unchanged_evidence_is_complete_no_op() -> None:
    view = DataManagerSuiteWindow()
    applied = []
    original = view.set_product_catalogs
    view.set_product_catalogs = lambda value: (applied.append(value), original(value))[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        applied.clear()
        calls_before = len(service.calls)
        presenter._refresh_on_timer()
        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("a")))
        assert len(service.calls) == calls_before + 1
        assert applied == []
    finally:
        view.close()


def test_background_g_changed_evidence_scans_products_once() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        initial_scans = [call[0] for call in service.calls].count(
            "scan_product_catalogs"
        )
        presenter._refresh_on_timer()
        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        assert [call[0] for call in service.calls].count(
            "scan_product_catalogs"
        ) == initial_scans + 1
    finally:
        view.close()


def test_background_h_unrelated_market_change_skips_selected_market_work() -> None:
    view = DataManagerSuiteWindow()
    applied = []
    original = view.set_product_catalogs
    view.set_product_catalogs = lambda value: (applied.append(value), original(value))[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        applied.clear()
        presenter._selected_market = MARKET
        presenter._catalog = CATALOG
        presenter._refresh_on_timer()
        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        scan = service.calls[-1]
        scan[2](
            TaskResult(
                scan[1],
                "completed",
                _product_catalog("b", catalog=CATALOG_BOTH),
            )
        )
        assert len(applied) == 1
        assert not any(call[0] == ("inspect", MARKET) for call in service.calls)
    finally:
        view.close()


def test_background_i_selected_market_change_inspects_without_busy_takeover() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        presenter._selected_market = MARKET
        presenter._catalog = CATALOG
        presenter._refresh_on_timer()
        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        scan = service.calls[-1]
        scan[2](
            TaskResult(
                scan[1],
                "completed",
                _product_catalog("b", catalog=_changed_selected_catalog()),
            )
        )
        assert service.calls[-1][0] == ("inspect", MARKET)
        assert presenter._active_task_id is None
        assert not view._busy
    finally:
        view.close()


def test_background_j_direct_and_batch_share_one_creation_catalog_submission() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_background_to_creation_catalog(view, service, presenter)
        assert [call[0] for call in service.calls].count(
            ("direct_catalog", MARKET)
        ) == 3
    finally:
        view.close()


def test_background_k_one_creation_result_updates_both_visible_windows() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct, batch, creation = _settle_background_to_creation_catalog(
            view, service, presenter
        )
        catalog = _batch_catalog()
        creation[2](TaskResult(creation[1], "completed", catalog))
        assert view.artifact_creation_dialog() is direct
        assert view.construct_batch_dialog() is batch
        assert direct._catalog is catalog
        assert batch._catalog is catalog
    finally:
        view.close()


def test_background_l_closed_direct_is_not_resurrected() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct, batch, creation = _settle_background_to_creation_catalog(
            view, service, presenter
        )
        direct.close()
        QApplication.processEvents()
        creation[2](TaskResult(creation[1], "completed", _batch_catalog()))
        assert not direct.isVisible()
        assert batch.isVisible()
    finally:
        view.close()


def test_background_m_closed_batch_is_not_resurrected() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct, batch, creation = _settle_background_to_creation_catalog(
            view, service, presenter
        )
        batch.close()
        QApplication.processEvents()
        creation[2](TaskResult(creation[1], "completed", _batch_catalog()))
        assert direct.isVisible()
        assert not batch.isVisible()
    finally:
        view.close()


def test_background_n_same_fingerprint_preserves_and_invalidates_batch_preview() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _direct, batch, creation = _settle_background_to_creation_catalog(
            view, service, presenter
        )
        signal = catalog_signals(batch._catalog)[0]
        request = expand_construct_batch(
            ConstructBatchExpansionRequest(
                batch._catalog,
                "derivative",
                {},
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(signal,),
            )
        )
        batch.set_plan(_batch_plan(request))
        creation[2](TaskResult(creation[1], "completed", _batch_catalog()))
        assert batch.reviewed_plan is None
        assert not batch.execute_button.isEnabled()
    finally:
        view.close()


def test_background_o_changed_fingerprint_clears_target_bound_state() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct, batch, creation = _settle_background_to_creation_catalog(
            view, service, presenter
        )
        changed_source = replace(_fingerprint(), csv_sha256="e" * 64)
        creation[2](
            TaskResult(
                creation[1],
                "completed",
                _batch_catalog(source=changed_source),
            )
        )
        assert direct._catalog.source_ohlcv == changed_source
        assert batch._catalog.source_ohlcv == changed_source
        assert batch._manual_selected_signal_keys == set()
    finally:
        view.close()


def test_background_p_catalog_application_defers_until_foreground_settles() -> None:
    view = DataManagerSuiteWindow()
    applied = []
    original = view.set_product_catalogs
    view.set_product_catalogs = lambda value: (applied.append(value), original(value))[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        applied.clear()
        presenter._refresh_on_timer()
        reconcile = service.calls[-1]
        presenter._submit(
            "scan_catalog",
            presenter._catalog_generation,
            lambda progress, result: service.submit_scan_catalog(
                progress_callback=progress, result_callback=result
            ),
            lambda _result: None,
        )
        foreground = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        product_scan = service.calls[-1]
        product_scan[2](
            TaskResult(product_scan[1], "completed", _product_catalog("b"))
        )
        assert applied == []
        assert presenter._background_deferred_catalogs is not None
        foreground[2](TaskResult(foreground[1], "completed", CATALOG))
        assert len(applied) == 1
        assert presenter._background_deferred_catalogs is None
    finally:
        view.close()


def test_background_q_disposal_cancels_and_fences_late_result() -> None:
    view = DataManagerSuiteWindow()
    applied = []
    original = view.set_product_catalogs
    view.set_product_catalogs = lambda value: (applied.append(value), original(value))[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service)
        applied.clear()
        presenter._refresh_on_timer()
        reconcile = service.calls[-1]
        presenter.dispose()
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("a")))
        assert service.cancelled == [reconcile[1]]
        assert applied == []
        assert len(service.calls) == 3
    finally:
        view.close()


def _start_background_market_race(
    view: DataManagerSuiteWindow,
    service: _ControlledApplication,
    presenter: DataManagerSuitePresenter,
):
    _settle_initial_warmup(service)
    presenter._selected_market = MARKET
    presenter._catalog = CATALOG
    presenter._refresh_on_timer()
    reconcile = service.calls[-1]
    reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
    product_scan = service.calls[-1]
    product_scan[2](
        TaskResult(
            product_scan[1],
            "completed",
            _product_catalog("b", catalog=_changed_selected_catalog()),
        )
    )
    market_scan = service.calls[-1]
    assert market_scan[0] == ("inspect", MARKET)
    return market_scan


def _start_foreground_scan(
    service: _ControlledApplication,
    presenter: DataManagerSuitePresenter,
):
    presenter._submit(
        "scan_catalog",
        presenter._catalog_generation,
        lambda progress, result: service.submit_scan_catalog(
            progress_callback=progress, result_callback=result
        ),
        lambda _result: None,
    )
    foreground = service.calls[-1]
    assert presenter._active_task_id == foreground[1]
    return foreground


def test_background_market_result_defers_to_foreground_and_reinspects() -> None:
    view = DataManagerSuiteWindow()
    applied = []
    original = view.set_market_snapshot
    view.set_market_snapshot = lambda value: (applied.append(value), original(value))[1]
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        market_scan = _start_background_market_race(view, service, presenter)
        foreground = _start_foreground_scan(service, presenter)

        market_scan[2](TaskResult(market_scan[1], "completed", MARKET_SNAPSHOT))

        assert applied == []
        assert not any(call[0] == ("direct_catalog", MARKET) for call in service.calls)
        assert presenter._active_task_id == foreground[1]
        assert presenter._background_selected_market_refresh_pending == MARKET

        inspect_count = [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        )
        foreground[2](TaskResult(foreground[1], "completed", CATALOG))

        assert [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        ) == inspect_count + 1
        assert service.calls[-1][0] == ("inspect", MARKET)
        assert presenter._background_selected_market_refresh_pending is None
        assert applied == []
    finally:
        view.close()


def test_background_creation_result_defers_to_foreground_and_reinspects() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        direct, batch, creation = _settle_background_to_creation_catalog(
            view, service, presenter
        )
        signal = catalog_signals(batch._catalog)[0]
        request = expand_construct_batch(
            ConstructBatchExpansionRequest(
                batch._catalog,
                "derivative",
                {},
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(signal,),
            )
        )
        plan = _batch_plan(request)
        batch.set_plan(plan)
        presenter._construct_batch_plan = plan
        presenter._pending_construct_batch_request = request
        direct_catalog = direct._catalog
        batch_catalog = batch._catalog
        foreground = _start_foreground_scan(service, presenter)

        creation[2](TaskResult(creation[1], "completed", _batch_catalog()))

        assert direct._catalog is direct_catalog
        assert batch._catalog is batch_catalog
        assert batch.reviewed_plan is plan
        assert presenter._construct_batch_plan is plan
        assert presenter._pending_construct_batch_request is request
        assert presenter._active_task_id == foreground[1]
        assert presenter._background_selected_market_refresh_pending == MARKET

        inspect_count = [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        )
        foreground[2](TaskResult(foreground[1], "completed", CATALOG))

        assert [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        ) == inspect_count + 1
        assert service.calls[-1][0] == ("inspect", MARKET)
    finally:
        view.close()


def test_background_pending_market_is_discarded_after_target_change() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        market_scan = _start_background_market_race(view, service, presenter)
        foreground = _start_foreground_scan(service, presenter)
        market_scan[2](TaskResult(market_scan[1], "completed", MARKET_SNAPSHOT))
        presenter._selected_market = MARKET_B
        before = len(service.calls)

        foreground[2](TaskResult(foreground[1], "completed", CATALOG))

        assert len(service.calls) == before
        assert presenter._background_selected_market_refresh_pending is None
    finally:
        view.close()


def test_background_pending_market_is_cleared_and_fenced_by_disposal() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        market_scan = _start_background_market_race(view, service, presenter)
        foreground = _start_foreground_scan(service, presenter)
        market_scan[2](TaskResult(market_scan[1], "completed", MARKET_SNAPSHOT))
        before = len(service.calls)

        presenter.dispose()
        foreground[2](TaskResult(foreground[1], "completed", CATALOG))

        assert presenter._background_selected_market_refresh_pending is None
        assert len(service.calls) == before
    finally:
        view.close()


def test_deferred_catalog_inspection_consumes_satisfied_market_catchup() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _open_both_creation_dialogs(view, service, presenter)
        service._service = object()
        presenter._product_catalogs = _product_catalog("a")
        presenter._catalog = CATALOG
        presenter._background_evidence_signature = "a" * 64
        presenter._initial_warmup_complete = True
        presenter.refresh()
        reconcile = service.calls[-1]
        reconcile[2](
            TaskResult(reconcile[1], "completed", _reconciliation("b"))
        )
        product_scan = service.calls[-1]
        product_scan[2](
            TaskResult(
                product_scan[1],
                "completed",
                _product_catalog("b", catalog=_changed_selected_catalog()),
            )
        )
        market_scan = service.calls[-1]
        assert market_scan[0] == ("inspect", MARKET)
        foreground = _start_foreground_scan(service, presenter)
        market_scan[2](TaskResult(market_scan[1], "completed", MARKET_SNAPSHOT))
        assert presenter._background_selected_market_refresh_pending == MARKET

        presenter.refresh()
        reconcile = service.calls[-1]
        reconcile[2](
            TaskResult(reconcile[1], "completed", _reconciliation("c"))
        )
        product_scan = service.calls[-1]
        product_scan[2](
            TaskResult(
                product_scan[1],
                "completed",
                _product_catalog("c", catalog=CATALOG_BOTH),
            )
        )
        assert presenter._background_deferred_catalogs is not None
        assert presenter._background_selected_market_refresh_pending == MARKET
        inspect_count = [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        )
        creation_count = [call[0] for call in service.calls].count(
            ("direct_catalog", MARKET)
        )

        foreground[2](TaskResult(foreground[1], "completed", CATALOG))

        assert [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        ) == inspect_count + 1
        assert presenter._background_selected_market_refresh_pending is None
        fresh_market = service.calls[-1]
        assert fresh_market[0] == ("inspect", MARKET)
        fresh_market[2](
            TaskResult(fresh_market[1], "completed", MARKET_SNAPSHOT)
        )
        fresh_creation = service.calls[-1]
        assert fresh_creation[0] == ("direct_catalog", MARKET)
        fresh_creation[2](
            TaskResult(fresh_creation[1], "completed", _batch_catalog())
        )

        assert [call[0] for call in service.calls].count(
            ("inspect", MARKET)
        ) == inspect_count + 1
        assert [call[0] for call in service.calls].count(
            ("direct_catalog", MARKET)
        ) == creation_count + 1
    finally:
        view.close()


@pytest.mark.parametrize(
    ("deletion_kind", "expected_operation"),
    (
        ("recipe", "delete_portable_recipe"),
        ("recipe_collection", "delete_recipe_collection"),
        ("artifact", "delete_managed_artifact"),
        ("artifact_collection", "delete_artifact_collection"),
    ),
)
def test_catalog_deletions_submit_exact_identity_and_refresh_canonically(
    deletion_kind: str, expected_operation: str
) -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    refreshes: list[str] = []
    presenter._after_write_refresh = lambda: refreshes.append("refresh")
    (
        recipe,
        recipe_entry,
        recipe_collection,
        recipe_collection_entry,
        artifact_summary,
        artifact_entry,
        artifact_collection,
    ) = _deletion_values()
    cases = {
        "recipe": (
            view.catalog_delete_recipe_requested,
            recipe_entry,
            ("delete_portable_recipe", recipe.recipe_id),
            recipe,
        ),
        "recipe_collection": (
            view.catalog_delete_recipe_collection_requested,
            recipe_collection_entry,
            ("delete_recipe_collection", recipe_collection.collection_id),
            recipe_collection,
        ),
        "artifact": (
            view.catalog_delete_artifact_requested,
            artifact_entry,
            (
                "delete_managed_artifact",
                artifact_entry.market_id,
                artifact_entry.logical_artifact_id,
            ),
            artifact_summary,
        ),
        "artifact_collection": (
            view.catalog_delete_artifact_collection_requested,
            artifact_collection,
            ("delete_artifact_collection", artifact_collection.collection_id),
            artifact_collection,
        ),
    }
    try:
        _settle_initial_scan(service)
        signal, entry, expected_call, result_value = cases[deletion_kind]
        signal.emit(entry)
        deletion = service.calls[-1]

        assert deletion[0] == expected_call
        assert deletion[0][0] == expected_operation
        deletion[2](TaskResult(deletion[1], "completed", result_value))

        assert refreshes == ["refresh"]
        assert "deletion completed" in view.status_text().casefold()
        assert all(call[0] != "refresh_after_delete" for call in service.calls)
    finally:
        view.close()


def test_catalog_deletion_failure_reports_refusal_without_refresh() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    refreshes: list[str] = []
    presenter._after_write_refresh = lambda: refreshes.append("refresh")
    recipe_entry = _deletion_values()[1]
    try:
        _settle_initial_scan(service)
        view.catalog_delete_recipe_requested.emit(recipe_entry)
        deletion = service.calls[-1]
        deletion[2](
            TaskResult(
                deletion[1],
                "failed",
                error_type="DataManagerServiceError",
                error_message="Recipe is referenced by an Artifact Collection revision",
            )
        )

        assert refreshes == []
        assert view.status_text() == "Recipe deletion failed"
        assert "referenced by an Artifact Collection" in (
            view._operation_surface.notes_text()
        )
    finally:
        view.close()


def test_deleted_recipe_refresh_updates_open_derivation_existing_ids() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    recipe, recipe_entry = _deletion_values()[:2]
    initial = _product_catalog(
        "a", portable_recipes=DataManagerPortableRecipeCatalog((recipe_entry,))
    )
    try:
        _settle_initial_warmup(service, snapshot=initial)
        dialog = _open_derivation_dialog(
            view, service, recipe_id=recipe.recipe_id
        )
        assert dialog.set_plan(_derivation_plan(recipe_id=recipe.recipe_id))
        assert dialog.preview_table.item(0, 5).text() == "Existing"

        view.catalog_delete_recipe_requested.emit(recipe_entry)
        deletion = service.calls[-1]
        deletion[2](TaskResult(deletion[1], "completed", recipe))
        reconcile = service.calls[-1]
        assert reconcile[0] == "reconcile_status"
        refreshed = _product_catalog("b")
        reconcile[2](
            TaskResult(
                reconcile[1], "completed", refreshed.latest_reconciliation
            )
        )
        product_scan = service.calls[-1]
        assert product_scan[0] == "scan_product_catalogs"
        product_scan[2](TaskResult(product_scan[1], "completed", refreshed))

        assert dialog.preview_table.item(0, 5).text() == "New"
    finally:
        view.close()


def test_deleted_artifact_refreshes_open_direct_and_batch_catalogs() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    artifact_summary, artifact_entry = _deletion_values()[4:6]
    try:
        direct, batch = _open_both_creation_dialogs(view, service, presenter)
        service._service = object()
        presenter._product_catalogs = _product_catalog("a")
        presenter._catalog = CATALOG
        presenter._background_evidence_signature = "a" * 64
        presenter._initial_warmup_complete = True

        view.catalog_delete_artifact_requested.emit(artifact_entry)
        deletion = service.calls[-1]
        deletion[2](TaskResult(deletion[1], "completed", artifact_summary))
        reconcile = service.calls[-1]
        reconcile[2](TaskResult(reconcile[1], "completed", _reconciliation("b")))
        product_scan = service.calls[-1]
        product_scan[2](
            TaskResult(
                product_scan[1],
                "completed",
                _product_catalog("b", catalog=_changed_selected_catalog()),
            )
        )
        market_scan = service.calls[-1]
        assert market_scan[0] == ("inspect", MARKET)
        market_scan[2](TaskResult(market_scan[1], "completed", MARKET_SNAPSHOT))
        creation_scan = service.calls[-1]
        assert creation_scan[0] == ("direct_catalog", MARKET)
        refreshed_catalog = _batch_catalog()
        creation_scan[2](
            TaskResult(creation_scan[1], "completed", refreshed_catalog)
        )

        assert direct._catalog is refreshed_catalog
        assert batch._catalog is refreshed_catalog
    finally:
        view.close()


def test_legacy_deletion_uses_canonical_refresh_without_exception_path() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    refreshes: list[str] = []
    presenter._after_write_refresh = lambda: refreshes.append("refresh")
    artifact = DataManagerArtifactEntry(
        MARKET,
        "6" * 64,
        "7" * 64,
        "sma",
        "indicator",
        ("sma_20",),
        1,
        0,
        0,
        datetime(2026, 8, 17, tzinfo=UTC),
    )
    try:
        _settle_initial_scan(service)
        presenter._selected_market = MARKET
        presenter._selected_artifact = artifact
        view.delete_artifact_requested.emit()
        deletion = service.calls[-1]
        assert deletion[0] == (
            "delete_artifact",
            MARKET,
            "indicator",
            "sma",
            artifact.artifact_id,
        )
        deletion[2](
            TaskResult(
                deletion[1],
                "completed",
                DataManagerDeletionResult(
                    MARKET,
                    "artifact",
                    "indicator",
                    "sma",
                    artifact.artifact_id,
                ),
            )
        )

        assert refreshes == ["refresh"]
        assert all(call[0] != "refresh_after_delete" for call in service.calls)
    finally:
        view.close()


def test_late_catalog_deletion_result_cannot_mutate_disposed_presenter() -> None:
    view = DataManagerSuiteWindow()
    service = _ControlledApplication()
    presenter = DataManagerSuitePresenter(view, service)
    refreshes: list[str] = []
    presenter._after_write_refresh = lambda: refreshes.append("refresh")
    recipe, recipe_entry = _deletion_values()[:2]
    try:
        _settle_initial_scan(service)
        view.catalog_delete_recipe_requested.emit(recipe_entry)
        deletion = service.calls[-1]
        status = view.status_text()
        presenter.dispose()
        deletion[2](TaskResult(deletion[1], "completed", recipe))

        assert refreshes == []
        assert view.status_text() == status
    finally:
        view.close()


def test_collection_presenter_forwards_exact_recipe_plan_create_and_edit_calls() -> None:
    from leonardo.recipes import PortableRecipeGraphPlan
    from tests.gui_test.test_data_manager_catalogs import associated_product_snapshot

    snapshot = associated_product_snapshot()
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service, snapshot=snapshot)
        view.create_recipe_collection_requested.emit()
        dialog = view.recipe_collection_dialog()
        assert dialog is not None and dialog.isVisible()
        dialog.select_all_button.click()
        roots = dialog.selected_root_recipe_ids()
        dialog.preview_button.click()
        preview = service.calls[-1]
        assert preview[0] == ("plan_recipe_collection", roots)
        plan = PortableRecipeGraphPlan(roots, roots, (), (roots,))
        preview[2](TaskResult(preview[1], "completed", plan))
        dialog.name_input.setText("Collection")
        dialog.description_input.setText("Description")
        dialog.publish_button.click()
        assert service.calls[-1][0] == (
            "create_recipe_collection",
            "Collection",
            "Description",
            roots,
        )
    finally:
        presenter.dispose()
        view.close()

    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service, snapshot=snapshot)
        selected = snapshot.recipe_collections.collections[0]
        view.edit_recipe_collection_requested.emit(selected)
        assert service.calls[-1][0] == (
            "inspect_recipe_collection",
            selected.collection_id,
            selected.revision_id,
        )
    finally:
        presenter.dispose()
        view.close()


def test_collection_presenter_forwards_exact_artifact_plan_and_create_call() -> None:
    from tests.gui_test.test_data_manager_artifact_collection_dialog import (
        MARKET_A,
        ROOT_A,
        _check,
        _plan,
        _snapshot,
    )

    snapshot = _snapshot()
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service, snapshot=snapshot)
        view.create_artifact_collection_requested.emit()
        dialog = view.artifact_collection_dialog()
        assert dialog is not None and dialog.isVisible()
        dialog.dataset_scope.setCurrentIndex(1)
        _check(dialog, ROOT_A)
        dialog.preview_button.click()
        preview = service.calls[-1]
        assert preview[0] == (
            "plan_artifact_collection_selection",
            MARKET_A,
            (ROOT_A,),
        )
        plan = _plan((ROOT_A,))
        preview[2](TaskResult(preview[1], "completed", plan))
        dialog.name_input.setText("Artifact Collection")
        dialog.publish_button.click()
        call = service.calls[-1][0]
        assert call[:4] == (
            "create_artifact_collection_from_selection",
            plan,
            "Artifact Collection",
            "",
        )
        assert tuple(item.column_name for item in call[4]) == ("value",)
    finally:
        presenter.dispose()
        view.close()


def test_collection_presenter_forwards_exact_immutable_edit_calls() -> None:
    from tests.gui_test.test_data_manager_artifact_collection_dialog import (
        _plan as artifact_plan,
        _revision as artifact_revision,
        _snapshot as artifact_snapshot,
    )
    from tests.gui_test.test_data_manager_recipe_collection_dialog import (
        _inspection as recipe_inspection,
        _plan as recipe_plan,
        _recipe,
        _snapshot as recipe_snapshot,
        ROOT_ID,
        SUPPORT_ID,
    )

    snapshot = recipe_snapshot(_recipe(ROOT_ID, "ema"), _recipe(SUPPORT_ID, "sma"))
    inspection = recipe_inspection()
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service, snapshot=snapshot)
        view.show_recipe_collection_dialog(snapshot, inspection=inspection)
        dialog = view.recipe_collection_dialog()
        assert dialog is not None
        plan = recipe_plan()
        assert dialog.set_plan(plan)
        dialog.description_input.setText("Updated")
        dialog.publish_button.click()
        assert service.calls[-1][0] == (
            "update_recipe_collection",
            inspection.collection.collection_id,
            inspection.collection.display_name,
            "Updated",
            inspection.root_recipe_ids,
            inspection.collection.revision_id,
        )
    finally:
        presenter.dispose()
        view.close()

    snapshot = artifact_snapshot()
    revision = artifact_revision()
    view = DataManagerSuiteWindow()
    service = _ControlledApplication(product_catalogs=True)
    presenter = DataManagerSuitePresenter(view, service)
    try:
        _settle_initial_warmup(service, snapshot=snapshot)
        view.show_artifact_collection_dialog(snapshot, revision=revision)
        dialog = view.artifact_collection_dialog()
        assert dialog is not None
        plan = artifact_plan(revision.root_logical_artifact_ids)
        assert dialog.set_plan(plan)
        dialog.description_input.setText("Updated")
        dialog.publish_button.click()
        call = service.calls[-1][0]
        assert call[:5] == (
            "edit_artifact_collection_from_selection",
            revision.collection_id,
            plan,
            revision.display_name,
            "Updated",
        )
        assert call[5] == dialog.selected_outputs()
        assert call[6] == dialog.presentation_order()
        assert call[7] == revision.revision_id
    finally:
        presenter.dispose()
        view.close()
