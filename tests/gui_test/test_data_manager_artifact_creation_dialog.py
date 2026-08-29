from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QLineEdit

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
    DataManagerDirectArtifactRequest,
    DataManagerDirectArtifactResult,
)
from leonardo.data_manager.models import (
    DataManagerArtifactMaterializationResult,
    DataManagerManagedArtifactEntry,
)
from leonardo.gui.windows.data_manager_artifact_creation_dialog import (
    DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID,
    DataManagerArtifactCreationDialog,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
OTHER_MARKET = MarketId("bybit", "linear", "ETHUSDT", "1h")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fingerprint(market: MarketId = MARKET) -> OHLCVSourceFingerprintV1:
    return OHLCVSourceFingerprintV1(
        market,
        "1" * 64,
        "2" * 64,
        10,
        1,
        10,
        "committed",
        "ok",
        "1.0",
    )


def _result(*, created: bool) -> DataManagerDirectArtifactResult:
    recipe_id = "f" * 64
    logical_artifact_id = "d" * 64
    artifact_id = "c" * 64
    managed = DataManagerManagedArtifactEntry(
        logical_artifact_id,
        recipe_id,
        MARKET,
        artifact_id,
        None,
        "sma",
        "indicator",
        ("sma_7",),
        10,
        1,
        10,
        datetime(2026, 8, 9, tzinfo=UTC),
    )
    version_key = ManagedArtifactVersionKey(logical_artifact_id, artifact_id)
    return DataManagerDirectArtifactResult(
        recipe_id,
        DataManagerArtifactMaterializationResult(
            "e" * 64,
            MARKET,
            _fingerprint(),
            (logical_artifact_id,),
            (),
            (artifact_id,) if created else (),
            () if created else (artifact_id,),
            (version_key,) if created else (),
            () if created else (version_key,),
            (logical_artifact_id,) if created else (),
            (managed,),
        ),
    )


def _option(
    key: str,
    kind: str,
    outputs: tuple[str, ...],
    ordinal: int,
    *,
    market: MarketId = MARKET,
) -> DataManagerDirectArtifactOption:
    return DataManagerDirectArtifactOption(
        market,
        f"{ordinal:x}" * 64,
        f"{ordinal + 8:x}" * 64,
        key,
        kind,
        key.replace("_", " ").title(),
        outputs,
        _fingerprint(market),
    )


def _catalog(market: MarketId = MARKET) -> DataManagerDirectArtifactCatalog:
    return DataManagerDirectArtifactCatalog(
        market,
        _fingerprint(market),
        (
            _option("sma", "indicator", ("sma_20",), 1, market=market),
            _option("rsi", "oscillator", ("rsi_14",), 2, market=market),
            _option("derivative", "construct", ("derivative_sma",), 3, market=market),
        ),
        (
            _option(
                "peaks_troughs",
                "indicator",
                (
                    "peak_fractal_3",
                    "trough_fractal_3",
                    "peak_fractal_5",
                    "trough_fractal_5",
                ),
                4,
                market=market,
            ),
        ),
    )


def _select(dialog: DataManagerArtifactCreationDialog, key: str) -> None:
    for row in range(dialog.tool_list.count()):
        item = dialog.tool_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole).key == key:
            dialog.tool_list.setCurrentRow(row)
            return
    raise AssertionError(f"tool not found: {key}")


def _choose_sources(dialog: DataManagerArtifactCreationDialog) -> None:
    assert dialog._editor is not None
    for row in dialog.source_selector._rows:
        option = next(
            item
            for item in dialog._editor._catalog.source_options
            if item.source_kind == "artifact"
        )
        dialog.source_selector.select_option(row.role, option)


def _assert_saved_artifact_kinds(dialog: DataManagerArtifactCreationDialog) -> None:
    assert dialog.source_selector is not None
    for row in dialog.source_selector._rows:
        assert row.kind.count() == 1
        assert row.kind.itemText(0) == "Saved Artifact"
        assert row.kind.itemData(0) == "artifact"
        assert row.kind.findText("OHLCV") == -1
        assert row.kind.findText("Current Study") == -1


