"""Rate limits, abandoned sign-ups, buttons after re-joining, and the pre-sync host check."""

from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker.bot.commands import sync_cmd
from canvas_tracker.hub.handlers import item_button, on_text, routed
from canvas_tracker.hub.hub import SIGNUP_ABANDONED_AFTER, HostGuard, Verification
from canvas_tracker.hub.ratelimit import RateLimiter
from canvas_tracker.hub.registry import open_registry
from canvas_tracker.hub.tenant import user_db_path
from canvas_tracker.render import copy
from canvas_tracker.render.message import item_callback
from canvas_tracker.runtime.sync import SyncOutcome
from canvas_tracker.store.repo import LAST_SYNC_ERROR
from tests.factories import NOW
from tests.hub_helpers import BAD_TOKEN, GOOD_TOKEN, HubEnv, build_hub, sign_up
from tests.integration.sim_env import ScenarioItem
from tests.tg_helpers import callback_update, context, message_update, mock_bot


def texts(replies: list) -> list[str]:  # type: ignore[type-arg]
    return [r.text for r in replies]


def sent_texts(bot) -> list[str]:  # type: ignore[no-untyped-def]
    return [c.kwargs["text"] for c in bot.send_message.await_args_list]


def planner(item_id: int, title: str) -> list[dict]:  # type: ignore[type-arg]
    data = ScenarioItem(item_id, title, lambda _t: NOW + timedelta(hours=5)).planner_json(NOW)
    assert data is not None
    return [data]


async def at_token_step(env: HubEnv, telegram_id: int) -> None:
    arg = None if telegram_id == env.hub.owner_id() else env.hub.registry.create_invite(NOW)
    await env.signup.start(telegram_id, "Friend", arg)
    user = env.hub.registry.get_user(telegram_id)
    assert user is not None
    await env.signup.text(user, "school.instructure.com")


# --- rate limiter --------------------------------------------------------------


def test_rate_limiter_is_a_sliding_window_per_user() -> None:
    limiter = RateLimiter(2, timedelta(minutes=10))
    assert limiter.hit(1, NOW) is None
    assert limiter.hit(1, NOW + timedelta(minutes=1)) is None
    assert limiter.hit(1, NOW + timedelta(minutes=2)) == timedelta(minutes=8)
    assert limiter.wait(1, NOW + timedelta(minutes=2)) == timedelta(minutes=8)
    assert limiter.hit(2, NOW + timedelta(minutes=2)) is None  # someone else isn't affected
    assert limiter.hit(1, NOW + timedelta(minutes=10)) is None  # the first hit has aged out
    assert limiter.hit(1, NOW + timedelta(minutes=10)) == timedelta(minutes=1)


def test_rate_limiter_forgets_users_whose_window_passed() -> None:
    limiter = RateLimiter(1, timedelta(minutes=1))
    for user in range(50):
        limiter.hit(user, NOW)
    assert len(limiter) == 50
    for user in range(50):
        assert limiter.wait(user, NOW + timedelta(minutes=2)) is None
    assert len(limiter) == 0
    with pytest.raises(ValueError):
        RateLimiter(0, timedelta(minutes=1))


