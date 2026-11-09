"""Regressions for the pre-release review: crashes on odd input, overlapping sign-up
pruning, failure time in owner alerts, and state kept across a token/feed switch."""

import asyncio
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import ItemType, SendKind
from canvas_tracker.hub.hub import HostGuard, Verification, resolves_publicly
from canvas_tracker.hub.monitor import SYNC_FAILING_AFTER
from canvas_tracker.planning import keys
from canvas_tracker.planning.plan import plan
from canvas_tracker.render import copy
from canvas_tracker.runtime.sync import FeedSync, SyncOutcome
from canvas_tracker.sources import feed as feed_source
from canvas_tracker.sources.feed import FeedClient
from canvas_tracker.store import repo
from canvas_tracker.store.repo import LAST_SUCCESSFUL_SYNC_AT, SYNC_FAILING_SINCE
from tests.factories import NOW, make_item, make_settings
from tests.hub_helpers import FEED_PATH, FEED_URL, build_hub, feed_assignment, ics, sign_up
from tests.store_helpers import new_store

H = timedelta(hours=1)
NY = ZoneInfo("America/New_York")
LONG_LABEL_FEED = f"https://{'a' * 64}.example.edu/feeds/calendars/user_x.ics"


# --- the host check and feed check always answer -------------------------------------


async def test_a_hostname_label_over_63_characters_is_refused_not_raised() -> None:
    assert not await resolves_publicly(f"{'a' * 64}.example.edu")


async def test_a_host_check_that_raises_refuses_the_host() -> None:
    async def broken(_host: str) -> bool:
        raise UnicodeError("label too long")

    guard = HostGuard(broken, lambda: NOW)
    assert not await guard("a.example")


async def test_verify_feed_answers_whatever_the_client_raises(tmp_path: Path) -> None:
    env = build_hub(tmp_path)

    class Exploding(FeedClient):
        async def fetch(self, etag: str | None = None, last_modified: str | None = None):  # type: ignore[no-untyped-def]
            raise RuntimeError("something nobody expected")

    env.hub.feed_client_factory = lambda _base, url: Exploding(url)
    assert await env.hub.verify_feed(FEED_URL) == Verification("not_feed")


async def test_a_feed_link_with_a_huge_host_label_gets_a_reply(tmp_path: Path) -> None:
    def public(host: str) -> bool:
        if len(host.split(".")[0]) > 63:
            raise UnicodeError("label too long")  # what getaddrinfo does
        return True

    env = build_hub(tmp_path, public=public)
    await env.signup.start(1, "Me", None)
    user = env.hub.registry.get_user(1)
    assert user is not None
    replies = await env.signup.text(user, LONG_LABEL_FEED)
    assert replies and all(r.text for r in replies)


