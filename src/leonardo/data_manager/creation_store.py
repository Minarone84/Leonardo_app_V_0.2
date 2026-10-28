"""Atomic persistence for Data Manager Collections, Seeds, and Databases."""

from __future__ import annotations

import json
import os
import stat
import csv
import io
import shutil
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .creation_models import (
    ArtifactCollectionHeadV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    DatabaseDefinitionV1,
    DatabaseHeadV1,
    DatabaseRevisionManifest,
    DatabaseRevisionManifestV1,
    artifact_collection_revision_from_dict,
    database_collection_references,
    database_revision_from_dict,
    DatabaseSeedV1,
    DatabaseSeedV2,
    DataManagerCreationError,
    LoadedDatabaseRevision,
    canonical_json_bytes,
)

from .utc_classification_snapshot import _decode_snapshot


class DataManagerCreationStoreError(DataManagerCreationError):
    """Raised when Data Manager creation persistence cannot be trusted."""


class DataManagerCreationIdentityCollision(DataManagerCreationStoreError):
    """Raised when an immutable identity already contains different bytes."""


def _snapshot_rows(values: bytes, *, columns=None, row_count=None, first=None, last=None, nullable_columns=()):
    try:
        rows = list(csv.reader(io.StringIO(values.decode("utf-8"), newline=""), strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise DataManagerCreationStoreError("snapshot CSV is invalid") from exc
    if len(rows) < 2:
        raise DataManagerCreationStoreError("snapshot has no rows")
    header, data = tuple(rows[0]), rows[1:]
    if not header or header[0] != "ts_ms" or len(header) != len(set(header)):
        raise DataManagerCreationStoreError("snapshot header is invalid")
    if columns is not None and (set(header) != set(columns) or len(header) != len(columns)):
        raise DataManagerCreationStoreError("snapshot header disagrees with manifest")
    timestamps = []
    for row in data:
        if len(row) != len(header):
            raise DataManagerCreationStoreError("snapshot row width is invalid")
        try:
            timestamp = int(row[0])
        except ValueError as exc:
            raise DataManagerCreationStoreError("snapshot timestamp is invalid") from exc
        if str(timestamp) != row[0] or timestamp < 0 or (timestamps and timestamp <= timestamps[-1]):
            raise DataManagerCreationStoreError("snapshot timestamps must be canonical, unique and increasing")
        timestamps.append(timestamp)
        for name, token in zip(header[1:], row[1:], strict=True):
            if token == "" and name in nullable_columns:
                continue
            if not token.strip() or token.lower() in {"nan", "inf", "-inf", "+inf", "infinity", "null"}:
                raise DataManagerCreationStoreError("snapshot contains missing or nonfinite values")
            if name in {"open", "high", "low", "close", "volume"}:
                try:
                    value = Decimal(token)
                except InvalidOperation as exc:
                    raise DataManagerCreationStoreError("snapshot OHLCV value is invalid") from exc
                if not value.is_finite() or (name == "volume" and value < 0):
                    raise DataManagerCreationStoreError("snapshot OHLCV value is invalid")
    if row_count is not None and len(data) != row_count:
        raise DataManagerCreationStoreError("snapshot row count disagrees with manifest")
    if (first is not None and timestamps[0] != first) or (last is not None and timestamps[-1] != last):
        raise DataManagerCreationStoreError("snapshot range disagrees with manifest")
    return header, data, tuple(timestamps)


def _database_nullable_columns(manifest):
    if isinstance(manifest, DatabaseRevisionManifestV1):
        return tuple(
            target for source, target in manifest.column_mapping.items()
            if source not in {"ts_ms", "open", "high", "low", "close", "volume"}
        )
    return tuple(output.column_name for output in manifest.selected_outputs)


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
        self._collection_semantic_key_resolver: (
            Callable[[object, Sequence[str], Sequence[ArtifactCollectionOutputV1]], tuple[object, ...]]
            | None
        ) = None

    @property
    def root_dir(self) -> Path:
        return self._root

    def new_collection_id(self) -> str:
        return f"ac_{self._token()}"

    def set_collection_semantic_key_resolver(
        self,
        resolver: Callable[
            [object, Sequence[str], Sequence[ArtifactCollectionOutputV1]],
            tuple[object, ...],
        ],
    ) -> None:
        if not callable(resolver):
            raise TypeError("resolver must be callable")
        self._collection_semantic_key_resolver = resolver

    def new_seed_id(self) -> str:
        return f"seed_{self._token()}"

    def new_database_id(self) -> str:
        return f"db_{self._token()}"

    def save_collection_revision(
        self,
        revision: ArtifactCollectionRevisionV1,
        *,
        expected_head_revision_id: str | None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(revision, ArtifactCollectionRevisionV1):
            raise TypeError("revision must be an ArtifactCollectionRevisionV1")
        with self._lock:
            current = self._load_optional_collection_head(revision.collection_id)
            current_id = None if current is None else current.revision_id
            if current_id != expected_head_revision_id:
                raise DataManagerCreationStoreError("Artifact Collection head changed")
            if revision.previous_revision_id != current_id:
                raise DataManagerCreationStoreError("previous Collection revision is not current")
            winner = self._equivalent_collection(revision)
            if winner is not None and winner.collection_id != revision.collection_id:
                return winner
            if before_publish is not None:
                before_publish()
            self._publish_collection_revision(revision)
        return revision

    def create_collection_revision(
        self,
        *,
        market_id: object,
        source_ohlcv: object,
        root_logical_artifact_ids: Sequence[str],
        support_logical_artifact_ids: Sequence[str],
        members: Sequence[ArtifactCollectionMemberV1],
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
        presentation_order: Sequence[str],
        revision_factory: Callable[[str], ArtifactCollectionRevisionV1],
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        requested_key = self._collection_semantic_key(
            market_id=market_id,
            source_ohlcv=source_ohlcv,
            root_logical_artifact_ids=root_logical_artifact_ids,
            support_logical_artifact_ids=support_logical_artifact_ids,
            members=members,
            selected_outputs=selected_outputs,
            presentation_order=presentation_order,
        )
        with self._lock:
            winner = self._equivalent_collection_key(requested_key)
            if winner is not None:
                return winner
            collection_id = self.new_collection_id()
            revision = revision_factory(collection_id)
            if not isinstance(revision, ArtifactCollectionRevisionV1):
                raise TypeError(
                    "revision_factory must return an ArtifactCollectionRevisionV1"
                )
            if revision.collection_id != collection_id:
                raise DataManagerCreationStoreError(
                    "Artifact Collection factory returned a different identity"
                )
            if revision.previous_revision_id is not None:
                raise DataManagerCreationStoreError(
                    "new Artifact Collection cannot have a previous revision"
                )
            if self._collection_semantic_key_from_revision(revision) != requested_key:
                raise DataManagerCreationStoreError(
                    "Artifact Collection factory changed requested semantics"
                )
            if before_publish is not None:
                before_publish()
            self._publish_collection_revision(revision)
            return revision

    def find_equivalent_collection(
        self,
        *,
        market_id: object,
        source_ohlcv: object,
        root_logical_artifact_ids: Sequence[str],
        support_logical_artifact_ids: Sequence[str],
        members: Sequence[ArtifactCollectionMemberV1],
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
        presentation_order: Sequence[str],
    ) -> ArtifactCollectionRevisionV1 | None:
        """Return the current oldest semantic winner without publishing."""

        requested_key = self._collection_semantic_key(
            market_id=market_id,
            source_ohlcv=source_ohlcv,
            root_logical_artifact_ids=root_logical_artifact_ids,
            support_logical_artifact_ids=support_logical_artifact_ids,
            members=members,
            selected_outputs=selected_outputs,
            presentation_order=presentation_order,
        )
        with self._lock:
            return self._equivalent_collection_key(requested_key)

    def _publish_collection_revision(
        self, revision: ArtifactCollectionRevisionV1
    ) -> None:
        collection_dir = self._collection_dir(revision.collection_id)
        revisions_dir = collection_dir / "revisions"
        revision_path = revisions_dir / f"{revision.revision_id}.json"
        revision_existed = revision_path.exists()
        head_path = collection_dir / "head.json"
        previous_head = self._read_safe_file(head_path) if head_path.exists() else None
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

    def _equivalent_collection(
        self, revision: ArtifactCollectionRevisionV1
    ) -> ArtifactCollectionRevisionV1 | None:
        return self._equivalent_collection_key(
            self._collection_semantic_key_from_revision(revision)
        )

    def _equivalent_collection_key(
        self, requested_key: tuple[object, ...]
    ) -> ArtifactCollectionRevisionV1 | None:
        candidates: list[ArtifactCollectionRevisionV1] = []
        for collection_id in self.list_collection_ids():
            try:
                current = self.load_collection(collection_id)
            except (DataManagerCreationStoreError, FileNotFoundError):
                continue
            if (
                current.validation_state == "valid"
                and self._collection_semantic_key_from_revision(current)
                == requested_key
            ):
                candidates.append(current)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (item.created_at_utc, item.collection_id),
        )

    def _collection_semantic_key_from_revision(
        self, revision: ArtifactCollectionRevisionV1
    ) -> tuple[object, ...]:
        return self._collection_semantic_key(
            market_id=revision.market_id,
            source_ohlcv=revision.source_ohlcv,
            root_logical_artifact_ids=revision.root_logical_artifact_ids,
            support_logical_artifact_ids=revision.support_logical_artifact_ids,
            members=revision.members,
            selected_outputs=revision.selected_outputs,
            presentation_order=revision.presentation_order,
        )

    def _collection_semantic_key(
        self,
        *,
        market_id: object,
        source_ohlcv: object,
        root_logical_artifact_ids: Sequence[str],
        support_logical_artifact_ids: Sequence[str],
        members: Sequence[ArtifactCollectionMemberV1],
        selected_outputs: Sequence[ArtifactCollectionOutputV1],
        presentation_order: Sequence[str],
    ) -> tuple[object, ...]:
        del support_logical_artifact_ids
        del presentation_order
        resolver = self._collection_semantic_key_resolver
        if resolver is None:
            raise DataManagerCreationStoreError(
                "Artifact Collection semantic authority is not configured"
            )
        return resolver(market_id, root_logical_artifact_ids, selected_outputs)

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
                self._load_canonical(path, artifact_collection_revision_from_dict)
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
            revision = self._load_canonical(path, artifact_collection_revision_from_dict)
            if revision.collection_id != collection_id or revision.revision_id != exact:
                raise DataManagerCreationStoreError("Artifact Collection identity disagrees with path")
            return revision

    def delete_collection(
        self,
        collection_id: str,
        *,
        before_delete: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        with self._lock:
            current = self.load_collection(collection_id)
            revisions = self._preflight_collection_deletion(collection_id)
            if current.revision_id not in {item.revision_id for item in revisions}:
                raise DataManagerCreationStoreError(
                    "Artifact Collection revisions do not match head"
                )
            if before_delete is not None:
                before_delete()

            collection_dir = self._collection_dir(collection_id)
            (collection_dir / "head.json").unlink()
            revisions_dir = collection_dir / "revisions"
            for revision in revisions:
                (revisions_dir / f"{revision.revision_id}.json").unlink()
            revisions_dir.rmdir()
            collection_dir.rmdir()
            self._remove_empty_directory(self._root / "artifact_collections")
            self._remove_empty_directory(self._root)
            return current

    def save_seed(self, seed, *, values_csv: bytes | None = None, before_publish=None):
        if not isinstance(seed, (DatabaseSeedV1, DatabaseSeedV2)):
            raise TypeError("seed must be a Database Seed")
        with self._lock:
            legacy = self._seed_path(seed.seed_id)
            directory = legacy.with_suffix("")
            if isinstance(seed, DatabaseSeedV1):
                if directory.exists():
                    raise DataManagerCreationStoreError("both Seed layouts claim the same identity")
                if before_publish is not None:
                    before_publish()
                self._write_immutable(legacy, seed.canonical_json_bytes())
                return seed
            if legacy.exists():
                raise DataManagerCreationStoreError("both Seed layouts claim the same identity")
            self._validate_seed_values(seed, values_csv)
            if directory.exists():
                if self.load_seed(seed.seed_id) != seed or self.load_seed_values(seed.seed_id) != values_csv:
                    raise DataManagerCreationIdentityCollision("Database Seed identity collision")
                return seed
            self._ensure_directory(directory.parent)
            temporary = directory.parent / f".tmp-{self._token()}"
            try:
                temporary.mkdir()
                for name, content in (("manifest.json", seed.canonical_json_bytes()), ("values.csv", values_csv)):
                    (temporary / name).write_bytes(content)
                    self._flush_file(temporary / name)
                if before_publish is not None:
                    before_publish()
                os.rename(temporary, directory)
            finally:
                if temporary.exists():
                    for child in temporary.iterdir():
                        child.unlink()
                    temporary.rmdir()
        return seed

    def list_seeds(self):
        return self._list_seeds(metadata_only=False)

    def list_seeds_metadata(self):
        return self._list_seeds(metadata_only=True)

    def _list_seeds(self, *, metadata_only):
        root = self._root / "database_seeds"
        with self._lock:
            if not root.exists():
                return ()
            self._require_safe_directory(root)
            identities = set()
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                if not path.name.startswith("seed_"):
                    continue
                if path.name.endswith(".json"):
                    self._read_safe_file(path)
                    identities.add(path.stem)
                else:
                    self._require_safe_directory(path)
                    identities.add(path.name)
            load = self.load_seed_metadata if metadata_only else self.load_seed
            values = tuple(load(identity) for identity in sorted(identities))
            return tuple(sorted(values, key=lambda item: (item.created_at_utc, item.seed_id)))

    def load_seed(self, seed_id):
        with self._lock:
            pending = self._seed_append_pending(seed_id)
            if pending is not None:
                return pending[3]
            legacy = self._seed_path(seed_id)
            directory = legacy.with_suffix("")
            if legacy.exists() and directory.exists():
                raise DataManagerCreationStoreError("both Seed layouts claim the same identity")
            if directory.exists():
                self._require_safe_directory(directory)
                if {p.name for p in directory.iterdir()} != {"manifest.json", "values.csv"}:
                    raise DataManagerCreationStoreError("Database Seed payload files are not exact")
                seed = self._load_canonical(directory / "manifest.json", DatabaseSeedV2.from_dict)
                self._validate_seed_values(seed, self._read_safe_file(directory / "values.csv"))
            else:
                seed = self._load_canonical(legacy, DatabaseSeedV1.from_dict)
            if seed.seed_id != seed_id:
                raise DataManagerCreationStoreError("Database Seed identity disagrees with path")
            return seed

    def load_seed_metadata(self, seed_id):
        with self._lock:
            legacy = self._seed_path(seed_id)
            directory = legacy.with_suffix("")
            record = legacy.parent / f".seed-append-{seed_id}.json"
            if record.exists() or record.is_symlink():
                # Pending append has not committed. Browse the old manifest,
                # without reading either canonical or backup values.
                payload = self._seed_append_file(record)
                try:
                    data = json.loads(payload)
                except (ValueError, UnicodeError) as exc:
                    raise DataManagerCreationStoreError("invalid Seed append record") from exc
                fields = {"version", "seed_id", "backup_token", "manifest_sha256", "values_sha256"}
                if (not isinstance(data, dict) or set(data) != fields
                        or type(data["version"]) is not int or data["version"] != 1
                        or data["seed_id"] != seed_id or seed_id != seed_id.lower()
                        or canonical_json_bytes(data) != payload
                        or legacy.exists() or legacy.is_symlink()):
                    raise DataManagerCreationStoreError("invalid Seed append record fields")
                self._require_safe_directory(self._root)
                self._require_safe_directory(directory)
                if {p.name for p in directory.iterdir()} != {"manifest.json", "values.csv"}:
                    raise DataManagerCreationStoreError("Database Seed payload files are not exact")
                for key, length in (("backup_token", 32), ("manifest_sha256", 64), ("values_sha256", 64)):
                    token = data[key]
                    if not isinstance(token, str) or len(token) != length or any(c not in "0123456789abcdef" for c in token):
                        raise DataManagerCreationStoreError("invalid Seed append record token/hash")
                directory = legacy.parent / f".seed-append-{seed_id}-{data['backup_token']}"
                self._require_safe_directory(directory)
                if {p.name for p in directory.iterdir()} != {"manifest.json", "values.csv"}:
                    raise DataManagerCreationStoreError("Database Seed payload files are not exact")
                manifest = self._seed_append_file(directory / "manifest.json")
                if sha256(manifest).hexdigest() != data["manifest_sha256"]:
                    raise DataManagerCreationStoreError("Seed append backup manifest differs")
                seed = self._load_canonical(directory / "manifest.json", DatabaseSeedV2.from_dict)
            else:
                if legacy.exists() and directory.exists():
                    raise DataManagerCreationStoreError("both Seed layouts claim the same identity")
                if directory.exists():
                    self._require_safe_directory(directory)
                    if {p.name for p in directory.iterdir()} != {"manifest.json", "values.csv"}:
                        raise DataManagerCreationStoreError("Database Seed payload files are not exact")
                    seed = self._load_canonical(directory / "manifest.json", DatabaseSeedV2.from_dict)
                else:
                    seed = self._load_canonical(legacy, DatabaseSeedV1.from_dict)
            if seed.seed_id != seed_id:
                raise DataManagerCreationStoreError("Database Seed identity disagrees with path")
            return seed

    @staticmethod
    def _validate_seed_values(seed, values):
        if not isinstance(values, bytes) or sha256(values).hexdigest() != seed.values_sha256:
            raise DataManagerCreationStoreError("Database Seed values hash disagrees")
        header, _rows, _timestamps = _snapshot_rows(
            values, columns=("ts_ms", *seed.selected_ohlcv_columns),
            row_count=seed.row_count, first=seed.selected_range_start_ms,
            last=seed.selected_range_end_ms,
        )
        if header != ("ts_ms", *seed.selected_ohlcv_columns) or len(header) != seed.column_count:
            raise DataManagerCreationStoreError("Database Seed header/order/count disagrees")
        if (seed.source_row_count != seed.source_ohlcv.row_count or
                seed.first_timestamp_ms != seed.source_ohlcv.first_timestamp_ms or
                seed.last_timestamp_ms != seed.source_ohlcv.last_timestamp_ms):
            raise DataManagerCreationStoreError("Database Seed source evidence disagrees")

    def load_seed_values(self, seed_id):
        with self._lock:
            pending = self._seed_append_pending(seed_id)
            if pending is not None:
                return pending[5]
            seed = self.load_seed(seed_id)
            if not isinstance(seed, DatabaseSeedV2):
                raise DataManagerCreationStoreError("legacy Seed requires proven source reconstruction")
            return self._read_safe_file(self._seed_path(seed_id).with_suffix("") / "values.csv")

    def delete_seed(self, seed_id):
        with self._lock:
            pending = self._seed_append_pending(seed_id)
            if pending is not None:
                self._rollback_seed_append(pending)
            seed = self.load_seed(seed_id)
            if isinstance(seed, DatabaseSeedV2):
                directory = self._seed_path(seed_id).with_suffix("")
                for name in ("manifest.json", "values.csv"):
                    (directory / name).unlink()
                directory.rmdir()
            else:
                self._seed_path(seed_id).unlink()
            return seed

    def _seed_append_file(self, path):
        self._require_safe_directory(path.parent)
        if getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise DataManagerCreationStoreError("unsafe Seed append file")
        return self._read_safe_file(path)

    def _seed_append_pair(self, directory, seed_id):
        self._require_safe_directory(directory.parent)
        self._require_safe_directory(directory)
        if {p.name for p in directory.iterdir()} != {"manifest.json", "values.csv"}:
            raise DataManagerCreationStoreError("Database Seed payload files are not exact")
        manifest = self._seed_append_file(directory / "manifest.json")
        try:
            seed = DatabaseSeedV2.from_dict(json.loads(manifest))
        except (ValueError, TypeError, KeyError) as exc:
            raise DataManagerCreationStoreError("invalid Seed append manifest") from exc
        if seed.seed_id != seed_id or manifest != seed.canonical_json_bytes():
            raise DataManagerCreationStoreError("Seed append manifest identity/encoding differs")
        values = self._seed_append_file(directory / "values.csv")
        self._validate_seed_values(seed, values)
        return seed, manifest, values

    def _seed_append_pending(self, seed_id):
        legacy = self._seed_path(seed_id)
        record = legacy.parent / f".seed-append-{seed_id}.json"
        if not record.exists() and not record.is_symlink():
            return None
        self._require_safe_directory(self._root)
        self._require_safe_directory(legacy.parent)
        directory = legacy.with_suffix("")
        if legacy.exists() or legacy.is_symlink():
            raise DataManagerCreationStoreError("pending append requires V2 Seed layout")
        self._require_safe_directory(directory)
        if {p.name for p in directory.iterdir()} != {"manifest.json", "values.csv"}:
            raise DataManagerCreationStoreError("Database Seed payload files are not exact")
        # Canonical files can contain an unpublished pair, but must remain safe files.
        for name in ("manifest.json", "values.csv"):
            self._seed_append_file(directory / name)
        payload = self._seed_append_file(record)
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeError) as exc:
            raise DataManagerCreationStoreError("invalid Seed append record") from exc
        fields = {"version", "seed_id", "backup_token", "manifest_sha256", "values_sha256"}
        if (not isinstance(data, dict) or set(data) != fields or
                type(data["version"]) is not int or data["version"] != 1 or
                data["seed_id"] != seed_id or seed_id != seed_id.lower() or
                canonical_json_bytes(data) != payload):
            raise DataManagerCreationStoreError("invalid Seed append record fields")
        for key, length in (("backup_token", 32), ("manifest_sha256", 64), ("values_sha256", 64)):
            value = data[key]
            if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
                raise DataManagerCreationStoreError("invalid Seed append record token/hash")
        backup = legacy.parent / f".seed-append-{seed_id}-{data['backup_token']}"
        seed, manifest, values = self._seed_append_pair(backup, seed_id)
        if sha256(manifest).hexdigest() != data["manifest_sha256"] or sha256(values).hexdigest() != data["values_sha256"]:
            raise DataManagerCreationStoreError("Seed append backup hash differs")
        return record, payload, backup, seed, manifest, values

    def _require_seed_append_owner(self, pending):
        if self._seed_append_pending(pending[3].seed_id) != pending:
            raise DataManagerCreationStoreError("Seed append recovery ownership changed")

    def _cleanup_seed_append_backup(self, pending, *, allow_partial=False):
        record, _payload, backup, seed, manifest, values = pending
        if record.exists() or record.is_symlink():
            raise DataManagerCreationStoreError("Seed append backup is still referenced")
        if allow_partial:
            self._require_safe_directory(backup.parent)
            self._require_safe_directory(backup)
            names = {p.name for p in backup.iterdir()}
            if not names <= {"manifest.json", "values.csv"}:
                raise DataManagerCreationStoreError("Seed append partial backup ownership changed")
            for name, expected in (("manifest.json", manifest), ("values.csv", values)):
                if name in names and self._seed_append_file(backup / name) != expected:
                    raise DataManagerCreationStoreError("Seed append partial backup bytes changed")
        else:
            if self._seed_append_pair(backup, seed.seed_id) != (seed, manifest, values):
                raise DataManagerCreationStoreError("Seed append backup ownership changed")
            names = {"manifest.json", "values.csv"}
        root = (self._root / "database_seeds").resolve(strict=True)
        if backup.resolve(strict=True).parent != root:
            raise DataManagerCreationStoreError("Seed append cleanup escaped its root")
        for name in names:
            path = backup / name
            if path.resolve(strict=True).parent != backup.resolve(strict=True):
                raise DataManagerCreationStoreError("Seed append cleanup escaped its backup")
        for name in sorted(names):
            (backup / name).unlink()
        backup.rmdir()

    def _rollback_seed_append(self, pending):
        self._require_seed_append_owner(pending)
        record, _payload, _backup, seed, manifest, values = pending
        directory = self._seed_path(seed.seed_id).with_suffix("")
        self._restore_atomic_target(directory / "values.csv", values)
        self._require_seed_append_owner(pending)
        self._restore_atomic_target(directory / "manifest.json", manifest)
        if self._seed_append_pair(directory, seed.seed_id) != (seed, manifest, values):
            raise DataManagerCreationStoreError("Seed append rollback verification failed")
        self._require_seed_append_owner(pending)
        record.unlink()
        self._cleanup_seed_append_backup(pending)

    def append_seed(self, previous_seed, seed, previous_values_csv, values_csv, before_publish=None):
        if not isinstance(seed, (DatabaseSeedV1, DatabaseSeedV2)) or type(seed) is not type(previous_seed):
            raise TypeError("Seed append must preserve Seed class")
        preserved = ("seed_id", "schema_version", "display_name", "description", "market_id",
                     "selected_ohlcv_columns", "selected_range_start_ms", "created_at_utc")
        if any(getattr(seed, key) != getattr(previous_seed, key) for key in preserved):
            raise DataManagerCreationStoreError("Seed append changed preserved identity/fields")
        if not isinstance(previous_values_csv, bytes) or not isinstance(values_csv, bytes):
            raise TypeError("Seed append values must be bytes")
        old_header, old_rows, old_axis = _snapshot_rows(
            previous_values_csv, columns=("ts_ms", *seed.selected_ohlcv_columns),
            first=previous_seed.selected_range_start_ms, last=previous_seed.selected_range_end_ms,
        )
        header, rows, axis = _snapshot_rows(values_csv, columns=old_header,
                                          first=seed.selected_range_start_ms, last=seed.selected_range_end_ms)
        if (old_header != ("ts_ms", *seed.selected_ohlcv_columns) or header != old_header
                or len(rows) <= len(old_rows) or not values_csv.startswith(previous_values_csv)
                or rows[:len(old_rows)] != old_rows or axis[:len(old_axis)] != old_axis):
            raise DataManagerCreationStoreError("Seed append must preserve the exact old prefix/axis")
        with self._lock:
            if self.load_seed_metadata(seed.seed_id) != previous_seed:
                raise DataManagerCreationStoreError("Seed changed before append")
            if isinstance(seed, DatabaseSeedV1):
                if before_publish is not None:
                    before_publish()
                self._write_atomic(self._seed_path(seed.seed_id), seed.canonical_json_bytes())
                return seed
            if self.read_trusted_seed_values(seed.seed_id) != previous_values_csv:
                raise DataManagerCreationStoreError("Seed values changed before append")
            self._validate_seed_values(seed, values_csv)
            interrupted = self._seed_append_pending(seed.seed_id)
            if interrupted is not None:
                self._rollback_seed_append(interrupted)
            if self.load_seed_metadata(seed.seed_id) != previous_seed or self.read_trusted_seed_values(seed.seed_id) != previous_values_csv:
                raise DataManagerCreationStoreError("Seed changed during pending rollback")
            directory = self._seed_path(seed.seed_id).with_suffix("")
            token = self._token()
            record = directory.parent / f".seed-append-{seed.seed_id}.json"
            backup = directory.parent / f".seed-append-{seed.seed_id}-{token}"
            if record.exists() or record.is_symlink() or backup.exists() or backup.is_symlink():
                raise DataManagerCreationIdentityCollision("Seed append recovery path collision")
            manifest = previous_seed.canonical_json_bytes()
            payload = canonical_json_bytes(dict(version=1, seed_id=seed.seed_id, backup_token=token,
                                                 manifest_sha256=sha256(manifest).hexdigest(),
                                                 values_sha256=sha256(previous_values_csv).hexdigest()))
            pending = record, payload, backup, previous_seed, manifest, previous_values_csv
            backup.mkdir()
            # No canonical write is allowed until immutable record ownership is proven.
            owned = False
            try:
                self._write_immutable(backup / "manifest.json", manifest)
                self._write_immutable(backup / "values.csv", previous_values_csv)
                if self._seed_append_pair(backup, seed.seed_id) != (previous_seed, manifest, previous_values_csv):
                    raise DataManagerCreationStoreError("Seed append backup verification failed")
                if record.exists() or record.is_symlink():
                    raise DataManagerCreationIdentityCollision("Seed append record collision")
                self._write_immutable(record, payload)
                self._require_seed_append_owner(pending)
                owned = True
                self._write_atomic(directory / "values.csv", values_csv)
                self._require_seed_append_owner(pending)
                self._write_atomic(directory / "manifest.json", seed.canonical_json_bytes())
                if before_publish is not None:
                    before_publish()
                if self._seed_append_pair(directory, seed.seed_id) != (seed, seed.canonical_json_bytes(), values_csv):
                    raise DataManagerCreationStoreError("Seed append candidate changed before publication")
                self._require_seed_append_owner(pending)
                record.unlink()
            except Exception:
                if owned:
                    self._rollback_seed_append(pending)
                elif not record.exists() and not record.is_symlink():
                    self._cleanup_seed_append_backup(pending, allow_partial=True)
                raise
            try:
                self._cleanup_seed_append_backup(pending)
            except OSError:
                pass  # Logical commit succeeded; this disposable backup may remain.
            return seed

    def publish_database_revision(
        self,
        definition: DatabaseDefinitionV1,
        manifest: DatabaseRevisionManifest,
        values_csv: bytes,
        *,
        expected_head_revision_id: str | None,
        utc_classification: bytes | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseRevisionManifest:
        if not isinstance(definition, DatabaseDefinitionV1):
            raise TypeError("definition must be a DatabaseDefinitionV1")
        if not isinstance(manifest, DatabaseRevisionManifest):
            raise TypeError("manifest must be a Database revision manifest")
        if definition.database_id != manifest.database_id:
            raise DataManagerCreationStoreError(
                "Database definition and revision identities differ"
            )
        if not isinstance(values_csv, bytes):
            raise TypeError("values_csv must be bytes")
        self._validate_database_values(manifest, values_csv)
        _decode_snapshot(utc_classification, manifest)
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
                if loaded.manifest != manifest or loaded.values_csv != values_csv or loaded.utc_classification != utc_classification:
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
                    if utc_classification is not None:
                        (temporary / "utc_classification.json").write_bytes(utc_classification)
                        self._flush_file(temporary / "utc_classification.json")
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
    ) -> tuple[DatabaseRevisionManifest, ...]:
        revisions = self._database_dir(database_id) / "revisions"
        with self._lock:
            if not revisions.exists():
                return ()
            self._require_safe_directory(revisions)
            values = tuple(
                self.load_database_manifest(database_id, child.name)
                for child in sorted(revisions.iterdir(), key=lambda item: item.name)
                if child.is_dir() and len(child.name) == 64 and all(c in "0123456789abcdef" for c in child.name)
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
            manifest = self._load_canonical(
                directory / "manifest.json", database_revision_from_dict
            )
            expected = {"manifest.json", "values.csv"}
            if getattr(manifest, "utc_classification", None) is not None:
                expected.add("utc_classification.json")
            if children != expected:
                raise DataManagerCreationStoreError("Database revision payload files are not exact")
            classification = (self._read_safe_file(directory / "utc_classification.json")
                              if "utc_classification.json" in expected else None)
            _decode_snapshot(classification, manifest)
            values = self._read_safe_file(directory / "values.csv")
            if manifest.database_id != database_id or manifest.revision_id != exact:
                raise DataManagerCreationStoreError("Database revision identity disagrees with path")
            if sha256(values).hexdigest() != manifest.values_sha256:
                raise DataManagerCreationStoreError(
                    "Database revision values hash does not match manifest"
                )
            self._validate_database_values(manifest, values)
            return LoadedDatabaseRevision(manifest, values, classification)

    def load_database_manifest(self, database_id, revision_id=None):
        with self._lock:
            exact = revision_id or self.load_database_head(database_id).revision_id
            directory = self._database_dir(database_id) / "revisions" / exact
            self._require_safe_directory(directory)
            manifest = self._load_canonical(directory / "manifest.json", database_revision_from_dict)
            expected = {"manifest.json", "values.csv"}
            if getattr(manifest, "utc_classification", None) is not None:
                expected.add("utc_classification.json")
            if {item.name for item in directory.iterdir()} != expected:
                raise DataManagerCreationStoreError("Database revision payload files are not exact")
            if "utc_classification.json" in expected:
                _decode_snapshot(self._read_safe_file(directory / "utc_classification.json"), manifest)
            if manifest.database_id != database_id or manifest.revision_id != exact:
                raise DataManagerCreationStoreError("Database revision identity disagrees with path")
            return manifest

    def read_trusted_database_revision(self, database_id, revision_id=None):
        with self._lock:
            manifest = self.load_database_manifest(database_id, revision_id)
            path = self._database_dir(database_id) / "revisions" / manifest.revision_id / "values.csv"
            classification = (self._read_safe_file(path.parent / "utc_classification.json")
                              if getattr(manifest, "utc_classification", None) is not None else None)
            _decode_snapshot(classification, manifest)
            return LoadedDatabaseRevision(manifest, self._read_safe_file(path), classification)

    def read_trusted_seed_values(self, seed_id):
        with self._lock:
            seed = self.load_seed_metadata(seed_id)
            if not isinstance(seed, DatabaseSeedV2):
                raise DataManagerCreationStoreError("legacy Seed requires proven source reconstruction")
            legacy = self._seed_path(seed_id)
            record = legacy.parent / f".seed-append-{seed_id}.json"
            if record.exists() or record.is_symlink():
                # Recovery reads retain their strict ownership and pairing proof.
                return self._seed_append_pending(seed_id)[5]
            return self._read_safe_file(legacy.with_suffix("") / "values.csv")

    @staticmethod
    def _validate_database_values(manifest, values):
        if sha256(values).hexdigest() != manifest.values_sha256:
            raise DataManagerCreationStoreError("Database revision values hash does not match manifest")
        header, _rows, _timestamps = _snapshot_rows(
            values, columns=tuple(manifest.column_mapping.values()),
            row_count=manifest.row_count, first=manifest.first_timestamp_ms,
            last=manifest.last_timestamp_ms,
            nullable_columns=_database_nullable_columns(manifest),
        )
        if len(header) != manifest.column_count:
            raise DataManagerCreationStoreError("Database column count disagrees")

    def delete_database(self, database_id, *, before_delete=None):
        with self._lock:
            live = self._database_dir(database_id)
            quarantine = live.with_name(".deleted-" + database_id)
            if live.exists() and quarantine.exists():
                raise DataManagerCreationStoreError("Database and deletion quarantine both exist")
            if live.exists():
                self._require_safe_directory(live)
                if {p.name for p in live.iterdir()} != {"definition.json", "head.json", "revisions"}:
                    raise DataManagerCreationStoreError("Database owned paths are not exact")
                self.load_database_definition(database_id)
                head = self.load_database_head(database_id)
                revisions = self.list_database_revisions(database_id)
                if head.revision_id not in {r.revision_id for r in revisions}:
                    raise DataManagerCreationStoreError("Database revision inventory disagrees with head")
                if {p.name for p in (live / "revisions").iterdir()} != {r.revision_id for r in revisions}:
                    raise DataManagerCreationStoreError("Database revision inventory is not exact")
                if before_delete is not None:
                    before_delete()
                os.rename(live, quarantine)
            elif not quarantine.exists():
                raise FileNotFoundError(f"Database not found: {database_id}")
            self._require_safe_directory(quarantine)
            for root, directories, files in os.walk(quarantine, followlinks=False):
                for name in directories:
                    self._require_safe_directory(Path(root) / name)
                for name in files:
                    self._read_safe_file(Path(root) / name)
            try:
                shutil.rmtree(quarantine)
            except OSError as exc:
                raise DataManagerCreationStoreError(
                    f"deletion committed; cleanup incomplete: {quarantine}: {exc}"
                ) from exc
            return database_id

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

    def _preflight_collection_deletion(
        self, collection_id: str
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        collection_dir = self._collection_dir(collection_id)
        self._require_safe_directory(collection_dir)
        if {item.name for item in collection_dir.iterdir()} != {
            "head.json",
            "revisions",
        }:
            raise DataManagerCreationStoreError(
                "Artifact Collection persistence files are not exact"
            )
        head = self.load_collection_head(collection_id)
        revisions_dir = collection_dir / "revisions"
        self._require_safe_directory(revisions_dir)
        paths = tuple(sorted(revisions_dir.iterdir(), key=lambda item: item.name))
        if not paths:
            raise DataManagerCreationStoreError(
                "Artifact Collection has no revisions"
            )
        revisions: list[ArtifactCollectionRevisionV1] = []
        for path in paths:
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise DataManagerCreationStoreError(
                    "Artifact Collection revision files are not exact"
                )
            revision = self.load_collection(collection_id, path.stem)
            revisions.append(revision)
        if head.revision_id not in {item.revision_id for item in revisions}:
            raise DataManagerCreationStoreError(
                "Artifact Collection head revision is missing"
            )
        return tuple(revisions)

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

    def _remove_empty_directory(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        self._require_safe_directory(path)
        if not any(path.iterdir()):
            path.rmdir()

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