async def test_token_checks_are_rate_limited(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await at_token_step(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    assert texts(await env.signup.text(user, "not a token")) == [copy.TOKEN_FORMAT]  # free
    for _ in range(5):
        assert texts(await env.signup.text(user, BAD_TOKEN)) == [copy.TOKEN_PROBLEMS["rejected"]]
    calls = len(env.canvas.calls)
    env.clock.now = NOW + timedelta(minutes=1)
    [reply] = await env.signup.text(user, GOOD_TOKEN)
    assert reply.text == copy.TOKEN_TOO_MANY.format(minutes=14)
    assert len(env.canvas.calls) == calls  # the token wasn't sent to Canvas

    # the handler doesn't claim to be checking a token it won't check
    bot = mock_bot()
    await on_text(env.signup)(message_update(GOOD_TOKEN, user_id=1, bot=bot), context())
    assert copy.TOKEN_CHECKING not in sent_texts(bot)
    assert sent_texts(bot)[-1] == copy.TOKEN_TOO_MANY.format(minutes=14)

    env.clock.now = NOW + timedelta(minutes=15)
    assert texts(await env.signup.text(user, GOOD_TOKEN)) == [copy.TOKEN_SAVED, copy.ASK_TZ]


async def test_token_edits_share_the_limit(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)  # one check used
    user = env.hub.registry.get_user(1)
    assert user is not None
    env.signup.begin_edit(user, "tok")
    for _ in range(4):
        user = env.hub.registry.get_user(1)
        assert user is not None
        await env.signup.text(user, BAD_TOKEN)
    user = env.hub.registry.get_user(1)
    assert user is not None and env.signup.token_wait(user) is not None
    [reply] = await env.signup.text(user, GOOD_TOKEN)
    assert reply.text == copy.TOKEN_TOO_MANY.format(minutes=15)


async def test_manual_sync_is_limited_to_once_a_minute(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    handler = routed(env.signup, sync_cmd)
    bot = mock_bot()
    await handler(message_update("/sync", user_id=1, bot=bot), context())
    calls = len(env.canvas.calls)
    env.clock.now = NOW + timedelta(seconds=20)
    await handler(message_update("/sync", user_id=1, bot=bot), context())
    assert sent_texts(bot)[-1] == copy.SYNC_TOO_SOON.format(seconds=40)
    assert len(env.canvas.calls) == calls

    other = mock_bot()  # another user's /sync isn't held up
    await handler(message_update("/sync", user_id=5, bot=other), context())
    assert sent_texts(other)[-1] != copy.SYNC_TOO_SOON.format(seconds=40)

    env.clock.now = NOW + timedelta(seconds=60)
    await handler(message_update("/sync", user_id=1, bot=bot), context())
    assert not sent_texts(bot)[-1].startswith("⏳")
    assert len(env.canvas.calls) > calls


# --- abandoned sign-ups ----------------------------------------------------------


async def test_stalled_signups_are_removed_and_free_their_slot(tmp_path: Path) -> None:
    env = build_hub(tmp_path, max_users=3)
    await sign_up(env, 1)  # the owner, active
    await at_token_step(env, 5)  # stalls at the token step
    await at_token_step(env, 6)  # keeps going a few days later
    full = env.hub.registry.create_invite(NOW)
    assert texts(await env.signup.start(9, "Late", full)) == [copy.BOT_FULL]

    env.clock.now = NOW + timedelta(days=5)
    six = env.hub.registry.get_user(6)
    assert six is not None
    await env.signup.text(six, "nope")  # any answer counts as activity

    env.clock.now = NOW + SIGNUP_ABANDONED_AFTER - timedelta(minutes=1)
    await env.hub.tick_all()
    assert env.hub.registry.get_user(5) is not None  # not 7 days yet

    env.clock.now = NOW + SIGNUP_ABANDONED_AFTER + timedelta(minutes=1)
    await env.hub.tick_all()
    assert env.hub.registry.get_user(5) is None
    assert [m.text for m in env.notifiers[5].sent] == [copy.SIGNUP_EXPIRED]
    assert env.hub.registry.get_user(6) is not None  # was active 2 days ago
    assert env.hub.registry.get_user(1) is not None  # active users stay

    late = env.hub.registry.create_invite(env.clock.now)
    assert texts(await env.signup.start(9, "Late", late)) == [copy.SIGNUP_INTRO, copy.ASK_URL]


async def test_the_owner_and_active_users_are_never_pruned(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Owner", None)  # the owner, half signed up
    await sign_up(env, 5)
    env.clock.now = NOW + timedelta(days=60)
    assert await env.hub.prune_signups() == []
    assert env.hub.registry.get_user(1) is not None
    assert env.hub.registry.get_user(5) is not None


async def test_the_bot_full_check_prunes_first(tmp_path: Path) -> None:
    env = build_hub(tmp_path, max_users=2)
    await sign_up(env, 1)
    await at_token_step(env, 5)
    env.clock.now = NOW + timedelta(days=8)
    code = env.hub.registry.create_invite(env.clock.now)
    assert texts(await env.signup.start(9, "New", code)) == [copy.SIGNUP_INTRO, copy.ASK_URL]
    assert env.hub.registry.get_user(5) is None


def test_existing_onboarding_rows_get_a_fresh_week_from_the_migration(tmp_path: Path) -> None:
    from canvas_tracker.store.db import connect

    path = tmp_path / "registry.db"
    conn = connect(path)
    from importlib.resources import files

    for name in ("0001_registry.sql", "0002_pending_url.sql", "0003_email.sql"):
        sql = files("canvas_tracker.hub.migrations").joinpath(name).read_text("utf-8")
        conn.executescript(f"BEGIN;\n{sql}\nCOMMIT;")
    conn.execute("PRAGMA user_version = 3")
    conn.execute(
        "INSERT INTO users (telegram_id, status, created_at) "
        "VALUES (5, 'onboarding', '2020-01-01T00:00:00.000000Z'), "
        "(6, 'active', '2020-01-01T00:00:00.000000Z')"
    )
    conn.close()
    reg = open_registry(path)
    five, six = reg.get_user(5), reg.get_user(6)
    assert five is not None and five.last_seen_at is not None
    assert five.last_seen_at > five.created_at
    assert six is not None and six.last_seen_at is None
    assert reg.stale_signups(five.last_seen_at - timedelta(seconds=1)) == []
    assert reg.stale_signups(five.last_seen_at + timedelta(seconds=1)) == [5]


# --- buttons after /disconnect and re-joining --------------------------------------


async def test_old_buttons_cant_act_on_a_rejoined_users_new_items(tmp_path: Path) -> None:
    """Regression: re-joining starts a new database whose item ids restart at 1, so an
    old "✅ Done" button used to mark the new item done."""
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    env.canvas.items = {GOOD_TOKEN: planner(11, "Old essay")}
    await sign_up(env, 5)
    first = env.hub.tenant(5)
    assert first is not None
    await first.tick()
    [old_item] = first.store.snapshot().items
    assert old_item.db_id is not None
    old_salt = first.store.button_salt()
    old_button = item_callback("d", old_item.db_id, old_salt)

    user = env.hub.registry.get_user(5)
    assert user is not None
    await env.signup.disconnect(user, confirmed=True)
    env.canvas.items = {GOOD_TOKEN: planner(22, "New lab")}
    await sign_up(env, 5)
    second = env.hub.tenant(5)
    assert second is not None
    await second.tick()
    [new_item] = second.store.snapshot().items
    assert new_item.db_id == old_item.db_id  # the ids really do collide
    assert second.store.button_salt() != old_salt

    for data in (old_button, f"d:{old_item.db_id}"):
        bot = mock_bot()
        await item_button(env.signup)(callback_update(data, user_id=5, bot=bot), context())
        assert bot.answer_callback_query.await_args.kwargs.get("text") == copy.BUTTON_STALE
    after = second.store.get_item(new_item.db_id)
    assert after is not None and after.bot_done_at is None

    # the new database's own buttons work, and every one it sends carries its salt
    sent = [b.callback_data for m in env.notifiers[5].sent for r in m.keyboard for b in r]
    salt = second.store.button_salt()
    assert any(d is not None and d.endswith(f":{salt}") for d in sent)
    bot = mock_bot()
    fresh = item_callback("d", new_item.db_id, salt)
    await item_button(env.signup)(callback_update(fresh, user_id=5, bot=bot), context())
    assert bot.answer_callback_query.await_args.kwargs.get("text") == copy.DONE
    assert user_db_path(tmp_path, 5).exists()


# --- the Canvas host is re-checked before each sync -----------------------------------


async def test_host_guard_caches_passes_but_not_failures() -> None:
    answers = [True, False, True]
    asked: list[str] = []

    async def check(host: str) -> bool:
        asked.append(host)
        return answers.pop(0)

    now = [NOW]
    guard = HostGuard(check, lambda: now[0], ttl=timedelta(minutes=5))
    assert await guard("a.example")
    now[0] = NOW + timedelta(minutes=4)
    assert await guard("a.example")  # cached
    assert asked == ["a.example"]
    now[0] = NOW + timedelta(minutes=5)
    assert not await guard("a.example")  # re-checked: now private
    assert await guard("a.example")  # a failure isn't cached
    assert asked == ["a.example"] * 3
    assert not await guard("")  # no host never passes


async def test_sync_refuses_a_host_that_now_resolves_privately(tmp_path: Path) -> None:
    public = {"school.instructure.com": True}
    env = build_hub(tmp_path, public=lambda host: public.get(host, False))
    env.canvas.items = {GOOD_TOKEN: planner(11, "Essay")}
    await sign_up(env, 1)
    tenant = env.hub.tenant(1)
    assert tenant is not None
    assert await tenant.sync.sync(env.clock()) is SyncOutcome.OK

    public["school.instructure.com"] = False  # DNS rebinding: now points inside
    env.clock.now = NOW + timedelta(minutes=10)  # past the cached pass
    calls = len(env.canvas.calls)
    assert await tenant.sync.sync(env.clock()) is SyncOutcome.UNAVAILABLE
    assert await tenant.sync.enrich(env.clock()) is SyncOutcome.UNAVAILABLE
    assert len(env.canvas.calls) == calls  # nothing was sent to it
    assert tenant.store.get_state(LAST_SYNC_ERROR) == "CanvasHostRefused"
    assert await env.hub.verify("https://school.instructure.com", GOOD_TOKEN) == Verification(
        "unreachable"
    )

    public["school.instructure.com"] = True
    assert await tenant.sync.sync(env.clock()) is not SyncOutcome.UNAVAILABLE
