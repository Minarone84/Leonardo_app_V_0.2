from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import pytest

from leonardo.data import MarketId
from leonardo.financial_tools import ALL_FINANCIAL_TOOL_SPECS
from leonardo.research import (
    StudyArtifactOption,
    StudySetupCatalog,
    StudySetupDraft,
    StudySetupSourceSelection,
    StudySetupValidationError,
    StudySourceOption,
    StudyUserMetadata,
    build_study_request,
    source_role_schema,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
ARTIFACT_ID = "a" * 64


def catalog() -> StudySetupCatalog:
    return StudySetupCatalog(
        market_id=MARKET,
        tools=tuple(ALL_FINANCIAL_TOOL_SPECS.values()),
        ohlcv_sources=tuple(
            StudySourceOption("ohlcv", name.upper(), "ohlc", column_name=name)
            for name in ("open", "high", "low", "close", "volume")
        ),
        study_sources=(
            StudySourceOption(
                "study", "EMA: ema_9", "indicator", study_id="study_ema", output_name="ema_9"
            ),
        ),
        artifact_options=(
            StudyArtifactOption(
                MARKET, ARTIFACT_ID, "indicator", "sma", "Saved SMA", ("sma_50",)
            ),
        ),
    )


def test_catalog_is_task_1014_driven_and_role_schemas_are_exact() -> None:
    value = catalog()

    assert len(value.tools) == 26
    assert tuple(item.key for item in value.tools) == tuple(ALL_FINANCIAL_TOOL_SPECS)
    assert source_role_schema("ema") == ()
    assert source_role_schema("derivative") == ("source",)
    assert source_role_schema("delta") == ("fast", "slow")
    assert source_role_schema("braids") == ("fast", "mid?", "slow")
    assert source_role_schema("dynamic_binning") == ("source_1", "...")
    assert source_role_schema("universal_trend_classifier") == ("peak+trough?",)
    script = """
import builtins

original_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name.startswith("PySide6"):
        raise ModuleNotFoundError("PySide6 blocked by Task 1021 regression")
    return original_import(name, *args, **kwargs)

builtins.__import__ = blocked_import
import leonardo.research.study_environment
import leonardo.research.study_environment_store
import leonardo.research.study_setup
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_builds_existing_calculation_and_artifact_requests() -> None:
    value = catalog()
    metadata = StudyUserMetadata(True, "supporting_indicator", "Setup evidence")
    ema = build_study_request(
        StudySetupDraft("calculation", "ema", {"period": 20}, user_metadata=metadata),
        value,
    )
    derivative = build_study_request(
        StudySetupDraft(
            "calculation",
            "derivative",
            {"order": 1},
            (
                StudySetupSourceSelection(
                    "source", "study", study_id="study_ema", output_name="ema_9"
                ),
            ),
        ),
        value,
    )
    saved = build_study_request(
        StudySetupDraft("artifact", "sma", artifact_id=ARTIFACT_ID), value
    )

    assert ema.parameters["period"] == 20
    assert ema.user_metadata == metadata
    assert derivative.input_sources[0].study_id == "study_ema"
    assert saved.artifact_id == ARTIFACT_ID
    assert saved.display_name == "Saved SMA"


def test_source_order_family_and_stale_artifact_selection_are_rejected() -> None:
    value = catalog()
    with pytest.raises(StudySetupValidationError):
        build_study_request(
            StudySetupDraft(
                "calculation",
                "delta",
                {"mode": "abs", "eps": 1e-12},
                (
                    StudySetupSourceSelection("slow", "ohlcv", column_name="close"),
                    StudySetupSourceSelection("fast", "ohlcv", column_name="open"),
                ),
            ),
            value,
        )
    with pytest.raises(StudySetupValidationError, match="current selectable"):
        build_study_request(
            StudySetupDraft("artifact", "sma", artifact_id="b" * 64), value
        )
    mixed = replace(
        value,
        artifact_options=(
            *value.artifact_options,
            StudyArtifactOption(
                MARKET,
                "c" * 64,
                "oscillator",
                "rsi",
                "Saved RSI",
                ("rsi_14",),
            ),
        ),
    )
    with pytest.raises(StudySetupValidationError, match="one family"):
        build_study_request(
            StudySetupDraft(
                "calculation",
                "braids",
                {"tie_policy": "carry"},
                (
                    StudySetupSourceSelection(
                        "fast", "study", study_id="study_ema", output_name="ema_9"
                    ),
                    StudySetupSourceSelection(
                        "slow",
                        "artifact",
                        artifact_kind="oscillator",
                        artifact_tool_key="rsi",
                        artifact_id="c" * 64,
                        output_name="rsi_14",
                    ),
                ),
            ),
            mixed,
        )


def test_catalog_and_drafts_defensively_copy_mutable_inputs() -> None:
    parameters = {"period": 20}
    draft = StudySetupDraft("calculation", "ema", parameters)
    parameters["period"] = 99

    assert draft.parameters == {"period": 20}
    with pytest.raises(TypeError):
        draft.parameters["period"] = 2


def test_artifact_source_projection_exposes_only_analysis_usable_outputs() -> None:
    value = catalog()
    restricted = replace(
        value.artifact_options[0],
        output_names=("sma_50", "ambient_state"),
        analysis_usable_output_names=("sma_50",),
    )
    projected = replace(value, artifact_options=(restricted,)).source_options
    assert tuple(item.output_name for item in projected if item.source_kind == "artifact") == (
        "sma_50",
    )
