"""Regression tests for the friends-mode review findings."""

import asyncio
from datetime import time
from pathlib import Path

import pytest

from canvas_tracker.hub.handlers import on_text, setup_button
from canvas_tracker.hub.parsing import normalize_canvas_url, resolve_timezone
from canvas_tracker.hub.registry import HUB_LAST_TICK_AT
from canvas_tracker.hub.secretbox import SecretBox, generate_key
from canvas_tracker.render import copy
from tests.factories import NOW
from tests.hub_helpers import GOOD_TOKEN, build_hub, sign_up
from tests.tg_helpers import callback_update, context, message_update, mock_bot


def texts(replies: list) -> list[str]:  # type: ignore[type-arg]
    return [r.text for r in replies]


async def test_slow_friend_does_not_hold_up_the_others(  # review I1
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    slow, fast = env.hub.tenant(1), env.hub.tenant(5)
    assert slow is not None and fast is not None
    await env.hub.tick_all()  # let the first ticks that sign-up started finish
    release = asyncio.Event()
    fast_ticks = 0

    async def hang() -> None:
        await release.wait()

    async def count() -> None:
        nonlocal fast_ticks
        fast_ticks += 1

    monkeypatch.setattr(slow.runtime, "tick", hang)
    monkeypatch.setattr(fast.runtime, "tick", count)
    for _ in range(3):
        await asyncio.wait_for(env.hub.tick_all(wait_s=0.05), timeout=1)
    assert fast_ticks == 3  # the hung friend didn't block anyone
    assert env.hub.registry.get_time(HUB_LAST_TICK_AT) == NOW  # heartbeat still written
    release.set()
    await env.hub.close()


async def test_a_token_pasted_at_any_step_is_deleted(tmp_path: Path) -> None:  # review I3
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    bot = mock_bot()
    await on_text(env.signup)(message_update(GOOD_TOKEN, user_id=1, bot=bot), context())
    bot.delete_message.assert_awaited_once()
    assert copy.TOKEN_DELETED in [c.kwargs["text"] for c in bot.send_message.await_args_list]


async def test_failed_delete_is_not_claimed(tmp_path: Path) -> None:  # review I3
    from telegram.error import BadRequest

    env = build_hub(tmp_path)
    await sign_up(env, 1)
    bot = mock_bot()
    bot.delete_message.side_effect = BadRequest("can't")
    await on_text(env.signup)(message_update(GOOD_TOKEN, user_id=1, bot=bot), context())
    sent = [c.kwargs["text"] for c in bot.send_message.await_args_list]
    assert copy.TOKEN_DELETE_FAILED in sent and copy.TOKEN_DELETED not in sent


async def test_wrong_token_key_is_not_reported_as_a_rejected_token(  # review I4
    tmp_path: Path,
) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    await env.hub.close()
    again = build_hub(tmp_path)
    again.hub.box = SecretBox(generate_key())  # the key changed
    broken = again.hub.load()
    assert broken == [1, 5]
    assert again.hub.tenants == {}
    owner = again.hub.registry.get_user(5)
    assert owner is not None
    # the user is told what to do, and can fix it by pasting a token again
    assert texts(again.signup.settings(owner))[0].startswith("⚙️")
    again.signup.begin_edit(owner, "tok")
    owner = again.hub.registry.get_user(5)
    assert owner is not None
    assert texts(await again.signup.text(owner, GOOD_TOKEN)) == [copy.TOKEN_SAVED]
    assert again.hub.tenant(5) is not None


async def test_late_morning_times_are_refused(tmp_path: Path) -> None:  # review I5
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    env.signup.begin_edit(user, "dt")
    user = env.hub.registry.get_user(1)
    assert user is not None
    assert texts(await env.signup.text(user, "23:59")) == [copy.DIGEST_TOO_LATE]
    user = env.hub.registry.get_user(1)
    assert user is not None
    assert texts(await env.signup.text(user, "8 pm"))[0] == copy.SAVED


async def test_remove_asks_to_confirm_by_name_and_id(tmp_path: Path) -> None:  # review I6
    env = build_hub(tmp_path)
    await sign_up(env, 1, name="Owner")
    await sign_up(env, 5, name="Ana")
    await sign_up(env, 6, name="Ben")
    owner = env.hub.registry.get_user(1)
    assert owner is not None
    [ask] = await env.signup.remove(owner, "3")
    assert "Ben" in ask.text
    assert ask.keyboard[0][0].callback_data == "rm:6"
    # Ana leaves before the owner confirms: the button still means Ben
    await env.hub.remove(5)
    bot = mock_bot()
    await setup_button(env.signup)(callback_update("rm:6", user_id=1, bot=bot), context())
    assert env.hub.registry.get_user(6) is None
    # a friend can't use the button
    await sign_up(env, 7)
    bot = mock_bot()
    await setup_button(env.signup)(callback_update("rm:1", user_id=7, bot=bot), context())
    assert env.hub.registry.get_user(1) is not None


async def test_changing_the_canvas_address(tmp_path: Path) -> None:  # review I7
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    [reply] = env.signup.settings(user)
    assert "set:url" in [b.callback_data for row in reply.keyboard for b in row]
    env.signup.begin_edit(user, "url")
    user = env.hub.registry.get_user(1)
    assert user is not None
    [ask] = await env.signup.text(user, "canvas.newschool.edu")
    assert ask.text == copy.ASK_TOKEN_NEW_SITE
    user = env.hub.registry.get_user(1)
    assert user is not None and user.canvas_base_url == "https://school.instructure.com"
    assert texts(await env.signup.text(user, GOOD_TOKEN)) == [copy.TOKEN_SAVED]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.canvas_base_url == "https://canvas.newschool.edu"
    tenant = env.hub.tenant(1)
    assert tenant is not None and tenant.settings.canvas_host == "canvas.newschool.edu"


async def test_start_leaves_an_unfinished_edit(tmp_path: Path) -> None:  # review I7
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    env.signup.begin_edit(user, "tok")
    await env.signup.start(1, "Me", None)
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step is None


async def test_pairing_feedback_for_the_owner(tmp_path: Path) -> None:  # review minor 2
    from canvas_tracker.bot.pairing import PairingCode

    pairing = PairingCode(now=lambda: NOW, on_new_code=lambda _c: None)
    env = build_hub(tmp_path, owner=None, pairing=pairing)
    assert texts(await env.signup.start(3, "Me", "ABCD2345")) == [copy.PAIR_WRONG]
    for _ in range(10):  # strangers' random args don't use up the owner's code
        await env.signup.start(4, "X", "hello")
    assert texts(await env.signup.start(3, "Me", pairing.code))[0] == copy.PAIRED_OWNER


async def test_owner_rights_follow_the_configured_owner(tmp_path: Path) -> None:  # minor 3
    env = build_hub(tmp_path, owner=1)
    await sign_up(env, 1)
    await sign_up(env, 5)
    env.hub.owner_env_id = 5
    old_owner = env.hub.registry.get_user(1)
    assert old_owner is not None
    assert texts(env.signup.users(old_owner)) == [copy.OWNER_ONLY]


def test_default_port_dropped_and_other_ports_refused() -> None:  # minor 4
    assert normalize_canvas_url("https://school.instructure.com:443") == (
        "https://school.instructure.com"
    )
    assert normalize_canvas_url("school.instructure.com:8443") is None


def test_long_zone_names() -> None:  # minor 5
    assert resolve_timezone("Pacific Standard Time") == "America/Los_Angeles"
    assert resolve_timezone("Eastern Daylight Time") == "America/New_York"


async def test_closed_tenant_tick_is_a_no_op(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:  # minor 1
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    tenant = env.hub.tenant(1)
    assert tenant is not None
    await tenant.close()
    await tenant.tick()  # must not touch the closed database
    assert tenant.start_tick() is None
    assert "tick failed" not in caplog.text


def test_digest_time_limit_constant() -> None:
    from canvas_tracker.hub.signup import LATEST_DIGEST

    assert time(20, 0) == LATEST_DIGEST
