"""Canonical Research Workspace Snapshot to Notebook linkage authority."""

from __future__ import annotations

from threading import RLock

from leonardo.research.notebook import ResearchNotebookSummary
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotV1
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore


class ResearchWorkspaceNotebookLinkError(RuntimeError):
    """Raised when coordinated Workspace Snapshot and Notebook mutation fails."""


class ResearchWorkspaceNotebookLinkService:
    """Own the durable relationship between Workspace Snapshots and Notebooks."""

    def __init__(
        self,
        snapshot_store: ResearchWorkspaceSnapshotStore,
        notebook_service: ResearchNotebookService,
    ) -> None:
        if not isinstance(snapshot_store, ResearchWorkspaceSnapshotStore):
            raise TypeError("snapshot_store must be ResearchWorkspaceSnapshotStore")
        if not isinstance(notebook_service, ResearchNotebookService):
            raise TypeError("notebook_service must be ResearchNotebookService")
        self._snapshot_store = snapshot_store
        self._notebook_service = notebook_service
        self._lock = RLock()

    def assign_notebook(
        self,
        snapshot_id: str,
        notebook_id: str,
    ) -> ResearchWorkspaceSnapshotV1:
        with self._lock:
            self._notebook_service.load_notebook(notebook_id)
            snapshot = self._snapshot_store.load(snapshot_id)
            if snapshot.notebook_id == notebook_id:
                return snapshot
            return self._snapshot_store.replace_notebook_id(
                snapshot.snapshot_id,
                notebook_id,
            )

    def unassign_notebook(
        self,
        snapshot_id: str,
        notebook_id: str,
    ) -> ResearchWorkspaceSnapshotV1:
        with self._lock:
            snapshot = self._snapshot_store.load(snapshot_id)
            if snapshot.notebook_id != notebook_id:
                raise ResearchWorkspaceNotebookLinkError(
                    "Workspace Snapshot notebook assignment is stale or mismatched"
                )
            return self._snapshot_store.replace_notebook_id(
                snapshot.snapshot_id,
                None,
            )

    def validate_notebook_reference(
        self,
        notebook_id: str | None,
    ) -> tuple[str, ...]:
        if notebook_id is None:
            return ()
        with self._lock:
            try:
                self._notebook_service.load_notebook(notebook_id)
            except Exception:
                return (f"assigned notebook is unavailable: {notebook_id}",)
        return ()

    def delete_notebook_with_reference_cleanup(
        self,
        notebook_id: str,
    ) -> ResearchNotebookSummary:
        with self._lock:
            self._notebook_service.load_notebook(notebook_id)
            originals = tuple(
                self._snapshot_store.load(summary.snapshot_id)
                for summary in self._snapshot_store.list_summaries()
                if summary.valid and summary.notebook_id == notebook_id
            )
            cleared: list[ResearchWorkspaceSnapshotV1] = []
            try:
                for snapshot in originals:
                    self._snapshot_store.replace_notebook_id(
                        snapshot.snapshot_id,
                        None,
                    )
                    cleared.append(snapshot)
            except Exception as cleanup_error:
                rollback_errors = self._restore_references(cleared)
                detail = self._failure_detail(cleanup_error, rollback_errors)
                raise ResearchWorkspaceNotebookLinkError(
                    f"Notebook reference cleanup failed: {detail}"
                ) from cleanup_error

            try:
                return self._notebook_service.delete_notebook(notebook_id)
            except Exception as deletion_error:
                rollback_errors = self._restore_references(cleared)
                if not rollback_errors:
                    raise
                detail = self._failure_detail(deletion_error, rollback_errors)
                raise ResearchWorkspaceNotebookLinkError(
                    f"Notebook deletion and reference rollback failed: {detail}"
                ) from deletion_error

    def _restore_references(
        self,
        cleared: list[ResearchWorkspaceSnapshotV1],
    ) -> tuple[Exception, ...]:
        errors: list[Exception] = []
        for snapshot in reversed(cleared):
            try:
                self._snapshot_store.replace_notebook_id(
                    snapshot.snapshot_id,
                    snapshot.notebook_id,
                )
            except Exception as error:
                errors.append(error)
        return tuple(errors)

    @staticmethod
    def _failure_detail(
        primary: Exception,
        rollback_errors: tuple[Exception, ...],
    ) -> str:
        detail = f"{type(primary).__name__}: {primary}"
        if rollback_errors:
            rollback = "; ".join(
                f"{type(error).__name__}: {error}"
                for error in rollback_errors
            )
            detail += f"; rollback failures: {rollback}"
        return detail
