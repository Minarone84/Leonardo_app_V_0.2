from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.financial_tools import (
    ALL_FINANCIAL_TOOL_SPECS,
    calculate_financial_tool,
    get_financial_tool_spec,
)
from leonardo.research import (
    ResearchStudyService,
    StudyInputSource,
    StudySaveAttempt,
    ResearchStudySetupService,
    StudyEnvironmentDraft,
    StudyEnvironmentEntryV1,
    StudyEnvironmentPresentationV1,
    StudyEnvironmentStore,
    StudyEnvironmentV1,
    StudyEnvironmentValidationError,
    StudyExecutionRequest,
    StudyPresentationRegistry,
    StudyUserMetadata,
)

from tests.research_test.test_study_execution import (
    accepted_context,
    prepare,
    research_service,
)


def _save_attempt(study) -> StudySaveAttempt:
    return StudySaveAttempt(
        session_id=study.session_id,
        generation=study.generation,
        request_id="catalog-save-" + study.study_id,
        study_id=study.study_id,
        market_id=study.market_id,
        dataset_fingerprint=study.dataset_fingerprint,
    )


def test_service_projects_catalog_and_constructs_environment_without_values(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
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

    assert len(catalog.tools) == 25
    assert "dynamic_binning" not in tuple(item.key for item in catalog.tools)
    assert len(catalog.ohlcv_sources) == 5
    assert {item.output_name for item in catalog.study_sources} == {"ema_20", "rsi_14"}
    assert tuple(item.entry_id for item in draft.entries) == ("entry_001", "entry_002")
    assert draft.entries[0].parameters["period"] == 20


def test_environment_capture_uses_stable_dependency_order_for_three_levels(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
    sma = prepare(runtime, dataset, "sma", parameters={"period": 3})
    derivative = prepare(
        runtime,
        dataset,
        "derivative",
        parameters={"order": 1},
        sources=(
            StudyInputSource(
                "source", "study", study_id=sma.study_id, output_name="sma_3"
            ),
        ),
        studies=(sma,),
    )
    angle = prepare(
        runtime,
        dataset,
        "angle",
        sources=(
            StudyInputSource(
                "source",
                "study",
                study_id=derivative.study_id,
                output_name=derivative.result.output_names[0],
            ),
        ),
        studies=(sma, derivative),
    )
    rsi = prepare(runtime, dataset, "rsi", parameters={"period": 14})
    supplied = (angle, rsi, derivative, sma)
    presentations = StudyPresentationRegistry()
    presentation_values = tuple(
        presentations.register(study) for study in supplied
    )
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    draft = service.build_environment(
        dataset,
        supplied,
        presentation_values,
        display_name="Three levels",
    )

    assert tuple(entry.tool_key for entry in draft.entries) == (
        "rsi",
        "sma",
        "derivative",
        "angle",
    )
    assert tuple(entry.entry_id for entry in draft.entries) == (
        "entry_001",
        "entry_002",
        "entry_003",
        "entry_004",
    )
    assert draft.entries[2].sources[0].source_entry_id == "entry_002"
    assert draft.entries[3].sources[0].source_entry_id == "entry_003"


def test_environment_capture_orders_peaks_before_utc_and_rebinds_entry_sources(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
    peaks = prepare(runtime, dataset, "peaks_troughs")
    utc = prepare(
        runtime,
        dataset,
        "universal_trend_classifier",
        sources=tuple(
            StudyInputSource(
                role,
                "study",
                study_id=peaks.study_id,
                output_name=output,
            )
            for role, output in (
                ("trend_peak", "peak_fractal_5"),
                ("trend_trough", "trough_fractal_5"),
                ("range_peak", "peak_fractal_3"),
                ("range_trough", "trough_fractal_3"),
            )
        ),
        studies=(peaks,),
    )
    presentations = StudyPresentationRegistry()
    utc_presentation = presentations.register(utc)
    peaks_presentation = presentations.register(peaks)
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    draft = service.build_environment(
        dataset,
        (utc, peaks),
        (utc_presentation, peaks_presentation),
        display_name="P&T to UTC",
    )

    assert tuple(entry.tool_key for entry in draft.entries) == (
        "peaks_troughs",
        "universal_trend_classifier",
    )
    assert {source.source_entry_id for source in draft.entries[1].sources} == {
        "entry_001"
    }


def test_environment_capture_rejects_missing_dependency_and_cycle(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
    first = prepare(runtime, dataset, "sma", parameters={"period": 3})
    second = prepare(runtime, dataset, "rsi", parameters={"period": 14})
    presentations = StudyPresentationRegistry()
    first_presentation = presentations.register(first)
    second_presentation = presentations.register(second)
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )
    original_first = first.setup_request
    original_second = second.setup_request
    object.__setattr__(
        first,
        "setup_request",
        StudyExecutionRequest(
            "sma",
            {"period": 3},
            (
                StudyInputSource(
                    "source",
                    "study",
                    study_id="missing-study",
                    output_name="missing",
                ),
            ),
        ),
    )
    with pytest.raises(
        StudyEnvironmentValidationError,
        match="Study dependency is missing: missing-study",
    ):
        service.build_environment(
            dataset,
            (first, second),
            (first_presentation, second_presentation),
            display_name="Missing",
        )

    object.__setattr__(
        first,
        "setup_request",
        StudyExecutionRequest(
            "sma",
            {"period": 3},
            (
                StudyInputSource(
                    "source",
                    "study",
                    study_id=second.study_id,
                    output_name=second.analysis_usable_output_names[0],
                ),
            ),
        ),
    )
    object.__setattr__(
        second,
        "setup_request",
        StudyExecutionRequest(
            "rsi",
            {"period": 14},
            (
                StudyInputSource(
                    "source",
                    "study",
                    study_id=first.study_id,
                    output_name=first.analysis_usable_output_names[0],
                ),
            ),
        ),
    )
    with pytest.raises(
        StudyEnvironmentValidationError,
        match="Study dependency cycle detected",
    ):
        service.build_environment(
            dataset,
            (first, second),
            (first_presentation, second_presentation),
            display_name="Cycle",
        )
    object.__setattr__(first, "setup_request", original_first)
    object.__setattr__(second, "setup_request", original_second)


def test_pure_environment_is_cross_market_compatible(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
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


def test_catalog_projects_same_name_artifacts_without_identity_or_naming_mutation(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
    sma_20 = prepare(runtime, dataset, "sma", parameters={"period": 20})
    sma_200 = prepare(runtime, dataset, "sma", parameters={"period": 200})
    saved = (
        runtime.save_study(_save_attempt(sma_20), dataset, sma_20, (sma_20,)),
        runtime.save_study(_save_attempt(sma_200), dataset, sma_200, (sma_200,)),
    )
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    catalog = service.build_catalog(dataset, ())
    options = tuple(
        option for option in catalog.artifact_options if option.tool_key == "sma"
    )

    assert len(options) == 2
    assert {option.display_name for option in options} == {"SMA"}
    assert {option.artifact_id for option in options} == {
        item.saved_link.artifact_id for item in saved
    }
    assert {
        (option.parameters["period"], option.output_names)
        for option in options
    } == {
        (20, ("sma_20",)),
        (200, ("sma_200",)),
    }
    assert catalog.artifact_rejections == ()


def test_catalog_projects_artifact_backed_source_without_internal_identity(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
    source = prepare(runtime, dataset, "sma", parameters={"period": 20})
    source_saved = runtime.save_study(
        _save_attempt(source), dataset, source, (source,)
    )
    derivative = prepare(
        runtime,
        dataset,
        "derivative",
        parameters={"order": 1},
        sources=(
            StudyInputSource(
                "source",
                "artifact",
                artifact_kind=source_saved.saved_link.kind,
                artifact_tool_key=source_saved.saved_link.tool_key,
                artifact_id=source_saved.saved_link.artifact_id,
                output_name="sma_20",
            ),
        ),
    )
    derivative_saved = runtime.save_study(
        _save_attempt(derivative), dataset, derivative, (derivative,)
    )
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    catalog = service.build_catalog(dataset, ())
    option = next(
        item
        for item in catalog.artifact_options
        if item.artifact_id == derivative_saved.saved_link.artifact_id
    )

    assert option.parameters == {"order": 1}
    assert option.source_bindings == (("source", "sma_20"),)
    assert "__research_" not in option.source_bindings[0][1]
    assert "__study_" not in option.source_bindings[0][1]
    assert source_saved.saved_link.artifact_id not in option.source_bindings[0][1]
    assert tuple(item.artifact_id for item in catalog.artifact_options) == tuple(
        item.artifact_id for item in artifacts.list_artifacts(dataset.market_id)
    )
    assert catalog.artifact_rejections == ()


def test_dynamic_binning_remains_global_but_is_rejected_from_research_artifacts(
    tmp_path: Path,
) -> None:
    dataset, artifacts, frame = accepted_context(tmp_path)
    dynamic_result = calculate_financial_tool("dynamic_binning", frame)
    dynamic_saved = artifacts.save_calculation(dataset.market_id, dynamic_result)
    sma_saved = artifacts.save_calculation(
        dataset.market_id,
        calculate_financial_tool("sma", frame, {"period": 20}),
    )
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    catalog = service.build_catalog(dataset, ())
    global_summaries = artifacts.list_artifacts(dataset.market_id)
    rejection = tuple(
        item
        for item in catalog.artifact_rejections
        if item.artifact_id == dynamic_saved.metadata.artifact_id
    )

    assert len(ALL_FINANCIAL_TOOL_SPECS) == 26
    assert "dynamic_binning" in ALL_FINANCIAL_TOOL_SPECS
    assert get_financial_tool_spec("dynamic_binning").kind == "construct"
    assert get_financial_tool_spec("dynamic_binning").behavior.chart_renderable is False
    assert dynamic_result.output_names == ()
    assert tuple(dynamic_result.analysis) == (
        "steps",
        "variation_diagnostics",
        "binning_artifact",
        "labeled_rows",
    )
    assert dynamic_saved.metadata.artifact_id in tuple(
        item.artifact_id for item in global_summaries
    )
    assert sma_saved.metadata.artifact_id in tuple(
        item.artifact_id for item in catalog.artifact_options
    )
    assert dynamic_saved.metadata.artifact_id not in tuple(
        item.artifact_id for item in catalog.artifact_options
    )
    assert len(rejection) == 1
    assert rejection[0].artifact_id == dynamic_saved.metadata.artifact_id
    assert rejection[0].kind == "construct"
    assert rejection[0].tool_key == "dynamic_binning"
    assert rejection[0].reason == (
        "Dynamic Binning is reserved for Analysis and unavailable in Research."
    )


def test_dynamic_binning_cannot_build_a_new_research_environment(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runtime = research_service(tmp_path, artifacts)
    dynamic = prepare(
        runtime,
        dataset,
        "dynamic_binning",
        sources=(
            StudyInputSource(
                "source_1",
                "ohlcv",
                column_name="close",
            ),
        ),
    )
    presentations = StudyPresentationRegistry()
    presentation = presentations.register(dynamic)
    service = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )

    with pytest.raises(
        StudyEnvironmentValidationError,
        match=(
            "^Dynamic Binning is reserved for Analysis and cannot be saved "
            "in a Research Study Environment\\.$"
        ),
    ):
        service.build_environment(
            dataset,
            (dynamic,),
            (presentation,),
            display_name="Dynamic Binning",
        )


def test_legacy_dynamic_binning_environment_is_parseable_blocked_and_unchanged(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    store = StudyEnvironmentStore(
        tmp_path / "study_environments",
        id_factory=lambda: "legacy_dynamic",
    )
    service = ResearchStudySetupService(artifacts, store)
    presentation = StudyEnvironmentPresentationV1(True, (), ())
    dynamic_entry = StudyEnvironmentEntryV1(
        entry_id="entry_001",
        mode="artifact",
        kind="construct",
        tool_key="dynamic_binning",
        display_name="Legacy Dynamic Binning",
        parameters={},
        sources=(),
        artifact_id="d" * 64,
        expected_output_names=("analysis_payload",),
        user_metadata=StudyUserMetadata(),
        presentation=presentation,
    )
    remaining_entry = StudyEnvironmentEntryV1(
        entry_id="entry_002",
        mode="artifact",
        kind="indicator",
        tool_key="sma",
        display_name="Missing SMA",
        parameters={},
        sources=(),
        artifact_id="e" * 64,
        expected_output_names=("sma_20",),
        user_metadata=StudyUserMetadata(),
        presentation=presentation,
    )
    environment = store.create(
        StudyEnvironmentDraft(
            display_name="Legacy Dynamic Binning",
            description="Stored legacy Research environment.",
            created_from=dataset.market_id,
            entries=(dynamic_entry, remaining_entry),
        )
    )
    path = store.environment_path(environment.environment_id)
    before = path.read_bytes()

    loaded = service.load_environment(environment.environment_id)
    restored = StudyEnvironmentV1.from_dict(loaded.to_dict())
    report = service.compatibility(loaded, dataset)

    assert restored == loaded
    assert report.blockers[0] == (
        "entry_001: Dynamic Binning is reserved for Analysis and unavailable "
        "in Research"
    )
    assert any(item.startswith("entry_002:") for item in report.blockers)
    assert path.read_bytes() == before
    assert service.load_environment(environment.environment_id) == loaded
    assert tuple(
        item.environment_id for item in service.list_environments()
    ) == (environment.environment_id,)
