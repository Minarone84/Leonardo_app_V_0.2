from __future__ import annotations

from pathlib import Path

import leonardo.research as research


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = {
    "study_application.py",
    "study_execution.py",
    "study_projection.py",
    "studies.py",
}
TESTS = {
    "test_study_application.py",
    "test_study_architecture.py",
    "test_study_artifact_apply_save.py",
    "test_study_dependencies.py",
    "test_study_execution.py",
    "test_study_models.py",
    "test_study_projection.py",
    "test_study_session_registry.py",
}


def test_task_1017_exact_added_inventory_exists() -> None:
    source = ROOT / "src" / "leonardo" / "research"
    tests = ROOT / "tests" / "research_test"
    assert PRODUCTION <= {path.name for path in source.glob("*.py")}
    assert TESTS <= {path.name for path in tests.glob("test_study*.py")}
    assert {
        path.name for path in (tests / "fixtures").glob("task_1017_*")
    } == {
        "task_1017_study_execution_expected.json",
        "task_1017_study_execution_input.csv",
    }


def test_production_has_no_gui_formula_or_direct_filesystem_boundary() -> None:
    source = ROOT / "src" / "leonardo" / "research"
    text = "\n".join((source / name).read_text(encoding="utf-8") for name in PRODUCTION)
    for forbidden in (
        "PySide6",
        "leonardo.gui",
        "QWidget",
        "QDialog",
        "pathlib",
        "open(",
        "read_csv",
        "to_csv",
        "ArtifactRecipeExecutor",
        "AnalysisSuite",
        "Backtest",
        "WorkspaceSnapshot",
        "StudyEnvironment",
        "ArtifactCollection",
        "RecipeCollection",
    ):
        assert forbidden not in text
    assert "._calculation" not in text
    assert "ArtifactService" in text
    assert "calculate_financial_tool" in text


def test_existing_research_exports_are_preserved_and_frozen_exports_exist() -> None:
    existing = {
        "ChartSessionState",
        "HistoricalDataset",
        "ResearchDatasetApplicationService",
        "ResidentOHLCVSlice",
    }
    added = {
        "ChartStudy",
        "ChartStudyRegistry",
        "PreparedStudy",
        "ResearchStudyApplicationService",
        "ResearchStudyService",
        "ResidentStudyProjection",
        "StudyApplyAttempt",
        "StudyArtifactRequest",
        "StudyDependencyError",
        "StudyDependencyRef",
        "StudyError",
        "StudyExecutionRequest",
        "StudyInputSource",
        "StudyNotFoundError",
        "StudyOperationCancelled",
        "StudySaveAttempt",
        "StudySaveBlockedError",
        "StudySaveOutcome",
        "StudySavedLink",
        "StudyValidationError",
    }
    assert existing | added <= set(research.__all__)
