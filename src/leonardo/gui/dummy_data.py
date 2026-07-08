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
