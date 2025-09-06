from __future__ import annotations

import os
from datetime import datetime, tzinfo, timedelta
from zoneinfo import ZoneInfo


def _configured_tz() -> tzinfo:
    """Return the timezone configured for the application."""
    tz_name = os.getenv("CHORETRACKER_TZ")
    if tz_name:
        return ZoneInfo(tz_name)
    system_tz = datetime.now().astimezone().tzinfo
    return system_tz if system_tz is not None else ZoneInfo("UTC")


def get_now() -> datetime:
    """Return the current time in the configured timezone.

    Uses the ``CHORETRACKER_TZ`` environment variable if set, otherwise
    defaults to the system timezone.
    """
    return datetime.now(_configured_tz())


def parse_datetime(value: str) -> datetime:
    """Parse an ISO formatted datetime string.

    If ``value`` lacks timezone information, apply the timezone configured
    via ``CHORETRACKER_TZ`` (default system timezone).
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_configured_tz())
    return dt


def ensure_tz(dt: datetime | None) -> datetime | None:
    """Ensure ``dt`` is timezone-aware using the configured timezone."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=_configured_tz())
    return dt


def end_of_day(dt: datetime) -> datetime:
    """Return the start of the next day in ``dt``'s timezone."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

