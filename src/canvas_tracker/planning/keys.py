"""Deterministic send keys: one key per message the bot should send at most once."""

from __future__ import annotations

from datetime import UTC, date, datetime

from canvas_tracker.domain.models import Item


def _ts(instant: datetime | None) -> str:
    if instant is None:
        raise ValueError("a send key needs a timestamp")
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def digest_key(d: date) -> str:
    return f"digest:{d.isoformat()}"


def reminder_key(anchor: datetime, k: int) -> str:
    return f"rem:{_ts(anchor)}:{k}"


def new_urgent_key(item: Item) -> str:
    return f"new:{item.ref}:{_ts(item.due_at)}"


def snooze_end_key(item: Item) -> str:
    return f"snz:{item.ref}:{_ts(item.snoozed_until)}"


def overnight_key(d: date) -> str:
    return f"overnight:{d.isoformat()}"


def overdue_key(item: Item) -> str:
    return f"overdue:{item.ref}:{_ts(item.due_at)}"


def auth_alert_key(since: datetime) -> str:
    return f"auth:{_ts(since)}"


def announcement_key(item: Item) -> str:
    return f"ann:{item.ref}"


def event_soon_key(item: Item) -> str:
    return f"evt:{item.ref}:{_ts(item.due_at)}"


def email_digest_key(d: date) -> str:
    return f"email:digest:{d.isoformat()}"


def email_deadline_key(due_at: datetime) -> str:
    return f"email:due:{_ts(due_at)}"
