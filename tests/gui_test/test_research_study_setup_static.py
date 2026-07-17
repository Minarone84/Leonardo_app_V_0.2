from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_task_1021_pure_modules_have_no_qt_and_gui_has_no_owner_imports() -> None:
    pure = (
        ROOT / "src/leonardo/research/study_setup.py",
        ROOT / "src/leonardo/research/study_environment.py",
        ROOT / "src/leonardo/research/study_environment_store.py",
    )
    for path in pure:
        assert "PySide6" not in path.read_text(encoding="utf-8")

    gui = (
        ROOT / "src/leonardo/gui/widgets/study_source_selector_widget.py",
        ROOT / "src/leonardo/gui/windows/study_setup_dialog.py",
        ROOT / "src/leonardo/gui/windows/study_environment_save_dialog.py",
        ROOT / "src/leonardo/gui/windows/study_environment_manager_dialog.py",
    )
    forbidden = ("ArtifactService", "pathlib", "os.", "calculate_financial_tool")
    for path in gui:
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        assert not any(value in source for value in forbidden)
