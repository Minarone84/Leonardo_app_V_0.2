from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

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
    compute_logical_artifact_id,
    recipe_identity_payload,
)
from .models import (
    ArtifactAlreadyExistsError,
    ArtifactError,
    ArtifactIdentityCollisionError,
    ArtifactLineageError,
    ArtifactHeadV1,
    ArtifactMetadataV1,
    ArtifactNotFoundError,
    ArtifactRecipeV1,
    ArtifactSaveResult,
    ArtifactSourceRefV1,
    ArtifactSummary,
    ArtifactValidationError,
    ArtifactVersionRecordV1,
    LoadedArtifact,
    ManagedArtifactGraphPublicationResult,
    ManagedArtifactSummary,
    ManagedArtifactVersionKey,
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


@dataclass(frozen=True, slots=True)
class PreparedManagedArtifact:
    logical_artifact_id: str
    portable_recipe_id: str
    previous_artifact_id: str | None
    metadata: ArtifactMetadataV1
    version_record: ArtifactVersionRecordV1
    head: ArtifactHeadV1
    values_bytes: bytes
    analysis_bytes: bytes | None
    recipe_bytes: bytes
    metadata_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ArtifactMetadataV1):
            raise ArtifactValidationError("metadata must be ArtifactMetadataV1")
        if not isinstance(self.version_record, ArtifactVersionRecordV1):
            raise ArtifactValidationError(
                "version_record must be ArtifactVersionRecordV1"
            )
        if not isinstance(self.head, ArtifactHeadV1):
            raise ArtifactValidationError("head must be ArtifactHeadV1")
        metadata = self.metadata
        record = self.version_record
        head = self.head
        if (
            self.logical_artifact_id != record.logical_artifact_id
            or self.logical_artifact_id != head.logical_artifact_id
            or self.portable_recipe_id != record.portable_recipe_id
            or self.previous_artifact_id != record.previous_artifact_id
            or metadata.artifact_id != record.artifact_id
            or metadata.artifact_id != head.artifact_id
            or metadata.recipe.market_id != record.market_id
        ):
            raise ArtifactValidationError("prepared managed Artifact identities disagree")
        if compute_logical_artifact_id(
            metadata.recipe.market_id, self.portable_recipe_id
        ) != self.logical_artifact_id:
            raise ArtifactValidationError("prepared logical Artifact identity disagrees")
        if sha256_bytes(self.values_bytes) != metadata.values_sha256:
            raise ArtifactValidationError("prepared values bytes disagree with metadata")
        if (self.analysis_bytes is None) != (metadata.analysis_sha256 is None):
            raise ArtifactValidationError("prepared analysis bytes disagree with metadata")
        if (
            self.analysis_bytes is not None
            and sha256_bytes(self.analysis_bytes) != metadata.analysis_sha256
        ):
            raise ArtifactValidationError("prepared analysis bytes disagree with metadata")
        if self.recipe_bytes != encode_canonical_json(metadata.recipe.to_dict()):
            raise ArtifactValidationError("prepared Recipe bytes are not canonical")
        if self.metadata_bytes != encode_canonical_json(metadata.to_dict()):
            raise ArtifactValidationError("prepared metadata bytes are not canonical")


