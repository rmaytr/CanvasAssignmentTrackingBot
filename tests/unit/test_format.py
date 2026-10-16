import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from canvas_tracker.render.format import (
    escape,
    format_due,
    format_left,
    safe_link,
    split_blocks,
)
from canvas_tracker.render.message import Button
from tests.factories import NOW

NY = ZoneInfo("America/New_York")


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NY).astimezone(UTC)


def test_escape() -> None:
    assert escape('<b>&"x"</b>') == "&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;"


def test_safe_link_allows_only_https_on_canvas_host() -> None:
    host = "canvas.example.edu"
    assert safe_link("https://canvas.example.edu/courses/1", host) == (
        "https://canvas.example.edu/courses/1"
    )
    assert safe_link("http://canvas.example.edu/courses/1", host) is None
    assert safe_link("https://evil.example/x", host) is None
    assert safe_link("https://canvas.example.edu.evil.example/x", host) is None
    assert safe_link(None, host) is None


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (ny(20, 23, 59), "today 11:59 PM"),
        (ny(21, 14, 0), "tomorrow 2:00 PM"),
        (ny(22, 23, 59), "Thu 11:59 PM"),
        (ny(26, 0, 30), "Mon 12:30 AM"),
        (ny(27, 9, 5), "Oct 27 9:05 AM"),
        (ny(30, 23, 59), "Oct 30 11:59 PM"),
    ],
)
def test_format_due(due: datetime, expected: str) -> None:
    assert format_due(due, NOW, NY) == expected


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(hours=9, minutes=58), "9 h 58 m"),
        (timedelta(minutes=58), "58 m"),
        (timedelta(hours=51), "2 d 3 h"),
        (timedelta(hours=47, minutes=59), "47 h 59 m"),
        (timedelta(seconds=-5), "0 m"),
    ],
)
def test_format_left(delta: timedelta, expected: str) -> None:
    assert format_left(delta) == expected


def test_split_blocks_keeps_blocks_whole_and_in_order() -> None:
    blocks = [f"{i:03d}" + "x" * 97 for i in range(50)]
    parts = split_blocks(blocks)
    assert all(len(p) <= 4096 for p in parts)
    assert len(parts) == 2
    assert "\n".join(parts).split("\n") == blocks


def test_split_blocks_cuts_an_oversized_block_at_whitespace_without_tags() -> None:
    block = '<a href="https://canvas.example.edu/x">' + ("word " * 1200) + "</a>"
    parts = split_blocks([block], limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert all("<a" not in p and "</a>" not in p for p in parts)
    assert "".join(p.replace(" ", "") for p in parts) == "word" * 1200


def test_button_requires_exactly_one_action_and_short_callback() -> None:
    Button("ok", callback_data="d:1")
    Button("ok", url="https://canvas.example.edu/x")
    with pytest.raises(ValueError):
        Button("bad")
    with pytest.raises(ValueError):
        Button("bad", callback_data="d:1", url="https://canvas.example.edu/x")
    with pytest.raises(ValueError):
        Button("bad", callback_data="x" * 65)


def test_output_ignores_host_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:  # Review Focus 4
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    in_utc = format_due(ny(21, 14, 0), NOW, NY)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    in_tokyo = format_due(ny(21, 14, 0), NOW, NY)
    monkeypatch.undo()
    time.tzset()
    assert in_utc == in_tokyo == "tomorrow 2:00 PM"
