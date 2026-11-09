"""Calendar-feed mode through a real hub: sign-up on both paths, /settings switches,
alerts, /status, /users and the chat handlers. Token users must see no change."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker.bot.commands import status_cmd, sync_cmd
from canvas_tracker.domain.models import SendKind
from canvas_tracker.hub.handlers import feedback_cmd, on_text, setup_button
from canvas_tracker.hub.hub import TOKEN_CHECKS_PER_WINDOW
from canvas_tracker.hub.monitor import SYNC_FAILING_AFTER
from canvas_tracker.hub.registry import REGISTRY_MIGRATIONS, Registry, User
from canvas_tracker.hub.secretbox import SecretBox, generate_key
from canvas_tracker.render import copy
from canvas_tracker.runtime.sync import FeedSync, SyncService
from canvas_tracker.sources.feed import FeedClient
from canvas_tracker.store.db import _migrations, connect, migrate
from canvas_tracker.store.repo import AUTH_FAILED_SINCE
from tests.factories import NOW
from tests.hub_helpers import (
    FEED_PATH,
    FEED_URL,
    GOOD_TOKEN,
    OTHER_FEED_URL,
    HubEnv,
    build_hub,
    feed_assignment,
    ics,
    sign_up,
)
from tests.tg_helpers import callback_update, context, message_update, mock_bot

OTHER_FEED_PATH = "/feeds/calendars/user_OTHERfeedLINK987zyx.ics"


def texts(replies: list) -> list[str]:  # type: ignore[type-arg]
    return [r.text for r in replies]


def sent_texts(bot) -> list[str]:  # type: ignore[no-untyped-def]
    return [c.kwargs["text"] for c in bot.send_message.await_args_list]


def user(env: HubEnv, telegram_id: int) -> User:
    found = env.hub.registry.get_user(telegram_id)
    assert found is not None
    return found


def with_feed(env: HubEnv, path: str = FEED_PATH) -> None:
    env.canvas.feeds[path] = ics(feed_assignment(501, "20261021T045900Z"))


async def at_secret_step(env: HubEnv, telegram_id: int = 7) -> None:
    code = env.hub.registry.create_invite(NOW)
    await env.signup.start(telegram_id, "Ana", code)
    await env.signup.text(user(env, telegram_id), "school.instructure.com")


async def tick(env: HubEnv, telegram_id: int) -> None:
    tenant = env.hub.tenant(telegram_id)
    assert tenant is not None
    if tenant.running is not None:
        await tenant.running
    await tenant.tick()


# --- sign-up -----------------------------------------------------------------------


async def test_token_step_offers_both_ways(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await at_secret_step(env)
    [reply] = env.signup.prompt(user(env, 7))
    assert reply.text == copy.ASK_TOKEN
    assert "🔑 Access token" in reply.text and "📅 Calendar feed link" in reply.text
    assert reply.keyboard[0][0].url == "https://school.instructure.com/profile/settings"
    assert reply.keyboard[1][0].callback_data == "su:mode:feed"


async def test_sign_up_with_the_feed_button_end_to_end(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    with_feed(env)
    await at_secret_step(env)
    [reply] = await env.signup.choice(user(env, 7), "mode", "feed")
    assert reply.text == copy.ASK_FEED and user(env, 7).step == "feed"
    assert reply.keyboard[0][0].url == "https://school.instructure.com/calendar"
    assert reply.keyboard[1][0].callback_data == "su:mode:token"

    replies = await env.signup.text(user(env, 7), FEED_URL)
    assert texts(replies) == [copy.FEED_SAVED, copy.ASK_TZ]
    # the feed's own time zone is offered first
    assert replies[1].keyboard[0][0].callback_data == "su:tz:America/Chicago"
    stored = user(env, 7)
    assert stored.mode == "feed" and stored.token_sealed is None and stored.feed_sealed
    assert SecretBox(env.key).open(stored.feed_sealed) == FEED_URL
    assert FEED_URL.encode() not in (tmp_path / "registry.db").read_bytes()

    await env.signup.choice(user(env, 7), "tz", "America/Chicago")
    await env.signup.choice(user(env, 7), "dt", "07:00")
    [done] = await env.signup.choice(user(env, 7), "qh", "23:00-06:00")
    assert done.text.startswith("✅ All set!") and done.text.endswith(copy.FEED_ALL_SET)

    tenant = env.hub.tenant(7)
    assert tenant is not None and isinstance(tenant.sync, FeedSync)
    assert tenant.settings.calendar_feed
    await tick(env, 7)
    [item] = tenant.store.snapshot().items
    assert (item.plannable_type, item.title, item.course_name) == (
        "feed_assignment",
        "Essay",
        "ENG 101",
    )
    # only the feed was fetched: no API call, so no token was ever needed
    assert {path for _t, path in env.canvas.calls} == {FEED_PATH}


async def test_feed_link_pasted_at_the_token_step_or_address_step_just_works(
    tmp_path: Path,
) -> None:
    env = build_hub(tmp_path)
    with_feed(env)
    await at_secret_step(env, 7)
    assert texts(await env.signup.text(user(env, 7), FEED_URL)) == [copy.FEED_SAVED, copy.ASK_TZ]

    # at step 1 the link also names the Canvas site
    env.canvas.feeds["/feeds/calendars/user_x123.ics"] = ics()
    code = env.hub.registry.create_invite(NOW)
    await env.signup.start(8, "Ben", code)
    link = "webcal://canvas.school.edu/feeds/calendars/user_x123.ics"
    assert texts(await env.signup.text(user(env, 8), link)) == [copy.FEED_SAVED, copy.ASK_TZ]
    assert user(env, 8).canvas_base_url == "https://canvas.school.edu"


async def test_feed_link_replaces_a_differently_typed_address(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.feeds[FEED_PATH] = ics()
    code = env.hub.registry.create_invite(NOW)
    await env.signup.start(7, "Ana", code)
    await env.signup.text(user(env, 7), "canvas.school.edu")  # the vanity address
    await env.signup.text(user(env, 7), FEED_URL)
    assert user(env, 7).canvas_base_url == "https://school.instructure.com"


async def test_bad_feed_links_get_a_clear_answer(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.feeds[FEED_PATH] = b"<html>Please log in</html>"
    await at_secret_step(env)
    await env.signup.choice(user(env, 7), "mode", "feed")
    host = "school.instructure.com"
    for text, expected in (
        (FEED_URL.replace("https", "http"), copy.FEED_INVALID),
        ("https://school.instructure.com/calendar", copy.FEED_INVALID),
        ("just some words", copy.FEED_INVALID),
        (OTHER_FEED_URL, copy.FEED_PROBLEMS["rejected"].format(host=host)),  # 404
        (FEED_URL, copy.FEED_PROBLEMS["not_feed"].format(host=host)),  # not iCalendar
    ):
        assert texts(await env.signup.text(user(env, 7), text)) == [expected]
    assert user(env, 7).step == "feed" and user(env, 7).feed_sealed is None


async def test_feed_on_a_private_host_is_refused_before_any_request(tmp_path: Path) -> None:
    env = build_hub(tmp_path, public=lambda host: host != "school.instructure.com")
    await env.signup.start(1, "Me", None)
    await env.signup.text(user(env, 1), "canvas.school.edu")
    replies = await env.signup.text(user(env, 1), FEED_URL)
    assert texts(replies) == [
        copy.FEED_PROBLEMS["unreachable"].format(host="school.instructure.com")
    ]
    assert env.canvas.calls == []


async def test_feed_checks_share_the_token_rate_limit(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await at_secret_step(env)
    for _ in range(TOKEN_CHECKS_PER_WINDOW):
        await env.signup.text(user(env, 7), OTHER_FEED_URL)
    [reply] = await env.signup.text(user(env, 7), FEED_URL)
    assert reply.text == copy.FEED_TOO_MANY.format(minutes=15)
    assert env.signup.token_wait(user(env, 7)) is not None


async def test_switching_back_to_a_token_during_sign_up(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await at_secret_step(env)
    await env.signup.choice(user(env, 7), "mode", "feed")
    [reply] = await env.signup.choice(user(env, 7), "mode", "token")
    assert reply.text == copy.ASK_TOKEN and user(env, 7).step == "token"
    # a token pasted at the feed step is used as a token
    await env.signup.choice(user(env, 7), "mode", "feed")
    assert texts(await env.signup.text(user(env, 7), GOOD_TOKEN)) == [
        copy.TOKEN_SAVED,
        copy.ASK_TZ,
    ]
    assert user(env, 7).mode == "token"


async def test_mode_buttons_outside_the_secret_steps_do_nothing(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    assert texts(await env.signup.choice(user(env, 1), "mode", "feed")) == [copy.HELP]
    assert user(env, 1).mode == "token" and user(env, 1).step is None
    await at_secret_step(env, 7)
    assert texts(await env.signup.choice(user(env, 7), "mode", "bogus")) == [copy.ASK_TOKEN]


# --- token users are unaffected ----------------------------------------------------


async def test_token_users_keep_everything_as_before(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    stored = user(env, 1)
    assert stored.mode == "token" and stored.feed_sealed is None
    tenant = env.hub.tenant(1)
    assert tenant is not None and isinstance(tenant.sync, SyncService)
    assert not tenant.settings.calendar_feed
    [reply] = env.signup.settings(stored)
    assert f"Connection: {copy.CONNECTION_TOKEN}" in reply.text
    bot = mock_bot()
    await status_cmd(tenant.deps)(message_update("/status", user_id=1, bot=bot), context())
    [status] = sent_texts(bot)
    assert "Token: OK" in status and copy.STATUS_FEED_NOTE not in status


# --- /settings -----------------------------------------------------------------------


async def test_settings_switch_token_to_feed_and_back(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    with_feed(env)
    await sign_up(env, 1)
    [prompt] = env.signup.begin_edit(user(env, 1), "feed")
    assert prompt.text == copy.ASK_FEED_SWITCH and user(env, 1).step == "edit_feed"

    assert texts(await env.signup.text(user(env, 1), FEED_URL)) == [copy.FEED_SAVED]
    switched = user(env, 1)
    assert switched.mode == "feed" and switched.token_sealed is None and switched.step is None
    tenant = env.hub.tenant(1)
    assert tenant is not None and isinstance(tenant.sync, FeedSync)
    [reply] = env.signup.settings(switched)
    assert f"Connection: {copy.CONNECTION_FEED}" in reply.text

    [prompt] = env.signup.begin_edit(switched, "tok")
    assert prompt.text == copy.ASK_TOKEN_SWITCH
    assert texts(await env.signup.text(user(env, 1), GOOD_TOKEN)) == [copy.TOKEN_SAVED]
    back = user(env, 1)
    assert back.mode == "token" and back.feed_sealed is None and back.token_sealed
    tenant = env.hub.tenant(1)
    assert tenant is not None and isinstance(tenant.sync, SyncService)


async def test_feed_user_replaces_their_link_and_cancel_keeps_it(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1, feed=FEED_URL)
    [prompt] = env.signup.begin_edit(user(env, 1), "feed")
    assert prompt.text == copy.ASK_FEED_EDIT
    assert texts(env.signup.cancel(user(env, 1))) == [copy.CANCELLED]
    assert SecretBox(env.key).open(user(env, 1).feed_sealed or b"") == FEED_URL

    env.canvas.feeds[OTHER_FEED_PATH] = ics()
    env.signup.begin_edit(user(env, 1), "feed")
    assert texts(await env.signup.text(user(env, 1), OTHER_FEED_URL)) == [copy.FEED_SAVED]
    assert SecretBox(env.key).open(user(env, 1).feed_sealed or b"") == OTHER_FEED_URL


async def test_new_canvas_address_for_a_feed_user_asks_for_a_feed_link(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1, feed=FEED_URL)
    env.signup.begin_edit(user(env, 1), "url")
    [prompt] = await env.signup.text(user(env, 1), "canvas.other.edu")
    assert prompt.text == copy.ASK_FEED_NEW_SITE and user(env, 1).step == "edit_feed"
    assert prompt.keyboard[0][0].url == "https://canvas.other.edu/calendar"
    assert user(env, 1).canvas_base_url == "https://school.instructure.com"  # not yet


# --- running in feed mode -------------------------------------------------------------


async def test_rejected_feed_alerts_once_and_shows_in_status_and_users(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)  # the owner, on a token
    await sign_up(env, 7, feed=FEED_URL)
    await tick(env, 7)
    del env.canvas.feeds[FEED_PATH]  # the link stops working
    env.clock.now = NOW + timedelta(minutes=11)
    await tick(env, 7)
    tenant = env.hub.tenant(7)
    assert tenant is not None and tenant.store.get_time(AUTH_FAILED_SINCE) is not None
    alerts = [m.text for m in env.notifiers[7].sent if m.text == copy.FEED_AUTH_ALERT]
    assert len(alerts) == 1
    assert copy.AUTH_ALERT not in [m.text for m in env.notifiers[7].sent]

    bot = mock_bot()
    await status_cmd(tenant.deps)(message_update("/status", user_id=7, bot=bot), context())
    [status] = sent_texts(bot)
    assert "Calendar feed: failed since" in status and copy.STATUS_FEED_NOTE in status

    bot = mock_bot()
    await sync_cmd(tenant.deps)(message_update("/sync", user_id=7, bot=bot), context())
    assert sent_texts(bot) == [copy.SYNC_FAILED_FEED_AUTH]

    [users] = env.signup.users(user(env, 1))
    lines = users.text.splitlines()
    assert " · token · ✓ synced" in lines[1]
    assert " · feed · 📅 feed link rejected since" in lines[2]
    assert FEED_PATH not in users.text


async def test_feed_reminders_never_claim_to_know_about_submissions(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1, feed=FEED_URL)
    env.canvas.feeds[FEED_PATH] = ics(feed_assignment(501, "20261021T010000Z"))  # in 9 hours
    await tick(env, 1)
    sent = [m.text for m in env.notifiers[1].sent]
    assert sent, "an urgent assignment should be reminded"
    assert all("not submitted" not in text for text in sent)
    tenant = env.hub.tenant(1)
    assert tenant is not None
    kinds = {row["kind"] for row in tenant.store.conn.execute("SELECT kind FROM notifications")}
    assert kinds & {SendKind.REMINDER.value, SendKind.NEW_URGENT.value}


async def test_undecryptable_feed_link_marks_the_user_broken(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1, feed=FEED_URL)
    await env.hub.close()
    env.hub.box = SecretBox(generate_key())  # TOKEN_KEY was replaced
    env.hub.tenants.clear()
    assert env.hub.load() == [1]


# --- chat handlers -------------------------------------------------------------------


async def test_feed_link_message_is_deleted_and_checked(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    with_feed(env)
    await env.signup.start(1, "Me", None)
    await env.signup.text(user(env, 1), "school.instructure.com")
    bot = mock_bot()
    await on_text(env.signup)(message_update(FEED_URL, user_id=1, bot=bot), context())
    bot.delete_message.assert_awaited_once()
    assert sent_texts(bot) == [
        copy.FEED_DELETED,
        copy.FEED_CHECKING,
        copy.FEED_SAVED,
        copy.ASK_TZ,
    ]
    assert all(FEED_PATH not in t for t in sent_texts(bot))


async def test_feed_link_pasted_anywhere_is_deleted_but_not_used(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    bot = mock_bot()
    await on_text(env.signup)(message_update(f"my feed {FEED_URL}", user_id=1, bot=bot), context())
    bot.delete_message.assert_awaited_once()
    assert sent_texts(bot) == [copy.FEED_DELETED, copy.HELP]
    assert user(env, 1).mode == "token"


async def test_feed_mode_button_through_the_handler(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await at_secret_step(env, 7)
    bot = mock_bot()
    await setup_button(env.signup)(callback_update("su:mode:feed", user_id=7, bot=bot), context())
    assert sent_texts(bot) == [copy.ASK_FEED]


async def test_feedback_with_a_feed_link_is_deleted_and_not_forwarded(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    env.notifiers[1].sent.clear()
    bot = mock_bot()
    update = message_update(f"/feedback broken? {FEED_URL}", user_id=5, bot=bot)
    await feedback_cmd(env.signup)(update, context())
    bot.delete_message.assert_awaited_once()
    assert sent_texts(bot) == [copy.FEED_DELETED, copy.FEEDBACK_HAS_FEED]
    assert env.notifiers[1].sent == []


async def test_an_oversized_feed_tells_the_owner_why_after_six_hours(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 7, feed=FEED_URL)
    await tick(env, 7)
    tenant = env.hub.tenant(7)
    assert tenant is not None and isinstance(tenant.client, FeedClient)
    tenant.client._max_bytes = 10  # the feed outgrew the limit
    env.clock.now = NOW + timedelta(minutes=11)
    await tick(env, 7)
    assert await env.hub.watch() == []
    env.clock.now = NOW + SYNC_FAILING_AFTER + timedelta(minutes=12)
    [alert] = await env.hub.watch()
    assert copy.MONITOR_REASON_FEED_TOO_LARGE in alert and FEED_PATH not in alert


def test_registry_upgrade_keeps_existing_users_on_tokens(tmp_path: Path) -> None:
    conn = connect(tmp_path / "old.db")
    for number, sql in _migrations(REGISTRY_MIGRATIONS):
        if number >= 6:
            break
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    conn.execute(
        "INSERT INTO users (telegram_id, status, display_name, canvas_base_url, token_sealed, "
        "tz, quiet, created_at) VALUES (5, 'active', 'Old', 'https://x.edu', x'00', 'UTC', "
        "'off', '2026-01-01T00:00:00.000000Z')"
    )
    migrate(conn, REGISTRY_MIGRATIONS)
    registry = Registry(conn)
    old = registry.get_user(5)
    assert old is not None and old.mode == "token" and old.feed_sealed is None
    with pytest.raises(sqlite3.IntegrityError):
        registry.update_user(5, mode="calendar")
