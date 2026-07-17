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


def test_go_to_dialog_keeps_invalid_input_open_and_exposes_accepted_timestamp() -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit

    from leonardo.gui.windows.research_go_to_dialog import ResearchGoToDialog

    app = QApplication.instance() or QApplication([])
    dialog = ResearchGoToDialog(3, "session-3", "BTCUSDT 1m", "1m")
    try:
        assert dialog.objectName() == "research.go_to_dialog"
        field = dialog.findChild(QLineEdit, "research.go_to_dialog.input")
        error = dialog.findChild(QLabel, "research.go_to_dialog.label.error")
        go = dialog.findChild(object, "research.go_to_dialog.button.go")
        field.setText("2026-02-30")
        go.click()
        assert dialog.result() == 0 and error.text()
        field.setText("2026-07-17 09:30")
        go.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.timestamp_ms == 1784280600000
    finally:
        dialog.close()
        app.processEvents()
