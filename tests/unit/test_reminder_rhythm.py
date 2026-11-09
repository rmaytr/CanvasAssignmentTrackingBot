"""Per-user reminder rhythm in the planner: interval (or off), urgency window, lookahead."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from canvas_tracker.domain.models import Cycle, Plan, Send, SendKind, Settings
from canvas_tracker.planning.plan import plan
from canvas_tracker.planning.reminders import next_reminder_at, plan_alerts, plan_cycle
from tests.factories import NOW, make_item, make_settings, make_snapshot
from tests.planning_sim import simulate

NYZ = ZoneInfo("America/New_York")
H = timedelta(hours=1)
TWO_H = make_settings()  # quiet 00:00-08:00, morning list 08:00, every 2 h
ONE_H = make_settings(reminder_interval=H)
OFF = make_settings(reminder_interval=None)


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NYZ).astimezone(UTC)


def cycle(anchor: datetime, interval: timedelta | None = 2 * H) -> Cycle:
    return Cycle(anchor=anchor, interval=interval)


def reminder_times(log: list[tuple[datetime, Send]]) -> list[datetime]:
    return [t for t, s in log if s.kind is SendKind.REMINDER]


# --- interval "off" ---------------------------------------------------------------


def test_off_sends_no_repeating_reminder_and_opens_no_cycle() -> None:
    item = make_item(due_in=5 * H)
    assert plan_cycle(NOW, make_snapshot([item]), OFF) == Plan()


def test_off_keeps_an_open_cycle_while_work_is_urgent_and_closes_it_after() -> None:
    item = make_item(due_in=5 * H)
    snap = make_snapshot([item], cycle=cycle(NOW - 2 * H))
    assert plan_cycle(NOW, snap, OFF) == Plan()  # nothing sent, cycle kept
    done = replace(item, submitted=True)
    assert plan_cycle(NOW, make_snapshot([done], cycle=snap.cycle), OFF) == Plan(close_cycle=True)


def test_turning_reminders_back_on_continues_the_old_rhythm() -> None:
    """Off then on again with the same interval must not re-send the slot already sent."""
    item = make_item(due_in=8 * H)
    anchor = NOW - 2 * H
    sent = frozenset({f"rem:{anchor:%Y-%m-%dT%H:%MZ}:1"})  # the 12:00 slot went out
    later = NOW + timedelta(minutes=10)
    snap = make_snapshot([item], cycle=cycle(anchor), sent_keys=sent)
    assert plan_cycle(later, snap, TWO_H).sends == ()
    assert [s.key for s in plan_cycle(NOW + 2 * H, snap, TWO_H).sends] == [
        f"rem:{anchor:%Y-%m-%dT%H:%MZ}:2"
    ]


def test_off_still_sends_the_morning_list_overnight_overdue_and_snooze_end() -> None:
    overdue = make_item(due_in=timedelta(minutes=-1))
    snoozed = make_item(due_in=3 * H, snoozed_until=NOW - timedelta(minutes=1))
    kinds = {s.kind for s in plan_alerts(NOW, make_snapshot([overdue, snoozed]), OFF)}
    assert kinds == {SendKind.OVERDUE, SendKind.SNOOZE_END}

    night = make_item(due_at=ny(21, 3, 0))  # it was on this morning's list
    listed = make_snapshot([night], last_reminded_at={night.ref: ny(20, 8, 0)})
    overnight = plan_alerts(ny(20, 23, 30), listed, OFF)
    assert [s.kind for s in overnight] == [SendKind.OVERNIGHT]

    morning = plan(ny(20, 8, 0), make_snapshot([make_item(due_at=ny(20, 20, 0))]), OFF)
    assert [s.kind for s in morning.sends] == [SendKind.DIGEST]


def test_off_alerts_once_for_work_posted_after_the_morning_list_and_due_before_the_next() -> None:
    new = make_item(due_at=ny(20, 23, 0))  # posted at noon, due tonight
    alerts = plan_alerts(NOW, make_snapshot([new]), OFF)
    assert [s.kind for s in alerts] == [SendKind.NEW_URGENT]
    sent = make_snapshot([new], sent_keys=frozenset(s.key for s in alerts))
    assert plan_alerts(NOW + H, sent, OFF) == ()


def test_off_no_alert_for_work_the_morning_list_already_showed() -> None:
    listed = make_item(due_at=ny(20, 23, 0))
    snap = make_snapshot([listed], last_reminded_at={listed.ref: ny(20, 8, 0)})
    assert plan_alerts(NOW, snap, OFF) == ()


def test_off_with_a_short_window_no_alert_for_work_the_morning_list_showed() -> None:
    """Review: with a 12 h window, work due before the next morning list was on this
    morning's list before it became urgent; it must not be called "just posted"."""
    off_12 = replace(OFF, reminder_window=12 * H)
    listed = make_item(due_at=ny(21, 7, 0))  # due tomorrow 7 AM, on today's 8 AM list
    snap = make_snapshot([listed], last_reminded_at={listed.ref: ny(20, 8, 0)})
    for hour in (9, 12, 19, 20, 23):
        assert plan_alerts(ny(20, hour, 5), snap, off_12) == (), hour
    posted_later = make_item(due_at=ny(21, 7, 0))  # not on the list: still one heads-up
    fresh = make_snapshot([posted_later])
    assert [s.kind for s in plan_alerts(ny(20, 19, 5), fresh, off_12)] == [SendKind.NEW_URGENT]


