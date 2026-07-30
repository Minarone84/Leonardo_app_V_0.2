"""Construct the restored Research Suite from existing application services."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from leonardo.gui.research.lifecycle_presenter import (
    RestoredResearchLifecyclePresenter,
)
from leonardo.gui.research.suite_window import ResearchSuiteWindow
from leonardo.research import (
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResearchStudySetupApplicationService,
)
from leonardo.research.notebook_application import (
    ResearchNotebookApplicationService,
)
from leonardo.research.workspace_snapshot_application import (
    ResearchWorkspaceSnapshotApplicationService,
)

WindowTracker = Callable[[QWidget, str, str, str], None]


def create_restored_research_suite(
    dataset_service: ResearchDatasetApplicationService,
    study_service: ResearchStudyApplicationService,
    study_setup_service: ResearchStudySetupApplicationService,
    snapshot_service: ResearchWorkspaceSnapshotApplicationService,
    notebook_service: ResearchNotebookApplicationService,
    window_tracker: WindowTracker,
    *,
    parent: QWidget | None = None,
) -> tuple[ResearchSuiteWindow, RestoredResearchLifecyclePresenter]:
    """Construct one restored Research Suite and its real-service presenter."""
    if not callable(window_tracker):
        raise TypeError("window_tracker must be callable")
    if not isinstance(
        dataset_service,
        ResearchDatasetApplicationService,
    ):
        raise TypeError(
            "dataset_service must be ResearchDatasetApplicationService"
        )
    if not isinstance(
        study_service,
        ResearchStudyApplicationService,
    ):
        raise TypeError(
            "study_service must be ResearchStudyApplicationService"
        )
    if not isinstance(
        study_setup_service,
        ResearchStudySetupApplicationService,
    ):
        raise TypeError(
            "study_setup_service must be "
            "ResearchStudySetupApplicationService"
        )
    if not isinstance(
        snapshot_service,
        ResearchWorkspaceSnapshotApplicationService,
    ):
        raise TypeError(
            "snapshot_service must be "
            "ResearchWorkspaceSnapshotApplicationService"
        )
    if not isinstance(
        notebook_service,
        ResearchNotebookApplicationService,
    ):
        raise TypeError(
            "notebook_service must be ResearchNotebookApplicationService"
        )

    window = ResearchSuiteWindow(parent=parent)
    window_tracker(window, "research_suite.window", "Research Suite", "suite")

    presenter = RestoredResearchLifecyclePresenter(
        window,
        dataset_service,
        study_service,
        window_tracker,
        study_setup_service=study_setup_service,
        snapshot_service=snapshot_service,
        notebook_service=notebook_service,
    )
    return window, presenter
