"""The small iCalendar reader behind calendar-feed mode."""

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from canvas_tracker.sources.ical import (
    ContentLine,
    parse_calendar,
    parse_line,
    parse_when,
    unescape,
    unfold,
)

FIXTURE = Path(__file__).parents[1] / "fixtures/canvas/calendar_feed.handmade.ics"
NY = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")


def cal(*lines: str, newline: str = "\r\n") -> bytes:
    return newline.join(["BEGIN:VCALENDAR", *lines, "END:VCALENDAR"]).encode()


# --- unfolding and content lines ---------------------------------------------------


def test_unfold_joins_continuation_lines_with_crlf_or_lf_and_tabs() -> None:
    data = b"SUMMARY:Long\r\n  title\nDESCRIPTION:a\n\tb\r\nUID:x\r\n"
    assert unfold(data) == ["SUMMARY:Long title", "DESCRIPTION:ab", "UID:x"]


def test_unfold_repairs_a_fold_inside_a_multibyte_character() -> None:
    word = "Café".encode()  # "é" is two bytes; Canvas may fold between them
    data = b"SUMMARY:" + word[:4] + b"\r\n " + word[4:] + b"\r\n"
    assert unfold(data) == ["SUMMARY:Café"]


def test_unfold_drops_a_byte_order_mark_and_accepts_text() -> None:
    assert unfold("﻿BEGIN:VCALENDAR\r\nEND:VCALENDAR") == ["BEGIN:VCALENDAR", "END:VCALENDAR"]


def test_unfold_replaces_invalid_utf8_instead_of_failing() -> None:
    assert unfold(b"SUMMARY:\xff ok") == ["SUMMARY:� ok"]


def test_parse_line_reads_name_params_and_value() -> None:
    line = parse_line('dtstart;TZID="America/New_York";X-A=1,"b:c":20261020T150000')
    assert line == ContentLine(
        "DTSTART", {"TZID": "America/New_York", "X-A": "1,b:c"}, "20261020T150000"
    )


def test_parse_line_keeps_colons_in_the_value() -> None:
    line = parse_line("URL;VALUE=URI:https://host/x?a=1")
    assert line is not None and line.value == "https://host/x?a=1"


@pytest.mark.parametrize("text", ["", ":value", "NOCOLON", 'X;P="unterminated:1', "X;P=1"])
def test_parse_line_rejects_malformed_lines(text: str) -> None:
    assert parse_line(text) is None


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        (r"a\, b\; c", "a, b; c"),
        (r"line1\nline2\Nline3", "line1\nline2\nline3"),
        (r"back\\slash", "back\\slash"),
        (r"keep \x as is", r"keep \x as is"),
        ("trailing\\", "trailing\\"),
        ("plain", "plain"),
    ],
)
def test_unescape(raw: str, text: str) -> None:
    assert unescape(raw) == text


# --- dates and times -----------------------------------------------------------------


def when(value: str, **params: str) -> tuple[datetime, date | None] | None:
    return parse_when(ContentLine("DTSTART", params, value), NY)


def test_utc_times() -> None:
    assert when("20261021T045900Z") == (datetime(2026, 10, 21, 4, 59, tzinfo=UTC), None)


def test_tzid_times_use_that_zone_across_dst() -> None:
    summer = when("20260715T090000", TZID="America/Chicago")
    winter = when("20261215T090000", TZID="America/Chicago")
    assert summer == (datetime(2026, 7, 15, 14, 0, tzinfo=UTC), None)
    assert winter == (datetime(2026, 12, 15, 15, 0, tzinfo=UTC), None)


def test_unknown_tzid_and_floating_times_use_the_fallback_zone() -> None:
    expected = (datetime(2026, 10, 20, 13, 0, tzinfo=UTC), None)
    assert when("20261020T090000", TZID="Mars/Olympus_Mons") == expected
    assert when("20261020T090000") == expected


def test_all_day_dates_are_local_midnight_and_keep_the_day() -> None:
    assert when("20261022") == (datetime(2026, 10, 22, 4, 0, tzinfo=UTC), date(2026, 10, 22))


def test_leap_second_is_clamped() -> None:
    assert when("20261231T235960Z") == (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), None)


