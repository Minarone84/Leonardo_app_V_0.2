from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.gui.path_policy import (
    GUI_OVERRIDE_STORE_DIRNAME,
    GuiOverridePathPolicy,
    resolve_gui_override_store_root,
)


def test_resolves_override_store_root_under_injected_base_path(tmp_path: Path) -> None:
    base_dir = tmp_path / "settings"

    result = resolve_gui_override_store_root(base_dir)

    assert result == base_dir / "gui_overrides"


def test_uses_deterministic_child_directory_name(tmp_path: Path) -> None:
    policy = GuiOverridePathPolicy(tmp_path / "settings")

    assert GUI_OVERRIDE_STORE_DIRNAME == "gui_overrides"
    assert policy.override_store_root.name == "gui_overrides"


def test_resolution_does_not_create_directory_or_write_files(tmp_path: Path) -> None:
    base_dir = tmp_path / "settings"

    result = resolve_gui_override_store_root(base_dir)

    assert result == base_dir / "gui_overrides"
    assert base_dir.exists() is False
    assert result.exists() is False
    assert list(tmp_path.iterdir()) == []


def test_accepts_path_input(tmp_path: Path) -> None:
    base_dir = tmp_path / "settings"

    policy = GuiOverridePathPolicy(base_dir)

    assert policy.base_dir == base_dir
    assert policy.override_store_root == base_dir / "gui_overrides"


def test_accepts_string_path_input(tmp_path: Path) -> None:
    base_dir = tmp_path / "settings"

    result = resolve_gui_override_store_root(str(base_dir))

    assert result == base_dir / "gui_overrides"


@pytest.mark.parametrize("base_dir", ("", "   "))
def test_rejects_empty_string(base_dir: str) -> None:
    with pytest.raises(ValueError, match="base_dir must be a non-empty path"):
        resolve_gui_override_store_root(base_dir)


def test_rejects_none() -> None:
    with pytest.raises(TypeError, match="base_dir is required"):
        resolve_gui_override_store_root(None)  # type: ignore[arg-type]


def test_source_avoids_runtime_path_fallbacks() -> None:
    source = _path_policy_source()
    forbidden_tokens = (
        "Path." + "home",
        "home" + "(",
        "Path." + "cwd",
        "cwd" + "(",
        "get" + "cwd",
        "App" + "Data",
        "." + "config",
        "runs" + "_dir",
        "tmp" + "_dir",
        "repo" + "_root",
    )

    for token in forbidden_tokens:
        assert token not in source


def test_source_has_no_core_qt_runner_or_store_dependencies() -> None:
    source = _path_policy_source()
    forbidden_tokens = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "App" + "Config",
        "load_" + "default_config",
        "PySide" + "6",
        "PyQt" + "6",
        "Qt" + "Widgets",
        "Qt" + "Core",
        "Qt" + "Gui",
        "Q" + "Application",
        "Leonardo" + "GuiRunner",
        "run_" + "gui_app",
        "GuiMetadata" + "OverrideStore",
    )

    for token in forbidden_tokens:
        assert token not in source


def _path_policy_source() -> str:
    project_dir = Path(__file__).resolve().parents[2]
    return (project_dir / "src" / "leonardo" / "gui" / "path_policy.py").read_text(
        encoding="utf-8"
    )
