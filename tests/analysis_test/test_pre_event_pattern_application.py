from dataclasses import replace
from threading import Event

from leonardo.analysis.application import AnalysisApplicationService
from leonardo.analysis.pattern_models import PreEventSpec, PatternRefinement, NumericCondition
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from tests.analysis_test.test_trend_start_application import real_study
from tests.analysis_test.test_analysis_application import callbacks
from tests.analysis_test.test_analysis_service import files


def test_pre_event_execution_and_later_refinement_use_core_without_refitting_or_writes(tmp_path, monkeypatch):
    service, parent, catalogue, req, domain = real_study(tmp_path)
    profile = tuple(c.profile.to_dict() for c in parent.columns)
    before = files(domain._creation.store.root_dir)
    import leonardo.analysis.service as module
    def forbidden(*args, **kwargs):
        raise AssertionError("pre-event study must reuse the completed bins")
    monkeypatch.setattr(module, "fit_directional_binning", forbidden)
    manager = TaskManager(); runner = CoreRunner(manager)
    app = AnalysisApplicationService(runner, service)
    runner.start(); session = app.begin_session()
    def execute(submit):
        values, done = [], Event()
        submission = submit(**callbacks(values, done))
        assert done.wait(20)
        assert values[0].status == "completed", values[0].error_message
        assert manager.get_snapshot(submission.task_id).metadata["area"] == "analysis"
        return values[0].value
    try:
        req = replace(req, family=catalogue.families(req.instance_id, "T")[0]["family"],
                      pre_event=PreEventSpec(max_terms=2), comparison="non_start", min_matches=1)
        result = execute(lambda **kw: app.submit_patterns(session, parent, req, **kw))
        assert not result.frame("patterns").empty
        row = result.frame("patterns").iloc[0]
        ledger = execute(lambda **kw: app.submit_pattern_matches(session, result, row.pattern_id, "target", **kw))
        assert ledger.matched.sum() == row.matched
        ref = PatternRefinement(basis="formation", movement_enabled=True,
                                movement=(NumericCondition("directional_move", "pct", 100000),))
        refined = execute(lambda **kw: app.submit_patterns(session, parent, replace(req, refinement=ref), **kw))
        assert refined.frame("patterns").empty
        assert result.frame("patterns").iloc[0].matched == row.matched
        assert tuple(c.profile.to_dict() for c in parent.columns) == profile
        assert files(domain._creation.store.root_dir) == before
    finally:
        app.end_session(session); runner.shutdown()
