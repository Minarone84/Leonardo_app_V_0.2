"""Real copied V6 evidence through the existing shared-Core execution path."""
from dataclasses import replace
from threading import Event
from hashlib import sha256

import numpy as np

import pytest

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.pattern_models import NumericCondition, PatternRefinement, PatternRequest
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_analysis_service import request, files
from tests.analysis_test.test_analysis_application import callbacks, wait_until
from tests.data_manager_test.test_utc_classification_lifecycle import utc_database


def bidirectional_database(tmp_path):
    from leonardo.ohlcv.store import OHLCVStore, Candle
    from leonardo.data_manager import ArtifactCollectionOutputV1
    from tests.data_manager_test.test_update_workflow import _domain, MARKET
    from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
    from tests.data_manager_test.test_artifact_materialization import _utc_recipe
    from tests.data_manager_test.test_database_content_management import _seed_database
    domain, artifacts, recipes, historical = _domain(tmp_path, initialize=False)
    store = OHLCVStore(historical)
    x = np.arange(240)
    closes = 100 + 8*np.sin(x/5) + 12*np.sin(x/45)
    candles = [Candle(1_700_000_000_000+i*60_000, float(v), float(v+1), float(v-1), float(v), 100.)
               for i, v in enumerate(closes)]
    store.write(MARKET, candles, source="test", persistence_status="committed")
    csv, sidecar = store.csv_path(MARKET), store.sidecar_path(MARKET)
    store.publish_validation(MARKET, expected_csv_size=csv.stat().st_size,
        expected_csv_mtime_ns=csv.stat().st_mtime_ns, expected_csv_sha256=sha256(csv.read_bytes()).hexdigest(),
        expected_sidecar_size=sidecar.stat().st_size, expected_sidecar_mtime_ns=sidecar.stat().st_mtime_ns,
        expected_sidecar_sha256=sha256(sidecar.read_bytes()).hexdigest(), status="ok", row_count=len(candles),
        first_timestamp_ms=candles[0].ts_ms, last_timestamp_ms=candles[-1].ts_ms,
        warnings=(), issue_codes=(), error_count=0, warning_count=0, validator="DAS-disposable-fixture")
    peaks = _leaf("peaks_troughs", {})
    recipes.save_recipe(peaks)
    utc = _utc_recipe(peaks, roles=("trend_peak", "trend_trough", "range_peak", "range_trough"))
    materialization = _materialize(domain, recipes, utc)
    _, base = _seed_database(domain, start_index=0)
    selection = ArtifactCollectionOutputV1(materialization.root_logical_artifact_ids[0], "uptrend", "up_0")
    plan = domain.plan_database_content_edit(base.database_id, artifact_additions=(selection,))
    assert not plan.blocked
    manifest = domain.execute_database_content_edit(plan)
    return domain, artifacts, historical, materialization, manifest


def real_study(tmp_path):
    domain, artifacts, historical, materialization, manifest = bidirectional_database(tmp_path)
    service = AnalysisService(domain._creation.store)
    parent = service.run(request(manifest, "close"))
    catalogue = service.load_pattern_catalogue(parent)
    instance = catalogue.to_dict()["instances"][0]
    req = PatternRequest(parent.entry.reference, catalogue.run_key, instance["instance_id"], "T", "UP",
        ("close",), manifest.first_timestamp_ms, manifest.last_timestamp_ms,
        before=1, after=1, sequence_lengths=(2,))
    return service, parent, catalogue, req, domain


