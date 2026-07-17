from __future__ import annotations

import builtins
import importlib
import sys

from leonardo.gui.widgets.research_workspace_layout import (
    build_research_workspace_layout,
    build_research_workspace_layout_in_order,
)


def test_ordered_layout_preserves_supplied_order_and_geometry() -> None:
    plan = build_research_workspace_layout_in_order((5, 4, 3), "scroll_4")
    assert [(item.slot_id, item.row, item.column, item.column_span) for item in plan.items] == [
        (5, 0, 0, 2),
        (4, 1, 0, 1),
        (3, 1, 1, 1),
    ]


def test_ordered_layout_supports_zero_through_eight_and_old_api_still_sorts() -> None:
    for count in range(9):
        supplied = tuple(range(8, 8 - count, -1))
        assert tuple(
            item.slot_id
            for item in build_research_workspace_layout_in_order(
                supplied, "fit_8"
            ).items
        ) == supplied
    assert tuple(
        item.slot_id
        for item in build_research_workspace_layout((7, 2, 5), "scroll_4").items
    ) == (2, 5, 7)


def test_pure_layout_module_imports_without_pyside6(monkeypatch) -> None:
    module_name = "leonardo.gui.widgets.research_workspace_layout"
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("PySide6"):
            raise AssertionError("pure layout imported PySide6")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    sys.modules.pop(module_name, None)
    importlib.import_module(module_name)
