from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from choretracker.time_utils import ensure_tz, parse_datetime


@pytest.fixture(autouse=True)
def configure_tz(monkeypatch):
    monkeypatch.setenv("CHORETRACKER_TZ", "America/Los_Angeles")


def test_ensure_tz_converts_fixed_offset_to_configured_zone():
    dt = datetime.fromisoformat("2023-10-29T09:00:00-07:00")

    converted = ensure_tz(dt)

    assert isinstance(converted.tzinfo, ZoneInfo)
    assert converted.tzinfo.key == "America/Los_Angeles"
    assert converted.utcoffset() == timedelta(hours=-7)
    # Adding a week should cross the DST boundary and adopt the new offset
    assert (converted + timedelta(days=7)).utcoffset() == timedelta(hours=-8)


def test_parse_datetime_normalizes_timezone():
    dt = parse_datetime("2023-10-29T09:00:00-07:00")

    assert isinstance(dt.tzinfo, ZoneInfo)
    assert dt.tzinfo.key == "America/Los_Angeles"
