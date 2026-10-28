from dataclasses import replace
import pytest

from leonardo.research import StudyArtifactRequest, StudyValidationError
from leonardo.financial_tools import get_utc_classification
from tests.research_test.test_study_execution import accepted_context, apply_attempt, prepare, research_service
from tests.research_test.test_study_artifact_apply_save import _artifact_input, _save_attempt
from tests.financial_tools_test.test_utc_classification_compatibility import with_analysis


def utc_study(tmp_path):
    dataset, artifacts, frame = accepted_context(tmp_path)
    service = research_service(tmp_path, artifacts)
    peaks = prepare(service, dataset, "peaks_troughs")
    saved = service.save_study(_save_attempt(peaks), dataset, peaks, (peaks,))
    sources = tuple(_artifact_input(role, saved, name) for role, name in (
        ("trend_peak", "peak_fractal_5"), ("trend_trough", "trough_fractal_5"),
        ("range_peak", "peak_fractal_3"), ("range_trough", "trough_fractal_3")))
    study = prepare(service, dataset, "universal_trend_classifier", sources=sources)
    return dataset, artifacts, service, study


@pytest.mark.parametrize("legacy", (False, True))
def test_utc_linked_study_restore_and_resave_preserve_exact_contract(tmp_path, legacy):
    dataset, artifacts, service, study = utc_study(tmp_path)
    if legacy:
        study = replace(study, result=with_analysis(study.result, {}))
    outcome = service.save_study(_save_attempt(study), dataset, study, (study,))
    link = outcome.saved_link
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    restored = service.prepare_artifact(apply_attempt(dataset), dataset,
        StudyArtifactRequest(link.kind, link.tool_key, link.artifact_id)).study
    assert restored.result.analysis == study.result.analysis
    assert restored.result.to_frame().equals(study.result.to_frame())
    assert get_utc_classification(restored.result).status == ("legacy_unavailable" if legacy else "retrospective")
    assert {p: p.read_bytes() for p in before} == before
    artifact_dir = artifacts._store.artifact_dir(dataset.market_id, link.kind, link.tool_key, link.artifact_id)
    artifact_bytes = {p: p.read_bytes() for p in artifact_dir.iterdir() if p.is_file()}
    repeated = service.save_study(_save_attempt(restored), dataset, restored, (restored,))
    assert not repeated.created and repeated.saved_link == link
    assert {p: p.read_bytes() for p in artifact_bytes} == artifact_bytes


def test_linked_current_study_cannot_silently_discard_classification(tmp_path):
    dataset, _, service, study = utc_study(tmp_path)
    outcome = service.save_study(_save_attempt(study), dataset, study, (study,))
    invalid = replace(study, saved_link=outcome.saved_link, result=with_analysis(study.result, {}))
    with pytest.raises(StudyValidationError, match="analysis"):
        service.save_study(_save_attempt(invalid), dataset, invalid, (invalid,))


def test_v1_study_roundtrip_and_enriched_link_cannot_discard_only_metrics(tmp_path):
    dataset, _, service, study = utc_study(tmp_path / "v1")
    v1 = replace(study, result=with_analysis(study.result, {"utc_classification": study.result.analysis["utc_classification"]}))
    saved_v1 = service.save_study(_save_attempt(v1), dataset, v1, (v1,))
    restored = service.prepare_artifact(apply_attempt(dataset), dataset,
        StudyArtifactRequest(saved_v1.saved_link.kind, saved_v1.saved_link.tool_key, saved_v1.saved_link.artifact_id)).study
    assert restored.result.analysis == v1.result.analysis
    dataset, _, service, study = utc_study(tmp_path / "enriched")
    v1 = replace(study, result=with_analysis(study.result, {"utc_classification": study.result.analysis["utc_classification"]}))
    enriched = service.save_study(_save_attempt(study), dataset, study, (study,))
    stripped = replace(v1, saved_link=enriched.saved_link)
    with pytest.raises(StudyValidationError, match="analysis"):
        service.save_study(_save_attempt(stripped), dataset, stripped, (stripped,))
