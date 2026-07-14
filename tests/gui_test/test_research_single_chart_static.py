from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_single_chart_research_wiring_is_explicit_and_legacy_free() -> None:
    paths = {
        "window": ROOT / "src/leonardo/gui/windows/research_suite_window.py",
        "presenter": ROOT / "src/leonardo/gui/presenters/research_presenter.py",
        "composition": ROOT / "src/leonardo/gui/composition.py",
        "application": ROOT / "src/leonardo/research/application.py",
        "volume": ROOT / "src/leonardo/research/volume.py",
        "workspace": ROOT / "src/leonardo/gui/chart/pane_workspace.py",
    }
    for path in paths.values():
        ast.parse(path.read_text(encoding="utf-8"))

    window = paths["window"].read_text(encoding="utf-8")
    presenter = paths["presenter"].read_text(encoding="utf-8")
    composition = paths["composition"].read_text(encoding="utf-8")
    application = paths["application"].read_text(encoding="utf-8")
    volume = paths["volume"].read_text(encoding="utf-8")
    workspace = paths["workspace"].read_text(encoding="utf-8")

    assert "research_suite.window" in window
    assert "research_suite.combo.accepted_dataset" in window
    assert "ChartPaneWorkspaceWidget" in window
    assert "research_suite.button.toggle_autoscale" in window
    assert "research_suite.button.toggle_volume" in window
    assert "build_resident_volume_projection" in presenter
    assert "record_action(" not in window
    assert "ResearchSuitePresenter" in composition
    assert "research_dataset_service" in composition
    assert "submit_catalog" in application
    assert "submit_resident_slice" in application
    assert "ChartSessionState" in presenter
    assert "HorizontalViewport" in presenter
    assert "ResidentRefillDirection" in presenter

    assert "QSplitter" in workspace
    assert "DEFAULT_VOLUME_MEAN_PERIOD" in volume

    combined = "\n".join((window, presenter, composition, application, volume, workspace))
    for forbidden in (
        "DatasetId",
        "CoreBridge",
        "QApplication.processEvents",
        "leonardo.contracts",
        "dummy_data",
    ):
        assert forbidden not in combined
