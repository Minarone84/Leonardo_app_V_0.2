"""R03 reviewed-content contract; genuine stores, public API and Core commands."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from collections.abc import Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Event

import pytest

from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data_manager import DataManagerApplicationService, DataManagerOperationError
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.research import StudyEnvironmentDraft
from tests.data_manager_test.test_artifact_materialization import _domain
from tests.data_manager_test.test_portable_recipe_workflow import _save_environment
from tests.research_test.test_study_environment_models import fixture_environment


def _plain(value):
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _receipt(label, **values):
    destination = os.environ.get("R03_OBSERVATIONS") or os.environ.get("R02_OBSERVATIONS")
    if destination:
        node = os.environ.get("PYTEST_CURRENT_TEST", "external")
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        name = sha256((node + label).encode()).hexdigest()[:20]
        (path / (name + ".json")).write_text(
            json.dumps({"node": node, "label": label, **values}, default=str,
                       indent=2, sort_keys=True), encoding="utf-8")


def _inventory(root):
    return {p.relative_to(root).as_posix(): {"size": p.stat().st_size,
            "sha256": sha256(p.read_bytes()).hexdigest()}
            for p in sorted(root.rglob("*")) if p.is_file()}


def _entry(period):
    entry = fixture_environment().entries[0]
    parameters = dict(resolve_parameters("ema", {"period": period}))
    outputs = resolve_output_names("ema", parameters)
    return replace(entry, parameters=parameters, expected_output_names=outputs,
                   presentation=replace(entry.presentation, line_styles=tuple(
                       replace(style, output_name=outputs[0])
                       for style in entry.presentation.line_styles)))


def _setup(tmp_path):
    market, service, artifacts, recipes, historical, environments = _domain(tmp_path / "d")
    environment = _save_environment(environments, market=market, entries=(_entry(3),))
    roots = (environment.entries[0].entry_id,)
    plan = service.plan_recipe_derivation(environment.environment_id, roots)
    assert not plan.blocked
    return service, environments, recipes, environment, roots, plan


def _edit(store, environment, period=5):
    return store.update(environment.environment_id, StudyEnvironmentDraft(
        environment.display_name, environment.description, environment.created_from,
        (_entry(period),), environment.environment_id))


@contextmanager
def _application(service):
    runner = CoreRunner(TaskManager())
    application = DataManagerApplicationService(runner, service)
    runner.start()
    try:
        yield application
    finally:
        runner.shutdown()


def _core_call(submit, *args, **kwargs):
    done = Event()
    results = []
    def settled(result):
        results.append(result)
        done.set()
    submission = submit(*args, result_callback=settled, **kwargs)
    assert done.wait(10), "Core command did not drain"
    assert len(results) == 1
    assert results[0].task_id == submission.task_id
    _receipt("core", result=_plain(results[0]) if is_dataclass(results[0]) else repr(results[0]))
    return results[0]


def _invoke(service, route, environment, roots, **kwargs):
    kwargs.setdefault("create_collection", False)
    if route == "sync":
        try:
            return "completed", service.persist_recipe_derivation(environment, roots, **kwargs)
        except DataManagerOperationError as error:
            return "failed", str(error)
    with _application(service) as application:
        result = _core_call(application.submit_persist_recipe_derivation,
                            environment, roots, **kwargs)
    return result.status, result.value if result.status == "completed" else result.error_message


@pytest.mark.parametrize("route", ["sync", "core"])
@pytest.mark.parametrize("token_kind", ["stale", "empty", "upper", "short", "space", "integer"])
@pytest.mark.parametrize("collection", [False, True])
def test_supplied_token_refuses_stale_or_malformed_without_writes(tmp_path, route, token_kind, collection):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    token = {"stale": plan.environment_content_hash, "empty": "", "upper": "A" * 64,
             "short": "a" * 63, "space": " " + "a" * 64, "integer": 7}[token_kind]
    if token_kind == "stale":
        _edit(store, env)
    before = _inventory(recipes.root_dir)
    state, value = _invoke(service, route, env.environment_id, roots,
        create_collection=collection, collection_display_name="R03", expected_environment_content_hash=token)
    after = _inventory(recipes.root_dir)
    _receipt("refusal", before=before, after=after, status=state, message=value, token=token)
    assert state == "failed"
    assert "Preview again" in value
    assert after == before


@pytest.mark.parametrize("route", ["sync", "core"])
@pytest.mark.parametrize("token_mode", ["valid", "explicit_none", "omitted"])
def test_valid_and_none_programmatic_paths(tmp_path, route, token_mode):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    options = {} if token_mode == "omitted" else {"expected_environment_content_hash":
        plan.environment_content_hash if token_mode == "valid" else None}
    state, result = _invoke(service, route, env.environment_id, roots, **options)
    assert state == "completed"
    assert result.created_recipe_ids == (plan.recipes[0].recipe_id,)
    assert result.new_provenance_ids
    _receipt("valid", result=_plain(result), disk=_inventory(recipes.root_dir), mode=token_mode)


@pytest.mark.parametrize("route", ["sync", "core"])
@pytest.mark.parametrize("token_mode", ["reviewed", "legacy"])
def test_execution_read_drift_and_gate_seam_refuse(tmp_path, monkeypatch, route, token_mode):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    original = store.load
    reads = []
    def load(identity):
        reads.append(identity)
        if len(reads) == 2:
            _edit(store, env)
        return original(identity)
    monkeypatch.setattr(store, "load", load)
    before = _inventory(recipes.root_dir)
    status, message = _invoke(service, route, env.environment_id, roots,
        expected_environment_content_hash=plan.environment_content_hash if token_mode == "reviewed" else None)
    after = _inventory(recipes.root_dir)
    _receipt("double_read", before=before, after=after, reads=reads, status=status, message=message)
    assert status == "failed" and "changed" in message
    assert after == before


@pytest.mark.parametrize("route", ["sync", "core"])
def test_before_publish_seam_rechecks_reviewed_content(tmp_path, monkeypatch, route):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    before = _inventory(recipes.root_dir)
    gates = []
    if route == "sync":
        def gate():
            gates.append("entered")
            _edit(store, env)
        with pytest.raises(DataManagerOperationError, match="Preview again"):
            service._persist_recipe_derivation(env.environment_id, roots, create_collection=False,
                expected_environment_content_hash=plan.environment_content_hash, before_publish=gate)
    else:
        # Instrument only the existing gate seam, retaining the real gate implementation.
        from leonardo.data_manager.application import _CancellationGate
        original = _CancellationGate.begin_destructive
        def gate(self):
            original(self)
            gates.append("entered")
            _edit(store, env)
        monkeypatch.setattr(_CancellationGate, "begin_destructive", gate)
        status, message = _invoke(service, route, env.environment_id, roots,
            expected_environment_content_hash=plan.environment_content_hash)
        assert status == "failed" and "Preview again" in message
    after = _inventory(recipes.root_dir)
    _receipt("gate_seam", before=before, after=after, gates=gates)
    assert gates == ["entered"] and after == before


@pytest.mark.parametrize("route", ["sync", "core"])
@pytest.mark.parametrize("fault", ["deleted", "blocked_root", "cancelled"])
def test_missing_blocked_and_cancelled_leave_store_unchanged(tmp_path, monkeypatch, route, fault):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    before = _inventory(recipes.root_dir)
    if fault == "deleted":
        store.delete(env.environment_id)
    if fault == "blocked_root":
        roots = ("missing_entry",)
    if fault == "cancelled" and route == "sync":
        def refuse():
            raise RuntimeError("Data Manager operation cancelled before publication")
        with pytest.raises(RuntimeError, match="cancelled before publication"):
            service._persist_recipe_derivation(env.environment_id, roots, create_collection=False,
                expected_environment_content_hash=plan.environment_content_hash, before_publish=refuse)
    elif fault == "cancelled":
        entered, release, done = Event(), Event(), Event()
        original = service._build_derivation_plan
        def hold(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return original(*args, **kwargs)
        monkeypatch.setattr(service, "_build_derivation_plan", hold)
        results = []
        with _application(service) as app:
            submission = app.submit_persist_recipe_derivation(env.environment_id, roots, create_collection=False,
                expected_environment_content_hash=plan.environment_content_hash,
                result_callback=lambda result: (results.append(result), done.set()))
            try:
                assert entered.wait(10)
                assert app.cancel(submission.task_id)
            finally:
                release.set()
            assert done.wait(10)
        assert len(results) == 1 and results[0].status == "cancelled"
    else:
        state, message = _invoke(service, route, env.environment_id, roots,
            expected_environment_content_hash=plan.environment_content_hash)
        assert state == "failed" and message
    after = _inventory(recipes.root_dir)
    _receipt("nonwrite_control", before=before, after=after, fault=fault, route=route)
    assert after == before


@pytest.mark.parametrize("route", ["sync", "core"])
@pytest.mark.parametrize("collection", [False, True])
def test_semantic_reuse_and_provenance_collection_outcomes(tmp_path, route, collection):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    # Legitimate competing persistence changes actions, not reviewed Environment content.
    recipes.save_recipe(plan.recipes[0])
    kwargs = dict(create_collection=collection, collection_display_name="Reviewed roots",
                  expected_environment_content_hash=plan.environment_content_hash)
    state, first = _invoke(service, route, env.environment_id, roots, **kwargs)
    assert state == "completed" and not first.created_recipe_ids
    assert first.reused_recipe_ids == (plan.recipes[0].recipe_id,) and first.new_provenance_ids
    assert first.collection_outcome == ("CREATED" if collection else "NONE")
    before = _inventory(recipes.root_dir)
    state, second = _invoke(service, route, env.environment_id, roots, **kwargs)
    after = _inventory(recipes.root_dir)
    _receipt("reuse", first=_plain(first), second=_plain(second), before=before, after=after)
    assert state == "completed" and not second.new_provenance_ids
    assert second.existing_provenance_ids == first.new_provenance_ids
    assert second.collection_outcome == ("REUSED_EXISTING" if collection else "NONE")
    assert after == before


def test_later_environment_edit_does_not_mutate_saved_recipe(tmp_path):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    result = service.persist_recipe_derivation(env.environment_id, roots, create_collection=False,
        expected_environment_content_hash=plan.environment_content_hash)
    before = _inventory(recipes.root_dir)
    changed = _edit(store, env)
    assert changed.content_hash != plan.environment_content_hash
    assert _inventory(recipes.root_dir) == before
    assert recipes.load_recipe(result.root_recipe_ids[0]).parameters["period"] == 3
    _receipt("saved_snapshot", disk=before, reviewed=plan.environment_content_hash,
             current=changed.content_hash, result=_plain(result))
