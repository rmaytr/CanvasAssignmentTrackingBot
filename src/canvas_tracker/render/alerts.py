"""Rendering for every send kind: reminders, alerts and (via digest.py) the digest."""

from __future__ import annotations

from datetime import datetime, timedelta

from canvas_tracker.domain.models import Item, Send, SendKind, Settings, Snapshot
from canvas_tracker.render import copy
from canvas_tracker.render.digest import render_digest
from canvas_tracker.render.format import TELEGRAM_LIMIT, format_due, format_left
from canvas_tracker.render.items import heading, link_for, title_html
from canvas_tracker.render.message import Button, RenderedMessage

MAX_ITEMS_PER_MESSAGE = 30  # 3 buttons each stays under Telegram's 100-button keyboard limit
_HEADERS = {
    SendKind.NEW_URGENT: copy.NEW_URGENT_HEADER,
    SendKind.SNOOZE_END: copy.SNOOZE_END_HEADER,
    SendKind.OVERNIGHT: copy.OVERNIGHT_HEADER,
}


def _slot_number(key: str) -> int:
    tail = key.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _item_block(n: int, item: Item, snap: Snapshot, now: datetime, settings: Settings) -> str:
    assert item.due_at is not None  # noqa: S101 - only dated items are reminded
    left = item.due_at - now
    line = copy.REMINDER_LINE.format(
        when=format_due(item.due_at, now, settings.zone), left=format_left(left)
    )
    if left < timedelta(hours=2):
        line += copy.UNDER_TWO_HOURS
    return f"{n}. {heading(item, snap, settings.canvas_host)}\n   {line}"


def _item_row(n: int, item: Item, settings: Settings) -> tuple[Button, ...]:
    if item.db_id is None:
        return ()
    row = [
        Button(f"{copy.BTN_DONE} {n}", callback_data=f"d:{item.db_id}"),
        Button(f"{copy.BTN_SNOOZE} {n}", callback_data=f"s:{item.db_id}"),
    ]
    url = link_for(item, settings.canvas_host)
    if url is not None:
        row.append(Button(f"🔗 {n}", url=url))
    return tuple(row)


def _list_messages(
    header: str, items: list[Item], snap: Snapshot, now: datetime, settings: Settings
) -> list[RenderedMessage]:
    messages: list[RenderedMessage] = []
    text = f"{header}\n"
    rows: list[tuple[Button, ...]] = []
    count = 0
    for n, item in enumerate(items, start=1):
        block = _item_block(n, item, snap, now, settings)
        if count and (
            count >= MAX_ITEMS_PER_MESSAGE or len(text) + 1 + len(block) > TELEGRAM_LIMIT
        ):
            messages.append(RenderedMessage(text, tuple(r for r in rows if r)))
            text, rows, count = block, [], 0
        else:
            text = f"{text}\n{block}"
        rows.append(_item_row(n, item, settings))
        count += 1
    messages.append(RenderedMessage(text, tuple(r for r in rows if r)))
    return messages


def _overdue(item: Item, now: datetime, settings: Settings) -> RenderedMessage:
    assert item.due_at is not None  # noqa: S101
    tz = settings.zone
    text = copy.OVERDUE_NOTICE.format(
        title=title_html(item, settings.canvas_host), when=format_due(item.due_at, now, tz)
    )
    if item.lock_at is not None and item.lock_at > now:
        text += "\n" + copy.OVERDUE_STILL_ACCEPTED.format(until=format_due(item.lock_at, now, tz))
    row: list[Button] = []
    if item.db_id is not None:
        row += [
            Button(copy.BTN_DONE, callback_data=f"d:{item.db_id}"),
            Button(copy.BTN_STOP, callback_data=f"x:{item.db_id}"),
        ]
    url = link_for(item, settings.canvas_host)
    if url is not None:
        row.append(Button(copy.BTN_OPEN, url=url))
    return RenderedMessage(text, (tuple(row),) if row else ())


def render_send(
    send: Send, snap: Snapshot, now: datetime, settings: Settings
) -> list[RenderedMessage]:
    if send.kind is SendKind.DIGEST:
        return render_digest(snap, now, settings)
    if send.kind is SendKind.AUTH_ALERT:
        return [RenderedMessage(copy.AUTH_ALERT)]
    by_ref = {item.ref: item for item in snap.items}
    items = [by_ref[ref] for ref in send.item_refs if ref in by_ref and by_ref[ref].due_at]
    if not items:
        return []
    if send.kind is SendKind.OVERDUE:
        return [_overdue(items[0], now, settings)]
    if send.kind is SendKind.REMINDER:
        template = copy.REMINDER_HEADERS[_slot_number(send.key) % len(copy.REMINDER_HEADERS)]
        header = template.format(count=len(items))
    else:
        header = _HEADERS[send.kind]
    return _list_messages(header, items, snap, now, settings)
