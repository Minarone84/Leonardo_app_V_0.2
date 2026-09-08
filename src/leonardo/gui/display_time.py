"""Canonical GUI display-time policy."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


DEFAULT_DISPLAY_TIME_ZONE = "Europe/Rome"
DISPLAY_TIME_ZONE_PROPERTY = "leonardo.display_time_zone"
DISPLAY_TIME_SETTINGS_ORGANIZATION = "Leonardo"
DISPLAY_TIME_SETTINGS_APPLICATION = "Leonardo V2"
DISPLAY_TIME_SETTINGS_KEY = "presentation/display_time_zone"

_DISPLAY_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?P<zone>\S+) \((?P<offset>[+-]\d{2}:\d{2})\)$"
)


def validate_display_time_zone(value: str) -> str:
    """Validate and return one IANA display-time-zone name unchanged."""
    if not isinstance(value, str) or not value:
        raise ValueError("display time zone must be a non-empty string")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"invalid display time zone: {value}") from error
    return value


def available_display_time_zones() -> tuple[str, ...]:
    """Return runtime IANA time-zone names in deterministic order."""
    return tuple(sorted(available_timezones()))


def load_display_time_zone(*, settings=None) -> str:
    """Load the persisted display zone, falling back to Europe/Rome."""
    resolved_settings = (
        QSettings(
            DISPLAY_TIME_SETTINGS_ORGANIZATION,
            DISPLAY_TIME_SETTINGS_APPLICATION,
        )
        if settings is None
        else settings
    )
    value = resolved_settings.value(DISPLAY_TIME_SETTINGS_KEY, None)
    try:
        return validate_display_time_zone(value)
    except ValueError:
        return DEFAULT_DISPLAY_TIME_ZONE


def current_display_time_zone_name(
    *,
    application=None,
    settings=None,
) -> str:
    """Return and cache the current GUI session display zone."""
    resolved_application = QApplication.instance() if application is None else application
    if resolved_application is None:
        return DEFAULT_DISPLAY_TIME_ZONE
    value = resolved_application.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        return validate_display_time_zone(value)
    except ValueError:
        value = load_display_time_zone(settings=settings)
        resolved_application.setProperty(DISPLAY_TIME_ZONE_PROPERTY, value)
        return value


def set_display_time_zone(
    value: str,
    *,
    application=None,
    settings=None,
) -> bool:
    """Set and persist the GUI display zone, returning whether it changed."""
    validated = validate_display_time_zone(value)
    resolved_application = QApplication.instance() if application is None else application
    current = current_display_time_zone_name(
        application=resolved_application,
        settings=settings,
    )
    if resolved_application is not None:
        resolved_application.setProperty(DISPLAY_TIME_ZONE_PROPERTY, validated)
    resolved_settings = (
        QSettings(
            DISPLAY_TIME_SETTINGS_ORGANIZATION,
            DISPLAY_TIME_SETTINGS_APPLICATION,
        )
        if settings is None
        else settings
    )
    resolved_settings.setValue(DISPLAY_TIME_SETTINGS_KEY, validated)
    return current != validated


def format_display_timestamp_ms(
    value: int | None,
    *,
    zone_name: str | None = None,
) -> str:
    """Format an absolute Unix epoch-millisecond value for GUI display."""
    if value is None:
        return ""
    if type(value) is not int:
        raise TypeError("timestamp value must be an integer or None")
    return _format_display_datetime(
        datetime.fromtimestamp(value / 1000, tz=UTC),
        zone_name=zone_name,
    )


def format_display_datetime(
    value: datetime | None,
    *,
    zone_name: str | None = None,
) -> str:
    """Format a timezone-aware datetime for GUI display."""
    if value is None:
        return ""
    if not isinstance(value, datetime):
        raise TypeError("datetime value must be a datetime or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime value must be timezone-aware")
    return _format_display_datetime(value, zone_name=zone_name)


def parse_display_datetime(value: str) -> datetime:
    """Parse canonical display text using its explicit numeric UTC offset."""
    if not isinstance(value, str):
        raise ValueError("display datetime must be a canonical string")
    match = _DISPLAY_TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("invalid canonical display datetime")
    try:
        return datetime.strptime(
            f"{match.group('timestamp')} {match.group('offset')}",
            "%Y-%m-%d %H:%M:%S %z",
        )
    except ValueError as error:
        raise ValueError("invalid canonical display datetime") from error


def _format_display_datetime(value: datetime, *, zone_name: str | None) -> str:
    selected_zone = (
        current_display_time_zone_name()
        if zone_name is None
        else validate_display_time_zone(zone_name)
    )
    localized = value.astimezone(ZoneInfo(selected_zone))
    offset = localized.strftime("%z")
    return (
        f"{localized.strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"({offset[:3]}:{offset[3:]})"
    )
