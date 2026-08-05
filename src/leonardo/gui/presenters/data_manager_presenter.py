"""Presenter for the canonical Data Manager catalog/manage workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.data import MarketId
from leonardo.data_manager import (
    BatchArtifactBranchRequest,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DataManagerApplicationService,
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationRequest,
    DataManagerArtifactMaterializationResult,
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerFocusRequest,
    DataManagerMarketSnapshot,
    DataManagerPreview,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeDerivationPlan,
    DataManagerRecipePersistenceResult,
    DataManagerStudyEnvironmentInspection,
    DataManagerRecipeEntry,
    ArtifactCollectionUpdatePlan,
    ArtifactCollectionUpdateResult,
    ArtifactCollectionOutputV1,
    DatabaseUpdatePlan,
    DatabaseUpdateResult,
    DatabaseReadiness,
)
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.gui.windows.data_manager_preview_dialog import DataManagerPreviewDialog
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from leonardo.gui.data_manager.reconciliation import (
    DataManagerReconciliationCoordinator,
)


_MARKET_UNAVAILABLE_ERROR = "DataManagerMarketUnavailableError"


@dataclass(frozen=True, slots=True)
class _BasePlanContext:
    market_id: MarketId
    recipe_mode: str
    root_recipe_ids: tuple[str, ...]
    recipe_collection_id: str | None
    recipe_collection_revision_id: str | None


@dataclass(frozen=True, slots=True)
class _BatchPlanContext:
    request: BatchArtifactRequest


@dataclass(frozen=True, slots=True)
class _ReadinessContext:
    seed_id: str
    collection_id: str
    collection_revision_id: str


class _QtCallbackDispatcher(QObject):
    requested = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.requested.connect(self._invoke, Qt.ConnectionType.QueuedConnection)

    def dispatch(self, callback: Callable[[], None]) -> None:
        self.requested.emit(callback)

    @staticmethod
    def _invoke(callback: object) -> None:
        if callable(callback):
            callback()


class DataManagerSuitePresenter(QObject):
    """Fence async Data Manager results and coordinate immutable view state."""

    def __init__(
        self,
        view: DataManagerSuiteWindow,
        service: DataManagerApplicationService,
    ) -> None:
        super().__init__(view)
        if not isinstance(view, DataManagerSuiteWindow):
            raise TypeError("view must be a DataManagerSuiteWindow")
        if not isinstance(service, DataManagerApplicationService):
            raise TypeError("service must be a DataManagerApplicationService")
        self._view = view
        self._service = service
        self._dispatcher = _QtCallbackDispatcher(self)
        self._catalog: DataManagerCatalogSnapshot | None = None
        self._market_snapshot: DataManagerMarketSnapshot | None = None
        self._selected_market: MarketId | None = None
        self._selected_artifact: DataManagerArtifactEntry | None = None
        self._selected_recipe: DataManagerRecipeEntry | None = None
        self._active_task_id: str | None = None
        self._active_operation: str | None = None
        self._catalog_generation = 0
        self._market_generation = 0
        self._pending_focus: DataManagerFocusRequest | None = None
        self._preview_dialogs: set[DataManagerPreviewDialog] = set()
        self._disposed = False
        self._creation_seed = None
        self._base_plan: DataManagerArtifactMaterializationPlan | None = None
        self._base_plan_context: _BasePlanContext | None = None
        self._pending_base_plan_context: _BasePlanContext | None = None
        self._base_materialization: DataManagerArtifactMaterializationResult | None = None
        self._batch_plan: BatchArtifactPlan | None = None
        self._batch_plan_context: _BatchPlanContext | None = None
        self._pending_batch_plan_context: _BatchPlanContext | None = None
        self._batch_materialization: DataManagerArtifactMaterializationResult | None = None
        self._creation_collection = None
        self._database_readiness: DatabaseReadiness | None = None
        self._readiness_context: _ReadinessContext | None = None
        self._pending_readiness_context: _ReadinessContext | None = None
        self._product_catalogs: DataManagerProductCatalogSnapshot | None = None
        self._artifact_update_plan: ArtifactCollectionUpdatePlan | None = None
        self._database_update_plan: DatabaseUpdatePlan | None = None
        self._derivation_plan = None
        self._recipe_persistence = None
        self._wire()
        self._reconciliation = DataManagerReconciliationCoordinator(
            refresh_when_opened=self._refresh_when_opened,
            refresh_on_timer=self._refresh_on_timer,
            is_busy=lambda: self._active_task_id is not None or self._disposed,
            parent=self,
        )
        self._reconciliation.start()

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    @property
    def selected_market_id(self) -> MarketId | None:
        return self._selected_market

    @property
    def pending_focus(self) -> DataManagerFocusRequest | None:
        return self._pending_focus

    def refresh(self) -> None:
        if self._disposed or self._active_task_id is not None:
            return
        if self._supports_product_catalogs():
            self._reconcile_then_catalog(force=True)
            return
        self._refresh_legacy_catalog()

    def _refresh_legacy_catalog(self) -> None:
        self._catalog_generation += 1
        generation = self._catalog_generation
        self._submit(
            "scan_catalog",
            generation,
            lambda progress, result: self._service.submit_scan_catalog(
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._settle_catalog,
        )

    def _refresh_when_opened(self) -> None:
        if self._supports_product_catalogs():
            self._reconcile_then_catalog(force=False)
        else:
            self._refresh_legacy_catalog()

    def _refresh_on_timer(self) -> None:
        if self._supports_product_catalogs():
            self._reconcile_then_catalog(force=False)

    def _supports_product_catalogs(self) -> bool:
        return (
            hasattr(self._service, "_service")
            and callable(getattr(self._service, "submit_reconcile_status", None))
            and callable(getattr(self._service, "submit_scan_product_catalogs", None))
        )

    def _reconcile_then_catalog(
        self, *, force: bool, preserve_report: bool = False
    ) -> None:
        if self._disposed or self._active_task_id is not None:
            return
        self._catalog_generation += 1
        generation = self._catalog_generation
        self._submit(
            "reconcile_status",
            generation,
            lambda progress, result: self._service.submit_reconcile_status(
                force=force,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result: self._settle_reconciliation(
                result, generation, preserve_report
            ),
            preserve_report=preserve_report,
        )

    def _settle_reconciliation(
        self, result: TaskResult, generation: int, preserve_report: bool
    ) -> None:
        if result.status != "completed":
            self._report_failure("Reconciliation", result)
            return
        self._submit(
            "scan_product_catalogs",
            generation,
            lambda progress, callback: self._service.submit_scan_product_catalogs(
                progress_callback=progress,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._settle_product_catalogs,
            preserve_report=preserve_report,
        )

    def _settle_product_catalogs(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, DataManagerProductCatalogSnapshot
        ):
            self._product_catalogs = result.value
            self._catalog = result.value.catalog
            self._view.set_product_catalogs(result.value)
            self._view.set_status(
                f"Ready: {result.value.catalog.accepted_count} accepted datasets; "
                f"{len(result.value.managed_artifacts.artifacts)} managed Artifacts; "
                f"{len(result.value.databases)} Databases"
            )
            self._revalidate_plan_contexts()
            if self._selected_market is not None:
                self._begin_market_inspection(self._selected_market)
            return
        self._report_failure("Product catalog scan", result)

    def focus_market(self, market_id: MarketId, *, source: str) -> None:
        request = DataManagerFocusRequest(market_id, source)
        if self._disposed:
            return
        self._pending_focus = request
        if self._active_task_id is not None:
            self._view.set_status("Operation in progress; latest market focus is pending")
            return
        if self._catalog is None:
            self.refresh()
            return
        self._apply_pending_focus()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._reconciliation.stop()
        task_id = self._active_task_id
        self._active_task_id = None
        self._active_operation = None
        if task_id is not None:
            self._service.cancel(task_id)
        for dialog in tuple(self._preview_dialogs):
            dialog.close()
        self._preview_dialogs.clear()

    def _wire(self) -> None:
        self._view.refresh_requested.connect(self.refresh)
        self._view.market_selected.connect(self._on_market_selected)
        self._view.artifact_selected.connect(self._on_artifact_selected)
        self._view.recipe_selected.connect(self._on_recipe_selected)
        self._view.preview_dataset_requested.connect(self._preview_dataset)
        self._view.preview_artifact_requested.connect(self._preview_artifact)
        self._view.validate_artifact_requested.connect(self._validate_artifact)
        self._view.delete_artifact_requested.connect(self._delete_artifact)
        self._view.delete_recipe_requested.connect(self._delete_recipe)
        self._view.creation_action_requested.connect(self._on_creation_action)
        self._view.update_action_requested.connect(self._on_update_action)
        self._view.catalog_row_selected.connect(self._on_catalog_row_selected)
        self._view.catalog_history_selected.connect(
            self._on_catalog_history_selected
        )
        self._view.creation_cancel_requested.connect(self._cancel_active_operation)
        self._view.closing.connect(self.dispose)

    def _cancel_active_operation(self) -> None:
        task_id = self._active_task_id
        if task_id is not None and self._service.cancel(task_id):
            self._view.set_status("Cancellation requested")

    def _on_catalog_history_selected(
        self, family: str, logical_identity: str, value: object
    ) -> None:
        if self._disposed or self._active_task_id is not None:
            return
        if not family or not logical_identity:
            return
        self._view.set_historical_catalog_inspection(value)

    def _on_catalog_row_selected(self, family: str, value: object) -> None:
        if self._disposed or self._active_task_id is not None or value is None:
            return
        generation = self._catalog_generation
        if family == "Study Environments":
            self._submit(
                "inspect_study_environment",
                generation,
                lambda progress, result: self._service.submit_inspect_study_environment(
                    value.environment_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_catalog_inspection,
            )
        elif family == "Portable Recipes":
            self._submit(
                "inspect_portable_recipe",
                generation,
                lambda progress, result: self._service.submit_inspect_portable_recipe(
                    value.recipe_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_catalog_inspection,
            )
        elif family == "Recipe Collections":
            self._submit(
                "inspect_recipe_collection",
                generation,
                lambda progress, result: self._service.submit_list_recipe_collection_revisions(
                    value.collection_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_revision_history,
            )
        elif family == "Managed Artifacts":
            self._submit(
                "inspect_managed_artifact",
                generation,
                lambda progress, result: self._service.submit_inspect_managed_artifact(
                    value.market_id,
                    value.logical_artifact_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_managed_history,
            )
        elif family == "Artifact Collections":
            self._submit(
                "inspect_artifact_collection",
                generation,
                lambda progress, result: self._service.submit_list_artifact_collection_revisions(
                    value.collection_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_revision_history,
            )
        elif family == "Databases":
            self._submit(
                "inspect_database",
                generation,
                lambda progress, result: self._service.submit_list_database_revisions(
                    value.definition.database_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_revision_history,
            )

    def _settle_catalog_inspection(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._view.set_catalog_inspection(_object_fields(result.value))
            return
        self._report_failure("Catalog inspection", result)

    def _settle_revision_history(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, tuple):
            values = tuple(result.value)
            logical_identity = ""
            if values:
                logical_identity = str(
                    getattr(values[0], "collection_id", None)
                    or getattr(values[0], "database_id", "")
                )
            self._view.set_catalog_history(logical_identity, values)
            return
        self._report_failure("Revision history", result)

    def _settle_managed_history(self, result: TaskResult) -> None:
        if result.status == "completed":
            versions = tuple(getattr(result.value, "versions", ()))
            current = getattr(result.value, "current", result.value)
            self._view.set_catalog_history(
                str(getattr(current, "logical_artifact_id", "")),
                versions,
            )
            return
        self._report_failure("Managed Artifact history", result)

    def _on_update_action(self, action: str, payload: object) -> None:
        if self._disposed or self._active_task_id is not None or not isinstance(payload, dict):
            return
        generation = self._catalog_generation
        if action == "context_changed":
            scope = str(payload.get("scope") or "")
            if scope == "artifact" and self._artifact_update_plan is not None:
                if payload.get("collection_id") != self._artifact_update_plan.collection_id:
                    self._artifact_update_plan = None
                    self._view.clear_update_artifact_plan()
                    self._view.set_status(
                        "Artifact update plan is stale after Collection selection changed"
                    )
            elif scope == "database" and self._database_update_plan is not None:
                if payload.get("database_id") != self._database_update_plan.database_id:
                    self._database_update_plan = None
                    self._view.clear_update_database_plan()
                    self._view.set_status(
                        "Database update plan is stale after Database selection changed"
                    )
            return
        if action == "refresh_reconciliation":
            self._reconcile_then_catalog(force=True)
            return
        if action == "plan_artifact_update":
            collection_id = str(payload.get("collection_id") or "")
            if not collection_id:
                self._view.set_status("Select an Artifact Collection explicitly")
                return
            self._submit(
                "plan_artifact_update",
                generation,
                lambda progress, result: self._service.submit_plan_artifact_collection_update(
                    collection_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_artifact_update_plan,
            )
            return
        if action == "execute_artifact_update":
            if self._artifact_update_plan is None or self._artifact_update_plan.blocked:
                self._view.set_status("Create an unblocked Artifact update plan first")
                return
            if not self._artifact_update_plan_is_current(payload):
                self._artifact_update_plan = None
                self._view.clear_update_artifact_plan()
                self._view.set_status(
                    "Artifact update plan is stale; plan the selected Collection again"
                )
                return
            self._submit(
                "execute_artifact_update",
                generation,
                lambda progress, result: self._service.submit_execute_artifact_collection_update(
                    self._artifact_update_plan,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_update_write,
            )
            return
        if action == "plan_database_update":
            database_id = str(payload.get("database_id") or "")
            if not database_id:
                self._view.set_status("Select a Database explicitly")
                return
            self._submit(
                "plan_database_update",
                generation,
                lambda progress, result: self._service.submit_plan_database_update(
                    database_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_database_update_plan,
            )
            return
        plan = self._database_update_plan
        if plan is None or plan.blockers:
            self._view.set_status("Create an unblocked Database update plan first")
            return
        if not self._database_update_plan_is_current(payload):
            self._database_update_plan = None
            self._view.clear_update_database_plan()
            self._view.set_status(
                "Database update plan is stale; plan the selected Database again"
            )
            return
        if action == "execute_database_append":
            if plan.mode != "APPEND":
                self._view.set_status("Append requires a matching APPEND plan")
                return
            submit = self._service.submit_execute_database_append
        elif action == "execute_database_rebuild":
            if plan.mode != "REBUILD_REQUIRED":
                self._view.set_status(
                    "Rebuild requires a matching REBUILD_REQUIRED plan"
                )
                return
            if not bool(payload.get("rebuild_confirmed")):
                self._view.set_status("Confirm the full Database rebuild")
                return
            if not self._view.confirm_database_rebuild(plan):
                self._view.set_status("Database rebuild cancelled")
                return
            submit = self._service.submit_execute_database_rebuild
        else:
            return
        self._submit(
            action,
            generation,
            lambda progress, result: submit(
                plan,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._settle_update_write,
        )

    def _settle_artifact_update_plan(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, ArtifactCollectionUpdatePlan
        ):
            self._artifact_update_plan = result.value
            self._view.set_update_artifact_plan(result.value)
            self._view.set_status(
                f"Artifact update plan ready: {len(result.value.nodes)} nodes; "
                f"blockers={len(result.value.blockers)}"
            )
            return
        self._report_failure("Artifact update planning", result)

    def _settle_database_update_plan(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, DatabaseUpdatePlan):
            self._database_update_plan = result.value
            self._view.set_update_database_plan(result.value)
            self._view.set_status(
                f"Database update plan ready: {result.value.mode}; "
                f"blockers={len(result.value.blockers)}"
            )
            return
        self._report_failure("Database update planning", result)

    def _settle_update_write(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, ArtifactCollectionUpdateResult
        ):
            self._view.set_artifact_update_result(result.value)
            self._artifact_update_plan = None
            self._view.clear_update_artifact_plan()
            self._view.set_status("Update publication completed; refreshing reconciliation")
            self._reconcile_then_catalog(force=False, preserve_report=True)
            return
        if result.status == "completed" and isinstance(
            result.value, DatabaseUpdateResult
        ):
            self._view.set_database_update_result(result.value)
            self._database_update_plan = None
            self._view.clear_update_database_plan()
            self._view.set_status("Update publication completed; refreshing reconciliation")
            self._reconcile_then_catalog(force=False, preserve_report=True)
            return
        self._report_failure("Update publication", result)

    def _artifact_update_plan_is_current(self, payload: dict) -> bool:
        plan = self._artifact_update_plan
        if plan is None or str(payload.get("collection_id") or "") != plan.collection_id:
            return False
        revision = self._current_artifact_collection_revision(plan.collection_id)
        return revision is None or revision == plan.collection_revision_id

    def _database_update_plan_is_current(self, payload: dict) -> bool:
        plan = self._database_update_plan
        if plan is None or str(payload.get("database_id") or "") != plan.database_id:
            return False
        revision = self._current_database_revision(plan.database_id)
        return revision is None or revision == plan.database_revision_id

    def _current_recipe_collection_revision(self, collection_id: str) -> str | None:
        catalogs = self._product_catalogs
        if catalogs is None:
            return None
        for item in catalogs.recipe_collections.collections:
            if item.collection_id == collection_id:
                return item.revision_id
        return None

    def _current_artifact_collection_revision(self, collection_id: str) -> str | None:
        catalogs = self._product_catalogs
        if catalogs is None:
            return None
        for item in catalogs.artifact_collections:
            if item.collection_id == collection_id:
                return item.revision_id
        return None

    def _current_database_revision(self, database_id: str) -> str | None:
        catalogs = self._product_catalogs
        if catalogs is None:
            return None
        for item in catalogs.databases:
            if item.definition.database_id == database_id:
                manifest = item.current_manifest
                return None if manifest is None else manifest.revision_id
        return None

    def _revalidate_plan_contexts(self) -> None:
        plan = self._artifact_update_plan
        if plan is not None and self._current_artifact_collection_revision(
            plan.collection_id
        ) not in {None, plan.collection_revision_id}:
            self._artifact_update_plan = None
            self._view.clear_update_artifact_plan()
            self._view.set_status("Artifact update plan became stale after catalog refresh")
        database_plan = self._database_update_plan
        if database_plan is not None and self._current_database_revision(
            database_plan.database_id
        ) not in {None, database_plan.database_revision_id}:
            self._database_update_plan = None
            self._view.clear_update_database_plan()
            self._view.set_status("Database update plan became stale after catalog refresh")
        context = self._base_plan_context
        if (
            context is not None
            and context.recipe_collection_id is not None
            and self._current_recipe_collection_revision(
                context.recipe_collection_id
            ) not in {None, context.recipe_collection_revision_id}
        ):
            self._clear_base_plan("Base Artifact plan became stale after catalog refresh")
        readiness = self._readiness_context
        if (
            readiness is not None
            and self._current_artifact_collection_revision(
                readiness.collection_id
            ) not in {None, readiness.collection_revision_id}
        ):
            self._clear_readiness("Database readiness became stale after catalog refresh")

    def _on_creation_action(self, action: str, payload: object) -> None:
        if self._disposed or self._active_task_id is not None or not isinstance(payload, dict):
            return
        market = self._selected_market
        if action == "context_changed":
            scope = str(payload.get("scope") or "")
            if scope == "base" and self._base_plan is not None:
                self._clear_base_plan(
                    "Base Artifact plan is stale after Recipe selection changed"
                )
            elif scope == "batch" and self._batch_plan is not None:
                self._clear_batch_plan(
                    "Batch Artifact plan is stale after branch or destination changed"
                )
            elif scope == "readiness" and self._database_readiness is not None:
                self._clear_readiness(
                    "Database readiness is stale after Seed or Collection changed"
                )
            return
        if action == "use_target":
            if market is not None:
                self._view.set_creation_summary(f"Target OHLCV: {market.as_key()}")
                self._view.select_creation_stage(1)
            return
        if action in {"refresh_foundations", "reload_creation"}:
            self._scan_creation_foundations()
            return
        if action == "inspect_environment":
            environment_id = str(payload.get("environment_id") or "")
            if not environment_id:
                self._view.set_creation_summary("Select a Study Environment explicitly.")
                return
            self._submit(
                "inspect_study_environment",
                self._catalog_generation,
                lambda progress, result: self._service.submit_inspect_study_environment(
                    environment_id,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_environment_inspection,
            )
            return
        if action == "plan_recipe_derivation":
            environment_id = str(payload.get("environment_id") or "")
            roots = tuple(payload.get("environment_root_entry_ids") or ())
            if not environment_id or not roots:
                self._view.set_creation_summary(
                    "Select an Environment and explicit root entries."
                )
                return
            self._submit(
                "plan_recipe_derivation",
                self._catalog_generation,
                lambda progress, result: self._service.submit_plan_recipe_derivation(
                    environment_id,
                    roots,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_recipe_derivation,
            )
            return
        if action == "persist_recipe_derivation":
            environment_id = str(payload.get("environment_id") or "")
            roots = tuple(payload.get("environment_root_entry_ids") or ())
            if not environment_id or not roots:
                self._view.set_creation_summary(
                    "Select an Environment and explicit root entries."
                )
                return
            self._submit(
                "persist_recipe_derivation",
                self._catalog_generation,
                lambda progress, result: self._service.submit_persist_recipe_derivation(
                    environment_id,
                    roots,
                    create_collection=False,
                    progress_callback=progress,
                    result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_recipe_persistence,
            )
            return
        if action in {"create_recipe_collection", "update_recipe_collection"}:
            self._submit_recipe_collection(action, payload)
            return
        if action in {"load_seed", "validate_seed", "delete_seed"}:
            self._submit_seed_action(action, payload)
            return
        if action in {
            "load_collection",
            "validate_collection",
            "revise_collection",
            "add_collection_branches",
            "remove_collection_branches",
        }:
            self._submit_collection_action(action, payload)
            return
        if market is None:
            self._view.set_creation_summary("Select and accept a Target OHLCV first.")
            return
        generation = self._market_generation
        if action == "create_seed":
            name = str(payload.get("seed_name", "")).strip()
            if not name:
                self._view.set_creation_summary("Database Seed name is required.")
                return
            description = str(payload.get("seed_description", "")).strip()
            columns = tuple(payload.get("seed_columns") or ())
            if not columns:
                self._view.set_creation_summary("Select at least one OHLCV column.")
                return
            custom_range = payload.get("range_mode") == "custom"
            try:
                range_start = (
                    int(str(payload.get("range_start") or "")) if custom_range else None
                )
                range_end = (
                    int(str(payload.get("range_end") or "")) if custom_range else None
                )
            except ValueError:
                self._view.set_creation_summary("Custom range timestamps must be integers.")
                return
            self._submit(
                "create_database_seed",
                generation,
                lambda progress, result: self._service.submit_create_database_seed(
                    market,
                    name,
                    description=description,
                    selected_ohlcv_columns=columns,
                    selected_range_start_ms=range_start,
                    selected_range_end_ms=range_end,
                    progress_callback=progress, result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ),
                self._settle_seed,
            )
            return
        if action == "plan_base":
            context = self._base_context(payload, market)
            if context is None:
                return
            if context.recipe_mode == "collection":
                collection_id = str(payload.get("recipe_collection_id") or "")
                request = DataManagerArtifactMaterializationRequest(
                    target_market_id=market,
                    recipe_collection_id=collection_id,
                )
            else:
                request = DataManagerArtifactMaterializationRequest(
                    market, context.root_recipe_ids
                )
            self._pending_base_plan_context = context
            self._submit(
                "plan_base_artifacts", generation,
                lambda progress, result: self._service.submit_plan_artifact_materialization(
                    request, progress_callback=progress, result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ), self._settle_base_plan,
            )
            return
        if action == "materialize_base":
            if self._base_plan is None or self._base_plan.blocked:
                self._view.set_creation_summary("Create an unblocked base Artifact plan first.")
                return
            if self._base_context(payload, market) != self._base_plan_context:
                self._clear_base_plan(
                    "Base Artifact plan is stale; plan the current Recipe selection again"
                )
                return
            self._submit(
                "materialize_base_artifacts", generation,
                lambda progress, result: self._service.submit_execute_artifact_materialization(
                    self._base_plan, progress_callback=progress, result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ), self._settle_base_materialization,
            )
            return
        if action == "plan_batch":
            self._plan_batch(payload, generation)
            return
        if action == "execute_batch":
            if self._batch_plan is None or self._batch_plan.blocked:
                self._view.set_creation_summary("Create an unblocked batch plan first.")
                return
            current_batch = self._batch_context(payload)
            if current_batch is None or current_batch != self._batch_plan_context:
                self._clear_batch_plan(
                    "Batch Artifact plan is stale; plan the current branches again"
                )
                return
            self._submit(
                "execute_batch_artifacts", generation,
                lambda progress, result: self._service.submit_execute_batch_artifacts(
                    self._batch_plan, progress_callback=progress, result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ), self._settle_batch,
            )
            return
        if action == "create_collection":
            if self._creation_collection is not None:
                self._view.set_creation_summary(
                    f"Artifact Collection ready: {self._creation_collection.collection_id}"
                )
                self._view.select_creation_stage(7)
                return
            if self._base_materialization is None:
                self._view.set_creation_summary("Materialize base Artifacts first.")
                return
            self._submit(
                "create_artifact_collection", generation,
                lambda progress, result: self._service.submit_create_artifact_collection(
                    self._base_materialization, f"{self._creation_seed.display_name if self._creation_seed else 'Database'} Artifacts",
                    progress_callback=progress, result_callback=result,
                    callback_dispatcher=self._dispatcher.dispatch,
                ), self._settle_collection,
            )
            return
        if action == "review":
            seed_id = self._current_seed_id(payload)
            collection_id = self._current_collection_id(payload)
            if not seed_id or not collection_id:
                self._view.set_creation_summary("Select a Seed and Artifact Collection first.")
                return
            collection_revision_id = (
                self._creation_collection.revision_id
                if self._creation_collection is not None
                else self._current_artifact_collection_revision(collection_id)
            )
            if not collection_revision_id:
                self._view.set_creation_summary(
                    "Select an exact Artifact Collection revision first."
                )
                return
            self._pending_readiness_context = _ReadinessContext(
                seed_id, collection_id, collection_revision_id
            )
            self._submit(
                "assess_database_readiness", generation,
                lambda progress, result: self._service.submit_assess_database_readiness(
                    seed_id, collection_id, progress_callback=progress,
                    result_callback=result, callback_dispatcher=self._dispatcher.dispatch,
                ), self._settle_readiness,
            )
            return
        if action == "build":
            self._build_database(payload, generation)

    def _base_context(
        self, payload: dict, market: MarketId
    ) -> _BasePlanContext | None:
        mode = str(payload.get("recipe_mode") or "direct")
        if mode == "collection":
            collection_id = str(payload.get("recipe_collection_id") or "")
            if not collection_id:
                self._view.set_creation_summary(
                    "Select a Recipe Collection explicitly."
                )
                return None
            revision_id = self._current_recipe_collection_revision(collection_id)
            if not revision_id:
                self._view.set_creation_summary(
                    "The selected Recipe Collection revision is unavailable."
                )
                return None
            return _BasePlanContext(
                market, mode, (), collection_id, revision_id
            )
        roots = tuple(payload.get("portable_recipe_ids") or ())
        if not roots:
            selected = str(payload.get("portable_recipe_id") or "").strip()
            roots = (selected,) if selected else ()
        if not roots:
            self._view.set_creation_summary(
                "Select one or more portable Recipe roots first."
            )
            return None
        if len(set(roots)) != len(roots):
            self._view.set_creation_summary("Portable Recipe roots must be unique.")
            return None
        available = self._available_recipe_ids()
        if available and any(recipe_id not in available for recipe_id in roots):
            self._view.set_creation_summary(
                "Every direct Recipe root must exist in the portable Recipe catalog."
            )
            return None
        return _BasePlanContext(market, mode, roots, None, None)

    def _batch_context(self, payload: dict) -> _BatchPlanContext | None:
        materialization = self._base_materialization
        if materialization is None:
            self._view.set_creation_summary("Materialize base Artifacts first.")
            return None
        branch_values = tuple(payload.get("batch_branches") or ())
        if not branch_values:
            self._view.set_creation_summary(
                "Add at least one explicit batch branch before planning."
            )
            return None
        try:
            branches = tuple(
                BatchArtifactBranchRequest(
                    source_logical_artifact_id=str(
                        value.get("source_logical_artifact_id") or ""
                    ),
                    source_output=str(value.get("source_output") or ""),
                    tool_key=str(value.get("tool_key") or ""),
                    parameters=value.get("parameters"),
                    requested_outputs=tuple(value.get("requested_outputs") or ()),
                )
                for value in branch_values
            )
            destination_value = str(
                payload.get("batch_destination") or "individual"
            )
            destination = (
                "collection_revision"
                if destination_value == "existing_collection"
                else destination_value
            )
            collection_id = (
                str(payload.get("collection_id") or "") or None
                if destination == "collection_revision"
                else None
            )
            request = BatchArtifactRequest(
                materialization.target_market_id,
                branches,
                destination,
                collection_id,
            )
        except (TypeError, ValueError) as error:
            self._view.set_creation_summary(f"Invalid batch branch: {error}")
            return None
        return _BatchPlanContext(request)

    def _current_seed_id(self, payload: dict) -> str:
        return str(payload.get("seed_id") or "") or (
            "" if self._creation_seed is None else self._creation_seed.seed_id
        )

    def _current_collection_id(self, payload: dict) -> str:
        return str(payload.get("collection_id") or "") or (
            ""
            if self._creation_collection is None
            else self._creation_collection.collection_id
        )

    def _available_recipe_ids(self) -> set[str]:
        catalogs = self._product_catalogs
        if catalogs is None:
            return set()
        return {
            item.recipe_id
            for item in catalogs.portable_recipes.recipes
            if item.valid
        }

    def _clear_base_plan(self, message: str) -> None:
        self._base_plan = None
        self._base_plan_context = None
        self._pending_base_plan_context = None
        self._view.set_creation_plan_rows(())
        self._view.set_creation_base_plan_ready(False)
        self._view.set_creation_summary(message)

    def _clear_batch_plan(self, message: str) -> None:
        self._batch_plan = None
        self._batch_plan_context = None
        self._pending_batch_plan_context = None
        self._view.set_creation_batch_plan_ready(False)
        self._view.set_creation_summary(message)

    def _clear_readiness(self, message: str) -> None:
        self._database_readiness = None
        self._readiness_context = None
        self._pending_readiness_context = None
        self._view.set_creation_readiness_rows(())
        self._view.set_creation_readiness_ready(False)
        self._view.set_creation_summary(message)

    def _invalidate_creation_context(self, message: str) -> None:
        self._base_plan = None
        self._base_plan_context = None
        self._pending_base_plan_context = None
        self._base_materialization = None
        self._batch_plan = None
        self._batch_plan_context = None
        self._pending_batch_plan_context = None
        self._batch_materialization = None
        self._database_readiness = None
        self._readiness_context = None
        self._pending_readiness_context = None
        self._creation_seed = None
        self._creation_collection = None
        self._view.set_creation_plan_rows(())
        self._view.set_creation_readiness_rows(())
        self._view.invalidate_creation_plans()
        self._view.set_creation_summary(message)

    def _submit_seed_action(self, action: str, payload: dict) -> None:
        seed_id = str(payload.get("seed_id") or "")
        if not seed_id:
            self._view.set_creation_summary("Select a Database Seed explicitly.")
            return
        if action == "load_seed":
            submit = self._service.submit_load_database_seed
            settle = self._settle_seed_load
        elif action == "validate_seed":
            submit = self._service.submit_validate_database_seed
            settle = self._settle_seed_validation
        else:
            if not self._view.confirm_database_seed_deletion(seed_id):
                self._view.set_creation_summary("Database Seed deletion cancelled.")
                return
            submit = self._service.submit_delete_database_seed
            settle = self._settle_seed_deletion
        self._submit(
            action,
            self._catalog_generation,
            lambda progress, result: submit(
                seed_id,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            settle,
        )

    def _submit_collection_action(self, action: str, payload: dict) -> None:
        collection_id = str(payload.get("collection_id") or "")
        if not collection_id:
            self._view.set_creation_summary("Select an Artifact Collection explicitly.")
            return
        revision_id = str(payload.get("collection_revision_id") or "") or None
        generation = self._catalog_generation
        if action == "load_collection":
            submit = lambda progress, result: self._service.submit_load_artifact_collection(
                collection_id,
                revision_id,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
            settle = self._settle_collection_load
        elif action == "validate_collection":
            submit = lambda progress, result: self._service.submit_validate_artifact_collection(
                collection_id,
                revision_id,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
            settle = self._settle_collection_validation
        elif action == "add_collection_branches":
            if self._batch_materialization is None:
                self._view.set_creation_summary(
                    "Execute an explicit batch materialization before adding branches."
                )
                return
            submit = lambda progress, result: self._service.submit_add_artifact_collection_branches(
                collection_id,
                self._batch_materialization,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
            settle = self._settle_collection_write
        else:
            remove_roots = tuple(payload.get("collection_remove_roots") or ())
            if action == "remove_collection_branches" and not remove_roots:
                self._view.set_creation_summary(
                    "Enter optional root logical Artifact IDs to remove."
                )
                return
            selected_outputs = None
            presentation_order = None
            if action == "revise_collection":
                parsed = self._selected_outputs_for_revision(
                    collection_id,
                    tuple(payload.get("collection_selected_outputs") or ()),
                    remove_roots,
                )
                if parsed is None:
                    return
                selected_outputs, presentation_order = parsed
            name = str(payload.get("collection_name") or "").strip() or None
            description_value = str(payload.get("collection_description") or "")
            description = description_value if description_value else None
            submit = lambda progress, result: self._service.submit_revise_artifact_collection(
                collection_id,
                display_name=name,
                description=description,
                selected_outputs=selected_outputs,
                presentation_order=presentation_order,
                remove_root_logical_artifact_ids=remove_roots,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
            settle = self._settle_collection_write
        self._submit(action, generation, submit, settle)

    def _selected_outputs_for_revision(
        self,
        collection_id: str,
        rows: tuple[dict[str, str], ...],
        remove_roots: tuple[str, ...],
    ) -> tuple[tuple[ArtifactCollectionOutputV1, ...], tuple[str, ...]] | None:
        collection = self._creation_collection
        if collection is None or collection.collection_id != collection_id:
            self._view.set_creation_summary(
                "Load the selected Artifact Collection revision before editing outputs."
            )
            return None
        supports = set(collection.support_logical_artifact_ids)
        if supports & set(remove_roots):
            self._view.set_creation_summary(
                "Required support members are locked and cannot be removed."
            )
            return None
        members = {
            item.version_key.logical_artifact_id: set(item.output_names)
            for item in collection.members
        }
        if not rows:
            self._view.set_creation_summary(
                "Artifact Collection selected outputs cannot be empty."
            )
            return None
        outputs: list[ArtifactCollectionOutputV1] = []
        ordered: list[tuple[int, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        seen_columns: set[str] = set()
        seen_orders: set[int] = set()
        for row in rows:
            logical_id = str(row.get("logical_artifact_id") or "")
            output_name = str(row.get("output_name") or "")
            column_name = str(row.get("column_name") or "")
            try:
                order = int(str(row.get("order") or ""))
            except ValueError:
                self._view.set_creation_summary(
                    "Every selected output requires an integer presentation order."
                )
                return None
            if logical_id not in members or output_name not in members[logical_id]:
                self._view.set_creation_summary(
                    "Every selected output must exist on a loaded Collection member."
                )
                return None
            if not column_name:
                self._view.set_creation_summary(
                    "Every selected output requires a non-empty Database column name."
                )
                return None
            pair = (logical_id, output_name)
            if pair in seen_pairs or column_name in seen_columns:
                self._view.set_creation_summary(
                    "Selected outputs and Database column names must be unique."
                )
                return None
            if order < 1 or order in seen_orders:
                self._view.set_creation_summary(
                    "Presentation order must be unique and start at 1."
                )
                return None
            seen_pairs.add(pair)
            seen_columns.add(column_name)
            seen_orders.add(order)
            try:
                outputs.append(
                    ArtifactCollectionOutputV1(
                        logical_id, output_name, column_name
                    )
                )
            except (TypeError, ValueError) as error:
                self._view.set_creation_summary(
                    f"Invalid selected output: {error}"
                )
                return None
            ordered.append((order, column_name))
        if seen_orders != set(range(1, len(rows) + 1)):
            self._view.set_creation_summary(
                "Presentation order must be complete and deterministic."
            )
            return None
        return tuple(outputs), tuple(
            column for _order, column in sorted(ordered)
        )

    def _submit_recipe_collection(self, action: str, payload: dict) -> None:
        persistence = self._recipe_persistence
        roots = tuple(payload.get("portable_recipe_ids") or ())
        if not roots and persistence is not None:
            roots = persistence.root_recipe_ids
        if not roots:
            self._view.set_creation_summary(
                "Select explicit portable Recipe roots or persist an Environment derivation first."
            )
            return
        if len(set(roots)) != len(roots):
            self._view.set_creation_summary("Portable Recipe roots must be unique.")
            return
        available = self._available_recipe_ids()
        if available and any(recipe_id not in available for recipe_id in roots):
            self._view.set_creation_summary(
                "Every Recipe Collection root must exist in the portable Recipe catalog."
            )
            return
        name = str(payload.get("recipe_collection_name") or "").strip()
        description = str(payload.get("recipe_collection_description") or "").strip()
        if not name:
            self._view.set_creation_summary("Recipe Collection name is required.")
            return
        if action == "create_recipe_collection":
            submit = lambda progress, result: self._service.submit_create_recipe_collection(
                name,
                description,
                roots,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        else:
            collection_id = str(payload.get("recipe_collection_id") or "")
            if not collection_id:
                self._view.set_creation_summary(
                    "Select a Recipe Collection revision explicitly."
                )
                return
            submit = lambda progress, result: self._service.submit_update_recipe_collection(
                collection_id,
                name,
                description,
                roots,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            )
        self._submit(
            action,
            self._catalog_generation,
            submit,
            self._settle_recipe_collection_write,
        )

    def _settle_environment_inspection(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, DataManagerStudyEnvironmentInspection
        ):
            self._view.set_creation_environment_rows(tuple(
                (
                    item.entry_id,
                    item.tool_key,
                    item.mode,
                    item.status,
                    ", ".join(item.dependency_entry_ids),
                    item.reason,
                )
                for item in result.value.entries
            ))
            self._view.set_creation_summary(
                f"Study Environment inspection: {len(result.value.entries)} entries"
            )
            return
        self._report_failure("Study Environment inspection", result)

    def _settle_recipe_derivation(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, DataManagerRecipeDerivationPlan
        ):
            self._derivation_plan = result.value
            self._view.set_creation_recipe_rows(tuple(
                (
                    item.recipe_id,
                    item.tool_key,
                    item.kind,
                    ", ".join(item.output_names),
                    str(len(item.dependencies)),
                    "blocked" if result.value.blocked else "planned",
                )
                for item in result.value.recipes
            ))
            self._view.set_creation_summary(
                f"Recipe derivation planned: {len(result.value.recipes)} Recipes; "
                f"blockers={len(result.value.blockers)}"
            )
            return
        self._report_failure("Recipe derivation planning", result)

    def _settle_recipe_persistence(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, DataManagerRecipePersistenceResult
        ):
            self._recipe_persistence = result.value
            self._view.set_creation_summary(
                f"Portable Recipes persisted: {len(result.value.root_recipe_ids)} root; "
                f"{len(result.value.support_recipe_ids)} support"
            )
            self._after_write_refresh()
            return
        self._report_failure("Recipe persistence", result)

    def _settle_recipe_collection_write(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._view.set_creation_summary("Recipe Collection revision published")
            self._after_write_refresh()
            return
        self._report_failure("Recipe Collection publication", result)

    def _scan_creation_foundations(self) -> None:
        self._submit(
            "scan_creation_foundations", self._market_generation,
            lambda progress, result: self._service.submit_scan_creation_foundations(
                progress_callback=progress, result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ), self._settle_creation_foundations,
        )

    def _after_write_refresh(self) -> None:
        if self._supports_product_catalogs():
            self._reconcile_then_catalog(force=False, preserve_report=True)
        else:
            self._scan_creation_foundations()

    def _plan_batch(self, payload: dict, generation: int) -> None:
        context = self._batch_context(payload)
        if context is None:
            return
        self._pending_batch_plan_context = context
        self._submit(
            "plan_batch_artifacts", generation,
            lambda progress, result: self._service.submit_plan_batch_artifacts(
                context.request, progress_callback=progress, result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ), self._settle_batch_plan,
        )

    def _build_database(self, payload: dict, generation: int) -> None:
        seed_id = self._current_seed_id(payload)
        collection_id = self._current_collection_id(payload)
        if self._database_readiness is None or not self._database_readiness.ready:
            self._view.set_creation_summary("Validate Database readiness before building.")
            return
        collection_revision_id = (
            self._creation_collection.revision_id
            if self._creation_collection is not None
            and self._creation_collection.collection_id == collection_id
            else self._current_artifact_collection_revision(collection_id)
        )
        current_context = (
            None
            if not collection_revision_id
            else _ReadinessContext(seed_id, collection_id, collection_revision_id)
        )
        if current_context != self._readiness_context:
            self._clear_readiness(
                "Database readiness is stale; validate the current Seed and Collection again"
            )
            return
        if not bool(payload.get("build_confirmed")):
            self._view.set_creation_summary("Confirm immutable Database publication.")
            return
        database_id = str(payload.get("database_id") or "") or None
        display_name = str(payload.get("database_name") or "") or None
        description = str(payload.get("database_description") or "") or None
        readiness = self._database_readiness
        database_identity = database_id or display_name or "New Database"
        coverage = (
            f"{readiness.first_usable_timestamp_ms} - "
            f"{readiness.last_usable_timestamp_ms}"
        )
        if not self._view.confirm_database_publication(
            database_identity=database_identity,
            market_id=self._selected_market,
            seed_id=seed_id,
            collection_id=collection_id,
            collection_revision_id=collection_revision_id,
            row_count=readiness.row_count,
            column_count=readiness.column_count,
            coverage=coverage,
            selected_columns=readiness.column_names,
        ):
            self._view.set_creation_summary("Database publication cancelled.")
            return
        self._submit(
            "build_database_revision", generation,
            lambda progress, result: self._service.submit_build_database_revision(
                seed_id,
                collection_id,
                database_id=database_id,
                display_name=display_name,
                description=description,
                progress_callback=progress,
                result_callback=result, callback_dispatcher=self._dispatcher.dispatch,
            ), self._settle_database,
        )

    def _settle_seed(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._creation_seed = result.value
            self._database_readiness = None
            self._readiness_context = None
            self._view.set_creation_readiness_ready(False)
            self._view.set_creation_summary(f"Database Seed created: {result.value.seed_id}")
            self._view.select_creation_stage(2)
            self._after_write_refresh()
            return
        self._report_failure("Database Seed creation", result)

    def _settle_seed_load(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._creation_seed = result.value
            self._view.set_creation_summary(
                f"Database Seed loaded: {result.value.seed_id}"
            )
            return
        self._report_failure("Database Seed load", result)

    def _settle_seed_validation(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, tuple):
            valid, blockers = result.value
            self._view.set_creation_summary(
                f"Database Seed valid={valid}; blockers={' | '.join(blockers) or 'none'}"
            )
            return
        self._report_failure("Database Seed validation", result)

    def _settle_seed_deletion(self, result: TaskResult) -> None:
        if result.status == "completed":
            deleted_id = str(getattr(result.value, "seed_id", ""))
            if self._creation_seed is not None and self._creation_seed.seed_id == deleted_id:
                self._creation_seed = None
            self._view.set_creation_summary(f"Database Seed deleted: {deleted_id}")
            self._after_write_refresh()
            return
        self._report_failure("Database Seed deletion", result)

    def _settle_creation_foundations(self, result: TaskResult) -> None:
        if result.status != "completed" or not isinstance(result.value, tuple) or len(result.value) != 6:
            self._report_failure("Creation foundation scan", result)
            return
        environments, recipes, recipe_collections, seeds, collections, databases = result.value
        self._view.set_creation_catalogs(
            portable_recipes=tuple(
                (item.recipe_id, f"{item.tool_key} — {', '.join(item.output_names)}")
                for item in recipes.recipes if item.valid
            ),
            seeds=tuple((item.seed_id, item.display_name) for item in seeds),
            collections=tuple((item.collection_id, item.display_name) for item in collections),
            databases=tuple((item, item) for item in databases),
            environments=tuple(
                (item.environment_id, item.display_name)
                for item in environments.environments
                if item.valid
            ),
            recipe_collections=tuple(
                (item.collection_id, item.display_name)
                for item in recipe_collections.collections
                if item.valid
            ),
        )
        self._view.set_creation_summary(
            f"Foundations: {len(recipes.recipes)} Recipes, {len(seeds)} Seeds, "
            f"{len(collections)} Artifact Collections, {len(databases)} Databases"
        )

    def _settle_base_plan(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, DataManagerArtifactMaterializationPlan):
            context = self._pending_base_plan_context
            self._pending_base_plan_context = None
            if context is None:
                self._view.set_creation_summary("Base Artifact plan context is unavailable.")
                return
            self._base_plan = result.value
            self._base_plan_context = context
            self._view.set_creation_base_plan_ready(not result.value.blocked)
            self._view.set_creation_plan_rows(tuple(
                (
                    item.portable_recipe_id,
                    item.logical_artifact_id,
                    item.tool_key,
                    item.role,
                    item.status,
                    " | ".join(item.blockers),
                )
                for item in result.value.nodes
            ))
            self._view.set_creation_summary(
                f"Base plan: {len(result.value.nodes)} Artifact(s), "
                f"{len(result.value.execution_stages)} stage(s), blockers={len(result.value.blockers)}"
            )
            if not result.value.blocked:
                self._view.select_creation_stage(4)
            return
        self._pending_base_plan_context = None
        self._view.set_creation_base_plan_ready(False)
        self._report_failure("Base Artifact planning", result)

    def _settle_base_materialization(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, DataManagerArtifactMaterializationResult):
            self._base_materialization = result.value
            self._view.set_creation_summary(
                f"Base Artifacts ready: {len(result.value.root_logical_artifact_ids)} root, "
                f"{len(result.value.support_logical_artifact_ids)} support"
            )
            self._view.select_creation_stage(5)
            self._after_write_refresh()
            return
        self._report_failure("Base Artifact materialization", result)

    def _settle_batch_plan(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, BatchArtifactPlan):
            context = self._pending_batch_plan_context
            self._pending_batch_plan_context = None
            if context is None:
                self._view.set_creation_summary("Batch plan context is unavailable.")
                return
            self._batch_plan = result.value
            self._batch_plan_context = context
            self._view.set_creation_batch_plan_ready(not result.value.blocked)
            self._view.set_creation_summary(
                f"Batch plan: {len(result.value.new_recipe_ids)} new Recipe(s), "
                f"{len(result.value.reusable_recipe_ids)} reusable, blockers={len(result.value.blockers)}"
            )
            return
        self._pending_batch_plan_context = None
        self._view.set_creation_batch_plan_ready(False)
        self._report_failure("Batch planning", result)

    def _settle_batch(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, tuple):
            self._batch_materialization, self._creation_collection = result.value
            collection_text = (
                "individual managed Artifacts"
                if self._creation_collection is None
                else f"Collection {self._creation_collection.collection_id}"
            )
            self._view.set_creation_summary(f"Batch complete; {collection_text}")
            self._view.select_creation_stage(6)
            self._after_write_refresh()
            return
        self._report_failure("Batch execution", result)

    def _settle_collection(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._creation_collection = result.value
            self._database_readiness = None
            self._readiness_context = None
            self._view.set_creation_readiness_ready(False)
            self._view.set_creation_summary(f"Artifact Collection created: {result.value.collection_id}")
            self._view.select_creation_stage(7)
            self._after_write_refresh()
            return
        self._report_failure("Artifact Collection creation", result)

    def _settle_collection_load(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._creation_collection = result.value
            self._view.set_creation_collection_rows(_collection_rows(result.value))
            self._view.set_creation_summary(
                "Artifact Collection loaded: "
                f"{result.value.collection_id} / {result.value.revision_id}"
            )
            return
        self._report_failure("Artifact Collection load", result)

    def _settle_collection_validation(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._view.set_creation_summary(
                f"Artifact Collection valid={result.value.valid}; "
                f"database_ready={result.value.database_ready}; "
                f"blockers={' | '.join(result.value.blockers) or 'none'}"
            )
            return
        self._report_failure("Artifact Collection validation", result)

    def _settle_collection_write(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._creation_collection = result.value
            self._database_readiness = None
            self._readiness_context = None
            self._view.set_creation_readiness_ready(False)
            self._view.set_creation_collection_rows(_collection_rows(result.value))
            self._view.set_creation_summary(
                "Artifact Collection revision published: "
                f"{result.value.collection_id} / {result.value.revision_id}"
            )
            self._after_write_refresh()
            return
        self._report_failure("Artifact Collection revision", result)

    def _settle_readiness(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(result.value, DatabaseReadiness):
            context = self._pending_readiness_context
            self._pending_readiness_context = None
            if context is None or (
                result.value.seed_id,
                result.value.collection_id,
                result.value.collection_revision_id,
            ) != (
                context.seed_id,
                context.collection_id,
                context.collection_revision_id,
            ):
                self._view.set_creation_summary(
                    "Database readiness context does not match the current GUI selection."
                )
                self._view.set_creation_readiness_ready(False)
                return
            self._database_readiness = result.value
            self._readiness_context = context
            self._view.set_creation_readiness_ready(result.value.ready)
            self._view.set_creation_readiness_rows((
                ("Ready", "yes" if result.value.ready else "no", " | ".join(result.value.blockers)),
                ("Rows", str(result.value.row_count), f"Warm-up excluded: {result.value.warmup_excluded_rows}"),
                ("Columns", str(result.value.column_count), ", ".join(result.value.column_names)),
                ("Coverage", str(result.value.first_usable_timestamp_ms or ""), str(result.value.last_usable_timestamp_ms or "")),
            ))
            self._view.set_creation_summary(
                f"Database ready={result.value.ready}; rows={result.value.row_count}; "
                f"columns={result.value.column_count}; warm-up excluded={result.value.warmup_excluded_rows}"
            )
            if result.value.ready:
                self._view.select_creation_stage(8)
            return
        self._pending_readiness_context = None
        self._view.set_creation_readiness_ready(False)
        self._report_failure("Database readiness", result)

    def _settle_database(self, result: TaskResult) -> None:
        if result.status == "completed":
            self._view.set_creation_summary(
                f"Database revision published: {result.value.database_id} / {result.value.revision_id}"
            )
            self._view.set_creation_build_report(tuple(
                (name, str(getattr(result.value, name)))
                for name in (
                    "database_id",
                    "revision_id",
                    "collection_id",
                    "collection_revision_id",
                    "row_count",
                    "column_count",
                    "first_timestamp_ms",
                    "last_timestamp_ms",
                )
            ))
            self._database_readiness = None
            self._readiness_context = None
            self._view.set_creation_readiness_ready(False)
            self._after_write_refresh()
            return
        self._report_failure("Database build", result)

    def _on_market_selected(self, market_id: object) -> None:
        if self._disposed or self._active_task_id is not None:
            return
        if not isinstance(market_id, MarketId):
            self._invalidate_creation_context("Target OHLCV selection was cleared")
            self._selected_artifact = None
            self._selected_recipe = None
            self._market_snapshot = None
            self._selected_market = None
            return
        if market_id != self._selected_market:
            self._invalidate_creation_context(
                "Creation plans were cleared because Target OHLCV changed"
            )
        self._begin_market_inspection(market_id)

    def _begin_market_inspection(self, market_id: MarketId) -> None:
        if market_id != self._selected_market:
            self._invalidate_creation_context(
                "Creation plans were cleared because Target OHLCV changed"
            )
        self._selected_artifact = None
        self._selected_recipe = None
        self._market_snapshot = None
        self._selected_market = market_id
        self._view.set_market_snapshot(None)
        if not self._view.select_market(market_id, emit_selection=False):
            self._clear_unavailable_focus(
                market_id, "missing from the current Data Manager catalog"
            )
            return
        self._market_generation += 1
        generation = self._market_generation
        self._submit(
            "inspect_market",
            generation,
            lambda progress, result: self._service.submit_inspect_market(
                market_id,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result, expected=market_id: self._settle_market(result, expected),
        )

    def _on_artifact_selected(self, value: object) -> None:
        self._selected_artifact = (
            value if isinstance(value, DataManagerArtifactEntry) and value.valid else None
        )

    def _on_recipe_selected(self, value: object) -> None:
        self._selected_recipe = (
            value if isinstance(value, DataManagerRecipeEntry) and value.valid else None
        )

    def _preview_dataset(self) -> None:
        market = self._selected_market
        if market is None or self._active_task_id is not None:
            return
        generation = self._market_generation
        self._submit(
            "preview_dataset",
            generation,
            lambda progress, result: self._service.submit_preview_dataset(
                market,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result, expected=market: self._settle_preview(
                result, expected_market=expected
            ),
        )

    def _preview_artifact(self) -> None:
        artifact = self._selected_artifact
        if artifact is None or self._active_task_id is not None:
            return
        generation = self._market_generation
        identity = _artifact_identity(artifact)
        self._submit(
            "preview_artifact",
            generation,
            lambda progress, result: self._service.submit_preview_artifact(
                *identity,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result, expected=identity: self._settle_preview(
                result, expected_market=expected[0], expected_artifact=expected
            ),
        )

    def _validate_artifact(self) -> None:
        artifact = self._selected_artifact
        if artifact is None or self._active_task_id is not None:
            return
        generation = self._market_generation
        identity = _artifact_identity(artifact)
        self._submit(
            "validate_artifact",
            generation,
            lambda progress, result: self._service.submit_validate_artifact(
                *identity,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result, expected=identity: self._settle_validation(result, expected),
        )

    def _delete_artifact(self) -> None:
        artifact = self._selected_artifact
        if artifact is None or self._active_task_id is not None:
            return
        generation = self._market_generation
        identity = _artifact_identity(artifact)
        self._submit(
            "delete_artifact",
            generation,
            lambda progress, result: self._service.submit_delete_artifact(
                *identity,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result, expected=identity: self._settle_deletion(
                result, expected, "artifact"
            ),
        )

    def _delete_recipe(self) -> None:
        recipe = self._selected_recipe
        if recipe is None or self._active_task_id is not None:
            return
        generation = self._market_generation
        market = recipe.market_id
        identity = (market, recipe.kind, recipe.tool_key, recipe.recipe_id)
        self._submit(
            "delete_recipe",
            generation,
            lambda progress, result: self._service.submit_delete_recipe(
                *identity,
                progress_callback=progress,
                result_callback=result,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            lambda result, expected=identity: self._settle_deletion(
                result, expected, "recipe"
            ),
        )

    def _submit(
        self,
        operation: str,
        generation: int,
        submit,
        settle,
        *,
        preserve_report: bool = False,
    ) -> None:
        if self._active_task_id is not None or self._disposed:
            return
        self._active_operation = operation
        self._view.set_busy(True, operation, preserve_operation=preserve_report)
        task_ref: list[str] = []
        settled = [False]

        def on_progress(progress: TaskProgress) -> None:
            task_id = task_ref[0] if task_ref else progress.task_id
            if self._disposed or task_id != self._active_task_id:
                return
            self._view.set_status(progress.message)
            self._view.set_progress(
                progress.current, progress.total, progress.message
            )

        def on_result(result: TaskResult) -> None:
            settled[0] = True
            task_id = task_ref[0] if task_ref else result.task_id
            if self._disposed or task_id != self._active_task_id:
                return
            if operation in {
                "scan_catalog",
                "reconcile_status",
                "scan_product_catalogs",
                "inspect_study_environment",
                "inspect_portable_recipe",
                "inspect_recipe_collection",
                "inspect_managed_artifact",
                "inspect_artifact_collection",
                "inspect_database",
                "plan_artifact_update",
                "execute_artifact_update",
                "plan_database_update",
                "execute_database_append",
                "execute_database_rebuild",
            }:
                current = generation == self._catalog_generation
            else:
                current = generation == self._market_generation
            self._active_task_id = None
            self._active_operation = None
            self._view.set_busy(False)
            self._view.set_progress(0, 1)
            message = result.error_message or result.error_type or result.status
            if not preserve_report:
                self._view.settle_operation(
                    result.status,
                    str(message),
                    _operation_details(operation, task_id, result),
                )
            if current:
                settle(result)
            self._apply_pending_focus()

        try:
            submission = submit(on_progress, on_result)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._active_operation = None
            self._view.set_busy(False)
            self._view.set_status(f"{operation} submission failed")
            self._view.append_status(f"{type(error).__name__}: {error}")
            self._view.settle_operation(
                "failed", f"{type(error).__name__}: {error}"
            )
            self._apply_pending_focus()
            return
        task_ref.append(submission.task_id)
        if not settled[0]:
            self._active_task_id = submission.task_id
            self._view.set_operation_task(submission.task_id)

    def _settle_catalog(self, result: TaskResult) -> None:
        if result.status == "completed" and isinstance(
            result.value, DataManagerCatalogSnapshot
        ):
            self._catalog = result.value
            self._view.set_catalog(result.value)
            if (
                self._selected_market is not None
                and result.value.accepted_market(self._selected_market) is None
            ):
                market = self._selected_market
                self._clear_unavailable_focus(
                    market, self._unavailability_reason(result.value, market)
                )
                return
            self._view.set_status(
                f"Ready: {result.value.accepted_count} accepted, "
                f"{result.value.rejected_count} rejected"
            )
            if self._selected_market is not None and self._pending_focus is None:
                self._begin_market_inspection(self._selected_market)
            return
        self._report_failure("Catalog scan", result)

    def _settle_market(self, result: TaskResult, expected_market: MarketId) -> None:
        if self._settle_market_unavailable(result, expected_market):
            return
        if result.status == "completed" and isinstance(
            result.value, DataManagerMarketSnapshot
        ):
            if result.value.market_id != self._selected_market:
                return
            self._market_snapshot = result.value
            self._view.set_market_snapshot(result.value)
            self._view.set_status("Market inspection ready")
            return
        self._report_failure("Market inspection", result)

    def _settle_preview(
        self,
        result: TaskResult,
        *,
        expected_market: MarketId,
        expected_artifact: tuple[MarketId, str, str, str] | None = None,
    ) -> None:
        if self._settle_market_unavailable(result, expected_market):
            return
        if expected_artifact is not None:
            selected = self._selected_artifact
            if selected is None or _artifact_identity(selected) != expected_artifact:
                return
        if result.status == "completed" and isinstance(result.value, DataManagerPreview):
            if result.value.market_id != self._selected_market:
                return
            dialog = DataManagerPreviewDialog(result.value, self._view)
            self._preview_dialogs.add(dialog)
            dialog.finished.connect(lambda _code, value=dialog: self._preview_dialogs.discard(value))
            dialog.show()
            self._view.set_status("Preview ready")
            return
        self._report_failure("Preview", result)

    def _settle_validation(
        self, result: TaskResult, expected: tuple[MarketId, str, str, str]
    ) -> None:
        if self._settle_market_unavailable(result, expected[0]):
            return
        selected = self._selected_artifact
        if selected is None or _artifact_identity(selected) != expected:
            return
        if result.status == "completed" and isinstance(
            result.value, DataManagerArtifactValidation
        ):
            self._view.update_artifact_validation(result.value)
            self._selected_artifact = self._view.selected_artifact()
            self._view.set_status(f"Artifact is {result.value.status}")
            if result.value.reason:
                self._view.append_status(result.value.reason)
            return
        self._report_failure("Artifact validation", result)

    def _settle_deletion(
        self,
        result: TaskResult,
        expected: tuple[MarketId, str, str, str],
        expected_object_kind: str,
    ) -> None:
        if self._settle_market_unavailable(result, expected[0]):
            return
        if result.status != "completed" or not isinstance(
            result.value, DataManagerDeletionResult
        ):
            self._report_failure("Deletion", result)
            return
        deletion = result.value
        if (
            deletion.object_kind != expected_object_kind
            or _deletion_identity(deletion) != expected
        ):
            return
        market, kind, tool_key, object_id = expected
        if market != self._selected_market or self._market_snapshot is None:
            return
        if deletion.object_kind == "artifact":
            selected = self._selected_artifact
            if selected is None or _artifact_identity(selected) != expected:
                return
            artifacts = tuple(
                item
                for item in self._market_snapshot.artifacts
                if _artifact_identity(item) != expected
            )
            recipes = self._market_snapshot.recipes
        else:
            selected = self._selected_recipe
            if selected is None or (
                selected.market_id,
                selected.kind,
                selected.tool_key,
                selected.recipe_id,
            ) != expected:
                return
            artifacts = self._market_snapshot.artifacts
            recipes = tuple(
                item
                for item in self._market_snapshot.recipes
                if (
                    item.market_id,
                    item.kind,
                    item.tool_key,
                    item.recipe_id,
                )
                != expected
            )
        filtered = DataManagerMarketSnapshot(
            market_id=market,
            dataset=self._market_snapshot.dataset,
            recipes=recipes,
            artifacts=artifacts,
        )
        self._market_snapshot = filtered
        self._selected_artifact = None
        self._selected_recipe = None
        self._view.set_market_snapshot(filtered)
        self._view.set_status("Deletion completed")
        if self._pending_focus is not None:
            return
        generation = self._market_generation
        self._submit(
            "refresh_after_delete",
            generation,
            lambda progress, callback: self._service.submit_inspect_market(
                market,
                progress_callback=progress,
                result_callback=callback,
                callback_dispatcher=self._dispatcher.dispatch,
            ),
            self._settle_deletion_refresh,
        )
        if self._active_operation == "refresh_after_delete":
            self._view.set_status("Deletion completed; refreshing catalog")

    def _settle_deletion_refresh(self, result: TaskResult) -> None:
        if self._pending_focus is not None:
            return
        if result.status == "completed" and isinstance(
            result.value, DataManagerMarketSnapshot
        ):
            if result.value.market_id != self._selected_market:
                return
            self._market_snapshot = result.value
            self._view.set_market_snapshot(result.value)
            self._view.set_status("Deletion completed; catalog refreshed")
            return
        message = result.error_message or result.error_type or result.status
        status = f"Deletion completed; catalog refresh failed: {message}"
        self._view.set_status(status)
        self._view.append_status(status)

    def _report_failure(self, label: str, result: TaskResult) -> None:
        message = result.error_message or result.error_type or result.status
        self._view.set_status(f"{label} {result.status}")
        self._view.append_status(str(message))

    def _settle_market_unavailable(
        self, result: TaskResult, expected_market: MarketId
    ) -> bool:
        if (
            result.status != "failed"
            or result.error_type != _MARKET_UNAVAILABLE_ERROR
            or expected_market != self._selected_market
        ):
            return False
        message = result.error_message or result.error_type
        self._market_generation += 1
        self._selected_market = None
        self._selected_artifact = None
        self._selected_recipe = None
        self._market_snapshot = None
        self._view.clear_selected_market(str(message))
        self._view.set_status(str(message))
        return True

    def _apply_pending_focus(self) -> None:
        if self._disposed or self._active_task_id is not None:
            return
        request = self._pending_focus
        if request is None:
            return
        if self._catalog is None:
            self.refresh()
            return
        self._pending_focus = None
        accepted = self._catalog.accepted_market(request.market_id)
        if accepted is None:
            self._clear_unavailable_focus(
                request.market_id,
                self._unavailability_reason(self._catalog, request.market_id),
            )
            return
        self._begin_market_inspection(request.market_id)

    @staticmethod
    def _unavailability_reason(
        catalog: DataManagerCatalogSnapshot, market_id: MarketId
    ) -> str:
        rejected = next(
            (item for item in catalog.datasets if item.market_id == market_id), None
        )
        return (
            "missing from canonical persistence"
            if rejected is None
            else f"{rejected.rejection_code}: {rejected.rejection_reason}"
        )

    def _clear_unavailable_focus(self, market_id: MarketId, reason: str) -> None:
        self._market_generation += 1
        self._selected_market = None
        self._selected_artifact = None
        self._selected_recipe = None
        self._market_snapshot = None
        status = f"Requested market is unavailable: {market_id.as_key()}: {reason}"
        self._view.clear_selected_market(status)
        self._view.set_status(status)


def _artifact_identity(
    artifact: DataManagerArtifactEntry,
) -> tuple[MarketId, str, str, str]:
    return (
        artifact.market_id,
        artifact.kind,
        artifact.tool_key,
        artifact.artifact_id,
    )


def _object_fields(value: object) -> tuple[tuple[str, object], ...]:
    fields = getattr(value, "__dataclass_fields__", {})
    if fields:
        return tuple((name, getattr(value, name)) for name in fields)
    return (("value", value),)


def _collection_rows(value: object) -> tuple[tuple[str, ...], ...]:
    roots = set(getattr(value, "root_logical_artifact_ids", ()))
    order = {
        name: index + 1
        for index, name in enumerate(getattr(value, "presentation_order", ()))
    }
    return tuple(
        (
            item.logical_artifact_id,
            item.output_name,
            item.column_name,
            str(order.get(item.column_name, "")),
            "root" if item.logical_artifact_id in roots else "support",
            "no" if item.logical_artifact_id in roots else "yes",
        )
        for item in getattr(value, "selected_outputs", ())
    )


def _operation_details(
    operation: str, task_id: str, result: TaskResult
) -> tuple[tuple[str, str], ...]:
    publication_operations = {
        "persist_recipe_derivation",
        "create_recipe_collection",
        "update_recipe_collection",
        "create_database_seed",
        "delete_seed",
        "materialize_base_artifacts",
        "execute_batch_artifacts",
        "create_artifact_collection",
        "revise_collection",
        "add_collection_branches",
        "remove_collection_branches",
        "build_database_revision",
        "execute_artifact_update",
        "execute_database_append",
        "execute_database_rebuild",
    }
    details = [
        ("Operation", operation),
        ("Task ID", task_id),
        ("State", result.status),
        ("Error type", result.error_type or ""),
        ("Error message", result.error_message or ""),
        (
            "Published",
            "yes"
            if result.status == "completed" and operation in publication_operations
            else "no",
        ),
    ]
    for name, value in _object_fields(result.value):
        if name.endswith("_id") or name in {"mode", "status", "row_count", "column_count"}:
            details.append((name, str(value)))
    return tuple(details)


def _deletion_identity(
    deletion: DataManagerDeletionResult,
) -> tuple[MarketId, str, str, str]:
    return (
        deletion.market_id,
        deletion.kind,
        deletion.tool_key,
        deletion.object_id,
    )
