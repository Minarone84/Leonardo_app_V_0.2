"""Offscreen, real Core/store regressions for both reviewed derivation routes."""
from contextlib import contextmanager

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from leonardo.core.core_runner import TaskResult
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.data_manager_test.test_xrepair_r03_reviewed_derivation import (
    _application, _edit, _inventory, _plain, _receipt, _setup,
)
from tests.gui_test.test_data_manager_recipe_artifact_materialization_vertical import _settle


def _rows(window):
    table = window._operation_surface.details
    return tuple((table.item(row, 0).text(), table.item(row, 1).text())
                 for row in range(table.rowCount()))


@contextmanager
def _gui(service):
    qapp = QApplication.instance() or QApplication([])
    with _application(service) as application:
        window = DataManagerSuiteWindow()
        presenter = DataManagerSuitePresenter(window, application)
        window.show()
        QApplication.processEvents()
        try:
            presenter.refresh()
            _settle(presenter)
            yield application, window, presenter
        finally:
            _settle(presenter)
            presenter.dispose()
            window.close()
            QApplication.processEvents()
    assert qapp is not None


def _open(window, presenter, service, environment, collection=False):
    inspection = service.inspect_study_environment(environment.environment_id)
    window.derive_recipes_requested.emit(inspection.environment)
    _settle(presenter)
    dialog = window.recipe_derivation_dialog()
    assert dialog is not None and dialog.isVisible()
    dialog.study_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    dialog.collection_checkbox.setChecked(collection)
    dialog.collection_name.setText("R03 reviewed Collection")
    assert dialog.preview_button.isEnabled()
    dialog.preview_button.click()
    _settle(presenter)
    assert dialog.create_button.isEnabled()
    return dialog


@pytest.mark.parametrize("collection", [False, True])
def test_reviewed_gui_sequence_requires_repreview(tmp_path, collection):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        dialog = _open(window, presenter, service, env, collection)
        reviewed = presenter._catalog_derivation_plan
        changed = _edit(store, env)
        before = _inventory(recipes.root_dir)
        dialog.create_button.click()
        _settle(presenter)
        after = _inventory(recipes.root_dir)
        rows = _rows(window)
        actual_recipes = service.scan_portable_recipes().recipes
        _receipt("actual_preview_edit_create", before=before, after=after,
            reviewed_hash=reviewed.environment_content_hash, changed_hash=changed.content_hash,
            rows=rows, recipes=[_plain(x) for x in actual_recipes], collection=collection)
        assert dict(rows)["State"] == "failed"
        assert "Preview again" in dict(rows)["Error message"]
        assert after == before
        assert presenter._catalog_derivation_plan is None
        assert not dialog.create_button.isEnabled()
        dialog.preview_button.click()
        _settle(presenter)
        assert presenter._catalog_derivation_plan.environment_content_hash == changed.content_hash
        dialog.create_button.click()
        _settle(presenter)
        assert dict(_rows(window))["State"] == "completed"
        saved = service.scan_portable_recipes().recipes
        assert len(saved) == 1
        assert recipes.load_recipe(saved[0].recipe_id).parameters["period"] == 5
        _receipt("explicit_repreview_success", rows=_rows(window), disk=_inventory(recipes.root_dir))


@pytest.mark.parametrize("collection", [False, True])
def test_unchanged_gui_preview_creates_and_reuses(tmp_path, collection):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        dialog = _open(window, presenter, service, env, collection)
        dialog.create_button.click()
        _settle(presenter)
        assert dict(_rows(window))["State"] == "completed"
        before = _inventory(recipes.root_dir)
        assert recipes.load_recipe((plan.recipes[0].recipe_id,)[0]).parameters["period"] == 3
        dialog.preview_button.click()
        _settle(presenter)
        dialog.create_button.click()
        _settle(presenter)
        after = _inventory(recipes.root_dir)
        _receipt("unchanged_twice", before=before, after=after, rows=_rows(window))
        assert dict(_rows(window))["State"] == "completed" and after == before
        # Success/reuse closes no healthy dialog and automatic refresh preserves the report.
        assert dialog.isVisible() and not dialog.create_button.isEnabled()
        dialog.close()
        QApplication.processEvents()
        assert not isValid(dialog) or not dialog.isVisible()


