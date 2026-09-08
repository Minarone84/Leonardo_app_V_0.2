from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from leonardo.artifacts import ArtifactService
from leonardo.data import MarketId
from leonardo.financial_tools import ALL_FINANCIAL_TOOL_SPECS
from leonardo.ohlcv.store import Candle, OHLCVStore
from leonardo.research import (
    HistoricalDataset,
    ResearchStudyService,
    StudyApplyAttempt,
    StudyExecutionRequest,
    StudyInputSource,
)
from leonardo.recipes import PortableRecipeStore


FIXTURES = Path(__file__).parent / "fixtures"


def accepted_context(root: Path) -> tuple[HistoricalDataset, ArtifactService, pd.DataFrame]:
    frame = pd.read_csv(FIXTURES / "task_1017_study_execution_input.csv")
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    csv_path, csv_hash = publish_accepted_frame(root, frame, market)
    dataset = HistoricalDataset(
        market_id=market,
        csv_path=csv_path,
        file_sha256=csv_hash,
        row_count=len(frame),
        first_timestamp_ms=int(frame.ts_ms.iloc[0]),
        last_timestamp_ms=int(frame.ts_ms.iloc[-1]),
        ts_ms=tuple(int(value) for value in frame.ts_ms),
        open=tuple(float(value) for value in frame.open),
        high=tuple(float(value) for value in frame.high),
        low=tuple(float(value) for value in frame.low),
        close=tuple(float(value) for value in frame.close),
        volume=tuple(float(value) for value in frame.volume),
    )
    return dataset, ArtifactService(root), frame


def research_service(root: Path, artifacts: ArtifactService) -> ResearchStudyService:
    return ResearchStudyService(
        artifacts,
        PortableRecipeStore(root / "data_manager"),
    )


def publish_accepted_frame(
    root: Path, frame: pd.DataFrame, market: MarketId
) -> tuple[Path, str]:
    store = OHLCVStore(root)
    candles = [
        Candle(
            int(row.ts_ms),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
        )
        for row in frame.itertuples(index=False)
    ]
    store.write(market, candles, source="task-1017", persistence_status="committed")
    csv_path = store.csv_path(market)
    sidecar_path = store.sidecar_path(market)
    csv_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    sidecar_hash = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    csv_stat = csv_path.stat()
    sidecar_stat = sidecar_path.stat()
    store.publish_validation(
        market,
        expected_csv_size=csv_stat.st_size,
        expected_csv_mtime_ns=csv_stat.st_mtime_ns,
        expected_csv_sha256=csv_hash,
        expected_sidecar_size=sidecar_stat.st_size,
        expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=sidecar_hash,
        status="ok",
        row_count=len(frame),
        first_timestamp_ms=int(frame.ts_ms.iloc[0]),
        last_timestamp_ms=int(frame.ts_ms.iloc[-1]),
        warnings=(),
        issue_codes=(),
        error_count=0,
        warning_count=0,
        validator="task-1017-test",
    )
    return csv_path, csv_hash


def apply_attempt(dataset: HistoricalDataset, *, study_id: str | None = None) -> StudyApplyAttempt:
    return StudyApplyAttempt(
        session_id="task-1017-session",
        generation=1,
        request_id=uuid4().hex,
        study_id=study_id or uuid4().hex,
        market_id=dataset.market_id,
        dataset_fingerprint=dataset.file_sha256,
    )


def prepare(
    service: ResearchStudyService,
    dataset: HistoricalDataset,
    tool_key: str,
    *,
    parameters: dict[str, object] | None = None,
    sources: tuple[StudyInputSource, ...] = (),
    studies=(),
):
    return service.prepare_calculation(
        apply_attempt(dataset),
        dataset,
        tuple(studies),
        StudyExecutionRequest(
            tool_key=tool_key,
            parameters=parameters or {},
            input_sources=sources,
        ),
    ).study


