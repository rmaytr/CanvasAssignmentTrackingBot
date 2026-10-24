"""The real python-telegram-bot Application with our handlers, against a fake Telegram API.

Proves the wiring (gate group, command names, button patterns, the text filter) by
pushing raw updates through ``Application.process_update``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest, RequestData

from canvas_tracker.hub.handlers import register_handlers
from canvas_tracker.render import copy
from tests.hub_helpers import GOOD_TOKEN, build_hub


class FakeTelegram(BaseRequest):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    @property
    def read_timeout(self) -> float:
        return 1.0

    async def do_request(  # type: ignore[override]  # the timeouts don't matter here
        self, url: str, method: str, request_data: RequestData | None = None, **_: Any
    ) -> tuple[int, bytes]:
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data is not None else {}
        self.calls.append((endpoint, params))
        result: Any = True
        if endpoint == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Bot", "username": "TestCanvasBot"}
        elif endpoint == "sendMessage":
            result = {
                "message_id": len(self.calls),
                "date": 0,
                "chat": {"id": params["chat_id"], "type": "private"},
                "text": params.get("text", ""),
            }
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def texts(self, chat_id: int) -> list[str]:
        return [
            str(p["text"])
            for e, p in self.calls
            if e == "sendMessage" and int(p["chat_id"]) == chat_id
        ]


_ids = iter(range(1, 10_000))


def text_update(app: Application[Any, Any, Any, Any, Any, Any], user: int, text: str) -> Update:
    entities = (
        [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        if text.startswith("/")
        else []
    )
    data = {
        "update_id": next(_ids),
        "message": {
            "message_id": next(_ids),
            "date": 0,
            "chat": {"id": user, "type": "private"},
            "from": {"id": user, "is_bot": False, "first_name": f"User{user}"},
            "text": text,
            "entities": entities,
        },
    }
    update = Update.de_json(data, app.bot)
    assert update is not None
    return update


def button_update(app: Application[Any, Any, Any, Any, Any, Any], user: int, data: str) -> Update:
    payload = {
        "update_id": next(_ids),
        "callback_query": {
            "id": str(next(_ids)),
            "from": {"id": user, "is_bot": False, "first_name": f"User{user}"},
            "chat_instance": "c",
            "data": data,
            "message": {
                "message_id": next(_ids),
                "date": 0,
                "chat": {"id": user, "type": "private"},
                "text": "options",
            },
        },
    }
    update = Update.de_json(payload, app.bot)
    assert update is not None
    return update


async def test_full_flow_through_the_real_application(tmp_path: Path) -> None:
    env = build_hub(tmp_path, owner=1)
    fake = FakeTelegram()
    app = Application.builder().token("1:fake").request(fake).get_updates_request(fake).build()
    register_handlers(app, env.signup)
    await app.initialize()
    try:

        async def send(user: int, text: str) -> None:
            await app.process_update(text_update(app, user, text))

        async def tap(user: int, data: str) -> None:
            await app.process_update(button_update(app, user, data))

        # a stranger is ignored, except for a polite /start answer
        await send(99, "hello")
        await send(99, "/today")
        await send(99, "/start")
        assert fake.texts(99) == [copy.INVITE_ONLY]

        # the owner signs up entirely through chat messages and buttons
        await send(1, "/start")
        await send(1, "school.instructure.com")
        await send(1, GOOD_TOKEN)
        assert any(e == "deleteMessage" for e, _ in fake.calls), "token message deleted"
        await tap(1, "su:tz:America/Chicago")
        await tap(1, "su:dt:08:00")
        await tap(1, "su:qh:00:00-07:00")
        assert fake.texts(1)[-1].startswith("✅ All set!")
        assert all(GOOD_TOKEN not in t for t in fake.texts(1))

        # owner invites a friend, who signs up with the link's code
        await send(1, "/invite")
        link = fake.texts(1)[-1].split("\n")[-1]
        assert link.startswith("https://t.me/TestCanvasBot?start=")
        code = link.split("start=")[1]
        await send(5, f"/start {code}")
        assert fake.texts(5)[:2] == [copy.SIGNUP_INTRO, copy.ASK_URL]
        await send(5, "/today")
        assert fake.texts(5)[-2] == copy.FINISH_SIGNUP_FIRST

        # per-user commands reach the user's own data (after the first Canvas check)
        await env.hub.tick_all()
        await send(1, "/today")
        assert "Nothing due today" in fake.texts(1)[-1]
        await send(1, "/settings")
        assert fake.texts(1)[-1].startswith("⚙️ Your settings")
        await send(1, "/users")
        assert fake.texts(1)[-1].startswith("👥 Users (2 of 25)")
        await send(5, "/users")
        assert fake.texts(5)[-1] == copy.OWNER_ONLY

        # leaving
        await send(5, "/disconnect")
        await tap(5, "bye:yes")
        assert fake.texts(5)[-1] == copy.DISCONNECTED
        assert env.hub.registry.get_user(5) is None
        await send(5, "/today")  # a stranger again: ignored
        assert fake.texts(5)[-1] == copy.DISCONNECTED
    finally:
        await app.shutdown()
        await env.hub.close()
