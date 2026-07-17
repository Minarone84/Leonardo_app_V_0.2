from pathlib import Path


def test_restore_uses_run_generation_and_slot_session_guards():
    source = Path("src/leonardo/gui/presenters/research_presenter.py").read_text(encoding="utf-8")
    assert "workspace_generation" in source
    assert "outcome.session_id" in source
    assert "run.run_id" in source
