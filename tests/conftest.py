import pytest


@pytest.fixture(autouse=True)
def configure_test_timezone(monkeypatch):
    """Keep UTC test data independent of the host and deployment environment.

    Tests for other timezones can override this with their own monkeypatch.
    """
    monkeypatch.setenv("CHORETRACKER_TZ", "UTC")
