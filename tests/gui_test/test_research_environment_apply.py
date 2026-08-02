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
    StudyEnvironmentSourceV1,
    StudyExecutionRequest,
    StudyInputSource,
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


def test_peaks_utc_environment_replace_rebinds_new_dependency_studies(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        chart.submit_study_calculation(StudyExecutionRequest("peaks_troughs"))
        _wait_until(lambda: chart.session.study_count == 1)
        peaks = chart.session.studies[0]
        chart.submit_study_calculation(
            StudyExecutionRequest(
                "universal_trend_classifier",
                input_sources=tuple(
                    StudyInputSource(
                        role,
                        "study",
                        study_id=peaks.study_id,
                        output_name=output,
                    )
                    for role, output in (
                        ("trend_peak", "peak_fractal_5"),
                        ("trend_trough", "trough_fractal_5"),
                        ("range_peak", "peak_fractal_3"),
                        ("range_trough", "trough_fractal_3"),
                    )
                ),
            )
        )
        _wait_until(lambda: chart.session.study_count == 2)
        utc = chart.session.studies[1]
        draft = app.research_study_setup_domain.build_environment(
            chart.session.dataset,
            (utc, peaks),
            tuple(reversed(chart.session.study_presentations())),
            display_name="P&T to UTC",
        )
        environment = app.research_study_setup_domain.create_environment(draft)
        original_ids = {study.study_id for study in chart.session.studies}
        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        chart.apply_environment(environment, "replace")
        _wait_until(lambda: not chart.environment_apply_active)

        assert tuple(study.result.tool_key for study in chart.session.studies) == (
            "peaks_troughs",
            "universal_trend_classifier",
        )
        restored_peaks, restored_utc = chart.session.studies
        assert restored_peaks.study_id not in original_ids
        assert restored_utc.study_id not in original_ids
        assert {source.study_id for source in restored_utc.source_studies} == {
            restored_peaks.study_id
        }
        assert tuple(
            presentation.study_id
            for presentation in chart.session.study_presentations()
        ) == (restored_peaks.study_id, restored_utc.study_id)
    finally:
        main.close()
        app.shutdown()


def test_environment_apply_rejects_missing_and_cyclic_stored_dependencies_before_mutation(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        for request in (
            StudyExecutionRequest("ema", {"period": 20}),
            StudyExecutionRequest("rsi", {"period": 14}),
        ):
            chart.submit_study_calculation(request)
            expected = 1 if request.tool_key == "ema" else 2
            _wait_until(lambda expected=expected: chart.session.study_count == expected)
        environment = app.research_study_setup_domain.create_environment(
            app.research_study_setup_domain.build_environment(
                chart.session.dataset,
                chart.session.studies,
                chart.session.study_presentations(),
                display_name="Corrupt dependency checks",
            )
        )
        original_ids = tuple(study.study_id for study in chart.session.studies)

        missing_entry = replace(environment.entries[0])
        object.__setattr__(
            missing_entry,
            "sources",
            (
                StudyEnvironmentSourceV1(
                    "source",
                    "environment",
                    source_entry_id="missing_entry",
                    output_name="missing_output",
                ),
            ),
        )
        missing_environment = replace(environment)
        object.__setattr__(
            missing_environment,
            "entries",
            (missing_entry, environment.entries[1]),
        )
        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        with pytest.raises(
            StudyValidationError,
            match="Environment dependency is missing: missing_entry",
        ):
            chart.apply_environment(missing_environment, "replace")
        assert tuple(study.study_id for study in chart.session.studies) == original_ids

        first = replace(environment.entries[0])
        second = replace(environment.entries[1])
        object.__setattr__(
            first,
            "sources",
            (
                StudyEnvironmentSourceV1(
                    "source",
                    "environment",
                    source_entry_id=second.entry_id,
                    output_name=second.expected_output_names[0],
                ),
            ),
        )
        object.__setattr__(
            second,
            "sources",
            (
                StudyEnvironmentSourceV1(
                    "source",
                    "environment",
                    source_entry_id=first.entry_id,
                    output_name=first.expected_output_names[0],
                ),
            ),
        )
        cyclic_environment = replace(environment)
        object.__setattr__(cyclic_environment, "entries", (first, second))
        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        with pytest.raises(
            StudyValidationError,
            match="Environment dependency cycle detected",
        ):
            chart.apply_environment(cyclic_environment, "replace")
        assert tuple(study.study_id for study in chart.session.studies) == original_ids
    finally:
        main.close()
        app.shutdown()


def test_environment_replace_failure_rolls_back_new_studies_and_preserves_existing(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, chart = _open(tmp_path)
    try:
        for request in (
            StudyExecutionRequest("ema", {"period": 20}),
            StudyExecutionRequest("rsi", {"period": 14}),
        ):
            chart.submit_study_calculation(request)
            expected = 1 if request.tool_key == "ema" else 2
            _wait_until(lambda expected=expected: chart.session.study_count == expected)
        environment = app.research_study_setup_domain.create_environment(
            app.research_study_setup_domain.build_environment(
                chart.session.dataset,
                chart.session.studies,
                chart.session.study_presentations(),
                display_name="Rollback",
            )
        )
        bad_second = replace(environment.entries[1])
        object.__setattr__(bad_second, "expected_output_names", ("wrong_output",))
        bad_environment = replace(environment)
        object.__setattr__(
            bad_environment,
            "entries",
            (environment.entries[0], bad_second),
        )
        original_ids = tuple(study.study_id for study in chart.session.studies)
        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        chart.apply_environment(bad_environment, "replace")
        _wait_until(lambda: not chart.environment_apply_active)
        assert tuple(study.study_id for study in chart.session.studies) == original_ids
    finally:
        main.close()
        app.shutdown()
