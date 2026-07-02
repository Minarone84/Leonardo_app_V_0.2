"""Declarative GUI metadata contracts.

The models in this module describe GUI identities, default preferences, safe
settings exposure, and resolved profile state. They do not contain executable
behavior, Qt objects, service calls, persistence workflows, or Core registry
mutation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType


FORBIDDEN_EXECUTABLE_FIELD_NAMES = frozenset(
    {
        "callback",
        "handler",
        "command",
        "python",
        "expression",
        "import",
        "eval",
        "exec",
        "lambda",
        "callable",
        "script",
        "code",
    }
)

SAFE_SETTING_ROOTS = frozenset({"geometry", "display", "style", "tables", "reports"})


class GuiMetadataKind(str, Enum):
    """Supported declarative GUI metadata document kinds."""

    WINDOW = "window"
    DIALOG = "dialog"
    REPORT = "report"


class GuiMetadataIssueSeverity(str, Enum):
    """Structured severity for metadata validation and resolution issues."""

    ERROR = "error"
    WARNING = "warning"


class GuiMetadataIssueCode(str, Enum):
    """Stable issue codes emitted by metadata loading and resolution."""

    MISSING_REQUIRED_FIELD = "missing_required_field"
    UNKNOWN_FIELD = "unknown_field"
    FORBIDDEN_EXECUTABLE_FIELD = "forbidden_executable_field"
    DUPLICATE_ID = "duplicate_id"
    INVALID_SETTING_EXPOSURE_PATH = "invalid_setting_exposure_path"
    STALE_OVERRIDE_PATH = "stale_override_path"
    INVALID_OVERRIDE_VALUE = "invalid_override_value"
    INVALID_METADATA_VALUE = "invalid_metadata_value"


class ResolvedValueSource(str, Enum):
    """Origin of an effective profile value."""

    METADATA_DEFAULT = "metadata_default"
    USER_OVERRIDE = "user_override"
    SESSION_STATE = "session_state"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True)
class GuiMetadataIssue:
    """One structured metadata validation or resolution issue."""

    code: GuiMetadataIssueCode
    path: str
    message: str
    severity: GuiMetadataIssueSeverity = GuiMetadataIssueSeverity.ERROR

    def __post_init__(self) -> None:
        if not isinstance(self.code, GuiMetadataIssueCode):
            raise TypeError("code must be a GuiMetadataIssueCode")
        if not isinstance(self.severity, GuiMetadataIssueSeverity):
            raise TypeError("severity must be a GuiMetadataIssueSeverity")
        _validate_string(self.path, "path", allow_empty=True)
        _validate_non_empty_string(self.message, "message")


@dataclass(frozen=True)
class GuiMetadataReport:
    """Structured report emitted by metadata loading and resolution."""

    issues: tuple[GuiMetadataIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", _normalize_tuple(self.issues, GuiMetadataIssue, "issues"))

    @property
    def has_errors(self) -> bool:
        """Return whether the report contains an error severity issue."""

        return any(issue.severity is GuiMetadataIssueSeverity.ERROR for issue in self.issues)

    def with_issue(self, issue: GuiMetadataIssue) -> "GuiMetadataReport":
        """Return a report containing an additional issue."""

        if not isinstance(issue, GuiMetadataIssue):
            raise TypeError("issue must be a GuiMetadataIssue")
        return GuiMetadataReport(issues=(*self.issues, issue))

    def issues_by_code(self, code: GuiMetadataIssueCode) -> tuple[GuiMetadataIssue, ...]:
        """Return issues matching a stable issue code."""

        if not isinstance(code, GuiMetadataIssueCode):
            raise TypeError("code must be a GuiMetadataIssueCode")
        return tuple(issue for issue in self.issues if issue.code is code)


@dataclass(frozen=True)
class GuiGeometryDefaults:
    """Default geometry preferences for a GUI metadata profile."""

    width: int = 1024
    height: int = 768
    x: int | None = None
    y: int | None = None

    def __post_init__(self) -> None:
        _validate_positive_int(self.width, "width")
        _validate_positive_int(self.height, "height")
        _validate_optional_int(self.x, "x")
        _validate_optional_int(self.y, "y")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "width": self.width,
                "height": self.height,
                "x": self.x,
                "y": self.y,
            }
        )


@dataclass(frozen=True)
class GuiDisplayDefaults:
    """Default display preferences for a GUI metadata profile."""

    visible: bool = True
    enabled: bool = True
    theme: str = "system"

    def __post_init__(self) -> None:
        if not isinstance(self.visible, bool):
            raise TypeError("visible must be a bool")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        _validate_non_empty_string(self.theme, "theme")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "visible": self.visible,
                "enabled": self.enabled,
                "theme": self.theme,
            }
        )


@dataclass(frozen=True)
class GuiStyleDefaults:
    """Default style preferences for a GUI metadata profile."""

    font_size: int = 12
    density: str = "comfortable"

    def __post_init__(self) -> None:
        _validate_positive_int(self.font_size, "font_size")
        _validate_non_empty_string(self.density, "density")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "font_size": self.font_size,
                "density": self.density,
            }
        )


@dataclass(frozen=True)
class GuiActionReference:
    """Stable action identity reference without execution behavior."""

    action_id: str
    label: str

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.action_id, "action_id")
        _validate_non_empty_string(self.label, "label")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping({"action_id": self.action_id, "label": self.label})


@dataclass(frozen=True)
class GuiRegionReference:
    """Stable region identity reference for a GUI metadata profile."""

    region_id: str
    label: str

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.region_id, "region_id")
        _validate_non_empty_string(self.label, "label")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping({"region_id": self.region_id, "label": self.label})


@dataclass(frozen=True)
class GuiWidgetReference:
    """Stable widget identity reference without a framework widget instance."""

    widget_id: str
    region_id: str
    label: str
    widget_type: str

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.widget_id, "widget_id")
        _validate_non_empty_string(self.region_id, "region_id")
        _validate_non_empty_string(self.label, "label")
        _validate_non_empty_string(self.widget_type, "widget_type")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "widget_id": self.widget_id,
                "region_id": self.region_id,
                "label": self.label,
                "widget_type": self.widget_type,
            }
        )


@dataclass(frozen=True)
class GuiTableColumnDescriptor:
    """Declarative table column descriptor for display preferences."""

    column_id: str
    label: str
    visible: bool = True
    width: int | None = None
    order: int | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.column_id, "column_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.visible, bool):
            raise TypeError("visible must be a bool")
        _validate_optional_positive_int(self.width, "width")
        _validate_optional_int(self.order, "order")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "column_id": self.column_id,
                "label": self.label,
                "visible": self.visible,
                "width": self.width,
                "order": self.order,
            }
        )


@dataclass(frozen=True)
class GuiTableDescriptor:
    """Declarative table descriptor and column metadata."""

    table_id: str
    label: str
    columns: tuple[GuiTableColumnDescriptor, ...] = ()

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.table_id, "table_id")
        _validate_non_empty_string(self.label, "label")
        object.__setattr__(
            self,
            "columns",
            _normalize_tuple(self.columns, GuiTableColumnDescriptor, "columns"),
        )
        _validate_unique_ids((column.column_id for column in self.columns), "column_id")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation keyed by column ID."""

        return _readonly_mapping(
            {
                "table_id": self.table_id,
                "label": self.label,
                "columns": {
                    column.column_id: column.to_mapping()
                    for column in self.columns
                },
            }
        )


