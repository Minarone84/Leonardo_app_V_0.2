from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
)

from leonardo.gui.windows.study_environment_save_dialog import (
    StudyEnvironmentSaveDialog,
    StudyEnvironmentSourceChart,
)
from leonardo.research import StudyEnvironmentSummary
from tests.research_test.test_study_execution import accepted_context, prepare


def test_environment_metadata_fields_have_explicit_buddy_labels(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        __import__(
            "leonardo.research", fromlist=["ResearchStudyService"]
        ).ResearchStudyService(artifacts),
        dataset,
        "ema",
        parameters={"period": 20},
    )
    dialog = StudyEnvironmentSaveDialog(1, "session", (study,), ())

    name = dialog.findChild(QLineEdit, "research.environment_save_dialog.edit.name")
    description = dialog.findChild(
        QLineEdit, "research.environment_save_dialog.edit.description"
    )
    labels = {label.text(): label for label in dialog.findChildren(QLabel)}

    assert labels["Study Environment Name"].buddy() is name
    assert labels["Description"].buddy() is description


def test_environment_save_dialog_captures_slot_session_and_metadata_only(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        __import__("leonardo.research", fromlist=["ResearchStudyService"]).ResearchStudyService(artifacts),
        dataset,
        "ema",
        parameters={"period": 20},
    )
    dialog = StudyEnvironmentSaveDialog(2, "session_two", (study,), ())
    dialog.findChild(QLineEdit, "research.environment_save_dialog.edit.name").setText(
        "Momentum"
    )
    intent = dialog.current_intent()
    assert (intent.slot_id, intent.session_id, intent.mode) == (2, "session_two", "create")
    assert intent.metadata_overrides[0][0] == study.study_id


def test_environment_save_radio_style_is_local_and_exclusive(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    before = app.styleSheet()
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        __import__("leonardo.research", fromlist=["ResearchStudyService"]).ResearchStudyService(artifacts),
        dataset,
        "ema",
        parameters={"period": 20},
    )
    dialog = StudyEnvironmentSaveDialog(1, "session", (study,), ())
    style = dialog.styleSheet()
    assert "background-color: #111827" in style
    assert "border: 1px solid #9CA3AF" in style
    assert "background-color: #9CA3AF" in style
    assert "border: 1px solid #D1D5DB" in style
    assert dialog._create.isChecked() and not dialog._update.isChecked()
    dialog._update.setChecked(True)
    assert dialog._update.isChecked() and not dialog._create.isChecked()
    assert app.styleSheet() == before


def test_environment_create_clears_name_after_update_selection(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        __import__("leonardo.research", fromlist=["ResearchStudyService"]).ResearchStudyService(artifacts),
        dataset,
        "ema",
        parameters={"period": 20},
    )
    summary = StudyEnvironmentSummary(
        "env_existing",
        "Existing Environment",
        "Existing description",
        1,
        None,
        None,
    )
    dialog = StudyEnvironmentSaveDialog(1, "session", (study,), (summary,))
    create = dialog.findChild(
        QRadioButton, "research.environment_save_dialog.radio.create"
    )
    update = dialog.findChild(
        QRadioButton, "research.environment_save_dialog.radio.update"
    )
    existing = dialog.findChild(
        QComboBox, "research.environment_save_dialog.combo.existing"
    )
    name = dialog.findChild(QLineEdit, "research.environment_save_dialog.edit.name")
    save = dialog.findChild(QPushButton, "research.environment_save_dialog.button.save")

    assert create.isChecked()
    assert name.text() == ""
    name.setText("Temporary Create Name")
    update.setChecked(True)
    assert existing.isEnabled()
    assert name.text() == "Existing Environment"

    create.setChecked(True)
    assert name.text() == ""
    assert not name.isReadOnly()
    assert not save.isEnabled()
    name.setText("Existing Environment")
    assert not save.isEnabled()
    name.setText("New Environment")
    assert save.isEnabled()
    intent = dialog.current_intent()
    assert intent.mode == "create"
    assert intent.environment_id is None
    assert intent.display_name == "New Environment"

    update.setChecked(True)
    assert name.text() == "Existing Environment"


def test_environment_source_chart_repopulates_studies_and_emits_selected_identity(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = __import__(
        "leonardo.research", fromlist=["ResearchStudyService"]
    ).ResearchStudyService(artifacts)
    first = prepare(service, dataset, "ema", parameters={"period": 20})
    second = prepare(service, dataset, "rsi", parameters={"period": 14})
    sources = (
        StudyEnvironmentSourceChart(
            1,
            "session_one",
            "Position 1 | bybit | linear | BTCUSDT | 1m",
            (first,),
        ),
        StudyEnvironmentSourceChart(
            2,
            "session_two",
            "Position 2 | bybit | linear | BTCUSDT | 1m",
            (second,),
        ),
    )
    dialog = StudyEnvironmentSaveDialog(
        1,
        "session_one",
        (first,),
        (),
        source_charts=sources,
    )
    source = dialog.findChild(
        QComboBox, "research.environment_save_dialog.combo.source_chart"
    )
    table = dialog.findChild(
        QTableWidget, "research.environment_save_dialog.table.studies"
    )
    name = dialog.findChild(QLineEdit, "research.environment_save_dialog.edit.name")
    name.setText("Selected Chart Environment")
    assert source.count() == 2
    assert table.item(0, 1).text() == first.display_name

    source.setCurrentIndex(1)
    assert table.rowCount() == 1
    assert table.item(0, 1).text() == second.display_name
    intent = dialog.current_intent()
    assert (intent.slot_id, intent.session_id) == (2, "session_two")
    assert tuple(study_id for study_id, _metadata in intent.metadata_overrides) == (
        second.study_id,
    )


def test_environment_save_refusal_keeps_dialog_open(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        __import__(
            "leonardo.research", fromlist=["ResearchStudyService"]
        ).ResearchStudyService(artifacts),
        dataset,
        "ema",
        parameters={"period": 20},
    )
    dialog = StudyEnvironmentSaveDialog(1, "session", (study,), ())
    dialog._name.setText("Environment")
    dialog.save_requested.connect(
        lambda _intent: dialog.show_save_failure("Source Chart is stale")
    )
    dialog.show()
    dialog._save.click()
    assert dialog.isVisible()
    assert dialog._validation.text() == "Source Chart is stale"
