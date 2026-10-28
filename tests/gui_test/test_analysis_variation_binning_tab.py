"""Standalone presentation, configuration and single-database isolation acceptance."""
from dataclasses import replace
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from leonardo.financial_tools.variation_models import BinningPolicy
from leonardo.gui.analysis.database_presentation import DatabaseDisplayEntry
from leonardo.gui.analysis.variation_binning_tab import DatabaseColumnDisplayEntry
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    window = AnalysisSuiteWindow()
    first = DatabaseDisplayEntry("a", "Same Name", "bybit", "linear", "BTCUSDT", "4h", 8000, 12, 1704067200000, 1706745600000)
    window.set_database_catalog((first, replace(first, database_id="b", asset="ETHUSDT")))
    window.set_database_columns("a", (DatabaseColumnDisplayEntry("a", "delta_pct", "percent", "EMA20 / EMA50 delta"),
                                      DatabaseColumnDisplayEntry("a", "slope", "price/bar", "EMA20 slope"),
                                      DatabaseColumnDisplayEntry("a", "label", numeric=False)), source_label="DEMONSTRATION COLUMNS")
    window.set_database_columns("b", (DatabaseColumnDisplayEntry("b", "delta_pct", "percent", "Close / EMA20 delta"),
                                      DatabaseColumnDisplayEntry("b", "angle", "degrees", "EMA angle")), source_label="DEMONSTRATION COLUMNS")
    window.open_database_selector()
    for row in range(window._selector.table.rowCount()):
        window._selector.table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    window._selector.add_button.click()
    yield window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def activate(window, identity="a"):
    tab = window.variation_tab
    tab.database_choice.setCurrentIndex(tab.database_choice.findData(identity))
    return tab


def select(tab, *names):
    for row in range(tab.columns.rowCount()):
        item = tab.columns.item(row, 0)
        if item.data(Qt.ItemDataRole.UserRole) in names:
            item.setCheckState(Qt.CheckState.Checked)


def effective(tab, name):
    return next(value for value in tab.configuration()["columns"] if value["source"] == name)


def test_tab_starts_without_automatically_choosing_a_database(window):
    tab = window.variation_tab
    assert window.analysis_tabs.tabText(0).replace("&&", "&") == "Variation & Binning"
    assert tab.active_database_id() is None
    assert tab.columns.rowCount() == 0
    assert tab.configuration() is None
    assert not tab.run_button.isEnabled()


def test_multiple_columns_are_independent_and_bound_to_one_database(window):
    tab = activate(window)
    assert tab.columns.rowCount() == 2
    select(tab, "delta_pct", "slope")
    configuration = tab.configuration()
    assert configuration["database_id"] == "a"
    assert configuration["reference"] == "full_history"
    assert {value["source"] for value in configuration["columns"]} == {"delta_pct", "slope"}
    assert all(not value["override"] for value in configuration["columns"])


def test_gui_defaults_match_existing_policy_authority(window):
    tab = activate(window)
    select(tab, "delta_pct")
    from leonardo.financial_tools import DirectionalBinningPolicy
    policy = DirectionalBinningPolicy()
    values = effective(tab, "delta_pct")
    assert values["measurement"] == "directional_intensity"
    assert values["positive_bins"] == policy.positive_bins == 10
    assert values["negative_bins"] == policy.negative_bins == 10
    assert "cutoffs" not in values
    assert values["min_reference_count"] == policy.min_reference_count


def test_defaults_propagate_only_to_inheriting_columns(window):
    tab = activate(window)
    tab.defaults.measurement.setCurrentIndex(tab.defaults.measurement.findData("value"))
    select(tab, "delta_pct", "slope")
    override = tab.column_override("slope")
    override.override.setChecked(True)
    override.editor.measurement.setCurrentIndex(override.editor.measurement.findData("magnitude"))
    override.editor.minimum_count.setValue(3000)
    override.editor.cutoffs[0].setValue(2)
    tab.defaults.minimum_count.setValue(5000)
    tab.defaults.cutoffs[0].setValue(3)
    assert effective(tab, "delta_pct")["min_reference_count"] == 5000
    assert effective(tab, "delta_pct")["cutoffs"][0] == 3
    assert effective(tab, "slope")["min_reference_count"] == 3000
    assert effective(tab, "slope")["cutoffs"][0] == 2
    assert effective(tab, "slope")["measurement"] == "magnitude"
    assert override.editor.isEnabled()


def test_disabling_override_restores_latest_shared_defaults(window):
    tab = activate(window)
    select(tab, "delta_pct")
    page = tab.column_override("delta_pct")
    page.override.setChecked(True)
    page.editor.minimum_count.setValue(3000)
    tab.defaults.minimum_count.setValue(7000)
    page.override.setChecked(False)
    assert effective(tab, "delta_pct")["min_reference_count"] == 7000
    assert not page.editor.isEnabled()
    page.override.setChecked(True)
    assert page.editor.minimum_count.value() == 7000


