"""Deterministic lazy exports for Leonardo Light V2 Qt windows."""

from __future__ import annotations

from importlib import import_module


__all__ = [
    "AnalysisSuiteWindow",
    "ConnectionSuiteWindow",
    "DataManagerSuiteWindow",
    "HistoricalDownloadManagerWindow",
    "LeonardoMainWindow",
    "OhlcvDownloadPreflightWindow",
    "OhlcvDownloadTaskWindow",
    "OhlcvMaintenanceWindow",
    "ResearchSuiteWindow",
    "RuntimeManagerWindow",
    "TradingSuiteWindow",
]

_LAZY_EXPORTS = {
    "AnalysisSuiteWindow": "analysis_suite_window",
    "ConnectionSuiteWindow": "connection_suite_window",
    "DataManagerSuiteWindow": "data_manager_suite_window",
    "HistoricalDownloadManagerWindow": "historical_download_manager_window",
    "LeonardoMainWindow": "main_window",
    "OhlcvDownloadPreflightWindow": "ohlcv_download_preflight_window",
    "OhlcvDownloadTaskWindow": "ohlcv_download_task_window",
    "OhlcvMaintenanceWindow": "ohlcv_maintenance_window",
    "ResearchSuiteWindow": "research_suite_window",
    "RuntimeManagerWindow": "runtime_manager_window",
    "TradingSuiteWindow": "trading_suite_window",
}


def __getattr__(name: str):
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(
        import_module(f"leonardo.gui.windows.{module_name}"), name
    )
    globals()[name] = value
    return value
