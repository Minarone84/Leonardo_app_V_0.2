"""Application configuration for Leonardo Light V2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    repo_root: Path
    runs_dir: Path
    historical_data_dir: Path
    tmp_dir: Path
    study_environments_dir: Path
    workspace_snapshots_dir: Path
    research_notebooks_dir: Path


@dataclass(frozen=True)
class AuditConfig:
    enabled: bool = True
    memory_max_events: int = 1000
    jsonl_enabled: bool = False
    jsonl_path: Path | None = None


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    environment: str
    paths: RuntimePaths
    audit: AuditConfig
    actor_id: str = "local-user"
    development_mode: bool = True


def load_default_config(repo_root: Path | str | None = None) -> AppConfig:
    """Build default configuration without creating directories."""

    root = Path.cwd() if repo_root is None else Path(repo_root)
    resolved = root.resolve(strict=False)
    return AppConfig(
        app_name="Leonardo Light V2",
        environment="development",
        paths=RuntimePaths(
            repo_root=resolved,
            runs_dir=resolved / "runs",
            historical_data_dir=resolved / "historical_data",
            tmp_dir=resolved / "tmp",
            study_environments_dir=resolved / "study_environments",
            workspace_snapshots_dir=resolved / "workspace_snapshots",
            research_notebooks_dir=resolved / "research_notebooks",
        ),
        audit=AuditConfig(jsonl_path=resolved / "runs" / "audit.jsonl"),
    )
