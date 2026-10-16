"""Pure simulation of the planner over time, for tests.

Each step builds a Snapshot from the scenario's items at that instant plus the
simulated sent keys, cycle and last-reminded times, calls ``plan()`` and
applies the result the way the runtime does.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from canvas_tracker.domain.models import REMINDER_KINDS, Cycle, Item, Send, Settings, Snapshot
from canvas_tracker.planning.plan import plan

ItemsAt = Callable[[datetime], tuple[Item, ...]]


def snapshot_at(
    t: datetime,
    items: tuple[Item, ...],
    sent: set[str],
    last: dict[str, datetime],
    cycle: Cycle | None,
    auth_failed_since: datetime | None = None,
) -> Snapshot:
    return Snapshot(
        items=items,
        courses={},
        groups={},
        sent_keys=frozenset(sent),
        last_reminded_at=dict(last),
        cycle=cycle,
        pause_until=None,
        last_successful_sync_at=t,
        auth_failed_since=auth_failed_since,
    )


def simulate(
    items_by_time: ItemsAt,
    settings: Settings,
    start: datetime,
    end: datetime,
    step: timedelta = timedelta(seconds=60),
    crash_on: frozenset[str] = frozenset(),
    auth_failed_since: datetime | None = None,
    replay_check: bool = False,
) -> list[tuple[datetime, Send]]:
    """Run the planner from ``start`` to ``end``; return every (time, send).

    A key in ``crash_on`` is "sent but not recorded" once, modelling a crash
    between sending and marking it sent. With ``replay_check``, every step is
    re-planned after applying its results and must produce no sends.
    """
    sent: set[str] = set()
    last: dict[str, datetime] = {}
    cycle: Cycle | None = None
    crashed: set[str] = set()
    log: list[tuple[datetime, Send]] = []
    t = start
    while t < end:
        items = items_by_time(t)
        result = plan(t, snapshot_at(t, items, sent, last, cycle, auth_failed_since), settings)
        if result.open_cycle_at is not None:
            cycle = Cycle(anchor=result.open_cycle_at)
        if result.close_cycle:
            cycle = None
        for send in result.sends:
            log.append((t, send))
            if send.key in crash_on and send.key not in crashed:
                crashed.add(send.key)
                continue
            sent.add(send.key)
            if send.kind in REMINDER_KINDS:
                for ref in send.item_refs:
                    last[ref] = t
        if replay_check:
            again = plan(t, snapshot_at(t, items, sent, last, cycle, auth_failed_since), settings)
            assert again.sends == (), f"replay at {t} produced {again.sends}"
        t += step
    return log
