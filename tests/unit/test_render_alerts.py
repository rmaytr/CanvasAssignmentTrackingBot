import re
from dataclasses import replace
from datetime import timedelta

from canvas_tracker.domain.models import Send, SendKind
from canvas_tracker.render.alerts import render_send
from tests.factories import make_item, make_settings, make_snapshot
from tests.render_fixtures import COURSES, DIGEST_NOW, HOST, ny

S = make_settings(canvas_host=HOST)
NOW = ny(20, 14, 1)
CALLBACK = re.compile(r"^[dsux]:\d+$")


def test_reminder_lists_items_nearest_first_with_buttons() -> None:
    hw = make_item(
        db_id=1,
        course_id=1,
        title="Homework 4",
        due_at=ny(20, 23, 59),
        html_url=f"https://{HOST}/courses/1/assignments/11",
    )
    quiz = make_item(db_id=2, course_id=2, title="Quiz 7", due_at=ny(20, 16, 0))
    send = Send("rem:2026-10-20T03:59Z:5", SendKind.REMINDER, (quiz.ref, hw.ref))
    [msg] = render_send(send, make_snapshot([hw, quiz], courses=COURSES), NOW, S, stale=False)
    assert msg.text == "\n".join(
        [
            "⏰ Reminder: 2 due within 24 hours",
            "",
            "1. MATH 221 · Quiz 7",
            "   due today 4:00 PM · 1 h 59 m left ⚠️",
            "2. CS 101 · "
            '<a href="https://canvas.example.edu/courses/1/assignments/11">Homework 4</a>',
            "   due today 11:59 PM · 9 h 58 m left",
        ]
    )
    rows = [[(b.label, b.callback_data, b.url) for b in row] for row in msg.keyboard]
    assert rows == [
        [("✅ Done 1", "d:2", None), ("💤 2h 1", "s:2", None)],
        [
            ("✅ Done 2", "d:1", None),
            ("💤 2h 2", "s:1", None),
            ("🔗 2", None, "https://canvas.example.edu/courses/1/assignments/11"),
        ],
    ]


def test_header_rotates_with_slot_number() -> None:
    item = make_item(db_id=1, due_at=ny(20, 23, 59))
    snap = make_snapshot([item])
    headers = [
        render_send(
            Send(f"rem:2026-10-20T03:59Z:{k}", SendKind.REMINDER, (item.ref,)), snap, NOW, S
        )[0].text.split("\n")[0]
        for k in (0, 1, 2, 3)
    ]
    assert headers[0] == "⏰ Due within 24 hours: 1 not submitted"
    assert headers[1] == "⏰ Still to submit in the next 24 hours: 1"
    assert headers[0] == headers[3] and len(set(headers)) == 3


def test_forty_urgent_items_split_into_two_messages() -> None:  # Review Focus 3
    items = [
        make_item(db_id=i, title=f"Task {i}", due_at=NOW + timedelta(hours=1, minutes=i))
        for i in range(1, 41)
    ]
    send = Send("rem:2026-10-20T03:59Z:0", SendKind.REMINDER, tuple(i.ref for i in items))
    msgs = render_send(send, make_snapshot(items), NOW, S)
    assert len(msgs) == 2
    for msg in msgs:
        assert len(msg.text) <= 4096
        assert sum(len(row) for row in msg.keyboard) <= 90
    assert "40." in msgs[1].text


def test_overdue_notice_mentions_lock_only_when_in_future() -> None:
    open_item = make_item(db_id=7, title="Lab 2", due_at=ny(20, 14, 0), lock_at=ny(23, 23, 59))
    send = Send(f"overdue:{open_item.ref}:x", SendKind.OVERDUE, (open_item.ref,))
    [msg] = render_send(send, make_snapshot([open_item]), NOW, S, stale=False)
    assert msg.text == (
        "❗ Lab 2 is now overdue (was due today 2:00 PM).\n"
        "Canvas still accepts it until Fri 11:59 PM."
    )
    assert [b.label for row in msg.keyboard for b in row] == ["✅ Done", "🔕 Stop"]
    locked = replace(open_item, lock_at=ny(20, 14, 0))
    [msg2] = render_send(send, make_snapshot([locked]), NOW, S)
    assert "still accepts" not in msg2.text


