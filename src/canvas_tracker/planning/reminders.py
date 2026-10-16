"""The consolidated 2-hour reminder cycle and its one-off alerts (PRD §7.5).

All timing is in UTC durations from the cycle anchor, never wall-clock slots,
so clock changes can't shift or duplicate reminders.
"""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import (
    DIGEST_FOLD,
    OVERDUE_NOTICE_GRACE,
    OVERNIGHT_LEAD,
    SLOT_GRACE,
    SNOOZE_END_GRACE,
    Item,
    Plan,
    Send,
    SendKind,
    Settings,
    Snapshot,
)
from canvas_tracker.domain.status import REMINDABLE_TYPES, is_active, is_urgent
from canvas_tracker.planning.keys import (
    new_urgent_key,
    overdue_key,
    overnight_key,
    reminder_key,
    snooze_end_key,
)
from canvas_tracker.planning.timeutil import (
    at_local,
    floor_minute,
    in_quiet,
    local_date,
    next_quiet_window,
)


def _by_due(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (i.due_at, i.ref))


def _quiet(instant: datetime, settings: Settings) -> bool:
    return in_quiet(instant, settings.zone, settings.quiet_start, settings.quiet_end)


def _paused(now: datetime, snap: Snapshot) -> bool:
    return snap.pause_until is not None and snap.pause_until > now


def _open_item(item: Item) -> bool:
    return (
        item.due_at is not None
        and item.type in REMINDABLE_TYPES
        and item.gone_at is None
        and not is_done(item)
    )


def plan_cycle(now: datetime, snap: Snapshot, settings: Settings) -> Plan:
    """Open/close the reminder cycle and send the current slot if it is owed."""
    urgent = [i for i in snap.items if is_urgent(i, now, settings)]
    if snap.cycle is None:
        if not urgent:
            return Plan()
        anchor = floor_minute(now)
        opened: datetime | None = anchor
    else:
        if not urgent:
            return Plan(close_cycle=True)
        anchor = snap.cycle.anchor
        opened = None

    interval = settings.reminder_interval
    k = (now - anchor) // interval
    slot = anchor + k * interval
    zone = settings.zone
    digest_at = at_local(local_date(slot, zone), settings.digest_time, zone)
    key = reminder_key(anchor, k)
    skip = (
        now - slot > SLOT_GRACE
        or _quiet(slot, settings)
        or _quiet(now, settings)
        or abs(slot - digest_at) <= DIGEST_FOLD
        or key in snap.sent_keys
    )
    active = _by_due([i for i in urgent if is_active(i, now, settings, snap.pause_until)])
    if skip or not active:
        return Plan(open_cycle_at=opened)
    return Plan(
        sends=(Send(key, SendKind.REMINDER, tuple(i.ref for i in active)),),
        open_cycle_at=opened,
    )


def _next_slot(now: datetime, snap: Snapshot, settings: Settings) -> datetime:
    interval = settings.reminder_interval
    if snap.cycle is None:
        return floor_minute(now) + interval
    anchor = snap.cycle.anchor
    return anchor + ((now - anchor) // interval + 1) * interval


def _overnight(now: datetime, snap: Snapshot, settings: Settings) -> list[Send]:
    start, end = settings.quiet_start, settings.quiet_end
    if start is None or end is None or start == end:
        return []
    zone = settings.zone
    qs, qe = next_quiet_window(now, zone, start, end)
    if not qs - OVERNIGHT_LEAD <= now < qs:
        return []
    due = _by_due(
        [i for i in snap.items if _open_item(i) and i.due_at is not None and qs <= i.due_at < qe]
    )
    key = overnight_key(local_date(qs - OVERNIGHT_LEAD, zone))
    if not due or key in snap.sent_keys:
        return []
    return [Send(key, SendKind.OVERNIGHT, tuple(i.ref for i in due))]


def plan_alerts(now: datetime, snap: Snapshot, settings: Settings) -> tuple[Send, ...]:
    """One-off alerts: new last-minute work, snooze ends, overnight warning, overdue notices."""
    if _paused(now, snap):
        return ()
    overnight = _overnight(now, snap, settings)
    if _quiet(now, settings):
        return tuple(overnight)

    interval = settings.reminder_interval
    next_slot = _next_slot(now, snap, settings)
    new_urgent: list[Send] = []
    snooze_end: list[Send] = []
    for item in _by_due([i for i in snap.items if is_active(i, now, settings, snap.pause_until)]):
        if item.due_at is None:
            continue
        last = snap.last_reminded_at.get(item.ref)
        key = new_urgent_key(item)
        if (
            item.due_at <= next_slot
            and (last is None or last < item.due_at - interval)
            and key not in snap.sent_keys
        ):
            new_urgent.append(Send(key, SendKind.NEW_URGENT, (item.ref,)))
        until = item.snoozed_until
        if until is not None and now - SNOOZE_END_GRACE < until <= now:
            key = snooze_end_key(item)
            if (last is None or last < until) and key not in snap.sent_keys:
                snooze_end.append(Send(key, SendKind.SNOOZE_END, (item.ref,)))

    overdue: list[Send] = []
    for item in _by_due([i for i in snap.items if _open_item(i) and not i.stop_reminders]):
        if item.due_at is None:
            continue
        key = overdue_key(item)
        if item.due_at <= now < item.due_at + OVERDUE_NOTICE_GRACE and key not in snap.sent_keys:
            overdue.append(Send(key, SendKind.OVERDUE, (item.ref,)))

    return (*new_urgent, *snooze_end, *overnight, *overdue)
