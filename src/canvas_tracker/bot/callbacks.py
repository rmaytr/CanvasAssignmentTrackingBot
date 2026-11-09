"""Done / Snooze / Undo / Stop buttons (PRD §7.6). Every press is answered exactly once."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError

from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.domain.models import SNOOZE_LENGTH, SNOOZE_MIN_LEFT, UNDO_WINDOW
from canvas_tracker.render import copy
from canvas_tracker.render.format import clock
from canvas_tracker.render.message import ITEM_CALLBACK_PATTERN, item_callback

Action = Literal["d", "s", "u", "x"]
_CALLBACK_RE = re.compile(ITEM_CALLBACK_PATTERN)


@dataclass(frozen=True, slots=True)
class ItemPress:
    action: Action
    db_id: int
    salt: str | None  # None for buttons sent before salts existed


def parse_callback(data: str) -> ItemPress | None:
    match = _CALLBACK_RE.match(data)
    if match is None:
        return None
    action: Action = match.group(1)  # type: ignore[assignment]
    return ItemPress(action, int(match.group(2)), match.group(3))


def snooze_until(now: datetime, due_at: datetime) -> datetime | None:
    """Snooze for 2 h, but never past 30 minutes before the deadline."""
    if due_at - now <= SNOOZE_MIN_LEFT:
        return None
    return min(now + SNOOZE_LENGTH, due_at - SNOOZE_MIN_LEFT)


def _number(label: str) -> str:
    tail = label.rsplit(" ", 1)[-1]
    return tail if tail.isdigit() else ""


def _undo_keyboard(
    markup: InlineKeyboardMarkup | None, db_id: int, salt: str
) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    done, snooze = item_callback("d", db_id, salt), item_callback("s", db_id, salt)
    rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        datas = [b.callback_data for b in row]
        if done not in datas:
            rows.append(list(row))
            continue
        button = next(b for b in row if b.callback_data == done)
        undo = InlineKeyboardButton(
            copy.UNDO_BUTTON.format(n=_number(button.text)),
            callback_data=item_callback("u", db_id, salt),
        )
        mine = all(b.callback_data in (done, snooze) or b.url is not None for b in row)
        if mine:  # a reminder row for just this item: replace the whole row
            rows.append([undo])
        else:  # a digest row shared with other items: replace just this button
            rows.append([undo if b.callback_data == done else b for b in row])
    return InlineKeyboardMarkup(rows)


def on_callback(deps: BotDeps) -> Callable[[Update, Any], Coroutine[Any, Any, None]]:
    async def handler(update: Update, _context: Any) -> None:
        query = update.callback_query
        if query is None:
            return
        parsed = parse_callback(query.data or "")
        if parsed is not None and not deps.store.accepts_button(parsed.salt):
            # From an earlier sign-up's database: its item ids mean something else here.
            await query.answer(copy.BUTTON_STALE)
            return
        item = deps.store.get_item(parsed.db_id) if parsed is not None else None
        if parsed is None or item is None or item.gone_at is not None:
            await query.answer(copy.ITEM_GONE)
            return
        action, db_id, salt = parsed.action, parsed.db_id, parsed.salt or ""
        now = deps.clock()
        if action == "d":
            deps.store.set_bot_done(db_id, now)
            await query.answer(copy.DONE)
            message = query.message
            markup = getattr(message, "reply_markup", None)
            new_markup = _undo_keyboard(markup, db_id, salt)
            if new_markup is not None:
                # The message may be too old to edit; the item is marked done either way.
                with contextlib.suppress(TelegramError):
                    await query.edit_message_reply_markup(reply_markup=new_markup)
        elif action == "s":
            until = snooze_until(now, item.due_at) if item.due_at is not None else None
            if until is None:
                await query.answer(copy.SNOOZE_TOO_LATE)
            else:
                deps.store.snooze(db_id, until)
                await query.answer(copy.SNOOZED.format(until=clock(until, deps.settings.zone)))
        elif action == "u":
            recent = item.bot_done_at is not None and now - item.bot_done_at <= UNDO_WINDOW
            if recent or item.stop_reminders:
                deps.store.clear_user_flags(db_id)
                await query.answer(copy.UNDONE)
            else:
                await query.answer(copy.UNDO_EXPIRED)
        else:
            deps.store.set_stop(db_id)
            await query.answer(copy.STOPPED)

    return handler
