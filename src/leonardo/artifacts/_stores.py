from __future__ import annotations

import ctypes
import errno
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

from leonardo.data import MarketId, timeframe_to_storage_segment
from leonardo.financial_tools import canonicalize_tool_key, get_financial_tool_spec

from .models import (
    ArtifactAlreadyExistsError,
    ArtifactIdentityCollisionError,
    ArtifactNotFoundError,
    ArtifactValidationError,
)


_FailureHook = Callable[[str], None]
_SafetyCheck = Callable[[Path], Path]
_KINDS = frozenset({"indicator", "oscillator", "construct"})


def _market_root(root: Path, market_id: MarketId) -> Path:
    return (
        root
        / market_id.exchange
        / market_id.market_type
        / market_id.symbol
        / timeframe_to_storage_segment(market_id.timeframe)
    )


def _validate_kind_tool(kind: str, tool_key: str) -> None:
    if not isinstance(kind, str):
        raise ArtifactValidationError("kind must be a string")
    if kind not in _KINDS:
        raise ArtifactValidationError("kind must be indicator, oscillator, or construct")
    if not isinstance(tool_key, str):
        raise ArtifactValidationError("tool_key must be a string")
    if canonicalize_tool_key(tool_key) != tool_key:
        raise ArtifactValidationError("tool_key must be canonical")
    try:
        spec = get_financial_tool_spec(tool_key)
    except KeyError as exc:
        raise ArtifactValidationError(f"unknown tool_key: {tool_key}") from exc
    if spec.kind != kind:
        raise ArtifactValidationError("kind does not match tool_key")


def _validate_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ArtifactValidationError(f"{field_name} must be a lowercase SHA-256")


