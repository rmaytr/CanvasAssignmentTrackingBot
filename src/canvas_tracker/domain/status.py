"""Item status predicates: urgent, active, overdue (PRD §7.5)."""

from __future__ import annotations

from datetime import datetime

from canvas_tracker.domain.done_rule import is_done
from canvas_tracker.domain.models import OVERDUE_SECTION_MAX, Item, ItemType, Settings

REMINDABLE_TYPES = frozenset(t for t in ItemType if t is not ItemType.EVENT)


def hours_left(item: Item, now: datetime) -> float | None:
    if item.due_at is None:
        return None
    return (item.due_at - now).total_seconds() / 3600


def _still_accepting(item: Item, now: datetime) -> bool:
    return item.lock_at is None or item.lock_at > now


def is_overdue_accepting(item: Item, now: datetime) -> bool:
    """Past due, at most 7 days ago, not done, and Canvas still accepts it."""
    if item.due_at is None or item.gone_at is not None or is_done(item):
        return False
    return item.due_at <= now < item.due_at + OVERDUE_SECTION_MAX and _still_accepting(item, now)


def is_urgent(item: Item, now: datetime, settings: Settings) -> bool:
    """Due within the reminder window (or overdue, when overdue reminders are on)."""
    if (
        item.due_at is None
        or item.type not in REMINDABLE_TYPES
        or item.gone_at is not None
        or is_done(item)
    ):
        return False
    left = item.due_at - now
    if left.total_seconds() > 0:
        return left <= settings.reminder_window
    return (
        settings.overdue_reminders
        and not item.stop_reminders
        and now < item.due_at + settings.overdue_reminder_max
        and _still_accepting(item, now)
    )


def is_active(item: Item, now: datetime, settings: Settings, pause_until: datetime | None) -> bool:
    """Urgent and not snoozed, stopped or paused: it belongs in the next reminder."""
    if not is_urgent(item, now, settings) or item.stop_reminders:
        return False
    if item.snoozed_until is not None and item.snoozed_until > now:
        return False
    return not (pause_until is not None and pause_until > now)
