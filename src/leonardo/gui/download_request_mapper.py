"""Map GUI-local download drafts to Download Manager contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from leonardo.contracts.download_data_boundary import (
    DownloadDataSelectionDraft,
    DownloadDataSelectionSummary,
)
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
    execution_plan_phase: str | None = None
    execution_plan_ready: bool = False
    execution_plan_blocked: bool = False
    sandbox_execution_status: str | None = None
    sandbox_execution_completed: bool = False
    sandbox_execution_message: str = "Sandbox execution was not run."
    sandbox_root: str | None = None
    sandbox_csv_paths: tuple[str, ...] = ()
    sandbox_metadata_paths: tuple[str, ...] = ()
    sandbox_bars_written: int = 0
    sandbox_first_timestamp_ms: int | None = None
    sandbox_last_timestamp_ms: int | None = None
    sandbox_timeframes_completed: tuple[str, ...] = ()
    sandbox_result_summaries: tuple[str, ...] = ()


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


def download_data_selection_drafts_from_request_draft(
    draft: DownloadRequestDraftLike,
) -> tuple[DownloadDataSelectionDraft, ...]:
    """
    Convert a GUI-local download request draft into Download Data selections.

    Multi-symbol GUI drafts are split into one canonical Download Data
    selection per symbol. Missing exchange, market, symbol, or selected
    timeframe values are represented as incomplete selection drafts rather than
    being defaulted by the mapper.
    """

    exchange_id = _optional_text(draft.source_provider)
    market_type = _optional_text(draft.market)
    selected_timeframes = _download_data_selected_timeframes(draft)
    symbols = _download_data_symbols(draft.symbols)
    warnings = _download_data_selection_warnings(draft, symbols)

    if not symbols:
        return (
            _download_data_selection_draft(
                exchange_id=exchange_id,
                market_type=market_type,
                symbol=None,
                selected_timeframes=selected_timeframes,
                warnings=warnings,
            ),
        )

    return tuple(
        _download_data_selection_draft(
            exchange_id=exchange_id,
            market_type=market_type,
            symbol=symbol,
            selected_timeframes=selected_timeframes,
            warnings=warnings,
        )
        for symbol in symbols
    )


def download_data_selection_summary_from_selection_draft(
    draft: DownloadDataSelectionDraft,
) -> DownloadDataSelectionSummary:
    """
    Convert a complete Download Data selection draft into its recap summary.

    Summaries require a complete selection identity. Incomplete selection drafts
    raise ``ValueError`` with the missing contract fields named explicitly.
    """

    if not isinstance(draft, DownloadDataSelectionDraft):
        raise TypeError("draft must be a DownloadDataSelectionDraft")

    missing_fields = _missing_download_data_selection_fields(
        draft.exchange_id,
        draft.market_type,
        draft.symbol,
        draft.selected_timeframes,
    )
    if missing_fields:
        missing_text = ", ".join(missing_fields)
        raise ValueError(f"Download Data selection is incomplete: {missing_text}")

    return DownloadDataSelectionSummary(
        exchange_id=draft.exchange_id or "",
        market_type=draft.market_type or "",
        symbol=draft.symbol or "",
        selected_timeframes=draft.selected_timeframes,
        warnings=draft.warnings,
        blockers=draft.blockers,
    )


def download_data_selection_summaries_from_request_draft(
    draft: DownloadRequestDraftLike,
) -> tuple[DownloadDataSelectionSummary, ...]:
    """
    Convert a GUI-local draft into complete Download Data selection summaries.

    The conversion intentionally raises on incomplete generated selections,
    matching the contract that summaries represent recap-ready selection data.
    """

    return tuple(
        download_data_selection_summary_from_selection_draft(selection_draft)
        for selection_draft in download_data_selection_drafts_from_request_draft(draft)
    )


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
    execution_plan_phase: str | None = None,
    execution_plan_ready: bool = False,
    execution_plan_blocked: bool = False,
    sandbox_execution_status: str | None = None,
    sandbox_execution_completed: bool = False,
    sandbox_execution_message: str = "Sandbox execution was not run.",
    sandbox_root: str | None = None,
    sandbox_csv_paths: tuple[str, ...] = (),
    sandbox_metadata_paths: tuple[str, ...] = (),
    sandbox_bars_written: int = 0,
    sandbox_first_timestamp_ms: int | None = None,
    sandbox_last_timestamp_ms: int | None = None,
    sandbox_timeframes_completed: tuple[str, ...] = (),
    sandbox_result_summaries: tuple[str, ...] = (),
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
        execution_plan_phase=execution_plan_phase,
        execution_plan_ready=execution_plan_ready,
        execution_plan_blocked=execution_plan_blocked,
        sandbox_execution_status=sandbox_execution_status,
        sandbox_execution_completed=sandbox_execution_completed,
        sandbox_execution_message=sandbox_execution_message,
        sandbox_root=sandbox_root,
        sandbox_csv_paths=tuple(sandbox_csv_paths),
        sandbox_metadata_paths=tuple(sandbox_metadata_paths),
        sandbox_bars_written=sandbox_bars_written,
        sandbox_first_timestamp_ms=sandbox_first_timestamp_ms,
        sandbox_last_timestamp_ms=sandbox_last_timestamp_ms,
        sandbox_timeframes_completed=tuple(sandbox_timeframes_completed),
        sandbox_result_summaries=tuple(sandbox_result_summaries),
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
        execution_plan_phase=None,
        execution_plan_ready=False,
        execution_plan_blocked=False,
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


def _download_data_selection_draft(
    *,
    exchange_id: str | None,
    market_type: str | None,
    symbol: str | None,
    selected_timeframes: tuple[str, ...],
    warnings: tuple[str, ...],
) -> DownloadDataSelectionDraft:
    return DownloadDataSelectionDraft(
        exchange_id=exchange_id,
        market_type=market_type,
        symbol=symbol,
        selected_timeframes=selected_timeframes,
        warnings=warnings,
        blockers=_download_data_selection_blockers(
            exchange_id,
            market_type,
            symbol,
            selected_timeframes,
        ),
    )


def _download_data_symbols(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.strip() for value in values if value.strip())


def _download_data_selected_timeframes(
    draft: DownloadRequestDraftLike,
) -> tuple[str, ...]:
    if draft.timeframe_mode != "explicit":
        return ()
    return tuple(value.strip() for value in draft.timeframes if value.strip())


def _download_data_selection_warnings(
    draft: DownloadRequestDraftLike,
    symbols: tuple[str, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if len(symbols) > 1:
        warnings.append(
            "Multiple symbols were split into one Download Data selection per symbol."
        )
    if draft.timeframe_mode != "explicit":
        warnings.append(
            "Only explicit timeframes map to Download Data selected_timeframes."
        )
    return tuple(warnings)


def _download_data_selection_blockers(
    exchange_id: str | None,
    market_type: str | None,
    symbol: str | None,
    selected_timeframes: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{field_name} is required for Download Data selection."
        for field_name in _missing_download_data_selection_fields(
            exchange_id,
            market_type,
            symbol,
            selected_timeframes,
        )
    )


def _missing_download_data_selection_fields(
    exchange_id: str | None,
    market_type: str | None,
    symbol: str | None,
    selected_timeframes: tuple[str, ...],
) -> tuple[str, ...]:
    missing: list[str] = []
    if exchange_id is None:
        missing.append("exchange_id")
    if market_type is None:
        missing.append("market_type")
    if symbol is None:
        missing.append("symbol")
    if not selected_timeframes:
        missing.append("selected_timeframes")
    return tuple(missing)


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
