import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from leonardo.research.notebook import (
    ResearchNotebookAlreadyExistsError,
    ResearchNotebookDraft,
    ResearchNotebookV1,
)
from leonardo.research.notebook_store import ResearchNotebookStore


def _notebook():
    payload = json.loads(
        Path("tests/gui_test/fixtures/task_1023_research_notebook_input.json").read_text(
            encoding="utf-8"
        )
    )["notebook"]
    return ResearchNotebookV1.from_dict(payload)


def _draft(notebook, *, name=None):
    return ResearchNotebookDraft(
        notebook_id=notebook.notebook_id,
        display_name=name or notebook.display_name,
        description=notebook.description,
        annotation_settings=notebook.annotation_settings,
        pages=notebook.pages,
    )


def test_store_create_update_load_list_and_delete(tmp_path):
    now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    store = ResearchNotebookStore(tmp_path / "notebooks", clock=lambda: now)
    assert store.list_summaries() == ()
    assert not store.root_dir.exists()
    created = store.create(_draft(_notebook()))
    assert store.load(created.notebook_id) == created
    summary = store.list_summaries()[0]
    assert (
        summary.page_count,
        summary.note_count,
        summary.potential_trade_count,
        summary.point_of_interest_count,
    ) == (2, 3, 2, 2)
    updated = store.update(
        created.notebook_id, _draft(created, name="Updated Journal")
    )
    assert updated.created_at_utc == created.created_at_utc
    assert updated.notebook_id == created.notebook_id
    store.delete(created.notebook_id)
    assert store.list_summaries() == ()


def test_invalid_direct_child_remains_visible_and_is_exactly_deletable(tmp_path):
    root = tmp_path / "notebooks"
    root.mkdir()
    invalid = root / "Invalid Name.json"
    invalid.write_text("{}", encoding="utf-8")
    neighbor = root / "neighbor.txt"
    neighbor.write_text("keep", encoding="utf-8")
    store = ResearchNotebookStore(root)
    summary = store.list_summaries()[0]
    assert not summary.valid
    assert summary.rejection_reason
    store.delete("Invalid Name")
    assert not invalid.exists()
    assert neighbor.read_text(encoding="utf-8") == "keep"


def test_display_names_are_unique_case_insensitively(tmp_path):
    store = ResearchNotebookStore(
        tmp_path / "notebooks",
        clock=lambda: datetime(2026, 7, 17, 12, tzinfo=timezone.utc),
    )
    notebook = _notebook()
    store.create(_draft(notebook))
    duplicate = ResearchNotebookDraft(
        notebook_id="notebook_other",
        display_name=notebook.display_name.upper(),
        description="",
        annotation_settings=notebook.annotation_settings,
        pages=(),
    )
    with pytest.raises(ResearchNotebookAlreadyExistsError):
        store.create(duplicate)


def test_failed_atomic_update_preserves_exact_prior_bytes(tmp_path, monkeypatch):
    store = ResearchNotebookStore(
        tmp_path / "notebooks",
        clock=lambda: datetime(2026, 7, 17, 12, tzinfo=timezone.utc),
    )
    created = store.create(_draft(_notebook()))
    path = store.notebook_path(created.notebook_id)
    before = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replacement failure")

    monkeypatch.setattr("leonardo.research.notebook_store.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        store.update(created.notebook_id, _draft(created, name="Changed"))
    assert path.read_bytes() == before
    assert not tuple(store.root_dir.glob("*.tmp"))