@pytest.mark.parametrize("fault", ["no_preview", "reselected", "foreign", "stale"])
def test_dialog_and_presenter_reject_stale_selection_and_foreign_preview(tmp_path, fault):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        dialog = _open(window, presenter, service, env)
        incoming = presenter._catalog_derivation_plan
        if fault == "no_preview":
            dialog.invalidate_preview("Preview again")
        elif fault == "reselected":
            dialog.study_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
            dialog.study_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        elif fault == "foreign":
            from tests.data_manager_test.test_portable_recipe_workflow import _save_environment
            foreign = _save_environment(store, environment_id="foreign", display_name="Foreign",
                entries=env.entries, market=env.created_from)
            incoming = service.plan_recipe_derivation(foreign.environment_id, roots)
        else:
            _edit(store, env)
            incoming = service.plan_recipe_derivation(env.environment_id, roots)
        assert not dialog.reviewed_plan_matches(incoming)
        presenter._catalog_derivation_plan = incoming
        before = _inventory(recipes.root_dir)
        # Deliver the unchanged signal payload even if the button is disabled: presenter must fence it.
        dialog.create_requested.emit(env.environment_id, roots, False, "", "")
        _settle(presenter)
        assert _inventory(recipes.root_dir) == before
        _receipt("dialog_gate", fault=fault, before=before, after=_inventory(recipes.root_dir))


def test_legacy_creation_action_carries_reviewed_hash_and_clears_failures(tmp_path, monkeypatch):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        payload = {"environment_id": env.environment_id, "environment_root_entry_ids": roots}
        observed = []
        original = app.submit_persist_recipe_derivation
        def submit(*args, **kwargs):
            observed.append(kwargs.get("expected_environment_content_hash"))
            return original(*args, **kwargs)
        monkeypatch.setattr(app, "submit_persist_recipe_derivation", submit)
        window.creation_action_requested.emit("persist_recipe_derivation", payload)
        assert observed == []
        window.creation_action_requested.emit("plan_recipe_derivation", payload)
        _settle(presenter)
        assert presenter._derivation_plan.environment_content_hash == plan.environment_content_hash
        window.creation_action_requested.emit("persist_recipe_derivation", {
            **payload, "environment_root_entry_ids": ("other",)})
        assert observed == []
        _edit(store, env)
        before = _inventory(recipes.root_dir)
        window.creation_action_requested.emit("persist_recipe_derivation", payload)
        _settle(presenter)
        assert observed == [plan.environment_content_hash]
        assert dict(_rows(window))["State"] == "failed"
        assert presenter._derivation_plan is None and _inventory(recipes.root_dir) == before
        window.creation_action_requested.emit("plan_recipe_derivation", payload)
        _settle(presenter)
        window.creation_action_requested.emit("persist_recipe_derivation", payload)
        _settle(presenter)
        assert dict(_rows(window))["State"] == "completed"
        # A failed new Preview cannot retain the previous successful held plan.
        store.delete(env.environment_id)
        window.creation_action_requested.emit("plan_recipe_derivation", payload)
        assert presenter._derivation_plan is None
        _settle(presenter)
        assert presenter._derivation_plan is None
        _receipt("legacy", forwarded=observed, rows=_rows(window), disk=_inventory(recipes.root_dir))


@pytest.mark.parametrize("retirement", ["closed", "replaced", "different_expected_environment"])
def test_retired_catalog_completion_preserves_new_dialog(tmp_path, retirement):
    service, store, recipes, env, roots, plan = _setup(tmp_path)
    with _gui(service) as (app, window, presenter):
        old = _open(window, presenter, service, env)
        expected_environment = env.environment_id
        if retirement == "closed":
            old.close()
        elif retirement == "replaced":
            old.close()
            _open(window, presenter, service, env)
        else:
            expected_environment = "foreign"
        current = window.recipe_derivation_dialog()
        held = presenter._catalog_derivation_plan
        held_dialog = getattr(current, "_reviewed_plan", None)
        presenter._settle_catalog_recipe_persistence(
            TaskResult("retired", "failed", error_type="DataManagerOperationError",
                       error_message="Preview again"), old, expected_environment)
        assert presenter._catalog_derivation_plan is held
        assert getattr(current, "_reviewed_plan", None) is held_dialog
        _receipt("late_completion", retirement=retirement,
                 preserved_plan_hash=held.environment_content_hash)
