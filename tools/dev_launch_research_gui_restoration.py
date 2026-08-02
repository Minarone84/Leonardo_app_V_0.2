"""Launch the restored Research GUI shell with deterministic read models."""

from __future__ import annotations

import os

from leonardo.core.window_registry import WindowRegistry
from leonardo.data import MarketId
from leonardo.gui.research import ResearchSuiteWindow
from leonardo.gui.research import (
    ResearchChartPanel,
    ResearchFinancialToolsDialog,
    ResearchNewChartDialog,
    ResearchStudiesManagerDialog,
)
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.window_tracking import GuiWindowTracker
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
    ResearchNotebookSnapshotAssignment,
)


_LIFECYCLE_PENDING_TEXT = "Available after Research chart lifecycle wiring."


def _show_tracked_window(
    window_id: str,
    widget,
    registry: WindowRegistry,
    tracked_windows: dict[str, object],
) -> None:
    existing = tracked_windows.get(window_id)
    if existing is not None and existing is not widget:
        raise RuntimeError(f"logical window already exists: {window_id}")
    if existing is None:
        tracked_windows[window_id] = widget
        GuiWindowTracker(
            widget,
            window_id=window_id,
            title=widget.windowTitle(),
            window_type="dialog" if hasattr(widget, "finished") else "window",
            registry=registry,
        )

        def forget(_object=None) -> None:
            if tracked_windows.get(window_id) is widget:
                tracked_windows.pop(window_id, None)

        widget.destroyed.connect(forget)
        if hasattr(widget, "finished"):
            widget.finished.connect(
                lambda _result: registry.close_window(window_id)
            )
    widget.show()
    registry.open_window(window_id)
    widget.raise_()
    widget.activateWindow()
    try:
        registry.focus_window(window_id)
    except RuntimeError:
        pass


def _dispose_tracked_window(
    window_id: str,
    registry: WindowRegistry,
    tracked_windows: dict[str, object],
) -> None:
    widget = tracked_windows.pop(window_id, None)
    if widget is None:
        return
    widget.close()
    registry.close_window(window_id)
    widget.deleteLater()
from leonardo.gui.windows.research_notebook_window import (
    ResearchNotebookSaveIntent,
    ResearchNotebookWindow,
)
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
from leonardo.research import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchWorkspaceSnapshotCompatibilityReport,
    StudyEnvironmentCompatibilityReport,
    WorkspaceSnapshotChartCompatibility,
)
from tools.research_gui_dev_fixtures import (
    RESEARCH_GUI_DATASET_FIXTURES,
    ResearchGuiDevChartFixture,
    build_additional_workspace_chart_fixtures,
    build_chart_fixture_for_market,
    build_notebook_gui_fixtures,
    build_primary_chart_fixture,
    build_study_environment_gui_fixtures,
    build_study_setup_catalog_fixture,
    build_workspace_snapshot_gui_fixtures,
)


def _build_chart_panel(
    fixture: ResearchGuiDevChartFixture,
    financial_tools_dialogs: dict[
        ResearchChartPanel, ResearchFinancialToolsDialog
    ],
    studies_manager_dialogs: dict[
        ResearchChartPanel, ResearchStudiesManagerDialog
    ],
    *,
    slot_id: int | None = None,
    window_registry: WindowRegistry | None = None,
    tracked_windows: dict[str, object] | None = None,
    chart_fixtures: dict[
        ResearchChartPanel, ResearchGuiDevChartFixture
    ] | None = None,
) -> ResearchChartPanel:
    if (window_registry is None) != (tracked_windows is None):
        raise ValueError("window_registry and tracked_windows must be supplied together")
    if window_registry is not None and (
        type(slot_id) is not int or slot_id <= 0
    ):
        raise ValueError("slot_id must be positive when window tracking is enabled")
    panel = ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )

    def open_financial_tools() -> None:
        dialog = financial_tools_dialogs.get(panel)
        if dialog is None:
            dialog = ResearchFinancialToolsDialog(
                panel.market_id,
                build_study_setup_catalog_fixture(fixture),
                panel,
            )
            financial_tools_dialogs[panel] = dialog
        if window_registry is None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        else:
            _show_tracked_window(
                f"research_restoration.chart.{slot_id}.financial_tools",
                dialog,
                window_registry,
                tracked_windows,
            )

    def open_studies_manager() -> None:
        dialog = studies_manager_dialogs.get(panel)
        if dialog is None:
            dialog = ResearchStudiesManagerDialog(
                panel.market_id,
                fixture.study_entries,
                panel,
            )
            studies_manager_dialogs[panel] = dialog
        else:
            dialog.set_entries(fixture.study_entries)
        if window_registry is None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        else:
            _show_tracked_window(
                f"research_restoration.chart.{slot_id}.studies",
                dialog,
                window_registry,
                tracked_windows,
            )

    panel.financial_tools_requested.connect(open_financial_tools)
    panel.studies_requested.connect(open_studies_manager)
    if window_registry is not None:
        def cleanup_chart_context() -> None:
            for role in ("financial_tools", "studies"):
                _dispose_tracked_window(
                    f"research_restoration.chart.{slot_id}.{role}",
                    window_registry,
                    tracked_windows,
                )
            financial_tools_dialogs.pop(panel, None)
            studies_manager_dialogs.pop(panel, None)
            if chart_fixtures is not None:
                chart_fixtures.pop(panel, None)

        panel.close_requested.connect(cleanup_chart_context)
    panel.go_to_button.setEnabled(False)
    panel.go_to_button.setToolTip(_LIFECYCLE_PENDING_TEXT)
    return panel


