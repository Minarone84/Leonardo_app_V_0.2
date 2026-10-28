from hashlib import sha256
import pandas as pd
import pytest

from leonardo.artifacts import ArtifactService, ArtifactSourceRefV1, ArtifactValidationError
from leonardo.financial_tools import calculate_financial_tool, get_utc_classification
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.financial_tools_test.test_utc_classification_compatibility import with_analysis


def saved_utc(tmp_path, *, legacy=False):
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    pt = calculate_financial_tool("peaks_troughs", frame)
    saved_pt = service.save_calculation(market, pt)
    for column in pt.output_names:
        frame[column] = pt.to_frame()[column]
    result = calculate_financial_tool("UTC", frame, {"peak_column": "peak_fractal_5", "trough_column": "trough_fractal_5"})
    if legacy:
        result = with_analysis(result, {})
    refs = tuple(ArtifactSourceRefV1(role, saved_pt.metadata.artifact_id, name) for role, name in (
        ("trend_peak", "peak_fractal_5"), ("trend_trough", "trough_fractal_5"),
        ("range_peak", "peak_fractal_3"), ("range_trough", "trough_fractal_3")))
    saved = service.save_calculation(market, result, source_artifacts=refs)
    return service, market, result, saved


@pytest.mark.parametrize("legacy", (False, True))
def test_direct_artifact_roundtrip_preserves_bytes_and_exact_analysis(tmp_path, legacy):
    service, market, result, saved = saved_utc(tmp_path, legacy=legacy)
    files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    loaded = service.load_artifact_by_id(market, saved.metadata.artifact_id)
    pd.testing.assert_frame_equal(loaded.frame, result.to_frame(), check_exact=True)
    assert loaded.analysis == result.analysis
    assert (saved.metadata.analysis_sha256 is None) == legacy
    assert {p: p.read_bytes() for p in files} == files
    if not legacy:
        assert type(loaded.analysis["utc_classification"]["episodes"][0]["formation"][0]["ts_ms"]) is int


def test_analysis_is_part_of_artifact_identity_and_tamper_is_rejected(tmp_path):
    service, market, result, saved = saved_utc(tmp_path)
    legacy = service.save_calculation(market, with_analysis(result, {}), source_artifacts=saved.metadata.recipe.source_artifacts)
    assert legacy.metadata.artifact_id != saved.metadata.artifact_id
    assert legacy.metadata.values_sha256 == saved.metadata.values_sha256
    directory = service._store.artifact_dir(market, saved.metadata.recipe.kind, result.tool_key, saved.metadata.artifact_id)
    (directory / "analysis.json").write_bytes(b"{}")
    with pytest.raises(ArtifactValidationError, match="SHA-256"):
        ArtifactService(tmp_path).load_artifact_by_id(market, saved.metadata.artifact_id)


def test_artifact_rejects_contradictory_timing_even_with_consistent_hashes(tmp_path):
    from leonardo.artifacts.identity import artifact_identity_payload, canonical_json_identity_bytes
    from leonardo.artifacts.serialization import encode_analysis_json, encode_canonical_json
    from leonardo.financial_tools import UtcClassificationContext
    from tests.artifacts_test.test_artifact_service_roundtrip import _frame

    service, market, _, original = saved_utc(tmp_path)
    frame = _frame()
    pt = calculate_financial_tool("peaks_troughs", frame).to_frame()
    for name in pt.columns[1:]:
        frame[name] = pt[name]
    context = UtcClassificationContext(
        bar_closed_at_ms=tuple(int(t)+60_000 for t in frame.ts_ms), canonical_window=5)
    result = calculate_financial_tool("UTC", frame,
        {"peak_column":"peak_fractal_5", "trough_column":"trough_fractal_5"}, utc_context=context)
    saved = service.save_calculation(market, result, source_artifacts=original.metadata.recipe.source_artifacts)
    assert service.load_artifact_by_id(market, saved.metadata.artifact_id).analysis == result.analysis
    analysis = result.analysis
    episode = analysis["utc_classification"]["episodes"][0]
    for swing in episode["formation"]:
        swing["available_at_ms"] = swing["ts_ms"]
    episode["confirmed_at_ms"] = episode["decision_frontier_ms"]
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="availability.*context"):
        with_analysis(result, analysis)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before

    # Build a self-consistently hashed malformed fixture to reach semantic load validation.
    analysis_bytes = encode_analysis_json(analysis)
    metadata = saved.metadata.to_dict()
    metadata["analysis_sha256"] = sha256(analysis_bytes).hexdigest()
    identity = artifact_identity_payload(
        recipe_id=saved.metadata.recipe.recipe_id,
        source_ohlcv=saved.metadata.source_ohlcv.to_dict(),
        source_artifacts=saved.metadata.recipe.source_artifacts,
        row_count=saved.metadata.row_count,
        first_timestamp_ms=saved.metadata.first_timestamp_ms,
        last_timestamp_ms=saved.metadata.last_timestamp_ms,
        values_sha256=saved.metadata.values_sha256,
        analysis_sha256=metadata["analysis_sha256"])
    metadata["artifact_id"] = sha256(canonical_json_identity_bytes(identity)).hexdigest()
    original_dir = service._store.artifact_dir(market, saved.metadata.recipe.kind, result.tool_key, saved.metadata.artifact_id)
    malformed_dir = service._store.artifact_dir(market, saved.metadata.recipe.kind, result.tool_key, metadata["artifact_id"])
    malformed_dir.mkdir()
    for path in original_dir.iterdir():
        if path.is_file():
            (malformed_dir/path.name).write_bytes(path.read_bytes())
    (malformed_dir/"analysis.json").write_bytes(analysis_bytes)
    (malformed_dir/"artifact.meta.json").write_bytes(encode_canonical_json(metadata))
    with pytest.raises(ArtifactValidationError, match="runtime outputs") as error:
        ArtifactService(tmp_path).load_artifact_by_id(market, metadata["artifact_id"])
    assert "availability" in str(error.value.__cause__)


