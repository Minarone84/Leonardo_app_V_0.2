"""Data-only theme token contract for GUI presentation styling."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
import re


REQUIRED_THEME_GROUPS = frozenset(
    {
        "identity",
        "colors",
        "typography",
        "spacing",
        "radius",
        "effects",
        "components",
    }
)
REQUIRED_IDENTITY_TOKENS = (
    "theme_id",
    "display_name",
    "description",
    "mode",
)
REQUIRED_COLOR_TOKENS = (
    "background",
    "surface",
    "surface_alt",
    "panel",
    "panel_alt",
    "border",
    "border_active",
    "text_primary",
    "text_secondary",
    "text_muted",
    "accent_primary",
    "accent_secondary",
    "accent_tertiary",
    "success",
    "warning",
    "error",
    "info",
)
REQUIRED_TYPOGRAPHY_TOKENS = (
    "base_font_family",
    "monospace_font_family",
    "base_font_size",
    "small_font_size",
    "title_font_size",
)
REQUIRED_SPACING_TOKENS = ("xs", "sm", "md", "lg", "xl")
REQUIRED_RADIUS_TOKENS = ("sm", "md", "lg")
REQUIRED_EFFECT_TOKENS = ("glow_enabled", "shadow_enabled", "border_intensity")
REQUIRED_COMPONENT_TOKENS = (
    "button",
    "panel",
    "card",
    "table",
    "tab",
    "status_chip",
    "input",
)

_THEME_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_FORBIDDEN_THEME_FIELD_NAMES = frozenset(
    {
        "object_id",
        "object_ids",
        "action_id",
        "action_ids",
    }
)


class ThemeValidationError(ValueError):
    """Raised when a GUI theme profile violates the theme token contract."""


@dataclass(frozen=True)
class GuiThemeIdentity:
    """Stable identity tokens for one GUI theme profile."""

    theme_id: str
    display_name: str
    description: str
    mode: str


@dataclass(frozen=True)
class GuiThemeColors:
    """Color tokens consumed by GUI stylesheet generation."""

    background: str
    surface: str
    surface_alt: str
    panel: str
    panel_alt: str
    border: str
    border_active: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent_primary: str
    accent_secondary: str
    accent_tertiary: str
    success: str
    warning: str
    error: str
    info: str


@dataclass(frozen=True)
class GuiThemeTypography:
    """Typography tokens consumed by GUI stylesheet generation."""

    base_font_family: str
    monospace_font_family: str
    base_font_size: int
    small_font_size: int
    title_font_size: int


@dataclass(frozen=True)
class GuiThemeSpacing:
    """Spacing scale tokens for future GUI layout styling."""

    xs: int
    sm: int
    md: int
    lg: int
    xl: int


@dataclass(frozen=True)
class GuiThemeRadius:
    """Corner radius tokens for GUI presentation components."""

    sm: int
    md: int
    lg: int


@dataclass(frozen=True)
class GuiThemeEffects:
    """Non-behavioral visual effect tokens for GUI presentation."""

    glow_enabled: bool
    shadow_enabled: bool
    border_intensity: str


@dataclass(frozen=True)
class GuiTheme:
    """
    Validated GUI presentation theme.

    Themes are static presentation configuration. They do not define GUI object
    identifiers, action identifiers, runtime behavior, domain policy, storage
    behavior, or roadmap metadata.
    """

    identity: GuiThemeIdentity
    colors: GuiThemeColors
    typography: GuiThemeTypography
    spacing: GuiThemeSpacing
    radius: GuiThemeRadius
    effects: GuiThemeEffects
    components: Mapping[str, Mapping[str, object]]

    @property
    def theme_id(self) -> str:
        """Return the stable theme identifier."""

        return self.identity.theme_id

    @property
    def owner_area(self) -> str:
        """Return the owning Leonardo area for theme presentation concerns."""

        return "gui"

    @property
    def presentation_only(self) -> bool:
        """Return whether this theme is constrained to presentation tokens."""

        return True


def theme_from_mapping(data: Mapping[str, object]) -> GuiTheme:
    """
    Build a validated GUI theme from a decoded mapping.

    The loader intentionally validates the complete required token surface and
    rejects object/action identifier fields anywhere in the profile. Theme
    profiles must remain presentation data, not GUI metadata or behavior.
    """

    if not isinstance(data, Mapping):
        raise ThemeValidationError("theme profile root must be a mapping")
    _reject_forbidden_theme_fields(data)
    _require_keys(data, REQUIRED_THEME_GROUPS, "theme profile")

    identity_data = _mapping_at(data, "identity")
    colors_data = _mapping_at(data, "colors")
    typography_data = _mapping_at(data, "typography")
    spacing_data = _mapping_at(data, "spacing")
    radius_data = _mapping_at(data, "radius")
    effects_data = _mapping_at(data, "effects")
    components_data = _mapping_at(data, "components")

    _require_keys(identity_data, REQUIRED_IDENTITY_TOKENS, "identity")
    _require_keys(colors_data, REQUIRED_COLOR_TOKENS, "colors")
    _require_keys(typography_data, REQUIRED_TYPOGRAPHY_TOKENS, "typography")
    _require_keys(spacing_data, REQUIRED_SPACING_TOKENS, "spacing")
    _require_keys(radius_data, REQUIRED_RADIUS_TOKENS, "radius")
    _require_keys(effects_data, REQUIRED_EFFECT_TOKENS, "effects")
    _require_keys(components_data, REQUIRED_COMPONENT_TOKENS, "components")

    identity = GuiThemeIdentity(
        theme_id=_theme_id_at(identity_data, "theme_id"),
        display_name=_non_empty_string_at(identity_data, "display_name"),
        description=_non_empty_string_at(identity_data, "description"),
        mode=_non_empty_string_at(identity_data, "mode"),
    )
    return GuiTheme(
        identity=identity,
        colors=GuiThemeColors(
            **{
                key: _color_at(colors_data, key)
                for key in REQUIRED_COLOR_TOKENS
            }
        ),
        typography=GuiThemeTypography(
            base_font_family=_non_empty_string_at(
                typography_data,
                "base_font_family",
            ),
            monospace_font_family=_non_empty_string_at(
                typography_data,
                "monospace_font_family",
            ),
            base_font_size=_positive_int_at(typography_data, "base_font_size"),
            small_font_size=_positive_int_at(typography_data, "small_font_size"),
            title_font_size=_positive_int_at(typography_data, "title_font_size"),
        ),
        spacing=GuiThemeSpacing(
            **{key: _non_negative_int_at(spacing_data, key) for key in REQUIRED_SPACING_TOKENS}
        ),
        radius=GuiThemeRadius(
            **{key: _non_negative_int_at(radius_data, key) for key in REQUIRED_RADIUS_TOKENS}
        ),
        effects=GuiThemeEffects(
            glow_enabled=_bool_at(effects_data, "glow_enabled"),
            shadow_enabled=_bool_at(effects_data, "shadow_enabled"),
            border_intensity=_non_empty_string_at(effects_data, "border_intensity"),
        ),
        components=_freeze_components(components_data),
    )


def _reject_forbidden_theme_fields(value: object, path: str = "theme") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ThemeValidationError(f"{path} contains non-string key")
            child_path = f"{path}.{key}"
            if key in _FORBIDDEN_THEME_FIELD_NAMES:
                raise ThemeValidationError(
                    f"{child_path} is forbidden in theme profiles"
                )
            _reject_forbidden_theme_fields(item, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_theme_fields(item, f"{path}[{index}]")


def _require_keys(
    data: Mapping[str, object],
    required_keys: object,
    label: str,
) -> None:
    missing = sorted(set(required_keys) - set(data))
    if missing:
        raise ThemeValidationError(f"{label} missing required tokens: {', '.join(missing)}")


def _mapping_at(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ThemeValidationError(f"{key} must be a mapping")
    return value


def _theme_id_at(data: Mapping[str, object], key: str) -> str:
    value = _non_empty_string_at(data, key)
    if _THEME_ID_PATTERN.fullmatch(value) is None:
        raise ThemeValidationError(f"{key} must be a stable machine-readable theme ID")
    return value


def _non_empty_string_at(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ThemeValidationError(f"{key} must be a non-empty string")
    return value


def _color_at(data: Mapping[str, object], key: str) -> str:
    value = _non_empty_string_at(data, key)
    if not value.startswith("#") or len(value) not in {4, 7}:
        raise ThemeValidationError(f"{key} must be a hex color token")
    return value


def _positive_int_at(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ThemeValidationError(f"{key} must be a positive integer")
    return value


def _non_negative_int_at(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ThemeValidationError(f"{key} must be a non-negative integer")
    return value


def _bool_at(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ThemeValidationError(f"{key} must be a boolean")
    return value


def _freeze_components(
    components_data: Mapping[str, object],
) -> Mapping[str, Mapping[str, object]]:
    frozen: dict[str, Mapping[str, object]] = {}
    for key, value in components_data.items():
        if key not in REQUIRED_COMPONENT_TOKENS:
            continue
        if not isinstance(value, Mapping):
            raise ThemeValidationError(f"components.{key} must be a mapping")
        frozen[key] = MappingProxyType(dict(value))
    return MappingProxyType(frozen)
