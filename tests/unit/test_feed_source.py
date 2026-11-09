"""Calendar-feed mode: link checks, mapping feed entries to Items, the client, FeedSync."""

import gzip
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import ItemType
from canvas_tracker.hub.parsing import contains_feed_url, normalize_feed_url
from canvas_tracker.runtime.logging import REDACTED, RedactingFilter
from canvas_tracker.runtime.sync import FeedSync, SyncOutcome
from canvas_tracker.sources.canvas_client import CanvasProtocolError, CanvasUnavailable
from canvas_tracker.sources.feed import (
    FEED_ASSIGNMENT,
    FEED_EVENT,
    FEED_OTHER,
    FeedClient,
    FeedRejected,
    FeedTooLarge,
    feed_identity,
    is_feed_url,
    map_feed_event,
    split_summary,
)
from canvas_tracker.sources.ical import CalendarEvent, parse_calendar
from canvas_tracker.store.repo import (
    AUTH_FAILED_SINCE,
    FEED_ETAG,
    FEED_LAST_MODIFIED,
    LAST_ENRICHMENT_AT,
    LAST_SUCCESSFUL_SYNC_AT,
    LAST_SYNC_ERROR,
    PLANNER_ETAG,
    SOURCE_MODE,
    Store,
)
from tests.factories import NOW
from tests.hub_helpers import FEED_PATH, FEED_URL, feed_assignment, ics
from tests.store_helpers import new_store

BASE = "https://school.instructure.com"
NY = ZoneInfo("America/New_York")
FIXTURE = Path(__file__).parents[1] / "fixtures/canvas/calendar_feed.handmade.ics"

# --- links -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (FEED_URL, FEED_URL),
        (f"  {FEED_URL}\n", FEED_URL),
        (FEED_URL.replace("https://", "webcal://"), FEED_URL),
        (FEED_URL.replace("https://", "WEBCAL://"), FEED_URL),
        (FEED_URL.removeprefix("https://"), FEED_URL),
        (FEED_URL.replace("school.instructure.com", "School.Instructure.COM"), FEED_URL),
        (FEED_URL.replace(".com/", ".com:443/"), FEED_URL),
        (f"{FEED_URL}#top", FEED_URL),
    ],
)
def test_normalize_feed_url_accepts_canvas_feed_links(text: str, expected: str) -> None:
    assert normalize_feed_url(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        FEED_URL.replace("https://", "http://"),  # never plain http
        FEED_URL.replace("https://", "ftp://"),
        FEED_URL.replace("school.instructure.com", "localhost"),
        FEED_URL.replace("school.instructure.com", "canvas.local"),
        FEED_URL.replace("school.instructure.com", "canvas.internal"),
        FEED_URL.replace("school.instructure.com", "10.0.0.5"),
        FEED_URL.replace("school.instructure.com", "[::1]"),
        FEED_URL.replace(".com/", ".com:8443/"),
        FEED_URL.replace("https://", "https://me:pw@"),
        f"{FEED_URL}?x=1",
        "https://school.instructure.com/calendar",
        "https://school.instructure.com/feeds/calendars/user_x.txt",
        "https://school.instructure.com/feeds/calendars/../../etc/passwd.ics",
        "https://school.instructure.com/feeds/calendars/a/b.ics",
        f"{FEED_URL} extra words",
        "",
    ],
)
def test_normalize_feed_url_refuses_everything_else(text: str) -> None:
    assert normalize_feed_url(text) is None


def test_is_feed_url_is_strict() -> None:
    assert is_feed_url(FEED_URL)
    assert not is_feed_url(FEED_URL.replace("https", "http"))
    assert not is_feed_url(f"{FEED_URL}?q=1")
    assert not is_feed_url("https://school.instructure.com/api/v1/users/self")
    assert not is_feed_url("https://school.instructure.com:99999/feeds/calendars/user_a.ics")


def test_contains_feed_url_spots_links_in_any_text() -> None:
    assert contains_feed_url(f"here you go {FEED_URL} thanks")
    assert contains_feed_url("HTTPS://X.EDU/FEEDS/CALENDARS/USER_A.ICS")
    assert not contains_feed_url("https://school.instructure.com/calendar")


