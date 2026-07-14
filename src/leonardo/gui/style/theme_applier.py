"""Generate and apply GUI presentation stylesheets from theme tokens."""

from __future__ import annotations

from leonardo.gui.style.theme_tokens import GuiTheme


def build_stylesheet(theme: GuiTheme) -> str:
    """
    Build a Qt stylesheet from validated GUI theme tokens.

    The stylesheet uses global component selectors only. It does not reference
    GUI object IDs, action IDs, domain state, roadmap metadata, or runtime data.
    """

    colors = theme.colors
    typography = theme.typography
    spacing = theme.spacing
    radius = theme.radius

    return f"""
QWidget {{
    background-color: {colors.background};
    color: {colors.text_primary};
    font-family: "{typography.base_font_family}";
    font-size: {typography.base_font_size}pt;
}}

QMainWindow, QDialog {{
    background-color: {colors.background};
}}

QMenuBar, QMenu {{
    background-color: {colors.surface};
    color: {colors.text_primary};
    border: 1px solid {colors.border};
}}

QMenuBar::item:selected, QMenu::item:selected {{
    background-color: {colors.panel_alt};
    color: {colors.accent_primary};
}}

QPushButton {{
    background-color: {colors.panel};
    color: {colors.text_primary};
    border: 1px solid {colors.border};
    border-radius: {radius.sm}px;
    padding: {spacing.sm}px {spacing.md}px;
}}

QPushButton:hover {{
    border-color: {colors.border_active};
    color: {colors.accent_primary};
}}

QPushButton:disabled {{
    color: {colors.text_muted};
    border-color: {colors.border};
}}

QGroupBox, QFrame {{
    background-color: {colors.surface};
    border: 1px solid {colors.border};
    border-radius: {radius.md}px;
    margin-top: {spacing.sm}px;
}}

QTableWidget, QTableView {{
    background-color: {colors.surface_alt};
    alternate-background-color: {colors.panel};
    color: {colors.text_primary};
    gridline-color: {colors.border};
    selection-background-color: {colors.panel_alt};
    selection-color: {colors.accent_primary};
}}

QHeaderView::section {{
    background-color: {colors.panel};
    color: {colors.text_secondary};
    border: 1px solid {colors.border};
    padding: {spacing.xs}px {spacing.sm}px;
}}

QTabWidget::pane {{
    border: 1px solid {colors.border};
    background-color: {colors.surface};
}}

QTabBar::tab {{
    background-color: {colors.panel};
    color: {colors.text_secondary};
    border: 1px solid {colors.border};
    padding: {spacing.sm}px {spacing.md}px;
}}

QTabBar::tab:selected {{
    color: {colors.accent_primary};
    border-color: {colors.border_active};
}}

QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {colors.panel};
    color: {colors.text_primary};
    border: 1px solid {colors.border};
    border-radius: {radius.sm}px;
    padding: {spacing.xs}px {spacing.sm}px;
}}

QStatusBar {{
    background-color: {colors.surface};
    color: {colors.text_secondary};
    border-top: 1px solid {colors.border};
}}
""".strip()


def apply_theme_stylesheet(target: object, theme: GuiTheme) -> str:
    """
    Apply a generated stylesheet to a Qt-like target.

    The target must expose ``setStyleSheet(str)``. This helper avoids importing
    Qt directly so the theme system remains testable without owning application
    startup or widget construction.
    """

    set_stylesheet = getattr(target, "setStyleSheet", None)
    if not callable(set_stylesheet):
        raise TypeError("theme target must expose callable setStyleSheet")
    stylesheet = build_stylesheet(theme)
    set_stylesheet(stylesheet)
    return stylesheet
