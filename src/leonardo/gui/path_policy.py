"""Pure GUI path-policy helpers for metadata override storage."""

from __future__ import annotations

from pathlib import Path


GUI_OVERRIDE_STORE_DIRNAME = "gui_overrides"


class GuiOverridePathPolicy:
    """
    Resolve GUI override storage paths from caller-owned base paths.

    The policy is intentionally pure. It does not inspect filesystem state,
    create directories, write files, select platform-specific locations, import
    Core configuration, import Qt, or construct the override store. Callers own
    the base directory policy and pass the chosen base path explicitly.
    """

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = _coerce_base_dir(base_dir)

    @property
    def base_dir(self) -> Path:
        """Return the caller-owned base directory used for path resolution."""

        return self._base_dir

    @property
    def override_store_root(self) -> Path:
        """Return the deterministic GUI override-store root below the base."""

        return self._base_dir / GUI_OVERRIDE_STORE_DIRNAME


def resolve_gui_override_store_root(base_dir: Path | str) -> Path:
    """
    Resolve the GUI metadata override-store root below an injected base path.

    Parameters
    ----------
    base_dir:
        Caller-owned base directory. The caller is responsible for selecting
        the platform or application policy for this base path.

    Returns
    -------
    pathlib.Path
        Deterministic override-store root under the injected base directory.

    Raises
    ------
    TypeError
        Raised when ``base_dir`` is ``None`` or not path-like for this policy.
    ValueError
        Raised when ``base_dir`` is an empty string.
    """

    return GuiOverridePathPolicy(base_dir).override_store_root


def _coerce_base_dir(base_dir: Path | str) -> Path:
    if base_dir is None:
        raise TypeError("base_dir is required")
    if isinstance(base_dir, str):
        if not base_dir.strip():
            raise ValueError("base_dir must be a non-empty path")
        return Path(base_dir)
    if isinstance(base_dir, Path):
        return base_dir
    raise TypeError("base_dir must be a pathlib.Path or string")
