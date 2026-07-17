"""Deterministic lazy exports for GUI-owned reusable widget helpers."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DEFAULT_SUITE_NAVIGATION_SEGMENTS",
    "SuiteNavigationDonut",
    "SuiteNavigationDonutGeometry",
    "SuiteNavigationSegment",
    "calculate_suite_navigation_donut_geometry",
    "StudyManagerWidget",
    "ResearchChartSlotWidget",
    "ResearchWorkspaceWidget",
]

_LAZY_EXPORTS = {
    "DEFAULT_SUITE_NAVIGATION_SEGMENTS": (
        "leonardo.gui.widgets.suite_navigation_donut",
        "DEFAULT_SUITE_NAVIGATION_SEGMENTS",
    ),
    "SuiteNavigationDonut": (
        "leonardo.gui.widgets.suite_navigation_donut",
        "SuiteNavigationDonut",
    ),
    "SuiteNavigationDonutGeometry": (
        "leonardo.gui.widgets.suite_navigation_donut",
        "SuiteNavigationDonutGeometry",
    ),
    "SuiteNavigationSegment": (
        "leonardo.gui.widgets.suite_navigation_donut",
        "SuiteNavigationSegment",
    ),
    "calculate_suite_navigation_donut_geometry": (
        "leonardo.gui.widgets.suite_navigation_donut",
        "calculate_suite_navigation_donut_geometry",
    ),
    "StudyManagerWidget": (
        "leonardo.gui.widgets.study_manager_widget",
        "StudyManagerWidget",
    ),
    "ResearchChartSlotWidget": (
        "leonardo.gui.widgets.research_chart_slot_widget",
        "ResearchChartSlotWidget",
    ),
    "ResearchWorkspaceWidget": (
        "leonardo.gui.widgets.research_workspace_widget",
        "ResearchWorkspaceWidget",
    ),
}


def __getattr__(name: str):
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
