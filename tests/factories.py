"""Shared test factories. Times are UTC; NOW is Tue 2026-10-20 12:00 in New York."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_tracker.domain.models import Item, ItemType, Settings, Snapshot

NOW = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)
_ids = itertools.count(1)


def make_item(
    *, due_in: timedelta | None = timedelta(hours=10), now: datetime = NOW, **overrides: Any
) -> Item:
    fields: dict[str, Any] = {
        "plannable_type": "assignment",
        "plannable_id": next(_ids),
        "title": "Homework",
        "type": ItemType.ASSIGNMENT,
        "course_id": 1,
        "points_possible": 10.0,
        "submission_types": ("online_upload",),
        "due_at": None if due_in is None else now + due_in,
    }
    fields.update(overrides)
    return Item(**fields)


def make_settings(**overrides: Any) -> Settings:
    fields: dict[str, Any] = {"tz": "America/New_York"}
    fields.update(overrides)
    return Settings(**fields)


def make_snapshot(items: tuple[Item, ...] | list[Item] = (), **overrides: Any) -> Snapshot:
    fields: dict[str, Any] = {
        "items": tuple(items),
        "courses": {},
        "groups": {},
        "sent_keys": frozenset(),
        "last_reminded_at": {},
        "cycle": None,
        "pause_until": None,
        "last_successful_sync_at": NOW,
        "auth_failed_since": None,
    }
    fields.update(overrides)
    return Snapshot(**fields)
