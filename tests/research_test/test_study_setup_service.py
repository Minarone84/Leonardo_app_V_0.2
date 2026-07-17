from __future__ import annotations

from pathlib import Path

from leonardo.research import (
    ResearchStudyService,
    ResearchStudySetupService,
    StudyEnvironmentStore,
    StudyExecutionRequest,
    StudyPresentationRegistry,
)

from tests.research_test.test_study_execution import accepted_context, prepare


def test_service_projects_catalog_and_constructs_environment_without_values(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = ResearchStudyService(artifacts)
    ema = prepare(runtime, dataset, "ema", parameters={"period": 20})
    rsi = prepare(runtime, dataset, "rsi", parameters={"period": 14})
    presentations = StudyPresentationRegistry()
    first = presentations.register(ema)
    second = presentations.register(rsi)
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    catalog = service.build_catalog(dataset, (ema, rsi))
    draft = service.build_environment(
        dataset,
        (ema, rsi),
        (first, second),
        display_name="Momentum",
    )

    assert len(catalog.tools) == 26
    assert len(catalog.ohlcv_sources) == 5
    assert {item.output_name for item in catalog.study_sources} == {"ema_20", "rsi_14"}
    assert tuple(item.entry_id for item in draft.entries) == ("entry_001", "entry_002")
    assert draft.entries[0].parameters["period"] == 20


def test_pure_environment_is_cross_market_compatible(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = ResearchStudyService(artifacts)
    study = prepare(runtime, dataset, "ema", parameters={"period": 20})
    presentations = StudyPresentationRegistry()
    presentation = presentations.register(study)
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )
    draft = service.build_environment(
        dataset, (study,), (presentation,), display_name="Pure"
    )
    environment = StudyEnvironmentStore(
        tmp_path / "other", id_factory=lambda: "pure"
    ).create(draft)

    assert service.compatibility(environment, dataset).compatible


def test_catalog_cancellation_is_observed(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )
    from leonardo.research import StudyOperationCancelled
    import pytest

    with pytest.raises(StudyOperationCancelled):
        service.build_catalog(dataset, (), cancellation_requested=lambda: True)
