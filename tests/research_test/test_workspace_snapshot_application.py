from pathlib import Path


def test_application_service_uses_shared_core_runner_and_task_prefix():
    source = Path("src/leonardo/research/workspace_snapshot_application.py").read_text(
        encoding="utf-8"
    )
    assert "CoreRunner" in source
    assert "research.workspace_snapshot." in source
    assert "ThreadPoolExecutor" not in source