def test_feed_links_are_redacted_from_logs() -> None:
    redacting = RedactingFilter([])
    text = redacting.redact(f"GET {FEED_URL} failed; also webcal link {FEED_URL}.")
    assert FEED_PATH not in text and "user_TEST" not in text
    assert text.count(REDACTED) == 2


# --- mapping -----------------------------------------------------------------------


def event(
    uid: str, summary: str = "Essay [ENG 101]", url: str | None = None, day: date | None = None
) -> CalendarEvent:
    start = datetime(2026, 10, 21, 4, 59, tzinfo=UTC)
    return CalendarEvent(uid=uid, summary=summary, start=start, url=url, day=day)


@pytest.mark.parametrize(
    ("uid", "url", "identity"),
    [
        ("event-assignment-501", None, (FEED_ASSIGNMENT, 501, True)),
        ("event-calendar-event-9001", None, (FEED_EVENT, 9001, False)),
        ("event-assignment-override-7", None, ("feed_assignment_override", 7, True)),
        ("event-sub-assignment-8", None, ("feed_sub_assignment", 8, True)),
        ("event-appointment-group-3", None, ("feed_appointment_group", 3, False)),
        ("odd", f"{BASE}/courses/4/assignments/77", (FEED_ASSIGNMENT, 77, True)),
        (
            "odd",
            f"{BASE}/calendar?assignment_id=78&include_contexts=course_4",
            (FEED_ASSIGNMENT, 78, True),
        ),
    ],
)
def test_feed_identity(uid: str, url: str | None, identity: tuple[str, int, bool]) -> None:
    assert feed_identity(event(uid, url=url)) == identity


def test_feed_identity_hashes_unknown_uids_stably_and_never_like_the_planner() -> None:
    kind, first, assignment = feed_identity(event("holiday@school.edu"))
    assert (kind, assignment) == (FEED_OTHER, False)
    assert feed_identity(event("holiday@school.edu"))[1] == first
    assert 0 < first < 2**48
    assert feed_identity(event("other@school.edu"))[1] != first


@pytest.mark.parametrize(
    ("summary", "parts"),
    [
        ("Essay draft [ENG 101]", ("Essay draft", "ENG 101")),
        ("Lab [2] report [CHEM 1]", ("Lab [2] report", "CHEM 1")),
        ("No course", ("No course", "")),
        ("[ENG 101]", ("[ENG 101]", "")),
        ("  Spaced   [X] ", ("Spaced", "X")),
    ],
)
def test_split_summary(summary: str, parts: tuple[str, str]) -> None:
    assert split_summary(summary) == parts


def test_map_assignment_from_the_canvas_style_entry() -> None:
    item = map_feed_event(
        event(
            "event-assignment-501",
            url=f"{BASE}/calendar?assignment_id=501&include_contexts=course_42",
        ),
        BASE,
        NY,
    )
    assert item.plannable_type == FEED_ASSIGNMENT and item.plannable_id == 501
    assert item.type is ItemType.ASSIGNMENT
    assert (item.title, item.course_name, item.course_id) == ("Essay", "ENG 101", 42)
    assert item.due_at == datetime(2026, 10, 21, 4, 59, tzinfo=UTC)
    assert item.html_url == f"{BASE}/courses/42/assignments/501"
    # nothing about submissions, and nothing that would trigger API enrichment
    assert item.assignment_id is None and not item.submitted and not is_done(item)


def test_all_day_assignment_is_due_at_1159_pm_local_and_all_day_event_at_midnight() -> None:
    day = date(2026, 10, 22)
    work = map_feed_event(event("event-assignment-2", day=day), BASE, NY)
    party = map_feed_event(event("event-calendar-event-3", summary="Fall break", day=day), BASE, NY)
    assert work.due_at == datetime(2026, 10, 23, 3, 59, tzinfo=UTC)  # 11:59 PM EDT
    assert party.due_at == datetime(2026, 10, 22, 4, 0, tzinfo=UTC)  # midnight EDT
    assert party.type is ItemType.EVENT and party.course_name == ""


