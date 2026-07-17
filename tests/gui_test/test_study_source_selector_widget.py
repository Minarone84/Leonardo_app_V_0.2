from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.gui.widgets.study_source_selector_widget import StudySourceSelectorWidget
from leonardo.research import (
    ResearchStudySetupService,
    StudyArtifactOption,
    StudyEnvironmentStore,
    StudySetupDraft,
    StudySetupCatalogRejection,
    build_study_request,
)
from tests.research_test.test_study_execution import accepted_context


def test_source_selector_emits_canonical_fixed_and_multi_source_intent(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    catalog = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "env")
    ).build_catalog(dataset, ())
    widget = StudySourceSelectorWidget(catalog, ("source",))
    widget.select_option("source", catalog.ohlcv_sources[3])
    assert widget.objectName() == "research.study_source_selector"
    assert widget.selections()[0].column_name == "close"

    widget.set_schema(("source_1", "..."))
    widget.select_option("source_1", catalog.ohlcv_sources[0])
    widget.findChild(type(widget._add), "research.study_source_selector.button.add").click()
    widget.select_option("source_2", catalog.ohlcv_sources[4])
    assert tuple(item.role for item in widget.selections()) == ("source_1", "source_2")


def test_saved_artifact_sources_show_disabled_rejections_and_non_analysis_outputs(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    base = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "env")
    ).build_catalog(dataset, ())
    artifact_id = "a" * 64
    catalog = replace(
        base,
        artifact_options=(
            StudyArtifactOption(
                dataset.market_id,
                artifact_id,
                "indicator",
                "ema",
                "Saved EMA",
                ("ema_20", "ema_state"),
                ("ema_20",),
            ),
        ),
        artifact_rejections=(
            StudySetupCatalogRejection("b" * 64, "indicator", "sma", "stale"),
        ),
    )
    widget = StudySourceSelectorWidget(catalog, ("source",))
    emissions: list[None] = []
    widget.intent_changed.connect(lambda: emissions.append(None))
    widget.set_catalog(catalog)
    assert emissions == []

    row = widget._rows[0]
    row.kind.setCurrentIndex(row.kind.findData("artifact"))
    labels = tuple(row.item.itemText(index) for index in range(row.item.count()))
    assert labels == (
        "Saved EMA: ema_20",
        "Saved EMA: ema_state - not analysis-usable",
        f"sma: {'b' * 64} - stale",
    )
    assert row.item.model().item(0).isEnabled()
    assert not row.item.model().item(1).isEnabled()
    assert not row.item.model().item(2).isEnabled()
    assert row.item.itemData(1) is None
    assert row.item.itemData(2) is None

    valid = next(
        option
        for option in catalog.source_options
        if option.source_kind == "artifact"
    )
    widget.select_option("source", valid)
    selection = widget.selections()[0]
    assert selection.output_name == "ema_20"
    request = build_study_request(
        StudySetupDraft("calculation", "derivative", sources=(selection,)),
        catalog,
    )
    assert request.input_sources[0].artifact_id == artifact_id
    assert request.input_sources[0].output_name == "ema_20"
    row.item.setCurrentIndex(1)
    assert widget.selections() == ()
    row.kind.setCurrentIndex(row.kind.findData("ohlcv"))
    assert row.item.currentIndex() == -1
    assert widget.selections() == ()
