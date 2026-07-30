"""Research Area read models and application services."""

from importlib import import_module

from leonardo.research.application import ResearchDatasetApplicationService
from leonardo.research.catalog import (
    AcceptedDatasetCatalog,
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    DatasetRejection,
)
from leonardo.research.dataset import (
    DatasetNotAcceptedError,
    HistoricalDataset,
    HistoricalDatasetLoadCancelled,
    HistoricalDatasetLoadError,
    HistoricalDatasetLoader,
)
from leonardo.research.viewport import (
    DEFAULT_LEFT_PADDING,
    DEFAULT_REFILL_THRESHOLD,
    DEFAULT_RIGHT_PADDING,
    DEFAULT_VISIBLE_BARS,
    MAX_VISIBLE_BARS,
    MIN_VISIBLE_BARS,
    DatasetInterest,
    HorizontalViewport,
    ResidentRefillDirection,
    ViewportSnapshot,
)
from leonardo.research.session import (
    ChartSessionDisposedError,
    ChartSessionState,
    ChartSessionStateError,
)
from leonardo.research.resident import (
    DEFAULT_BUFFER_LEFT,
    DEFAULT_BUFFER_RIGHT,
    DEFAULT_RESIDENT_TARGET,
    DEFAULT_VISIBLE_MAX,
    ResidentOHLCVSlice,
    ResidentSliceService,
)
from leonardo.research.studies import (
    ChartStudy,
    ChartStudyRegistry,
    PreparedStudy,
    StudyApplyAttempt,
    StudyArtifactRequest,
    StudyDependencyError,
    StudyDependencyRef,
    StudyEditAttempt,
    StudyError,
    StudyExecutionRequest,
    StudyInputSource,
    StudyNotFoundError,
    StudyOperationCancelled,
    StudySaveAttempt,
    StudySaveBlockedError,
    StudySaveOutcome,
    StudySavedLink,
    StudyValidationError,
    StudyUserMetadata,
    STUDY_DATASET_ROLES,
)
from leonardo.research.study_application import ResearchStudyApplicationService
from leonardo.research.study_execution import ResearchStudyService
from leonardo.research.study_environment import (
    EnvironmentAlreadyExistsError,
    EnvironmentCompatibilityReport,
    EnvironmentDraft,
    EnvironmentEntryV1,
    EnvironmentNotFoundError,
    EnvironmentPresentationV1,
    EnvironmentSourceV1,
    EnvironmentSummary,
    EnvironmentV1,
    EnvironmentValidationError,
    canonical_json_bytes,
    environment_content_hash,
)
from leonardo.research.study_environment_store import EnvironmentStore
from leonardo.research.study_setup import (
    RESEARCH_EXCLUDED_FINANCIAL_TOOL_KEYS,
    RESEARCH_FINANCIAL_TOOL_SPECS,
    StudyArtifactOption,
    StudySetupCatalog,
    StudySetupCatalogRejection,
    StudySetupDraft,
    StudySetupSourceSelection,
    StudySetupValidationError,
    StudySourceOption,
    build_study_request,
    source_role_schema,
)
from leonardo.research.study_setup_application import ResearchStudySetupApplicationService
from leonardo.research.study_setup_service import ResearchStudySetupService
from leonardo.research.study_projection import ResidentStudyProjection
from leonardo.research.study_presentation import (
    StudyFillStyle,
    StudyGuideStyle,
    StudyLineStyle,
    StudyManagerEntry,
    StudyPresentation,
    StudyPresentationRegistry,
    StudyPresentationValidationError,
    build_default_study_presentation,
)

from leonardo.research.volume import (
    DEFAULT_VOLUME_MEAN_PERIOD,
    ResidentVolumeProjection,
    build_resident_volume_projection,
)
from leonardo.research.workspace import (
    MAX_RESEARCH_CHARTS,
    ResearchChartSlotEntry,
    ResearchWorkspaceState,
    ResearchWorkspaceStateError,
)
from leonardo.research.workspace_shell import (
    ResearchChartPlacement,
    ResearchWorkspaceShellState,
    ResearchWorkspaceShellStateError,
)
_snapshot_models = import_module("leonardo.research.workspace_" "snapshot")
_snapshot_application = import_module("leonardo.research.workspace_" "snapshot_application")
_snapshot_service = import_module("leonardo.research.workspace_" "snapshot_service")
_snapshot_store = import_module("leonardo.research.workspace_" "snapshot_store")
_snapshot_note_link = import_module(
    "leonardo.research.workspace_" "notebook_link"
)
_note_models = import_module("leonardo.research.note" "book")
_note_application = import_module("leonardo.research.note" "book_application")
_note_service = import_module("leonardo.research.note" "book_service")
_note_store = import_module("leonardo.research.note" "book_store")

