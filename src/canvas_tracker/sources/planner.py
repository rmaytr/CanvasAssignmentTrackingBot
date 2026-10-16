"""Map Canvas Planner items to domain Items (PRD §7.1-7.2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_tracker.domain.models import Item, ItemType
from canvas_tracker.sources.canvas_client import CanvasClient

PLANNER_PATH = "/api/v1/planner/items"
WINDOW_BACK = timedelta(days=28)
WINDOW_AHEAD = timedelta(days=21)
_TYPES = {
    "assignment": ItemType.ASSIGNMENT,
    "quiz": ItemType.QUIZ,
    "discussion_topic": ItemType.DISCUSSION,
    "sub_assignment": ItemType.SUB_ASSIGNMENT,
    "wiki_page": ItemType.PAGE,
    "planner_note": ItemType.NOTE,
    "calendar_event": ItemType.EVENT,
    "assessment_request": ItemType.PEER_REVIEW,
    "peer_review_sub_assignment": ItemType.PEER_REVIEW,
}


def _z(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: object) -> datetime | None:
    """ISO 8601 with ``Z`` or an offset, converted to UTC; None for missing or bad values."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def planner_window(now: datetime) -> tuple[datetime, datetime]:
    return now - WINDOW_BACK, now + WINDOW_AHEAD


def planner_params(now: datetime) -> dict[str, str]:
    start, end = planner_window(now)
    return {"start_date": _z(start), "end_date": _z(end), "per_page": "100"}


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def map_planner_item(raw: Mapping[str, Any], base_url: str) -> Item | None:
    """One planner item, or None when it has no date (it can't be reminded or ranked)."""
    due_at = parse_time(raw.get("plannable_date"))
    plannable_id = _int(raw.get("plannable_id"))
    plannable_type = raw.get("plannable_type")
    if due_at is None or plannable_id is None or not isinstance(plannable_type, str):
        return None
    plannable = _mapping(raw.get("plannable"))
    submissions = _mapping(raw.get("submissions"))  # may be ``false`` for non-submittables
    override = raw.get("planner_override")
    marked = override.get("marked_complete") if isinstance(override, Mapping) else None
    assignment_id = _int(plannable.get("assignment_id"))
    if assignment_id is None and plannable_type == "assignment":
        assignment_id = plannable_id
    html_url = raw.get("html_url") if isinstance(raw.get("html_url"), str) else None
    if html_url is not None and html_url.startswith("/"):
        html_url = base_url.rstrip("/") + html_url
    title = plannable.get("title") or plannable.get("name") or ""
    context_name = raw.get("context_name")

    def flag(name: str) -> bool:
        return submissions.get(name) is True

    return Item(
        plannable_type=plannable_type,
        plannable_id=plannable_id,
        title=str(title),
        type=_TYPES.get(plannable_type, ItemType.OTHER),
        course_id=_int(raw.get("course_id")),
        course_name=context_name if isinstance(context_name, str) else "",
        assignment_id=assignment_id,
        due_at=due_at,
        html_url=html_url,
        points_possible=_float(plannable.get("points_possible")),
        submitted=flag("submitted"),
        excused=flag("excused"),
        graded=flag("graded"),
        late=flag("late"),
        missing=flag("missing"),
        redo_request=flag("redo_request"),
        marked_complete=marked if isinstance(marked, bool) else None,
    )


@dataclass(frozen=True, slots=True)
class PlannerFetch:
    items: tuple[Item, ...] | None  # None: unchanged since the stored ETag (HTTP 304)
    etag: str | None
    window: tuple[datetime, datetime]


async def fetch_planner(
    client: CanvasClient, now: datetime, etag: str | None, base_url: str
) -> PlannerFetch:
    window = planner_window(now)
    result = await client.get_all_if_changed(PLANNER_PATH, planner_params(now), etag)
    if result.not_modified:
        return PlannerFetch(items=None, etag=etag, window=window)
    items = tuple(
        item
        for item in (
            map_planner_item(raw, base_url) for raw in result.data if isinstance(raw, Mapping)
        )
        if item is not None
    )
    return PlannerFetch(items=items, etag=result.etag, window=window)
