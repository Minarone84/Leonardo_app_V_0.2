from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).parents[2]

PRODUCTION_PATHS = (
    "src/leonardo/research/__init__.py",
    "src/leonardo/research/workspace.py",
    "src/leonardo/gui/composition.py",
    "src/leonardo/gui/presenters/research_presenter.py",
    "src/leonardo/gui/presenters/research_chart_presenter.py",
    "src/leonardo/gui/widgets/__init__.py",
    "src/leonardo/gui/widgets/research_workspace_layout.py",
    "src/leonardo/gui/widgets/research_chart_slot_widget.py",
    "src/leonardo/gui/widgets/research_workspace_widget.py",
    "src/leonardo/gui/windows/research_suite_window.py",
)

ADDED_TEST_AND_DOC_PATHS = (
    "tests/research_test/test_research_workspace_state.py",
    "tests/gui_test/test_research_workspace_layout.py",
    "tests/gui_test/test_research_chart_slot_widget.py",
    "tests/gui_test/test_research_workspace_widget.py",
    "tests/gui_test/test_research_multi_chart_presenter.py",
    "tests/gui_test/test_research_multi_chart_concurrency.py",
    "tests/gui_test/test_research_multi_chart_integration.py",
    "tests/gui_test/test_research_multi_chart_static.py",
    "tests/gui_test/fixtures/task_1019_workspace_input.json",
    "tests/gui_test/fixtures/task_1019_workspace_expected.json",
    "docs/core_docs/TASK_1019_EIGHT_SLOT_RESEARCH_WORKSPACE.md",
)

TASK_1019_WORKSPACE_PATHS = (
    "src/leonardo/research/workspace.py",
    "src/leonardo/gui/widgets/research_workspace_layout.py",
    "src/leonardo/gui/widgets/research_chart_slot_widget.py",
    "src/leonardo/gui/widgets/research_workspace_widget.py",
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> tuple[str, ...]:
    tree = ast.parse(_source(relative))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return tuple(names)


def test_domain_and_layout_are_qt_free() -> None:
    for path in (
        "src/leonardo/research/workspace.py",
        "src/leonardo/gui/widgets/research_workspace_layout.py",
    ):
        assert all(not name.startswith("PySide6") for name in _imports(path))


def test_widgets_do_not_import_services_calculation_persistence_or_filesystem() -> None:
    forbidden = (
        "leonardo.research.application",
        "leonardo.research.study_application",
        "leonardo.financial_tools",
        "leonardo.artifacts",
        "pathlib",
        "os",
    )
    for path in (
        "src/leonardo/gui/widgets/research_chart_slot_widget.py",
        "src/leonardo/gui/widgets/research_workspace_widget.py",
    ):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports)


def test_presenter_boundaries_exclude_core_store_and_artifact_service() -> None:
    suite_source = _source("src/leonardo/gui/presenters/research_presenter.py")
    assert "CoreRunner(" not in suite_source
    assert "OHLCVStore(" not in suite_source
    assert "ArtifactService(" not in suite_source
    chart_imports = _imports(
        "src/leonardo/gui/presenters/research_chart_presenter.py"
    )
    assert "leonardo.artifacts" not in chart_imports
    assert not any(name.startswith("leonardo.ohlcv") for name in chart_imports)


def test_no_later_task_implementations_enter_task_1019_production() -> None:
    combined = "\n".join(_source(path) for path in TASK_1019_WORKSPACE_PATHS)
    for token in (
        "PanAnchor",
        "WorkspaceSnapshot",
        "StudyEnvironment",
        "Notebook",
        "GoToDate",
        "detach_chart",
        "dock_chart",
    ):
        assert token not in combined


def test_exact_task_inventory_and_fixture_hashes() -> None:
    assert all((ROOT / path).is_file() for path in PRODUCTION_PATHS)
    assert all((ROOT / path).is_file() for path in ADDED_TEST_AND_DOC_PATHS)
    expected_hashes = {
        "tests/gui_test/fixtures/task_1019_workspace_input.json": (
            "1863fd43d51ed30c2b2fee71baf2b2a4ca3c949306a5103a57134cc8708ed1b8"
        ),
        "tests/gui_test/fixtures/task_1019_workspace_expected.json": (
            "9ddfbc8f38e4a5e24fee1e35eb733fe5cf11c37816b51d16dfefc79674badd57"
        ),
    }
    for path, expected in expected_hashes.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
