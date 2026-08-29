from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTreeWidget,
    QWidget,
)

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import DataManagerDatasetEntry
from leonardo.data_manager.construct_batch import (
    ConstructBatchExpansionRequest,
    ConstructBatchSourceScope,
    current_ohlcv_signals,
    expand_construct_batch,
)
from leonardo.data_manager.creation_models import BatchArtifactPlan
from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
)
from leonardo.gui.windows.data_manager_construct_batch_dialog import (
    DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID,
    DataManagerConstructBatchDialog,
)
from leonardo.gui.data_manager.table_presentation import (
    DATA_MANAGER_DATASET_COLUMNS,
    data_manager_dataset_details,
    data_manager_dataset_row,
)
from leonardo.gui.windows import data_manager_construct_batch_dialog as dialog_module


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
_QAPP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def qapp():
    return _QAPP


def _dispose_dialog(dialog) -> None:
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
    _QAPP.processEvents()


def _catalog(
    market=MARKET,
    *,
    kinds=("indicator", "oscillator"),
    include_bb=False,
    csv_sha="1" * 64,
):
    source = OHLCVSourceFingerprintV1(
        market, csv_sha, "2" * 64, 6, 1, 6, "committed", "ok", "1.0"
    )
    definitions = {
        "indicator": (
            "a",
            "b",
            "sma",
            "indicator",
            "SMA",
            ("sma_20",),
        ),
        "oscillator": (
            "c",
            "d",
            "rsi",
            "oscillator",
            "RSI",
            ("rsi_14",),
        ),
        "construct": (
            "e",
            "f",
            "derivative",
            "construct",
            "Derivative",
            ("derivative",),
        ),
    }
    options = [definitions[kind] for kind in kinds]
    if include_bb:
        options.append(
            (
                "0",
                "9",
                "bb",
                "indicator",
                "Bollinger Bands [period=20, std=2]",
                ("bb_middle", "bb_upper_band", "bb_lower_band"),
            )
        )
    return DataManagerDirectArtifactCatalog(
        market,
        source,
        tuple(
            DataManagerDirectArtifactOption(
                market,
                logical * 64,
                artifact * 64,
                tool_key,
                kind,
                display_name,
                output_names,
                source,
            )
            for logical, artifact, tool_key, kind, display_name, output_names in options
        ),
        (),
    )


def _dataset_entry(catalog):
    source = catalog.source_ohlcv
    return DataManagerDatasetEntry(
        market_id=source.market_id,
        accepted=True,
        row_count=source.row_count,
        first_timestamp_ms=source.first_timestamp_ms,
        last_timestamp_ms=source.last_timestamp_ms,
        persistence_status=source.persistence_status,
        validation_status=source.validation_status,
    )


def _artifact_items(dialog):
    return tuple(
        dialog.selected_signals.topLevelItem(index)
        for index in range(dialog.selected_signals.topLevelItemCount())
        if isinstance(
            dialog.selected_signals.topLevelItem(index).data(
                0, Qt.ItemDataRole.UserRole
            ),
            DataManagerDirectArtifactOption,
        )
    )


def _source_items(dialog):
    return tuple(
        dialog.selected_signals.topLevelItem(index)
        for index in range(dialog.selected_signals.topLevelItemCount())
    )


def _current_dataset_item(dialog):
    return next(
        item for item in _source_items(dialog) if item.text(0) == "Current Dataset"
    )


def _signal_items(dialog):
    return tuple(
        parent.child(index)
        for parent in _source_items(dialog)
        for index in range(parent.childCount())
    )


def _artifact_signal_items(dialog):
    return tuple(
        parent.child(index)
        for parent in _artifact_items(dialog)
        for index in range(parent.childCount())
    )


def _visible_signal_items(dialog):
    return tuple(
        item for item in _signal_items(dialog) if not item.isHidden()
    )


def _visible_signals(dialog):
    return tuple(
        item.data(0, Qt.ItemDataRole.UserRole)
        for item in _visible_signal_items(dialog)
    )


