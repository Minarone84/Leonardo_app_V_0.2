"""TOML loading and validation for declarative GUI metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib

from leonardo.gui.metadata.models import (
    FORBIDDEN_EXECUTABLE_FIELD_NAMES,
    GuiActionReference,
    GuiDisplayDefaults,
    GuiGeometryDefaults,
    GuiMetadataDocument,
    GuiMetadataIssue,
    GuiMetadataIssueCode,
    GuiMetadataKind,
    GuiMetadataReport,
    GuiRegionReference,
    GuiReportDescriptor,
    GuiReportSectionDescriptor,
    GuiSettingExposure,
    GuiStyleDefaults,
    GuiTableColumnDescriptor,
    GuiTableDescriptor,
    GuiWidgetReference,
    is_safe_setting_path,
)


_TOP_LEVEL_FIELDS = frozenset(
    {
        "metadata_id",
        "kind",
        "schema_version",
        "title",
        "label",
        "geometry",
        "display",
        "style",
        "actions",
        "regions",
        "widgets",
        "tables",
        "reports",
        "settings",
        "metadata",
    }
)
_REQUIRED_TOP_LEVEL_FIELDS = frozenset({"metadata_id", "kind", "schema_version", "title"})
_GEOMETRY_FIELDS = frozenset({"width", "height", "x", "y"})
_DISPLAY_FIELDS = frozenset({"visible", "enabled", "theme"})
_STYLE_FIELDS = frozenset({"font_size", "density"})
_ACTION_FIELDS = frozenset({"action_id", "label"})
_REGION_FIELDS = frozenset({"region_id", "label"})
_WIDGET_FIELDS = frozenset({"widget_id", "region_id", "label", "widget_type"})
_TABLE_FIELDS = frozenset({"table_id", "label", "columns"})
_TABLE_COLUMN_FIELDS = frozenset({"column_id", "label", "visible", "width", "order"})
_REPORT_FIELDS = frozenset({"report_id", "label", "sections"})
_REPORT_SECTION_FIELDS = frozenset({"section_id", "label", "visible", "order"})
_SETTING_FIELDS = frozenset({"path", "label", "value_type", "description"})


@dataclass(frozen=True)
class GuiMetadataLoadResult:
    """Result of loading and validating a GUI metadata source document."""

    document: GuiMetadataDocument | None
    report: GuiMetadataReport

    def __post_init__(self) -> None:
        if self.document is not None and not isinstance(self.document, GuiMetadataDocument):
            raise TypeError("document must be a GuiMetadataDocument or None")
        if not isinstance(self.report, GuiMetadataReport):
            raise TypeError("report must be a GuiMetadataReport")


def load_metadata_document(path: str | Path) -> GuiMetadataLoadResult:
    """Load a GUI metadata document from a TOML file.

    The loader only reads source metadata. It does not persist override files,
    construct widgets, import Qt, or call Core services.
    """

    source_path = Path(path)
    try:
        with source_path.open("rb") as source_file:
            data = tomllib.load(source_file)
    except tomllib.TOMLDecodeError as error:
        issue = GuiMetadataIssue(
            code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
            path=str(source_path),
            message=f"Invalid TOML metadata: {error}",
        )
        return GuiMetadataLoadResult(document=None, report=GuiMetadataReport((issue,)))

    return metadata_document_from_mapping(data)


def metadata_document_from_mapping(data: Mapping[str, object]) -> GuiMetadataLoadResult:
    """Validate and build a metadata document from a mapping."""

    issues: list[GuiMetadataIssue] = []
    if not isinstance(data, Mapping):
        return _invalid_root_result()

    _collect_forbidden_field_issues(data, "", issues)
    _collect_unknown_fields(data, _TOP_LEVEL_FIELDS, "", issues)
    _collect_missing_required_fields(data, _REQUIRED_TOP_LEVEL_FIELDS, "", issues)

    if issues:
        return GuiMetadataLoadResult(document=None, report=GuiMetadataReport(tuple(issues)))

    try:
        geometry = GuiGeometryDefaults(**_optional_section(data, "geometry", _GEOMETRY_FIELDS, issues))
        display = GuiDisplayDefaults(**_optional_section(data, "display", _DISPLAY_FIELDS, issues))
        style = GuiStyleDefaults(**_optional_section(data, "style", _STYLE_FIELDS, issues))
        actions = tuple(_parse_items(data, "actions", _ACTION_FIELDS, _action_from_mapping, issues))
        regions = tuple(_parse_items(data, "regions", _REGION_FIELDS, _region_from_mapping, issues))
        widgets = tuple(_parse_items(data, "widgets", _WIDGET_FIELDS, _widget_from_mapping, issues))
        tables = tuple(_parse_items(data, "tables", _TABLE_FIELDS, _table_from_mapping, issues))
        reports = tuple(_parse_items(data, "reports", _REPORT_FIELDS, _report_from_mapping, issues))
        settings = tuple(_parse_items(data, "settings", _SETTING_FIELDS, _setting_from_mapping, issues))
        _collect_duplicate_ids((action.action_id for action in actions), "actions.action_id", issues)
        _collect_duplicate_ids((region.region_id for region in regions), "regions.region_id", issues)
        _collect_duplicate_ids((widget.widget_id for widget in widgets), "widgets.widget_id", issues)
        _collect_duplicate_ids((table.table_id for table in tables), "tables.table_id", issues)
        _collect_duplicate_ids((report.report_id for report in reports), "reports.report_id", issues)
        _collect_duplicate_ids((setting.path for setting in settings), "settings.path", issues)
        kind = GuiMetadataKind(_string_field(data, "kind"))
        document = GuiMetadataDocument(
            metadata_id=_string_field(data, "metadata_id"),
            kind=kind,
            schema_version=_string_field(data, "schema_version"),
            title=_string_field(data, "title"),
            label=_optional_string_field(data, "label"),
            geometry=geometry,
            display=display,
            style=style,
            actions=actions,
            regions=regions,
            widgets=widgets,
            tables=tables,
            reports=reports,
            settings=settings,
            metadata=_metadata_section(data, issues),
        )
    except (TypeError, ValueError) as error:
        issues.append(
            GuiMetadataIssue(
                code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
                path="",
                message=str(error),
            )
        )
        return GuiMetadataLoadResult(document=None, report=GuiMetadataReport(tuple(issues)))

    profile_values = document.to_profile_mapping()
    for setting in settings:
        if not is_safe_setting_path(profile_values, setting.path):
            issues.append(
                GuiMetadataIssue(
                    code=GuiMetadataIssueCode.INVALID_SETTING_EXPOSURE_PATH,
                    path=f"settings.{setting.path}",
                    message=f"Setting exposure path is not a safe profile leaf: {setting.path}",
                )
            )

    report = GuiMetadataReport(tuple(issues))
    if report.has_errors:
        return GuiMetadataLoadResult(document=None, report=report)
    return GuiMetadataLoadResult(document=document, report=report)


def _invalid_root_result() -> GuiMetadataLoadResult:
    issue = GuiMetadataIssue(
        code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
        path="",
        message="metadata document must be a mapping",
    )
    return GuiMetadataLoadResult(document=None, report=GuiMetadataReport((issue,)))


def _optional_section(
    data: Mapping[str, object],
    key: str,
    allowed_fields: frozenset[str],
    issues: list[GuiMetadataIssue],
) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        issues.append(
            GuiMetadataIssue(
                code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
                path=key,
                message=f"{key} must be a table",
            )
        )
        return {}
    _collect_unknown_fields(value, allowed_fields, key, issues)
    return dict(value)


def _metadata_section(data: Mapping[str, object], issues: list[GuiMetadataIssue]) -> Mapping[str, object]:
    value = data.get("metadata", {})
    if not isinstance(value, Mapping):
        issues.append(
            GuiMetadataIssue(
                code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
                path="metadata",
                message="metadata must be a table",
            )
        )
        return {}
    return value


def _parse_items(
    data: Mapping[str, object],
    key: str,
    allowed_fields: frozenset[str],
    factory: object,
    issues: list[GuiMetadataIssue],
) -> Iterable[object]:
    value = data.get(key, ())
    if value in (None, ()):
        return ()
    if not isinstance(value, list):
        issues.append(
            GuiMetadataIssue(
                code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
                path=key,
                message=f"{key} must be an array of tables",
            )
        )
        return ()
    parsed: list[object] = []
    for index, item in enumerate(value):
        item_path = f"{key}.{index}"
        if not isinstance(item, Mapping):
            issues.append(
                GuiMetadataIssue(
                    code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
                    path=item_path,
                    message=f"{key} entries must be tables",
                )
            )
            continue
        _collect_unknown_fields(item, allowed_fields, item_path, issues)
        try:
            parsed.append(factory(item, item_path, issues))
        except (TypeError, ValueError) as error:
            issues.append(
                GuiMetadataIssue(
                    code=GuiMetadataIssueCode.INVALID_METADATA_VALUE,
                    path=item_path,
                    message=str(error),
                )
            )
    return tuple(parsed)


def _action_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiActionReference:
    if not _require_item_fields(item, frozenset({"action_id", "label"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    return GuiActionReference(action_id=item["action_id"], label=item["label"])


def _region_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiRegionReference:
    if not _require_item_fields(item, frozenset({"region_id", "label"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    return GuiRegionReference(region_id=item["region_id"], label=item["label"])


def _widget_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiWidgetReference:
    if not _require_item_fields(
        item,
        frozenset({"widget_id", "region_id", "label", "widget_type"}),
        path,
        issues,
    ):
        raise ValueError(f"Missing required fields for {path}")
    return GuiWidgetReference(
        widget_id=item["widget_id"],
        region_id=item["region_id"],
        label=item["label"],
        widget_type=item["widget_type"],
    )


def _table_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiTableDescriptor:
    if not _require_item_fields(item, frozenset({"table_id", "label"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    columns = tuple(_parse_items(item, "columns", _TABLE_COLUMN_FIELDS, _table_column_from_mapping, issues))
    _collect_duplicate_ids(
        (column.column_id for column in columns),
        f"{path}.columns.column_id",
        issues,
    )
    return GuiTableDescriptor(
        table_id=item["table_id"],
        label=item["label"],
        columns=columns,
    )


def _table_column_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiTableColumnDescriptor:
    if not _require_item_fields(item, frozenset({"column_id", "label"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    return GuiTableColumnDescriptor(
        column_id=item["column_id"],
        label=item["label"],
        visible=item.get("visible", True),
        width=item.get("width"),
        order=item.get("order"),
    )


def _report_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiReportDescriptor:
    if not _require_item_fields(item, frozenset({"report_id", "label"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    sections = tuple(
        _parse_items(item, "sections", _REPORT_SECTION_FIELDS, _report_section_from_mapping, issues)
    )
    _collect_duplicate_ids(
        (section.section_id for section in sections),
        f"{path}.sections.section_id",
        issues,
    )
    return GuiReportDescriptor(
        report_id=item["report_id"],
        label=item["label"],
        sections=sections,
    )


def _report_section_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiReportSectionDescriptor:
    if not _require_item_fields(item, frozenset({"section_id", "label"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    return GuiReportSectionDescriptor(
        section_id=item["section_id"],
        label=item["label"],
        visible=item.get("visible", True),
        order=item.get("order"),
    )


def _setting_from_mapping(
    item: Mapping[str, object],
    path: str,
    issues: list[GuiMetadataIssue],
) -> GuiSettingExposure:
    if not _require_item_fields(item, frozenset({"path", "label", "value_type"}), path, issues):
        raise ValueError(f"Missing required fields for {path}")
    return GuiSettingExposure(
        path=item["path"],
        label=item["label"],
        value_type=item["value_type"],
        description=item.get("description", ""),
    )


def _collect_forbidden_field_issues(
    value: object,
    path: str,
    issues: list[GuiMetadataIssue],
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}" if path else key_text
            if key_text.lower() in FORBIDDEN_EXECUTABLE_FIELD_NAMES:
                issues.append(
                    GuiMetadataIssue(
                        code=GuiMetadataIssueCode.FORBIDDEN_EXECUTABLE_FIELD,
                        path=next_path,
                        message=f"Executable metadata field is forbidden: {key_text}",
                    )
                )
            _collect_forbidden_field_issues(item, next_path, issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            next_path = f"{path}.{index}" if path else str(index)
            _collect_forbidden_field_issues(item, next_path, issues)


def _collect_unknown_fields(
    value: Mapping[str, object],
    allowed_fields: frozenset[str],
    path: str,
    issues: list[GuiMetadataIssue],
) -> None:
    for key in value:
        key_text = str(key)
        if key_text not in allowed_fields:
            issue_path = f"{path}.{key_text}" if path else key_text
            issues.append(
                GuiMetadataIssue(
                    code=GuiMetadataIssueCode.UNKNOWN_FIELD,
                    path=issue_path,
                    message=f"Unknown metadata field: {issue_path}",
                )
            )


def _collect_missing_required_fields(
    value: Mapping[str, object],
    required_fields: frozenset[str],
    path: str,
    issues: list[GuiMetadataIssue],
) -> None:
    for field_name in sorted(required_fields):
        if field_name not in value:
            issue_path = f"{path}.{field_name}" if path else field_name
            issues.append(
                GuiMetadataIssue(
                    code=GuiMetadataIssueCode.MISSING_REQUIRED_FIELD,
                    path=issue_path,
                    message=f"Missing required metadata field: {issue_path}",
                )
            )


def _require_item_fields(
    value: Mapping[str, object],
    required_fields: frozenset[str],
    path: str,
    issues: list[GuiMetadataIssue],
) -> bool:
    _collect_missing_required_fields(value, required_fields, path, issues)
    return required_fields.issubset(value)


def _string_field(value: Mapping[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(f"{key} must be a string")
    return item


def _optional_string_field(value: Mapping[str, object], key: str) -> str:
    if key not in value:
        return ""
    return _string_field(value, key)


def _collect_duplicate_ids(
    values: Iterable[str],
    path: str,
    issues: list[GuiMetadataIssue],
) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            issues.append(
                GuiMetadataIssue(
                    code=GuiMetadataIssueCode.DUPLICATE_ID,
                    path=path,
                    message=f"Duplicate metadata ID at {path}: {value}",
                )
            )
        seen.add(value)
