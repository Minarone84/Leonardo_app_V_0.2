from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from leonardo.artifacts import ArtifactSourceRefV1
from leonardo.financial_tools import (
    ALL_FINANCIAL_TOOL_SPECS,
    FinancialToolCalculationResult,
    calculate_financial_tool,
)
from leonardo.research import (
    ResearchStudyService,
    StudyArtifactRequest,
    StudyInputSource,
    StudySaveAttempt,
    StudySaveBlockedError,
    StudyOperationCancelled,
    StudyValidationError,
)
from leonardo.research.study_projection import project_study

from tests.research_test.test_study_execution import (
    accepted_context,
    apply_attempt,
    prepare,
    publish_accepted_frame,
)
from tests.research_test.test_study_projection import resident


def _save_attempt(study) -> StudySaveAttempt:
    return StudySaveAttempt(
        session_id=study.session_id,
        generation=study.generation,
        request_id="save-" + study.study_id,
        study_id=study.study_id,
        market_id=study.market_id,
        dataset_fingerprint=study.dataset_fingerprint,
    )


def test_apply_writes_nothing_and_save_uses_exact_stored_result(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    live = prepare(service, dataset, "sma", parameters={"period": 3})
    assert artifacts.list_artifacts(dataset.market_id) == ()

    outcome = service.save_study(
        _save_attempt(live), dataset, live, (live,), description="Task 1017"
    )

    assert outcome.study_id == live.study_id
    loaded = artifacts.load_artifact(
        dataset.market_id,
        outcome.saved_link.kind,
        outcome.saved_link.tool_key,
        outcome.saved_link.artifact_id,
    )
    assert loaded.frame.equals(live.result.to_frame().reset_index(drop=True))


def test_loaded_artifact_apply_never_calculates_and_projects_equally(
    tmp_path: Path, monkeypatch
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    live = prepare(service, dataset, "sma", parameters={"period": 3})
    saved = service.save_study(_save_attempt(live), dataset, live, (live,))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("artifact Apply must not calculate")

    monkeypatch.setattr("leonardo.research.study_execution.calculate_financial_tool", forbidden)
    loaded = service.prepare_artifact(
        apply_attempt(dataset),
        dataset,
        StudyArtifactRequest(
            saved.saved_link.kind,
            saved.saved_link.tool_key,
            saved.saved_link.artifact_id,
        ),
    ).study

    current = resident(dataset)
    live_projection = project_study(live, current)
    loaded_projection = project_study(loaded, current)
    assert loaded_projection.ts_ms == live_projection.ts_ms
    assert dict(loaded_projection.render_series) == dict(live_projection.render_series)
    assert dict(loaded_projection.style_driver_series) == dict(
        live_projection.style_driver_series
    )
    assert loaded.source_kind == "artifact"
    assert loaded.saved_link == saved.saved_link


def test_transient_dependency_blocks_then_durable_lineage_succeeds(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    dependent = prepare(
        service,
        dataset,
        "derivative",
        parameters={"order": 1},
        sources=(
            StudyInputSource(
                "source", "study", study_id=source.study_id, output_name="sma_3"
            ),
        ),
        studies=(source,),
    )
    with pytest.raises(StudySaveBlockedError, match="unsaved"):
        service.save_study(
            _save_attempt(dependent), dataset, dependent, (source, dependent)
        )

    source_outcome = service.save_study(
        _save_attempt(source), dataset, source, (source, dependent)
    )
    linked_source = replace(source, saved_link=source_outcome.saved_link)
    dependent_outcome = service.save_study(
        _save_attempt(dependent),
        dataset,
        dependent,
        (linked_source, dependent),
    )
    metadata = artifacts.load_artifact(
        dataset.market_id,
        dependent_outcome.saved_link.kind,
        dependent_outcome.saved_link.tool_key,
        dependent_outcome.saved_link.artifact_id,
    ).metadata

    assert metadata.recipe.source_artifacts[0].role == "source"
    assert metadata.recipe.source_artifacts[0].artifact_id == source_outcome.saved_link.artifact_id
    assert metadata.recipe.source_artifacts[0].output_name == "sma_3"
    linked_dependent = replace(dependent, saved_link=dependent_outcome.saved_link)
    repeated = service.save_study(
        _save_attempt(linked_dependent),
        dataset,
        linked_dependent,
        (linked_source, dependent),
    )
    assert repeated.created is False


def test_cancellation_before_persistence_writes_nothing(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    study = prepare(service, dataset, "sma", parameters={"period": 3})
    cancelled = Event()
    cancelled.set()

    with pytest.raises(StudyOperationCancelled, match="save source resolution"):
        service.save_study(
            _save_attempt(study),
            dataset,
            study,
            (study,),
            cancellation_requested=cancelled.is_set,
        )
    assert artifacts.list_artifacts(dataset.market_id) == ()


def _changed_frame(frame):
    changed = frame.copy(deep=True)
    for column in ("open", "high", "low", "close"):
        changed[column] = changed[column] + 50.0
    return changed


def test_changed_same_timeline_artifact_is_rejected_for_apply_and_source(
    tmp_path: Path,
) -> None:
    dataset, artifacts, frame = accepted_context(tmp_path)
    changed = _changed_frame(frame)
    publish_accepted_frame(tmp_path, changed, dataset.market_id)
    saved = artifacts.save_calculation(
        dataset.market_id,
        calculate_financial_tool("sma", changed, {"period": 3}),
    )
    service = ResearchStudyService(artifacts)
    request = StudyArtifactRequest(
        "indicator", "sma", saved.metadata.artifact_id
    )

    with pytest.raises(StudyValidationError, match="fingerprint"):
        service.prepare_artifact(apply_attempt(dataset), dataset, request)
    with pytest.raises(StudyValidationError, match="fingerprint"):
        prepare(
            service,
            dataset,
            "derivative",
            sources=(
                StudyInputSource(
                    "source",
                    "artifact",
                    artifact_kind="indicator",
                    artifact_tool_key="sma",
                    artifact_id=saved.metadata.artifact_id,
                    output_name="sma_3",
                ),
            ),
        )


def test_stale_live_study_save_removes_only_new_artifact(tmp_path: Path) -> None:
    dataset, artifacts, frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    live = prepare(service, dataset, "sma", parameters={"period": 3})
    publish_accepted_frame(tmp_path, _changed_frame(frame), dataset.market_id)

    with pytest.raises(StudyValidationError, match="fingerprint"):
        service.save_study(_save_attempt(live), dataset, live, (live,))

    assert artifacts.list_artifacts(dataset.market_id) == ()
    assert len(artifacts.list_recipes(dataset.market_id)) == 1


def test_already_linked_artifact_must_equal_exact_study_truth(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    live = prepare(service, dataset, "sma", parameters={"period": 3})
    outcome = service.save_study(_save_attempt(live), dataset, live, (live,))
    forged_frame = live.result.to_frame()
    forged_frame.loc[5, "sma_3"] = float(forged_frame.loc[5, "sma_3"]) + 1.0
    forged_result = FinancialToolCalculationResult(
        tool_key=live.result.tool_key,
        kind=live.result.kind,
        parameters=live.result.parameters,
        bindings=live.result.bindings,
        output_names=live.result.output_names,
        frame=forged_frame,
        analysis=live.result.analysis,
    )
    forged = replace(live, result=forged_result, saved_link=outcome.saved_link)

    with pytest.raises(StudyValidationError, match="output truth"):
        service.save_study(_save_attempt(forged), dataset, forged, (forged,))


def test_cross_session_same_id_saved_source_cannot_be_substituted(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    dependent = prepare(
        service,
        dataset,
        "derivative",
        sources=(
            StudyInputSource(
                "source", "study", study_id=source.study_id, output_name="sma_3"
            ),
        ),
        studies=(source,),
    )
    saved = service.save_study(
        _save_attempt(source), dataset, source, (source, dependent)
    )
    foreign_source = replace(
        source, session_id="foreign-session", saved_link=saved.saved_link
    )

    with pytest.raises(StudySaveBlockedError) as captured:
        service.save_study(
            _save_attempt(dependent),
            dataset,
            dependent,
            (foreign_source, dependent),
        )
    assert captured.value.blockers == (
        f"source:stale:{source.study_id}",
    )


def test_artifact_display_name_fallback_and_override(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    live = prepare(service, dataset, "sma", parameters={"period": 3})
    saved = artifacts.save_calculation(
        dataset.market_id,
        live.result,
        display_name="My Custom SMA",
    )

    fallback = service.prepare_artifact(
        apply_attempt(dataset),
        dataset,
        StudyArtifactRequest("indicator", "sma", saved.metadata.artifact_id),
    ).study
    overridden = service.prepare_artifact(
        apply_attempt(dataset),
        dataset,
        StudyArtifactRequest(
            "indicator",
            "sma",
            saved.metadata.artifact_id,
            display_name="Explicit SMA",
        ),
    ).study

    assert fallback.display_name == "My Custom SMA"
    assert overridden.display_name == "Explicit SMA"


def _artifact_input(role: str, saved, output_name: str) -> StudyInputSource:
    return StudyInputSource(
        role,
        "artifact",
        artifact_kind=saved.saved_link.kind,
        artifact_tool_key=saved.saved_link.tool_key,
        artifact_id=saved.saved_link.artifact_id,
        output_name=output_name,
    )


def _braid_result(tool_key: str, frame, mid_values=None):
    working = frame.copy(deep=True)
    parameters = {"fast": "close", "mid": "open", "slow": "low"}
    if mid_values is not None:
        working["__research_mid"] = mid_values
        parameters["mid"] = "__research_mid"
    return calculate_financial_tool(tool_key, working, parameters)


def test_legitimate_artifact_source_selector_families_still_pass(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    sources = {
        key: prepare(service, dataset, key, parameters={"period": 3})
        for key in ("sma", "ema", "hma")
    }
    saved = {
        key: service.save_study(_save_attempt(study), dataset, study, (study,))
        for key, study in sources.items()
    }
    cases = (
        ("derivative", (_artifact_input("source", saved["sma"], "sma_3"),)),
        ("angle", (_artifact_input("source", saved["sma"], "sma_3"),)),
        (
            "delta",
            (
                _artifact_input("fast", saved["sma"], "sma_3"),
                _artifact_input("slow", saved["hma"], "hma_3"),
            ),
        ),
        (
            "braids",
            tuple(
                _artifact_input(role, saved[key], f"{key}_3")
                for role, key in zip(
                    ("fast", "mid", "slow"), ("sma", "ema", "hma"), strict=True
                )
            ),
        ),
        (
            "braid_instability",
            tuple(
                _artifact_input(role, saved[key], f"{key}_3")
                for role, key in zip(
                    ("fast", "mid", "slow"), ("sma", "ema", "hma"), strict=True
                )
            ),
        ),
        (
            "trap_area",
            (
                _artifact_input("fast", saved["sma"], "sma_3"),
                _artifact_input("slow", saved["hma"], "hma_3"),
            ),
        ),
        (
            "dynamic_binning",
            (_artifact_input("source_1", saved["sma"], "sma_3"),),
        ),
        (
            "percent_span_angle",
            (_artifact_input("source_1", saved["sma"], "sma_3"),),
        ),
        (
            "angle_momentum",
            (_artifact_input("source_1", saved["sma"], "sma_3"),),
        ),
    )
    for tool_key, inputs in cases:
        study = prepare(service, dataset, tool_key, sources=inputs)
        assert study.result.row_count == dataset.row_count

    peaks = prepare(service, dataset, "peaks_troughs")
    peaks_saved = service.save_study(
        _save_attempt(peaks), dataset, peaks, (peaks,)
    )
    utc = prepare(
        service,
        dataset,
        "universal_trend_classifier",
        parameters={"fractal_window": 5, "trend_fractal_window": 5},
        sources=(
            _artifact_input("peak", peaks_saved, "peak_fractal_5"),
            _artifact_input("trough", peaks_saved, "trough_fractal_5"),
        ),
    )
    assert utc.result.row_count == dataset.row_count


def test_persisted_missing_categorical_and_nested_lineage_are_rejected(
    tmp_path: Path,
) -> None:
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
    malformed = artifacts.save_calculation(dataset.market_id, derivative.result)
    with pytest.raises(StudyValidationError, match="lineage roles"):
        service.prepare_artifact(
            apply_attempt(dataset),
            dataset,
            StudyArtifactRequest(
                "construct", "derivative", malformed.metadata.artifact_id
            ),
        )

    hck = prepare(
        service,
        dataset,
        "hck",
        parameters={"fast_vwap_l": 3, "slow_vwap_l": 5},
    )
    hck_saved = artifacts.save_calculation(dataset.market_id, hck.result)
    categorical = artifacts.save_calculation(
        dataset.market_id,
        derivative.result,
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", hck_saved.metadata.artifact_id, "vwap_color"
            ),
        ),
    )
    with pytest.raises(StudyValidationError, match="not analysis-usable"):
        service.prepare_artifact(
            apply_attempt(dataset),
            dataset,
            StudyArtifactRequest(
                "construct", "derivative", categorical.metadata.artifact_id
            ),
        )
    forged_direct_source = replace(
        derivative,
        source_studies=(),
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", hck_saved.metadata.artifact_id, "vwap_color"
            ),
        ),
    )
    with pytest.raises(StudyValidationError, match="not analysis-usable"):
        service.save_study(
            _save_attempt(forged_direct_source),
            dataset,
            forged_direct_source,
            (forged_direct_source,),
        )

    nested = artifacts.save_calculation(
        dataset.market_id,
        derivative.result,
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", malformed.metadata.artifact_id, derivative.result.output_names[0]
            ),
        ),
    )
    with pytest.raises(StudyValidationError, match="lineage roles"):
        service.prepare_artifact(
            apply_attempt(dataset),
            dataset,
            StudyArtifactRequest("construct", "derivative", nested.metadata.artifact_id),
        )


@pytest.mark.parametrize("use", ["apply", "source", "idempotent-save"])
def test_validate_then_load_source_change_is_rejected(
    tmp_path: Path, monkeypatch, use: str
) -> None:
    root = tmp_path / use
    dataset, artifacts, frame = accepted_context(root)
    service = ResearchStudyService(artifacts)
    source = prepare(service, dataset, "sma", parameters={"period": 3})
    saved = service.save_study(_save_attempt(source), dataset, source, (source,))
    linked = replace(source, saved_link=saved.saved_link)
    original = artifacts.validate_artifact_current
    calls = 0

    def race(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            publish_accepted_frame(root, _changed_frame(frame), dataset.market_id)
        return result

    monkeypatch.setattr(artifacts, "validate_artifact_current", race)
    with pytest.raises(StudyValidationError, match="changed during validation"):
        if use == "apply":
            service.prepare_artifact(
                apply_attempt(dataset),
                dataset,
                StudyArtifactRequest("indicator", "sma", saved.saved_link.artifact_id),
            )
        elif use == "source":
            prepare(
                service,
                dataset,
                "derivative",
                sources=(_artifact_input("source", saved, "sma_3"),),
            )
        else:
            service.save_study(
                _save_attempt(linked), dataset, linked, (linked,)
            )


def test_post_save_current_race_removes_exact_artifact_and_retains_recipe(
    tmp_path: Path, monkeypatch
) -> None:
    dataset, artifacts, frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    study = prepare(service, dataset, "sma", parameters={"period": 3})
    original = artifacts.save_calculation

    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        publish_accepted_frame(tmp_path, _changed_frame(frame), dataset.market_id)
        return result

    monkeypatch.setattr(artifacts, "save_calculation", race)
    with pytest.raises(StudyValidationError):
        service.save_study(_save_attempt(study), dataset, study, (study,))

    assert artifacts.list_artifacts(dataset.market_id) == ()
    assert len(artifacts.list_recipes(dataset.market_id)) == 1


def test_linked_save_requires_exact_recipe_id_and_durable_source_refs(
    tmp_path: Path,
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    sma = prepare(service, dataset, "sma", parameters={"period": 3})
    saved_sma = service.save_study(_save_attempt(sma), dataset, sma, (sma,))
    linked_sma = replace(sma, saved_link=saved_sma.saved_link)
    fake_link = replace(saved_sma.saved_link, recipe_id="f" * 64)
    with pytest.raises(StudyValidationError, match="identity"):
        service.save_study(
            _save_attempt(replace(sma, saved_link=fake_link)),
            dataset,
            replace(sma, saved_link=fake_link),
            (linked_sma,),
        )

    derivative = prepare(
        service,
        dataset,
        "derivative",
        sources=(_artifact_input("source", saved_sma, "sma_3"),),
    )
    saved_derivative = service.save_study(
        _save_attempt(derivative), dataset, derivative, (derivative,)
    )
    ema = prepare(service, dataset, "ema", parameters={"period": 3})
    saved_ema = service.save_study(_save_attempt(ema), dataset, ema, (ema,))
    forged = replace(
        derivative,
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", saved_ema.saved_link.artifact_id, "ema_3"
            ),
        ),
        saved_link=saved_derivative.saved_link,
    )
    with pytest.raises(StudyValidationError, match="source lineage"):
        service.save_study(
            _save_attempt(forged), dataset, forged, (forged, linked_sma)
        )


@pytest.mark.parametrize("tool_key", ["braids", "braid_instability"])
@pytest.mark.parametrize("selectors", ["all-ohlcv", "mixed"])
def test_malformed_persisted_braids_reject_apply_save_source_and_nested_lineage(
    tmp_path: Path, tool_key: str, selectors: str
) -> None:
    dataset, artifacts, frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    refs = ()
    mid_values = None
    if selectors == "mixed":
        sma_result = calculate_financial_tool("sma", frame, {"period": 3})
        sma_saved = artifacts.save_calculation(dataset.market_id, sma_result)
        mid_values = sma_result.to_frame()["sma_3"].to_numpy()
        refs = (
            ArtifactSourceRefV1("mid", sma_saved.metadata.artifact_id, "sma_3"),
        )
    malformed_result = _braid_result(tool_key, frame, mid_values)
    malformed = artifacts.save_calculation(
        dataset.market_id,
        malformed_result,
        source_artifacts=refs,
    )
    request = StudyArtifactRequest(
        "construct", tool_key, malformed.metadata.artifact_id
    )

    with pytest.raises(StudyValidationError, match="source families"):
        service.prepare_artifact(apply_attempt(dataset), dataset, request)

    base = prepare(service, dataset, "sma", parameters={"period": 4})
    object.__setattr__(base, "result", malformed_result)
    object.__setattr__(base, "source_studies", ())
    object.__setattr__(base, "source_artifacts", refs)
    before = artifacts.list_artifacts(dataset.market_id)
    with pytest.raises(StudyValidationError, match="source families"):
        service.save_study(_save_attempt(base), dataset, base, (base,))
    assert artifacts.list_artifacts(dataset.market_id) == before

    output_name = malformed_result.output_names[0]
    with pytest.raises(StudyValidationError, match="source families"):
        prepare(
            service,
            dataset,
            "derivative",
            sources=(
                StudyInputSource(
                    "source",
                    "artifact",
                    artifact_kind="construct",
                    artifact_tool_key=tool_key,
                    artifact_id=malformed.metadata.artifact_id,
                    output_name=output_name,
                ),
            ),
        )

    consumer_frame = frame.copy(deep=True)
    consumer_frame["__research_source"] = malformed_result.to_frame()[
        output_name
    ].to_numpy()
    consumer_result = calculate_financial_tool(
        "derivative",
        consumer_frame,
        {},
        bindings={"source": "__research_source"},
    )
    nested = artifacts.save_calculation(
        dataset.market_id,
        consumer_result,
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", malformed.metadata.artifact_id, output_name
            ),
        ),
    )
    with pytest.raises(StudyValidationError, match="source families"):
        service.prepare_artifact(
            apply_attempt(dataset),
            dataset,
            StudyArtifactRequest("construct", "derivative", nested.metadata.artifact_id),
        )


