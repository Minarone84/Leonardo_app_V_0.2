from pathlib import Path


def test_composition_exposes_one_snapshot_application_service():
    app = Path("src/leonardo/core/app.py").read_text(encoding="utf-8")
    composition = Path("src/leonardo/gui/composition.py").read_text(encoding="utf-8")
    assert app.count("ResearchWorkspaceSnapshotStore(") == 1
    assert "research_workspace_snapshot_service" in composition
