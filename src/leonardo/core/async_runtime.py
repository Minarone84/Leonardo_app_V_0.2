"""Minimal async helpers for the Leonardo V2 Core task foundation.

Async event-loop ownership is intentionally deferred to a later runner phase.
This module only provides local helpers used by the Core TaskManager.
"""

from __future__ import annotations

import inspect
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def normalize_task_name(task_name: str) -> str:
    """Validate and normalize a human-readable task name."""

    if not isinstance(task_name, str):
        raise TypeError("task_name must be a string")
    normalized = task_name.strip()
    if not normalized:
        raise ValueError("task_name must be a non-empty string")
    return normalized


def is_coroutine_object(value: object) -> bool:
    """Return whether a value is a coroutine object accepted by TaskManager."""

    return inspect.iscoroutine(value)


def close_coroutine_if_needed(value: object) -> None:
    """Close a coroutine object when a submission is rejected before scheduling."""

    if inspect.iscoroutine(value):
        value.close()


CoroutineObject = Coroutine[Any, Any, object]
