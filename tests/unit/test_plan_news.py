from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from canvas_tracker.domain.models import Item, ItemType, Send, SendKind
from canvas_tracker.domain.status import is_overdue_accepting, is_urgent
from canvas_tracker.planning.news import plan_news
from canvas_tracker.planning.plan import plan
from canvas_tracker.render.alerts import render_send
from canvas_tracker.sources.planner import map_planner_item
from tests.factories import make_item, make_settings, make_snapshot

NYZ = ZoneInfo("America/New_York")
S = make_settings(canvas_host="school.instructure.com")  # quiet 00:00-08:00


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NYZ).astimezone(UTC)


def announcement(posted: datetime, **kw: Any) -> Item:
    return make_item(
        type=ItemType.ANNOUNCEMENT,
        plannable_type="announcement",
        due_at=posted,
        html_url="https://school.instructure.com/courses/1/discussion_topics/5",
        **kw,
    )


def event(start: datetime) -> Item:
    return make_item(type=ItemType.EVENT, plannable_type="calendar_event", due_at=start)


def test_planner_maps_announcements() -> None:
    raw = {
        "plannable_type": "announcement",
        "plannable_id": 5,
        "plannable_date": "2026-10-27T13:00:00Z",
        "plannable": {"title": "Bytes and Bites"},
        "submissions": False,
    }
    item = map_planner_item(raw, "https://school.instructure.com")
    assert item is not None and item.type is ItemType.ANNOUNCEMENT


def test_announcement_is_never_urgent_or_overdue() -> None:
    item = announcement(ny(20, 9))
    now = ny(20, 9, 2)
    assert not is_urgent(item, now, S)
    assert not is_overdue_accepting(item, now)
    kinds = {s.kind for s in plan(now, make_snapshot([item]), S).sends}
    assert SendKind.OVERDUE not in kinds and SendKind.REMINDER not in kinds


def test_new_announcement_sent_once() -> None:
    item = announcement(ny(20, 9))
    [send] = plan_news(ny(20, 9, 5), make_snapshot([item]), S)
    assert send == Send(f"ann:{item.ref}", SendKind.ANNOUNCEMENT, (item.ref,))
    done = make_snapshot([item], sent_keys=frozenset({send.key}))
    assert plan_news(ny(20, 9, 6), done, S) == ()


def test_announcement_waits_out_quiet_hours_and_old_ones_are_skipped() -> None:
    night = announcement(ny(21, 2))
    assert plan_news(ny(21, 2, 1), make_snapshot([night]), S) == ()
    late_digest = replace(S, digest_time=time(9, 0))
    sends = plan_news(ny(21, 8), make_snapshot([night]), late_digest)
    assert [s.kind for s in sends] == [SendKind.ANNOUNCEMENT]
    stale = announcement(ny(19, 9))
    assert plan_news(ny(20, 10), make_snapshot([stale]), S) == ()


def test_event_heads_up_one_hour_before() -> None:
    item = event(ny(20, 18))
    assert plan_news(ny(20, 16, 59), make_snapshot([item]), S) == ()
    [send] = plan_news(ny(20, 17), make_snapshot([item]), S)
    assert send.kind is SendKind.EVENT_SOON
    assert plan_news(ny(20, 18), make_snapshot([item]), S) == ()


def test_news_respects_pause() -> None:
    snap = make_snapshot([announcement(ny(20, 9))], pause_until=ny(20, 12))
    assert plan_news(ny(20, 9, 5), snap, S) == ()


def test_announcement_message_has_only_an_open_button() -> None:
    item = announcement(ny(20, 9), title="Tea ceremony", course_name="Culture")
    snap = make_snapshot([item])
    send = Send("ann:x", SendKind.ANNOUNCEMENT, (item.ref,))
    [msg] = render_send(send, snap, ny(20, 9, 5), S, stale=False)
    assert msg.text.startswith("📢 New announcement\nCulture · <a href=")
    assert "overdue" not in msg.text
    assert [[b.label for b in row] for row in msg.keyboard] == [["🔗 Open"]]


def test_event_message() -> None:
    item = replace(event(ny(20, 18)), title="Midterm review")
    send = Send("evt:x", SendKind.EVENT_SOON, (item.ref,))
    [msg] = render_send(send, make_snapshot([item]), ny(20, 17), S, stale=False)
    assert msg.text == "📅 Event at 6:00 PM (in 1 h 0 m)\nMidterm review"


def test_deadline_email_ignores_announcements() -> None:
    from canvas_tracker.planning.email import plan_email

    item = announcement(ny(20, 22))
    snap = make_snapshot([item], sent_keys=frozenset({"email:digest:2026-10-20"}))
    assert plan_email(ny(20, 21), snap, make_settings(email=True)) == ()


def test_overdue_timeline_has_no_announcement_noise() -> None:
    item = announcement(ny(20, 13))
    for minutes in (1, 5, 120, 240):
        now = ny(20, 13) + timedelta(minutes=minutes)
        kinds = {s.kind for s in plan(now, make_snapshot([item]), S).sends}
        assert SendKind.OVERDUE not in kinds and SendKind.REMINDER not in kinds


def test_overnight_announcement_only_in_the_morning_list() -> None:
    from canvas_tracker.render.digest import render_digest

    item = announcement(ny(21, 2), title="Overnight news")
    snap = make_snapshot([item], last_successful_sync_at=ny(21, 8))
    assert plan_news(ny(21, 8), snap, S) == ()
    [msg] = render_digest(snap, ny(21, 8), S)
    assert "Overnight news" in msg.text


def test_digest_skips_announcements_already_sent() -> None:
    from canvas_tracker.render.digest import render_digest

    item = announcement(ny(20, 7, 30), title="Early news")
    key = f"ann:{item.ref}"
    snap = make_snapshot([item], sent_keys=frozenset({key}), last_successful_sync_at=ny(20, 8))
    [msg] = render_digest(snap, ny(20, 8), S)
    assert "Early news" not in msg.text
