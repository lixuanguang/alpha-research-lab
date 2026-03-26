"""Date and timestamp utilities."""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from utils.config_loader import DateUtilsConfig

DAY = timedelta(days=1)


def to_ms(dt: datetime) -> int:
    """Convert a UTC datetime to epoch milliseconds."""
    return int(dt.timestamp() * 1000)


def day_start(d: date) -> datetime:
    """Return midnight UTC for *d*."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def day_end(d: date) -> datetime:
    """Return the last millisecond of *d* in UTC."""
    return day_start(d + DAY) - timedelta(milliseconds=1)


def resolve_period(value: str | int, granularity: str, *, fallback_ms: int | str | None = None) -> tuple[int, str]:
    """Resolve a period-start timestamp (ms) and label from text or a timestamp."""
    raw = DateUtilsConfig.load().period_specs.get(granularity.strip().lower())
    if raw is None:
        raise ValueError(f"Unsupported period granularity {granularity!r}.")

    if isinstance(value, str):
        match = re.search(raw["pattern"], value)
        if match:
            parts = [int(p) for p in match.groups()] + [1, 1]
            timestamp_ms = to_ms(datetime(parts[0], parts[1], parts[2], tzinfo=UTC))
        elif fallback_ms is not None:
            timestamp_ms = int(fallback_ms)
        else:
            raise ValueError(f"Unable to infer period from text {value!r}")
    else:
        timestamp_ms = int(value)

    label_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return timestamp_ms, label_dt.strftime(raw["format"])


def iso_or_none(d: date | None) -> str | None:
    """Return *d* as an ISO-8601 string, or ``None`` if *d* is falsy."""
    return d.isoformat() if d else None


def coerce_date(value: Any, *, label: str = "date") -> date:
    """Coerce a date or ``YYYY-MM-DD`` string to a `date`."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{label} must be a date or YYYY-MM-DD string, got {type(value).__name__}.")
