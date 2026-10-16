"""Owner-only gate, pairing via /start, and /help (PRD §7.6).

The gate runs before every other handler (group -1). Updates from anyone but
the owner, or from any non-private chat, are dropped without a reply.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import time, timedelta
from typing import Any

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ApplicationHandlerStop, TypeHandler

from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.bot.pairing import PairingResult
from canvas_tracker.render import copy
from canvas_tracker.store.repo import OWNER_ID

Handler = Callable[[Update, Any], Coroutine[Any, Any, None]]
_PAIRING_REPLIES = {
    PairingResult.WRONG: copy.PAIR_WRONG,
    PairingResult.EXPIRED: copy.PAIR_EXPIRED,
    PairingResult.LOCKED: copy.PAIR_LOCKED,
}


def owner_id(deps: BotDeps) -> int | None:
    if deps.env_owner_id is not None:
        return deps.env_owner_id
    stored = deps.store.get_state(OWNER_ID)
    return int(stored) if stored is not None and stored.lstrip("-").isdigit() else None


def _is_start(update: Update) -> bool:
    message = update.message
    if message is None or not message.text:
        return False
    command = message.text.split(maxsplit=1)[0]
    return command == "/start" or command.startswith("/start@")


def build_gate(deps: BotDeps) -> TypeHandler[Update, Any, None]:
    async def gate(update: Update, _context: Any) -> None:
        user, chat = update.effective_user, update.effective_chat
        if user is None or chat is None or chat.type != ChatType.PRIVATE:
            raise ApplicationHandlerStop
        owner = owner_id(deps)
        if owner is not None:
            if user.id != owner:
                raise ApplicationHandlerStop
            return
        if not _is_start(update):
            raise ApplicationHandlerStop

    return TypeHandler(Update, gate)


def _clock(t: time) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _interval(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes} min"


def start(deps: BotDeps) -> Handler:
    async def handler(update: Update, context: Any) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        if owner_id(deps) is None:
            if not context.args:
                await message.reply_text(copy.SEND_CODE)
                return
            result = deps.pairing.check(str(context.args[0]))
            if result is PairingResult.OK:
                deps.store.set_state(OWNER_ID, str(user.id))
                await message.reply_text(copy.PAIRED)
            else:
                await message.reply_text(_PAIRING_REPLIES[result])
            return
        s = deps.settings
        quiet = (
            f"{_clock(s.quiet_start)} to {_clock(s.quiet_end)}"
            if s.quiet_start is not None and s.quiet_end is not None
            else copy.QUIET_OFF
        )
        await message.reply_text(
            copy.WELCOME.format(
                digest=_clock(s.digest_time),
                tz=s.tz,
                window=int(s.reminder_window.total_seconds() // 3600),
                interval=_interval(s.reminder_interval),
                quiet=quiet,
            )
        )

    return handler


def help_cmd(_deps: BotDeps) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(copy.HELP)

    return handler
