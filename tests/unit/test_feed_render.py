"""Feed-mode wording (no claims about submissions) and all-day events. Pure."""

from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_tracker.domain.models import Item, ItemType, Send, SendKind
from canvas_tracker.planning.keys import event_soon_key
from canvas_tracker.planning.news import is_all_day, next_event_heads_up, plan_news
from canvas_tracker.render import copy
from canvas_tracker.render.alerts import render_send
from canvas_tracker.render.digest import render_digest
from canvas_tracker.render.views import StatusInfo, render_status
from tests.factories import NOW, make_item, make_settings, make_snapshot

TOKEN = make_settings(canvas_host="school.instructure.com")
FEED = make_settings(canvas_host="school.instructure.com", calendar_feed=True)


def feed_item(**kw: Any) -> Item:
    return make_item(
        plannable_type="feed_assignment", points_possible=None, submission_types=(), db_id=3, **kw
    )


def test_auth_alert_names_the_feed_in_feed_mode() -> None:
    send = Send("auth:x", SendKind.AUTH_ALERT)
    [feed] = render_send(send, make_snapshot(), NOW, FEED)
    [token] = render_send(send, make_snapshot(), NOW, TOKEN)
    assert feed.text == copy.FEED_AUTH_ALERT and token.text == copy.AUTH_ALERT


def test_reminders_and_snooze_ends_say_not_marked_done_in_feed_mode() -> None:
    item = feed_item(due_in=timedelta(hours=5))
    snap = make_snapshot([item])
    for slot in range(3):
        send = Send(f"rem:2026-10-20T16:00Z:{slot}", SendKind.REMINDER, (item.ref,))
        [message] = render_send(send, snap, NOW, FEED)
        header = message.text.splitlines()[0]
        assert header == copy.FEED_REMINDER_HEADERS[slot].format(count=1, window="24 hours")
        assert "submit" not in header
        [token_message] = render_send(send, snap, NOW, TOKEN)
        assert token_message.text.splitlines()[0] == copy.REMINDER_HEADERS[slot].format(
            count=1, window="24 hours"
        )
    snooze = Send("snooze:x", SendKind.SNOOZE_END, (item.ref,))
    assert render_send(snooze, snap, NOW, FEED)[0].text.startswith(copy.FEED_SNOOZE_END_HEADER)
    assert render_send(snooze, snap, NOW, TOKEN)[0].text.startswith(copy.SNOOZE_END_HEADER)


def test_overdue_notice_asks_to_tap_done_in_feed_mode() -> None:
    item = feed_item(due_in=timedelta(minutes=-1))
    send = Send("overdue:x", SendKind.OVERDUE, (item.ref,))
    [feed] = render_send(send, make_snapshot([item]), NOW, FEED)
    [token] = render_send(send, make_snapshot([item]), NOW, TOKEN)
    assert copy.FEED_OVERDUE_NOTE in feed.text and copy.FEED_OVERDUE_NOTE not in token.text
    assert feed.keyboard[0][0].label == copy.BTN_DONE


def test_digest_mentions_the_feed_only_when_there_is_work() -> None:
    work = make_snapshot([feed_item(due_in=timedelta(hours=5))])
    assert copy.FEED_DIGEST_NOTE in "\n".join(m.text for m in render_digest(work, NOW, FEED))
    assert copy.FEED_DIGEST_NOTE not in "\n".join(m.text for m in render_digest(work, NOW, TOKEN))
    empty = make_snapshot()
    assert copy.FEED_DIGEST_NOTE not in "\n".join(m.text for m in render_digest(empty, NOW, FEED))


def test_status_shows_the_feed_state_and_the_done_hint() -> None:
    info = StatusInfo(
        last_successful_sync_at=NOW,
        auth_failed_since=None,
        next_digest_at=NOW + timedelta(hours=16),
        next_slot_at=None,
        pause_until=None,
        version="9.9.9",
    )
    feed = render_status(info, NOW, FEED).text
    token = render_status(info, NOW, TOKEN).text
    assert "Calendar feed: OK" in feed and copy.STATUS_FEED_NOTE in feed
    assert "Token: OK" in token and copy.STATUS_FEED_NOTE not in token


# --- all-day events --------------------------------------------------------------------

MIDNIGHT_NY = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)  # Wed 00:00 in New York


def event(start: datetime) -> Item:
    return make_item(type=ItemType.EVENT, plannable_type="feed_event", due_at=start)


def test_is_all_day_means_local_midnight_events_only() -> None:
    zone = TOKEN.zone
    assert is_all_day(event(MIDNIGHT_NY), zone)
    assert not is_all_day(event(MIDNIGHT_NY + timedelta(minutes=1)), zone)
    work = make_item(due_at=MIDNIGHT_NY)
    assert not is_all_day(work, zone)  # only events


def test_all_day_events_get_no_late_night_heads_up() -> None:
    settings = make_settings(quiet_start=None, quiet_end=None)
    all_day, timed = event(MIDNIGHT_NY), event(MIDNIGHT_NY + timedelta(hours=1))
    snap = make_snapshot([all_day, timed])
    at = MIDNIGHT_NY - timedelta(minutes=30)  # 11:30 PM the night before
    sends = plan_news(at, snap, settings)
    assert [s.key for s in sends] == []  # the timed one is still more than an hour away
    sends = plan_news(MIDNIGHT_NY + timedelta(minutes=10), snap, settings)
    assert [s.key for s in sends] == [event_soon_key(timed)]
    assert next_event_heads_up(at, make_snapshot([all_day]), settings) is None


def test_digest_lists_all_day_events_as_all_day() -> None:
    morning = MIDNIGHT_NY + timedelta(hours=8)
    snap = make_snapshot([event(MIDNIGHT_NY)], last_successful_sync_at=morning)
    text = "\n".join(m.text for m in render_digest(snap, morning, TOKEN))
    assert f"📅 {copy.ALL_DAY} · " in text