def test_dialog_identity_families_and_research_parameter_editor(qapp) -> None:
    dialog = DataManagerArtifactCreationDialog(_catalog())
    try:
        assert dialog.objectName() == DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID
        assert dialog.property("object_id") == "data_manager.artifact_creation.window"
        assert dialog.windowTitle() == "Create Artifact"
        assert not dialog.isModal()
        selected = dialog.findChild(
            QGroupBox, "data_manager.artifact_creation.selected_dataset"
        )
        assert selected is not None and selected.title() == "Selected Dataset"
        fields = {
            key: dialog.findChild(
                QLineEdit,
                f"data_manager.artifact_creation.dataset.{key}",
            )
            for key in ("exchange", "market_type", "asset", "timeframe")
        }
        assert {key: field.text() for key, field in fields.items()} == {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "asset": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        }
        assert all(
            "Target MarketId" not in label.text()
            for label in dialog.findChildren(QLabel)
        )
        assert tuple(dialog.family_combo.itemText(index) for index in range(4)) == (
            "All",
            "Indicator",
            "Oscillator",
            "Construct",
        )
        assert "Dynamic Binning" not in tuple(
            dialog.tool_list.item(row).text() for row in range(dialog.tool_list.count())
        )
        assert dialog.calculate_button.text() == "Calculate Artifact"
        assert dialog.findChild(object, "research.financial_tools.button.apply") is None
        assert dialog.findChild(object, "research.financial_tools.saved_artifacts") is None

        _select(dialog, "sma")
        assert "period" in dialog.parameter_controls
        _select(dialog, "rsi")
        assert "period" in dialog.parameter_controls

        dialog.invalidate_target()
        assert all(field.text() == "" for field in fields.values())
        dialog.set_catalog(_catalog(OTHER_MARKET))
        assert {key: field.text() for key, field in fields.items()} == {
            "exchange": OTHER_MARKET.exchange,
            "market_type": OTHER_MARKET.market_type,
            "asset": OTHER_MARKET.symbol,
            "timeframe": OTHER_MARKET.timeframe,
        }
    finally:
        dialog.close()


def test_construct_and_utc_sources_are_catalog_bounded(qapp) -> None:
    dialog = DataManagerArtifactCreationDialog(_catalog())
    try:
        _select(dialog, "derivative")
        _assert_saved_artifact_kinds(dialog)
        options = dialog._editor._catalog.artifact_options
        assert {item.tool_key for item in options} == {"sma", "rsi", "derivative"}
        assert "peaks_troughs" not in {item.tool_key for item in options}
        assert "universal_trend_classifier" not in {item.tool_key for item in options}
        assert "braids" not in {item.tool_key for item in options}
        assert any(item.tool_key == "derivative" for item in options)

        _select(dialog, "universal_trend_classifier")
        utc_options = dialog._editor._catalog.artifact_options
        assert {item.tool_key for item in utc_options} == {"peaks_troughs"}
        assert not hasattr(dialog.source_selector, "_rows")
    finally:
        dialog.close()


@pytest.mark.parametrize("tool_key", ("braids", "braid_instability"))
def test_mixed_family_braids_build_data_manager_requests(qapp, tool_key) -> None:
    dialog = DataManagerArtifactCreationDialog(_catalog())
    try:
        _select(dialog, tool_key)
        assert dialog.source_selector.schema == ("fast", "mid", "slow")
        _assert_saved_artifact_kinds(dialog)
        assert dialog._editor is not None
        options = tuple(
            item
            for item in dialog._editor._catalog.source_options
            if item.source_kind == "artifact"
        )
        for role, option in zip(("fast", "mid", "slow"), options, strict=True):
            dialog.source_selector.select_option(role, option)
        request = dialog._build_request()
        assert isinstance(request, DataManagerDirectArtifactRequest)
        assert request.tool_key == tool_key
        assert tuple(source.role for source in request.sources) == (
            "fast",
            "mid",
            "slow",
        )
        assert {source.artifact_id for source in request.sources} == {
            item.artifact_id for item in _catalog().construct_options
        }
    finally:
        dialog.close()


