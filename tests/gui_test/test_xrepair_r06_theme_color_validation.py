"""R06 theme token/public loader regressions; no rendering or theme writes."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from leonardo.gui.style.theme_loader import THEME_PROFILE_PATH, load_default_theme, load_theme
from leonardo.gui.style.theme_tokens import REQUIRED_COLOR_TOKENS, ThemeValidationError, _color_at, theme_from_mapping


def _profile():
    return json.loads(THEME_PROFILE_PATH.read_text(encoding="utf-8"))


def _receipt(request, **values):
    root = (Path(os.environ["R02_OBSERVATIONS"]) if "R02_OBSERVATIONS" in os.environ
            else request.getfixturevalue("tmp_path") / "observations")
    root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
    (root / (name + ".json")).write_text(json.dumps(dict(node=request.node.nodeid, **values), indent=2))


def _read_token(route, token, tmp_path):
    if route == "private":
        return _color_at({"background": token}, "background")
    profile = _profile(); profile["colors"]["background"] = token
    if route == "mapping":
        return theme_from_mapping(profile).colors.background
    path = tmp_path / "disposable_theme.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return load_theme(path).colors.background


@pytest.mark.parametrize("route", ["private", "mapping", "file"])
@pytest.mark.parametrize("token", ["#abc", "#ABC", "#aBc", "#abcdef", "#ABCDEF", "#a1B2c3"])
def test_valid_hex_preserves_exact_case_and_format(route, token, tmp_path, request):
    result = _read_token(route, token, tmp_path)
    assert result == token
    _receipt(request, route=route, input=token, output=result)


@pytest.mark.parametrize("route", ["private", "mapping", "file"])
@pytest.mark.parametrize("token", ["#Z09", "#12zz34", "#+12", "#-12", "#1_2", "#1 2", "#12ab 4", "#１２３", "#ab\u0430", "#abcdef "])
def test_nonhex_tokens_rejected(route, token, tmp_path, request):
    error = None
    try:
        _read_token(route, token, tmp_path)
    except ThemeValidationError as caught:
        error = str(caught)
    _receipt(request, route=route, input=token, error=error)
    assert error == "background must be a hex color token"


@pytest.mark.parametrize("token", ["12ab34", "#12", "#12345", "#12345678", " #abc", "#abc "])
def test_existing_prefix_length_rejections(token, tmp_path):
    for route in ("private", "mapping", "file"):
        with pytest.raises(ThemeValidationError, match="background must be a hex color token"):
            _read_token(route, token, tmp_path)


@pytest.mark.parametrize("token", [None, False, 123, "", "   "])
def test_existing_nonempty_type_rejections(token, tmp_path):
    for route in ("private", "mapping", "file"):
        with pytest.raises(ThemeValidationError, match="background must be a non-empty string"):
            _read_token(route, token, tmp_path)


@pytest.mark.parametrize("slot", sorted(REQUIRED_COLOR_TOKENS))
@pytest.mark.parametrize("route", ["mapping", "file"])
def test_every_required_palette_slot_rejects_nonhex(slot, route, tmp_path):
    profile = _profile(); profile["colors"][slot] = "#gg0000"
    with pytest.raises(ThemeValidationError, match=slot + " must be a hex color token"):
        if route == "mapping":
            theme_from_mapping(profile)
        else:
            path = tmp_path / "invalid_slot.json"; path.write_text(json.dumps(profile))
            load_theme(path)


@pytest.mark.parametrize("field", ["object_id", "action_id"])
def test_forbidden_identifiers_and_required_groups_stay_active(field):
    profile = _profile(); profile["components"]["button"][field] = "forbidden"
    with pytest.raises(ThemeValidationError, match="forbidden"):
        theme_from_mapping(profile)
    profile = _profile(); del profile["colors"]["background"]
    with pytest.raises(ThemeValidationError, match="missing required tokens: background"):
        theme_from_mapping(profile)
    profile = _profile(); del profile["typography"]
    with pytest.raises(ThemeValidationError, match="missing required tokens: typography"):
        theme_from_mapping(profile)


def test_bundled_full_values_and_recovery_after_bad_profile(tmp_path, request):
    original = THEME_PROFILE_PATH.read_bytes()
    assert hashlib.sha256(original).hexdigest() == "674c990eec611983f77f51e348200be0d57d4c1927db28a673878e7939a19870"
    profile = _profile()
    for bad in ("#Z09", "#12zz34"):
        with pytest.raises(ThemeValidationError):
            _read_token("file", bad, tmp_path)
    theme = load_default_theme()
    for group in ("identity", "colors", "typography", "spacing", "radius", "effects"):
        assert {key: getattr(getattr(theme, group), key) for key in profile[group]} == profile[group]
    assert theme.components == profile["components"]
    assert theme.theme_id == "leonardo_jarvish_cockpit" and theme.presentation_only
    assert THEME_PROFILE_PATH.read_bytes() == original
    _receipt(request, resource_sha256=hashlib.sha256(original).hexdigest(), full_profile=profile,
             recovered_default=theme.theme_id, resource_unchanged=True)
