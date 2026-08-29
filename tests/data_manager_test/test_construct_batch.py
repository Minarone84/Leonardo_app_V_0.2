from __future__ import annotations

import pytest

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager.construct_batch import (
    ConstructBatchCombination,
    ConstructBatchExpansionRequest,
    ConstructBatchSignal,
    ConstructBatchSourceScope,
    catalog_signals,
    current_ohlcv_signals,
    expand_construct_batch,
    project_batch_preview,
)
from leonardo.data_manager.creation_models import (
    BatchArtifactPlan,
    BatchArtifactSource,
)
from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
SOURCE = OHLCVSourceFingerprintV1(
    MARKET, "1" * 64, "2" * 64, 10, 1, 10, "committed", "ok", "1.0"
)


def _option(index, tool_key, kind, outputs):
    return DataManagerDirectArtifactOption(
        MARKET,
        f"{index:x}" * 64,
        f"{index + 8:x}" * 64,
        tool_key,
        kind,
        tool_key.replace("_", " ").title(),
        tuple(outputs),
        SOURCE,
    )


def _catalog():
    return DataManagerDirectArtifactCatalog(
        MARKET,
        SOURCE,
        (
            _option(1, "sma", "indicator", ("sma_20",)),
            _option(2, "ema", "indicator", ("ema_20",)),
            _option(3, "rsi", "oscillator", ("rsi_14",)),
            _option(4, "smi", "oscillator", ("smi_14_3",)),
            _option(5, "derivative", "construct", ("derivative_sma_20",)),
            _option(
                6,
                "braid_instability",
                "construct",
                ("braid_instability",),
            ),
        ),
        (),
    )


def _signals():
    return catalog_signals(_catalog())


def _request(tool_key, scope, **values):
    return ConstructBatchExpansionRequest(
        catalog=_catalog(),
        tool_key=tool_key,
        parameters=values.pop("parameters", {}),
        source_scope=scope,
        **values,
    )


def test_unary_scopes_expand_only_task_1062_catalogue_signals() -> None:
    derivative = expand_construct_batch(
        _request("derivative", ConstructBatchSourceScope.ALL_OSCILLATORS)
    )
    assert tuple(
        branch.sources[0].output_name for branch in derivative.branches
    ) == ("rsi_14", "smi_14_3")
    assert all(branch.sources[0].role == "source" for branch in derivative.branches)

    momentum = expand_construct_batch(
        _request("angle_momentum", ConstructBatchSourceScope.ALL_INDICATORS)
    )
    assert tuple(branch.sources[0].output_name for branch in momentum.branches) == (
        "sma_20",
        "ema_20",
    )
    assert all(branch.sources[0].role == "source_1" for branch in momentum.branches)

    angle = expand_construct_batch(
        _request("angle", ConstructBatchSourceScope.ALL_CONSTRUCTS)
    )
    assert tuple(branch.sources[0].output_name for branch in angle.branches) == (
        "derivative_sma_20",
        "braid_instability",
    )
    assert "braids" not in {signal.tool_key for signal in _signals()}
    assert "dynamic_binning" not in {signal.tool_key for signal in _signals()}


def test_current_ohlcv_sources_accept_exact_ohlc_and_reject_volume() -> None:
    signals = current_ohlcv_signals(_catalog())
    assert tuple(signal.column for signal in signals) == (
        "open",
        "high",
        "low",
        "close",
    )
    assert tuple(signal.label for signal in signals) == (
        "Open",
        "High",
        "Low",
        "Close",
    )
    for signal in signals:
        source = signal.as_source("source")
        assert source.source_kind == "current_ohlcv"
        assert source.market_id == MARKET
        assert source.source_ohlcv == SOURCE
        assert source.column == signal.column
        assert source.logical_artifact_id is None
        assert source.artifact_id is None
    with pytest.raises(ValueError, match="open, high, low, or close"):
        BatchArtifactSource.current_ohlcv("source", MARKET, SOURCE, "volume")


def test_raw_ohlc_expands_unary_delta_and_explicit_mixed_branches() -> None:
    open_, high, low, close = current_ohlcv_signals(_catalog())
    sma, _ema, rsi = _signals()[:3]

    unary = expand_construct_batch(
        _request(
            "derivative",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(close,),
        )
    )
    assert tuple(
        (source.role, source.source_kind, source.column)
        for source in unary.branches[0].sources
    ) == (("source", "current_ohlcv", "close"),)

    mixed_delta = expand_construct_batch(
        _request(
            "delta",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(close, sma),
            fixed_signal=close,
            fixed_role="fast",
        )
    )
    assert tuple(
        (source.role, source.source_kind, source.output_name)
        for source in mixed_delta.branches[0].sources
    ) == (
        ("fast", "current_ohlcv", "close"),
        ("slow", "artifact", "sma_20"),
    )

    raw_delta = expand_construct_batch(
        _request(
            "delta",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(high, low),
            fixed_signal=high,
            fixed_role="fast",
        )
    )
    assert tuple(source.column for source in raw_delta.branches[0].sources) == (
        "high",
        "low",
    )

    trap = expand_construct_batch(
        _request(
            "trap_area",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(close, sma, open_),
            combinations=(
                ConstructBatchCombination(fast=close, mid=sma, slow=open_),
            ),
        )
    )
    assert tuple(source.source_kind for source in trap.branches[0].sources) == (
        "current_ohlcv",
        "artifact",
        "current_ohlcv",
    )

    for tool_key in ("braids", "braid_instability"):
        branch = expand_construct_batch(
            _request(
                tool_key,
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(high, rsi, low),
                combinations=(
                    ConstructBatchCombination(fast=high, mid=rsi, slow=low),
                ),
            )
        ).branches[0]
        assert tuple(source.role for source in branch.sources) == (
            "fast",
            "mid",
            "slow",
        )
        assert tuple(source.source_kind for source in branch.sources) == (
            "current_ohlcv",
            "artifact",
            "current_ohlcv",
        )


