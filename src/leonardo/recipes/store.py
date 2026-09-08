"""Hardened global persistence for portable Recipes and Collections."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from leonardo.financial_tools import get_financial_tool_spec

from .identity import (
    ObjectSemanticKey,
    compute_portable_recipe_id,
    portable_recipe_object_semantic_key,
)
from .models import (
    PortableRecipeCollectionHeadV1,
    PortableRecipeCollectionRevisionV1,
    PortableRecipeDependencyV1,
    PortableRecipeOHLCVInputV1,
    PortableRecipeOriginV1,
    PortableRecipePersistenceMetadataV1,
    PortableRecipeProvenanceV1,
    PortableRecipeV1,
    PortableRecipeValidationError,
    canonical_json_bytes,
)
from .planner import PortableRecipeGraphPlanner


class PortableRecipeStoreError(PortableRecipeValidationError):
    """Raised when portable Recipe persisted truth cannot be used safely."""


class PortableRecipeIdentityCollisionError(PortableRecipeStoreError):
    """Raised when an immutable identity already contains different bytes."""


@dataclass(frozen=True, slots=True)
class PortableRecipeSummary:
    recipe_id: str
    tool_key: str
    tool_version: str
    kind: str
    output_names: tuple[str, ...]
    dependency_count: int
    ohlcv_input_count: int
    valid: bool = True
    rejection_reason: str = ""


@dataclass(frozen=True, slots=True)
class PortableRecipeSemanticRecord:
    persisted_recipe_id: str
    canonical_current_recipe_id: str
    semantic_key: bytes
    canonical_recipe: PortableRecipeV1


@dataclass(frozen=True, slots=True)
class PortableRecipeCollectionSummary:
    collection_id: str
    revision_id: str
    display_name: str
    description: str
    root_count: int
    member_count: int
    created_at_utc: datetime | None
    updated_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""


class PortableRecipeStore:
    """Own canonical global portable Recipe persistence under one runtime root."""

    def __init__(
        self,
        root_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        collection_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root_dir = Path(root_dir).absolute()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._collection_id_factory = collection_id_factory or (lambda: uuid4().hex)
        self._lock = RLock()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def save_recipe(self, recipe: PortableRecipeV1) -> PortableRecipeV1:
        if not isinstance(recipe, PortableRecipeV1):
            raise TypeError("recipe must be a PortableRecipeV1")
        path = self._recipe_path(recipe.recipe_id)
        with self._lock:
            if path.exists():
                self._write_immutable(path, recipe.canonical_json_bytes())
                return recipe
            metadata = PortableRecipePersistenceMetadataV1(
                recipe.recipe_id, self._now(), ()
            )
            self._write_new_recipe_with_metadata(recipe, metadata)
        return recipe

    def persist_recipe(
        self,
        recipe: PortableRecipeV1,
        *,
        origin_kind: str,
        origin_details: Mapping[str, str],
    ) -> PortableRecipeV1:
        """Persist or reuse a Recipe and atomically record one known origin."""

        if not isinstance(recipe, PortableRecipeV1):
            raise TypeError("recipe must be a PortableRecipeV1")
        path = self._recipe_path(recipe.recipe_id)
        with self._lock:
            recorded_at = self._now()
            origin = PortableRecipeOriginV1.build(
                origin_kind=origin_kind,
                origin_recorded_at_utc=recorded_at,
                details=origin_details,
            )
            if path.exists():
                self._write_immutable(path, recipe.canonical_json_bytes())
                self._record_recipe_origin_locked(recipe.recipe_id, origin)
                return recipe
            metadata = PortableRecipePersistenceMetadataV1(
                recipe.recipe_id, recorded_at, (origin,)
            )
            self._write_new_recipe_with_metadata(recipe, metadata)
        return recipe

    def load_recipe(self, recipe_id: str) -> PortableRecipeV1:
        path = self._recipe_path(recipe_id)
        with self._lock:
            return self._load_model(path, PortableRecipeV1)

    def load_persistence_metadata(
        self, recipe_id: str
    ) -> PortableRecipePersistenceMetadataV1 | None:
        """Return authoritative persistence metadata without migrating legacy data."""

        self._validate_sha(recipe_id, "recipe_id")
        with self._lock:
            self._load_recipe_semantics(self._recipe_path(recipe_id))
            return self._load_persistence_metadata_locked(recipe_id)

    def record_recipe_origin(
        self,
        recipe_id: str,
        *,
        origin_kind: str,
        origin_details: Mapping[str, str],
    ) -> PortableRecipePersistenceMetadataV1:
        """Merge one meaningful origin without changing Recipe identity or age."""

        self._validate_sha(recipe_id, "recipe_id")
        with self._lock:
            self._load_recipe_semantics(self._recipe_path(recipe_id))
            origin = PortableRecipeOriginV1.build(
                origin_kind=origin_kind,
                origin_recorded_at_utc=self._now(),
                details=origin_details,
            )
            return self._record_recipe_origin_locked(recipe_id, origin)

    def list_recipe_summaries(self) -> tuple[PortableRecipeSummary, ...]:
        root = self._root_dir / "recipes"
        with self._lock:
            self._require_root_if_present()
            if not root.exists():
                return ()
            self._require_safe_directory(root)
            summaries: list[PortableRecipeSummary] = []
            for path in sorted(root.glob("*.json")):
                try:
                    recipe = self._load_model(path, PortableRecipeV1)
                    if recipe.recipe_id != path.stem:
                        raise PortableRecipeStoreError("Recipe ID does not match file name")
                    summaries.append(
                        PortableRecipeSummary(
                            recipe.recipe_id,
                            recipe.tool_key,
                            recipe.tool_version,
                            recipe.kind,
                            recipe.output_names,
                            len(recipe.dependencies),
                            len(recipe.ohlcv_inputs),
                        )
                    )
                except (FileNotFoundError, PortableRecipeStoreError) as exc:
                    summaries.append(
                        PortableRecipeSummary(
                            path.stem, "", "", "", (), 0, 0, False,
                            f"{type(exc).__name__}: {exc}",
                        )
                    )
            return tuple(
                sorted(summaries, key=lambda item: (item.kind, item.tool_key, item.recipe_id))
            )

    def inspect_recipe_semantics(
        self, recipe_id: str
    ) -> PortableRecipeSemanticRecord:
        """Read one current or historical Recipe through canonical semantics."""

        path = self._recipe_path(recipe_id)
        with self._lock:
            record = self._load_recipe_semantics(path)
            semantic_key = self._recipe_semantic_key(
                record.canonical_recipe,
                {},
                set(),
                persisted_recipe_id=record.persisted_recipe_id,
            )
            return PortableRecipeSemanticRecord(
                record.persisted_recipe_id,
                record.canonical_current_recipe_id,
                semantic_key,
                record.canonical_recipe,
            )

    def semantic_key_for_recipe(
        self,
        recipe: PortableRecipeV1,
        *,
        recipes: Mapping[str, PortableRecipeV1] | None = None,
    ) -> ObjectSemanticKey:
        """Return the shared semantic key for a candidate Recipe graph."""

        if not isinstance(recipe, PortableRecipeV1):
            raise TypeError("recipe must be a PortableRecipeV1")
        with self._lock:
            return self._recipe_semantic_key(recipe, dict(recipes or {}), set())

    def find_equivalent_recipe(
        self,
        recipe: PortableRecipeV1,
        *,
        recipes: Mapping[str, PortableRecipeV1] | None = None,
    ) -> PortableRecipeV1 | None:
        """Return the deterministic valid semantic winner without publishing."""

        requested_key = self.semantic_key_for_recipe(recipe, recipes=recipes)
        candidates: list[PortableRecipeV1] = []
        for summary in self.list_recipe_summaries():
            if not summary.valid:
                continue
            try:
                current = self.load_recipe(summary.recipe_id)
                if self.semantic_key_for_recipe(current) == requested_key:
                    candidates.append(current)
            except (FileNotFoundError, PortableRecipeStoreError):
                continue
        if not candidates:
            return None
        return min(candidates, key=lambda item: item.recipe_id)

    def recipe_deletion_blockers(self, recipe_id: str) -> tuple[str, ...]:
        """Return exact Recipe and Collection references blocking deletion."""

        self._validate_sha(recipe_id, "recipe_id")
        with self._lock:
            self.inspect_recipe_semantics(recipe_id)
            blockers: list[str] = []
            for candidate in self._all_recipe_semantics_for_deletion_proof():
                if candidate.persisted_recipe_id == recipe_id:
                    continue
                if any(
                    dependency.recipe_id == recipe_id
                    for dependency in candidate.canonical_recipe.dependencies
                ):
                    blockers.append(
                        f"Recipe {candidate.persisted_recipe_id}"
                    )
            for revision in self._all_collection_revisions_for_recipe_reference_proof():
                if recipe_id in revision.member_recipe_ids:
                    blockers.append(
                        f"Recipe Collection {revision.collection_id} "
                        f"revision {revision.revision_id}"
                    )
            return tuple(blockers)

    def save_provenance(
        self, provenance: PortableRecipeProvenanceV1
    ) -> PortableRecipeProvenanceV1:
        if not isinstance(provenance, PortableRecipeProvenanceV1):
            raise TypeError("provenance must be a PortableRecipeProvenanceV1")
        recipe = self.load_recipe(provenance.recipe_id)
        if recipe.recipe_id != provenance.recipe_id:
            raise PortableRecipeStoreError("provenance Recipe does not exist")
        path = self._provenance_path(provenance.recipe_id, provenance.provenance_id)
        with self._lock:
            self._record_recipe_origin_locked(
                provenance.recipe_id,
                PortableRecipeOriginV1.build(
                    origin_kind="study_environment",
                    origin_recorded_at_utc=self._now(),
                    details={
                        "environment_id": provenance.study_environment_id,
                        "environment_content_hash": (
                            provenance.study_environment_content_hash
                        ),
                        "entry_id": provenance.study_entry_id,
                    },
                ),
            )
            self._write_immutable(path, provenance.canonical_json_bytes())
        return provenance

    def list_provenance(self, recipe_id: str) -> tuple[PortableRecipeProvenanceV1, ...]:
        self._validate_sha(recipe_id, "recipe_id")
        root = self._root_dir / "recipe_provenance" / recipe_id
        with self._lock:
            self._require_root_if_present()
            if not root.exists():
                return ()
            self._require_safe_directory(root)
            values: list[PortableRecipeProvenanceV1] = []
            for path in sorted(root.glob("*.json")):
                if path.name == "metadata.json":
                    continue
                item = self._load_model(path, PortableRecipeProvenanceV1)
                if item.recipe_id != recipe_id or item.provenance_id != path.stem:
                    raise PortableRecipeStoreError("provenance identity does not match path")
                values.append(item)
            return tuple(sorted(values, key=lambda item: item.provenance_id))

    def create_collection(
        self,
        display_name: str,
        description: str,
        root_recipe_ids: Sequence[str],
        member_recipe_ids: Sequence[str],
    ) -> PortableRecipeCollectionRevisionV1:
        with self._lock:
            canonical_members = self._validate_collection_request_members(
                root_recipe_ids, member_recipe_ids
            )
            existing = self._find_equivalent_current_collection(
                root_recipe_ids, canonical_members
            )
            if existing is not None:
                return existing
            collection_id = self._new_collection_id()
            created_at = self._now()
            revision = PortableRecipeCollectionRevisionV1.build(
                collection_id=collection_id,
                display_name=display_name,
                description=description,
                root_recipe_ids=root_recipe_ids,
                member_recipe_ids=canonical_members,
                previous_revision_id=None,
                created_at_utc=created_at,
            )
            self._publish_revision(revision, updated_at_utc=created_at)
            return revision

    def find_equivalent_collection(
        self,
        root_recipe_ids: Sequence[str],
        member_recipe_ids: Sequence[str],
    ) -> PortableRecipeCollectionRevisionV1 | None:
        """Return the current oldest semantic winner without publishing."""

        with self._lock:
            canonical_members = self._validate_collection_request_members(
                root_recipe_ids, member_recipe_ids
            )
            return self._find_equivalent_current_collection(
                root_recipe_ids, canonical_members
            )

    def update_collection(
        self,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: Sequence[str],
        member_recipe_ids: Sequence[str],
        *,
        expected_head_revision_id: str | None = None,
    ) -> PortableRecipeCollectionRevisionV1:
        with self._lock:
            current = self.load_collection(collection_id)
            if (
                expected_head_revision_id is not None
                and current.revision_id != expected_head_revision_id
            ):
                raise PortableRecipeStoreError(
                    "Recipe Collection changed since it was selected"
                )
            canonical_members = self._validate_collection_request_members(
                root_recipe_ids, member_recipe_ids
            )
            existing = self._find_equivalent_current_collection(
                root_recipe_ids, canonical_members
            )
            if existing is not None and existing.collection_id != collection_id:
                return existing
            created_at = self._now()
            revision = PortableRecipeCollectionRevisionV1.build(
                collection_id=collection_id,
                display_name=display_name,
                description=description,
                root_recipe_ids=root_recipe_ids,
                member_recipe_ids=canonical_members,
                previous_revision_id=current.revision_id,
                created_at_utc=created_at,
            )
            self._publish_revision(revision, updated_at_utc=created_at)
            return revision

    def load_collection(self, collection_id: str) -> PortableRecipeCollectionRevisionV1:
        head_path = self._collection_dir(collection_id) / "head.json"
        with self._lock:
            head = self._load_model(head_path, PortableRecipeCollectionHeadV1)
            if head.collection_id != collection_id:
                raise PortableRecipeStoreError("Collection head identity does not match path")
            revision = self.load_collection_revision(collection_id, head.revision_id)
            self._validate_collection_members(
                revision.root_recipe_ids, revision.member_recipe_ids
            )
            return revision

    def load_collection_revision(
        self, collection_id: str, revision_id: str
    ) -> PortableRecipeCollectionRevisionV1:
        path = self._revision_path(collection_id, revision_id)
        with self._lock:
            revision = self._load_model(path, PortableRecipeCollectionRevisionV1)
            if revision.collection_id != collection_id or revision.revision_id != revision_id:
                raise PortableRecipeStoreError("Collection revision identity does not match path")
            return revision

    def list_collection_summaries(self) -> tuple[PortableRecipeCollectionSummary, ...]:
        root = self._root_dir / "recipe_collections"
        with self._lock:
            self._require_root_if_present()
            if not root.exists():
                return ()
            self._require_safe_directory(root)
            summaries: list[PortableRecipeCollectionSummary] = []
            for path in sorted(item for item in root.iterdir() if item.is_dir() or _is_link(item)):
                collection_id = path.name
                try:
                    revision = self.load_collection(collection_id)
                    head = self._load_model(path / "head.json", PortableRecipeCollectionHeadV1)
                    revisions = self.list_collection_revisions(collection_id)
                    if not revisions:
                        raise PortableRecipeStoreError(
                            "portable Recipe Collection has no valid revisions"
                        )
                    summaries.append(
                        PortableRecipeCollectionSummary(
                            collection_id,
                            revision.revision_id,
                            revision.display_name,
                            revision.description,
                            len(revision.root_recipe_ids),
                            len(revision.member_recipe_ids),
                            revisions[0].created_at_utc,
                            head.updated_at_utc,
                        )
                    )
                except (FileNotFoundError, PortableRecipeStoreError) as exc:
                    summaries.append(
                        PortableRecipeCollectionSummary(
                            collection_id, "", collection_id, "", 0, 0, None, None,
                            False, f"{type(exc).__name__}: {exc}",
                        )
                    )
            return tuple(
                sorted(
                    summaries,
                    key=lambda item: (item.display_name.casefold(), item.collection_id),
                )
            )

    def list_collection_revisions(
        self, collection_id: str
    ) -> tuple[PortableRecipeCollectionRevisionV1, ...]:
        root = self._collection_dir(collection_id) / "revisions"
        with self._lock:
            self._require_root_if_present()
            if not root.exists():
                return ()
            self._require_safe_directory(root)
            revisions = tuple(
                self.load_collection_revision(collection_id, path.stem)
                for path in sorted(root.glob("*.json"))
            )
            return tuple(sorted(revisions, key=lambda item: (item.created_at_utc, item.revision_id)))

    def delete_recipe(
        self,
        recipe_id: str,
        *,
        before_delete: Callable[[], None] | None = None,
        canonical_winner_id: str | None = None,
    ) -> PortableRecipeV1:
        with self._lock:
            if canonical_winner_id is None:
                recipe = self.load_recipe(recipe_id)
            else:
                self._validate_sha(canonical_winner_id, "canonical_winner_id")
                if recipe_id == canonical_winner_id:
                    raise PortableRecipeStoreError(
                        "duplicate Recipe candidate equals canonical winner"
                    )
                candidate = self.inspect_recipe_semantics(recipe_id)
                winner = self.inspect_recipe_semantics(canonical_winner_id)
                if candidate.semantic_key != winner.semantic_key:
                    raise PortableRecipeStoreError(
                        "duplicate Recipe semantic identity changed"
                    )
                recipe = candidate.canonical_recipe

            blockers = self.recipe_deletion_blockers(recipe_id)
            if any(
                item.startswith("Recipe ")
                and not item.startswith("Recipe Collection ")
                for item in blockers
            ):
                raise PortableRecipeStoreError(
                    "portable Recipe is referenced by another Recipe"
                )
            if blockers:
                raise PortableRecipeStoreError(
                    "portable Recipe is referenced by a Recipe Collection"
                )

            provenance_dir = self._root_dir / "recipe_provenance" / recipe_id
            provenance_paths = self._provenance_paths_for_deletion(
                recipe_id, provenance_dir
            )
            if before_delete is not None:
                before_delete()

            self._recipe_path(recipe_id).unlink()
            for path in provenance_paths:
                path.unlink()
            if provenance_dir.exists():
                provenance_dir.rmdir()
            self._remove_empty_directory(self._root_dir / "recipe_provenance")
            self._remove_empty_directory(self._root_dir / "recipes")
            self._remove_empty_directory(self._root_dir)
            return recipe

    def _write_new_recipe_with_metadata(
        self,
        recipe: PortableRecipeV1,
        metadata: PortableRecipePersistenceMetadataV1,
    ) -> None:
        recipe_path = self._recipe_path(recipe.recipe_id)
        metadata_path = self._persistence_metadata_path(recipe.recipe_id)
        self._write_immutable(recipe_path, recipe.canonical_json_bytes())
        try:
            self._write_immutable(metadata_path, metadata.canonical_json_bytes())
        except (OSError, PortableRecipeValidationError):
            recipe_path.unlink()
            self._remove_empty_directory(self._root_dir / "recipes")
            self._remove_empty_directory(
                self._root_dir / "recipe_provenance" / recipe.recipe_id
            )
            self._remove_empty_directory(self._root_dir / "recipe_provenance")
            self._remove_empty_directory(self._root_dir)
            raise

    def _record_recipe_origin_locked(
        self, recipe_id: str, origin: PortableRecipeOriginV1
    ) -> PortableRecipePersistenceMetadataV1:
        current = self._load_persistence_metadata_locked(recipe_id)
        if current is None:
            current = PortableRecipePersistenceMetadataV1(recipe_id, None, ())
        if any(item.origin_id == origin.origin_id for item in current.origins):
            return current
        updated = PortableRecipePersistenceMetadataV1(
            recipe_id,
            current.first_persisted_at_utc,
            (*current.origins, origin),
        )
        self._write_mutable(
            self._persistence_metadata_path(recipe_id),
            updated.canonical_json_bytes(),
        )
        return updated

    def _load_persistence_metadata_locked(
        self, recipe_id: str
    ) -> PortableRecipePersistenceMetadataV1 | None:
        path = self._persistence_metadata_path(recipe_id)
        if not path.exists() and not _is_link(path):
            self._require_root_if_present()
            return None
        metadata = self._load_model(path, PortableRecipePersistenceMetadataV1)
        if metadata.recipe_id != recipe_id:
            raise PortableRecipeStoreError(
                "Recipe persistence metadata identity does not match path"
            )
        return metadata

    def delete_collection(
        self,
        collection_id: str,
        *,
        before_delete: Callable[[], None] | None = None,
    ) -> PortableRecipeCollectionRevisionV1:
        with self._lock:
            current = self.load_collection(collection_id)
            collection_dir = self._collection_dir(collection_id)
            revisions = self._preflight_collection_directory(collection_dir)
            if not revisions or current.revision_id not in {
                item.revision_id for item in revisions
            }:
                raise PortableRecipeStoreError(
                    "portable Recipe Collection revisions do not match head"
                )
            if before_delete is not None:
                before_delete()

            (collection_dir / "head.json").unlink()
            revisions_dir = collection_dir / "revisions"
            for revision in revisions:
                (revisions_dir / f"{revision.revision_id}.json").unlink()
            revisions_dir.rmdir()
            collection_dir.rmdir()
            self._remove_empty_directory(self._root_dir / "recipe_collections")
            self._remove_empty_directory(self._root_dir)
            return current

    def _publish_revision(
        self,
        revision: PortableRecipeCollectionRevisionV1,
        *,
        updated_at_utc: datetime,
    ) -> None:
        revision_path = self._revision_path(revision.collection_id, revision.revision_id)
        self._write_immutable(revision_path, revision.canonical_json_bytes())
        head = PortableRecipeCollectionHeadV1(
            revision.collection_id, revision.revision_id, updated_at_utc
        )
        self._write_mutable(
            self._collection_dir(revision.collection_id) / "head.json",
            head.canonical_json_bytes(),
        )

    def _all_recipe_semantics_for_deletion_proof(
        self,
    ) -> tuple[PortableRecipeSemanticRecord, ...]:
        root = self._root_dir / "recipes"
        self._require_safe_directory(root)
        values: list[PortableRecipeSemanticRecord] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if (
                _is_link(path)
                or not path.is_file()
                or path.suffix != ".json"
                or len(path.stem) != 64
            ):
                raise PortableRecipeStoreError(
                    "unexpected portable Recipe persistence shape"
                )
            self._validate_sha(path.stem, "recipe_id")
            values.append(self._load_recipe_semantics(path))
        return tuple(values)

    def _load_recipe_semantics(self, path: Path) -> PortableRecipeSemanticRecord:
        self._require_safe_file(path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortableRecipeStoreError("invalid portable Recipe JSON") from exc
        expected_fields = {
            "schema_version",
            "object_type",
            "recipe_id",
            "tool_key",
            "tool_version",
            "kind",
            "parameters",
            "output_names",
            "ohlcv_inputs",
            "dependencies",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise PortableRecipeStoreError(
                "portable Recipe JSON does not match its persisted schema"
            )
        persisted_recipe_id = payload["recipe_id"]
        self._validate_sha(persisted_recipe_id, "recipe_id")
        if persisted_recipe_id != path.stem:
            raise PortableRecipeStoreError("Recipe ID does not match file name")
        try:
            if not isinstance(payload["ohlcv_inputs"], list) or not isinstance(
                payload["dependencies"], list
            ):
                raise PortableRecipeValidationError(
                    "Recipe sources must be JSON arrays"
                )
            ohlcv_inputs = tuple(
                PortableRecipeOHLCVInputV1.from_dict(item)
                for item in payload["ohlcv_inputs"]
            )
            dependencies = tuple(
                PortableRecipeDependencyV1.from_dict(item)
                for item in payload["dependencies"]
            )
            canonical_recipe_id = compute_portable_recipe_id(
                tool_key=payload["tool_key"],
                tool_version=payload["tool_version"],
                kind=payload["kind"],
                parameters=payload["parameters"],
                output_names=payload["output_names"],
                ohlcv_inputs=ohlcv_inputs,
                dependencies=dependencies,
                schema_version=payload["schema_version"],
                object_type=payload["object_type"],
            )
            current_payload = dict(payload)
            current_payload["recipe_id"] = canonical_recipe_id
            canonical_recipe = PortableRecipeV1.from_dict(current_payload)
            persisted_payload = canonical_recipe.to_dict()
            persisted_payload["recipe_id"] = persisted_recipe_id
            if raw != canonical_json_bytes(persisted_payload):
                raise PortableRecipeStoreError(
                    "portable Recipe JSON bytes are not canonical"
                )
        except PortableRecipeStoreError:
            raise
        except (TypeError, ValueError, PortableRecipeValidationError) as exc:
            raise PortableRecipeStoreError(
                "portable Recipe JSON does not match its persisted schema"
            ) from exc
        return PortableRecipeSemanticRecord(
            persisted_recipe_id,
            canonical_recipe_id,
            b"",
            canonical_recipe,
        )

    def _recipe_semantic_key(
        self,
        recipe: PortableRecipeV1,
        recipes: dict[str, PortableRecipeV1],
        active: set[str],
        *,
        persisted_recipe_id: str | None = None,
    ) -> ObjectSemanticKey:
        identity = persisted_recipe_id or recipe.recipe_id
        if identity in active:
            raise PortableRecipeStoreError(
                "portable Recipe semantic dependency graph contains a cycle"
            )
        active.add(identity)

        def dependency_key(recipe_id: str) -> ObjectSemanticKey:
            dependency = recipes.get(recipe_id)
            dependency_persisted_id: str | None = None
            if dependency is None:
                record = self._load_recipe_semantics(self._recipe_path(recipe_id))
                dependency = record.canonical_recipe
                dependency_persisted_id = record.persisted_recipe_id
            return self._recipe_semantic_key(
                dependency,
                recipes,
                active,
                persisted_recipe_id=dependency_persisted_id,
            )

        try:
            return portable_recipe_object_semantic_key(
                recipe,
                dependency_key,
                implicit_ohlcv_inputs=tuple(
                    item.name for item in get_financial_tool_spec(recipe.tool_key).data_inputs
                ),
            )
        finally:
            active.remove(identity)

    def _all_collection_revisions_for_deletion_proof(
        self,
    ) -> tuple[PortableRecipeCollectionRevisionV1, ...]:
        root = self._root_dir / "recipe_collections"
        if not root.exists() and not _is_link(root):
            return ()
        self._require_safe_directory(root)
        values: list[PortableRecipeCollectionRevisionV1] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if _is_link(path) or not path.is_dir():
                raise PortableRecipeStoreError(
                    "unexpected portable Recipe Collection persistence shape"
                )
            self._validate_collection_id(path.name)
            current = self.load_collection(path.name)
            revisions = self._preflight_collection_directory(path)
            if current.revision_id not in {item.revision_id for item in revisions}:
                raise PortableRecipeStoreError(
                    "portable Recipe Collection revisions do not match head"
                )
            values.extend(revisions)
        return tuple(values)

    def _all_collection_revisions_for_recipe_reference_proof(
        self,
    ) -> tuple[PortableRecipeCollectionRevisionV1, ...]:
        root = self._root_dir / "recipe_collections"
        if not root.exists() and not _is_link(root):
            return ()
        self._require_safe_directory(root)
        values: list[PortableRecipeCollectionRevisionV1] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if _is_link(path) or not path.is_dir():
                raise PortableRecipeStoreError(
                    "unexpected portable Recipe Collection persistence shape"
                )
            self._validate_collection_id(path.name)
            values.extend(self._preflight_collection_directory(path))
        return tuple(values)

    def _preflight_collection_directory(
        self, collection_dir: Path
    ) -> tuple[PortableRecipeCollectionRevisionV1, ...]:
        self._require_safe_directory(collection_dir)
        children = {item.name for item in collection_dir.iterdir()}
        if children != {"head.json", "revisions"}:
            raise PortableRecipeStoreError(
                "unexpected portable Recipe Collection persistence shape"
            )
        head = self._load_model(
            collection_dir / "head.json", PortableRecipeCollectionHeadV1
        )
        if head.collection_id != collection_dir.name:
            raise PortableRecipeStoreError(
                "Collection head identity does not match path"
            )
        revisions_dir = collection_dir / "revisions"
        self._require_safe_directory(revisions_dir)
        paths = tuple(sorted(revisions_dir.iterdir(), key=lambda item: item.name))
        if not paths:
            raise PortableRecipeStoreError(
                "portable Recipe Collection has no valid revisions"
            )
        revisions: list[PortableRecipeCollectionRevisionV1] = []
        for path in paths:
            if _is_link(path) or not path.is_file() or path.suffix != ".json":
                raise PortableRecipeStoreError(
                    "unexpected portable Recipe Collection revision shape"
                )
            self._validate_sha(path.stem, "revision_id")
            revision = self.load_collection_revision(
                collection_dir.name, path.stem
            )
            revisions.append(revision)
        if head.revision_id not in {item.revision_id for item in revisions}:
            raise PortableRecipeStoreError(
                "portable Recipe Collection head revision is missing"
            )
        return tuple(revisions)

    def _provenance_paths_for_deletion(
        self, recipe_id: str, provenance_dir: Path
    ) -> tuple[Path, ...]:
        if not provenance_dir.exists() and not _is_link(provenance_dir):
            return ()
        self._require_safe_directory(provenance_dir)
        paths = tuple(sorted(provenance_dir.iterdir(), key=lambda item: item.name))
        for path in paths:
            if _is_link(path) or not path.is_file() or path.suffix != ".json":
                raise PortableRecipeStoreError(
                    "unexpected portable Recipe provenance persistence shape"
                )
            if path.name == "metadata.json":
                value = self._load_model(path, PortableRecipePersistenceMetadataV1)
                if value.recipe_id != recipe_id:
                    raise PortableRecipeStoreError(
                        "Recipe persistence metadata identity does not match path"
                    )
            else:
                self._validate_sha(path.stem, "provenance_id")
                value = self._load_model(path, PortableRecipeProvenanceV1)
                if value.recipe_id != recipe_id or value.provenance_id != path.stem:
                    raise PortableRecipeStoreError(
                        "provenance identity does not match path"
                    )
        return paths

    def _remove_empty_directory(self, path: Path) -> None:
        if not path.exists() and not _is_link(path):
            return
        self._require_safe_directory(path)
        if not any(path.iterdir()):
            path.rmdir()

    def _validate_collection_members(
        self, root_recipe_ids: Sequence[str], member_recipe_ids: Sequence[str]
    ) -> None:
        plan = PortableRecipeGraphPlanner(self.load_recipe).plan(root_recipe_ids)
        if tuple(member_recipe_ids) != plan.member_recipe_ids:
            raise PortableRecipeStoreError(
                "Collection members must match the canonical graph planner result"
            )

    def _validate_collection_request_members(
        self, root_recipe_ids: Sequence[str], member_recipe_ids: Sequence[str]
    ) -> tuple[str, ...]:
        requested_members = tuple(member_recipe_ids)
        plan = PortableRecipeGraphPlanner(self.load_recipe).plan(root_recipe_ids)
        if (
            len(requested_members) != len(plan.member_recipe_ids)
            or frozenset(requested_members) != frozenset(plan.member_recipe_ids)
        ):
            raise PortableRecipeStoreError(
                "Collection members must match the canonical graph planner result"
            )
        return plan.member_recipe_ids

    def _collection_semantic_key(
        self, root_recipe_ids: Sequence[str], member_recipe_ids: Sequence[str]
    ) -> frozenset[ObjectSemanticKey]:
        del root_recipe_ids
        return frozenset(
            self.inspect_recipe_semantics(recipe_id).semantic_key
            for recipe_id in member_recipe_ids
        )

    def _find_equivalent_current_collection(
        self, root_recipe_ids: Sequence[str], member_recipe_ids: Sequence[str]
    ) -> PortableRecipeCollectionRevisionV1 | None:
        requested_key = self._collection_semantic_key(
            root_recipe_ids, member_recipe_ids
        )
        candidates: list[
            tuple[datetime, str, PortableRecipeCollectionRevisionV1]
        ] = []
        for summary in self.list_collection_summaries():
            if not summary.valid or summary.created_at_utc is None:
                continue
            try:
                revision = self.load_collection(summary.collection_id)
            except (FileNotFoundError, PortableRecipeStoreError):
                continue
            if self._collection_semantic_key(
                revision.root_recipe_ids, revision.member_recipe_ids
            ) == requested_key:
                candidates.append(
                    (summary.created_at_utc, summary.collection_id, revision)
                )
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0], item[1]))[2]

    def _recipe_path(self, recipe_id: str) -> Path:
        self._validate_sha(recipe_id, "recipe_id")
        return self._root_dir / "recipes" / f"{recipe_id}.json"

    def _provenance_path(self, recipe_id: str, provenance_id: str) -> Path:
        self._validate_sha(recipe_id, "recipe_id")
        self._validate_sha(provenance_id, "provenance_id")
        return self._root_dir / "recipe_provenance" / recipe_id / f"{provenance_id}.json"

    def _persistence_metadata_path(self, recipe_id: str) -> Path:
        self._validate_sha(recipe_id, "recipe_id")
        return self._root_dir / "recipe_provenance" / recipe_id / "metadata.json"

    def _collection_dir(self, collection_id: str) -> Path:
        self._validate_collection_id(collection_id)
        return self._root_dir / "recipe_collections" / collection_id

    def _revision_path(self, collection_id: str, revision_id: str) -> Path:
        self._validate_sha(revision_id, "revision_id")
        return self._collection_dir(collection_id) / "revisions" / f"{revision_id}.json"

    def _new_collection_id(self) -> str:
        raw = self._collection_id_factory()
        if not isinstance(raw, str):
            raise PortableRecipeStoreError("collection_id_factory must return text")
        collection_id = raw if raw.startswith("prc_") else f"prc_{raw}"
        self._validate_collection_id(collection_id)
        path = self._collection_dir(collection_id)
        if path.exists():
            raise PortableRecipeIdentityCollisionError(
                f"portable Recipe Collection already exists: {collection_id}"
            )
        return collection_id

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise PortableRecipeStoreError("clock must return timezone-aware UTC")
        if value.utcoffset().total_seconds() != 0:
            raise PortableRecipeStoreError("clock must return UTC")
        return value.astimezone(UTC)

    def _load_model(self, path: Path, model):
        self._require_safe_file(path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortableRecipeStoreError("invalid portable Recipe JSON") from exc
        if not isinstance(payload, dict):
            raise PortableRecipeStoreError("portable Recipe JSON root must be an object")
        try:
            value = model.from_dict(payload)
            canonical = value.canonical_json_bytes()
        except PortableRecipeStoreError:
            raise
        except PortableRecipeValidationError as exc:
            raise PortableRecipeStoreError(
                "portable Recipe JSON does not match its persisted schema"
            ) from exc
        if raw != canonical:
            raise PortableRecipeStoreError("portable Recipe JSON bytes are not canonical")
        return value

    def _write_immutable(self, path: Path, content: bytes) -> None:
        if path.exists():
            self._require_safe_file(path)
            if path.read_bytes() == content:
                return
            raise PortableRecipeIdentityCollisionError(
                f"portable Recipe identity collision: {path.name}"
            )
        self._atomic_write(path, content)

    def _write_mutable(self, path: Path, content: bytes) -> None:
        if path.exists():
            self._require_safe_file(path)
            if path.read_bytes() == content:
                return
        self._atomic_write(path, content)

    def _atomic_write(self, path: Path, content: bytes) -> None:
        self._ensure_write_directory(path.parent)
        self._require_contained(path)
        if path.exists() and _is_link(path):
            raise PortableRecipeStoreError("portable Recipe path must not be a link")
        temporary = path.parent / f".{uuid4().hex[:8]}.tmp"
        self._require_contained(temporary)
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _ensure_write_directory(self, directory: Path) -> None:
        self._require_contained(directory)
        if self._root_dir.exists():
            self._require_safe_directory(self._root_dir)
        directory.mkdir(parents=True, exist_ok=True)
        current = self._root_dir
        self._require_safe_directory(current)
        relative = directory.relative_to(self._root_dir)
        for part in relative.parts:
            current = current / part
            self._require_safe_directory(current)

    def _require_safe_file(self, path: Path) -> None:
        if _is_link(path):
            raise PortableRecipeStoreError(
                "portable Recipe path must not be a link"
            )
        self._require_contained(path)
        if _is_link(path.parent):
            raise PortableRecipeStoreError("portable Recipe directory must not be a link")
        if not path.exists() and not _is_link(path):
            if self._root_dir.exists():
                self._require_safe_directory(self._root_dir)
            raise FileNotFoundError(path)
        self._require_safe_directory(path.parent)
        if _is_link(path):
            raise PortableRecipeStoreError("portable Recipe path must not be a link")
        if not path.is_file():
            raise FileNotFoundError(path)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(self._root_dir.resolve(strict=True))
        except ValueError as exc:
            raise PortableRecipeStoreError("portable Recipe path escapes root") from exc

    def _require_root_if_present(self) -> None:
        if self._root_dir.exists() or _is_link(self._root_dir):
            self._require_safe_directory(self._root_dir)

    def _require_safe_directory(self, path: Path) -> None:
        self._require_contained(path)
        if _is_link(path):
            raise PortableRecipeStoreError("portable Recipe directory must not be a link")
        if not path.is_dir():
            raise PortableRecipeStoreError("portable Recipe storage path must be a directory")
        current = path
        while current != self._root_dir:
            if _is_link(current):
                raise PortableRecipeStoreError("portable Recipe directory must not be a link")
            current = current.parent
        if _is_link(self._root_dir):
            raise PortableRecipeStoreError("portable Recipe root must not be a link")

    def _require_contained(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(self._root_dir.resolve(strict=False))
        except ValueError as exc:
            raise PortableRecipeStoreError("portable Recipe path escapes root") from exc

    @staticmethod
    def _validate_sha(value: object, name: str) -> None:
        if not isinstance(value, str) or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value
        ):
            raise PortableRecipeStoreError(f"{name} must be a lowercase SHA-256")

    @staticmethod
    def _validate_collection_id(value: object) -> None:
        if not isinstance(value, str) or not value.startswith("prc_") or len(value) != 36 or any(
            char not in "0123456789abcdef" for char in value[4:]
        ):
            raise PortableRecipeStoreError("collection_id must match prc_<32 lowercase hex>")


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


__all__ = (
    "PortableRecipeCollectionSummary",
    "PortableRecipeIdentityCollisionError",
    "PortableRecipeStore",
    "PortableRecipeStoreError",
    "PortableRecipeSummary",
)
