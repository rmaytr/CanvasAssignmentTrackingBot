import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import respx

from canvas_tracker.domain.models import ItemType
from canvas_tracker.sources.canvas_client import CanvasClient
from canvas_tracker.sources.planner import (
    PLANNER_PATH,
    fetch_planner,
    map_planner_item,
    planner_params,
    planner_window,
)
from tests.factories import NOW

BASE = "https://canvas.example.edu"
RAW: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[1] / "fixtures/canvas/planner_items.handmade.json").read_text()
)
BY_ID = {r["plannable_id"]: r for r in RAW}


def test_every_fixture_item_maps_without_raising() -> None:  # Review Focus 1
    mapped = [map_planner_item(r, BASE) for r in RAW]
    assert sum(m is not None for m in mapped) == 6
    assert map_planner_item(BY_ID[31], BASE) is None  # planner note without a date


def test_assignment_fields() -> None:
    item = map_planner_item(BY_ID[11], BASE)
    assert item is not None
    assert (item.type, item.title, item.course_id, item.course_name) == (
        ItemType.ASSIGNMENT,
        "Title 1",
        1,
        "Course 1",
    )
    assert item.due_at == datetime(2026, 10, 21, 3, 59, 59, tzinfo=UTC)
    assert (item.assignment_id, item.points_possible) == (11, 10.0)
    assert item.html_url == f"{BASE}/courses/1/assignments/11"
    assert item.marked_complete is None and item.submitted is False


def test_submissions_false_gives_default_flags() -> None:
    quiz = map_planner_item(BY_ID[21], BASE)
    assert quiz is not None and quiz.type is ItemType.QUIZ and quiz.assignment_id == 210
    assert not any([quiz.submitted, quiz.excused, quiz.graded, quiz.late, quiz.missing])


def test_peer_review_event_and_override() -> None:
    review = map_planner_item(BY_ID[41], BASE)
    event = map_planner_item(BY_ID[51], BASE)
    discussion = map_planner_item(BY_ID[61], BASE)
    assert review is not None and review.type is ItemType.PEER_REVIEW
    assert event is not None and event.type is ItemType.EVENT
    assert event.html_url == "https://canvas.example.edu/calendar?event_id=51"
    assert discussion is not None and discussion.marked_complete is True


def test_offset_dates_become_utc_and_flags_map() -> None:
    item = map_planner_item(BY_ID[71], BASE)
    assert item is not None
    assert item.due_at == datetime(2026, 10, 25, 3, 59, tzinfo=UTC)
    assert (item.submitted, item.graded, item.late) == (True, True, True)


def test_unknown_type_is_other() -> None:
    raw = {**BY_ID[11], "plannable_type": "something_new"}
    item = map_planner_item(raw, BASE)
    assert item is not None and item.type is ItemType.OTHER


def test_window_and_params() -> None:
    assert planner_params(NOW) == {
        "start_date": "2026-09-22T16:00:00Z",
        "end_date": "2026-11-10T16:00:00Z",
        "per_page": "100",
    }
    assert planner_window(NOW) == (
        datetime(2026, 9, 22, 16, 0, tzinfo=UTC),
        datetime(2026, 11, 10, 16, 0, tzinfo=UTC),
    )


@respx.mock
async def test_fetch_planner_returns_none_items_on_304() -> None:
    respx.get(f"{BASE}{PLANNER_PATH}").respond(304)
    client = CanvasClient(BASE, lambda: "t")
    result = await fetch_planner(client, NOW, 'W/"x"', BASE)
    assert result.items is None and result.etag == 'W/"x"'


@respx.mock
async def test_fetch_planner_maps_items_and_skips_undated() -> None:
    respx.get(f"{BASE}{PLANNER_PATH}").mock(
        return_value=httpx.Response(200, json=RAW, headers={"ETag": 'W/"y"'})
    )
    client = CanvasClient(BASE, lambda: "t")
    result = await fetch_planner(client, NOW, None, BASE)
    assert result.items is not None and len(result.items) == 6 and result.etag == 'W/"y"'
    assert result.window == planner_window(NOW)
