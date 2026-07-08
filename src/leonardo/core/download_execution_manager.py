"""Non-executing Download Execution Manager skeleton for Leonardo V2 Core."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.download_data_execution import (
    DownloadDataExecutionResult,
    DownloadDataExecutionStatus,
)
from leonardo.contracts.download_execution import (
    DownloadExecutionEstimate,
    DownloadExecutionPhase,
    DownloadExecutionPlan,
    DownloadExecutionProgress,
    DownloadExecutionSnapshot,
    DownloadPreflightLayer,
    DownloadPreflightLayerResult,
    DownloadPreflightLayerStatus,
    default_execution_progress,
)
from leonardo.contracts.download_provider_capabilities import (
    ProviderCapabilityStatus,
    ProviderDataKind,
)
from leonardo.contracts.downloads import (
    DownloadPreflight,
    DownloadRequest,
    DownloadTimeframeMode,
    DownloadWorkflowKind,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.download_capability_catalog import DownloadCapabilityCatalog
from leonardo.core.download_manager import DownloadManager
from leonardo.download_data.smoke_execution import (
    fixture_bybit_kline_transport,
    run_bybit_ohlcv_smoke_slice,
)


@dataclass(frozen=True)
class _CapabilityReadinessResult:
    layer: DownloadPreflightLayerResult
    blocked_reason: str | None


class DownloadExecutionManager:
    """
    Create retained download execution snapshots and explicit smoke runs.

    The manager owns planning/read-model state for future execution. It reads
    submitted request state from `DownloadManager`. Planning and readiness
    classification remain non-executing. The sandbox smoke method is a separate,
    explicit fixture-transport path that requires an injected sandbox root.
    """

    def __init__(
        self,
        download_manager: DownloadManager,
        audit_log: AuditLog | None = None,
        capability_catalog: DownloadCapabilityCatalog | None = None,
    ) -> None:
        if not isinstance(download_manager, DownloadManager):
            raise TypeError("download_manager must be a DownloadManager")
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog or None")
        if capability_catalog is not None and not isinstance(
            capability_catalog,
            DownloadCapabilityCatalog,
        ):
            raise TypeError(
                "capability_catalog must be a DownloadCapabilityCatalog or None"
            )
        self._download_manager = download_manager
        self._audit_log = audit_log
        self._capability_catalog = (
            capability_catalog
            if capability_catalog is not None
            else DownloadCapabilityCatalog()
        )
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

    def classify_readiness(self, plan_id: str) -> DownloadExecutionSnapshot:
        """
        Classify a retained planned snapshot as ready or blocked.

        The classifier inspects the current stored Download Manager request,
        structural preflight, provider capability facts, and item read models.
        It delegates phase mutation to `mark_ready` and `mark_blocked`, so audit
        behavior and immutable snapshot updates stay centralized.
        """

        snapshot = self._require_snapshot(plan_id)
        _validate_readiness_classification(snapshot)
        blocked_reason = _structural_readiness_blocker(
            snapshot,
            self._download_manager,
        )
        if blocked_reason is not None:
            return self.mark_blocked(plan_id, blocked_reason)

        capability_result = _capability_readiness_result(
            snapshot,
            self._download_manager,
            self._capability_catalog,
        )
        self._store_snapshot(
            _snapshot_with_preflight_layer(snapshot, capability_result.layer)
        )
        if capability_result.blocked_reason is not None:
            return self.mark_blocked(plan_id, capability_result.blocked_reason)

        item_blocked_reason = _item_readiness_blocker(
            self._require_snapshot(plan_id),
            self._download_manager,
        )
        if item_blocked_reason is not None:
            return self.mark_blocked(plan_id, item_blocked_reason)
        return self.mark_ready(plan_id)

    def mark_ready(self, plan_id: str) -> DownloadExecutionSnapshot:
        """
        Mark a retained planned execution snapshot as ready.

        This method is a non-executing lifecycle classification. It updates the
        retained immutable read model only; it does not create tasks, create
        operations, queue work, call adapters, or write outputs.
        """

        snapshot = self._require_snapshot(plan_id)
        reason = "Download execution plan is ready for future execution."
        return self._transition_planned_snapshot(
            snapshot,
            DownloadExecutionPhase.READY,
            reason=reason,
        )

    def mark_blocked(
        self,
        plan_id: str,
        reason: str,
    ) -> DownloadExecutionSnapshot:
        """
        Mark a retained planned execution snapshot as blocked.

        The reason is stored in read-model fields for Runtime Manager and audit
        visibility. The method does not execute downloads or create execution
        artifacts.
        """

        _validate_reason(reason)
        snapshot = self._require_snapshot(plan_id)
        return self._transition_planned_snapshot(
            snapshot,
            DownloadExecutionPhase.BLOCKED,
            reason=reason,
        )

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

    def run_sandbox_smoke(
        self,
        request_id: str,
        *,
        sandbox_root: str | Path,
        transport: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    ) -> DownloadDataExecutionResult:
        """
        Run the explicit offline Download Data smoke execution for one request.

        The method requires a submitted, readiness-classified request and an
        explicit sandbox root. It uses deterministic fixture transport by
        default and never selects the live Bybit HTTP transport.
        """

        _validate_request_id(request_id)
        request = self._download_manager.get_request(request_id)
        if request is None:
            raise KeyError(f"Download request is not submitted: {request_id}")

        snapshot = self.get_snapshot_for_request(request_id)
        if snapshot is None:
            raise ValueError("Download execution plan is required before smoke run")
        if snapshot.plan.phase is not DownloadExecutionPhase.READY:
            raise ValueError(
                "Download execution plan must be ready before sandbox smoke run"
            )

        _validate_smoke_request(request)
        active_transport = transport or fixture_bybit_kline_transport
        results = tuple(
            run_bybit_ohlcv_smoke_slice(
                sandbox_root=sandbox_root,
                transport=active_transport,
                exchange_id="bybit",
                market_type="spot",
                symbol=symbol,
                timeframe=timeframe,
                limit=_smoke_limit(request),
            )
            for symbol in request.symbols
            for timeframe in request.timeframes
        )
        return DownloadDataExecutionResult(
            workflow_id=f"download-data-sandbox-smoke-{request_id}",
            status=DownloadDataExecutionStatus.COMPLETED,
            targets=tuple(
                target for result in results for target in result.targets
            ),
            storage_results=tuple(
                storage_result
                for result in results
                for storage_result in result.storage_results
            ),
            progress_events=tuple(
                progress_event
                for result in results
                for progress_event in result.progress_events
            ),
            total_bars_downloaded=sum(
                result.total_bars_downloaded for result in results
            ),
            metadata={
                "source": "download_execution_manager",
                "request_id": request_id,
                "sandbox_root_ref": str(Path(sandbox_root).resolve(strict=False)),
                "transport": "fixture",
            },
        )

    def _require_snapshot(self, plan_id: str) -> DownloadExecutionSnapshot:
        _validate_plan_id(plan_id)
        snapshot = self.get_snapshot(plan_id)
        if snapshot is None:
            raise KeyError(f"Download execution plan is not retained: {plan_id}")
        return snapshot

    def _store_snapshot(self, snapshot: DownloadExecutionSnapshot) -> None:
        self._snapshot_by_plan_id[snapshot.plan.plan_id] = snapshot
        self._plan_id_by_request_id[snapshot.plan.request_id] = snapshot.plan.plan_id

    def _transition_planned_snapshot(
        self,
        snapshot: DownloadExecutionSnapshot,
        new_phase: DownloadExecutionPhase,
        *,
        reason: str,
    ) -> DownloadExecutionSnapshot:
        _validate_planned_transition(snapshot, new_phase)
        updated = _snapshot_with_phase(snapshot, new_phase, reason=reason)
        self._store_snapshot(updated)
        self._emit_phase_changed(snapshot, updated, reason)
        return updated

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

    def _emit_phase_changed(
        self,
        previous: DownloadExecutionSnapshot,
        updated: DownloadExecutionSnapshot,
        reason: str,
    ) -> None:
        if self._audit_log is None:
            return
        self._audit_log.emit(
            AuditEvent(
                event_type="download.execution.phase.changed",
                message="Download execution phase changed.",
                severity=AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                payload={
                    "plan_id": updated.plan.plan_id,
                    "request_id": updated.plan.request_id,
                    "old_phase": previous.plan.phase.value,
                    "new_phase": updated.plan.phase.value,
                    "reason": reason,
                },
            )
        )


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string")


def _validate_plan_id(plan_id: str) -> None:
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise ValueError("plan_id must be a non-empty string")


def _validate_reason(reason: str) -> None:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")


def _validate_smoke_request(request: DownloadRequest) -> None:
    if request.workflow_kind is not DownloadWorkflowKind.DOWNLOAD_DATA:
        raise ValueError("sandbox smoke supports Download Data workflow only")
    if request.source is None or request.source.strip().lower() != "bybit":
        raise ValueError("sandbox smoke supports bybit provider only")
    if request.market is None or request.market.strip().lower() != "spot":
        raise ValueError("sandbox smoke supports spot market only")
    if request.timeframe_mode is not DownloadTimeframeMode.EXPLICIT:
        raise ValueError("sandbox smoke requires explicit timeframe mode")
    if not request.symbols:
        raise ValueError("sandbox smoke requires at least one symbol")
    if not request.timeframes:
        raise ValueError("sandbox smoke requires at least one timeframe")


def _smoke_limit(request: DownloadRequest) -> int:
    value = dict(request.metadata).get("limit")
    if value is None:
        return 10
    if type(value) is not int or value < 1:
        raise ValueError("sandbox smoke limit must be a positive integer")
    return value


def _validate_planned_transition(
    snapshot: DownloadExecutionSnapshot,
    new_phase: DownloadExecutionPhase,
) -> None:
    if snapshot.plan.phase is DownloadExecutionPhase.PLANNED:
        return
    raise ValueError(
        "Download execution plan cannot transition from "
        f"{snapshot.plan.phase.value} to {new_phase.value}; only planned plans "
        "can transition in this phase."
    )


def _validate_readiness_classification(snapshot: DownloadExecutionSnapshot) -> None:
    if snapshot.plan.phase is DownloadExecutionPhase.PLANNED:
        return
    raise ValueError(
        "Download execution plan cannot be readiness-classified from "
        f"{snapshot.plan.phase.value}; only planned plans can be classified "
        "in this phase."
    )


def _structural_readiness_blocker(
    snapshot: DownloadExecutionSnapshot,
    download_manager: DownloadManager,
) -> str | None:
    request = download_manager.get_request(snapshot.plan.request_id)
    if request is None:
        return "Stored download request is unavailable."
    if request.request_id != snapshot.plan.request_id:
        return "Download request state is inconsistent."

    preflight = download_manager.get_preflight(snapshot.plan.request_id)
    if preflight is None:
        return "Stored structural preflight is unavailable."
    if preflight.request_id != snapshot.plan.request_id:
        return "Download request/preflight state is inconsistent."

    if request.workflow_kind is not DownloadWorkflowKind.DOWNLOAD_DATA:
        return f"Unsupported workflow kind: {request.workflow_kind.value}."
    if snapshot.plan.workflow_kind != request.workflow_kind.value:
        return "Download plan/request workflow state is inconsistent."

    if preflight.can_run is not True:
        return "Structural preflight failed."

    return None


def _capability_readiness_result(
    snapshot: DownloadExecutionSnapshot,
    download_manager: DownloadManager,
    capability_catalog: DownloadCapabilityCatalog,
) -> _CapabilityReadinessResult:
    request = download_manager.get_request(snapshot.plan.request_id)
    if request is None:
        return _blocked_capability("Stored download request is unavailable.")

    metadata: dict[str, object] = {
        "request_id": request.request_id,
        "provider": request.source,
        "market": request.market,
        "timeframe_mode": request.timeframe_mode.value,
    }

    if request.source is None:
        return _blocked_capability(
            "Download provider source is required for capability preflight.",
            metadata=metadata,
        )
    if request.market is None:
        return _blocked_capability(
            "Download market is required for capability preflight.",
            metadata=metadata,
        )

    provider = capability_catalog.get_provider(request.source)
    if provider is None:
        return _blocked_capability(
            f"Unknown provider: {request.source.strip().lower()}.",
            metadata=metadata,
        )
    metadata["provider"] = provider.provider
    if provider.status is not ProviderCapabilityStatus.SUPPORTED:
        return _blocked_capability(
            f"Provider is not supported: {provider.status.value}.",
            metadata=metadata,
        )

    market = capability_catalog.get_market(provider.provider, request.market)
    if market is None:
        return _blocked_capability(
            f"Unknown provider market: {request.market.strip().lower()}.",
            metadata=metadata,
        )
    metadata["market"] = market.market
    if market.status is not ProviderCapabilityStatus.SUPPORTED:
        return _blocked_capability(
            f"Provider market is not supported: {market.status.value}.",
            metadata=metadata,
        )
    if ProviderDataKind.OHLCV.value not in market.data_kinds:
        return _blocked_capability(
            "Provider market does not support OHLCV data.",
            metadata=metadata,
        )

    try:
        expansion = capability_catalog.expand_timeframes(
            provider.provider,
            market.market,
            request.timeframe_mode.value,
            request.timeframes,
        )
    except Exception as exc:
        return _failed_capability(
            f"Capability preflight failed: {type(exc).__name__}: {exc}",
            metadata=metadata,
        )

    metadata["expanded_timeframes"] = expansion.timeframes
    if expansion.issues:
        return _blocked_capability(expansion.issues[0], metadata=metadata)
    if not expansion.timeframes:
        return _blocked_capability(
            "No supported timeframes are declared.",
            metadata=metadata,
        )
    if request.timeframe_mode is not DownloadTimeframeMode.EXPLICIT:
        return _blocked_capability(
            "Timeframe expansion is supported by catalog but execution items "
            "are not materialized yet.",
            metadata=metadata,
        )

    provider_intervals: dict[str, str] = {}
    for timeframe in expansion.timeframes:
        provider_interval = capability_catalog.provider_interval_for_timeframe(
            provider.provider,
            market.market,
            timeframe,
        )
        if provider_interval is None:
            return _blocked_capability(
                f"Provider interval mapping is missing for timeframe: {timeframe}.",
                metadata=metadata,
            )
        provider_intervals[timeframe] = provider_interval

    metadata["provider_intervals"] = provider_intervals
    return _CapabilityReadinessResult(
        layer=DownloadPreflightLayerResult(
            layer=DownloadPreflightLayer.CAPABILITY,
            status=DownloadPreflightLayerStatus.PASSED,
            can_continue=True,
            issues=(),
            metadata=metadata,
        ),
        blocked_reason=None,
    )


def _blocked_capability(
    reason: str,
    *,
    metadata: dict[str, object] | None = None,
) -> _CapabilityReadinessResult:
    return _CapabilityReadinessResult(
        layer=DownloadPreflightLayerResult(
            layer=DownloadPreflightLayer.CAPABILITY,
            status=DownloadPreflightLayerStatus.BLOCKED,
            can_continue=False,
            issues=(reason,),
            metadata=metadata or {},
        ),
        blocked_reason=reason,
    )


def _failed_capability(
    reason: str,
    *,
    metadata: dict[str, object],
) -> _CapabilityReadinessResult:
    return _CapabilityReadinessResult(
        layer=DownloadPreflightLayerResult(
            layer=DownloadPreflightLayer.CAPABILITY,
            status=DownloadPreflightLayerStatus.FAILED,
            can_continue=False,
            issues=(reason,),
            metadata=metadata,
        ),
        blocked_reason=reason,
    )


def _item_readiness_blocker(
    snapshot: DownloadExecutionSnapshot,
    download_manager: DownloadManager,
) -> str | None:
    request = download_manager.get_request(snapshot.plan.request_id)
    if request is None:
        return "Stored download request is unavailable."
    if request.timeframe_mode is not DownloadTimeframeMode.EXPLICIT:
        return "Timeframe expansion is unresolved."

    item_ids = tuple(
        item.item_id for item in download_manager.list_items(request.request_id)
    )
    if not item_ids:
        return "Explicit timeframe mode has no stored items."
    if snapshot.plan.item_ids != item_ids:
        return "Download plan/item state is inconsistent."
    return None


def _snapshot_with_preflight_layer(
    snapshot: DownloadExecutionSnapshot,
    layer: DownloadPreflightLayerResult,
) -> DownloadExecutionSnapshot:
    layers: list[DownloadPreflightLayerResult] = []
    found_layer = False
    for existing in snapshot.preflight_layers:
        if existing.layer is layer.layer:
            layers.append(layer)
            found_layer = True
        else:
            layers.append(existing)
    if not found_layer:
        layers.append(layer)
    return DownloadExecutionSnapshot(
        plan=snapshot.plan,
        preflight_layers=tuple(layers),
        estimate=snapshot.estimate,
        progress=snapshot.progress,
        outputs=snapshot.outputs,
        errors=snapshot.errors,
        metadata=snapshot.metadata,
    )


def _snapshot_with_phase(
    snapshot: DownloadExecutionSnapshot,
    phase: DownloadExecutionPhase,
    *,
    reason: str,
) -> DownloadExecutionSnapshot:
    plan = _plan_with_phase(snapshot.plan, phase)
    progress = _progress_with_phase(snapshot.progress, plan.request_id, phase, reason)
    metadata = dict(snapshot.metadata)
    metadata["lifecycle_reason"] = reason
    if phase is DownloadExecutionPhase.BLOCKED:
        metadata["blocked_reason"] = reason
    return DownloadExecutionSnapshot(
        plan=plan,
        preflight_layers=snapshot.preflight_layers,
        estimate=snapshot.estimate,
        progress=progress,
        outputs=snapshot.outputs,
        errors=snapshot.errors,
        metadata=metadata,
    )


def _plan_with_phase(
    plan: DownloadExecutionPlan,
    phase: DownloadExecutionPhase,
) -> DownloadExecutionPlan:
    return DownloadExecutionPlan(
        plan_id=plan.plan_id,
        request_id=plan.request_id,
        workflow_kind=plan.workflow_kind,
        phase=phase,
        operation_id=plan.operation_id,
        task_id=plan.task_id,
        connection_refs=plan.connection_refs,
        adapter_ref=plan.adapter_ref,
        storage_policy_ref=plan.storage_policy_ref,
        dataset_refs=plan.dataset_refs,
        item_ids=plan.item_ids,
        created_at_utc=plan.created_at_utc,
        metadata=plan.metadata,
    )


def _progress_with_phase(
    progress: DownloadExecutionProgress | None,
    request_id: str,
    phase: DownloadExecutionPhase,
    message: str,
) -> DownloadExecutionProgress:
    base = progress if progress is not None else default_execution_progress(request_id)
    return DownloadExecutionProgress(
        request_id=base.request_id,
        phase=phase,
        total_items=base.total_items,
        completed_items=base.completed_items,
        failed_items=base.failed_items,
        skipped_items=base.skipped_items,
        running_items=base.running_items,
        current_item_id=base.current_item_id,
        current_symbol=base.current_symbol,
        current_timeframe=base.current_timeframe,
        rows_downloaded=base.rows_downloaded,
        candles_downloaded=base.candles_downloaded,
        pages_fetched=base.pages_fetched,
        percent=base.percent,
        message=message,
        updated_at_utc=base.updated_at_utc,
        metadata=base.metadata,
    )


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
