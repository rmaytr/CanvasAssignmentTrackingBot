from datetime import timedelta
from pathlib import Path

import pytest
from telegram.ext import ApplicationHandlerStop

from canvas_tracker.bot.commands import today_cmd
from canvas_tracker.hub.handlers import (
    build_gate,
    help_cmd,
    item_button,
    on_text,
    routed,
    setup_button,
    start,
)
from canvas_tracker.hub.registry import HUB_LAST_TICK_AT
from canvas_tracker.render import copy
from tests.factories import NOW
from tests.hub_helpers import GOOD_TOKEN, OTHER_TOKEN, build_hub, sign_up
from tests.integration.sim_env import ScenarioItem
from tests.tg_helpers import callback_update, context, message_update, mock_bot


def sent_texts(bot) -> list[str]:  # type: ignore[no-untyped-def]
    return [c.kwargs["text"] for c in bot.send_message.await_args_list]


async def passes_gate(env, update) -> bool:  # type: ignore[no-untyped-def]
    try:
        await build_gate(env.signup).callback(update, context())
    except ApplicationHandlerStop:
        return False
    return True


async def test_gate_drops_strangers_but_lets_start_through(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    assert not await passes_gate(env, message_update("/today", user_id=999))
    assert not await passes_gate(env, message_update("hello", user_id=999))
    assert not await passes_gate(env, callback_update("d:1", user_id=999))
    assert await passes_gate(env, message_update("/start abc", user_id=999))
    assert not await passes_gate(env, message_update("/start", user_id=999, chat_type="group"))
    await sign_up(env, 1)
    assert await passes_gate(env, message_update("/today", user_id=1))


async def test_start_without_invite_is_politely_refused(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    bot = mock_bot()
    await start(env.signup)(message_update("/start", user_id=999, bot=bot), context())
    assert sent_texts(bot) == [copy.INVITE_ONLY]


async def test_token_message_is_deleted(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.text(user, "school.instructure.com")
    bot = mock_bot()
    await on_text(env.signup)(message_update(GOOD_TOKEN, user_id=1, bot=bot), context())
    bot.delete_message.assert_awaited_once()
    assert sent_texts(bot) == [copy.TOKEN_CHECKING, copy.TOKEN_SAVED, copy.ASK_TZ]
    assert all(GOOD_TOKEN not in t for t in sent_texts(bot))


async def test_commands_wait_until_signup_is_finished(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    bot = mock_bot()
    await routed(env.signup, today_cmd)(message_update("/today", user_id=1, bot=bot), context())
    assert sent_texts(bot) == [copy.FINISH_SIGNUP_FIRST, copy.ASK_URL]


def planner(item_id: int, title: str) -> list[dict]:  # type: ignore[type-arg]
    item = ScenarioItem(item_id, title, lambda _t: NOW + timedelta(hours=5))
    data = item.planner_json(NOW)
    assert data is not None
    return [data]


async def test_friends_only_see_and_touch_their_own_items(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    env.canvas.items = {GOOD_TOKEN: planner(11, "Ana's essay"), OTHER_TOKEN: planner(22, "Ben lab")}
    await sign_up(env, 1, token=GOOD_TOKEN)
    await sign_up(env, 5, token=OTHER_TOKEN)
    await env.hub.tick_all()

    ana, ben = env.hub.tenant(1), env.hub.tenant(5)
    assert ana is not None and ben is not None
    [ana_item] = ana.store.snapshot().items
    [ben_item] = ben.store.snapshot().items
    assert ana_item.title == "Ana's essay" and ben_item.title == "Ben lab"
    assert all("Ben lab" not in m.text for m in env.notifiers[1].sent)
    assert all("Ana's essay" not in m.text for m in env.notifiers[5].sent)

    bot = mock_bot()
    await routed(env.signup, today_cmd)(message_update("/today", user_id=5, bot=bot), context())
    assert "Ben lab" in sent_texts(bot)[0] and "Ana" not in sent_texts(bot)[0]

    # Ben pressing "Done" with an id that only exists in Ana's file can't reach Ana's item
    assert ana_item.db_id is not None
    bogus = ana_item.db_id + 1000 if ana_item.db_id == ben_item.db_id else ana_item.db_id
    bot = mock_bot()
    await item_button(env.signup)(callback_update(f"d:{bogus}", user_id=5, bot=bot), context())
    assert bot.answer_callback_query.await_args.kwargs.get("text") == copy.ITEM_GONE
    after = ana.store.get_item(ana_item.db_id)
    assert after is not None and after.bot_done_at is None

    bot = mock_bot()
    data = f"d:{ben_item.db_id}"
    await item_button(env.signup)(callback_update(data, user_id=5, bot=bot), context())
    done = ben.store.get_item(ben_item.db_id or 0)
    assert done is not None and done.bot_done_at is not None
    untouched = ana.store.get_item(ana_item.db_id)
    assert untouched is not None and untouched.bot_done_at is None


async def test_setup_buttons(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    bot = mock_bot()
    await setup_button(env.signup)(callback_update("set:qh", user_id=1, bot=bot), context())
    bot.answer_callback_query.assert_awaited_once()
    assert sent_texts(bot) == [copy.ASK_QUIET_EDIT]
    bot = mock_bot()
    await setup_button(env.signup)(callback_update("su:qh:off", user_id=1, bot=bot), context())
    assert sent_texts(bot)[0] == copy.SAVED
    user = env.hub.registry.get_user(1)
    assert user is not None and user.quiet == "off"

    bot = mock_bot()
    await setup_button(env.signup)(callback_update("bye:yes", user_id=1, bot=bot), context())
    assert sent_texts(bot) == [copy.DISCONNECTED]
    assert env.hub.registry.get_user(1) is None


async def test_owner_help_lists_owner_commands(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    bot = mock_bot()
    await help_cmd(env.signup)(message_update("/help", user_id=1, bot=bot), context())
    assert "/invite" in sent_texts(bot)[0]
    bot = mock_bot()
    await help_cmd(env.signup)(message_update("/help", user_id=5, bot=bot), context())
    assert "/invite" not in sent_texts(bot)[0]


async def test_one_failing_friend_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_hub(tmp_path)
    env.canvas.items = {GOOD_TOKEN: planner(11, "Essay")}
    await sign_up(env, 1, token=GOOD_TOKEN)
    await sign_up(env, 5, token=OTHER_TOKEN)
    broken = env.hub.tenant(5)
    assert broken is not None

    async def explode() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(broken.runtime, "tick", explode)
    await env.hub.tick_all()
    ok = env.hub.tenant(1)
    assert ok is not None and len(ok.store.snapshot().items) == 1
    assert env.hub.registry.get_time(HUB_LAST_TICK_AT) == NOW


async def test_restart_loads_active_users(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await env.signup.start(5, "Half", env.hub.registry.create_invite(NOW))  # still signing up
    await env.hub.close()
    again = build_hub(tmp_path)
    again.hub.box = env.hub.box
    again.hub.load()
    assert set(again.hub.tenants) == {1}
