from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.research import (
    ResearchStudyService,
    StudyExecutionRequest,
    StudyInputSource,
    StudyValidationError,
)
from leonardo.financial_tools import FinancialToolCalculationResult

from tests.research_test.test_study_execution import accepted_context, apply_attempt, prepare


def test_role_schema_and_service_owned_selectors_are_rejected(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    with pytest.raises(StudyValidationError, match="source roles"):
        service.prepare_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest("derivative", {}, ()),
        )
    with pytest.raises(StudyValidationError, match="service-owned"):
        service.prepare_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest(
                "delta",
                {"fast": "close"},
                (
                    StudyInputSource("fast", "ohlcv", column_name="high"),
                    StudyInputSource("slow", "ohlcv", column_name="low"),
                ),
            ),
        )


@pytest.mark.parametrize("tool_key", ["braids", "braid_instability"])
def test_mixed_family_braid_sources_and_output_eligibility_are_enforced(
    tmp_path: Path, tool_key: str
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    rsi = prepare(service, dataset, "rsi", parameters={"period": 3})
    hck = prepare(
        service,
        dataset,
        "hck",
        parameters={"fast_vwap_l": 3, "slow_vwap_l": 5},
    )
    derivative = prepare(
        service,
        dataset,
        "derivative",
        sources=(
            StudyInputSource(
                "source", "study", study_id=sma.study_id, output_name="sma_3"
            ),
        ),
        studies=(sma,),
    )
    mixed = prepare(
        service,
        dataset,
        tool_key,
        sources=(
            StudyInputSource("fast", "study", study_id=sma.study_id, output_name="sma_3"),
            StudyInputSource("mid", "study", study_id=rsi.study_id, output_name="rsi_3"),
            StudyInputSource(
                "slow", "study", study_id=derivative.study_id,
                output_name=derivative.result.output_names[0],
            ),
        ),
        studies=(sma, rsi, derivative),
    )
    assert mixed.result.row_count == dataset.row_count
    with pytest.raises(StudyValidationError, match="not analysis-usable"):
        prepare(
            service,
            dataset,
            "derivative",
            sources=(
                StudyInputSource(
                    "source", "study", study_id=hck.study_id, output_name="vwap_color"
                ),
            ),
            studies=(hck,),
        )


def test_stale_source_timeline_is_rejected(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    stale = replace(source, dataset_fingerprint="b" * 64)

    with pytest.raises(StudyValidationError, match="fingerprint"):
        prepare(
            service,
            dataset,
            "derivative",
            sources=(
                StudyInputSource(
                    "source", "study", study_id=stale.study_id, output_name="sma_3"
                ),
            ),
            studies=(stale,),
        )


def test_source_from_another_session_generation_is_rejected(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    foreign = replace(source, session_id="another-session")

    with pytest.raises(StudyValidationError, match="session generation"):
        prepare(
            service,
            dataset,
            "derivative",
            sources=(
                StudyInputSource(
                    "source", "study", study_id=foreign.study_id, output_name="sma_3"
                ),
            ),
            studies=(foreign,),
        )


def test_non_range_index_source_is_injected_by_position(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    source_frame = source.result.to_frame()
    source_frame.index = range(100, 100 + len(source_frame))
    non_range_result = FinancialToolCalculationResult(
        tool_key=source.result.tool_key,
        kind=source.result.kind,
        parameters=source.result.parameters,
        bindings=source.result.bindings,
        output_names=source.result.output_names,
        frame=source_frame,
        analysis=source.result.analysis,
    )
    non_range_source = replace(source, result=non_range_result)
    selector = (
        StudyInputSource("source", "study", study_id=source.study_id, output_name="sma_3"),
    )
    canonical = prepare(
        service, dataset, "derivative", sources=selector, studies=(source,)
    )
    non_range = prepare(
        service,
        dataset,
        "derivative",
        sources=selector,
        studies=(non_range_source,),
    )

    assert non_range.result.to_frame().equals(canonical.result.to_frame())


def test_utc_external_sources_require_exact_windows_and_one_owner(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    peaks = prepare(service, dataset, "peaks_troughs")

    def sources(
        trend_peak: str = "peak_fractal_5",
        trend_trough: str = "trough_fractal_5",
        range_peak: str = "peak_fractal_3",
        range_trough: str = "trough_fractal_3",
        *,
        range_owner=peaks,
    ):
        return (
            StudyInputSource(
                "trend_peak", "study", study_id=peaks.study_id, output_name=trend_peak
            ),
            StudyInputSource(
                "trend_trough", "study", study_id=peaks.study_id, output_name=trend_trough
            ),
            StudyInputSource(
                "range_peak", "study", study_id=range_owner.study_id, output_name=range_peak
            ),
            StudyInputSource(
                "range_trough",
                "study",
                study_id=range_owner.study_id,
                output_name=range_trough,
            ),
        )

    with pytest.raises(StudyValidationError, match="must be 'peak_fractal_5'"):
        prepare(
            service,
            dataset,
            "universal_trend_classifier",
            parameters={"fractal_window": 5, "trend_fractal_window": 5},
            sources=sources(trend_peak="peak_fractal_3"),
            studies=(peaks,),
        )

    with pytest.raises(StudyValidationError, match="must be 'peak_fractal_3'"):
        prepare(
            service,
            dataset,
            "universal_trend_classifier",
            sources=sources(range_peak="peak_fractal_5"),
            studies=(peaks,),
        )

    other = replace(peaks, study_id="other-peaks")
    with pytest.raises(StudyValidationError, match="one Peaks"):
        prepare(
            service,
            dataset,
            "universal_trend_classifier",
            sources=sources(range_owner=other),
            studies=(peaks, other),
        )

    exact = prepare(
        service,
        dataset,
        "universal_trend_classifier",
        parameters={"fractal_window": 5, "trend_fractal_window": 5},
        sources=sources(),
        studies=(peaks,),
    )
    assert tuple(ref.role for ref in exact.source_studies) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )
    assert tuple(ref.output_name for ref in exact.source_studies) == (
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_3",
        "trough_fractal_3",
    )

    stale = replace(peaks, dataset_fingerprint="b" * 64)
    with pytest.raises(StudyValidationError, match="fingerprint"):
        prepare(
            service,
            dataset,
            "universal_trend_classifier",
            sources=tuple(
                replace(source, study_id=stale.study_id) for source in sources()
            ),
            studies=(stale,),
        )
    foreign_market = replace(
        peaks,
        market_id=replace(peaks.market_id, symbol="ETHUSDT"),
    )
    with pytest.raises(StudyValidationError, match="MarketId"):
        prepare(
            service,
            dataset,
            "universal_trend_classifier",
            sources=tuple(
                replace(source, study_id=foreign_market.study_id)
                for source in sources()
            ),
            studies=(foreign_market,),
        )


@pytest.mark.parametrize("tool_key", ["braids", "braid_instability"])
def test_live_braid_sources_reject_ohlcv_and_preserve_all_indicator_inputs(
    tmp_path: Path, tool_key: str
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    ema = prepare(service, dataset, "ema", parameters={"period": 3})
    hma = prepare(service, dataset, "hma", parameters={"period": 3})

    with pytest.raises(StudyValidationError, match="source families"):
        prepare(
            service,
            dataset,
            tool_key,
            sources=(
                StudyInputSource("fast", "ohlcv", column_name="close"),
                StudyInputSource("mid", "ohlcv", column_name="open"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            ),
        )
    with pytest.raises(StudyValidationError, match="source families"):
        prepare(
            service,
            dataset,
            tool_key,
            sources=(
                StudyInputSource("fast", "ohlcv", column_name="close"),
                StudyInputSource(
                    "mid", "study", study_id=sma.study_id, output_name="sma_3"
                ),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            ),
            studies=(sma,),
        )

    accepted = prepare(
        service,
        dataset,
        tool_key,
        sources=tuple(
            StudyInputSource(role, "study", study_id=study.study_id, output_name=output)
            for role, study, output in zip(
                ("fast", "mid", "slow"),
                (sma, ema, hma),
                ("sma_3", "ema_3", "hma_3"),
                strict=True,
            )
        ),
        studies=(sma, ema, hma),
    )
    assert accepted.result.row_count == dataset.row_count


@pytest.mark.parametrize(
    ("tool_key", "roles"),
    [
        ("derivative", (("source", "close"),)),
        ("angle", (("source", "close"),)),
        ("delta", (("fast", "high"), ("slow", "low"))),
        ("trap_area", (("fast", "high"), ("slow", "low"))),
        ("percent_span_angle", (("source_1", "close"),)),
        ("angle_momentum", (("source_1", "close"),)),
        ("dynamic_binning", (("source_1", "close"),)),
    ],
)
def test_valid_ohlcv_capable_constructs_remain_accepted(
    tmp_path: Path, tool_key: str, roles: tuple[tuple[str, str], ...]
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        ResearchStudyService(artifacts),
        dataset,
        tool_key,
        sources=tuple(
            StudyInputSource(role, "ohlcv", column_name=column)
            for role, column in roles
        ),
    )

    assert study.result.row_count == dataset.row_count
