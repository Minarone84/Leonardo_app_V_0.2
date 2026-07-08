"""GUI windows for Leonardo V2 metadata-driven surfaces."""

from leonardo.gui.windows.analysis_suite_window import (
    AnalysisSuiteWindow,
    load_analysis_suite_profile,
)
from leonardo.gui.windows.data_manager_suite_window import (
    DataManagerSuiteWindow,
    load_data_manager_suite_profile,
)
from leonardo.gui.windows.dummy_metadata_test_window import (
    DummyMetadataTestWindow,
    load_dummy_metadata_profile,
)
from leonardo.gui.windows.main_window import LeonardoMainWindow, load_main_window_profile
from leonardo.gui.windows.research_suite_window import (
    ResearchSuiteWindow,
    load_research_suite_profile,
)
from leonardo.gui.windows.runtime_manager_window import (
    RuntimeManagerWindow,
    load_runtime_manager_profile,
)
from leonardo.gui.windows.settings_inspector_window import SettingsInspectorWindow
from leonardo.gui.windows.trading_suite_window import (
    TradingSuiteWindow,
    load_trading_suite_profile,
)

__all__ = [
    "AnalysisSuiteWindow",
    "DataManagerSuiteWindow",
    "DummyMetadataTestWindow",
    "LeonardoMainWindow",
    "ResearchSuiteWindow",
    "RuntimeManagerWindow",
    "SettingsInspectorWindow",
    "TradingSuiteWindow",
    "load_analysis_suite_profile",
    "load_data_manager_suite_profile",
    "load_dummy_metadata_profile",
    "load_main_window_profile",
    "load_research_suite_profile",
    "load_runtime_manager_profile",
    "load_trading_suite_profile",
]