class _CanonicalArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(os.path.abspath(root))
        self._resolved_root = self._root.resolve(strict=False)
        self._failure_hook: _FailureHook | None = None
        self._assert_safe(self._root)
        if self._root.exists() and not self._root.is_dir():
            raise ArtifactValidationError("historical_root must be a directory")

    def artifact_dir(self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str) -> Path:
        _validate_kind_tool(kind, tool_key)
        _validate_id(artifact_id, "artifact_id")
        return self._assert_safe(
            _market_root(self._root, market_id) / "artifacts" / kind / tool_key / artifact_id
        )

    def recipe_path(self, market_id: MarketId, kind: str, tool_key: str, recipe_id: str) -> Path:
        _validate_kind_tool(kind, tool_key)
        _validate_id(recipe_id, "recipe_id")
        return self._assert_safe(
            _market_root(self._root, market_id)
            / "recipes"
            / kind
            / tool_key
            / f"{recipe_id}.json"
        )

    def write_artifact(
        self,
        final_dir: Path,
        *,
        values_bytes: bytes,
        analysis_bytes: bytes | None,
        metadata_bytes: bytes,
        pre_publication: Callable[[], None] | None = None,
    ) -> None:
        final_dir = self._assert_safe(final_dir)
        if final_dir.exists():
            raise ArtifactAlreadyExistsError(f"artifact already exists: {final_dir.name}")
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe(final_dir.parent)
        staging = final_dir.with_name(f".staging-{uuid4().hex}")
        staging.mkdir()
        self._assert_safe(staging)
        try:
            self._fail("before_values_write")
            _write_bytes(self._assert_safe(staging / "values.csv"), values_bytes)
            self._fail("after_values_write")
            if analysis_bytes is not None:
                self._fail("during_analysis_write")
                _write_bytes(self._assert_safe(staging / "analysis.json"), analysis_bytes)
            self._fail("during_metadata_write")
            _write_bytes(self._assert_safe(staging / "artifact.meta.json"), metadata_bytes)
            self._fail("during_artifact_publication")
            self._assert_safe(staging)
            self._assert_safe(final_dir)
            self._fail("before_native_artifact_publication")
            if pre_publication is not None:
                pre_publication()
            _publish_directory_no_replace(staging, final_dir)
        except Exception:
            _remove_exact_staging_dir(staging, self._assert_safe)
            raise

    def write_recipe(self, path: Path, payload: bytes) -> bool:
        path = self._assert_safe(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe(path.parent)
        if path.exists():
            self._assert_safe(path)
            if not path.is_file():
                raise ArtifactIdentityCollisionError(f"recipe identity collision: {path.stem}")
            existing = path.read_bytes()
            if existing == payload:
                return False
            raise ArtifactIdentityCollisionError(f"recipe identity collision: {path.stem}")
        temporary = path.with_name(f".staging-{uuid4().hex}.json")
        try:
            _write_bytes(self._assert_safe(temporary), payload)
            self._fail("during_recipe_publication")
            self._assert_safe(temporary)
            self._assert_safe(path.parent)
            self._assert_safe(path)
            try:
                os.link(temporary, path)
            except FileExistsError:
                self._assert_safe(path)
                if not path.is_file():
                    raise ArtifactIdentityCollisionError(
                        f"recipe identity collision: {path.stem}"
                    )
                existing = path.read_bytes()
                if existing == payload:
                    return False
                raise ArtifactIdentityCollisionError(f"recipe identity collision: {path.stem}")
            return True
        finally:
            self._assert_safe(temporary)
            temporary.unlink(missing_ok=True)

    def read_recipe_bytes(self, path: Path) -> bytes:
        path = self._assert_safe(path)
        if not path.is_file():
            raise ArtifactNotFoundError(f"recipe not found: {path.stem}")
        return path.read_bytes()

    def read_artifact_bytes(self, directory: Path) -> tuple[bytes, bytes | None, bytes]:
        directory = self._assert_safe(directory)
        if not directory.is_dir():
            raise ArtifactNotFoundError(f"artifact not found: {directory.name}")
        entries = tuple(directory.iterdir())
        for entry in entries:
            self._assert_safe(entry)
        names = {entry.name for entry in entries}
        if names not in (
            {"values.csv", "artifact.meta.json"},
            {"values.csv", "artifact.meta.json", "analysis.json"},
        ) or any(not entry.is_file() for entry in entries):
            raise ArtifactValidationError("artifact directory payload inventory is invalid")
        metadata_path = directory / "artifact.meta.json"
        values_path = directory / "values.csv"
        analysis_path = directory / "analysis.json"
        return values_path.read_bytes(), analysis_path.read_bytes() if analysis_path.is_file() else None, metadata_path.read_bytes()

    def iter_recipe_paths(
        self, market_id: MarketId, *, kind: str | None = None, tool_key: str | None = None
    ) -> Iterator[Path]:
        _validate_catalog_filters(kind, tool_key)
        root = _market_root(self._root, market_id) / "recipes"
        self._assert_safe(root)
        for kind_dir in _selected_kind_dirs(root, kind, self._assert_safe):
            for tool_dir in _selected_tool_dirs(kind_dir, tool_key, self._assert_safe):
                paths: list[Path] = []
                for path in tool_dir.iterdir():
                    self._assert_safe(path)
                    if path.is_file() and path.suffix == ".json":
                        paths.append(path)
                yield from sorted(paths)

    def iter_artifact_dirs(
        self, market_id: MarketId, *, kind: str | None = None, tool_key: str | None = None
    ) -> Iterator[Path]:
        _validate_catalog_filters(kind, tool_key)
        root = _market_root(self._root, market_id) / "artifacts"
        self._assert_safe(root)
        for kind_dir in _selected_kind_dirs(root, kind, self._assert_safe):
            for tool_dir in _selected_tool_dirs(kind_dir, tool_key, self._assert_safe):
                paths: list[Path] = []
                for path in tool_dir.iterdir():
                    self._assert_safe(path)
                    if path.is_dir():
                        paths.append(path)
                yield from sorted(paths)

    def find_artifact_dirs(self, market_id: MarketId, artifact_id: str) -> tuple[Path, ...]:
        _validate_id(artifact_id, "artifact_id")
        return tuple(path for path in self.iter_artifact_dirs(market_id) if path.name == artifact_id)

    def delete_artifact_dir(self, directory: Path) -> None:
        directory = self._assert_safe(directory)
        if not directory.is_dir():
            raise ArtifactNotFoundError(f"artifact not found: {directory.name}")
        allowed = {"values.csv", "artifact.meta.json", "analysis.json"}
        entries = tuple(directory.iterdir())
        for entry in entries:
            self._assert_safe(entry)
        if any(not entry.is_file() or entry.name not in allowed for entry in entries):
            raise ArtifactValidationError("artifact directory contains unexpected entries")
        self._assert_safe(directory)
        for name in ("values.csv", "analysis.json", "artifact.meta.json"):
            target = self._assert_safe(directory / name)
            target.unlink(missing_ok=True)
        directory.rmdir()

    def delete_recipe_file(self, path: Path) -> None:
        path = self._assert_safe(path)
        if not path.is_file():
            raise ArtifactNotFoundError(f"recipe not found: {path.stem}")
        self._assert_safe(path)
        path.unlink()

    def _fail(self, stage: str) -> None:
        if self._failure_hook is not None:
            self._failure_hook(stage)

    def _assert_safe(self, path: Path) -> Path:
        candidate = Path(os.path.abspath(path))
        try:
            relative = candidate.relative_to(self._root)
        except ValueError as exc:
            raise ArtifactValidationError("storage path escapes historical_root") from exc
        if _is_link_or_junction(self._root):
            raise ArtifactValidationError("historical_root must not be a link or junction")
        current = self._root
        for part in relative.parts:
            current /= part
            if _is_link_or_junction(current):
                raise ArtifactValidationError("storage paths must not contain links or junctions")
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self._resolved_root)
        except ValueError as exc:
            raise ArtifactValidationError("resolved storage path escapes historical_root") from exc
        return candidate


