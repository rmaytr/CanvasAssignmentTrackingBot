from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_tracker.domain.models import Cycle, Plan, Send, SendKind
from canvas_tracker.planning.reminders import plan_alerts, plan_cycle
from tests.factories import NOW, make_item, make_settings, make_snapshot

NYZ = ZoneInfo("America/New_York")
S = make_settings()  # quiet 00:00-08:00, digest 08:00, interval 2 h
TUE_2359 = datetime(2026, 10, 20, 23, 59, tzinfo=NYZ).astimezone(UTC)


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NYZ).astimezone(UTC)


def cycle_at(anchor: datetime) -> Cycle:
    return Cycle(anchor=anchor)


# --- plan_cycle -----------------------------------------------------------


def test_first_urgent_item_opens_cycle_and_sends_slot_zero() -> None:
    item = make_item(due_in=timedelta(hours=24))
    plan = plan_cycle(NOW, make_snapshot([item]), S)
    assert plan == Plan(
        sends=(Send("rem:2026-10-20T16:00Z:0", SendKind.REMINDER, (item.ref,)),),
        open_cycle_at=NOW,
    )


def test_slot_k_fires_on_its_two_hour_mark() -> None:
    item = make_item(due_in=timedelta(hours=10))
    anchor = NOW - timedelta(hours=2)
    plan = plan_cycle(NOW, make_snapshot([item], cycle=cycle_at(anchor)), S)
    assert [s.key for s in plan.sends] == ["rem:2026-10-20T14:00Z:1"]
    assert plan.open_cycle_at is None


def test_between_slots_nothing_is_sent() -> None:
    item = make_item(due_in=timedelta(hours=10))
    anchor = NOW - timedelta(hours=1)
    snap = make_snapshot(
        [item], cycle=cycle_at(anchor), sent_keys=frozenset({"rem:2026-10-20T15:00Z:0"})
    )
    assert plan_cycle(NOW, snap, S).sends == ()


def test_catch_up_sends_only_the_latest_slot_within_grace() -> None:
    item = make_item(due_in=timedelta(hours=10))
    late20 = plan_cycle(
        NOW, make_snapshot([item], cycle=cycle_at(NOW - timedelta(hours=10, minutes=20))), S
    )
    assert [s.key for s in late20.sends] == ["rem:2026-10-20T05:40Z:5"]
    late40 = plan_cycle(
        NOW, make_snapshot([item], cycle=cycle_at(NOW - timedelta(hours=10, minutes=40))), S
    )
    assert late40.sends == ()


def test_slot_inside_quiet_hours_is_skipped() -> None:
    item = make_item(due_at=TUE_2359)
    snap = make_snapshot([item], cycle=cycle_at(ny(19, 23, 59)))
    assert plan_cycle(ny(20, 3, 59), snap, S).sends == ()


def test_slot_near_digest_time_is_folded_into_the_digest() -> None:
    item = make_item(due_at=TUE_2359)
    snap = make_snapshot([item], cycle=cycle_at(ny(19, 22, 10)))
    assert plan_cycle(ny(20, 8, 10), snap, S).sends == ()
    assert [s.key for s in plan_cycle(ny(20, 10, 10), snap, S).sends] == ["rem:2026-10-20T02:10Z:6"]


def test_cycle_closes_when_nothing_is_urgent() -> None:
    done = make_item(due_in=timedelta(hours=5), submitted=True)
    plan = plan_cycle(NOW, make_snapshot([done], cycle=cycle_at(NOW - timedelta(hours=2))), S)
    assert plan == Plan(close_cycle=True)


def test_done_and_snoozed_items_are_left_out_of_the_slot() -> None:
    a = make_item(due_in=timedelta(hours=5))
    b = make_item(due_in=timedelta(hours=4), submitted=True)
    c = make_item(due_in=timedelta(hours=3), snoozed_until=NOW + timedelta(hours=1))
    d = make_item(due_in=timedelta(hours=2))
    plan = plan_cycle(NOW, make_snapshot([a, b, c, d]), S)
    assert plan.sends[0].item_refs == (d.ref, a.ref)  # nearest deadline first


def test_pause_keeps_the_cycle_but_sends_nothing() -> None:
    item = make_item(due_in=timedelta(hours=5))
    plan = plan_cycle(NOW, make_snapshot([item], pause_until=NOW + timedelta(hours=1)), S)
    assert plan.sends == () and plan.open_cycle_at == NOW


# --- plan_alerts ----------------------------------------------------------


