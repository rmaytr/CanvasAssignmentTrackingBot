"""When the daily digest is due (PRD §7.4)."""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.models import Send, SendKind, Settings, Snapshot
from canvas_tracker.domain.status import is_urgent
from canvas_tracker.planning.keys import digest_key
from canvas_tracker.planning.timeutil import at_local, local_date


def plan_digest(now: datetime, snap: Snapshot, settings: Settings) -> Send | None:
    """The digest send for today's local date, if it is due and not yet sent.

    Due from ``digest_time`` until ``digest_grace_until`` (local). Keyed by the
    local date, so restarts and clock changes can't send it twice.
    """
    zone = settings.zone
    today = local_date(now, zone)
    key = digest_key(today)
    if key in snap.sent_keys:
        return None
    if (
        not at_local(today, settings.digest_time, zone)
        <= now
        < at_local(today, settings.digest_grace_until, zone)
    ):
        return None
    refs = tuple(sorted(i.ref for i in snap.items if is_urgent(i, now, settings)))
    return Send(key, SendKind.DIGEST, refs)
