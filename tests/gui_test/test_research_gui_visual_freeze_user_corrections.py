from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
)

from leonardo.gui.research.chart_panel import ResearchChartPanel
from leonardo.gui.research.financial_tools_dialog import (
    ResearchFinancialToolsDialog,
)
from leonardo.gui.research.suite_window import ResearchSuiteWindow
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
)
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.gui.windows.study_environment_manager_dialog import (
    StudyEnvironmentManagerDialog,
    StudyEnvironmentTarget,
)
from leonardo.gui.windows.study_environment_save_dialog import (
    StudyEnvironmentSaveDialog,
)
from leonardo.gui.windows.workspace_snapshot_manager_dialog import (
    WorkspaceSnapshotLoadIntent,
    WorkspaceSnapshotManagerDialog,
)
from leonardo.gui.windows.workspace_snapshot_preflight_dialog import (
    WorkspaceSnapshotPreflightDialog,
)
from leonardo.gui.windows.workspace_snapshot_save_dialog import (
    WorkspaceSnapshotSaveDialog,
)
from leonardo.research import ResearchWorkspaceSnapshotCompatibilityReport
from leonardo.research.workspace_snapshot import (
    WorkspaceSnapshotChartCompatibility,
)
from tools import dev_launch_research_gui_restoration as dev_launcher
from tools.research_gui_dev_fixtures import (
    RESEARCH_GUI_DATASET_FIXTURES,
    build_chart_fixture_for_market,
    build_notebook_gui_fixtures,
    build_primary_chart_fixture,
    build_study_setup_catalog_fixture,
    build_study_environment_gui_fixtures,
    build_workspace_snapshot_gui_fixtures,
)


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def gui_bundles():
    primary = build_primary_chart_fixture()
    secondary = build_chart_fixture_for_market(
        RESEARCH_GUI_DATASET_FIXTURES[1].market_id,
        slot_id=2,
    )
    environments = build_study_environment_gui_fixtures(primary)
    workspaces = build_workspace_snapshot_gui_fixtures(
        primary,
        secondary,
        environments,
    )
    notebooks = build_notebook_gui_fixtures(
        primary.market_id,
        secondary.market_id,
    )
    return primary, environments, workspaces, notebooks


def _assert_vertical_header_physically_aligned(
    table: QTableWidget,
) -> None:
    vertical_header = table.verticalHeader()

    assert vertical_header.isVisible()
    assert table.rowCount() > 0

    assert vertical_header.frameShape() == QFrame.Shape.NoFrame
    assert vertical_header.frameWidth() == 0

    header_viewport_origin_y = vertical_header.viewport().mapToGlobal(
        QPoint(0, 0)
    ).y()
    table_viewport_origin_y = table.viewport().mapToGlobal(
        QPoint(0, 0)
    ).y()

    assert header_viewport_origin_y == table_viewport_origin_y

    for row in range(table.rowCount()):
        header_top = vertical_header.viewport().mapToGlobal(
            QPoint(
                0,
                vertical_header.sectionViewportPosition(row),
            )
        ).y()

        row_top = table.viewport().mapToGlobal(
            QPoint(
                0,
                table.rowViewportPosition(row),
            )
        ).y()

        assert header_top == row_top

        header_bottom = header_top + vertical_header.sectionSize(row)
        row_bottom = row_top + table.rowHeight(row)

        assert header_bottom == row_bottom


def test_chart_bottom_bar_uses_native_text_first_geometry(qapp, gui_bundles) -> None:
    fixture = gui_bundles[0]
    panel = ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )
    panel.resize(1400, 900)
    panel.show()
    qapp.processEvents()
    try:
        commands = (
            panel.go_to_button,
            panel.financial_tools_button,
            panel.studies_button,
            panel.detach_button,
            panel.close_button,
            panel.autoscale_button,
        )
        for button in commands:
            assert button.width() >= button.sizeHint().width()
            assert button.height() >= button.sizeHint().height()
        assert panel.position_label.width() >= panel.position_label.sizeHint().width()
        assert panel.position_combo.width() >= panel.position_combo.sizeHint().width()
        controls = (
            panel.dataset_label,
            panel.position_label,
            panel.position_combo,
            *commands,
        )
        margins = panel.control_bar.layout().contentsMargins()
        required = max(item.sizeHint().height() for item in controls)
        required += margins.top() + margins.bottom()
        assert panel.control_bar.height() >= required
        assert panel.dataset_label.toolTip() == panel.dataset_label.text()
    finally:
        panel.close()


