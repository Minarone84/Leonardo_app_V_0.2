from datetime import UTC

import pytest

from leonardo.core.async_runtime import (
    close_coroutine_if_needed,
    is_coroutine_object,
    normalize_task_name,
    utc_now,
)


def test_utc_now_returns_timezone_aware_utc_timestamp() -> None:
    assert utc_now().tzinfo is UTC


def test_normalize_task_name_rejects_empty_names() -> None:
    with pytest.raises(ValueError, match="task_name"):
        normalize_task_name("  ")


def test_coroutine_detection_and_close_helper() -> None:
    async def sample() -> None:
        return None

    coroutine = sample()

    assert is_coroutine_object(coroutine) is True
    close_coroutine_if_needed(coroutine)
    assert coroutine.cr_frame is None
