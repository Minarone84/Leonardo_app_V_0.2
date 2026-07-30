from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.research import (
    ChartSessionState,
    PreparedStudy,
    ResearchStudyService,
    StudyArtifactRequest,
    StudyDependencyError,
    StudyEditAttempt,
    StudyExecutionRequest,
    StudyInputSource,
    StudyUserMetadata,
    StudyValidationError,
)
from tests.research_test.test_study_execution import accepted_context
from tests.research_test.test_study_projection import resident
from tests.research_test.test_study_artifact_apply_save import (
    _artifact_input,
    _save_attempt,
)
from tests.research_test.test_study_execution import apply_attempt, prepare


def _session(dataset) -> ChartSessionState:
    session = ChartSessionState(session_id="task-1017-session")
    opened = session.begin_dataset_open(dataset.market_id)
    assert session.accept_dataset_open(opened, dataset)
    sliced = session.begin_resident_slice_request()
    assert session.accept_resident_slice(sliced, resident(dataset, 0, 10))
    return session


def _apply(service, session, request):
    dataset = session.dataset
    assert dataset is not None
    attempt = session.begin_study_apply()
    prepared = service.prepare_calculation(
        attempt, dataset, session.studies, request
    )
    assert session.accept_study_apply(attempt, prepared)
    return prepared.study


def _save(service, session, study_id):
    dataset = session.dataset
    assert dataset is not None
    attempt = session.begin_study_save(study_id)
    study = session.study_registry.get(study_id)
    outcome = service.save_study(attempt, dataset, study, session.studies)
    assert session.accept_study_save(attempt, outcome)
    return outcome


def _edit(service, session, study_id, request):
    dataset = session.dataset
    assert dataset is not None
    attempt = session.begin_study_edit(study_id)
    prepared = service.prepare_edit(
        attempt, dataset, session.studies, request
    )
    assert session.accept_study_edit(attempt, prepared)
    return session.study_registry.get(study_id)


