from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _direct_calls(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_real_service_research_composition_has_one_shared_construction_authority() -> None:
    paths = {
        "main_composition": ROOT / "src/leonardo/gui/composition.py",
        "research_composition": ROOT
        / "src/leonardo/gui/research/composition.py",
        "service_launcher": ROOT
        / "tools/dev_launch_research_gui_service_wiring.py",
    }
    sources = {
        name: path.read_text(encoding="utf-8") for name, path in paths.items()
    }
    for source in sources.values():
        ast.parse(source)

    main_composition = sources["main_composition"]
    research_composition = sources["research_composition"]
    service_launcher = sources["service_launcher"]

    assert (
        "from leonardo.gui.research.composition import "
        "create_restored_research_suite"
    ) in main_composition
    assert "create_restored_research_suite(" in main_composition
    assert "leonardo.gui.windows.research_suite_window" not in main_composition
    assert "ResearchSuitePresenter" not in main_composition
    assert "ResearchSuiteWindow" not in _direct_calls(main_composition)
    assert "RestoredResearchLifecyclePresenter" not in _direct_calls(
        main_composition
    )

    assert (
        "from leonardo.gui.research.composition import "
        "create_restored_research_suite"
    ) in service_launcher
    assert "create_restored_research_suite(" in service_launcher
    assert "ResearchSuiteWindow" not in _direct_calls(service_launcher)
    assert "RestoredResearchLifecyclePresenter" not in _direct_calls(
        service_launcher
    )

    direct_calls = _direct_calls(research_composition)
    assert "ResearchSuiteWindow" in direct_calls
    assert "RestoredResearchLifecyclePresenter" in direct_calls
    assert "create_restored_research_suite" in research_composition
    for forbidden in (
        "LeonardoApp",
        "CoreRunner",
        "TaskManager",
        "WindowRegistry",
        "OHLCVStore",
        "ArtifactService",
        "AcceptedDatasetCatalog",
        "research_gui_dev_fixtures",
    ):
        assert forbidden not in research_composition
