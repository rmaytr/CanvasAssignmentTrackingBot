"""Telegram delivery: HTML parse mode, no link previews, owner chat only."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

from canvas_tracker.notify.base import NotifyError, NotPairedError
from canvas_tracker.render.message import Button, RenderedMessage


def _button(b: Button) -> InlineKeyboardButton:
    if b.url is not None:
        return InlineKeyboardButton(b.label, url=b.url)
    return InlineKeyboardButton(b.label, callback_data=b.callback_data)


def to_markup(keyboard: tuple[tuple[Button, ...], ...]) -> InlineKeyboardMarkup | None:
    rows = [[_button(b) for b in row] for row in keyboard if row]
    return InlineKeyboardMarkup(rows) if rows else None


def _seconds(value: int | float | timedelta) -> float:
    return value.total_seconds() if isinstance(value, timedelta) else float(value)


class TelegramNotifier:
    def __init__(
        self,
        bot: Bot,
        chat_id: Callable[[], int | None],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._sleep = sleep

    async def _send_once(self, chat_id: int, msg: RenderedMessage) -> int | None:
        sent = await self._bot.send_message(
            chat_id=chat_id,
            text=msg.text,
            parse_mode=ParseMode.HTML,
            reply_markup=to_markup(msg.keyboard),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        message_id = getattr(sent, "message_id", None)
        return message_id if isinstance(message_id, int) else None

    async def send(self, msg: RenderedMessage) -> int | None:
        chat_id = self._chat_id()
        if chat_id is None:
            raise NotPairedError("NotPaired")
        try:
            try:
                return await self._send_once(chat_id, msg)
            except RetryAfter as exc:
                await self._sleep(_seconds(exc.retry_after))
                return await self._send_once(chat_id, msg)
        except TelegramError as exc:
            raise NotifyError(type(exc).__name__) from None