def test_overlay_child_surfaces_have_local_transparency_authority(
    qapp, gui_bundles
) -> None:
    fixture = gui_bundles[0]
    panel = ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )
    panel.show()
    qapp.processEvents()
    try:
        overlays = (panel.price_overlay, *panel.oscillator_overlays)
        for overlay in overlays:
            assert "rgba(0, 0, 0, 128)" in overlay.styleSheet()
            assert "rgba(11, 16, 22, 190)" not in overlay.styleSheet()
            surface = overlay.content_widget
            assert surface.property("research_overlay_surface") is True
            assert not surface.autoFillBackground()
            assert surface.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            assert not surface.testAttribute(
                Qt.WidgetAttribute.WA_OpaquePaintEvent
            )
        for row in panel.price_overlay.study_rows:
            assert row.property("research_overlay_surface") is True
            assert not row.autoFillBackground()
            assert row.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            assert not row.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    finally:
        panel.close()


def test_table_sizing_is_content_derived_and_validates_multipliers(qapp) -> None:
    table = QTableWidget(3, 2)
    table.setHorizontalHeaderLabels(("Short", "Description"))
    table.setItem(0, 0, QTableWidgetItem("A"))
    table.setItem(0, 1, QTableWidgetItem("Longer content"))
    table.setCellWidget(1, 0, QComboBox(table))
    table.setItem(1, 1, QTableWidgetItem("Combo row"))
    table.setCellWidget(2, 0, QPushButton("Action", table))
    table.setItem(2, 1, QTableWidgetItem("Button row"))
    table.show()
    qapp.processEvents()
    table.resizeColumnsToContents()
    baseline = table.columnWidth(1)
    horizontal_style = table.horizontalHeader().styleSheet()
    resize_table_columns_to_contents(table, {1: 3.0})
    qapp.processEvents()
    _assert_vertical_header_physically_aligned(table)
    assert table.columnWidth(1) >= round(baseline * 3.0) - 1
    vertical_header = table.verticalHeader()
    alignment = vertical_header.defaultAlignment()
    assert alignment & Qt.AlignmentFlag.AlignHCenter
    assert alignment & Qt.AlignmentFlag.AlignVCenter
    assert "padding: 0px" in vertical_header.styleSheet()
    assert "margin: 0px" in vertical_header.styleSheet()
    assert table.horizontalHeader().styleSheet() == horizontal_style
    for row in range(table.rowCount()):
        header_item = table.verticalHeaderItem(row)
        assert header_item is not None
        assert header_item.text() == str(row + 1)
        item_alignment = Qt.AlignmentFlag(header_item.textAlignment())
        assert item_alignment & Qt.AlignmentFlag.AlignHCenter
        assert item_alignment & Qt.AlignmentFlag.AlignVCenter
        assert vertical_header.sectionSize(row) == table.rowHeight(row)

    table.insertRow(3)
    table.setItem(3, 0, QTableWidgetItem("Added"))
    table.setItem(3, 1, QTableWidgetItem("Added after initial sizing"))
    larger_font = table.font()
    larger_font.setPointSize(larger_font.pointSize() + 4)
    table.setFont(larger_font)
    resize_table_columns_to_contents(table, {1: 3.0})
    qapp.processEvents()
    _assert_vertical_header_physically_aligned(table)
    added_header = table.verticalHeaderItem(3)
    assert added_header is not None
    assert added_header.text() == "4"
    added_alignment = Qt.AlignmentFlag(added_header.textAlignment())
    assert added_alignment & Qt.AlignmentFlag.AlignHCenter
    assert added_alignment & Qt.AlignmentFlag.AlignVCenter
    assert vertical_header.sectionSize(3) == table.rowHeight(3)

    with pytest.raises(ValueError):
        resize_table_columns_to_contents(table, {1: float("nan")})
    with pytest.raises(ValueError):
        resize_table_columns_to_contents(table, {2: 1.0})
    table.close()


