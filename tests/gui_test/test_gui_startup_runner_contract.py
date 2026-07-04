"""Test-only contract harness for the future GUI startup runner boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest


class FakeBoundaryError(RuntimeError):
    """Raised by fake startup boundaries to model conservative failures."""


@dataclass(frozen=True)
class FakeCoreContext:
    """Minimal Core context marker returned by the fake Core application."""

    context_id: str = "fake-core-context"


class FakeCoreApp:
    """Fake Core application boundary with explicit startup and shutdown hooks."""

    def __init__(
        self,
        events: list[str],
        *,
        startup_error: Exception | None = None,
        shutdown_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._startup_error = startup_error
        self._shutdown_error = shutdown_error
        self.context = FakeCoreContext()
        self.startup_calls = 0
        self.shutdown_calls = 0

    def startup(self) -> FakeCoreContext:
        self._events.append("core.startup")
        self.startup_calls += 1
        if self._startup_error is not None:
            raise self._startup_error
        return self.context

    def shutdown(self) -> None:
        self._events.append("core.shutdown")
        self.shutdown_calls += 1
        if self._shutdown_error is not None:
            raise self._shutdown_error


class FakeQApplicationBoundary:
    """Fake Qt application boundary used instead of a real GUI event loop."""

    def __init__(
        self,
        events: list[str],
        *,
        event_loop_error: Exception | None = None,
        exit_code: int = 0,
    ) -> None:
        self._events = events
        self._event_loop_error = event_loop_error
        self._exit_code = exit_code
        self.event_loop_calls = 0

    def run_event_loop(self) -> int:
        self._events.append("qapplication.event_loop")
        self.event_loop_calls += 1
        if self._event_loop_error is not None:
            raise self._event_loop_error
        return self._exit_code


@dataclass(frozen=True)
class FakeOverrideStore:
    """Fake override store retaining only the injected root path."""

    root: Path


class FakeOverrideStoreFactory:
    """Fake override-store factory that records configured roots."""

    def __init__(
        self,
        events: list[str],
        *,
        error: Exception | None = None,
    ) -> None:
        self._events = events
        self._error = error
        self.roots: list[Path] = []

    def __call__(self, root: Path) -> FakeOverrideStore:
        self._events.append("override_store.create")
        self.roots.append(root)
        if self._error is not None:
            raise self._error
        return FakeOverrideStore(root)


class FakeMainWindow:
    """Fake Main Window that records show and close order."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.show_calls = 0
        self.close_calls = 0
        self._events.append("main_window.construct")

    def show(self) -> None:
        self._events.append("main_window.show")
        self.show_calls += 1

    def close(self) -> None:
        self._events.append("main_window.close")
        self.close_calls += 1


