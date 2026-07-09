import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from leonardo.gui.widgets import (  # noqa: E402
    DEFAULT_SUITE_NAVIGATION_SEGMENTS,
    SuiteNavigationDonut,
    calculate_suite_navigation_donut_geometry,
)


def test_suite_navigation_geometry_reserves_utility_row() -> None:
    geometry = calculate_suite_navigation_donut_geometry(
        width=500,
        height=400,
        utility_row_height=50,
        spacing=10,
        margin=20,
    )

    assert geometry.segment_degrees == 72.0
    assert geometry.outer_diameter == pytest.approx(276.0)
    assert geometry.inner_diameter == pytest.approx(
        geometry.outer_diameter * 0.80
    )
    assert geometry.center_x == pytest.approx(250.0)
    assert geometry.center_y == pytest.approx(170.0)


def test_suite_navigation_segments_are_existing_main_window_actions() -> None:
    assert [
        (segment.object_id, segment.label, segment.action_id)
        for segment in DEFAULT_SUITE_NAVIGATION_SEGMENTS
    ] == [
        (
            "main_window.donut.segment.connection_suite",
            "Connection Suite",
            "main_window.download_data",
        ),
        (
            "main_window.donut.segment.research_suite",
            "Research Suite",
            "main_window.open_research_suite",
        ),
        (
            "main_window.donut.segment.data_manager",
            "Data Manager Suite",
            "main_window.open_data_manager_suite",
        ),
        (
            "main_window.donut.segment.analysis_suite",
            "Analysis Suite",
            "main_window.open_analysis_suite",
        ),
        (
            "main_window.donut.segment.trading_suite",
            "Trading Suite",
            "main_window.open_trading_suite",
        ),
    ]


def test_suite_navigation_hit_testing_maps_each_segment(
    qapplication: QApplication,
) -> None:
    donut = SuiteNavigationDonut()
    donut.resize(420, 420)

    for segment in donut.segments():
        point = donut.activation_point_for_action_id(segment.action_id)
        assert donut.segment_at_point(point) == segment

    center = donut.geometry_model().center.toPoint()
    assert donut.segment_at_point(center) is None

    donut.deleteLater()
    qapplication.processEvents()


def test_suite_navigation_mouse_click_emits_existing_action_id(
    qapplication: QApplication,
) -> None:
    donut = SuiteNavigationDonut()
    donut.resize(420, 420)
    donut.show()
    qapplication.processEvents()
    emitted: list[str] = []
    donut.segment_activated.connect(emitted.append)

    QTest.mouseClick(
        donut,
        Qt.MouseButton.LeftButton,
        pos=donut.activation_point_for_action_id("main_window.open_analysis_suite"),
    )
    qapplication.processEvents()

    assert emitted == ["main_window.open_analysis_suite"]

    donut.close()
    donut.deleteLater()
    qapplication.processEvents()


def test_suite_navigation_widget_consumes_jarvish_theme_tokens(
    qapplication: QApplication,
) -> None:
    donut = SuiteNavigationDonut()

    assert donut.theme_id == "leonardo_jarvish_cockpit"
    assert donut.font().family()
    assert donut.font().pointSize() > 0

    donut.deleteLater()
    qapplication.processEvents()


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
