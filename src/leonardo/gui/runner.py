"""Minimal production-capable GUI runner for Leonardo V2."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AppConfig
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.metadata import GuiMetadataOverrideStore
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme


class CoreAppBoundary(Protocol):
    """Core application lifecycle boundary consumed by the GUI runner."""

    context: object

    def startup(self) -> object:
        """Start Core and return the Core context."""

    def shutdown(self) -> None:
        """Stop Core and release Core-owned resources."""


class MainWindowBoundary(Protocol):
    """Top-level GUI window boundary owned by the runner."""

    def show(self) -> None:
        """Show the top-level GUI window."""

    def close(self) -> None:
        """Close the top-level GUI window."""


class GuiCompositionBoundary(Protocol):
    """GUI composition boundary used to create the Main Window."""

    def create_main_window(self) -> MainWindowBoundary:
        """Create the composed Main Window."""


AppFactory = Callable[[AppConfig | None], CoreAppBoundary]
QApplicationFactory = Callable[[], object]
OverrideStoreFactory = Callable[[Path], object]
CompositionFactory = Callable[[object, object], GuiCompositionBoundary]
EventLoopRunner = Callable[[object], int]
ThemeApplier = Callable[[object], None]


class LeonardoGuiRunner:
    """
    Coordinate Core startup with GUI composition and Qt application ownership.

    The runner owns the top-level GUI startup sequence. It constructs and starts
    `LeonardoApp`, creates or reuses the Qt application boundary, injects an
    explicitly configured GUI override root into composition, shows the composed
    Main Window, runs the event-loop boundary, then closes GUI windows before
    shutting Core down.

    The runner does not define a CLI entry point or production override-root
    policy. Tests can replace every external boundary to avoid a real Qt event
    loop and filesystem writes outside `tmp_path`.
    """

    def __init__(
        self,
        *,
        override_store_root: Path | str,
        config: AppConfig | None = None,
        app_factory: AppFactory | None = None,
        qapplication_factory: QApplicationFactory | None = None,
        override_store_factory: OverrideStoreFactory | None = None,
        composition_factory: CompositionFactory | None = None,
        event_loop_runner: EventLoopRunner | None = None,
        theme_applier: ThemeApplier | None = None,
    ) -> None:
        if override_store_root is None:
            raise TypeError("override_store_root is required")
        self._override_store_root = Path(override_store_root)
        self._config = config
        self._app_factory = app_factory or _default_app_factory
        self._qapplication_factory = qapplication_factory or _default_qapplication_factory
        self._override_store_factory = (
            override_store_factory or _default_override_store_factory
        )
        self._composition_factory = composition_factory or _default_composition_factory
        self._event_loop_runner = event_loop_runner or _default_event_loop_runner
        self._theme_applier = theme_applier or _default_theme_applier

    @property
    def override_store_root(self) -> Path:
        """Return the explicit GUI override root used by this runner."""

        return self._override_store_root

    def run(self) -> int:
        """
        Run the minimal GUI startup sequence.

        Returns
        -------
        int
            Exit code returned by the configured event-loop boundary.

        Raises
        ------
        Exception
            Re-raises startup, construction, event-loop, close, or shutdown
            failures. Shutdown failures are surfaced and chained from a primary
            failure when one exists.
        """

        app: CoreAppBoundary | None = None
        main_window: MainWindowBoundary | None = None
        core_started = False
        primary_error: Exception | None = None

        try:
            app = self._app_factory(self._config)
            app.startup()
            core_started = True

            qapplication = self._qapplication_factory()
            self._theme_applier(qapplication)
            override_store = self._override_store_factory(self._override_store_root)
            composition = self._composition_factory(app.context, override_store)
            main_window = composition.create_main_window()
            main_window.show()
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

            if app is not None and core_started:
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
    override_store_root: Path | str,
    config: AppConfig | None = None,
    app_factory: AppFactory | None = None,
    qapplication_factory: QApplicationFactory | None = None,
    override_store_factory: OverrideStoreFactory | None = None,
    composition_factory: CompositionFactory | None = None,
    event_loop_runner: EventLoopRunner | None = None,
    theme_applier: ThemeApplier | None = None,
) -> int:
    """
    Run the minimal Leonardo GUI startup sequence.

    This function is a convenience wrapper around `LeonardoGuiRunner`. It does
    not install an entry point, derive a production override path, or create any
    command-line behavior.
    """

    return LeonardoGuiRunner(
        override_store_root=override_store_root,
        config=config,
        app_factory=app_factory,
        qapplication_factory=qapplication_factory,
        override_store_factory=override_store_factory,
        composition_factory=composition_factory,
        event_loop_runner=event_loop_runner,
        theme_applier=theme_applier,
    ).run()


def _default_app_factory(config: AppConfig | None) -> CoreAppBoundary:
    return LeonardoApp(config)


def _default_qapplication_factory() -> object:
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    return application


def _default_override_store_factory(root: Path) -> GuiMetadataOverrideStore:
    return GuiMetadataOverrideStore(root)


def _default_composition_factory(
    context: object,
    override_store: object,
) -> GuiCompositionBoundary:
    if not isinstance(override_store, GuiMetadataOverrideStore):
        raise TypeError("override_store must be a GuiMetadataOverrideStore")
    return GuiCompositionRoot(context, override_store=override_store)


def _default_event_loop_runner(application: object) -> int:
    event_loop = getattr(application, "exec")
    return int(event_loop())


def _default_theme_applier(application: object) -> None:
    apply_theme_stylesheet(application, load_default_theme())
