"""Canvas's private calendar feed (``/feeds/calendars/….ics``) as a source of Items.

The feed needs no access token: its long random link is the secret, so it is stored
encrypted like a token, kept out of the logs, and only ever fetched from the host it
names. The feed has no submission status, so feed items are only ever done when the
user taps ✅ Done; and it has no grade weights, so ranking works without them.

Downloads are HTTPS only, capped at 5 MB (counted after decompression), time out,
and may only redirect within the same host.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import time
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

from canvas_tracker.domain.models import Item, ItemType
from canvas_tracker.planning.timeutil import at_local
from canvas_tracker.sources.canvas_client import (
    USER_AGENT,
    CanvasAuthError,
    CanvasProtocolError,
    CanvasUnavailable,
)
from canvas_tracker.sources.ical import CalendarEvent

FEED_PATH_RE = re.compile(r"^/feeds/calendars/[A-Za-z0-9_.~-]{1,200}\.ics$")
FEED_MAX_BYTES = 5 * 1024 * 1024
FEED_TIMEOUT_S = 20.0
MAX_REDIRECTS = 3
ALL_DAY_DUE = time(23, 59)  # Canvas exports work due at 11:59 PM as an all-day entry
# Feed items use their own plannable types, so they can never collide with planner ones.
FEED_ASSIGNMENT = "feed_assignment"
FEED_EVENT = "feed_event"
FEED_OTHER = "feed_other"
_UID_RE = re.compile(r"^event-([a-z][a-z_-]{0,40}?)-(\d{1,18})$")
_ASSIGNMENT_PATH_RE = re.compile(r"/courses/(\d{1,18})/assignments/(\d{1,18})")
_COURSE_PATH_RE = re.compile(r"/courses/(\d{1,18})")
_COURSE_CONTEXT_RE = re.compile(r"(?:^|,)course_(\d{1,18})(?:,|$)")
_SUMMARY_RE = re.compile(r"^(.*?)\s*\[([^\[\]]+)\]\s*$", re.DOTALL)


class FeedRejected(CanvasAuthError):
    """Canvas no longer serves this feed link (401, 403, 404 or 410): it needs a fresh one."""


class FeedTooLarge(CanvasProtocolError):
    """The feed is larger than the download limit."""


class _Retry(Exception):
    """A failure worth trying again (throttling, a server error, the network)."""


def is_feed_url(url: str) -> bool:
    """An ``https://host/feeds/calendars/….ics`` link with nothing else in it."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.username is None
        and parts.password is None
        and bool(parts.hostname)
        and port in (None, 443)
        and not parts.query
        and not parts.fragment
        and FEED_PATH_RE.match(parts.path) is not None
    )


@dataclass(frozen=True, slots=True)
class FeedResponse:
    not_modified: bool
    body: bytes
    etag: str | None = None
    last_modified: str | None = None


