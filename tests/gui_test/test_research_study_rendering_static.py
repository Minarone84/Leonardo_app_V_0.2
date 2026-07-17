from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_task_1018_module_boundaries_and_inventory_are_exact() -> None:
    pure = (
        ROOT / "src/leonardo/research/study_presentation.py",
        ROOT / "src/leonardo/gui/chart/study_scene.py",
        ROOT / "src/leonardo/gui/chart/oscillator_scene.py",
    )
    for path in pure:
        assert "PySide6" not in path.read_text(encoding="utf-8")

    gui_paths = (
        ROOT / "src/leonardo/gui/chart/candlestick_widget.py",
        ROOT / "src/leonardo/gui/chart/oscillator_widget.py",
        ROOT / "src/leonardo/gui/chart/pane_workspace.py",
        ROOT / "src/leonardo/gui/widgets/study_manager_widget.py",
        ROOT / "src/leonardo/gui/windows/study_style_dialog.py",
        ROOT / "src/leonardo/gui/presenters/research_presenter.py",
    )
    forbidden = (
        "calculate_financial_tool",
        "ArtifactService",
        "pathlib",
        "Path(",
        "DatasetId",
        "dummy",
        "StudyEnvironment",
        "workspace_snapshot",
    )
    for path in gui_paths:
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path

    expected_new = {
        "src/leonardo/research/study_presentation.py",
        "src/leonardo/gui/chart/study_scene.py",
        "src/leonardo/gui/chart/oscillator_scene.py",
        "src/leonardo/gui/chart/oscillator_widget.py",
        "src/leonardo/gui/widgets/study_manager_widget.py",
        "src/leonardo/gui/windows/study_style_dialog.py",
    }
    assert all((ROOT / path).is_file() for path in expected_new)