class ArtifactService:
    """Own the canonical create, inspect, validate, and delete workflows."""

    def __init__(self, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._ohlcv_store = OHLCVStore(self._historical_root)
        self._store = _CanonicalArtifactStore(self._historical_root)
        self._mutation_lock = RLock()

    def capture_accepted_source(
        self, market_id: MarketId
    ) -> OHLCVSourceFingerprintV1:
        market = _require_market(market_id)
        source, _timestamps = self._capture_accepted_ohlcv(market)
        return OHLCVSourceFingerprintV1.from_dict(source.to_dict())

    def load_artifact_by_id(
        self, market_id: MarketId, artifact_id: str
    ) -> LoadedArtifact:
        market = _require_market(market_id)
        directories = self._store.find_artifact_dirs(market, artifact_id)
        if not directories:
            raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")
        if len(directories) != 1:
            raise ArtifactLineageError(f"duplicate artifact identity: {artifact_id}")
        return self._load_artifact_directory(market, directories[0])

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
        values_sha256 = sha256_bytes(values_bytes)
        analysis_sha256 = sha256_bytes(analysis_bytes) if analysis_bytes is not None else None
        def require_publication_source() -> None:
            current_source = self._capture_ohlcv(market)
            if current_source != source:
                raise ArtifactLineageError("OHLCV source changed before artifact publication")

        with self._mutation_lock:
            current_source = self._capture_ohlcv(market)
            if current_source != source:
                raise ArtifactLineageError(
                    "OHLCV source changed before recipe publication"
                )
            self._validate_exact_source_refs_locked(market, refs, source)
            recipe_result = self._save_recipe_locked(
                market,
                calculation,
                refs,
                display_name=display,
                description=normalized_description,
                created_at_utc=created,
            )
            recipe = recipe_result.recipe
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
            artifact_id = hashlib.sha256(
                canonical_json_identity_bytes(identity_payload)
            ).hexdigest()
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
            final_dir = self._store.artifact_dir(
                market, recipe.kind, recipe.tool_key, artifact_id
            )
            self._store.write_artifact(
                final_dir,
                values_bytes=values_bytes,
                analysis_bytes=analysis_bytes,
                metadata_bytes=encode_canonical_json(metadata.to_dict()),
                pre_publication=require_publication_source,
            )
            try:
                published_source = self._capture_ohlcv(market)
            except Exception as exc:
                self._store.delete_artifact_dir(final_dir)
                raise ArtifactLineageError("OHLCV source changed during artifact publication") from exc
            if published_source != source:
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
        path = self._store.recipe_path(market, kind, tool_key, recipe_id)
        with self._mutation_lock:
            recipe = self.load_recipe(market, kind, tool_key, recipe_id)
            for directory in self._store.iter_artifact_dirs(market):
                try:
                    loaded = self._load_artifact_directory(market, directory)
                except ArtifactValidationError:
                    continue
                if loaded.metadata.recipe.recipe_id == recipe_id:
                    raise RecipeInUseError(
                        f"recipe is referenced by artifact {directory.name}"
                    )
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
        directory = self._store.artifact_dir(market, kind, tool_key, artifact_id)
        with self._mutation_lock:
            loaded = self.load_artifact(market, kind, tool_key, artifact_id)
            for logical_dir in self._store.iter_logical_artifact_dirs(market):
                for version_path in self._store.iter_version_record_paths(
                    market, logical_dir.name
                ):
                    if version_path.stem == artifact_id:
                        raise ArtifactLineageError(
                            "artifact is referenced by managed version"
                        )
            try:
                candidate_dirs = tuple(self._store.iter_artifact_dirs(market))
            except (ArtifactError, OSError) as exc:
                raise ArtifactLineageError(
                    "cannot prove artifact is unreferenced"
                ) from exc
            for candidate_dir in candidate_dirs:
                try:
                    candidate = self._load_artifact_directory(
                        market, candidate_dir
                    )
                except (ArtifactError, OSError) as exc:
                    raise ArtifactLineageError(
                        "cannot prove artifact is unreferenced"
                    ) from exc
                if any(
                    ref.artifact_id == artifact_id
                    for ref in candidate.metadata.recipe.source_artifacts
                ):
                    raise ArtifactLineageError(
                        "artifact is referenced by dependent artifact"
                    )
            summary = _artifact_summary(loaded.metadata)
            self._store.delete_artifact_dir(directory)
        return summary

    def prepare_managed_calculation(
        self,
        market_id: MarketId,
        portable_recipe_id: str,
        result: FinancialToolCalculationResult,
        *,
        expected_source: OHLCVSourceFingerprintV1,
        source_artifacts: Sequence[ArtifactSourceRefV1] = (),
        source_metadata: Sequence[ArtifactMetadataV1] = (),
        previous_artifact_id: str | None = None,
        display_name: str | None = None,
        description: str = "",
        created_at_utc: datetime | None = None,
    ) -> PreparedManagedArtifact:
        market = _require_market(market_id)
        portable_id = _require_sha(portable_recipe_id, "portable_recipe_id")
        calculation = _require_result(result)
        refs = _require_refs(source_artifacts)
        if not isinstance(expected_source, OHLCVSourceFingerprintV1):
            raise ArtifactValidationError(
                "expected_source must be an OHLCVSourceFingerprintV1"
            )
        if expected_source.market_id != market:
            raise ArtifactLineageError("expected source MarketId does not match target")
        previous = (
            None
            if previous_artifact_id is None
            else _require_sha(previous_artifact_id, "previous_artifact_id")
        )
        display, normalized_description, created = _recipe_arguments(
            calculation, display_name, description, created_at_utc
        )
        current, timestamps = self._capture_accepted_ohlcv(market)
        if current != expected_source:
            raise ArtifactLineageError("accepted OHLCV source changed before preparation")
        frame = calculation.to_frame()
        self._validate_full_coverage(calculation, frame, current, timestamps)
        runtime_types = FinancialToolCalculationResult.validate_runtime_outputs(
            tool_key=calculation.tool_key,
            parameters=calculation.parameters,
            bindings=calculation.bindings,
            output_names=calculation.output_names,
            frame=frame,
        )
        if not isinstance(source_metadata, Sequence) or isinstance(
            source_metadata, (str, bytes, bytearray)
        ):
            raise ArtifactValidationError("source_metadata must be a sequence")
        metadata_by_id: dict[str, ArtifactMetadataV1] = {}
        for item in source_metadata:
            if not isinstance(item, ArtifactMetadataV1):
                raise ArtifactValidationError(
                    "source_metadata must contain ArtifactMetadataV1 values"
                )
            if item.artifact_id in metadata_by_id:
                raise ArtifactLineageError("duplicate supplied source metadata owner")
            metadata_by_id[item.artifact_id] = item
        referenced_ids = {item.artifact_id for item in refs}
        if set(metadata_by_id) != referenced_ids:
            raise ArtifactLineageError(
                "source metadata must exactly match referenced Artifacts"
            )
        for ref in refs:
            metadata = metadata_by_id[ref.artifact_id]
            if metadata.recipe.market_id != market:
                raise ArtifactLineageError("source Artifact belongs to another MarketId")
            if metadata.source_ohlcv != expected_source:
                raise ArtifactLineageError("source Artifact OHLCV lineage is not exact")
            if ref.output_name not in metadata.recipe.output_names:
                raise ArtifactLineageError(
                    f"source artifact {ref.artifact_id} has no output {ref.output_name!r}"
                )
        recipe = _build_artifact_recipe(
            market,
            calculation,
            refs,
            display_name=display,
            description=normalized_description,
            created_at_utc=created,
        )
        recipe_path = self._store.recipe_path(
            market, recipe.kind, recipe.tool_key, recipe.recipe_id
        )
        existing_recipe_bytes = self._store.read_optional_bytes(recipe_path)
        if existing_recipe_bytes is not None:
            existing_recipe = self.load_recipe(
                market, recipe.kind, recipe.tool_key, recipe.recipe_id
            )
            if (
                existing_recipe.display_name != recipe.display_name
                or existing_recipe.description != recipe.description
            ):
                raise ArtifactIdentityCollisionError(
                    f"recipe identity collision: {recipe.recipe_id}"
                )
            recipe = existing_recipe
            recipe_bytes = existing_recipe_bytes
        else:
            recipe_bytes = encode_canonical_json(recipe.to_dict())
        values_bytes = encode_values_csv(
            frame, calculation.output_names, runtime_types
        )
        analysis = calculation.analysis
        analysis_bytes = encode_analysis_json(analysis) if analysis else None
        values_sha256 = sha256_bytes(values_bytes)
        analysis_sha256 = (
            sha256_bytes(analysis_bytes) if analysis_bytes is not None else None
        )
        identity_payload = artifact_identity_payload(
            recipe_id=recipe.recipe_id,
            source_ohlcv=current.to_dict(),
            source_artifacts=refs,
            row_count=calculation.row_count,
            first_timestamp_ms=calculation.first_timestamp_ms,
            last_timestamp_ms=calculation.last_timestamp_ms,
            values_sha256=values_sha256,
            analysis_sha256=analysis_sha256,
        )
        artifact_id = hashlib.sha256(
            canonical_json_identity_bytes(identity_payload)
        ).hexdigest()
        metadata = ArtifactMetadataV1(
            artifact_id=artifact_id,
            recipe=recipe,
            source_ohlcv=current,
            row_count=calculation.row_count,
            first_timestamp_ms=calculation.first_timestamp_ms,
            last_timestamp_ms=calculation.last_timestamp_ms,
            values_sha256=values_sha256,
            analysis_filename="analysis.json" if analysis_bytes is not None else None,
            analysis_sha256=analysis_sha256,
            created_at_utc=created,
        )
        metadata_bytes = encode_canonical_json(metadata.to_dict())
        artifact_dir = self._store.artifact_dir(
            market, recipe.kind, recipe.tool_key, artifact_id
        )
        if artifact_dir.exists():
            loaded = self.load_artifact(
                market, recipe.kind, recipe.tool_key, artifact_id
            )
            existing_values, existing_analysis, existing_metadata_bytes = (
                self._store.read_artifact_bytes(artifact_dir)
            )
            existing = loaded.metadata
            if (
                existing.recipe != recipe
                or existing.source_ohlcv != current
                or existing.recipe.source_artifacts != refs
                or existing.row_count != calculation.row_count
                or existing.first_timestamp_ms != calculation.first_timestamp_ms
                or existing.last_timestamp_ms != calculation.last_timestamp_ms
                or existing_values != values_bytes
                or existing_analysis != analysis_bytes
                or existing.values_sha256 != values_sha256
                or existing.analysis_sha256 != analysis_sha256
            ):
                raise ArtifactIdentityCollisionError(
                    f"artifact identity collision: {artifact_id}"
                )
            metadata = existing
            metadata_bytes = existing_metadata_bytes
        logical_id = compute_logical_artifact_id(market, portable_id)
        version_record = ArtifactVersionRecordV1(
            logical_artifact_id=logical_id,
            artifact_id=artifact_id,
            portable_recipe_id=portable_id,
            market_id=market,
            previous_artifact_id=previous,
            created_at_utc=created,
        )
        head = ArtifactHeadV1(logical_id, artifact_id, created)
        return PreparedManagedArtifact(
            logical_id,
            portable_id,
            previous,
            metadata,
            version_record,
            head,
            values_bytes,
            analysis_bytes,
            recipe_bytes,
            metadata_bytes,
        )

    def load_artifact_head(
        self, market_id: MarketId, logical_artifact_id: str
    ) -> ArtifactHeadV1:
        market = _require_market(market_id)
        logical_id = _require_sha(logical_artifact_id, "logical_artifact_id")
        path = self._store.head_path(market, logical_id)
        data = self._store.read_optional_bytes(path)
        if data is None:
            raise ArtifactNotFoundError(f"Artifact head not found: {logical_id}")
        head = ArtifactHeadV1.from_dict(
            decode_canonical_json(data, context="Artifact head")
        )
        if head.logical_artifact_id != logical_id:
            raise ArtifactValidationError("Artifact head identity does not match path")
        return head

    def load_artifact_version(
        self,
        market_id: MarketId,
        logical_artifact_id: str,
        artifact_id: str,
    ) -> ArtifactVersionRecordV1:
        market = _require_market(market_id)
        logical_id = _require_sha(logical_artifact_id, "logical_artifact_id")
        exact_artifact_id = _require_sha(artifact_id, "artifact_id")
        path = self._store.version_record_path(
            market, logical_id, exact_artifact_id
        )
        data = self._store.read_optional_bytes(path)
        if data is None:
            raise ArtifactNotFoundError(
                f"Artifact version not found: {exact_artifact_id}"
            )
        record = ArtifactVersionRecordV1.from_dict(
            decode_canonical_json(data, context="Artifact version record")
        )
        if (
            record.logical_artifact_id != logical_id
            or record.artifact_id != exact_artifact_id
            or record.market_id != market
        ):
            raise ArtifactValidationError(
                "Artifact version identity does not match canonical path"
            )
        return record

    def list_artifact_versions(
        self, market_id: MarketId, logical_artifact_id: str
    ) -> tuple[ArtifactVersionRecordV1, ...]:
        market = _require_market(market_id)
        logical_id = _require_sha(logical_artifact_id, "logical_artifact_id")
        records = tuple(
            self.load_artifact_version(market, logical_id, path.stem)
            for path in self._store.iter_version_record_paths(market, logical_id)
        )
        return tuple(
            sorted(records, key=lambda item: (item.created_at_utc, item.artifact_id))
        )

    def list_managed_artifacts(
        self, market_id: MarketId
    ) -> tuple[ManagedArtifactSummary, ...]:
        market = _require_market(market_id)
        summaries: list[ManagedArtifactSummary] = []
        for directory in self._store.iter_logical_artifact_dirs(market):
            logical_id = directory.name
            try:
                head = self.load_artifact_head(market, logical_id)
                record = self.load_artifact_version(
                    market, logical_id, head.artifact_id
                )
                versions = self.list_artifact_versions(market, logical_id)
                _validate_managed_version_chain(
                    logical_id, versions, head_artifact_id=head.artifact_id
                )
                loaded = self.load_artifact_by_id(market, head.artifact_id)
                if loaded.metadata.artifact_id != record.artifact_id:
                    raise ArtifactLineageError(
                        "managed Artifact metadata disagrees with version record"
                    )
                if loaded.metadata.recipe.market_id != record.market_id:
                    raise ArtifactLineageError(
                        "managed Artifact MarketId disagrees with version record"
                    )
                if record.previous_artifact_id is not None:
                    previous = self.load_artifact_version(
                        market, logical_id, record.previous_artifact_id
                    )
                    if previous.logical_artifact_id != logical_id:
                        raise ArtifactLineageError(
                            "previous version belongs to another logical Artifact"
                        )
                summaries.append(_managed_summary(record, loaded.metadata))
            except (ArtifactError, OSError) as exc:
                summaries.append(
                    ManagedArtifactSummary(
                        logical_id,
                        "",
                        market,
                        "",
                        None,
                        "",
                        "",
                        (),
                        0,
                        0,
                        0,
                        None,
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
        return tuple(sorted(summaries, key=lambda item: item.logical_artifact_id))

    def list_managed_markets(self) -> tuple[MarketId, ...]:
        return tuple(self._store.iter_managed_market_ids())

    def publish_managed_artifact_graph(
        self,
        prepared_artifacts: Sequence[PreparedManagedArtifact],
        *,
        expected_source: OHLCVSourceFingerprintV1,
        before_publish: Callable[[], None] | None = None,
    ) -> ManagedArtifactGraphPublicationResult:
        if not isinstance(prepared_artifacts, Sequence) or isinstance(
            prepared_artifacts, (str, bytes, bytearray)
        ):
            raise ArtifactValidationError("prepared_artifacts must be a sequence")
        prepared = tuple(prepared_artifacts)
        if not prepared:
            raise ArtifactValidationError("prepared_artifacts must not be empty")
        if not all(isinstance(item, PreparedManagedArtifact) for item in prepared):
            raise ArtifactValidationError(
                "prepared_artifacts must contain PreparedManagedArtifact values"
            )
        if not isinstance(expected_source, OHLCVSourceFingerprintV1):
            raise ArtifactValidationError(
                "expected_source must be an OHLCVSourceFingerprintV1"
            )
        market = expected_source.market_id
        created_recipe_paths: list[Path] = []
        created_artifact_dirs: list[Path] = []
        created_version_paths: list[Path] = []
        logical_ids_by_version_path: dict[Path, str] = {}
        touched_heads: dict[Path, bytes | None] = {}
        logical_ids_by_head: dict[Path, str] = {}
        head_prior_bytes: dict[str, bytes | None] = {}

        with self._mutation_lock:
            version_paths: dict[str, Path] = {}
            head_paths: dict[str, Path] = {}
            head_payloads: dict[str, bytes] = {}
            version_create: dict[str, bool] = {}
            head_needs_write: dict[str, bool] = {}

            current_source = self._capture_ohlcv(market)
            if current_source != expected_source:
                raise ArtifactLineageError("OHLCV source changed before publication")

            if len({item.logical_artifact_id for item in prepared}) != len(prepared):
                raise ArtifactValidationError("logical Artifact IDs must be unique")

            candidate_by_artifact_id: dict[str, PreparedManagedArtifact] = {}
            candidate_index_by_artifact_id: dict[str, int] = {}
            candidate_ids = {item.metadata.artifact_id for item in prepared}
            seen_candidate_ids: set[str] = set()
            for index, item in enumerate(prepared):
                if item.metadata.source_ohlcv != expected_source:
                    raise ArtifactLineageError("prepared Artifact source is not exact")
                for ref in item.metadata.recipe.source_artifacts:
                    if (
                        ref.artifact_id in candidate_ids
                        and ref.artifact_id not in seen_candidate_ids
                    ):
                        raise ArtifactLineageError(
                            "prepared Artifact graph is not in topological order"
                        )
                seen_candidate_ids.add(item.metadata.artifact_id)
                prior = candidate_by_artifact_id.get(item.metadata.artifact_id)
                if prior is None:
                    candidate_by_artifact_id[item.metadata.artifact_id] = item
                    candidate_index_by_artifact_id[item.metadata.artifact_id] = index
                elif (
                    prior.values_bytes != item.values_bytes
                    or prior.analysis_bytes != item.analysis_bytes
                    or not _artifact_metadata_semantically_equivalent(
                        prior.metadata, item.metadata
                    )
                ):
                    raise ArtifactIdentityCollisionError(
                        f"artifact identity collision: {item.metadata.artifact_id}"
                    )

            recipe_states: dict[
                str, tuple[Path, ArtifactRecipeV1, bytes, bool]
            ] = {}
            for item in prepared:
                recipe = item.metadata.recipe
                prior_state = recipe_states.get(recipe.recipe_id)
                if prior_state is not None:
                    if not _recipes_semantically_equivalent(prior_state[1], recipe):
                        raise ArtifactIdentityCollisionError(
                            f"recipe identity collision: {recipe.recipe_id}"
                        )
                    continue
                recipe_path = self._store.recipe_path(
                    market, recipe.kind, recipe.tool_key, recipe.recipe_id
                )
                existing_bytes = self._store.read_optional_bytes(recipe_path)
                if existing_bytes is None:
                    recipe_states[recipe.recipe_id] = (
                        recipe_path, recipe, item.recipe_bytes, True
                    )
                else:
                    existing_recipe = self.load_recipe(
                        market, recipe.kind, recipe.tool_key, recipe.recipe_id
                    )
                    if not _recipes_semantically_equivalent(existing_recipe, recipe):
                        raise ArtifactIdentityCollisionError(
                            f"recipe identity collision: {recipe.recipe_id}"
                        )
                    recipe_states[recipe.recipe_id] = (
                        recipe_path, existing_recipe, existing_bytes, False
                    )

            artifact_states: dict[
                str,
                tuple[Path, ArtifactMetadataV1, bytes, bytes | None, bytes, bool],
            ] = {}
            for artifact_id, item in candidate_by_artifact_id.items():
                metadata = item.metadata
                recipe = metadata.recipe
                artifact_dir = self._store.artifact_dir(
                    market, recipe.kind, recipe.tool_key, artifact_id
                )
                if artifact_dir.exists():
                    values, analysis, metadata_bytes = (
                        self._store.read_artifact_bytes(artifact_dir)
                    )
                    loaded = self._load_artifact_directory(market, artifact_dir)
                    if (
                        values != item.values_bytes
                        or analysis != item.analysis_bytes
                        or not _artifact_metadata_semantically_equivalent(
                            loaded.metadata, metadata
                        )
                    ):
                        raise ArtifactIdentityCollisionError(
                            f"artifact identity collision: {artifact_id}"
                        )
                    artifact_states[artifact_id] = (
                        artifact_dir,
                        loaded.metadata,
                        values,
                        analysis,
                        metadata_bytes,
                        False,
                    )
                else:
                    canonical_recipe = recipe_states[recipe.recipe_id][1]
                    canonical_metadata = replace(metadata, recipe=canonical_recipe)
                    artifact_states[artifact_id] = (
                        artifact_dir,
                        canonical_metadata,
                        item.values_bytes,
                        item.analysis_bytes,
                        encode_canonical_json(canonical_metadata.to_dict()),
                        True,
                    )

            summary_records: dict[str, ArtifactVersionRecordV1] = {}
            for item in prepared:
                logical_id = item.logical_artifact_id
                artifact_id = item.metadata.artifact_id
                version_path = self._store.version_record_path(
                    market, logical_id, artifact_id
                )
                version_paths[logical_id] = version_path
                existing_version = self._store.read_optional_bytes(version_path)
                head_path = self._store.head_path(market, logical_id)
                head_paths[logical_id] = head_path
                prior_head = self._store.read_optional_bytes(head_path)
                head_payloads[logical_id] = item.head.canonical_json_bytes()
                if prior_head is None:
                    if item.previous_artifact_id is not None:
                        raise ArtifactLineageError(
                            "new logical Artifact cannot name a previous Artifact"
                        )
                    if tuple(
                        self._store.iter_version_record_paths(market, logical_id)
                    ):
                        raise ArtifactLineageError(
                            "managed Artifact versions exist without a head"
                        )
                    version_create[logical_id] = True
                    head_needs_write[logical_id] = True
                    summary_records[logical_id] = item.version_record
                else:
                    current_head = ArtifactHeadV1.from_dict(
                        decode_canonical_json(prior_head, context="Artifact head")
                    )
                    if current_head.logical_artifact_id != logical_id:
                        raise ArtifactLineageError(
                            "existing Artifact head identity is invalid"
                        )
                    records = self.list_artifact_versions(market, logical_id)
                    _validate_managed_version_chain(
                        logical_id,
                        records,
                        head_artifact_id=current_head.artifact_id,
                    )
                    if current_head.artifact_id == artifact_id:
                        if existing_version is None:
                            raise ArtifactLineageError(
                                "managed Artifact head has no matching version record"
                            )
                        if artifact_states[artifact_id][5]:
                            raise ArtifactLineageError(
                                "managed Artifact payload is missing"
                            )
                        existing_record = self.load_artifact_version(
                            market, logical_id, artifact_id
                        )
                        if (
                            existing_record.portable_recipe_id
                            != item.portable_recipe_id
                            or existing_record.market_id != market
                        ):
                            raise ArtifactLineageError(
                                "existing managed version record is incompatible"
                            )
                        version_create[logical_id] = False
                        head_needs_write[logical_id] = False
                        summary_records[logical_id] = existing_record
                    elif current_head.artifact_id == item.previous_artifact_id:
                        if existing_version is not None:
                            raise ArtifactLineageError(
                                "existing managed version record is not the current head"
                            )
                        version_create[logical_id] = True
                        head_needs_write[logical_id] = True
                        summary_records[logical_id] = item.version_record
                    else:
                        raise ArtifactLineageError(
                            "logical Artifact head changed after preparation"
                        )
                if head_needs_write[logical_id]:
                    head_prior_bytes[logical_id] = prior_head

            for index, item in enumerate(prepared):
                for ref in item.metadata.recipe.source_artifacts:
                    source_candidate = candidate_by_artifact_id.get(ref.artifact_id)
                    if source_candidate is None:
                        self._validate_exact_source_refs_locked(
                            market, (ref,), expected_source
                        )
                        continue
                    if candidate_index_by_artifact_id[ref.artifact_id] >= index:
                        raise ArtifactLineageError(
                            "prepared Artifact graph is not in topological order"
                        )
                    source_metadata = artifact_states[ref.artifact_id][1]
                    if source_metadata.source_ohlcv != expected_source:
                        raise ArtifactLineageError(
                            "source Artifact OHLCV lineage is not exact"
                        )
                    if ref.output_name not in source_metadata.recipe.output_names:
                        raise ArtifactLineageError(
                            f"source artifact {ref.artifact_id} "
                            f"has no output {ref.output_name!r}"
                        )

            if before_publish is not None:
                before_publish()

            created_artifact_ids: list[str] = []
            reused_artifact_ids: list[str] = []
            created_version_keys: list[ManagedArtifactVersionKey] = []
            reused_version_keys: list[ManagedArtifactVersionKey] = []
            advanced_logical_ids: list[str] = []
            try:
                published_recipe_ids: set[str] = set()
                published_artifact_ids: set[str] = set()
                for item in prepared:
                    logical_id = item.logical_artifact_id
                    recipe_id = item.metadata.recipe.recipe_id
                    recipe_path, _recipe, recipe_bytes, create_recipe = (
                        recipe_states[recipe_id]
                    )
                    if recipe_id not in published_recipe_ids and create_recipe:
                        if self._store.write_recipe(recipe_path, recipe_bytes):
                            created_recipe_paths.append(recipe_path)
                    published_recipe_ids.add(recipe_id)
                    artifact_id = item.metadata.artifact_id
                    if artifact_id not in published_artifact_ids:
                        (
                            artifact_dir,
                            _metadata,
                            values_bytes,
                            analysis_bytes,
                            metadata_bytes,
                            create_artifact,
                        ) = artifact_states[artifact_id]
                        if create_artifact:
                            self._store.write_artifact(
                                artifact_dir,
                                values_bytes=values_bytes,
                                analysis_bytes=analysis_bytes,
                                metadata_bytes=metadata_bytes,
                            )
                            created_artifact_dirs.append(artifact_dir)
                            created_artifact_ids.append(artifact_id)
                        else:
                            reused_artifact_ids.append(artifact_id)
                        published_artifact_ids.add(artifact_id)
                    version_key = ManagedArtifactVersionKey(
                        logical_id, artifact_id
                    )
                    if version_create[logical_id]:
                        if self._store.write_version_record(
                            version_paths[logical_id],
                            item.version_record.canonical_json_bytes(),
                        ):
                            created_version_paths.append(version_paths[logical_id])
                            logical_ids_by_version_path[
                                version_paths[logical_id]
                            ] = logical_id
                            created_version_keys.append(version_key)
                    else:
                        reused_version_keys.append(version_key)

                current_source = self._capture_ohlcv(market)
                if current_source != expected_source:
                    raise ArtifactLineageError(
                        "OHLCV source changed during managed publication"
                    )
                for item in prepared:
                    logical_id = item.logical_artifact_id
                    if head_needs_write[logical_id]:
                        head_path = head_paths[logical_id]
                        try:
                            self._store.replace_head(
                                head_path, head_payloads[logical_id]
                            )
                        except Exception:
                            if self._store.read_optional_bytes(
                                head_path
                            ) == head_payloads[logical_id]:
                                touched_heads[head_path] = head_prior_bytes[
                                    logical_id
                                ]
                                logical_ids_by_head[head_path] = logical_id
                            raise
                        touched_heads[head_path] = head_prior_bytes[logical_id]
                        logical_ids_by_head[head_path] = logical_id
                        advanced_logical_ids.append(logical_id)
                final_source = self._capture_ohlcv(market)
                if final_source != expected_source:
                    raise ArtifactLineageError(
                        "OHLCV source changed after managed head publication"
                    )
            except Exception as publication_error:
                try:
                    self._store.managed_rollback_stage()
                    for path, prior_bytes in reversed(tuple(touched_heads.items())):
                        if prior_bytes is None:
                            self._store.delete_head(path)
                        else:
                            self._store.restore_head(path, prior_bytes)
                    for path in reversed(created_version_paths):
                        self._store.delete_version_record(path)
                    for directory in reversed(created_artifact_dirs):
                        self._store.delete_artifact_dir(directory)
                    for path in reversed(created_recipe_paths):
                        if not self._recipe_has_artifact_reference(market, path.stem):
                            self._store.delete_recipe_file(path)
                    cleanup_logical_ids = tuple(
                        dict.fromkeys(
                            logical_ids_by_version_path[path]
                            for path in reversed(created_version_paths)
                        )
                    ) + tuple(
                        dict.fromkeys(
                            logical_ids_by_head[path]
                            for path in reversed(tuple(touched_heads))
                        )
                    )
                    for logical_id in dict.fromkeys(cleanup_logical_ids):
                        self._store.remove_empty_managed_directories(
                            market, logical_id
                        )
                except Exception as rollback_error:
                    raise ArtifactLineageError(
                        "managed Artifact publication failed and rollback failed: "
                        f"publication={type(publication_error).__name__}: {publication_error}; "
                        f"rollback={type(rollback_error).__name__}: {rollback_error}"
                    ) from rollback_error
                if isinstance(
                    publication_error,
                    (ArtifactError, RuntimeError, AssertionError),
                ):
                    raise
                raise ArtifactLineageError(
                    "managed Artifact publication failed: "
                    f"{type(publication_error).__name__}: {publication_error}"
                ) from publication_error

            summaries = tuple(
                _managed_summary(
                    summary_records[item.logical_artifact_id],
                    artifact_states[item.metadata.artifact_id][1],
                )
                for item in prepared
            )
            return ManagedArtifactGraphPublicationResult(
                summaries,
                tuple(created_artifact_ids),
                tuple(reused_artifact_ids),
                tuple(created_version_keys),
                tuple(reused_version_keys),
                tuple(advanced_logical_ids),
            )

    def _recipe_has_artifact_reference(
        self, market: MarketId, recipe_id: str
    ) -> bool:
        for directory in self._store.iter_artifact_dirs(market):
            try:
                loaded = self._load_artifact_directory(market, directory)
            except ArtifactValidationError:
                continue
            if loaded.metadata.recipe.recipe_id == recipe_id:
                return True
        return False

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
        with self._mutation_lock:
            return self._save_recipe_locked(
                market,
                result,
                refs,
                display_name=display_name,
                description=description,
                created_at_utc=created_at_utc,
            )

    def _save_recipe_locked(
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

    def _validate_exact_source_refs_locked(
        self,
        market: MarketId,
        refs: tuple[ArtifactSourceRefV1, ...],
        expected_source: OHLCVSourceFingerprintV1,
    ) -> None:
        for ref in refs:
            self._validate_exact_source_ref_locked(
                market,
                ref,
                expected_source,
                visiting=set(),
            )

    def _validate_exact_source_ref_locked(
        self,
        market: MarketId,
        ref: ArtifactSourceRefV1,
        expected_source: OHLCVSourceFingerprintV1,
        *,
        visiting: set[str],
    ) -> None:
        if ref.artifact_id in visiting:
            raise ArtifactLineageError("source artifact lineage cycle detected")
        loaded = self._load_source_artifact(market, ref.artifact_id)
        metadata = loaded.metadata
        if metadata.recipe.market_id != market:
            raise ArtifactLineageError(
                "source Artifact belongs to another MarketId"
            )
        if metadata.source_ohlcv != expected_source:
            raise ArtifactLineageError(
                "source Artifact OHLCV lineage is not exact"
            )
        if ref.output_name not in metadata.recipe.output_names:
            raise ArtifactLineageError(
                f"source artifact {ref.artifact_id} has no output {ref.output_name!r}"
            )
        visiting.add(ref.artifact_id)
        try:
            for source_ref in metadata.recipe.source_artifacts:
                self._validate_exact_source_ref_locked(
                    market,
                    source_ref,
                    expected_source,
                    visiting=visiting,
                )
        finally:
            visiting.remove(ref.artifact_id)

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


def _require_sha(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ArtifactValidationError(f"{field_name} must be a lowercase SHA-256")
    return value


def _recipes_semantically_equivalent(
    left: ArtifactRecipeV1, right: ArtifactRecipeV1
) -> bool:
    return (
        left.schema_version == right.schema_version
        and left.recipe_id == right.recipe_id
        and left.market_id == right.market_id
        and left.tool_key == right.tool_key
        and left.kind == right.kind
        and left.parameters == right.parameters
        and left.bindings == right.bindings
        and left.output_names == right.output_names
        and left.source_artifacts == right.source_artifacts
        and left.display_name == right.display_name
        and left.description == right.description
    )


def _artifact_metadata_semantically_equivalent(
    left: ArtifactMetadataV1, right: ArtifactMetadataV1
) -> bool:
    return (
        left.schema_version == right.schema_version
        and left.artifact_id == right.artifact_id
        and _recipes_semantically_equivalent(left.recipe, right.recipe)
        and left.source_ohlcv == right.source_ohlcv
        and left.row_count == right.row_count
        and left.first_timestamp_ms == right.first_timestamp_ms
        and left.last_timestamp_ms == right.last_timestamp_ms
        and left.values_filename == right.values_filename
        and left.values_sha256 == right.values_sha256
        and left.analysis_filename == right.analysis_filename
        and left.analysis_sha256 == right.analysis_sha256
    )


def _validate_managed_version_chain(
    logical_artifact_id: str,
    records: Sequence[ArtifactVersionRecordV1],
    *,
    head_artifact_id: str,
) -> None:
    if not records:
        raise ArtifactLineageError("managed Artifact has no version records")
    by_id = {item.artifact_id: item for item in records}
    if len(by_id) != len(records):
        raise ArtifactLineageError("managed Artifact versions contain duplicate IDs")
    if any(item.logical_artifact_id != logical_artifact_id for item in records):
        raise ArtifactLineageError("managed Artifact version belongs to another identity")
    if len({item.portable_recipe_id for item in records}) != 1:
        raise ArtifactLineageError("managed Artifact versions disagree on portable Recipe")
    referenced = {
        item.previous_artifact_id
        for item in records
        if item.previous_artifact_id is not None
    }
    if not referenced.issubset(by_id):
        raise ArtifactLineageError("managed Artifact version predecessor is missing")
    tips = set(by_id).difference(referenced)
    if tips != {head_artifact_id}:
        raise ArtifactLineageError("managed Artifact head disagrees with version chain")
    visited: set[str] = set()
    current: str | None = head_artifact_id
    while current is not None:
        if current in visited:
            raise ArtifactLineageError("managed Artifact version chain contains a cycle")
        visited.add(current)
        current = by_id[current].previous_artifact_id
    if visited != set(by_id):
        raise ArtifactLineageError("managed Artifact version chain is disconnected")


def _build_artifact_recipe(
    market: MarketId,
    result: FinancialToolCalculationResult,
    refs: tuple[ArtifactSourceRefV1, ...],
    *,
    display_name: str,
    description: str,
    created_at_utc: datetime,
) -> ArtifactRecipeV1:
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
    return ArtifactRecipeV1(
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


def _managed_summary(
    record: ArtifactVersionRecordV1, metadata: ArtifactMetadataV1
) -> ManagedArtifactSummary:
    return ManagedArtifactSummary(
        record.logical_artifact_id,
        record.portable_recipe_id,
        record.market_id,
        record.artifact_id,
        record.previous_artifact_id,
        metadata.recipe.tool_key,
        metadata.recipe.kind,
        metadata.recipe.output_names,
        metadata.row_count,
        metadata.first_timestamp_ms,
        metadata.last_timestamp_ms,
        metadata.created_at_utc,
    )


def _sort_time(value: datetime | None) -> datetime:
    return value if value is not None else datetime.max.replace(tzinfo=UTC)
