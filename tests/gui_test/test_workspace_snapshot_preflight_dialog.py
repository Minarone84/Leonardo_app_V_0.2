import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton

from leonardo.gui.windows.workspace_snapshot_preflight_dialog import WorkspaceSnapshotPreflightDialog
from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotCompatibilityReport


def test_preflight_load_is_enabled_only_without_blockers():
    QApplication.instance() or QApplication([])
    compatible = ResearchWorkspaceSnapshotCompatibilityReport(
        "snapshot_a", "replace", True, ()
    )
    dialog = WorkspaceSnapshotPreflightDialog(compatible)
    assert dialog.findChild(QPushButton, "research.workspace_snapshot_preflight_dialog.button.load").isEnabled()
    blocked = WorkspaceSnapshotPreflightDialog(
        ResearchWorkspaceSnapshotCompatibilityReport(
            "snapshot_a", "replace", False, (), ("missing dataset",)
        )
    )
    assert not blocked.findChild(QPushButton, "research.workspace_snapshot_preflight_dialog.button.load").isEnabled()


def _compatible_dialog() -> WorkspaceSnapshotPreflightDialog:
    return WorkspaceSnapshotPreflightDialog(
        ResearchWorkspaceSnapshotCompatibilityReport(
            "snapshot_a", "replace", True, ()
        )
    )


def test_preflight_mode_and_restore_transition_are_exact() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _compatible_dialog()
    dialog.show()
    app.processEvents()
    load = dialog.findChild(
        QPushButton, "research.workspace_snapshot_preflight_dialog.button.load"
    )
    cancel = dialog.findChild(
        QPushButton, "research.workspace_snapshot_preflight_dialog.button.cancel"
    )
    overall = dialog.findChild(
        QProgressBar, "research.workspace_snapshot_preflight_dialog.progress"
    )
    current = dialog.findChild(
        QProgressBar,
        "research.workspace_snapshot_preflight_dialog.progress.current",
    )
    status = dialog.findChild(
        QLabel, "research.workspace_snapshot_preflight_dialog.label.restore_status"
    )
    assert load.isEnabled()
    assert cancel.isEnabled()
    assert status.text() == ""
    assert (overall.minimum(), overall.maximum(), overall.value()) == (0, 1, 1)

    dialog.begin_restore(3)
    assert not load.isEnabled()
    assert not cancel.isEnabled()
    assert (overall.minimum(), overall.maximum(), overall.value()) == (0, 3, 0)
    assert (current.minimum(), current.maximum()) == (0, 0)
    assert status.text() == "Preparing Workspace restore..."
    dialog.reject()
    dialog.close()
    app.processEvents()
    assert dialog.isVisible()

    dialog.show_failure("test cleanup")
    dialog.close()


def test_current_and_overall_restore_progress_are_exact() -> None:
    QApplication.instance() or QApplication([])
    dialog = _compatible_dialog()
    dialog.begin_restore(2)
    dialog.set_restore_stage("Chart 1 of 2: Loading historical dataset...")
    dialog.set_current_progress(25, 100)
    assert (
        dialog.current_progress.minimum(),
        dialog.current_progress.maximum(),
        dialog.current_progress.value(),
    ) == (0, 100, 25)
    dialog.complete_chart(1, 2)
    assert dialog.progress.value() == 1
    assert dialog.restore_status.text() == "Chart 1 of 2 complete."
    dialog.show_failure("test cleanup")
    dialog.close()


def test_success_allows_presenter_driven_close() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _compatible_dialog()
    dialog.show()
    dialog.begin_restore(1)
    dialog.complete_chart(1, 1)
    dialog.show_success()
    assert dialog.restore_status.text() == "Workspace restored."
    dialog.accept()
    app.processEvents()
    assert not dialog.isVisible()


def test_failure_requires_explicit_close() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _compatible_dialog()
    dialog.show()
    dialog.begin_restore(2)
    dialog.complete_chart(1, 2)
    dialog.show_failure("chart_2 dataset failed")
    assert dialog.isVisible()
    assert dialog.progress.value() == 1
    assert dialog.restore_status.text() == (
        "Workspace restore failed: chart_2 dataset failed"
    )
    assert dialog.cancel_button.text() == "Close"
    assert dialog.cancel_button.isEnabled()
    dialog.cancel_button.click()
    app.processEvents()
    assert not dialog.isVisible()


def test_rollback_active_and_terminal_states_preserve_original_failure() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _compatible_dialog()
    dialog.show()
    dialog.begin_restore(2)
    dialog.begin_rollback(1)
    assert dialog.restore_active
    assert dialog.restore_status.text() == (
        "Workspace restore failed. Restoring previous workspace..."
    )
    assert not dialog.cancel_button.isEnabled()
    dialog.close()
    app.processEvents()
    assert dialog.isVisible()

    dialog.show_rollback_success("new chart failed")
    assert dialog.restore_status.text() == (
        "Workspace restore failed: new chart failed\n"
        "Previous workspace restored."
    )
    assert dialog.cancel_button.isEnabled()
    dialog.cancel_button.click()
    app.processEvents()
    assert not dialog.isVisible()


def test_rollback_failure_preserves_both_failures() -> None:
    QApplication.instance() or QApplication([])
    dialog = _compatible_dialog()
    dialog.begin_restore(2)
    dialog.begin_rollback(1)
    dialog.show_rollback_failure("new chart failed", "old chart failed")
    assert dialog.restore_status.text() == (
        "Workspace restore failed: new chart failed\n"
        "Rollback failed: old chart failed"
    )
    assert dialog.cancel_button.text() == "Close"
    assert dialog.cancel_button.isEnabled()
    dialog.close()
