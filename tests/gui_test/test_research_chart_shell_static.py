from __future__ import annotations

import ast
from pathlib import Path


def test_pure_shell_and_navigation_have_no_qt_imports() -> None:
    for path in (
        Path("src/leonardo/research/workspace_shell.py"),
        Path("src/leonardo/gui/chart/navigation.py"),
        Path("src/leonardo/gui/widgets/research_workspace_layout.py"),
    ):
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        assert "PySide6" not in source


def test_shell_widgets_do_not_own_services_or_persistence() -> None:
    paths = (
        "src/leonardo/gui/widgets/research_chart_slot_widget.py",
        "src/leonardo/gui/widgets/research_workspace_widget.py",
        "src/leonardo/gui/windows/research_chart_window.py",
        "src/leonardo/gui/windows/research_go_to_dialog.py",
    )
    forbidden = (
        "ArtifactService",
        "ResearchDatasetApplicationService",
        "ResearchStudyApplicationService",
        "pathlib",
    )
    for path in paths:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert all(token not in source for token in forbidden)
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            for node in ast.walk(tree)
        )


def test_task_1021_through_1025_features_are_absent() -> None:
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/leonardo/research/workspace_shell.py",
            "src/leonardo/gui/presenters/research_presenter.py",
            "src/leonardo/gui/windows/research_suite_window.py",
        )
    )
    for forbidden in (
        "StudyEnvironment",
        "WorkspaceSnapshot",
        "Notebook",
        "Annotation",
        "DataManager",
        "Backtest",
    ):
        assert forbidden not in sources