def test_automatic_scopes_remain_saved_artifact_only() -> None:
    for scope in (
        ConstructBatchSourceScope.ALL_INDICATORS,
        ConstructBatchSourceScope.ALL_OSCILLATORS,
        ConstructBatchSourceScope.ALL_CONSTRUCTS,
    ):
        request = expand_construct_batch(_request("angle", scope))
        assert all(
            source.source_kind == "artifact"
            for branch in request.branches
            for source in branch.sources
        )


def test_selected_signals_and_delta_generate_only_explicit_pool_pairs() -> None:
    sma, ema, rsi = _signals()[:3]
    selected = expand_construct_batch(
        _request(
            "angle",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(rsi, sma),
        )
    )
    assert tuple(branch.sources[0].artifact_id for branch in selected.branches) == (
        rsi.artifact_id,
        sma.artifact_id,
    )

    fixed_fast = expand_construct_batch(
        _request(
            "delta",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(sma, ema, rsi),
            fixed_signal=sma,
            fixed_role="fast",
        )
    )
    assert tuple(
        tuple((source.role, source.output_name) for source in branch.sources)
        for branch in fixed_fast.branches
    ) == (
        (("fast", "sma_20"), ("slow", "ema_20")),
        (("fast", "sma_20"), ("slow", "rsi_14")),
    )

    fixed_slow = expand_construct_batch(
        _request(
            "delta",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(sma, ema),
            fixed_signal=ema,
            fixed_role="slow",
        )
    )
    assert tuple(
        (branch.sources[0].output_name, branch.sources[1].output_name)
        for branch in fixed_slow.branches
    ) == (("sma_20", "ema_20"),)


def test_explicit_trap_braids_and_instability_never_generate_cartesian_products() -> None:
    sma, ema, rsi, smi = _signals()[:4]
    selected = (sma, ema, rsi, smi)
    trap = expand_construct_batch(
        _request(
            "trap_area",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=selected,
            combinations=(
                ConstructBatchCombination(sma, ema),
                ConstructBatchCombination(sma, smi, rsi),
            ),
        )
    )
    assert tuple(tuple(source.role for source in branch.sources) for branch in trap.branches) == (
        ("fast", "slow"),
        ("fast", "mid", "slow"),
    )

    triples = (
        ConstructBatchCombination(sma, rsi, ema),
        ConstructBatchCombination(rsi, smi, sma),
    )
    for tool_key in ("braids", "braid_instability"):
        result = expand_construct_batch(
            _request(
                tool_key,
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=selected,
                combinations=triples,
            )
        )
        assert len(result.branches) == 2
        assert all(
            tuple(source.role for source in branch.sources)
            == ("fast", "mid", "slow")
            for branch in result.branches
        )


def test_expansion_rejects_sources_outside_catalogue_and_projects_only_real_rows() -> None:
    signal = _signals()[0]
    forged = ConstructBatchSignal(
        signal.logical_artifact_id,
        "f" * 64,
        signal.output_name,
        signal.tool_key,
        signal.kind,
        signal.label,
    )
    with pytest.raises(ValueError, match="current catalogue"):
        expand_construct_batch(
            _request(
                "angle",
                ConstructBatchSourceScope.SELECTED_SIGNALS,
                selected_signals=(forged,),
            )
        )

    request = expand_construct_batch(
        _request(
            "angle",
            ConstructBatchSourceScope.SELECTED_SIGNALS,
            selected_signals=(signal,),
        )
    )
    plan = BatchArtifactPlan(
        request=request,
        branch_recipe_ids=("a" * 64,),
        branch_reuse_current=(True,),
        recipe_ids=("a" * 64,),
        dependency_edges=(),
        execution_stages=(("a" * 64,),),
        new_recipe_ids=(),
        reusable_recipe_ids=("a" * 64,),
        new_logical_artifact_ids=(),
        reusable_logical_artifact_ids=("b" * 64,),
        naming_collisions=(),
        unsupported_combinations=(),
        blockers=(),
    )
    rows = project_batch_preview(plan)
    assert len(rows) == 1
    assert tuple(rows[0].__dataclass_fields__) == (
        "sources",
        "construct",
        "parameters",
        "inputs",
        "result",
    )
    assert rows[0].sources == "Sma / sma_20"
    assert rows[0].inputs == "source=Sma / sma_20"
    assert rows[0].result == "Reuse Current"
