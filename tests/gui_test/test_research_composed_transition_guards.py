from __future__ import annotations

from dataclasses import replace
from threading import Event

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from PySide6.QtWidgets import QMessageBox

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.research import StudyExecutionRequest
from leonardo.gui.windows.workspace_snapshot_preflight_dialog import WorkspaceSnapshotPreflightDialog
from tests.gui_test.test_research_single_chart_integration import (
    _open_restored_chart, _wait_until, _write_accepted_dataset,
)
from tests.gui_test.test_research_gui_service_workspace_lifecycle import _restore_dialog


@pytest.fixture
def composed(tmp_path):
    qapp = QApplication.instance() or QApplication([])
    quit_on_close = qapp.quitOnLastWindowClosed()
    qapp.setQuitOnLastWindowClosed(False)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir, rows=80)
    app = LeonardoApp(config)
    context = app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(context)
    main = composition.create_main_window()
    main.show()
    main.action_for_id("main_window.open_research_suite").trigger()
    window = composition.research_suite_window
    presenter = composition.research_suite_presenter
    _wait_until(lambda: presenter._active_catalog_task_id is None)
    try:
        yield qapp, app, composition, main, window, presenter
    finally:
        current = composition.research_suite_presenter
        if current is not None:
            current.dispose()
        main.close()
        app.shutdown()
        qapp.processEvents()
        qapp.setQuitOnLastWindowClosed(quit_on_close)


def _dirty(presenter, monkeypatch, decision):
    presenter._new_notebook()
    editor = presenter._notebook_editor
    editor._name.setText("Unsaved research")
    assert editor.is_dirty
    decisions = []
    monkeypatch.setattr(editor, "dirty_decision", lambda: decisions.append(decision) or decision)
    return editor, decisions


def _assert_tracked_owners(app, *, suite="open", main="open"):
    windows = {item.window_id: item for item in app.window_registry.list_windows()}
    for identity, expected in (("research_suite.window", suite), ("main_window.window", main)):
        tracked = windows[identity]
        assert tracked.status == expected
        assert (tracked.closed_at_utc is None) == (expected == "open")


@pytest.mark.parametrize("target", ["suite", "main", "exit"])
@pytest.mark.parametrize("saved", [False, True])
def test_dirty_cancel_preserves_composed_owners(composed, monkeypatch, target, saved):
    _, app, composition, main, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    main.action_for_id("main_window.open_analysis_suite").trigger()
    other = composition._analysis_suite_window
    editor, decisions = _dirty(presenter, monkeypatch, "cancel")
    if saved:
        presenter._save_notebook_editor(False)
        _wait_until(lambda: not presenter._notebook_save_pending)
        editor._description.setText("unsaved change to an existing Notebook")
    if target == "exit":
        main.action_for_id("main_window.exit").trigger()
    else:
        (window if target == "suite" else main).close()
    assert decisions == ["cancel"]
    assert composition.research_suite_presenter is presenter
    assert presenter._notebook_editor is editor and editor.is_dirty
    assert presenter._chart_presenters[slot] is chart
    assert main.isVisible() and window.isVisible() and other.isVisible()
    _assert_tracked_owners(app)


@pytest.mark.parametrize("mode", ["replace", "append"])
def test_dirty_cancel_precedes_workspace_mutation(composed, monkeypatch, mode):
    _, _, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    assert snapshot is not None
    _open_restored_chart(window, presenter)
    before = dict(presenter._chart_presenters)
    editor, decisions = _dirty(presenter, monkeypatch, "cancel")
    dialog, _ = _restore_dialog(window, presenter, snapshot, mode)
    assert decisions == ["cancel"]
    assert presenter._chart_presenters == before
    assert presenter._snapshot_restore is None
    assert presenter._notebook_editor is editor and editor.is_dirty
    assert presenter._current_workspace_snapshot_id is None
    assert not dialog.restore_active and dialog.cancel_button.isEnabled()


def test_new_selector_requests_a_current_catalog(composed):
    _, _, _, _, _, presenter = composed
    presenter.open_new_chart()
    assert presenter._active_catalog_task_id is not None
    assert not presenter._new_chart_dialog.isVisible()
    _wait_until(lambda: presenter._new_chart_dialog.isVisible())
    assert len(presenter._new_chart_dialog._dataset_summaries) == 1


