from __future__ import annotations

import os
from time import perf_counter
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.gui.data_manager.catalogs import DataManagerCatalogWorkspace
from leonardo.gui.data_manager.update import DataManagerUpdateWorkspace


def _measure_catalog_rows(count: int, columns: int) -> float:
    workspace = DataManagerCatalogWorkspace()
    try:
        workspace._all_rows = tuple(
            (tuple(f"value-{row}-{column}" for column in range(columns)), row)
            for row in range(count)
        )
        started = perf_counter()
        workspace._populate()
        elapsed = perf_counter() - started
        assert workspace.table.rowCount() == count
        return elapsed
    finally:
        workspace.close()


def test_large_catalog_and_dependency_plan_rendering_are_responsive() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    recipe_elapsed = _measure_catalog_rows(1000, 11)
    artifact_elapsed = _measure_catalog_rows(1000, 12)
    collection_elapsed = _measure_catalog_rows(200, 12)
    database_elapsed = _measure_catalog_rows(100, 13)

    update = DataManagerUpdateWorkspace()
    try:
        nodes = tuple(
            SimpleNamespace(
                portable_recipe_id=f"{index:064x}",
                logical_artifact_id=f"{index + 1000:064x}",
                tool_key="sma",
                role="ROOT",
                action="CREATE",
                update_strategy=SimpleNamespace(value="FULL_RECALCULATION"),
                context_rows=0,
                revisable_tail_rows=0,
                blockers=(),
            )
            for index in range(100)
        )
        started = perf_counter()
        update.set_artifact_plan(SimpleNamespace(nodes=nodes))
        plan_elapsed = perf_counter() - started
        assert update.artifact_plan_table.rowCount() == 100
    finally:
        update.close()

    measurements = {
        "recipes": recipe_elapsed,
        "artifacts": artifact_elapsed,
        "collections": collection_elapsed,
        "databases": database_elapsed,
        "dependency_plan": plan_elapsed,
    }
    print("Task 1061 GUI performance:", measurements)
    assert recipe_elapsed < 5.0
    assert artifact_elapsed < 5.0
    assert plan_elapsed < 5.0
