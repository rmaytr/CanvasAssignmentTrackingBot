"""Zone-aware time helpers. Inputs and outputs are UTC unless named ``local``."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def at_local(d: date, t: time, tz: ZoneInfo) -> datetime:
    """The UTC instant of local wall time ``t`` on ``d``.

    Uses fold=0, so a wall time that doesn't exist (a spring-forward gap)
    lands after the gap, and an ambiguous one picks the first occurrence.
    """
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC)


def local_date(instant: datetime, tz: ZoneInfo) -> date:
    return instant.astimezone(tz).date()


def in_quiet(instant: datetime, tz: ZoneInfo, start: time | None, end: time | None) -> bool:
    """Whether ``instant`` falls in the daily quiet window [start, end), which may wrap midnight."""
    if start is None or end is None or start == end:
        return False
    local = instant.astimezone(tz).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end


def next_quiet_window(
    now: datetime, tz: ZoneInfo, start: time, end: time
) -> tuple[datetime, datetime]:
    """The first quiet window (UTC start, UTC end) that starts after ``now``."""
    today = local_date(now, tz)
    for offset in range(-1, 3):
        d = today + timedelta(days=offset)
        window_start = at_local(d, start, tz)
        if window_start > now:
            end_day = d if start < end else d + timedelta(days=1)
            return window_start, at_local(end_day, end, tz)
    raise AssertionError("unreachable: a quiet window starts within two days")


def floor_minute(instant: datetime) -> datetime:
    return instant.replace(second=0, microsecond=0)