def test_new_item_due_before_next_slot_gets_an_immediate_alert() -> None:
    other = make_item(due_in=timedelta(hours=20))
    d = make_item(due_in=timedelta(hours=1))
    snap = make_snapshot([other, d], cycle=cycle_at(NOW - timedelta(minutes=30)))
    assert plan_alerts(NOW, snap, S) == (
        Send(f"new:{d.ref}:2026-10-20T17:00Z", SendKind.NEW_URGENT, (d.ref,)),
    )


def test_no_new_alert_when_recently_reminded() -> None:
    d = make_item(due_in=timedelta(hours=1))
    snap = make_snapshot(
        [d],
        cycle=cycle_at(NOW - timedelta(minutes=30)),
        last_reminded_at={d.ref: NOW - timedelta(minutes=30)},
    )
    assert plan_alerts(NOW, snap, S) == ()


def test_item_due_after_next_slot_waits_for_the_slot() -> None:
    d = make_item(due_in=timedelta(hours=3))
    snap = make_snapshot([d], cycle=cycle_at(NOW - timedelta(minutes=30)))
    assert plan_alerts(NOW, snap, S) == ()


def test_snooze_end_reminds_once_within_grace() -> None:
    item = make_item(due_in=timedelta(hours=3), snoozed_until=NOW - timedelta(minutes=1))
    snap = make_snapshot([item], cycle=cycle_at(NOW - timedelta(minutes=30)))
    assert plan_alerts(NOW, snap, S) == (
        Send(f"snz:{item.ref}:2026-10-20T15:59Z", SendKind.SNOOZE_END, (item.ref,)),
    )
    stale = replace(item, snoozed_until=NOW - timedelta(minutes=31))
    assert plan_alerts(NOW, make_snapshot([stale], cycle=snap.cycle), S) == ()
    covered = make_snapshot([item], cycle=snap.cycle, last_reminded_at={item.ref: NOW})
    assert plan_alerts(NOW, covered, S) == ()


def test_overnight_warning_at_2330_for_work_due_while_asleep() -> None:
    night = make_item(due_at=ny(21, 3, 0))
    tonight = make_item(due_at=ny(20, 23, 59))
    snap = make_snapshot([night, tonight], cycle=cycle_at(ny(20, 3, 0)))
    sends = [s for s in plan_alerts(ny(20, 23, 30), snap, S) if s.kind is SendKind.OVERNIGHT]
    assert sends == [Send("overnight:2026-10-20", SendKind.OVERNIGHT, (night.ref,))]
    early = [s for s in plan_alerts(ny(20, 23, 29), snap, S) if s.kind is SendKind.OVERNIGHT]
    assert early == []


def test_no_overnight_warning_when_nothing_is_due_overnight() -> None:
    tonight = make_item(due_at=ny(20, 23, 59))
    snap = make_snapshot([tonight], cycle=cycle_at(ny(20, 0, 0)))
    assert [s for s in plan_alerts(ny(20, 23, 30), snap, S) if s.kind is SendKind.OVERNIGHT] == []


def test_overdue_notice_once_right_after_the_deadline() -> None:
    item = make_item(due_in=timedelta(minutes=-1))
    assert plan_alerts(NOW, make_snapshot([item]), S) == (
        Send(f"overdue:{item.ref}:2026-10-20T15:59Z", SendKind.OVERDUE, (item.ref,)),
    )
    sent = make_snapshot([item], sent_keys=frozenset({f"overdue:{item.ref}:2026-10-20T15:59Z"}))
    assert plan_alerts(NOW, sent, S) == ()


def test_no_overdue_notice_after_grace_in_quiet_hours_or_when_stopped() -> None:
    assert plan_alerts(NOW, make_snapshot([make_item(due_in=timedelta(hours=-2))]), S) == ()
    night = make_item(due_at=ny(21, 2, 59))
    assert plan_alerts(ny(21, 3, 0), make_snapshot([night]), S) == ()
    stopped = make_item(due_in=timedelta(minutes=-1), stop_reminders=True)
    assert plan_alerts(NOW, make_snapshot([stopped]), S) == ()


def test_pause_mutes_all_alerts() -> None:
    overdue = make_item(due_in=timedelta(minutes=-1))
    soon = make_item(due_in=timedelta(hours=1))
    snap = make_snapshot(
        [overdue, soon],
        cycle=cycle_at(NOW - timedelta(minutes=30)),
        pause_until=NOW + timedelta(hours=1),
    )
    assert plan_alerts(NOW, snap, S) == ()
