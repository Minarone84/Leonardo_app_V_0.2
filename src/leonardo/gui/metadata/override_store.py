"""Durable JSON store for changed-only GUI metadata overrides."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from leonardo.gui.metadata.models import GuiMetadataOverrideDocument
from leonardo.gui.metadata.resolver import GuiMetadataResolver


OVERRIDE_FILE_SCHEMA_VERSION = "leonardo.gui.override.v1"
_SAFE_METADATA_ID_PATTERN = r"[A-Za-z0-9_.-]+"


@dataclass(frozen=True)
class GuiMetadataOverrideStoreDiagnostic:
    """Structured diagnostic produced by the GUI override store."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("message must be a non-empty string")


@dataclass(frozen=True)
class GuiMetadataOverrideStoreResult:
    """Result returned by GUI override store load and save operations."""

    metadata_id: str
    path: Path | None
    document: GuiMetadataOverrideDocument | None
    errors: tuple[GuiMetadataOverrideStoreDiagnostic, ...] = ()
    warnings: tuple[GuiMetadataOverrideStoreDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def ok(self) -> bool:
        """Return whether the operation completed without blocking errors."""

        return not self.errors

    @property
    def blockers(self) -> tuple[GuiMetadataOverrideStoreDiagnostic, ...]:
        """Return blocking diagnostics using the task-level result vocabulary."""

        return self.errors


class GuiMetadataOverrideStore:
    """
    Persist changed-only GUI metadata overrides under an injected root path.

    The store owns JSON file persistence for user preference overrides only. It
    does not load source metadata, resolve effective profiles, persist session
    state, import GUI windows, or depend on runtime services.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._resolver = GuiMetadataResolver()

    @property
    def root(self) -> Path:
        """Return the configured override storage root."""

        return self._root

    def path_for(self, metadata_id: str) -> Path:
        """Return the override file path for a safe metadata identifier."""

        _validate_safe_metadata_id(metadata_id)
        return self._root / f"{metadata_id}.override.json"

    def load(self, metadata_id: str) -> GuiMetadataOverrideStoreResult:
        """Load changed-only overrides for one metadata profile."""

        path_result = self._path_result(metadata_id)
        if path_result is not None:
            return path_result

        path = self.path_for(metadata_id)
        if not path.exists():
            return self._result(metadata_id, path, self._empty_document(metadata_id))

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            return self._invalid_file_result(
                metadata_id,
                path,
                "corrupt_json",
                f"Override file contains invalid JSON: {error.msg}",
            )
        except OSError as error:
            return self._invalid_file_result(
                metadata_id,
                path,
                "read_failed",
                f"Override file could not be read: {error}",
            )

        return self._document_from_payload(metadata_id, path, payload)

    def save(
        self,
        document: GuiMetadataOverrideDocument,
    ) -> GuiMetadataOverrideStoreResult:
        """Persist one changed-only override document."""

        if not isinstance(document, GuiMetadataOverrideDocument):
            raise TypeError("document must be a GuiMetadataOverrideDocument")

        path_result = self._path_result(document.metadata_id)
        if path_result is not None:
            return path_result

        path = self.path_for(document.metadata_id)
        if not document.values:
            return self._delete_empty_override(document.metadata_id, path)

        payload = {
            "schema_version": OVERRIDE_FILE_SCHEMA_VERSION,
            "metadata_id": document.metadata_id,
            "updated_at_ms": int(time.time_ns() // 1_000_000),
            "overrides": dict(document.values),
        }
        try:
            encoded = json.dumps(payload, indent=2, sort_keys=True)
        except (TypeError, ValueError) as error:
            return self._error_result(
                document.metadata_id,
                path,
                document,
                "write_failed",
                f"Override values are not JSON-serializable: {error}",
            )

        temp_path: Path | None = None
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._root,
                prefix=f".{document.metadata_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except OSError as error:
            if temp_path is not None:
                _unlink_if_exists(temp_path)
            return self._error_result(
                document.metadata_id,
                path,
                document,
                "write_failed",
                f"Override file could not be written: {error}",
            )

        return self._result(document.metadata_id, path, document)

    def reset_field(
        self,
        metadata_id: str,
        path: str,
    ) -> GuiMetadataOverrideStoreResult:
        """Remove one override entry from durable storage."""

        loaded = self.load(metadata_id)
        if not loaded.ok or loaded.document is None:
            return loaded
        return self.save(self._resolver.reset_field(loaded.document, path))

    def reset_section(
        self,
        metadata_id: str,
        section_path: str,
    ) -> GuiMetadataOverrideStoreResult:
        """Remove override entries under one section from durable storage."""

        loaded = self.load(metadata_id)
        if not loaded.ok or loaded.document is None:
            return loaded
        return self.save(self._resolver.reset_section(loaded.document, section_path))

    def reset_profile(self, metadata_id: str) -> GuiMetadataOverrideStoreResult:
        """Remove all persisted overrides for one metadata profile."""

        path_result = self._path_result(metadata_id)
        if path_result is not None:
            return path_result

        path = self.path_for(metadata_id)
        empty = self._empty_document(metadata_id)
        try:
            _unlink_if_exists(path)
        except OSError as error:
            return self._error_result(
                metadata_id,
                path,
                empty,
                "delete_failed",
                f"Override file could not be deleted: {error}",
            )
        return self._result(metadata_id, path, empty)

    def _document_from_payload(
        self,
        metadata_id: str,
        path: Path,
        payload: object,
    ) -> GuiMetadataOverrideStoreResult:
        if not isinstance(payload, dict):
            return self._invalid_file_result(
                metadata_id,
                path,
                "invalid_payload",
                "Override file JSON payload must be an object",
            )

        required = ("schema_version", "metadata_id", "updated_at_ms", "overrides")
        missing = tuple(field for field in required if field not in payload)
        if missing:
            return self._invalid_file_result(
                metadata_id,
                path,
                "missing_required_field",
                f"Override file is missing required fields: {', '.join(missing)}",
            )

        schema_version = payload["schema_version"]
        if schema_version != OVERRIDE_FILE_SCHEMA_VERSION:
            return self._invalid_file_result(
                metadata_id,
                path,
                "schema_mismatch",
                "Override file schema_version is not supported",
            )

        payload_metadata_id = payload["metadata_id"]
        if payload_metadata_id != metadata_id:
            return self._invalid_file_result(
                metadata_id,
                path,
                "metadata_id_mismatch",
                "Override file metadata_id does not match requested metadata_id",
            )

        updated_at_ms = payload["updated_at_ms"]
        if (
            not isinstance(updated_at_ms, int)
            or isinstance(updated_at_ms, bool)
            or updated_at_ms < 0
        ):
            return self._invalid_file_result(
                metadata_id,
                path,
                "invalid_updated_at",
                "Override file updated_at_ms must be a non-negative integer",
            )

        overrides = payload["overrides"]
        if not isinstance(overrides, dict):
            return self._invalid_file_result(
                metadata_id,
                path,
                "invalid_overrides",
                "Override file overrides must be an object",
            )

        try:
            document = GuiMetadataOverrideDocument(
                metadata_id=metadata_id,
                values=overrides,
            )
        except (TypeError, ValueError) as error:
            return self._invalid_file_result(
                metadata_id,
                path,
                "invalid_overrides",
                f"Override file overrides are invalid: {error}",
            )
        return self._result(metadata_id, path, document)

    def _delete_empty_override(
        self,
        metadata_id: str,
        path: Path,
    ) -> GuiMetadataOverrideStoreResult:
        document = self._empty_document(metadata_id)
        try:
            _unlink_if_exists(path)
        except OSError as error:
            return self._error_result(
                metadata_id,
                path,
                document,
                "delete_failed",
                f"Empty override file could not be deleted: {error}",
            )
        return self._result(metadata_id, path, document)

    def _path_result(self, metadata_id: str) -> GuiMetadataOverrideStoreResult | None:
        try:
            self.path_for(metadata_id)
        except (TypeError, ValueError) as error:
            return GuiMetadataOverrideStoreResult(
                metadata_id=str(metadata_id),
                path=None,
                document=None,
                errors=(
                    GuiMetadataOverrideStoreDiagnostic(
                        code="unsafe_metadata_id",
                        message=str(error),
                    ),
                ),
            )
        return None

    def _invalid_file_result(
        self,
        metadata_id: str,
        path: Path,
        code: str,
        message: str,
    ) -> GuiMetadataOverrideStoreResult:
        return self._error_result(
            metadata_id,
            path,
            self._empty_document(metadata_id),
            code,
            message,
        )

    def _error_result(
        self,
        metadata_id: str,
        path: Path | None,
        document: GuiMetadataOverrideDocument | None,
        code: str,
        message: str,
    ) -> GuiMetadataOverrideStoreResult:
        return GuiMetadataOverrideStoreResult(
            metadata_id=metadata_id,
            path=path,
            document=document,
            errors=(GuiMetadataOverrideStoreDiagnostic(code=code, message=message),),
        )

    def _result(
        self,
        metadata_id: str,
        path: Path,
        document: GuiMetadataOverrideDocument,
    ) -> GuiMetadataOverrideStoreResult:
        return GuiMetadataOverrideStoreResult(
            metadata_id=metadata_id,
            path=path,
            document=document,
        )

    def _empty_document(self, metadata_id: str) -> GuiMetadataOverrideDocument:
        return GuiMetadataOverrideDocument(metadata_id=metadata_id, values={})


def _validate_safe_metadata_id(metadata_id: str) -> None:
    if not isinstance(metadata_id, str):
        raise TypeError("metadata_id must be a string")
    if not metadata_id:
        raise ValueError("metadata_id must be a non-empty safe identifier")
    if ".." in metadata_id:
        raise ValueError("metadata_id must not contain '..'")
    if re.fullmatch(_SAFE_METADATA_ID_PATTERN, metadata_id) is None:
        raise ValueError(
            "metadata_id must contain only letters, numbers, underscore, dot, or dash"
        )


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
