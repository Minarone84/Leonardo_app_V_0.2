from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.gui.runner import LeonardoGuiRunner, run_gui_app


class FakeBoundaryError(RuntimeError):
    pass


class FakeCoreContext:
    pass


class FakeCoreApp:
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


class FakeQtApplication:
    pass


class FakeOverrideStore:
    def __init__(self, root: Path) -> None:
        self.root = root


class FakeMainWindow:
    def __init__(self, events: list[str], *, close_error: Exception | None = None) -> None:
        self._events = events
        self._close_error = close_error
        self.show_calls = 0
        self.close_calls = 0
        self._events.append("main_window.construct")

    def show(self) -> None:
        self._events.append("main_window.show")
        self.show_calls += 1

    def close(self) -> None:
        self._events.append("main_window.close")
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class FakeComposition:
    def __init__(
        self,
        events: list[str],
        *,
        main_window_error: Exception | None = None,
        window_close_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._main_window_error = main_window_error
        self._window_close_error = window_close_error
        self.create_main_window_calls = 0
        self.main_window: FakeMainWindow | None = None

    def create_main_window(self) -> FakeMainWindow:
        self._events.append("composition.create_main_window")
        self.create_main_window_calls += 1
        if self._main_window_error is not None:
            raise self._main_window_error
        self.main_window = FakeMainWindow(
            self._events,
            close_error=self._window_close_error,
        )
        return self.main_window


class RunnerHarness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        startup_error: Exception | None = None,
        qapplication_error: Exception | None = None,
        override_store_error: Exception | None = None,
        composition_error: Exception | None = None,
        main_window_error: Exception | None = None,
        event_loop_error: Exception | None = None,
        shutdown_error: Exception | None = None,
        window_close_error: Exception | None = None,
    ) -> None:
        self.events: list[str] = []
        self.override_store_root = tmp_path / "overrides"
        self.startup_error = startup_error
        self.qapplication_error = qapplication_error
        self.override_store_error = override_store_error
        self.composition_error = composition_error
        self.main_window_error = main_window_error
        self.event_loop_error = event_loop_error
        self.shutdown_error = shutdown_error
        self.window_close_error = window_close_error
        self.app: FakeCoreApp | None = None
        self.qapplication: FakeQtApplication | None = None
        self.override_roots: list[Path] = []
        self.composition_contexts: list[FakeCoreContext] = []
        self.composition_stores: list[FakeOverrideStore] = []
        self.composition: FakeComposition | None = None
        self.event_loop_applications: list[FakeQtApplication] = []

    def app_factory(self, _config: object | None) -> FakeCoreApp:
        self.events.append("core_app.create")
        self.app = FakeCoreApp(
            self.events,
            startup_error=self.startup_error,
            shutdown_error=self.shutdown_error,
        )
        return self.app

    def qapplication_factory(self) -> FakeQtApplication:
        self.events.append("qapplication.create")
        if self.qapplication_error is not None:
            raise self.qapplication_error
        self.qapplication = FakeQtApplication()
        return self.qapplication

    def override_store_factory(self, root: Path) -> FakeOverrideStore:
        self.events.append("override_store.create")
        self.override_roots.append(root)
        if self.override_store_error is not None:
            raise self.override_store_error
        return FakeOverrideStore(root)

    def composition_factory(
        self,
        context: object,
        override_store: object,
    ) -> FakeComposition:
        self.events.append("composition.create_root")
        assert isinstance(context, FakeCoreContext)
        assert isinstance(override_store, FakeOverrideStore)
        self.composition_contexts.append(context)
        self.composition_stores.append(override_store)
        if self.composition_error is not None:
            raise self.composition_error
        self.composition = FakeComposition(
            self.events,
            main_window_error=self.main_window_error,
            window_close_error=self.window_close_error,
        )
        return self.composition

    def event_loop_runner(self, application: object) -> int:
        self.events.append("event_loop.run")
        assert isinstance(application, FakeQtApplication)
        self.event_loop_applications.append(application)
        if self.event_loop_error is not None:
            raise self.event_loop_error
        return 7

    def build_runner(self) -> LeonardoGuiRunner:
        return LeonardoGuiRunner(
            override_store_root=self.override_store_root,
            app_factory=self.app_factory,
            qapplication_factory=self.qapplication_factory,
            override_store_factory=self.override_store_factory,
            composition_factory=self.composition_factory,
            event_loop_runner=self.event_loop_runner,
        )


def test_runner_orders_startup_composition_event_loop_and_shutdown(
    tmp_path: Path,
) -> None:
    harness = RunnerHarness(tmp_path)

    assert harness.build_runner().run() == 7

    assert harness.events == [
        "core_app.create",
        "core.startup",
        "qapplication.create",
        "override_store.create",
        "composition.create_root",
        "composition.create_main_window",
        "main_window.construct",
        "main_window.show",
        "event_loop.run",
        "main_window.close",
        "core.shutdown",
    ]
    assert harness.app is not None
    assert harness.composition is not None
    assert harness.composition_contexts == [harness.app.context]
    assert harness.composition.create_main_window_calls == 1
    assert harness.composition.main_window is not None
    assert harness.composition.main_window.show_calls == 1
    assert harness.composition.main_window.close_calls == 1
    assert harness.event_loop_applications == [harness.qapplication]


def test_run_gui_app_wrapper_uses_injected_boundaries(tmp_path: Path) -> None:
    harness = RunnerHarness(tmp_path)

    result = run_gui_app(
        override_store_root=harness.override_store_root,
        app_factory=harness.app_factory,
        qapplication_factory=harness.qapplication_factory,
        override_store_factory=harness.override_store_factory,
        composition_factory=harness.composition_factory,
        event_loop_runner=harness.event_loop_runner,
    )

    assert result == 7
    assert harness.events[-2:] == ["main_window.close", "core.shutdown"]


