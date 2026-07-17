"""Lean GUI composition over an existing LeonardoApp context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from PySide6.QtWidgets import QWidget

from leonardo.gui.action_observer import GuiActionObserver, build_gui_action_observer
from leonardo.gui.presenters import (
    HistoricalDownloadPresenter,
    OhlcvMaintenancePresenter,
    ResearchSuitePresenter,
)
from leonardo.gui.window_tracking import GuiWindowTracker
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow
from leonardo.gui.windows.connection_suite_window import ConnectionSuiteWindow
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from leonardo.gui.windows.historical_download_manager_window import HistoricalDownloadManagerWindow
from leonardo.gui.windows.main_window import LeonardoMainWindow
from leonardo.gui.windows.ohlcv_maintenance_window import OhlcvMaintenanceWindow
from leonardo.gui.windows.research_suite_window import ResearchSuiteWindow
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow
from leonardo.gui.windows.trading_suite_window import TradingSuiteWindow


class RuntimeSnapshotBackend(Protocol):
    def snapshot(self) -> object: ...


class GuiCoreContext(Protocol):
    runtime_manager: RuntimeSnapshotBackend
    window_registry: object
    action_registry: object
    config: object
    connection_service: object
    historical_download_service: object
    ohlcv_maintenance_service: object
    research_dataset_service: object
    research_study_service: object


class GuiCompositionRoot:
    """Construct and retain GUI windows without creating Core or Area services."""

    def __init__(self, context: GuiCoreContext, *, track_windows: bool = True) -> None:
        snapshot = getattr(getattr(context, "runtime_manager", None), "snapshot", None)
        if not callable(snapshot):
            raise TypeError("context.runtime_manager must expose callable snapshot")
        self._context = context
        self._snapshot_provider = snapshot
        self._track_windows = track_windows
        self._window_registry = getattr(context, "window_registry", None)
        if track_windows and self._window_registry is None:
            raise TypeError("context.window_registry is required when tracking windows")
        self._action_observer: GuiActionObserver | None = build_gui_action_observer(context)
        self._trackers: dict[str, GuiWindowTracker] = {}
        self._connection_suite_window: ConnectionSuiteWindow | None = None
        self._historical_download_manager_window: HistoricalDownloadManagerWindow | None = None
        self._historical_download_presenter: HistoricalDownloadPresenter | None = None
        self._ohlcv_maintenance_window: OhlcvMaintenanceWindow | None = None
        self._ohlcv_maintenance_presenter: OhlcvMaintenancePresenter | None = None
        self._research_suite_window: ResearchSuiteWindow | None = None
        self._research_suite_presenter: ResearchSuitePresenter | None = None
        self._data_manager_suite_window: DataManagerSuiteWindow | None = None
        self._analysis_suite_window: AnalysisSuiteWindow | None = None
        self._trading_suite_window: TradingSuiteWindow | None = None
        self._runtime_manager_window: RuntimeManagerWindow | None = None

    @property
    def window_trackers(self) -> Mapping[str, GuiWindowTracker]:
        return dict(self._trackers)

    def tracker_for(self, window_id: str) -> GuiWindowTracker | None:
        return self._trackers.get(window_id)

    @property
    def connection_suite_window(self) -> ConnectionSuiteWindow | None:
        return self._connection_suite_window

    @property
    def historical_download_manager_window(self) -> HistoricalDownloadManagerWindow | None:
        return self._historical_download_manager_window

    @property
    def ohlcv_maintenance_window(self) -> OhlcvMaintenanceWindow | None:
        return self._ohlcv_maintenance_window

    @property
    def ohlcv_maintenance_presenter(self) -> OhlcvMaintenancePresenter | None:
        return self._ohlcv_maintenance_presenter

    @property
    def research_suite_window(self) -> ResearchSuiteWindow | None:
        return self._research_suite_window

    @property
    def research_suite_presenter(self) -> ResearchSuitePresenter | None:
        return self._research_suite_presenter

    @property
    def data_manager_suite_window(self) -> DataManagerSuiteWindow | None:
        return self._data_manager_suite_window

    @property
    def analysis_suite_window(self) -> AnalysisSuiteWindow | None:
        return self._analysis_suite_window

    @property
    def trading_suite_window(self) -> TradingSuiteWindow | None:
        return self._trading_suite_window

    def create_main_window(self) -> LeonardoMainWindow:
        main_window: LeonardoMainWindow | None = None

        def open_download(action_id: str) -> str:
            if main_window is None:
                raise RuntimeError("Main Window is not available")
            return self._open_connection_suite(main_window)

        def open_maintenance(action_id: str) -> str:
            if main_window is None:
                raise RuntimeError("Main Window is not available")
            return self._open_ohlcv_maintenance(main_window)

        def open_suite(action_id: str) -> str:
            if main_window is None:
                raise RuntimeError("Main Window is not available")
            return self._open_suite_shell(action_id, main_window)

        main_window = LeonardoMainWindow(
            runtime_manager_window_factory=self._create_runtime_manager_window,
            action_observer=self._action_observer,
            on_download_data_requested=open_download,
            on_ohlcv_maintenance_requested=open_maintenance,
            on_suite_shell_requested=open_suite,
            on_close_requested=self._close_suite_shells,
            username=getattr(getattr(self._context, "config", None), "actor_id", "local-user"),
        )
        self._register_window_actions(main_window, "main_window.window")
        self._install_tracker(main_window, "main_window.window", "Leonardo", "main_window")
        return main_window

    def _create_runtime_manager_window(self) -> RuntimeManagerWindow:
        if self._runtime_manager_window is None:
            self._runtime_manager_window = RuntimeManagerWindow(
                snapshot_provider=self._snapshot_provider,
                action_observer=self._action_observer,
            )
            self._register_window_actions(
                self._runtime_manager_window,
                "runtime_manager.window",
            )
            self._install_tracker(
                self._runtime_manager_window,
                "runtime_manager.window",
                "Runtime Manager",
                "tool",
            )
        return self._runtime_manager_window

    def _open_connection_suite(self, parent: LeonardoMainWindow) -> str:
        if self._connection_suite_window is None:
            window = ConnectionSuiteWindow(
                action_observer=self._action_observer,
                parent=parent,
            )
            self._connection_suite_window = window
            self._register_window_actions(window, "connection_suite.home.window")
            self._install_tracker(
                window,
                "connection_suite.home.window",
                "Connection Suite",
                "suite",
            )
            try:
                window.button_for_id(
                    "connection_suite.button.view_historical_download_manager"
                ).clicked.connect(lambda: self._open_historical_download_manager(parent))
            except KeyError:
                pass
        self._show_window(self._connection_suite_window)
        return "Connection Suite shell opened."

    def _open_historical_download_manager(self, parent: LeonardoMainWindow) -> str:
        if self._historical_download_manager_window is None:
            window = HistoricalDownloadManagerWindow(parent=parent)
            presenter = HistoricalDownloadPresenter(
                window,
                getattr(self._context, "connection_service"),
                getattr(self._context, "historical_download_service"),
            )
            self._historical_download_manager_window = window
            self._historical_download_presenter = presenter
            window.maintenance_requested.connect(
                lambda: self._open_ohlcv_maintenance(parent)
            )
            self._register_window_actions(
                window,
                "historical_download_manager.window",
            )
            self._install_tracker(
                window,
                "historical_download_manager.window",
                "Historical Download Manager",
                "workflow",
            )
        self._show_window(self._historical_download_manager_window)
        return "Historical Download Manager shell opened."


    def _open_ohlcv_maintenance(self, parent: LeonardoMainWindow) -> str:
        if self._ohlcv_maintenance_window is None:
            window = OhlcvMaintenanceWindow(parent=parent)
            presenter = OhlcvMaintenancePresenter(
                window,
                getattr(self._context, "ohlcv_maintenance_service"),
            )
            self._ohlcv_maintenance_window = window
            self._ohlcv_maintenance_presenter = presenter
            self._register_window_actions(window, "ohlcv_maintenance.window")
            self._install_tracker(
                window,
                "ohlcv_maintenance.window",
                "OHLCV Maintenance",
                "workflow",
            )
        else:
            self._ohlcv_maintenance_presenter.refresh()
        self._show_window(self._ohlcv_maintenance_window)
        return "OHLCV Maintenance opened."

    def _open_suite_shell(self, action_id: str, parent: LeonardoMainWindow) -> str:
        if action_id == "main_window.open_research_suite":
            return self._open_research_suite(parent)
        mapping = {
            "main_window.open_data_manager_suite": (
                "_data_manager_suite_window",
                DataManagerSuiteWindow,
                "data_manager_suite.window",
                "Data Manager Suite",
            ),
            "main_window.open_analysis_suite": (
                "_analysis_suite_window",
                AnalysisSuiteWindow,
                "analysis_suite.window",
                "Analysis Suite",
            ),
            "main_window.open_trading_suite": (
                "_trading_suite_window",
                TradingSuiteWindow,
                "trading_suite.window",
                "Trading Suite",
            ),
        }
        try:
            attr_name, factory, window_id, title = mapping[action_id]
        except KeyError as error:
            raise ValueError(f"Unsupported suite shell action ID: {action_id}") from error
        window = getattr(self, attr_name)
        if window is None:
            window = factory(action_observer=self._action_observer, parent=parent)
            setattr(self, attr_name, window)
            self._register_window_actions(window, window_id)
            self._install_tracker(window, window_id, title, "suite")
        self._show_window(window)
        return f"{title} shell opened."

    def _open_research_suite(self, parent: LeonardoMainWindow) -> str:
        if (
            self._research_suite_window is None
            or self._research_suite_presenter is None
            or self._research_suite_presenter.is_disposed
        ):
            window = ResearchSuiteWindow(
                action_observer=self._action_observer,
                floating_window_tracker=self._install_tracker,
                parent=parent,
            )
            presenter = ResearchSuitePresenter(
                window,
                getattr(self._context, "research_dataset_service"),
                getattr(self._context, "research_study_service"),
            )
            self._research_suite_window = window
            self._research_suite_presenter = presenter
            self._register_window_actions(window, "research_suite.window")
            self._install_tracker(
                window,
                "research_suite.window",
                "Research Suite",
                "suite",
            )
        self._show_window(self._research_suite_window)
        return "Research Suite opened."

    def _register_window_actions(self, window: object, window_id: str) -> None:
        observer = self._action_observer
        if observer is None:
            return
        action_ids = getattr(window, "action_ids", None)
        action_labels = getattr(window, "action_labels", None)
        if callable(action_ids):
            labels = action_labels() if callable(action_labels) else {}
            for action_id in action_ids():
                observer.register_action(
                    action_id,
                    label=labels.get(action_id, action_id),
                    window_id=window_id,
                )
        buttons = getattr(window, "_buttons", None)
        if isinstance(buttons, dict):
            for button_id, button in buttons.items():
                property_value = button.property("action_id") if hasattr(button, "property") else None
                action_id = property_value if isinstance(property_value, str) and property_value else button_id
                label = button.text() if hasattr(button, "text") else action_id
                observer.register_action(action_id, label=label, window_id=window_id)

    def _install_tracker(
        self,
        window: QWidget,
        window_id: str,
        title: str,
        window_type: str,
    ) -> None:
        if not self._track_windows:
            return
        tracker = GuiWindowTracker(
            window,
            window_id=window_id,
            title=title,
            window_type=window_type,
            registry=self._window_registry,
        )
        self._trackers[window_id] = tracker

    def _close_suite_shells(self) -> None:
        for attr_name in (
            "_connection_suite_window",
            "_historical_download_manager_window",
            "_ohlcv_maintenance_window",
            "_research_suite_window",
            "_data_manager_suite_window",
            "_analysis_suite_window",
            "_trading_suite_window",
            "_runtime_manager_window",
        ):
            window = getattr(self, attr_name)
            if window is not None:
                window.close()

    @staticmethod
    def _show_window(window: QWidget) -> None:
        window.show()
        window.raise_()
        window.activateWindow()
