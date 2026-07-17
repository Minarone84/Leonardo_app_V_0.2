from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTabWidget,
)

from leonardo.core.core_runner import TaskResult, TaskSubmission
from leonardo.gui.presenters.research_presenter import ResearchSuitePresenter
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
)
from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
)
from tests.gui_test.test_research_notebook_presenter import (
    _open_persisted_editor,
)
from tests.gui_test.test_research_study_presenter import _open


def test_notebook_runtime_tracks_generations_and_one_mutation_task() -> None:
    source = inspect.getsource(ResearchSuitePresenter)
    assert "_notebook_editor_generation" in source
    assert "_notebook_manager_generation" in source
    assert "_notebook_task_id" in source
    assert "task_id != self._notebook_task_id" in source
    assert "self._notebook_service.cancel(self._notebook_task_id)" in source


def test_stale_save_load_and_delete_results_do_not_mutate_newer_editor(
    tmp_path
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open(tmp_path)
    try:
        notebook, old_editor = _open_persisted_editor(app, window, presenter)
        old_generation = presenter._notebook_editor_generation
        presenter._close_notebook_editor()
        presenter._open_notebook_editor(
            draft=ResearchNotebookDraft(
                "Newer Notebook",
                "",
                ResearchNotebookAnnotationSettingsV1(),
                (),
            )
        )
        newer_editor = presenter._notebook_editor
        assert newer_editor is not None

        presenter._notebook_pending_action = ("close", None)
        presenter._saved_notebook_result(
            old_editor,
            old_generation,
            TaskResult("stale_save", "completed", notebook),
        )
        presenter._loaded_notebook_result(
            old_generation,
            notebook.notebook_id,
            TaskResult("stale_load", "completed", notebook),
        )
        stale_manager = ResearchNotebookManagerDialog((), window)
        presenter._notebook_manager = ResearchNotebookManagerDialog((), window)
        presenter._notebook_manager_generation = 2
        presenter._deleted_notebook_result(
            stale_manager,
            1,
            notebook.notebook_id,
            TaskResult("stale_delete", "completed", None),
        )

        assert presenter._notebook_pending_action is None
        assert presenter._notebook_editor is newer_editor
        assert newer_editor.last_valid_draft.display_name == "Newer Notebook"
    finally:
        presenter._close_notebook_editor()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_dispose_cancels_one_notebook_task_and_clears_each_chart_once(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, presenter = _open(tmp_path)
    chart = presenter.chart_presenter(presenter.active_slot_id)
    cancellations: list[str] = []
    clears: list[int] = []
    original_clear = chart.clear_notebook_annotations
    monkeypatch.setattr(
        app.research_notebook_service,
        "cancel",
        lambda task_id: cancellations.append(task_id) or True,
    )
    monkeypatch.setattr(
        chart,
        "clear_notebook_annotations",
        lambda: clears.append(chart.slot_id) or original_clear(),
    )
    presenter._notebook_task_id = "notebook_task"

    presenter.dispose()
    presenter.dispose()

    assert cancellations == ["notebook_task"]
    assert clears == [chart.slot_id]
    assert presenter._chart_presenters == {}
    main.close()
    QCoreApplication.processEvents()
    app.shutdown()


def test_failed_save_restores_invalid_dirty_editor_without_raw_data_loss(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, presenter = _open(tmp_path)
    callbacks = []

    def controlled_update(_notebook_id, _draft, **values):
        callbacks.append(values["result_callback"])
        return TaskSubmission("pending_save", "controlled notebook save")

    try:
        _notebook, editor = _open_persisted_editor(
            app, presenter._view, presenter
        )
        monkeypatch.setattr(
            app.research_notebook_service,
            "submit_update_notebook",
            controlled_update,
        )
        presenter._save_notebook_editor(False)
        name = editor.findChild(
            QLineEdit, "research.notebook_window.edit.name"
        )
        add_note = editor.findChild(
            QPushButton, "research.notebook_window.button.add_note"
        )
        save = editor.findChild(
            QPushButton, "research.notebook_window.button.save"
        )
        save_as = editor.findChild(
            QPushButton, "research.notebook_window.button.save_as"
        )
        assert not name.isEnabled()
        assert not add_note.isEnabled()
        assert not save.isEnabled()
        assert not save_as.isEnabled()

        tabs = editor.findChild(QTabWidget, "research.notebook_window.tabs.pages")
        table = tabs.currentWidget().findChild(
            QTableWidget, "research.notebook_window.table.notes"
        )
        table.item(0, 2).setText("invalid-during-save")
        editor._editor_changed()
        assert not editor.is_current_valid
        presenter.close_active_notebook()
        assert presenter._notebook_editor is editor

        callbacks[0](
            TaskResult(
                "pending_save",
                "failed",
                error_type="TestFailure",
                error_message="save rejected",
            )
        )

        assert table.item(0, 2).text() == "invalid-during-save"
        assert editor.is_dirty
        assert not editor.is_current_valid
        assert name.isEnabled()
        assert add_note.isEnabled()
        assert not save.isEnabled()
        assert not save_as.isEnabled()
        assert presenter._notebook_pending_action is None
    finally:
        presenter._notebook_task_id = None
        presenter._close_notebook_editor()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
