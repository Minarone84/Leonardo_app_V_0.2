from __future__ import annotations

from pathlib import Path
import copy
import json
import re

import pytest

from leonardo.gui.style import (
    DEFAULT_THEME_ID,
    GuiThemeRegistry,
    ThemeValidationError,
    apply_theme_stylesheet,
    build_stylesheet,
    build_theme_registry,
    load_default_theme,
    load_theme,
    theme_from_mapping,
)
from leonardo.gui.style.theme_tokens import (
    REQUIRED_COLOR_TOKENS,
    REQUIRED_COMPONENT_TOKENS,
    REQUIRED_EFFECT_TOKENS,
    REQUIRED_IDENTITY_TOKENS,
    REQUIRED_RADIUS_TOKENS,
    REQUIRED_SPACING_TOKENS,
    REQUIRED_THEME_GROUPS,
    REQUIRED_TYPOGRAPHY_TOKENS,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_THEME_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "style"
    / "themes"
    / "leonardo_jarvish_cockpit.json"
)
_ROADMAP_PATH = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata" / "gui_roadmap.json"
)
_STYLE_ROOT = _REPO_ROOT / "src" / "leonardo" / "gui" / "style"


def test_jarvish_theme_loads_by_id() -> None:
    registry = build_theme_registry()

    theme = registry.load_theme("leonardo_jarvish_cockpit")

    assert theme.theme_id == "leonardo_jarvish_cockpit"
    assert theme.identity.display_name == "Leonardo Jarvish Cockpit"
    assert theme.owner_area == "gui"
    assert theme.presentation_only is True


def test_default_theme_is_jarvish() -> None:
    assert DEFAULT_THEME_ID == "leonardo_jarvish_cockpit"
    assert build_theme_registry().default_theme_id == DEFAULT_THEME_ID
    assert load_default_theme().theme_id == DEFAULT_THEME_ID


def test_required_theme_token_groups_and_tokens_exist() -> None:
    raw_theme = _load_raw_theme()

    assert REQUIRED_THEME_GROUPS <= set(raw_theme)
    assert set(REQUIRED_IDENTITY_TOKENS) <= set(raw_theme["identity"])
    assert set(REQUIRED_COLOR_TOKENS) <= set(raw_theme["colors"])
    assert set(REQUIRED_TYPOGRAPHY_TOKENS) <= set(raw_theme["typography"])
    assert set(REQUIRED_SPACING_TOKENS) <= set(raw_theme["spacing"])
    assert set(REQUIRED_RADIUS_TOKENS) <= set(raw_theme["radius"])
    assert set(REQUIRED_EFFECT_TOKENS) <= set(raw_theme["effects"])
    assert set(REQUIRED_COMPONENT_TOKENS) <= set(raw_theme["components"])


def test_missing_required_token_fails_clearly() -> None:
    raw_theme = _load_raw_theme()
    del raw_theme["colors"]["accent_primary"]

    with pytest.raises(ThemeValidationError, match="colors missing required tokens"):
        theme_from_mapping(raw_theme)


def test_unknown_theme_id_is_rejected() -> None:
    registry = build_theme_registry()

    with pytest.raises(KeyError, match="Unknown GUI theme"):
        registry.load_theme("missing_theme")


def test_registered_theme_ids_are_deterministic(tmp_path: Path) -> None:
    registry = GuiThemeRegistry(
        {
            "z_theme": tmp_path / "z.json",
            "a_theme": tmp_path / "a.json",
        },
        default_theme_id="a_theme",
    )

    assert registry.available_theme_ids() == ("a_theme", "z_theme")


def test_theme_profile_id_must_match_requested_registry_id(tmp_path: Path) -> None:
    raw_theme = _load_raw_theme()
    raw_theme["identity"]["theme_id"] = "other_theme"
    theme_path = tmp_path / "theme.json"
    theme_path.write_text(json.dumps(raw_theme), encoding="utf-8")
    registry = GuiThemeRegistry({"expected_theme": theme_path}, default_theme_id="expected_theme")

    with pytest.raises(ThemeValidationError, match="theme ID mismatch"):
        registry.load_theme("expected_theme")


def test_stylesheet_generation_uses_theme_tokens() -> None:
    theme = load_theme(_THEME_PATH)

    stylesheet = build_stylesheet(theme)

    assert "#070B10" in stylesheet
    assert "#24C8DB" in stylesheet
    assert 'font-family: "Segoe UI"' in stylesheet
    assert "QPushButton" in stylesheet
    assert "object_id" not in stylesheet
    assert "action_id" not in stylesheet


def test_apply_theme_stylesheet_uses_set_stylesheet_boundary() -> None:
    class Target:
        def __init__(self) -> None:
            self.stylesheet = ""

        def setStyleSheet(self, stylesheet: str) -> None:
            self.stylesheet = stylesheet

    target = Target()
    theme = load_theme(_THEME_PATH)

    applied = apply_theme_stylesheet(target, theme)

    assert applied == target.stylesheet
    assert theme.colors.accent_primary in target.stylesheet


def test_apply_theme_stylesheet_requires_stylesheet_target() -> None:
    with pytest.raises(TypeError, match="setStyleSheet"):
        apply_theme_stylesheet(object(), load_theme(_THEME_PATH))


def test_theme_profiles_do_not_define_object_or_action_ids() -> None:
    raw_theme = _load_raw_theme()

    assert _forbidden_id_paths(raw_theme) == []

    invalid_theme = copy.deepcopy(raw_theme)
    invalid_theme["components"]["button"]["object_id"] = "main_window.button.bad"
    with pytest.raises(ThemeValidationError, match="object_id"):
        theme_from_mapping(invalid_theme)


def test_theme_system_modules_do_not_import_forbidden_layers() -> None:
    forbidden_patterns = (
        r"from leonardo\.core\b",
        r"import leonardo\.core\b",
        r"from leonardo\.connection\b",
        r"import leonardo\.connection\b",
        r"from leonardo\.data\b",
        r"import leonardo\.data\b",
        r"from leonardo\.storage\b",
        r"import leonardo\.storage\b",
        r"from leonardo\.trading\b",
        r"import leonardo\.trading\b",
        r"from leonardo\.chart\b",
        r"import leonardo\.chart\b",
        r"from leonardo\.providers?\b",
        r"import leonardo\.providers?\b",
        r"PySide6",
        r"PyQt6",
        r"requests",
        r"aiohttp",
        r"websockets",
        r"socket\.",
        r"subprocess",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(_STYLE_ROOT.glob("*.py"))
    )

    for pattern in forbidden_patterns:
        assert re.search(pattern, source) is None, pattern


def test_theme_loading_does_not_mutate_gui_roadmap_metadata() -> None:
    before = _ROADMAP_PATH.read_text(encoding="utf-8")

    load_default_theme()
    build_theme_registry().load_default_theme()

    assert _ROADMAP_PATH.read_text(encoding="utf-8") == before


def _load_raw_theme() -> dict[str, object]:
    data = json.loads(_THEME_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _forbidden_id_paths(value: object, path: str = "theme") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in {"object_id", "object_ids", "action_id", "action_ids"}:
                found.append(child_path)
            found.extend(_forbidden_id_paths(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_forbidden_id_paths(item, f"{path}[{index}]"))
    return found
