from __future__ import annotations

from pathlib import Path

import pytest

from tools.dev_launch_gui import main


class FakeAppEntry:
    def __init__(self, *, result: int = 23, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, settings_base_dir: Path | str) -> int:
        self.calls.append({"settings_base_dir": settings_base_dir})
        if self.error is not None:
            raise self.error
        return self.result


def test_main_requires_settings_base_dir() -> None:
    fake = FakeAppEntry()

    with pytest.raises(SystemExit) as exc_info:
        main([], app_entry=fake)

    assert exc_info.value.code != 0
    assert fake.calls == []


def test_main_calls_fake_app_entry_once_with_parsed_path(tmp_path: Path) -> None:
    fake = FakeAppEntry()
    settings_base_dir = tmp_path / "settings"

    main(["--settings-base-dir", str(settings_base_dir)], app_entry=fake)

    assert fake.calls == [{"settings_base_dir": settings_base_dir}]


def test_main_returns_app_entry_integer_result(tmp_path: Path) -> None:
    fake = FakeAppEntry(result=37)

    result = main(
        ["--settings-base-dir", str(tmp_path / "settings")],
        app_entry=fake,
    )

    assert result == 37


def test_app_entry_exceptions_propagate(tmp_path: Path) -> None:
    failure = RuntimeError("dev launch failed")
    fake = FakeAppEntry(error=failure)

    with pytest.raises(RuntimeError) as exc_info:
        main(
            ["--settings-base-dir", str(tmp_path / "settings")],
            app_entry=fake,
        )

    assert exc_info.value is failure


def test_no_env_var_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAppEntry()
    monkeypatch.setenv("LEONARDO_GUI_SETTINGS_BASE_DIR", "ignored")

    with pytest.raises(SystemExit) as exc_info:
        main([], app_entry=fake)

    assert exc_info.value.code != 0
    assert fake.calls == []


def test_dev_launch_helper_does_not_write_outside_tmp_path(tmp_path: Path) -> None:
    fake = FakeAppEntry()
    settings_base_dir = tmp_path / "settings"

    main(["--settings-base-dir", str(settings_base_dir)], app_entry=fake)

    assert settings_base_dir.exists() is False
    assert list(tmp_path.iterdir()) == []


def test_source_has_no_platform_or_runtime_path_fallbacks() -> None:
    source = _dev_launch_source()
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


def test_source_has_no_settings_env_fallback() -> None:
    source = _dev_launch_source()
    forbidden_tokens = (
        "os." + "environ",
        "get" + "env",
        "en" + "viron",
    )

    for token in forbidden_tokens:
        assert token not in source


def test_source_has_no_core_or_qt_ownership() -> None:
    source = _dev_launch_source()
    forbidden_tokens = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "Leonardo" + "App",
        "App" + "Config",
        "load_" + "default_config",
        "PySide" + "6",
        "PyQt" + "6",
        "Qt" + "Widgets",
        "Qt" + "Core",
        "Qt" + "Gui",
        "Q" + "Application",
    )

    for token in forbidden_tokens:
        assert token not in source


def test_pyproject_is_not_modified_for_public_entry_points() -> None:
    pyproject_source = _project_file("pyproject.toml").read_text(encoding="utf-8")
    forbidden_tokens = (
        "console" + "_scripts",
        "gui" + "_scripts",
        "entry" + "_points",
        "[project." + "scripts]",
        "[project." + "gui-scripts]",
    )

    for token in forbidden_tokens:
        assert token not in pyproject_source


def test_no_package_main_files_are_created() -> None:
    project_dir = _project_dir()
    main_filename = "__main__" + ".py"

    assert not (project_dir / "src" / "leonardo" / main_filename).exists()
    assert not (project_dir / "src" / "leonardo" / "gui" / main_filename).exists()


def test_tests_do_not_call_real_event_loop_directly() -> None:
    forbidden = "." + "ex" + "ec" + "()"

    assert forbidden not in _dev_launch_source()
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")


def _dev_launch_source() -> str:
    return _project_file("tools", "dev_launch_gui.py").read_text(encoding="utf-8")


def _project_file(*parts: str) -> Path:
    return _project_dir().joinpath(*parts)


def _project_dir() -> Path:
    return Path(__file__).resolve().parents[2]
