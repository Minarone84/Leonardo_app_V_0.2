"""Deterministic GUI-only dummy data for Leonardo V2 shell windows.

The values in this module are local display fixtures. They do not represent
provider truth, account truth, file state, calculated studies, storage state,
analysis results, or trading authorization.
"""

from __future__ import annotations

from collections.abc import Mapping


DummyRow = Mapping[str, object]


def research_workspace_status() -> str:
    """Return the dummy Research Suite workspace status text."""

    return "DUMMY workspace loaded: shell only, no chart engine."


def research_overview_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Research Suite overview rows."""

    return (
        {
            "surface": "Active Workspace",
            "state": "Research Lab / dummy",
            "details": "GUI shell display state only.",
        },
        {
            "surface": "Chart Renderer",
            "state": "offline placeholder",
            "details": "No candles, viewport, or renderer are constructed.",
        },
        {
            "surface": "Study Runtime",
            "state": "not available",
            "details": "No indicators or study calculations run.",
        },
    )


def research_market_context_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy market context rows."""

    return (
        {
            "field": "Dataset",
            "value": "DUMMY BTCUSDT 1h",
            "status": "not loaded",
        },
        {
            "field": "Source",
            "value": "disconnected",
            "status": "no provider/API call",
        },
        {
            "field": "Persistence",
            "value": "disabled",
            "status": "no storage read/write",
        },
    )


def research_chart_control_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy chart control rows."""

    return (
        {
            "control": "Crosshair",
            "value": "visual placeholder",
            "state": "inert",
        },
        {
            "control": "Zoom",
            "value": "locked",
            "state": "no viewport engine",
        },
        {
            "control": "Study Overlay",
            "value": "none",
            "state": "no calculation",
        },
    )


def research_study_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy study sidebar rows."""

    return (
        {
            "slot": "primary",
            "name": "DUMMY RSI Study Placeholder",
            "status": "placeholder",
        },
        {
            "slot": "secondary",
            "name": "DUMMY Volume Pane Placeholder",
            "status": "placeholder",
        },
    )


def research_workspace_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy chart workspace rows."""

    return (
        {
            "pane": "chart.primary",
            "symbol": "DUMMY:BTCUSDT",
            "timeframe": "1m",
            "status": "chart placeholder only",
        },
        {
            "pane": "chart.secondary",
            "symbol": "DUMMY:ETHUSDT",
            "timeframe": "5m",
            "status": "chart placeholder only",
        },
    )


def data_manager_dataset_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Data Manager dataset rows."""

    return (
        {
            "dataset_id": "dummy_dataset_btc_1m",
            "market": "DUMMY BTCUSDT",
            "rows": 1200,
            "status": "catalog placeholder",
        },
        {
            "dataset_id": "dummy_dataset_eth_5m",
            "market": "DUMMY ETHUSDT",
            "rows": 720,
            "status": "catalog placeholder",
        },
    )


def data_manager_overview_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Data Manager overview rows."""

    return (
        {
            "surface": "Dataset Catalog",
            "state": "dummy ready",
            "details": "Local display rows only; no dataset scan.",
        },
        {
            "surface": "Artifact Catalog",
            "state": "dummy ready",
            "details": "No artifact metadata or storage is loaded.",
        },
        {
            "surface": "Analysis Database",
            "state": "offline placeholder",
            "details": "No database connection or materialization backend.",
        },
    )


def data_manager_artifact_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy artifact catalog rows."""

    return (
        {
            "artifact_id": "dummy_artifact_rsi",
            "kind": "indicator placeholder",
            "source": "dummy_dataset_btc_1m",
            "status": "not calculated",
        },
        {
            "artifact_id": "dummy_artifact_volume",
            "kind": "oscillator placeholder",
            "source": "dummy_dataset_eth_5m",
            "status": "not calculated",
        },
    )


def data_manager_recipe_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy recipe rows."""

    return (
        {
            "recipe_id": "dummy_recipe_momentum_pack",
            "kind": "recipe placeholder",
            "status": "shell only",
        },
        {
            "recipe_id": "dummy_recipe_volume_pack",
            "kind": "recipe placeholder",
            "status": "shell only",
        },
    )


def data_manager_storage_readiness_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy storage and database readiness rows."""

    return (
        {
            "component": "Storage Root",
            "state": "disabled",
            "details": "No path inspection or file access.",
        },
        {
            "component": "Metadata Sidecars",
            "state": "not loaded",
            "details": "No sidecar reads or validation.",
        },
        {
            "component": "Analysis Database",
            "state": "not connected",
            "details": "No database creation, rebuild, or mutation.",
        },
    )


