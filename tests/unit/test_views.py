from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from canvas_tracker.render.views import (
    StatusInfo,
    parse_pause,
    render_status,
    render_today,
    render_week,
)
from tests.factories import NOW, make_item, make_settings, make_snapshot

NY = ZoneInfo("America/New_York")
S = make_settings(canvas_host="canvas.example.edu")


def test_parse_pause_durations_and_until() -> None:
    assert parse_pause("3h", NOW, NY) == NOW + timedelta(hours=3)
    assert parse_pause("90m", NOW, NY) == NOW + timedelta(minutes=90)
    assert parse_pause("until 18:00", NOW, NY) == datetime(2026, 10, 20, 22, 0, tzinfo=UTC)
    assert parse_pause("until 08:00", NOW, NY) == datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    assert parse_pause("off", NOW, NY) is None


@pytest.mark.parametrize("arg", ["0m", "8d", "soon", "", "200h", "until 25:00"])
def test_parse_pause_rejects(arg: str) -> None:
    with pytest.raises(ValueError):
        parse_pause(arg, NOW, NY)


def test_today_includes_overdue_and_urgent_but_not_far_low_items() -> None:
    today = make_item(db_id=1, title="Due tonight", due_in=timedelta(hours=8))
    overdue = make_item(db_id=2, title="Late lab", due_in=timedelta(hours=-5))
    later = make_item(db_id=3, title="Next week", due_in=timedelta(days=6), points_possible=0.0)
    [msg] = render_today(make_snapshot([today, overdue, later]), NOW, S)
    assert "Due tonight" in msg.text and "Late lab" in msg.text and "Next week" not in msg.text
    assert {b.callback_data for row in msg.keyboard for b in row} == {"d:1", "d:2"}


def test_today_empty() -> None:
    [msg] = render_today(make_snapshot(), NOW, S)
    assert "Nothing due today" in msg.text


def test_week_groups_by_tier() -> None:
    urgent = make_item(db_id=1, title="Soon", due_in=timedelta(hours=5))
    low = make_item(db_id=2, title="Someday", due_in=timedelta(days=6), points_possible=0.0)
    beyond = make_item(db_id=3, title="Far", due_in=timedelta(days=9))
    [msg] = render_week(make_snapshot([urgent, low, beyond]), NOW, S)
    text = msg.text
    assert (
        text.index("🔴 URGENT") < text.index("Soon") < text.index("⚪ LOW") < text.index("Someday")
    )
    assert "Far" not in text


def test_status_text() -> None:
    info = StatusInfo(
        last_successful_sync_at=NOW - timedelta(minutes=3),
        auth_failed_since=None,
        next_digest_at=NOW + timedelta(hours=20),
        next_slot_at=None,
        pause_until=None,
        version="0.1.0",
    )
    text = render_status(info, NOW, S).text
    assert "Token: OK" in text and "0.1.0" in text and "Next reminder: none scheduled" in text
    failed = StatusInfo(
        last_successful_sync_at=None,
        auth_failed_since=NOW - timedelta(hours=1),
        next_digest_at=NOW,
        next_slot_at=NOW + timedelta(hours=1),
        pause_until=NOW + timedelta(hours=2),
        version="0.1.0",
    )
    text = render_status(failed, NOW, S).text
    assert "Token: failed since today 11:00 AM" in text and "Last sync: never" in text
    assert "Paused until today 2:00 PM" in text