def test_full_dataset_calculation_and_transient_alias_are_exact(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    derivative = prepare(
        service,
        dataset,
        "derivative",
        parameters={"order": 1},
        sources=(
            StudyInputSource(
                role="source",
                source_kind="study",
                study_id=sma.study_id,
                output_name="sma_3",
            ),
        ),
        studies=(sma,),
    )

    assert derivative.result.bindings == {"source": "__research_source"}
    assert derivative.result.output_names == ("research_source__d1",)
    assert derivative.source_studies[0].study_id == sma.study_id
    assert derivative.result.row_count == dataset.row_count
    expected = json.loads(
        (FIXTURES / "task_1017_study_execution_expected.json").read_text(encoding="utf-8")
    )
    values = derivative.result.to_frame()["research_source__d1"].tolist()
    assert [None if pd.isna(value) else value for value in values] == expected[
        "transient_derivative"
    ]["full_frame"]["research_source__d1"]


def test_all_26_tools_prepare_against_full_dataset(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    indicator_sources = (
        prepare(service, dataset, "sma", parameters={"period": 3}),
        prepare(service, dataset, "ema", parameters={"period": 3}),
        prepare(service, dataset, "hma", parameters={"period": 3}),
    )
    output_names = tuple(study.result.output_names[0] for study in indicator_sources)
    peaks_troughs_source = prepare(
        service,
        dataset,
        "peaks_troughs",
    )

    prepared_keys: set[str] = set()
    for key in ALL_FINANCIAL_TOOL_SPECS:
        parameters: dict[str, object] = {}
        sources: tuple[StudyInputSource, ...] = ()
        studies = ()
        if key == "universal_trend_classifier":
            parameters = {
                "fractal_window": 3,
                "trend_fractal_window": 5,
                "range_fractal_window": 3,
            }
            studies = (peaks_troughs_source,)
            sources = (
                StudyInputSource(
                    "trend_peak",
                    "study",
                    study_id=peaks_troughs_source.study_id,
                    output_name="peak_fractal_5",
                ),
                StudyInputSource(
                    "trend_trough",
                    "study",
                    study_id=peaks_troughs_source.study_id,
                    output_name="trough_fractal_5",
                ),
                StudyInputSource(
                    "range_peak",
                    "study",
                    study_id=peaks_troughs_source.study_id,
                    output_name="peak_fractal_3",
                ),
                StudyInputSource(
                    "range_trough",
                    "study",
                    study_id=peaks_troughs_source.study_id,
                    output_name="trough_fractal_3",
                ),
            )
        elif key in {"derivative", "angle"}:
            sources = (StudyInputSource("source", "ohlcv", column_name="close"),)
        elif key == "delta":
            sources = (
                StudyInputSource("fast", "ohlcv", column_name="high"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            )
        elif key in {"braids", "braid_instability"}:
            studies = indicator_sources
            sources = tuple(
                StudyInputSource(
                    role,
                    "study",
                    study_id=study.study_id,
                    output_name=output,
                )
                for role, study, output in zip(
                    ("fast", "mid", "slow"), indicator_sources, output_names, strict=True
                )
            )
        elif key == "trap_area":
            sources = (
                StudyInputSource("fast", "ohlcv", column_name="high"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            )
        elif key in {"dynamic_binning", "percent_span_angle", "angle_momentum"}:
            sources = (StudyInputSource("source_1", "ohlcv", column_name="close"),)
        study = prepare(
            service,
            dataset,
            key,
            parameters=parameters,
            sources=sources,
            studies=studies,
        )
        assert study.result.row_count == dataset.row_count
        if key == "universal_trend_classifier":
            assert study.result.parameters["fractal_window"] == 5
            assert study.result.parameters["trend_fractal_window"] == 5
            assert study.result.parameters["range_fractal_window"] == 3
            assert tuple(ref.role for ref in study.source_studies) == (
                "trend_peak",
                "trend_trough",
                "range_peak",
                "range_trough",
            )
            assert tuple(ref.output_name for ref in study.source_studies) == (
                "peak_fractal_5",
                "trough_fractal_5",
                "peak_fractal_3",
                "trough_fractal_3",
            )
            assert {
                ref.study_id
                for ref in study.source_studies
            } == {peaks_troughs_source.study_id}
        prepared_keys.add(study.result.tool_key)

    assert prepared_keys == set(ALL_FINANCIAL_TOOL_SPECS)