def test_database_switch_clears_selection_and_overrides_even_for_same_column_name(window):
    tab = activate(window)
    select(tab, "delta_pct")
    page = tab.column_override("delta_pct")
    page.override.setChecked(True)
    page.editor.minimum_count.setValue(9000)
    tab.defaults.minimum_count.setValue(4000)
    activate(window, "b")
    assert tab.selected_column_names() == ()
    assert tab.configuration() is None
    assert not tab.column_override("delta_pct").override.isChecked()
    select(tab, "delta_pct", "angle")
    assert tab.configuration()["database_id"] == "b"
    assert effective(tab, "delta_pct")["min_reference_count"] == 4000
    assert tab.columns.item(0, 3).text() == "Close / EMA20 delta"
    activate(window, "a")
    assert tab.selected_column_names() == ()
    assert not tab.column_override("delta_pct").override.isChecked()


def test_foreign_column_metadata_is_rejected_atomically(window):
    tab = activate(window)
    select(tab, "delta_pct")
    with pytest.raises(ValueError, match="all columns"):
        window.set_database_columns("a", (DatabaseColumnDisplayEntry("b", "alien"),))
    assert tab.selected_column_names() == ("delta_pct",)
    assert tab.columns.rowCount() == 2
    with pytest.raises(ValueError, match="display catalogue"):
        window.set_database_columns("unknown", ())


@pytest.mark.parametrize("entries", [(DatabaseColumnDisplayEntry("a", "same"), DatabaseColumnDisplayEntry("a", "same")),
                                     (DatabaseColumnDisplayEntry("a", ""),)])
def test_ambiguous_column_identity_is_rejected(window, entries):
    tab = activate(window)
    with pytest.raises(ValueError, match="non-empty and unique"):
        window.set_database_columns("a", entries)
    assert tab.columns.rowCount() == 2


@pytest.mark.parametrize("action", ["remove", "uncheck"])
def test_active_database_becoming_unavailable_clears_its_inputs(window, action):
    tab = activate(window)
    select(tab, "delta_pct")
    if action == "remove":
        window.remove_database("a")
    else:
        row = next(row for row in range(window.selected_table.rowCount()) if window.selected_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == "a")
        window.selected_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
    assert tab.active_database_id() is None
    assert tab.columns.rowCount() == 0
    assert tab.override_column.count() == 0
    assert tab.configuration() is None
    assert tab.database_choice.findData("b") > 0


def test_unrelated_removal_preserves_active_inputs(window):
    tab = activate(window)
    select(tab, "delta_pct")
    page = tab.column_override("delta_pct")
    page.override.setChecked(True)
    page.editor.minimum_count.setValue(4500)
    window.remove_database("b")
    assert tab.active_database_id() == "a"
    assert tab.selected_column_names() == ("delta_pct",)
    assert effective(tab, "delta_pct")["min_reference_count"] == 4500


def test_invalid_boundaries_have_visible_feedback_and_no_ready_configuration(window):
    tab = activate(window)
    tab.defaults.measurement.setCurrentIndex(tab.defaults.measurement.findData("value"))
    select(tab, "delta_pct", "slope")
    tab.defaults.cutoffs[1].setValue(1)
    assert tab.configuration() is None
    assert "strictly increasing" in tab.configuration_status.text()
    tab.defaults.cutoffs[1].setValue(5)
    assert tab.configuration() is not None
    page = tab.column_override("slope")
    page.override.setChecked(True)
    page.editor.cutoffs[2].setValue(99)
    assert tab.configuration() is None
    assert not tab.run_button.isEnabled()


def test_all_overrides_can_be_valid_with_unused_invalid_defaults(window):
    tab = activate(window)
    tab.defaults.measurement.setCurrentIndex(tab.defaults.measurement.findData("value"))
    select(tab, "delta_pct")
    tab.column_override("delta_pct").override.setChecked(True)
    tab.defaults.cutoffs[0].setValue(5)
    assert tab.configuration() is not None


def test_deselection_preserves_same_database_override_for_reselection(window):
    tab = activate(window)
    select(tab, "delta_pct")
    page = tab.column_override("delta_pct")
    page.override.setChecked(True)
    page.editor.minimum_count.setValue(3500)
    tab.columns.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert tab.configuration() is None
    assert tab.override_column.count() == 0
    select(tab, "delta_pct")
    assert effective(tab, "delta_pct")["min_reference_count"] == 3500


def test_replacing_active_column_metadata_clears_prior_inputs(window):
    tab = activate(window)
    select(tab, "delta_pct")
    window.set_database_columns("a", (DatabaseColumnDisplayEntry("a", "new_column"),))
    assert tab.selected_column_names() == ()
    assert tab.columns.rowCount() == 1
    assert tab.columns.item(0, 1).text() == "new_column"


def test_missing_and_empty_column_catalogues_are_distinct(app):
    window = AnalysisSuiteWindow()
    entry = DatabaseDisplayEntry("a", "A", "bybit", "linear", "BTCUSDT", "4h")
    window.set_database_catalog((entry,))
    window.open_database_selector()
    window._selector.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    window._selector.add_button.click()
    try:
        tab = activate(window)
        assert "not connected" in tab.column_source.text()
        window.set_database_columns("a", ())
        assert "No numeric" in tab.column_source.text()
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_keyboard_selection_and_override_navigation(window, app):
    window.show()
    tab = activate(window)
    app.processEvents()
    tab.columns.setCurrentCell(0, 0)
    tab.columns.setFocus()
    QTest.keyClick(tab.columns, Qt.Key.Key_Space)
    assert tab.selected_column_names() == ("delta_pct",)
    tab.settings_tabs.setCurrentIndex(1)
    assert tab.override_column.currentData() == "delta_pct"
    assert tab.override_stack.currentWidget() is tab.column_override("delta_pct")


