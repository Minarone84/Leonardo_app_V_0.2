"""In-memory Download Manager state service for Leonardo V2 Core."""

from __future__ import annotations

from collections import Counter

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.downloads import (
    DownloadPreflight,
    DownloadRequest,
    DownloadRequestItem,
    DownloadStatus,
    DownloadSummary,
    DownloadTimeframeMode,
    DownloadValidationIssue,
    DownloadValidationSeverity,
)
from leonardo.core.audit_log import AuditLog


_ACTIVE_STATUSES = frozenset(
    {
        DownloadStatus.REQUESTED,
        DownloadStatus.VALIDATED,
        DownloadStatus.QUEUED,
        DownloadStatus.RUNNING,
    }
)


class DownloadManager:
    """
    Own in-memory Download Manager request and read-model state.

    The manager records download intent, structural preflight results, and
    deterministic item read models. It does not execute downloads, resolve
    adapters, open connections, launch processes, persist files, or own GUI
    behavior.
    """

    def __init__(self, audit_log: AuditLog | None = None) -> None:
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog or None")
        self._audit_log = audit_log
        self._request_by_id: dict[str, DownloadRequest] = {}
        self._preflight_by_request_id: dict[str, DownloadPreflight] = {}
        self._item_by_id: dict[str, DownloadRequestItem] = {}

    def submit_request(self, request: DownloadRequest) -> DownloadPreflight:
        """
        Store a download request and create a structural preflight read model.

        Duplicate request identifiers are rejected before state mutation. Invalid
        structural requests are retained with a failed preflight for auditability
        and read-model visibility.
        """

        if not isinstance(request, DownloadRequest):
            raise TypeError("request must be a DownloadRequest")
        if not isinstance(request.request_id, str) or not request.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if request.request_id in self._request_by_id:
            raise ValueError(f"Download request already submitted: {request.request_id}")

        issues = self._validate_request_structure(request)
        can_run = not issues
        preflight = DownloadPreflight(
            request_id=request.request_id,
            status=DownloadStatus.VALIDATED if can_run else DownloadStatus.FAILED,
            can_run=can_run,
            required_connections=self._required_connections(request),
            websocket_required=request.websocket_required,
            websocket_available=None,
            estimated_items=self._estimated_items(request, can_run=can_run),
            estimated_symbols=len(request.symbols),
            estimated_timeframes=self._estimated_timeframes(request),
            issues=issues,
            metadata=self._preflight_metadata(request),
        )

        self._request_by_id[request.request_id] = request
        self._preflight_by_request_id[request.request_id] = preflight
        if can_run:
            for item in self._expand_items(request):
                self._item_by_id[item.item_id] = item

        self._emit_request_submitted(request)
        self._emit_preflight_completed(request, preflight)
        return preflight

    def get_request(self, request_id: str) -> DownloadRequest | None:
        """Return a stored request by identifier, if present."""

        return self._request_by_id.get(request_id)

    def list_requests(self) -> tuple[DownloadRequest, ...]:
        """Return stored requests in deterministic request identifier order."""

        return tuple(
            self._request_by_id[request_id]
            for request_id in sorted(self._request_by_id)
        )

    def get_preflight(self, request_id: str) -> DownloadPreflight | None:
        """Return a stored preflight by request identifier, if present."""

        return self._preflight_by_request_id.get(request_id)

    def list_preflights(self) -> tuple[DownloadPreflight, ...]:
        """Return stored preflights in deterministic request identifier order."""

        return tuple(
            self._preflight_by_request_id[request_id]
            for request_id in sorted(self._preflight_by_request_id)
        )

    def list_items(self, request_id: str | None = None) -> tuple[DownloadRequestItem, ...]:
        """Return generated item read models, optionally scoped to one request."""

        items = sorted(self._item_by_id.values(), key=lambda item: item.item_id)
        if request_id is None:
            return tuple(items)
        return tuple(item for item in items if item.request_id == request_id)

    def get_summary(self) -> DownloadSummary:
        """Return an aggregate summary built from current in-memory read models."""

        status_counts: Counter[DownloadStatus] = Counter(
            preflight.status for preflight in self._preflight_by_request_id.values()
        )
        status_counts.update(item.status for item in self._item_by_id.values())

        active_request_ids = tuple(
            request_id
            for request_id, preflight in sorted(self._preflight_by_request_id.items())
            if preflight.status in _ACTIVE_STATUSES
        )
        queued_request_ids = tuple(
            request_id
            for request_id, preflight in sorted(self._preflight_by_request_id.items())
            if preflight.status is DownloadStatus.QUEUED
        )
        failed_request_ids = tuple(
            request_id
            for request_id, preflight in sorted(self._preflight_by_request_id.items())
            if preflight.status is DownloadStatus.FAILED
        )
        active_item_ids = tuple(
            item.item_id
            for item in sorted(self._item_by_id.values(), key=lambda value: value.item_id)
            if item.status in _ACTIVE_STATUSES
        )
        failed_item_ids = tuple(
            item.item_id
            for item in sorted(self._item_by_id.values(), key=lambda value: value.item_id)
            if item.status is DownloadStatus.FAILED
        )

        return DownloadSummary(
            total_requests=len(self._request_by_id),
            total_items=len(self._item_by_id),
            requested_count=status_counts[DownloadStatus.REQUESTED],
            validated_count=status_counts[DownloadStatus.VALIDATED],
            queued_count=status_counts[DownloadStatus.QUEUED],
            running_count=status_counts[DownloadStatus.RUNNING],
            completed_count=status_counts[DownloadStatus.COMPLETED],
            failed_count=status_counts[DownloadStatus.FAILED],
            cancelled_count=status_counts[DownloadStatus.CANCELLED],
            skipped_count=status_counts[DownloadStatus.SKIPPED],
            partially_completed_count=status_counts[
                DownloadStatus.PARTIALLY_COMPLETED
            ],
            active_request_ids=active_request_ids,
            queued_request_ids=queued_request_ids,
            failed_request_ids=failed_request_ids,
            active_item_ids=active_item_ids,
            failed_item_ids=failed_item_ids,
            websocket_required_count=sum(
                1
                for preflight in self._preflight_by_request_id.values()
                if preflight.websocket_required
            ),
            connection_blocked_count=sum(
                1
                for preflight in self._preflight_by_request_id.values()
                if preflight.missing_connections
            ),
            preflight_failed_count=sum(
                1
                for preflight in self._preflight_by_request_id.values()
                if preflight.status is DownloadStatus.FAILED or not preflight.can_run
            ),
            metadata={"source": "download_manager"},
        )

    def _validate_request_structure(
        self,
        request: DownloadRequest,
    ) -> tuple[DownloadValidationIssue, ...]:
        issues: list[DownloadValidationIssue] = []
        if not request.symbols:
            issues.append(
                DownloadValidationIssue(
                    code="missing_symbols",
                    severity=DownloadValidationSeverity.ERROR,
                    message="At least one symbol is required.",
                    field="symbols",
                )
            )
        if (
            request.timeframe_mode is DownloadTimeframeMode.EXPLICIT
            and not request.timeframes
        ):
            issues.append(
                DownloadValidationIssue(
                    code="missing_timeframes",
                    severity=DownloadValidationSeverity.ERROR,
                    message="Explicit timeframe mode requires at least one timeframe.",
                    field="timeframes",
                )
            )
        return tuple(issues)

    def _expand_items(self, request: DownloadRequest) -> tuple[DownloadRequestItem, ...]:
        if request.timeframe_mode is not DownloadTimeframeMode.EXPLICIT:
            return ()

        items: list[DownloadRequestItem] = []
        for symbol in request.symbols:
            for timeframe in request.timeframes:
                item_id = f"{request.request_id}:{symbol}:{timeframe}"
                items.append(
                    DownloadRequestItem(
                        item_id=item_id,
                        request_id=request.request_id,
                        workflow_kind=request.workflow_kind,
                        symbol=symbol,
                        timeframe=timeframe,
                        status=DownloadStatus.VALIDATED,
                        source=request.source,
                        market=request.market,
                        connection_id=request.connection_ref,
                        metadata={
                            "request_id": request.request_id,
                            "batch_id": request.batch_id,
                            "source": request.source,
                            "market": request.market,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "workflow_kind": request.workflow_kind.value,
                            "timeframe_mode": request.timeframe_mode.value,
                            "range_mode": request.range_mode.value,
                            "connection_ref": request.connection_ref,
                            "websocket_required": request.websocket_required,
                        },
                    )
                )
        return tuple(items)

    def _emit_request_submitted(self, request: DownloadRequest) -> None:
        if self._audit_log is None:
            return
        self._audit_log.emit(
            AuditEvent(
                event_type="download.request.submitted",
                message="Download request submitted.",
                severity=AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                actor_id=request.requested_by,
                connection_id=request.connection_ref,
                correlation_id=request.correlation_id,
                payload={
                    "request_id": request.request_id,
                    "workflow_kind": request.workflow_kind.value,
                    "symbols": request.symbols,
                    "timeframe_mode": request.timeframe_mode.value,
                    "timeframes": request.timeframes,
                    "range_mode": request.range_mode.value,
                },
            )
        )

    def _emit_preflight_completed(
        self,
        request: DownloadRequest,
        preflight: DownloadPreflight,
    ) -> None:
        if self._audit_log is None:
            return
        self._audit_log.emit(
            AuditEvent(
                event_type="download.preflight.completed",
                message="Download preflight completed.",
                severity=AuditSeverity.INFO
                if preflight.can_run
                else AuditSeverity.WARNING,
                category=AuditCategory.RUNTIME,
                actor_id=request.requested_by,
                connection_id=request.connection_ref,
                correlation_id=request.correlation_id,
                payload={
                    "request_id": request.request_id,
                    "status": preflight.status.value,
                    "can_run": preflight.can_run,
                    "issue_codes": tuple(issue.code for issue in preflight.issues),
                },
            )
        )

    @staticmethod
    def _required_connections(request: DownloadRequest) -> tuple[str, ...]:
        if request.connection_ref is None:
            return ()
        return (request.connection_ref,)

    @staticmethod
    def _estimated_items(
        request: DownloadRequest,
        *,
        can_run: bool,
    ) -> int | None:
        if not can_run:
            return 0
        if request.timeframe_mode is DownloadTimeframeMode.EXPLICIT:
            return len(request.symbols) * len(request.timeframes)
        return None

    @staticmethod
    def _estimated_timeframes(request: DownloadRequest) -> int | None:
        if request.timeframe_mode is DownloadTimeframeMode.EXPLICIT:
            return len(request.timeframes)
        return None

    @staticmethod
    def _preflight_metadata(request: DownloadRequest) -> dict[str, object]:
        return {
            "workflow_kind": request.workflow_kind.value,
            "timeframe_mode": request.timeframe_mode.value,
            "range_mode": request.range_mode.value,
            "source": request.source,
            "market": request.market,
            "connection_ref": request.connection_ref,
        }
