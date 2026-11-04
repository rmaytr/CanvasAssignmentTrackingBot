from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_tracker.domain.models import EMAIL_KINDS, Send, SendKind
from canvas_tracker.planning.email import plan_email
from canvas_tracker.planning.plan import plan
from tests.factories import make_item, make_settings, make_snapshot
from tests.planning_sim import simulate

NYZ = ZoneInfo("America/New_York")
S = make_settings(email=True)  # quiet 00:00-08:00, digest 08:00


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NYZ).astimezone(UTC)


DUE = ny(20, 23, 59)


def emails(sends: tuple[Send, ...]) -> list[Send]:
    return [s for s in sends if s.kind in EMAIL_KINDS]


def test_no_email_sends_unless_email_is_on() -> None:
    item = make_item(due_at=DUE)
    result = plan(ny(20, 22), make_snapshot([item]), make_settings())
    assert emails(result.sends) == []


def test_morning_email_comes_with_the_telegram_digest() -> None:
    item = make_item(due_at=DUE)
    result = plan(ny(20, 8), make_snapshot([item]), S)
    kinds = [s.kind for s in result.sends]
    assert SendKind.DIGEST in kinds
    assert Send("email:digest:2026-10-20", SendKind.EMAIL_DIGEST, (item.ref,)) in result.sends


def test_morning_email_still_due_when_telegram_digest_already_went_out() -> None:
    snap = make_snapshot([], sent_keys=frozenset({"digest:2026-10-20"}))
    [send] = plan_email(ny(20, 9), snap, S)
    assert send.kind is SendKind.EMAIL_DIGEST


def test_morning_email_sent_once_per_day() -> None:
    snap = make_snapshot([], sent_keys=frozenset({"email:digest:2026-10-20"}))
    assert plan_email(ny(20, 9), snap, S) == ()


def test_deadline_email_two_hours_before() -> None:
    item = make_item(due_at=DUE)
    assert plan_email(ny(20, 21, 58), make_snapshot([item]), S) == ()
    [send] = plan_email(ny(20, 21, 59), make_snapshot([item]), S)
    assert send == Send("email:due:2026-10-21T03:59Z", SendKind.EMAIL_DEADLINE, (item.ref,))


def test_same_deadline_is_one_email_and_other_times_are_separate() -> None:
    a = make_item(due_at=DUE, title="Essay")
    b = make_item(due_at=DUE, title="Quiz")
    c = make_item(due_at=DUE - timedelta(minutes=30), title="Lab")
    sends = plan_email(ny(20, 22, 0), make_snapshot([a, b, c]), S)
    assert [(s.key, s.item_refs) for s in sends] == [
        ("email:due:2026-10-21T03:29Z", (c.ref,)),
        ("email:due:2026-10-21T03:59Z", tuple(sorted((a.ref, b.ref)))),
    ]


def test_deadline_email_skips_done_stopped_gone_and_undated() -> None:
    items = [
        make_item(due_at=DUE, submitted=True),
        make_item(due_at=DUE, stop_reminders=True),
        make_item(due_at=DUE, gone_at=ny(20, 12)),
        make_item(due_in=None),
    ]
    assert plan_email(ny(20, 22), make_snapshot(items), S) == ()


def test_deadline_email_waits_out_quiet_hours_and_pause() -> None:
    morning = make_item(due_at=ny(21, 9))  # window 07:00-09:00, quiet until 08:00
    snap = make_snapshot([morning], sent_keys=frozenset({"email:digest:2026-10-21"}))
    assert plan_email(ny(21, 7, 30), snap, S) == ()
    assert [s.kind for s in plan_email(ny(21, 8, 1), snap, S)] == [SendKind.EMAIL_DEADLINE]
    paused = replace(snap, pause_until=ny(21, 12))
    assert plan_email(ny(21, 8, 1), paused, S) == ()


def test_deadline_email_never_after_the_deadline() -> None:
    item = make_item(due_at=DUE)
    assert plan_email(DUE, make_snapshot([item]), S) == ()


def test_simulation_sends_each_email_exactly_once() -> None:
    a = make_item(due_at=DUE)
    b = make_item(due_at=DUE)
    log = simulate(lambda _t: (a, b), S, start=ny(20, 6), end=ny(21, 1))
    sent = [(t.astimezone(NYZ).strftime("%H:%M"), s.kind) for t, s in log if s.kind in EMAIL_KINDS]
    assert sent == [("08:00", SendKind.EMAIL_DIGEST), ("21:59", SendKind.EMAIL_DEADLINE)]
