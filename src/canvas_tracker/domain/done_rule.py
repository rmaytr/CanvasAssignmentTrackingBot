"""When an item counts as done (PRD §7.2), mirroring Canvas's own planner rule."""

from __future__ import annotations

from enum import StrEnum

from canvas_tracker.domain.models import Item


class DoneSource(StrEnum):
    CANVAS_MARKED = "canvas_marked"
    SUBMITTED = "submitted"
    EXCUSED = "excused"
    GRADED_OFFLINE = "graded_offline"
    BOT = "bot"


OFFLINE_SUBMISSION_TYPES = frozenset({"on_paper", "none", "external_tool"})


def done_source(item: Item) -> DoneSource | None:
    """Return why ``item`` is done, or ``None`` if it still needs doing."""
    if item.redo_request:
        return None
    if item.marked_complete is True:
        return DoneSource.CANVAS_MARKED
    unmarked = item.marked_complete is False
    if item.submitted and not unmarked:
        return DoneSource.SUBMITTED
    if item.excused:
        return DoneSource.EXCUSED
    if (
        item.graded
        and item.submission_types
        and all(t in OFFLINE_SUBMISSION_TYPES for t in item.submission_types)
        and not unmarked
    ):
        return DoneSource.GRADED_OFFLINE
    if item.bot_done_at is not None and item.bot_done_due_at == item.due_at:
        return DoneSource.BOT
    return None


def is_done(item: Item) -> bool:
    return done_source(item) is not None
