from __future__ import annotations

import json
from pathlib import Path

from leonardo.research import ResearchStudyService, ResidentOHLCVSlice, StudyInputSource
from leonardo.research.study_projection import project_study

from tests.research_test.test_study_execution import FIXTURES, accepted_context, prepare


def resident(dataset, start: int = 4, end: int = 10) -> ResidentOHLCVSlice:
    return ResidentOHLCVSlice(
        market_id=dataset.market_id,
        dataset_fingerprint=dataset.file_sha256,
        base_index=start,
        end_index_exclusive=end,
        ts_ms=dataset.ts_ms[start:end],
        open=dataset.open[start:end],
        high=dataset.high[start:end],
        low=dataset.low[start:end],
        close=dataset.close[start:end],
        volume=dataset.volume[start:end],
        has_more_left=start > 0,
        has_more_right=end < dataset.row_count,
        first_timestamp_ms=dataset.ts_ms[start],
        last_timestamp_ms=dataset.ts_ms[end - 1],
    )


def test_exact_sma_and_hck_resident_projection(tmp_path: Path) -> None:
    expected = json.loads(
        (FIXTURES / "task_1017_study_execution_expected.json").read_text(encoding="utf-8")
    )
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    current = resident(dataset)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    hck = prepare(
        service,
        dataset,
        "hck",
        parameters={"fast_vwap_l": 3, "slow_vwap_l": 5},
    )

    sma_projection = project_study(sma, current)
    hck_projection = project_study(hck, current)

    assert {
        name: list(values) for name, values in sma_projection.render_series.items()
    } == expected["sma"]["resident_projection"]["render_series"]
    assert {
        name: list(values) for name, values in hck_projection.render_series.items()
    } == expected["hck"]["resident_projection"]["render_series"]
    assert {
        name: list(values) for name, values in hck_projection.style_driver_series.items()
    } == expected["hck"]["resident_projection"]["style_driver_series"]
    assert "vwap_color" not in hck_projection.render_series


def test_non_visual_projection_is_empty_and_refresh_is_positional(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    dynamic = prepare(
        service,
        dataset,
        "dynamic_binning",
        sources=(StudyInputSource("source_1", "ohlcv", column_name="close"),),
    )

    first = project_study(dynamic, resident(dataset, 0, 6))
    shifted = project_study(dynamic, resident(dataset, 4, 10))

    assert dict(first.render_series) == {}
    assert dict(first.style_driver_series) == {}
    assert shifted.ts_ms == dataset.ts_ms[4:10]
