"""A small iCalendar (RFC 5545) reader for Canvas calendar feeds. Pure: no I/O, no clock.

Only what a Canvas feed needs is read: the VEVENTs directly inside the VCALENDAR,
with DTSTART/DTEND (UTC ``Z``, ``TZID=`` with the tz database, floating, or all-day
``DATE`` values), SUMMARY, DESCRIPTION, URL, UID and STATUS. Lines are unfolded
before they are decoded, so a fold inside a multi-byte character can't garble it.
Recurrence rules are not expanded (Canvas doesn't use them for assignments): a
recurring event counts once, at its first start. Anything malformed is skipped,
never raised, so one odd entry can't hide the rest of someone's calendar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_EVENTS = 10_000  # a feed with more than this is cut off rather than parsed for ever
_FOLD_RE = re.compile(rb"\r?\n[ \t]")
_LINE_SPLIT_RE = re.compile(r"\r\n|\n|\r")
_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATETIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$")
_ESCAPES = {"n": "\n", "N": "\n", "\\": "\\", ";": ";", ",": ","}


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    uid: str
    summary: str
    start: datetime  # UTC; for an all-day event, local midnight of ``day``
    end: datetime | None = None  # UTC
    day: date | None = None  # set only for all-day (DATE) events
    url: str | None = None
    description: str = ""

    @property
    def all_day(self) -> bool:
        return self.day is not None


@dataclass(frozen=True, slots=True)
class Calendar:
    events: tuple[CalendarEvent, ...]
    time_zone: str | None = None  # X-WR-TIMEZONE, when it names a real zone


@dataclass(frozen=True, slots=True)
class ContentLine:
    name: str
    params: dict[str, str]
    value: str


def unfold(data: bytes | str) -> list[str]:
    """The logical lines of an iCalendar text (continuation lines joined back up)."""
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    text = _FOLD_RE.sub(b"", raw).decode("utf-8", errors="replace")
    return [line for line in _LINE_SPLIT_RE.split(text.removeprefix("﻿")) if line]


def parse_line(line: str) -> ContentLine | None:
    """``NAME;PARAM=value;P2="quoted:value":VALUE`` → its parts, or None if malformed."""
    n = len(line)
    i = 0
    while i < n and line[i] not in ";:":
        i += 1
    name = line[:i].strip().upper()
    if not name:
        return None
    params: dict[str, str] = {}
    while i < n and line[i] == ";":
        i += 1
        start = i
        while i < n and line[i] not in "=;:":
            i += 1
        param = line[start:i].strip().upper()
        values: list[str] = []
        if i < n and line[i] == "=":
            i += 1
            while True:
                if i < n and line[i] == '"':
                    end = line.find('"', i + 1)
                    if end < 0:
                        return None
                    values.append(line[i + 1 : end])
                    i = end + 1
                else:
                    start = i
                    while i < n and line[i] not in ",;:":
                        i += 1
                    values.append(line[start:i])
                if i < n and line[i] == ",":
                    i += 1
                    continue
                break
        if param:
            params[param] = ",".join(values)
    if i >= n or line[i] != ":":
        return None
    return ContentLine(name, params, line[i + 1 :])


def unescape(value: str) -> str:
    """TEXT escapes: ``\\\\`` ``\\;`` ``\\,`` and ``\\n``/``\\N`` (a line break)."""
    if "\\" not in value:
        return value
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value) and value[i + 1] in _ESCAPES:
            out.append(_ESCAPES[value[i + 1]])
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name.strip().strip('"'))
    except (ZoneInfoNotFoundError, ValueError):
        return None


def parse_when(line: ContentLine, fallback: ZoneInfo) -> tuple[datetime, date | None] | None:
    """A DTSTART/DTEND value as (UTC instant, day for all-day values), or None.

    ``Z`` values are UTC; ``TZID=`` values use that zone (or ``fallback`` when the
    zone is unknown); floating values use ``fallback``; a ``DATE`` is local midnight."""
    value = line.value.strip()
    match = _DATE_RE.match(value)
    if match is not None:
        try:
            day = date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError:
            return None
        return datetime.combine(day, time(0, 0), tzinfo=fallback).astimezone(UTC), day
    match = _DATETIME_RE.match(value)
    if match is None:
        return None
    year, month, mday, hour, minute, second = (int(match[k]) for k in range(1, 7))
    zone = UTC if match[7] == "Z" else (_zone(line.params.get("TZID")) or fallback)
    try:
        wall = datetime(year, month, mday, hour, minute, min(second, 59), tzinfo=zone)
    except ValueError:
        return None
    return wall.astimezone(UTC), None


def _event(props: dict[str, ContentLine], fallback: ZoneInfo) -> CalendarEvent | None:
    status = props.get("STATUS")
    cancelled = status is not None and status.value.strip().upper() == "CANCELLED"
    if "DTSTART" not in props or cancelled:
        return None
    start = parse_when(props["DTSTART"], fallback)
    if start is None:
        return None
    end = parse_when(props["DTEND"], fallback) if "DTEND" in props else None
    summary = unescape(props["SUMMARY"].value).strip() if "SUMMARY" in props else ""
    uid = unescape(props["UID"].value).strip() if "UID" in props else ""
    if not uid:  # still a stable identity, as long as the entry itself doesn't change
        uid = f"{summary}@{start[0].isoformat()}"
    url = props["URL"].value.strip() if "URL" in props else None
    description = unescape(props["DESCRIPTION"].value) if "DESCRIPTION" in props else ""
    return CalendarEvent(
        uid=uid,
        summary=summary,
        start=start[0],
        end=None if end is None else end[0],
        day=start[1],
        url=url or None,
        description=description,
    )


def parse_calendar(
    data: bytes | str, default_zone: ZoneInfo, max_events: int = MAX_EVENTS
) -> Calendar:
    """Every usable VEVENT in a VCALENDAR. Times without a zone of their own use the
    calendar's X-WR-TIMEZONE, else ``default_zone`` (the user's). Raises ValueError
    only when the text isn't an iCalendar at all."""
    lines = [parsed for parsed in map(parse_line, unfold(data)) if parsed is not None]
    if not lines or lines[0].name != "BEGIN" or lines[0].value.strip().upper() != "VCALENDAR":
        raise ValueError("not an iCalendar feed")
    calendar_zone_name: str | None = None
    for line in lines:
        if line.name == "X-WR-TIMEZONE":
            if _zone(line.value) is not None:
                calendar_zone_name = line.value.strip().strip('"')
            break
        if line.name == "BEGIN" and line.value.strip().upper() != "VCALENDAR":
            break  # calendar properties come before the first component
    fallback = _zone(calendar_zone_name) or default_zone
    events: list[CalendarEvent] = []
    stack: list[str] = []
    props: dict[str, ContentLine] | None = None
    for line in lines:
        if line.name == "BEGIN":
            component = line.value.strip().upper()
            stack.append(component)
            if component == "VEVENT" and stack == ["VCALENDAR", "VEVENT"]:
                props = {}
            continue
        if line.name == "END":
            component = line.value.strip().upper()
            if component in stack:
                while stack and stack.pop() != component:
                    pass  # an END that skips levels closes everything in between
            if component == "VEVENT" and props is not None and stack == ["VCALENDAR"]:
                event = _event(props, fallback)
                props = None
                if event is not None:
                    events.append(event)
                    if len(events) >= max_events:
                        break
            continue
        if props is not None and stack == ["VCALENDAR", "VEVENT"]:
            props.setdefault(line.name, line)  # the first of each property wins
    return Calendar(events=tuple(events), time_zone=calendar_zone_name)
