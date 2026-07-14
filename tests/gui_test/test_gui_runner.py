from __future__ import annotations

import pytest

from leonardo.gui.runner import LeonardoGuiRunner


class _FakeApp:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.context = object()
        self.calls: list[str] = []
        self._fail_at = fail_at

    def startup(self) -> object:
        self.calls.append("startup")
        if self._fail_at == "startup":
            raise RuntimeError("startup failed")
        return self.context

    def start_core_runtime(self) -> object:
        self.calls.append("start_core_runtime")
        if self._fail_at == "core":
            raise RuntimeError("core failed")
        return self.context

    def shutdown(self) -> None:
        self.calls.append("shutdown")


class _FakeWindow:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def show(self) -> None:
        self._calls.append("show")

    def close(self) -> None:
        self._calls.append("close")


class _FakeComposition:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def create_main_window(self) -> _FakeWindow:
        self._calls.append("compose")
        return _FakeWindow(self._calls)


def _runner(app: _FakeApp, *, event_loop_result: int = 0) -> LeonardoGuiRunner:
    calls = app.calls

    def event_loop(_application: object) -> int:
        calls.append("event_loop")
        if event_loop_result < 0:
            raise RuntimeError("event loop failed")
        return event_loop_result

    return LeonardoGuiRunner(
        app_factory=lambda _config: app,
        qapplication_factory=lambda: object(),
        composition_factory=lambda _context: _FakeComposition(calls),
        theme_applier=lambda _application: calls.append("theme"),
        event_loop_runner=event_loop,
    )


def test_runner_orders_core_gui_and_shutdown() -> None:
    app = _FakeApp()
    assert _runner(app).run() == 0
    assert app.calls == [
        "startup",
        "start_core_runtime",
        "theme",
        "compose",
        "show",
        "event_loop",
        "close",
        "shutdown",
    ]


@pytest.mark.parametrize(
    ("fail_at", "expected_calls"),
    (
        ("startup", ["startup", "shutdown"]),
        ("core", ["startup", "start_core_runtime", "shutdown"]),
    ),
)
def test_runner_shuts_down_when_initialization_fails(
    fail_at: str,
    expected_calls: list[str],
) -> None:
    app = _FakeApp(fail_at=fail_at)
    with pytest.raises(RuntimeError):
        _runner(app).run()
    assert app.calls == expected_calls


def test_runner_closes_window_and_shuts_down_when_event_loop_fails() -> None:
    app = _FakeApp()
    with pytest.raises(RuntimeError, match="event loop failed"):
        _runner(app, event_loop_result=-1).run()
    assert app.calls[-2:] == ["close", "shutdown"]
