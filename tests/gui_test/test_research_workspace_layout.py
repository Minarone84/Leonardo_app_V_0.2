from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from leonardo.gui.widgets.research_workspace_layout import (
    build_research_workspace_layout,
)


FIXTURE = Path(__file__).with_name("fixtures") / "task_1019_workspace_expected.json"


@pytest.mark.parametrize("count", range(9))
@pytest.mark.parametrize("mode", ("scroll_4", "fit_8"))
def test_all_frozen_layouts_are_exact(count: int, mode: str) -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["layout_plans"][str(count)]
    plan = build_research_workspace_layout(range(1, count + 1), mode)
    assert plan.count == expected["count"]
    assert plan.row_count == expected["row_count"]
    assert tuple(
        {
            "visual_index": item.visual_index,
            "row": item.row,
            "column": item.column,
            "row_span": item.row_span,
            "column_span": item.column_span,
        }
        for item in plan.items
    ) == tuple(expected["items"])
    assert plan.vertical_scroll == ("as_needed" if mode == "scroll_4" else "off")
    assert plan.minimum_height_ratio == (
        max(1.0, expected["row_count"] / 2.0) if mode == "scroll_4" else 1.0
    )


def test_logical_gaps_compact_visually_without_changing_slot_ids() -> None:
    plan = build_research_workspace_layout((8, 1, 6, 3), "scroll_4")
    assert tuple(item.slot_id for item in plan.items) == (1, 3, 6, 8)
    assert tuple(item.visual_index for item in plan.items) == (0, 1, 2, 3)
    assert tuple((item.row, item.column) for item in plan.items) == (
        (0, 0), (0, 1), (1, 0), (1, 1)
    )


@pytest.mark.parametrize(
    ("slot_ids", "mode"),
    (((1, 1), "scroll_4"), ((0,), "scroll_4"), ((9,), "scroll_4"), (range(9), "fit_8")),
)
def test_invalid_layout_inputs_are_rejected(slot_ids, mode: str) -> None:
    with pytest.raises(ValueError):
        build_research_workspace_layout(slot_ids, mode)
    with pytest.raises(ValueError):
        build_research_workspace_layout((), "unknown")


def test_layout_and_widget_package_import_without_pyside6() -> None:
    script = """
import builtins

original_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name == "PySide6" or name.startswith("PySide6."):
        raise ModuleNotFoundError("PySide6 blocked by Task 1019 regression")
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked_import

import leonardo.gui.widgets as widgets
expected = [
    "DEFAULT_SUITE_NAVIGATION_SEGMENTS",
    "SuiteNavigationDonut",
    "SuiteNavigationDonutGeometry",
    "SuiteNavigationSegment",
    "calculate_suite_navigation_donut_geometry",
    "StudyManagerWidget",
    "ResearchChartSlotWidget",
    "ResearchWorkspaceWidget",
]
assert widgets.__all__ == expected
assert not set(expected).intersection(vars(widgets))
try:
    widgets.unknown_export
except AttributeError:
    pass
else:
    raise AssertionError("unknown widget export did not raise AttributeError")

from leonardo.gui.widgets.research_workspace_layout import (
    build_research_workspace_layout,
)
plan = build_research_workspace_layout((1, 3, 8), "scroll_4")
assert tuple(item.slot_id for item in plan.items) == (1, 3, 8)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(Path.cwd() / "src"), str(Path.cwd())))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
