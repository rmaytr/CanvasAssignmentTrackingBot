from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_tracker.domain.models import Item, Send, SendKind
from tests.factories import make_item, make_settings
from tests.planning_sim import simulate

NY = ZoneInfo("America/New_York")
S = make_settings()


def ny(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=NY).astimezone(UTC)


def local_log(log: list[tuple[datetime, Send]], zone: ZoneInfo = NY) -> list[tuple[str, SendKind]]:
    return [(t.astimezone(zone).strftime("%a %H:%M"), s.kind) for t, s in log]


EXAMPLE_ITEM = make_item(due_at=ny(10, 20, 23, 59))
EXAMPLE_EXPECTED = [
    ("Mon 23:59", SendKind.REMINDER),
    ("Tue 08:00", SendKind.DIGEST),
    *[(f"Tue {h}:59", SendKind.REMINDER) for h in ("09", "11", "13", "15", "17", "19", "21")],
    ("Tue 23:59", SendKind.OVERDUE),
]


def test_prd_worked_example_tuesday_2359() -> None:
    log = simulate(lambda _t: (EXAMPLE_ITEM,), S, start=ny(10, 19, 20), end=ny(10, 21, 1))
    assert local_log(log) == EXAMPLE_EXPECTED


def test_dst_fall_back_day() -> None:
    item = make_item(due_at=ny(11, 1, 23, 59))
    log = simulate(lambda _t: (item,), S, start=ny(10, 31, 20), end=ny(11, 2, 1))
    assert local_log(log) == [
        ("Sun 08:00", SendKind.DIGEST),
        *[(f"Sun {h}:59", SendKind.REMINDER) for h in ("09", "11", "13", "15", "17", "19", "21")],
        ("Sun 23:59", SendKind.OVERDUE),
    ]
    digests = [s for _t, s in log if s.kind is SendKind.DIGEST]
    assert [s.key for s in digests] == ["digest:2026-11-01"]


def test_submission_mid_cycle_stops_reminders() -> None:
    def items(t: datetime) -> tuple[Item, ...]:
        return (replace(EXAMPLE_ITEM, submitted=t >= ny(10, 20, 14, 30)),)

    log = simulate(items, S, start=ny(10, 19, 20), end=ny(10, 21, 1))
    assert local_log(log) == EXAMPLE_EXPECTED[:5]  # ... through the 13:59 reminder
    assert all(t < ny(10, 20, 14, 30) for t, _s in log)


def test_extension_cancels_overdue_and_restarts_later() -> None:
    new_due = ny(10, 22, 23, 59)

    def items(t: datetime) -> tuple[Item, ...]:
        return (replace(EXAMPLE_ITEM, due_at=new_due) if t >= ny(10, 20, 12, 30) else EXAMPLE_ITEM,)

    log = simulate(items, S, start=ny(10, 19, 20), end=ny(10, 22, 1))
    assert SendKind.OVERDUE not in [s.kind for _t, s in log]
    assert local_log(log) == [
        ("Mon 23:59", SendKind.REMINDER),
        ("Tue 08:00", SendKind.DIGEST),
        ("Tue 09:59", SendKind.REMINDER),
        ("Tue 11:59", SendKind.REMINDER),
        ("Wed 08:00", SendKind.DIGEST),
        ("Wed 23:59", SendKind.REMINDER),
    ]
    assert log[-1][1].key == "rem:2026-10-22T03:59Z:0"


def test_last_minute_posting_during_open_cycle_alerts_immediately() -> None:
    a = make_item(due_at=ny(10, 21, 12, 0))
    d = make_item(due_at=ny(10, 20, 23, 30))

    def items(t: datetime) -> tuple[Item, ...]:
        return (a, d) if t >= ny(10, 20, 22, 50) else (a,)

    log = simulate(items, S, start=ny(10, 20, 11), end=ny(10, 20, 23))
    at_2250 = [(s.kind, s.item_refs) for t, s in log if t == ny(10, 20, 22, 50)]
    assert at_2250 == [(SendKind.NEW_URGENT, (d.ref,))]


def test_last_minute_posting_with_no_cycle_opens_one() -> None:
    d = make_item(due_at=ny(10, 20, 23, 30))
    log = simulate(
        lambda t: (d,) if t >= ny(10, 20, 22, 50) else (),
        S,
        start=ny(10, 20, 22),
        end=ny(10, 20, 23),
    )
    assert [(t, s.kind, s.item_refs) for t, s in log] == [
        (ny(10, 20, 22, 50), SendKind.REMINDER, (d.ref,))
    ]


def test_crash_allowance_is_one_duplicate() -> None:
    crash_key = "rem:2026-10-20T03:59Z:5"
    log = simulate(
        lambda _t: (EXAMPLE_ITEM,),
        S,
        start=ny(10, 19, 20),
        end=ny(10, 21, 1),
        crash_on=frozenset({crash_key}),
    )
    counts = Counter(s.key for _t, s in log)
    assert counts[crash_key] == 2
    assert all(n == 1 for key, n in counts.items() if key != crash_key)


def test_auth_alert_once_and_not_in_quiet_hours() -> None:
    log = simulate(
        lambda _t: (),
        S,
        start=ny(10, 20, 2),
        end=ny(10, 20, 10),
        auth_failed_since=ny(10, 20, 3),
    )
    assert [(t, s.kind, s.key) for t, s in log] == [
        (ny(10, 20, 8), SendKind.DIGEST, "digest:2026-10-20"),
        (ny(10, 20, 8), SendKind.AUTH_ALERT, "auth:2026-10-20T07:00Z"),
    ]


def test_dublin_digest_across_negative_dst_change() -> None:
    dublin = make_settings(tz="Europe/Dublin")
    log = simulate(
        lambda _t: (),
        dublin,
        start=datetime(2026, 10, 24, 0, 0, tzinfo=UTC),
        end=datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
        step=timedelta(minutes=10),
    )
    assert [(t, s.key) for t, s in log] == [
        (datetime(2026, 10, 24, 7, 0, tzinfo=UTC), "digest:2026-10-24"),
        (datetime(2026, 10, 25, 8, 0, tzinfo=UTC), "digest:2026-10-25"),
    ]


def test_replay_of_any_tick_is_a_no_op() -> None:
    simulate(
        lambda _t: (EXAMPLE_ITEM,), S, start=ny(10, 19, 20), end=ny(10, 21, 1), replay_check=True
    )


def test_plan_is_deterministic() -> None:
    from canvas_tracker.planning.plan import plan
    from tests.factories import make_snapshot

    snap = make_snapshot([EXAMPLE_ITEM, make_item(due_in=timedelta(minutes=-5))])
    t = ny(10, 20, 12)
    assert plan(t, snap, S) == plan(t, snap, S)
