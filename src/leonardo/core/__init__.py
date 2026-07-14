"""Lean runtime infrastructure for Leonardo Light V2."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from leonardo.core.app import CoreContext, LeonardoApp

__all__ = ["CoreContext", "LeonardoApp"]


def __getattr__(name: str):
    if name in __all__:
        from leonardo.core.app import CoreContext, LeonardoApp

        return {"CoreContext": CoreContext, "LeonardoApp": LeonardoApp}[name]
    raise AttributeError(name)