async def test_a_feed_that_cant_be_parsed_in_odd_ways_is_not_a_feed(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.feeds[FEED_PATH] = b"BEGIN:VCALENDAR\r\n" + b"BEGIN:A\r\n" * 50_000
    assert await env.hub.verify_feed(FEED_URL) == Verification(None)


# --- pruning stalled sign-ups --------------------------------------------------------


async def test_someone_who_comes_back_while_pruning_runs_is_kept(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    for telegram_id in (5, 6):
        code = env.hub.registry.create_invite(NOW)
        await env.signup.start(telegram_id, "Friend", code)
    env.clock.now = NOW + timedelta(days=8)
    gate = asyncio.Event()
    env.hub.notifier_factory(5)  # creates the fake notifier
    real_send = env.notifiers[5].send

    async def slow_send(msg):  # type: ignore[no-untyped-def]
        await gate.wait()  # the notice to 5 is in flight ...
        return await real_send(msg)

    env.notifiers[5].send = slow_send  # type: ignore[method-assign]
    first = asyncio.create_task(env.hub.prune_signups())
    second = asyncio.create_task(env.hub.prune_signups())  # /start prunes at the same time
    await asyncio.sleep(0)
    six = env.hub.registry.get_user(6)
    assert six is not None
    await env.signup.start(6, "Friend", None)  # ... while 6 comes back
    gate.set()
    removed = [*await first, *await second]
    assert removed == [5]
    assert env.hub.registry.get_user(6) is not None
    assert [m.text for m in env.notifiers[5].sent].count(copy.SIGNUP_EXPIRED) == 1
    six_heard = [m.text for m in env.notifiers[6].sent] if 6 in env.notifiers else []
    assert copy.SIGNUP_EXPIRED not in six_heard


def test_delete_stale_signup_only_deletes_stalled_rows(tmp_path: Path) -> None:
    from canvas_tracker.hub.registry import open_registry

    reg = open_registry(tmp_path / "registry.db")
    reg.create_user(5, "A", now=NOW)
    assert not reg.delete_stale_signup(5, NOW - H)  # seen after the cutoff: kept
    assert reg.delete_stale_signup(5, NOW + H)
    assert reg.get_user(5) is None


# --- owner alerts count failing time, not time without syncs -------------------------


async def test_one_failure_after_a_long_outage_doesnt_alert_the_owner(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.feeds[FEED_PATH] = ics()
    await sign_up(env, 1, name="Owner")
    await sign_up(env, 2, name="Mia", feed=FEED_URL)
    for tenant in list(env.hub.tenants.values()):
        if tenant.running is not None:
            await tenant.running
    tenant = env.hub.tenants[2]
    assert tenant.store.get_time(SYNC_FAILING_SINCE) is None
    tenant.store.set_time(LAST_SUCCESSFUL_SYNC_AT, NOW - 7 * H)  # the server was down
    env.canvas.feed_status = 503
    env.clock.now = NOW + H
    assert await tenant.sync.sync(env.clock()) is SyncOutcome.UNAVAILABLE
    assert tenant.store.get_time(SYNC_FAILING_SINCE) == NOW + H
    assert await env.hub.watch() == []  # failed once, just now
    env.clock.now = NOW + H + SYNC_FAILING_AFTER
    assert await tenant.sync.sync(env.clock()) is SyncOutcome.UNAVAILABLE
    assert tenant.store.get_time(SYNC_FAILING_SINCE) == NOW + H  # the first failure counts
    [alert] = await env.hub.watch()
    assert "6 h" in alert
    env.canvas.feed_status = 200
    assert await tenant.sync.sync(env.clock()) is SyncOutcome.OK
    assert tenant.store.get_time(SYNC_FAILING_SINCE) is None


# --- switching between token and feed keeps what the user did ------------------------


def _planner(**overrides: object):  # type: ignore[no-untyped-def]
    return make_item(plannable_type="assignment", course_id=42, **overrides)  # type: ignore[arg-type]


def _feed_body(*assignments: tuple[int, str]) -> bytes:
    return ics(*(feed_assignment(n, due) for n, due in assignments))


async def _feed_sync(store: repo.Store, body: bytes) -> SyncOutcome:
    async def no_sleep(_s: float) -> None:
        return None

    client = FeedClient(
        lambda: FEED_URL,
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=body)),
        sleep=no_sleep,
    )
    return await FeedSync(client, store, "https://school.instructure.com", zone=NY).sync(NOW)


def test_feed_constants_match_the_store() -> None:
    assert repo.FEED_ASSIGNMENT == feed_source.FEED_ASSIGNMENT
    assert repo.FEED_EVENT == feed_source.FEED_EVENT


async def test_token_to_feed_keeps_done_snoozed_stopped_and_reminder_history() -> None:
    store = new_store()
    due = NOW + 1 * H
    submitted = _planner(plannable_id=101, assignment_id=101, due_at=due, submitted=True)
    snoozed = _planner(plannable_id=102, assignment_id=102, due_at=due)
    reminded = _planner(plannable_id=103, assignment_id=103, due_at=due)
    store.upsert_items([submitted, snoozed, reminded], NOW - 2 * H)
    by_ref = {i.ref: i for i in store.snapshot().items}
    snoozed_id = by_ref["assignment-102"].db_id
    assert snoozed_id is not None
    store.snooze(snoozed_id, NOW + 3 * H)
    store.claim("rem:x:0", SendKind.REMINDER, ["assignment-103"], NOW - H)
    store.mark_sent("rem:x:0", NOW - H, 1)
    overdue = keys.overdue_key(by_ref["assignment-103"])
    store.claim(overdue, SendKind.OVERDUE, ["assignment-103"], NOW - H)
    store.mark_sent(overdue, NOW - H, 2)

    store.use_source("feed")
    stamp = due.strftime("%Y%m%dT%H%M00Z")
    assert await _feed_sync(store, _feed_body((101, stamp), (102, stamp), (103, stamp))) is (
        SyncOutcome.OK
    )
    items = {i.ref: i for i in store.snapshot().items}
    assert set(items) == {"feed_assignment-101", "feed_assignment-102", "feed_assignment-103"}
    assert items["feed_assignment-102"].db_id == snoozed_id  # same row: old buttons still work
    assert items["feed_assignment-102"].snoozed_until == NOW + 3 * H
    assert is_done(items["feed_assignment-101"])  # Canvas knew it was submitted
    assert not is_done(items["feed_assignment-103"])
    snap = store.snapshot()
    assert snap.last_reminded_at["feed_assignment-103"] == NOW - H
    assert keys.overdue_key(items["feed_assignment-103"]) in snap.sent_keys
    sends = plan(NOW, snap, make_settings(tz="America/New_York")).sends
    assert not [s for s in sends if s.kind is SendKind.NEW_URGENT]


async def test_feed_to_token_keeps_the_done_mark() -> None:
    store = new_store()
    store.use_source("feed")
    due = NOW + 5 * H
    stamp = due.strftime("%Y%m%dT%H%M00Z")
    await _feed_sync(store, _feed_body((201, stamp)))
    [item] = store.snapshot().items
    assert item.db_id is not None
    store.set_bot_done(item.db_id, NOW)
    store.use_source("token")
    planner = _planner(plannable_id=201, assignment_id=201, due_at=due + timedelta(seconds=59))
    store.upsert_items([planner], NOW)
    [after] = store.snapshot().items
    assert after.ref == "assignment-201" and after.db_id == item.db_id and is_done(after)


def test_an_extension_during_a_switch_still_reopens_the_item() -> None:
    store = new_store()
    old = _planner(plannable_id=301, assignment_id=301, due_at=NOW + H, type=ItemType.ASSIGNMENT)
    store.upsert_items([old], NOW)
    [item] = store.snapshot().items
    assert item.db_id is not None
    store.set_bot_done(item.db_id, NOW)
    moved = make_item(
        plannable_type=repo.FEED_ASSIGNMENT, plannable_id=301, due_at=NOW + 30 * H, course_id=42
    )
    store.upsert_items([moved], NOW)
    [after] = store.snapshot().items
    assert after.db_id == item.db_id and not is_done(after)


# --- wording that matches what the bot does (review findings) -------------------------


async def test_a_token_without_planner_access_points_to_the_feed(tmp_path: Path) -> None:
    from tests.hub_helpers import NO_PLANNER_TOKEN

    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    me = env.hub.registry.get_user(1)
    assert me is not None
    await env.signup.text(me, "school.instructure.com")
    me = env.hub.registry.get_user(1)
    assert me is not None
    [reply] = await env.signup.text(me, NO_PLANNER_TOKEN)
    assert reply.text == copy.TOKEN_PROBLEMS["no_planner"] and "📅" in reply.text
    buttons = [b for row in reply.keyboard for b in row]
    assert any(b.label == copy.BTN_USE_FEED for b in buttons)


async def test_feed_users_disconnect_and_removal_dont_mention_a_token(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.feeds[FEED_PATH] = ics()
    await sign_up(env, 1)
    await sign_up(env, 5, name="Ben", feed=FEED_URL)
    await sign_up(env, 6, name="Cy", feed=FEED_URL)
    five = env.hub.registry.get_user(5)
    owner = env.hub.registry.get_user(1)
    assert five is not None and five.feed_mode and owner is not None
    [confirm] = env.signup.disconnect_prompt(five)
    assert confirm.text == copy.DISCONNECT_CONFIRM_FEED and "token" not in confirm.text
    [bye] = await env.signup.disconnect(five, confirmed=True)
    assert bye.text == copy.DISCONNECTED_FEED and "token" not in bye.text
    await env.signup.remove_confirmed(owner, "6")
    assert [m.text for m in env.notifiers[6].sent][-1] == copy.REMOVED_BY_OWNER_FEED
    [token_confirm] = env.signup.disconnect_prompt(owner)
    assert token_confirm.text == copy.DISCONNECT_CONFIRM


def test_feed_rhythm_and_stale_note_say_done_not_submitted() -> None:
    from canvas_tracker.render.items import stale_note
    from canvas_tracker.render.views import rhythm_sentence
    from tests.factories import make_snapshot

    feed = make_settings(calendar_feed=True)
    assert rhythm_sentence(feed).endswith("until you mark it ✅ Done.")
    assert "submitted" not in rhythm_sentence(feed)
    assert "submitted" in rhythm_sentence(make_settings())
    snap = make_snapshot(last_successful_sync_at=NOW - 5 * H)
    assert "✅ Done" in stale_note(snap, NOW, feed) and "submitted" not in stale_note(
        snap, NOW, feed
    )
    assert "submitted" in stale_note(snap, NOW, make_settings())


def test_the_reminders_menu_names_what_the_window_does() -> None:
    assert "Start reminding: due within {window}" in copy.REMINDERS_MENU
    assert "urgent" not in copy.REMINDERS_MENU


def test_token_expiry_advice_is_the_same_everywhere() -> None:
    assert "120 days or less" in copy.ASK_TOKEN and "120 days or less" in copy.AUTH_ALERT
    assert "latest date" not in copy.ASK_TOKEN and "best" not in copy.ASK_TOKEN