def test_v1_and_enriched_artifacts_have_same_values_but_distinct_analysis_identity(tmp_path):
    from leonardo.financial_tools import get_utc_episode_metrics
    service, market, result, enriched = saved_utc(tmp_path)
    v1_result = with_analysis(result, {"utc_classification": result.analysis["utc_classification"]})
    v1 = service.save_calculation(market, v1_result, source_artifacts=enriched.metadata.recipe.source_artifacts)
    assert enriched.metadata.artifact_id != v1.metadata.artifact_id
    assert enriched.metadata.values_sha256 == v1.metadata.values_sha256
    assert enriched.metadata.recipe.recipe_id == v1.metadata.recipe.recipe_id
    assert get_utc_episode_metrics(v1_result) is None
    loaded = service.load_artifact_by_id(market, v1.metadata.artifact_id)
    assert loaded.analysis == v1_result.analysis
    assert service.load_artifact_by_id(market, enriched.metadata.artifact_id).analysis == result.analysis


def test_corrupt_metrics_are_rejected_even_with_recomputed_artifact_identity(tmp_path):
    from leonardo.artifacts.identity import artifact_identity_payload, canonical_json_identity_bytes
    from leonardo.artifacts.serialization import encode_analysis_json, encode_canonical_json
    service, market, result, saved = saved_utc(tmp_path)
    analysis = result.analysis
    analysis["utc_episode_metrics"]["episodes"][0]["formation_metrics"]["duration"]["bars"] += 1
    analysis_bytes = encode_analysis_json(analysis)
    metadata = saved.metadata.to_dict()
    metadata["analysis_sha256"] = sha256(analysis_bytes).hexdigest()
    identity = artifact_identity_payload(recipe_id=saved.metadata.recipe.recipe_id,
        source_ohlcv=saved.metadata.source_ohlcv.to_dict(), source_artifacts=saved.metadata.recipe.source_artifacts,
        row_count=saved.metadata.row_count, first_timestamp_ms=saved.metadata.first_timestamp_ms,
        last_timestamp_ms=saved.metadata.last_timestamp_ms, values_sha256=saved.metadata.values_sha256,
        analysis_sha256=metadata["analysis_sha256"])
    metadata["artifact_id"] = sha256(canonical_json_identity_bytes(identity)).hexdigest()
    original = service._store.artifact_dir(market, saved.metadata.recipe.kind, result.tool_key, saved.metadata.artifact_id)
    corrupt = service._store.artifact_dir(market, saved.metadata.recipe.kind, result.tool_key, metadata["artifact_id"])
    corrupt.mkdir()
    for path in original.iterdir():
        if path.is_file(): (corrupt/path.name).write_bytes(path.read_bytes())
    (corrupt/"analysis.json").write_bytes(analysis_bytes)
    (corrupt/"artifact.meta.json").write_bytes(encode_canonical_json(metadata))
    with pytest.raises(ArtifactValidationError, match="runtime outputs") as error:
        ArtifactService(tmp_path).load_artifact_by_id(market, metadata["artifact_id"])
    assert "metrics" in str(error.value.__cause__)
