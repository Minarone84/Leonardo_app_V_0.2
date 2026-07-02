import pytest

from leonardo.contracts.audit import AuditCategory
from leonardo.contracts.runtime import AppLifecycleStatus
from leonardo.core.app import LeonardoApp
from leonardo.core.config import load_default_config


def test_default_config_resolves_runtime_paths_without_creating_directories(tmp_path) -> None:
    config = load_default_config(tmp_path)

    assert config.paths.repo_root == tmp_path.resolve()
    assert config.paths.runs_dir == tmp_path / "runs"
    assert config.paths.historical_data_dir == tmp_path / "historical_data"
    assert config.paths.tmp_dir == tmp_path / "tmp"
    assert not config.paths.runs_dir.exists()


def test_leonardo_app_startup_and_shutdown_transition_state() -> None:
    app = LeonardoApp()

    context = app.startup()

    assert context is app.context
    assert app.state_store.get_app_status() is AppLifecycleStatus.RUNNING
    assert app.contract_registry.get_contract(
        "leonardo.runtime.app_state",
        "1.0",
    ) is not None
    assert app.contract_registry.get_contract(
        "leonardo.runtime.task_state",
        "1.0",
    ) is not None
    assert context.task_manager is app.task_manager

    app.shutdown()
    app.shutdown()

    assert app.state_store.get_app_status() is AppLifecycleStatus.STOPPED


def test_leonardo_app_startup_failure_sets_failed_state_and_routes_error() -> None:
    class FailingApp(LeonardoApp):
        def _register_runtime_contracts(self) -> None:
            raise RuntimeError("contract registration failed")

    app = FailingApp()

    with pytest.raises(RuntimeError, match="contract registration failed"):
        app.startup()

    assert app.state_store.get_app_status() is AppLifecycleStatus.FAILED
    assert any(
        event.category is AuditCategory.ERROR
        and event.event_type == "error.reported"
        for event in app.audit_log.snapshot()
    )