@dataclass(frozen=True)
class GuiReportSectionDescriptor:
    """Declarative report section descriptor for display preferences."""

    section_id: str
    label: str
    visible: bool = True
    order: int | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.section_id, "section_id")
        _validate_non_empty_string(self.label, "label")
        if not isinstance(self.visible, bool):
            raise TypeError("visible must be a bool")
        _validate_optional_int(self.order, "order")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "section_id": self.section_id,
                "label": self.label,
                "visible": self.visible,
                "order": self.order,
            }
        )


@dataclass(frozen=True)
class GuiReportDescriptor:
    """Declarative report descriptor and section metadata."""

    report_id: str
    label: str
    sections: tuple[GuiReportSectionDescriptor, ...] = ()

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.report_id, "report_id")
        _validate_non_empty_string(self.label, "label")
        object.__setattr__(
            self,
            "sections",
            _normalize_tuple(self.sections, GuiReportSectionDescriptor, "sections"),
        )
        _validate_unique_ids((section.section_id for section in self.sections), "section_id")

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation keyed by section ID."""

        return _readonly_mapping(
            {
                "report_id": self.report_id,
                "label": self.label,
                "sections": {
                    section.section_id: section.to_mapping()
                    for section in self.sections
                },
            }
        )


@dataclass(frozen=True)
class GuiSettingExposure:
    """Declarative exposure of a safe profile path to settings UI."""

    path: str
    label: str
    value_type: str
    description: str = ""

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.path, "path")
        _validate_non_empty_string(self.label, "label")
        _validate_non_empty_string(self.value_type, "value_type")
        _validate_string(self.description, "description", allow_empty=True)

    def to_mapping(self) -> Mapping[str, object]:
        """Return a defensive mapping representation."""

        return _readonly_mapping(
            {
                "path": self.path,
                "label": self.label,
                "value_type": self.value_type,
                "description": self.description,
            }
        )


@dataclass(frozen=True)
class GuiMetadataDocument:
    """Source metadata defaults for one window, dialog, or report profile."""

    metadata_id: str
    kind: GuiMetadataKind
    schema_version: str
    title: str
    label: str = ""
    geometry: GuiGeometryDefaults = field(default_factory=GuiGeometryDefaults)
    display: GuiDisplayDefaults = field(default_factory=GuiDisplayDefaults)
    style: GuiStyleDefaults = field(default_factory=GuiStyleDefaults)
    actions: tuple[GuiActionReference, ...] = ()
    regions: tuple[GuiRegionReference, ...] = ()
    widgets: tuple[GuiWidgetReference, ...] = ()
    tables: tuple[GuiTableDescriptor, ...] = ()
    reports: tuple[GuiReportDescriptor, ...] = ()
    settings: tuple[GuiSettingExposure, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.metadata_id, "metadata_id")
        if not isinstance(self.kind, GuiMetadataKind):
            raise TypeError("kind must be a GuiMetadataKind")
        _validate_non_empty_string(self.schema_version, "schema_version")
        _validate_non_empty_string(self.title, "title")
        _validate_string(self.label, "label", allow_empty=True)
        if not isinstance(self.geometry, GuiGeometryDefaults):
            raise TypeError("geometry must be a GuiGeometryDefaults")
        if not isinstance(self.display, GuiDisplayDefaults):
            raise TypeError("display must be a GuiDisplayDefaults")
        if not isinstance(self.style, GuiStyleDefaults):
            raise TypeError("style must be a GuiStyleDefaults")
        object.__setattr__(
            self,
            "actions",
            _normalize_tuple(self.actions, GuiActionReference, "actions"),
        )
        object.__setattr__(
            self,
            "regions",
            _normalize_tuple(self.regions, GuiRegionReference, "regions"),
        )
        object.__setattr__(
            self,
            "widgets",
            _normalize_tuple(self.widgets, GuiWidgetReference, "widgets"),
        )
        object.__setattr__(
            self,
            "tables",
            _normalize_tuple(self.tables, GuiTableDescriptor, "tables"),
        )
        object.__setattr__(
            self,
            "reports",
            _normalize_tuple(self.reports, GuiReportDescriptor, "reports"),
        )
        object.__setattr__(
            self,
            "settings",
            _normalize_tuple(self.settings, GuiSettingExposure, "settings"),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))
        _validate_unique_ids((action.action_id for action in self.actions), "action_id")
        _validate_unique_ids((region.region_id for region in self.regions), "region_id")
        _validate_unique_ids((widget.widget_id for widget in self.widgets), "widget_id")
        _validate_unique_ids((table.table_id for table in self.tables), "table_id")
        _validate_unique_ids((report.report_id for report in self.reports), "report_id")
        _validate_unique_ids((setting.path for setting in self.settings), "setting path")

    def to_profile_mapping(self) -> Mapping[str, object]:
        """Return source defaults as a defensive effective-profile mapping."""

        label = self.label if self.label else self.title
        return _readonly_mapping(
            {
                "identity": {
                    "metadata_id": self.metadata_id,
                    "kind": self.kind.value,
                    "schema_version": self.schema_version,
                    "title": self.title,
                    "label": label,
                },
                "geometry": self.geometry.to_mapping(),
                "display": self.display.to_mapping(),
                "style": self.style.to_mapping(),
                "actions": {
                    action.action_id: action.to_mapping()
                    for action in self.actions
                },
                "regions": {
                    region.region_id: region.to_mapping()
                    for region in self.regions
                },
                "widgets": {
                    widget.widget_id: widget.to_mapping()
                    for widget in self.widgets
                },
                "tables": {
                    table.table_id: table.to_mapping()
                    for table in self.tables
                },
                "reports": {
                    report.report_id: report.to_mapping()
                    for report in self.reports
                },
                "settings": {
                    setting.path: setting.to_mapping()
                    for setting in self.settings
                },
                "metadata": self.metadata,
            }
        )


@dataclass(frozen=True)
class GuiMetadataOverrideDocument:
    """Changed-only persistent preference overrides for a metadata profile."""

    metadata_id: str
    values: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "1"

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.metadata_id, "metadata_id")
        _validate_non_empty_string(self.schema_version, "schema_version")
        for path in self.values:
            _validate_non_empty_string(path, "override path")
        object.__setattr__(self, "values", _readonly_mapping(self.values))

    @property
    def changed_paths(self) -> tuple[str, ...]:
        """Return changed override paths in deterministic order."""

        return tuple(sorted(self.values))


@dataclass(frozen=True)
class GuiMetadataSessionState:
    """Non-persistent session state for one metadata profile."""

    metadata_id: str
    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.metadata_id, "metadata_id")
        for path in self.values:
            _validate_non_empty_string(path, "session state path")
        object.__setattr__(self, "values", _readonly_mapping(self.values))


@dataclass(frozen=True)
class ResolvedValueTrace:
    """Trace explaining one effective profile value."""

    path: str
    source: ResolvedValueSource
    effective_value: object | None = None
    default_value: object | None = None
    override_value: object | None = None
    session_value: object | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.path, "path")
        if not isinstance(self.source, ResolvedValueSource):
            raise TypeError("source must be a ResolvedValueSource")


@dataclass(frozen=True)
class EffectiveGuiMetadataProfile:
    """Resolved profile produced from metadata defaults and overlays."""

    metadata_id: str
    kind: GuiMetadataKind
    schema_version: str
    values: Mapping[str, object]
    traces: Mapping[str, ResolvedValueTrace]
    report: GuiMetadataReport = field(default_factory=GuiMetadataReport)

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.metadata_id, "metadata_id")
        if not isinstance(self.kind, GuiMetadataKind):
            raise TypeError("kind must be a GuiMetadataKind")
        _validate_non_empty_string(self.schema_version, "schema_version")
        for path, trace in self.traces.items():
            _validate_non_empty_string(path, "trace path")
            if not isinstance(trace, ResolvedValueTrace):
                raise TypeError("traces values must be ResolvedValueTrace")
        if not isinstance(self.report, GuiMetadataReport):
            raise TypeError("report must be a GuiMetadataReport")
        object.__setattr__(self, "values", _readonly_mapping(self.values))
        object.__setattr__(self, "traces", MappingProxyType(dict(self.traces)))

    def trace_for(self, path: str) -> ResolvedValueTrace:
        """Return the value trace for a path, or a missing trace."""

        _validate_non_empty_string(path, "path")
        trace = self.traces.get(path)
        if trace is not None:
            return trace
        return ResolvedValueTrace(path=path, source=ResolvedValueSource.MISSING)


def path_exists(values: Mapping[str, object], path: str) -> bool:
    """Return whether a dotted path exists in a profile mapping."""

    return get_path_value(values, path)[0]


def is_profile_leaf_path(values: Mapping[str, object], path: str) -> bool:
    """Return whether a dotted path resolves to a scalar profile value."""

    found, value = get_path_value(values, path)
    return found and not isinstance(value, Mapping)


def is_safe_setting_path(values: Mapping[str, object], path: str) -> bool:
    """Return whether a settings exposure path targets a safe profile leaf."""

    parts = split_profile_path(path)
    if not parts or parts[0] not in SAFE_SETTING_ROOTS:
        return False
    return is_profile_leaf_path(values, path)


def get_path_value(values: Mapping[str, object], path: str) -> tuple[bool, object | None]:
    """Resolve a dotted path from a profile mapping."""

    parts = split_profile_path(path)
    current: object = values
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def split_profile_path(path: str) -> tuple[str, ...]:
    """Split and validate a dotted profile path."""

    _validate_non_empty_string(path, "path")
    parts = tuple(part.strip() for part in path.split("."))
    if not all(parts):
        raise ValueError("path must not contain empty components")
    return parts


def _normalize_tuple(values: Sequence[object], item_type: type, field_name: str) -> tuple:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{field_name} must be a sequence")
    normalized = tuple(values)
    for value in normalized:
        if not isinstance(value, item_type):
            raise TypeError(f"{field_name} entries must be {item_type.__name__}")
    return normalized


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("mapping keys must be strings")
        normalized[key] = _readonly_value(item)
    return MappingProxyType(normalized)


def _readonly_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _readonly_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_readonly_value(item) for item in value)
    return value


def _validate_string(value: str, field_name: str, *, allow_empty: bool) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    _validate_string(value, field_name, allow_empty=False)


def _validate_positive_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an int")
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


def _validate_optional_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an int")


def _validate_optional_positive_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    _validate_positive_int(value, field_name)


def _validate_unique_ids(values: Sequence[str] | object, field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"Duplicate {field_name}: {value}")
        seen.add(value)
