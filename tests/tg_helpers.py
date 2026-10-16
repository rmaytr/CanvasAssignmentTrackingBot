"""Build real python-telegram-bot Update objects around a mock Bot."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from telegram import Bot, Update

from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.bot.pairing import PairingCode
from canvas_tracker.domain.models import Settings
from tests.factories import NOW, make_settings
from tests.store_helpers import new_store


def mock_bot() -> AsyncMock:
    bot = AsyncMock(spec=Bot)
    bot.defaults = None
    return bot


def message_update(
    text: str, user_id: int = 77, chat_type: str = "private", bot: AsyncMock | None = None
) -> Update:
    entities = (
        [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        if text.startswith("/")
        else []
    )
    data: dict[str, Any] = {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "date": 1760000000,
            "chat": {"id": user_id if chat_type == "private" else -100, "type": chat_type},
            "from": {"id": user_id, "is_bot": False, "first_name": "A"},
            "text": text,
            "entities": entities,
        },
    }
    update = Update.de_json(data, bot or mock_bot())
    assert update is not None
    return update


def callback_update(data: str, user_id: int = 77, bot: AsyncMock | None = None) -> Update:
    payload: dict[str, Any] = {
        "update_id": 2,
        "callback_query": {
            "id": "cq1",
            "from": {"id": user_id, "is_bot": False, "first_name": "A"},
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": 9,
                "date": 1760000000,
                "chat": {"id": user_id, "type": "private"},
                "text": "reminder",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "✅ Done 1", "callback_data": "d:1"},
                            {"text": "💤 2h 1", "callback_data": "s:1"},
                        ],
                        [{"text": "✅ Done 2", "callback_data": "d:2"}],
                    ]
                },
            },
        },
    }
    update = Update.de_json(payload, bot or mock_bot())
    assert update is not None
    return update


def context(*args: str) -> Any:
    return SimpleNamespace(args=list(args), bot_data={})


def make_deps(
    owner: int | None = None, settings: Settings | None = None, now: Any = NOW
) -> BotDeps:
    store = new_store()
    clock = now if callable(now) else (lambda: now)
    return BotDeps(
        store=store,
        settings=settings or make_settings(canvas_host="canvas.example.edu"),
        clock=clock,
        sync=AsyncMock(),
        pairing=PairingCode(now=clock, on_new_code=lambda _code: None),
        env_owner_id=owner,
        hidden_courses=frozenset(),
    )