def test_off_no_alert_for_work_the_next_morning_list_will_show() -> None:
    tomorrow = make_item(due_at=ny(21, 14, 0))  # urgent, but tomorrow's 8 AM list has it
    assert plan_alerts(NOW, make_snapshot([tomorrow]), OFF) == ()


def test_off_over_a_whole_day_sends_only_one_offs() -> None:
    items = (make_item(due_at=ny(21, 18, 0)), make_item(due_at=ny(21, 3, 0)))
    log = simulate(lambda _t: items, OFF, start=ny(20, 7, 0), end=ny(22, 7, 0))
    kinds = [s.kind for _t, s in log]
    assert SendKind.REMINDER not in kinds
    assert kinds.count(SendKind.DIGEST) == 2 and SendKind.OVERNIGHT in kinds


# --- changing the interval mid-cycle ----------------------------------------------


def test_shorter_interval_restarts_the_cycle_without_resending_the_current_slot() -> None:
    """Regression: 2 h -> 1 h at 12:10 used to re-send the 12:00 reminder as slot 2."""
    item = make_item(due_in=10 * H)
    anchor = NOW - 2 * H  # 10:00; slots 0 (10:00) and 1 (12:00) were sent
    sent = frozenset({f"rem:{anchor:%Y-%m-%dT%H:%MZ}:{k}" for k in (0, 1)})
    snap = make_snapshot([item], cycle=cycle(anchor), sent_keys=sent)
    now = NOW + timedelta(minutes=10)
    restart = plan_cycle(now, snap, ONE_H)
    assert restart == Plan(open_cycle_at=NOW + H)  # 1 h after the 12:00 reminder
    moved = make_snapshot([item], cycle=cycle(NOW + H, H), sent_keys=sent)
    assert plan_cycle(now + timedelta(minutes=30), moved, ONE_H).sends == ()
    assert [s.key for s in plan_cycle(NOW + H, moved, ONE_H).sends] == [
        f"rem:{NOW + H:%Y-%m-%dT%H:%MZ}:0"
    ]


def test_a_slot_still_owed_at_the_change_goes_out_once_on_the_new_cycle() -> None:
    item = make_item(due_in=10 * H)
    anchor = NOW - 3 * H  # every 3 h: 09:00 sent, 12:00 due now but not sent yet
    sent = frozenset({f"rem:{anchor:%Y-%m-%dT%H:%MZ}:0"})
    snap = make_snapshot([item], cycle=cycle(anchor, 3 * H), sent_keys=sent)
    now = NOW + timedelta(minutes=2)
    result = plan_cycle(now, snap, TWO_H)
    assert result.open_cycle_at == NOW
    assert [s.key for s in result.sends] == [f"rem:{NOW:%Y-%m-%dT%H:%MZ}:0"]


