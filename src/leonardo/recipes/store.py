"""Hardened global persistence for portable Recipes and Collections."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .models import (
    PortableRecipeCollectionHeadV1,
    PortableRecipeCollectionRevisionV1,
    PortableRecipeProvenanceV1,
    PortableRecipeV1,
    PortableRecipeValidationError,
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
            self._write_immutable(path, recipe.canonical_json_bytes())
        return recipe

    def load_recipe(self, recipe_id: str) -> PortableRecipeV1:
        path = self._recipe_path(recipe_id)
        with self._lock:
            return self._load_model(path, PortableRecipeV1)

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
            collection_id = self._new_collection_id()
            self._validate_collection_members(root_recipe_ids, member_recipe_ids)
            created_at = self._now()
            revision = PortableRecipeCollectionRevisionV1.build(
                collection_id=collection_id,
                display_name=display_name,
                description=description,
                root_recipe_ids=root_recipe_ids,
                member_recipe_ids=member_recipe_ids,
                previous_revision_id=None,
                created_at_utc=created_at,
            )
            self._publish_revision(revision, updated_at_utc=created_at)
            return revision

    def update_collection(
        self,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: Sequence[str],
        member_recipe_ids: Sequence[str],
    ) -> PortableRecipeCollectionRevisionV1:
        with self._lock:
            current = self.load_collection(collection_id)
            self._validate_collection_members(root_recipe_ids, member_recipe_ids)
            created_at = self._now()
            revision = PortableRecipeCollectionRevisionV1.build(
                collection_id=collection_id,
                display_name=display_name,
                description=description,
                root_recipe_ids=root_recipe_ids,
                member_recipe_ids=member_recipe_ids,
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

    def _validate_collection_members(
        self, root_recipe_ids: Sequence[str], member_recipe_ids: Sequence[str]
    ) -> None:
        plan = PortableRecipeGraphPlanner(self.load_recipe).plan(root_recipe_ids)
        if tuple(member_recipe_ids) != plan.member_recipe_ids:
            raise PortableRecipeStoreError(
                "Collection members must match the canonical graph planner result"
            )

    def _recipe_path(self, recipe_id: str) -> Path:
        self._validate_sha(recipe_id, "recipe_id")
        return self._root_dir / "recipes" / f"{recipe_id}.json"

    def _provenance_path(self, recipe_id: str, provenance_id: str) -> Path:
        self._validate_sha(recipe_id, "recipe_id")
        self._validate_sha(provenance_id, "provenance_id")
        return self._root_dir / "recipe_provenance" / recipe_id / f"{provenance_id}.json"

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