def data_manager_import_export_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy import/export control rows."""

    return (
        {
            "control": "Import Dataset",
            "state": "disabled",
            "details": "No file picker, parser, or storage write.",
        },
        {
            "control": "Export Artifact",
            "state": "disabled",
            "details": "No export path or file writer.",
        },
        {
            "control": "Sync Metadata",
            "state": "placeholder",
            "details": "No backend metadata mutation.",
        },
    )


def data_manager_processing_queue_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy materialization queue rows."""

    return (
        {
            "item": "Artifact calculation",
            "progress": "0%",
            "state": "engine unavailable",
        },
        {
            "item": "Recipe collection",
            "progress": "0%",
            "state": "execution disabled",
        },
        {
            "item": "Database materialization",
            "progress": "0%",
            "state": "storage disabled",
        },
    )


def connection_provider_status_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Connection Suite provider status rows."""

    return (
        {
            "surface": "Provider Catalog",
            "state": "offline",
            "details": "DUMMY catalog placeholder; no discovery or API call.",
        },
        {
            "surface": "Account Profiles",
            "state": "not connected",
            "details": "DUMMY profile placeholder; no account sync.",
        },
        {
            "surface": "API Transport",
            "state": "disabled",
            "details": "DUMMY transport placeholder; no client exists.",
        },
        {
            "surface": "Credentials",
            "state": "not loaded",
            "details": "DUMMY credential status; no environment read.",
        },
        {
            "surface": "Rate Limits",
            "state": "placeholder",
            "details": "DUMMY rate-limit context; no provider policy loaded.",
        },
    )


def connection_websocket_status_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Connection Suite websocket status rows."""

    return (
        {
            "channel": "WebSocket Channels",
            "state": "offline",
            "details": "DUMMY stream list; no websocket client.",
        },
        {
            "channel": "Live Stream",
            "state": "disabled",
            "details": "DUMMY live-feed placeholder only.",
        },
        {
            "channel": "Heartbeat",
            "state": "placeholder",
            "details": "DUMMY heartbeat row; no timer or network.",
        },
        {
            "channel": "Reconnect Policy",
            "state": "future module",
            "details": "DUMMY policy placeholder; no reconnect logic.",
        },
    )


def connection_download_overview_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Connection Suite download overview rows."""

    return (
        {
            "queue": "Historical Downloads",
            "scope": "DUMMY BTCUSDT / 1m",
            "progress": "0%",
            "state": "idle shell",
        },
        {
            "queue": "Preflight",
            "scope": "DUMMY validation preview",
            "progress": "0%",
            "state": "not executed",
        },
        {
            "queue": "Storage",
            "scope": "DUMMY target path",
            "progress": "0%",
            "state": "writes forbidden",
        },
    )


def connection_activity_messages() -> tuple[str, ...]:
    """Return deterministic dummy Connection Suite activity messages."""

    return (
        "Connection Suite shell loaded from GUI-only dummy fixtures.",
        "no provider/API/websocket behavior exists in this shell.",
        "Historical download overview is inert; no request builder or execution path exists.",
    )


def ohlcv_preflight_request_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy OHLCV preflight request rows."""

    return (
        {
            "item": "Provider",
            "value": "Bybit dummy",
            "state": "offline placeholder",
        },
        {
            "item": "Market Type",
            "value": "linear dummy",
            "state": "not validated",
        },
        {
            "item": "Symbol",
            "value": "BTCUSDT dummy",
            "state": "not resolved",
        },
        {
            "item": "Timeframe",
            "value": "1h dummy",
            "state": "display only",
        },
        {
            "item": "Storage Mode",
            "value": "disabled",
            "state": "writes forbidden",
        },
    )


def ohlcv_preflight_validation_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy OHLCV preflight checklist rows."""

    return (
        {
            "check": "Provider metadata",
            "state": "not executed",
            "details": "No provider catalog lookup occurs in the GUI shell.",
        },
        {
            "check": "Symbol eligibility",
            "state": "not executed",
            "details": "No market metadata or symbol resolver is called.",
        },
        {
            "check": "Date range",
            "state": "placeholder",
            "details": "Dummy text only; no backend range calculation.",
        },
        {
            "check": "Storage availability",
            "state": "disabled",
            "details": "No file or database path is inspected.",
        },
    )


def ohlcv_preflight_workload_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy OHLCV preflight workload rows."""

    return (
        {
            "metric": "Expected Bars",
            "value": "24 dummy",
            "details": "Static fixture, not computed from dates.",
        },
        {
            "metric": "Pages",
            "value": "1 dummy",
            "details": "Static fixture, not derived from provider limits.",
        },
        {
            "metric": "Execution Backend",
            "value": "not available",
            "details": "Task creation is outside this shell.",
        },
    )


