"""Pure construction, persistence, preflight, and append planning for snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from uuid import uuid4

from leonardo.research.catalog import AcceptedDatasetCatalog, AcceptedDatasetSummary
from leonardo.research.dataset import HistoricalDatasetLoader
from leonardo.research.study_environment import EnvironmentV1
from leonardo.research.study_setup_service import ResearchStudySetupService
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotCompatibilityReport,
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
    ResearchWorkspaceSnapshotValidationError,
    WorkspaceSnapshotCapture,
    WorkspaceSnapshotChartCompatibility,
    WorkspaceSnapshotChartV1,
    WorkspaceSnapshotPaneSizeV1,
    WorkspaceSnapshotStateV1,
)
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore


CancellationCheck = Callable[[], bool]


class ResearchWorkspaceSnapshotService:
    """Own snapshot descriptions without owning live Research runtime state."""

    def __init__(
        self,
        catalog: AcceptedDatasetCatalog,
        loader: HistoricalDatasetLoader,
        study_setup: ResearchStudySetupService,
        store: ResearchWorkspaceSnapshotStore,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(catalog, AcceptedDatasetCatalog):
            raise TypeError("catalog must be AcceptedDatasetCatalog")
        if not isinstance(loader, HistoricalDatasetLoader):
            raise TypeError("loader must be HistoricalDatasetLoader")
        if not isinstance(study_setup, ResearchStudySetupService):
            raise TypeError("study_setup must be ResearchStudySetupService")
        if not isinstance(store, ResearchWorkspaceSnapshotStore):
            raise TypeError("store must be ResearchWorkspaceSnapshotStore")
        self._catalog = catalog
        self._loader = loader
        self._study_setup = study_setup
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def build_draft(
        self,
        capture: WorkspaceSnapshotCapture,
        *,
        display_name: str,
        description: str = "",
        snapshot_id: str | None = None,
    ) -> ResearchWorkspaceSnapshotDraft:
        if not isinstance(capture, WorkspaceSnapshotCapture):
            raise TypeError("capture must be WorkspaceSnapshotCapture")
        now = self._now()
        charts: list[WorkspaceSnapshotChartV1] = []
        for item in sorted(capture.charts, key=lambda value: value.workspace_position):
            if item.dataset.market_id != item.market_id:
                raise ResearchWorkspaceSnapshotValidationError(
                    f"{item.chart_ref}: dataset MarketId does not match chart"
                )
            environment: EnvironmentV1 | None = None
            runtime_to_entry: dict[str, str] = {}
            if item.studies:
                environment_draft = self._study_setup.build_environment(
                    item.dataset,
                    item.studies,
                    item.presentations,
                    display_name=f"Workspace {item.chart_ref}",
                    description="Embedded Research Workspace Snapshot Study Environment.",
                    environment_id=f"env_{item.chart_ref}",
                )
                environment = EnvironmentV1.build(
                    environment_id=environment_draft.environment_id or f"env_{item.chart_ref}",
                    display_name=environment_draft.display_name,
                    description=environment_draft.description,
                    created_at_utc=now,
                    updated_at_utc=now,
                    created_from=environment_draft.created_from,
                    entries=environment_draft.entries,
                )
                runtime_to_entry = {
                    study.study_id: entry.entry_id
                    for study, entry in zip(item.studies, environment.entries, strict=True)
                }
            panes: list[WorkspaceSnapshotPaneSizeV1] = []
            for runtime_ref, size in item.pane_sizes.items():
                if runtime_ref in {"price", "volume"}:
                    pane_ref = runtime_ref
                elif runtime_ref.startswith("oscillator:"):
                    study_id = runtime_ref.removeprefix("oscillator:")
                    try:
                        pane_ref = f"study:{runtime_to_entry[study_id]}"
                    except KeyError as exc:
                        raise ResearchWorkspaceSnapshotValidationError(
                            f"{item.chart_ref}: oscillator pane has no embedded Study entry"
                        ) from exc
                else:
                    raise ResearchWorkspaceSnapshotValidationError(
                        f"{item.chart_ref}: unknown runtime pane {runtime_ref}"
                    )
                panes.append(WorkspaceSnapshotPaneSizeV1(pane_ref, size))
            charts.append(
                WorkspaceSnapshotChartV1(
                    chart_ref=item.chart_ref,
                    workspace_position=item.workspace_position,
                    detached=item.detached,
                    market_id=item.market_id,
                    viewport=item.viewport,
                    price_scale=item.price_scale,
                    volume_visible=item.volume_visible,
                    pane_sizes=tuple(panes),
                    study_environment=environment,
                )
            )
        return ResearchWorkspaceSnapshotDraft(
            snapshot_id=snapshot_id,
            display_name=display_name,
            description=description,
            workspace=WorkspaceSnapshotStateV1(
                capture.visualization_mode,
                capture.pan_anchor_enabled,
                capture.active_chart_ref,
            ),
            charts=tuple(charts),
        )

    def list_snapshots(self) -> tuple[ResearchWorkspaceSnapshotSummary, ...]:
        return self._store.list_summaries()

    def load_snapshot(self, snapshot_id: str) -> ResearchWorkspaceSnapshotV1:
        return self._store.load(snapshot_id)

    def create_snapshot(self, draft: ResearchWorkspaceSnapshotDraft) -> ResearchWorkspaceSnapshotV1:
        return self._store.create(draft)

    def update_snapshot(
        self, snapshot_id: str, draft: ResearchWorkspaceSnapshotDraft
    ) -> ResearchWorkspaceSnapshotV1:
        return self._store.update(snapshot_id, draft)

    def delete_snapshot(self, snapshot_id: str) -> ResearchWorkspaceSnapshotSummary:
        return self._store.delete(snapshot_id)

    def preflight(
        self,
        snapshot: ResearchWorkspaceSnapshotV1,
        mode: str,
        current_workspace: object,
        *,
        cancellation_requested: CancellationCheck | None = None,
    ) -> ResearchWorkspaceSnapshotCompatibilityReport:
        if not isinstance(snapshot, ResearchWorkspaceSnapshotV1):
            raise TypeError("snapshot must be ResearchWorkspaceSnapshotV1")
        if mode not in {"append", "replace"}:
            raise ResearchWorkspaceSnapshotValidationError("mode must be append or replace")
        cancel = cancellation_requested or (lambda: False)
        blockers: list[str] = []
        warnings: list[str] = []
        occupied = _current_positions(current_workspace)
        current_count = len(occupied)
        if not _workspace_idle(current_workspace):
            blockers.append("target workspace is not idle")
        if mode == "append" and current_count + len(snapshot.charts) > 8:
            blockers.append("append exceeds the eight-chart workspace capacity")
        append_positions: tuple[tuple[str, int], ...] = ()
        if mode == "append" and current_count + len(snapshot.charts) <= 8:
            append_positions = self.plan_append_positions(snapshot, occupied)
        chart_reports: list[WorkspaceSnapshotChartCompatibility] = []
        for chart in snapshot.charts:
            _raise_if_cancelled(cancel)
            chart_blockers: list[str] = []
            chart_warnings: list[str] = []
            accepted = self._catalog.inspect_market(chart.market_id)
            if not isinstance(accepted, AcceptedDatasetSummary):
                chart_blockers.append(f"dataset is not accepted: {accepted.reason}")
                dataset = None
            else:
                try:
                    dataset = self._loader.load(
                        chart.market_id,
                        cancellation_requested=cancel,
                    )
                except (OSError, TypeError, ValueError) as exc:
                    chart_blockers.append(f"dataset load failed: {exc}")
                    dataset = None
            _raise_if_cancelled(cancel)
            environment = chart.study_environment
            if environment is not None and dataset is not None:
                report = self._study_setup.compatibility(
                    environment,
                    dataset,
                    cancellation_requested=cancel,
                )
                chart_blockers.extend(report.blockers)
                chart_warnings.extend(report.warnings)
            chart_reports.append(
                WorkspaceSnapshotChartCompatibility(
                    chart.chart_ref,
                    chart.workspace_position,
                    not chart_blockers,
                    tuple(chart_blockers),
                    tuple(chart_warnings),
                )
            )
            blockers.extend(f"{chart.chart_ref}: {item}" for item in chart_blockers)
            warnings.extend(f"{chart.chart_ref}: {item}" for item in chart_warnings)
        return ResearchWorkspaceSnapshotCompatibilityReport(
            snapshot.snapshot_id,
            mode,
            not blockers,
            tuple(chart_reports),
            tuple(blockers),
            tuple(warnings),
            append_positions,
        )

    def plan_append_positions(
        self,
        snapshot: ResearchWorkspaceSnapshotV1,
        occupied_positions: Iterable[int],
    ) -> tuple[tuple[str, int], ...]:
        if not isinstance(snapshot, ResearchWorkspaceSnapshotV1):
            raise TypeError("snapshot must be ResearchWorkspaceSnapshotV1")
        occupied = set(occupied_positions)
        if any(type(item) is not int or not 1 <= item <= 8 for item in occupied):
            raise ResearchWorkspaceSnapshotValidationError("occupied positions must be 1..8")
        if len(occupied) + len(snapshot.charts) > 8:
            raise ResearchWorkspaceSnapshotValidationError("append exceeds workspace capacity")
        planned: list[tuple[str, int]] = []
        for chart in snapshot.charts:
            position = chart.workspace_position
            if position in occupied:
                position = next(item for item in range(1, 9) if item not in occupied)
            occupied.add(position)
            planned.append((chart.chart_ref, position))
        return tuple(planned)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ResearchWorkspaceSnapshotValidationError("clock must return timezone-aware UTC")
        if value.utcoffset().total_seconds() != 0:
            raise ResearchWorkspaceSnapshotValidationError("clock must return UTC")
        return value


def _current_positions(current_workspace: object) -> tuple[int, ...]:
    if current_workspace is None:
        return ()
    if isinstance(current_workspace, Mapping):
        values = current_workspace.get("occupied_positions", ())
    else:
        values = getattr(current_workspace, "occupied_positions", None)
        if values is None:
            charts = getattr(current_workspace, "charts", ())
            values = tuple(getattr(item, "workspace_position") for item in charts)
    return tuple(values)


def _workspace_idle(current_workspace: object) -> bool:
    if current_workspace is None:
        return True
    if isinstance(current_workspace, Mapping):
        return bool(current_workspace.get("idle", True))
    return bool(getattr(current_workspace, "idle", True))


def _raise_if_cancelled(cancel: CancellationCheck) -> None:
    if cancel():
        from leonardo.research.studies import StudyOperationCancelled

        raise StudyOperationCancelled("workspace snapshot preflight cancelled")