def test_table_sizing_preserves_custom_headers_and_hidden_state(qapp) -> None:
    custom = QTableWidget(2, 1)
    custom.setItem(0, 0, QTableWidgetItem("Default row"))
    custom.setItem(1, 0, QTableWidgetItem("Custom row"))
    custom.setVerticalHeaderItem(1, QTableWidgetItem("Custom label"))
    custom.show()
    resize_table_columns_to_contents(custom)
    qapp.processEvents()
    _assert_vertical_header_physically_aligned(custom)
    assert custom.verticalHeaderItem(0).text() == "1"
    assert custom.verticalHeaderItem(1).text() == "Custom label"
    custom_alignment = Qt.AlignmentFlag(
        custom.verticalHeaderItem(1).textAlignment()
    )
    assert custom_alignment & Qt.AlignmentFlag.AlignHCenter
    assert custom_alignment & Qt.AlignmentFlag.AlignVCenter

    hidden = QTableWidget(1, 1)
    hidden.setItem(0, 0, QTableWidgetItem("Hidden header"))
    hidden.verticalHeader().hide()
    resize_table_columns_to_contents(hidden)
    assert hidden.verticalHeader().isHidden()
    custom.close()
    hidden.close()


def test_vertical_header_alignment_uses_physical_viewport_coordinates(
    qapp,
) -> None:
    table = QTableWidget(2, 1)
    table.setItem(0, 0, QTableWidgetItem("First row"))
    table.setItem(1, 0, QTableWidgetItem("Second row"))
    table.show()
    resize_table_columns_to_contents(table)
    qapp.processEvents()
    try:
        _assert_vertical_header_physically_aligned(table)
        header_origin_y = table.verticalHeader().viewport().mapToGlobal(
            QPoint(0, 0)
        ).y()
        table_origin_y = table.viewport().mapToGlobal(
            QPoint(0, 0)
        ).y()
        assert header_origin_y == table_origin_y
    finally:
        table.close()


def _assert_screen_fraction(
    dialog,
    width_fraction: float,
    height_fraction: float,
) -> None:
    screen = dialog.screen() or QApplication.primaryScreen()
    available = screen.availableGeometry()
    assert abs(dialog.width() - round(available.width() * width_fraction)) <= 2
    assert abs(dialog.height() - round(available.height() * height_fraction)) <= 2


def test_secondary_windows_use_available_screen_fractions(qapp, gui_bundles) -> None:
    primary, environments, workspaces, notebooks = gui_bundles
    target = (StudyEnvironmentTarget(1, "session_one", "Chart 1"),)
    report = ResearchWorkspaceSnapshotCompatibilityReport(
        "dev_snapshot_primary", "append", True, ()
    )
    financial_tools = ResearchFinancialToolsDialog(
        primary.market_id,
        build_study_setup_catalog_fixture(primary),
    )
    half_width_dialogs = (
        StudyEnvironmentSaveDialog(
            1,
            "session_one",
            environments.chart_studies,
            environments.summaries,
        ),
        StudyEnvironmentManagerDialog(environments.summaries, target, mode="load"),
        StudyEnvironmentManagerDialog(environments.summaries, target),
        ResearchNotebookWindow(),
    )
    third_width_dialogs = (
        WorkspaceSnapshotSaveDialog(workspaces.capture, workspaces.summaries),
        WorkspaceSnapshotManagerDialog(workspaces.summaries, mode="load"),
        WorkspaceSnapshotManagerDialog(workspaces.summaries),
        WorkspaceSnapshotPreflightDialog(report),
        ResearchNotebookManagerDialog(
            notebooks.summaries,
            assignments=notebooks.assignments,
        ),
    )
    try:
        _assert_screen_fraction(financial_tools, 1 / 2, 2 / 3)
        for dialog in half_width_dialogs:
            _assert_screen_fraction(dialog, 1 / 2, 1 / 2)
        for dialog in third_width_dialogs:
            _assert_screen_fraction(dialog, 1 / 3, 1 / 2)
    finally:
        for dialog in (financial_tools, *half_width_dialogs, *third_width_dialogs):
            dialog.close()


