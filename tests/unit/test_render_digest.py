from dataclasses import replace
from datetime import timedelta
from html.parser import HTMLParser

from canvas_tracker.render.digest import render_digest
from tests.factories import make_item, make_settings, make_snapshot
from tests.render_fixtures import DIGEST_NOW, HOST, ny, prd_digest_snapshot

S = make_settings(canvas_host=HOST)

EXPECTED = "\n".join(
    [
        "☀️ Good morning! Tue, Oct 20",
        "3 urgent · 1 high · 4 later this week (synced 7:58 AM)",
        "",
        "🔴 URGENT",
        '1. MATH 221 · <a href="https://canvas.example.edu/courses/2/quizzes/21">Quiz 7</a>',
        "   due today 2:00 PM (in 6 h) · ≈2% of grade · quiz · est. 1 h",
        "2. CS 101 · "
        '<a href="https://canvas.example.edu/courses/1/assignments/11">Homework 4: Recursion</a>',
        "   due today 11:59 PM (in 15 h) · ≈6% of grade · est. 2 h",
        "3. ENG 105 · Peer review: Essay 2",
        "   due today 11:59 PM (in 15 h) · peer review · est. 1 h",
        "",
        "🟠 HIGH",
        "4. PHYS 150 · Lab report 3",
        "   due Thu 11:59 PM (in 2 d) · ≈8% of grade · est. 3 h · start by Thu 7:00 PM",
        "",
        "🟡 MEDIUM / ⚪ LOW: 4 items, next: HIST 110 · Reading 6 (Fri 11:59 PM), "
        "CS 101 · Homework 5 (Sat 11:59 PM), MATH 221 · Quiz 8 (Sun 12:00 PM) → /week",
        "",
        "⚠️ OVERDUE",
        "• HIST 110 · Reading response 5: was due Sun 11:59 PM, still accepted until Fri 11:59 PM",
        "",
        "✅ Done yesterday: 2",
    ]
)


def test_digest_golden_text_and_buttons() -> None:
    [msg] = render_digest(prd_digest_snapshot(), DIGEST_NOW, S)
    assert msg.text == EXPECTED
    labels = [(b.label, b.callback_data) for row in msg.keyboard for b in row]
    assert labels == [("✅ 1", "d:2"), ("✅ 2", "d:1"), ("✅ 3", "d:3"), ("✅ 4", "d:4")]


def test_stale_banner_replaces_nothing_due() -> None:
    snap = make_snapshot(last_successful_sync_at=DIGEST_NOW - timedelta(minutes=31))
    [msg] = render_digest(snap, DIGEST_NOW, S)
    assert "⚠️ Couldn't reach Canvas since 7:29 AM, so this list may be out of date." in msg.text
    assert "Nothing due" not in msg.text


def test_nothing_due_when_fresh_and_empty() -> None:
    snap = make_snapshot(last_successful_sync_at=ny(20, 7, 58))
    [msg] = render_digest(snap, DIGEST_NOW, S)
    assert msg.text.endswith("Nothing due in the next 14 days 🎉 (synced 7:58 AM)")


def test_events_today_section() -> None:
    from canvas_tracker.domain.models import ItemType

    event = make_item(
        type=ItemType.EVENT,
        plannable_type="calendar_event",
        title="Midterm review",
        due_at=ny(20, 18, 0),
    )
    [msg] = render_digest(make_snapshot([event], last_successful_sync_at=DIGEST_NOW), DIGEST_NOW, S)
    assert "📅 Events today\n• 6:00 PM · Midterm review" in msg.text


class _TagBalance(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.ok = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        self.ok = self.ok and bool(self.stack) and self.stack.pop() == tag


ADVERSARIAL = ["<b>", "&amp;", "*_[]()~", "🎉✅", "مرحبا بالعالم", "x" * 5000, "line1\nline2"]


def test_adversarial_titles_are_escaped_and_fit() -> None:
    items = [
        make_item(
            db_id=i,
            title=t,
            due_at=DIGEST_NOW + timedelta(hours=2 + i),
            html_url=f"https://{HOST}/courses/1/assignments/{i}",
        )
        for i, t in enumerate(ADVERSARIAL)
    ]
    msgs = render_digest(make_snapshot(items, last_successful_sync_at=DIGEST_NOW), DIGEST_NOW, S)
    for msg in msgs:
        assert len(msg.text) <= 4096
        assert "<b>" not in msg.text
        parser = _TagBalance()
        parser.feed(msg.text)
        assert parser.ok and parser.stack == []
    assert "&lt;b&gt;" in msgs[0].text and "&amp;amp;" in msgs[0].text


def test_non_canvas_links_are_not_linked() -> None:
    snap = prd_digest_snapshot()
    items = tuple(
        replace(i, html_url="https://evil.example/phish") if i.db_id == 2 else i for i in snap.items
    )
    [msg] = render_digest(replace(snap, items=items), DIGEST_NOW, S)
    assert "evil.example" not in msg.text
    assert "1. MATH 221 · Quiz 7" in msg.text
