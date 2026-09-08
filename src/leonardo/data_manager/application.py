"""Core-supervised application service for Data Manager operations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Event, RLock
from uuid import uuid4

from leonardo.core.core_runner import (
    CallbackDispatcher,
    CoreRunner,
    ProgressCallback,
    ProgressReporter,
    ResultCallback,
    TaskResult,
    TaskSubmission,
)
from leonardo.data import MarketId

from .models import (
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationRequest,
    DataManagerArtifactMaterializationResult,
    DuplicateMaintenanceDomain,
    DuplicateMaintenancePreflight,
    DuplicateMaintenancePurgeResult,
    DuplicateMaintenanceScanResult,
    duplicate_maintenance_domain,
)
from .direct_artifact import (
    DataManagerDirectArtifactRequest,
)
from .creation_models import (
    ArtifactCollectionOutputV1,
    ArtifactCollectionSelectionPlan,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DatabaseContentAdditionPlan,
    DatabaseSeedCreationPlan,
    SeedOnlyDatabaseCreationPlan,
)
from .service import DataManagerService
from .update_models import ArtifactCollectionUpdatePlan, DatabaseUpdatePlan


class _CancellationGate:
    def __init__(self) -> None:
        self._cancelled = Event()
        self._destructive_started = False
        self._lock = RLock()

    def request_cancel(self) -> bool:
        with self._lock:
            if self._destructive_started:
                return False
            self._cancelled.set()
            return True

    def begin_destructive(self) -> None:
        with self._lock:
            if self._cancelled.is_set():
                raise RuntimeError("Data Manager operation cancelled before publication")
            self._destructive_started = True

    def raise_if_cancelled(self, stage: str) -> None:
        if self._cancelled.is_set():
            raise RuntimeError(f"Data Manager operation cancelled before {stage}")

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class DataManagerApplicationService:
    """Run one Data Manager operation through the shared CoreRunner."""

    def __init__(self, core_runner: CoreRunner, service: DataManagerService) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be a CoreRunner")
        if not isinstance(service, DataManagerService):
            raise TypeError("service must be a DataManagerService")
        self._runner = core_runner
        self._service = service
        self._cancellations: dict[str, _CancellationGate] = {}
        self._lock = RLock()

    def submit_scan_catalog(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_catalog",
            task_name="Data Manager catalog scan",
            start_message="Scanning canonical dataset catalog",
            completed_message="Data Manager catalog ready",
            work=lambda _reporter, _gate: self._service.scan_catalog(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_inspect_market(
        self,
        market_id: MarketId,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.inspect_market",
            task_name=f"Data Manager market inspection {market_id.as_key()}",
            start_message=f"Inspecting {market_id.as_key()}",
            completed_message="Market inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_market(market_id),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_preview_dataset(
        self,
        market_id: MarketId,
        limit: int = 200,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        def work(reporter: ProgressReporter, gate: _CancellationGate):
            def on_progress(current: int, total: int) -> None:
                if not gate.is_cancelled():
                    reporter.report(
                        f"Loading dataset preview {current}/{total}",
                        current=current,
                        total=total,
                    )

            return self._service._preview_dataset(
                market_id,
                limit=limit,
                progress=on_progress,
                cancellation_requested=gate.is_cancelled,
            )

        return self._market_submit(
            market_id,
            operation="data_manager.preview_dataset",
            task_name=f"Data Manager dataset preview {market_id.as_key()}",
            start_message=f"Preparing dataset preview for {market_id.as_key()}",
            completed_message="Dataset preview ready",
            work=work,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_preview_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        limit: int = 200,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.preview_artifact",
            task_name=f"Data Manager artifact preview {artifact_id}",
            start_message=f"Preparing artifact preview {artifact_id}",
            completed_message="Artifact preview ready",
            work=lambda _reporter, _gate: self._service.preview_artifact(
                market_id, kind, tool_key, artifact_id, limit=limit
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_validate_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.validate_artifact",
            task_name=f"Data Manager artifact validation {artifact_id}",
            start_message=f"Validating artifact {artifact_id}",
            completed_message="Artifact validation ready",
            work=lambda _reporter, _gate: self._service.validate_artifact_current(
                market_id, kind, tool_key, artifact_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_delete_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.delete_artifact",
            task_name=f"Data Manager artifact deletion {artifact_id}",
            start_message=f"Deleting exact artifact {artifact_id}",
            completed_message="Artifact deleted",
            work=lambda _reporter, gate: self._service._delete_artifact(
                market_id,
                kind,
                tool_key,
                artifact_id,
                before_delete=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_delete_recipe(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        recipe_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.delete_recipe",
            task_name=f"Data Manager recipe deletion {recipe_id}",
            start_message=f"Deleting exact recipe {recipe_id}",
            completed_message="Recipe deleted",
            work=lambda _reporter, gate: self._service._delete_recipe(
                market_id,
                kind,
                tool_key,
                recipe_id,
                before_delete=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_delete_portable_recipe(
        self,
        recipe_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.delete_portable_recipe",
            task_name=f"Data Manager portable Recipe deletion {recipe_id}",
            start_message=f"Proving portable Recipe {recipe_id} is unreferenced",
            completed_message="Portable Recipe deleted",
            work=lambda _reporter, gate: self._service._delete_portable_recipe(
                recipe_id, before_delete=gate.begin_destructive
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"recipe_id": recipe_id},
        )

    def submit_delete_recipe_collection(
        self,
        collection_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.delete_recipe_collection",
            task_name=f"Data Manager Recipe Collection deletion {collection_id}",
            start_message=f"Proving Recipe Collection {collection_id} is unreferenced",
            completed_message="Recipe Collection deleted",
            work=lambda _reporter, gate: self._service._delete_recipe_collection(
                collection_id, before_delete=gate.begin_destructive
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_delete_managed_artifact(
        self,
        market_id: MarketId,
        logical_artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.delete_managed_artifact",
            task_name=f"Data Manager managed Artifact deletion {logical_artifact_id}",
            start_message=f"Proving managed Artifact {logical_artifact_id} is unreferenced",
            completed_message="Managed Artifact deleted",
            work=lambda _reporter, gate: self._service._delete_managed_artifact(
                market_id,
                logical_artifact_id,
                before_delete=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"logical_artifact_id": logical_artifact_id},
        )

    def submit_delete_artifact_collection(
        self,
        collection_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.delete_artifact_collection",
            task_name=f"Data Manager Artifact Collection deletion {collection_id}",
            start_message=f"Proving Artifact Collection {collection_id} is unreferenced",
            completed_message="Artifact Collection deleted",
            work=lambda _reporter, gate: self._service._delete_artifact_collection(
                collection_id, before_delete=gate.begin_destructive
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_scan_study_environments(
        self,
        *,
        exchange: str | None = None,
        market_type: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        display_name_text: str | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_study_environments",
            task_name="Data Manager Study Environment scan",
            start_message="Scanning global Study Environments",
            completed_message="Study Environment catalog ready",
            work=lambda _reporter, _gate: self._service.scan_study_environments(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframe=timeframe,
                display_name_text=display_name_text,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_inspect_study_environment(
        self,
        environment_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.inspect_study_environment",
            task_name=f"Data Manager Study Environment inspection {environment_id}",
            start_message=f"Inspecting Study Environment {environment_id}",
            completed_message="Study Environment inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_study_environment(
                environment_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"environment_id": environment_id},
        )

    def submit_plan_recipe_derivation(
        self,
        environment_id: str,
        root_entry_ids: tuple[str, ...],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_recipe_derivation",
            task_name=f"Data Manager Recipe derivation plan {environment_id}",
            start_message=f"Planning portable Recipes from {environment_id}",
            completed_message="Portable Recipe derivation plan ready",
            work=lambda _reporter, _gate: self._service.plan_recipe_derivation(
                environment_id, root_entry_ids
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"environment_id": environment_id},
        )

    def submit_persist_recipe_derivation(
        self,
        environment_id: str,
        root_entry_ids: tuple[str, ...],
        *,
        create_collection: bool,
        collection_display_name: str = "",
        collection_description: str = "",
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.persist_recipe_derivation",
            task_name=f"Data Manager Recipe derivation persistence {environment_id}",
            start_message=f"Persisting portable Recipes from {environment_id}",
            completed_message="Portable Recipe derivation persisted",
            work=lambda _reporter, gate: self._service._persist_recipe_derivation(
                environment_id,
                root_entry_ids,
                create_collection=create_collection,
                collection_display_name=collection_display_name,
                collection_description=collection_description,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"environment_id": environment_id},
        )

    def submit_scan_portable_recipes(
        self,
        *,
        origin_exchange: str | None = None,
        origin_market_type: str | None = None,
        origin_symbol: str | None = None,
        origin_timeframe: str | None = None,
        tool_key: str | None = None,
        display_name_text: str | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_portable_recipes",
            task_name="Data Manager portable Recipe scan",
            start_message="Scanning global portable Recipe Library",
            completed_message="Portable Recipe Library ready",
            work=lambda _reporter, _gate: self._service.scan_portable_recipes(
                origin_exchange=origin_exchange,
                origin_market_type=origin_market_type,
                origin_symbol=origin_symbol,
                origin_timeframe=origin_timeframe,
                tool_key=tool_key,
                display_name_text=display_name_text,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_inspect_portable_recipe(
        self,
        recipe_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.inspect_portable_recipe",
            task_name=f"Data Manager portable Recipe inspection {recipe_id}",
            start_message=f"Inspecting portable Recipe {recipe_id}",
            completed_message="Portable Recipe inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_portable_recipe(
                recipe_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"recipe_id": recipe_id},
        )

    def submit_create_recipe_collection(
        self,
        display_name: str,
        description: str,
        root_recipe_ids: tuple[str, ...],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.create_recipe_collection",
            task_name="Data Manager Recipe Collection creation",
            start_message="Creating portable Recipe Collection",
            completed_message="Portable Recipe Collection created",
            work=lambda _reporter, gate: self._service._create_recipe_collection(
                display_name,
                description,
                root_recipe_ids,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_plan_recipe_collection(
        self,
        root_recipe_ids: tuple[str, ...],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_recipe_collection",
            task_name="Data Manager Recipe Collection planning",
            start_message="Planning portable Recipe Collection",
            completed_message="Portable Recipe Collection plan ready",
            work=lambda _reporter, _gate: self._service.plan_recipe_collection(
                root_recipe_ids
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_find_equivalent_recipe_collection(
        self,
        root_recipe_ids: tuple[str, ...],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.find_equivalent_recipe_collection",
            task_name="Data Manager Recipe Collection reuse lookup",
            start_message="Checking Recipe Collection reuse",
            completed_message="Recipe Collection reuse lookup ready",
            work=lambda _reporter, _gate: (
                self._service.find_equivalent_recipe_collection(root_recipe_ids)
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_update_recipe_collection(
        self,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: tuple[str, ...],
        *,
        expected_revision_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.update_recipe_collection",
            task_name=f"Data Manager Recipe Collection update {collection_id}",
            start_message=f"Updating portable Recipe Collection {collection_id}",
            completed_message="Portable Recipe Collection updated",
            work=lambda _reporter, gate: self._service._update_recipe_collection(
                collection_id,
                display_name,
                description,
                root_recipe_ids,
                before_publish=gate.begin_destructive,
                expected_revision_id=expected_revision_id,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_list_recipe_collections(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_recipe_collections",
            task_name="Data Manager Recipe Collection scan",
            start_message="Scanning portable Recipe Collections",
            completed_message="Portable Recipe Collections ready",
            work=lambda _reporter, _gate: self._service.list_recipe_collections(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_inspect_recipe_collection(
        self,
        collection_id: str,
        revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.inspect_recipe_collection",
            task_name=f"Data Manager Recipe Collection inspection {collection_id}",
            start_message=f"Inspecting portable Recipe Collection {collection_id}",
            completed_message="Portable Recipe Collection inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_recipe_collection(
                collection_id, revision_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={
                "collection_id": collection_id,
                "revision_id": revision_id,
            },
        )

    def submit_list_recipe_collection_revisions(
        self,
        collection_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_recipe_collection_revisions",
            task_name=f"Data Manager Recipe Collection history {collection_id}",
            start_message=f"Listing Recipe Collection revisions {collection_id}",
            completed_message="Recipe Collection history ready",
            work=lambda _reporter, _gate: self._service.list_recipe_collection_revisions(
                collection_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_plan_artifact_materialization(
        self,
        request: DataManagerArtifactMaterializationRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            request.target_market_id,
            operation="data_manager.plan_artifact_materialization",
            task_name="Data Manager Artifact materialization plan",
            start_message="Planning managed Artifact materialization",
            completed_message="Managed Artifact materialization plan ready",
            work=lambda _reporter, _gate: self._service.plan_artifact_materialization(
                request
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_build_direct_artifact_catalog(
        self,
        market_id: MarketId,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.build_direct_artifact_catalog",
            task_name="Data Manager direct Artifact source catalog",
            start_message="Building direct Artifact source catalog",
            completed_message="Direct Artifact source catalog ready",
            work=lambda _reporter, _gate: self._service.build_direct_artifact_catalog(
                market_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_create_direct_artifact(
        self,
        request: DataManagerDirectArtifactRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(request, DataManagerDirectArtifactRequest):
            raise TypeError("request must be a DataManagerDirectArtifactRequest")

        def create(reporter: ProgressReporter, gate: _CancellationGate):
            return self._service._create_direct_artifact(
                request,
                progress=lambda current, total, message: reporter.report(
                    message, current=current, total=total
                ),
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            )

        return self._market_submit(
            request.market_id,
            operation="data_manager.create_direct_artifact",
            task_name="Data Manager direct Artifact creation",
            start_message="Creating direct managed Artifact",
            completed_message="Direct managed Artifact creation complete",
            work=create,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_execute_artifact_materialization(
        self,
        plan: DataManagerArtifactMaterializationPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        def execute(reporter: ProgressReporter, gate: _CancellationGate):
            return self._service._execute_artifact_materialization(
                plan,
                progress=lambda current, total, message: reporter.report(
                    message, current=current, total=total
                ),
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            )

        return self._market_submit(
            plan.target_market_id,
            operation="data_manager.execute_artifact_materialization",
            task_name=f"Data Manager Artifact materialization {plan.plan_id}",
            start_message="Executing managed Artifact materialization",
            completed_message="Managed Artifact materialization complete",
            work=execute,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"plan_id": plan.plan_id},
        )

    def submit_inspect_managed_artifact(
        self,
        market_id: MarketId,
        logical_artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.inspect_managed_artifact",
            task_name=f"Data Manager managed Artifact inspection {logical_artifact_id}",
            start_message=f"Inspecting managed Artifact {logical_artifact_id}",
            completed_message="Managed Artifact inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_managed_artifact(
                market_id, logical_artifact_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"logical_artifact_id": logical_artifact_id},
        )

    def submit_scan_managed_artifacts(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_managed_artifacts",
            task_name="Data Manager managed Artifact scan",
            start_message="Scanning managed Artifact heads",
            completed_message="Managed Artifact catalog ready",
            work=lambda _reporter, _gate: self._service.scan_managed_artifacts(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_scan_product_catalogs(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_product_catalogs",
            task_name="Data Manager product catalog scan",
            start_message="Scanning Data Manager product catalogs",
            completed_message="Data Manager product catalogs ready",
            work=lambda _reporter, _gate: self._service.scan_product_catalogs(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_prepare_duplicate_maintenance(
        self,
        domain: DuplicateMaintenanceDomain | str,
        market_id: MarketId | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        exact_domain = duplicate_maintenance_domain(domain)
        return self._submit(
            operation="data_manager.duplicate_maintenance_preflight",
            task_name=(
                f"Data Manager {exact_domain.display_name} duplicate maintenance "
                "preflight"
            ),
            start_message=(
                f"Preparing {exact_domain.display_name} duplicate maintenance"
            ),
            completed_message="Duplicate maintenance preflight ready",
            work=lambda _reporter, _gate: self._service.prepare_duplicate_maintenance(
                exact_domain, market_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"domain": exact_domain.key},
        )

    def submit_scan_duplicate_maintenance(
        self,
        preflight: DuplicateMaintenancePreflight,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(preflight, DuplicateMaintenancePreflight):
            raise TypeError("preflight must be a DuplicateMaintenancePreflight")

        def scan(reporter: ProgressReporter, gate: _CancellationGate):
            return self._service.scan_duplicate_maintenance(
                preflight,
                progress=lambda current, total, message: reporter.report(
                    message, current=current, total=total
                ),
                cancellation_requested=gate.is_cancelled,
            )

        return self._submit(
            operation="data_manager.duplicate_maintenance_scan",
            task_name=(
                f"Data Manager {preflight.domain.display_name} duplicate "
                "maintenance scan"
            ),
            start_message=(
                f"Scanning {preflight.domain.display_name} duplicate candidates"
            ),
            completed_message="Duplicate maintenance scan complete",
            work=scan,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"domain": preflight.domain.key},
        )

    def submit_purge_duplicate_maintenance(
        self,
        scan: DuplicateMaintenanceScanResult,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(scan, DuplicateMaintenanceScanResult):
            raise TypeError("scan must be a DuplicateMaintenanceScanResult")

        def purge(
            reporter: ProgressReporter, gate: _CancellationGate
        ) -> DuplicateMaintenancePurgeResult:
            return self._service.purge_duplicate_maintenance(
                scan,
                progress=lambda current, total, message: reporter.report(
                    message, current=current, total=total
                ),
                cancellation_requested=gate.is_cancelled,
                before_delete=gate.begin_destructive,
            )

        return self._submit(
            operation="data_manager.duplicate_maintenance_purge",
            task_name=(
                f"Data Manager {scan.preflight.domain.display_name} duplicate purge"
            ),
            start_message=(
                f"Purging {scan.preflight.domain.display_name} safe duplicates"
            ),
            completed_message="Duplicate maintenance purge complete",
            work=purge,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"domain": scan.preflight.domain.key},
        )

    def submit_list_managed_artifact_versions(
        self,
        market_id: MarketId,
        logical_artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.list_managed_artifact_versions",
            task_name=f"Data Manager managed Artifact versions {logical_artifact_id}",
            start_message=f"Listing managed Artifact versions {logical_artifact_id}",
            completed_message="Managed Artifact versions ready",
            work=lambda _reporter, _gate: self._service.list_managed_artifact_versions(
                market_id, logical_artifact_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"logical_artifact_id": logical_artifact_id},
        )

    def submit_create_database_seed(
        self,
        market_id: MarketId,
        display_name: str,
        *,
        description: str = "",
        selected_ohlcv_columns: tuple[str, ...] = (
            "open", "high", "low", "close", "volume"
        ),
        selected_range_start_ms: int | None = None,
        selected_range_end_ms: int | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        def work(_reporter, gate):
            plan = self._service.plan_database_seed_creation(
                market_id,
                display_name,
                description=description,
                selected_ohlcv_columns=selected_ohlcv_columns,
                selected_range_start_ms=selected_range_start_ms,
                selected_range_end_ms=selected_range_end_ms,
            )
            return self._service.execute_database_seed_creation(
                plan,
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            )

        return self._market_submit(
            market_id,
            operation="data_manager.create_database_seed",
            task_name=f"Data Manager Database Seed {display_name}",
            start_message="Creating Database Seed",
            completed_message="Database Seed created",
            work=work,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_plan_database_seed_creation(
        self,
        market_id: MarketId,
        display_name: str,
        *,
        description: str = "",
        selected_ohlcv_columns: tuple[str, ...] = (
            "open", "high", "low", "close", "volume"
        ),
        selected_range_start_ms: int | None = None,
        selected_range_end_ms: int | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.plan_database_seed_creation",
            task_name=f"Data Manager Database Seed preview {display_name}",
            start_message="Planning Database Seed",
            completed_message="Database Seed preview ready",
            work=lambda _reporter, _gate: self._service.plan_database_seed_creation(
                market_id,
                display_name,
                description=description,
                selected_ohlcv_columns=selected_ohlcv_columns,
                selected_range_start_ms=selected_range_start_ms,
                selected_range_end_ms=selected_range_end_ms,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_execute_database_seed_creation(
        self,
        plan: DatabaseSeedCreationPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            plan.seed.market_id,
            operation="data_manager.execute_database_seed_creation",
            task_name=f"Data Manager Database Seed creation {plan.seed.display_name}",
            start_message="Publishing Database Seed",
            completed_message="Database Seed created",
            work=lambda _reporter, gate: self._service.execute_database_seed_creation(
                plan,
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"plan_id": plan.plan_id, "seed_id": plan.seed.seed_id},
        )

    def submit_plan_seed_only_database_creation(
        self,
        seed_id: str,
        display_name: str,
        *,
        description: str = "",
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_seed_only_database_creation",
            task_name=f"Data Manager Seed-only Database preview {display_name}",
            start_message="Planning Seed-only Database",
            completed_message="Seed-only Database preview ready",
            work=lambda _reporter, _gate: (
                self._service.plan_seed_only_database_creation(
                    seed_id, display_name, description=description
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id},
        )

    def submit_execute_seed_only_database_creation(
        self,
        plan: SeedOnlyDatabaseCreationPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.execute_seed_only_database_creation",
            task_name=f"Data Manager Seed-only Database creation {plan.display_name}",
            start_message="Publishing Seed-only Database",
            completed_message="Seed-only Database created",
            work=lambda _reporter, gate: (
                self._service.execute_seed_only_database_creation(
                    plan,
                    cancellation_requested=gate.is_cancelled,
                    before_publish=gate.begin_destructive,
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"plan_id": plan.plan_id, "seed_id": plan.seed_id},
        )

    def submit_list_database_seeds(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_database_seeds",
            task_name="Data Manager Database Seed scan",
            start_message="Scanning Database Seeds",
            completed_message="Database Seeds ready",
            work=lambda _reporter, _gate: self._service.list_database_seeds(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_load_database_seed(
        self,
        seed_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.load_database_seed",
            task_name=f"Data Manager Database Seed load {seed_id}",
            start_message=f"Loading Database Seed {seed_id}",
            completed_message="Database Seed loaded",
            work=lambda _reporter, _gate: self._service.load_database_seed(seed_id),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id},
        )

    def submit_inspect_database_seed(
        self,
        seed_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.inspect_database_seed",
            task_name=f"Data Manager Database Seed inspection {seed_id}",
            start_message=f"Inspecting Database Seed {seed_id}",
            completed_message="Database Seed inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_database_seed(seed_id),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id},
        )

    def submit_validate_database_seed(
        self,
        seed_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.validate_database_seed",
            task_name=f"Data Manager Database Seed validation {seed_id}",
            start_message=f"Validating Database Seed {seed_id}",
            completed_message="Database Seed validation ready",
            work=lambda _reporter, _gate: self._service.validate_database_seed(seed_id),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id},
        )

    def submit_delete_database_seed(
        self,
        seed_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.delete_database_seed",
            task_name=f"Data Manager Database Seed deletion {seed_id}",
            start_message=f"Deleting Database Seed {seed_id}",
            completed_message="Database Seed deleted",
            work=lambda _reporter, gate: (
                gate.begin_destructive(),
                self._service.delete_database_seed(seed_id),
            )[1],
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id},
        )

    def submit_scan_creation_foundations(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_creation_foundations",
            task_name="Data Manager creation foundation scan",
            start_message="Scanning creation workflow foundations",
            completed_message="Creation workflow foundations ready",
            work=lambda _reporter, _gate: self._service.scan_creation_foundations(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_create_artifact_collection(
        self,
        materialization: DataManagerArtifactMaterializationResult,
        display_name: str,
        *,
        description: str = "",
        source_recipe_collection_id: str | None = None,
        source_recipe_collection_revision_id: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            materialization.target_market_id,
            operation="data_manager.create_artifact_collection",
            task_name=f"Data Manager Artifact Collection {display_name}",
            start_message="Creating Artifact Collection",
            completed_message="Artifact Collection created",
            work=lambda _reporter, gate: (
                gate.begin_destructive(),
                self._service.create_artifact_collection(
                    materialization,
                    display_name,
                    description=description,
                    source_recipe_collection_id=source_recipe_collection_id,
                    source_recipe_collection_revision_id=(
                        source_recipe_collection_revision_id
                    ),
                    selected_outputs=selected_outputs,
                ),
            )[1],
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_plan_artifact_collection_selection(
        self,
        market_id: MarketId,
        root_logical_artifact_ids: Sequence[str],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.plan_artifact_collection_selection",
            task_name="Data Manager Artifact Collection selection planning",
            start_message="Planning Artifact Collection selection",
            completed_message="Artifact Collection selection plan ready",
            work=lambda _reporter, _gate: (
                self._service.plan_artifact_collection_selection(
                    market_id, root_logical_artifact_ids
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_find_equivalent_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
        presentation_order: Sequence[str],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            plan.market_id,
            operation="data_manager.find_equivalent_artifact_collection",
            task_name="Data Manager Artifact Collection reuse lookup",
            start_message="Checking Artifact Collection reuse",
            completed_message="Artifact Collection reuse lookup ready",
            work=lambda _reporter, _gate: (
                self._service.find_equivalent_artifact_collection_from_selection(
                    plan, selected_outputs, presentation_order
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_find_equivalent_artifact_collection_for_materialization(
        self,
        plan: DataManagerArtifactMaterializationPlan,
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            plan.target_market_id,
            operation="data_manager.find_equivalent_materialized_collection",
            task_name="Data Manager materialized Collection reuse lookup",
            start_message="Checking materialized Artifact Collection reuse",
            completed_message="Materialized Artifact Collection reuse lookup ready",
            work=lambda _reporter, _gate: (
                self._service.find_equivalent_artifact_collection_for_materialization(
                    plan, selected_outputs
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_create_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        display_name: str,
        *,
        description: str = "",
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            plan.market_id,
            operation="data_manager.create_artifact_collection_from_selection",
            task_name=f"Data Manager Artifact Collection {display_name}",
            start_message="Creating Artifact Collection from selection",
            completed_message="Artifact Collection created",
            work=lambda _reporter, gate: (
                self._service._create_artifact_collection_from_selection(
                    plan,
                    display_name,
                    description=description,
                    selected_outputs=selected_outputs,
                    before_publish=gate.begin_destructive,
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_edit_artifact_collection_from_selection(
        self,
        collection_id: str,
        plan: ArtifactCollectionSelectionPlan,
        *,
        display_name: str | None = None,
        description: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        presentation_order: Sequence[str] | None = None,
        expected_revision_id: str,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            plan.market_id,
            operation="data_manager.edit_artifact_collection_from_selection",
            task_name=f"Data Manager Artifact Collection edit {collection_id}",
            start_message=f"Editing Artifact Collection {collection_id}",
            completed_message="Artifact Collection edited",
            work=lambda _reporter, gate: (
                self._service._edit_artifact_collection_from_selection(
                    collection_id,
                    plan,
                    display_name=display_name,
                    description=description,
                    selected_outputs=selected_outputs,
                    presentation_order=presentation_order,
                    expected_revision_id=expected_revision_id,
                    before_publish=gate.begin_destructive,
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_list_artifact_collection_revisions(
        self,
        collection_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_artifact_collection_revisions",
            task_name=f"Data Manager Artifact Collection revisions {collection_id}",
            start_message=f"Listing Artifact Collection revisions {collection_id}",
            completed_message="Artifact Collection revisions ready",
            work=lambda _reporter, _gate: (
                self._service.list_artifact_collection_revisions(collection_id)
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_load_artifact_collection(
        self,
        collection_id: str,
        revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.load_artifact_collection",
            task_name=f"Data Manager Artifact Collection load {collection_id}",
            start_message=f"Loading Artifact Collection {collection_id}",
            completed_message="Artifact Collection loaded",
            work=lambda _reporter, _gate: self._service.load_artifact_collection(
                collection_id, revision_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id, "revision_id": revision_id},
        )

    def submit_inspect_artifact_collection(
        self,
        collection_id: str,
        revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.inspect_artifact_collection",
            task_name=f"Data Manager Artifact Collection inspection {collection_id}",
            start_message=f"Inspecting Artifact Collection {collection_id}",
            completed_message="Artifact Collection inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_artifact_collection(
                collection_id, revision_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id, "revision_id": revision_id},
        )

    def submit_inspect_artifact_collection_details(
        self,
        collection_id: str,
        revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.inspect_artifact_collection_details",
            task_name=(
                "Data Manager Artifact Collection detail inspection "
                f"{collection_id}"
            ),
            start_message=f"Inspecting Artifact Collection details {collection_id}",
            completed_message="Artifact Collection detail inspection ready",
            work=lambda _reporter, _gate: (
                self._service.inspect_artifact_collection_details(
                    collection_id, revision_id
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id, "revision_id": revision_id},
        )

    def submit_validate_artifact_collection(
        self,
        collection_id: str,
        revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.validate_artifact_collection",
            task_name=f"Data Manager Artifact Collection validation {collection_id}",
            start_message=f"Validating Artifact Collection {collection_id}",
            completed_message="Artifact Collection validation ready",
            work=lambda _reporter, _gate: self._service.validate_artifact_collection(
                collection_id, revision_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id, "revision_id": revision_id},
        )

    def submit_revise_artifact_collection(
        self,
        collection_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        presentation_order: Sequence[str] | None = None,
        remove_root_logical_artifact_ids: Sequence[str] = (),
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.revise_artifact_collection",
            task_name=f"Data Manager Artifact Collection revision {collection_id}",
            start_message=f"Revising Artifact Collection {collection_id}",
            completed_message="Artifact Collection revised",
            work=lambda _reporter, gate: (
                gate.begin_destructive(),
                self._service.revise_artifact_collection(
                    collection_id,
                    display_name=display_name,
                    description=description,
                    selected_outputs=selected_outputs,
                    presentation_order=presentation_order,
                    remove_root_logical_artifact_ids=(
                        remove_root_logical_artifact_ids
                    ),
                ),
            )[1],
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_add_artifact_collection_branches(
        self,
        collection_id: str,
        materialization: DataManagerArtifactMaterializationResult,
        *,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            materialization.target_market_id,
            operation="data_manager.add_artifact_collection_branches",
            task_name=f"Data Manager Artifact Collection branch add {collection_id}",
            start_message=f"Adding Artifact branches to Collection {collection_id}",
            completed_message="Artifact Collection branches added",
            work=lambda _reporter, gate: (
                gate.begin_destructive(),
                self._service.add_artifact_collection_branches(
                    collection_id,
                    materialization,
                    selected_outputs=selected_outputs,
                ),
            )[1],
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_list_artifact_collections(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_artifact_collections",
            task_name="Data Manager Artifact Collection scan",
            start_message="Scanning Artifact Collections",
            completed_message="Artifact Collections ready",
            work=lambda _reporter, _gate: self._service.list_artifact_collections(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_plan_batch_artifacts(
        self,
        request: BatchArtifactRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            request.market_id,
            operation="data_manager.plan_batch_artifacts",
            task_name="Data Manager batch Artifact plan",
            start_message="Planning explicit batch Artifact branches",
            completed_message="Batch Artifact plan ready",
            work=lambda _reporter, _gate: self._service.plan_batch_artifacts(request),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_execute_batch_artifacts(
        self,
        plan: BatchArtifactPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        def execute(reporter: ProgressReporter, gate: _CancellationGate):
            return self._service.execute_batch_artifacts(
                plan,
                cancellation_requested=gate.is_cancelled,
                progress=lambda current, total, message: reporter.report(
                    message, current=current, total=total
                ),
            )

        return self._market_submit(
            plan.request.market_id,
            operation="data_manager.execute_batch_artifacts",
            task_name="Data Manager batch Artifact execution",
            start_message="Executing explicit batch Artifact branches",
            completed_message="Batch Artifact execution complete",
            work=execute,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_assess_database_readiness(
        self,
        seed_id: str,
        collection_id: str,
        collection_revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.assess_database_readiness",
            task_name="Data Manager Database readiness",
            start_message="Validating Database readiness",
            completed_message="Database readiness ready",
            work=lambda _reporter, _gate: self._service.assess_database_readiness(
                seed_id, collection_id, collection_revision_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id, "collection_id": collection_id},
        )

    def submit_build_database_revision(
        self,
        seed_id: str,
        collection_id: str,
        *,
        collection_revision_id: str | None = None,
        database_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.build_database_revision",
            task_name="Data Manager Database build",
            start_message="Materializing immutable Database revision",
            completed_message="Database revision published",
            work=lambda _reporter, gate: self._service.build_database_revision(
                seed_id,
                collection_id,
                collection_revision_id=collection_revision_id,
                database_id=database_id,
                display_name=display_name,
                description=description,
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"seed_id": seed_id, "collection_id": collection_id},
        )

    def submit_plan_database_artifact_addition(
        self,
        database_id: str,
        root_logical_artifact_ids: Sequence[str],
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_database_artifact_addition",
            task_name=f"Data Manager Database Artifact Preview {database_id}",
            start_message="Planning Database Artifact content",
            completed_message="Database Artifact content Preview ready",
            work=lambda _reporter, _gate: (
                self._service.plan_database_artifact_addition(
                    database_id, root_logical_artifact_ids
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": database_id},
        )

    def submit_plan_database_collection_addition(
        self,
        database_id: str,
        collection_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_database_collection_addition",
            task_name=f"Data Manager Database Collection Preview {database_id}",
            start_message="Planning Database Artifact Collection content",
            completed_message="Database Collection content Preview ready",
            work=lambda _reporter, _gate: (
                self._service.plan_database_collection_addition(
                    database_id, collection_id
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={
                "database_id": database_id,
                "collection_id": collection_id,
            },
        )

    def submit_execute_database_content_addition(
        self,
        plan: DatabaseContentAdditionPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        if not isinstance(plan, DatabaseContentAdditionPlan):
            raise TypeError("plan must be a DatabaseContentAdditionPlan")
        return self._market_submit(
            plan.market_id,
            operation="data_manager.execute_database_content_addition",
            task_name=f"Data Manager Database content addition {plan.database_id}",
            start_message="Publishing immutable Database content revision",
            completed_message="Database content revision published",
            work=lambda _reporter, gate: (
                self._service.execute_database_content_addition(
                    plan,
                    cancellation_requested=gate.is_cancelled,
                    before_publish=gate.begin_destructive,
                )
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={
                "database_id": plan.database_id,
                "plan_id": plan.plan_id,
            },
        )

    def submit_list_databases(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_databases",
            task_name="Data Manager Database scan",
            start_message="Scanning Databases",
            completed_message="Databases ready",
            work=lambda _reporter, _gate: self._service.list_database_ids(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_load_database_definition(
        self,
        database_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.load_database_definition",
            task_name=f"Data Manager Database definition load {database_id}",
            start_message=f"Loading Database definition {database_id}",
            completed_message="Database definition loaded",
            work=lambda _reporter, _gate: self._service.load_database_definition(
                database_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": database_id},
        )

    def submit_list_database_revisions(
        self,
        database_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.list_database_revisions",
            task_name=f"Data Manager Database revisions {database_id}",
            start_message=f"Listing Database revisions {database_id}",
            completed_message="Database revisions ready",
            work=lambda _reporter, _gate: self._service.list_database_revisions(
                database_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": database_id},
        )

    def submit_load_database_revision(
        self,
        database_id: str,
        revision_id: str | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.load_database_revision",
            task_name=f"Data Manager Database revision load {database_id}",
            start_message=f"Loading Database revision {database_id}",
            completed_message="Database revision loaded",
            work=lambda _reporter, _gate: self._service.load_database_revision(
                database_id, revision_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": database_id, "revision_id": revision_id},
        )

    def submit_reconcile_status(
        self,
        *,
        force: bool = False,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.reconcile_status",
            task_name="Data Manager reconciliation",
            start_message="Reconciling canonical Data Manager evidence",
            completed_message="Data Manager reconciliation ready",
            work=lambda _reporter, gate: self._service.reconcile_update_status(
                force=force,
                cancellation_requested=gate.is_cancelled,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_plan_artifact_collection_update(
        self,
        collection_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_artifact_collection_update",
            task_name=f"Data Manager Artifact Collection update plan {collection_id}",
            start_message=f"Planning Artifact Collection update {collection_id}",
            completed_message="Artifact Collection update plan ready",
            work=lambda _reporter, _gate: self._service.plan_artifact_collection_update(
                collection_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": collection_id},
        )

    def submit_execute_artifact_collection_update(
        self,
        plan: ArtifactCollectionUpdatePlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.execute_artifact_collection_update",
            task_name=f"Data Manager Artifact Collection update {plan.collection_id}",
            start_message=f"Updating Artifact Collection {plan.collection_id}",
            completed_message="Artifact Collection update completed",
            work=lambda _reporter, gate: self._service.execute_artifact_collection_update(
                plan,
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"collection_id": plan.collection_id, "plan_id": plan.plan_id},
        )

    def submit_plan_database_update(
        self,
        database_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.plan_database_update",
            task_name=f"Data Manager Database update plan {database_id}",
            start_message=f"Planning Database update {database_id}",
            completed_message="Database update plan ready",
            work=lambda _reporter, _gate: self._service.plan_database_update(database_id),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": database_id},
        )

    def submit_execute_database_append(
        self,
        plan: DatabaseUpdatePlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.execute_database_append",
            task_name=f"Data Manager Database append {plan.database_id}",
            start_message=f"Appending Database {plan.database_id}",
            completed_message="Database append completed",
            work=lambda _reporter, gate: self._service.execute_database_append(
                plan,
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": plan.database_id, "plan_id": plan.plan_id},
        )

    def submit_execute_database_rebuild(
        self,
        plan: DatabaseUpdatePlan,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.execute_database_rebuild",
            task_name=f"Data Manager Database rebuild {plan.database_id}",
            start_message=f"Rebuilding Database {plan.database_id}",
            completed_message="Database rebuild completed",
            work=lambda _reporter, gate: self._service.execute_database_rebuild(
                plan,
                cancellation_requested=gate.is_cancelled,
                before_publish=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"database_id": plan.database_id, "plan_id": plan.plan_id},
        )

    def latest_reconciliation_snapshot(self):
        return self._service.latest_update_status()

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            gate = self._cancellations.get(task_id)
        if gate is None or not gate.request_cancel():
            return False
        return self._runner.cancel(task_id)

    def cancel_all_pending(self) -> tuple[str, ...]:
        with self._lock:
            pending = tuple(self._cancellations.items())
        accepted: list[str] = []
        for task_id, gate in pending:
            if gate.request_cancel() and self._runner.cancel(task_id):
                accepted.append(task_id)
        return tuple(accepted)

    def _market_submit(self, market_id: MarketId, **values) -> TaskSubmission:
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        metadata = dict(values.pop("metadata", {}))
        metadata["market_id"] = market_id.as_key()
        return self._submit(metadata=metadata, **values)

    def _submit(
        self,
        *,
        operation: str,
        task_name: str,
        start_message: str,
        completed_message: str,
        work: Callable[[ProgressReporter, _CancellationGate], object],
        progress_callback: ProgressCallback | None,
        result_callback: ResultCallback | None,
        callback_dispatcher: CallbackDispatcher | None,
        destructive: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> TaskSubmission:
        gate = _CancellationGate()
        finished = Event()
        task_ref: list[str] = []

        def job(reporter: ProgressReporter):
            gate.raise_if_cancelled("execution")
            reporter.report(start_message, current=0, total=None)
            if destructive:
                gate.begin_destructive()
            value = work(reporter, gate)
            if not destructive:
                gate.raise_if_cancelled("publication")
            reporter.report(completed_message, current=1, total=1)
            return value

        def on_result(result: TaskResult) -> None:
            finished.set()
            task_id = task_ref[0] if task_ref else result.task_id
            with self._lock:
                self._cancellations.pop(task_id, None)
            if result_callback is not None:
                result_callback(result)

        submission = self._runner.submit_blocking_job(
            job,
            task_name=task_name,
            progress_callback=progress_callback,
            result_callback=on_result,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=True,
            correlation_id=uuid4().hex,
            metadata={"operation": operation, **dict(metadata or {})},
        )
        task_ref.append(submission.task_id)
        with self._lock:
            if not finished.is_set():
                self._cancellations[submission.task_id] = gate
        return submission
