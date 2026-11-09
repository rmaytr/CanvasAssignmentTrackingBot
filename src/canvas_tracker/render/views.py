"""On-demand views: /today, /week, /status, plus /pause argument parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import Item, Settings, Snapshot
from canvas_tracker.domain.priority import Score, Tier
from canvas_tracker.domain.status import REMINDABLE_TYPES, is_overdue_accepting
from canvas_tracker.planning.timeutil import at_local, local_date
from canvas_tracker.render import copy
from canvas_tracker.render.digest import BUTTONS_PER_ROW, MAX_DIGEST_BUTTONS, explain, item_score
from canvas_tracker.render.format import format_due, format_span, mask_email, split_blocks
from canvas_tracker.render.items import default_stale, heading, stale_banner
from canvas_tracker.render.message import Button, RenderedMessage, item_callback

PAUSE_MAX = timedelta(days=7)
_DURATION_RE = re.compile(r"^(\d{1,4})\s*(m|min|h)$")
_TIER_TITLES = {
    Tier.URGENT: copy.TIER_URGENT,
    Tier.HIGH: copy.TIER_HIGH,
    Tier.MEDIUM: copy.TIER_MEDIUM,
    Tier.LOW: copy.TIER_LOW,
}


def parse_pause(arg: str, now: datetime, tz: ZoneInfo) -> datetime | None:
    """``30m`` / ``3h`` / ``until 18:00`` → pause end (UTC); ``off`` → None."""
    text = arg.strip().lower()
    if text == "off":
        return None
    until: datetime | None = None
    match = _DURATION_RE.match(text)
    if match:
        amount = int(match.group(1))
        until = now + (
            timedelta(hours=amount) if match.group(2) == "h" else timedelta(minutes=amount)
        )
    elif text.startswith("until "):
        try:
            wall = time.fromisoformat(text.removeprefix("until ").strip())
        except ValueError:
            raise ValueError(copy.PAUSE_USAGE) from None
        today = local_date(now, tz)
        until = at_local(today, wall, tz)
        if until <= now:
            until = at_local(today + timedelta(days=1), wall, tz)
    if until is None or until <= now or until > now + PAUSE_MAX:
        raise ValueError(copy.PAUSE_USAGE)
    return until


def _open(item: Item) -> bool:
    return (
        item.due_at is not None
        and item.type in REMINDABLE_TYPES
        and item.gone_at is None
        and not is_done(item)
    )


def _list_view(
    title: str,
    empty: str,
    groups: list[tuple[str | None, list[tuple[Item, Score]]]],
    snap: Snapshot,
    now: datetime,
    settings: Settings,
) -> list[RenderedMessage]:
    stale = default_stale(snap, now)
    blocks = [title, stale_banner(snap, settings)] if stale else [title]
    numbered: list[Item] = []
    for heading_text, entries in groups:
        if not entries:
            continue
        blocks.append("")
        if heading_text:
            blocks.append(heading_text)
        for item, s in entries:
            numbered.append(item)
            why = explain(item, s, now, settings)
            blocks.append(f"{len(numbered)}. {heading(item, snap, settings.canvas_host)}\n   {why}")
    if not numbered and not stale:  # never claim "nothing due" from stale data
        blocks += ["", empty]
    buttons = [
        Button(f"✅ {n}", callback_data=item_callback("d", item.db_id, snap.button_salt))
        for n, item in enumerate(numbered, start=1)
        if item.db_id is not None
    ][:MAX_DIGEST_BUTTONS]
    keyboard = tuple(
        tuple(buttons[i : i + BUTTONS_PER_ROW]) for i in range(0, len(buttons), BUTTONS_PER_ROW)
    )
    parts = split_blocks(blocks)
    return [
        RenderedMessage(t, keyboard if n == len(parts) - 1 else ()) for n, t in enumerate(parts)
    ]


def _sorted(entries: list[tuple[Item, Score]]) -> list[tuple[Item, Score]]:
    return sorted(entries, key=lambda e: (e[0].due_at, -e[1].total, e[0].ref))


def render_today(snap: Snapshot, now: datetime, settings: Settings) -> list[RenderedMessage]:
    tz = settings.zone
    today = local_date(now, tz)
    chosen: list[tuple[Item, Score]] = []
    for item in snap.items:
        if not (_open(item) or (item.type in REMINDABLE_TYPES and is_overdue_accepting(item, now))):
            continue
        s = item_score(item, snap, now)
        assert item.due_at is not None  # noqa: S101 - _open/overdue imply a date
        if s.tier is Tier.URGENT or local_date(item.due_at, tz) == today:
            chosen.append((item, s))
    title = copy.TODAY_HEADER.format(date=f"{today:%a} {today:%b} {today.day}")
    return _list_view(title, copy.NOTHING_TODAY, [(None, _sorted(chosen))], snap, now, settings)


def render_week(snap: Snapshot, now: datetime, settings: Settings) -> list[RenderedMessage]:
    horizon = now + timedelta(days=7)
    by_tier: dict[Tier, list[tuple[Item, Score]]] = {tier: [] for tier in Tier}
    for item in snap.items:
        if _open(item) and item.due_at is not None and now < item.due_at <= horizon:
            s = item_score(item, snap, now)
            by_tier[s.tier].append((item, s))
    groups: list[tuple[str | None, list[tuple[Item, Score]]]] = [
        (_TIER_TITLES[tier], _sorted(by_tier[tier])) for tier in Tier
    ]
    return _list_view(copy.WEEK_HEADER, copy.NOTHING_WEEK, groups, snap, now, settings)


def rhythm_sentence(s: Settings) -> str:
    """One sentence on how often reminders come, for the welcome and all-set messages."""
    if s.reminder_interval is None:
        return copy.RHYTHM_OFF
    return (copy.RHYTHM_ON_FEED if s.calendar_feed else copy.RHYTHM_ON).format(
        window=format_span(s.reminder_window), interval=format_span(s.reminder_interval)
    )


def rhythm_short(s: Settings) -> str:
    """The rhythm in a few words, as /settings and /status show it."""
    if s.reminder_interval is None:
        return copy.RHYTHM_SHORT_OFF
    return copy.RHYTHM_SHORT_ON.format(
        interval=format_span(s.reminder_interval), window=format_span(s.reminder_window)
    )


def email_label(address: str | None, *, available: bool, masked: bool) -> str:
    """The email line of /settings (full address) and /status (masked address)."""
    if not available:
        return copy.EMAIL_UNAVAILABLE_LABEL
    if address is None:
        return copy.EMAIL_OFF_LABEL
    return mask_email(address) if masked else address


@dataclass(frozen=True, slots=True)
class StatusInfo:
    last_successful_sync_at: datetime | None
    auth_failed_since: datetime | None
    next_digest_at: datetime
    next_slot_at: datetime | None
    pause_until: datetime | None
    version: str
    email_available: bool = False
    email_address: str | None = None  # masked before it is shown
    next_event_at: datetime | None = None  # when the next 📅 heads-up goes out
    last_announcement_at: datetime | None = None


def render_status(info: StatusInfo, now: datetime, settings: Settings) -> RenderedMessage:
    tz = settings.zone

    def when(t: datetime) -> str:
        return format_due(t, now, tz)

    off = settings.reminder_interval is None
    if info.next_slot_at:
        slot = when(info.next_slot_at)
    else:
        slot = copy.STATUS_SLOT_OFF if off else copy.STATUS_NO_SLOT
    sync = when(info.last_successful_sync_at) if info.last_successful_sync_at else None
    token = (
        copy.STATUS_AUTH_FAILED.format(since=when(info.auth_failed_since))
        if info.auth_failed_since
        else copy.STATUS_AUTH_OK
    )
    lines = [
        copy.STATUS_SYNC.format(sync=sync or copy.STATUS_NEVER),
        (copy.STATUS_FEED if settings.calendar_feed else copy.STATUS_TOKEN).format(token=token),
        copy.STATUS_DIGEST.format(digest=when(info.next_digest_at)),
        copy.STATUS_SLOT.format(slot=slot),
        copy.STATUS_REMINDERS_OFF
        if off
        else copy.STATUS_REMINDERS_ON.format(rhythm=rhythm_short(settings)),
    ]
    if info.pause_until is not None and info.pause_until > now:
        lines.append(copy.STATUS_PAUSED.format(until=when(info.pause_until)))
    if settings.calendar_feed:
        lines.append(copy.STATUS_FEED_NOTE)
    email = email_label(info.email_address, available=info.email_available, masked=True)
    lines.append(copy.STATUS_EMAIL.format(email=email))
    if info.next_event_at is not None:
        lines.append(copy.STATUS_NEXT_EVENT.format(when=when(info.next_event_at)))
    if info.last_announcement_at is not None:
        lines.append(copy.STATUS_LAST_ANNOUNCEMENT.format(when=when(info.last_announcement_at)))
    lines.append(copy.STATUS_VERSION.format(version=info.version))
    return RenderedMessage("\n".join(lines))
