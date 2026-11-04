"""When the email copies are due: the morning list and a heads-up before each deadline.

Email goes alongside Telegram, never instead of it. The deadline email covers every
open item due at the same instant, so several assignments due at 11:59 PM make one
email. Like the Telegram reminders it waits out quiet hours and /pause, and it is
skipped once the deadline has passed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import (
    EMAIL_DEADLINE_LEAD,
    Item,
    Send,
    SendKind,
    Settings,
    Snapshot,
)
from canvas_tracker.domain.status import REMINDABLE_TYPES
from canvas_tracker.planning.digest import plan_digest
from canvas_tracker.planning.keys import email_deadline_key, email_digest_key
from canvas_tracker.planning.timeutil import in_quiet, local_date


def _wants_email(item: Item) -> bool:
    return (
        item.due_at is not None
        and item.type in REMINDABLE_TYPES
        and item.gone_at is None
        and not item.stop_reminders
        and not is_done(item)
    )


def plan_email(now: datetime, snap: Snapshot, settings: Settings) -> tuple[Send, ...]:
    sends: list[Send] = []
    # The same window and contents as the Telegram digest, under its own key, so it still
    # goes out if email is switched on after this morning's Telegram list was sent.
    digest = plan_digest(now, replace(snap, sent_keys=frozenset()), settings)
    if digest is not None:
        key = email_digest_key(local_date(now, settings.zone))
        if key not in snap.sent_keys:
            sends.append(Send(key, SendKind.EMAIL_DIGEST, digest.item_refs))

    paused = snap.pause_until is not None and snap.pause_until > now
    if paused or in_quiet(now, settings.zone, settings.quiet_start, settings.quiet_end):
        return tuple(sends)
    groups: dict[datetime, list[Item]] = defaultdict(list)
    for item in snap.items:
        due = item.due_at
        if due is not None and _wants_email(item) and due - EMAIL_DEADLINE_LEAD <= now < due:
            groups[due].append(item)
    for due_at in sorted(groups):
        key = email_deadline_key(due_at)
        if key not in snap.sent_keys:
            refs = tuple(sorted(i.ref for i in groups[due_at]))
            sends.append(Send(key, SendKind.EMAIL_DEADLINE, refs))
    return tuple(sends)
