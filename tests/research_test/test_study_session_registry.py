from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.research import (
    ChartSessionState,
    PreparedStudy,
    ResearchStudyService,
    StudyDependencyError,
    StudyExecutionRequest,
    StudyInputSource,
    StudyValidationError,
)
from leonardo.financial_tools import FinancialToolCalculationResult

from tests.research_test.test_study_execution import accepted_context, apply_attempt
from tests.research_test.test_study_projection import resident


def _open_session(dataset):
    session = ChartSessionState(session_id="task-1017-session")
    opened = session.begin_dataset_open(dataset.market_id)
    assert session.accept_dataset_open(opened, dataset)
    return session


def test_duplicate_same_configuration_studies_keep_distinct_ids(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open_session(dataset)

    for _ in range(2):
        attempt = session.begin_study_apply()
        prepared = service.prepare_calculation(
            attempt,
            dataset,
            session.studies,
            StudyExecutionRequest("sma", {"period": 3}),
        )
        assert session.accept_study_apply(attempt, prepared)

    assert session.study_count == 2
    assert session.studies[0].study_id != session.studies[1].study_id


def test_resident_refresh_reprojects_without_recalculation(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open_session(dataset)
    attempt = session.begin_study_apply()
    prepared = service.prepare_calculation(
        attempt, dataset, (), StudyExecutionRequest("sma", {"period": 3})
    )
    assert session.accept_study_apply(attempt, prepared)

    first_attempt = session.begin_resident_slice_request()
    assert session.accept_resident_slice(first_attempt, resident(dataset, 0, 6))
    first = session.study_registry.get_projection(prepared.study.study_id)
    second_attempt = session.begin_resident_slice_request()
    assert session.accept_resident_slice(second_attempt, resident(dataset, 4, 10))
    shifted = session.study_registry.get_projection(prepared.study.study_id)

    assert first.ts_ms == dataset.ts_ms[0:6]
    assert shifted.ts_ms == dataset.ts_ms[4:10]


def test_dataset_generation_reset_clears_studies_and_rejects_late_apply(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open_session(dataset)
    late_attempt = session.begin_study_apply()
    prepared = service.prepare_calculation(
        late_attempt, dataset, (), StudyExecutionRequest("sma", {"period": 3})
    )

    session.begin_dataset_open(dataset.market_id)

    assert session.accept_study_apply(late_attempt, prepared) is False
    assert session.study_count == 0


def test_dependency_aware_removal_and_save_link_same_study(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open_session(dataset)
    source_attempt = session.begin_study_apply()
    source_prepared = service.prepare_calculation(
        source_attempt, dataset, (), StudyExecutionRequest("sma", {"period": 3})
    )
    assert session.accept_study_apply(source_attempt, source_prepared)
    source = session.studies[0]
    dependent_attempt = session.begin_study_apply()
    dependent_prepared = service.prepare_calculation(
        dependent_attempt,
        dataset,
        session.studies,
        StudyExecutionRequest(
            "derivative",
            {"order": 1},
            (
                StudyInputSource(
                    "source", "study", study_id=source.study_id, output_name="sma_3"
                ),
            ),
        ),
    )
    assert session.accept_study_apply(dependent_attempt, dependent_prepared)
    with pytest.raises(StudyDependencyError):
        session.remove_study(source.study_id)

    save_attempt = session.begin_study_save(source.study_id)
    outcome = service.save_study(
        save_attempt, dataset, source, session.studies
    )
    assert session.accept_study_save(save_attempt, outcome)
    assert session.study_count == 2
    assert session.study_registry.get(source.study_id).saved_link == outcome.saved_link


def test_forged_middle_timestamp_is_rejected_without_resident(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open_session(dataset)
    attempt = session.begin_study_apply()
    prepared = service.prepare_calculation(
        attempt, dataset, (), StudyExecutionRequest("sma", {"period": 3})
    )
    forged_frame = prepared.study.result.to_frame()
    forged_frame.loc[5, "ts_ms"] = int(forged_frame.loc[5, "ts_ms"]) + 1
    forged_result = FinancialToolCalculationResult(
        tool_key=prepared.study.result.tool_key,
        kind=prepared.study.result.kind,
        parameters=prepared.study.result.parameters,
        bindings=prepared.study.result.bindings,
        output_names=prepared.study.result.output_names,
        frame=forged_frame,
        analysis=prepared.study.result.analysis,
    )
    forged = PreparedStudy(replace(prepared.study, result=forged_result))

    with pytest.raises(StudyValidationError, match="timeline"):
        session.accept_study_apply(attempt, forged)
    assert session.study_count == 0
    assert session.study_apply_pending == 0


@pytest.mark.parametrize("forgery", ["foreign-session", "forged-timeline"])
def test_registered_source_must_match_session_and_complete_timeline(
    tmp_path: Path, forgery: str
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open_session(dataset)
    source = service.prepare_calculation(
        apply_attempt(dataset),
        dataset,
        (),
        StudyExecutionRequest("sma", {"period": 3}),
    ).study
    dependent_attempt = session.begin_study_apply()
    dependent = service.prepare_calculation(
        dependent_attempt,
        dataset,
        (source,),
        StudyExecutionRequest(
            "derivative",
            {},
            (
                StudyInputSource(
                    "source", "study", study_id=source.study_id, output_name="sma_3"
                ),
            ),
        ),
    )
    if forgery == "foreign-session":
        registered = replace(source, session_id="foreign-session")
    else:
        frame = source.result.to_frame()
        frame.loc[5, "ts_ms"] = int(frame.loc[5, "ts_ms"]) + 1
        registered = replace(
            source,
            result=FinancialToolCalculationResult(
                tool_key=source.result.tool_key,
                kind=source.result.kind,
                parameters=source.result.parameters,
                bindings=source.result.bindings,
                output_names=source.result.output_names,
                frame=frame,
                analysis=source.result.analysis,
            ),
        )
    session.study_registry.register(registered)

    assert session.accept_study_apply(dependent_attempt, dependent) is False
    assert session.study_apply_pending == 0
    assert session.study_count == 1
