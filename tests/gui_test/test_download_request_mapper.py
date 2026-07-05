from pathlib import Path

import pytest

from leonardo.contracts.downloads import (
    DownloadPreflight,
    DownloadStatus,
    DownloadTimeframeMode,
    DownloadValidationIssue,
    DownloadValidationSeverity,
    DownloadWorkflowKind,
)
from leonardo.gui.download_request_mapper import (
    DownloadPreflightPreviewView,
    build_download_request_from_draft,
    build_preflight_preview_view,
)
from leonardo.gui.windows.download_request_builder_window import (
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    DownloadRequestDraft,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAPPER_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "download_request_mapper.py"


def test_mapper_builds_download_data_request_from_draft() -> None:
    draft = _draft()

    request = build_download_request_from_draft(draft)

    assert request.request_id.startswith("preview-")
    assert request.workflow_kind is DownloadWorkflowKind.DOWNLOAD_DATA
    assert request.source == "binance"
    assert request.market == "spot"
    assert request.symbols == ("BTCUSDT", "ETHUSDT")
    assert request.timeframe_mode is DownloadTimeframeMode.EXPLICIT
    assert request.timeframes == ("1m", "5m")
    assert request.connection_ref == "binance-spot"
    assert request.metadata["profile"] == "manual"


def test_mapper_builds_ohlcv_maintenance_request_from_draft() -> None:
    draft = _draft(workflow_mode=OHLCV_MAINTENANCE_WORKFLOW_MODE)

    request = build_download_request_from_draft(draft)

    assert request.workflow_kind is DownloadWorkflowKind.OHLCV_MAINTENANCE
    assert request.request_id.startswith("preview-")


def test_mapper_generates_deterministic_preview_ids() -> None:
    first = build_download_request_from_draft(_draft())
    second = build_download_request_from_draft(_draft())
    changed = build_download_request_from_draft(_draft(symbols=("SOLUSDT",)))

    assert first.request_id == second.request_id
    assert first.request_id != changed.request_id


@pytest.mark.parametrize(
    "timeframe_mode",
    ("all", "default", "supported"),
)
def test_mapper_does_not_create_fake_timeframes_for_unresolved_modes(
    timeframe_mode: str,
) -> None:
    draft = _draft(timeframe_mode=timeframe_mode, timeframes=("1m", "5m"))

    request = build_download_request_from_draft(draft)

    assert request.timeframe_mode is DownloadTimeframeMode(timeframe_mode)
    assert request.timeframes == ()


def test_mapper_converts_preflight_to_preview_view() -> None:
    issue = DownloadValidationIssue(
        code="missing_timeframes",
        severity=DownloadValidationSeverity.ERROR,
        message="Explicit timeframe mode requires at least one timeframe.",
        field="timeframes",
    )
    preflight = DownloadPreflight(
        request_id="preview-test",
        status=DownloadStatus.FAILED,
        can_run=False,
        required_connections=("binance-spot",),
        websocket_required=True,
        estimated_symbols=2,
        estimated_timeframes=0,
        estimated_items=0,
        issues=(issue,),
    )

    view = build_preflight_preview_view(preflight)

    assert isinstance(view, DownloadPreflightPreviewView)
    assert view.request_id == "preview-test"
    assert view.status == "failed"
    assert view.can_run is False
    assert view.required_connections == ("binance-spot",)
    assert view.websocket_required is True
    assert view.issues == (
        "ERROR timeframes: Explicit timeframe mode requires at least one timeframe.",
    )
    assert view.message == "Preflight preview blocked."


def test_mapper_imports_contracts_but_no_core_or_qt() -> None:
    source = _MAPPER_SOURCE.read_text(encoding="utf-8")

    assert "leonardo.contracts.downloads" in source
    assert "leonardo.core" not in source
    assert "PySide6" not in source
    assert "Qt" not in source
    assert "DownloadManager" not in source
    assert "LeonardoApp" not in source
    assert "RuntimeManager" not in source


def _draft(
    *,
    workflow_mode: str = DOWNLOAD_DATA_WORKFLOW_MODE,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    timeframe_mode: str = "explicit",
    timeframes: tuple[str, ...] = ("1m", "5m"),
) -> DownloadRequestDraft:
    return DownloadRequestDraft(
        workflow_mode=workflow_mode,
        source_provider="binance",
        market="spot",
        symbols=symbols,
        timeframe_mode=timeframe_mode,
        timeframes=timeframes,
        range_mode="latest",
        start="2026-01-01",
        end="2026-01-02",
        conflict_policy="skip_existing",
        priority="normal",
        connection_ref="binance-spot",
        websocket_required=True,
        tags=("preview",),
        metadata={"profile": "manual"},
        metadata_parse_error=None,
    )
