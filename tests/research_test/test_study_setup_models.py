from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import pytest

from leonardo.data import MarketId
from leonardo.financial_tools import ALL_FINANCIAL_TOOL_SPECS
from leonardo.research import (
    RESEARCH_EXCLUDED_FINANCIAL_TOOL_KEYS,
    RESEARCH_FINANCIAL_TOOL_SPECS,
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
from leonardo.research import study_setup


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
ARTIFACT_ID = "a" * 64


def catalog() -> StudySetupCatalog:
    return StudySetupCatalog(
        market_id=MARKET,
        tools=RESEARCH_FINANCIAL_TOOL_SPECS,
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

    global_keys = tuple(ALL_FINANCIAL_TOOL_SPECS)
    research_keys = tuple(item.key for item in value.tools)
    assert len(global_keys) == 26
    assert len(research_keys) == 25
    assert research_keys == tuple(
        key for key in global_keys if key != "dynamic_binning"
    )
    assert RESEARCH_EXCLUDED_FINANCIAL_TOOL_KEYS == frozenset(
        {"dynamic_binning"}
    )
    assert RESEARCH_FINANCIAL_TOOL_SPECS is (
        study_setup.RESEARCH_FINANCIAL_TOOL_SPECS
    )
    assert RESEARCH_EXCLUDED_FINANCIAL_TOOL_KEYS is (
        study_setup.RESEARCH_EXCLUDED_FINANCIAL_TOOL_KEYS
    )
    assert sum(item.kind == "indicator" for item in value.tools) == 10
    assert sum(item.kind == "oscillator" for item in value.tools) == 7
    assert sum(item.kind == "construct" for item in value.tools) == 8
    assert "dynamic_binning" not in research_keys
    assert set(research_keys) == set(global_keys) - {"dynamic_binning"}
    assert source_role_schema("ema") == ()
    assert source_role_schema("derivative") == ("source",)
    assert source_role_schema("delta") == ("fast", "slow")
    assert source_role_schema("braids") == ("fast", "mid", "slow")
    assert source_role_schema("braid_instability") == ("fast", "mid", "slow")
    assert source_role_schema("trap_area") == ("fast", "mid?", "slow")
    assert source_role_schema("dynamic_binning") == ("source_1", "...")
    assert source_role_schema("universal_trend_classifier") == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )
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


def test_catalog_rejects_noncanonical_tool_sequences_and_excluded_artifacts() -> None:
    value = catalog()
    with pytest.raises(StudySetupValidationError, match="Research Financial Tools"):
        replace(value, tools=tuple(ALL_FINANCIAL_TOOL_SPECS.values()))
    with pytest.raises(StudySetupValidationError, match="Research Financial Tools"):
        replace(value, tools=RESEARCH_FINANCIAL_TOOL_SPECS[:-1])
    with pytest.raises(StudySetupValidationError, match="unique"):
        replace(
            value,
            tools=(
                *RESEARCH_FINANCIAL_TOOL_SPECS,
                RESEARCH_FINANCIAL_TOOL_SPECS[-1],
            ),
        )
    with pytest.raises(StudySetupValidationError, match="Research Financial Tools"):
        replace(
            value,
            tools=(
                RESEARCH_FINANCIAL_TOOL_SPECS[1],
                RESEARCH_FINANCIAL_TOOL_SPECS[0],
                *RESEARCH_FINANCIAL_TOOL_SPECS[2:],
            ),
        )
    dynamic = StudyArtifactOption(
        MARKET,
        "d" * 64,
        "construct",
        "dynamic_binning",
        "Saved Dynamic Binning",
        ("analysis_payload",),
    )
    with pytest.raises(StudySetupValidationError, match="Research catalog"):
        replace(value, artifact_options=(*value.artifact_options, dynamic))


def test_dynamic_binning_calculation_and_artifact_drafts_are_rejected() -> None:
    value = catalog()
    for draft in (
        StudySetupDraft("calculation", "dynamic_binning"),
        StudySetupDraft(
            "artifact",
            "dynamic_binning",
            artifact_id="d" * 64,
        ),
    ):
        with pytest.raises(
            StudySetupValidationError,
            match="tool is not present in the canonical catalog",
        ):
            build_study_request(draft, value)


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


def test_source_order_stale_artifact_and_mixed_family_selection_rules() -> None:
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
    request = build_study_request(
        StudySetupDraft(
            "calculation",
            "braids",
            {"tie_policy": "carry"},
            (
                StudySetupSourceSelection(
                    "fast", "study", study_id="study_ema", output_name="ema_9"
                ),
                StudySetupSourceSelection(
                    "mid", "study", study_id="study_ema", output_name="ema_9"
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
    assert request.tool_key == "braids"
    assert tuple(source.role for source in request.input_sources) == (
        "fast",
        "mid",
        "slow",
    )
    fast, mid, slow = request.input_sources
    assert fast.source_kind == "study"
    assert mid.source_kind == "study"
    assert slow.source_kind == "artifact"
    assert slow.artifact_tool_key == "rsi"
    assert slow.artifact_id == "c" * 64
    assert slow.output_name == "rsi_14"


def test_braid_mid_is_required_while_trap_area_mid_remains_optional() -> None:
    value = catalog()
    fast_slow = (
        StudySetupSourceSelection("fast", "ohlcv", column_name="open"),
        StudySetupSourceSelection("slow", "ohlcv", column_name="close"),
    )

    for tool_key in ("braids", "braid_instability"):
        with pytest.raises(StudySetupValidationError, match="source roles"):
            build_study_request(
                StudySetupDraft("calculation", tool_key, sources=fast_slow),
                value,
            )

    trap_area = build_study_request(
        StudySetupDraft("calculation", "trap_area", sources=fast_slow),
        value,
    )
    assert tuple(source.role for source in trap_area.input_sources) == ("fast", "slow")


def test_catalog_and_drafts_defensively_copy_mutable_inputs() -> None:
    parameters = {"period": 20}
    draft = StudySetupDraft("calculation", "ema", parameters)
    parameters["period"] = 99

    assert draft.parameters == {"period": 20}
    with pytest.raises(TypeError):
        draft.parameters["period"] = 2


def test_artifact_option_projects_parameters_and_source_bindings_canonically() -> None:
    sma = StudyArtifactOption(
        MARKET,
        ARTIFACT_ID,
        "indicator",
        "sma",
        "Saved SMA",
        ("sma_20",),
        parameters={"period": 20},
    )
    delta = StudyArtifactOption(
        MARKET,
        "b" * 64,
        "construct",
        "delta",
        "Saved Delta",
        ("delta",),
        parameters={
            "eps": 1e-12,
            "slow": "__research_slow",
            "mode": "abs",
            "fast": "__research_fast",
        },
        source_bindings=(("fast", "ema_20"), ("slow", "ema_50")),
    )
    utc = StudyArtifactOption(
        MARKET,
        "c" * 64,
        "indicator",
        "universal_trend_classifier",
        "Saved UTC",
        ("utc_state",),
        parameters={
            "range_fractal_window": 3,
            "trough_column": "trough_fractal_5",
            "source": "close",
            "fractal_window": 5,
            "peak_column": "peak_fractal_5",
            "trend_fractal_window": 5,
        },
        source_bindings=(
            ("trend_peak", "peak_fractal_5"),
            ("trend_trough", "trough_fractal_5"),
            ("range_peak", "peak_fractal_3"),
            ("range_trough", "trough_fractal_3"),
        ),
    )

    assert sma.parameters == {"period": 20}
    assert tuple(delta.parameters) == ("mode", "eps")
    assert delta.parameters == {"mode": "abs", "eps": 1e-12}
    assert delta.source_bindings == (
        ("fast", "ema_20"),
        ("slow", "ema_50"),
    )
    assert tuple(utc.parameters) == (
        "source",
        "trend_fractal_window",
        "range_fractal_window",
    )
    assert utc.parameters == {
        "source": "close",
        "trend_fractal_window": 5,
        "range_fractal_window": 3,
    }
    assert tuple(role for role, _value in utc.source_bindings) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )


def test_artifact_option_rejects_invalid_source_binding_projections() -> None:
    values = {
        "market_id": MARKET,
        "artifact_id": ARTIFACT_ID,
        "kind": "construct",
        "tool_key": "derivative",
        "display_name": "Saved Derivative",
        "output_names": ("close__d1",),
        "parameters": {"order": 1, "source": "__research_source"},
    }
    for bindings, message in (
        ((("source", "close"), ("source", "open")), "unique"),
        ((("source", ""),), "canonical non-empty"),
        ((("source", "__research_source"),), "internal aliases"),
        ((("source", "a" * 64),), "Artifact IDs"),
    ):
        with pytest.raises(StudySetupValidationError, match=message):
            StudyArtifactOption(**values, source_bindings=bindings)


def test_artifact_option_defensively_copies_projection_inputs() -> None:
    parameters = {"order": 1, "source": "__research_source"}
    bindings = [("source", "close")]
    option = StudyArtifactOption(
        MARKET,
        ARTIFACT_ID,
        "construct",
        "derivative",
        "Saved Derivative",
        ("close__d1",),
        parameters=parameters,
        source_bindings=bindings,
    )
    parameters["order"] = 99
    bindings.append(("extra", "open"))

    assert option.parameters == {"order": 1}
    assert option.source_bindings == (("source", "close"),)
    with pytest.raises(TypeError):
        option.parameters["order"] = 2


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


def _utc_catalog() -> StudySetupCatalog:
    value = catalog()
    outputs = (
        "peak_fractal_3",
        "trough_fractal_3",
        "peak_fractal_5",
        "trough_fractal_5",
    )
    return replace(
        value,
        study_sources=tuple(
            StudySourceOption(
                "study",
                f"Peaks & Troughs: {output}",
                "indicator",
                study_id="study_peaks",
                output_name=output,
            )
            for output in outputs
        )
        + (
            StudySourceOption(
                "study",
                "Other Peaks & Troughs: trough_fractal_3",
                "indicator",
                study_id="study_other_peaks",
                output_name="trough_fractal_3",
            ),
        ),
    )


def _utc_sources(
    *,
    trend_window: int = 5,
    range_window: int = 3,
    range_trough_owner: str = "study_peaks",
) -> tuple[StudySetupSourceSelection, ...]:
    return (
        StudySetupSourceSelection(
            "trend_peak",
            "study",
            study_id="study_peaks",
            output_name=f"peak_fractal_{trend_window}",
        ),
        StudySetupSourceSelection(
            "trend_trough",
            "study",
            study_id="study_peaks",
            output_name=f"trough_fractal_{trend_window}",
        ),
        StudySetupSourceSelection(
            "range_peak",
            "study",
            study_id="study_peaks",
            output_name=f"peak_fractal_{range_window}",
        ),
        StudySetupSourceSelection(
            "range_trough",
            "study",
            study_id=range_trough_owner,
            output_name=f"trough_fractal_{range_window}",
        ),
    )


def test_utc_setup_requires_exact_four_roles_outputs_and_one_owner() -> None:
    value = _utc_catalog()
    accepted = build_study_request(
        StudySetupDraft(
            "calculation",
            "universal_trend_classifier",
            sources=_utc_sources(),
        ),
        value,
    )
    assert tuple(source.role for source in accepted.input_sources) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )

    for sources in (
        (),
        _utc_sources()[:2],
        _utc_sources()[2:],
    ):
        with pytest.raises(StudySetupValidationError, match="source roles"):
            build_study_request(
                StudySetupDraft(
                    "calculation",
                    "universal_trend_classifier",
                    sources=sources,
                ),
                value,
            )

    wrong_trend = list(_utc_sources())
    wrong_trend[0] = replace(wrong_trend[0], output_name="peak_fractal_3")
    with pytest.raises(StudySetupValidationError, match="exact Peaks"):
        build_study_request(
            StudySetupDraft(
                "calculation",
                "universal_trend_classifier",
                sources=tuple(wrong_trend),
            ),
            value,
        )

    wrong_range = list(_utc_sources())
    wrong_range[2] = replace(wrong_range[2], output_name="peak_fractal_5")
    with pytest.raises(StudySetupValidationError, match="exact Peaks"):
        build_study_request(
            StudySetupDraft(
                "calculation",
                "universal_trend_classifier",
                sources=tuple(wrong_range),
            ),
            value,
        )

    with pytest.raises(StudySetupValidationError, match="one Peaks"):
        build_study_request(
            StudySetupDraft(
                "calculation",
                "universal_trend_classifier",
                sources=_utc_sources(range_trough_owner="study_other_peaks"),
            ),
            value,
        )


def test_utc_setup_accepts_one_output_pair_when_windows_match() -> None:
    request = build_study_request(
        StudySetupDraft(
            "calculation",
            "universal_trend_classifier",
            {"range_fractal_window": 5},
            _utc_sources(range_window=5),
        ),
        _utc_catalog(),
    )
    assert tuple(source.output_name for source in request.input_sources) == (
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_5",
        "trough_fractal_5",
    )