def _plan(request, reuse=False):
    return BatchArtifactPlan(
        request=request,
        branch_recipe_ids=("e" * 64,),
        branch_reuse_current=(reuse,),
        recipe_ids=("e" * 64,),
        dependency_edges=(),
        execution_stages=(("e" * 64,),),
        new_recipe_ids=() if reuse else ("e" * 64,),
        reusable_recipe_ids=("e" * 64,) if reuse else (),
        new_logical_artifact_ids=() if reuse else ("f" * 64,),
        reusable_logical_artifact_ids=("f" * 64,) if reuse else (),
        naming_collisions=(),
        unsupported_combinations=(),
        blockers=(),
    )


def _plan_for_branches(request):
    recipe_ids = tuple(
        f"{index:064x}" for index in range(1, len(request.branches) + 1)
    )
    logical_ids = tuple(
        f"{index:064x}" for index in range(101, len(request.branches) + 101)
    )
    return BatchArtifactPlan(
        request=request,
        branch_recipe_ids=recipe_ids,
        branch_reuse_current=(False,) * len(request.branches),
        recipe_ids=recipe_ids,
        dependency_edges=(),
        execution_stages=(recipe_ids,),
        new_recipe_ids=recipe_ids,
        reusable_recipe_ids=(),
        new_logical_artifact_ids=logical_ids,
        reusable_logical_artifact_ids=(),
        naming_collisions=(),
        unsupported_combinations=(),
        blockers=(),
    )


