"""Pure UTC parsing for Research chart Go-to-Date navigation."""

from __future__ import annotations

from datetime import datetime, timezone
import re


_GO_TO_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:(?: |T)(?P<time>\d{2}:\d{2}(?::\d{2})?))?$"
)


def go_to_input_format_hint(timeframe: str) -> str:
    if not isinstance(timeframe, str) or not timeframe:
        raise ValueError("timeframe must be a non-empty string")
    return (
        "YYYY-MM-DD"
        if timeframe in {"1d", "1w", "1M", "1D", "1W"}
        else "YYYY-MM-DD HH:MM"
    )


def parse_go_to_utc_timestamp(text: str, timeframe: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    go_to_input_format_hint(timeframe)
    match = _GO_TO_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError("enter a UTC date or date and time in the displayed format")
    value = match.group("date")
    supplied_time = match.group("time")
    if supplied_time is not None:
        value = f"{value} {supplied_time}"
    format_text = "%Y-%m-%d"
    if supplied_time is not None:
        format_text += " %H:%M:%S" if supplied_time.count(":") == 2 else " %H:%M"
    try:
        parsed = datetime.strptime(value, format_text).replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError("enter a valid UTC date and time") from error
    return int(parsed.timestamp() * 1_000)