def test_unsaved_edit_replaces_same_study_and_reconciles_style(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _session(dataset)
    original = _apply(
        service, session, StudyExecutionRequest("sma", {"period": 3})
    )
    presentation = session.study_presentations()[0]
    old_name = original.renderable_output_names[0]
    custom = replace(
        presentation.signal_styles[old_name],
        color="#FFFFFF",
        line_width=3.0,
        line_pattern="dotted",
        visible=False,
    )
    session.replace_study_line_style(original.study_id, old_name, custom)
    session.set_study_visibility(original.study_id, False)
    old_projection = session.study_registry.get_projection(original.study_id)

    edited = _edit(
        service,
        session,
        original.study_id,
        StudyExecutionRequest("sma", {"period": 5}),
    )

    assert edited.study_id == original.study_id
    assert edited.source_kind == "calculation"
    assert edited.saved_link is None
    assert edited.setup_request == edited.edit_request
    assert edited.setup_request.parameters == {"period": 5}
    assert not edited.result.to_frame().equals(original.result.to_frame())
    new_name = edited.renderable_output_names[0]
    current = session.study_presentations()[0]
    assert not current.visible
    assert current.pane_id == presentation.pane_id
    assert current.revision == 2
    assert tuple(current.signal_styles) == (new_name,)
    assert old_name not in current.signal_styles
    assert current.signal_styles[new_name] == replace(custom, output_name=new_name)
    assert session.study_registry.get_projection(original.study_id) != old_projection


def test_edit_preserves_display_name_and_user_metadata_at_both_boundaries(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _session(dataset)
    metadata = StudyUserMetadata(
        important=True,
        dataset_role="supporting_indicator",
        description="Original metadata",
    )
    original = _apply(
        service,
        session,
        StudyExecutionRequest(
            "sma",
            {"period": 3},
            display_name="Named SMA",
            user_metadata=metadata,
        ),
    )
    before = (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    )

    renamed_request = StudyExecutionRequest(
        "sma",
        {"period": 5},
        display_name="Renamed SMA",
        user_metadata=metadata,
    )
    renamed_attempt = session.begin_study_edit(original.study_id)
    with pytest.raises(StudyValidationError, match="display name"):
        service.prepare_edit(
            renamed_attempt,
            dataset,
            session.studies,
            renamed_request,
        )
    assert session.settle_study_edit_failure(renamed_attempt)
    assert (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    ) == before

    changed_metadata = StudyUserMetadata(
        important=False,
        dataset_role="volume",
        description="Changed metadata",
    )
    metadata_request = StudyExecutionRequest(
        "sma",
        {"period": 5},
        display_name="Named SMA",
        user_metadata=changed_metadata,
    )
    metadata_attempt = session.begin_study_edit(original.study_id)
    with pytest.raises(StudyValidationError, match="user metadata"):
        service.prepare_edit(
            metadata_attempt,
            dataset,
            session.studies,
            metadata_request,
        )
    assert session.settle_study_edit_failure(metadata_attempt)
    assert (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    ) == before

    valid_request = StudyExecutionRequest(
        "sma",
        {"period": 5},
        display_name="Named SMA",
        user_metadata=metadata,
    )
    valid_attempt = session.begin_study_edit(original.study_id)
    prepared = service.prepare_edit(
        valid_attempt,
        dataset,
        session.studies,
        valid_request,
    )
    forged_renamed_request = replace(
        valid_request,
        display_name="Renamed SMA",
    )
    forged_renamed = PreparedStudy(
        replace(
            prepared.study,
            display_name="Renamed SMA",
            setup_request=forged_renamed_request,
            edit_request=forged_renamed_request,
        )
    )
    with pytest.raises(StudyValidationError, match="display name"):
        session.accept_study_edit(valid_attempt, forged_renamed)
    assert (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    ) == before

    second_attempt = session.begin_study_edit(original.study_id)
    second_prepared = service.prepare_edit(
        second_attempt,
        dataset,
        session.studies,
        valid_request,
    )
    forged_metadata_request = replace(
        valid_request,
        user_metadata=changed_metadata,
    )
    forged_metadata = PreparedStudy(
        replace(
            second_prepared.study,
            user_metadata=changed_metadata,
            setup_request=forged_metadata_request,
            edit_request=forged_metadata_request,
        )
    )
    with pytest.raises(StudyValidationError, match="user metadata"):
        session.accept_study_edit(second_attempt, forged_metadata)
    assert (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    ) == before


def test_saved_and_artifact_loaded_edits_leave_artifacts_immutable(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _session(dataset)
    study = _apply(
        service, session, StudyExecutionRequest("sma", {"period": 3})
    )
    saved = _save(service, session, study.study_id)
    before = artifacts.load_artifact(
        dataset.market_id,
        saved.saved_link.kind,
        saved.saved_link.tool_key,
        saved.saved_link.artifact_id,
    )
    count = len(artifacts.list_artifacts(dataset.market_id))

    edited = _edit(
        service,
        session,
        study.study_id,
        StudyExecutionRequest("sma", {"period": 5}),
    )
    assert edited.saved_link is None
    assert len(artifacts.list_artifacts(dataset.market_id)) == count
    after = artifacts.load_artifact(
        dataset.market_id,
        saved.saved_link.kind,
        saved.saved_link.tool_key,
        saved.saved_link.artifact_id,
    )
    assert after.metadata == before.metadata
    assert after.frame.equals(before.frame)

    apply_attempt = session.begin_study_apply()
    loaded = service.prepare_artifact(
        apply_attempt,
        dataset,
        StudyArtifactRequest(
            saved.saved_link.kind,
            saved.saved_link.tool_key,
            saved.saved_link.artifact_id,
        ),
    )
    assert loaded.study.edit_request == StudyExecutionRequest(
        "sma", {"period": 3}
    )
    assert session.accept_study_apply(apply_attempt, loaded)
    artifact_study = loaded.study
    edited_artifact = _edit(
        service,
        session,
        artifact_study.study_id,
        artifact_study.edit_request,
    )
    assert edited_artifact.source_kind == "calculation"
    assert edited_artifact.saved_link is None
    assert len(artifacts.list_artifacts(dataset.market_id)) == count


def test_artifact_dependency_edit_request_reconstructs_canonical_source(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _session(dataset)
    source = _apply(
        service, session, StudyExecutionRequest("sma", {"period": 3})
    )
    source_saved = _save(service, session, source.study_id)
    derivative = _apply(
        service,
        session,
        StudyExecutionRequest(
            "derivative",
            {"order": 1},
            (
                StudyInputSource(
                    "source",
                    "artifact",
                    artifact_kind="indicator",
                    artifact_tool_key="sma",
                    artifact_id=source_saved.saved_link.artifact_id,
                    output_name="sma_3",
                ),
            ),
        ),
    )
    derivative_saved = _save(service, session, derivative.study_id)
    attempt = session.begin_study_apply()
    loaded = service.prepare_artifact(
        attempt,
        dataset,
        StudyArtifactRequest(
            derivative.result.kind,
            "derivative",
            derivative_saved.saved_link.artifact_id,
        ),
    )
    request = loaded.study.edit_request
    assert request.parameters == {"order": 1}
    assert tuple(source.role for source in request.input_sources) == ("source",)
    source_request = request.input_sources[0]
    assert source_request.source_kind == "artifact"
    assert source_request.artifact_kind == "indicator"
    assert source_request.artifact_tool_key == "sma"
    assert source_request.artifact_id == source_saved.saved_link.artifact_id
    assert source_request.output_name == "sma_3"
    unchanged = service.prepare_edit(
        StudyEditAttempt(
            session_id=attempt.session_id,
            generation=attempt.generation,
            request_id="edit-request",
            study_id=loaded.study.study_id,
            market_id=attempt.market_id,
            dataset_fingerprint=attempt.dataset_fingerprint,
        ),
        dataset,
        (*session.studies, loaded.study),
        request,
    )
    assert unchanged.study.result.output_names == loaded.study.result.output_names


def test_edit_dependency_fencing_mutual_exclusion_and_failure_safety(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    session = _session(dataset)
    source = _apply(
        service, session, StudyExecutionRequest("sma", {"period": 3})
    )
    dependent = _apply(
        service,
        session,
        StudyExecutionRequest(
            "derivative",
            {"order": 1},
            (
                StudyInputSource(
                    "source",
                    "study",
                    study_id=source.study_id,
                    output_name="sma_3",
                ),
            ),
        ),
    )
    before = (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    )
    with pytest.raises(StudyDependencyError, match="cannot be edited"):
        session.begin_study_edit(source.study_id)
    assert (
        session.studies,
        session.study_registry.projection_snapshot(),
        session.study_presentations(),
    ) == before

    edit_attempt = session.begin_study_edit(dependent.study_id)
    with pytest.raises(Exception, match="Edit is already pending"):
        session.begin_study_save(dependent.study_id)
    assert session.settle_study_edit_failure(edit_attempt)
    save_attempt = session.begin_study_save(dependent.study_id)
    with pytest.raises(Exception, match="Save is already pending"):
        session.begin_study_edit(dependent.study_id)
    assert session.settle_study_save_failure(save_attempt)

    edit_attempt = session.begin_study_edit(dependent.study_id)
    original = session.study_registry.get(dependent.study_id)
    with pytest.raises(StudyValidationError, match="depend on itself"):
        service.prepare_edit(
            edit_attempt,
            dataset,
            session.studies,
            StudyExecutionRequest(
                "derivative",
                {"order": 1},
                (
                    StudyInputSource(
                        "source",
                        "study",
                        study_id=dependent.study_id,
                        output_name=dependent.analysis_usable_output_names[0],
                    ),
                ),
            ),
        )
    assert session.settle_study_edit_failure(edit_attempt)
    assert session.study_registry.get(dependent.study_id) == original

    stale = session.begin_study_edit(dependent.study_id)
    prepared = service.prepare_edit(
        stale,
        dataset,
        session.studies,
        dependent.edit_request,
    )
    assert session.settle_study_edit_failure(stale)
    assert not session.accept_study_edit(stale, prepared)
    assert session.study_registry.get(dependent.study_id) == original


def test_utc_artifact_edit_reconstruction_preserves_four_ordered_roles(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    peaks = prepare(service, dataset, "peaks_troughs")
    peaks_saved = service.save_study(
        _save_attempt(peaks), dataset, peaks, (peaks,)
    )
    utc = prepare(
        service,
        dataset,
        "universal_trend_classifier",
        parameters={
            "fractal_window": 5,
            "trend_fractal_window": 5,
            "range_fractal_window": 3,
        },
        sources=(
            _artifact_input("trend_peak", peaks_saved, "peak_fractal_5"),
            _artifact_input("trend_trough", peaks_saved, "trough_fractal_5"),
            _artifact_input("range_peak", peaks_saved, "peak_fractal_3"),
            _artifact_input("range_trough", peaks_saved, "trough_fractal_3"),
        ),
    )
    utc_saved = service.save_study(
        _save_attempt(utc), dataset, utc, (utc,)
    )
    loaded = service.prepare_artifact(
        apply_attempt(dataset),
        dataset,
        StudyArtifactRequest(
            utc.result.kind,
            "universal_trend_classifier",
            utc_saved.saved_link.artifact_id,
        ),
    ).study
    request = loaded.edit_request
    assert tuple(source.role for source in request.input_sources) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )
    assert request.parameters["trend_fractal_window"] == 5
    assert request.parameters["range_fractal_window"] == 3
    assert "fractal_window" not in request.parameters
    assert all(
        source.source_kind == "artifact"
        and source.artifact_tool_key == "peaks_troughs"
        and source.artifact_id == peaks_saved.saved_link.artifact_id
        for source in request.input_sources
    )


def test_mixed_implicit_ohlcv_and_artifact_roles_reconstruct_in_order(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    slow = prepare(service, dataset, "sma", parameters={"period": 3})
    slow_saved = service.save_study(
        _save_attempt(slow), dataset, slow, (slow,)
    )
    delta = prepare(
        service,
        dataset,
        "delta",
        sources=(
            StudyInputSource("fast", "ohlcv", column_name="high"),
            _artifact_input("slow", slow_saved, "sma_3"),
        ),
    )
    delta_saved = service.save_study(
        _save_attempt(delta), dataset, delta, (delta,)
    )
    loaded = service.prepare_artifact(
        apply_attempt(dataset),
        dataset,
        StudyArtifactRequest(
            "construct", "delta", delta_saved.saved_link.artifact_id
        ),
    ).study
    assert tuple(source.role for source in loaded.edit_request.input_sources) == (
        "fast",
        "slow",
    )
    assert loaded.edit_request.input_sources[0] == StudyInputSource(
        "fast", "ohlcv", column_name="high"
    )
    assert loaded.edit_request.input_sources[1].source_kind == "artifact"
    assert (
        loaded.edit_request.input_sources[1].artifact_id
        == slow_saved.saved_link.artifact_id
    )
