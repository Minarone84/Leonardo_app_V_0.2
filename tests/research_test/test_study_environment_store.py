from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from leonardo.research import (
    StudyEnvironmentAlreadyExistsError,
    StudyEnvironmentDraft,
    StudyEnvironmentStore,
    StudyEnvironmentValidationError,
    StudyEnvironmentV1,
)

from tests.research_test.test_study_environment_models import fixture_environment


def draft(name: str = "Momentum Structure") -> StudyEnvironmentDraft:
    source = fixture_environment()
    return StudyEnvironmentDraft(name, source.description, source.created_from, source.entries)


def test_store_create_update_list_load_delete_and_root_on_write(tmp_path: Path) -> None:
    root = tmp_path / "environments"
    now = datetime(2026, 7, 17, 10, tzinfo=timezone.utc)
    ticks = iter((now, now + timedelta(minutes=1)))
    store = StudyEnvironmentStore(root, clock=lambda: next(ticks), id_factory=lambda: "fixed")

    assert store.list_summaries() == ()
    assert not root.exists()
    created = store.create(draft())
    assert created.environment_id == "env_fixed"
    assert store.load(created.environment_id) == created
    assert store.list_summaries()[0].valid
    updated = store.update(created.environment_id, draft("Renamed Environment"))
    assert updated.created_at_utc == created.created_at_utc
    assert updated.updated_at_utc > created.updated_at_utc
    assert store.delete(created.environment_id).environment_id == created.environment_id
    assert store.list_summaries() == ()


def test_store_enforces_unique_names_and_lists_invalid_files(tmp_path: Path) -> None:
    store = StudyEnvironmentStore(tmp_path, id_factory=lambda: "one")
    store.create(draft())
    with pytest.raises(StudyEnvironmentAlreadyExistsError):
        store.create(StudyEnvironmentDraft("momentum structure", "", None, draft().entries, "env_two"))
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    summaries = store.list_summaries()
    assert any(not item.valid and item.environment_id == "broken" for item in summaries)
    with pytest.raises(StudyEnvironmentValidationError):
        store.load("broken")


def test_invalid_noncanonical_file_is_listed_and_exactly_deleted(tmp_path: Path) -> None:
    target = tmp_path / "BAD NAME.json"
    sibling = tmp_path / "KEEP ME.json"
    target.write_text("{", encoding="utf-8")
    sibling.write_text("{", encoding="utf-8")
    store = StudyEnvironmentStore(tmp_path)

    summary = next(
        item for item in store.list_summaries() if item.environment_id == "BAD NAME"
    )
    assert not summary.valid
    assert store.delete(summary.environment_id) == summary
    assert not target.exists()
    assert sibling.read_text(encoding="utf-8") == "{"


def test_invalid_delete_rejects_traversal_external_and_non_file_targets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "environments"
    root.mkdir()
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    (root / "DIRECTORY.json").mkdir()
    store = StudyEnvironmentStore(root)

    for identity in ("", ".", "..", "../external", "..\\external", str(external)):
        with pytest.raises(StudyEnvironmentValidationError):
            store.delete(identity)
    with pytest.raises(StudyEnvironmentValidationError):
        store.delete("DIRECTORY")
    assert external.read_text(encoding="utf-8") == "external"


def test_invalid_delete_rejects_file_link_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "environments"
    root.mkdir()
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    linked = root / "BAD LINK.json"
    try:
        linked.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"operating system denied symbolic-link creation: {exc}")
    store = StudyEnvironmentStore(root)

    with pytest.raises(StudyEnvironmentValidationError, match="link"):
        store.delete("BAD LINK")
    assert linked.is_symlink()
    assert external.read_text(encoding="utf-8") == "external"


def test_failed_atomic_update_preserves_previous_file(tmp_path: Path, monkeypatch) -> None:
    store = StudyEnvironmentStore(tmp_path, id_factory=lambda: "one")
    created = store.create(draft())
    path = store.environment_path(created.environment_id)
    before = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        store.update(created.environment_id, draft("Updated"))
    assert path.read_bytes() == before
    assert not tuple(tmp_path.glob("*.tmp"))


def test_store_rejects_symlink_paths_when_supported(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"operating system denied symbolic-link creation: {exc}")
    store = StudyEnvironmentStore(linked)
    with pytest.raises(StudyEnvironmentValidationError, match="link"):
        store.list_summaries()