def test_standalone_controls_without_presenter_never_execute_analysis(window, monkeypatch):
    import leonardo.financial_tools.variation as engine
    import leonardo.financial_tools.directional_variation as directional
    def forbidden(*args, **kwargs):
        raise AssertionError("Standalone presentation must not run analysis without a presenter")
    for name in ("analyze_variation", "fit_dynamic_binning", "classify_dynamic_binning"):
        monkeypatch.setattr(engine, name, forbidden)
    for name in ("analyze_directional_variation", "fit_directional_binning", "classify_directional_binning"):
        monkeypatch.setattr(directional, name, forbidden)
    tab = activate(window)
    select(tab, "delta_pct")
    for mode in ("directional_intensity", "value", "magnitude"):
        tab.defaults.measurement.setCurrentIndex(tab.defaults.measurement.findData(mode))
        tab.run_button.click()
    assert tab.configuration() is not None
    assert not tab.run_button.isEnabled()


@pytest.mark.parametrize("settings_tab", [0, 1])
@pytest.mark.parametrize("mode", ["directional_intensity", "value", "magnitude"])
def test_normal_window_keeps_configuration_controls_within_viewport(window, app, settings_tab, mode):
    window.resize(1280, 820)
    window.show()
    tab = activate(window)
    tab.defaults.measurement.setCurrentIndex(tab.defaults.measurement.findData(mode))
    select(tab, "delta_pct", "slope")
    tab.settings_tabs.setCurrentIndex(settings_tab)
    app.processEvents()
    scroll = tab.findChild(QScrollArea, "analysis_suite.binning.controls_scroll")
    assert scroll.horizontalScrollBar().maximum() == 0
    assert tab.database_choice.width() <= scroll.viewport().width()


def test_column_controls_have_distinct_live_identities_after_switching(window, app):
    tab = activate(window)
    first = tab.column_override("delta_pct").objectName()
    second = tab.column_override("slope").objectName()
    assert first != second
    activate(window, "b")
    assert tab.column_override("delta_pct").objectName() != first
    names = [widget.objectName() for widget in tab.findChildren(QWidget)
             if widget.objectName().startswith("analysis_suite.binning.column.")]
    assert len(names) == len(set(names))


def test_directional_counts_inherit_override_and_restore_independently(window):
    tab = activate(window)
    select(tab, "delta_pct", "slope")
    page = tab.column_override("slope")
    page.override.setChecked(True)
    page.editor.positive_bins.setValue(6)
    page.editor.negative_bins.setValue(12)
    tab.defaults.positive_bins.setValue(20)
    tab.defaults.negative_bins.setValue(8)
    assert (effective(tab, "delta_pct")["positive_bins"], effective(tab, "delta_pct")["negative_bins"]) == (20, 8)
    assert (effective(tab, "slope")["positive_bins"], effective(tab, "slope")["negative_bins"]) == (6, 12)
    page.override.setChecked(False)
    assert (effective(tab, "slope")["positive_bins"], effective(tab, "slope")["negative_bins"]) == (20, 8)
    assert not page.editor.isEnabled()


def test_mode_switches_only_emit_applicable_settings_and_retain_legacy_defaults(window):
    tab = activate(window)
    select(tab, "delta_pct")
    editor = tab.defaults
    assert editor.legacy_controls.isHidden() and not editor.directional_controls.isHidden()
    editor.positive_bins.setValue(13)
    for mode in ("value", "magnitude"):
        editor.measurement.setCurrentIndex(editor.measurement.findData(mode))
        values = effective(tab, "delta_pct")
        assert "positive_bins" not in values and "negative_bins" not in values
        assert values["cutoffs"] == BinningPolicy().cutoffs
        assert not editor.legacy_controls.isHidden() and editor.directional_controls.isHidden()
    editor.cutoffs[0].setValue(5)
    assert tab.configuration() is None
    editor.measurement.setCurrentIndex(editor.measurement.findData("directional_intensity"))
    assert effective(tab, "delta_pct")["positive_bins"] == 13
    assert "cutoffs" not in effective(tab, "delta_pct")
    assert "per populated direction" in editor.count_label.text()


def test_directional_limits_and_identity_are_visible_without_claiming_sign_coverage(window):
    tab = activate(window)
    select(tab, "delta_pct")
    for control in (tab.defaults.positive_bins, tab.defaults.negative_bins):
        assert (control.minimum(), control.maximum()) == (1, 1000)
    assert tab.defaults.positive_bins.objectName() != tab.defaults.negative_bins.objectName()
    assert not tab.run_button.isEnabled()
    assert "reference_kind" not in effective(tab, "delta_pct")
