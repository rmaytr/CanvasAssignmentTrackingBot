"""The consolidated reminder cycle (every 2 hours by default) and its one-off alerts (PRD §7.5).

All timing is in UTC durations from the cycle anchor, never wall-clock slots,
so clock changes can't shift or duplicate reminders.
"""

from __future__ import annotations

from datetime import datetime, timedelta

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


def _next_after(now: datetime, anchor: datetime, interval: timedelta) -> datetime:
    """The first slot of the cycle (``anchor``, ``interval``) that is after ``now``."""
    if now < anchor:
        return anchor
    return anchor + ((now - anchor) // interval + 1) * interval


def _rebased(now: datetime, snap: Snapshot, interval: timedelta) -> datetime | None:
    """The new anchor when the reminder interval changed mid-cycle, else None.

    Slot numbers only mean something for the interval they were counted with, so
    the cycle restarts on the new interval from its latest slot: a slot that is
    still owed (in its grace period, not sent) becomes slot 0 of the new cycle;
    otherwise the next reminder comes on the new spacing after the latest slot,
    or when it was planned anyway if that is sooner. Either way no key repeats:
    a new anchor is never an old anchor, except when the owed slot is the old
    cycle's slot 0, whose key is then the same one and still unsent.
    """
    cycle = snap.cycle
    if cycle is None or cycle.interval is None or cycle.interval == interval:
        return None
    old = cycle.interval
    if now < cycle.anchor:  # restarted before and nothing sent yet
        return min(cycle.anchor, floor_minute(now) + interval)
    k = (now - cycle.anchor) // old
    latest = cycle.anchor + k * old
    if now - latest <= SLOT_GRACE and reminder_key(cycle.anchor, k) not in snap.sent_keys:
        return latest
    return min(latest + old, _next_after(now, latest, interval))


def next_reminder_at(now: datetime, snap: Snapshot, settings: Settings) -> datetime | None:
    """When the open cycle's next reminder slot is (None: no cycle, or reminders are off)."""
    interval = settings.reminder_interval
    if interval is None or snap.cycle is None:
        return None
    anchor = _rebased(now, snap, interval) or snap.cycle.anchor
    return _next_after(now, anchor, interval)


def plan_cycle(now: datetime, snap: Snapshot, settings: Settings) -> Plan:
    """Open/close the reminder cycle and send the current slot if it is owed.

    With reminders off (``reminder_interval`` None) nothing is sent and no cycle
    opens, but an open one is kept while work is urgent, so turning reminders back
    on continues its rhythm instead of reminding again at once.
    """
    urgent = [i for i in snap.items if is_urgent(i, now, settings)]
    interval = settings.reminder_interval
    if snap.cycle is None:
        if not urgent or interval is None:
            return Plan()
        anchor = floor_minute(now)
        opened: datetime | None = anchor
    else:
        if not urgent:
            return Plan(close_cycle=True)
        if interval is None:
            return Plan()
        opened = _rebased(now, snap, interval)
        anchor = snap.cycle.anchor if opened is None else opened
    if now < anchor:
        return Plan(open_cycle_at=opened)

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


def _next_digest_at(now: datetime, settings: Settings) -> datetime:
    zone = settings.zone
    today = local_date(now, zone)
    at = at_local(today, settings.digest_time, zone)
    return at if at > now else at_local(today + timedelta(days=1), settings.digest_time, zone)


def _new_urgent_rule(
    now: datetime, snap: Snapshot, settings: Settings
) -> tuple[datetime, timedelta]:
    """(horizon, recent): alert an item due by ``horizon`` that wasn't mentioned within
    ``recent`` before its deadline.

    With reminders on, the horizon is the next reminder slot. With them off, it is the
    next morning list, and "mentioned" means since it became urgent: work posted after
    this morning's list and due before the next one gets one heads-up.
    """
    interval = settings.reminder_interval
    if interval is None:
        return _next_digest_at(now, settings), settings.reminder_window
    horizon = next_reminder_at(now, snap, settings) or floor_minute(now) + interval
    return horizon, interval


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

    next_slot, recent = _new_urgent_rule(now, snap, settings)
    new_urgent: list[Send] = []
    snooze_end: list[Send] = []
    for item in _by_due([i for i in snap.items if is_active(i, now, settings, snap.pause_until)]):
        if item.due_at is None:
            continue
        last = snap.last_reminded_at.get(item.ref)
        until = item.snoozed_until
        if until is not None and now - SNOOZE_END_GRACE < until <= now:
            key = snooze_end_key(item)
            if (last is None or last < until) and key not in snap.sent_keys:
                snooze_end.append(Send(key, SendKind.SNOOZE_END, (item.ref,)))
                continue  # the snooze-end message already says it's due soon
        key = new_urgent_key(item)
        if (
            item.due_at <= next_slot
            and (last is None or last < item.due_at - recent)
            and key not in snap.sent_keys
        ):
            new_urgent.append(Send(key, SendKind.NEW_URGENT, (item.ref,)))

    overdue: list[Send] = []
    for item in _by_due([i for i in snap.items if _open_item(i) and not i.stop_reminders]):
        if item.due_at is None:
            continue
        key = overdue_key(item)
        if item.due_at <= now < item.due_at + OVERDUE_NOTICE_GRACE and key not in snap.sent_keys:
            overdue.append(Send(key, SendKind.OVERDUE, (item.ref,)))

    return (*new_urgent, *snooze_end, *overnight, *overdue)
