from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter

from canvas_tracker.notify.base import FakeNotifier, NotifyError, NotPairedError
from canvas_tracker.notify.telegram import TelegramNotifier, to_markup
from canvas_tracker.render.message import Button, RenderedMessage

MSG = RenderedMessage(
    "<b>hi</b>",
    (
        (
            Button("✅ Done 1", callback_data="d:1"),
            Button("🔗 1", url="https://canvas.example.edu/x"),
        ),
    ),
)


def bot_mock() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=42)
    return bot


async def test_send_uses_html_and_disables_previews() -> None:
    bot = bot_mock()
    assert await TelegramNotifier(bot, lambda: 7).send(MSG) == 42
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 7 and kwargs["text"] == "<b>hi</b>"
    assert kwargs["parse_mode"] is ParseMode.HTML
    assert kwargs["link_preview_options"].is_disabled is True
    [[done, link]] = kwargs["reply_markup"].inline_keyboard
    assert (done.text, done.callback_data, link.url) == (
        "✅ Done 1",
        "d:1",
        "https://canvas.example.edu/x",
    )


def test_empty_keyboard_has_no_markup() -> None:
    assert to_markup(()) is None


async def test_retry_after_waits_then_retries_once() -> None:
    bot = bot_mock()
    bot.send_message.side_effect = [RetryAfter(3), SimpleNamespace(message_id=5)]
    sleep = AsyncMock()
    assert await TelegramNotifier(bot, lambda: 7, sleep=sleep).send(MSG) == 5
    sleep.assert_awaited_once_with(3.0)


async def test_other_telegram_errors_become_notify_errors() -> None:
    bot = bot_mock()
    bot.send_message.side_effect = NetworkError("boom 123456789:SECRET")
    with pytest.raises(NotifyError) as info:
        await TelegramNotifier(bot, lambda: 7).send(MSG)
    assert str(info.value) == "NetworkError"


async def test_unpaired_bot_refuses_to_send() -> None:
    with pytest.raises(NotPairedError):
        await TelegramNotifier(bot_mock(), lambda: None).send(MSG)


async def test_fake_notifier_records_and_can_fail() -> None:
    fake = FakeNotifier(fail_times=1)
    with pytest.raises(NotifyError):
        await fake.send(MSG)
    assert await fake.send(MSG) == 1
    assert await fake.send(MSG) == 2
    assert fake.sent == [MSG, MSG]