def test_research_table_consumers_use_centered_row_headers(
    qapp, gui_bundles
) -> None:
    primary, environments, workspaces, notebooks = gui_bundles
    target = (StudyEnvironmentTarget(1, "session_one", "Chart 1"),)
    report = ResearchWorkspaceSnapshotCompatibilityReport(
        "dev_snapshot_primary",
        "append",
        False,
        (
            WorkspaceSnapshotChartCompatibility(
                "chart_one",
                1,
                False,
                ("Dataset unavailable.",),
            ),
        ),
    )
    environment_save = StudyEnvironmentSaveDialog(
        1,
        "session_one",
        environments.chart_studies,
        environments.summaries,
    )
    environment_manager = StudyEnvironmentManagerDialog(
        environments.summaries,
        target,
    )
    workspace_save = WorkspaceSnapshotSaveDialog(
        workspaces.capture,
        workspaces.summaries,
    )
    workspace_manager = WorkspaceSnapshotManagerDialog(workspaces.summaries)
    workspace_preflight = WorkspaceSnapshotPreflightDialog(report)
    notebook_manager = ResearchNotebookManagerDialog(
        notebooks.summaries,
        assignments=notebooks.assignments,
    )
    notebook_editor = ResearchNotebookWindow()
    financial_tools = ResearchFinancialToolsDialog(
        primary.market_id,
        build_study_setup_catalog_fixture(primary),
    )
    dialogs = (
        environment_save,
        environment_manager,
        workspace_save,
        workspace_manager,
        workspace_preflight,
        notebook_manager,
        notebook_editor,
        financial_tools,
    )
    try:
        environment_manager.set_environment(environments.environments[0])
        workspace_manager.set_snapshot(workspaces.snapshots[0])
        notebook_editor.set_notebook(notebooks.notebooks[0])
        for dialog in dialogs:
            dialog.show()
        qapp.processEvents()

        for dialog in dialogs:
            for table in dialog.findChildren(QTableWidget):
                if table.rowCount() == 0 or not table.verticalHeader().isVisible():
                    continue
                for row in range(table.rowCount()):
                    header_item = table.verticalHeaderItem(row)
                    assert header_item is not None
                    alignment = Qt.AlignmentFlag(header_item.textAlignment())
                    assert alignment & Qt.AlignmentFlag.AlignHCenter
                    assert alignment & Qt.AlignmentFlag.AlignVCenter
                    assert (
                        table.verticalHeader().sectionSize(row)
                        == table.rowHeight(row)
                    )
                _assert_vertical_header_physically_aligned(table)
        assert financial_tools.saved_artifact_table.verticalHeader().isHidden()
    finally:
        for dialog in dialogs:
            dialog.close()