def test_catalog_source_changes_preserve_existing_chart_and_study(composed):
    _, _, _, _, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    chart.submit_study_calculation(StudyExecutionRequest("sma", {"period": 3}))
    _wait_until(lambda: chart.session.study_count == 1 and not chart.is_busy)
    dataset, study = chart.session.dataset, chart.session.studies[0]
    source = dataset.csv_path
    content = source.read_bytes()
    source.unlink()
    presenter.open_new_chart()
    _wait_until(presenter._new_chart_dialog.isVisible)
    assert presenter._new_chart_dialog._dataset_summaries == ()
    presenter._new_chart_dialog.reject()
    source.write_bytes(content)
    presenter.open_new_chart()
    _wait_until(presenter._new_chart_dialog.isVisible)
    assert len(presenter._new_chart_dialog._dataset_summaries) == 1
    assert chart.session.dataset is dataset and chart.session.studies[0] is study


@pytest.mark.parametrize("fail_save", [False, True])
def test_fenced_save_keeps_truthful_result_after_qt_owner_deletion(
    composed, monkeypatch, caplog, fail_save,
):
    _, app, composition, main, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    chart.submit_study_calculation(StudyExecutionRequest("sma", {"period": 3}))
    _wait_until(lambda: chart.session.study_count == 1 and not chart.is_busy)
    market = chart.session.dataset.market_id
    entered, release = Event(), Event()
    original = app.artifact_service.save_calculation

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(10), "test save gate timed out"
        if fail_save:
            raise OSError("injected real save failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(app.artifact_service, "save_calculation", delayed)
    try:
        chart.save_study(chart.session.studies[0].study_id)
        _wait_until(entered.is_set)
        task_id = next(t.task_id for t in app.task_manager.snapshots()
                       if t.metadata.get("operation") == "research_study_save")
        window.close()
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()
        assert not isValid(presenter)
        _assert_tracked_owners(app, suite="closed")
        main.action_for_id("main_window.open_research_suite").trigger()
        fresh = composition.research_suite_presenter
        assert fresh is not presenter
        _assert_tracked_owners(app)
        release.set()
        task = lambda: next(t for t in app.task_manager.snapshots() if t.task_id == task_id)
        _wait_until(lambda: task().status in {"completed", "failed", "cancelled"})
        assert task().status == ("failed" if fail_save else "completed")
        _wait_until(lambda: fresh._active_catalog_task_id is None)
        assert len(app.artifact_service.list_managed_artifacts(market)) == (0 if fail_save else 1)
        assert fresh._workspace_state.chart_count == 0
        assert "Signal source has been deleted" not in caplog.text
        assert "Exception in callback" not in caplog.text
    finally:
        release.set()


def _close_target(target, main, window, editor):
    {"main": main, "suite": window, "editor": editor}[target].close()


@pytest.mark.parametrize("target", ["suite", "main"])
def test_clean_close_and_reopen_agree_with_canonical_tracking(composed, target):
    _, app, composition, main, window, presenter = composed
    (window if target == "suite" else main).close()
    _assert_tracked_owners(app, suite="closed", main="closed" if target == "main" else "open")
    loop = QEventLoop()
    QTimer.singleShot(30, loop.quit)
    loop.exec()
    assert not isValid(presenter)
    main.show()
    main.action_for_id("main_window.open_research_suite").trigger()
    fresh = composition.research_suite_presenter
    _wait_until(lambda: fresh._active_catalog_task_id is None)
    assert fresh is not presenter
    assert composition.research_suite_window.isVisible()
    _assert_tracked_owners(app)


@pytest.mark.parametrize("target", ["editor", "suite", "main"])
@pytest.mark.parametrize("decision", ["save", "discard"])
@pytest.mark.parametrize("saved", [False, True])
def test_dirty_close_saves_or_discards_once(composed, monkeypatch, target, decision, saved):
    _, app, composition, main, window, presenter = composed
    editor, decisions = _dirty(presenter, monkeypatch, decision)
    if saved:
        presenter._save_notebook_editor(False)
        _wait_until(lambda: editor.notebook_id is not None and not presenter._notebook_save_pending)
        editor._description.setText("new unsaved description")
    before = app.research_notebook_domain.list_notebooks()
    accepted = []
    window.closed.connect(lambda: accepted.append(True))
    _close_target(target, main, window, editor)
    _wait_until(lambda: presenter._notebook_editor is None)
    assert decisions == [decision]
    assert len(accepted) == (0 if target == "editor" else 1)
    after = app.research_notebook_domain.list_notebooks()
    assert len(after) == (1 if saved or decision == "save" else 0)
    if saved:
        notebook = app.research_notebook_domain.load_notebook(before[0].notebook_id)
        assert notebook.description == ("new unsaved description" if decision == "save" else "")
    assert (composition.research_suite_presenter is presenter) == (target == "editor")
    _assert_tracked_owners(
        app, suite="open" if target == "editor" else "closed",
        main="closed" if target == "main" else "open",
    )


@pytest.mark.parametrize("target", ["editor", "suite", "main"])
@pytest.mark.parametrize("failure", ["invalid", "submission", "save"])
def test_close_save_failure_keeps_editor_and_workspace(composed, monkeypatch, target, failure):
    _, app, composition, main, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    editor, decisions = _dirty(presenter, monkeypatch, "save")

    def broken(*args, **kwargs):
        raise OSError("injected Notebook failure")

    if failure == "invalid":
        editor._name.setText("")
    elif failure == "submission":
        monkeypatch.setattr(presenter._notebook_service, "submit_create_notebook", broken)
    else:
        monkeypatch.setattr(app.research_notebook_domain, "create_notebook", broken)
    _close_target(target, main, window, editor)
    _wait_until(lambda: not presenter._notebook_save_pending)
    assert decisions == ["save"]
    assert presenter._notebook_editor is editor and editor.is_dirty
    assert presenter._chart_presenters[slot] is chart
    assert composition.research_suite_presenter is presenter
    assert window.isVisible() and main.isVisible()
    _assert_tracked_owners(app)
    assert "blocked" in editor._status.text() or "failed" in editor._status.text()
    assert app.research_notebook_domain.list_notebooks() == ()


@pytest.mark.parametrize("target", ["editor", "suite", "main"])
@pytest.mark.parametrize("already_saving", [False, True])
def test_pending_save_retains_one_close_and_rejects_conflicting_transition(
    composed, monkeypatch, target, already_saving,
):
    _, app, composition, main, window, presenter = composed
    editor, decisions = _dirty(presenter, monkeypatch, "save")
    entered, release = Event(), Event()
    original = app.research_notebook_domain.create_notebook
    calls = []

    def held(draft):
        calls.append(draft)
        entered.set()
        assert release.wait(10)
        return original(draft)

    monkeypatch.setattr(app.research_notebook_domain, "create_notebook", held)
    try:
        if already_saving:
            presenter._save_notebook_editor(False)
        _close_target(target, main, window, editor)
        _wait_until(entered.is_set)
        _close_target(target, main, window, editor)
        pending = presenter._notebook_pending_action
        presenter._new_notebook()
        assert presenter._notebook_pending_action == pending
        assert presenter._notebook_editor is editor
        _assert_tracked_owners(app)
        assert "transition is already pending" in window._activity_log.toPlainText()
        assert decisions == ([] if already_saving else ["save"])
        release.set()
        _wait_until(lambda: presenter._notebook_editor is None)
        assert len(calls) == 1
        assert len(app.research_notebook_domain.list_notebooks()) == 1
        _assert_tracked_owners(
            app, suite="open" if target == "editor" else "closed",
            main="closed" if target == "main" else "open",
        )
    finally:
        release.set()


def _review_snapshot(app, window, presenter, snapshot, mode):
    report = app.research_workspace_snapshot_domain.preflight(
        snapshot, mode,
        {"occupied_positions": window.workspace.shell_state.reserved_positions(), "idle": True},
    )
    assert report.compatible, report
    dialog = WorkspaceSnapshotPreflightDialog(report, window)
    presenter._snapshot_preflight_dialog = dialog
    dialog.load_requested.connect(lambda _: presenter._restore_snapshot_workspace(snapshot, report))
    dialog.finished.connect(lambda _: presenter._forget_snapshot_preflight(dialog))
    dialog.show()
    return dialog, report


@pytest.mark.parametrize("mode", ["replace", "append"])
@pytest.mark.parametrize("manager_open", [False, True])
def test_saved_restore_loads_target_without_competing_manager_refresh(
    composed, monkeypatch, mode, manager_open,
):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    target = app.research_notebook_domain.create_notebook(
        app.research_notebook_domain.build_draft(display_name="Target Notebook"))
    domain = app.research_workspace_snapshot_domain
    snapshot = domain.create_snapshot(domain.build_draft(
        presenter._capture_snapshot_workspace(), display_name="Target Workspace"))
    snapshot = app.research_workspace_notebook_link_domain.assign_notebook(
        snapshot.snapshot_id, target.notebook_id)
    if manager_open:
        presenter._open_notebook_manager()
        _wait_until(lambda: presenter._notebook_manager is not None
                    and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    _, decisions = _dirty(presenter, monkeypatch, "save")
    dialog, _ = _review_snapshot(app, window, presenter, snapshot, mode)
    entered, release = Event(), Event()
    original = app.research_notebook_domain.list_notebooks

    def held_list():
        entered.set()
        assert release.wait(10)
        return original()

    if manager_open:
        monkeypatch.setattr(app.research_notebook_domain, "list_notebooks", held_list)
    try:
        dialog.load_button.click()
        _wait_until(lambda: presenter._current_workspace_snapshot_id == snapshot.snapshot_id
                    and presenter._snapshot_restore is None)
        assert not entered.is_set(), "Manager refresh competed with the restore continuation"
    finally:
        release.set()
    _wait_until(lambda: not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    assert decisions == ["save"]
    assert len(original()) == 2
    assert presenter._assigned_notebook_id == domain.load_snapshot(snapshot.snapshot_id).notebook_id == target.notebook_id
    assert presenter._notebook_editor is not None
    assert presenter._notebook_editor.notebook_id == target.notebook_id


@pytest.mark.parametrize("failure", ["cancel", "incompatible", "preflight", "submission", "restore", "rollback"])
def test_saved_restore_refreshes_surviving_manager_after_settling(composed, monkeypatch, failure):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    manager = presenter._notebook_manager
    editor, _ = _dirty(presenter, monkeypatch, "save")
    dialog, _ = _review_snapshot(app, window, presenter, snapshot, "replace")
    original = app.research_workspace_snapshot_domain.preflight
    entered, release = Event(), Event()

    def checked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        if failure == "preflight":
            raise OSError("injected preflight failure")
        result = original(*args, **kwargs)
        return replace(result, compatible=False) if failure == "incompatible" else result

    def broken(*args, **kwargs):
        raise OSError("injected submission failure")

    if failure == "submission":
        monkeypatch.setattr(presenter._snapshot_service, "submit_preflight", broken)
    else:
        monkeypatch.setattr(app.research_workspace_snapshot_domain, "preflight", checked)
    if failure in {"restore", "rollback"}:
        load = presenter._service.submit_load
        calls = []

        def fail_load(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1 or failure == "rollback":
                raise OSError("injected restore failure")
            return load(*args, **kwargs)

        monkeypatch.setattr(presenter._service, "submit_load", fail_load)
    try:
        dialog.load_button.click()
        if failure != "submission":
            _wait_until(entered.is_set)
        if failure == "cancel":
            dialog.reject()
    finally:
        release.set()
    _wait_until(lambda: not presenter._notebook_save_pending and not presenter._notebook_task_id
                and not presenter._snapshot_task_ids and presenter._snapshot_restore is None)
    assert presenter._notebook_editor is editor and not editor.is_dirty
    assert presenter._notebook_manager is manager
    assert [item.notebook_id for item in manager.summaries] == [editor.notebook_id]
    assert presenter._notebook_manager_refresh_after_restore is None
    assert manager._refresh.isEnabled()


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("accepted", [False, True])
def test_clear_retires_only_accepted_selector_intent(composed, monkeypatch, pending, accepted):
    _, _, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    original = presenter._service.submit_catalog
    results = []

    def hold_delivery(**kwargs):
        callback = kwargs["result_callback"]
        kwargs["result_callback"] = lambda result: results.append((callback, result))
        return original(**kwargs)

    monkeypatch.setattr(presenter._service, "submit_catalog", hold_delivery)
    presenter.open_new_chart()
    _wait_until(lambda: bool(results))
    callback, result = results.pop()
    if not pending:
        callback(result)
        assert presenter._new_chart_dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs:
                        QMessageBox.StandardButton.Yes if accepted else QMessageBox.StandardButton.No)
    window.action_for_text("Clear Research Suite").trigger()
    if pending:
        callback(result)
    assert window.workspace.chart_count() == (0 if accepted else 1)
    assert presenter._new_chart_dialog.isVisible() is not accepted
    if accepted:
        presenter.open_new_chart()
        _wait_until(lambda: bool(results))
        callback, result = results.pop()
        callback(result)
        assert presenter._new_chart_dialog.isVisible()


def test_successful_restore_retires_pending_selector_intent(composed, monkeypatch):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    results = []
    original = presenter._service.submit_catalog

    def hold_delivery(**kwargs):
        callback = kwargs["result_callback"]
        kwargs["result_callback"] = lambda result: results.append((callback, result))
        return original(**kwargs)

    monkeypatch.setattr(presenter._service, "submit_catalog", hold_delivery)
    presenter.open_new_chart()
    _wait_until(lambda: bool(results))
    dialog, _ = _review_snapshot(app, window, presenter, snapshot, "replace")
    dialog.load_button.click()
    _wait_until(lambda: presenter._snapshot_restore is None)
    callback, result = results.pop()
    callback(result)
    assert not presenter._new_chart_dialog.isVisible()


@pytest.mark.parametrize("mode", ["replace", "append"])
@pytest.mark.parametrize("decision", ["save", "discard"])
@pytest.mark.parametrize("fail_restore", [False, True])
def test_reviewed_restore_resolves_notebook_once_and_preserves_buffer_on_failure(
    composed, monkeypatch, mode, decision, fail_restore,
):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    _open_restored_chart(window, presenter)
    before = dict(presenter._chart_presenters)
    editor, decisions = _dirty(presenter, monkeypatch, decision)
    dialog, report = _review_snapshot(app, window, presenter, snapshot, mode)
    if fail_restore:
        original = presenter._service.submit_load
        calls = []

        def fail_once(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise OSError("injected restore failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(presenter._service, "submit_load", fail_once)
    dialog.load_button.click()
    _wait_until(lambda: not presenter._notebook_save_pending
                and not presenter._snapshot_task_ids and presenter._snapshot_restore is None)
    assert decisions == [decision]
    assert len(app.research_notebook_domain.list_notebooks()) == (1 if decision == "save" else 0)
    if fail_restore:
        assert presenter._notebook_editor is editor
        assert editor.isEnabled()
        assert editor.is_dirty == (decision == "discard")
        assert window.workspace.chart_count() == 2
        if mode == "append":
            assert presenter._chart_presenters == before
        assert presenter._current_workspace_snapshot_id is None
        assert "injected restore failure" in dialog.restore_status.text()
    else:
        assert presenter._notebook_editor is None
        assert window.workspace.chart_count() == (1 if mode == "replace" else 3)
        assert presenter._current_workspace_snapshot_id == snapshot.snapshot_id


@pytest.mark.parametrize("mode", ["replace", "append"])
def test_same_notebook_restore_preserves_dirty_editor_without_prompt(composed, monkeypatch, mode):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    editor, decisions = _dirty(presenter, monkeypatch, "cancel")
    presenter._save_notebook_editor(False)
    _wait_until(lambda: not presenter._notebook_save_pending)
    editor._description.setText("keep this unsaved buffer")
    snapshot = replace(presenter._capture_rollback_snapshot(), notebook_id=editor.notebook_id)
    dialog, report = _review_snapshot(app, window, presenter, snapshot, mode)
    dialog.load_button.click()
    _wait_until(lambda: presenter._snapshot_restore is None)
    assert decisions == []
    assert presenter._notebook_editor is editor and editor.is_dirty
    assert editor._description.text() == "keep this unsaved buffer"


@pytest.mark.parametrize("stale", ["dialog", "incompatible", "dirty_again", "workspace"])
def test_saved_restore_rechecks_current_intent_before_teardown(composed, monkeypatch, stale):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    editor, decisions = _dirty(presenter, monkeypatch, "save")
    dialog, report = _review_snapshot(app, window, presenter, snapshot, "replace")
    before = dict(presenter._chart_presenters)
    original = app.research_workspace_snapshot_domain.preflight
    entered, release = Event(), Event()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        result = original(*args, **kwargs)
        return replace(result, compatible=False) if stale == "incompatible" else result

    monkeypatch.setattr(app.research_workspace_snapshot_domain, "preflight", held)
    try:
        dialog.load_button.click()
        _wait_until(entered.is_set)
        presenter._restore_snapshot_workspace(snapshot, report)
        assert decisions == ["save"]
        if stale == "dialog":
            dialog.reject()
        elif stale == "dirty_again":
            editor._description.setText("new edit after save")
        elif stale == "workspace":
            _open_restored_chart(window, presenter)
            before = dict(presenter._chart_presenters)
        release.set()
        _wait_until(lambda: not presenter._snapshot_task_ids)
        assert presenter._chart_presenters == before
        assert presenter._notebook_editor is editor
        assert presenter._current_workspace_snapshot_id is None
        assert len(app.research_notebook_domain.list_notebooks()) == 1
        assert "no longer current" in window._activity_log.toPlainText() or "compatibility changed" in window._activity_log.toPlainText()
    finally:
        release.set()


@pytest.mark.parametrize("mode", ["replace", "append"])
@pytest.mark.parametrize("invalid", [False, True])
def test_restore_save_failure_never_tears_down_workspace(composed, monkeypatch, mode, invalid):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    before = dict(presenter._chart_presenters)
    editor, decisions = _dirty(presenter, monkeypatch, "save")
    if invalid:
        editor._name.setText("")
    else:
        def broken(draft):
            raise OSError("injected save failure before restore")
        monkeypatch.setattr(app.research_notebook_domain, "create_notebook", broken)
    dialog, report = _review_snapshot(app, window, presenter, snapshot, mode)
    dialog.load_button.click()
    _wait_until(lambda: not presenter._notebook_save_pending)
    assert decisions == ["save"]
    assert presenter._chart_presenters == before
    assert presenter._notebook_editor is editor and editor.is_dirty
    assert presenter._snapshot_restore is None
    assert not dialog.restore_active and dialog.cancel_button.isEnabled()


def test_other_notebook_task_blocks_close_without_releasing_ownership(composed, monkeypatch):
    _, app, composition, main, window, presenter = composed
    editor, decisions = _dirty(presenter, monkeypatch, "discard")
    entered, release = Event(), Event()
    original = app.research_notebook_domain.list_notebooks

    def held():
        entered.set()
        assert release.wait(10)
        return original()

    monkeypatch.setattr(app.research_notebook_domain, "list_notebooks", held)
    try:
        presenter._open_notebook_manager()
        _wait_until(entered.is_set)
        main.close()
        assert composition.research_suite_presenter is presenter
        assert presenter._notebook_editor is editor and editor.is_dirty
        assert main.isVisible() and window.isVisible()
        assert decisions == []
        assert "Notebook operation is already in progress" in window._activity_log.toPlainText()
    finally:
        release.set()
        _wait_until(lambda: presenter._notebook_task_id is None)


@pytest.mark.parametrize("target", ["editor", "suite", "main"])
def test_save_close_with_open_manager_preserves_refresh_and_continuation(composed, monkeypatch, target):
    _, app, composition, main, window, presenter = composed
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    manager = presenter._notebook_manager
    editor, decisions = _dirty(presenter, monkeypatch, "save")
    _close_target(target, main, window, editor)
    _wait_until(lambda: presenter._notebook_editor is None)
    assert decisions == ["save"]
    assert len(app.research_notebook_domain.list_notebooks()) == 1
    if target == "editor":
        _wait_until(lambda: len(manager.summaries) == 1)
        assert presenter._notebook_manager is manager and manager.isVisible()
    else:
        assert composition.research_suite_presenter is None


@pytest.mark.parametrize("mode", ["replace", "append"])
@pytest.mark.parametrize("phase", ["preflight", "restore"])
def test_manager_refresh_cannot_take_saved_restore_notebook_slot(composed, monkeypatch, mode, phase):
    qapp, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    target = app.research_notebook_domain.create_notebook(
        app.research_notebook_domain.build_draft(display_name="Assigned target"))
    domain = app.research_workspace_snapshot_domain
    snapshot = domain.create_snapshot(domain.build_draft(
        presenter._capture_snapshot_workspace(), display_name="Assigned workspace"))
    snapshot = app.research_workspace_notebook_link_domain.assign_notebook(
        snapshot.snapshot_id, target.notebook_id)
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    manager = presenter._notebook_manager
    _, decisions = _dirty(presenter, monkeypatch, "save")
    dialog, _ = _review_snapshot(app, window, presenter, snapshot, mode)
    entered, release = Event(), Event()
    preflight = domain.preflight
    completed = presenter._snapshot_dataset_complete
    outcomes, listings = [], []
    listing = app.research_notebook_domain.list_notebooks

    def held_preflight(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return preflight(*args, **kwargs)

    def counted_list():
        listings.append(True)
        return listing()

    if phase == "preflight":
        monkeypatch.setattr(domain, "preflight", held_preflight)
    else:
        monkeypatch.setattr(presenter, "_snapshot_dataset_complete", lambda *args: outcomes.append(args))
    monkeypatch.setattr(app.research_notebook_domain, "list_notebooks", counted_list)
    try:
        dialog.load_button.click()
        _wait_until(entered.is_set if phase == "preflight" else lambda: bool(outcomes))
        assert not manager._refresh.isEnabled() and not manager._create.isEnabled()
        manager._refresh.click()
        manager.refresh_requested.emit()  # Admission must also reject a queued signal.
        presenter._open_notebook_manager()
        qapp.processEvents()
        assert presenter._notebook_task_id is None and listings == []
        release.set()
        if phase == "restore":
            completed(*outcomes.pop())
        _wait_until(lambda: presenter._snapshot_restore is None
                    and not presenter._snapshot_task_ids and not presenter._notebook_task_id)
    finally:
        release.set()
    assert decisions == ["save"] and listings == []
    assert len(listing()) == 2
    assert presenter._notebook_editor.notebook_id == target.notebook_id
    assert presenter._assigned_notebook_id == domain.load_snapshot(snapshot.snapshot_id).notebook_id == target.notebook_id
    assert presenter._notebook_manager is None
    assert presenter._notebook_manager_refresh_after_restore is None


@pytest.mark.parametrize("refused", [False, True])
def test_closed_manager_is_not_refreshed_or_reopened_by_restore(composed, monkeypatch, refused):
    _, app, _, _, window, presenter = composed
    _open_restored_chart(window, presenter)
    snapshot = presenter._capture_rollback_snapshot()
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    manager = presenter._notebook_manager
    _dirty(presenter, monkeypatch, "save")
    dialog, _ = _review_snapshot(app, window, presenter, snapshot, "replace")
    entered, release = Event(), Event()
    preflight = app.research_workspace_snapshot_domain.preflight
    listing = app.research_notebook_domain.list_notebooks
    calls = []

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        result = preflight(*args, **kwargs)
        return replace(result, compatible=False) if refused else result

    def counted():
        calls.append(True)
        return listing()

    monkeypatch.setattr(app.research_workspace_snapshot_domain, "preflight", held)
    monkeypatch.setattr(app.research_notebook_domain, "list_notebooks", counted)
    try:
        dialog.load_button.click()
        _wait_until(entered.is_set)
        manager.refresh_requested.emit()
        manager.reject()
        assert presenter._notebook_manager is None
        presenter._refresh_notebook_manager(manager)
        presenter._open_notebook_manager()
        assert presenter._notebook_task_id is None and calls == []
    finally:
        release.set()
    _wait_until(lambda: not presenter._snapshot_task_ids and presenter._snapshot_restore is None)
    assert presenter._notebook_manager is None and calls == []
    assert presenter._notebook_manager_refresh_after_restore is None
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    replacement = presenter._notebook_manager
    assert replacement is not manager and replacement._refresh.isEnabled()
    presenter._refresh_notebook_manager(manager)
    assert calls == [True] and presenter._notebook_task_id is None


@pytest.mark.parametrize("manager_open", [False, True])
@pytest.mark.parametrize("decision", ["save", "discard", "cancel"])
def test_clear_with_notebook_manager_preserves_saved_objects(composed, monkeypatch, manager_open, decision):
    _, app, _, _, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    csv_path = chart.session.dataset.csv_path
    csv_before = csv_path.read_bytes()
    pool_notebook = app.research_notebook_domain.create_notebook(
        app.research_notebook_domain.build_draft(display_name="Saved pool Notebook"))
    domain = app.research_workspace_snapshot_domain
    snapshot = domain.create_snapshot(domain.build_draft(
        presenter._capture_snapshot_workspace(), display_name="Saved pool Workspace"))
    snapshot = app.research_workspace_notebook_link_domain.assign_notebook(
        snapshot.snapshot_id, pool_notebook.notebook_id)
    if manager_open:
        presenter._open_notebook_manager()
        _wait_until(lambda: presenter._notebook_manager is not None
                    and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    editor, decisions = _dirty(presenter, monkeypatch, decision)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.action_for_text("Clear Research Suite").trigger()
    _wait_until(lambda: not presenter._notebook_save_pending and not presenter._notebook_task_id
                and not presenter._snapshot_task_ids)
    assert decisions == [decision]
    assert csv_path.read_bytes() == csv_before
    assert domain.load_snapshot(snapshot.snapshot_id) == snapshot
    assert app.research_notebook_domain.load_notebook(pool_notebook.notebook_id) == pool_notebook
    assert len(app.research_notebook_domain.list_notebooks()) == (2 if decision == "save" else 1)
    if decision == "cancel":
        assert presenter._notebook_editor is editor and editor.is_dirty
        assert presenter._chart_presenters[slot] is chart and not chart.session.is_disposed
    else:
        assert window.workspace.chart_count() == 0 and chart.session.is_disposed
        assert presenter._notebook_editor is None and presenter._notebook_manager is None


@pytest.mark.parametrize("failure", ["invalid", "submission", "execution"])
def test_clear_save_failure_keeps_manager_editor_and_charts(composed, monkeypatch, failure):
    _, app, _, _, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    manager = presenter._notebook_manager
    editor, decisions = _dirty(presenter, monkeypatch, "save")

    def broken(*args, **kwargs):
        raise OSError("injected Save before Clear failure")

    if failure == "invalid":
        editor._name.setText("")
    elif failure == "submission":
        monkeypatch.setattr(presenter._notebook_service, "submit_create_notebook", broken)
    else:
        monkeypatch.setattr(app.research_notebook_domain, "create_notebook", broken)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.action_for_text("Clear Research Suite").trigger()
    _wait_until(lambda: not presenter._notebook_save_pending)
    assert decisions == ["save"] and app.research_notebook_domain.list_notebooks() == ()
    assert presenter._chart_presenters[slot] is chart and not chart.session.is_disposed
    assert presenter._notebook_editor is editor and editor.is_dirty
    assert presenter._notebook_manager is manager and manager._refresh.isEnabled()


def test_save_clear_conflict_keeps_charts_and_refreshes_surviving_manager(composed, monkeypatch):
    _, app, _, _, window, presenter = composed
    slot = _open_restored_chart(window, presenter)
    chart = presenter._chart_presenters[slot]
    presenter._open_notebook_manager()
    _wait_until(lambda: presenter._notebook_manager is not None
                and not presenter._notebook_task_id and not presenter._snapshot_task_ids)
    manager = presenter._notebook_manager
    _, decisions = _dirty(presenter, monkeypatch, "save")
    save_enter, save_release, pre_enter, pre_release = Event(), Event(), Event(), Event()
    create = app.research_notebook_domain.create_notebook
    preflight = app.research_workspace_snapshot_domain.preflight
    snapshot = presenter._capture_rollback_snapshot()

    def held_create(draft):
        save_enter.set()
        assert save_release.wait(10)
        return create(draft)

    def held_preflight(*args, **kwargs):
        pre_enter.set()
        assert pre_release.wait(10)
        return preflight(*args, **kwargs)

    monkeypatch.setattr(app.research_notebook_domain, "create_notebook", held_create)
    monkeypatch.setattr(app.research_workspace_snapshot_domain, "preflight", held_preflight)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    try:
        window.action_for_text("Clear Research Suite").trigger()
        _wait_until(save_enter.is_set)
        presenter._submit_snapshot_task(
            lambda callback: presenter._snapshot_service.submit_preflight(
                snapshot, "append", {"occupied_positions": (slot,), "idle": True},
                result_callback=callback, callback_dispatcher=presenter._dispatch),
            lambda result: None)
        _wait_until(pre_enter.is_set)
        save_release.set()
        _wait_until(lambda: not presenter._notebook_save_pending and not presenter._notebook_task_id)
        assert decisions == ["save"]
        assert presenter._chart_presenters[slot] is chart and not chart.session.is_disposed
        assert presenter._notebook_manager is manager and len(manager.summaries) == 1
    finally:
        save_release.set()
        pre_release.set()
    _wait_until(lambda: not presenter._snapshot_task_ids)
    assert presenter._chart_presenters[slot] is chart  # No automatic retry of Clear.
    assert manager._refresh.isEnabled()