def test_dialog_identity_construct_choices_and_dataset_context(qapp) -> None:
    catalog = _catalog()
    dialog = DataManagerConstructBatchDialog(catalog)
    try:
        assert dialog.objectName() == DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID
        assert dialog.windowTitle() == "Batch Constructs"
        assert not dialog.isModal()
        assert tuple(
            dialog.construct_combo.itemData(index)
            for index in range(dialog.construct_combo.count())
        ) == (
            "derivative",
            "angle",
            "percent_span_angle",
            "angle_momentum",
            "delta",
            "trap_area",
            "braids",
            "braid_instability",
        )
        assert tuple(
            dialog.scope_combo.itemText(index)
            for index in range(dialog.scope_combo.count())
        ) == tuple(scope.value for scope in ConstructBatchSourceScope)
        table = dialog.dataset_table
        assert isinstance(table, QTableWidget)
        assert table.objectName() == "data_manager.construct_batch.dataset_table"
        assert tuple(
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())
        ) == DATA_MANAGER_DATASET_COLUMNS
        assert table.rowCount() == 1
        entry = _dataset_entry(catalog)
        assert tuple(
            table.item(0, column).text() for column in range(table.columnCount())
        ) == data_manager_dataset_row(entry)
        assert table.item(0, 10).toolTip() == data_manager_dataset_details(entry)
        assert table.item(0, 7).text() == "6"
        assert table.item(0, 8).text() == "1970-01-01 00:00:00 UTC"
        assert table.item(0, 9).text() == "1970-01-01 00:00:00 UTC"
        assert table.item(0, 5).text() == "committed"
        assert table.item(0, 6).text() == "ok"
        assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        assert table.selectionMode() == QAbstractItemView.SelectionMode.NoSelection
        assert table.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert not table.wordWrap()
        assert (
            table.horizontalScrollMode()
            == QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        for key in ("exchange", "market_type", "asset", "timeframe"):
            assert dialog.findChild(
                QLineEdit, f"data_manager.construct_batch.dataset.{key}"
            ) is None
    finally:
        _dispose_dialog(dialog)


def test_source_controls_and_recap_share_horizontal_layout_without_splitter(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    try:
        dialog.show()
        qapp.processEvents()
        assert isinstance(dialog.selected_signals, QTreeWidget)
        assert dialog.findChild(
            QWidget, "data_manager.construct_batch.source_preview_splitter"
        ) is None
        assert dialog.findChild(
            QWidget, "data_manager.construct_batch.sources.select_all"
        ) is None
        assert dialog.findChild(
            QWidget, "data_manager.construct_batch.sources.deselect_all"
        ) is None
        assert isinstance(dialog.source_recap_layout, QHBoxLayout)
        assert dialog.source_recap_layout.indexOf(dialog.source_group) == 0
        assert dialog.source_recap_layout.indexOf(dialog.recap_group) == 1
        assert isinstance(dialog.recap_group, QGroupBox)
        assert dialog.recap_group.title() == "Recap"
        assert dialog.recap_group.objectName() == "data_manager.construct_batch.recap"
        assert dialog.findChildren(QSplitter) == []
        root = dialog.layout()
        working_index = next(
            index
            for index in range(root.count())
            if root.itemAt(index).layout() is dialog.source_recap_layout
        )
        destination_layout = root.itemAt(working_index + 1).layout()
        assert destination_layout is not None
        assert destination_layout.indexOf(dialog.destination_combo) >= 0
    finally:
        _dispose_dialog(dialog)


def test_dataset_table_retargets_and_invalidates_without_stale_cells(qapp) -> None:
    first = _catalog()
    second = _catalog(
        MarketId("bybit", "linear", "ETHUSDT", "1M"),
        kinds=("construct",),
    )
    dialog = DataManagerConstructBatchDialog(first)
    table = dialog.dataset_table
    try:
        _signal_items(dialog)[0].setCheckState(0, Qt.CheckState.Checked)
        dialog.set_catalog(second, preserve_configuration=False)
        assert dialog.dataset_table is table
        assert table.rowCount() == 1
        assert tuple(
            table.item(0, column).text() for column in range(table.columnCount())
        ) == data_manager_dataset_row(_dataset_entry(second))
        assert table.item(0, 2).text() == "ETHUSDT"
        assert table.item(0, 3).text() == "1M"
        assert all(
            "BTCUSDT" not in table.item(0, column).text()
            for column in range(table.columnCount())
        )
        assert tuple(
            item.data(0, Qt.ItemDataRole.UserRole).tool_key
            for item in _artifact_signal_items(dialog)
        ) == ("derivative",)
        assert all(
            item.checkState(0) == Qt.CheckState.Unchecked
            for item in _signal_items(dialog)
        )

        dialog.invalidate_target()
        assert table.rowCount() == 0
        assert dialog.selected_signals.topLevelItemCount() == 0
        assert "Select an accepted dataset" in dialog.source_empty.text()
    finally:
        _dispose_dialog(dialog)


def test_preview_intent_exact_rows_and_configuration_invalidation(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    received: list[ConstructBatchExpansionRequest] = []
    dialog.preview_requested.connect(received.append)
    try:
        first = _artifact_signal_items(dialog)[0]
        first.setCheckState(0, Qt.CheckState.Checked)
        dialog.preview_button.click()
        assert len(received) == 1
        request = expand_construct_batch(received[0])
        assert request.branches[0].sources[0].artifact_id == "b" * 64

        plan = _plan(request, reuse=True)
        dialog.set_plan(plan)
        assert dialog.preview_table.horizontalHeaderItem(0).text() == "Source(s)"
        assert dialog.preview_table.horizontalHeaderItem(3).text() == "Inputs"
        assert dialog.preview_table.horizontalHeaderItem(4).text() == "Result"
        assert dialog.preview_table.item(0, 3).text().startswith("source=")
        assert dialog.preview_table.item(0, 4).text() == "Reuse Current"
        assert dialog.execute_button.isEnabled()

        dialog.scope_combo.setCurrentIndex(
            dialog.scope_combo.findData(
                ConstructBatchSourceScope.ALL_INDICATORS.value
            )
        )
        assert dialog.reviewed_plan is None
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.execute_button.isEnabled()
    finally:
        _dispose_dialog(dialog)


def test_explicit_triples_are_user_added_and_target_invalidation_clears_state(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    try:
        for item in _signal_items(dialog):
            item.setCheckState(0, Qt.CheckState.Checked)
        dialog.construct_combo.setCurrentIndex(
            dialog.construct_combo.findData("braids")
        )
        dialog.add_combination_button.click()
        dialog.add_combination_button.click()
        assert dialog.combination_table.rowCount() == 2
        assert dialog.add_combination_button.text() == "Add Triple"

        dialog.invalidate_target()
        assert dialog.market_id is None
        assert dialog.combination_table.rowCount() == 0
        assert not dialog.preview_button.isEnabled()
        assert not dialog.execute_button.isEnabled()
    finally:
        _dispose_dialog(dialog)


def test_success_keeps_visible_window_open_and_requires_new_preview(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    try:
        dialog.show()
        QCoreApplication.processEvents()
        _signal_items(dialog)[0].setCheckState(0, Qt.CheckState.Checked)
        request = expand_construct_batch(dialog._build_expansion_request())
        dialog.set_plan(_plan(request))
        assert dialog.execution_report is None
        dialog.settle_success(
            total_branches=8,
            new_branches=6,
            reused_branches=2,
        )
        assert dialog.isVisible()
        assert dialog.reviewed_plan is None
        assert not dialog.execute_button.isEnabled()
        report = dialog.execution_report
        assert report is not None and report.isVisible()
        assert report.parent() is dialog
        assert report.objectName() == "data_manager.construct_batch.execution_report"
        assert report.windowTitle() == "Batch Execution Complete"
        assert report.summary_label.text() == (
            "8 / 8 branches completed successfully"
        )
        assert report.new_label.text() == "New: 6"
        assert report.reused_label.text() == "Reuse Current: 2"
        assert len(report.findChildren(QPushButton)) == 1
        assert report.findChildren(QProgressBar) == []

        report.ok_button.click()
        qapp.processEvents()
        assert not report.isVisible()
        assert dialog.isVisible()
        assert dialog.reviewed_plan is None
        assert not dialog.execute_button.isEnabled()

        dialog.settle_success(
            total_branches=8,
            new_branches=8,
            reused_branches=0,
        )
        assert dialog.execution_report is report
        assert report.isVisible()
        assert report.new_label.text() == "New: 8"
        assert report.reused_label.text() == "Reuse Current: 0"
        dialog.close()
        qapp.processEvents()
        assert not report.isVisible()
    finally:
        _dispose_dialog(dialog)


@pytest.mark.parametrize(
    ("values", "error"),
    (
        ({"total_branches": 0, "new_branches": 0, "reused_branches": 0}, ValueError),
        ({"total_branches": 8, "new_branches": -1, "reused_branches": 9}, ValueError),
        ({"total_branches": 8, "new_branches": 6, "reused_branches": 1}, ValueError),
        ({"total_branches": True, "new_branches": 1, "reused_branches": 0}, TypeError),
    ),
)
def test_terminal_report_rejects_invalid_success_counts(qapp, values, error) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    try:
        with pytest.raises(error):
            dialog.settle_success(**values)
        assert dialog.execution_report is None
    finally:
        _dispose_dialog(dialog)


def test_batch_tables_reuse_shared_data_manager_sizing(
    qapp, monkeypatch,
) -> None:
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        dialog_module,
        "resize_data_manager_table",
        lambda table: calls.append((table.objectName(), table.rowCount())),
    )
    dialog = dialog_module.DataManagerConstructBatchDialog(_catalog())
    try:
        assert ("data_manager.construct_batch.dataset_table", 1) in calls
        assert "data_manager.construct_batch.combinations" in {
            name for name, _rows in calls
        }
        assert "data_manager.construct_batch.preview" in {
            name for name, _rows in calls
        }

        for item in _signal_items(dialog):
            item.setCheckState(0, Qt.CheckState.Checked)
        dialog.construct_combo.setCurrentIndex(
            dialog.construct_combo.findData("braids")
        )
        calls.clear()
        dialog.add_combination_button.click()
        assert ("data_manager.construct_batch.combinations", 1) in calls
        assert ("data_manager.construct_batch.preview", 0) in calls
        calls.clear()
        dialog.remove_combination_button.click()
        assert ("data_manager.construct_batch.combinations", 0) in calls
        assert ("data_manager.construct_batch.preview", 0) in calls

        dialog.construct_combo.setCurrentIndex(
            dialog.construct_combo.findData("derivative")
        )
        dialog.scope_combo.setCurrentIndex(
            dialog.scope_combo.findData(
                ConstructBatchSourceScope.ALL_INDICATORS.value
            )
        )
        request = expand_construct_batch(dialog._build_expansion_request())
        dialog.set_plan(_plan(request))
        assert calls[-1] == ("data_manager.construct_batch.preview", 1)
        dialog._configuration_changed()
        assert calls[-1] == ("data_manager.construct_batch.preview", 0)
    finally:
        _dispose_dialog(dialog)


def test_source_scopes_remain_visible_and_preserve_manual_checks(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(
        _catalog(
            kinds=("indicator", "oscillator", "construct"),
            include_bb=True,
        )
    )
    try:
        dialog.show()
        qapp.processEvents()
        assert not dialog.selected_signals.isHidden()
        assert tuple(signal.kind for signal in _visible_signals(dialog)) == (
            "current_ohlcv",
            "current_ohlcv",
            "current_ohlcv",
            "current_ohlcv",
            "indicator",
            "oscillator",
            "construct",
            "indicator",
            "indicator",
            "indicator",
        )
        for item in _signal_items(dialog):
            assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            assert item.data(0, Qt.ItemDataRole.CheckStateRole) is not None
        checked = (
            _signal_items(dialog)[0],
            next(
                item
                for item in _signal_items(dialog)
                if item.data(0, Qt.ItemDataRole.UserRole).tool_key == "bb"
            ),
        )
        for item in checked:
            item.setCheckState(0, Qt.CheckState.Checked)
        expected_checked = tuple(
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in _signal_items(dialog)
            if item in checked
        )
        assert dialog._build_expansion_request().selected_signals == expected_checked

        dialog.set_plan(
            _plan_for_branches(
                expand_construct_batch(dialog._build_expansion_request())
            )
        )
        for scope, kind in (
            (ConstructBatchSourceScope.ALL_INDICATORS, "indicator"),
            (ConstructBatchSourceScope.ALL_OSCILLATORS, "oscillator"),
            (ConstructBatchSourceScope.ALL_CONSTRUCTS, "construct"),
        ):
            dialog.scope_combo.setCurrentIndex(
                dialog.scope_combo.findData(scope.value)
            )
            assert not dialog.selected_signals.isHidden()
            visible = _visible_signals(dialog)
            assert visible
            assert {signal.kind for signal in visible} == {kind}
            if kind == "indicator":
                assert len(visible) == 4
            assert dialog._resolved_pool() == visible
            assert dialog.selected_signals.isEnabled()
            for visible_item in _visible_signal_items(dialog):
                assert not (
                    visible_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                )
                assert (
                    visible_item.data(0, Qt.ItemDataRole.CheckStateRole) is None
                )
            assert dialog.reviewed_plan is None

        dialog.scope_combo.setCurrentIndex(
            dialog.scope_combo.findData(
                ConstructBatchSourceScope.SELECTED_SIGNALS.value
            )
        )
        for item in _signal_items(dialog):
            expected_state = (
                Qt.CheckState.Checked
                if item in checked
                else Qt.CheckState.Unchecked
            )
            assert item.checkState(0) == expected_state
            assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            assert item.data(0, Qt.ItemDataRole.CheckStateRole) is not None
        assert dialog._resolved_pool() == expected_checked
        assert dialog.source_empty.isHidden()
    finally:
        _dispose_dialog(dialog)


@pytest.mark.parametrize(
    ("available_kinds", "scope", "expected_text"),
    (
        (
            ("oscillator", "construct"),
            ConstructBatchSourceScope.ALL_INDICATORS,
            "No eligible Indicator Artifact signals",
        ),
        (
            ("indicator", "construct"),
            ConstructBatchSourceScope.ALL_OSCILLATORS,
            "No eligible Oscillator Artifact signals",
        ),
        (
            ("indicator", "oscillator"),
            ConstructBatchSourceScope.ALL_CONSTRUCTS,
            "No eligible Construct Artifact signals",
        ),
    ),
)
def test_automatic_scope_empty_states_are_explicit(
    qapp, available_kinds, scope, expected_text
) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog(kinds=available_kinds))
    try:
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData(scope.value))
        assert not dialog.selected_signals.isHidden()
        assert _visible_signals(dialog) == ()
        assert expected_text in dialog.source_empty.text()
        assert not dialog.source_empty.isHidden()
    finally:
        _dispose_dialog(dialog)


def test_empty_artifact_catalog_still_exposes_current_dataset_ohlc(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog(kinds=()))
    try:
        assert not dialog.selected_signals.isHidden()
        assert dialog.selected_signals.topLevelItemCount() == 1
        assert _current_dataset_item(dialog).childCount() == 4
        assert dialog.source_empty.isHidden()
    finally:
        _dispose_dialog(dialog)


def test_artifact_tree_stores_canonical_options_and_exact_signal_children(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog(include_bb=True))
    try:
        assert isinstance(dialog.selected_signals, QTreeWidget)
        parents = _artifact_items(dialog)
        assert len(parents) == len(dialog._catalog.construct_options)
        for parent, option in zip(
            parents, dialog._catalog.construct_options, strict=True
        ):
            assert parent.data(0, Qt.ItemDataRole.UserRole) is option
            assert parent.text(0) == option.display_name
            assert parent.childCount() == len(option.output_names)
        items = _artifact_signal_items(dialog)
        assert len(items) == len(dialog._artifact_signals)
        for item, signal in zip(items, dialog._artifact_signals, strict=True):
            assert item.data(0, Qt.ItemDataRole.UserRole) is signal
            assert item.text(0) == signal.output_name
            assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    finally:
        _dispose_dialog(dialog)


def test_parent_and_child_checks_drive_exact_request_and_partial_state(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog(include_bb=True))
    try:
        dialog.show()
        qapp.processEvents()
        parent = next(
            parent
            for parent in _artifact_items(dialog)
            if parent.data(0, Qt.ItemDataRole.UserRole).tool_key == "bb"
        )
        item = parent.child(0)
        signal = item.data(0, Qt.ItemDataRole.UserRole)
        dialog.set_plan(
            _plan(
                expand_construct_batch(
                    ConstructBatchExpansionRequest(
                        dialog._catalog,
                        "derivative",
                        {},
                        ConstructBatchSourceScope.SELECTED_SIGNALS,
                        selected_signals=(signal,),
                    )
                )
            )
        )
        qapp.processEvents()

        assert item.checkState(0) == Qt.CheckState.Unchecked
        item.setCheckState(0, Qt.CheckState.Checked)
        qapp.processEvents()
        assert item.checkState(0) == Qt.CheckState.Checked
        assert parent.checkState(0) == Qt.CheckState.PartiallyChecked
        assert dialog._resolved_pool() == (signal,)
        request = dialog._build_expansion_request()
        assert request.selected_signals == (signal,)
        assert all(
            isinstance(source, type(signal)) for source in request.selected_signals
        )
        assert dialog.reviewed_plan is None
        assert not dialog.execute_button.isEnabled()

        parent.setCheckState(0, Qt.CheckState.Checked)
        assert all(
            parent.child(index).checkState(0) == Qt.CheckState.Checked
            for index in range(parent.childCount())
        )
        assert parent.checkState(0) == Qt.CheckState.Checked
        parent.setCheckState(0, Qt.CheckState.Unchecked)
        assert all(
            parent.child(index).checkState(0) == Qt.CheckState.Unchecked
            for index in range(parent.childCount())
        )
        assert parent.checkState(0) == Qt.CheckState.Unchecked
    finally:
        _dispose_dialog(dialog)


def test_unauthorized_tree_bulk_and_splitter_controls_are_absent(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog(include_bb=True))
    try:
        assert not hasattr(dialog, "source_preview_splitter")
        assert not hasattr(dialog, "select_all_button")
        assert not hasattr(dialog, "deselect_all_button")
        for object_id in (
            "data_manager.construct_batch.source_preview_splitter",
            "data_manager.construct_batch.sources.select_all",
            "data_manager.construct_batch.sources.deselect_all",
        ):
            assert dialog.findChild(QWidget, object_id) is None
    finally:
        _dispose_dialog(dialog)


def test_current_dataset_tree_exact_checks_and_fixed_signal_entries(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    try:
        parent = _current_dataset_item(dialog)
        assert parent.data(0, Qt.ItemDataRole.UserRole) == "current_ohlcv"
        assert tuple(parent.child(index).text(0) for index in range(parent.childCount())) == (
            "Open",
            "High",
            "Low",
            "Close",
        )
        assert all(
            parent.child(index).text(0) != "Volume"
            for index in range(parent.childCount())
        )
        parent.setCheckState(0, Qt.CheckState.Checked)
        assert all(
            parent.child(index).checkState(0) == Qt.CheckState.Checked
            for index in range(parent.childCount())
        )
        parent.child(0).setCheckState(0, Qt.CheckState.Unchecked)
        assert parent.checkState(0) == Qt.CheckState.PartiallyChecked

        fixed = tuple(
            dialog.fixed_signal_combo.itemData(index)
            for index in range(dialog.fixed_signal_combo.count())
        )
        assert fixed[:4] == current_ohlcv_signals(dialog._catalog)
        assert tuple(item.label for item in fixed[:4]) == (
            "Open",
            "High",
            "Low",
            "Close",
        )
        assert all(item.column != "volume" for item in fixed[:4])
        assert any(item.source_kind == "artifact" for item in fixed[4:])
    finally:
        _dispose_dialog(dialog)


def test_current_ohlcv_selection_survives_same_fingerprint_and_retargets_changed_fingerprint(
    qapp,
) -> None:
    original = _catalog()
    dialog = DataManagerConstructBatchDialog(original)
    try:
        close = _current_dataset_item(dialog).child(3)
        close.setCheckState(0, Qt.CheckState.Checked)
        dialog.fixed_signal_combo.setCurrentIndex(3)
        dialog.set_catalog(
            _catalog(), preserve_configuration=True
        )
        preserved = _current_dataset_item(dialog)
        assert preserved.child(3).checkState(0) == Qt.CheckState.Checked
        assert dialog.fixed_signal_combo.currentData().column == "close"

        dialog.set_plan(
            _plan(
                expand_construct_batch(dialog._build_expansion_request())
            )
        )
        dialog.set_catalog(
            _catalog(csv_sha="3" * 64), preserve_configuration=True
        )
        rebuilt = _current_dataset_item(dialog)
        assert all(
            rebuilt.child(index).checkState(0) == Qt.CheckState.Unchecked
            for index in range(rebuilt.childCount())
        )
        assert dialog.fixed_signal_combo.currentData().column == "open"
        assert dialog.fixed_signal_combo.currentData().source_ohlcv.csv_sha256 == "3" * 64
        assert dialog.reviewed_plan is None
    finally:
        _dispose_dialog(dialog)


def test_recap_renders_backend_owned_five_field_projection(qapp) -> None:
    dialog = DataManagerConstructBatchDialog(_catalog())
    try:
        close = _current_dataset_item(dialog).child(3)
        close.setCheckState(0, Qt.CheckState.Checked)
        request = expand_construct_batch(dialog._build_expansion_request())
        dialog.set_plan(_plan(request))

        assert dialog.preview_table.columnCount() == 5
        assert tuple(
            dialog.preview_table.horizontalHeaderItem(index).text()
            for index in range(dialog.preview_table.columnCount())
        ) == ("Source(s)", "Construct", "Parameters", "Inputs", "Result")
        assert dialog.preview_table.item(0, 0).text() == "Close"
        assert dialog.preview_table.item(0, 3).text() == "source=Close"
        assert dialog.preview_table.item(0, 4).text() == "New"
    finally:
        _dispose_dialog(dialog)
