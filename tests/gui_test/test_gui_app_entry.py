from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.gui.app_entry import (
    LeonardoGuiAppEntry,
    run_gui_app_from_settings_base,
)


class FakeRunner:
    def __init__(self, result: int = 19) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        override_store_root: Path | str,
        config: object | None = None,
    ) -> int:
        self.calls.append(
            {
                "override_store_root": Path(override_store_root),
                "config": config,
            }
        )
        return self.result


def test_app_entry_resolves_override_root_through_path_policy(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    settings_base_dir = tmp_path / "settings"

    run_gui_app_from_settings_base(
        settings_base_dir=settings_base_dir,
        runner=runner,
    )

    assert runner.calls == [
        {
            "override_store_root": settings_base_dir / "gui_overrides",
            "config": None,
        }
    ]


def test_app_entry_passes_resolved_root_to_runner(tmp_path: Path) -> None:
    runner = FakeRunner()

    LeonardoGuiAppEntry(runner=runner).run(settings_base_dir=tmp_path / "settings")

    assert runner.calls[0]["override_store_root"] == tmp_path / "settings" / (
        "gui_overrides"
    )


def test_app_entry_accepts_path_settings_base(tmp_path: Path) -> None:
    runner = FakeRunner()
    settings_base_dir = tmp_path / "path-settings"

    result = run_gui_app_from_settings_base(
        settings_base_dir=settings_base_dir,
        runner=runner,
    )

    assert result == 19
    assert runner.calls[0]["override_store_root"] == (
        settings_base_dir / "gui_overrides"
    )


def test_app_entry_accepts_string_settings_base(tmp_path: Path) -> None:
    runner = FakeRunner()
    settings_base_dir = tmp_path / "string-settings"

    run_gui_app_from_settings_base(
        settings_base_dir=str(settings_base_dir),
        runner=runner,
    )

    assert runner.calls[0]["override_store_root"] == (
        settings_base_dir / "gui_overrides"
    )


@pytest.mark.parametrize("settings_base_dir", ("", "   "))
def test_invalid_settings_base_propagates_path_policy_failure(
    settings_base_dir: str,
) -> None:
    runner = FakeRunner()

    with pytest.raises(ValueError, match="base_dir must be a non-empty path"):
        run_gui_app_from_settings_base(
            settings_base_dir=settings_base_dir,
            runner=runner,
        )

    assert runner.calls == []


def test_missing_settings_base_propagates_path_policy_failure() -> None:
    runner = FakeRunner()

    with pytest.raises(TypeError, match="base_dir is required"):
        run_gui_app_from_settings_base(
            settings_base_dir=None,  # type: ignore[arg-type]
            runner=runner,
        )

    assert runner.calls == []


def test_app_entry_returns_runner_result(tmp_path: Path) -> None:
    runner = FakeRunner(result=31)

    result = run_gui_app_from_settings_base(
        settings_base_dir=tmp_path / "settings",
        runner=runner,
    )

    assert result == 31


def test_app_entry_passes_optional_config_to_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    config = object()

    run_gui_app_from_settings_base(
        settings_base_dir=tmp_path / "settings",
        config=config,
        runner=runner,
    )

    assert runner.calls == [
        {
            "override_store_root": tmp_path / "settings" / "gui_overrides",
            "config": config,
        }
    ]


def test_app_entry_uses_injected_fake_runner(tmp_path: Path) -> None:
    runner = FakeRunner()

    LeonardoGuiAppEntry(runner=runner).run(settings_base_dir=tmp_path / "settings")

    assert len(runner.calls) == 1


def test_app_entry_can_use_injected_override_root_resolver(tmp_path: Path) -> None:
    runner = FakeRunner()
    resolved_root = tmp_path / "custom-root"
    resolver_calls: list[Path | str] = []

    def resolver(base_dir: Path | str) -> Path:
        resolver_calls.append(base_dir)
        return resolved_root

    run_gui_app_from_settings_base(
        settings_base_dir=tmp_path / "settings",
        runner=runner,
        override_root_resolver=resolver,
    )

    assert resolver_calls == [tmp_path / "settings"]
    assert runner.calls[0]["override_store_root"] == resolved_root


def test_app_entry_does_not_create_directories_or_write_files(tmp_path: Path) -> None:
    runner = FakeRunner()
    settings_base_dir = tmp_path / "settings"

    run_gui_app_from_settings_base(
        settings_base_dir=settings_base_dir,
        runner=runner,
    )

    assert settings_base_dir.exists() is False
    assert (settings_base_dir / "gui_overrides").exists() is False
    assert list(tmp_path.iterdir()) == []


def test_app_entry_source_has_no_runtime_path_fallbacks() -> None:
    source = _app_entry_source()
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


def test_app_entry_source_has_no_qt_or_core_app_ownership() -> None:
    source = _app_entry_source()
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


def test_app_entry_tests_do_not_call_real_event_loop_directly() -> None:
    forbidden = "." + "ex" + "ec" + "()"

    assert forbidden not in _app_entry_source()
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")


def test_no_pyproject_launcher_entry_points_are_added() -> None:
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


def test_no_module_main_or_launcher_directories_are_created() -> None:
    project_dir = _project_dir()
    main_filename = "__main__" + ".py"

    assert not (project_dir / "src" / "leonardo" / main_filename).exists()
    assert not (project_dir / "src" / "leonardo" / "gui" / main_filename).exists()
    assert not (project_dir / "scripts").exists()
    assert not (project_dir / "tools").exists()
    assert not (project_dir / "bin").exists()


def test_runner_remains_explicit_root_capable() -> None:
    runner_source = _project_file(
        "src",
        "leonardo",
        "gui",
        "runner.py",
    ).read_text(encoding="utf-8")

    assert "override_store_root" in runner_source
    assert "settings_base_dir" not in runner_source
    assert "def run_gui_app(" in runner_source


def _app_entry_source() -> str:
    return _project_file("src", "leonardo", "gui", "app_entry.py").read_text(
        encoding="utf-8"
    )


def _project_file(*parts: str) -> Path:
    return _project_dir().joinpath(*parts)


def _project_dir() -> Path:
    return Path(__file__).resolve().parents[2]
