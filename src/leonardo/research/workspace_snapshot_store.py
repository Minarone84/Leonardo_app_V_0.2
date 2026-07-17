"""Thread-safe atomic filesystem owner for Research Workspace Snapshot version 1 files."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotAlreadyExistsError,
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotNotFoundError,
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
    ResearchWorkspaceSnapshotValidationError,
    canonical_json_bytes,
)


class ResearchWorkspaceSnapshotStore:
    """Persist one canonical JSON file per Research Workspace Snapshot."""

    def __init__(
        self,
        root_dir: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root_dir = Path(root_dir).absolute()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._lock = RLock()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def snapshot_path(self, snapshot_id: str) -> Path:
        from leonardo.research.workspace_snapshot import _identifier

        identifier = _identifier(snapshot_id, "snapshot_id")
        path = self._root_dir / f"{identifier}.json"
        self._require_contained(path)
        return path

    def list_summaries(self) -> tuple[ResearchWorkspaceSnapshotSummary, ...]:
        with self._lock:
            if not self._root_dir.exists():
                return ()
            self._require_safe_root()
            summaries = [self._summary(path) for path in sorted(self._root_dir.glob("*.json"))]
            return tuple(
                sorted(
                    summaries,
                    key=lambda item: (
                        item.display_name.casefold(),
                        item.snapshot_id,
                    ),
                )
            )

    def load(self, snapshot_id: str) -> ResearchWorkspaceSnapshotV1:
        path = self.snapshot_path(snapshot_id)
        with self._lock:
            if not path.exists():
                raise ResearchWorkspaceSnapshotNotFoundError(snapshot_id)
            self._require_safe_path(path)
            return self._load_path(path)

    def create(self, draft: ResearchWorkspaceSnapshotDraft) -> ResearchWorkspaceSnapshotV1:
        if not isinstance(draft, ResearchWorkspaceSnapshotDraft):
            raise TypeError("draft must be ResearchWorkspaceSnapshotDraft")
        with self._lock:
            snapshot_id = draft.snapshot_id or f"snapshot_{self._id_factory()}"
            path = self.snapshot_path(snapshot_id)
            self._reject_duplicate(path, draft.display_name)
            now = self._now()
            snapshot = ResearchWorkspaceSnapshotV1.build(
                snapshot_id=snapshot_id,
                display_name=draft.display_name,
                description=draft.description,
                created_at_utc=now,
                updated_at_utc=now,
                workspace=draft.workspace,
                charts=draft.charts,
            )
            self._write(path, snapshot, refuse_existing=True)
            return snapshot

    def update(
        self, snapshot_id: str, draft: ResearchWorkspaceSnapshotDraft
    ) -> ResearchWorkspaceSnapshotV1:
        if not isinstance(draft, ResearchWorkspaceSnapshotDraft):
            raise TypeError("draft must be ResearchWorkspaceSnapshotDraft")
        path = self.snapshot_path(snapshot_id)
        with self._lock:
            if not path.exists():
                raise ResearchWorkspaceSnapshotNotFoundError(snapshot_id)
            current = self._load_path(path)
            self._reject_duplicate(path, draft.display_name, excluding=snapshot_id)
            snapshot = ResearchWorkspaceSnapshotV1.build(
                snapshot_id=current.snapshot_id,
                display_name=draft.display_name,
                description=draft.description,
                created_at_utc=current.created_at_utc,
                updated_at_utc=self._now(),
                workspace=draft.workspace,
                charts=draft.charts,
            )
            self._write(path, snapshot, refuse_existing=False)
            return snapshot

    def delete(self, snapshot_id: str) -> ResearchWorkspaceSnapshotSummary:
        path = self._delete_path(snapshot_id)
        with self._lock:
            if not self._root_dir.exists():
                raise ResearchWorkspaceSnapshotNotFoundError(snapshot_id)
            self._require_safe_root()
            if _is_link_or_junction(path):
                raise ResearchWorkspaceSnapshotValidationError(
                    "Research Workspace Snapshot path must not be a link"
                )
            if not path.exists():
                raise ResearchWorkspaceSnapshotNotFoundError(snapshot_id)
            self._require_safe_path(path)
            summary = self._summary(path)
            path.unlink()
            return summary

    def _delete_path(self, snapshot_id: str) -> Path:
        try:
            return self.snapshot_path(snapshot_id)
        except ResearchWorkspaceSnapshotValidationError:
            if not isinstance(snapshot_id, str):
                raise
            if (
                not snapshot_id
                or snapshot_id in {".", ".."}
                or "\x00" in snapshot_id
                or "/" in snapshot_id
                or "\\" in snapshot_id
                or Path(snapshot_id).is_absolute()
            ):
                raise ResearchWorkspaceSnapshotValidationError(
                    "invalid Research Workspace Snapshot delete identity"
                )
            path = self._root_dir / f"{snapshot_id}.json"
            if path.parent != self._root_dir:
                raise ResearchWorkspaceSnapshotValidationError(
                    "Research Workspace Snapshot delete path must be a direct child"
                )
            return path

    def _summary(self, path: Path) -> ResearchWorkspaceSnapshotSummary:
        try:
            snapshot = self._load_path(path)
            return ResearchWorkspaceSnapshotSummary(
                snapshot_id=snapshot.snapshot_id,
                display_name=snapshot.display_name,
                description=snapshot.description,
                chart_count=len(snapshot.charts),
                created_at_utc=snapshot.created_at_utc,
                updated_at_utc=snapshot.updated_at_utc,
            )
        except Exception as exc:
            return ResearchWorkspaceSnapshotSummary(
                snapshot_id=path.stem,
                display_name=path.stem,
                description="",
                chart_count=0,
                created_at_utc=None,
                updated_at_utc=None,
                valid=False,
                rejection_reason=f"{type(exc).__name__}: {exc}",
            )

    def _load_path(self, path: Path) -> ResearchWorkspaceSnapshotV1:
        self._require_safe_path(path)
        try:
            raw = path.read_bytes()
            decoded = raw.decode("utf-8")
            payload = json.loads(decoded)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchWorkspaceSnapshotValidationError("invalid Research Workspace Snapshot JSON") from exc
        if not isinstance(payload, dict):
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot JSON root must be an object")
        snapshot = ResearchWorkspaceSnapshotV1.from_dict(payload)
        if snapshot.snapshot_id != path.stem:
            raise ResearchWorkspaceSnapshotValidationError("snapshot ID does not match file name")
        if raw != snapshot.canonical_json_bytes():
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot JSON bytes are not canonical")
        return snapshot

    def _write(
        self,
        path: Path,
        snapshot: ResearchWorkspaceSnapshotV1,
        *,
        refuse_existing: bool,
    ) -> None:
        if refuse_existing and path.exists():
            raise ResearchWorkspaceSnapshotAlreadyExistsError(snapshot.snapshot_id)
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._require_safe_root()
        self._require_contained(path)
        if path.exists():
            self._require_safe_path(path)
        temporary = self._root_dir / f".{snapshot.snapshot_id}.{uuid4().hex}.tmp"
        self._require_contained(temporary)
        try:
            with temporary.open("xb") as handle:
                handle.write(snapshot.canonical_json_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            if refuse_existing and path.exists():
                raise ResearchWorkspaceSnapshotAlreadyExistsError(snapshot.snapshot_id)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _reject_duplicate(
        self,
        path: Path,
        display_name: str,
        *,
        excluding: str | None = None,
    ) -> None:
        if path.exists() and path.stem != excluding:
            raise ResearchWorkspaceSnapshotAlreadyExistsError(path.stem)
        folded = display_name.casefold()
        for summary in self.list_summaries():
            if (
                summary.valid
                and summary.snapshot_id != excluding
                and summary.display_name.casefold() == folded
            ):
                raise ResearchWorkspaceSnapshotAlreadyExistsError(display_name)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ResearchWorkspaceSnapshotValidationError("clock must return timezone-aware UTC")
        if value.utcoffset().total_seconds() != 0:
            raise ResearchWorkspaceSnapshotValidationError("clock must return UTC")
        return value

    def _require_safe_root(self) -> None:
        if not self._root_dir.is_dir():
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot root must be a directory")
        if _is_link_or_junction(self._root_dir):
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot root must not be a link")

    def _require_safe_path(self, path: Path) -> None:
        self._require_contained(path)
        self._require_safe_root()
        if _is_link_or_junction(path):
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot path must not be a link")
        resolved = path.resolve(strict=True)
        resolved_root = self._root_dir.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot path escapes root") from exc
        if not resolved.is_file():
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot path must be a file")

    def _require_contained(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(
                self._root_dir.resolve(strict=False)
            )
        except ValueError as exc:
            raise ResearchWorkspaceSnapshotValidationError("Research Workspace Snapshot path escapes root") from exc


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


WorkspaceSnapshotStore = ResearchWorkspaceSnapshotStore
