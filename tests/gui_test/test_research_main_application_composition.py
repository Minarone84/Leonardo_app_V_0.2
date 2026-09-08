from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressBar

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
            "Open Assigned Notebook": False,
            "Notebook Manager...": True,
        }
        assert {
            action_text: window.action_for_text(action_text).isEnabled()
            for action_text in expected_action_state
        } == expected_action_state
        for removed_action in (
            "Create New Notebook",
            "Open Notebook",
            "Save Notebook",
            "Load Notebook",
        ):
            with pytest.raises(KeyError):
                window.action_for_text(removed_action)

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

        save_environment_action = window.action_for_text(
            "Save Study Environment..."
        )
        save_environment_quick = window.quick_button_for_action(
            "Save Study Environment..."
        )
        assert save_environment_action.isEnabled()
        save_environment_action.trigger()
        _wait_until(lambda: slot_id in presenter._environment_save_dialogs)
        cancelled_dialog = presenter._environment_save_dialogs[slot_id]
        environment_records = tuple(
            item
            for item in context.window_registry.list_windows()
            if item.window_id.startswith("research.environment_save")
        )
        assert tuple(
            (item.window_id, item.status) for item in environment_records
        ) == (("research.environment_save", "open"),)
        cancelled_dialog.reject()
        _wait_until(
            lambda: slot_id not in presenter._environment_save_dialogs
            and not presenter._setup_task_ids
            and save_environment_action.isEnabled()
        )
        assert save_environment_quick.isEnabled()
        save_environment_action.trigger()
        _wait_until(lambda: slot_id in presenter._environment_save_dialogs)
        closed_dialog = presenter._environment_save_dialogs[slot_id]
        assert closed_dialog is not cancelled_dialog
        environment_records = tuple(
            item
            for item in context.window_registry.list_windows()
            if item.window_id.startswith("research.environment_save")
        )
        assert tuple(
            (item.window_id, item.status) for item in environment_records
        ) == (("research.environment_save", "open"),)
        closed_dialog.close()
        _wait_until(
            lambda: slot_id not in presenter._environment_save_dialogs
            and not presenter._setup_task_ids
            and save_environment_action.isEnabled()
        )
        assert next(
            item
            for item in context.window_registry.list_windows()
            if item.window_id == "research.environment_save"
        ).status == "closed"

        second_slot_id, second_chart = presenter._create_restored_chart(market_id)
        second_chart.open_dataset(market_id)
        _wait_until(
            lambda: second_chart.session.dataset is not None
            and not second_chart.is_busy
        )
        second_chart.submit_study_calculation(
            StudyExecutionRequest("ema", {"period": 20})
        )
        _wait_until(
            lambda: len(second_chart.session.studies) == 1
            and not second_chart.is_busy
        )
        window.workspace.set_active_slot(second_slot_id)
        qapp.processEvents()
        assert presenter._active_presenter() is second_chart
        save_environment_action.trigger()
        _wait_until(
            lambda: second_slot_id in presenter._environment_save_dialogs
        )
        second_dialog = presenter._environment_save_dialogs[second_slot_id]
        assert second_dialog._source_chart.currentData().slot_id == second_slot_id
        environment_records = tuple(
            item
            for item in context.window_registry.list_windows()
            if item.window_id.startswith("research.environment_save")
        )
        assert tuple(
            (item.window_id, item.status) for item in environment_records
        ) == (("research.environment_save", "open"),)
        save_environment_action.trigger()
        assert (
            presenter._environment_save_dialogs[second_slot_id]
            is second_dialog
        )
        assert len(
            tuple(
                item
                for item in context.window_registry.list_windows()
                if item.window_id == "research.environment_save"
            )
        ) == 1
        second_dialog.close()
        _wait_until(
            lambda: second_slot_id not in presenter._environment_save_dialogs
        )
        assert next(
            item
            for item in context.window_registry.list_windows()
            if item.window_id == "research.environment_save"
        ).status == "closed"
        presenter._close_chart(second_slot_id)
        window.workspace.set_active_slot(slot_id)
        qapp.processEvents()
        assert presenter._active_presenter() is chart

        save_environment_action.trigger()
        _wait_until(lambda: slot_id in presenter._environment_save_dialogs)
        environment_dialog = presenter._environment_save_dialogs[slot_id]
        assert environment_dialog._source_chart.count() == 1
        environment_dialog._name.setText("Threshold Environment")
        assert environment_dialog.current_intent().slot_id == slot_id
        save_environment_action.trigger()
        assert presenter._environment_save_dialogs[slot_id] is environment_dialog
        environment_dialog._save.click()
        _wait_until(lambda: not presenter._setup_task_ids)
        environment_summary = app.research_study_setup_domain.list_environments()[0]

        save_environment_action.trigger()
        _wait_until(lambda: slot_id in presenter._environment_save_dialogs)
        rename_dialog = presenter._environment_save_dialogs[slot_id]
        rename_dialog._update.setChecked(True)
        assert (
            rename_dialog._existing.currentData()
            == environment_summary.environment_id
        )
        rename_dialog._name.setText("Renamed Threshold Environment")
        rename_dialog._save.click()
        _wait_until(lambda: not presenter._setup_task_ids)
        renamed_summaries = app.research_study_setup_domain.list_environments()
        assert len(renamed_summaries) == 1
        assert (
            renamed_summaries[0].environment_id
            == environment_summary.environment_id
        )
        assert renamed_summaries[0].display_name == "Renamed Threshold Environment"

        save_environment_action.trigger()
        _wait_until(lambda: slot_id in presenter._environment_save_dialogs)
        stale_dialog = presenter._environment_save_dialogs[slot_id]
        stale_dialog._name.setText("Stale Source Environment")
        stale_dialog._session_id = "stale_session"
        stale_dialog._save.click()
        assert stale_dialog.isVisible()
        assert "no longer ready" in stale_dialog._validation.text()
        assert not presenter._setup_task_ids
        stale_dialog.reject()
        _wait_until(lambda: slot_id not in presenter._environment_save_dialogs)

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
        apply_progress = environment_manager.findChild(
            QProgressBar,
            "research.environment_manager_dialog.progress.apply",
        )
        apply_status = environment_manager.findChild(
            QLabel,
            "research.environment_manager_dialog.label.apply_status",
        )
        assert environment_manager.apply_active
        assert environment_manager.isVisible()
        assert (apply_progress.minimum(), apply_progress.maximum()) == (
            0,
            len(environment.entries),
        )
        assert apply_progress.value() == 0
        assert apply_status.text() in {
            "Preparing Study Environment...",
            f"Applying Study 1 of {len(environment.entries)}: "
            f"{environment.entries[0].display_name}",
        }
        assert not environment_manager._list.isEnabled()
        assert not environment_manager._target.isEnabled()
        assert not environment_manager._apply.isEnabled()
        environment_manager.reject()
        assert environment_manager.isVisible()
        _wait_until(
            lambda: chart.session.study_count == study_count + 1
            and not chart.environment_apply_active
        )
        _wait_until(lambda: slot_id not in presenter._environment_managers)
        assert not environment_manager.isVisible()
        window.action_for_text("Load Study Environment...").trigger()
        _wait_until(
            lambda: slot_id in presenter._environment_managers
            and presenter._environment_managers[slot_id] is not environment_manager
            and not presenter._setup_task_ids
        )
        reopened_load_manager = presenter._environment_managers[slot_id]
        with pytest.raises(ValueError, match="mode must be 'load' or 'manage'"):
            presenter._open_environment_manager("invalid")

        _wait_until(lambda: not presenter._setup_task_ids)
        window.action_for_text("Manage Study Environments...").trigger()
        _wait_until(
            lambda: presenter._environment_manager_modes.get(slot_id) == "manage"
            and presenter._environment_managers[slot_id] is not reopened_load_manager
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

        assert presenter._current_workspace_snapshot_id is None
        assert presenter._assigned_notebook_id is None
        assert app.research_workspace_snapshot_domain.list_snapshots() == ()
        window.action_for_text("Notebook Manager...").trigger()
        _wait_until(
            lambda: presenter._notebook_manager is not None
            and presenter._notebook_task_id is None
            and not presenter._snapshot_task_ids
        )
        independent_notebook_manager = presenter._notebook_manager
        assert independent_notebook_manager.isVisible()
        assert independent_notebook_manager.assignments == ()
        independent_notebook_manager._create.click()
        qapp.processEvents()
        independent_editor = presenter._notebook_editor
        assert independent_editor is not None
        assert independent_editor.isVisible()
        assert presenter._notebook_manager is independent_notebook_manager
        independent_editor._name.setText("Independent Notebook")
        independent_editor._save.click()
        _wait_until(
            lambda: presenter._notebook_task_id is None
            and independent_editor.notebook_id is not None
            and any(
                summary.notebook_id == independent_editor.notebook_id
                for summary in independent_notebook_manager.summaries
            )
            and not presenter._snapshot_task_ids
        )
        notebook_id = independent_editor.notebook_id
        assert notebook_id is not None
        assert app.research_notebook_store.load(notebook_id).notebook_id == notebook_id
        assert presenter._current_workspace_snapshot_id is None
        assert presenter._assigned_notebook_id is None
        assert app.research_workspace_snapshot_domain.list_snapshots() == ()
        assert independent_notebook_manager.assignments == ()
        independent_editor._close.click()
        _wait_until(lambda: presenter._notebook_editor is None)
        notebook_row = next(
            index
            for index, summary in enumerate(independent_notebook_manager.summaries)
            if summary.notebook_id == notebook_id
        )
        independent_notebook_manager._list.item(notebook_row).setCheckState(
            Qt.CheckState.Checked
        )
        independent_notebook_manager._open.click()
        _wait_until(
            lambda: presenter._notebook_editor is not None
            and presenter._notebook_editor.notebook_id == notebook_id
        )
        qapp.processEvents()
        reopened_independent_editor = presenter._notebook_editor
        assert reopened_independent_editor is not independent_editor
        assert reopened_independent_editor.isVisible()
        assert presenter._notebook_manager is independent_notebook_manager
        assert independent_notebook_manager.isVisible()
        assert presenter._current_workspace_snapshot_id is None
        assert presenter._assigned_notebook_id is None
        presenter._close_notebook_editor()
        independent_notebook_manager.close()
        _wait_until(lambda: presenter._notebook_manager is None)

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

        window.action_for_text("Notebook Manager...").trigger()
        _wait_until(
            lambda: presenter._notebook_manager is not None
            and presenter._notebook_task_id is None
            and not presenter._snapshot_task_ids
        )
        post_save_notebook_manager = presenter._notebook_manager
        assert tuple(
            assignment.snapshot_id
            for assignment in post_save_notebook_manager.assignments
        ) == (snapshot.snapshot_id,)
        post_save_notebook_manager._create.click()
        post_save_editor = presenter._notebook_editor
        assert post_save_editor is not None
        assert post_save_editor.notebook_id is None
        post_save_draft = post_save_editor.current_draft()
        assert post_save_draft.display_name == "Untitled Notebook"
        assert tuple(page.market_id for page in post_save_draft.pages) == (
            snapshot.charts[0].market_id,
        )
        assert snapshot.notebook_id is None
        presenter._close_notebook_editor()
        post_save_notebook_manager.close()
        _wait_until(lambda: presenter._notebook_manager is None)

        window.action_for_text("Load Workspace...").trigger()
        _wait_until(
            lambda: presenter._snapshot_manager is not None
            and presenter._snapshot_manager_mode == "load"
        )
        load_manager = presenter._snapshot_manager
        window.action_for_text("Load Workspace...").trigger()
        assert presenter._snapshot_manager is load_manager
        _wait_until(lambda: not presenter._snapshot_task_ids)
        load_manager.snapshot_list.setCurrentRow(0)
        _wait_until(
            lambda: load_manager.snapshot is not None
            and load_manager.compatibility_report is not None
            and not presenter._snapshot_task_ids
        )
        load_manager.replace_radio.setChecked(True)
        _wait_until(
            lambda: load_manager.compatibility_report is not None
            and load_manager.compatibility_report.mode == "replace"
            and load_manager.compatibility_report.compatible
            and not presenter._snapshot_task_ids
        )
        load_manager.load_button.click()
        _wait_until(lambda: presenter._snapshot_preflight_dialog is not None)
        preflight = presenter._snapshot_preflight_dialog

        presenter._open_financial_tools(slot_id)
        _wait_until(
            lambda: slot_id in presenter._financial_tools_dialogs
            and slot_id not in presenter._active_study_setup_catalog_tasks
        )
        financial_tools = presenter._financial_tools_dialogs[slot_id]
        presenter._open_studies_manager(slot_id)
        studies_manager = presenter._studies_manager_dialogs[slot_id]
        presenter._open_go_to(slot_id)
        go_to = presenter._go_to_dialogs[slot_id]
        window.action_for_text("Notebook Manager...").trigger()
        _wait_until(lambda: presenter._notebook_manager is not None)
        old_notebook_manager = presenter._notebook_manager
        window.action_for_text("New Chart...").trigger()
        new_chart_dialog = presenter._new_chart_dialog

        assert financial_tools.isVisible()
        assert studies_manager.isVisible()
        assert go_to.isVisible()
        assert replacement_load_manager.isVisible()
        assert load_manager.isVisible()
        assert old_notebook_manager.isVisible()
        assert new_chart_dialog.isVisible()

        restore_load_entered = Event()
        release_restore_load = Event()
        loader = app.research_dataset_service._loader
        original_load = loader.load

        def blocked_restore_load(market_id, *, progress=None, cancellation_requested=None):
            if progress is not None:
                progress(1, 2)
            restore_load_entered.set()
            assert release_restore_load.wait(5.0)
            return original_load(
                market_id,
                progress=progress,
                cancellation_requested=cancellation_requested,
            )

        monkeypatch.setattr(loader, "load", blocked_restore_load)
        preflight.load_button.click()
        assert restore_load_entered.wait(5.0)
        qapp.processEvents()
        assert presenter._snapshot_preflight_dialog is preflight
        assert preflight.isVisible()
        assert preflight.restore_active
        assert preflight.progress.value() == 0
        assert preflight.current_progress.maximum() == 2
        assert preflight.current_progress.value() == 1
        release_restore_load.set()
        _wait_until(
            lambda: presenter._snapshot_restore is None
            and presenter._snapshot_preflight_dialog is None
        )
        assert preflight.progress.value() == len(snapshot.charts)
        assert preflight.restore_status.text() == "Workspace restored."
        assert not preflight.isVisible()
        assert presenter._snapshot_manager is None
        assert not load_manager.isVisible()
        assert not financial_tools.isVisible()
        assert not studies_manager.isVisible()
        assert not go_to.isVisible()
        assert not replacement_load_manager.isVisible()
        assert presenter._notebook_manager is None
        assert not old_notebook_manager.isVisible()
        assert presenter._new_chart_dialog is new_chart_dialog
        assert not new_chart_dialog.isVisible()
        assert presenter._financial_tools_dialogs == {}
        assert presenter._studies_manager_dialogs == {}
        assert presenter._go_to_dialogs == {}
        assert presenter._environment_managers == {}
        assert presenter._environment_manager_modes == {}
        assert presenter._workspace_state.chart_count == len(snapshot.charts)
        restored_slot = presenter._workspace_state.active_slot_id
        assert restored_slot is not None
        restored_chart = presenter._chart_presenters[restored_slot]
        assert restored_chart.session.selected_market_id == snapshot.charts[0].market_id
        assert restored_chart.session.study_count == len(
            snapshot.charts[0].study_environment.entries
        )
        assert presenter._current_workspace_snapshot_id == snapshot.snapshot_id
        window.action_for_text("Manage Workspaces...").trigger()
        _wait_until(
            lambda: presenter._snapshot_manager is not None
            and presenter._snapshot_manager_mode == "manage"
        )
        assert presenter._snapshot_manager is not load_manager

        window.action_for_text("Notebook Manager...").trigger()
        _wait_until(lambda: presenter._notebook_manager is not None)
        notebook_manager = presenter._notebook_manager
        _wait_until(
            lambda: any(
                summary.notebook_id == notebook_id
                for summary in notebook_manager.summaries
            )
            and presenter._notebook_task_id is None
            and not presenter._snapshot_task_ids
        )
        notebook_row = next(
            index
            for index, summary in enumerate(notebook_manager.summaries)
            if summary.notebook_id == notebook_id
        )
        notebook_manager._list.item(notebook_row).setCheckState(
            Qt.CheckState.Checked
        )
        notebook_manager._open.click()
        _wait_until(
            lambda: presenter._notebook_editor is not None
            and presenter._notebook_editor.notebook_id == notebook_id
        )
        editor = presenter._notebook_editor
        assert editor.isVisible()

        window.action_for_text("Notebook Manager...").trigger()
        assert presenter._notebook_manager is notebook_manager
        _wait_until(
            lambda: bool(notebook_manager.summaries)
            and bool(notebook_manager.assignments)
            and presenter._notebook_task_id is None
            and not presenter._snapshot_task_ids
        )
        presenter._close_notebook_editor()
        notebook_manager._open.click()
        _wait_until(
            lambda: presenter._notebook_editor is not None
            and presenter._notebook_editor.notebook_id == notebook_id
        )
        assert presenter._notebook_manager is notebook_manager
        presenter._close_notebook_editor()
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
        notebook_manager._assignment_table.setCurrentCell(0, 0)
        assert notebook_manager._selected_notebook.text() == "Independent Notebook"
        assert notebook_manager._target_workspace.text() == "Threshold Workspace"
        assert notebook_manager._current_assignment.text() == "Unassigned"
        assert notebook_manager._assignment_action.text() == "Assign Notebook"
        notebook_manager._assignment_action.click()
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
        assert window.action_for_text("Open Assigned Notebook").isEnabled()
        window.action_for_text("Open Assigned Notebook").trigger()
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
        notebook_row = next(
            index
            for index, summary in enumerate(notebook_manager.summaries)
            if summary.notebook_id == notebook_id
        )
        notebook_manager._list.item(notebook_row).setCheckState(
            Qt.CheckState.Checked
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
        assert not window.action_for_text("Open Assigned Notebook").isEnabled()
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
