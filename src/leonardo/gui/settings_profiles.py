"""Allowlisted GUI settings profiles for production settings inspection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from leonardo.gui.metadata import load_metadata_document


MAIN_WINDOW_SETTINGS_PROFILE_ID = "main_window.window"

_WINDOW_METADATA_DIR = Path(__file__).resolve().parent / "metadata" / "windows"
_ALLOWED_SETTINGS_PROFILES = (
    (MAIN_WINDOW_SETTINGS_PROFILE_ID, _WINDOW_METADATA_DIR / "main_window.window.toml"),
)


@dataclass(frozen=True)
class GuiSettingsProfileRef:
    """
    Reference to one source metadata profile exposed to the settings inspector.

    The reference identifies the metadata source file that composition may use
    to build a single-profile settings inspector. It does not include resolved
    overrides, Qt objects, or runtime state.
    """

    metadata_id: str
    title: str
    metadata_path: Path
    owner_area: str | None = None
    logical_kind: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.metadata_id, "metadata_id")
        _validate_non_empty_string(self.title, "title")
        if not isinstance(self.metadata_path, Path):
            raise TypeError("metadata_path must be a Path")
        _validate_optional_string(self.owner_area, "owner_area")
        _validate_optional_string(self.logical_kind, "logical_kind")


class GuiSettingsProfileProvider:
    """
    Provide explicitly approved GUI metadata profiles for settings inspection.

    The provider is intentionally allowlist-based. It does not discover window
    metadata by scanning the metadata directory because test-only and future
    profiles may exist before they are production settings-inspector surfaces.
    """

    def list_profiles(self) -> tuple[GuiSettingsProfileRef, ...]:
        """Return production settings profiles in deterministic allowlist order."""

        return tuple(
            self.get_profile(metadata_id)
            for metadata_id, _metadata_path in _ALLOWED_SETTINGS_PROFILES
        )

    def get_profile(self, metadata_id: str) -> GuiSettingsProfileRef:
        """Return the allowlisted profile reference for a metadata identifier."""

        _validate_non_empty_string(metadata_id, "metadata_id")
        for allowed_metadata_id, metadata_path in _ALLOWED_SETTINGS_PROFILES:
            if metadata_id == allowed_metadata_id:
                return _load_profile_ref(metadata_id, metadata_path)
        raise KeyError(f"Unknown settings profile: {metadata_id}")


def _load_profile_ref(metadata_id: str, metadata_path: Path) -> GuiSettingsProfileRef:
    result = load_metadata_document(metadata_path)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid GUI settings profile: {messages}")
    if result.document.metadata_id != metadata_id:
        raise ValueError(
            "GUI settings profile allowlist metadata ID mismatch: "
            f"expected {metadata_id}, got {result.document.metadata_id}"
        )
    return GuiSettingsProfileRef(
        metadata_id=result.document.metadata_id,
        title=result.document.title,
        metadata_path=metadata_path,
        owner_area=_optional_metadata_string(result.document.metadata, "owner_area"),
        logical_kind=_optional_metadata_string(result.document.metadata, "logical_kind"),
    )


def _optional_metadata_string(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"metadata.{key} must be a string")
    _validate_non_empty_string(value, f"metadata.{key}")
    return value


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)
