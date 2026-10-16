from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from canvas_tracker.planning.timeutil import (
    at_local,
    floor_minute,
    in_quiet,
    local_date,
    next_quiet_window,
)

NY = ZoneInfo("America/New_York")


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_spring_forward_gap_moves_forward() -> None:
    assert at_local(date(2027, 3, 14), time(2, 30), NY) == utc(2027, 3, 14, 7, 30)


@pytest.mark.parametrize(
    ("zone", "day", "expected"),
    [
        ("America/New_York", date(2026, 11, 1), utc(2026, 11, 1, 13, 0)),
        ("America/New_York", date(2026, 10, 31), utc(2026, 10, 31, 12, 0)),
        ("Europe/Berlin", date(2026, 10, 25), utc(2026, 10, 25, 7, 0)),
        ("Europe/Berlin", date(2026, 10, 24), utc(2026, 10, 24, 6, 0)),
        ("Europe/Dublin", date(2026, 10, 25), utc(2026, 10, 25, 8, 0)),
        ("Europe/Dublin", date(2026, 10, 24), utc(2026, 10, 24, 7, 0)),
        ("Asia/Kolkata", date(2026, 10, 20), utc(2026, 10, 20, 2, 30)),
        ("Australia/Lord_Howe", date(2026, 10, 4), utc(2026, 10, 3, 21, 0)),
        ("Australia/Lord_Howe", date(2026, 10, 3), utc(2026, 10, 2, 21, 30)),
        ("Pacific/Kiritimati", date(2026, 10, 20), utc(2026, 10, 19, 18, 0)),
    ],
)
def test_digest_instants_across_zones(zone: str, day: date, expected: datetime) -> None:
    result = at_local(day, time(8, 0), ZoneInfo(zone))
    assert result == expected
    assert result.utcoffset() == timedelta(0)


def test_local_date() -> None:
    assert local_date(utc(2026, 10, 21, 3, 59), NY) == date(2026, 10, 20)
    assert local_date(utc(2026, 10, 21, 4, 0), NY) == date(2026, 10, 21)


@pytest.mark.parametrize(
    ("local", "expected"),
    [(time(23, 59), False), (time(0, 0), True), (time(7, 59), True), (time(8, 0), False)],
)
def test_in_quiet_midnight_to_eight(local: time, expected: bool) -> None:
    instant = datetime.combine(date(2026, 10, 20), local, tzinfo=NY).astimezone(UTC)
    assert in_quiet(instant, NY, time(0, 0), time(8, 0)) is expected


@pytest.mark.parametrize(
    ("local", "expected"), [(time(23, 0), True), (time(12, 0), False), (time(6, 59), True)]
)
def test_in_quiet_wrapping_window(local: time, expected: bool) -> None:
    instant = datetime.combine(date(2026, 10, 20), local, tzinfo=NY).astimezone(UTC)
    assert in_quiet(instant, NY, time(22, 0), time(7, 0)) is expected


def test_in_quiet_disabled() -> None:
    assert in_quiet(utc(2026, 10, 20, 6, 0), NY, None, None) is False
    assert in_quiet(utc(2026, 10, 20, 6, 0), NY, time(8, 0), time(8, 0)) is False


def test_next_quiet_window() -> None:
    assert next_quiet_window(utc(2026, 10, 20, 16, 0), NY, time(0, 0), time(8, 0)) == (
        utc(2026, 10, 21, 4, 0),
        utc(2026, 10, 21, 12, 0),
    )


def test_next_quiet_window_skips_current_window() -> None:
    # 02:00 local is inside tonight's window; the next one starts tomorrow at 00:00
    assert next_quiet_window(utc(2026, 10, 21, 6, 0), NY, time(0, 0), time(8, 0)) == (
        utc(2026, 10, 22, 4, 0),
        utc(2026, 10, 22, 12, 0),
    )


def test_next_quiet_window_wrapping() -> None:
    assert next_quiet_window(utc(2026, 10, 20, 16, 0), NY, time(22, 0), time(7, 0)) == (
        utc(2026, 10, 21, 2, 0),
        utc(2026, 10, 21, 11, 0),
    )


def test_floor_minute() -> None:
    assert floor_minute(datetime(2026, 10, 20, 3, 59, 42, 123, tzinfo=UTC)) == utc(
        2026, 10, 20, 3, 59
    )
