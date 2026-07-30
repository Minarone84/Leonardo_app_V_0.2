from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLineEdit, QTableWidget, QTabWidget

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.presenters.research_presenter import (
    ResearchSuitePresenter as LegacyResearchSuitePresenter,
)
from leonardo.gui.windows.research_suite_window import (
    ResearchSuiteWindow as LegacyResearchSuiteWindow,
)
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
)
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchNotebookNoteV1,
    ResearchNotebookPageV1,
)
from tests.gui_test.test_research_single_chart_integration import (
    _wait_until,
    _write_accepted_dataset,
)


def _open_legacy_notebook_suite(tmp_path: Path):
    # Test-only legacy Notebook characterization for deferred Task 1035.
    # This is not the production Research composition path.
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    window = LegacyResearchSuiteWindow(parent=main)
    presenter = LegacyResearchSuitePresenter(
        window,
        app.context.research_dataset_service,
        app.context.research_study_service,
        app.context.research_study_setup_service,
        app.context.research_workspace_snapshot_service,
        app.context.research_notebook_service,
    )
    window.show()
    _wait_until(lambda: window.selected_market_id() is not None)
    window.button_for_id("research_suite.button.open_chart").click()
    _wait_until(lambda: window.status_text() == "Chart ready")
    return app, main, window, presenter


def test_suite_new_notebook_uses_current_chart_page(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        window.button_for_id("research_suite.button.new_notebook").click()
        QCoreApplication.processEvents()
        editor = window.findChild(ResearchNotebookWindow)
        assert editor is not None
        assert len(editor.current_draft().pages) == 1
        assert editor.current_draft().pages[0].market_id == presenter.session.dataset.market_id
    finally:
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def _open_persisted_editor(app, window, presenter):
    market = presenter.session.dataset.market_id
    notebook = app.research_notebook_domain.create_notebook(
        ResearchNotebookDraft(
            "Lifecycle Notebook",
            "saved",
            ResearchNotebookAnnotationSettingsV1(),
            (
                ResearchNotebookPageV1(
                    market,
                    notes=(
                        ResearchNotebookNoteV1(
                            "note_lifecycle", 1000, "saved note"
                        ),
                    ),
                ),
            ),
        )
    )
    presenter._open_notebook_editor(notebook=notebook)
    editor = window.findChild(ResearchNotebookWindow)
    assert editor is not None
    dirty = replace(editor.last_valid_draft, description="dirty edit")
    editor.set_draft(dirty, dirty=True)
    presenter._last_valid_notebook_draft = dirty
    return notebook, editor


def _invalidate_editor(editor: ResearchNotebookWindow) -> QTableWidget:
    tabs = editor.findChild(QTabWidget, "research.notebook_window.tabs.pages")
    table = tabs.currentWidget().findChild(
        QTableWidget, "research.notebook_window.table.notes"
    )
    table.item(0, 2).setText("invalid-current-cell")
    editor._editor_changed()
    assert not editor.is_current_valid
    assert editor.is_dirty
    return table


def _install_manager(window, presenter):
    dialog = ResearchNotebookManagerDialog((), window)
    presenter._notebook_manager_generation += 1
    presenter._notebook_manager = dialog
    return dialog, presenter._notebook_manager_generation


@pytest.mark.parametrize(
    ("decision", "closed"),
    (("save", True), ("discard", True), ("cancel", False)),
)
def test_dirty_close_save_discard_cancel(
    tmp_path, monkeypatch, decision: str, closed: bool
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        notebook, editor = _open_persisted_editor(app, window, presenter)
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: decision,
        )

        presenter.close_active_notebook()
        if decision == "save":
            _wait_until(lambda: presenter._notebook_task_id is None)

        assert (presenter._notebook_editor is None) is closed
        if decision == "save":
            assert app.research_notebook_store.load(
                notebook.notebook_id
            ).description == "dirty edit"
        elif decision == "cancel":
            assert editor.is_dirty
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


@pytest.mark.parametrize(
    ("decision", "deleted"),
    (("save", True), ("discard", True), ("cancel", False)),
)
def test_active_dirty_delete_save_discard_cancel(
    tmp_path, monkeypatch, decision: str, deleted: bool
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        notebook, editor = _open_persisted_editor(app, window, presenter)
        dialog, generation = _install_manager(window, presenter)
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: decision,
        )

        presenter._delete_notebook(dialog, generation, notebook.notebook_id)
        if deleted:
            _wait_until(lambda: presenter._notebook_task_id is None)

        path = app.config.paths.research_notebooks_dir / f"{notebook.notebook_id}.json"
        assert path.exists() is not deleted
        assert (presenter._notebook_editor is None) is deleted
        if decision == "cancel":
            assert editor.is_dirty
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_failed_save_clears_close_and_later_manual_save_does_not_close(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    callbacks = []
    submissions = iter(("save_failed", "save_manual"))

    def controlled_update(_notebook_id, _draft, **values):
        task_id = next(submissions)
        callbacks.append((task_id, values["result_callback"]))
        return TaskSubmission(task_id, "controlled notebook save")

    try:
        notebook, editor = _open_persisted_editor(app, window, presenter)
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            controlled_update,
        )
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: "save",
        )
        presenter.close_active_notebook()
        callbacks[0][1](
            TaskResult(
                callbacks[0][0],
                "failed",
                error_type="TestFailure",
                error_message="save rejected",
            )
        )

        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert editor.is_dirty

        saved = app.research_notebook_domain.update_notebook(
            notebook.notebook_id, editor.last_valid_draft
        )
        presenter._save_notebook_editor(False)
        callbacks[1][1](TaskResult(callbacks[1][0], "completed", saved))

        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert not editor.is_dirty
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_transition_is_blocked_while_notebook_task_is_active(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        _notebook, editor = _open_persisted_editor(app, window, presenter)
        decisions: list[str] = []
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: decisions.append("asked") or "save",
        )
        presenter._notebook_task_id = "busy"

        presenter._request_notebook_transition("close", None)

        assert decisions == []
        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert window.status_text() == "Notebook operation in progress"
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


