from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def _imports(path: str) -> tuple[str, ...]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return tuple(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )


def test_pure_modules_and_gui_boundaries_remain_separate() -> None:
    for path in (
        "src/leonardo/research/notebook.py",
        "src/leonardo/research/notebook_store.py",
        "src/leonardo/research/notebook_service.py",
        "src/leonardo/gui/chart/annotation_scene.py",
    ):
        assert not any(name.startswith("PySide6") for name in _imports(path))
    for path in (
        "src/leonardo/gui/windows/research_notebook_window.py",
        "src/leonardo/gui/windows/research_notebook_manager_dialog.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        for forbidden in (
            "ResearchNotebookStore",
            "CoreRunner",
            "ArtifactService",
            "WorkspaceSnapshot",
        ):
            assert forbidden not in source


def test_snapshot_schema_has_no_notebook_reference() -> None:
    source = (ROOT / "src/leonardo/research/workspace_snapshot.py").read_text(
        encoding="utf-8"
    )
    assert "notebook" not in source.lower()