def test_longer_interval_keeps_the_next_planned_reminder_then_spaces_out() -> None:
    """Regression: 1 h -> 2 h used to skip the slot that came next (its k was already used)."""
    item = make_item(due_in=10 * H)
    anchor = NOW - 2 * H  # hourly: 10:00, 11:00, 12:00 sent
    sent = frozenset({f"rem:{anchor:%Y-%m-%dT%H:%MZ}:{k}" for k in (0, 1, 2)})
    snap = make_snapshot([item], cycle=cycle(anchor, H), sent_keys=sent)
    now = NOW + timedelta(minutes=5)
    assert plan_cycle(now, snap, TWO_H) == Plan(open_cycle_at=NOW + H)  # 13:00 stays
    assert next_reminder_at(now, snap, TWO_H) == NOW + H


def test_a_cycle_whose_interval_is_unknown_keeps_counting_as_before() -> None:
    item = make_item(due_in=10 * H)
    snap = make_snapshot([item], cycle=Cycle(anchor=NOW - 2 * H))
    assert [s.key for s in plan_cycle(NOW, snap, TWO_H).sends] == ["rem:2026-10-20T14:00Z:1"]


def test_nothing_is_sent_before_a_restarted_cycles_first_slot() -> None:
    item = make_item(due_in=10 * H)
    snap = make_snapshot([item], cycle=cycle(NOW + H, H))
    assert plan_cycle(NOW, snap, ONE_H) == Plan()
    assert next_reminder_at(NOW, snap, ONE_H) == NOW + H


def test_next_reminder_is_none_without_a_cycle_or_when_off() -> None:
    snap = make_snapshot([make_item(due_in=5 * H)], cycle=cycle(NOW - H))
    assert next_reminder_at(NOW, snap, OFF) is None
    assert next_reminder_at(NOW, make_snapshot([]), TWO_H) is None
    assert next_reminder_at(NOW, snap, TWO_H) == NOW + H


def _switching(before: Settings, after: Settings, at: datetime) -> object:
    return lambda t: after if t >= at else before


def test_switching_intervals_never_doubles_up_or_leaves_a_long_gap() -> None:
    item = make_item(due_at=ny(21, 23, 0))  # urgent for the whole run
    for old, new in ((2, 1), (1, 2), (2, 3), (4, 1), (1, 4), (3, 2)):
        before = make_settings(reminder_interval=old * H, quiet_start=None, quiet_end=None)
        after = replace(before, reminder_interval=new * H)
        for minute in (0, 5, 25, 40, 70):
            switch = ny(21, 12, 0) + timedelta(minutes=minute)
            log = simulate(
                lambda _t: (item,),
                _switching(before, after, switch),  # type: ignore[arg-type]
                start=ny(21, 9, 0),
                end=ny(21, 22, 30),
                replay_check=True,
            )
            times = reminder_times(log)
            keys = [s.key for _t, s in log]
            assert len(keys) == len(set(keys)), (old, new, minute)
            gaps = [b - a for a, b in pairwise(times)]
            assert min(gaps) >= min(old, new) * H, (old, new, minute, times)
            assert max(gaps) <= max(old, new) * H, (old, new, minute, times)
            after_switch = [t for t in times if t > switch]
            assert len(after_switch) >= 2, (old, new, minute, times)
            assert all(b - a == new * H for a, b in pairwise(after_switch)), (old, new, minute)


def test_turning_off_and_on_again_mid_cycle_is_seamless() -> None:
    item = make_item(due_at=ny(21, 23, 0))
    on = make_settings(quiet_start=None, quiet_end=None)
    off = replace(on, reminder_interval=None)

    def settings_at(t: datetime) -> Settings:
        return off if ny(21, 12, 5) <= t < ny(21, 12, 20) else on

    log = simulate(lambda _t: (item,), settings_at, start=ny(21, 9, 0), end=ny(21, 17, 0))
    times = [t.astimezone(NYZ).strftime("%H:%M") for t in reminder_times(log)]
    assert times == ["09:00", "11:00", "13:00", "15:00"]


# --- urgency window ------------------------------------------------------------------


def test_the_window_decides_what_counts_as_urgent() -> None:
    item = make_item(due_in=18 * H)
    assert plan_cycle(NOW, make_snapshot([item]), make_settings(reminder_window=12 * H)) == Plan()
    wide = plan_cycle(NOW, make_snapshot([make_item(due_in=40 * H)]), TWO_H)
    assert wide == Plan()
    sends = plan_cycle(
        NOW, make_snapshot([make_item(due_in=40 * H)]), make_settings(reminder_window=48 * H)
    ).sends
    assert [s.kind for s in sends] == [SendKind.REMINDER]
