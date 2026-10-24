"""Friends mode end to end: a token pasted in the chat never reaches logs, messages or disk."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker.hub.handlers import on_text
from canvas_tracker.runtime.logging import configure_logging
from tests.hub_helpers import build_hub
from tests.tg_helpers import context, message_update, mock_bot

SENTINEL = "9999~SENTINELsentinelSENTINELsentinel99"
BOT_TOKEN = "424242424:SENTINEL_sentinel_SENTINEL_sentinel_00"


async def test_pasted_token_never_leaks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = build_hub(tmp_path)
    configure_logging("DEBUG", [BOT_TOKEN, env.key])
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    try:
        bots = []
        await env.signup.start(1, "Me", None)
        for text in ("school.instructure.com", SENTINEL, "Chicago", "8am", "off"):
            bot = mock_bot()
            bots.append(bot)
            await on_text(env.signup)(message_update(text, user_id=1, bot=bot), context())
        tenant = env.hub.tenant(1)
        assert tenant is not None
        for n in range(6):
            if n == 3:
                env.canvas.echo_401 = True  # Canvas starts rejecting and echoing the token
            await env.hub.tick_all()
            env.clock.now += timedelta(minutes=11)
        logging.getLogger("canvas_tracker").error("crash with %s", SENTINEL)
        await env.hub.close()
    finally:
        logging.getLogger().handlers = []
        logging.getLogger("httpx").setLevel(logging.WARNING)

    out = capsys.readouterr().out
    assert "crash with" in out  # the logs really were captured
    assert SENTINEL not in out and env.key not in out
    for bot in bots:
        for call in bot.send_message.await_args_list:
            assert SENTINEL not in call.kwargs["text"]
    assert all(SENTINEL not in m.text for n in env.notifiers.values() for m in n.sent)
    assert any("🔑" in m.text for m in env.notifiers[1].sent), "the auth alert was sent"
    for path in tmp_path.rglob("*.db*"):
        data = path.read_bytes()
        assert SENTINEL.encode() not in data, path
        assert env.key.encode() not in data, path
