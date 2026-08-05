"""Top-level Qt runner for Leonardo Light V2."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from leonardo.core.config import AppConfig


class CoreAppBoundary(Protocol):
    context: object

    def startup(self) -> object: ...
    def start_core_runtime(self) -> object: ...
    def shutdown(self) -> None: ...


class MainWindowBoundary(Protocol):
    def show(self) -> None: ...
    def close(self) -> None: ...


AppFactory = Callable[[AppConfig | None], CoreAppBoundary]
QApplicationFactory = Callable[[], object]
CompositionFactory = Callable[[object], object]
EventLoopRunner = Callable[[object], int]
ThemeApplier = Callable[[object], None]


class LeonardoGuiRunner:
    """Order Core startup, Qt composition, event loop, and shutdown."""

    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        app_factory: AppFactory | None = None,
        qapplication_factory: QApplicationFactory | None = None,
        composition_factory: CompositionFactory | None = None,
        event_loop_runner: EventLoopRunner | None = None,
        theme_applier: ThemeApplier | None = None,
    ) -> None:
        self._config = config
        self._app_factory = app_factory or _default_app_factory
        self._qapplication_factory = qapplication_factory or _default_qapplication_factory
        self._composition_factory = composition_factory or _default_composition_factory
        self._event_loop_runner = event_loop_runner or _default_event_loop_runner
        self._theme_applier = theme_applier or _default_theme_applier

    def run(self) -> int:
        app: CoreAppBoundary | None = None
        main_window: MainWindowBoundary | None = None
        primary_error: Exception | None = None
        try:
            app = self._app_factory(self._config)
            app.startup()
            app.start_core_runtime()
            qapplication = self._qapplication_factory()
            self._theme_applier(qapplication)
            composition = self._composition_factory(app.context)
            main_window = composition.create_main_window()
            main_window.show()
            _schedule_post_show_reconciliation(app.context)
            return int(self._event_loop_runner(qapplication))
        except Exception as exc:
            primary_error = exc
            raise
        finally:
            close_error: Exception | None = None
            if main_window is not None:
                try:
                    main_window.close()
                except Exception as exc:
                    close_error = exc
            if app is not None:
                try:
                    app.shutdown()
                except Exception as shutdown_error:
                    if primary_error is not None:
                        raise shutdown_error from primary_error
                    if close_error is not None:
                        raise shutdown_error from close_error
                    raise
            if close_error is not None and primary_error is None:
                raise close_error


def run_gui_app(
    *,
    config: AppConfig | None = None,
    app_factory: AppFactory | None = None,
    qapplication_factory: QApplicationFactory | None = None,
    composition_factory: CompositionFactory | None = None,
    event_loop_runner: EventLoopRunner | None = None,
    theme_applier: ThemeApplier | None = None,
) -> int:
    return LeonardoGuiRunner(
        config=config,
        app_factory=app_factory,
        qapplication_factory=qapplication_factory,
        composition_factory=composition_factory,
        event_loop_runner=event_loop_runner,
        theme_applier=theme_applier,
    ).run()


def _default_app_factory(config: AppConfig | None) -> CoreAppBoundary:
    from leonardo.core.app import LeonardoApp

    return LeonardoApp(config)


def _default_qapplication_factory() -> object:
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _default_composition_factory(context: object) -> object:
    from leonardo.gui.composition import GuiCompositionRoot

    return GuiCompositionRoot(context)


def _default_event_loop_runner(application: object) -> int:
    return int(getattr(application, "exec")())


def _default_theme_applier(application: object) -> None:
    from leonardo.gui.style import apply_theme_stylesheet, load_default_theme

    apply_theme_stylesheet(application, load_default_theme())


def _schedule_post_show_reconciliation(context: object) -> bool:
    from leonardo.gui.data_manager.reconciliation import (
        schedule_post_show_reconciliation,
    )

    return schedule_post_show_reconciliation(context)
