import inspect

import pytest

pytest.importorskip("PySide6")

from leonardo.gui.presenters.research_chart_presenter import ResearchChartPresenter


def test_chart_restore_callbacks_are_optional_keyword_only():
    open_parameter = inspect.signature(ResearchChartPresenter.open_dataset).parameters["completion_callback"]
    environment_parameter = inspect.signature(ResearchChartPresenter.apply_environment).parameters["completion_callback"]
    assert open_parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert environment_parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert open_parameter.default is None
    assert environment_parameter.default is None
