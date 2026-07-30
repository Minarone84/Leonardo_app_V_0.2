from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.research.lifecycle_presenter import (
    RestoredResearchLifecyclePresenter,
)
from leonardo.gui.research.suite_window import ResearchSuiteWindow
from leonardo.research import StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import (
    _wait_until,
    _write_accepted_dataset,
)


def test_main_application_owns_tracks_retires_and_reopens_restored_research(
    tmp_path: Path,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    context = app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(context)
    main = composition.create_main_window()
    authorities = (
        app.core_runner,
        app.task_manager,
        app.window_registry,
        app.ohlcv_store,
        context.research_dataset_service,
        context.research_study_service,
        context.research_study_setup_service,
        context.research_workspace_snapshot_service,
        context.research_notebook_service,
    )
    main.show()
    qapp.processEvents()
    try:
        main.action_for_id("main_window.open_research_suite").trigger()
        window = composition.research_suite_window
        presenter = composition.research_suite_presenter
        assert isinstance(window, ResearchSuiteWindow)
        assert isinstance(presenter, RestoredResearchLifecyclePresenter)
        assert presenter._service is context.research_dataset_service
        assert presenter._study_service is context.research_study_service
        assert presenter._study_setup_service is context.research_study_setup_service
        assert (
            presenter._snapshot_service
            is context.research_workspace_snapshot_service
        )
        assert presenter._notebook_service is context.research_notebook_service
        assert (
            app.research_workspace_snapshot_domain._notebook_link
            is app.research_workspace_notebook_link_domain
        )
        assert (
            app.research_workspace_snapshot_service._notebook_link
            is app.research_workspace_notebook_link_domain
        )
        assert (
            app.research_notebook_service._notebook_link
            is app.research_workspace_notebook_link_domain
        )
        assert (
            app.research_workspace_notebook_link_domain._snapshot_store
            is app.workspace_snapshot_store
        )
        assert (
            app.research_workspace_notebook_link_domain._notebook_service
            is app.research_notebook_domain
        )
        assert authorities == (
            app.core_runner,
            app.task_manager,
            app.window_registry,
            app.ohlcv_store,
            context.research_dataset_service,
            context.research_study_service,
            context.research_study_setup_service,
            context.research_workspace_snapshot_service,
            context.research_notebook_service,
        )
        _wait_until(
            lambda: next(
                item
                for item in context.window_registry.list_windows()
                if item.window_id == "research_suite.window"
            ).status
            == "open"
        )
        registry_rows = tuple(
            item
            for item in context.window_registry.list_windows()
            if item.window_id == "research_suite.window"
        )
        assert len(registry_rows) == 1
        assert composition.tracker_for("research_suite.window") is not None
        expected_action_state = {
            "Save Study Environment...": False,
            "Load Study Environment...": False,
            "Manage Study Environments...": True,
            "Save Workspace...": False,
            "Load Workspace...": True,
            "Manage Workspaces...": True,
            "Create New Notebook": True,
            "Open Notebook": False,
            "Notebook Manager...": True,
            "Save Notebook": False,
            "Load Notebook": True,
        }
        assert {
            action_text: window.action_for_text(action_text).isEnabled()
            for action_text in expected_action_state
        } == expected_action_state

        main.action_for_id("main_window.open_research_suite").trigger()
        assert composition.research_suite_window is window
        assert composition.research_suite_presenter is presenter
        assert len(
            tuple(
                item
                for item in context.window_registry.list_windows()
                if item.window_id == "research_suite.window"
            )
        ) == 1

        first_window_identity = id(window)
        first_presenter_identity = id(presenter)
        window.close()
        qapp.processEvents()
        assert presenter._disposed
        assert composition.research_suite_window is None
        assert composition.research_suite_presenter is None
        assert composition.tracker_for("research_suite.window") is None
        assert main.isVisible()
        assert app.status == "running"
        assert next(
            item
            for item in context.window_registry.list_windows()
            if item.window_id == "research_suite.window"
        ).status == "closed"

        main.action_for_id("main_window.open_research_suite").trigger()
        reopened_window = composition.research_suite_window
        reopened_presenter = composition.research_suite_presenter
        assert isinstance(reopened_window, ResearchSuiteWindow)
        assert isinstance(reopened_presenter, RestoredResearchLifecyclePresenter)
        assert id(reopened_window) != first_window_identity
        assert id(reopened_presenter) != first_presenter_identity
        assert reopened_presenter._service is context.research_dataset_service
        assert reopened_presenter._study_service is context.research_study_service
        assert (
            reopened_presenter._study_setup_service
            is context.research_study_setup_service
        )
        assert (
            reopened_presenter._snapshot_service
            is context.research_workspace_snapshot_service
        )
        assert (
            reopened_presenter._notebook_service
            is context.research_notebook_service
        )
        assert len(
            tuple(
                item
                for item in context.window_registry.list_windows()
                if item.window_id == "research_suite.window"
            )
        ) == 1

        main.close()
        QCoreApplication.processEvents()
        assert reopened_presenter._disposed
        assert composition.research_suite_window is None
        assert composition.research_suite_presenter is None
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
    assert app.status == "stopped"


def test_restored_commands_use_composed_environment_snapshot_and_notebook_services(
    tmp_path: Path,
    monkeypatch,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    context = app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(context)
    main = composition.create_main_window()
    main.show()
    qapp.processEvents()
    try:
        main.action_for_id("main_window.open_research_suite").trigger()
        window = composition.research_suite_window
        presenter = composition.research_suite_presenter
        assert isinstance(window, ResearchSuiteWindow)
        assert isinstance(presenter, RestoredResearchLifecyclePresenter)
        _wait_until(lambda: bool(presenter._dataset_summaries))
        market_id = presenter._dataset_summaries[0].market_id
        slot_id, chart = presenter._create_restored_chart(market_id)
        chart.open_dataset(market_id)
        _wait_until(
            lambda: chart.session.dataset is not None and not chart.is_busy
        )
        chart.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 14})
        )
        _wait_until(lambda: len(chart.session.studies) == 1 and not chart.is_busy)
        study = chart.session.studies[0]
        chart.apply_guide_values(
            study.study_id,
            {
                "overbought": 70.0,
                "center": 50.0,
                "oversold": 25.0,
            },
        )
        presenter._on_chart_state_changed(slot_id)

        window.action_for_text("Save Study Environment...").trigger()
        _wait_until(lambda: slot_id in presenter._environment_save_dialogs)
        environment_dialog = presenter._environment_save_dialogs[slot_id]
        environment_dialog._name.setText("Threshold Environment")
        environment_dialog._save.click()
        _wait_until(lambda: not presenter._setup_task_ids)
        environment_summary = app.research_study_setup_domain.list_environments()[0]
        environment = app.research_study_setup_domain.load_environment(
            environment_summary.environment_id
        )
        assert (
            environment.entries[0]
            .presentation.guide_styles[-1]
            .value
        ) == 25.0

        window.action_for_text("Load Study Environment...").trigger()
        _wait_until(lambda: bool(presenter._environment_managers))
        _wait_until(
            lambda: presenter._environment_manager_modes.get(slot_id) == "load"
            and not presenter._setup_task_ids
        )
        environment_manager = presenter._environment_managers[slot_id]
        assert environment_manager._mode == "load"
        assert environment_manager.windowTitle() == "Load Study Environment"
        assert environment_manager._name.isReadOnly()
        assert environment_manager._description.isReadOnly()
        assert environment_manager._save.isHidden()
        assert environment_manager.environment is not None
        _wait_until(lambda: environment_manager._report is not None)
        study_count = chart.session.study_count
        environment_manager._apply.click()
        _wait_until(
            lambda: chart.session.study_count == study_count + 1
            and not chart.environment_apply_active
        )
        window.action_for_text("Load Study Environment...").trigger()
        assert presenter._environment_managers[slot_id] is environment_manager
        with pytest.raises(ValueError, match="mode must be 'load' or 'manage'"):
            presenter._open_environment_manager("invalid")

        _wait_until(lambda: not presenter._setup_task_ids)
        window.action_for_text("Manage Study Environments...").trigger()
        _wait_until(
            lambda: presenter._environment_manager_modes.get(slot_id) == "manage"
            and presenter._environment_managers[slot_id] is not environment_manager
            and not presenter._setup_task_ids
        )
        manage_manager = presenter._environment_managers[slot_id]
        assert manage_manager._mode == "manage"
        assert manage_manager.windowTitle() == "Manage Study Environments"
        assert not manage_manager._name.isReadOnly()
        assert not manage_manager._description.isReadOnly()
        assert manage_manager._save.isVisible()
        assert manage_manager.environment is not None
        manage_manager._name.setText("Updated Threshold Environment")
        manage_manager._save.click()
        _wait_until(lambda: not presenter._setup_task_ids)
        assert (
            app.research_study_setup_domain.load_environment(
                environment_summary.environment_id
            ).display_name
            == "Updated Threshold Environment"
        )
        window.action_for_text("Manage Study Environments...").trigger()
        assert presenter._environment_managers[slot_id] is manage_manager

        manager_window_id = f"research.environment_manager.{slot_id}"
        assert len(
            tuple(
                item
                for item in context.window_registry.list_windows()
                if item.window_id == manager_window_id
                and item.status == "open"
            )
        ) == 1
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        manage_manager._delete.click()
        _wait_until(
            lambda: not presenter._setup_task_ids
            and not app.research_study_setup_domain.list_environments()
        )

        window.action_for_text("Load Study Environment...").trigger()
        _wait_until(
            lambda: presenter._environment_manager_modes.get(slot_id) == "load"
            and presenter._environment_managers[slot_id] is not manage_manager
            and not presenter._setup_task_ids
        )
        replacement_load_manager = presenter._environment_managers[slot_id]
        assert replacement_load_manager._mode == "load"
        assert replacement_load_manager.windowTitle() == "Load Study Environment"
        assert len(
            tuple(
                item
                for item in context.window_registry.list_windows()
                if item.window_id == manager_window_id
                and item.status == "open"
            )
        ) == 1

        window.action_for_text("Save Workspace...").trigger()
        _wait_until(lambda: presenter._snapshot_save_dialog is not None)
        snapshot_dialog = presenter._snapshot_save_dialog
        snapshot_dialog.name_edit.setText("Threshold Workspace")
        snapshot_dialog.save_button.click()
        _wait_until(lambda: not presenter._snapshot_task_ids)
        snapshot_summary = app.research_workspace_snapshot_domain.list_snapshots()[0]
        snapshot = app.research_workspace_snapshot_domain.load_snapshot(
            snapshot_summary.snapshot_id
        )
        assert (
            snapshot.charts[0]
            .study_environment.entries[0]
            .presentation.guide_styles[-1]
            .value
        ) == 25.0

        window.action_for_text("Load Workspace...").trigger()
        _wait_until(
            lambda: presenter._snapshot_manager is not None
            and presenter._snapshot_manager_mode == "load"
        )
        load_manager = presenter._snapshot_manager
        window.action_for_text("Load Workspace...").trigger()
        assert presenter._snapshot_manager is load_manager
        _wait_until(lambda: not presenter._snapshot_task_ids)
        window.action_for_text("Manage Workspaces...").trigger()
        _wait_until(
            lambda: presenter._snapshot_manager is not None
            and presenter._snapshot_manager_mode == "manage"
        )
        assert presenter._snapshot_manager is not load_manager

        window.action_for_text("Create New Notebook").trigger()
        editor = presenter._notebook_editor
        assert editor is not None
        assert editor.is_current_valid
        assert window.action_for_text("Save Notebook").isEnabled()
        window.action_for_text("Save Notebook").trigger()
        _wait_until(
            lambda: presenter._notebook_task_id is None
            and editor.notebook_id is not None
        )
        notebook_id = editor.notebook_id
        assert app.research_notebook_store.load(notebook_id).notebook_id == notebook_id

        window.action_for_text("Notebook Manager...").trigger()
        _wait_until(lambda: presenter._notebook_manager is not None)
        notebook_manager = presenter._notebook_manager
        window.action_for_text("Notebook Manager...").trigger()
        assert presenter._notebook_manager is notebook_manager
        _wait_until(
            lambda: bool(notebook_manager.summaries)
            and bool(notebook_manager.assignments)
            and presenter._notebook_task_id is None
            and not presenter._snapshot_task_ids
        )
        assert notebook_manager.assignments[0].snapshot_id == snapshot.snapshot_id
        assert notebook_manager.assignments[0].notebook_id is None
        assignment_entered = Event()
        release_assignment = Event()
        original_assign = (
            app.research_workspace_notebook_link_domain.assign_notebook
        )

        def blocked_assign(snapshot_id, assigned_notebook_id):
            assignment_entered.set()
            assert release_assignment.wait(5.0)
            return original_assign(snapshot_id, assigned_notebook_id)

        monkeypatch.setattr(
            app.research_workspace_notebook_link_domain,
            "assign_notebook",
            blocked_assign,
        )
        notebook_manager._assign.click()
        assert assignment_entered.wait(5.0)
        notebook_manager.close()
        qapp.processEvents()
        assert presenter._notebook_manager is None
        release_assignment.set()
        _wait_until(
            lambda: not presenter._snapshot_task_ids
            and presenter._notebook_task_id is None
            and app.research_workspace_snapshot_domain.load_snapshot(
                snapshot.snapshot_id
            ).notebook_id
            == notebook_id
        )
        assert presenter._assigned_notebook_id == notebook_id
        assert presenter._current_workspace_snapshot_id == snapshot.snapshot_id
        presenter._close_notebook_editor()
        assert window.action_for_text("Open Notebook").isEnabled()
        window.action_for_text("Open Notebook").trigger()
        _wait_until(
            lambda: presenter._notebook_editor is not None
            and presenter._notebook_editor.notebook_id == notebook_id
        )
        presenter._close_notebook_editor()

        monkeypatch.setattr(
            app.research_workspace_notebook_link_domain,
            "assign_notebook",
            original_assign,
        )
        window.action_for_text("Notebook Manager...").trigger()
        _wait_until(lambda: presenter._notebook_manager is not None)
        notebook_manager = presenter._notebook_manager
        _wait_until(
            lambda: bool(notebook_manager.summaries)
            and bool(notebook_manager.assignments)
            and presenter._notebook_task_id is None
            and not presenter._snapshot_task_ids
        )
        deletion_entered = Event()
        release_deletion = Event()
        original_delete = (
            app.research_workspace_notebook_link_domain
            .delete_notebook_with_reference_cleanup
        )

        def blocked_delete(deleted_notebook_id):
            deletion_entered.set()
            assert release_deletion.wait(5.0)
            return original_delete(deleted_notebook_id)

        monkeypatch.setattr(
            app.research_workspace_notebook_link_domain,
            "delete_notebook_with_reference_cleanup",
            blocked_delete,
        )
        notebook_manager._delete.click()
        assert deletion_entered.wait(5.0)
        notebook_manager.close()
        qapp.processEvents()
        assert presenter._notebook_manager is None
        release_deletion.set()
        _wait_until(
            lambda: presenter._notebook_task_id is None
            and app.research_workspace_snapshot_domain.load_snapshot(
                snapshot.snapshot_id
            ).notebook_id
            is None
        )
        assert all(
            summary.notebook_id != notebook_id
            for summary in app.research_notebook_store.list_summaries()
        )
        assert presenter._assigned_notebook_id is None
        assert presenter._current_workspace_snapshot_id == snapshot.snapshot_id
        assert not window.action_for_text("Open Notebook").isEnabled()
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