def _selected_kind_dirs(
    root: Path, kind: str | None, safety: _SafetyCheck
) -> tuple[Path, ...]:
    if kind is not None:
        if kind not in _KINDS:
            raise ArtifactValidationError("invalid kind filter")
        candidate = safety(root / kind)
        return (candidate,) if candidate.is_dir() else ()
    if not root.is_dir():
        return ()
    paths: list[Path] = []
    for path in root.iterdir():
        safety(path)
        if path.is_dir() and path.name in _KINDS:
            paths.append(path)
    return tuple(sorted(paths))


def _validate_catalog_filters(kind: str | None, tool_key: str | None) -> None:
    if kind is not None:
        if not isinstance(kind, str):
            raise ArtifactValidationError("kind filter must be a string or None")
        if kind not in _KINDS:
            raise ArtifactValidationError("invalid kind filter")
    if tool_key is None:
        return
    if not isinstance(tool_key, str):
        raise ArtifactValidationError("tool_key filter must be a string or None")
    if canonicalize_tool_key(tool_key) != tool_key:
        raise ArtifactValidationError("tool_key filter must be canonical")
    try:
        get_financial_tool_spec(tool_key)
    except KeyError as exc:
        raise ArtifactValidationError(f"unknown tool_key: {tool_key}") from exc


def _selected_tool_dirs(
    kind_dir: Path, tool_key: str | None, safety: _SafetyCheck
) -> tuple[Path, ...]:
    if tool_key is not None:
        if canonicalize_tool_key(tool_key) != tool_key:
            raise ArtifactValidationError("tool_key filter must be canonical")
        try:
            spec = get_financial_tool_spec(tool_key)
        except KeyError as exc:
            raise ArtifactValidationError(f"unknown tool_key: {tool_key}") from exc
        if spec.kind != kind_dir.name:
            return ()
        candidate = safety(kind_dir / tool_key)
        return (candidate,) if candidate.is_dir() else ()
    paths: list[Path] = []
    for path in kind_dir.iterdir():
        safety(path)
        if path.is_dir() and canonicalize_tool_key(path.name) == path.name:
            paths.append(path)
    return tuple(sorted(paths))


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _remove_exact_staging_dir(directory: Path, safety: _SafetyCheck) -> None:
    safety(directory)
    if not directory.exists():
        return
    allowed = {"values.csv", "artifact.meta.json", "analysis.json"}
    entries = tuple(directory.iterdir())
    for entry in entries:
        safety(entry)
    if any(not entry.is_file() or entry.name not in allowed for entry in entries):
        raise ArtifactValidationError("staging directory contains unexpected entries")
    for entry in entries:
        entry.unlink()
    directory.rmdir()


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _publish_directory_no_replace(source: Path, destination: Path) -> None:
    if os.name == "nt":
        try:
            os.rename(source, destination)
        except OSError as exc:
            if isinstance(exc, FileExistsError) or getattr(exc, "winerror", None) == 183:
                raise ArtifactAlreadyExistsError(
                    f"artifact already exists: {destination.name}"
                ) from exc
            raise
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "renameat2 is unavailable for no-replace publication")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise ArtifactAlreadyExistsError(
                f"artifact already exists: {destination.name}"
            )
        raise OSError(error_number, os.strerror(error_number), str(destination))
    raise OSError(errno.ENOTSUP, "native no-replace directory publication is unsupported")
