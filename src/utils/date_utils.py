"""Date and timestamp utilities."""

from datetime import UTC, date, datetime, timedelta
from typing import Any


def to_ms(dt: datetime) -> int:
    """Convert a datetime to epoch milliseconds.

    @param dt: UTC-aware datetime to convert.
    @return: Milliseconds since the Unix epoch.
    """
    return int(dt.timestamp() * 1000)


def day_start(value: date) -> datetime:
    """Return the UTC start of a calendar day.

    @param value: Date to convert.
    @return: Midnight UTC for the given date.
    """
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def day_end(value: date) -> datetime:
    """Return the UTC end of a calendar day.

    @param value: Date to convert.
    @return: Final millisecond of the given UTC date.
    """
    return day_start(value + timedelta(days=1)) - timedelta(milliseconds=1)


def coerce_date(value: Any, *, label: str = "date") -> date:
    """Convert a date-like value to a date.

    @param value: Date instance or ISO ``YYYY-MM-DD`` string.
    @param label: Field name used in validation errors.
    @return: Parsed date value.
    @raises ValueError: Raised when value is not a date or ISO date string.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{label} must be a date or YYYY-MM-DD string, got {type(value).__name__}.")
