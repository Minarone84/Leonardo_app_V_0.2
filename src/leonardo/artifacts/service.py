from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
)
from leonardo.ohlcv.store import OHLCVStore

from ._stores import _CanonicalArtifactStore
from .identity import (
    artifact_identity_payload,
    canonical_json_identity_bytes,
    recipe_identity_payload,
)
from .models import (
    ArtifactAlreadyExistsError,
    ArtifactIdentityCollisionError,
    ArtifactLineageError,
    ArtifactMetadataV1,
    ArtifactNotFoundError,
    ArtifactRecipeV1,
    ArtifactSaveResult,
    ArtifactSourceRefV1,
    ArtifactSummary,
    ArtifactValidationError,
    LoadedArtifact,
    OHLCVSourceFingerprintV1,
    RecipeInUseError,
    RecipeSaveResult,
    RecipeSummary,
)
from .serialization import (
    capture_file_state,
    decode_analysis_json,
    decode_canonical_json,
    decode_values_csv,
    encode_analysis_json,
    encode_canonical_json,
    encode_values_csv,
    sha256_bytes,
)


class ArtifactService:
    """Own the canonical create, inspect, validate, and delete workflows."""

    def __init__(self, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._ohlcv_store = OHLCVStore(self._historical_root)
        self._store = _CanonicalArtifactStore(self._historical_root)

    def save_recipe_from_result(
        self,
        market_id: MarketId,
        result: FinancialToolCalculationResult,
        *,
        source_artifacts: Sequence[ArtifactSourceRefV1] = (),
        display_name: str | None = None,
        description: str = "",
        created_at_utc: datetime | None = None,
    ) -> RecipeSaveResult:
        market = _require_market(market_id)
        calculation = _require_result(result)
        refs = _require_refs(source_artifacts)
        display, normalized_description, created = _recipe_arguments(
            calculation, display_name, description, created_at_utc
        )
        if refs:
            current, current_timestamps = self._capture_accepted_ohlcv(market)
            self._validate_source_refs(market, refs, current, current_timestamps)
        return self._save_recipe(
            market,
            calculation,
            refs,
            display_name=display,
            description=normalized_description,
            created_at_utc=created,
        )

    def save_calculation(
        self,
        market_id: MarketId,
        result: FinancialToolCalculationResult,
        *,
        source_artifacts: Sequence[ArtifactSourceRefV1] = (),
        display_name: str | None = None,
        description: str = "",
        created_at_utc: datetime | None = None,
    ) -> ArtifactSaveResult:
        market = _require_market(market_id)
        calculation = _require_result(result)
        refs = _require_refs(source_artifacts)
        display, normalized_description, created = _recipe_arguments(
            calculation, display_name, description, created_at_utc
        )
        source, source_timestamps = self._capture_accepted_ohlcv(market)
        frame = calculation.to_frame()
        self._validate_full_coverage(calculation, frame, source, source_timestamps)
        self._validate_source_refs(market, refs, source, source_timestamps)
        runtime_types = FinancialToolCalculationResult.validate_runtime_outputs(
            tool_key=calculation.tool_key,
            parameters=calculation.parameters,
            bindings=calculation.bindings,
            output_names=calculation.output_names,
            frame=frame,
        )
        values_bytes = encode_values_csv(frame, calculation.output_names, runtime_types)
        analysis = calculation.analysis
        analysis_bytes = encode_analysis_json(analysis) if analysis else None
        checked_source, checked_timestamps = self._capture_accepted_ohlcv(market)
        if checked_source != source or checked_timestamps != source_timestamps:
            raise ArtifactLineageError("OHLCV source changed before recipe publication")
        recipe_result = self._save_recipe(
            market,
            calculation,
            refs,
            display_name=display,
            description=normalized_description,
            created_at_utc=created,
        )
        recipe = recipe_result.recipe
        values_sha256 = sha256_bytes(values_bytes)
        analysis_sha256 = sha256_bytes(analysis_bytes) if analysis_bytes is not None else None
        identity_payload = artifact_identity_payload(
            recipe_id=recipe.recipe_id,
            source_ohlcv=source.to_dict(),
            source_artifacts=refs,
            row_count=calculation.row_count,
            first_timestamp_ms=calculation.first_timestamp_ms,
            last_timestamp_ms=calculation.last_timestamp_ms,
            values_sha256=values_sha256,
            analysis_sha256=analysis_sha256,
        )
        artifact_id = hashlib.sha256(canonical_json_identity_bytes(identity_payload)).hexdigest()
        metadata = ArtifactMetadataV1(
            artifact_id=artifact_id,
            recipe=recipe,
            source_ohlcv=source,
            row_count=calculation.row_count,
            first_timestamp_ms=calculation.first_timestamp_ms,
            last_timestamp_ms=calculation.last_timestamp_ms,
            values_sha256=values_sha256,
            analysis_filename="analysis.json" if analysis_bytes is not None else None,
            analysis_sha256=analysis_sha256,
            created_at_utc=_created(created_at_utc),
        )
        final_dir = self._store.artifact_dir(market, recipe.kind, recipe.tool_key, artifact_id)
        def require_publication_source() -> None:
            current_source, current_timestamps = self._capture_accepted_ohlcv(market)
            if current_source != source or current_timestamps != source_timestamps:
                raise ArtifactLineageError("OHLCV source changed before artifact publication")

        self._store.write_artifact(
            final_dir,
            values_bytes=values_bytes,
            analysis_bytes=analysis_bytes,
            metadata_bytes=encode_canonical_json(metadata.to_dict()),
            pre_publication=require_publication_source,
        )
        try:
            published_source, published_timestamps = self._capture_accepted_ohlcv(market)
        except Exception as exc:
            self._store.delete_artifact_dir(final_dir)
            raise ArtifactLineageError("OHLCV source changed during artifact publication") from exc
        if published_source != source or published_timestamps != source_timestamps:
            self._store.delete_artifact_dir(final_dir)
            raise ArtifactLineageError("OHLCV source changed during artifact publication")
        return ArtifactSaveResult(metadata=metadata, path=final_dir)

    def load_recipe(
        self, market_id: MarketId, kind: str, tool_key: str, recipe_id: str
    ) -> ArtifactRecipeV1:
        market = _require_market(market_id)
        path = self._store.recipe_path(market, kind, tool_key, recipe_id)
        payload = decode_canonical_json(self._store.read_recipe_bytes(path), context="recipe")
        recipe = ArtifactRecipeV1.from_dict(payload)
        if (
            recipe.market_id != market
            or recipe.kind != kind
            or recipe.tool_key != tool_key
            or recipe.recipe_id != recipe_id
        ):
            raise ArtifactValidationError("recipe content does not match canonical path")
        return recipe

    def list_recipes(
        self,
        market_id: MarketId,
        *,
        kind: str | None = None,
        tool_key: str | None = None,
    ) -> tuple[RecipeSummary, ...]:
        market = _require_market(market_id)
        summaries: list[RecipeSummary] = []
        for path in self._store.iter_recipe_paths(market, kind=kind, tool_key=tool_key):
            path_kind = path.parent.parent.name
            path_tool = path.parent.name
            try:
                recipe = self.load_recipe(market, path_kind, path_tool, path.stem)
                summaries.append(_recipe_summary(recipe))
            except Exception as exc:
                summaries.append(
                    RecipeSummary(
                        market_id=market,
                        recipe_id=path.stem,
                        tool_key=path_tool,
                        kind=path_kind,
                        output_names=(),
                        display_name="",
                        created_at_utc=None,
                        valid=False,
                        rejection_reason=f"{type(exc).__name__}: {exc}",
                    )
                )
        return tuple(sorted(summaries, key=lambda item: (_sort_time(item.created_at_utc), item.recipe_id)))

    def delete_recipe(
        self, market_id: MarketId, kind: str, tool_key: str, recipe_id: str
    ) -> RecipeSummary:
        market = _require_market(market_id)
        recipe = self.load_recipe(market, kind, tool_key, recipe_id)
        for directory in self._store.iter_artifact_dirs(market):
            try:
                loaded = self._load_artifact_directory(market, directory)
            except ArtifactValidationError:
                continue
            if loaded.metadata.recipe.recipe_id == recipe_id:
                raise RecipeInUseError(f"recipe is referenced by artifact {directory.name}")
        path = self._store.recipe_path(market, kind, tool_key, recipe_id)
        self._store.delete_recipe_file(path)
        return _recipe_summary(recipe)

    def load_artifact(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> LoadedArtifact:
        market = _require_market(market_id)
        directory = self._store.artifact_dir(market, kind, tool_key, artifact_id)
        return self._load_artifact_directory(market, directory)

    def list_artifacts(
        self,
        market_id: MarketId,
        *,
        kind: str | None = None,
        tool_key: str | None = None,
    ) -> tuple[ArtifactSummary, ...]:
        market = _require_market(market_id)
        summaries: list[ArtifactSummary] = []
        for directory in self._store.iter_artifact_dirs(market, kind=kind, tool_key=tool_key):
            path_kind = directory.parent.parent.name
            path_tool = directory.parent.name
            try:
                loaded = self._load_artifact_directory(market, directory)
                summaries.append(_artifact_summary(loaded.metadata))
            except Exception as exc:
                summaries.append(
                    ArtifactSummary(
                        market_id=market,
                        artifact_id=directory.name,
                        recipe_id="",
                        tool_key=path_tool,
                        kind=path_kind,
                        output_names=(),
                        row_count=0,
                        first_timestamp_ms=0,
                        last_timestamp_ms=0,
                        created_at_utc=None,
                        valid=False,
                        rejection_reason=f"{type(exc).__name__}: {exc}",
                    )
                )
        return tuple(sorted(summaries, key=lambda item: (_sort_time(item.created_at_utc), item.artifact_id)))

    def validate_artifact_current(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> ArtifactSummary:
        market = _require_market(market_id)
        current, current_timestamps = self._capture_accepted_ohlcv(market)
        loaded = self.load_artifact(market, kind, tool_key, artifact_id)
        self._validate_loaded_lineage(
            market, loaded, current, current_timestamps, visiting=set()
        )
        final_source, _final_timestamps = self._capture_accepted_ohlcv(market)
        if final_source != current:
            raise ArtifactLineageError("OHLCV source changed during current validation")
        return _artifact_summary(loaded.metadata)

    def delete_artifact(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> ArtifactSummary:
        market = _require_market(market_id)
        loaded = self.load_artifact(market, kind, tool_key, artifact_id)
        summary = _artifact_summary(loaded.metadata)
        directory = self._store.artifact_dir(market, kind, tool_key, artifact_id)
        self._store.delete_artifact_dir(directory)
        return summary

    def _save_recipe(
        self,
        market: MarketId,
        result: FinancialToolCalculationResult,
        refs: tuple[ArtifactSourceRefV1, ...],
        *,
        display_name: str,
        description: str,
        created_at_utc: datetime,
    ) -> RecipeSaveResult:
        payload = recipe_identity_payload(
            market_id=market,
            tool_key=result.tool_key,
            kind=result.kind,
            parameters=result.parameters,
            bindings=result.bindings,
            output_names=result.output_names,
            source_artifacts=refs,
        )
        recipe_id = hashlib.sha256(canonical_json_identity_bytes(payload)).hexdigest()
        path = self._store.recipe_path(market, result.kind, result.tool_key, recipe_id)
        if path.is_file():
            existing = self.load_recipe(market, result.kind, result.tool_key, recipe_id)
            if existing.display_name != display_name or existing.description != description:
                raise ArtifactIdentityCollisionError(f"recipe identity collision: {recipe_id}")
            return RecipeSaveResult(recipe=existing, path=path, created=False)
        recipe = ArtifactRecipeV1(
            recipe_id=recipe_id,
            market_id=market,
            tool_key=result.tool_key,
            kind=result.kind,
            parameters=result.parameters,
            bindings=result.bindings,
            output_names=result.output_names,
            source_artifacts=refs,
            display_name=display_name,
            description=description,
            created_at_utc=created_at_utc,
        )
        created = self._store.write_recipe(path, encode_canonical_json(recipe.to_dict()))
        return RecipeSaveResult(recipe=recipe, path=path, created=created)

    def _capture_ohlcv(self, market: MarketId) -> OHLCVSourceFingerprintV1:
        csv_path = self._ohlcv_store.csv_path(market)
        sidecar_path = self._ohlcv_store.sidecar_path(market)
        if not csv_path.is_file():
            raise ArtifactLineageError("canonical OHLCV CSV is missing")
        if not sidecar_path.is_file():
            raise ArtifactLineageError("canonical OHLCV sidecar is missing")
        try:
            csv_before = capture_file_state(csv_path)
            sidecar_before = capture_file_state(sidecar_path)
            sidecar = self._ohlcv_store.read_sidecar(market)
            csv_after = capture_file_state(csv_path)
            sidecar_after = capture_file_state(sidecar_path)
        except (OSError, ValueError, TypeError, ArtifactValidationError) as exc:
            raise ArtifactLineageError(f"failed to capture stable OHLCV source: {exc}") from exc
        if csv_before != csv_after or sidecar_before != sidecar_after:
            raise ArtifactLineageError("OHLCV files changed during lineage capture")
        if sidecar.market_id != market:
            raise ArtifactLineageError("OHLCV sidecar MarketId does not match")
        if sidecar.file_sha256 != csv_after.sha256:
            raise ArtifactLineageError("OHLCV CSV hash does not match sidecar")
        try:
            return OHLCVSourceFingerprintV1(
                market_id=market,
                csv_sha256=csv_after.sha256,
                sidecar_sha256=sidecar_after.sha256,
                row_count=sidecar.row_count,
                first_timestamp_ms=sidecar.first_timestamp_ms,
                last_timestamp_ms=sidecar.last_timestamp_ms,
                persistence_status=sidecar.persistence_status,
                validation_status=sidecar.validation_status,
                sidecar_schema_version=sidecar.schema_version,
            )
        except ArtifactValidationError as exc:
            raise ArtifactLineageError(f"OHLCV source is not accepted: {exc}") from exc

    def _capture_accepted_ohlcv(
        self, market: MarketId
    ) -> tuple[OHLCVSourceFingerprintV1, tuple[int, ...]]:
        first = self._capture_ohlcv(market)
        try:
            timestamps = tuple(candle.ts_ms for candle in self._ohlcv_store.read(market))
        except (OSError, TypeError, ValueError) as exc:
            raise ArtifactLineageError("failed to read accepted OHLCV timeline") from exc
        second = self._capture_ohlcv(market)
        if first != second:
            raise ArtifactLineageError("OHLCV source changed during timeline capture")
        if (
            len(timestamps) != first.row_count
            or not timestamps
            or timestamps[0] != first.first_timestamp_ms
            or timestamps[-1] != first.last_timestamp_ms
            or any(current <= previous for previous, current in zip(timestamps, timestamps[1:]))
        ):
            raise ArtifactLineageError("OHLCV timeline does not match its accepted fingerprint")
        return first, timestamps

    def _validate_full_coverage(
        self,
        result: FinancialToolCalculationResult,
        frame: pd.DataFrame,
        source: OHLCVSourceFingerprintV1,
        source_timestamps: tuple[int, ...],
    ) -> None:
        if (
            result.row_count != source.row_count
            or result.first_timestamp_ms != source.first_timestamp_ms
            or result.last_timestamp_ms != source.last_timestamp_ms
        ):
            raise ArtifactLineageError("calculation coverage does not match the full OHLCV source")
        result_timestamps = tuple(int(value) for value in frame["ts_ms"])
        if source_timestamps != result_timestamps:
            raise ArtifactLineageError("calculation timestamps do not exactly cover the OHLCV source")

    def _validate_source_refs(
        self,
        market: MarketId,
        refs: tuple[ArtifactSourceRefV1, ...],
        current: OHLCVSourceFingerprintV1,
        current_timestamps: tuple[int, ...],
    ) -> None:
        for ref in refs:
            loaded = self._load_source_artifact(market, ref.artifact_id)
            if ref.output_name not in loaded.metadata.recipe.output_names:
                raise ArtifactLineageError(
                    f"source artifact {ref.artifact_id} has no output {ref.output_name!r}"
                )
            self._validate_loaded_lineage(
                market, loaded, current, current_timestamps, visiting=set()
            )

    def _validate_loaded_lineage(
        self,
        market: MarketId,
        loaded: LoadedArtifact,
        current: OHLCVSourceFingerprintV1,
        current_timestamps: tuple[int, ...],
        *,
        visiting: set[str],
    ) -> None:
        metadata = loaded.metadata
        if metadata.artifact_id in visiting:
            raise ArtifactLineageError("source artifact lineage cycle detected")
        if metadata.source_ohlcv != current:
            raise ArtifactLineageError(f"artifact {metadata.artifact_id} has stale OHLCV lineage")
        artifact_timestamps = tuple(int(value) for value in loaded.frame["ts_ms"])
        if artifact_timestamps != current_timestamps:
            raise ArtifactLineageError(
                f"artifact {metadata.artifact_id} timeline does not match current OHLCV"
            )
        visiting.add(metadata.artifact_id)
        try:
            for ref in metadata.recipe.source_artifacts:
                source = self._load_source_artifact(market, ref.artifact_id)
                if ref.output_name not in source.metadata.recipe.output_names:
                    raise ArtifactLineageError(
                        f"source artifact {ref.artifact_id} has no output {ref.output_name!r}"
                    )
                self._validate_loaded_lineage(
                    market,
                    source,
                    current,
                    current_timestamps,
                    visiting=visiting,
                )
        finally:
            visiting.remove(metadata.artifact_id)

    def _load_source_artifact(self, market: MarketId, artifact_id: str) -> LoadedArtifact:
        directories = self._store.find_artifact_dirs(market, artifact_id)
        if not directories:
            raise ArtifactLineageError(f"source artifact not found for current MarketId: {artifact_id}")
        if len(directories) != 1:
            raise ArtifactLineageError(f"duplicate source artifact identity: {artifact_id}")
        return self._load_artifact_directory(market, directories[0])

    def _load_artifact_directory(self, market: MarketId, directory: Path) -> LoadedArtifact:
        values_bytes, analysis_bytes, metadata_bytes = self._store.read_artifact_bytes(directory)
        metadata = ArtifactMetadataV1.from_dict(
            decode_canonical_json(metadata_bytes, context="artifact metadata")
        )
        path_kind = directory.parent.parent.name
        path_tool = directory.parent.name
        if (
            metadata.recipe.market_id != market
            or metadata.recipe.kind != path_kind
            or metadata.recipe.tool_key != path_tool
            or metadata.artifact_id != directory.name
        ):
            raise ArtifactValidationError("artifact content does not match canonical path")
        if sha256_bytes(values_bytes) != metadata.values_sha256:
            raise ArtifactValidationError("values.csv SHA-256 mismatch")
        if (analysis_bytes is None) != (metadata.analysis_filename is None):
            raise ArtifactValidationError("analysis file pairing mismatch")
        if analysis_bytes is not None and sha256_bytes(analysis_bytes) != metadata.analysis_sha256:
            raise ArtifactValidationError("analysis.json SHA-256 mismatch")
        runtime_types = FinancialToolCalculationResult.runtime_output_types(
            tool_key=metadata.recipe.tool_key,
            parameters=metadata.recipe.parameters,
            bindings=metadata.recipe.bindings,
            output_names=metadata.recipe.output_names,
        )
        frame = decode_values_csv(values_bytes, metadata.recipe.output_names, runtime_types)
        for name, runtime_type in zip(
            metadata.recipe.output_names,
            runtime_types,
            strict=True,
        ):
            if runtime_type == "categorical":
                frame[name] = frame[name].astype(
                    FinancialToolCalculationResult.categorical_output_dtype(
                        tool_key=metadata.recipe.tool_key,
                        output_name=name,
                    )
                )
        if (
            len(frame) != metadata.row_count
            or int(frame["ts_ms"].iloc[0]) != metadata.first_timestamp_ms
            or int(frame["ts_ms"].iloc[-1]) != metadata.last_timestamp_ms
        ):
            raise ArtifactValidationError("values.csv coverage does not match artifact metadata")
        analysis = decode_analysis_json(analysis_bytes) if analysis_bytes is not None else {}
        try:
            validated = FinancialToolCalculationResult(
                tool_key=metadata.recipe.tool_key,
                kind=metadata.recipe.kind,
                parameters=metadata.recipe.parameters,
                bindings=metadata.recipe.bindings,
                output_names=metadata.recipe.output_names,
                frame=frame,
                analysis=analysis,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactValidationError("artifact runtime outputs are invalid") from exc
        return LoadedArtifact(metadata, validated.to_frame(), validated.analysis)


def _require_market(market_id: MarketId) -> MarketId:
    if not isinstance(market_id, MarketId):
        raise ArtifactValidationError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        market_id.exchange, market_id.market_type, market_id.symbol, market_id.timeframe
    )
    if canonical != market_id:
        raise ArtifactValidationError("market_id must already be canonical")
    return market_id


def _require_result(result: FinancialToolCalculationResult) -> FinancialToolCalculationResult:
    if not isinstance(result, FinancialToolCalculationResult):
        raise ArtifactValidationError("result must be a FinancialToolCalculationResult")
    try:
        FinancialToolCalculationResult.validate_configuration(
            tool_key=result.tool_key,
            kind=result.kind,
            parameters=result.parameters,
            bindings=result.bindings,
            output_names=result.output_names,
        )
        FinancialToolCalculationResult.validate_runtime_outputs(
            tool_key=result.tool_key,
            parameters=result.parameters,
            bindings=result.bindings,
            output_names=result.output_names,
            frame=result.to_frame(),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtifactValidationError("result Financial Tool configuration is invalid") from exc
    return result


def _require_refs(source_artifacts: Sequence[ArtifactSourceRefV1]) -> tuple[ArtifactSourceRefV1, ...]:
    if not isinstance(source_artifacts, Sequence) or isinstance(source_artifacts, (str, bytes, bytearray)):
        raise ArtifactValidationError("source_artifacts must be a sequence")
    if not all(isinstance(item, ArtifactSourceRefV1) for item in source_artifacts):
        raise ArtifactValidationError("source_artifacts must contain ArtifactSourceRefV1 values")
    refs = tuple(sorted(source_artifacts, key=lambda item: (item.role, item.artifact_id, item.output_name)))
    if len({item.role for item in refs}) != len(refs):
        raise ArtifactValidationError("source artifact roles must be unique")
    return refs


def _created(value: datetime | None) -> datetime:
    created = datetime.now(UTC) if value is None else value
    if not isinstance(created, datetime) or created.tzinfo is None:
        raise ArtifactValidationError("created_at_utc must be timezone-aware")
    return created.astimezone(UTC)


def _recipe_arguments(
    result: FinancialToolCalculationResult,
    display_name: str | None,
    description: str,
    created_at_utc: datetime | None,
) -> tuple[str, str, datetime]:
    if display_name is not None and not isinstance(display_name, str):
        raise ArtifactValidationError("display_name must be a string or None")
    display = result.tool_key if display_name is None else display_name.strip()
    if not display:
        raise ArtifactValidationError("display_name must be non-empty")
    if not isinstance(description, str):
        raise ArtifactValidationError("description must be a string")
    return display, description.strip(), _created(created_at_utc)


def _recipe_summary(recipe: ArtifactRecipeV1) -> RecipeSummary:
    return RecipeSummary(
        market_id=recipe.market_id,
        recipe_id=recipe.recipe_id,
        tool_key=recipe.tool_key,
        kind=recipe.kind,
        output_names=recipe.output_names,
        display_name=recipe.display_name,
        created_at_utc=recipe.created_at_utc,
    )


def _artifact_summary(metadata: ArtifactMetadataV1) -> ArtifactSummary:
    return ArtifactSummary(
        market_id=metadata.recipe.market_id,
        artifact_id=metadata.artifact_id,
        recipe_id=metadata.recipe.recipe_id,
        tool_key=metadata.recipe.tool_key,
        kind=metadata.recipe.kind,
        output_names=metadata.recipe.output_names,
        row_count=metadata.row_count,
        first_timestamp_ms=metadata.first_timestamp_ms,
        last_timestamp_ms=metadata.last_timestamp_ms,
        created_at_utc=metadata.created_at_utc,
    )


def _sort_time(value: datetime | None) -> datetime:
    return value if value is not None else datetime.max.replace(tzinfo=UTC)
