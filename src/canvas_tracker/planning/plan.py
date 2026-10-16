"""The whole planner: what the bot owes the student at ``now`` (PRD §9.3).

``plan()`` is pure and deterministic: the same instant, snapshot and settings
always give the same actions, and only actions that are due at ``now``.
"""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.models import Plan, Send, SendKind, Settings, Snapshot
from canvas_tracker.planning.digest import plan_digest
from canvas_tracker.planning.keys import auth_alert_key
from canvas_tracker.planning.reminders import plan_alerts, plan_cycle
from canvas_tracker.planning.timeutil import in_quiet

_COVERABLE = frozenset({SendKind.NEW_URGENT, SendKind.SNOOZE_END})


def plan(now: datetime, snap: Snapshot, settings: Settings) -> Plan:
    sends: list[Send] = []
    digest = plan_digest(now, snap, settings)
    if digest is not None:
        sends.append(digest)
    cycle = plan_cycle(now, snap, settings)
    sends.extend(cycle.sends)

    # A single-item alert is redundant when this plan's digest or reminder already lists it.
    covered = {ref for send in sends for ref in send.item_refs}
    for alert in plan_alerts(now, snap, settings):
        if alert.kind in _COVERABLE and set(alert.item_refs) <= covered:
            continue
        sends.append(alert)

    since = snap.auth_failed_since
    if since is not None and not in_quiet(
        now, settings.zone, settings.quiet_start, settings.quiet_end
    ):
        key = auth_alert_key(since)
        if key not in snap.sent_keys:
            sends.append(Send(key, SendKind.AUTH_ALERT))

    return Plan(
        sends=tuple(sends), open_cycle_at=cycle.open_cycle_at, close_cycle=cycle.close_cycle
    )
