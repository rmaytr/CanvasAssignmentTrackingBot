from dataclasses import replace
from datetime import UTC, date, datetime

from canvas_tracker.planning.keys import (
    auth_alert_key,
    digest_key,
    new_urgent_key,
    overdue_key,
    overnight_key,
    reminder_key,
    snooze_end_key,
)
from tests.factories import make_item

DUE = datetime(2026, 10, 21, 3, 59, tzinfo=UTC)


def test_keys_have_stable_formats() -> None:
    item = make_item(plannable_type="quiz", plannable_id=7, due_at=DUE)
    snoozed = replace(item, snoozed_until=datetime(2026, 10, 20, 18, 30, 15, tzinfo=UTC))
    assert digest_key(date(2026, 10, 20)) == "digest:2026-10-20"
    assert reminder_key(datetime(2026, 10, 20, 3, 59, tzinfo=UTC), 0) == "rem:2026-10-20T03:59Z:0"
    assert new_urgent_key(item) == "new:quiz-7:2026-10-21T03:59Z"
    assert snooze_end_key(snoozed) == "snz:quiz-7:2026-10-20T18:30Z"
    assert overnight_key(date(2026, 10, 20)) == "overnight:2026-10-20"
    assert overdue_key(item) == "overdue:quiz-7:2026-10-21T03:59Z"
    assert auth_alert_key(datetime(2026, 10, 20, 9, 5, tzinfo=UTC)) == "auth:2026-10-20T09:05Z"


def test_due_change_gives_new_item_keys() -> None:
    item = make_item(due_at=DUE)
    moved = replace(item, due_at=datetime(2026, 10, 23, 3, 59, tzinfo=UTC))
    assert overdue_key(item) != overdue_key(moved)
    assert new_urgent_key(item) != new_urgent_key(moved)
