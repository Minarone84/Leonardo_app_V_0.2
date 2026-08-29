from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from leonardo.financial_tools.construct_input_eligibility import (
    ConstructInputEligibility,
    FinancialToolInputCompatibilityError,
    FinancialToolInputSource,
    construct_input_policy,
    financial_tool_source_role_schema,
    load_construct_input_eligibility,
    validate_construct_input_eligibility,
    validate_financial_tool_inputs,
    validate_financial_tool_source_roles,
)
from leonardo.financial_tools.specifications import (
    ALL_FINANCIAL_TOOL_SPECS,
    get_financial_tool_spec,
    validate_catalog,
)


ALL_NUMERIC_SIGNALS = {
    "sma", "ema", "tema", "hma", "kama", "bb", "hck", "strategy",
    "rsi", "arsi", "tdirsi", "smi", "mfi", "obv", "volume",
    "derivative", "angle", "braid_instability", "delta", "trap_area",
    "percent_span_angle", "angle_momentum",
}
NO_CONSTRUCT_SOURCES = {
    "peaks_troughs", "universal_trend_classifier", "dynamic_binning", "braids",
}


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_canonical_registry_has_exact_catalog_coverage_and_policy() -> None:
    registry = load_construct_input_eligibility()

    assert len(registry) == 26
    assert set(registry) == set(ALL_FINANCIAL_TOOL_SPECS)
    assert {
        key for key, entry in registry.items()
        if entry.construct_source_policy == "all_numeric_signals"
    } == ALL_NUMERIC_SIGNALS
    assert {
        key for key, entry in registry.items()
        if entry.construct_source_policy == "none"
    } == NO_CONSTRUCT_SOURCES
    assert all(
        entry.tool_key == key
        and entry.kind == ALL_FINANCIAL_TOOL_SPECS[key].kind
        for key, entry in registry.items()
    )
    with pytest.raises(TypeError):
        registry["sma"] = registry["sma"]  # type: ignore[index]
    with pytest.raises(KeyError):
        construct_input_policy("not_registered")


def test_registry_validation_rejects_missing_unknown_and_kind_mismatch() -> None:
    registry = dict(load_construct_input_eligibility())
    missing = dict(registry)
    missing.pop("sma")
    with pytest.raises(ValueError, match="missing tools"):
        validate_construct_input_eligibility(missing, ALL_FINANCIAL_TOOL_SPECS)

    unknown = {
        **registry,
        "unknown": ConstructInputEligibility(
            "unknown", "indicator", "all_numeric_signals"
        ),
    }
    with pytest.raises(ValueError, match="unknown tools"):
        validate_construct_input_eligibility(unknown, ALL_FINANCIAL_TOOL_SPECS)

    mismatched = {
        **registry,
        "sma": replace(registry["sma"], kind="oscillator"),
    }
    with pytest.raises(ValueError, match="kind mismatch"):
        validate_construct_input_eligibility(mismatched, ALL_FINANCIAL_TOOL_SPECS)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"schema_version": 1},
        {"schema_version": 2, "tools": {}},
        {"schema_version": 1, "tools": []},
        {"schema_version": 1, "tools": {"sma": {"kind": "indicator"}}},
        {
            "schema_version": 1,
            "tools": {
                "sma": {
                    "kind": "unknown",
                    "construct_source_policy": "all_numeric_signals",
                }
            },
        },
        {
            "schema_version": 1,
            "tools": {
                "sma": {
                    "kind": "indicator",
                    "construct_source_policy": "unknown",
                }
            },
        },
        {
            "schema_version": 1,
            "tools": {
                "": {
                    "kind": "indicator",
                    "construct_source_policy": "all_numeric_signals",
                }
            },
        },
    ],
)
def test_loader_rejects_malformed_schema(tmp_path: Path, payload: object) -> None:
    with pytest.raises(ValueError):
        load_construct_input_eligibility(_write_json(tmp_path / "registry.json", payload))


def test_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":1,"tools":{"sma":{"kind":"indicator",'
        '"kind":"indicator","construct_source_policy":"all_numeric_signals"}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_construct_input_eligibility(path)


def test_catalog_validation_and_braid_compatibility_are_exact() -> None:
    validate_catalog()
    expected = {
        "braids": ("fast_mid_slow", ("indicator", "oscillator", "construct"),
                   "one_or_more", "state_series"),
        "braid_instability": (
            "fast_mid_slow", ("indicator", "oscillator", "construct"),
            "single", "plotted_line",
        ),
    }
    for tool_key, preserved in expected.items():
        construct_io = get_financial_tool_spec(tool_key).construct_io
        assert construct_io is not None
        assert construct_io.source_compatibility == "mixed_numeric"
        assert (
            construct_io.input_binding,
            construct_io.allowed_source_families,
            construct_io.output_cardinality,
            construct_io.output_role,
        ) == preserved


def _source(
    role: str,
    family: str = "indicator",
    *,
    output_name: str = "value",
    tool_key: str = "sma",
    owner_id: str = "owner",
    analysis_usable: bool = True,
    value_type: str = "numeric",
) -> FinancialToolInputSource:
    return FinancialToolInputSource(
        role,
        family,  # type: ignore[arg-type]
        output_name,
        True,
        tool_key,
        owner_id,
        analysis_usable,
        value_type,
    )


