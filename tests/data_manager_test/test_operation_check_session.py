from __future__ import annotations

import pytest
from leonardo.artifacts import ArtifactLineageError

from tests.data_manager_test.test_update_workflow import MARKET, _append, _domain


def _count_parses(monkeypatch, service):
    calls = []
    original = service._loader._parse

    def parse(summary, **kwargs):
        calls.append(summary.market_id)
        return original(summary, **kwargs)

    monkeypatch.setattr(service._loader, "_parse", parse)
    return calls


def test_selection_and_nested_captures_reuse_exact_session_evidence(tmp_path, monkeypatch):
    service, artifacts, _recipes, _historical = _domain(tmp_path)
    calls = _count_parses(monkeypatch, service)
    service.begin_session()
    service.inspect_market(MARKET)
    service.inspect_market(MARKET)
    with service._operation_checks():
        first = artifacts.capture_accepted_source(MARKET)
        assert artifacts.capture_accepted_source(MARKET) == first
        service._loader.load(MARKET)
    assert calls == [MARKET]
    assert artifacts._dms_checks.get() is None
    service.end_session()
    service.begin_session()
    service.inspect_market(MARKET)
    assert calls == [MARKET, MARKET]


def test_source_change_and_explicit_invalidation_discard_only_affected_success(tmp_path, monkeypatch):
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    calls = _count_parses(monkeypatch, service)
    service.inspect_market(MARKET)
    _append(historical)
    service.inspect_market(MARKET)
    assert calls == [MARKET, MARKET]
    service.invalidate_source(MARKET)
    service.inspect_market(MARKET)
    assert calls == [MARKET, MARKET, MARKET]


def test_failed_source_check_never_grants_reusable_success(tmp_path, monkeypatch):
    service, artifacts, _recipes, _historical = _domain(tmp_path)
    calls = _count_parses(monkeypatch, service)
    path = artifacts._ohlcv_store.csv_path(MARKET)
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    for _ in range(2):
        with pytest.raises(ValueError):
            service.inspect_market(MARKET)
    assert MARKET not in service._source_evidence
    path.write_bytes(original)
    service.inspect_market(MARKET)
    assert calls == [MARKET, MARKET, MARKET]


def test_shared_strict_defaults_do_not_trust_dms_success(tmp_path):
    service, artifacts, _recipes, _historical = _domain(tmp_path)
    service.inspect_market(MARKET)
    path = artifacts._ohlcv_store.csv_path(MARKET)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ArtifactLineageError):
        artifacts.capture_accepted_source(MARKET)
    assert service._catalog.scan().rejected
    with pytest.raises(PermissionError):
        service._loader.load(MARKET)


def test_change_during_check_cannot_publish_success(tmp_path, monkeypatch):
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    original = service._loader._parse

    def parse(summary, **kwargs):
        result = original(summary, **kwargs)
        _append(historical)
        service.invalidate_source(MARKET)
        return result

    monkeypatch.setattr(service._loader, "_parse", parse)
    with pytest.raises(RuntimeError, match="changed during checking"):
        service.inspect_market(MARKET)
    assert MARKET not in service._source_evidence


def test_first_check_reports_progress_and_honors_cancellation(tmp_path):
    service, artifacts, _recipes, _historical = _domain(tmp_path)
    events = []
    cancelled = False

    def progress(current, total, message):
        nonlocal cancelled
        events.append((current, total, message))
        cancelled = True

    with service._operation_checks(progress=progress, cancellation_requested=lambda: cancelled):
        with pytest.raises(RuntimeError, match="cancelled"):
            artifacts.capture_accepted_source(MARKET)
    assert events and "Checking OHLCV" in events[0][2]
    assert MARKET not in service._source_evidence


def test_dispose_during_check_cannot_restore_session_evidence(tmp_path, monkeypatch):
    service, artifacts, _recipes, _historical = _domain(tmp_path)
    original = service._loader._parse

    def parse(summary, **kwargs):
        dataset = original(summary, **kwargs)
        service.end_session()
        return dataset

    monkeypatch.setattr(service._loader, "_parse", parse)
    with service._operation_checks():
        with pytest.raises(RuntimeError, match="changed during checking"):
            artifacts.capture_accepted_source(MARKET)
        with pytest.raises(RuntimeError, match="session ended"):
            artifacts.capture_accepted_source(MARKET)
    assert service._source_evidence == {}


def test_loader_eviction_keeps_evidence_without_retaining_ohlcv_values(tmp_path, monkeypatch):
    service, artifacts, _recipes, _historical = _domain(tmp_path)
    calls = _count_parses(monkeypatch, service)
    service.inspect_market(MARKET)
    evidence = service._source_evidence[MARKET]
    assert isinstance(evidence[2], tuple)
    assert all(type(timestamp) is int for timestamp in evidence[2])
    service._loader.clear_cache()
    with service._operation_checks():
        artifacts.capture_accepted_source(MARKET)
        assert calls == [MARKET]
        service._loader.load(MARKET)
    assert calls == [MARKET, MARKET]  # One required data load after eviction.