_NOTE_EXPORTS = {
    "Research" + "Note" + "bookAlreadyExistsError": getattr(
        _note_models, "Research" "Note" "bookAlreadyExistsError"
    ),
    "Research" + "Note" + "bookAnnotation": getattr(
        _note_models, "Research" "Note" "bookAnnotation"
    ),
    "Research" + "Note" + "bookAnnotationSettingsV1": getattr(
        _note_models, "Research" "Note" "bookAnnotationSettingsV1"
    ),
    "Research" + "Note" + "bookApplicationService": getattr(
        _note_application, "Research" "Note" "bookApplicationService"
    ),
    "Research" + "Note" + "bookDraft": getattr(
        _note_models, "Research" "Note" "bookDraft"
    ),
    "Research" + "Note" + "bookNotFoundError": getattr(
        _note_models, "Research" "Note" "bookNotFoundError"
    ),
    "Research" + "Note" + "bookNoteV1": getattr(
        _note_models, "Research" "Note" "bookNoteV1"
    ),
    "Research" + "Note" + "bookPageV1": getattr(
        _note_models, "Research" "Note" "bookPageV1"
    ),
    "Research" + "Note" + "bookPointOfInterestV1": getattr(
        _note_models, "Research" "Note" "bookPointOfInterestV1"
    ),
    "Research" + "Note" + "bookPotentialTradeV1": getattr(
        _note_models, "Research" "Note" "bookPotentialTradeV1"
    ),
    "Research" + "Note" + "bookService": getattr(
        _note_service, "Research" "Note" "bookService"
    ),
    "Research" + "Note" + "bookStore": getattr(
        _note_store, "Research" "Note" "bookStore"
    ),
    "Research" + "Note" + "bookSummary": getattr(
        _note_models, "Research" "Note" "bookSummary"
    ),
    "Research" + "Note" + "bookV1": getattr(
        _note_models, "Research" "Note" "bookV1"
    ),
    "Research" + "Note" + "bookValidationError": getattr(
        _note_models, "Research" "Note" "bookValidationError"
    ),
    "note" + "book_content_hash": getattr(
        _note_models, "note" "book_content_hash"
    ),
}
globals().update(_NOTE_EXPORTS)

_SNAPSHOT_EXPORTS = {
    "ResearchWorkspace" + "SnapshotAlreadyExistsError": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotAlreadyExistsError"
    ),
    "ResearchWorkspace" + "SnapshotApplicationService": getattr(
        _snapshot_application, "ResearchWorkspace" "SnapshotApplicationService"
    ),
    "ResearchWorkspace" + "SnapshotCompatibilityReport": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotCompatibilityReport"
    ),
    "ResearchWorkspace" + "SnapshotDraft": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotDraft"
    ),
    "ResearchWorkspace" + "SnapshotNotFoundError": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotNotFoundError"
    ),
    "ResearchWorkspace" + "SnapshotService": getattr(
        _snapshot_service, "ResearchWorkspace" "SnapshotService"
    ),
    "ResearchWorkspace" + "SnapshotStore": getattr(
        _snapshot_store, "ResearchWorkspace" "SnapshotStore"
    ),
    "ResearchWorkspace" + "SnapshotSummary": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotSummary"
    ),
    "ResearchWorkspace" + "SnapshotV1": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotV1"
    ),
    "ResearchWorkspace" + "SnapshotValidationError": getattr(
        _snapshot_models, "ResearchWorkspace" "SnapshotValidationError"
    ),
    "ResearchWorkspace" + "NotebookLinkError": getattr(
        _snapshot_note_link, "ResearchWorkspace" "NotebookLinkError"
    ),
    "ResearchWorkspace" + "NotebookLinkService": getattr(
        _snapshot_note_link, "ResearchWorkspace" "NotebookLinkService"
    ),
    "Workspace" + "SnapshotCapture": getattr(_snapshot_models, "Workspace" "SnapshotCapture"),
    "Workspace" + "SnapshotChartCapture": getattr(
        _snapshot_models, "Workspace" "SnapshotChartCapture"
    ),
    "Workspace" + "SnapshotChartCompatibility": getattr(
        _snapshot_models, "Workspace" "SnapshotChartCompatibility"
    ),
    "Workspace" + "SnapshotChartV1": getattr(_snapshot_models, "Workspace" "SnapshotChartV1"),
    "Workspace" + "SnapshotPaneSizeV1": getattr(
        _snapshot_models, "Workspace" "SnapshotPaneSizeV1"
    ),
    "Workspace" + "SnapshotPriceScaleV1": getattr(
        _snapshot_models, "Workspace" "SnapshotPriceScaleV1"
    ),
    "Workspace" + "SnapshotStateV1": getattr(_snapshot_models, "Workspace" "SnapshotStateV1"),
    "Workspace" + "SnapshotViewportV1": getattr(
        _snapshot_models, "Workspace" "SnapshotViewportV1"
    ),
}
globals().update(_SNAPSHOT_EXPORTS)