def test_study_environment_modes_and_relative_columns(qapp, gui_bundles) -> None:
    _primary, environments, _workspaces, _notebooks = gui_bundles
    target = (StudyEnvironmentTarget(1, "session_one", "Chart 1"),)
    load = StudyEnvironmentManagerDialog(
        environments.summaries, target, mode="load"
    )
    manage = StudyEnvironmentManagerDialog(environments.summaries, target)
    save = StudyEnvironmentSaveDialog(
        1,
        "session_one",
        environments.chart_studies,
        environments.summaries,
    )
    try:
        environment = environments.environments[0]
        load.set_environment(environment)
        manage.set_environment(environment)
        assert load.windowTitle() == "Load Study Environment"
        assert load._save.isHidden()
        assert load._name.isReadOnly() and load._description.isReadOnly()
        assert not bool(
            load._table.item(0, 3).flags() & Qt.ItemFlag.ItemIsUserCheckable
        )
        assert not load._table.cellWidget(0, 4).isEnabled()
        assert not bool(
            load._table.item(0, 5).flags() & Qt.ItemFlag.ItemIsEditable
        )
        assert manage.windowTitle() == "Manage Study Environments"
        assert manage.layout().stretch(0) == 13
        assert manage.layout().stretch(1) == 27
        assert load.layout().stretch(0) == 13
        assert load.layout().stretch(1) == 27
        assert not manage._save.isHidden()
        assert manage._save.text() == "Save Changes"
        assert not manage._name.isReadOnly()
        assert manage._table.cellWidget(0, 4).isEnabled()
        emitted = []
        load.metadata_save_requested.connect(emitted.append)
        load._save.click()
        assert emitted == []

        save._table.resizeColumnsToContents()
        save_baseline = tuple(save._table.columnWidth(index) for index in (3, 5, 6))
        save._resize_study_columns()
        assert save._table.columnWidth(3) >= round(save_baseline[0] * 1.20) - 1
        assert save._table.columnWidth(5) >= round(save_baseline[1] * 1.20) - 1
        assert save._table.columnWidth(6) >= round(save_baseline[2] * 3.00) - 1

        manage._table.resizeColumnsToContents()
        manager_baseline = tuple(manage._table.columnWidth(index) for index in (4, 5))
        manage._resize_study_columns()
        assert manage._table.columnWidth(4) >= round(manager_baseline[0] * 1.20) - 1
        assert manage._table.columnWidth(5) >= round(manager_baseline[1] * 3.00) - 1
        with pytest.raises(ValueError):
            StudyEnvironmentManagerDialog((), (), mode="invalid")
    finally:
        save.close()
        load.close()
        manage.close()


def test_market_id_tables_use_four_canonical_display_columns(
    qapp, gui_bundles
) -> None:
    primary, _environments, workspaces, notebooks = gui_bundles
    save = WorkspaceSnapshotSaveDialog(workspaces.capture, workspaces.summaries)
    manage = WorkspaceSnapshotManagerDialog(workspaces.summaries)
    notebook_manager = ResearchNotebookManagerDialog(notebooks.summaries)
    try:
        manage.set_snapshot(workspaces.snapshots[0])
        expected_headers = ("Exchange", "Market Type", "Asset", "Timeframe")
        assert tuple(
            save.chart_table.horizontalHeaderItem(column).text()
            for column in range(1, 5)
        ) == expected_headers
        assert tuple(
            manage.chart_table.horizontalHeaderItem(column).text()
            for column in range(1, 5)
        ) == expected_headers
        assert tuple(
            notebook_manager._pages.horizontalHeaderItem(column).text()
            for column in range(4)
        ) == expected_headers

        expected_values = (
            primary.market_id.exchange,
            primary.market_id.market_type,
            primary.market_id.symbol,
            primary.market_id.timeframe,
        )
        assert expected_values == ("bybit", "linear", "BTCUSDT", "4h")
        assert tuple(
            save.chart_table.item(0, column).text() for column in range(1, 5)
        ) == expected_values
        assert tuple(
            manage.chart_table.item(0, column).text() for column in range(1, 5)
        ) == expected_values
        assert tuple(
            notebook_manager._pages.item(0, column).text() for column in range(4)
        ) == expected_values
    finally:
        save.close()
        manage.close()
        notebook_manager.close()


