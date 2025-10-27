from __future__ import annotations

from datetime import datetime, timezone

DATETIME_OUTPUT_FORMAT = "%Y-%m-%d %H:%M:%S"


def normalize_datetime(value: datetime) -> datetime:
    """Return a timezone-naive UTC datetime."""
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def parse_datetime_string(raw: str) -> datetime:
    """
    Parse event timestamps.

    Accepts ISO 8601 strings that may include a space or 'T' separator as well as a trailing 'Z'.
    """
    cleaned = raw.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("Invalid datetime format, expected ISO 8601 string") from exc

    return normalize_datetime(parsed)


def format_datetime(value: datetime) -> str:
    """Render datetimes consistently for API responses."""
    return normalize_datetime(value).strftime(DATETIME_OUTPUT_FORMAT)


def utc_now_naive() -> datetime:
    """Return the current UTC time without timezone info (for DB compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
