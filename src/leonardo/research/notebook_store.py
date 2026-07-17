"""Thread-safe atomic filesystem owner for Research Notebook version 1 files."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from leonardo.research.notebook import (
    ResearchNotebookAlreadyExistsError,
    ResearchNotebookDraft,
    ResearchNotebookNotFoundError,
    ResearchNotebookSummary,
    ResearchNotebookV1,
    ResearchNotebookValidationError,
)


class ResearchNotebookStore:
    """Persist one canonical JSON file per Research Notebook."""

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

    def notebook_path(self, notebook_id: str) -> Path:
        from leonardo.research.notebook import _identifier

        identifier = _identifier(notebook_id, "notebook_id")
        path = self._root_dir / f"{identifier}.json"
        self._require_contained(path)
        return path

    def list_summaries(self) -> tuple[ResearchNotebookSummary, ...]:
        with self._lock:
            if not self._root_dir.exists():
                return ()
            self._require_safe_root()
            summaries = [
                self._summary(path) for path in sorted(self._root_dir.glob("*.json"))
            ]
            return tuple(
                sorted(
                    summaries,
                    key=lambda item: (
                        item.display_name.casefold(),
                        item.notebook_id,
                    ),
                )
            )

    def load(self, notebook_id: str) -> ResearchNotebookV1:
        path = self.notebook_path(notebook_id)
        with self._lock:
            if not path.exists():
                raise ResearchNotebookNotFoundError(notebook_id)
            self._require_safe_path(path)
            return self._load_path(path)

    def create(self, draft: ResearchNotebookDraft) -> ResearchNotebookV1:
        if not isinstance(draft, ResearchNotebookDraft):
            raise TypeError("draft must be ResearchNotebookDraft")
        with self._lock:
            notebook_id = draft.notebook_id or f"notebook_{self._id_factory()}"
            path = self.notebook_path(notebook_id)
            self._reject_duplicate(path, draft.display_name)
            now = self._now()
            notebook = ResearchNotebookV1.build(
                notebook_id=notebook_id,
                display_name=draft.display_name,
                description=draft.description,
                created_at_utc=now,
                updated_at_utc=now,
                annotation_settings=draft.annotation_settings,
                pages=draft.pages,
            )
            self._write(path, notebook, refuse_existing=True)
            return notebook

    def update(
        self, notebook_id: str, draft: ResearchNotebookDraft
    ) -> ResearchNotebookV1:
        if not isinstance(draft, ResearchNotebookDraft):
            raise TypeError("draft must be ResearchNotebookDraft")
        path = self.notebook_path(notebook_id)
        with self._lock:
            if not path.exists():
                raise ResearchNotebookNotFoundError(notebook_id)
            current = self._load_path(path)
            self._reject_duplicate(path, draft.display_name, excluding=notebook_id)
            notebook = ResearchNotebookV1.build(
                notebook_id=current.notebook_id,
                display_name=draft.display_name,
                description=draft.description,
                created_at_utc=current.created_at_utc,
                updated_at_utc=self._now(),
                annotation_settings=draft.annotation_settings,
                pages=draft.pages,
            )
            self._write(path, notebook, refuse_existing=False)
            return notebook

    def delete(self, notebook_id: str) -> ResearchNotebookSummary:
        path = self._delete_path(notebook_id)
        with self._lock:
            if not self._root_dir.exists():
                raise ResearchNotebookNotFoundError(notebook_id)
            self._require_safe_root()
            if _is_link_or_junction(path):
                raise ResearchNotebookValidationError(
                    "Research Notebook path must not be a link"
                )
            if not path.exists():
                raise ResearchNotebookNotFoundError(notebook_id)
            self._require_safe_path(path)
            summary = self._summary(path)
            path.unlink()
            return summary

    def _delete_path(self, notebook_id: str) -> Path:
        try:
            return self.notebook_path(notebook_id)
        except ResearchNotebookValidationError:
            if not isinstance(notebook_id, str):
                raise
            if (
                not notebook_id
                or notebook_id in {".", ".."}
                or "\x00" in notebook_id
                or "/" in notebook_id
                or "\\" in notebook_id
                or Path(notebook_id).is_absolute()
            ):
                raise ResearchNotebookValidationError(
                    "invalid Research Notebook delete identity"
                )
            path = self._root_dir / f"{notebook_id}.json"
            if path.parent != self._root_dir:
                raise ResearchNotebookValidationError(
                    "Research Notebook delete path must be a direct child"
                )
            return path

    def _summary(self, path: Path) -> ResearchNotebookSummary:
        try:
            notebook = self._load_path(path)
            return ResearchNotebookSummary(
                notebook_id=notebook.notebook_id,
                display_name=notebook.display_name,
                description=notebook.description,
                created_at_utc=notebook.created_at_utc,
                updated_at_utc=notebook.updated_at_utc,
                page_count=len(notebook.pages),
                note_count=sum(len(page.notes) for page in notebook.pages),
                potential_trade_count=sum(
                    len(page.potential_trades) for page in notebook.pages
                ),
                point_of_interest_count=sum(
                    len(page.points_of_interest) for page in notebook.pages
                ),
                page_market_ids=tuple(page.market_id for page in notebook.pages),
                path=path,
            )
        except Exception as exc:
            return ResearchNotebookSummary(
                notebook_id=path.stem,
                display_name=path.stem,
                description="",
                created_at_utc=None,
                updated_at_utc=None,
                page_count=0,
                note_count=0,
                potential_trade_count=0,
                point_of_interest_count=0,
                page_market_ids=(),
                valid=False,
                rejection_reason=f"{type(exc).__name__}: {exc}",
                path=path,
            )

    def _load_path(self, path: Path) -> ResearchNotebookV1:
        self._require_safe_path(path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchNotebookValidationError(
                "invalid Research Notebook JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchNotebookValidationError(
                "Research Notebook JSON root must be an object"
            )
        notebook = ResearchNotebookV1.from_dict(payload)
        if notebook.notebook_id != path.stem:
            raise ResearchNotebookValidationError(
                "notebook ID does not match file name"
            )
        if raw != notebook.canonical_json_bytes():
            raise ResearchNotebookValidationError(
                "Research Notebook JSON bytes are not canonical"
            )
        return notebook

    def _write(
        self,
        path: Path,
        notebook: ResearchNotebookV1,
        *,
        refuse_existing: bool,
    ) -> None:
        if refuse_existing and path.exists():
            raise ResearchNotebookAlreadyExistsError(notebook.notebook_id)
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._require_safe_root()
        self._require_contained(path)
        if path.exists():
            self._require_safe_path(path)
        temporary = self._root_dir / f".{notebook.notebook_id}.{uuid4().hex}.tmp"
        self._require_contained(temporary)
        try:
            with temporary.open("xb") as handle:
                handle.write(notebook.canonical_json_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            if refuse_existing and path.exists():
                raise ResearchNotebookAlreadyExistsError(notebook.notebook_id)
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
            raise ResearchNotebookAlreadyExistsError(path.stem)
        folded = display_name.casefold()
        for summary in self.list_summaries():
            if (
                summary.valid
                and summary.notebook_id != excluding
                and summary.display_name.casefold() == folded
            ):
                raise ResearchNotebookAlreadyExistsError(display_name)

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ResearchNotebookValidationError(
                "clock must return timezone-aware UTC"
            )
        if value.utcoffset().total_seconds() != 0:
            raise ResearchNotebookValidationError("clock must return UTC")
        return value

    def _require_safe_root(self) -> None:
        if not self._root_dir.is_dir():
            raise ResearchNotebookValidationError(
                "Research Notebook root must be a directory"
            )
        if _is_link_or_junction(self._root_dir):
            raise ResearchNotebookValidationError(
                "Research Notebook root must not be a link"
            )

    def _require_safe_path(self, path: Path) -> None:
        self._require_contained(path)
        self._require_safe_root()
        if _is_link_or_junction(path):
            raise ResearchNotebookValidationError(
                "Research Notebook path must not be a link"
            )
        resolved = path.resolve(strict=True)
        resolved_root = self._root_dir.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ResearchNotebookValidationError(
                "Research Notebook path escapes root"
            ) from exc
        if not resolved.is_file():
            raise ResearchNotebookValidationError(
                "Research Notebook path must be a file"
            )

    def _require_contained(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(
                self._root_dir.resolve(strict=False)
            )
        except ValueError as exc:
            raise ResearchNotebookValidationError(
                "Research Notebook path escapes root"
            ) from exc


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
