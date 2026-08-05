"""Atomic persistence for Data Manager Collections, Seeds, and Databases."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .creation_models import (
    ArtifactCollectionHeadV1,
    ArtifactCollectionRevisionV1,
    DatabaseDefinitionV1,
    DatabaseHeadV1,
    DatabaseRevisionManifestV1,
    DatabaseSeedV1,
    DataManagerCreationError,
    LoadedDatabaseRevision,
    canonical_json_bytes,
)


class DataManagerCreationStoreError(DataManagerCreationError):
    """Raised when Data Manager creation persistence cannot be trusted."""


class DataManagerCreationIdentityCollision(DataManagerCreationStoreError):
    """Raised when an immutable identity already contains different bytes."""


class DataManagerCreationStore:
    """Own the three configured Data Manager creation persistence roots."""

    def __init__(
        self,
        root_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root = Path(root_dir).absolute()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: uuid4().hex)
        self._lock = RLock()

    @property
    def root_dir(self) -> Path:
        return self._root

    def new_collection_id(self) -> str:
        return f"ac_{self._token()}"

    def new_seed_id(self) -> str:
        return f"seed_{self._token()}"

    def new_database_id(self) -> str:
        return f"db_{self._token()}"

    def save_collection_revision(
        self,
        revision: ArtifactCollectionRevisionV1,
        *,
        expected_head_revision_id: str | None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(revision, ArtifactCollectionRevisionV1):
            raise TypeError("revision must be an ArtifactCollectionRevisionV1")
        with self._lock:
            collection_dir = self._collection_dir(revision.collection_id)
            current = self._load_optional_collection_head(revision.collection_id)
            current_id = None if current is None else current.revision_id
            if current_id != expected_head_revision_id:
                raise DataManagerCreationStoreError("Artifact Collection head changed")
            if revision.previous_revision_id != current_id:
                raise DataManagerCreationStoreError("previous Collection revision is not current")
            revisions_dir = collection_dir / "revisions"
            revision_path = revisions_dir / f"{revision.revision_id}.json"
            revision_existed = revision_path.exists()
            head_path = collection_dir / "head.json"
            previous_head = (
                self._read_safe_file(head_path) if head_path.exists() else None
            )
            self._write_immutable(revision_path, revision.canonical_json_bytes())
            head = ArtifactCollectionHeadV1(
                revision.collection_id, revision.revision_id, self._clock()
            )
            try:
                self._write_atomic(head_path, canonical_json_bytes(head.to_dict()))
            except Exception:
                self._restore_atomic_target(head_path, previous_head)
                if not revision_existed and revision_path.exists():
                    revision_path.unlink()
                if revisions_dir.exists() and not any(revisions_dir.iterdir()):
                    revisions_dir.rmdir()
                if collection_dir.exists() and not any(collection_dir.iterdir()):
                    collection_dir.rmdir()
                raise
        return revision

    def list_collection_ids(self) -> tuple[str, ...]:
        root = self._root / "artifact_collections"
        with self._lock:
            return self._safe_child_directories(root, prefix="ac_")

    def list_collection_revisions(
        self, collection_id: str
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        directory = self._collection_dir(collection_id) / "revisions"
        with self._lock:
            if not directory.exists():
                return ()
            self._require_safe_directory(directory)
            revisions = tuple(
                self._load_canonical(path, ArtifactCollectionRevisionV1.from_dict)
                for path in sorted(directory.glob("*.json"))
            )
            return tuple(sorted(revisions, key=lambda item: (item.revised_at_utc, item.revision_id)))

    def load_collection_head(self, collection_id: str) -> ArtifactCollectionHeadV1:
        with self._lock:
            head = self._load_optional_collection_head(collection_id)
            if head is None:
                raise FileNotFoundError(f"Artifact Collection not found: {collection_id}")
            return head

    def load_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionRevisionV1:
        with self._lock:
            exact = revision_id or self.load_collection_head(collection_id).revision_id
            path = self._collection_dir(collection_id) / "revisions" / f"{exact}.json"
            revision = self._load_canonical(path, ArtifactCollectionRevisionV1.from_dict)
            if revision.collection_id != collection_id or revision.revision_id != exact:
                raise DataManagerCreationStoreError("Artifact Collection identity disagrees with path")
            return revision

    def save_seed(self, seed: DatabaseSeedV1) -> DatabaseSeedV1:
        if not isinstance(seed, DatabaseSeedV1):
            raise TypeError("seed must be a DatabaseSeedV1")
        with self._lock:
            self._write_immutable(self._seed_path(seed.seed_id), seed.canonical_json_bytes())
        return seed

    def list_seeds(self) -> tuple[DatabaseSeedV1, ...]:
        root = self._root / "database_seeds"
        with self._lock:
            if not root.exists():
                return ()
            self._require_safe_directory(root)
            values = tuple(
                self._load_canonical(path, DatabaseSeedV1.from_dict)
                for path in sorted(root.glob("seed_*.json"))
            )
            return tuple(sorted(values, key=lambda item: (item.created_at_utc, item.seed_id)))

    def load_seed(self, seed_id: str) -> DatabaseSeedV1:
        with self._lock:
            seed = self._load_canonical(self._seed_path(seed_id), DatabaseSeedV1.from_dict)
            if seed.seed_id != seed_id:
                raise DataManagerCreationStoreError("Database Seed identity disagrees with path")
            return seed

    def delete_seed(self, seed_id: str) -> DatabaseSeedV1:
        with self._lock:
            seed = self.load_seed(seed_id)
            for database_id in self.list_database_ids():
                for revision in self.list_database_revisions(database_id):
                    if revision.seed_id == seed_id:
                        raise DataManagerCreationStoreError("Database Seed is referenced by a Database")
            self._seed_path(seed_id).unlink()
            return seed

    def publish_database_revision(
        self,
        definition: DatabaseDefinitionV1,
        manifest: DatabaseRevisionManifestV1,
        values_csv: bytes,
        *,
        expected_head_revision_id: str | None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseRevisionManifestV1:
        if not isinstance(definition, DatabaseDefinitionV1):
            raise TypeError("definition must be a DatabaseDefinitionV1")
        if not isinstance(manifest, DatabaseRevisionManifestV1):
            raise TypeError("manifest must be a DatabaseRevisionManifestV1")
        if definition.database_id != manifest.database_id:
            raise DataManagerCreationStoreError(
                "Database definition and revision identities differ"
            )
        if not isinstance(values_csv, bytes):
            raise TypeError("values_csv must be bytes")
        with self._lock:
            database_dir = self._database_dir(manifest.database_id)
            current = self._load_optional_database_head(manifest.database_id)
            current_id = None if current is None else current.revision_id
            if current_id != expected_head_revision_id:
                raise DataManagerCreationStoreError("Database head changed")
            if manifest.previous_revision_id != current_id:
                raise DataManagerCreationStoreError("previous Database revision is not current")
            definition_path = database_dir / "definition.json"
            definition_existed = definition_path.exists()
            if current is None:
                self._write_immutable(
                    definition_path, definition.canonical_json_bytes()
                )
            elif self.load_database_definition(manifest.database_id) != definition:
                raise DataManagerCreationStoreError("Database definition is immutable")
            revisions_dir = database_dir / "revisions"
            final_dir = revisions_dir / manifest.revision_id
            revision_existed = final_dir.exists()
            if final_dir.exists():
                loaded = self.load_database_revision(manifest.database_id, manifest.revision_id)
                if loaded.manifest != manifest or loaded.values_csv != values_csv:
                    raise DataManagerCreationIdentityCollision("Database revision identity collision")
            else:
                self._ensure_directory(revisions_dir)
                temporary = revisions_dir / f".tmp-{self._token()}"
                try:
                    temporary.mkdir()
                    (temporary / "manifest.json").write_bytes(manifest.canonical_json_bytes())
                    (temporary / "values.csv").write_bytes(values_csv)
                    self._flush_file(temporary / "manifest.json")
                    self._flush_file(temporary / "values.csv")
                    if before_publish is not None:
                        before_publish()
                    os.rename(temporary, final_dir)
                except FileExistsError as exc:
                    raise DataManagerCreationIdentityCollision(
                        "Database revision was published concurrently"
                    ) from exc
                finally:
                    if temporary.exists():
                        for child in temporary.iterdir():
                            child.unlink()
                        temporary.rmdir()
                    if not final_dir.exists() and revisions_dir.exists() and not any(revisions_dir.iterdir()):
                        revisions_dir.rmdir()
                    if (
                        database_dir.exists()
                        and not final_dir.exists()
                        and not (database_dir / "head.json").exists()
                    ):
                        definition_path = database_dir / "definition.json"
                        if definition_path.exists():
                            definition_path.unlink()
                    if database_dir.exists() and not any(database_dir.iterdir()):
                        database_dir.rmdir()
            head = DatabaseHeadV1(manifest.database_id, manifest.revision_id, self._clock())
            head_path = database_dir / "head.json"
            previous_head = (
                self._read_safe_file(head_path) if head_path.exists() else None
            )
            try:
                self._write_atomic(head_path, canonical_json_bytes(head.to_dict()))
            except Exception:
                self._restore_atomic_target(head_path, previous_head)
                if not revision_existed and final_dir.exists():
                    for child in final_dir.iterdir():
                        child.unlink()
                    final_dir.rmdir()
                if not definition_existed and definition_path.exists():
                    definition_path.unlink()
                if revisions_dir.exists() and not any(revisions_dir.iterdir()):
                    revisions_dir.rmdir()
                if database_dir.exists() and not any(database_dir.iterdir()):
                    database_dir.rmdir()
                raise
        return manifest

    def list_database_ids(self) -> tuple[str, ...]:
        with self._lock:
            return self._safe_child_directories(self._root / "databases", prefix="db_")

    def load_database_definition(self, database_id: str) -> DatabaseDefinitionV1:
        with self._lock:
            definition = self._load_canonical(
                self._database_dir(database_id) / "definition.json",
                DatabaseDefinitionV1.from_dict,
            )
            if definition.database_id != database_id:
                raise DataManagerCreationStoreError(
                    "Database definition identity disagrees with path"
                )
            return definition

    def list_database_revisions(
        self, database_id: str
    ) -> tuple[DatabaseRevisionManifestV1, ...]:
        revisions = self._database_dir(database_id) / "revisions"
        with self._lock:
            if not revisions.exists():
                return ()
            self._require_safe_directory(revisions)
            values = tuple(
                self.load_database_revision(database_id, child.name).manifest
                for child in sorted(revisions.iterdir(), key=lambda item: item.name)
                if child.is_dir()
            )
            return tuple(sorted(values, key=lambda item: (item.created_at_utc, item.revision_id)))

    def load_database_revision(
        self, database_id: str, revision_id: str | None = None
    ) -> LoadedDatabaseRevision:
        with self._lock:
            exact = revision_id or self.load_database_head(database_id).revision_id
            directory = self._database_dir(database_id) / "revisions" / exact
            self._require_safe_directory(directory)
            children = {item.name for item in directory.iterdir()}
            if children != {"manifest.json", "values.csv"}:
                raise DataManagerCreationStoreError("Database revision payload files are not exact")
            manifest = self._load_canonical(
                directory / "manifest.json", DatabaseRevisionManifestV1.from_dict
            )
            values = self._read_safe_file(directory / "values.csv")
            if manifest.database_id != database_id or manifest.revision_id != exact:
                raise DataManagerCreationStoreError("Database revision identity disagrees with path")
            return LoadedDatabaseRevision(manifest, values)

    def load_database_head(self, database_id: str) -> DatabaseHeadV1:
        with self._lock:
            head = self._load_optional_database_head(database_id)
            if head is None:
                raise FileNotFoundError(f"Database not found: {database_id}")
            return head

    def _load_optional_collection_head(self, collection_id: str) -> ArtifactCollectionHeadV1 | None:
        path = self._collection_dir(collection_id) / "head.json"
        if not path.exists():
            return None
        head = self._load_canonical(path, ArtifactCollectionHeadV1.from_dict)
        if head.collection_id != collection_id:
            raise DataManagerCreationStoreError("Artifact Collection head identity disagrees")
        return head

    def _load_optional_database_head(self, database_id: str) -> DatabaseHeadV1 | None:
        path = self._database_dir(database_id) / "head.json"
        if not path.exists():
            return None
        head = self._load_canonical(path, DatabaseHeadV1.from_dict)
        if head.database_id != database_id:
            raise DataManagerCreationStoreError("Database head identity disagrees")
        return head

    def _collection_dir(self, collection_id: str) -> Path:
        self._require_id(collection_id, "ac_")
        return self._root / "artifact_collections" / collection_id

    def _seed_path(self, seed_id: str) -> Path:
        self._require_id(seed_id, "seed_")
        return self._root / "database_seeds" / f"{seed_id}.json"

    def _database_dir(self, database_id: str) -> Path:
        self._require_id(database_id, "db_")
        return self._root / "databases" / database_id

    @staticmethod
    def _require_id(value: object, prefix: str) -> None:
        if not isinstance(value, str) or not value.startswith(prefix) or len(value) != len(prefix) + 32:
            raise DataManagerCreationStoreError("canonical Data Manager identity is invalid")
        try:
            int(value[len(prefix):], 16)
        except ValueError as exc:
            raise DataManagerCreationStoreError("canonical Data Manager identity is invalid") from exc

    def _token(self) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or len(token) != 32:
            raise DataManagerCreationStoreError("identity factory must return 32 lowercase hex")
        try:
            int(token, 16)
        except ValueError as exc:
            raise DataManagerCreationStoreError("identity factory must return 32 lowercase hex") from exc
        return token.lower()

    def _safe_child_directories(self, root: Path, *, prefix: str) -> tuple[str, ...]:
        if not root.exists():
            return ()
        self._require_safe_directory(root)
        result: list[str] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if path.name.startswith(prefix):
                self._require_safe_directory(path)
                result.append(path.name)
        return tuple(result)

    def _load_canonical(self, path: Path, factory):
        raw = self._read_safe_file(path)
        try:
            data = json.loads(raw.decode("utf-8"))
            value = factory(data)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DataManagerCreationStoreError(f"invalid persisted payload: {path.name}") from exc
        encoder = getattr(value, "canonical_json_bytes", None)
        canonical = encoder() if callable(encoder) else canonical_json_bytes(value.to_dict())
        if raw != canonical:
            raise DataManagerCreationStoreError(f"noncanonical persisted bytes: {path.name}")
        return value

    def _read_safe_file(self, path: Path) -> bytes:
        self._require_under_root(path)
        if path.is_symlink() or not path.is_file():
            raise DataManagerCreationStoreError(f"unsafe or missing persistence file: {path.name}")
        return path.read_bytes()

    def _write_immutable(self, path: Path, payload: bytes) -> None:
        if path.exists():
            if self._read_safe_file(path) != payload:
                raise DataManagerCreationIdentityCollision(f"identity collision: {path.name}")
            return
        self._ensure_directory(path.parent)
        temporary = path.parent / f".tmp-{self._token()}"
        try:
            temporary.write_bytes(payload)
            self._flush_file(temporary)
            os.link(temporary, path)
        except FileExistsError:
            if self._read_safe_file(path) != payload:
                raise DataManagerCreationIdentityCollision(f"identity collision: {path.name}")
        finally:
            if temporary.exists():
                temporary.unlink()

    def _write_atomic(self, path: Path, payload: bytes) -> None:
        self._ensure_directory(path.parent)
        temporary = path.parent / f".tmp-{self._token()}"
        try:
            temporary.write_bytes(payload)
            self._flush_file(temporary)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _restore_atomic_target(self, path: Path, payload: bytes | None) -> None:
        if payload is None:
            if path.exists():
                self._read_safe_file(path)
                path.unlink()
            return
        if path.exists() and self._read_safe_file(path) == payload:
            return
        self._ensure_directory(path.parent)
        temporary = path.parent / f".tmp-{self._token()}"
        try:
            temporary.write_bytes(payload)
            self._flush_file(temporary)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _ensure_directory(self, path: Path) -> None:
        self._require_under_root(path)
        relative = path.relative_to(self._root)
        current = self._root
        if current.exists():
            self._require_safe_directory(current)
        else:
            current.mkdir()
        for part in relative.parts:
            current = current / part
            if current.exists():
                self._require_safe_directory(current)
            else:
                current.mkdir()

    def _require_safe_directory(self, path: Path) -> None:
        self._require_under_root(path)
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise DataManagerCreationStoreError(f"persistence directory not found: {path.name}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise DataManagerCreationStoreError(f"unsafe persistence directory: {path.name}")
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise DataManagerCreationStoreError(f"reparse-point persistence directory: {path.name}")

    def _require_under_root(self, path: Path) -> None:
        try:
            Path(path).absolute().relative_to(self._root)
        except ValueError as exc:
            raise DataManagerCreationStoreError("persistence path escapes Data Manager root") from exc

    @staticmethod
    def _flush_file(path: Path) -> None:
        with path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