class FakeGuiComposition:
    """Fake GUI composition root that owns Main Window creation."""

    def __init__(
        self,
        events: list[str],
        *,
        main_window_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._main_window_error = main_window_error
        self.main_window: FakeMainWindow | None = None
        self.create_main_window_calls = 0

    def create_main_window(self) -> FakeMainWindow:
        self._events.append("composition.create_main_window")
        self.create_main_window_calls += 1
        if self._main_window_error is not None:
            raise self._main_window_error
        self.main_window = FakeMainWindow(self._events)
        return self.main_window


class FakeGuiCompositionFactory:
    """Fake composition factory that records Core context and override store use."""

    def __init__(
        self,
        events: list[str],
        *,
        composition_error: Exception | None = None,
        main_window_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._composition_error = composition_error
        self._main_window_error = main_window_error
        self.contexts: list[FakeCoreContext] = []
        self.override_stores: list[FakeOverrideStore] = []
        self.compositions: list[FakeGuiComposition] = []

    def __call__(
        self,
        context: FakeCoreContext,
        override_store: FakeOverrideStore,
    ) -> FakeGuiComposition:
        self._events.append("composition.create_root")
        self.contexts.append(context)
        self.override_stores.append(override_store)
        if self._composition_error is not None:
            raise self._composition_error
        composition = FakeGuiComposition(
            self._events,
            main_window_error=self._main_window_error,
        )
        self.compositions.append(composition)
        return composition


def run_gui_startup_contract(
    *,
    app_factory: Callable[[], FakeCoreApp],
    qapplication_factory: Callable[[], FakeQApplicationBoundary],
    override_store_factory: FakeOverrideStoreFactory,
    composition_factory: FakeGuiCompositionFactory,
    override_store_root: Path,
) -> int:
    """
    Model the expected future startup runner sequence with fake boundaries.

    The helper is intentionally local to this test module. It defines ordering
    and failure semantics without constructing production Core or Qt objects.
    """

    app: FakeCoreApp | None = None
    main_window: FakeMainWindow | None = None
    core_started = False
    primary_error: Exception | None = None

    try:
        app = app_factory()
        context = app.startup()
        core_started = True
        qapplication = qapplication_factory()
        override_store = override_store_factory(override_store_root)
        composition = composition_factory(context, override_store)
        main_window = composition.create_main_window()
        main_window.show()
        return qapplication.run_event_loop()
    except Exception as exc:
        primary_error = exc
        raise
    finally:
        if main_window is not None:
            main_window.close()

        if app is not None and core_started:
            try:
                app.shutdown()
            except Exception as shutdown_error:
                if primary_error is not None:
                    raise shutdown_error from primary_error
                raise


class StartupContractHarness:
    """Scenario builder for the test-only startup contract helper."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        startup_error: Exception | None = None,
        qapplication_error: Exception | None = None,
        composition_error: Exception | None = None,
        main_window_error: Exception | None = None,
        event_loop_error: Exception | None = None,
        shutdown_error: Exception | None = None,
    ) -> None:
        self.events: list[str] = []
        self.override_store_root = tmp_path / "configured-overrides"
        self._startup_error = startup_error
        self._qapplication_error = qapplication_error
        self._event_loop_error = event_loop_error
        self._shutdown_error = shutdown_error
        self.app: FakeCoreApp | None = None
        self.qapplication_boundary: FakeQApplicationBoundary | None = None
        self.override_store_factory = FakeOverrideStoreFactory(self.events)
        self.composition_factory = FakeGuiCompositionFactory(
            self.events,
            composition_error=composition_error,
            main_window_error=main_window_error,
        )

    def app_factory(self) -> FakeCoreApp:
        self.events.append("core_app.create")
        self.app = FakeCoreApp(
            self.events,
            startup_error=self._startup_error,
            shutdown_error=self._shutdown_error,
        )
        return self.app

    def qapplication_factory(self) -> FakeQApplicationBoundary:
        self.events.append("qapplication.create")
        if self._qapplication_error is not None:
            raise self._qapplication_error
        self.qapplication_boundary = FakeQApplicationBoundary(
            self.events,
            event_loop_error=self._event_loop_error,
        )
        return self.qapplication_boundary

    def run(self) -> int:
        return run_gui_startup_contract(
            app_factory=self.app_factory,
            qapplication_factory=self.qapplication_factory,
            override_store_factory=self.override_store_factory,
            composition_factory=self.composition_factory,
            override_store_root=self.override_store_root,
        )


def test_successful_sequence_orders_core_gui_loop_and_shutdown(
    tmp_path: Path,
) -> None:
    harness = StartupContractHarness(tmp_path)

    assert harness.run() == 0

    assert harness.events == [
        "core_app.create",
        "core.startup",
        "qapplication.create",
        "override_store.create",
        "composition.create_root",
        "composition.create_main_window",
        "main_window.construct",
        "main_window.show",
        "qapplication.event_loop",
        "main_window.close",
        "core.shutdown",
    ]
    assert harness.app is not None
    assert harness.app.context is harness.composition_factory.contexts[0]
    assert harness.qapplication_boundary is not None
    assert harness.qapplication_boundary.event_loop_calls == 1
    assert harness.composition_factory.compositions[0].create_main_window_calls == 1
    assert harness.composition_factory.compositions[0].main_window is not None
    assert harness.composition_factory.compositions[0].main_window.show_calls == 1
    assert harness.composition_factory.compositions[0].main_window.close_calls == 1


def test_override_store_root_is_injected_and_no_production_writes(
    tmp_path: Path,
) -> None:
    harness = StartupContractHarness(tmp_path)

    harness.run()

    assert harness.override_store_factory.roots == [harness.override_store_root]
    assert harness.override_store_root.parent == tmp_path
    assert harness.override_store_root.exists() is False
    assert harness.composition_factory.override_stores[0].root == (
        harness.override_store_root
    )


def test_core_startup_failure_stops_before_gui_creation(tmp_path: Path) -> None:
    failure = FakeBoundaryError("core startup failed")
    harness = StartupContractHarness(tmp_path, startup_error=failure)

    with pytest.raises(FakeBoundaryError, match="core startup failed"):
        harness.run()

    assert harness.events == [
        "core_app.create",
        "core.startup",
    ]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 0
    assert harness.qapplication_boundary is None
    assert harness.override_store_factory.roots == []
    assert harness.composition_factory.compositions == []


def test_qapplication_failure_after_core_startup_still_shuts_down_core(
    tmp_path: Path,
) -> None:
    failure = FakeBoundaryError("qapplication creation failed")
    harness = StartupContractHarness(tmp_path, qapplication_error=failure)

    with pytest.raises(FakeBoundaryError, match="qapplication creation failed"):
        harness.run()

    assert harness.events == [
        "core_app.create",
        "core.startup",
        "qapplication.create",
        "core.shutdown",
    ]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


@pytest.mark.parametrize(
    ("failure_name", "expected_events"),
    (
        (
            "composition",
            [
                "core_app.create",
                "core.startup",
                "qapplication.create",
                "override_store.create",
                "composition.create_root",
                "core.shutdown",
            ],
        ),
        (
            "main_window",
            [
                "core_app.create",
                "core.startup",
                "qapplication.create",
                "override_store.create",
                "composition.create_root",
                "composition.create_main_window",
                "core.shutdown",
            ],
        ),
    ),
)
def test_composition_or_window_failure_after_core_startup_shuts_down_core(
    tmp_path: Path,
    failure_name: str,
    expected_events: list[str],
) -> None:
    failure = FakeBoundaryError(f"{failure_name} failed")
    harness = StartupContractHarness(
        tmp_path,
        composition_error=failure if failure_name == "composition" else None,
        main_window_error=failure if failure_name == "main_window" else None,
    )

    with pytest.raises(FakeBoundaryError, match=f"{failure_name} failed"):
        harness.run()

    assert harness.events == expected_events
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


def test_event_loop_failure_closes_window_then_shutdown_and_surfaces_failure(
    tmp_path: Path,
) -> None:
    failure = FakeBoundaryError("event loop failed")
    harness = StartupContractHarness(tmp_path, event_loop_error=failure)

    with pytest.raises(FakeBoundaryError, match="event loop failed"):
        harness.run()

    assert harness.events[-3:] == [
        "qapplication.event_loop",
        "main_window.close",
        "core.shutdown",
    ]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1
    assert harness.composition_factory.compositions[0].main_window is not None
    assert harness.composition_factory.compositions[0].main_window.close_calls == 1


def test_shutdown_failure_is_surfaced(tmp_path: Path) -> None:
    failure = FakeBoundaryError("shutdown failed")
    harness = StartupContractHarness(tmp_path, shutdown_error=failure)

    with pytest.raises(FakeBoundaryError, match="shutdown failed"):
        harness.run()

    assert harness.events[-2:] == [
        "main_window.close",
        "core.shutdown",
    ]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


def test_harness_uses_fake_boundaries_and_no_production_startup_module(
    tmp_path: Path,
) -> None:
    harness = StartupContractHarness(tmp_path)

    harness.run()

    assert type(harness.app) is FakeCoreApp
    assert type(harness.qapplication_boundary) is FakeQApplicationBoundary
    repo_root = Path(__file__).resolve().parents[2]
    forbidden_startup_modules = [
        repo_root / "src" / "leonardo" / "gui" / "startup.py",
        repo_root / "src" / "leonardo" / "gui" / "runner.py",
        repo_root / "src" / "leonardo" / "gui" / "app.py",
    ]
    assert [path for path in forbidden_startup_modules if path.exists()] == []
