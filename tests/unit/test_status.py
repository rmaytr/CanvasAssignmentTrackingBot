from datetime import timedelta

import pytest

from canvas_tracker.domain.models import ItemType
from canvas_tracker.domain.status import (
    hours_left,
    is_active,
    is_overdue_accepting,
    is_urgent,
)
from tests.factories import NOW, make_item, make_settings

S = make_settings()
S_OVERDUE = make_settings(overdue_reminders=True)


@pytest.mark.parametrize(
    ("due_in", "expected"),
    [
        (timedelta(hours=24), True),
        (timedelta(hours=24, seconds=1), False),
        (timedelta(0), False),
        (timedelta(seconds=-1), False),
        (timedelta(minutes=1), True),
    ],
)
def test_is_urgent_window_edges(due_in: timedelta, expected: bool) -> None:
    assert is_urgent(make_item(due_in=due_in), NOW, S) is expected


def test_not_urgent_for_events_gone_done_or_undated() -> None:
    assert not is_urgent(make_item(type=ItemType.EVENT, plannable_type="calendar_event"), NOW, S)
    assert not is_urgent(make_item(gone_at=NOW), NOW, S)
    assert not is_urgent(make_item(submitted=True), NOW, S)
    assert not is_urgent(make_item(due_in=None), NOW, S)


def test_overdue_reminders_opt_in() -> None:
    assert is_urgent(make_item(due_in=timedelta(hours=-1)), NOW, S_OVERDUE)
    assert not is_urgent(make_item(due_in=timedelta(hours=-48)), NOW, S_OVERDUE)
    locked = make_item(due_in=timedelta(hours=-1), lock_at=NOW - timedelta(minutes=1))
    assert not is_urgent(locked, NOW, S_OVERDUE)
    stopped = make_item(due_in=timedelta(hours=-1), stop_reminders=True)
    assert not is_urgent(stopped, NOW, S_OVERDUE)


def test_is_active_respects_snooze_and_pause() -> None:
    item = make_item(due_in=timedelta(hours=3))
    from dataclasses import replace

    assert not is_active(replace(item, snoozed_until=NOW + timedelta(minutes=1)), NOW, S, None)
    assert is_active(replace(item, snoozed_until=NOW), NOW, S, None)
    assert not is_active(item, NOW, S, NOW + timedelta(minutes=1))
    assert is_active(item, NOW, S, NOW)
    assert not is_active(replace(item, stop_reminders=True), NOW, S, None)


@pytest.mark.parametrize(
    ("due_in", "expected"),
    [
        (timedelta(days=-6, hours=-23), True),
        (timedelta(days=-7), False),
        (timedelta(0), True),
        (timedelta(seconds=1), False),
    ],
)
def test_is_overdue_accepting_edges(due_in: timedelta, expected: bool) -> None:
    assert is_overdue_accepting(make_item(due_in=due_in), NOW) is expected


def test_overdue_not_accepting_when_locked_or_done() -> None:
    locked = make_item(due_in=timedelta(hours=-1), lock_at=NOW)
    assert not is_overdue_accepting(locked, NOW)
    assert not is_overdue_accepting(make_item(due_in=timedelta(hours=-1), excused=True), NOW)


def test_hours_left() -> None:
    assert hours_left(make_item(due_in=timedelta(hours=5, minutes=30)), NOW) == 5.5
    assert hours_left(make_item(due_in=None), NOW) is None