def _raw(role: str, column: str) -> FinancialToolInputSource:
    return FinancialToolInputSource(
        role, "ohlc", column, False, None, None, True, "numeric"
    )


def test_canonical_role_schemas_and_full_validation_are_exact() -> None:
    expected = {
        "derivative": (("source",),),
        "angle": (("source",),),
        "delta": (("fast", "slow"),),
        "braids": (("fast", "mid", "slow"),),
        "braid_instability": (("fast", "mid", "slow"),),
        "trap_area": (("fast", "slow"), ("fast", "mid", "slow")),
        "percent_span_angle": (("source_N",),),
        "angle_momentum": (("source_N",),),
        "universal_trend_classifier": (
            ("trend_peak", "trend_trough", "range_peak", "range_trough"),
        ),
        "sma": ((),),
    }
    for tool_key, schema in expected.items():
        assert financial_tool_source_role_schema(
            get_financial_tool_spec(tool_key)
        ) == schema

    validate_financial_tool_source_roles(
        get_financial_tool_spec("trap_area"), ("fast", "slow")
    )
    validate_financial_tool_source_roles(
        get_financial_tool_spec("trap_area"), ("fast", "mid", "slow")
    )
    validate_financial_tool_source_roles(
        get_financial_tool_spec("angle_momentum"),
        ("source_1", "source_2", "source_3"),
    )
    with pytest.raises(FinancialToolInputCompatibilityError, match="contiguous"):
        validate_financial_tool_source_roles(
            get_financial_tool_spec("angle_momentum"),
            ("source_1", "source_3"),
        )
    with pytest.raises(FinancialToolInputCompatibilityError, match="unique"):
        validate_financial_tool_source_roles(
            get_financial_tool_spec("delta"), ("fast", "fast")
        )


def test_partial_artifact_roles_preserve_exact_role_identity() -> None:
    derivative = get_financial_tool_spec("derivative")
    validate_financial_tool_inputs(
        derivative,
        (_source("source"),),
        allow_partial_roles=True,
        family_scope="dependencies",
    )
    with pytest.raises(FinancialToolInputCompatibilityError, match="roles"):
        validate_financial_tool_inputs(
            derivative,
            (_source("fast"),),
            allow_partial_roles=True,
            family_scope="dependencies",
        )
    with pytest.raises(FinancialToolInputCompatibilityError, match="roles"):
        validate_financial_tool_inputs(
            get_financial_tool_spec("sma"),
            (_source("source"),),
            allow_partial_roles=True,
            family_scope="dependencies",
        )


def test_dependency_outputs_must_be_numeric_and_analysis_usable() -> None:
    spec = get_financial_tool_spec("derivative")
    validate_financial_tool_inputs(spec, (_source("source"),))
    for source in (
        _source("source", analysis_usable=False),
        _source("source", value_type="categorical"),
        _source("source", value_type="boolean"),
    ):
        with pytest.raises(
            FinancialToolInputCompatibilityError, match="numeric analysis"
        ):
            validate_financial_tool_inputs(spec, (source,))


def test_recipe_and_artifact_family_scopes_remain_distinct() -> None:
    spec = get_financial_tool_spec("braids")
    recipe_sources = (
        _raw("fast", "high"),
        _source("mid", "oscillator", tool_key="rsi"),
        _raw("slow", "low"),
    )
    with pytest.raises(FinancialToolInputCompatibilityError, match="source-family"):
        validate_financial_tool_inputs(spec, recipe_sources, family_scope="all")
    validate_financial_tool_inputs(
        spec, recipe_sources, family_scope="dependencies"
    )

    same_family = replace(
        get_financial_tool_spec("delta"),
        construct_io=replace(
            get_financial_tool_spec("delta").construct_io,
            source_compatibility="same_family",
        ),
    )
    with pytest.raises(FinancialToolInputCompatibilityError, match="same-family"):
        validate_financial_tool_inputs(
            same_family,
            (_source("fast", "indicator"), _source("slow", "oscillator")),
        )


def test_utc_requires_exact_peaks_troughs_owner_and_outputs() -> None:
    spec = get_financial_tool_spec("universal_trend_classifier")
    parameters = {"trend_fractal_window": 5, "range_fractal_window": 3}
    valid = (
        _source("trend_peak", output_name="peak_fractal_5", tool_key="peaks_troughs"),
        _source("trend_trough", output_name="trough_fractal_5", tool_key="peaks_troughs"),
        _source("range_peak", output_name="peak_fractal_3", tool_key="peaks_troughs"),
        _source("range_trough", output_name="trough_fractal_3", tool_key="peaks_troughs"),
    )
    validate_financial_tool_inputs(spec, valid, parameters=parameters)
    with pytest.raises(FinancialToolInputCompatibilityError, match="one complete"):
        validate_financial_tool_inputs(
            spec,
            (*valid[:3], replace(valid[3], owner_id="other")),
            parameters=parameters,
        )
    with pytest.raises(FinancialToolInputCompatibilityError, match="trend/range"):
        validate_financial_tool_inputs(
            spec,
            (*valid[:3], replace(valid[3], output_name="trough_fractal_5")),
            parameters=parameters,
        )
