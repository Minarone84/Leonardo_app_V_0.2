from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

from leonardo.gui.display_time import (
    DEFAULT_DISPLAY_TIME_ZONE,
    DISPLAY_TIME_SETTINGS_KEY,
    DISPLAY_TIME_ZONE_PROPERTY,
    available_display_time_zones,
    current_display_time_zone_name,
    format_display_datetime,
    format_display_timestamp_ms,
    load_display_time_zone,
    parse_display_datetime,
    set_display_time_zone,
    validate_display_time_zone,
)
from leonardo.gui.windows.settings_dialog import LeonardoSettingsDialog


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path) -> QSettings:
    value = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    value.clear()
    return value


@pytest.fixture(autouse=True)
def restore_display_zone_property(qapp: QApplication):
    previous = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, None)
    yield
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, previous)


def test_default_zone_and_available_zones(
    qapp: QApplication,
    settings: QSettings,
) -> None:
    assert load_display_time_zone(settings=settings) == DEFAULT_DISPLAY_TIME_ZONE
    assert current_display_time_zone_name(
        application=qapp,
        settings=settings,
    ) == DEFAULT_DISPLAY_TIME_ZONE
    assert qapp.property(DISPLAY_TIME_ZONE_PROPERTY) == DEFAULT_DISPLAY_TIME_ZONE
    zones = available_display_time_zones()
    assert zones == tuple(sorted(zones))
    assert "Europe/Rome" in zones
    assert "UTC" in zones


def test_summer_and_winter_display_use_real_rome_dst() -> None:
    assert format_display_datetime(
        datetime(2026, 8, 9, 17, 42, 17, tzinfo=UTC),
        zone_name="Europe/Rome",
    ) == "2026-08-09 19:42:17 CEST (+02:00)"
    assert format_display_datetime(
        datetime(2026, 1, 9, 17, 42, 17, tzinfo=UTC),
        zone_name="Europe/Rome",
    ) == "2026-01-09 18:42:17 CET (+01:00)"
    assert format_display_timestamp_ms(
        1786297337123,
        zone_name="Europe/Rome",
    ) == "2026-08-09 19:42:17 CEST (+02:00)"


def test_dst_fallback_display_parses_by_explicit_offset() -> None:
    first = format_display_datetime(
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        zone_name="Europe/Rome",
    )
    second = format_display_datetime(
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        zone_name="Europe/Rome",
    )
    assert first == "2026-10-25 02:30:00 CEST (+02:00)"
    assert second == "2026-10-25 02:30:00 CET (+01:00)"
    assert parse_display_datetime(first) < parse_display_datetime(second)


@pytest.mark.parametrize("value", ("", "Invalid/Zone", None, 123))
def test_invalid_explicit_zone_is_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        validate_display_time_zone(value)  # type: ignore[arg-type]


def test_malformed_persisted_zone_falls_back(
    qapp: QApplication,
    settings: QSettings,
) -> None:
    settings.setValue(DISPLAY_TIME_SETTINGS_KEY, "Invalid/Zone")
    assert load_display_time_zone(settings=settings) == DEFAULT_DISPLAY_TIME_ZONE
    assert current_display_time_zone_name(
        application=qapp,
        settings=settings,
    ) == DEFAULT_DISPLAY_TIME_ZONE


def test_set_display_zone_persists_and_updates_application(
    qapp: QApplication,
    settings: QSettings,
) -> None:
    assert set_display_time_zone(
        "UTC", application=qapp, settings=settings
    ) is True
    assert qapp.property(DISPLAY_TIME_ZONE_PROPERTY) == "UTC"
    assert settings.value(DISPLAY_TIME_SETTINGS_KEY) == "UTC"
    assert set_display_time_zone(
        "UTC", application=qapp, settings=settings
    ) is False
    with pytest.raises(ValueError):
        set_display_time_zone(
            "Invalid/Zone", application=qapp, settings=settings
        )


def test_settings_dialog_selects_current_zone_and_cancel_changes_nothing(
    qapp: QApplication,
    settings: QSettings,
) -> None:
    set_display_time_zone("Europe/Rome", application=qapp, settings=settings)
    dialog = LeonardoSettingsDialog(settings=settings, application=qapp)
    try:
        combo = dialog.findChild(QComboBox, "settings.combo.display_time_zone")
        assert combo.currentText() == "Europe/Rome"
        combo.setCurrentText("UTC")
        dialog.findChild(QPushButton, "settings.button.cancel").click()
        assert dialog.result() == dialog.DialogCode.Rejected
        assert dialog.display_time_zone_changed is False
        assert settings.value(DISPLAY_TIME_SETTINGS_KEY) == "Europe/Rome"
        assert qapp.property(DISPLAY_TIME_ZONE_PROPERTY) == "Europe/Rome"
    finally:
        dialog.close()


def test_settings_dialog_save_updates_property_and_reports_actual_change(
    qapp: QApplication,
    settings: QSettings,
) -> None:
    set_display_time_zone("Europe/Rome", application=qapp, settings=settings)
    changed = LeonardoSettingsDialog(settings=settings, application=qapp)
    unchanged = None
    try:
        changed.findChild(QComboBox, "settings.combo.display_time_zone").setCurrentText(
            "UTC"
        )
        changed.findChild(QPushButton, "settings.button.save").click()
        assert changed.result() == changed.DialogCode.Accepted
        assert changed.display_time_zone_changed is True
        assert settings.value(DISPLAY_TIME_SETTINGS_KEY) == "UTC"
        assert qapp.property(DISPLAY_TIME_ZONE_PROPERTY) == "UTC"

        unchanged = LeonardoSettingsDialog(settings=settings, application=qapp)
        unchanged.findChild(QPushButton, "settings.button.save").click()
        assert unchanged.result() == unchanged.DialogCode.Accepted
        assert unchanged.display_time_zone_changed is False
    finally:
        changed.close()
        if unchanged is not None:
            unchanged.close()


def test_settings_dialog_has_frozen_identity_and_explanatory_text(
    qapp: QApplication,
    settings: QSettings,
) -> None:
    dialog = LeonardoSettingsDialog(settings=settings, application=qapp)
    try:
        assert dialog.objectName() == "settings.dialog"
        assert dialog.windowTitle() == "Settings"
        assert dialog.isModal()
        assert dialog.findChild(QLabel, "settings.label.display_time_zone").text() == (
            "Display Time Zone"
        )
        assert dialog.findChild(QLabel, "settings.label.display_time_note").text() == (
            "Stored timestamps remain UTC. This setting changes display only."
        )
    finally:
        dialog.close()
