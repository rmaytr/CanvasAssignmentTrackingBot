"""The daily digest message (PRD §7.4)."""

from __future__ import annotations

from datetime import datetime, timedelta

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import STALE_AFTER, Item, ItemType, Settings, Snapshot
from canvas_tracker.domain.priority import Score, Tier, score
from canvas_tracker.domain.status import REMINDABLE_TYPES, is_overdue_accepting
from canvas_tracker.render import copy
from canvas_tracker.render.format import clock, format_due, split_blocks
from canvas_tracker.render.items import heading, plain_heading
from canvas_tracker.render.message import Button, RenderedMessage

MAX_DIGEST_BUTTONS = 96
BUTTONS_PER_ROW = 4


def _coarse(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} m"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} d"


def _pct(share: float) -> str:
    pct = share * 100
    return "<1" if pct < 1 else f"{pct:.0f}"


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def item_score(item: Item, snap: Snapshot, now: datetime) -> Score:
    course = snap.courses.get(item.course_id) if item.course_id is not None else None
    group = (
        snap.groups.get(item.assignment_group_id) if item.assignment_group_id is not None else None
    )
    return score(item, now, course, group)


def explain(item: Item, s: Score, now: datetime, settings: Settings) -> str:
    """One line that says why an item ranks where it does."""
    tz = settings.zone
    assert item.due_at is not None  # noqa: S101 - callers only pass dated items
    parts = [
        copy.EXPLAIN_DUE.format(
            when=format_due(item.due_at, now, tz), left=_coarse(item.due_at - now)
        )
    ]
    if s.grade_share is not None and s.grade_share > 0:
        parts.append(copy.EXPLAIN_SHARE.format(share=_pct(s.grade_share)))
    elif s.grade_share is None and (item.points_possible or 0) > 0:
        parts.append(copy.EXPLAIN_WEIGHT_UNKNOWN)
    label = copy.TYPE_LABELS.get(item.type.value)
    if label:
        parts.append(label)
    parts.append(copy.EXPLAIN_EFFORT.format(hours=_num(s.effort_hours)))
    if s.tier is Tier.HIGH:
        start = item.due_at - timedelta(hours=1.5 * s.effort_hours)
        start_local = start.astimezone(tz).replace(minute=0, second=0, microsecond=0)
        parts.append(copy.EXPLAIN_START_BY.format(when=format_due(start_local, now, tz)))
    return " · ".join(parts)


def _open(item: Item) -> bool:
    return (
        item.due_at is not None
        and item.type in REMINDABLE_TYPES
        and item.gone_at is None
        and not is_done(item)
    )


def _sort_key(entry: tuple[Item, Score], snap: Snapshot) -> tuple[datetime, int, str]:
    item, s = entry
    assert item.due_at is not None  # noqa: S101
    course = snap.courses.get(item.course_id) if item.course_id is not None else None
    return (item.due_at, -s.total, course.code if course else item.course_name)


def render_digest(snap: Snapshot, now: datetime, settings: Settings) -> list[RenderedMessage]:
    tz = settings.zone
    host = settings.canvas_host
    today = now.astimezone(tz).date()
    upcoming = [
        (i, item_score(i, snap, now))
        for i in snap.items
        if _open(i) and i.due_at is not None and now < i.due_at <= now + settings.digest_lookahead
    ]
    upcoming.sort(key=lambda e: _sort_key(e, snap))
    urgent = [e for e in upcoming if e[1].tier is Tier.URGENT]
    high = [e for e in upcoming if e[1].tier is Tier.HIGH]
    rest = [e for e in upcoming if e[1].tier in (Tier.MEDIUM, Tier.LOW)]
    overdue = sorted(
        (i for i in snap.items if i.type in REMINDABLE_TYPES and is_overdue_accepting(i, now)),
        key=lambda i: (i.due_at, i.ref),
    )
    events = sorted(
        (
            i
            for i in snap.items
            if i.type is ItemType.EVENT
            and i.gone_at is None
            and i.due_at is not None
            and i.due_at.astimezone(tz).date() == today
        ),
        key=lambda i: (i.due_at, i.ref),
    )
    yesterday = today - timedelta(days=1)
    done_yesterday = sum(
        1
        for i in snap.items
        if any(
            t is not None and t.astimezone(tz).date() == yesterday
            for t in (i.done_seen_at, i.bot_done_at)
        )
    )

    last = snap.last_successful_sync_at
    fresh = last is not None and now - last <= STALE_AFTER
    synced = clock(last, tz) if last is not None else "never"
    week = sum(1 for i, _s in rest if i.due_at is not None and i.due_at <= now + timedelta(days=7))
    blocks = [copy.DIGEST_HEADER.format(date=f"{today:%a}, {today:%b} {today.day}")]
    blocks.append(
        copy.DIGEST_COUNTS.format(urgent=len(urgent), high=len(high), later=week, synced=synced)
    )
    if not fresh:
        blocks.append(
            copy.STALE_BANNER.format(since=synced) if last is not None else copy.STALE_NEVER
        )

    numbered: list[Item] = []
    for title, entries in ((copy.TIER_URGENT, urgent), (copy.TIER_HIGH, high)):
        if not entries:
            continue
        blocks += ["", title]
        for item, s in entries:
            numbered.append(item)
            why = explain(item, s, now, settings)
            blocks.append(f"{len(numbered)}. {heading(item, snap, host)}\n   {why}")
    if rest:
        nxt = ", ".join(
            f"{plain_heading(i, snap)} ({format_due(i.due_at, now, tz)})"
            for i, _s in rest[:3]
            if i.due_at is not None
        )
        blocks += ["", copy.TIER_REST.format(count=len(rest), next=nxt)]
    if overdue:
        blocks += ["", copy.SECTION_OVERDUE]
        for item in overdue:
            assert item.due_at is not None  # noqa: S101
            accepted = (
                copy.OVERDUE_ACCEPTED.format(until=format_due(item.lock_at, now, tz))
                if item.lock_at is not None
                else ""
            )
            blocks.append(
                copy.OVERDUE_LINE.format(
                    heading=plain_heading(item, snap),
                    when=format_due(item.due_at, now, tz),
                    accepted=accepted,
                )
            )
    if events:
        blocks += ["", copy.SECTION_EVENTS]
        for item in events:
            assert item.due_at is not None  # noqa: S101
            blocks.append(f"• {clock(item.due_at, tz)} · {plain_heading(item, snap)}")
    if done_yesterday:
        blocks += ["", copy.DONE_YESTERDAY.format(count=done_yesterday)]
    if fresh and not (urgent or high or rest or overdue or events):
        blocks.append(copy.NOTHING_DUE.format(days=settings.digest_lookahead.days, synced=synced))

    buttons = [
        Button(f"✅ {n}", callback_data=f"d:{item.db_id}")
        for n, item in enumerate(numbered, start=1)
        if item.db_id is not None
    ][:MAX_DIGEST_BUTTONS]
    keyboard = tuple(
        tuple(buttons[i : i + BUTTONS_PER_ROW]) for i in range(0, len(buttons), BUTTONS_PER_ROW)
    )
    parts = split_blocks(blocks)
    return [
        RenderedMessage(text, keyboard if n == len(parts) - 1 else ())
        for n, text in enumerate(parts)
    ]
