"""Production settings inspector viewmodel for GUI metadata preferences.

The viewmodel exposes metadata-declared settings as rows that a GUI dialog can
render later. It owns local edit state and coordinates changed-only persistence
through the GUI metadata override store. It does not import Qt, construct
windows, mutate source metadata, or depend on Core services.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataDocument,
    GuiMetadataIssue,
    GuiMetadataIssueCode,
    GuiMetadataOverrideDocument,
    GuiMetadataOverrideStore,
    GuiMetadataOverrideStoreDiagnostic,
    GuiMetadataOverrideStoreResult,
    GuiMetadataResolver,
    GuiSettingExposure,
    ResolvedValueSource,
)
from leonardo.gui.metadata.models import get_path_value, split_profile_path


_SUPPORTED_VALUE_TYPES = frozenset({"integer", "boolean", "string"})


class GuiSettingsInspectorRowSource(str, Enum):
    """Viewmodel-level source for one settings row."""

    DEFAULT = "default"
    OVERRIDE = "override"
    DIRTY = "dirty"
    INVALID = "invalid"


@dataclass(frozen=True)
class GuiSettingsInspectorDiagnostic:
    """Structured diagnostic exposed by the settings inspector viewmodel."""

    code: str
    message: str
    path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("message must be a non-empty string")
        if not isinstance(self.path, str):
            raise TypeError("path must be a string")


@dataclass(frozen=True)
class GuiSettingsParseResult:
    """Result from parsing a user-provided settings value."""

    value: object | None = None
    diagnostics: tuple[GuiSettingsInspectorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def ok(self) -> bool:
        """Return whether parsing and validation completed without diagnostics."""

        return not self.diagnostics


@dataclass(frozen=True)
class GuiSettingsInspectorResult:
    """Result from a settings viewmodel persistence operation."""

    metadata_id: str
    diagnostics: tuple[GuiSettingsInspectorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.metadata_id, str) or not self.metadata_id:
            raise ValueError("metadata_id must be a non-empty string")
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def ok(self) -> bool:
        """Return whether the operation completed without diagnostics."""

        return not self.diagnostics


@dataclass(frozen=True)
class GuiSettingsInspectorRow:
    """One metadata-declared setting exposed to a future settings UI."""

    path: str
    label: str
    value_type: str
    description: str
    default_value: object | None
    effective_value: object | None
    override_value: object | None
    source: GuiSettingsInspectorRowSource
    dirty: bool
    diagnostics: tuple[GuiSettingsInspectorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class GuiSettingsInspectorViewModel:
    """
    Coordinate non-Qt inspection and persistence for metadata-exposed settings.

    The viewmodel lists only settings declared by the source metadata document.
    Local edits update pending override state and are validated through
    `GuiMetadataResolver`; disk writes occur only through explicit save/reset
    methods on the injected `GuiMetadataOverrideStore`.
    """

    def __init__(
        self,
        metadata_document: GuiMetadataDocument,
        override_store: GuiMetadataOverrideStore,
        *,
        override_load_result: GuiMetadataOverrideStoreResult | None = None,
        resolver: GuiMetadataResolver | None = None,
    ) -> None:
        if not isinstance(metadata_document, GuiMetadataDocument):
            raise TypeError("metadata_document must be a GuiMetadataDocument")
        if not isinstance(override_store, GuiMetadataOverrideStore):
            raise TypeError("override_store must be a GuiMetadataOverrideStore")
        if resolver is not None and not isinstance(resolver, GuiMetadataResolver):
            raise TypeError("resolver must be a GuiMetadataResolver or None")

        self._document = metadata_document
        self._override_store = override_store
        self._resolver = resolver if resolver is not None else GuiMetadataResolver()
        self._load_result = (
            override_load_result
            if override_load_result is not None
            else override_store.load(metadata_document.metadata_id)
        )
        self._loaded_overrides = self._document_from_load_result(self._load_result)
        self._pending_values: dict[str, object] = dict(self._loaded_overrides.values)
        self._loaded_values: dict[str, object] = dict(self._loaded_overrides.values)
        self._edit_diagnostics: dict[str, tuple[GuiSettingsInspectorDiagnostic, ...]] = {}

    @property
    def metadata_id(self) -> str:
        """Return the metadata profile identifier inspected by this viewmodel."""

        return self._document.metadata_id

    @property
    def diagnostics(self) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
        """Return non-field diagnostics from the current override load state."""

        return _store_diagnostics(self._load_result.errors + self._load_result.warnings)

    @property
    def rows(self) -> tuple[GuiSettingsInspectorRow, ...]:
        """Return settings rows in metadata declaration order."""

        return tuple(self._row_for_setting(setting) for setting in self._document.settings)

    @property
    def effective_profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective profile for the current pending settings state."""

        return self._current_profile()

    def row_for_path(self, path: str) -> GuiSettingsInspectorRow:
        """Return one settings row for a metadata-declared setting path."""

        setting = self._setting_for_path(path)
        return self._row_for_setting(setting)

    def exposed_paths(self) -> tuple[str, ...]:
        """Return metadata-declared setting paths in declaration order."""

        return tuple(setting.path for setting in self._document.settings)

    def edit_value(self, path: str, value: object) -> GuiSettingsParseResult:
        """
        Parse, validate, and stage a local edit for one exposed setting.

        The method updates only in-memory pending override state. It never
        writes override files and never mutates the source metadata document.
        """

        setting = self._setting_for_path(path)
        parsed = self._parse_value(setting, value)
        if not parsed.ok:
            self._edit_diagnostics[path] = parsed.diagnostics
            return parsed

        pending = dict(self._pending_values)
        default_value = self._default_value(path)
        if parsed.value == default_value:
            pending.pop(path, None)
        else:
            pending[path] = parsed.value

        validation_diagnostics = self._validate_candidate(pending, path)
        if validation_diagnostics:
            self._edit_diagnostics[path] = validation_diagnostics
            return GuiSettingsParseResult(
                value=parsed.value,
                diagnostics=validation_diagnostics,
            )

        self._pending_values = pending
        self._edit_diagnostics.pop(path, None)
        return parsed

    def save(self) -> GuiSettingsInspectorResult:
        """Persist the current pending changed-only override document."""

        diagnostics = self._blocking_diagnostics()
        if diagnostics:
            return GuiSettingsInspectorResult(
                metadata_id=self.metadata_id,
                diagnostics=diagnostics,
            )

        candidate = GuiMetadataOverrideDocument(
            metadata_id=self.metadata_id,
            values=self._normalized_pending_values(),
        )
        result = self._override_store.save(candidate)
        if not result.ok:
            return GuiSettingsInspectorResult(
                metadata_id=self.metadata_id,
                diagnostics=_store_diagnostics(result.errors + result.warnings),
            )

        self._load_result = result
        self._loaded_overrides = self._document_from_load_result(result)
        self._loaded_values = dict(self._loaded_overrides.values)
        self._pending_values = dict(self._loaded_overrides.values)
        self._edit_diagnostics = {}
        return GuiSettingsInspectorResult(metadata_id=self.metadata_id)

    def reset_field(self, path: str) -> GuiSettingsInspectorResult:
        """Remove one override entry and reload viewmodel row state."""

        self._setting_for_path(path)
        result = self._override_store.reset_field(self.metadata_id, path)
        return self._reload_after_store_result(result)

    def reset_section(self, section_path: str) -> GuiSettingsInspectorResult:
        """Remove override entries under one section prefix and reload state."""

        split_profile_path(section_path)
        result = self._override_store.reset_section(self.metadata_id, section_path)
        return self._reload_after_store_result(result)

    def reset_profile(self) -> GuiSettingsInspectorResult:
        """Remove all persisted overrides for the inspected metadata profile."""

        result = self._override_store.reset_profile(self.metadata_id)
        return self._reload_after_store_result(result)

    def _reload_after_store_result(
        self,
        result: GuiMetadataOverrideStoreResult,
    ) -> GuiSettingsInspectorResult:
        if not result.ok:
            return GuiSettingsInspectorResult(
                metadata_id=self.metadata_id,
                diagnostics=_store_diagnostics(result.errors + result.warnings),
            )
        self._load_result = result
        self._loaded_overrides = self._document_from_load_result(result)
        self._loaded_values = dict(self._loaded_overrides.values)
        self._pending_values = dict(self._loaded_overrides.values)
        self._edit_diagnostics = {}
        return GuiSettingsInspectorResult(metadata_id=self.metadata_id)

    def _row_for_setting(self, setting: GuiSettingExposure) -> GuiSettingsInspectorRow:
        path = setting.path
        profile = self._current_profile()
        trace = profile.trace_for(path)
        found, default_value = get_path_value(self._document.to_profile_mapping(), path)
        effective_value = trace.effective_value if found else None
        override_value = self._pending_values.get(path)
        diagnostics = self._diagnostics_for_row(setting, profile)
        dirty = self._pending_values.get(path) != self._loaded_values.get(path)
        source = self._source_for_row(path, trace.source, dirty, diagnostics)

        return GuiSettingsInspectorRow(
            path=path,
            label=setting.label,
            value_type=setting.value_type,
            description=setting.description,
            default_value=default_value if found else None,
            effective_value=effective_value,
            override_value=override_value,
            source=source,
            dirty=dirty,
            diagnostics=diagnostics,
        )

    def _source_for_row(
        self,
        path: str,
        trace_source: ResolvedValueSource,
        dirty: bool,
        diagnostics: tuple[GuiSettingsInspectorDiagnostic, ...],
    ) -> GuiSettingsInspectorRowSource:
        if diagnostics or trace_source is ResolvedValueSource.INVALID:
            return GuiSettingsInspectorRowSource.INVALID
        if dirty:
            return GuiSettingsInspectorRowSource.DIRTY
        if path in self._pending_values or trace_source is ResolvedValueSource.USER_OVERRIDE:
            return GuiSettingsInspectorRowSource.OVERRIDE
        return GuiSettingsInspectorRowSource.DEFAULT

    def _diagnostics_for_row(
        self,
        setting: GuiSettingExposure,
        profile: EffectiveGuiMetadataProfile,
    ) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
        diagnostics: list[GuiSettingsInspectorDiagnostic] = []
        if setting.value_type not in _SUPPORTED_VALUE_TYPES:
            diagnostics.append(
                GuiSettingsInspectorDiagnostic(
                    code="unknown_value_type",
                    path=setting.path,
                    message=f"Unsupported setting value_type: {setting.value_type}",
                )
            )

        found, _ = get_path_value(self._document.to_profile_mapping(), setting.path)
        if not found:
            diagnostics.append(
                GuiSettingsInspectorDiagnostic(
                    code=GuiMetadataIssueCode.STALE_OVERRIDE_PATH.value,
                    path=setting.path,
                    message=f"Setting path does not exist in source metadata: {setting.path}",
                )
            )

        diagnostics.extend(self._edit_diagnostics.get(setting.path, ()))
        diagnostics.extend(_issue_diagnostics(profile.report.issues, setting.path))
        return tuple(_deduplicate_diagnostics(diagnostics))

    def _blocking_diagnostics(self) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
        diagnostics: list[GuiSettingsInspectorDiagnostic] = []
        for setting in self._document.settings:
            diagnostics.extend(self._diagnostics_for_row(setting, self._current_profile()))
        diagnostics.extend(_issue_diagnostics(self._current_profile().report.issues, ""))
        return tuple(_deduplicate_diagnostics(diagnostics))

    def _parse_value(
        self,
        setting: GuiSettingExposure,
        value: object,
    ) -> GuiSettingsParseResult:
        path = setting.path
        if setting.value_type == "integer":
            if isinstance(value, int) and not isinstance(value, bool):
                return GuiSettingsParseResult(value=value)
            if isinstance(value, str):
                text = value.strip()
                if text and (
                    text.isdigit()
                    or (text[0] in {"-", "+"} and text[1:].isdigit())
                ):
                    return GuiSettingsParseResult(value=int(text))
            return self._parse_error(path, "invalid_integer", f"Expected integer for {path}")

        if setting.value_type == "boolean":
            if isinstance(value, bool):
                return GuiSettingsParseResult(value=value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes"}:
                    return GuiSettingsParseResult(value=True)
                if normalized in {"false", "0", "no"}:
                    return GuiSettingsParseResult(value=False)
            return self._parse_error(path, "invalid_boolean", f"Expected boolean for {path}")

        if setting.value_type == "string":
            if isinstance(value, str):
                return GuiSettingsParseResult(value=value)
            return GuiSettingsParseResult(value=str(value))

        return self._parse_error(
            path,
            "unknown_value_type",
            f"Unsupported setting value_type: {setting.value_type}",
        )

    def _parse_error(
        self,
        path: str,
        code: str,
        message: str,
    ) -> GuiSettingsParseResult:
        return GuiSettingsParseResult(
            diagnostics=(GuiSettingsInspectorDiagnostic(code=code, path=path, message=message),)
        )

    def _validate_candidate(
        self,
        values: Mapping[str, object],
        path: str,
    ) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
        candidate = GuiMetadataOverrideDocument(
            metadata_id=self.metadata_id,
            values=values,
        )
        profile = self._resolver.resolve(self._document, candidate)
        return _issue_diagnostics(profile.report.issues, path)

    def _current_profile(self) -> EffectiveGuiMetadataProfile:
        return self._resolver.resolve(
            self._document,
            GuiMetadataOverrideDocument(
                metadata_id=self.metadata_id,
                values=self._normalized_pending_values(),
            ),
        )

    def _normalized_pending_values(self) -> dict[str, object]:
        values = dict(self._pending_values)
        for setting in self._document.settings:
            default_value = self._default_value(setting.path)
            if setting.path in values and values[setting.path] == default_value:
                values.pop(setting.path, None)
        return values

    def _default_value(self, path: str) -> object | None:
        found, value = get_path_value(self._document.to_profile_mapping(), path)
        return value if found else None

    def _setting_for_path(self, path: str) -> GuiSettingExposure:
        for setting in self._document.settings:
            if setting.path == path:
                return setting
        raise ValueError(f"Setting path is not exposed by metadata: {path}")

    def _document_from_load_result(
        self,
        result: GuiMetadataOverrideStoreResult,
    ) -> GuiMetadataOverrideDocument:
        if result.document is not None:
            return result.document
        return GuiMetadataOverrideDocument(metadata_id=self.metadata_id)


def _store_diagnostics(
    diagnostics: tuple[GuiMetadataOverrideStoreDiagnostic, ...],
) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
    return tuple(
        GuiSettingsInspectorDiagnostic(
            code=diagnostic.code,
            message=diagnostic.message,
        )
        for diagnostic in diagnostics
    )


def _issue_diagnostics(
    issues: tuple[GuiMetadataIssue, ...],
    path: str,
) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
    return tuple(
        GuiSettingsInspectorDiagnostic(
            code=issue.code.value,
            path=issue.path,
            message=issue.message,
        )
        for issue in issues
        if not path or issue.path == path
    )


def _deduplicate_diagnostics(
    diagnostics: list[GuiSettingsInspectorDiagnostic],
) -> tuple[GuiSettingsInspectorDiagnostic, ...]:
    seen: set[tuple[str, str, str]] = set()
    deduplicated: list[GuiSettingsInspectorDiagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.path, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(diagnostic)
    return tuple(deduplicated)
