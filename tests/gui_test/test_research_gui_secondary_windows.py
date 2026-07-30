from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from leonardo.data import MarketId
from leonardo.gui.research import ResearchSuiteWindow
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
    ResearchNotebookSnapshotAssignment,
)
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.gui.windows.study_environment_manager_dialog import (
    StudyEnvironmentManagerDialog,
)
from leonardo.gui.windows.study_environment_save_dialog import (
    StudyEnvironmentSaveDialog,
)
from leonardo.gui.windows.workspace_snapshot_manager_dialog import (
    WorkspaceSnapshotManagerDialog,
)
from leonardo.gui.windows.workspace_snapshot_preflight_dialog import (
    WorkspaceSnapshotPreflightDialog,
)
from leonardo.gui.windows.workspace_snapshot_save_dialog import (
    WorkspaceSnapshotSaveDialog,
)
from tools.research_gui_dev_fixtures import (
    build_chart_fixture_for_market,
    build_notebook_gui_fixtures,
    build_primary_chart_fixture,
    build_study_environment_gui_fixtures,
    build_workspace_snapshot_gui_fixtures,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def secondary_bundles():
    primary = build_primary_chart_fixture()
    secondary = build_chart_fixture_for_market(
        MarketId("bybit", "linear", "ETHUSDT", "1h"), slot_id=2
    )
    environments = build_study_environment_gui_fixtures(primary)
    snapshots = build_workspace_snapshot_gui_fixtures(
        primary, secondary, environments
    )
    notebooks = build_notebook_gui_fixtures(
        primary.market_id, secondary.market_id
    )
    return primary, secondary, environments, snapshots, notebooks


@pytest.mark.parametrize(
    ("action_text", "signal_name"),
    (
        ("Save Study Environment...", "save_study_environment_requested"),
        ("Load Study Environment...", "load_study_environment_requested"),
        ("Manage Study Environments...", "manage_study_environments_requested"),
        ("Save Workspace...", "save_workspace_snapshot_requested"),
        ("Load Workspace...", "load_workspace_snapshot_requested"),
        ("Manage Workspaces...", "manage_workspace_snapshots_requested"),
        ("Create New Notebook", "create_notebook_requested"),
        ("Open Notebook", "open_notebook_requested"),
        ("Notebook Manager...", "notebook_manager_requested"),
        ("Save Notebook", "save_notebook_requested"),
        ("Load Notebook", "load_notebook_requested"),
    ),
)
def test_existing_actions_emit_secondary_window_intents_and_log_activity(
    qapp: QApplication, action_text: str, signal_name: str
) -> None:
    window = ResearchSuiteWindow(())
    try:
        if "Study Environment" in action_text:
            window.set_study_environment_actions_state(True, True, True)
        if "Workspace" in action_text:
            window.set_workspace_snapshot_actions_state(True, True, True)
        if "Notebook" in action_text:
            window.set_notebook_actions_state(True, True, True, True)
        if action_text == "Open Notebook":
            window.set_assigned_notebook_state("BTC Market Review")
        action = window.action_for_text(action_text)
        quick = (
            window.quick_button_for_action(action_text)
            if action_text
            in {
                "Open Notebook",
                "Save Study Environment...",
                "Load Study Environment...",
                "Save Workspace...",
                "Load Workspace...",
            }
            else None
        )
        spy = QSignalSpy(getattr(window, signal_name))
        action.trigger()
        assert spy.count() == 1
        if quick is not None:
            assert quick.defaultAction() is action
        activity = window.findChild(
            object, "research_restoration.activity.log"
        )
        assert activity.toPlainText().splitlines()[-1] == (
            f"{action_text} requested"
        )
    finally:
        window.close()


def test_open_notebook_action_tracks_assignment_presentation(
    qapp: QApplication,
) -> None:
    window = ResearchSuiteWindow(())
    try:
        action = window.action_for_text("Open Notebook")
        quick = window.quick_button_for_action("Open Notebook")
        assert not action.isEnabled()
        assert action.toolTip() == (
            "No notebook assigned to the current workspace."
        )
        assert action.statusTip() == action.toolTip()
        assert not quick.isEnabled()

        window.set_assigned_notebook_state("BTC Market Review")
        assert action.isEnabled()
        assert action.toolTip() == "Open assigned notebook: BTC Market Review"
        assert action.statusTip() == action.toolTip()
        assert quick.isEnabled()

        with pytest.raises(ValueError):
            window.set_assigned_notebook_state("")
        with pytest.raises(ValueError):
            window.set_assigned_notebook_state(" padded ")
    finally:
        window.close()


def test_study_environment_fixture_is_exact_and_in_memory(
    secondary_bundles, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = secondary_bundles[0]

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("fixture construction must not access files")

    monkeypatch.setattr(Path, "open", forbidden_open)
    bundle = build_study_environment_gui_fixtures(primary)
    assert tuple(study.study_id for study in bundle.chart_studies) == (
        "dev-env-sma",
        "dev-env-rsi",
    )
    assert len(bundle.environments) == 1
    environment = bundle.environments[0]
    assert environment.environment_id == "dev_env_core"
    assert environment.display_name == "Core Research Environment"
    assert tuple(entry.entry_id for entry in environment.entries) == (
        "env_sma",
        "env_rsi",
    )
    assert tuple(entry.display_name for entry in environment.entries) == (
        "SMA 20",
        "RSI 14",
    )
    assert environment.created_at_utc.isoformat() == "2026-01-01T12:00:00+00:00"
    assert len(bundle.summaries) == 2
    assert bundle.summaries[1].environment_id == "dev_env_invalid"
    assert not bundle.summaries[1].valid
    assert bundle.summaries[1].rejection_reason == "Invalid development fixture"


def test_workspace_snapshot_fixture_is_exact_and_in_memory(
    secondary_bundles,
) -> None:
    _primary, _secondary, _environments, bundle, _notebooks = secondary_bundles
    assert bundle.capture.visualization_mode == "scroll_4"
    assert bundle.capture.active_chart_ref == "chart_001"
    assert len(bundle.capture.charts) == 2
    assert tuple(item.snapshot_id for item in bundle.snapshots) == (
        "dev_snapshot_primary",
        "dev_snapshot_secondary",
    )
    primary, secondary = bundle.snapshots
    assert primary.display_name == "Morning Research Workspace"
    assert primary.workspace.visualization_mode == "scroll_4"
    assert primary.workspace.active_chart_ref == "chart_001"
    assert len(primary.charts) == 2
    assert primary.charts[0].study_environment.environment_id == "dev_env_core"
    assert secondary.display_name == "Secondary Research Workspace"
    assert secondary.workspace.visualization_mode == "fit_8"
    assert len(secondary.charts) == 1
    assert len(bundle.summaries) == 3
    assert bundle.summaries[2].snapshot_id == "dev_snapshot_invalid"
    assert not bundle.summaries[2].valid


def test_notebook_fixture_is_exact_and_in_memory(secondary_bundles) -> None:
    bundle = secondary_bundles[4]
    assert tuple(item.notebook_id for item in bundle.notebooks) == (
        "dev_notebook_market_review",
        "dev_notebook_eth_notes",
    )
    primary, secondary = bundle.notebooks
    assert primary.display_name == "BTC Market Review"
    assert len(primary.pages) == 1
    assert len(primary.pages[0].notes) == 1
    assert len(primary.pages[0].potential_trades) == 1
    assert len(primary.pages[0].points_of_interest) == 1
    assert secondary.display_name == "ETH Research Notes"
    assert len(secondary.pages) == 1
    assert len(secondary.pages[0].notes) == 1
    assert len(bundle.summaries) == 3
    assert bundle.summaries[2].notebook_id == "dev_notebook_invalid"
    assert not bundle.summaries[2].valid
    assert bundle.assignments == (
        ResearchNotebookSnapshotAssignment(
            "dev_snapshot_primary",
            "Morning Research Workspace",
            "dev_notebook_market_review",
        ),
        ResearchNotebookSnapshotAssignment(
            "dev_snapshot_secondary",
            "Secondary Research Workspace",
            None,
        ),
    )
    assert bundle.current_snapshot_id == "dev_snapshot_primary"


def test_notebook_manager_constructor_remains_backward_compatible(
    qapp: QApplication, secondary_bundles
) -> None:
    summaries = secondary_bundles[4].summaries
    parent = ResearchSuiteWindow(())
    dialog = ResearchNotebookManagerDialog(summaries, parent)
    try:
        assert dialog.parent() is parent
        assert dialog.summaries == summaries
        assert dialog.assignments == ()
    finally:
        dialog.close()
        parent.close()


def test_notebook_manager_assignment_projection_and_intents(
    qapp: QApplication, secondary_bundles
) -> None:
    bundle = secondary_bundles[4]
    dialog = ResearchNotebookManagerDialog(
        bundle.summaries, assignments=bundle.assignments
    )
    try:
        table = dialog.findChild(
            QTableWidget, "research.notebook_manager_dialog.table.assignments"
        )
        notebook_list = dialog.findChild(
            QListWidget, "research.notebook_manager_dialog.list.notebooks"
        )
        assign = dialog.findChild(
            QPushButton, "research.notebook_manager_dialog.button.assign"
        )
        unassign = dialog.findChild(
            QPushButton, "research.notebook_manager_dialog.button.unassign"
        )
        assert table.columnCount() == 2
        assert tuple(
            table.horizontalHeaderItem(index).text() for index in range(2)
        ) == ("Workspace", "Assigned Notebook")
        assert table.rowCount() == 2
        assert table.item(0, 0).text() == "Morning Research Workspace"
        assert table.item(0, 1).text() == "BTC Market Review"
        assert table.item(1, 0).text() == "Secondary Research Workspace"
        assert table.item(1, 1).text() == "Unassigned"

        notebook_list.setCurrentRow(1)
        table.setCurrentCell(1, 0)
        assign_spy = QSignalSpy(dialog.assign_requested)
        assert assign.isEnabled()
        assert not unassign.isEnabled()
        assign.click()
        assert assign_spy.count() == 1
        assert assign_spy.at(0) == [
            "dev_notebook_eth_notes",
            "dev_snapshot_secondary",
        ]

        updated = (
            bundle.assignments[0],
            ResearchNotebookSnapshotAssignment(
                "dev_snapshot_secondary",
                "Secondary Research Workspace",
                "dev_notebook_eth_notes",
            ),
        )
        dialog.set_assignments(updated)
        assert table.currentRow() == 1
        assert table.item(1, 1).text() == "ETH Research Notes"
        assert not assign.isEnabled()
        assert unassign.isEnabled()
        unassign_spy = QSignalSpy(dialog.unassign_requested)
        unassign.click()
        assert unassign_spy.at(0) == [
            "dev_notebook_eth_notes",
            "dev_snapshot_secondary",
        ]
    finally:
        dialog.close()


def test_notebook_delete_confirmation_lists_assigned_snapshots(
    qapp: QApplication,
    secondary_bundles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = secondary_bundles[4]
    dialog = ResearchNotebookManagerDialog(
        bundle.summaries, assignments=bundle.assignments
    )
    captured: list[str] = []

    def confirm(_parent, _title, message, *_args):
        captured.append(message)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    deleted = QSignalSpy(dialog.delete_requested)
    try:
        dialog.findChild(
            QPushButton, "research.notebook_manager_dialog.button.delete"
        ).click()
        assert "Morning Research Workspace" in captured[0]
        assert "Workspace references" in captured[0]
        assert deleted.at(0) == ["dev_notebook_market_review"]
    finally:
        dialog.close()


def test_existing_secondary_window_families_are_reused(
    qapp: QApplication, secondary_bundles
) -> None:
    primary, _secondary, environments, snapshots, notebooks = secondary_bundles
    save_environment = StudyEnvironmentSaveDialog(
        1,
        "dev_session_1",
        environments.chart_studies,
        environments.summaries,
    )
    manage_environment = StudyEnvironmentManagerDialog(
        environments.summaries, ()
    )
    save_snapshot = WorkspaceSnapshotSaveDialog(
        snapshots.capture, snapshots.summaries
    )
    manage_snapshot = WorkspaceSnapshotManagerDialog(snapshots.summaries)
    preflight = WorkspaceSnapshotPreflightDialog(
        __import__(
            "leonardo.research", fromlist=["ResearchWorkspaceSnapshotCompatibilityReport"]
        ).ResearchWorkspaceSnapshotCompatibilityReport(
            "dev_snapshot_primary", "append", True, ()
        )
    )
    manager = ResearchNotebookManagerDialog(
        notebooks.summaries, assignments=notebooks.assignments
    )
    editor = ResearchNotebookWindow()
    try:
        assert save_environment.windowTitle() == "Save Study Environment"
        assert manage_environment.windowTitle() == "Manage Study Environments"
        assert save_snapshot.windowTitle() == "Save Workspace"
        assert manage_snapshot.windowTitle() == "Manage Workspaces"
        assert preflight.windowTitle() == "Load Workspace"
        assert manager.windowTitle() == "Research Notebooks"
        assert editor.windowTitle() == "Research Notebook"
        assert primary.market_id.as_key() in {
            page.market_id.as_key()
            for notebook in notebooks.notebooks
            for page in notebook.pages
        }
    finally:
        for dialog in (
            save_environment,
            manage_environment,
            save_snapshot,
            manage_snapshot,
            preflight,
            manager,
        ):
            dialog.close()
        editor.hide()


def test_launcher_wires_fixture_only_secondary_workflows() -> None:
    source = Path("tools/dev_launch_research_gui_restoration.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "build_study_environment_gui_fixtures",
        "build_workspace_snapshot_gui_fixtures",
        "build_notebook_gui_fixtures",
        "StudyEnvironmentSaveDialog(",
        "StudyEnvironmentManagerDialog(",
        "WorkspaceSnapshotSaveDialog(",
        "WorkspaceSnapshotManagerDialog(",
        "WorkspaceSnapshotPreflightDialog(",
        "ResearchNotebookManagerDialog(",
        "ResearchNotebookWindow(",
        "save_study_environment_requested.connect",
        "load_study_environment_requested.connect",
        "manage_study_environments_requested.connect",
        "save_workspace_snapshot_requested.connect",
        "load_workspace_snapshot_requested.connect",
        "manage_workspace_snapshots_requested.connect",
        "create_notebook_requested.connect",
        "open_notebook_requested.connect",
        "notebook_manager_requested.connect",
        "save_notebook_requested.connect",
        "load_notebook_requested.connect",
        '"Save requested (dev GUI)."',
    ):
        assert required in source
    for forbidden in (
        "CoreRunner",
        "StudyEnvironmentStore",
        "ResearchWorkspaceSnapshotStore",
        "ResearchNotebookStore",
        "ArtifactStore",
        "write_text(",
        "write_bytes(",
        "json.dump",
        "Save Recipe",
        "Recipe Export",
        "Export Recipe",
        "Study Environment Recipe",
    ):
        assert forbidden not in source
    assert source.count("ResearchChartPanel(") == 1
    assert "window.workspace.add_chart(slot_id," in source
    assert "preflight.load_requested.connect(dev_intents.append)" in source


def test_manager_module_has_no_domain_ownership_imports() -> None:
    source = Path(
        "src/leonardo/gui/windows/research_notebook_manager_dialog.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "WorkspaceSnapshotStore",
        "ResearchNotebookStore",
        "CoreRunner",
        "ApplicationService",
    ):
        assert forbidden not in source
    assert "ResearchNotebookSummary" in source
    assert "ResearchNotebookSnapshotAssignment" in source