def test_map_keeps_event_links_and_drops_non_https_ones() -> None:
    linked = map_feed_event(
        event("event-calendar-event-9", url=f"{BASE}/calendar?event_id=9"), BASE, NY
    )
    plain = map_feed_event(event("event-calendar-event-10", url="http://evil.example/x"), BASE, NY)
    assert linked.html_url == f"{BASE}/calendar?event_id=9"
    assert plain.html_url is None and plain.course_id is None


def test_map_untitled_entry() -> None:
    assert map_feed_event(event("event-assignment-1", summary=""), BASE, NY).title == "(untitled)"


def test_whole_fixture_maps_without_collisions() -> None:
    items = [map_feed_event(e, BASE, NY) for e in parse_calendar(FIXTURE.read_bytes(), NY).events]
    assert len({i.ref for i in items}) == len(items) == 5
    assert all(i.plannable_type.startswith("feed_") for i in items)


# --- the client --------------------------------------------------------------------


class Server:
    """A fake Canvas that serves one feed and records every request."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.respond = respond or (lambda _r: httpx.Response(200, content=ics()))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)


def client(server: Server, url: str = FEED_URL, **kw: object) -> FeedClient:
    async def no_sleep(_s: float) -> None:
        return None

    return FeedClient(
        lambda: url,
        host="school.instructure.com",
        transport=httpx.MockTransport(server),
        sleep=no_sleep,
        **kw,  # type: ignore[arg-type]
    )


async def test_fetch_returns_the_body_and_validators_without_any_token() -> None:
    server = Server(
        lambda _r: httpx.Response(
            200, content=ics(), headers={"ETag": '"v1"', "Last-Modified": "Tue, 20 Oct 2026"}
        )
    )
    response = await client(server).fetch()
    assert not response.not_modified and response.body.startswith(b"BEGIN:VCALENDAR")
    assert (response.etag, response.last_modified) == ('"v1"', "Tue, 20 Oct 2026")
    [request] = server.requests
    assert "Authorization" not in request.headers and request.url == FEED_URL


async def test_validators_are_sent_and_304_means_not_modified() -> None:
    server = Server(lambda _r: httpx.Response(304))
    response = await client(server).fetch('"v1"', "Tue, 20 Oct 2026")
    assert response.not_modified and response.etag == '"v1"'
    headers = server.requests[0].headers
    assert headers["If-None-Match"] == '"v1"'
    assert headers["If-Modified-Since"] == "Tue, 20 Oct 2026"


@pytest.mark.parametrize("status", [401, 403, 404, 410])
async def test_refused_links_are_rejected(status: int) -> None:
    with pytest.raises(FeedRejected):
        await client(Server(lambda _r: httpx.Response(status))).fetch()


async def test_throttling_and_server_errors_are_retried_then_unavailable() -> None:
    server = Server(lambda _r: httpx.Response(403, text="403 Forbidden (Rate Limit Exceeded)"))
    with pytest.raises(CanvasUnavailable):
        await client(server, max_retries=2).fetch()
    assert len(server.requests) == 3

    answers = iter([httpx.Response(503), httpx.Response(200, content=ics())])
    server = Server(lambda _r: next(answers))
    assert not (await client(server, max_retries=2).fetch()).not_modified


async def test_network_errors_become_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(CanvasUnavailable):
        await client(Server(boom), max_retries=1).fetch()


async def test_other_client_errors_are_protocol_errors() -> None:
    with pytest.raises(CanvasProtocolError):
        await client(Server(lambda _r: httpx.Response(400))).fetch()


async def test_same_host_redirects_are_followed() -> None:
    moved = f"{BASE}/feeds/calendars/user_moved.ics"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == FEED_PATH:
            return httpx.Response(302, headers={"Location": "/feeds/calendars/user_moved.ics"})
        return httpx.Response(200, content=ics())

    server = Server(respond)
    await client(server).fetch()
    assert [str(r.url) for r in server.requests] == [FEED_URL, moved]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/feeds/calendars/user_a.ics",
        "http://school.instructure.com/feeds/calendars/user_a.ics",  # no downgrade
        "https://school.instructure.com:8443/feeds/calendars/user_a.ics",
        "https://169.254.169.254/latest/meta-data",
    ],
)
async def test_redirects_to_another_host_are_refused(location: str) -> None:
    server = Server(lambda _r: httpx.Response(301, headers={"Location": location}))
    with pytest.raises(CanvasProtocolError, match="another host"):
        await client(server).fetch()
    assert len(server.requests) == 1


async def test_redirect_loops_and_missing_locations_stop() -> None:
    server = Server(lambda _r: httpx.Response(302, headers={"Location": FEED_PATH}))
    with pytest.raises(CanvasProtocolError, match="too many redirects"):
        await client(server).fetch()
    assert len(server.requests) == 4
    with pytest.raises(CanvasProtocolError, match="location"):
        await client(Server(lambda _r: httpx.Response(302))).fetch()


async def test_oversized_feeds_are_refused_by_header_or_while_reading() -> None:
    declared = Server(
        lambda _r: httpx.Response(200, content=b"x", headers={"Content-Length": "999999999"})
    )
    with pytest.raises(FeedTooLarge):
        await client(declared).fetch()
    streamed = Server(lambda _r: httpx.Response(200, content=b"x" * 2000))
    with pytest.raises(FeedTooLarge):
        await client(streamed, max_bytes=1000).fetch()


async def test_a_compressed_feed_counts_at_its_unpacked_size() -> None:
    bomb = gzip.compress(b"A" * 200_000)  # about 200 bytes on the wire
    server = Server(
        lambda _r: httpx.Response(200, content=bomb, headers={"Content-Encoding": "gzip"})
    )
    with pytest.raises(FeedTooLarge):
        await client(server, max_bytes=100_000).fetch()


async def test_links_that_arent_feeds_or_are_on_another_host_are_never_requested() -> None:
    server = Server()
    with pytest.raises(CanvasProtocolError):
        await client(server, url="https://school.instructure.com/api/v1/users/self").fetch()
    with pytest.raises(CanvasProtocolError, match="another host"):
        await client(server, url="https://other.instructure.com/feeds/calendars/user_a.ics").fetch()
    assert server.requests == []


async def test_an_unreadable_stored_link_counts_as_rejected() -> None:
    def broken() -> str:
        raise OSError("can't be decrypted")

    feed = FeedClient(broken, transport=httpx.MockTransport(Server()))
    with pytest.raises(FeedRejected):
        await feed.fetch()


# --- FeedSync ----------------------------------------------------------------------


def feed_sync(store: Store, server: Server, host_ok: bool = True) -> FeedSync:
    async def host_check() -> bool:
        return host_ok

    return FeedSync(client(server), store, BASE, zone=NY, host_check=host_check)


async def test_sync_stores_feed_items_and_validators() -> None:
    store = new_store()
    body = ics(
        feed_assignment(501, "20261021T045900Z"),
        "DTSTART:20261020T190000Z\r\nSUMMARY:Office hours [ENG 101]\r\n"
        "UID:event-calendar-event-9001",
        feed_assignment(600, "20260101T000000Z", "Long ago"),  # outside the window
        feed_assignment(601, "20270601T000000Z", "Far future"),
    )
    server = Server(lambda _r: httpx.Response(200, content=body, headers={"ETag": '"v1"'}))
    assert await feed_sync(store, server).sync(NOW) is SyncOutcome.OK
    snap = store.snapshot()
    assert sorted((i.ref, i.type) for i in snap.items) == [
        ("feed_assignment-501", ItemType.ASSIGNMENT),
        ("feed_event-9001", ItemType.EVENT),
    ]
    assert store.get_state(FEED_ETAG) == '"v1"' and store.get_state(FEED_LAST_MODIFIED) is None
    assert store.get_time(LAST_SUCCESSFUL_SYNC_AT) == NOW
    assert not store.needs_enrichment()


async def test_vanished_entries_are_gone_and_bot_done_survives_a_resync() -> None:
    store = new_store()
    bodies = iter(
        [
            ics(feed_assignment(1, "20261021T045900Z"), feed_assignment(2, "20261022T045900Z")),
            ics(feed_assignment(1, "20261021T045900Z")),
        ]
    )
    server = Server(lambda _r: httpx.Response(200, content=next(bodies)))
    sync = feed_sync(store, server)
    await sync.sync(NOW)
    first = next(i for i in store.snapshot().items if i.plannable_id == 1)
    assert first.db_id is not None
    store.set_bot_done(first.db_id, NOW)
    await sync.sync(NOW + timedelta(minutes=10))
    items = {i.plannable_id: i for i in store.snapshot().items}
    assert is_done(items[1]) and items[2].gone_at is not None


async def test_not_modified_keeps_items_and_counts_as_success() -> None:
    store = new_store()
    store.set_state(FEED_ETAG, '"v1"')
    server = Server(lambda r: httpx.Response(304 if r.headers.get("If-None-Match") else 500))
    assert await feed_sync(store, server).sync(NOW) is SyncOutcome.NOT_MODIFIED
    assert store.get_time(LAST_SUCCESSFUL_SYNC_AT) == NOW


async def test_a_rejected_link_is_an_auth_failure() -> None:
    store = new_store()
    outcome = await feed_sync(store, Server(lambda _r: httpx.Response(404))).sync(NOW)
    assert outcome is SyncOutcome.AUTH_FAILED
    assert store.get_time(AUTH_FAILED_SINCE) == NOW
    assert store.get_state(LAST_SYNC_ERROR) == "FeedRejected"


async def test_garbage_is_a_protocol_error_and_keeps_old_items() -> None:
    store = new_store()
    good = Server(
        lambda _r: httpx.Response(200, content=ics(feed_assignment(1, "20261021T045900Z")))
    )
    await feed_sync(store, good).sync(NOW)
    bad = Server(lambda _r: httpx.Response(200, content=b"<html>Log in</html>"))
    assert await feed_sync(store, bad).sync(NOW) is SyncOutcome.PROTOCOL_ERROR
    assert store.get_state(LAST_SYNC_ERROR) == "CanvasProtocolError"
    assert [i.gone_at for i in store.snapshot().items] == [None]


async def test_a_private_host_is_never_fetched() -> None:
    store = new_store()
    server = Server()
    assert await feed_sync(store, server, host_ok=False).sync(NOW) is SyncOutcome.UNAVAILABLE
    assert server.requests == [] and store.get_state(LAST_SYNC_ERROR) == "CanvasHostRefused"


async def test_enrich_makes_no_requests() -> None:
    store = new_store()
    server = Server()
    assert await feed_sync(store, server).enrich(NOW) is SyncOutcome.OK
    assert server.requests == [] and store.get_time(LAST_ENRICHMENT_AT) == NOW


def test_switching_source_drops_cached_validators_once() -> None:
    store = new_store()
    store.set_state(PLANNER_ETAG, '"planner"')
    store.use_source("token")  # existing token users: nothing changes
    assert store.get_state(PLANNER_ETAG) == '"planner"' and store.get_state(SOURCE_MODE) is None
    store.use_source("feed")
    assert store.get_state(PLANNER_ETAG) is None and store.get_state(SOURCE_MODE) == "feed"
    store.set_state(FEED_ETAG, '"feed"')
    store.use_source("feed")
    assert store.get_state(FEED_ETAG) == '"feed"'
    store.use_source("token")
    assert store.get_state(FEED_ETAG) is None and store.get_state(SOURCE_MODE) == "token"


async def test_feed_sync_errors_never_log_the_link(caplog: pytest.LogCaptureFixture) -> None:
    store = new_store()

    def boom(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"crash while reading {FEED_URL}")

    with caplog.at_level(logging.WARNING):
        outcome = await feed_sync(store, Server(boom)).sync(NOW)
    assert outcome is SyncOutcome.PROTOCOL_ERROR
    texts = [
        r.getMessage() + (logging.Formatter().formatException(r.exc_info) if r.exc_info else "")
        for r in caplog.records
    ]
    assert any(FEED_PATH in t for t in texts)  # the raw traceback has it...
    redacting = RedactingFilter([])
    assert all(FEED_PATH not in redacting.redact(t) for t in texts)  # ...the log filter doesn't