def test_overnight_new_and_snooze_end_kinds() -> None:
    item = make_item(db_id=3, title="Essay", due_at=ny(21, 3, 0))
    snap = make_snapshot([item])
    night = render_send(Send("overnight:2026-10-20", SendKind.OVERNIGHT, (item.ref,)), snap, NOW, S)
    assert night[0].text.startswith("🌙 Due while you sleep:\n")
    new = render_send(Send("new:x", SendKind.NEW_URGENT, (item.ref,)), snap, NOW, S)
    assert new[0].text.startswith("🆕 Just posted and due soon\n")
    snz = render_send(Send("snz:x", SendKind.SNOOZE_END, (item.ref,)), snap, NOW, S)
    assert snz[0].text.startswith("⏰ Snooze over: still not submitted\n")


def test_auth_alert_has_no_canvas_data() -> None:
    [msg] = render_send(Send("auth:x", SendKind.AUTH_ALERT), make_snapshot(), NOW, S)
    assert msg.text.startswith("🔑 Canvas rejected the bot's access token")
    assert msg.keyboard == ()


def test_digest_kind_delegates_to_digest_renderer() -> None:
    msgs = render_send(Send("digest:2026-10-20", SendKind.DIGEST), make_snapshot(), DIGEST_NOW, S)
    assert msgs[0].text.startswith("☀️ Good morning! Tue, Oct 20")


def test_every_callback_matches_the_protocol() -> None:
    items = [make_item(db_id=i, due_at=NOW + timedelta(hours=i)) for i in range(1, 6)]
    for kind in (SendKind.REMINDER, SendKind.OVERNIGHT, SendKind.OVERDUE, SendKind.NEW_URGENT):
        msgs = render_send(
            Send("rem:2026-10-20T03:59Z:0", kind, tuple(i.ref for i in items)),
            make_snapshot(items),
            NOW,
            S,
        )
        for msg in msgs:
            for row in msg.keyboard:
                for b in row:
                    assert b.url is not None or CALLBACK.match(b.callback_data or "")


def test_missing_refs_are_skipped() -> None:
    item = make_item(db_id=1)
    send = Send("rem:2026-10-20T03:59Z:0", SendKind.REMINDER, (item.ref, "assignment-999999"))
    [msg] = render_send(send, make_snapshot([item]), NOW, S)
    assert "1 not submitted" in msg.text


def test_stale_data_is_labelled_on_every_nag() -> None:  # review I4
    item = make_item(db_id=1, title="Lab", due_at=ny(20, 23, 59))
    snap = make_snapshot([item], last_successful_sync_at=ny(20, 13, 0))
    note = "⚠️ Based on Canvas data from today 1:00 PM. If you've already submitted, ignore this."
    for kind in (SendKind.REMINDER, SendKind.NEW_URGENT, SendKind.SNOOZE_END, SendKind.OVERNIGHT):
        send = Send("rem:2026-10-20T03:59Z:0", kind, (item.ref,))
        assert note in render_send(send, snap, NOW, S, stale=True)[0].text
        assert note not in render_send(send, snap, NOW, S, stale=False)[0].text
    overdue = make_item(db_id=2, title="Quiz", due_at=ny(20, 14, 0))
    msg = render_send(
        Send("overdue:x", SendKind.OVERDUE, (overdue.ref,)),
        make_snapshot([overdue], last_successful_sync_at=ny(20, 13, 0)),
        NOW,
        S,
        stale=True,
    )[0]
    assert note in msg.text


def test_digest_honours_an_explicit_stale_flag() -> None:  # review I4 / Minor 13
    snap = make_snapshot(last_successful_sync_at=DIGEST_NOW - timedelta(minutes=10))
    text = render_send(Send("digest:2026-10-20", SendKind.DIGEST), snap, DIGEST_NOW, S, stale=True)[
        0
    ].text
    assert "Couldn't reach Canvas since 7:50 AM" in text and "Nothing due" not in text
