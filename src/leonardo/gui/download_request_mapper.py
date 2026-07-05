"""Map GUI-local download drafts to Download Manager contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from leonardo.contracts.downloads import (
    DownloadConflictPolicy,
    DownloadPreflight,
    DownloadPriority,
    DownloadRangeMode,
    DownloadRequest,
    DownloadTimeframeMode,
    DownloadValidationIssue,
    DownloadWorkflowKind,
)


@dataclass(frozen=True)
class DownloadPreflightPreviewView:
    """
    GUI-safe read model for displaying a Core preflight preview.

    The view carries serializable values only. It does not expose Core services
    or mutable Download Manager state to widgets.
    """

    request_id: str
    status: str
    can_run: bool
    estimated_symbols: int | None
    estimated_timeframes: int | None
    estimated_items: int | None
    required_connections: tuple[str, ...]
    websocket_required: bool
    issues: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class DownloadSubmitResultView:
    """
    GUI-safe read model for displaying a submit intent result.

    The view reports whether Core accepted the request into Download Manager
    runtime state. It does not expose Core services, task execution, adapter
    handles, or persistence behavior to widgets.
    """

    request_id: str
    accepted: bool
    status: str
    can_run: bool
    item_count: int
    estimated_items: int | None
    issues: tuple[str, ...]
    message: str
    runtime_visible: bool
    execution_plan_id: str | None = None
    execution_plan_created: bool = False
    execution_plan_message: str = "Execution plan was not created."


class DownloadRequestDraftLike(Protocol):
    """Attribute contract consumed from GUI-local download request drafts."""

    workflow_mode: str
    source_provider: str
    market: str
    symbols: tuple[str, ...]
    timeframe_mode: str
    timeframes: tuple[str, ...]
    range_mode: str
    start: str
    end: str
    conflict_policy: str
    priority: str
    connection_ref: str
    websocket_required: bool
    tags: tuple[str, ...]
    metadata: Mapping[str, object]


def build_download_request_from_draft(
    draft: DownloadRequestDraftLike,
) -> DownloadRequest:
    """
    Convert a GUI-local download draft into a Core download request contract.

    The generated request identifier is preview-scoped and deterministic for
    normalized draft content. It is not a final submit identifier.
    """

    payload = _normalized_payload(draft)
    return _build_download_request(payload, request_id=_preview_request_id(payload))


def build_download_request_for_submit(
    draft: DownloadRequestDraftLike,
) -> DownloadRequest:
    """
    Convert a GUI-local draft into a submit-scoped download request contract.

    The generated request identifier is deterministic for normalized draft
    content and uses the submit-specific ``request-`` prefix. It does not reuse
    preview identifiers.
    """

    payload = _normalized_payload(draft)
    return _build_download_request(payload, request_id=_submit_id(payload))


def _build_download_request(
    payload: Mapping[str, object],
    *,
    request_id: str,
) -> DownloadRequest:
    return DownloadRequest(
        request_id=request_id,
        workflow_kind=DownloadWorkflowKind(payload["workflow_kind"]),
        source=payload["source"],
        market=payload["market"],
        symbols=tuple(payload["symbols"]),
        timeframe_mode=DownloadTimeframeMode(payload["timeframe_mode"]),
        timeframes=tuple(payload["timeframes"]),
        range_mode=DownloadRangeMode(payload["range_mode"]),
        start=payload["start"],
        end=payload["end"],
        conflict_policy=DownloadConflictPolicy(payload["conflict_policy"]),
        priority=DownloadPriority(payload["priority"]),
        connection_ref=payload["connection_ref"],
        websocket_required=bool(payload["websocket_required"]),
        tags=tuple(payload["tags"]),
        metadata=payload["metadata"],
    )


def build_preflight_preview_view(
    preflight: DownloadPreflight,
) -> DownloadPreflightPreviewView:
    """Convert a Core preflight contract into a GUI-safe display view."""

    if not isinstance(preflight, DownloadPreflight):
        raise TypeError("preflight must be a DownloadPreflight")
    return DownloadPreflightPreviewView(
        request_id=preflight.request_id,
        status=preflight.status.value,
        can_run=preflight.can_run,
        estimated_symbols=preflight.estimated_symbols,
        estimated_timeframes=preflight.estimated_timeframes,
        estimated_items=preflight.estimated_items,
        required_connections=preflight.required_connections,
        websocket_required=preflight.websocket_required,
        issues=tuple(_format_issue(issue) for issue in preflight.issues),
        message=(
            "Preflight preview passed."
            if preflight.can_run
            else "Preflight preview blocked."
        ),
    )


def build_submit_result_view(
    request: DownloadRequest,
    preflight: DownloadPreflight,
    *,
    item_count: int,
    accepted: bool = True,
    execution_plan_id: str | None = None,
    execution_plan_created: bool = False,
    execution_plan_message: str = "Execution plan was not created.",
) -> DownloadSubmitResultView:
    """Convert a Core submit result into a GUI-safe display view."""

    if not isinstance(request, DownloadRequest):
        raise TypeError("request must be a DownloadRequest")
    if not isinstance(preflight, DownloadPreflight):
        raise TypeError("preflight must be a DownloadPreflight")
    if type(item_count) is not int or item_count < 0:
        raise ValueError("item_count must be a non-negative integer")
    return DownloadSubmitResultView(
        request_id=request.request_id,
        accepted=accepted,
        status=preflight.status.value,
        can_run=preflight.can_run,
        item_count=item_count,
        estimated_items=preflight.estimated_items,
        issues=tuple(_format_issue(issue) for issue in preflight.issues),
        message=(
            "Download request submitted."
            if accepted
            else "Download request rejected."
        ),
        runtime_visible=accepted,
        execution_plan_id=execution_plan_id,
        execution_plan_created=execution_plan_created,
        execution_plan_message=execution_plan_message,
    )


def build_submit_error_view(
    request_id: str,
    message: str,
    issues: tuple[str, ...],
) -> DownloadSubmitResultView:
    """Return a GUI-safe rejected submit result for handled errors."""

    return DownloadSubmitResultView(
        request_id=request_id,
        accepted=False,
        status="rejected",
        can_run=False,
        item_count=0,
        estimated_items=None,
        issues=tuple(issues),
        message=message,
        runtime_visible=False,
        execution_plan_id=None,
        execution_plan_created=False,
        execution_plan_message=(
            "Execution plan was not created because submit was rejected."
        ),
    )


def _normalized_payload(draft: DownloadRequestDraftLike) -> dict[str, object]:
    timeframe_mode = draft.timeframe_mode
    return {
        "workflow_kind": draft.workflow_mode,
        "source": _optional_text(draft.source_provider),
        "market": _optional_text(draft.market),
        "symbols": tuple(draft.symbols),
        "timeframe_mode": timeframe_mode,
        "timeframes": tuple(draft.timeframes) if timeframe_mode == "explicit" else (),
        "range_mode": draft.range_mode,
        "start": _optional_text(draft.start),
        "end": _optional_text(draft.end),
        "conflict_policy": draft.conflict_policy,
        "priority": draft.priority,
        "connection_ref": _optional_text(draft.connection_ref),
        "websocket_required": draft.websocket_required,
        "tags": tuple(draft.tags),
        "metadata": _json_safe(draft.metadata),
    }


def _preview_request_id(payload: Mapping[str, object]) -> str:
    return _request_id(payload, prefix="preview")


def _submit_id(payload: Mapping[str, object]) -> str:
    return _request_id(payload, prefix="request")


def _request_id(payload: Mapping[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _optional_text(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("Select ") or stripped.startswith("No connection selected"):
        return None
    return stripped


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, tuple | list):
        return tuple(_json_safe(item) for item in value)
    return value


def _format_issue(issue: DownloadValidationIssue) -> str:
    field = f" {issue.field}" if issue.field is not None else ""
    return f"{issue.severity.value.upper()}{field}: {issue.message}"
