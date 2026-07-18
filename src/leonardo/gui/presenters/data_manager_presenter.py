"""Presenter for the canonical Data Manager catalog/manage workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

from leonardo.core.core_runner import TaskProgress, TaskResult
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerApplicationService,
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerFocusRequest,
    DataManagerMarketSnapshot,
    DataManagerPreview,
    DataManagerRecipeEntry,
)
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.gui.windows.data_manager_preview_dialog import DataManagerPreviewDialog
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


_MARKET_UNAVAILABLE_ERROR = "DataManagerMarketUnavailableError"


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
        self._wire()
        self.refresh()

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
        self._view.closing.connect(self.dispose)

    def _on_market_selected(self, market_id: object) -> None:
        if self._disposed or self._active_task_id is not None:
            return
        if not isinstance(market_id, MarketId):
            self._selected_artifact = None
            self._selected_recipe = None
            self._market_snapshot = None
            self._selected_market = None
            return
        self._begin_market_inspection(market_id)

    def _begin_market_inspection(self, market_id: MarketId) -> None:
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

    def _submit(self, operation: str, generation: int, submit, settle) -> None:
        if self._active_task_id is not None or self._disposed:
            return
        self._active_operation = operation
        self._view.set_busy(True, operation)
        task_ref: list[str] = []
        settled = [False]

        def on_progress(progress: TaskProgress) -> None:
            task_id = task_ref[0] if task_ref else progress.task_id
            if self._disposed or task_id != self._active_task_id:
                return
            self._view.set_status(progress.message)
            self._view.set_progress(progress.current, progress.total)

        def on_result(result: TaskResult) -> None:
            settled[0] = True
            task_id = task_ref[0] if task_ref else result.task_id
            if self._disposed or task_id != self._active_task_id:
                return
            if operation == "scan_catalog":
                current = generation == self._catalog_generation
            else:
                current = generation == self._market_generation
            self._active_task_id = None
            self._active_operation = None
            self._view.set_busy(False)
            self._view.set_progress(0, 1)
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
            self._apply_pending_focus()
            return
        task_ref.append(submission.task_id)
        if not settled[0]:
            self._active_task_id = submission.task_id

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


def _deletion_identity(
    deletion: DataManagerDeletionResult,
) -> tuple[MarketId, str, str, str]:
    return (
        deletion.market_id,
        deletion.kind,
        deletion.tool_key,
        deletion.object_id,
    )
