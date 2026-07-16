from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

from leonardo.artifacts import ArtifactSourceRefV1
from leonardo.financial_tools import calculate_financial_tool
from leonardo.research import (
    ResearchStudyService,
    StudyDependencyRef,
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudyInputSource,
    StudyValidationError,
)

from tests.research_test.test_study_execution import accepted_context, prepare


def test_input_sources_enforce_exact_field_combinations() -> None:
    assert StudyInputSource("source", "ohlcv", column_name="close").column_name == "close"
    with pytest.raises(StudyValidationError):
        StudyInputSource("source", "ohlcv", column_name="close", output_name="x")
    with pytest.raises(StudyValidationError):
        StudyInputSource("source", "study", study_id="study")
    with pytest.raises(StudyValidationError):
        StudyArtifactRequest("indicator", "sma", "A" * 64)


def test_artifact_request_preserves_omitted_display_override() -> None:
    omitted = StudyArtifactRequest("indicator", "sma", "a" * 64)
    explicit = StudyArtifactRequest(
        "indicator", "sma", "a" * 64, display_name="Explicit SMA"
    )

    assert omitted.display_name is None
    assert explicit.display_name == "Explicit SMA"
    with pytest.raises(StudyValidationError):
        StudyArtifactRequest("indicator", "sma", "a" * 64, display_name=" ")


def test_request_defensively_copies_parameters_and_sources() -> None:
    parameters = {"period": 3}
    sources = [StudyInputSource("source", "ohlcv", column_name="close")]
    request = StudyExecutionRequest("derivative", parameters, tuple(sources))
    parameters["period"] = 99
    sources.clear()

    assert request.parameters == {"period": 3}
    assert len(request.input_sources) == 1
    with pytest.raises(TypeError):
        request.parameters["period"] = 4


def test_chart_study_retains_defensive_full_result_and_task_1014_metadata(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        ResearchStudyService(artifacts), dataset, "hck", parameters={"fast_vwap_l": 3, "slow_vwap_l": 5}
    )
    external = study.result.to_frame()
    external.loc[:, "fast_vwap"] = 0.0

    assert study.pane_role == "price"
    assert study.renderable_output_names == ("fast_vwap", "slow_vwap")
    assert study.style_driver_output_names == ("vwap_color",)
    assert study.analysis_usable_output_names == ("fast_vwap", "slow_vwap")
    assert study.result.to_frame()["fast_vwap"].iloc[-1] != 0.0


def test_artifact_study_requires_saved_link_and_no_transient_dependencies(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from leonardo.research import StudyDependencyRef, StudySavedLink

    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(ResearchStudyService(artifacts), dataset, "sma", parameters={"period": 3})
    with pytest.raises(StudyValidationError, match="saved_link"):
        replace(study, source_kind="artifact")
    link = StudySavedLink("indicator", "sma", "a" * 64, "b" * 64)
    with pytest.raises(StudyValidationError, match="transient"):
        replace(
            study,
            source_kind="artifact",
            saved_link=link,
            source_studies=(StudyDependencyRef("source", "source-study", "sma_3"),),
        )


def test_chart_study_rejects_missing_invented_and_self_lineage(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
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

    with pytest.raises(StudyValidationError, match="lineage roles"):
        replace(derivative, source_studies=())
    with pytest.raises(StudyValidationError, match="lineage roles"):
        replace(
            sma,
            source_artifacts=(
                ArtifactSourceRefV1("source", "a" * 64, "sma_3"),
            ),
        )
    with pytest.raises(StudyValidationError, match="depend on itself"):
        replace(
            derivative,
            source_studies=(
                StudyDependencyRef("source", derivative.study_id, "sma_3"),
            ),
        )


def test_chart_study_accepts_ohlcv_bound_derivative_without_lineage(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    derivative = prepare(
        ResearchStudyService(artifacts),
        dataset,
        "derivative",
        sources=(StudyInputSource("source", "ohlcv", column_name="close"),),
    )

    assert derivative.result.bindings == {"source": "close"}
    assert derivative.source_studies == ()
    assert derivative.source_artifacts == ()


@pytest.mark.parametrize("tool_key", ["braids", "braid_instability"])
@pytest.mark.parametrize("selectors", ["all-ohlcv", "mixed"])
def test_chart_study_rejects_forbidden_implicit_ohlcv_braid_sources(
    tmp_path: Path, tool_key: str, selectors: str
) -> None:
    dataset, artifacts, frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    base = prepare(service, dataset, "ema", parameters={"period": 3})
    parameters = {"fast": "close", "mid": "open", "slow": "low"}
    dependencies = ()
    working = frame.copy(deep=True)
    if selectors == "mixed":
        working["__research_mid"] = source.result.to_frame()["sma_3"].to_numpy()
        parameters["mid"] = "__research_mid"
        dependencies = (StudyDependencyRef("mid", source.study_id, "sma_3"),)
    result = calculate_financial_tool(tool_key, working, parameters)

    with pytest.raises(StudyValidationError, match="source families"):
        replace(base, result=result, source_studies=dependencies)