def test_workspace_visible_terminology_modes_and_multiline_description(
    qapp, gui_bundles, monkeypatch
) -> None:
    _primary, _environments, workspaces, _notebooks = gui_bundles
    suite = ResearchSuiteWindow(())
    save = WorkspaceSnapshotSaveDialog(workspaces.capture, workspaces.summaries)
    load = WorkspaceSnapshotManagerDialog(workspaces.summaries, mode="load")
    manage = WorkspaceSnapshotManagerDialog(workspaces.summaries)
    try:
        assert tuple(action.text() for action in suite.file_menu.actions())[6:9] == (
            "Save Workspace...",
            "Load Workspace...",
            "Manage Workspaces...",
        )
        assert suite.quick_button_for_action("Save Workspace...").text() == "Save Workspace"
        assert suite.quick_button_for_action("Load Workspace...").text() == "Load Workspace"
        assert save.windowTitle() == "Save Workspace"
        assert save.name_edit.placeholderText() == "Workspace name"
        assert isinstance(save.description_edit, QPlainTextEdit)
        assert save.description_edit.minimumHeight() >= (
            3 * save.description_edit.fontMetrics().lineSpacing()
            + 2 * save.description_edit.frameWidth()
        )
        save.name_edit.setText("New Workspace")
        save.description_edit.setPlainText("one\ntwo\nthree")
        emitted = []
        save.save_requested.connect(emitted.append)
        save.save_button.click()
        assert emitted[0].description == "one\ntwo\nthree"

        snapshot = workspaces.snapshots[0]
        load.snapshot_list.setCurrentRow(0)
        manage.snapshot_list.setCurrentRow(0)
        load.set_snapshot(snapshot)
        manage.set_snapshot(snapshot)
        assert load.windowTitle() == "Load Workspace"
        assert load.metadata_button.isHidden()
        assert load.name_edit.isReadOnly() and load.description_edit.isReadOnly()
        assert manage.windowTitle() == "Manage Workspaces"
        assert manage.metadata_button.text() == "Save Changes"
        assert not manage.metadata_button.isHidden()
        assert not manage.name_edit.isReadOnly()
        assert not manage.description_edit.isReadOnly()
        emitted = []
        load.metadata_requested.connect(emitted.append)
        load.metadata_button.click()
        assert emitted == []

        prompts = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args: prompts.append(args) or QMessageBox.No,
        )
        manage.delete_button.click()
        assert prompts[0][1] == "Delete Workspace"
        assert prompts[0][2].startswith("Delete Workspace ")
        with pytest.raises(ValueError):
            WorkspaceSnapshotManagerDialog((), mode="invalid")
    finally:
        suite.close()
        save.close()
        load.close()
        manage.close()


def test_notebook_keeps_market_pages_with_exact_inner_category_tabs(
    qapp, gui_bundles
) -> None:
    notebook = gui_bundles[3].notebooks[0]
    editor = ResearchNotebookWindow()
    try:
        editor.set_notebook(notebook)
        pages = editor.findChild(QTabWidget, "research.notebook_window.tabs.pages")
        assert pages.count() >= 1
        market_page = pages.widget(0)
        categories = market_page.findChild(
            QTabWidget, "research.notebook_window.tabs.categories"
        )
        assert tuple(categories.tabText(index) for index in range(3)) == (
            "Notes",
            "Potential Trades",
            "Points of Interest",
        )
        expected = (
            ("research.notebook_window.table.notes", "research.notebook_window.button.add_note"),
            ("research.notebook_window.table.trades", "research.notebook_window.button.add_trade"),
            ("research.notebook_window.table.poi", "research.notebook_window.button.add_poi"),
        )
        for index, (table_name, button_name) in enumerate(expected):
            category = categories.widget(index)
            assert category.findChild(QTableWidget, table_name) is not None
            assert category.findChild(QPushButton, button_name) is not None
    finally:
        editor.close()