def ohlcv_preflight_warning_messages() -> tuple[str, ...]:
    """Return deterministic dummy OHLCV preflight warning messages."""

    return (
        "DUMMY preflight only: no validation engine is called.",
        "Provider/API/network/storage checks are intentionally disabled.",
        "Open Dummy Task Shell emits GUI intent only.",
    )


def ohlcv_task_stage_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy OHLCV task stage rows."""

    return (
        {
            "stage": "Queued",
            "state": "dummy",
            "details": "No TaskManager registration is performed.",
        },
        {
            "stage": "Preflight",
            "state": "complete dummy",
            "details": "Static fixture, not a validated backend result.",
        },
        {
            "stage": "Provider",
            "state": "offline dummy",
            "details": "No provider transport exists in this shell.",
        },
        {
            "stage": "Output",
            "state": "disabled",
            "details": "No file or database writes are authorized.",
        },
    )


def ohlcv_task_output_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy OHLCV task output rows."""

    return (
        {
            "item": "Rows Written",
            "value": "0",
            "state": "storage disabled",
        },
        {
            "item": "Output Path",
            "value": "not assigned",
            "state": "no filesystem access",
        },
        {
            "item": "Final State",
            "value": "awaiting execution backend",
            "state": "dummy only",
        },
    )


def ohlcv_task_log_messages() -> tuple[str, ...]:
    """Return deterministic dummy OHLCV task log messages."""

    return (
        "DUMMY task shell loaded.",
        "No async task, provider transport, download loop, or storage writer exists here.",
        "Progress bars are local display placeholders only.",
    )


def analysis_readiness_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Analysis Suite readiness rows."""

    return (
        {
            "item": "Analysis Database",
            "state": "dummy unavailable",
            "details": "No database materialization in GUI shell phase.",
        },
        {
            "item": "Target Plan",
            "state": "placeholder",
            "details": "Target planning UI shell only.",
        },
    )


def analysis_overview_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Analysis Suite overview rows."""

    return (
        {
            "surface": "Analysis Mode",
            "state": "offline placeholder",
            "details": "No analysis engine is attached.",
        },
        {
            "surface": "Input Dataset",
            "state": "not loaded",
            "details": "No dataset or storage access occurs.",
        },
        {
            "surface": "Run Status",
            "state": "idle dummy",
            "details": "No run execution or report generation.",
        },
    )


def analysis_feature_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy feature planning rows."""

    return (
        {
            "feature_set": "dummy_feature_set_momentum",
            "status": "placeholder",
            "notes": "No feature calculation.",
        },
        {
            "feature_set": "dummy_feature_set_volatility",
            "status": "placeholder",
            "notes": "No diagnostics engine.",
        },
    )


def analysis_result_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy result summary rows."""

    return (
        {
            "result": "Score",
            "value": "unavailable",
            "state": "engine pending",
        },
        {
            "result": "Candidate Rules",
            "value": "0",
            "state": "not scanned",
        },
        {
            "result": "Report",
            "value": "not generated",
            "state": "writes forbidden",
        },
    )


def analysis_diagnostics_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy diagnostics rows."""

    return (
        {
            "check": "Target Readiness",
            "state": "placeholder",
            "details": "No labels or targets generated.",
        },
        {
            "check": "Feature Readiness",
            "state": "placeholder",
            "details": "No feature calculation occurs.",
        },
        {
            "check": "Temporal Validation",
            "state": "not available",
            "details": "No validation workflow runs.",
        },
    )


def analysis_queue_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy analysis queue rows."""

    return (
        {
            "queue": "Analysis Runs",
            "state": "empty",
            "details": "No queued execution tasks.",
        },
        {
            "queue": "Diagnostics",
            "state": "idle",
            "details": "No diagnostics runtime is attached.",
        },
    )


def trading_account_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy Trading Suite account/risk rows."""

    return (
        {
            "field": "Mode",
            "value": "DUMMY paper shell",
            "status": "visual only",
        },
        {
            "field": "Risk Profile",
            "value": "disabled placeholder",
            "status": "no order routing",
        },
    )


def trading_position_rows() -> tuple[DummyRow, ...]:
    """Return deterministic dummy order/position rows."""

    return (
        {
            "ref": "dummy_position_none",
            "symbol": "DUMMY:BTCUSDT",
            "side": "none",
            "status": "placeholder",
        },
        {
            "ref": "dummy_order_none",
            "symbol": "DUMMY:ETHUSDT",
            "side": "none",
            "status": "placeholder",
        },
    )
