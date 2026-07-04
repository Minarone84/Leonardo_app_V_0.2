"""Pure GUI app-entry composition helpers for Leonardo V2."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from leonardo.gui.path_policy import resolve_gui_override_store_root


GuiAppRunner = Callable[..., int]
GuiOverrideRootResolver = Callable[[Path | str], Path]


class LeonardoGuiAppEntry:
    """
    Compose explicit GUI settings-path selection with the GUI runner boundary.

    The app-entry helper resolves a caller-provided settings base directory
    through the GUI override path policy, then delegates startup to the runner
    boundary. It does not own platform settings policy, Core lifecycle, Qt
    application lifecycle, filesystem creation, or packaging entry points.
    """

    def __init__(
        self,
        *,
        runner: GuiAppRunner | None = None,
        override_root_resolver: GuiOverrideRootResolver = (
            resolve_gui_override_store_root
        ),
    ) -> None:
        self._runner = runner or _default_runner
        self._override_root_resolver = override_root_resolver

    def run(
        self,
        *,
        settings_base_dir: Path | str,
        config: object | None = None,
    ) -> int:
        """
        Run the GUI through the runner boundary using an explicit settings base.

        Parameters
        ----------
        settings_base_dir:
            Caller-owned settings base directory. The path policy resolves the
            GUI override-store root below this base.
        config:
            Optional configuration object passed through to the runner boundary.

        Returns
        -------
        int
            Result returned by the configured runner boundary.
        """

        override_store_root = self._override_root_resolver(settings_base_dir)
        return int(
            self._runner(
                override_store_root=override_store_root,
                config=config,
            )
        )


def run_gui_app_from_settings_base(
    *,
    settings_base_dir: Path | str,
    config: object | None = None,
    runner: GuiAppRunner | None = None,
    override_root_resolver: GuiOverrideRootResolver = resolve_gui_override_store_root,
) -> int:
    """
    Run the GUI with override storage resolved from an explicit settings base.

    This function is a small composition wrapper around
    ``LeonardoGuiAppEntry``. It does not create a command-line interface,
    package entry point, platform default path, or launcher.
    """

    return LeonardoGuiAppEntry(
        runner=runner,
        override_root_resolver=override_root_resolver,
    ).run(settings_base_dir=settings_base_dir, config=config)


def _default_runner(
    *,
    override_store_root: Path | str,
    config: object | None = None,
) -> int:
    from leonardo.gui.runner import run_gui_app

    return run_gui_app(override_store_root=override_store_root, config=config)