@pytest.mark.parametrize(
    ("decision", "replaced"),
    (("save", True), ("discard", True), ("cancel", False)),
)
def test_dirty_notebook_replacement_uses_save_discard_cancel(
    tmp_path, monkeypatch, decision: str, replaced: bool
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        _notebook, editor = _open_persisted_editor(app, window, presenter)
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: decision,
        )

        presenter._request_notebook_transition("new", None)
        if decision == "save":
            _wait_until(lambda: presenter._notebook_task_id is None)

        assert (presenter._notebook_editor is not editor) is replaced
        if replaced:
            assert presenter._notebook_editor.notebook_id is None
        else:
            assert editor.is_dirty
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_save_submission_failure_clears_pending_transition(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        _notebook, editor = _open_persisted_editor(app, window, presenter)
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("submission rejected")
            ),
        )
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: "save",
        )

        presenter.close_active_notebook()

        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert editor.is_dirty
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_stale_manager_prevents_deferred_delete(tmp_path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    callback = []

    def controlled_update(_notebook_id, _draft, **values):
        callback.append(values["result_callback"])
        return TaskSubmission("deferred_save", "controlled notebook save")

    try:
        notebook, editor = _open_persisted_editor(app, window, presenter)
        dialog, generation = _install_manager(window, presenter)
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            controlled_update,
        )
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: "save",
        )
        presenter._delete_notebook(dialog, generation, notebook.notebook_id)
        saved = app.research_notebook_domain.update_notebook(
            notebook.notebook_id, editor.last_valid_draft
        )
        presenter._notebook_manager = None
        presenter._notebook_manager_generation += 1

        callback[0](TaskResult("deferred_save", "completed", saved))

        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert (
            app.config.paths.research_notebooks_dir
            / f"{notebook.notebook_id}.json"
        ).exists()
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


@pytest.mark.parametrize(
    "transition",
    ("manual", "close", "replacement", "suite_close"),
)
def test_invalid_dirty_save_never_submits_or_transitions(
    tmp_path, monkeypatch, transition: str
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    submissions: list[object] = []
    try:
        _notebook, editor = _open_persisted_editor(app, window, presenter)
        table = _invalidate_editor(editor)
        raw = table.item(0, 2).text()
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            lambda *_args, **_kwargs: submissions.append(object()),
        )
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: "save",
        )

        if transition == "manual":
            presenter._save_notebook_editor(False)
        elif transition == "close":
            presenter.close_active_notebook()
        elif transition == "replacement":
            presenter._request_notebook_transition("new", None)
        else:
            assert not presenter._request_suite_close()

        assert submissions == []
        assert presenter._notebook_task_id is None
        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert editor.is_dirty
        assert not editor.is_current_valid
        assert table.item(0, 2).text() == raw
        assert not window.isHidden()
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_invalid_active_dirty_delete_submits_neither_save_nor_delete(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    submissions: list[str] = []
    try:
        notebook, editor = _open_persisted_editor(app, window, presenter)
        table = _invalidate_editor(editor)
        raw = table.item(0, 2).text()
        dialog, generation = _install_manager(window, presenter)
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            lambda *_args, **_kwargs: submissions.append("save"),
        )
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_delete_notebook",
            lambda *_args, **_kwargs: submissions.append("delete"),
        )
        monkeypatch.setattr(
            ResearchNotebookWindow,
            "dirty_decision",
            lambda _self: "save",
        )

        presenter._delete_notebook(dialog, generation, notebook.notebook_id)

        assert submissions == []
        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is editor
        assert table.item(0, 2).text() == raw
        assert (
            app.config.paths.research_notebooks_dir
            / f"{notebook.notebook_id}.json"
        ).exists()
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_presenter_submits_exact_current_valid_draft_not_cached_draft(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    captured = []

    def controlled_update(_notebook_id, draft, **values):
        captured.append((draft, values["result_callback"]))
        return TaskSubmission("exact_current", "controlled notebook save")

    try:
        _notebook, editor = _open_persisted_editor(app, window, presenter)
        stale = presenter._last_valid_notebook_draft
        description = editor.findChild(
            QLineEdit, "research.notebook_window.edit.description"
        )
        description.setText("exact current description")
        presenter._last_valid_notebook_draft = stale
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            controlled_update,
        )

        presenter._save_notebook_editor(False)

        assert captured[0][0].description == "exact current description"
        assert captured[0][0] == editor.current_draft()
        captured[0][1](
            TaskResult("exact_current", "failed", error_message="test settlement")
        )
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
