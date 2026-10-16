"""Property tests for the planner over random items, zones, quiet hours and submissions."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, replace
from itertools import pairwise
from datetime import UTC, datetime, time, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import (
    DIGEST_FOLD,
    REMINDER_KINDS,
    Item,
    Send,
    SendKind,
    Settings,
)
from canvas_tracker.domain.status import is_active
from canvas_tracker.planning.timeutil import in_quiet
from tests.factories import make_item, make_settings
from tests.planning_sim import simulate

settings.register_profile("ci", max_examples=200, deadline=None)
settings.register_profile("dev", max_examples=50, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

ZONES = [
    "America/New_York",
    "Europe/Berlin",
    "Europe/Dublin",
    "Asia/Kolkata",
    "Australia/Lord_Howe",
    "Pacific/Kiritimati",
]
BASE = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)  # the window crosses both fall-back changes
STEP = timedelta(minutes=10)
HORIZON = timedelta(days=3)
QUIET_KINDS = frozenset(
    {
        SendKind.REMINDER,
        SendKind.NEW_URGENT,
        SendKind.SNOOZE_END,
        SendKind.OVERDUE,
        SendKind.AUTH_ALERT,
    }
)
NAG_KINDS = frozenset({SendKind.REMINDER, SendKind.NEW_URGENT, SendKind.SNOOZE_END})


@dataclass(frozen=True)
class Scenario:
    settings: Settings
    start: datetime
    items: tuple[Item, ...]
    submitted_at: tuple[datetime | None, ...]

    def items_at(self, t: datetime) -> tuple[Item, ...]:
        return tuple(
            replace(item, submitted=sub is not None and t >= sub)
            for item, sub in zip(self.items, self.submitted_at, strict=True)
        )


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    zone = draw(st.sampled_from(ZONES))
    quiet = draw(
        st.one_of(
            st.none(),
            st.tuples(st.integers(0, 23), st.integers(0, 23)).filter(lambda p: p[0] != p[1]),
        )
    )
    cfg = (
        make_settings(tz=zone, quiet_start=None, quiet_end=None)
        if quiet is None
        else make_settings(tz=zone, quiet_start=time(quiet[0]), quiet_end=time(quiet[1]))
    )
    start = BASE + timedelta(minutes=draw(st.integers(0, 9 * 24 * 60)))
    count = draw(st.integers(0, 6))
    items: list[Item] = []
    subs: list[datetime | None] = []
    for i in range(count):
        due = start + timedelta(minutes=draw(st.integers(-2 * 24 * 60, 5 * 24 * 60)))
        items.append(make_item(plannable_id=1000 + i, due_at=due))
        sub = draw(st.one_of(st.none(), st.integers(0, 3 * 24 * 60)))
        subs.append(None if sub is None else start + timedelta(minutes=sub))
    return Scenario(cfg, start, tuple(items), tuple(subs))


def run(sc: Scenario, replay_check: bool = False) -> list[tuple[datetime, Send]]:
    return simulate(
        sc.items_at, sc.settings, sc.start, sc.start + HORIZON, step=STEP, replay_check=replay_check
    )


def _quiet(sc: Scenario, t: datetime) -> bool:
    return in_quiet(t, sc.settings.zone, sc.settings.quiet_start, sc.settings.quiet_end)


@given(scenarios())
def test_no_key_is_sent_twice(sc: Scenario) -> None:
    counts = Counter(send.key for _t, send in run(sc))
    assert all(n == 1 for n in counts.values()), counts.most_common(3)


@given(scenarios())
def test_never_nags_about_done_or_past_due_work(sc: Scenario) -> None:
    for t, send in run(sc):
        if send.kind not in NAG_KINDS:
            continue
        by_ref = {item.ref: item for item in sc.items_at(t)}
        for ref in send.item_refs:
            item = by_ref[ref]
            assert not is_done(item), (t, send)
            assert item.due_at is not None and item.due_at > t, (t, send)


@given(scenarios())
def test_nothing_but_digest_and_overnight_inside_quiet_hours(sc: Scenario) -> None:
    for t, send in run(sc):
        assert not (send.kind in QUIET_KINDS and _quiet(sc, t)), (t, send)


@given(scenarios())
def test_active_items_are_reminded_at_least_every_interval(sc: Scenario) -> None:
    log = run(sc)
    span = sc.settings.reminder_interval + DIGEST_FOLD + STEP
    for ref in {item.ref for item in sc.items}:
        covering = [t for t, s in log if s.kind in REMINDER_KINDS and ref in s.item_refs]
        t = sc.start
        run_start: datetime | None = None
        while t <= sc.start + HORIZON:
            item = next(i for i in sc.items_at(t) if i.ref == ref)
            live = (
                t < sc.start + HORIZON
                and is_active(item, t, sc.settings, None)
                and not _quiet(sc, t)
            )
            if live and run_start is None:
                run_start = t
            elif not live and run_start is not None:
                points = [run_start, *[c for c in covering if run_start <= c < t], t]
                gaps = [b - a for a, b in pairwise(points)]
                assert max(gaps) <= span, (ref, run_start, t, covering)
                run_start = None
            t += STEP


@given(scenarios())
def test_replaying_any_tick_is_a_no_op(sc: Scenario) -> None:
    run(sc, replay_check=True)
