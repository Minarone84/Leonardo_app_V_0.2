from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.research import (
    StudyEnvironmentCompatibilityReport,
    StudyExecutionRequest,
    StudyValidationError,
)
from tests.gui_test.test_research_single_chart_integration import _wait_until
from tests.gui_test.test_research_study_presenter import _open


def _single_study_environment(app, presenter):
    dataset = presenter.session.dataset
    draft = app.research_study_setup_domain.build_environment(
        dataset,
        presenter.session.studies,
        presenter.session.study_presentations(),
        display_name="EMA Environment",
    )
    return app.research_study_setup_domain.create_environment(draft)


def test_environment_append_and_replace_use_sequential_task_1017_apply(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        chart.submit_study_calculation(StudyExecutionRequest("ema", {"period": 20}))
        _wait_until(lambda: chart.session.study_count == 1)
        environment = _single_study_environment(app, chart)
        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        chart.apply_environment(environment, "append")
        _wait_until(lambda: not chart.environment_apply_active)
        assert chart.session.study_count == 2
        assert chart.session.studies[-1].user_metadata == environment.entries[0].user_metadata

        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        chart.apply_environment(environment, "replace")
        _wait_until(lambda: not chart.environment_apply_active)
        assert chart.session.study_count == 1
        assert chart.session.studies[0].result.output_names == environment.entries[0].expected_output_names
    finally:
        main.close()
        app.shutdown()


def test_environment_presentation_restores_guides_and_accepts_legacy_omission(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        chart.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 14})
        )
        _wait_until(lambda: chart.session.study_count == 1)
        study = chart.session.studies[0]
        environment = _single_study_environment(app, chart)
        entry = environment.entries[0]
        current_guides = tuple(
            chart.session.study_presentations()[0].guide_styles.values()
        )
        custom_guides = tuple(
            replace(
                guide,
                value=25.0 if guide.guide_id == "oversold" else guide.value,
            )
            for guide in current_guides
        )
        custom_entry = replace(
            entry,
            presentation=replace(
                entry.presentation,
                guide_styles=custom_guides,
            ),
        )

        chart._apply_environment_presentation(study.study_id, custom_entry)
        assert (
            chart.session.study_presentations()[0]
            .guide_styles["oversold"]
            .value
        ) == 25.0

        chart.apply_guide_values(
            study.study_id,
            {"overbought": 70.0, "center": 50.0, "oversold": 30.0},
        )
        legacy_entry = replace(
            entry,
            presentation=replace(entry.presentation, guide_styles=()),
        )
        chart._apply_environment_presentation(study.study_id, legacy_entry)
        assert (
            chart.session.study_presentations()[0]
            .guide_styles["oversold"]
            .value
        ) == 30.0
    finally:
        main.close()
        app.shutdown()


def test_tdirsi_legacy_missing_fill_is_narrowly_accepted(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        chart.submit_study_calculation(StudyExecutionRequest("tdirsi"))
        _wait_until(lambda: chart.session.study_count == 1)
        study = chart.session.studies[0]
        environment = _single_study_environment(app, chart)
        entry = environment.entries[0]
        current = chart.session.study_presentations()[0]
        assert tuple(current.fill_styles) == ("tdirsi_band",)

        legacy_entry = replace(
            entry,
            presentation=replace(entry.presentation, fill_styles=()),
        )
        chart._apply_environment_presentation(study.study_id, legacy_entry)
        retained = chart.session.study_presentations()[0]
        assert retained.fill_styles == current.fill_styles
        assert retained.revision == current.revision

        wrong_fill = replace(
            entry.presentation.fill_styles[0],
            fill_id="wrong_tdirsi_band",
        )
        wrong_entry = replace(
            entry,
            presentation=replace(
                entry.presentation,
                fill_styles=(wrong_fill,),
            ),
        )
        with pytest.raises(
            StudyValidationError,
            match="environment presentation styles do not match Study",
        ):
            chart._apply_environment_presentation(study.study_id, wrong_entry)

        extra_fill = replace(
            entry.presentation.fill_styles[0],
            fill_id="extra_tdirsi_band",
        )
        extra_entry = replace(
            entry,
            presentation=replace(
                entry.presentation,
                fill_styles=entry.presentation.fill_styles + (extra_fill,),
            ),
        )
        with pytest.raises(
            StudyValidationError,
            match="environment presentation styles do not match Study",
        ):
            chart._apply_environment_presentation(study.study_id, extra_entry)
    finally:
        main.close()
        app.shutdown()


def test_non_tdirsi_missing_default_fill_remains_invalid(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        chart.submit_study_calculation(
            StudyExecutionRequest("bb", {"period": 3, "std": 1.5})
        )
        _wait_until(lambda: chart.session.study_count == 1)
        study = chart.session.studies[0]
        environment = _single_study_environment(app, chart)
        entry = environment.entries[0]
        assert tuple(chart.session.study_presentations()[0].fill_styles) == (
            "bb_band",
        )
        missing_fill = replace(
            entry,
            presentation=replace(entry.presentation, fill_styles=()),
        )
        with pytest.raises(
            StudyValidationError,
            match="environment presentation styles do not match Study",
        ):
            chart._apply_environment_presentation(study.study_id, missing_fill)
    finally:
        main.close()
        app.shutdown()