def test_dev_composition_reuses_and_tracks_logical_windows(
    qapp, monkeypatch
) -> None:
    monkeypatch.setenv("LEONARDO_RESEARCH_GUI_POPULATE_8", "1")
    monkeypatch.setattr(QApplication, "exec", lambda _self: 0)
    assert dev_launcher.main() == 0
    qapp.processEvents()
    window = next(
        item
        for item in qapp.topLevelWidgets()
        if item.objectName() == "research_restoration.window"
        and item.isVisible()
        and hasattr(item, "_dev_tracked_windows")
    )
    tracked = window._dev_tracked_windows
    registry = window._dev_window_registry
    try:
        emitters = (
            (window.save_study_environment_requested, "research_restoration.study_environment.save"),
            (window.load_study_environment_requested, "research_restoration.study_environment.load"),
            (window.manage_study_environments_requested, "research_restoration.study_environment.manage"),
            (window.save_workspace_snapshot_requested, "research_restoration.workspace.save"),
            (window.load_workspace_snapshot_requested, "research_restoration.workspace.load"),
            (window.manage_workspace_snapshots_requested, "research_restoration.workspace.manage"),
            (window.notebook_manager_requested, "research_restoration.notebook.manager"),
            (window.load_notebook_requested, "research_restoration.notebook.load"),
            (window.create_notebook_requested, "research_restoration.notebook.editor"),
        )
        for signal, window_id in emitters:
            signal.emit()
            qapp.processEvents()
            first = tracked[window_id]
            signal.emit()
            qapp.processEvents()
            assert tracked[window_id] is first

        first_panel = window.workspace.chart_panel_for_slot(1)
        second_panel = window.workspace.chart_panel_for_slot(2)
        for panel, slot_id in ((first_panel, 1), (second_panel, 2)):
            panel.financial_tools_button.click()
            panel.studies_button.click()
            qapp.processEvents()
            financial_id = f"research_restoration.chart.{slot_id}.financial_tools"
            studies_id = f"research_restoration.chart.{slot_id}.studies"
            first_financial = tracked[financial_id]
            first_studies = tracked[studies_id]
            panel.financial_tools_button.click()
            panel.studies_button.click()
            assert tracked[financial_id] is first_financial
            assert tracked[studies_id] is first_studies
        assert tracked["research_restoration.chart.1.financial_tools"] is not tracked[
            "research_restoration.chart.2.financial_tools"
        ]

        load_manager = tracked["research_restoration.workspace.load"]
        load_manager.load_requested.emit(
            WorkspaceSnapshotLoadIntent("dev_snapshot_primary", "append")
        )
        qapp.processEvents()
        assert "research_restoration.workspace.preflight" in tracked

        records = {item.window_id: item for item in registry.list_windows()}
        for window_id in (
            "research_restoration.main",
            "research_restoration.study_environment.save",
            "research_restoration.chart.1.financial_tools",
            "research_restoration.chart.1.studies",
            "research_restoration.notebook.editor",
            "research_restoration.workspace.preflight",
        ):
            assert records[window_id].status == "open"
            assert records[window_id].focused_at_utc is not None

        reusable = tracked["research_restoration.study_environment.save"]
        reusable.reject()
        qapp.processEvents()
        records = {item.window_id: item for item in registry.list_windows()}
        assert records["research_restoration.study_environment.save"].status == "closed"
        window.workspace.set_active_slot(reusable._slot_id)
        window.save_study_environment_requested.emit()
        qapp.processEvents()
        assert tracked["research_restoration.study_environment.save"] is reusable
        records = {item.window_id: item for item in registry.list_windows()}
        assert records["research_restoration.study_environment.save"].status == "open"

        assert first_panel.go_to_button.isVisible()
        assert not first_panel.go_to_button.isEnabled()
        assert first_panel.go_to_button.toolTip() == dev_launcher._LIFECYCLE_PENDING_TEXT
        pan_anchor = window.action_for_text("Pan Anchor")
        assert pan_anchor.isVisible()
        assert not pan_anchor.isEnabled()
        assert pan_anchor.toolTip() == dev_launcher._LIFECYCLE_PENDING_TEXT
        assert pan_anchor.statusTip() == dev_launcher._LIFECYCLE_PENDING_TEXT
    finally:
        for widget in tuple(tracked.values()):
            widget.close()
        window.close()
        qapp.processEvents()


