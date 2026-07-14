from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "src" / "leonardo" / "gui"
WINDOWS = GUI / "windows"


def test_retired_gui_architecture_is_absent() -> None:
    forbidden_paths = (
        GUI / "metadata",
        GUI / "dummy_data.py",
        GUI / "settings_inspector.py",
        GUI / "settings_profiles.py",
        WINDOWS / "settings_inspector_window.py",
        WINDOWS / "dummy_metadata_test_window.py",
        WINDOWS / "dummy_metadata_settings_inspector.py",
        WINDOWS / "traceable_shell_widgets.py",
    )
    assert all(not path.exists() for path in forbidden_paths)
    assert not tuple(GUI.rglob("*.window.toml"))
    assert not tuple(GUI.rglob("*roadmap*.json"))


def test_gui_source_does_not_import_retired_modules_or_fixture_data() -> None:
    forbidden = (
        "leonardo.gui.metadata",
        "leonardo.gui.dummy_data",
        "leonardo.contracts",
        "parent_object_id",
        "load_dummy",
        "reset_dummy",
    )
    offenders: list[tuple[str, str]] = []
    for path in GUI.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append((str(path.relative_to(ROOT)), token))
    assert offenders == []


def test_every_top_level_window_sets_stable_runtime_identity() -> None:
    expected = {
        "main_window.py": "main_window.window",
        "connection_suite_window.py": "connection_suite.home.window",
        "research_suite_window.py": "research_suite.window",
        "data_manager_suite_window.py": "data_manager_suite.window",
        "analysis_suite_window.py": "analysis_suite.window",
        "trading_suite_window.py": "trading_suite.window",
        "runtime_manager_window.py": "runtime_manager.window",
        "historical_download_manager_window.py": "historical_download_manager.window",
        "ohlcv_download_preflight_window.py": "ohlcv_download_preflight.window",
        "ohlcv_download_task_window.py": "ohlcv_download_task.window",
        "ohlcv_maintenance_window.py": "ohlcv_maintenance.window",
    }
    for filename, object_id in expected.items():
        path = WINDOWS / filename
        text = path.read_text(encoding="utf-8")
        ast.parse(text)
        assert object_id in text
        assert "setObjectName" in text
