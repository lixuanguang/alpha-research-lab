"""Shared datetime helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def to_timestamp_ms(value: str, fmt: str = "%Y%m%d") -> str:
    '''
    Convert a formatted datetime string to epoch milliseconds.

    @param value: Datetime string to convert.
    @param fmt: Datetime format of the input string.
    @return: Epoch milliseconds as a string.
    '''
    parsed_datetime = datetime.strptime(value, fmt)
    return str(int(parsed_datetime.replace(tzinfo=UTC).timestamp() * 1000))


def shift_date(value: str, days: int = 1, fmt: str = "%Y%m%d") -> str:
    '''
    Shift a formatted date string by a number of days.

    @param value: Date string to shift.
    @param days: Number of days to shift by.
    @param fmt: Date format of the input and output string.
    @return: Shifted date as a string.
    '''
    parsed_date = datetime.strptime(value, fmt).date() + timedelta(days=days)
    return parsed_date.strftime(fmt)


def timestamp_ms_to_string(value: str | int, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    '''
    Convert epoch milliseconds to a formatted UTC datetime string.

    @param value: Epoch milliseconds.
    @param fmt: Output datetime format.
    @return: Formatted UTC datetime string.
    '''
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC).strftime(fmt)