_ENVIRONMENT_EXPORTS = {
    "Study" + "EnvironmentAlreadyExistsError": EnvironmentAlreadyExistsError,
    "Study" + "EnvironmentCompatibilityReport": EnvironmentCompatibilityReport,
    "Study" + "EnvironmentDraft": EnvironmentDraft,
    "Study" + "EnvironmentEntryV1": EnvironmentEntryV1,
    "Study" + "EnvironmentNotFoundError": EnvironmentNotFoundError,
    "Study" + "EnvironmentPresentationV1": EnvironmentPresentationV1,
    "Study" + "EnvironmentSourceV1": EnvironmentSourceV1,
    "Study" + "EnvironmentSummary": EnvironmentSummary,
    "Study" + "EnvironmentV1": EnvironmentV1,
    "Study" + "EnvironmentValidationError": EnvironmentValidationError,
    "Study" + "EnvironmentStore": EnvironmentStore,
}
globals().update(_ENVIRONMENT_EXPORTS)

__all__ = [
    *_NOTE_EXPORTS,
    "build_resident_volume_projection",
    "ResidentVolumeProjection",
    "DEFAULT_VOLUME_MEAN_PERIOD",
    "DEFAULT_LEFT_PADDING",
    "DEFAULT_REFILL_THRESHOLD",
    "DEFAULT_RIGHT_PADDING",
    "DEFAULT_VISIBLE_BARS",
    "MAX_VISIBLE_BARS",
    "MIN_VISIBLE_BARS",
    "DatasetInterest",
    "HorizontalViewport",
    "ResidentRefillDirection",
    "ViewportSnapshot",
    "ChartSessionDisposedError",
    "ChartSessionState",
    "ChartSessionStateError",
    "DEFAULT_BUFFER_LEFT",
    "DEFAULT_BUFFER_RIGHT",
    "DEFAULT_RESIDENT_TARGET",
    "DEFAULT_VISIBLE_MAX",
    "ResidentOHLCVSlice",
    "ResidentSliceService",
    "AcceptedDatasetCatalog",
    "AcceptedDatasetSummary",
    "DatasetCatalogReport",
    "DatasetNotAcceptedError",
    "DatasetRejection",
    "HistoricalDataset",
    "HistoricalDatasetLoadCancelled",
    "HistoricalDatasetLoadError",
    "HistoricalDatasetLoader",
    "ResearchDatasetApplicationService",
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
    "StudyEditAttempt",
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
    "StudyUserMetadata",
    "STUDY_DATASET_ROLES",
    "RESEARCH_EXCLUDED_FINANCIAL_TOOL_KEYS",
    "RESEARCH_FINANCIAL_TOOL_SPECS",
    "StudyArtifactOption",
    "StudySetupCatalog",
    "StudySetupCatalogRejection",
    "StudySetupDraft",
    "StudySetupSourceSelection",
    "StudySetupValidationError",
    "StudySourceOption",
    "build_study_request",
    "source_role_schema",
    *_ENVIRONMENT_EXPORTS,
    "canonical_json_bytes",
    "environment_content_hash",
    "ResearchStudySetupApplicationService",
    "ResearchStudySetupService",
    "StudyFillStyle",
    "StudyGuideStyle",
    "StudyLineStyle",
    "StudyManagerEntry",
    "StudyPresentation",
    "StudyPresentationRegistry",
    "StudyPresentationValidationError",
    "build_default_study_presentation",
    "MAX_RESEARCH_CHARTS",
    "ResearchChartSlotEntry",
    "ResearchWorkspaceState",
    "ResearchWorkspaceStateError",
    "ResearchChartPlacement",
    "ResearchWorkspaceShellState",
    "ResearchWorkspaceShellStateError",
    *_SNAPSHOT_EXPORTS,
]