def test_chart_local_windows_close_with_slot_and_survive_detach_dock(
    qapp, monkeypatch
) -> None:
    monkeypatch.setenv("LEONARDO_RESEARCH_GUI_POPULATE_8", "1")
    monkeypatch.setattr(QApplication, "exec", lambda _self: 0)
    assert dev_launcher.main() == 0
    qapp.processEvents()
    window = next(
        widget
        for widget in qapp.topLevelWidgets()
        if widget.objectName() == "research_restoration.window"
        and widget.isVisible()
        and hasattr(widget, "_dev_tracked_windows")
    )
    tracked = window._dev_tracked_windows
    registry = window._dev_window_registry
    financial_dialogs = window._dev_financial_tools_dialogs
    studies_dialogs = window._dev_studies_manager_dialogs
    chart_fixtures = window._dev_chart_fixtures
    financial_id = "research_restoration.chart.1.financial_tools"
    studies_id = "research_restoration.chart.1.studies"
    try:
        first_panel = window.workspace.chart_panel_for_slot(1)
        assert window.workspace.chart_panel_for_slot(2) is not None
        first_panel.financial_tools_button.click()
        first_panel.studies_button.click()
        qapp.processEvents()
        first_financial = tracked[financial_id]
        first_studies = tracked[studies_id]

        first_panel.detach_button.click()
        qapp.processEvents()
        assert window.workspace.chart_panel_for_slot(1) is first_panel
        assert window.workspace.detached_slot_ids() == (1,)
        assert financial_dialogs[first_panel] is first_financial
        assert studies_dialogs[first_panel] is first_studies
        assert tracked[financial_id] is first_financial
        assert tracked[studies_id] is first_studies
        records = {item.window_id: item for item in registry.list_windows()}
        assert records[financial_id].status == "open"
        assert records[studies_id].status == "open"

        first_panel.detach_button.click()
        qapp.processEvents()
        assert window.workspace.chart_panel_for_slot(1) is first_panel
        assert window.workspace.detached_slot_ids() == ()
        assert financial_dialogs[first_panel] is first_financial
        assert studies_dialogs[first_panel] is first_studies
        assert tracked[financial_id] is first_financial
        assert tracked[studies_id] is first_studies

        first_panel.close_button.click()
        qapp.processEvents()
        assert 1 not in window.workspace.slot_ids()
        assert financial_id not in tracked
        assert studies_id not in tracked
        assert first_panel not in financial_dialogs
        assert first_panel not in studies_dialogs
        assert first_panel not in chart_fixtures
        records = {item.window_id: item for item in registry.list_windows()}
        assert records[financial_id].status == "closed"
        assert records[studies_id].status == "closed"

        def accept_dataset(dialog) -> QDialog.DialogCode:
            selected = RESEARCH_GUI_DATASET_FIXTURES[0]
            for combo, value in (
                (dialog.exchange_combo, selected.market_id.exchange),
                (dialog.market_type_combo, selected.market_id.market_type),
                (dialog.asset_combo, selected.market_id.symbol),
                (dialog.timeframe_combo, selected.market_id.timeframe),
            ):
                index = combo.findData(value)
                assert index > 0
                combo.setCurrentIndex(index)
            dialog._accept_selection()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(dev_launcher.ResearchNewChartDialog, "exec", accept_dataset)
        window.new_chart_requested.emit()
        qapp.processEvents()
        replacement = window.workspace.chart_panel_for_slot(1)
        assert replacement is not first_panel
        replacement.financial_tools_button.click()
        replacement.studies_button.click()
        qapp.processEvents()
        assert tracked[financial_id] is not first_financial
        assert tracked[studies_id] is not first_studies
        assert financial_dialogs[replacement] is tracked[financial_id]
        assert studies_dialogs[replacement] is tracked[studies_id]
        assert replacement in chart_fixtures
        records = {item.window_id: item for item in registry.list_windows()}
        assert records[financial_id].status == "open"
        assert records[studies_id].status == "open"
    finally:
        for widget in tuple(tracked.values()):
            widget.close()
        window.close()
        qapp.processEvents()