@pytest.mark.parametrize("value", ["20261332", "20260230T100000Z", "2026-10-20", "soon", ""])
def test_bad_dates_are_none(value: str) -> None:
    assert when(value) is None


# --- whole calendars -------------------------------------------------------------------


def test_the_handmade_canvas_feed() -> None:
    calendar = parse_calendar(FIXTURE.read_bytes(), NY)
    assert calendar.time_zone == "America/Chicago"
    by_uid = {e.uid: e for e in calendar.events}
    # cancelled and start-less entries are skipped
    assert sorted(by_uid) == [
        "event-assignment-501",
        "event-assignment-502",
        "event-assignment-503",
        "event-calendar-event-9001",
        "event-calendar-event-9002",
    ]
    essay = by_uid["event-assignment-501"]
    assert essay.summary == "Essay draft [ENG 101]"
    assert essay.start == datetime(2026, 10, 21, 4, 59, tzinfo=UTC)
    assert essay.description == (
        "Write 500 words, then upload.\nUse the template; cite sources. A long line folded "
        "by Canvas."
    )
    assert essay.url == (
        "https://canvas.example.edu/calendar?assignment_id=501&include_contexts=course_42"
    )
    office = by_uid["event-calendar-event-9001"]
    assert office.start == datetime(2026, 10, 20, 19, 0, tzinfo=UTC)  # 3 PM in New York
    assert office.end == datetime(2026, 10, 20, 20, 0, tzinfo=UTC)
    assert office.description == ""  # the alarm's description stays with the alarm
    reading = by_uid["event-calendar-event-9002"]
    assert reading.all_day and reading.day == date(2026, 10, 23)
    assert reading.start == datetime(2026, 10, 23, 5, 0, tzinfo=UTC)  # the feed's zone


def test_feed_zone_is_ignored_when_unknown_and_user_zone_is_used() -> None:
    data = cal("X-WR-TIMEZONE:Nowhere/Land", "BEGIN:VEVENT", "UID:a", "DTSTART:20261020T090000",
               "END:VEVENT")  # fmt: skip
    calendar = parse_calendar(data, NY)
    assert calendar.time_zone is None
    assert calendar.events[0].start == datetime(2026, 10, 20, 13, 0, tzinfo=UTC)


def test_lf_only_feeds_and_lowercase_names_work() -> None:
    data = cal("begin:vevent", "uid:a", "dtstart:20261020T090000Z", "summary:x", "end:vevent",
               newline="\n")  # fmt: skip
    [event] = parse_calendar(data, NY).events
    assert (event.uid, event.summary) == ("a", "x")


def test_first_property_wins_and_malformed_lines_are_skipped() -> None:
    data = cal("BEGIN:VEVENT", "UID:a", "SUMMARY:first", "garbage without colon",
               "SUMMARY:second", "DTSTART:20261020T090000Z", "END:VEVENT")  # fmt: skip
    [event] = parse_calendar(data, NY).events
    assert event.summary == "first"


def test_missing_uid_gets_a_stable_one() -> None:
    data = cal("BEGIN:VEVENT", "SUMMARY:Quiz", "DTSTART:20261020T090000Z", "END:VEVENT")
    [first] = parse_calendar(data, NY).events
    [again] = parse_calendar(data, NY).events
    assert first.uid and first.uid == again.uid


def test_events_outside_the_calendar_or_nested_elsewhere_are_ignored() -> None:
    data = cal(
        "BEGIN:VTODO", "BEGIN:VEVENT", "UID:nested", "DTSTART:20261020T090000Z", "END:VEVENT",
        "END:VTODO", "BEGIN:VEVENT", "UID:real", "DTSTART:20261020T090000Z", "END:VEVENT",
    )  # fmt: skip
    assert [e.uid for e in parse_calendar(data, NY).events] == ["real"]


def test_an_unclosed_event_is_dropped_without_breaking_the_rest() -> None:
    data = cal("BEGIN:VEVENT", "UID:open", "DTSTART:20261020T090000Z")
    assert parse_calendar(data, NY).events == ()


