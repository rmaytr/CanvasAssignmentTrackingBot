import pytest
from telegram.ext import ApplicationHandlerStop

from canvas_tracker.bot.gate import build_gate, help_cmd, owner_id, start
from canvas_tracker.render import copy
from canvas_tracker.store.repo import OWNER_ID
from tests.tg_helpers import context, make_deps, message_update, mock_bot


async def run_gate(deps, update) -> bool:  # type: ignore[no-untyped-def]
    """True if the update passes the gate."""
    gate = build_gate(deps)
    try:
        await gate.callback(update, context())
    except ApplicationHandlerStop:
        return False
    return True


async def test_stranger_is_dropped_silently() -> None:
    bot = mock_bot()
    assert not await run_gate(make_deps(owner=77), message_update("/today", user_id=999, bot=bot))
    bot.send_message.assert_not_awaited()


async def test_owner_in_group_chat_is_dropped() -> None:
    assert not await run_gate(make_deps(owner=77), message_update("/today", chat_type="group"))


async def test_owner_private_chat_passes() -> None:
    assert await run_gate(make_deps(owner=77), message_update("/today"))


async def test_unpaired_only_start_passes() -> None:
    deps = make_deps(owner=None)
    assert not await run_gate(deps, message_update("/today", user_id=999))
    assert not await run_gate(deps, message_update("hello", user_id=999))
    assert await run_gate(deps, message_update("/start ABCD2345", user_id=999))


async def test_stored_owner_is_used_when_env_unset() -> None:
    deps = make_deps(owner=None)
    deps.store.set_state(OWNER_ID, "55")
    assert owner_id(deps) == 55
    assert not await run_gate(deps, message_update("/start X", user_id=999))
    env = make_deps(owner=77)
    env.store.set_state(OWNER_ID, "55")
    assert owner_id(env) == 77


async def test_start_with_correct_code_pairs_owner() -> None:
    deps = make_deps(owner=None)
    bot = mock_bot()
    await start(deps)(
        message_update(f"/start {deps.pairing.code}", user_id=4242, bot=bot),
        context(deps.pairing.code),
    )
    assert deps.store.get_state(OWNER_ID) == "4242"
    assert bot.send_message.await_args.kwargs["text"] == copy.PAIRED


@pytest.mark.parametrize(
    ("args", "reply"), [((), copy.SEND_CODE), (("WRONG000",), copy.PAIR_WRONG)]
)
async def test_start_without_or_with_wrong_code(args: tuple[str, ...], reply: str) -> None:
    deps = make_deps(owner=None)
    bot = mock_bot()
    await start(deps)(message_update("/start", bot=bot), context(*args))
    assert deps.store.get_state(OWNER_ID) is None
    assert bot.send_message.await_args.kwargs["text"] == reply


async def test_start_when_paired_shows_welcome_and_settings() -> None:
    deps = make_deps(owner=77)
    bot = mock_bot()
    await start(deps)(message_update("/start", bot=bot), context())
    text = bot.send_message.await_args.kwargs["text"]
    assert text.startswith("👋") and "8:00 AM" in text and "every 2 h" in text


async def test_help_lists_commands() -> None:
    bot = mock_bot()
    await help_cmd(make_deps(owner=77))(message_update("/help", bot=bot), context())
    text = bot.send_message.await_args.kwargs["text"]
    for command in ("/today", "/week", "/digest", "/sync", "/status", "/pause"):
        assert command in text
