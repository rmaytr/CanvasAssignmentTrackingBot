"""Telegram handlers for friends mode: the gate, routing to each user's tenant, sign-up.

Every update is matched to a user by the Telegram ID that sent it, and per-user
commands and buttons only ever see that user's own tenant.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from canvas_tracker.bot.callbacks import on_callback
from canvas_tracker.bot.commands import (
    digest_cmd,
    pause_cmd,
    status_cmd,
    sync_cmd,
    today_cmd,
    week_cmd,
)
from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.hub.parsing import looks_like_token
from canvas_tracker.hub.registry import User
from canvas_tracker.hub.signup import TOKEN_STEPS, Reply, Signup
from canvas_tracker.notify.telegram import to_markup
from canvas_tracker.render import copy

Handler = Callable[[Update, Any], Coroutine[Any, Any, None]]
ITEM_CALLBACK = re.compile(r"^[dsux]:\d+$")
SETUP_CALLBACK = re.compile(r"^(su|set|bye):")


async def send_replies(update: Update, replies: list[Reply]) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    for reply in replies:
        await chat.send_message(
            reply.text,
            reply_markup=to_markup(reply.keyboard),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


def _is_start(update: Update) -> bool:
    message = update.message
    if message is None or not message.text:
        return False
    command = message.text.split(maxsplit=1)[0]
    return command == "/start" or command.startswith("/start@")


def build_gate(signup: Signup) -> TypeHandler[Update, Any, None]:
    """Private chats only. Known users pass; strangers may only send /start."""

    async def gate(update: Update, _context: Any) -> None:
        user, chat = update.effective_user, update.effective_chat
        if user is None or chat is None or chat.type != ChatType.PRIVATE or user.is_bot:
            raise ApplicationHandlerStop
        if signup.registry.get_user(user.id) is None and not _is_start(update):
            raise ApplicationHandlerStop

    return TypeHandler(Update, gate)


def _current(signup: Signup, update: Update) -> User | None:
    tg = update.effective_user
    return None if tg is None else signup.registry.get_user(tg.id)


def _arg(context: Any) -> str | None:
    args = getattr(context, "args", None) or []
    return str(args[0]) if args else None


def start(signup: Signup) -> Handler:
    async def handler(update: Update, context: Any) -> None:
        tg = update.effective_user
        if tg is None:
            return
        name = tg.full_name or (f"@{tg.username}" if tg.username else str(tg.id))
        await send_replies(update, await signup.start(tg.id, name, _arg(context)))

    return handler


def help_cmd(signup: Signup) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        user = _current(signup, update)
        text = copy.HELP + (copy.HELP_OWNER if user is not None and user.is_owner else "")
        await send_replies(update, [Reply(text)])

    return handler


def routed(signup: Signup, factory: Callable[[BotDeps], Handler]) -> Handler:
    """Run a per-user command against the sender's own tenant."""

    async def handler(update: Update, context: Any) -> None:
        user = _current(signup, update)
        if user is None:
            return
        tenant = signup.hub.tenant(user.telegram_id)
        if user.status != "active" or tenant is None:
            await send_replies(update, [Reply(copy.FINISH_SIGNUP_FIRST), *signup.prompt(user)])
            return
        await factory(tenant.deps)(update, context)

    return handler


def item_button(signup: Signup) -> Handler:
    async def handler(update: Update, context: Any) -> None:
        query = update.callback_query
        user = _current(signup, update)
        tenant = signup.hub.tenant(user.telegram_id) if user is not None else None
        if query is None:
            return
        if tenant is None:
            await query.answer(copy.ITEM_GONE)
            return
        await on_callback(tenant.deps)(update, context)

    return handler


def setup_button(signup: Signup) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        query = update.callback_query
        user = _current(signup, update)
        if query is None:
            return
        await query.answer()
        if user is None:
            return
        with contextlib.suppress(TelegramError):  # stop double taps on old option buttons
            await query.edit_message_reply_markup(reply_markup=None)
        prefix, _, rest = (query.data or "").partition(":")
        if prefix == "su":
            kind, _, value = rest.partition(":")
            replies = await signup.choice(user, kind, value)
        elif prefix == "set":
            replies = signup.begin_edit(user, rest)
        else:
            replies = await signup.disconnect(user, confirmed=rest == "yes")
        await send_replies(update, replies)

    return handler


def on_text(signup: Signup) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        user, message = _current(signup, update), update.effective_message
        if user is None or message is None or not message.text:
            return
        text = message.text
        if user.step in TOKEN_STEPS:
            # A token must not stay in the chat history, whatever else happens.
            with contextlib.suppress(TelegramError):
                await message.delete()
            if looks_like_token(text):
                await send_replies(update, [Reply(copy.TOKEN_CHECKING)])
        await send_replies(update, await signup.text(user, text))

    return handler


def _simple(signup: Signup, action: Callable[[User], list[Reply]]) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        user = _current(signup, update)
        if user is not None:
            await send_replies(update, action(user))

    return handler


def invite_cmd(signup: Signup) -> Handler:
    async def handler(update: Update, context: Any) -> None:
        user = _current(signup, update)
        if user is None:
            return
        username = getattr(getattr(context, "bot", None), "username", None)
        await send_replies(update, signup.invite(user, username))

    return handler


def remove_cmd(signup: Signup) -> Handler:
    async def handler(update: Update, context: Any) -> None:
        user = _current(signup, update)
        if user is not None:
            await send_replies(update, await signup.remove(user, _arg(context)))

    return handler


def register_handlers(app: Application[Any, Any, Any, Any, Any, Any], signup: Signup) -> None:
    app.add_handler(build_gate(signup), group=-1)
    app.add_handler(CommandHandler("start", start(signup)))
    app.add_handler(CommandHandler("help", help_cmd(signup)))
    for name, factory in (
        ("today", today_cmd),
        ("week", week_cmd),
        ("digest", digest_cmd),
        ("sync", sync_cmd),
        ("status", status_cmd),
        ("pause", pause_cmd),
    ):
        app.add_handler(CommandHandler(name, routed(signup, factory)))
    app.add_handler(CommandHandler("settings", _simple(signup, signup.settings)))
    app.add_handler(CommandHandler("cancel", _simple(signup, signup.cancel)))
    app.add_handler(
        CommandHandler("disconnect", _simple(signup, lambda _u: signup.disconnect_prompt()))
    )
    app.add_handler(CommandHandler("invite", invite_cmd(signup)))
    app.add_handler(CommandHandler("users", _simple(signup, signup.users)))
    app.add_handler(CommandHandler("remove", remove_cmd(signup)))
    app.add_handler(CallbackQueryHandler(item_button(signup), pattern=ITEM_CALLBACK))
    app.add_handler(CallbackQueryHandler(setup_button(signup), pattern=SETUP_CALLBACK))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text(signup)))
