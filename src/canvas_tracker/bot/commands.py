"""Chat commands: /today /week /digest /sync /status /pause (plus /start, /help)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any

from telegram import LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from canvas_tracker import __version__
from canvas_tracker.bot.callbacks import on_callback
from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.bot.gate import build_gate, help_cmd, start
from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.notify.telegram import to_markup
from canvas_tracker.planning.keys import digest_key
from canvas_tracker.planning.timeutil import at_local, local_date
from canvas_tracker.render import copy
from canvas_tracker.render.digest import render_digest
from canvas_tracker.render.format import format_due
from canvas_tracker.render.message import RenderedMessage
from canvas_tracker.render.views import (
    StatusInfo,
    parse_pause,
    render_status,
    render_today,
    render_week,
)
from canvas_tracker.runtime.sync import SyncOutcome
from canvas_tracker.store.repo import PAUSE_UNTIL

Handler = Callable[[Update, Any], Coroutine[Any, Any, None]]


async def _reply(update: Update, messages: list[RenderedMessage]) -> None:
    message = update.effective_message
    if message is None:
        return
    for msg in messages:
        await message.reply_text(
            msg.text,
            parse_mode=ParseMode.HTML,
            reply_markup=to_markup(msg.keyboard),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


async def _reply_text(update: Update, text: str) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(text)


def today_cmd(deps: BotDeps) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        now = deps.clock()
        await _reply(
            update, render_today(deps.store.snapshot(deps.hidden_courses), now, deps.settings)
        )

    return handler


def week_cmd(deps: BotDeps) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        now = deps.clock()
        await _reply(
            update, render_week(deps.store.snapshot(deps.hidden_courses), now, deps.settings)
        )

    return handler


def digest_cmd(deps: BotDeps) -> Handler:
    """Send the digest now, without claiming the day's send key (the scheduled one still comes)."""

    async def handler(update: Update, _context: Any) -> None:
        now = deps.clock()
        await _reply(
            update, render_digest(deps.store.snapshot(deps.hidden_courses), now, deps.settings)
        )

    return handler


def sync_cmd(deps: BotDeps) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        outcome = await deps.sync.sync(deps.clock())
        if outcome is SyncOutcome.OK:
            snap = deps.store.snapshot(deps.hidden_courses)
            count = sum(1 for i in snap.items if i.gone_at is None and not is_done(i))
            await _reply_text(update, copy.SYNC_OK.format(count=count))
        elif outcome is SyncOutcome.NOT_MODIFIED:
            await _reply_text(update, copy.SYNC_NOT_MODIFIED)
        else:
            await _reply_text(update, copy.SYNC_FAILED[outcome])

    return handler


def _next_digest(now: datetime, deps: BotDeps, sent: frozenset[str]) -> datetime:
    tz = deps.settings.zone
    today = local_date(now, tz)
    at = at_local(today, deps.settings.digest_time, tz)
    if at > now or (
        now < at_local(today, deps.settings.digest_grace_until, tz)
        and digest_key(today) not in sent
    ):
        return max(at, now)
    return at_local(today + timedelta(days=1), deps.settings.digest_time, tz)


def status_cmd(deps: BotDeps) -> Handler:
    async def handler(update: Update, _context: Any) -> None:
        now = deps.clock()
        snap = deps.store.snapshot(deps.hidden_courses)
        next_slot = None
        if snap.cycle is not None:
            interval = deps.settings.reminder_interval
            k = (now - snap.cycle.anchor) // interval
            next_slot = snap.cycle.anchor + (k + 1) * interval
        info = StatusInfo(
            last_successful_sync_at=snap.last_successful_sync_at,
            auth_failed_since=snap.auth_failed_since,
            next_digest_at=_next_digest(now, deps, snap.sent_keys),
            next_slot_at=next_slot,
            pause_until=snap.pause_until,
            version=__version__,
        )
        await _reply_text(update, render_status(info, now, deps.settings).text)

    return handler


def pause_cmd(deps: BotDeps) -> Handler:
    async def handler(update: Update, context: Any) -> None:
        now = deps.clock()
        arg = " ".join(context.args or [])
        if not arg:
            await _reply_text(update, copy.PAUSE_USAGE)
            return
        try:
            until = parse_pause(arg, now, deps.settings.zone)
        except ValueError:
            await _reply_text(update, copy.PAUSE_USAGE)
            return
        deps.store.set_time(PAUSE_UNTIL, until)
        if until is None:
            await _reply_text(update, copy.PAUSE_OFF)
        else:
            await _reply_text(
                update, copy.PAUSED_UNTIL.format(until=format_due(until, now, deps.settings.zone))
            )

    return handler


def register_handlers(app: Application[Any, Any, Any, Any, Any, Any], deps: BotDeps) -> None:
    """The owner gate first (group -1), then every command and the button handler."""
    app.add_handler(build_gate(deps), group=-1)
    for name, factory in (
        ("start", start),
        ("help", help_cmd),
        ("today", today_cmd),
        ("week", week_cmd),
        ("digest", digest_cmd),
        ("sync", sync_cmd),
        ("status", status_cmd),
        ("pause", pause_cmd),
    ):
        app.add_handler(CommandHandler(name, factory(deps)))
    app.add_handler(CallbackQueryHandler(on_callback(deps)))
