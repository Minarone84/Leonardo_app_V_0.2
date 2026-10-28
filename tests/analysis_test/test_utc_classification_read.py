from dataclasses import replace
import pytest

from leonardo.analysis import AnalysisService
from tests.analysis_test.test_analysis_service import reference, make_database, files
from tests.data_manager_test.test_utc_classification_lifecycle import utc_database


def test_pinned_read_separates_members_and_excludes_metadata_from_numeric_columns(tmp_path):
    domain, _, _, _, manifest = utc_database(tmp_path, windows=(5, 7))
    store = domain._creation.store
    service = AnalysisService(store)
    before = files(store.root_dir)
    bundle = service.load_utc_classification(reference(manifest))
    assert bundle.status == "available"
    associations = bundle.associations_frame()
    assert associations["first_timestamp_ms"].dtype == object
    assert set(associations.column_name) == {"up_0", "up_1"}
    for artifact_id in associations.artifact_id.unique():
        report = bundle.report(artifact_id)
        assert report.episodes
        assert report.to_episode_frame().confirmed_at_ms.dtype == object
        metrics = bundle.metrics(artifact_id)
        assert metrics.episodes
        assert metrics.to_dict()["input_key"] == report.to_dict()["input_key"]
        frame = metrics.to_episode_frame()
        frame.iloc[0]["episode_metrics"]["status"] = "tampered"
        assert bundle.metrics(artifact_id).episodes[0]["episode_metrics"]["status"] != "tampered"
    assert all(c.name not in {"formation_key", "episode_id", "confirmed_at_ms"}
               for c in service.load_columns(reference(manifest)).columns)
    mutated = bundle.to_dict()
    mutated["associations"].clear()
    assert len(bundle.associations_frame()) == 2
    with pytest.raises(KeyError): bundle.report("absent")
    with pytest.raises(KeyError): bundle.metrics("absent")
    with pytest.raises(ValueError, match="reference"):
        service.load_utc_classification(replace(reference(manifest), values_sha256="0" * 64))
    assert files(store.root_dir) == before


def test_legacy_database_read_does_not_invent_classification(tmp_path):
    store, manifest, _ = make_database(tmp_path)
    bundle = AnalysisService(store).load_utc_classification(reference(manifest))
    assert bundle.status == "legacy_unavailable"
    assert bundle.associations_frame().empty


def test_provider_specific_metrics_keep_partial_coverage_and_legacy_absence(tmp_path):
    import json
    domain, _, _, _, manifest = utc_database(tmp_path)
    bundle = AnalysisService(domain._creation.store).load_utc_classification(reference(manifest))
    payload = bundle.to_dict()
    association = payload["associations"][0]
    identity = association["artifact_id"]
    metric_axis = bundle.metrics(identity).to_dict()["timestamps_ms"]
    association["first_timestamp_ms"] = metric_axis[4]
    partial = replace(bundle, _payload=json.dumps(payload).encode())
    assert partial.metrics(identity).to_dict()["timestamps_ms"][0] < partial.associations_frame().iloc[0].first_timestamp_ms
    assert partial.associations_frame().iloc[0].first_timestamp_ms == metric_axis[4]
    payload["reports"][association["report_sha256"]].pop("utc_episode_metrics")
    v1 = replace(bundle, _payload=json.dumps(payload).encode())
    assert v1.metrics(identity) is None and v1.report(identity) is not None
    payload["reports"][association["report_sha256"]] = {}
    legacy = replace(bundle, _payload=json.dumps(payload).encode())
    assert legacy.metrics(identity) is None and legacy.report(identity) is None