def test_max_events_cuts_off_a_huge_feed() -> None:
    events = [
        f"BEGIN:VEVENT\r\nUID:{n}\r\nDTSTART:20261020T090000Z\r\nEND:VEVENT" for n in range(50)
    ]
    assert len(parse_calendar(cal(*events), NY, max_events=10).events) == 10


@pytest.mark.parametrize(
    "data", [b"", b"<html>login</html>", b"BEGIN:VEVENT\r\nEND:VEVENT", b"\x00\x01"]
)
def test_not_a_calendar_raises(data: bytes) -> None:
    with pytest.raises(ValueError, match="iCalendar"):
        parse_calendar(data, NY)


def test_chicago_fallback_for_floating_times_in_a_feed_without_zone() -> None:
    data = cal("BEGIN:VEVENT", "UID:a", "DTSTART:20261020T090000", "END:VEVENT")
    assert parse_calendar(data, CHICAGO).events[0].start == datetime(
        2026, 10, 20, 14, 0, tzinfo=UTC
    )


# --- hostile feeds (review findings) ------------------------------------------------


def test_deep_nesting_parses_in_linear_time() -> None:
    """A feed host could nest components 100k deep; END used to scan the whole stack."""
    import time as clock

    n = 100_000
    data = b"BEGIN:VCALENDAR\r\n" + b"BEGIN:A\r\n" * n + b"END:B\r\n" * n + b"END:VCALENDAR"
    started = clock.perf_counter()
    assert parse_calendar(data, NY).events == ()
    assert clock.perf_counter() - started < 2.0


def test_events_after_ignored_deep_nesting_still_count() -> None:
    deep = ["BEGIN:X"] * 50 + ["UID:inside", "DTSTART:20261020T090000Z"] + ["END:X"] * 50
    data = cal(*deep, "BEGIN:VEVENT", "UID:real", "DTSTART:20261020T090000Z", "END:VEVENT")
    assert [e.uid for e in parse_calendar(data, NY).events] == ["real"]


def test_an_over_long_tzid_or_calendar_zone_is_ignored_not_raised() -> None:
    long_zone = "A" * 300
    data = cal(
        f"X-WR-TIMEZONE:{long_zone}",
        "BEGIN:VEVENT", "UID:a", f"DTSTART;TZID={long_zone}:20261110T120000", "END:VEVENT",
        "BEGIN:VEVENT", "UID:b", "DTSTART:20261110T120000Z", "END:VEVENT",
    )  # fmt: skip
    calendar = parse_calendar(data, NY)
    assert calendar.time_zone is None
    assert [e.uid for e in calendar.events] == ["a", "b"]
    assert calendar.events[0].start == datetime(2026, 11, 10, 17, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "zone"),
    [
        ("DTSTART;VALUE=DATE:00010101", ZoneInfo("Asia/Tokyo")),
        ("DTSTART;VALUE=DATE:99991231", ZoneInfo("America/Los_Angeles")),
        ("DTSTART:00010101T000000", ZoneInfo("Asia/Tokyo")),
        ("DTSTART:99991231T235959", ZoneInfo("America/Los_Angeles")),
    ],
)
def test_dates_at_the_edge_of_the_range_are_skipped_not_raised(value: str, zone: ZoneInfo) -> None:
    data = cal(
        "BEGIN:VEVENT", "UID:odd", value, "END:VEVENT",
        "BEGIN:VEVENT", "UID:ok", "DTSTART:20261110T120000Z", "END:VEVENT",
    )  # fmt: skip
    assert [e.uid for e in parse_calendar(data, zone).events] == ["ok"]


def test_long_text_values_are_cut() -> None:
    data = cal(
        "BEGIN:VEVENT", "UID:" + "u" * 50_000, "SUMMARY:" + "s" * 50_000,
        "DESCRIPTION:" + "d" * 50_000, "URL:https://x.example/" + "p" * 50_000,
        "DTSTART:20261110T120000Z", "END:VEVENT",
    )  # fmt: skip
    [event] = parse_calendar(data, NY).events
    assert len(event.uid) <= 2_000 and len(event.summary) <= 2_000
    assert len(event.description) <= 2_000 and len(event.url or "") <= 2_000
