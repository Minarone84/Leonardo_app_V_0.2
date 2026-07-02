"""Configuration models for the Leonardo V2 Core runtime foundation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    """
    Filesystem paths used by the Core runtime foundation.

    The model resolves path identity only. Directory creation is owned by later
    runtime or persistence phases.
    """

    repo_root: Path
    runs_dir: Path
    historical_data_dir: Path
    tmp_dir: Path


@dataclass(frozen=True)
class AuditConfig:
    """
    Audit logging configuration.

    The JSONL path is resolved during configuration loading, but directories are
    not created until a durable sink writes an event.
    """

    enabled: bool = True
    memory_max_events: int = 1000
    jsonl_enabled: bool = False
    jsonl_path: Path | None = None


@dataclass(frozen=True)
class AppConfig:
    """Core application configuration for the initial runtime foundation."""

    app_name: str
    environment: str
    paths: RuntimePaths
    audit: AuditConfig
    development_mode: bool = True


def load_default_config(repo_root: Path | str | None = None) -> AppConfig:
    """
    Build the default Core configuration without creating directories.

    Parameters
    ----------
    repo_root:
        Optional repository root. When omitted, the current working directory is
        treated as the runtime root.
    """

    root = Path.cwd() if repo_root is None else Path(repo_root)
    resolved_root = root.resolve(strict=False)
    return AppConfig(
        app_name="Leonardo V2",
        environment="development",
        paths=RuntimePaths(
            repo_root=resolved_root,
            runs_dir=resolved_root / "runs",
            historical_data_dir=resolved_root / "historical_data",
            tmp_dir=resolved_root / "tmp",
        ),
        audit=AuditConfig(
            jsonl_path=resolved_root / "runs" / "audit.jsonl",
        ),
    )
