"""Domain service for Study Setup catalogs and Study Environment persistence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone

from leonardo.artifacts import ArtifactError, ArtifactService
from leonardo.financial_tools import (
    resolve_output_signals,
    resolve_parameters,
)
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.studies import (
    ChartStudy,
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudyOperationCancelled,
    StudyUserMetadata,
)
from leonardo.research.study_environment import (
    StudyEnvironmentCompatibilityReport,
    StudyEnvironmentDraft,
    StudyEnvironmentEntryV1,
    StudyEnvironmentPresentationV1,
    StudyEnvironmentSourceV1,
    StudyEnvironmentSummary,
    StudyEnvironmentV1,
    StudyEnvironmentValidationError,
)
from leonardo.research.study_environment_store import StudyEnvironmentStore
from leonardo.research.study_presentation import StudyPresentation
from leonardo.research.study_setup import (
    RESEARCH_FINANCIAL_TOOL_SPECS,
    StudyArtifactOption,
    StudySetupCatalog,
    StudySetupCatalogRejection,
    StudySourceOption,
)


CancellationCheck = Callable[[], bool]


class ResearchStudySetupService:
    """Own immutable setup projections and Study Environment domain operations."""

    def __init__(
        self,
        artifacts: ArtifactService,
        environments: StudyEnvironmentStore,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(artifacts, ArtifactService):
            raise TypeError("artifacts must be an ArtifactService")
        if not isinstance(environments, StudyEnvironmentStore):
            raise TypeError("environments must be a StudyEnvironmentStore")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")
        if id_factory is not None and not callable(id_factory):
            raise TypeError("id_factory must be callable or None")
        self._artifacts = artifacts
        self._environments = environments
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory

    def build_catalog(
        self,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        *,
        cancellation_requested: CancellationCheck | None = None,
    ) -> StudySetupCatalog:
        if not isinstance(dataset, HistoricalDataset):
            raise TypeError("dataset must be a HistoricalDataset")
        snapshot = tuple(studies)
        if not all(isinstance(item, ChartStudy) for item in snapshot):
            raise TypeError("studies must contain ChartStudy values")
        cancel = cancellation_requested or _never_cancelled
        _raise_if_cancelled(cancel, "Study catalog projection")
        ohlcv = tuple(
            StudySourceOption("ohlcv", column.upper(), "ohlc", column_name=column)
            for column in ("open", "high", "low", "close", "volume")
        )
        study_sources = tuple(
            StudySourceOption(
                "study",
                f"{study.display_name}: {output}",
                study.result.kind,
                study_id=study.study_id,
                output_name=output,
            )
            for study in snapshot
            for output in study.analysis_usable_output_names
        )
        options: list[StudyArtifactOption] = []
        rejections: list[StudySetupCatalogRejection] = []
        for summary in self._artifacts.list_artifacts(dataset.market_id):
            _raise_if_cancelled(cancel, "artifact catalog traversal")
            if summary.tool_key == "dynamic_binning":
                rejections.append(
                    StudySetupCatalogRejection(
                        artifact_id=summary.artifact_id,
                        kind=summary.kind,
                        tool_key=summary.tool_key,
                        reason=(
                            "Dynamic Binning is reserved for Analysis and "
                            "unavailable in Research."
                        ),
                    )
                )
                continue
            try:
                if not summary.valid:
                    raise StudyEnvironmentValidationError(
                        summary.rejection_reason or "artifact is invalid"
                    )
                current = self._artifacts.validate_artifact_current(
                    dataset.market_id,
                    summary.kind,
                    summary.tool_key,
                    summary.artifact_id,
                )
                loaded = self._artifacts.load_artifact(
                    dataset.market_id,
                    current.kind,
                    current.tool_key,
                    current.artifact_id,
                )
                options.append(
                    StudyArtifactOption(
                        market_id=dataset.market_id,
                        artifact_id=current.artifact_id,
                        kind=current.kind,
                        tool_key=current.tool_key,
                        display_name=loaded.metadata.recipe.display_name,
                        output_names=current.output_names,
                        analysis_usable_output_names=tuple(
                            signal.name
                            for signal in resolve_output_signals(
                                current.tool_key,
                                {
                                    **dict(loaded.metadata.recipe.parameters),
                                    **dict(loaded.metadata.recipe.bindings),
                                },
                            )
                            if signal.analysis_usable
                        ),
                        parameters=loaded.metadata.recipe.parameters,
                        source_bindings=_artifact_source_bindings(
                            loaded.metadata.recipe.tool_key,
                            loaded.metadata.recipe.parameters,
                            loaded.metadata.recipe.bindings,
                            loaded.metadata.recipe.source_artifacts,
                        ),
                    )
                )
            except (ArtifactError, OSError, TypeError, ValueError) as exc:
                rejections.append(
                    StudySetupCatalogRejection(
                        artifact_id=summary.artifact_id,
                        kind=summary.kind,
                        tool_key=summary.tool_key,
                        reason=str(exc),
                    )
                )
        return StudySetupCatalog(
            market_id=dataset.market_id,
            tools=RESEARCH_FINANCIAL_TOOL_SPECS,
            ohlcv_sources=ohlcv,
            study_sources=study_sources,
            artifact_options=tuple(options),
            artifact_rejections=tuple(rejections),
        )

    def build_environment(
        self,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        presentations: Sequence[StudyPresentation],
        *,
        display_name: str,
        description: str = "",
        environment_id: str | None = None,
        metadata_overrides: Mapping[str, StudyUserMetadata] | None = None,
    ) -> StudyEnvironmentDraft:
        if not isinstance(dataset, HistoricalDataset):
            raise TypeError("dataset must be a HistoricalDataset")
        study_snapshot = tuple(studies)
        presentation_snapshot = tuple(presentations)
        if not study_snapshot:
            raise StudyEnvironmentValidationError("an empty chart cannot be saved")
        if not all(isinstance(item, ChartStudy) for item in study_snapshot):
            raise TypeError("studies must contain ChartStudy values")
        if not all(isinstance(item, StudyPresentation) for item in presentation_snapshot):
            raise TypeError("presentations must contain StudyPresentation values")
        presentation_by_id = {item.study_id: item for item in presentation_snapshot}
        if set(presentation_by_id) != {item.study_id for item in study_snapshot}:
            raise StudyEnvironmentValidationError("Study presentations do not match Studies")
        overrides = dict(metadata_overrides or {})
        if not all(isinstance(value, StudyUserMetadata) for value in overrides.values()):
            raise StudyEnvironmentValidationError("metadata overrides are invalid")
        ordered_studies = _stable_study_order(study_snapshot)
        entry_ids = {
            study.study_id: f"entry_{index:03d}"
            for index, study in enumerate(ordered_studies, start=1)
        }
        prior: set[str] = set()
        entries: list[StudyEnvironmentEntryV1] = []
        for study in ordered_studies:
            if study.result.tool_key == "dynamic_binning":
                raise StudyEnvironmentValidationError(
                    "Dynamic Binning is reserved for Analysis and cannot be "
                    "saved in a Research Study Environment."
                )
            request = study.setup_request
            presentation = presentation_by_id[study.study_id]
            metadata = overrides.get(study.study_id, study.user_metadata)
            if isinstance(request, StudyExecutionRequest):
                sources = tuple(
                    _environment_source(source, entry_ids, prior)
                    for source in request.input_sources
                )
                parameters = _canonical_user_parameters(
                    request.tool_key, request.parameters
                )
                mode = "calculation"
                artifact_id = None
            elif isinstance(request, StudyArtifactRequest):
                sources = ()
                parameters = {}
                mode = "artifact"
                artifact_id = request.artifact_id
            else:
                raise StudyEnvironmentValidationError("Study setup_request is invalid")
            entries.append(
                StudyEnvironmentEntryV1(
                    entry_id=entry_ids[study.study_id],
                    mode=mode,
                    kind=study.result.kind,
                    tool_key=study.result.tool_key,
                    display_name=study.display_name,
                    parameters=parameters,
                    sources=sources,
                    artifact_id=artifact_id,
                    expected_output_names=study.result.output_names,
                    user_metadata=metadata,
                    presentation=StudyEnvironmentPresentationV1(
                        visible=presentation.visible,
                        line_styles=tuple(presentation.signal_styles.values()),
                        fill_styles=tuple(presentation.fill_styles.values()),
                        guide_styles=tuple(presentation.guide_styles.values()),
                    ),
                )
            )
            prior.add(study.study_id)
        return StudyEnvironmentDraft(
            environment_id=environment_id,
            display_name=display_name,
            description=description,
            created_from=dataset.market_id,
            entries=tuple(entries),
        )

    def list_environments(self) -> tuple[StudyEnvironmentSummary, ...]:
        return self._environments.list_summaries()

    def load_environment(self, environment_id: str) -> StudyEnvironmentV1:
        return self._environments.load(environment_id)

    def create_environment(self, draft: StudyEnvironmentDraft) -> StudyEnvironmentV1:
        return self._environments.create(draft)

    def update_environment(
        self, environment_id: str, draft: StudyEnvironmentDraft
    ) -> StudyEnvironmentV1:
        return self._environments.update(environment_id, draft)

    def delete_environment(self, environment_id: str) -> StudyEnvironmentSummary:
        return self._environments.delete(environment_id)

    def compatibility(
        self,
        environment: StudyEnvironmentV1,
        dataset: HistoricalDataset,
        *,
        cancellation_requested: CancellationCheck | None = None,
    ) -> StudyEnvironmentCompatibilityReport:
        if not isinstance(environment, StudyEnvironmentV1):
            raise TypeError("environment must be StudyEnvironmentV1")
        if not isinstance(dataset, HistoricalDataset):
            raise TypeError("dataset must be a HistoricalDataset")
        cancel = cancellation_requested or _never_cancelled
        blockers: list[str] = []
        for entry in environment.entries:
            _raise_if_cancelled(cancel, "environment compatibility traversal")
            if entry.tool_key == "dynamic_binning":
                blockers.append(
                    f"{entry.entry_id}: Dynamic Binning is reserved for Analysis "
                    "and unavailable in Research"
                )
                continue
            artifact_refs = []
            if entry.mode == "artifact":
                artifact_refs.append(
                    (
                        entry.entry_id,
                        entry.kind,
                        entry.tool_key,
                        entry.artifact_id,
                        None,
                    )
                )
            artifact_refs.extend(
                (
                    entry.entry_id,
                    source.artifact_kind,
                    source.artifact_tool_key,
                    source.artifact_id,
                    source.output_name,
                )
                for source in entry.sources
                if source.source_kind == "artifact"
            )
            for entry_id, kind, tool_key, artifact_id, source_output in artifact_refs:
                if environment.created_from is None or dataset.market_id != environment.created_from:
                    blockers.append(
                        f"{entry_id}: artifact references require exact created_from MarketId"
                    )
                    continue
                try:
                    current = self._artifacts.validate_artifact_current(
                        dataset.market_id, kind or "", tool_key or "", artifact_id or ""
                    )
                    loaded = self._artifacts.load_artifact(
                        dataset.market_id, current.kind, current.tool_key, current.artifact_id
                    )
                    if source_output is None and tuple(current.output_names) != entry.expected_output_names:
                        blockers.append(f"{entry_id}: artifact outputs changed")
                    if source_output is not None:
                        signals = resolve_output_signals(
                            current.tool_key,
                            {
                                **dict(loaded.metadata.recipe.parameters),
                                **dict(loaded.metadata.recipe.bindings),
                            },
                        )
                        usable = tuple(
                            signal.name for signal in signals if signal.analysis_usable
                        )
                        if source_output not in usable:
                            blockers.append(
                                f"{entry_id}: artifact source output is not analysis-usable"
                            )
                except (ArtifactError, OSError, TypeError, ValueError) as exc:
                    blockers.append(f"{entry_id}: {exc}")
        return StudyEnvironmentCompatibilityReport(
            environment.environment_id,
            blockers=tuple(blockers),
            warnings=(),
        )


def _environment_source(source, entry_ids: Mapping[str, str], prior: set[str]):
    if source.source_kind == "ohlcv":
        return StudyEnvironmentSourceV1(
            role=source.role,
            source_kind="ohlcv",
            column_name=source.column_name,
        )
    if source.source_kind == "study":
        if source.study_id not in prior:
            raise StudyEnvironmentValidationError(
                "Study dependencies must be included and earlier in the chart order"
            )
        return StudyEnvironmentSourceV1(
            role=source.role,
            source_kind="environment",
            source_entry_id=entry_ids[source.study_id],
            output_name=source.output_name,
        )
    return StudyEnvironmentSourceV1(
        role=source.role,
        source_kind="artifact",
        artifact_kind=source.artifact_kind,
        artifact_tool_key=source.artifact_tool_key,
        artifact_id=source.artifact_id,
        output_name=source.output_name,
    )


def _stable_study_order(
    studies: tuple[ChartStudy, ...],
) -> tuple[ChartStudy, ...]:
    by_id = {study.study_id: study for study in studies}
    if len(by_id) != len(studies):
        raise StudyEnvironmentValidationError("Study identities must be unique")
    dependencies: dict[str, set[str]] = {}
    for study in studies:
        request = study.setup_request
        required: set[str] = set()
        if isinstance(request, StudyExecutionRequest):
            for source in request.input_sources:
                if source.source_kind != "study":
                    continue
                dependency_id = source.study_id or ""
                dependency = by_id.get(dependency_id)
                if dependency is None:
                    raise StudyEnvironmentValidationError(
                        f"Study dependency is missing: {dependency_id or '<empty>'}"
                    )
                if source.output_name not in dependency.analysis_usable_output_names:
                    raise StudyEnvironmentValidationError(
                        "Study dependency output is missing: "
                        f"{dependency_id}/{source.output_name or '<empty>'}"
                    )
                required.add(dependency_id)
        dependencies[study.study_id] = required

    ordered: list[ChartStudy] = []
    accepted: set[str] = set()
    remaining = list(studies)
    while remaining:
        ready = next(
            (
                study
                for study in remaining
                if dependencies[study.study_id].issubset(accepted)
            ),
            None,
        )
        if ready is None:
            cycle = ", ".join(study.study_id for study in remaining)
            raise StudyEnvironmentValidationError(
                f"Study dependency cycle detected: {cycle}"
            )
        ordered.append(ready)
        accepted.add(ready.study_id)
        remaining.remove(ready)
    return tuple(ordered)


def _canonical_user_parameters(
    tool_key: str, parameters: Mapping[str, object]
) -> dict[str, object]:
    selectors = _owned_selector_names(tool_key)
    return {
        name: value
        for name, value in resolve_parameters(tool_key, parameters).items()
        if name not in selectors
    }


def _artifact_source_bindings(
    tool_key: str,
    parameters: Mapping[str, object],
    bindings: Mapping[str, object],
    source_artifacts: Sequence[object],
) -> tuple[tuple[str, str], ...]:
    artifact_outputs = {
        ref.role: ref.output_name
        for ref in source_artifacts
    }

    def value(role: str, fallback: object) -> str:
        selected = artifact_outputs.get(role, fallback)
        if not isinstance(selected, str) or not selected:
            raise ValueError(f"Artifact source binding is missing: {role}")
        return selected

    if tool_key in {"derivative", "angle"}:
        return (("source", value("source", bindings.get("source"))),)
    if tool_key == "delta":
        return tuple(
            (role, value(role, parameters.get(role)))
            for role in ("fast", "slow")
        )
    if tool_key in {"braids", "braid_instability"}:
        return tuple(
            (role, value(role, parameters.get(role)))
            for role in ("fast", "mid", "slow")
        )
    if tool_key == "trap_area":
        projected = [
            ("fast", value("fast", parameters.get("fast"))),
        ]
        mid = artifact_outputs.get("mid", parameters.get("mid"))
        if mid not in (None, ""):
            projected.append(("mid", value("mid", mid)))
        projected.append(("slow", value("slow", parameters.get("slow"))))
        return tuple(projected)
    if tool_key in {"dynamic_binning", "percent_span_angle", "angle_momentum"}:
        columns = parameters.get("source_columns")
        if not isinstance(columns, str) or not columns:
            raise ValueError("Artifact source_columns binding is missing")
        projected = []
        for index, column in enumerate(columns.split(","), start=1):
            role = f"source_{index}"
            projected.append((role, value(role, column)))
        return tuple(projected)
    if tool_key == "universal_trend_classifier":
        return tuple(
            (role, value(role, None))
            for role in (
                "trend_peak",
                "trend_trough",
                "range_peak",
                "range_trough",
            )
        )
    return ()


def _owned_selector_names(tool_key: str) -> frozenset[str]:
    if tool_key in {"derivative", "angle"}:
        return frozenset({"source"})
    if tool_key == "delta":
        return frozenset({"fast", "slow"})
    if tool_key in {"braids", "braid_instability", "trap_area"}:
        return frozenset({"fast", "mid", "slow"})
    if tool_key in {"dynamic_binning", "percent_span_angle", "angle_momentum"}:
        return frozenset({"source_columns"})
    if tool_key == "universal_trend_classifier":
        return frozenset({"peak_column", "trough_column"})
    return frozenset()


def _raise_if_cancelled(check: CancellationCheck, stage: str) -> None:
    if check():
        raise StudyOperationCancelled(f"Study setup operation cancelled before {stage}")


def _never_cancelled() -> bool:
    return False