class FeedClient:
    """GETs one user's calendar feed. ``url`` is read on every fetch (it is decrypted
    only when needed); ``host``, when given, is the only host the link may be on."""

    def __init__(
        self,
        url: Callable[[], str],
        *,
        host: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
        max_retries: int = 2,
        max_bytes: int = FEED_MAX_BYTES,
        timeout_s: float = FEED_TIMEOUT_S,
    ) -> None:
        self._url = url
        self._host = host.lower() if host else None
        self._sleep = sleep
        self._rand = rand
        self._max_retries = max_retries
        self._max_bytes = max_bytes
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            transport=transport, follow_redirects=False, timeout=httpx.Timeout(timeout_s)
        )

    async def fetch(
        self, etag: str | None = None, last_modified: str | None = None
    ) -> FeedResponse:
        try:
            url = self._url()
        except OSError:
            raise FeedRejected("could not read the calendar feed link") from None
        parts = urlsplit(url)
        if not is_feed_url(url):
            raise CanvasProtocolError("that isn't a Canvas calendar feed link")
        if self._host is not None and (parts.hostname or "").lower() != self._host:
            raise CanvasProtocolError("the calendar feed is on another host")
        headers = {"User-Agent": USER_AGENT, "Accept": "text/calendar, */*;q=0.5"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        origin = ("https", parts.netloc.lower())
        for attempt in range(self._max_retries + 1):
            try:
                async with self._lock:
                    return await self._get(url, origin, headers, etag, last_modified)
            except _Retry as exc:
                if attempt == self._max_retries:
                    raise CanvasUnavailable(str(exc)) from None
                await self._sleep(self._rand() * min(30.0, 2.0 * 2.0**attempt))
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- internals -------------------------------------------------------------

    async def _read(self, response: httpx.Response, limit: int) -> bytes:
        length = response.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > limit:
            raise FeedTooLarge("the calendar feed is too large")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():  # decoded bytes: a gzip bomb counts in full
            total += len(chunk)
            if total > limit:
                raise FeedTooLarge("the calendar feed is too large")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _get(
        self,
        url: str,
        origin: tuple[str, str],
        headers: Mapping[str, str],
        etag: str | None,
        last_modified: str | None,
    ) -> FeedResponse:
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                async with self._http.stream("GET", current, headers=headers) as response:
                    status = response.status_code
                    if status == 304:
                        return FeedResponse(
                            not_modified=True,
                            body=b"",
                            etag=response.headers.get("ETag") or etag,
                            last_modified=response.headers.get("Last-Modified") or last_modified,
                        )
                    if status == 403 and await self._throttled(response):
                        raise _Retry("Canvas is throttling requests (HTTP 403)")
                    if status in (401, 403, 404, 410):
                        raise FeedRejected(f"Canvas refused the calendar feed (HTTP {status})")
                    if status == 429 or status >= 500:
                        raise _Retry(f"Canvas unavailable (HTTP {status})")
                    if 300 <= status < 400:
                        location = response.headers.get("Location")
                        if not location:
                            raise CanvasProtocolError("redirect without a location")
                        target = urljoin(current, location)
                        moved = urlsplit(target)
                        if (moved.scheme, moved.netloc.lower()) != origin:
                            raise CanvasProtocolError("redirect to another host refused")
                        current = target
                        continue
                    if status >= 400:
                        raise CanvasProtocolError(f"unexpected Canvas response (HTTP {status})")
                    body = await self._read(response, self._max_bytes)
                    return FeedResponse(
                        not_modified=False,
                        body=body,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                    )
            except httpx.TransportError:
                raise _Retry("network error talking to Canvas") from None
        raise CanvasProtocolError("too many redirects")

    async def _throttled(self, response: httpx.Response) -> bool:
        try:
            body = await self._read(response, 64 * 1024)
        except FeedTooLarge:
            return False
        return b"Rate Limit Exceeded" in body


# --- mapping ----------------------------------------------------------------------


def _stable_id(uid: str) -> int:
    """A positive 48-bit id derived from the entry's UID, the same on every sync."""
    return int.from_bytes(hashlib.sha256(uid.encode("utf-8")).digest()[:6], "big")


def _query_int(query: Mapping[str, list[str]], name: str) -> int | None:
    values = query.get(name) or []
    return int(values[0]) if values and values[0].isdigit() and len(values[0]) <= 18 else None


@dataclass(frozen=True, slots=True)
class _Link:
    course_id: int | None
    assignment_id: int | None
    url: str | None


def _link(url: str | None) -> _Link:
    if not url:
        return _Link(None, None, None)
    parts = urlsplit(url)
    if parts.scheme != "https":
        return _Link(None, None, None)
    query = parse_qs(parts.query)
    path_assignment = _ASSIGNMENT_PATH_RE.search(parts.path)
    course_path = _COURSE_PATH_RE.search(parts.path)
    contexts = ",".join(query.get("include_contexts", []))
    course_context = _COURSE_CONTEXT_RE.search(contexts)
    course_id = (
        int(course_path.group(1))
        if course_path
        else (int(course_context.group(1)) if course_context else None)
    )
    assignment_id = (
        int(path_assignment.group(2)) if path_assignment else _query_int(query, "assignment_id")
    )
    return _Link(course_id, assignment_id, url)


def feed_identity(event: CalendarEvent) -> tuple[str, int, bool]:
    """(plannable_type, plannable_id, is_assignment) for a feed entry. Canvas's UIDs look
    like ``event-assignment-123`` or ``event-calendar-event-456``; failing that the link
    can name the assignment; failing that the UID itself is hashed into an id."""
    match = _UID_RE.match(event.uid)
    if match is not None:
        kind = match.group(1).replace("-", "_")
        number = int(match.group(2))
        if kind == "assignment":
            return FEED_ASSIGNMENT, number, True
        if kind == "calendar_event":
            return FEED_EVENT, number, False
        return f"feed_{kind}", number, "assignment" in kind
    link = _link(event.url)
    if link.assignment_id is not None:
        return FEED_ASSIGNMENT, link.assignment_id, True
    return FEED_OTHER, _stable_id(event.uid), False


def split_summary(summary: str) -> tuple[str, str]:
    """``"Essay [CS 101]"`` → ``("Essay", "CS 101")``; no brackets → (summary, "")."""
    match = _SUMMARY_RE.match(summary)
    if match is None or not match.group(1).strip():
        return summary.strip(), ""
    return match.group(1).strip(), match.group(2).strip()


def map_feed_event(event: CalendarEvent, base_url: str, zone: ZoneInfo) -> Item:
    """One feed entry as an Item: assignments are work with a due date, everything else
    an event. Feed items carry no submission data, so they're only done via the bot."""
    plannable_type, plannable_id, is_assignment = feed_identity(event)
    title, course = split_summary(event.summary)
    link = _link(event.url)
    base = base_url.rstrip("/")
    html_url = link.url
    if is_assignment and plannable_type == FEED_ASSIGNMENT and link.course_id is not None:
        html_url = f"{base}/courses/{link.course_id}/assignments/{plannable_id}"
    if event.day is not None:
        due_at = at_local(event.day, ALL_DAY_DUE if is_assignment else time(0, 0), zone)
    else:
        due_at = event.start
    return Item(
        plannable_type=plannable_type,
        plannable_id=plannable_id,
        title=title or event.summary or "(untitled)",
        type=ItemType.ASSIGNMENT if is_assignment else ItemType.EVENT,
        course_id=link.course_id,
        course_name=course,
        due_at=due_at,
        html_url=html_url,
    )