def test_all_26_tools_save_apply_exact_frame_and_idempotent_save(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    source_studies = {
        key: prepare(service, dataset, key, parameters={"period": 3})
        for key in ("sma", "ema", "hma")
    }
    source_saves = {
        key: service.save_study(_save_attempt(study), dataset, study, (study,))
        for key, study in source_studies.items()
    }

    completed: set[str] = set()
    for tool_key in ALL_FINANCIAL_TOOL_SPECS:
        sources: tuple[StudyInputSource, ...] = ()
        if tool_key in {"derivative", "angle"}:
            sources = (StudyInputSource("source", "ohlcv", column_name="close"),)
        elif tool_key == "delta":
            sources = (
                StudyInputSource("fast", "ohlcv", column_name="high"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            )
        elif tool_key in {"braids", "braid_instability"}:
            sources = tuple(
                _artifact_input(role, source_saves[key], f"{key}_3")
                for role, key in zip(
                    ("fast", "mid", "slow"), ("sma", "ema", "hma"), strict=True
                )
            )
        elif tool_key == "trap_area":
            sources = (
                StudyInputSource("fast", "ohlcv", column_name="high"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            )
        elif tool_key in {"dynamic_binning", "percent_span_angle", "angle_momentum"}:
            sources = (StudyInputSource("source_1", "ohlcv", column_name="close"),)
        study = prepare(service, dataset, tool_key, sources=sources)
        outcome = service.save_study(
            _save_attempt(study), dataset, study, (study,)
        )
        loaded = service.prepare_artifact(
            apply_attempt(dataset),
            dataset,
            StudyArtifactRequest(
                outcome.saved_link.kind,
                outcome.saved_link.tool_key,
                outcome.saved_link.artifact_id,
            ),
        ).study
        assert loaded.result.to_frame().equals(
            study.result.to_frame().reset_index(drop=True)
        )
        linked = replace(study, saved_link=outcome.saved_link)
        repeated = service.save_study(
            _save_attempt(linked), dataset, linked, (linked,)
        )
        assert repeated.created is False
        completed.add(tool_key)

    assert completed == set(ALL_FINANCIAL_TOOL_SPECS)
