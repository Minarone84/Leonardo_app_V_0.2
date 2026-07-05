"""Non-executing Download Execution Manager skeleton for Leonardo V2 Core."""

from __future__ import annotations

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.download_execution import (
    DownloadExecutionEstimate,
    DownloadExecutionPhase,
    DownloadExecutionPlan,
    DownloadExecutionSnapshot,
    DownloadPreflightLayer,
    DownloadPreflightLayerResult,
    DownloadPreflightLayerStatus,
    default_execution_progress,
)
from leonardo.contracts.downloads import DownloadPreflight, DownloadRequest
from leonardo.core.audit_log import AuditLog
from leonardo.core.download_manager import DownloadManager


class DownloadExecutionManager:
    """
    Create and retain non-executing download execution snapshots.

    The manager owns planning/read-model state for future execution. It reads
    submitted request state from `DownloadManager`, but it does not fetch data,
    resolve adapters, create operations, create tasks, launch processes, update
    Runtime Manager views, write output files, or own GUI behavior.
    """

    def __init__(
        self,
        download_manager: DownloadManager,
        audit_log: AuditLog | None = None,
    ) -> None:
        if not isinstance(download_manager, DownloadManager):
            raise TypeError("download_manager must be a DownloadManager")
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog or None")
        self._download_manager = download_manager
        self._audit_log = audit_log
        self._snapshot_by_plan_id: dict[str, DownloadExecutionSnapshot] = {}
        self._plan_id_by_request_id: dict[str, str] = {}

    def create_plan(self, request_id: str) -> DownloadExecutionSnapshot:
        """
        Create or return a planned execution snapshot for a submitted request.

        The method is idempotent per request identifier. It does not submit,
        preview, execute, enqueue, or mutate Download Manager state.
        """

        _validate_request_id(request_id)
        existing = self.get_snapshot_for_request(request_id)
        if existing is not None:
            return existing

        request = self._download_manager.get_request(request_id)
        if request is None:
            raise KeyError(f"Download request is not submitted: {request_id}")

        preflight = self._download_manager.get_preflight(request_id)
        items = self._download_manager.list_items(request_id)
        item_ids = tuple(item.item_id for item in items)
        plan_id = _plan_id_for_request(request_id)

        plan = DownloadExecutionPlan(
            plan_id=plan_id,
            request_id=request.request_id,
            workflow_kind=request.workflow_kind.value,
            phase=DownloadExecutionPhase.PLANNED,
            connection_refs=_connection_refs(request, preflight),
            item_ids=item_ids,
            metadata=_plan_metadata(request, preflight),
        )
        snapshot = DownloadExecutionSnapshot(
            plan=plan,
            preflight_layers=(_structural_layer(preflight),),
            estimate=_estimate_for(request, preflight, item_count=len(item_ids)),
            progress=default_execution_progress(request.request_id),
            metadata={"source": "download_execution_manager"},
        )
        self._snapshot_by_plan_id[plan.plan_id] = snapshot
        self._plan_id_by_request_id[request.request_id] = plan.plan_id
        self._emit_plan_created(snapshot)
        return snapshot

    def get_snapshot(self, plan_id: str) -> DownloadExecutionSnapshot | None:
        """Return a retained execution snapshot by plan identifier, if present."""

        return self._snapshot_by_plan_id.get(plan_id)

    def get_snapshot_for_request(
        self,
        request_id: str,
    ) -> DownloadExecutionSnapshot | None:
        """Return a retained execution snapshot for a request, if present."""

        plan_id = self._plan_id_by_request_id.get(request_id)
        if plan_id is None:
            return None
        return self._snapshot_by_plan_id.get(plan_id)

    def list_snapshots(self) -> tuple[DownloadExecutionSnapshot, ...]:
        """Return retained snapshots in deterministic plan identifier order."""

        return tuple(
            self._snapshot_by_plan_id[plan_id]
            for plan_id in sorted(self._snapshot_by_plan_id)
        )

    def _emit_plan_created(self, snapshot: DownloadExecutionSnapshot) -> None:
        if self._audit_log is None:
            return
        self._audit_log.emit(
            AuditEvent(
                event_type="download.execution.plan.created",
                message="Download execution plan created.",
                severity=AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                payload={
                    "plan_id": snapshot.plan.plan_id,
                    "request_id": snapshot.plan.request_id,
                    "phase": snapshot.plan.phase.value,
                    "item_ids": snapshot.plan.item_ids,
                },
            )
        )


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string")


def _plan_id_for_request(request_id: str) -> str:
    return f"execution-plan-{request_id}"


def _connection_refs(
    request: DownloadRequest,
    preflight: DownloadPreflight | None,
) -> tuple[str, ...]:
    if preflight is not None:
        return preflight.required_connections
    if request.connection_ref is not None:
        return (request.connection_ref,)
    return ()


def _structural_layer(
    preflight: DownloadPreflight | None,
) -> DownloadPreflightLayerResult:
    if preflight is None:
        return DownloadPreflightLayerResult(
            layer=DownloadPreflightLayer.STRUCTURAL,
            status=DownloadPreflightLayerStatus.NOT_RUN,
            can_continue=False,
            issues=("Stored structural preflight is unavailable.",),
        )
    if preflight.can_run:
        return DownloadPreflightLayerResult(
            layer=DownloadPreflightLayer.STRUCTURAL,
            status=DownloadPreflightLayerStatus.PASSED,
            can_continue=True,
            issues=(),
            metadata={"request_id": preflight.request_id},
        )
    return DownloadPreflightLayerResult(
        layer=DownloadPreflightLayer.STRUCTURAL,
        status=DownloadPreflightLayerStatus.FAILED,
        can_continue=False,
        issues=tuple(issue.message for issue in preflight.issues),
        metadata={
            "request_id": preflight.request_id,
            "issue_codes": tuple(issue.code for issue in preflight.issues),
        },
    )


def _estimate_for(
    request: DownloadRequest,
    preflight: DownloadPreflight | None,
    *,
    item_count: int,
) -> DownloadExecutionEstimate:
    estimated_items = item_count if item_count else None
    if estimated_items is None and preflight is not None:
        estimated_items = preflight.estimated_items
    return DownloadExecutionEstimate(
        request_id=request.request_id,
        estimated_items=estimated_items,
        metadata={
            "source": "download_execution_manager",
            "timeframe_mode": request.timeframe_mode.value,
            "range_mode": request.range_mode.value,
        },
    )


def _plan_metadata(
    request: DownloadRequest,
    preflight: DownloadPreflight | None,
) -> dict[str, object]:
    return {
        "source": request.source,
        "market": request.market,
        "workflow_kind": request.workflow_kind.value,
        "timeframe_mode": request.timeframe_mode.value,
        "range_mode": request.range_mode.value,
        "preflight_status": preflight.status.value if preflight is not None else None,
        "preflight_can_run": preflight.can_run if preflight is not None else None,
    }
