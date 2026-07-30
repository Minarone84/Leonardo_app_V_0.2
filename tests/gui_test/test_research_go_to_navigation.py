from __future__ import annotations

import builtins
import importlib
import json
from pathlib import Path
import runpy
import sys

import pytest

from leonardo.gui.chart.navigation import (
    go_to_input_format_hint,
    parse_go_to_utc_timestamp,
)
FIXTURES = Path(__file__).parent / "fixtures"


def test_frozen_go_to_parser_cases() -> None:
    cases = json.loads(
        (FIXTURES / "task_1020_chart_shell_input.json").read_text(encoding="utf-8")
    )["go_to_cases"]
    for case in cases:
        if "expected_timestamp_ms" in case:
            assert parse_go_to_utc_timestamp(case["text"], case["timeframe"]) == case[
                "expected_timestamp_ms"
            ]
        else:
            with pytest.raises(ValueError):
                parse_go_to_utc_timestamp(case["text"], case["timeframe"])


def test_go_to_hints_and_invalid_values() -> None:
    assert go_to_input_format_hint("1d") == "YYYY-MM-DD"
    assert go_to_input_format_hint("1w") == "YYYY-MM-DD"
    assert go_to_input_format_hint("1D") == "YYYY-MM-DD"
    assert go_to_input_format_hint("1W") == "YYYY-MM-DD"
    assert go_to_input_format_hint("1M") == "YYYY-MM-DD"
    assert go_to_input_format_hint("1m") == "YYYY-MM-DD HH:MM"
    assert go_to_input_format_hint("1h") == "YYYY-MM-DD HH:MM"
    for value in ("2026-02-30", "2026-07-17Z", "2026-07-17 09:30 UTC"):
        with pytest.raises(ValueError):
            parse_go_to_utc_timestamp(value, "1m")


def test_navigation_module_imports_without_pyside6(monkeypatch) -> None:
    module_name = "leonardo.gui.chart.navigation"
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("PySide6"):
            raise AssertionError("navigation imported PySide6")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    sys.modules.pop(module_name, None)
    importlib.import_module(module_name)


def test_pure_test_module_collects_without_pyside6(monkeypatch) -> None:
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("PySide6"):
            raise AssertionError("pure Go-to tests imported PySide6 during collection")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    runpy.run_path(__file__, run_name="task_1020_headless_collection_probe")


def test_go_to_dialog_exposes_structured_utc_controls_and_timestamp() -> None:
    pytest.importorskip("PySide6")
    from datetime import UTC, datetime

    from PySide6.QtCore import QDate, QTime
    from PySide6.QtWidgets import (
        QApplication,
        QDateEdit,
        QDialog,
        QLabel,
        QLineEdit,
        QTimeEdit,
    )

    from leonardo.gui.windows.research_go_to_dialog import ResearchGoToDialog

    app = QApplication.instance() or QApplication([])
    dialog = ResearchGoToDialog(3, "session-3", "BTCUSDT 1m", "1m")
    try:
        assert dialog.objectName() == "research.go_to_dialog"
        field = dialog.findChild(QLineEdit, "research.go_to_dialog.input")
        date = dialog.findChild(QDateEdit, "research.go_to_dialog.input.date")
        time = dialog.findChild(QTimeEdit, "research.go_to_dialog.input.time")
        calendar = dialog.findChild(
            QLabel, "research.go_to_dialog.icon.calendar"
        )
        clock = dialog.findChild(QLabel, "research.go_to_dialog.icon.clock")
        error = dialog.findChild(QLabel, "research.go_to_dialog.label.error")
        go = dialog.findChild(object, "research.go_to_dialog.button.go")
        dialog.show()
        app.processEvents()
        assert field.isVisible()
        assert field is not date.lineEdit()
        assert field.parentWidget() is dialog
        assert field.placeholderText() == "YYYY-MM-DD HH:mm"
        assert date.calendarPopup()
        assert date.displayFormat() == "yyyy-MM-dd"
        assert time.displayFormat() == "HH:mm"
        assert calendar.text() == "📅"
        assert calendar.accessibleName() == "Calendar"
        assert calendar.toolTip() == "Select UTC date"
        assert clock.text() == "🕒"
        assert clock.accessibleName() == "Clock"
        assert clock.toolTip() == "Select UTC time"

        date.setDate(QDate(2026, 7, 17))
        time.setTime(QTime(9, 30, 59, 999))
        assert field.text() == "2026-07-17 09:30"

        field.setText("2025-04-03 07:08")
        field.editingFinished.emit()
        assert date.date() == QDate(2025, 4, 3)
        assert time.time().hour() == 7
        assert time.time().minute() == 8

        selector_values = (date.date(), time.time())
        for invalid in (
            "2026-02-30 09:30",
            "2026-07-17",
            "2026-07-17 09:30:00",
            "2026/07/17 09:30",
            "2026-07-17 09:30 UTC",
            "",
        ):
            dialog._timestamp_ms = None
            field.setText(invalid)
            go.click()
            assert dialog.result() == QDialog.DialogCode.Rejected
            assert (
                error.text()
                == "Enter a valid UTC date and time as YYYY-MM-DD HH:mm."
            )
            assert (date.date(), time.time()) == selector_values
            assert dialog.timestamp_ms is None

        field.setText("2026-07-17 09:30")
        field.editingFinished.emit()
        assert date.date() == QDate(2026, 7, 17)
        assert time.time().hour() == 9
        assert time.time().minute() == 30
        go.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.timestamp_ms == 1784280600000
        accepted = datetime.fromtimestamp(dialog.timestamp_ms / 1_000, UTC)
        assert (accepted.second, accepted.microsecond) == (0, 0)

        error.setText("old error")
        dialog._timestamp_ms = 123
        field.setText("2001-01-01 01:02")
        date.setDate(QDate(2001, 1, 1))
        time.setTime(QTime(1, 2, 59, 999))
        before = datetime.now(UTC).replace(second=0, microsecond=0)
        dialog.prepare_for_open()
        after = datetime.now(UTC).replace(second=0, microsecond=0)
        reset = datetime(
            date.date().year(),
            date.date().month(),
            date.date().day(),
            time.time().hour(),
            time.time().minute(),
            tzinfo=UTC,
        )
        assert before <= reset <= after
        assert time.time().second() == 0
        assert field.text() == reset.strftime("%Y-%m-%d %H:%M")
        assert error.text() == ""
        assert dialog.timestamp_ms is None
    finally:
        dialog.close()
        app.processEvents()
