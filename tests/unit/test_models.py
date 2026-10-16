from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.factories import make_item, make_settings


def test_item_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="due_at must be timezone-aware UTC"):
        make_item(due_at=datetime(2026, 10, 20, 12, 0))  # noqa: DTZ001


def test_item_rejects_non_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC"):
        make_item(due_at=datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("America/New_York")))


def test_item_ref() -> None:
    assert make_item(plannable_type="quiz", plannable_id=7).ref == "quiz-7"


def test_settings_rejects_unknown_zone() -> None:
    with pytest.raises(ValueError):
        make_settings(tz="Mars/Olympus")


def test_settings_rejects_interval_under_30_minutes() -> None:
    with pytest.raises(ValueError):
        make_settings(reminder_interval=timedelta(minutes=29))
