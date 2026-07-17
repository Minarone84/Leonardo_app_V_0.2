from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from leonardo.research import (
    ChartSessionState,
    ResearchStudyService,
    StudyExecutionRequest,
)

from tests.research_test.test_study_execution import accepted_context
from tests.research_test.test_study_projection import resident


def _open(dataset):
    session = ChartSessionState(session_id="task-1018-session")
    attempt = session.begin_dataset_open(dataset.market_id)
    assert session.accept_dataset_open(attempt, dataset)
    return session


def _accept(session, service, dataset, tool_key="sma", parameters=None):
    attempt = session.begin_study_apply()
    prepared = service.prepare_calculation(
        attempt,
        dataset,
        session.studies,
        StudyExecutionRequest(tool_key, parameters or {}),
    )
    assert session.accept_study_apply(attempt, prepared)
    return prepared.study


def test_session_accepts_and_clears_study_presentation_atomically(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    session = _open(dataset)
    study = _accept(session, ResearchStudyService(artifacts), dataset)
    assert session.study_presentations()[0].study_id == study.study_id
    assert session.study_manager_entries()[0].pane_label == "Price"

    session.begin_dataset_open(dataset.market_id)
    assert session.studies == ()
    assert session.study_presentations() == ()


def test_style_and_visibility_survive_resident_refresh_and_save(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _open(dataset)
    study = _accept(session, service, dataset, parameters={"period": 3})
    presentation = session.study_presentations()[0]
    style = replace(presentation.signal_styles["sma_3"], color="#FFFFFF")
    edited = session.replace_study_line_style(study.study_id, "sma_3", style)
    session.set_study_visibility(study.study_id, False)

    refill = session.begin_resident_slice_request()
    assert session.accept_resident_slice(refill, resident(dataset, 2, 10))
    assert session.study_presentations()[0].revision == edited.revision + 1
    pane_id = session.study_presentations()[0].pane_id

    save_attempt = session.begin_study_save(study.study_id)
    outcome = service.save_study(save_attempt, dataset, study, session.studies)
    assert session.accept_study_save(save_attempt, outcome)
    after = session.study_presentations()[0]
    assert after.pane_id == pane_id
    assert after.revision == edited.revision + 1
    assert session.study_manager_entries()[0].saved is True

    session.remove_study(study.study_id)
    assert session.study_presentations() == ()