def test_all_operations_use_core_and_never_refit_or_mutate(tmp_path, monkeypatch):
    service, parent, catalogue, req, domain = real_study(tmp_path)
    before = files(domain._creation.store.root_dir)
    profiles = tuple(c.profile.to_dict() for c in parent.columns)
    import leonardo.analysis.service as module
    monkeypatch.setattr(module, "fit_directional_binning", lambda *a, **kw: pytest.fail("event filters refitted a profile"))
    manager = TaskManager()
    runner = CoreRunner(manager)
    app = AnalysisApplicationService(runner, service)
    runner.start()
    session = app.begin_session()
    def execute(submit):
        outcomes, done = [], Event()
        submission = submit(**callbacks(outcomes, done))
        assert done.wait(10)
        assert outcomes[0].status == "completed", outcomes[0].error_message
        assert manager.get_snapshot(submission.task_id).metadata["area"] == "analysis"
        return outcomes[0].value
    try:
        copied = execute(lambda **kw: app.submit_pattern_catalogue(session, parent, **kw))
        assert copied.to_dict() == catalogue.to_dict()
        for kind, direction in (("T", "UP"), ("P", "DOWN")):
            families = copied.families(req.instance_id, kind)
            assert families, "Fixture must include both P and T starts"
            selected = replace(req, event_kind=kind, trend_direction=direction, family=families[0]["family"])
            study = execute(lambda **kw: app.submit_patterns(session, parent, selected, **kw))
            assert not study.frame("events").empty
            assert set(study.frame("events").event_kind) == {kind}
            patterns = study.frame("patterns")
            assert not patterns.empty
            matches = execute(lambda **kw: app.submit_pattern_matches(session, study, patterns.iloc[0].pattern_id, "target", **kw))
            assert len(matches) == patterns.iloc[0].matched
            refinement = PatternRefinement(basis="formation", movement_enabled=True,
                movement=(NumericCondition("directional_move", "points", 0),))
            refined = execute(lambda **kw: app.submit_patterns(session, parent, replace(selected, refinement=refinement), **kw))
            assert refined.request.refinement == refinement
            assert set(refined.frame("events").measurement_basis) == {"formation"}
            assert not refined.frame("refinement_funnel").empty
        assert tuple(c.profile.to_dict() for c in parent.columns) == profiles
        assert files(domain._creation.store.root_dir) == before
    finally:
        app.end_session(session)
        runner.shutdown()


@pytest.mark.parametrize("operation", ("utc_catalogue", "patterns", "pattern_matches"))
@pytest.mark.parametrize("outcome", ("cancel", "close", "failure"))
def test_study_workers_drain_and_do_not_publish_partial_or_late_results(tmp_path, monkeypatch, operation, outcome):
    service, parent, catalogue, req, _ = real_study(tmp_path)
    study = service.run_patterns(parent, replace(req, family=catalogue.families(req.instance_id, "T")[0]["family"]))
    started, release, done = Event(), Event(), Event()
    def blocked(*args, checkpoint, **kwargs):
        started.set()
        assert release.wait(10)
        checkpoint()
        raise ValueError("fixture copied-evidence failure")
    method = {"utc_catalogue": "load_pattern_catalogue", "patterns": "run_patterns", "pattern_matches": "pattern_matches"}[operation]
    monkeypatch.setattr(service, method, blocked)
    runner = CoreRunner(TaskManager())
    app = AnalysisApplicationService(runner, service)
    runner.start()
    session, outcomes = app.begin_session(), []
    def submit(**kw):
        if operation == "utc_catalogue":
            return app.submit_pattern_catalogue(session, parent, **kw)
        if operation == "patterns":
            return app.submit_patterns(session, parent, req, **kw)
        return app.submit_pattern_matches(session, study, study.frame("patterns").iloc[0].pattern_id, "target", **kw)
    try:
        submit(**callbacks(outcomes, done))
        assert started.wait(5)
        with pytest.raises(RuntimeError, match="still running"):
            submit(**callbacks([], Event()))
        if outcome == "close":
            app.end_session(session)
        elif outcome == "cancel":
            assert app.cancel(session)
        if outcome != "failure":
            assert app.has_draining_workers and not done.is_set()
        release.set()
        if outcome == "close":
            wait_until(lambda: not app.is_busy(session))
            assert outcomes == []
        else:
            assert done.wait(5)
            assert outcomes[0].status == ("cancelled" if outcome == "cancel" else "failed")
            assert outcomes[0].value is None
            if outcome == "failure":
                assert "copied-evidence failure" in outcomes[0].error_message
    finally:
        release.set()
        app.end_session(session)
        runner.shutdown()