def test_dynamic_construct_rows_are_saved_artifact_only(qapp) -> None:
    dialog = DataManagerArtifactCreationDialog(_catalog())
    try:
        _select(dialog, "trap_area")
        _assert_saved_artifact_kinds(dialog)
        dialog.source_selector._add.click()
        assert tuple(row.role for row in dialog.source_selector._rows) == (
            "fast",
            "mid",
            "slow",
        )
        _assert_saved_artifact_kinds(dialog)

        _select(dialog, "angle_momentum")
        _assert_saved_artifact_kinds(dialog)
        dialog.source_selector._add.click()
        assert len(dialog.source_selector._rows) == 2
        _assert_saved_artifact_kinds(dialog)
    finally:
        dialog.close()


def test_mixed_saved_source_request_and_same_market_refresh_preserve_selection(
    qapp,
) -> None:
    dialog = DataManagerArtifactCreationDialog(_catalog())
    try:
        _select(dialog, "derivative")
        option = next(
            item
            for item in dialog._editor._catalog.source_options
            if item.source_kind == "artifact" and item.artifact_tool_key == "rsi"
        )
        role = dialog.source_selector._rows[0].role
        dialog.source_selector.select_option(role, option)
        request = dialog._build_request()
        assert isinstance(request, DataManagerDirectArtifactRequest)
        assert request.sources[0].artifact_id == option.artifact_id
        assert request.sources[0].output_name == option.output_name

        dialog.set_catalog(_catalog(), preserve_configuration=True)
        _assert_saved_artifact_kinds(dialog)
        selection = dialog.source_selector.selections()[0]
        assert selection.source_kind == "artifact"
        assert selection.artifact_id == option.artifact_id
        assert selection.output_name == option.output_name
    finally:
        dialog.close()


def test_calculate_busy_refresh_invalidation_and_success_lifecycle(qapp) -> None:
    dialog = DataManagerArtifactCreationDialog(_catalog())
    emitted: list[object] = []
    dialog.calculate_requested.connect(emitted.append)
    try:
        _select(dialog, "sma")
        dialog.parameter_controls["period"].setValue(7)
        dialog.calculate_button.click()
        assert len(emitted) == 1
        assert isinstance(emitted[0], DataManagerDirectArtifactRequest)
        assert emitted[0].parameters["period"] == 7

        dialog.set_busy(True)
        assert not dialog.calculate_button.isEnabled()
        dialog.set_busy(False)
        assert dialog.calculate_button.isEnabled()
        dialog.set_catalog(_catalog(), preserve_configuration=True)
        assert dialog._current_spec.key == "sma"
        assert dialog.parameter_controls["period"].value() == 7

        logical_artifact_id = "d" * 64
        recipe_id = "f" * 64
        dialog.settle_success(_result(created=True))
        assert dialog._current_spec.key == "sma"
        assert dialog.status_label.text() == (
            f"Root Artifact created: {logical_artifact_id}"
        )
        assert recipe_id not in dialog.status_label.text()
        assert dialog.parameter_controls["period"].value() == 7

        dialog.settle_success(_result(created=False))
        assert dialog.status_label.text() == (
            f"Root Artifact current/reused: {logical_artifact_id}"
        )
        assert recipe_id not in dialog.status_label.text()
        assert dialog._current_spec.key == "sma"
        assert dialog.parameter_controls["period"].value() == 7

        dialog.set_catalog(_catalog(OTHER_MARKET), preserve_configuration=False)
        assert dialog.market_id == OTHER_MARKET
        assert dialog._current_spec is None
        assert dialog.source_selector is None
        assert not dialog.calculate_button.isEnabled()
    finally:
        dialog.close()
