from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from leonardo.gui.widgets.study_source_selector_widget import StudySourceSelectorWidget
from leonardo.research import (
    ResearchStudySetupService,
    StudyArtifactOption,
    StudyEnvironmentStore,
    StudySetupDraft,
    StudySetupCatalogRejection,
    build_study_request,
    source_role_schema,
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


def test_braid_mid_is_fixed_while_trap_area_mid_remains_optional(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    catalog = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "env")
    ).build_catalog(dataset, ())

    for tool_key in ("braids", "braid_instability"):
        widget = StudySourceSelectorWidget(catalog, source_role_schema(tool_key))
        assert tuple(row.role for row in widget._rows) == ("fast", "mid", "slow")
        assert widget._add.isHidden()
        mid = next(row for row in widget._rows if row.role == "mid")
        assert mid.remove.isHidden()

    trap_area = StudySourceSelectorWidget(catalog, source_role_schema("trap_area"))
    assert tuple(row.role for row in trap_area._rows) == ("fast", "slow")
    assert trap_area._add.text() == "Add Mid"
    assert not trap_area._add.isHidden()


def test_delta_uses_contextual_labels_without_changing_canonical_roles(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    catalog = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "env")
    ).build_catalog(dataset, ())
    delta = StudySourceSelectorWidget(
        catalog,
        source_role_schema("delta"),
        role_labels={"fast": "Minuend", "slow": "Subtrahend"},
    )
    assert tuple(
        row.container.findChild(QLabel).text() for row in delta._rows
    ) == ("Minuend", "Subtrahend")
    delta.select_option("fast", catalog.ohlcv_sources[3])
    delta.select_option("slow", catalog.ohlcv_sources[0])
    assert tuple(selection.role for selection in delta.selections()) == (
        "fast",
        "slow",
    )

    for tool_key, labels in (
        ("braids", ("Fast", "Mid", "Slow")),
        ("braid_instability", ("Fast", "Mid", "Slow")),
        ("trap_area", ("Fast", "Slow")),
    ):
        selector = StudySourceSelectorWidget(
            catalog, source_role_schema(tool_key)
        )
        assert tuple(
            row.container.findChild(QLabel).text() for row in selector._rows
        ) == labels


def test_utc_has_four_mandatory_stable_generic_role_rows(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    catalog = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "env")
    ).build_catalog(dataset, ())
    widget = StudySourceSelectorWidget(
        catalog,
        source_role_schema("universal_trend_classifier"),
    )

    assert tuple(row.role for row in widget._rows) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )
    assert tuple(
        row.container.findChild(QLabel).text() for row in widget._rows
    ) == (
        "Trend Peak",
        "Trend Trough",
        "Range Peak",
        "Range Trough",
    )
    assert widget._add.isHidden()
    assert all(row.remove.isHidden() for row in widget._rows)