def main() -> int:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    application = QApplication.instance() or QApplication([])
    apply_theme_stylesheet(application, load_default_theme())
    window = ResearchSuiteWindow(RESEARCH_GUI_DATASET_FIXTURES)
    window_registry = WindowRegistry()
    tracked_windows: dict[str, object] = {}
    GuiWindowTracker(
        window,
        window_id="research_restoration.main",
        title=window.windowTitle(),
        window_type="main_window",
        registry=window_registry,
    )
    window._dev_window_registry = window_registry
    window._dev_tracked_windows = tracked_windows
    financial_tools_dialogs: dict[
        ResearchChartPanel, ResearchFinancialToolsDialog
    ] = {}
    studies_manager_dialogs: dict[
        ResearchChartPanel, ResearchStudiesManagerDialog
    ] = {}
    chart_fixtures: dict[ResearchChartPanel, ResearchGuiDevChartFixture] = {}
    window._dev_financial_tools_dialogs = financial_tools_dialogs
    window._dev_studies_manager_dialogs = studies_manager_dialogs
    window._dev_chart_fixtures = chart_fixtures
    dev_intents: list[object] = []
    fixture = build_primary_chart_fixture()
    secondary_fixture = build_chart_fixture_for_market(
        MarketId("bybit", "linear", "ETHUSDT", "1h"),
        slot_id=2,
    )
    environment_bundle = build_study_environment_gui_fixtures(fixture)
    snapshot_bundle = build_workspace_snapshot_gui_fixtures(
        fixture,
        secondary_fixture,
        environment_bundle,
    )
    notebook_bundle = build_notebook_gui_fixtures(
        fixture.market_id,
        secondary_fixture.market_id,
    )
    notebooks = list(notebook_bundle.notebooks)
    notebook_summaries = list(notebook_bundle.summaries)
    notebook_assignments = list(notebook_bundle.assignments)
    chart_panel = _build_chart_panel(
        fixture,
        financial_tools_dialogs,
        studies_manager_dialogs,
        slot_id=1,
        window_registry=window_registry,
        tracked_windows=tracked_windows,
        chart_fixtures=chart_fixtures,
    )
    chart_fixtures[chart_panel] = fixture
    window.workspace.show_single_chart(chart_panel)
    if os.environ.get("LEONARDO_RESEARCH_GUI_POPULATE_8") == "1":
        for slot_id, additional in enumerate(
            build_additional_workspace_chart_fixtures(), start=2
        ):
            additional_panel = _build_chart_panel(
                additional,
                financial_tools_dialogs,
                studies_manager_dialogs,
                slot_id=slot_id,
                window_registry=window_registry,
                tracked_windows=tracked_windows,
                chart_fixtures=chart_fixtures,
            )
            chart_fixtures[additional_panel] = additional
            window.workspace.add_chart(slot_id, additional_panel)

    def open_new_chart() -> None:
        if not window.workspace.can_add_chart():
            QMessageBox.information(
                window,
                "New Chart",
                "Maximum of 8 Research charts reached.",
            )
            return
        window_id = "research_restoration.new_chart"
        dialog = tracked_windows.get(window_id)
        if dialog is None:
            dialog = ResearchNewChartDialog(window.dataset_summaries, window)
            tracked_windows[window_id] = dialog
            GuiWindowTracker(
                dialog,
                window_id=window_id,
                title=dialog.windowTitle(),
                window_type="dialog",
                registry=window_registry,
            )
            dialog.finished.connect(
                lambda _result: window_registry.close_window(window_id)
            )
        dialog.reset_selection()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_dataset_summary()
        if selected is None:
            return
        slot_id = window.workspace.next_free_slot_id()
        if slot_id is None:
            QMessageBox.information(
                window,
                "New Chart",
                "Maximum of 8 Research charts reached.",
            )
            return
        selected_fixture = build_chart_fixture_for_market(
            selected.market_id,
            slot_id=slot_id,
        )
        selected_panel = _build_chart_panel(
            selected_fixture,
            financial_tools_dialogs,
            studies_manager_dialogs,
            slot_id=slot_id,
            window_registry=window_registry,
            tracked_windows=tracked_windows,
            chart_fixtures=chart_fixtures,
        )
        chart_fixtures[selected_panel] = selected_fixture
        window.workspace.add_chart(slot_id, selected_panel)
        window.workspace.set_active_slot(slot_id)

    def show_dialog(window_id: str, dialog) -> None:
        _show_tracked_window(
            window_id,
            dialog,
            window_registry,
            tracked_windows,
        )

    def environment_targets() -> tuple[StudyEnvironmentTarget, ...]:
        detached = set(window.workspace.detached_slot_ids())
        return tuple(
            StudyEnvironmentTarget(
                slot_id,
                f"dev_session_{slot_id}",
                window.workspace.chart_panel_for_slot(slot_id).dataset_label.text(),
                slot_id in detached,
            )
            for slot_id in window.workspace.slot_ids()
        )

    def open_environment_manager(*, mode: str) -> None:
        window_id = f"research_restoration.study_environment.{mode}"
        dialog = tracked_windows.get(window_id)
        if dialog is not None:
            dialog.set_summaries(environment_bundle.summaries)
            show_dialog(window_id, dialog)
            return
        dialog = StudyEnvironmentManagerDialog(
            environment_bundle.summaries,
            environment_targets(),
            window,
            mode=mode,
        )

        def select_environment(environment_id: str) -> None:
            environment = next(
                (
                    item
                    for item in environment_bundle.environments
                    if item.environment_id == environment_id
                ),
                None,
            )
            if environment is not None:
                dialog.set_environment(environment)

        dialog.environment_selected.connect(select_environment)
        dialog.compatibility_requested.connect(
            lambda intent: dialog.set_compatibility(
                intent,
                StudyEnvironmentCompatibilityReport(intent.environment_id),
            )
        )
        dialog.apply_requested.connect(dev_intents.append)
        dialog.metadata_save_requested.connect(dev_intents.append)
        dialog.delete_requested.connect(dev_intents.append)
        dialog.refresh_requested.connect(
            lambda: dialog.set_summaries(environment_bundle.summaries)
        )
        dialog.set_summaries(environment_bundle.summaries)
        show_dialog(window_id, dialog)

    def save_study_environment() -> None:
        slot_id = getattr(window.workspace, "active_slot_id")
        if slot_id is None:
            QMessageBox.information(
                window,
                "Study Environment",
                "Select a Research chart first.",
            )
            return
        panel = window.workspace.chart_panel_for_slot(slot_id)
        panel_fixture = chart_fixtures[panel]
        studies = build_study_environment_gui_fixtures(
            panel_fixture
        ).chart_studies
        window_id = "research_restoration.study_environment.save"
        dialog = tracked_windows.get(window_id)
        session_id = f"dev_session_{slot_id}"
        if dialog is not None and (
            dialog._slot_id != slot_id or dialog._session_id != session_id
        ):
            _dispose_tracked_window(
                window_id, window_registry, tracked_windows
            )
            dialog = None
        if dialog is None:
            dialog = StudyEnvironmentSaveDialog(
                slot_id,
                session_id,
                studies,
                environment_bundle.summaries,
                window,
            )
            dialog.save_requested.connect(dev_intents.append)
        show_dialog(window_id, dialog)

    def save_workspace_snapshot() -> None:
        window_id = "research_restoration.workspace.save"
        dialog = tracked_windows.get(window_id)
        if dialog is None:
            dialog = WorkspaceSnapshotSaveDialog(
                snapshot_bundle.capture,
                snapshot_bundle.summaries,
                window,
            )
            dialog.save_requested.connect(dev_intents.append)
        show_dialog(window_id, dialog)

    def open_snapshot_manager(*, mode: str) -> None:
        window_id = f"research_restoration.workspace.{mode}"
        dialog = tracked_windows.get(window_id)
        if dialog is not None:
            dialog.set_summaries(snapshot_bundle.summaries)
            show_dialog(window_id, dialog)
            return
        dialog = WorkspaceSnapshotManagerDialog(
            snapshot_bundle.summaries,
            window,
            mode=mode,
        )

        def select_snapshot(snapshot_id: str) -> None:
            snapshot = next(
                (
                    item
                    for item in snapshot_bundle.snapshots
                    if item.snapshot_id == snapshot_id
                ),
                None,
            )
            if snapshot is not None:
                dialog.set_snapshot(snapshot)
                compatibility_report(
                    WorkspaceSnapshotLoadIntent(
                        snapshot_id,
                        "append" if dialog.append_radio.isChecked() else "replace",
                    )
                )

        def compatibility_report(intent):
            snapshot = next(
                item
                for item in snapshot_bundle.snapshots
                if item.snapshot_id == intent.snapshot_id
            )
            report = ResearchWorkspaceSnapshotCompatibilityReport(
                intent.snapshot_id,
                intent.mode,
                True,
                tuple(
                    WorkspaceSnapshotChartCompatibility(
                        chart.chart_ref,
                        chart.workspace_position,
                        True,
                    )
                    for chart in snapshot.charts
                ),
            )
            dialog.set_compatibility(report)
            return report

        def open_preflight(intent) -> None:
            report = dialog.compatibility_report
            if report is None or report.snapshot_id != intent.snapshot_id:
                report = compatibility_report(intent)
            preflight_id = "research_restoration.workspace.preflight"
            preflight = tracked_windows.get(preflight_id)
            report_key = (report.snapshot_id, report.mode)
            if preflight is not None and getattr(
                preflight, "_dev_report_key", None
            ) != report_key:
                _dispose_tracked_window(
                    preflight_id, window_registry, tracked_windows
                )
                preflight = None
            if preflight is None:
                preflight = WorkspaceSnapshotPreflightDialog(report, window)
                preflight._dev_report_key = report_key
                preflight.load_requested.connect(dev_intents.append)
            show_dialog(preflight_id, preflight)

        dialog.selection_requested.connect(select_snapshot)
        dialog.compatibility_requested.connect(compatibility_report)
        dialog.load_requested.connect(open_preflight)
        dialog.metadata_requested.connect(dev_intents.append)
        dialog.delete_requested.connect(dev_intents.append)
        dialog.refresh_requested.connect(
            lambda: dialog.set_summaries(snapshot_bundle.summaries)
        )
        dialog.set_summaries(snapshot_bundle.summaries)
        show_dialog(window_id, dialog)

    def assigned_notebook_id() -> str | None:
        return next(
            (
                item.notebook_id
                for item in notebook_assignments
                if item.snapshot_id == notebook_bundle.current_snapshot_id
            ),
            None,
        )

    def sync_assigned_notebook_action() -> None:
        notebook_id = assigned_notebook_id()
        notebook = next(
            (item for item in notebooks if item.notebook_id == notebook_id),
            None,
        )
        window.set_assigned_notebook_state(
            None if notebook is None else notebook.display_name
        )

    def active_notebook_editor() -> ResearchNotebookWindow:
        window_id = "research_restoration.notebook.editor"
        editor = tracked_windows.get(window_id)
        if editor is None:
            editor = ResearchNotebookWindow(window)
            editor.save_requested.connect(handle_notebook_save)

            def hide_editor() -> None:
                if tracked_windows.get(window_id) is editor:
                    editor.hide()
                    window_registry.close_window(window_id)

            editor.close_requested.connect(hide_editor)
        return editor

    def show_notebook(notebook_id: str) -> None:
        notebook = next(
            (item for item in notebooks if item.notebook_id == notebook_id),
            None,
        )
        if notebook is None:
            return
        editor = active_notebook_editor()
        editor.set_notebook(notebook)
        show_dialog("research_restoration.notebook.editor", editor)

    def create_notebook() -> None:
        editor = active_notebook_editor()
        editor.set_draft(
            ResearchNotebookDraft(
                "Untitled Notebook",
                "",
                ResearchNotebookAnnotationSettingsV1(),
                (),
                None,
            ),
            dirty=False,
        )
        show_dialog("research_restoration.notebook.editor", editor)

    def open_assigned_notebook() -> None:
        notebook_id = assigned_notebook_id()
        if notebook_id is None:
            QMessageBox.information(
                window,
                "Open Notebook",
                "No notebook is assigned to the current Workspace.",
            )
            return
        show_notebook(notebook_id)

    def handle_notebook_save(intent: ResearchNotebookSaveIntent) -> None:
        dev_intents.append(intent)
        editor = tracked_windows.get("research_restoration.notebook.editor")
        if editor is not None:
            editor.set_dirty(False)
            editor.set_status("Save requested (dev GUI).")

    def open_notebook_manager() -> None:
        window_id = "research_restoration.notebook.manager"
        dialog = tracked_windows.get(window_id)
        if dialog is not None:
            dialog.set_summaries(tuple(notebook_summaries))
            dialog.set_assignments(tuple(notebook_assignments))
            show_dialog(window_id, dialog)
            return
        dialog = ResearchNotebookManagerDialog(
            tuple(notebook_summaries),
            window,
            assignments=tuple(notebook_assignments),
        )
        def refresh_manager() -> None:
            dialog.set_summaries(tuple(notebook_summaries))
            dialog.set_assignments(tuple(notebook_assignments))

        def assign_notebook(notebook_id: str, snapshot_id: str) -> None:
            for index, assignment in enumerate(notebook_assignments):
                if assignment.snapshot_id == snapshot_id:
                    notebook_assignments[index] = ResearchNotebookSnapshotAssignment(
                        assignment.snapshot_id,
                        assignment.snapshot_display_name,
                        notebook_id,
                    )
                    break
            refresh_manager()
            sync_assigned_notebook_action()

        def unassign_notebook(notebook_id: str, snapshot_id: str) -> None:
            for index, assignment in enumerate(notebook_assignments):
                if (
                    assignment.snapshot_id == snapshot_id
                    and assignment.notebook_id == notebook_id
                ):
                    notebook_assignments[index] = ResearchNotebookSnapshotAssignment(
                        assignment.snapshot_id,
                        assignment.snapshot_display_name,
                        None,
                    )
                    break
            refresh_manager()
            sync_assigned_notebook_action()

        def delete_notebook(notebook_id: str) -> None:
            notebooks[:] = [
                item for item in notebooks if item.notebook_id != notebook_id
            ]
            notebook_summaries[:] = [
                item
                for item in notebook_summaries
                if item.notebook_id != notebook_id
            ]
            for index, assignment in enumerate(notebook_assignments):
                if assignment.notebook_id == notebook_id:
                    notebook_assignments[index] = ResearchNotebookSnapshotAssignment(
                        assignment.snapshot_id,
                        assignment.snapshot_display_name,
                        None,
                    )
            refresh_manager()
            sync_assigned_notebook_action()

        dialog.open_requested.connect(show_notebook)
        dialog.create_requested.connect(create_notebook)
        dialog.refresh_requested.connect(refresh_manager)
        dialog.assign_requested.connect(assign_notebook)
        dialog.unassign_requested.connect(unassign_notebook)
        dialog.delete_requested.connect(delete_notebook)
        show_dialog(window_id, dialog)

    window.new_chart_requested.connect(open_new_chart)
    window.save_study_environment_requested.connect(save_study_environment)
    window.load_study_environment_requested.connect(
        lambda: open_environment_manager(mode="load")
    )
    window.manage_study_environments_requested.connect(
        lambda: open_environment_manager(mode="manage")
    )
    window.save_workspace_snapshot_requested.connect(save_workspace_snapshot)
    window.load_workspace_snapshot_requested.connect(
        lambda: open_snapshot_manager(mode="load")
    )
    window.manage_workspace_snapshots_requested.connect(
        lambda: open_snapshot_manager(mode="manage")
    )
    window.open_notebook_requested.connect(open_assigned_notebook)
    window.notebook_manager_requested.connect(open_notebook_manager)
    window.action_for_text("Scroll 4").triggered.connect(
        lambda checked: checked
        and window.workspace.set_visualization_mode("scroll_4")
    )
    window.action_for_text("Fit 8").triggered.connect(
        lambda checked: checked
        and window.workspace.set_visualization_mode("fit_8")
    )
    pan_anchor = window.action_for_text("Pan Anchor")
    pan_anchor.setEnabled(False)
    pan_anchor.setToolTip(_LIFECYCLE_PENDING_TEXT)
    pan_anchor.setStatusTip(_LIFECYCLE_PENDING_TEXT)
    sync_assigned_notebook_action()
    window.showMaximized()
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(main())
