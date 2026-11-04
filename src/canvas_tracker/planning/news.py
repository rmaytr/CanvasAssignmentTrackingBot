"""Announcements and calendar events: things to know about, not to do.

Each new announcement gets one 📢 message, and each event one 📅 heads-up an hour
before it starts. Neither is ever "due" or "overdue". Both wait out quiet hours and
/pause. Announcements posted before today's morning list are left to that list
(which shows the ones from the last 24 hours not already sent on their own), so
an overnight post doesn't arrive twice.
"""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.models import (
    ANNOUNCEMENT_FRESH,
    EVENT_LEAD,
    Item,
    ItemType,
    Send,
    SendKind,
    Settings,
    Snapshot,
)
from canvas_tracker.planning.keys import announcement_key, event_soon_key
from canvas_tracker.planning.timeutil import at_local, in_quiet, local_date


def _by_date(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (i.due_at, i.ref))


def is_fresh_announcement(item: Item, now: datetime) -> bool:
    return (
        item.type is ItemType.ANNOUNCEMENT
        and item.gone_at is None
        and item.due_at is not None
        and now - ANNOUNCEMENT_FRESH <= item.due_at <= now
    )


def plan_news(now: datetime, snap: Snapshot, settings: Settings) -> tuple[Send, ...]:
    if snap.pause_until is not None and snap.pause_until > now:
        return ()
    if in_quiet(now, settings.zone, settings.quiet_start, settings.quiet_end):
        return ()
    sends: list[Send] = []
    zone = settings.zone
    digest_at = at_local(local_date(now, zone), settings.digest_time, zone)
    for item in _by_date([i for i in snap.items if is_fresh_announcement(i, now)]):
        key = announcement_key(item)
        assert item.due_at is not None  # noqa: S101 - fresh announcements are dated
        in_digest = now >= digest_at and item.due_at < digest_at
        if key not in snap.sent_keys and not in_digest:
            sends.append(Send(key, SendKind.ANNOUNCEMENT, (item.ref,)))
    for item in _by_date([i for i in snap.items if i.type is ItemType.EVENT]):
        start = item.due_at
        if item.gone_at is None and start is not None and start - EVENT_LEAD <= now < start:
            key = event_soon_key(item)
            if key not in snap.sent_keys:
                sends.append(Send(key, SendKind.EVENT_SOON, (item.ref,)))
    return tuple(sends)
