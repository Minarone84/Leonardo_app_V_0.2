"""Synchronous Research Study calculation, artifact Apply, and Save orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from leonardo.artifacts import (
    ArtifactError,
    ArtifactService,
    ArtifactSourceRefV1,
    LoadedArtifact,
)
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    calculate_financial_tool,
    get_financial_tool_spec,
    resolve_parameters,
    resolve_output_signals,
)
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeOHLCVInputV1,
    PortableRecipeStore,
    PortableRecipeValidationError,
    PortableRecipeV1,
    build_portable_recipe,
)
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.studies import (
    ChartStudy,
    PreparedStudy,
    StudyApplyAttempt,
    StudyArtifactRequest,
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
    _canonical_selector_lineage,
    _validate_study_source_lineage,
    build_chart_study,
)


CancellationCheck = Callable[[], bool]
PersistenceGate = Callable[[], bool]
_ALIASES = {
    "source": "__research_source",
    "fast": "__research_fast",
    "mid": "__research_mid",
    "slow": "__research_slow",
    "peak": "__research_peak",
    "trough": "__research_trough",
    "trend_peak": "__research_trend_peak",
    "trend_trough": "__research_trend_trough",
    "range_peak": "__research_range_peak",
    "range_trough": "__research_range_trough",
}
_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_MULTI_SOURCE_TOOLS = frozenset(
    {"dynamic_binning", "percent_span_angle", "angle_momentum"}
)


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    role: str
    column_name: str
    family: str
    tool_key: str | None
    study_ref: StudyDependencyRef | None
    artifact_ref: ArtifactSourceRefV1 | None


class ResearchStudyService:
    """Prepare full immutable Study results and explicit durable saves."""

    def __init__(
        self,
        artifacts: ArtifactService,
        portable_recipes: PortableRecipeStore | None = None,
    ) -> None:
        if not isinstance(artifacts, ArtifactService):
            raise TypeError("artifacts must be an ArtifactService")
        if portable_recipes is not None and not isinstance(
            portable_recipes, PortableRecipeStore
        ):
            raise TypeError("portable_recipes must be a PortableRecipeStore")
        self._artifacts = artifacts
        self._portable_recipes = portable_recipes

    def prepare_calculation(
        self,
        attempt: StudyApplyAttempt,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        request: StudyExecutionRequest,
        *,
        cancellation_requested: CancellationCheck | None = None,
    ) -> PreparedStudy:
        """Calculate one tool exactly once against complete accepted OHLCV truth."""

        _validate_apply_context(attempt, dataset)
        if not isinstance(request, StudyExecutionRequest):
            raise StudyValidationError("request must be a StudyExecutionRequest")
        snapshot = _study_snapshot(studies)
        cancel = cancellation_requested or _never_cancelled
        _raise_if_cancelled(cancel, "source resolution")
        frame = _dataset_frame(dataset)
        parameters, bindings, resolved = self._resolve_sources(
            attempt, dataset, snapshot, request, frame
        )
        if request.tool_key == "universal_trend_classifier":
            resolved_parameters = resolve_parameters(request.tool_key, parameters)
            trend_window = int(resolved_parameters["trend_fractal_window"])
            range_window = int(resolved_parameters["range_fractal_window"])
            parameters["fractal_window"] = trend_window
            parameters["trend_fractal_window"] = trend_window
            parameters["range_fractal_window"] = range_window
        _raise_if_cancelled(cancel, "calculation")
        result = calculate_financial_tool(
            request.tool_key,
            frame,
            parameters,
            bindings=bindings,
        )
        _raise_if_cancelled(cancel, "calculation publication")
        _validate_result_timeline(result, dataset)
        study = build_chart_study(
            attempt=attempt,
            source_kind="calculation",
            display_name=request.display_name or get_financial_tool_spec(request.tool_key).title,
            result=result,
            setup_request=request,
            source_studies=tuple(
                item.study_ref for item in resolved if item.study_ref is not None
            ),
            source_artifacts=tuple(
                item.artifact_ref for item in resolved if item.artifact_ref is not None
            ),
        )
        _raise_if_cancelled(cancel, "Study publication")
        return PreparedStudy(study)

    def prepare_artifact(
        self,
        attempt: StudyApplyAttempt,
        dataset: HistoricalDataset,
        request: StudyArtifactRequest,
        *,
        cancellation_requested: CancellationCheck | None = None,
    ) -> PreparedStudy:
        """Load one current artifact into the same full Study result path."""

        _validate_apply_context(attempt, dataset)
        if not isinstance(request, StudyArtifactRequest):
            raise StudyValidationError("request must be a StudyArtifactRequest")
        cancel = cancellation_requested or _never_cancelled
        _raise_if_cancelled(cancel, "artifact source resolution")
        loaded, result = self._load_current_research_artifact(
            dataset,
            request.artifact_id,
            expected_kind=request.kind,
            expected_tool_key=request.tool_key,
        )
        _raise_if_cancelled(cancel, "artifact reconstruction")
        metadata = loaded.metadata
        link = StudySavedLink(
            kind=metadata.recipe.kind,
            tool_key=metadata.recipe.tool_key,
            recipe_id=metadata.recipe.recipe_id,
            artifact_id=metadata.artifact_id,
        )
        edit_request = self._artifact_edit_request(
            dataset,
            result,
            metadata.recipe.parameters,
            metadata.recipe.source_artifacts,
            display_name=(
                request.display_name
                if request.display_name is not None
                else metadata.recipe.display_name
            ),
            user_metadata=request.user_metadata,
        )
        study = build_chart_study(
            attempt=attempt,
            source_kind="artifact",
            display_name=(
                request.display_name
                if request.display_name is not None
                else metadata.recipe.display_name
            ),
            result=result,
            setup_request=request,
            edit_request=edit_request,
            source_artifacts=_canonical_study_source_refs(
                result.tool_key, metadata.recipe.source_artifacts
            ),
            saved_link=link,
        )
        _raise_if_cancelled(cancel, "Study publication")
        return PreparedStudy(study)

    def prepare_edit(
        self,
        attempt: StudyEditAttempt,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        request: StudyExecutionRequest,
        *,
        cancellation_requested: CancellationCheck | None = None,
    ) -> PreparedStudy:
        """Calculate one replacement without mutating the current Study."""

        _validate_edit_context(attempt, dataset)
        if not isinstance(request, StudyExecutionRequest):
            raise StudyValidationError("request must be a StudyExecutionRequest")
        snapshot = _study_snapshot(studies)
        target = _find_study(snapshot, attempt.study_id)
        if target.result.tool_key != request.tool_key:
            raise StudyValidationError("edited Study tool key must remain unchanged")
        if request.display_name != target.display_name:
            raise StudyValidationError(
                "edited Study display name must remain unchanged"
            )
        if request.user_metadata != target.user_metadata:
            raise StudyValidationError(
                "edited Study user metadata must remain unchanged"
            )
        if any(
            source.source_kind == "study" and source.study_id == attempt.study_id
            for source in request.input_sources
        ):
            raise StudyValidationError("a Study may not depend on itself")
        cancel = cancellation_requested or _never_cancelled
        _raise_if_cancelled(cancel, "source resolution")
        frame = _dataset_frame(dataset)
        parameters, bindings, resolved = self._resolve_sources(
            attempt, dataset, snapshot, request, frame
        )
        if request.tool_key == "universal_trend_classifier":
            resolved_parameters = resolve_parameters(request.tool_key, parameters)
            trend_window = int(resolved_parameters["trend_fractal_window"])
            range_window = int(resolved_parameters["range_fractal_window"])
            parameters["fractal_window"] = trend_window
            parameters["trend_fractal_window"] = trend_window
            parameters["range_fractal_window"] = range_window
        _raise_if_cancelled(cancel, "calculation")
        result = calculate_financial_tool(
            request.tool_key,
            frame,
            parameters,
            bindings=bindings,
        )
        _raise_if_cancelled(cancel, "calculation publication")
        _validate_result_timeline(result, dataset)
        study = build_chart_study(
            attempt=attempt,
            source_kind="calculation",
            display_name=request.display_name,
            result=result,
            setup_request=request,
            source_studies=tuple(
                item.study_ref for item in resolved if item.study_ref is not None
            ),
            source_artifacts=tuple(
                item.artifact_ref for item in resolved if item.artifact_ref is not None
            ),
            saved_link=None,
        )
        _raise_if_cancelled(cancel, "Study publication")
        return PreparedStudy(study)

    def _artifact_edit_request(
        self,
        dataset: HistoricalDataset,
        result: FinancialToolCalculationResult,
        recipe_parameters: Mapping[str, object],
        source_refs: Sequence[ArtifactSourceRefV1],
        *,
        display_name: str,
        user_metadata,
    ) -> StudyExecutionRequest:
        parameters = {
            name: value
            for name, value in recipe_parameters.items()
            if name not in _owned_selector_names(
                result.tool_key, edit_request=True
            )
        }
        selectors = _canonical_selector_lineage(result)
        sources: dict[str, StudyInputSource] = {
            role: StudyInputSource(
                role=role,
                source_kind="ohlcv",
                column_name=column,
            )
            for role, column in selectors.implicit_ohlcv
        }
        for ref in source_refs:
            _loaded, source_result = self._load_current_research_artifact(
                dataset, ref.artifact_id
            )
            sources[ref.role] = StudyInputSource(
                role=ref.role,
                source_kind="artifact",
                artifact_kind=source_result.kind,
                artifact_tool_key=source_result.tool_key,
                artifact_id=ref.artifact_id,
                output_name=ref.output_name,
            )
        ordered_roles = _edit_source_role_order(result, tuple(sources))
        request = StudyExecutionRequest(
            tool_key=result.tool_key,
            parameters=parameters,
            input_sources=tuple(sources[role] for role in ordered_roles),
            display_name=display_name,
            user_metadata=user_metadata,
        )
        _validate_role_schema(request.tool_key, request.input_sources)
        return request

    def save_study(
        self,
        attempt: StudySaveAttempt,
        dataset: HistoricalDataset,
        study: ChartStudy,
        studies: Sequence[ChartStudy],
        *,
        description: str = "",
        cancellation_requested: CancellationCheck | None = None,
        _begin_persistence: PersistenceGate | None = None,
    ) -> StudySaveOutcome:
        """Persist the exact stored result after durable lineage resolution."""

        _validate_save_context(attempt, dataset, study)
        if not isinstance(description, str):
            raise StudyValidationError("description must be a string")
        if self._portable_recipes is None:
            raise StudyValidationError(
                "portable Recipe store is required for explicit Study Save"
            )
        snapshot = _study_snapshot(studies)
        cancel = cancellation_requested or _never_cancelled
        _raise_if_cancelled(cancel, "save source resolution")
        refs = self._durable_source_refs(dataset, study, snapshot)
        if study.saved_link is not None:
            self._load_current_research_artifact(
                dataset,
                study.saved_link.artifact_id,
                expected_kind=study.saved_link.kind,
                expected_tool_key=study.saved_link.tool_key,
                expected_study=study,
                expected_source_refs=refs,
                expected_link=study.saved_link,
            )
            _raise_if_cancelled(cancel, "save publication")
            if _begin_persistence is not None and not _begin_persistence():
                raise StudyOperationCancelled(
                    "Study operation cancelled before persistence"
                )
            self._publish_portable_recipe(
                dataset,
                study.saved_link.artifact_id,
                study_id=study.study_id,
            )
            self._load_current_research_artifact(
                dataset,
                study.saved_link.artifact_id,
                expected_kind=study.saved_link.kind,
                expected_tool_key=study.saved_link.tool_key,
                expected_study=study,
                expected_source_refs=refs,
                expected_link=study.saved_link,
            )
            return StudySaveOutcome(
                study_id=study.study_id,
                saved_link=study.saved_link,
                created=False,
            )
        existing_artifact_ids = {
            item.artifact_id
            for item in self._artifacts.list_artifacts(
                dataset.market_id,
                kind=study.result.kind,
                tool_key=study.result.tool_key,
            )
        }
        _raise_if_cancelled(cancel, "persistence")
        if _begin_persistence is not None and not _begin_persistence():
            raise StudyOperationCancelled(
                "Study operation cancelled before persistence"
            )
        saved = self._artifacts.save_calculation(
            dataset.market_id,
            study.result,
            source_artifacts=refs,
            display_name=study.display_name,
            description=description,
        )
        metadata = saved.metadata
        saved_link = StudySavedLink(
            kind=metadata.recipe.kind,
            tool_key=metadata.recipe.tool_key,
            recipe_id=metadata.recipe.recipe_id,
            artifact_id=metadata.artifact_id,
        )
        try:
            _validate_artifact_metadata_dataset(metadata, dataset)
            self._load_current_research_artifact(
                dataset,
                metadata.artifact_id,
                expected_kind=metadata.recipe.kind,
                expected_tool_key=metadata.recipe.tool_key,
                expected_study=study,
                expected_source_refs=refs,
                expected_link=saved_link,
            )
            self._publish_portable_recipe(
                dataset,
                metadata.artifact_id,
                study_id=study.study_id,
            )
            self._load_current_research_artifact(
                dataset,
                metadata.artifact_id,
                expected_kind=metadata.recipe.kind,
                expected_tool_key=metadata.recipe.tool_key,
                expected_study=study,
                expected_source_refs=refs,
                expected_link=saved_link,
            )
        except (
            ArtifactError,
            OSError,
            PortableRecipeValidationError,
            StudyValidationError,
        ):
            if metadata.artifact_id not in existing_artifact_ids:
                try:
                    self._artifacts.delete_artifact(
                        dataset.market_id,
                        metadata.recipe.kind,
                        metadata.recipe.tool_key,
                        metadata.artifact_id,
                    )
                except ArtifactError as exc:
                    raise StudyValidationError(
                        "stale Study artifact could not be removed"
                    ) from exc
            raise
        return StudySaveOutcome(
            study_id=study.study_id,
            saved_link=saved_link,
            created=True,
        )

    def _publish_portable_recipe(
        self,
        dataset: HistoricalDataset,
        artifact_id: str,
        *,
        study_id: str,
    ) -> PortableRecipeV1:
        store = self._portable_recipes
        if store is None:
            raise StudyValidationError(
                "portable Recipe store is required for explicit Study Save"
            )
        published: dict[str, PortableRecipeV1] = {}
        resolving: set[str] = set()

        def publish(current_artifact_id: str) -> PortableRecipeV1:
            existing = published.get(current_artifact_id)
            if existing is not None:
                return existing
            if current_artifact_id in resolving:
                raise StudyValidationError(
                    "Research artifact lineage contains a Recipe publication cycle"
                )
            resolving.add(current_artifact_id)
            try:
                loaded, result = self._load_current_research_artifact(
                    dataset, current_artifact_id
                )
                dependencies = tuple(
                    PortableRecipeDependencyV1(
                        ref.role,
                        publish(ref.artifact_id).recipe_id,
                        ref.output_name,
                    )
                    for ref in loaded.metadata.recipe.source_artifacts
                )
                selectors = _canonical_selector_lineage(result)
                ohlcv_inputs = tuple(
                    PortableRecipeOHLCVInputV1(role, column)
                    for role, column in selectors.implicit_ohlcv
                )
                if not ohlcv_inputs and not dependencies:
                    ohlcv_inputs = tuple(
                        PortableRecipeOHLCVInputV1(item.name, item.name)
                        for item in get_financial_tool_spec(
                            result.tool_key
                        ).data_inputs
                    )
                candidate = build_portable_recipe(
                    tool_key=result.tool_key,
                    kind=result.kind,
                    parameters=result.parameters,
                    output_names=result.output_names,
                    ohlcv_inputs=ohlcv_inputs,
                    dependencies=dependencies,
                )
                winner = store.find_equivalent_recipe(candidate) or candidate
                store.persist_recipe(
                    winner,
                    origin_kind="research_save",
                    origin_details={"study_id": study_id},
                )
                published[current_artifact_id] = winner
                return winner
            finally:
                resolving.remove(current_artifact_id)

        return publish(artifact_id)

    def _resolve_sources(
        self,
        attempt: StudyApplyAttempt | StudyEditAttempt,
        dataset: HistoricalDataset,
        studies: tuple[ChartStudy, ...],
        request: StudyExecutionRequest,
        frame: pd.DataFrame,
    ) -> tuple[dict[str, object], dict[str, object], tuple[_ResolvedSource, ...]]:
        _validate_role_schema(request.tool_key, request.input_sources)
        parameters = dict(request.parameters)
        forbidden = _owned_selector_names(request.tool_key)
        supplied = tuple(sorted(forbidden.intersection(parameters)))
        if supplied:
            raise StudyValidationError(
                f"service-owned source selectors were supplied: {supplied!r}"
            )
        resolved_values: list[tuple[_ResolvedSource, tuple[object, ...] | None, str]] = []
        for source in request.input_sources:
            item, values = self._resolve_source(attempt, dataset, studies, source)
            column = (
                source.output_name
                if request.tool_key == "universal_trend_classifier"
                else source.column_name
                if source.source_kind == "ohlcv"
                else _alias(source.role)
            )
            if column is None:
                raise StudyValidationError("resolved source column is missing")
            resolved_values.append((item, values, column))
        resolved = tuple(
            _ResolvedSource(
                role=item.role,
                column_name=column,
                family=item.family,
                tool_key=item.tool_key,
                study_ref=item.study_ref,
                artifact_ref=item.artifact_ref,
            )
            for item, _values, column in resolved_values
        )
        _validate_source_compatibility(request.tool_key, resolved, parameters)
        injected: set[str] = set()
        for _item, values, column in resolved_values:
            if values is not None:
                if column in injected:
                    continue
                if column in frame.columns:
                    raise StudyValidationError(f"source alias collision: {column}")
                if len(values) != dataset.row_count:
                    raise StudyValidationError(
                        "source values do not match the active dataset row count"
                    )
                frame[column] = values
                injected.add(column)
        by_role = {item.role: item.column_name for item in resolved}
        bindings: dict[str, object] = {}
        if request.tool_key in {"derivative", "angle"}:
            bindings["source"] = by_role["source"]
        elif request.tool_key in {"delta", "braids", "braid_instability", "trap_area"}:
            for role in ("fast", "mid", "slow"):
                if role in by_role:
                    parameters[role] = by_role[role]
        elif request.tool_key in _MULTI_SOURCE_TOOLS:
            parameters["source_columns"] = ",".join(
                by_role[f"source_{index}"] for index in range(1, len(by_role) + 1)
            )
        elif request.tool_key == "universal_trend_classifier" and by_role:
            trend_window = resolve_parameters(
                request.tool_key, parameters
            )["trend_fractal_window"]
            parameters["peak_column"] = f"peak_fractal_{trend_window}"
            parameters["trough_column"] = f"trough_fractal_{trend_window}"
        return parameters, bindings, resolved

    def _resolve_source(
        self,
        attempt: StudyApplyAttempt | StudyEditAttempt,
        dataset: HistoricalDataset,
        studies: tuple[ChartStudy, ...],
        source: StudyInputSource,
    ) -> tuple[_ResolvedSource, tuple[object, ...] | None]:
        if source.source_kind == "ohlcv":
            column = source.column_name
            if column is None:
                raise StudyValidationError("OHLCV source column is missing")
            return _ResolvedSource(source.role, column, "ohlc", None, None, None), None
        if source.source_kind == "study":
            study = _find_study(studies, source.study_id or "")
            _validate_source_study(attempt, dataset, study)
            output = source.output_name or ""
            _validate_numeric_analysis_output(study.result, output)
            values = tuple(study.result.to_frame()[output].tolist())
            return (
                _ResolvedSource(
                    source.role,
                    _alias(source.role),
                    study.result.kind,
                    study.result.tool_key,
                    StudyDependencyRef(source.role, study.study_id, output),
                    None,
                ),
                values,
            )
        kind = source.artifact_kind or ""
        tool_key = source.artifact_tool_key or ""
        artifact_id = source.artifact_id or ""
        loaded, result = self._load_current_research_artifact(
            dataset,
            artifact_id,
            expected_kind=kind,
            expected_tool_key=tool_key,
        )
        output = source.output_name or ""
        _validate_numeric_analysis_output(result, output)
        values = tuple(result.to_frame()[output].tolist())
        return (
            _ResolvedSource(
                source.role,
                _alias(source.role),
                result.kind,
                result.tool_key,
                None,
                ArtifactSourceRefV1(
                    role=source.role,
                    artifact_id=artifact_id,
                    output_name=output,
                ),
            ),
            values,
        )

    def _durable_source_refs(
        self,
        dataset: HistoricalDataset,
        study: ChartStudy,
        studies: tuple[ChartStudy, ...],
        *,
        _resolving: tuple[str, ...] = (),
    ) -> tuple[ArtifactSourceRefV1, ...]:
        if study.study_id in _resolving:
            raise StudySaveBlockedError(
                "Study save blocked by a transient dependency cycle",
                blockers=(f"cycle:{study.study_id}",),
            )
        resolving = (*_resolving, study.study_id)
        refs = list(study.source_artifacts)
        blockers: list[str] = []
        for dependency in study.source_studies:
            try:
                source = _find_study(studies, dependency.study_id)
            except StudyNotFoundError:
                blockers.append(f"{dependency.role}:missing:{dependency.study_id}")
                continue
            if (
                source.session_id != study.session_id
                or source.market_id != dataset.market_id
                or source.dataset_fingerprint != dataset.file_sha256
                or source.generation != study.generation
            ):
                blockers.append(f"{dependency.role}:stale:{dependency.study_id}")
                continue
            try:
                _validate_result_timeline(source.result, dataset)
            except StudyValidationError:
                blockers.append(f"{dependency.role}:timeline:{dependency.study_id}")
                continue
            if dependency.output_name not in source.result.output_names:
                blockers.append(f"{dependency.role}:output:{dependency.output_name}")
                continue
            if source.saved_link is None:
                blockers.append(f"{dependency.role}:unsaved:{dependency.study_id}")
                continue
            try:
                source_refs = self._durable_source_refs(
                    dataset,
                    source,
                    studies,
                    _resolving=resolving,
                )
                self._load_current_research_artifact(
                    dataset,
                    source.saved_link.artifact_id,
                    expected_kind=source.saved_link.kind,
                    expected_tool_key=source.saved_link.tool_key,
                    expected_study=source,
                    expected_source_refs=source_refs,
                    expected_link=source.saved_link,
                )
            except (ArtifactError, StudyError) as exc:
                blockers.append(
                    f"{dependency.role}:invalid:{dependency.study_id}:{type(exc).__name__}"
                )
                continue
            refs.append(
                ArtifactSourceRefV1(
                    role=dependency.role,
                    artifact_id=source.saved_link.artifact_id,
                    output_name=dependency.output_name,
                )
            )
        if blockers:
            ordered = tuple(sorted(blockers))
            raise StudySaveBlockedError(
                f"Study save blocked by transient dependencies: {ordered!r}",
                blockers=ordered,
            )
        durable = tuple(sorted(refs, key=lambda item: item.role))
        _validate_study_source_lineage(
            study.result,
            (),
            durable,
            study_id=study.study_id,
        )
        self._validate_durable_artifact_sources(dataset, study.result, durable)
        return durable

    def _validate_durable_artifact_sources(
        self,
        dataset: HistoricalDataset,
        result: FinancialToolCalculationResult,
        refs: tuple[ArtifactSourceRefV1, ...],
    ) -> None:
        resolved: list[_ResolvedSource] = []
        for ref in refs:
            _loaded, source_result = self._load_current_research_artifact(
                dataset,
                ref.artifact_id,
            )
            _validate_numeric_analysis_output(source_result, ref.output_name)
            resolved.append(
                _ResolvedSource(
                    role=ref.role,
                    column_name=_alias(ref.role),
                    family=source_result.kind,
                    tool_key=source_result.tool_key,
                    study_ref=None,
                    artifact_ref=ref,
                )
            )
        _validate_source_compatibility(
            result.tool_key,
            _combined_semantic_sources(result, tuple(resolved)),
            result.parameters,
        )

    def _load_current_research_artifact(
        self,
        dataset: HistoricalDataset,
        artifact_id: str,
        *,
        expected_kind: str | None = None,
        expected_tool_key: str | None = None,
        expected_study: ChartStudy | None = None,
        expected_source_refs: tuple[ArtifactSourceRefV1, ...] | None = None,
        expected_link: StudySavedLink | None = None,
        _visiting: tuple[str, ...] = (),
    ) -> tuple[LoadedArtifact, FinancialToolCalculationResult]:
        if artifact_id in _visiting:
            raise StudyValidationError(
                f"Research artifact lineage cycle detected: {artifact_id}"
            )
        summaries = tuple(
            item
            for item in self._artifacts.list_artifacts(dataset.market_id)
            if item.artifact_id == artifact_id
        )
        if len(summaries) != 1:
            raise StudyValidationError(
                f"Research artifact identity is missing or ambiguous: {artifact_id}"
            )
        summary = summaries[0]
        if not summary.valid:
            raise StudyValidationError(
                f"Research artifact is invalid: {artifact_id}: {summary.rejection_reason}"
            )
        if expected_kind is not None and summary.kind != expected_kind:
            raise StudyValidationError("artifact kind does not match the requested source")
        if expected_tool_key is not None and summary.tool_key != expected_tool_key:
            raise StudyValidationError("artifact tool key does not match the requested source")
        try:
            self._artifacts.validate_artifact_current(
                dataset.market_id,
                summary.kind,
                summary.tool_key,
                artifact_id,
            )
            loaded = self._artifacts.load_artifact(
                dataset.market_id,
                summary.kind,
                summary.tool_key,
                artifact_id,
            )
        except ArtifactError as exc:
            raise StudyValidationError(
                f"Research artifact could not be loaded current: {artifact_id}"
            ) from exc
        result = _validate_loaded_artifact_dataset(loaded, dataset)
        self._validate_loaded_artifact_semantics(
            dataset,
            loaded,
            result,
            _visiting=(*_visiting, artifact_id),
        )
        if expected_study is not None:
            _validate_loaded_artifact_study(
                loaded,
                dataset,
                expected_study,
                expected_source_refs=expected_source_refs,
                expected_link=expected_link,
            )
        try:
            self._artifacts.validate_artifact_current(
                dataset.market_id,
                summary.kind,
                summary.tool_key,
                artifact_id,
            )
        except ArtifactError as exc:
            raise StudyValidationError(
                f"Research artifact changed during validation: {artifact_id}"
            ) from exc
        return loaded, result

    def _validate_loaded_artifact_semantics(
        self,
        dataset: HistoricalDataset,
        loaded: LoadedArtifact,
        result: FinancialToolCalculationResult,
        *,
        _visiting: tuple[str, ...],
    ) -> None:
        refs = loaded.metadata.recipe.source_artifacts
        _validate_study_source_lineage(result, (), refs, study_id=None)
        resolved: list[_ResolvedSource] = []
        for ref in refs:
            _source, source_result = self._load_current_research_artifact(
                dataset,
                ref.artifact_id,
                _visiting=_visiting,
            )
            _validate_numeric_analysis_output(source_result, ref.output_name)
            resolved.append(
                _ResolvedSource(
                    role=ref.role,
                    column_name=_alias(ref.role),
                    family=source_result.kind,
                    tool_key=source_result.tool_key,
                    study_ref=None,
                    artifact_ref=ref,
                )
            )
        _validate_source_compatibility(
            result.tool_key,
            _combined_semantic_sources(result, tuple(resolved)),
            result.parameters,
        )


def _validate_apply_context(
    attempt: StudyApplyAttempt, dataset: HistoricalDataset
) -> None:
    if not isinstance(attempt, StudyApplyAttempt):
        raise StudyValidationError("attempt must be a StudyApplyAttempt")
    if not isinstance(dataset, HistoricalDataset):
        raise StudyValidationError("dataset must be a HistoricalDataset")
    if attempt.market_id != dataset.market_id:
        raise StudyValidationError("attempt MarketId does not match dataset")
    if attempt.dataset_fingerprint != dataset.file_sha256:
        raise StudyValidationError("attempt fingerprint does not match dataset")


def _validate_edit_context(
    attempt: StudyEditAttempt, dataset: HistoricalDataset
) -> None:
    if not isinstance(attempt, StudyEditAttempt):
        raise StudyValidationError("attempt must be a StudyEditAttempt")
    if not isinstance(dataset, HistoricalDataset):
        raise StudyValidationError("dataset must be a HistoricalDataset")
    if attempt.market_id != dataset.market_id:
        raise StudyValidationError("attempt MarketId does not match dataset")
    if attempt.dataset_fingerprint != dataset.file_sha256:
        raise StudyValidationError("attempt fingerprint does not match dataset")


def _validate_save_context(
    attempt: StudySaveAttempt,
    dataset: HistoricalDataset,
    study: ChartStudy,
) -> None:
    if not isinstance(attempt, StudySaveAttempt):
        raise StudyValidationError("attempt must be a StudySaveAttempt")
    if not isinstance(dataset, HistoricalDataset):
        raise StudyValidationError("dataset must be a HistoricalDataset")
    if not isinstance(study, ChartStudy):
        raise StudyValidationError("study must be a ChartStudy")
    if (
        attempt.study_id != study.study_id
        or attempt.session_id != study.session_id
        or attempt.generation != study.generation
        or attempt.market_id != study.market_id
        or attempt.dataset_fingerprint != study.dataset_fingerprint
    ):
        raise StudyValidationError("save attempt does not match Study")
    if dataset.market_id != study.market_id or dataset.file_sha256 != study.dataset_fingerprint:
        raise StudyValidationError("Study does not match the active dataset")
    _validate_result_timeline(study.result, dataset)


def _dataset_frame(dataset: HistoricalDataset) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_ms": dataset.ts_ms,
            "open": dataset.open,
            "high": dataset.high,
            "low": dataset.low,
            "close": dataset.close,
            "volume": dataset.volume,
        }
    )


def _study_snapshot(studies: Sequence[ChartStudy]) -> tuple[ChartStudy, ...]:
    if not isinstance(studies, Sequence) or isinstance(studies, (str, bytes, bytearray)):
        raise StudyValidationError("studies must be a sequence")
    snapshot = tuple(studies)
    if not all(isinstance(study, ChartStudy) for study in snapshot):
        raise StudyValidationError("studies must contain ChartStudy values")
    if len({study.study_id for study in snapshot}) != len(snapshot):
        raise StudyValidationError("Study snapshot IDs must be unique")
    return snapshot


def _find_study(studies: tuple[ChartStudy, ...], study_id: str) -> ChartStudy:
    for study in studies:
        if study.study_id == study_id:
            return study
    raise StudyNotFoundError(f"Study not found: {study_id}")


def _validate_source_study(
    attempt: StudyApplyAttempt | StudyEditAttempt,
    dataset: HistoricalDataset,
    study: ChartStudy,
) -> None:
    if study.session_id != attempt.session_id or study.generation != attempt.generation:
        raise StudyValidationError("source Study does not belong to the active session generation")
    if study.market_id != dataset.market_id:
        raise StudyValidationError("source Study MarketId does not match active dataset")
    if study.dataset_fingerprint != dataset.file_sha256:
        raise StudyValidationError("source Study fingerprint does not match active dataset")
    _validate_result_timeline(study.result, dataset)


def _result_from_loaded_artifact(loaded: LoadedArtifact) -> FinancialToolCalculationResult:
    if not isinstance(loaded, LoadedArtifact):
        raise StudyValidationError("loaded artifact must be a LoadedArtifact")
    recipe = loaded.metadata.recipe
    return FinancialToolCalculationResult(
        tool_key=recipe.tool_key,
        kind=recipe.kind,
        parameters=recipe.parameters,
        bindings=recipe.bindings,
        output_names=recipe.output_names,
        frame=loaded.frame,
        analysis=loaded.analysis,
    )


def _validate_artifact_metadata_dataset(metadata, dataset: HistoricalDataset) -> None:
    recipe = metadata.recipe
    source = metadata.source_ohlcv
    if recipe.market_id != dataset.market_id:
        raise StudyValidationError("artifact MarketId does not match the active dataset")
    if source.csv_sha256 != dataset.file_sha256:
        raise StudyValidationError("artifact source fingerprint does not match the active dataset")
    if source.row_count != dataset.row_count:
        raise StudyValidationError("artifact source row count does not match the active dataset")
    if source.first_timestamp_ms != dataset.first_timestamp_ms:
        raise StudyValidationError(
            "artifact source first timestamp does not match the active dataset"
        )
    if source.last_timestamp_ms != dataset.last_timestamp_ms:
        raise StudyValidationError(
            "artifact source last timestamp does not match the active dataset"
        )


def _validate_loaded_artifact_dataset(
    loaded: LoadedArtifact, dataset: HistoricalDataset
) -> FinancialToolCalculationResult:
    _validate_artifact_metadata_dataset(loaded.metadata, dataset)
    result = _result_from_loaded_artifact(loaded)
    _validate_result_timeline(result, dataset)
    return result


def _validate_loaded_artifact_study(
    loaded: LoadedArtifact,
    dataset: HistoricalDataset,
    study: ChartStudy,
    *,
    expected_source_refs: tuple[ArtifactSourceRefV1, ...] | None,
    expected_link: StudySavedLink | None,
) -> FinancialToolCalculationResult:
    result = _validate_loaded_artifact_dataset(loaded, dataset)
    metadata = loaded.metadata
    recipe = metadata.recipe
    expected = study.result
    if expected_link is None:
        raise StudyValidationError("linked artifact validation requires a saved link")
    if (
        metadata.artifact_id != expected_link.artifact_id
        or recipe.recipe_id != expected_link.recipe_id
        or recipe.kind != expected_link.kind
        or recipe.tool_key != expected_link.tool_key
    ):
        raise StudyValidationError("linked artifact identity does not match the Study")
    if (
        result.tool_key != expected.tool_key
        or result.kind != expected.kind
        or dict(result.parameters) != dict(expected.parameters)
        or dict(result.bindings) != dict(expected.bindings)
        or result.output_names != expected.output_names
    ):
        raise StudyValidationError("linked artifact configuration does not match the Study")
    if expected_source_refs is None or recipe.source_artifacts != expected_source_refs:
        raise StudyValidationError("linked artifact source lineage does not match the Study")
    loaded_frame = result.to_frame().reset_index(drop=True)
    expected_frame = expected.to_frame().reset_index(drop=True)
    if not loaded_frame.equals(expected_frame):
        raise StudyValidationError("linked artifact output truth does not match the Study")
    if result.analysis != expected.analysis:
        raise StudyValidationError("linked artifact analysis does not match the Study")
    return result


def _validate_result_timeline(
    result: FinancialToolCalculationResult, dataset: HistoricalDataset
) -> None:
    if result.row_count != dataset.row_count:
        raise StudyValidationError("Study result row count does not match dataset")
    timestamps = tuple(int(value) for value in result.to_frame()["ts_ms"])
    if timestamps != dataset.ts_ms:
        raise StudyValidationError("Study result timeline does not match dataset")


def _validate_numeric_analysis_output(
    result: FinancialToolCalculationResult, output_name: str
) -> None:
    if output_name not in result.output_names:
        raise StudyValidationError(f"source output does not exist: {output_name!r}")
    signals = resolve_output_signals(
        result.tool_key, {**dict(result.parameters), **dict(result.bindings)}
    )
    signal = next((item for item in signals if item.name == output_name), None)
    if signal is None or not signal.analysis_usable:
        raise StudyValidationError(f"source output is not analysis-usable: {output_name!r}")
    runtime_types = FinancialToolCalculationResult.runtime_output_types(
        tool_key=result.tool_key,
        parameters=result.parameters,
        bindings=result.bindings,
        output_names=result.output_names,
    )
    runtime_type = runtime_types[result.output_names.index(output_name)]
    if runtime_type != "numeric":
        raise StudyValidationError(f"source output is not numeric: {output_name!r}")


def _validate_role_schema(tool_key: str, sources: tuple[StudyInputSource, ...]) -> None:
    roles = tuple(source.role for source in sources)
    role_set = set(roles)
    if tool_key in {"derivative", "angle"}:
        expected = {"source"}
    elif tool_key == "delta":
        expected = {"fast", "slow"}
    elif tool_key in {"braids", "braid_instability"}:
        expected = {"fast", "mid", "slow"}
    elif tool_key == "trap_area":
        if role_set not in ({"fast", "slow"}, {"fast", "mid", "slow"}):
            raise StudyValidationError("trap_area requires fast/slow and optional mid")
        return
    elif tool_key in _MULTI_SOURCE_TOOLS:
        if not roles:
            raise StudyValidationError(f"{tool_key} requires at least one source")
        expected_roles = tuple(f"source_{index}" for index in range(1, len(roles) + 1))
        if roles != expected_roles:
            raise StudyValidationError(
                f"{tool_key} sources must be contiguous and ordered: {expected_roles!r}"
            )
        return
    elif tool_key == "universal_trend_classifier":
        expected_roles = (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
        if roles != expected_roles:
            raise StudyValidationError(
                f"UTC source roles must be exactly {expected_roles!r}"
            )
        return
    else:
        expected = set()
    if role_set != expected or len(roles) != len(expected):
        raise StudyValidationError(
            f"{tool_key} source roles must be exactly {tuple(sorted(expected))!r}"
        )


def _combined_semantic_sources(
    result: FinancialToolCalculationResult,
    resolved: tuple[_ResolvedSource, ...],
) -> tuple[_ResolvedSource, ...]:
    selectors = _canonical_selector_lineage(result)
    implicit = tuple(
        _ResolvedSource(
            role=role,
            column_name=column,
            family="ohlc",
            tool_key=None,
            study_ref=None,
            artifact_ref=None,
        )
        for role, column in selectors.implicit_ohlcv
    )
    return (*implicit, *resolved)


def _canonical_study_source_refs(
    tool_key: str,
    refs: Sequence[ArtifactSourceRefV1],
) -> tuple[ArtifactSourceRefV1, ...]:
    snapshot = tuple(refs)
    if tool_key != "universal_trend_classifier":
        return snapshot
    by_role = {item.role: item for item in snapshot}
    return tuple(
        by_role[role]
        for role in (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
    )


def _validate_source_compatibility(
    tool_key: str,
    sources: tuple[_ResolvedSource, ...],
    parameters: Mapping[str, object] | None = None,
) -> None:
    if tool_key == "universal_trend_classifier" and sources:
        if parameters is None:
            raise StudyValidationError("UTC source validation requires parameters")
        resolved_parameters = resolve_parameters(tool_key, parameters)
        trend_window = resolved_parameters["trend_fractal_window"]
        range_window = resolved_parameters["range_fractal_window"]
        expected = {
            "trend_peak": f"peak_fractal_{trend_window}",
            "trend_trough": f"trough_fractal_{trend_window}",
            "range_peak": f"peak_fractal_{range_window}",
            "range_trough": f"trough_fractal_{range_window}",
        }
        owners: set[tuple[str, str]] = set()
        for source in sources:
            if source.family != "indicator" or source.tool_key != "peaks_troughs":
                raise StudyValidationError("UTC dependencies must be Peaks & Troughs outputs")
            output_name = (
                source.study_ref.output_name
                if source.study_ref is not None
                else source.artifact_ref.output_name if source.artifact_ref is not None else ""
            )
            if output_name != expected.get(source.role):
                raise StudyValidationError(
                    f"UTC {source.role} output must be {expected.get(source.role)!r}"
                )
            if source.study_ref is not None:
                owners.add(("study", source.study_ref.study_id))
            elif source.artifact_ref is not None:
                owners.add(("artifact", source.artifact_ref.artifact_id))
        if len(owners) != 1:
            raise StudyValidationError(
                "UTC sources must come from one Peaks & Troughs owner"
            )
        return
    spec = get_financial_tool_spec(tool_key)
    construct = spec.construct_io
    if construct is None:
        return
    invalid = tuple(
        source.family
        for source in sources
        if source.family not in construct.allowed_source_families
    )
    if invalid:
        raise StudyValidationError(f"source families are not allowed: {invalid!r}")
    if construct.source_compatibility == "same_family" and len(
        {source.family for source in sources}
    ) > 1:
        raise StudyValidationError("all sources must belong to the same family")


def _owned_selector_names(
    tool_key: str, *, edit_request: bool = False
) -> frozenset[str]:
    if tool_key in {"derivative", "angle"}:
        return frozenset({"source"})
    if tool_key in {"delta"}:
        return frozenset({"fast", "slow"})
    if tool_key in {"braids", "braid_instability", "trap_area"}:
        return frozenset({"fast", "mid", "slow"})
    if tool_key in _MULTI_SOURCE_TOOLS:
        return frozenset({"source_columns"})
    if tool_key == "universal_trend_classifier":
        names = {"peak_column", "trough_column"}
        if edit_request:
            names.add("fractal_window")
        return frozenset(names)
    return frozenset()


def _edit_source_role_order(
    result: FinancialToolCalculationResult, supplied_roles: tuple[str, ...]
) -> tuple[str, ...]:
    if not supplied_roles:
        return ()
    role_set = set(supplied_roles)
    if result.tool_key in {"derivative", "angle"}:
        ordered = ("source",)
    elif result.tool_key == "delta":
        ordered = ("fast", "slow")
    elif result.tool_key in {"braids", "braid_instability"}:
        ordered = ("fast", "mid", "slow")
    elif result.tool_key == "trap_area":
        ordered = (
            ("fast", "mid", "slow")
            if "mid" in role_set
            else ("fast", "slow")
        )
    elif result.tool_key in _MULTI_SOURCE_TOOLS:
        ordered = tuple(
            sorted(
                supplied_roles,
                key=lambda role: int(role.removeprefix("source_")),
            )
        )
    elif result.tool_key == "universal_trend_classifier":
        ordered = (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
    else:
        ordered = ()
    if role_set != set(ordered):
        raise StudyValidationError(
            f"artifact edit source roles are invalid: {tuple(sorted(role_set))!r}"
        )
    return ordered


def _alias(role: str) -> str:
    if role.startswith("source_"):
        suffix = role.removeprefix("source_")
        if suffix.isdigit() and int(suffix) > 0:
            return f"__research_source_{int(suffix)}"
    try:
        return _ALIASES[role]
    except KeyError as exc:
        raise StudyValidationError(f"unsupported source role: {role!r}") from exc


def _raise_if_cancelled(check: CancellationCheck, stage: str) -> None:
    if check():
        raise StudyOperationCancelled(f"Study operation cancelled before {stage}")


def _never_cancelled() -> bool:
    return False