def test_override_store_root_is_required() -> None:
    with pytest.raises(TypeError):
        LeonardoGuiRunner()  # type: ignore[call-arg]


def test_override_store_receives_injected_tmp_path(tmp_path: Path) -> None:
    harness = RunnerHarness(tmp_path)

    harness.build_runner().run()

    assert harness.override_roots == [harness.override_store_root]
    assert harness.override_store_root.parent == tmp_path
    assert harness.override_store_root.exists() is False
    assert harness.composition_stores[0].root == harness.override_store_root


def test_core_startup_failure_prevents_gui_creation(tmp_path: Path) -> None:
    failure = FakeBoundaryError("startup failed")
    harness = RunnerHarness(tmp_path, startup_error=failure)

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events == ["core_app.create", "core.startup"]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 0
    assert harness.qapplication is None
    assert harness.override_roots == []
    assert harness.composition is None


def test_qapplication_failure_triggers_core_shutdown(tmp_path: Path) -> None:
    failure = FakeBoundaryError("qt failed")
    harness = RunnerHarness(tmp_path, qapplication_error=failure)

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events == [
        "core_app.create",
        "core.startup",
        "qapplication.create",
        "core.shutdown",
    ]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


def test_override_store_creation_failure_triggers_core_shutdown(
    tmp_path: Path,
) -> None:
    failure = FakeBoundaryError("override store failed")
    harness = RunnerHarness(tmp_path, override_store_error=failure)

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events == [
        "core_app.create",
        "core.startup",
        "qapplication.create",
        "override_store.create",
        "core.shutdown",
    ]


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
def test_composition_and_main_window_failures_trigger_core_shutdown(
    tmp_path: Path,
    failure_name: str,
    expected_events: list[str],
) -> None:
    failure = FakeBoundaryError(f"{failure_name} failed")
    harness = RunnerHarness(
        tmp_path,
        composition_error=failure if failure_name == "composition" else None,
        main_window_error=failure if failure_name == "main_window" else None,
    )

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events == expected_events
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


def test_event_loop_failure_closes_main_window_and_shuts_down_core(
    tmp_path: Path,
) -> None:
    failure = FakeBoundaryError("event loop failed")
    harness = RunnerHarness(tmp_path, event_loop_error=failure)

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events[-3:] == [
        "event_loop.run",
        "main_window.close",
        "core.shutdown",
    ]
    assert harness.composition is not None
    assert harness.composition.main_window is not None
    assert harness.composition.main_window.close_calls == 1
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


def test_shutdown_failure_is_surfaced_on_normal_exit(tmp_path: Path) -> None:
    failure = FakeBoundaryError("shutdown failed")
    harness = RunnerHarness(tmp_path, shutdown_error=failure)

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events[-2:] == ["main_window.close", "core.shutdown"]


def test_shutdown_failure_is_chained_from_primary_failure(tmp_path: Path) -> None:
    event_loop_failure = FakeBoundaryError("event loop failed")
    shutdown_failure = FakeBoundaryError("shutdown failed")
    harness = RunnerHarness(
        tmp_path,
        event_loop_error=event_loop_failure,
        shutdown_error=shutdown_failure,
    )

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is shutdown_failure
    assert exc_info.value.__cause__ is event_loop_failure


def test_window_close_failure_is_surfaced_after_core_shutdown(tmp_path: Path) -> None:
    failure = FakeBoundaryError("close failed")
    harness = RunnerHarness(tmp_path, window_close_error=failure)

    with pytest.raises(FakeBoundaryError) as exc_info:
        harness.build_runner().run()

    assert exc_info.value is failure
    assert harness.events[-2:] == ["main_window.close", "core.shutdown"]
    assert harness.app is not None
    assert harness.app.shutdown_calls == 1


def test_runner_avoids_production_path_policy_and_source_metadata_mutation(
    tmp_path: Path,
) -> None:
    before = _metadata_sources()
    harness = RunnerHarness(tmp_path)

    harness.build_runner().run()

    assert _metadata_sources() == before
    source = _runner_source()
    assert "tmp_dir" not in source
    assert "runs_dir" not in source
    assert "Path.cwd" not in source
    assert ".home" not in source


def test_runner_does_not_own_runtime_manager_selector_or_settings_ui() -> None:
    source = _runner_source()

    assert "RuntimeManagerBackend" not in source
    assert "RuntimeManagerWindow" not in source
    assert "SettingsInspectorWindow" not in source
    assert "selector" not in source.lower()


def test_runner_tests_and_source_do_not_call_real_event_loop_directly() -> None:
    forbidden = "." + "ex" + "ec" + "()"

    assert forbidden not in Path(__file__).read_text(encoding="utf-8")
    assert forbidden not in _runner_source()


def test_core_and_gui_window_boundaries_remain_separate() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    core_root = repo_root / "src" / "leonardo" / "core"
    windows_root = repo_root / "src" / "leonardo" / "gui" / "windows"

    for path in core_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from leonardo.gui" not in source
        assert "import leonardo.gui" not in source
        assert "PySide6" not in source
        assert "PyQt6" not in source

    for path in windows_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "leonardo.core.app" not in source
        assert "Leonardo" + "App" not in source


def _runner_source() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "src" / "leonardo" / "gui" / "runner.py").read_text(
        encoding="utf-8"
    )


def _metadata_sources() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[2]
    metadata_root = repo_root / "src" / "leonardo" / "gui" / "metadata" / "windows"
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(metadata_root.glob("*.toml"))
    }
